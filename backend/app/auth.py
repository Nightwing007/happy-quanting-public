"""Passwords, session tokens and the login rate limiter. Routes are in app/api/auth.py."""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import User, UserSession

COOKIE = "hq_session"
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 8
USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
DEMO_USERNAME = "demo"

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


class AuthError(Exception):
    """A sign-in problem worded for the person; `code` is what clients branch on."""

    def __init__(self, message: str, code: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(pw: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    # maxmem raised: OpenSSL's 32 MiB default is exactly what n=2**14, r=8 needs.
    return hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=64 * 1024 * 1024)


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(pw, salt, _N, _R, _P, _DKLEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(pw: str, stored: str) -> bool:
    if stored == "!":  # no password set: nobody can log in
        return False
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        want = base64.b64decode(expected)
        got = _scrypt(pw, base64.b64decode(salt), int(n), int(r), int(p), len(want))
    except ValueError, TypeError:
        return False
    return hmac.compare_digest(got, want)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(db: Session, user: User, now: datetime) -> str:
    """Start a login and return the token for the cookie (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def user_for_token(db: Session, token: str | None, now: datetime) -> User | None:
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if session is None or session.expires_at <= now:
        return None
    return db.get(User, session.user_id)


def end_session(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
    db.commit()


class LoginLimiter:
    """In memory (resets on restart). Two guards on failed logins:

    - lockout: `max_failures` (5) per (username, ip) in 15 minutes -> 429 for that pair only;
    - slow-down: `slow_after` (20) failures for a username across ALL ips in the window -> every
      attempt on that username waits `delay_seconds` first. Never a lockout, so one attacker (or
      one shared proxy address) cannot lock the real owner out; it only makes guessing slower.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: float = 15 * 60,
        slow_after: int = 20,
        delay_seconds: float = 2.0,
    ) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.slow_after = slow_after
        self.delay_seconds = delay_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._by_user: dict[str, list[float]] = {}

    def _recent_user(self, username: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._by_user.get(username, []) if t > cutoff]
        if recent:
            self._by_user[username] = recent
        else:
            self._by_user.pop(username, None)
        return recent

    def slow(self, username: str) -> bool:
        return len(self._recent_user(username)) >= self.slow_after

    def _recent(self, key: tuple[str, str]) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, username: str, ip: str) -> bool:
        return len(self._recent((username, ip))) >= self.max_failures

    def fail(self, username: str, ip: str) -> None:
        self._recent((username, ip))
        now = time.monotonic()
        self._failures.setdefault((username, ip), []).append(now)
        self._recent_user(username)
        self._by_user.setdefault(username, []).append(now)

    def clear(self, username: str, ip: str) -> None:
        # Only this ip's lockout: one address succeeding must not wipe the slow-down tally.
        self._failures.pop((username, ip), None)

    def reset(self) -> None:
        self._failures.clear()
        self._by_user.clear()


login_limiter = LoginLimiter()


def ensure_demo_password(db: Session) -> str | None:
    """Give the demo user a random password the first time (its hash is "!"); return it once."""
    user = db.scalar(select(User).where(User.username == DEMO_USERNAME))
    if user is None or user.password_hash != "!":
        return None
    password = secrets.token_urlsafe(9)
    user.password_hash = hash_password(password)
    db.commit()
    return password
