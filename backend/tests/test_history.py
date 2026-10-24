"""Historical data: the cache, Yahoo's limits, the offline provider's sessions and the replay.

Calendar used throughout (2026): Mon 12 Oct .. Fri 16 Oct, Sat 17, Sun 18, Mon 19 .. Fri 23 Oct;
"today" is Sat 24 Oct. India is UTC+5:30 (09:15 IST = 03:45 UTC). New York is UTC-4 until
Sun 1 Nov 2026 and UTC-5 after it.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.base import ALLOWED_RANGES, Bar, DataUnavailable, MarketDataError
from app.market_data.fake import FakeProvider
from app.market_data.fx import get_fx_rate
from app.market_data.history import HistoryRangeError, earliest_date, get_history, history_limits
from app.market_data.replay import ReplayProvider
from app.models import BarCache, HistorySpan
from app.trading import hours
from app.trading.markets import market_for

TODAY = date(2026, 10, 24)
real_calendar = pytest.mark.real_calendar


class Counting:
    """Wraps a provider and records every get_history call as (symbol, interval, start, end)."""

    def __init__(self, inner: FakeProvider):
        self.inner = inner
        self.name = "counting"
        self.calls: list[tuple] = []

    def get_history(self, symbol, interval, start, end):
        self.calls.append((symbol, interval, start, end))
        return self.inner.get_history(symbol, interval, start, end)


def oct_(day: int) -> date:
    return date(2026, 10, day)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def ts(*args: int) -> int:
    return int(utc(*args).timestamp())


# ---- the cache -------------------------------------------------------------------------------


def test_cached_range_is_not_refetched(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    # Mon 12 Oct .. Fri 16 Oct 2026 is five trading days.
    first = get_history(db, provider, "RELIANCE.NS", "1d", oct_(12), oct_(16), TODAY)
    second = get_history(db, provider, "RELIANCE.NS", "1d", oct_(12), oct_(16), TODAY)
    assert len(provider.calls) == 1
    assert len(first) == 5
    assert second == first
    assert [b.time for b in first] == ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]


def test_a_sub_range_of_a_cached_range_is_served_from_cache(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    get_history(db, provider, "AAPL", "1d", oct_(12), oct_(23), TODAY)
    inner = get_history(db, provider, "AAPL", "1d", oct_(14), oct_(15), TODAY)
    assert len(provider.calls) == 1
    assert [b.time for b in inner] == ["2026-10-14", "2026-10-15"]


def test_partially_cached_range_fetches_only_the_gap(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    get_history(db, provider, "RELIANCE.NS", "1d", oct_(12), oct_(16), TODAY)
    # Asking for 12..23 Oct again: only Sat 17 Oct .. Fri 23 Oct is new.
    both = get_history(db, provider, "RELIANCE.NS", "1d", oct_(12), oct_(23), TODAY)
    assert provider.calls[1] == ("RELIANCE.NS", "1d", oct_(17), oct_(23))
    assert len(provider.calls) == 2
    assert len(both) == 10  # two Mon-Fri weeks
    # The two fetched spans were folded into one row.
    spans = db.scalars(select(HistorySpan)).all()
    assert [(s.start_date, s.end_date) for s in spans] == [(oct_(12), oct_(23))]


def test_a_gap_in_the_middle_is_the_only_thing_fetched(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    get_history(db, provider, "AAPL", "1d", oct_(5), oct_(9), TODAY)
    get_history(db, provider, "AAPL", "1d", oct_(19), oct_(23), TODAY)
    get_history(db, provider, "AAPL", "1d", oct_(5), oct_(23), TODAY)
    # Sat 10 Oct .. Sun 18 Oct lies between the two cached weeks.
    assert provider.calls[2] == ("AAPL", "1d", oct_(10), oct_(18))
    assert len(provider.calls) == 3


def test_a_weekend_with_no_bars_is_not_refetched_forever(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    # Sat 17 Oct and Sun 18 Oct 2026: no NSE bars, but the span has been asked about.
    for _ in range(3):
        assert get_history(db, provider, "RELIANCE.NS", "1d", oct_(17), oct_(18), TODAY) == []
    assert len(provider.calls) == 1


def test_today_is_always_asked_again(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    # Today's bars are still arriving, so the span recorded stops at yesterday (Fri 23 Oct).
    get_history(db, provider, "BTC-USD", "1d", oct_(22), TODAY, TODAY)
    get_history(db, provider, "BTC-USD", "1d", oct_(22), TODAY, TODAY)
    assert provider.calls[0] == ("BTC-USD", "1d", oct_(22), TODAY)
    assert provider.calls[1] == ("BTC-USD", "1d", TODAY, TODAY)


def test_intraday_range_is_cut_into_seven_day_requests(db: Session, fake_provider: FakeProvider) -> None:
    provider = Counting(fake_provider)
    bars = get_history(db, provider, "RELIANCE.NS", "1m", oct_(12), oct_(23), TODAY)
    # Twelve days: Mon 12 .. Sun 18 Oct, then Mon 19 .. Fri 23 Oct.
    assert [(c[2], c[3]) for c in provider.calls] == [
        (oct_(12), oct_(18)),
        (oct_(19), oct_(23)),
    ]
    assert len(bars) == 10 * 375  # ten NSE sessions of 375 minutes
    again = get_history(db, provider, "RELIANCE.NS", "1m", oct_(12), oct_(23), TODAY)
    assert len(provider.calls) == 2
    assert again == bars
    assert db.scalars(select(BarCache)).first().interval == "1m"


def test_bars_come_back_exactly_as_stored(db: Session, fake_provider: FakeProvider) -> None:
    fetched = fake_provider.get_history("AAPL", "1d", oct_(14), oct_(14))
    cached = get_history(db, fake_provider, "AAPL", "1d", oct_(14), oct_(14), TODAY)
    assert cached == fetched
    assert all(isinstance(b.close, Decimal) for b in cached)


def test_cached_bars_do_not_mix_symbols_or_intervals(db: Session, fake_provider: FakeProvider) -> None:
    get_history(db, fake_provider, "AAPL", "1d", oct_(12), oct_(16), TODAY)
    other = get_history(db, fake_provider, "MSFT", "1d", oct_(12), oct_(16), TODAY)
    assert len(other) == 5
    assert other[0].close != get_history(db, fake_provider, "AAPL", "1d", oct_(12), oct_(12), TODAY)[0].close


# ---- Yahoo's limits --------------------------------------------------------------------------


def test_one_minute_request_older_than_the_limit_is_refused_with_the_earliest_date(
    db: Session, fake_provider: FakeProvider
) -> None:
    provider = Counting(fake_provider)
    # Today is 24 Oct 2026; 1m reaches back 29 days (one inside Yahoo's 30), to 25 Sep 2026.
    with pytest.raises(HistoryRangeError) as caught:
        get_history(db, provider, "RELIANCE.NS", "1m", date(2026, 9, 24), oct_(1), TODAY)
    assert "25 Sep 2026" in caught.value.message
    assert provider.calls == []  # a refused request never costs an upstream call
    # The first allowed day itself is fine.
    assert get_history(db, provider, "RELIANCE.NS", "1m", date(2026, 9, 25), date(2026, 9, 25), TODAY)


def test_earliest_dates_per_interval() -> None:
    assert earliest_date("1m", TODAY) == date(2026, 9, 25)  # 24 Oct - 29 days
    assert earliest_date("5m", TODAY) == date(2026, 8, 26)  # 24 Oct - 59 days
    assert earliest_date("30m", TODAY) == date(2026, 8, 26)
    assert earliest_date("1h", TODAY) == date(2024, 10, 25)  # 24 Oct 2026 - 729 days
    assert earliest_date("1d", TODAY) is None
    assert [i for i, _ in history_limits(TODAY)] == list(ALLOWED_RANGES)


def test_sixty_day_intervals_and_hourly_are_checked_too(db: Session, fake_provider: FakeProvider) -> None:
    with pytest.raises(HistoryRangeError, match="26 Aug 2026"):
        get_history(db, fake_provider, "AAPL", "15m", date(2026, 8, 25), date(2026, 8, 30), TODAY)
    with pytest.raises(HistoryRangeError, match="25 Oct 2024"):
        get_history(db, fake_provider, "AAPL", "1h", date(2024, 10, 24), date(2024, 11, 1), TODAY)


def test_daily_history_has_no_limit(db: Session, fake_provider: FakeProvider) -> None:
    bars = get_history(db, fake_provider, "AAPL", "1d", date(2015, 1, 5), date(2015, 1, 9), TODAY)
    assert len(bars) == 5  # Mon 5 Jan .. Fri 9 Jan 2015


def test_bad_dates_are_refused_with_sentences(db: Session, fake_provider: FakeProvider) -> None:
    with pytest.raises(HistoryRangeError, match="after the end date"):
        get_history(db, fake_provider, "AAPL", "1d", oct_(16), oct_(12), TODAY)
    with pytest.raises(HistoryRangeError, match="after today"):
        get_history(db, fake_provider, "AAPL", "1d", oct_(20), oct_(25), TODAY)
    with pytest.raises(HistoryRangeError, match="isn't available"):
        get_history(db, fake_provider, "AAPL", "2m", oct_(20), oct_(21), TODAY)


def test_history_limits_route(client: TestClient, fixed_clock: datetime) -> None:
    # The fixed clock says Mon 2 Mar 2026, so 1m reaches back to 1 Feb 2026 (2 Mar - 29 days).
    body = client.get("/api/market/history-limits").json()
    assert body["today"] == "2026-03-02"
    by_interval = {row["interval"]: row["earliest"] for row in body["limits"]}
    assert by_interval["1m"] == "2026-02-01"
    assert by_interval["1d"] is None
    assert list(by_interval) == list(ALLOWED_RANGES)


# ---- the offline provider's sessions ----------------------------------------------------------


def test_nse_session_runs_0915_to_1530_ist(fake_provider: FakeProvider) -> None:
    bars = fake_provider.get_history("RELIANCE.NS", "1m", oct_(14), oct_(14))
    assert len(bars) == 375  # 09:15 to 15:30 is 6h15m
    assert bars[0].time == ts(2026, 10, 14, 3, 45)  # 09:15 IST = 03:45 UTC
    assert bars[-1].time == ts(2026, 10, 14, 9, 59)  # last bar starts 15:29 IST, ends 15:30 IST = 10:00 UTC


def test_us_session_runs_0930_to_1600_eastern_across_the_clock_change(fake_provider: FakeProvider) -> None:
    summer = fake_provider.get_history("AAPL", "1m", oct_(14), oct_(14))
    assert len(summer) == 390
    assert summer[0].time == ts(2026, 10, 14, 13, 30)  # 09:30 EDT = 13:30 UTC
    assert summer[-1].time + 60 == ts(2026, 10, 14, 20, 0)  # 16:00 EDT
    winter = fake_provider.get_history("AAPL", "1m", date(2026, 12, 2), date(2026, 12, 2))
    assert winter[0].time == ts(2026, 12, 2, 14, 30)  # 09:30 EST = 14:30 UTC
    assert winter[-1].time + 60 == ts(2026, 12, 2, 21, 0)  # 16:00 EST


def test_crypto_trades_all_day_every_day_and_stocks_skip_weekends(fake_provider: FakeProvider) -> None:
    saturday = oct_(17)
    coin = fake_provider.get_history("BTC-USD", "1m", saturday, saturday)
    assert len(coin) == 1440
    assert coin[0].time == ts(2026, 10, 17, 0, 0)
    assert coin[-1].time == ts(2026, 10, 17, 23, 59)
    assert fake_provider.get_history("RELIANCE.NS", "1m", saturday, saturday) == []
    assert fake_provider.get_history("AAPL", "1d", saturday, saturday) == []
    assert len(fake_provider.get_history("BTC-USD", "1d", saturday, saturday)) == 1


def test_hourly_and_five_minute_bars_group_from_the_open(fake_provider: FakeProvider) -> None:
    day = oct_(14)
    minutes = fake_provider.get_history("RELIANCE.NS", "1m", day, day)
    hourly = fake_provider.get_history("RELIANCE.NS", "1h", day, day)
    assert len(hourly) == 7  # six full hours from 09:15 and a final 15 minutes
    assert hourly[0].time == minutes[0].time
    assert hourly[0].open == minutes[0].open and hourly[0].close == minutes[59].close
    assert hourly[0].high == max(b.high for b in minutes[:60])
    assert hourly[0].volume == sum(b.volume for b in minutes[:60])
    assert len(fake_provider.get_history("RELIANCE.NS", "5m", day, day)) == 75


def test_history_is_deterministic_and_independent_of_the_range_asked(fake_provider: FakeProvider) -> None:
    alone = fake_provider.get_history("AAPL", "1m", oct_(14), oct_(14))
    wider = fake_provider.get_history("AAPL", "1m", oct_(13), oct_(15))
    assert alone == [b for b in wider if b in alone]
    assert fake_provider.get_history("AAPL", "1m", oct_(14), oct_(14)) == alone
    # Moving the live price must not rewrite the past.
    fake_provider.set_price("AAPL", Decimal("999"))
    assert fake_provider.get_history("AAPL", "1m", oct_(14), oct_(14)) == alone


def test_minute_bars_are_well_formed(fake_provider: FakeProvider) -> None:
    for bar in fake_provider.get_history("AAPL", "1m", oct_(14), oct_(14)):
        assert bar.low <= min(bar.open, bar.close) and bar.high >= max(bar.open, bar.close)


def test_daily_history_covers_years_and_fx_pairs(fake_provider: FakeProvider) -> None:
    years = fake_provider.get_history("RELIANCE.NS", "1d", date(2020, 1, 1), oct_(23))
    assert len(years) > 1500
    fx = fake_provider.get_history("USDINR=X", "1d", oct_(12), oct_(18))
    assert len(fx) == 5
    assert all(Decimal("70") < b.close < Decimal("100") for b in fx)  # near the seed rate 83.5
    weekly = fake_provider.get_history("AAPL", "1wk", oct_(12), oct_(25))
    assert [b.time for b in weekly] == ["2026-10-12", "2026-10-19"]  # Mondays


def test_intraday_for_an_unlisted_symbol_says_so(fake_provider: FakeProvider) -> None:
    with pytest.raises(DataUnavailable, match="no intraday history for MSFT"):
        fake_provider.get_history("MSFT", "1m", oct_(14), oct_(14))


# ---- the replay ------------------------------------------------------------------------------


def nse_replay(cursor: datetime, fake: FakeProvider, **kwargs) -> ReplayProvider:
    replay = ReplayProvider(cursor, inner=fake, **kwargs)
    # Tue 13 and Wed 14 Oct 2026 in one-minute bars.
    replay.load("RELIANCE.NS", "1m", fake.get_history("RELIANCE.NS", "1m", oct_(13), oct_(14)))
    return replay


def test_quote_is_the_close_of_the_last_bar_that_has_ended(fake_provider: FakeProvider) -> None:
    minutes = fake_provider.get_history("RELIANCE.NS", "1m", oct_(14), oct_(14))
    by_start = {b.time: b for b in minutes}
    replay = nse_replay(utc(2026, 10, 14, 4, 0, 0), fake_provider)
    # 04:00:00 UTC is 09:30 IST. The bar starting 03:59 ends exactly then, so it counts.
    quote = replay.get_quote("RELIANCE.NS")
    assert quote.price == by_start[ts(2026, 10, 14, 3, 59)].close
    assert quote.as_of == ts(2026, 10, 14, 4, 0)
    # The bar starting 04:00 is still forming until 04:01:00, however far into it we are.
    replay.cursor = utc(2026, 10, 14, 4, 0, 59)
    assert replay.get_quote("RELIANCE.NS").price == by_start[ts(2026, 10, 14, 3, 59)].close
    replay.cursor = utc(2026, 10, 14, 4, 1, 0)
    assert replay.get_quote("RELIANCE.NS").price == by_start[ts(2026, 10, 14, 4, 0)].close
    assert replay.get_quote("RELIANCE.NS").as_of == ts(2026, 10, 14, 4, 1)


def test_replay_never_leaks_a_future_bar_in_the_quote(fake_provider: FakeProvider) -> None:
    minutes = fake_provider.get_history("RELIANCE.NS", "1m", oct_(14), oct_(14))
    replay = nse_replay(utc(2026, 10, 14, 3, 0), fake_provider)
    future_closes = {b.close for b in minutes}
    for offset in range(0, 375 * 60, 17):  # every 17 seconds through the session
        replay.cursor = utc(2026, 10, 14, 3, 45) + timedelta(seconds=offset)
        quote = replay.get_quote("RELIANCE.NS")
        assert quote.as_of <= replay.cursor.timestamp()
    # Before the first bar of the 14th has ended, the 13th's last close is the quote.
    replay.cursor = utc(2026, 10, 14, 3, 45, 30)
    last_of_13th = fake_provider.get_history("RELIANCE.NS", "1m", oct_(13), oct_(13))[-1]
    assert replay.get_quote("RELIANCE.NS").price == last_of_13th.close
    assert future_closes  # the session really had bars to leak


def test_replay_never_leaks_a_future_bar_in_get_bars(fake_provider: FakeProvider) -> None:
    replay = nse_replay(utc(2026, 10, 14, 4, 0, 0), fake_provider)
    for cursor in (utc(2026, 10, 14, 3, 59, 59), utc(2026, 10, 14, 4, 0, 0), utc(2026, 10, 14, 4, 0, 1)):
        replay.cursor = cursor
        bars = replay.get_bars("RELIANCE.NS", "1m", "max")
        assert bars
        assert all(int(b.time) + 60 <= cursor.timestamp() for b in bars)
    # Exactly on the boundary 04:00:00: the 03:59 bar is the last one, and it is included.
    replay.cursor = utc(2026, 10, 14, 4, 0, 0)
    assert int(replay.get_bars("RELIANCE.NS", "1m", "max")[-1].time) == ts(2026, 10, 14, 3, 59)
    # One second earlier it is not.
    replay.cursor = utc(2026, 10, 14, 3, 59, 59)
    assert int(replay.get_bars("RELIANCE.NS", "1m", "max")[-1].time) == ts(2026, 10, 14, 3, 58)
    # And the range window cuts the past, not the future.
    replay.cursor = utc(2026, 10, 14, 4, 0, 0)
    # Window = the last day before 04:00 on the 14th, i.e. from 04:00 on the 13th: all of the 14th's
    # 15 closed bars plus the 13th's bars that started at or after 04:00 UTC (09:30 IST).
    day = replay.get_bars("RELIANCE.NS", "1m", "1d")
    assert len(day) == 15 + (375 - 15)
    assert len(replay.get_bars("RELIANCE.NS", "1m", "5d")) == 15 + 375


def test_get_history_on_the_replay_is_bounded_by_the_cursor_too(fake_provider: FakeProvider) -> None:
    replay = nse_replay(utc(2026, 10, 14, 4, 0, 0), fake_provider)
    got = replay.get_history("RELIANCE.NS", "1m", oct_(14), oct_(14))
    assert len(got) == 15  # 03:45 .. 03:59 UTC
    assert max(int(b.time) for b in got) + 60 <= ts(2026, 10, 14, 4, 0)


def test_before_any_bar_has_ended_there_is_no_quote(fake_provider: FakeProvider) -> None:
    replay = nse_replay(utc(2026, 10, 13, 3, 45, 30), fake_provider)  # the first bar ends 03:46
    with pytest.raises(DataUnavailable, match="No RELIANCE.NS bar has closed"):
        replay.get_quote("RELIANCE.NS")
    with pytest.raises(DataUnavailable, match="no data loaded"):
        replay.get_quote("AAPL")


def test_previous_close_is_the_prior_sessions_last_close(fake_provider: FakeProvider) -> None:
    tues = fake_provider.get_history("RELIANCE.NS", "1m", oct_(13), oct_(13))
    replay = nse_replay(utc(2026, 10, 14, 5, 0), fake_provider, timezones={"RELIANCE.NS": "Asia/Kolkata"})
    # The 13th's last bar, 15:29 IST, is the prior session's last close.
    assert replay.get_quote("RELIANCE.NS").previous_close == tues[-1].close
    replay.cursor = utc(2026, 10, 13, 5, 0)  # still the 13th: nothing earlier is loaded
    assert replay.get_quote("RELIANCE.NS").previous_close is None


def test_get_bars_stamps_exchange_local_time_when_the_zone_is_known(fake_provider: FakeProvider) -> None:
    replay = nse_replay(utc(2026, 10, 14, 4, 0), fake_provider, timezones={"RELIANCE.NS": "Asia/Kolkata"})
    first_of_14th = replay.get_bars("RELIANCE.NS", "1m", "1d")[-15]  # 15 bars of the 14th have closed
    # 03:45 UTC shifted by +5:30 reads 09:15 as a "UTC" clock, like the live provider's bars.
    assert first_of_14th.time == ts(2026, 10, 14, 9, 15)


@real_calendar
def test_quote_as_of_passes_can_fill_in_session_and_fails_before(fake_provider: FakeProvider) -> None:
    market = market_for("RELIANCE.NS", "equity")
    replay = nse_replay(utc(2026, 10, 14, 4, 0), fake_provider)

    # Wed 14 Oct, 09:30 IST: open, and the quote was stamped 09:30 IST, after the 09:15 open.
    cursor = utc(2026, 10, 14, 4, 0)
    assert hours.can_fill(market, replay.get_quote("RELIANCE.NS").as_of, cursor)

    # 09:15:30 IST: the market is open but no bar of today has closed, so the quote is still
    # yesterday's last close (stamped 15:30 IST on the 13th), older than today's open: stale.
    cursor = utc(2026, 10, 14, 3, 45, 30)
    replay.cursor = cursor
    assert replay.get_quote("RELIANCE.NS").as_of == ts(2026, 10, 13, 10, 0)
    assert not hours.can_fill(market, replay.get_quote("RELIANCE.NS").as_of, cursor)

    # One bar later (09:16 IST) the quote is fresh.
    replay.cursor = utc(2026, 10, 14, 3, 46)
    assert hours.can_fill(market, replay.get_quote("RELIANCE.NS").as_of, replay.cursor)

    # 08:30 IST, before the open: closed whatever the quote says.
    cursor = utc(2026, 10, 14, 3, 0)
    replay.cursor = cursor
    assert not hours.can_fill(market, replay.get_quote("RELIANCE.NS").as_of, cursor)


def test_fx_without_loaded_intraday_bars_falls_back_to_the_nearest_earlier_daily_close(
    fake_provider: FakeProvider,
) -> None:
    replay = nse_replay(utc(2026, 10, 14, 5, 0), fake_provider)
    daily = fake_provider.get_history("USDINR=X", "1d", oct_(12), oct_(16))
    replay.load("USDINR=X", "1d", daily)
    by_day = {b.time: b for b in daily}
    # Wed 14 Oct 05:00 UTC: the 14th's daily bar ends at midnight after it, so the 13th's close is
    # the nearest earlier one, stamped midnight 14 Oct.
    quote = replay.get_quote("USDINR=X")
    assert quote.price == by_day["2026-10-13"].close
    assert quote.as_of == ts(2026, 10, 14, 0, 0)
    assert quote.previous_close == by_day["2026-10-12"].close
    assert get_fx_rate(replay, "USD", "INR") == by_day["2026-10-13"].close
    replay.cursor = utc(2026, 10, 15, 0, 0)  # exactly midnight: the 14th's bar has now ended
    assert replay.get_quote("USDINR=X").price == by_day["2026-10-14"].close
    # Never a later day's rate, even though the 15th and 16th are loaded.
    replay.cursor = utc(2026, 10, 14, 23, 59, 59)
    assert replay.get_quote("USDINR=X").price == by_day["2026-10-13"].close


def test_fx_with_loaded_intraday_bars_replays_like_a_stock(fake_provider: FakeProvider) -> None:
    replay = ReplayProvider(utc(2026, 10, 14, 10, 1, 30), inner=fake_provider)
    one = Decimal("1")
    replay.load(
        "USDINR=X",
        "1m",
        [Bar(ts(2026, 10, 14, 10, m), one, one, one, Decimal(83) + Decimal(m) / 10, 0) for m in range(4)],
    )
    replay.load("USDINR=X", "1d", fake_provider.get_history("USDINR=X", "1d", oct_(12), oct_(13)))
    # 10:01:30: the 10:00 bar has ended (10:01), the 10:01 bar has not. Finer and fresher than the
    # daily close, so the minute bar wins.
    quote = replay.get_quote("USDINR=X")
    assert quote.price == Decimal("83.0")
    assert quote.as_of == ts(2026, 10, 14, 10, 1)
    replay.cursor = utc(2026, 10, 14, 10, 2, 0)
    assert replay.get_quote("USDINR=X").price == Decimal("83.1")


def test_search_and_fundamentals_delegate_or_raise_clearly(fake_provider: FakeProvider) -> None:
    with_inner = ReplayProvider(utc(2026, 10, 14), inner=fake_provider)
    assert with_inner.search("reliance")
    assert with_inner.get_fundamentals("RELIANCE.NS").sector == "Energy"
    bare = ReplayProvider(utc(2026, 10, 14))
    with pytest.raises(MarketDataError, match="can't search"):
        bare.search("reliance")
    with pytest.raises(MarketDataError, match="no fundamentals"):
        bare.get_fundamentals("RELIANCE.NS")


def test_replay_cursor_must_be_aware(fake_provider: FakeProvider) -> None:
    replay = nse_replay(utc(2026, 10, 14, 4, 0), fake_provider)
    replay.cursor = datetime(2026, 10, 14, 4, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        replay.get_quote("RELIANCE.NS")


def test_daily_replay_never_shows_the_day_in_progress(fake_provider: FakeProvider) -> None:
    replay = ReplayProvider(utc(2026, 10, 14, 12, 0), inner=fake_provider)
    replay.load("AAPL", "1d", fake_provider.get_history("AAPL", "1d", oct_(12), oct_(16)))
    assert [b.time for b in replay.get_bars("AAPL", "1d", "max")] == ["2026-10-12", "2026-10-13"]
