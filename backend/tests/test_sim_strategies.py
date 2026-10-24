"""A virtual sim session can run an algorithm: library, saved, uploaded code, or a marketplace
listing tried before subscribing (whose code, settings and logs stay hidden).

Daily bars of RELIANCE.NS from the offline provider, on the real NSE calendar. The fixed clock is
Monday 2026-03-02, so 2026-01-05 .. 2026-02-27 is all in the past. SMA crossover with 3/5-day
averages trades several times on that stretch (the figures are the provider's deterministic noise,
so the tests compare the sim with the backtester instead of with hand-worked numbers).
"""

import multiprocessing
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algos import jobs
from app.algos.backtest import run_backtest
from app.config import get_settings
from app.market_data.fake import FakeProvider
from app.models import SimSession, SimStatus, Trade
from app.sim import runner, strategies

D = Decimal
SYMBOL = "RELIANCE.NS"
START, END = date(2026, 1, 5), date(2026, 2, 27)
TODAY = date(2026, 3, 2)
FAST = {"fast_period": 3, "slow_period": 5, "percent_of_cash": "50"}

SRC_SENTINEL = "SENTINEL_SRC_c04b77e1"
LOG_SENTINEL = "SENTINEL_LOG_6d92a315"
PARAM_SENTINEL = "47.3159265"

FLIP_SOURCE = f'''from app.algos import hq

# {SRC_SENTINEL}


class Flip(hq.Strategy):
    name = "Flip"
    description = "Buys a share, sells it on the next bar, and so on."
    markets = ("india",)
    interval = "1d"
    warmup_bars = 0
    PARAMETERS = {{}}

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, quantity=1)
                ctx.log("{LOG_SENTINEL} buying")
            else:
                ctx.sell(symbol)
                ctx.log("{LOG_SENTINEL} selling")
'''

pytestmark = pytest.mark.real_calendar


@pytest.fixture(autouse=True)
def rupee_world(offline_market_data, monkeypatch: pytest.MonkeyPatch, fixed_clock) -> None:
    monkeypatch.setenv("BASE_CURRENCY", "INR")
    monkeypatch.setenv("STARTING_CASH", "1000000")
    get_settings.cache_clear()
    yield
    strategies.drop_all()


def sim_body(strategy: dict | None, **over) -> dict:
    body = {"symbols": [SYMBOL], "start_date": START.isoformat(), "end_date": END.isoformat(), "speed": 60}
    if strategy is not None:
        body["strategy"] = strategy
    return {**body, **over}


def create(client: TestClient, strategy: dict | None, **over):
    return client.post("/api/sim/sessions", json=sim_body(strategy, **over))


def play(db: Session, provider: FakeProvider, session_id: int) -> SimSession:
    session = db.get(SimSession, session_id)
    runner.advance(db, session, 10_000, provider)
    db.refresh(session)
    return session


def rows_of(db: Session, session: SimSession) -> list[tuple]:
    trades = db.scalars(select(Trade).where(Trade.account_id == session.account_id).order_by(Trade.id))
    return [
        (t.symbol, t.direction, t.quantity, t.entry_price, t.opened_at, t.status, t.closed_how)
        for t in trades
    ]


def publish_listing(client: TestClient, **over) -> dict:
    draft = over.pop("_draft", False)
    body = dict(
        name="Flipper", markets=["india"], test_symbols=[SYMBOL], fee_percent="10", tagline="t",
        description="d", source=FLIP_SOURCE,
    )  # fmt: skip
    r = client.post("/api/marketplace/listings", json={**body, **over})
    assert r.status_code == 200, r.text
    listing = r.json()
    if draft:
        return listing
    assert client.post(f"/api/marketplace/listings/{listing['id']}/publish").status_code == 200
    return listing


def save_algo(client: TestClient, **params) -> int:
    r = client.post(
        "/api/algos/mine",
        json={"name": "Quick SMA", "description": "", "strategy": "sma_crossover", "params": params},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --- one engine ---------------------------------------------------------------------------


def test_a_library_algo_in_a_sim_trades_exactly_like_its_backtest(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    r = create(client, {"kind": "library", "key": "sma_crossover", "params": FAST})
    assert r.status_code == 200, r.text
    assert r.json()["interval"] == "1d"  # defaulted from the algorithm
    session = play(db, fake_provider, r.json()["id"])
    assert session.status == SimStatus.FINISHED

    result = run_backtest(
        db, fake_provider, strategy_key="sma_crossover", params=FAST, symbols=[SYMBOL], interval="1d",
        start=START, end=END, starting_cash=D(get_settings().starting_cash), account_currency="INR",
        today=TODAY,
    )  # fmt: skip
    expected = [
        (t.symbol, t.direction, t.quantity, t.entry_price, t.entry_at, t.status, t.closed_how)
        for t in result.trades
    ]
    assert len(expected) >= 2  # the comparison means something
    assert rows_of(db, session) == expected


def test_a_source_strategy_with_warmup_trades_exactly_like_its_backtest(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    # Uploaded code declares `warmup_bars = 5` as a literal, so both the sim and the backtester
    # preload five bars before START and the strategy may decide before the first open.
    source = FLIP_SOURCE.replace("warmup_bars = 0", "warmup_bars = 5")
    r = create(client, {"kind": "source", "source": source})
    assert r.status_code == 200, r.text
    session = play(db, fake_provider, r.json()["id"])
    assert strategies.warmup_bars(db, session) == 5

    result = run_backtest(
        db, fake_provider, source=source, symbols=[SYMBOL], interval="1d", start=START, end=END,
        starting_cash=D(get_settings().starting_cash), account_currency="INR", today=TODAY,
    )  # fmt: skip
    assert result.warmup_bars == 5
    expected = [
        (t.symbol, t.direction, t.quantity, t.entry_price, t.entry_at, t.status, t.closed_how)
        for t in result.trades
    ]
    assert len(expected) >= 5
    assert rows_of(db, session) == expected


def test_a_saved_algo_and_a_source_strategy_run(client: TestClient, db: Session, fake_provider: FakeProvider):
    algo_id = save_algo(client, **FAST)
    mine = create(client, {"kind": "mine", "algo_id": algo_id})
    assert mine.status_code == 200, mine.text
    library = create(client, {"kind": "library", "key": "sma_crossover", "params": FAST})
    mine_rows = rows_of(db, play(db, fake_provider, mine.json()["id"]))
    assert mine_rows and mine_rows == rows_of(db, play(db, fake_provider, library.json()["id"]))

    source = create(client, {"kind": "source", "source": FLIP_SOURCE})
    assert source.status_code == 200, source.text
    session = play(db, fake_provider, source.json()["id"])
    assert len(rows_of(db, session)) >= 5  # buys and sells a share most days

    state = client.get(f"/api/sim/sessions/{session.id}").json()
    assert state["strategy"] == {"kind": "source", "name": "Flip", "interval": "1d", "creator": None}
    # The owner of the code sees how it behaved.
    assert state["strategy_log"] and LOG_SENTINEL in state["strategy_log"][-1]["text"]
    assert len(state["strategy_log"]) <= 100


def test_someone_elses_saved_algo_is_not_found(client: TestClient, second_client: TestClient):
    algo_id = save_algo(client, **FAST)
    r = create(second_client, {"kind": "mine", "algo_id": algo_id})
    assert r.status_code == 404


def test_a_source_with_problems_is_refused_and_they_are_listed(client: TestClient):
    r = create(client, {"kind": "source", "source": "import os\n"})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_source" and r.json()["problems"]
    assert client.get("/api/sim/sessions").json() == []  # nothing was made


def test_an_interval_that_is_not_the_strategys_is_refused_with_a_sentence(client: TestClient):
    r = create(client, {"kind": "library", "key": "sma_crossover"}, interval="1m")
    assert r.status_code == 400
    assert "1d bars" in r.json()["detail"] and "1m" in r.json()["detail"]
    assert client.get("/api/sim/sessions").json() == []


# --- trying a listing before subscribing --------------------------------------------------


def test_another_user_can_try_a_published_listing_and_sees_none_of_its_insides(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
):
    listing = publish_listing(client)
    from_algo = publish_listing(
        client, name="Saved", source=None,
        user_algo_id=save_algo(client, **{**FAST, "percent_of_cash": PARAM_SENTINEL}),
    )  # fmt: skip

    for item in (listing, from_algo):
        r = create(second_client, {"kind": "listing", "listing_id": item["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["interval"] == "1d"
        session = play(db, fake_provider, r.json()["id"])
        assert rows_of(db, session), f"{item['name']} made no trades"

        state = second_client.get(f"/api/sim/sessions/{session.id}")
        assert state.status_code == 200
        assert state.json()["strategy"] == {
            "kind": "listing", "name": item["name"], "interval": "1d", "creator": "tester",
        }  # fmt: skip
        assert state.json()["strategy_log"] == []
        for secret in (SRC_SENTINEL, LOG_SENTINEL, PARAM_SENTINEL, "def on_bar", "percent_of_cash"):
            assert secret not in state.text, f"state leaked {secret}"
            assert secret not in r.text and secret not in second_client.get("/api/sim/sessions").text
        # The pinned version is stored server-side, the code is not on the row.
        pinned = (session.strategy_kind, session.listing_id, session.listing_version)
        assert pinned == ("listing", item["id"], 1)
        assert session.source is None and session.params is None

    # The creator's own sim of their listing goes through the same hiding.
    mine = create(client, {"kind": "listing", "listing_id": listing["id"]})
    assert client.get(f"/api/sim/sessions/{mine.json()['id']}").json()["strategy_log"] == []


def test_a_draft_listing_cannot_be_tried(client: TestClient, second_client: TestClient):
    draft = publish_listing(client, _draft=True)
    r = create(second_client, {"kind": "listing", "listing_id": draft["id"]})
    assert r.status_code == 404
    assert create(second_client, {"kind": "listing", "listing_id": 9999}).status_code == 404


def test_the_listing_version_is_pinned_when_the_sim_is_made(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
):
    listing = publish_listing(client)
    r = create(second_client, {"kind": "listing", "listing_id": listing["id"]})
    edited = client.put(
        f"/api/marketplace/listings/{listing['id']}",
        json={"source": FLIP_SOURCE.replace("Flip", "Flop"), "changelog": "v2"},
    )
    assert edited.status_code == 200, edited.text
    session = play(db, fake_provider, r.json()["id"])
    assert session.listing_version == 1 and rows_of(db, session)


# --- the sandbox child --------------------------------------------------------------------


def test_the_sandbox_child_is_gone_after_delete_reset_and_finish(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    assert multiprocessing.active_children() == []

    deleted = create(client, {"kind": "source", "source": FLIP_SOURCE}).json()["id"]
    runner.advance(db, db.get(SimSession, deleted), 3, fake_provider)
    assert len(multiprocessing.active_children()) == 1  # held between steps
    assert client.delete(f"/api/sim/sessions/{deleted}").status_code == 204
    assert multiprocessing.active_children() == []

    reset = create(client, {"kind": "source", "source": FLIP_SOURCE}).json()["id"]
    runner.advance(db, db.get(SimSession, reset), 3, fake_provider)
    assert len(multiprocessing.active_children()) == 1
    runner.reset_session(db, db.get(SimSession, reset), fake_provider)
    assert multiprocessing.active_children() == []

    finished = play(db, fake_provider, reset)  # rebuilt from the first bar, then played to the end
    assert finished.status == SimStatus.FINISHED
    assert multiprocessing.active_children() == []
    assert strategies._runs == {}


def test_manual_trading_next_to_a_strategy_is_allowed(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    sim = create(client, {"kind": "library", "key": "sma_crossover", "params": FAST}).json()
    runner.advance(db, db.get(SimSession, sim["id"]), 12, fake_provider)
    r = client.post(
        f"/api/sim/sessions/{sim['id']}/orders",
        json={"symbol": SYMBOL, "side": "buy", "type": "market", "quantity": "1"},
    )
    assert r.status_code == 200, r.text


# --- saved algorithms that hold editor code ----------------------------------------------------


def save_source_algo(client: TestClient, source: str = FLIP_SOURCE, **over):
    body = {"name": "Flip (mine)", "description": "from the editor", "source": source, **over}
    return client.post("/api/algos/mine", json=body)


def test_editor_code_is_saved_owner_only_and_checked_by_the_validator(
    client: TestClient, second_client: TestClient
):
    r = save_source_algo(client)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["source"] == FLIP_SOURCE and row["strategy"] == "" and row["interval"] == "1d"
    assert row["strategy_name"] == "Flip" and row["markets"] == ["india"]

    # Owner-only: another user sees none of it and gets "not found" for the id.
    assert second_client.get("/api/algos/mine").json() == []
    assert second_client.get(f"/api/algos/mine/{row['id']}").status_code == 404
    other_put = second_client.put(f"/api/algos/mine/{row['id']}", json={"name": "x", "source": FLIP_SOURCE})
    assert other_put.status_code == 404

    # Code that breaks the rules is refused with the validator's line-numbered problems.
    bad = save_source_algo(client, "import os\n" + FLIP_SOURCE)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_source"
    assert "Line 1" in bad.json()["detail"]
    both = client.post(
        "/api/algos/mine", json={"name": "x", "strategy": "sma_crossover", "source": FLIP_SOURCE}
    )
    assert both.status_code == 400

    # Editing replaces the code; switching to a library strategy clears it.
    edited = client.put(
        f"/api/algos/mine/{row['id']}", json={"name": "Flip 2", "source": FLIP_SOURCE + "\n# edit\n"}
    )
    assert edited.status_code == 200 and edited.json()["source"].endswith("# edit\n")
    back = client.put(f"/api/algos/mine/{row['id']}", json={"name": "SMA", "strategy": "sma_crossover"})
    assert back.json()["source"] is None and back.json()["strategy"] == "sma_crossover"


def test_a_saved_editor_algo_runs_in_a_backtest_and_in_the_sim(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    source = FLIP_SOURCE.replace("warmup_bars = 0", "warmup_bars = 5")
    algo_id = save_source_algo(client, source).json()["id"]

    made = client.post(
        "/api/backtests",
        json={
            "algo_id": algo_id, "symbols": [SYMBOL], "interval": "1d",
            "start_date": START.isoformat(), "end_date": END.isoformat(),
        },
    )  # fmt: skip
    assert made.status_code == 200, made.text
    jobs.run_backtest_job(db, made.json()["id"], fake_provider, today=TODAY)
    done = client.get(f"/api/backtests/{made.json()['id']}").json()
    assert done["status"] == "done" and done["results"]["warmup_bars"] == 5
    assert "source" not in done and SRC_SENTINEL not in str(done)  # the code is never in a result

    r = create(client, {"kind": "mine", "algo_id": algo_id})
    assert r.status_code == 200, r.text
    session = play(db, fake_provider, r.json()["id"])
    assert strategies.warmup_bars(db, session) == 5
    assert len(rows_of(db, session)) >= 5
    state = client.get(f"/api/sim/sessions/{session.id}").json()
    assert any(LOG_SENTINEL in line["text"] for line in state["strategy_log"])  # the owner sees logs
    assert SRC_SENTINEL not in str(state)
    assert state["strategy"] == {"kind": "mine", "name": "Flip (mine)", "interval": "1d", "creator": None}
