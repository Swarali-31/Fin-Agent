"""Password accounts and revocable, opaque cookie sessions."""
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
import re
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from backend.app.api.responses import success
from backend.app.db.models import UserRecord, SessionRecord
from backend.app.services.api import configured_repository, APIServiceError
from backend.app.config.settings import get_settings

router = APIRouter(prefix="/api/v1/auth")
COOKIE = "finagent_session"
_attempts: dict[tuple[str, str], deque] = defaultdict(deque)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Enter a valid email address, such as you@example.com.")
        email = value.strip().lower()
        local, separator, domain = email.partition("@")
        if (not separator or len(local) > 64 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local)
                or local.startswith(".") or local.endswith(".") or ".." in local
                or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain)):
            raise ValueError("Enter a valid email address, such as you@example.com.")
        return email


class Signup(Credentials):
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter your name.")
        return value.strip()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, _digest = encoded.split("$")
        return hmac.compare_digest(password_hash(password, salt), encoded)
    except ValueError:
        return False


_DUMMY_PASSWORD_HASH = password_hash("unused-password", "0" * 32)


def public_user(user: UserRecord) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email}


def authenticate(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 128:
        return None
    repository = configured_repository(request=request)
    with repository._sessions() as session:
        record = session.get(SessionRecord, hashlib.sha256(token.encode()).hexdigest())
        if not record or (record.expires_at.replace(tzinfo=UTC) if record.expires_at.tzinfo is None else record.expires_at.astimezone(UTC)) <= datetime.now(UTC):
            return None
        user = session.get(UserRecord, record.user_id)
        return public_user(user) if user else None


def rate_limit(request: Request, action: str) -> None:
    key = (request.client.host if request.client else "local", action)
    now = time.monotonic()
    # Bound memory without resetting active rate-limit buckets.
    if len(_attempts) > 1000:
        for old in list(_attempts):
            if not _attempts[old] or _attempts[old][-1] < now - 900:
                del _attempts[old]
    bucket = _attempts[key]
    while bucket and bucket[0] < now - 900:
        bucket.popleft()
    if len(bucket) >= 20:
        raise APIServiceError(429, "too_many_attempts", "Too many attempts. Try again in 15 minutes.")
    bucket.append(now)


def session_response(request: Request, user: dict, status_code: int = 200):
    token = secrets.token_urlsafe(32)
    repository = configured_repository(request=request)
    owned = repository.for_user(user["id"])
    profiles = owned.list_profiles()
    if not profiles:
        owned.create_profile(f"personal-{user['id']}", user.get("currency", "INR"))
        profiles = owned.list_profiles()
    user = {**user, "profile_id": profiles[0]["profile_id"], "currency": profiles[0]["currency"]}
    with repository._sessions.begin() as session:
        old_token = request.cookies.get(COOKIE)
        if old_token:
            previous = session.get(SessionRecord, hashlib.sha256(old_token.encode()).hexdigest())
            if previous:
                session.delete(previous)
        session.add(SessionRecord(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user["id"], expires_at=datetime.now(UTC) + timedelta(days=7)))
    response = success(request, user, status_code=status_code)
    response.set_cookie(COOKIE, token, httponly=True, secure=get_settings().secure_cookies,
                        samesite="lax", max_age=604800, path="/")
    return response


@router.post("/signup", status_code=201)
async def signup(request: Request, body: Signup):
    rate_limit(request, "signup")
    repository = configured_repository(request=request)
    encoded = await run_in_threadpool(password_hash, body.password)
    try:
        with repository._sessions.begin() as session:
            user = UserRecord(email=body.email, name=body.name, password_hash=encoded)
            session.add(user)
            session.flush()
            result = public_user(user)
    except IntegrityError:
        raise APIServiceError(409, "account_exists", "An account with this email already exists. Sign in instead.")
    return session_response(request, {**result, "currency": body.currency}, 201)


@router.post("/login")
async def login(request: Request, body: Credentials):
    rate_limit(request, "login")
    repository = configured_repository(request=request)
    with repository._sessions() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.email == body.email))
        # Constant-cost password verification even for unknown accounts.
        encoded = user.password_hash if user else _DUMMY_PASSWORD_HASH
        valid = await run_in_threadpool(verify_password, body.password, encoded)
        if not user or not valid:
            raise APIServiceError(401, "invalid_credentials", "Email or password is incorrect.")
        result = public_user(user)
    return session_response(request, result)


@router.get("/me")
async def me(request: Request):
    user = authenticate(request)
    if not user:
        raise APIServiceError(401, "authentication_required", "Sign in to continue.")
    profiles = configured_repository(request=request).for_user(user["id"]).list_profiles()
    return success(request, {**user, "profile_id": profiles[0]["profile_id"] if profiles else None,
                             "currency": profiles[0]["currency"] if profiles else "INR"})


@router.get("/setup")
async def setup(request: Request):
    return success(request, {"accounts_available": bool(get_settings().database_url)})


@router.post("/logout")
async def logout(request: Request):
    repository = configured_repository(request=request)
    with repository._sessions.begin() as session:
        token = request.cookies.get(COOKIE, "")
        record = session.get(SessionRecord, hashlib.sha256(token.encode()).hexdigest())
        if record:
            session.delete(record)
    response = success(request, {"signed_out": True})
    response.delete_cookie(COOKIE, path="/")
    return response
