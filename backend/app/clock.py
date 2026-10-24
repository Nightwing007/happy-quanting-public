from datetime import UTC, datetime


def now() -> datetime:
    """The only place trading code gets the time; tests replace it.

    Always call it as `clock.now()` through the module, so monkeypatching `clock.now` works.
    """
    return datetime.now(UTC)
