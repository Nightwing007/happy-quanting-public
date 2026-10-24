from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import auth, clock
from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.models import User
from app.schemas import LoginIn, ProfileIn, SignupIn, UserOut
from app.trading.engine import create_live_account

router = APIRouter(tags=["auth"])

# Same sentence for an unknown user and a wrong password, so the form cannot be used to find
# out which usernames exist.
WRONG_LOGIN = "Wrong username or password."

# A real hash to verify against when the user is unknown, so both paths take the same time.
_DUMMY_HASH = auth.hash_password("not-a-real-password")


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        path="/",
        secure=get_settings().cookie_secure,
    )


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/api/auth/signup", response_model=UserOut)
def signup(body: SignupIn, request: Request, response: Response, db: DbSession):
    username = body.username.strip().lower()
    if not auth.USERNAME_RE.match(username):
        raise auth.AuthError(
            "Usernames are 3 to 30 characters: letters, numbers and underscores.", "invalid_username", 400
        )
    if len(body.password) < auth.MIN_PASSWORD_LENGTH:
        raise auth.AuthError(
            f"Passwords need at least {auth.MIN_PASSWORD_LENGTH} characters.", "weak_password", 400
        )
    taken = auth.AuthError("That username is taken.", "username_taken", 409)
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise taken
    display_name = (body.display_name or "").strip() or username
    user = User(
        username=username,
        display_name=display_name[:60],
        bio="",
        password_hash=auth.hash_password(body.password),
        is_creator=False,
        created_at=clock.now(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two signups for one name at once
        db.rollback()
        raise taken from None
    create_live_account(db, user_id=user.id)
    _set_cookie(response, auth.new_session(db, user, clock.now()))
    return user


@router.post("/api/auth/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: DbSession):
    username = body.username.strip().lower()
    ip = _ip(request)
    if auth.login_limiter.blocked(username, ip):
        raise auth.AuthError(
            "Too many failed attempts. Please wait 15 minutes and try again.", "too_many_attempts", 429
        )
    user = db.scalar(select(User).where(User.username == username))
    ok = auth.verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
        auth.login_limiter.fail(username, ip)
        raise auth.AuthError(WRONG_LOGIN, "wrong_login", 401)
    auth.login_limiter.clear(username, ip)
    _set_cookie(response, auth.new_session(db, user, clock.now()))
    return user


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DbSession):
    auth.end_session(db, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    response.status_code = 204


@router.get("/api/me", response_model=UserOut)
def read_me(user: CurrentUser):
    return user


@router.put("/api/me", response_model=UserOut)
def update_me(body: ProfileIn, user: CurrentUser, db: DbSession):
    fields = body.model_dump(exclude_unset=True)
    if fields.get("display_name") is not None:
        user.display_name = fields["display_name"].strip() or user.display_name
    if "bio" in fields and fields["bio"] is not None:
        user.bio = fields["bio"]
    if "avatar_url" in fields:
        user.avatar_url = fields["avatar_url"] or None
    db.commit()
    return user
