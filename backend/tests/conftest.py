from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import clock
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app
from app.market_data import get_provider
from app.market_data.fake import FakeProvider
from app.trading import brokers, hours, markets


@pytest.fixture
def db_session() -> Iterator[Session]:
    # StaticPool keeps one connection, otherwise each checkout gets its own empty :memory: db.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(db_session: Session, fake_provider: FakeProvider) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    # One FakeProvider per test, so a test can set_price on it and see the API reflect that.
    app.dependency_overrides[get_provider] = lambda: fake_provider
    app.dependency_overrides[get_settings] = lambda: Settings(market_data_provider="fake")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def offline_market_data(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Guarantee no test reaches Yahoo, whatever a developer's .env says.
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "fake")
    # The app lifespan would otherwise migrate the real dev database.
    monkeypatch.setenv("RUN_MIGRATIONS", "false")
    monkeypatch.setenv("BACKGROUND_JOBS", "false")
    # Expected figures in the tests assume this account, whatever a developer's .env says.
    monkeypatch.setenv("BASE_CURRENCY", "USD")
    monkeypatch.setenv("STARTING_CASH", "100000")
    get_settings.cache_clear()
    get_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_provider.cache_clear()


@pytest.fixture(autouse=True)
def markets_always_open(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every market as open, whatever the real date, unless the test is marked
    `real_calendar`. Without it the suite would pass or fail by the day of the week it runs on.

    `is_open` and `can_fill` both read `market_status`, so replacing it is enough. Its session
    began at the epoch, so no quote is ever too old to fill on.
    """
    if request.node.get_closest_marker("real_calendar"):
        return

    def always_open(market, at=None):
        return hours.MarketStatus("open", True, datetime(1970, 1, 1, tzinfo=UTC), None, None, "UTC")

    monkeypatch.setattr(hours, "market_status", always_open)


FIXED_NOW = datetime(2026, 3, 2, 10, 30, tzinfo=UTC)


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    monkeypatch.setattr(clock, "now", lambda: FIXED_NOW)
    return FIXED_NOW


@pytest.fixture
def db(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def zero_costs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trade with no charges at all, for tests about something other than costs (average cost,
    cash checks, order lifecycle) whose expected numbers should not depend on a fee schedule.

    It swaps in a market and a broker with empty fee lists through the same two lookup
    functions `trade_cost` uses, so the charges code still runs end to end and just finds
    nothing to charge.
    """
    real_market_for = markets.market_for
    real_get_broker = brokers.get_broker

    def free_market(symbol: str, instrument_type: str):
        return replace(real_market_for(symbol, instrument_type), fees=[])

    def free_broker(code: str):
        return replace(
            real_get_broker(code),
            fees=[],
            fx_markup_percent=Decimal(0),
            markets=tuple(markets.MARKETS),  # offers everything, so no test trips on a broker
        )

    monkeypatch.setattr(markets, "market_for", free_market)
    monkeypatch.setattr(brokers, "get_broker", free_broker)
