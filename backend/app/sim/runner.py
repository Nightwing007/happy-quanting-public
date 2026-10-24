"""Play a past stretch of days through the real engine.

A session owns a `kind="sim"` account and a cursor. Moving the cursor to the end of the next
bar and then running `run_tick` (the same function the live loop runs) is all a replayed minute
is, so a target, a stop or the 15:20 square-off fire here for the same reasons they fire live.
"""

import threading
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.market_data import get_provider
from app.market_data.base import TRADABLE_TYPES, Bar, Instrument, MarketDataProvider
from app.market_data.history import HistoryRangeError, get_history
from app.market_data.replay import ReplayProvider, SessionBounds
from app.models import Account, AccountKind, Order, SimSession, SimStatus, Trade
from app.trading import hours
from app.trading.context import TradingContext
from app.trading.engine import ZERO, get_account, reset_account
from app.trading.markets import Market, market_for
from app.trading.tick import run_tick

MIN_SPEED, MAX_SPEED = 1, 200
MAX_SYMBOLS = 10
# A foreign symbol is converted with the nearest earlier daily close of its currency pair; this
# many days back spans any weekend or run of holidays.
FX_LOOKBACK_DAYS = 7


_BAR_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}  # intraday only


class SimError(Exception):
    """A request the session can't honour. `status_code` is what the API answers with."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SimNotFound(SimError):
    status_code = 404


class SimConflict(SimError):
    status_code = 409


@dataclass
class SimRun:
    """A session with its bars in memory and a context that trades against them."""

    session: SimSession
    replay: ReplayProvider
    ctx: TradingContext
    ends: list[int]  # every moment a bar of the session's symbols finishes, ascending, unique
    first_cursor: datetime  # the start of the first bar: nothing has finished yet
    timezones: dict[str, str]  # symbol -> exchange zone
    markets: list[Market]


class _NoFetch:
    """Stands in for the provider when bars are read back from the cache. Everything a session
    needs was fetched when it was made; today's bars would otherwise be asked for again on every
    tick, and the replay would shift under the player."""

    name = "cache"

    def get_history(self, symbol: str, interval: str, start: date, end: date) -> list[Bar]:
        return []


_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(session_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(session_id, threading.Lock())


def _instrument(provider: MarketDataProvider, symbol: str) -> Instrument:
    quote = provider.get_quote(symbol)  # for the name, type and currency only, never a price
    return Instrument(symbol, quote.name, quote.exchange, quote.type, quote.currency)


def session_functions(instruments: list[Instrument], markets: list[Market]) -> dict[str, SessionBounds]:
    """Each symbol's exchange hours, for a replay of daily bars (see `ReplayProvider`)."""
    return {i.symbol: partial(hours.session_bounds, m) for i, m in zip(instruments, markets, strict=True)}


def fx_pairs(instruments: list[Instrument], account_currency: str) -> list[str]:
    """The pairs `get_fx_rate` will ask for to bring these instruments into the account currency."""
    foreign = {i.currency for i in instruments if i.currency != account_currency}
    return sorted(f"{currency}{account_currency}=X" for currency in foreign)


def load_bars(
    db: Session,
    provider: MarketDataProvider,
    session: SimSession,
    instruments: list[Instrument],
    account_currency: str,
) -> tuple[dict[str, list[Bar]], dict[str, list[Bar]]]:
    """(session bars by symbol, daily FX bars by pair) through the shared bar cache. `provider`
    is asked only for what the cache lacks."""
    # Checked against Yahoo's limits as of the day the session was made, so a session does not
    # become unplayable as its (still cached) days age out of what Yahoo would serve today.
    today = session.created_at.astimezone(UTC).date()
    bars = {
        s: get_history(db, provider, s, session.interval, session.start_date, session.end_date, today)
        for s in session.symbols
    }
    fx_start = session.start_date - timedelta(days=FX_LOOKBACK_DAYS)
    fx = {
        pair: get_history(db, provider, pair, "1d", fx_start, session.end_date, today)
        for pair in fx_pairs(instruments, account_currency)
    }
    return bars, fx


def build_run(db: Session, session: SimSession, provider: MarketDataProvider | None = None) -> SimRun:
    """`provider` supplies instrument details only; no price ever comes from it."""
    provider = provider or get_provider()
    account = db.get(Account, session.account_id)
    assert account is not None
    instruments = [_instrument(provider, s) for s in session.symbols]
    markets = [market_for(i.symbol, i.type) for i in instruments]
    timezones = {i.symbol: hours.timezone_of(m) for i, m in zip(instruments, markets, strict=True)}
    bars, fx = load_bars(db, _NoFetch(), session, instruments, account.currency)  # type: ignore[arg-type]

    replay = ReplayProvider(
        session.cursor,
        instruments={i.symbol: i for i in instruments},
        inner=provider,
        timezones=timezones,
        sessions=session_functions(instruments, markets),
    )
    for symbol, series in bars.items():
        replay.load(symbol, session.interval, series)
    for pair, series in fx.items():
        replay.load(pair, "1d", series)

    ends = replay.visit_times(session.symbols, session.interval)
    first = replay.first_cursor(session.symbols, session.interval) or session.cursor
    # The context's clock is the replay's cursor: one value, moved only by `_advance_locked`.
    ctx = TradingContext(db, account, replay, lambda: replay.cursor)
    return SimRun(session, replay, ctx, ends, first, timezones, markets)


def build_context(
    db: Session, session: SimSession, provider: MarketDataProvider | None = None
) -> TradingContext:
    """A context for the session's account whose clock is the session cursor."""
    return build_run(db, session, provider).ctx


def create_session(
    db: Session,
    provider: MarketDataProvider,
    *,
    symbols: list[str],
    interval: str,
    start_date: date,
    end_date: date,
    speed: int,
    owner_user_id: int | None = None,
) -> SimSession:
    """Validate the range against what Yahoo serves, fetch and cache the bars, then make the
    session and its account. Nothing is created if any step fails."""
    symbols = list(dict.fromkeys(symbols))
    if not symbols or len(symbols) > MAX_SYMBOLS:
        raise SimError(f"Pick between 1 and {MAX_SYMBOLS} symbols.")
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise SimError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED} bars a second.")
    instruments = [_instrument(provider, s) for s in symbols]
    for inst in instruments:
        if inst.type not in TRADABLE_TYPES:
            raise SimError(
                f"{inst.name} ({inst.symbol}) can be charted but not traded, so it can't be replayed."
            )
        market_for(inst.symbol, inst.type)  # an exchange we don't model is refused here

    settings = get_settings()
    now = clock.now()
    draft = SimSession(
        symbols=symbols, interval=interval, start_date=start_date, end_date=end_date, speed=speed,
        created_at=now, cursor=now, status=SimStatus.READY, owner_user_id=owner_user_id,
    )
    bars, _ = load_bars(db, provider, draft, instruments, settings.base_currency)
    empty = [s for s, series in bars.items() if not series]
    if len(empty) == len(symbols):
        raise HistoryRangeError(
            f"No {interval} bars between {start_date:%d %b %Y} and {end_date:%d %b %Y}: the market "
            "was shut (weekend or holiday). Pick a trading day."
        )
    if empty:
        raise HistoryRangeError(f"No {interval} bars for {', '.join(empty)} in that range.")

    live = get_account(db)
    account = Account(
        currency=settings.base_currency,
        cash=settings.starting_cash,
        starting_cash=settings.starting_cash,
        realized_pnl=ZERO,
        margin_used=ZERO,
        created_at=now,
        kind=AccountKind.SIM,
        user_id=owner_user_id,
        broker_india=live.broker_india,
        broker_international=live.broker_international,
        broker_crypto=live.broker_crypto,
    )
    db.add(account)
    db.flush()
    draft.account_id = account.id
    db.add(draft)
    db.flush()
    draft.cursor = build_run(db, draft, provider).first_cursor
    db.commit()
    return draft


def get_session(db: Session, session_id: int) -> SimSession:
    found = db.get(SimSession, session_id)
    if found is None:
        raise SimNotFound(f"There is no simulation {session_id}.")
    return found


def list_sessions(db: Session) -> list[SimSession]:
    return list(db.scalars(select(SimSession).order_by(SimSession.id.desc())))


def progress_percent(run: SimRun) -> float:
    if not run.ends:
        return 100.0
    played = bisect_right(run.ends, int(run.session.cursor.timestamp()))
    return round(100 * played / len(run.ends), 1)


def advance(
    db: Session, session: SimSession, n_bars: int, provider: MarketDataProvider | None = None
) -> int:
    """Move the cursor to the end of the next bar, `n_bars` times, running one tick after each.
    Returns how many steps were taken (fewer than asked when the data ends).

    The cursor jumps from one bar's end to the next one's, so a night or a weekend costs one
    step, not a thousand (a gap inside an open session is stepped through, see `_next_stop`).
    Reaching the end of the last bar finishes the session.
    """
    with _lock_for(session.id):
        db.refresh(session)  # a request or the driver may have moved it since this object was read
        if session.status == SimStatus.FINISHED:
            return 0
        return _advance_locked(db, build_run(db, session, provider), n_bars, until=None)


def advance_until(
    db: Session, session: SimSession, until: datetime, provider: MarketDataProvider | None = None
) -> int:
    """Step until the next bar would end after `until`."""
    with _lock_for(session.id):
        db.refresh(session)
        if session.status == SimStatus.FINISHED:
            return 0
        return _advance_locked(db, build_run(db, session, provider), None, until=until)


def _next_stop(run: SimRun, cursor: datetime) -> int | None:
    """The next moment worth ticking at, in unix seconds, or None when the data has ended.

    Normally the end of the next bar. But a gap inside an open session (Yahoo's minutes are not
    always all there) is time that really passes: the last price still stands and a square-off or
    a target is still due on the clock, so the cursor steps one bar length at a time through it
    instead of leaping to the far side. A closed market (night, weekend, holiday) is jumped.
    """
    index = bisect_right(run.ends, int(cursor.timestamp()))
    if index >= len(run.ends):
        return None
    next_end = run.ends[index]
    length = _BAR_SECONDS.get(run.session.interval)
    here = int(cursor.timestamp())
    if length and next_end - here > length and any(
        hours.market_status(m, cursor).state == "open" for m in run.markets
    ):
        return here + length
    return next_end


def _advance_locked(db: Session, run: SimRun, n_bars: int | None, until: datetime | None) -> int:
    session, replay = run.session, run.replay
    steps = 0
    while n_bars is None or steps < n_bars:
        stop = _next_stop(run, replay.cursor)
        if stop is None:
            break
        target = datetime.fromtimestamp(stop, UTC)
        if until is not None and target > until:
            break
        replay.cursor = target
        session.cursor = target
        finished = stop >= run.ends[-1]
        if finished:
            session.status = SimStatus.FINISHED
        # Committed before the tick: a tick step that fails rolls back, and the session's cursor
        # must not slip behind the replay's clock.
        db.commit()
        run_tick(run.ctx)
        steps += 1
        if finished:
            break
    return steps


def set_status(db: Session, session: SimSession, status: SimStatus) -> None:
    with _lock_for(session.id):
        db.refresh(session)
        if session.status == SimStatus.FINISHED:
            if status == SimStatus.RUNNING:
                raise SimConflict("This simulation has finished. Reset it to play it again.")
            return  # pausing something that already stopped is not an error
        session.status = status
        db.commit()


def set_speed(db: Session, session: SimSession, speed: int) -> None:
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise SimError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED} bars a second.")
    session.speed = speed
    db.commit()


def reset_session(db: Session, session: SimSession, provider: MarketDataProvider | None = None) -> None:
    """Back to the first bar with the starting cash and no orders or trades."""
    with _lock_for(session.id):
        db.refresh(session)
        run = build_run(db, session, provider)
        reset_account(run.ctx)
        session.cursor = run.first_cursor
        session.status = SimStatus.READY
        db.commit()


def delete_session(db: Session, session: SimSession) -> None:
    session_id, account_id = session.id, session.account_id
    with _lock_for(session_id):
        db.delete(session)
        db.flush()
        # Orders point at trades, so they go first.
        db.execute(delete(Order).where(Order.account_id == account_id))
        db.execute(delete(Trade).where(Trade.account_id == account_id))
        db.execute(delete(Account).where(Account.id == account_id))
        db.commit()
    with _locks_guard:
        _locks.pop(session_id, None)
