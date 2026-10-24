from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, MetaData, String, create_engine
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import DATA_DIR, get_settings

# Every constraint gets a deterministic name, otherwise Alembic emits unnamed foreign keys
# and SQLite batch migrations (and downgrades) cannot refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DecimalString(TypeDecorator):
    """Stores a Decimal as TEXT.

    SQLite's only numeric type is a float, and floats lose paise (0.1 + 0.2 != 0.3).
    Keeping the exact decimal string means what we read back is what we wrote.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            # A float (or int) in a money path is a bug; fail loudly rather than round silently.
            raise TypeError(f"DecimalString needs a Decimal, got {type(value).__name__}")
        # Fixed-point, never scientific: str(Decimal("0.00000001")) is "1E-8".
        return f"{value:f}"

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


class UTCDateTime(TypeDecorator):
    """Stores an aware UTC datetime as naive UTC and hands back an aware UTC datetime.

    SQLite drops tzinfo, so without this a value read back is naive and cannot be compared
    with the aware clock the engine uses.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # One-clock rule: every time comes from an aware UTC clock, so a naive one is a bug.
            raise ValueError("UTCDateTime needs a timezone-aware datetime, got a naive one")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


def build_engine(database_url: str):
    kwargs = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, **kwargs)


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
