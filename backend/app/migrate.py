import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from app.config import BACKEND_DIR
from app.db import Base
from app.db import engine as default_engine

logger = logging.getLogger(__name__)

BASELINE_REVISION = "0001"


def _alembic_config() -> Config:
    # Absolute path so this works from any cwd (tests, dev.py, uvicorn).
    ini = Path(BACKEND_DIR / "alembic.ini")
    return Config(str(ini))


def upgrade_database(engine: Engine | None = None) -> None:
    """Bring the database to the latest schema, creating it if needed.

    A database made before migrations existed has the app tables but no `alembic_version`;
    it is stamped at the baseline first so Alembic does not try to create tables that exist.
    """
    engine = engine or default_engine
    cfg = _alembic_config()
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables and tables & set(Base.metadata.tables):
            logger.info("Pre-migrations database found; stamping at %s", BASELINE_REVISION)
            cfg.attributes["connection"] = connection
            command.stamp(cfg, BASELINE_REVISION)
            connection.commit()
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        connection.commit()
    logger.info("Database is at the latest migration")
