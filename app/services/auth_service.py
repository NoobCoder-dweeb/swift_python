from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import RLock
from uuid import UUID

import bcrypt
from fastapi import HTTPException, Request, status

from app.repositories.state_repository import UserRow, get_state_repository


SESSION_USER_KEY = "swift_sales_officer"
ALLOWED_LEVELS = {"sales officer", "admin", "sales manager"}
LEGACY_LEVEL_ALIASES = {"sales person": "sales officer"}
FULL_PAGE_ACCESS_ROLES = {"admin", "administrator", "sales manager"}
ADMIN_ROLES = {"admin", "administrator"}


@dataclass(frozen=True)
class SalesOfficerAccount:
    """represents a database-backed sales reviewer account."""

    user_id: str
    username: str
    email: str
    name: str
    level: str
    initials: str

    @property
    def role(self) -> str:
        """keeps existing route/template access checks compatible."""
        return self.level

    @property
    def can_view_all_pages(self) -> bool:
        """distinguishes managers/admins from regular sales reviewers."""
        return role_can_view_all_pages(self.level)

    @property
    def is_admin(self) -> bool:
        """returns true for accounts allowed to change security controls."""
        return role_is_admin(self.level)

    def public_dict(self) -> dict[str, str | bool]:
        """returns fields safe for templates and session display."""
        payload = asdict(self)
        payload["role"] = self.level.title()
        payload["can_view_all_pages"] = self.can_view_all_pages
        payload["is_admin"] = self.is_admin
        return payload


@dataclass(frozen=True)
class DefaultUserSeed:
    """defines first-run reviewer users inserted into the configured database."""

    username: str
    email: str
    password: str
    level: str
    name: str
    initials: str


DEFAULT_USER_SEEDS: tuple[DefaultUserSeed, ...] = (
    DefaultUserSeed(
        "john",
        "john@project-swift.local",
        "swift123",
        "sales officer",
        "John Doe",
        "JD",
    ),
    DefaultUserSeed(
        "aisha",
        "aisha@project-swift.local",
        "swift123",
        "sales officer",
        "Aisha Sales",
        "AS",
    ),
    DefaultUserSeed(
        "mira",
        "mira@project-swift.local",
        "swift123",
        "sales officer",
        "Mira Tan",
        "MT",
    ),
    DefaultUserSeed(
        "manager",
        "manager@project-swift.local",
        "swift123",
        "sales manager",
        "Sales Manager",
        "SM",
    ),
    DefaultUserSeed(
        "admin",
        "admin@project-swift.local",
        "swift123",
        "admin",
        "Admin User",
        "AU",
    ),
)
DEFAULT_USER_PROFILES = {
    seed.username: {"name": seed.name, "initials": seed.initials}
    for seed in DEFAULT_USER_SEEDS
}
_seed_lock = RLock()
_seeded_repository_ids: set[int] = set()


def hash_password(password: str) -> str:
    """returns a bcrypt hash suitable for storage in swift_users."""
    return bcrypt.hashpw((password or "").encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    """checks a submitted password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            (password or "").encode(),
            (hashed_password or "").encode(),
        )
    except ValueError:
        return False


def normalize_level(level: str | None) -> str:
    """keeps role gates tied to the supported database level values."""
    normalized = (level or "").strip().lower()
    normalized = LEGACY_LEVEL_ALIASES.get(normalized, normalized)
    return normalized if normalized in ALLOWED_LEVELS else "sales officer"


def role_can_view_all_pages(role: str) -> bool:
    """returns true for roles allowed to view every UI page."""
    return (role or "").strip().lower() in FULL_PAGE_ACCESS_ROLES


def role_is_admin(role: str) -> bool:
    """returns true for roles allowed to administer security settings."""
    return (role or "").strip().lower() in ADMIN_ROLES


def list_accounts() -> list[dict[str, str | bool]]:
    """lists database-backed sales reviewer accounts for UI context."""
    ensure_default_users()
    return [
        _account_from_row(row).public_dict()
        for row in get_state_repository().list_users()
    ]


def authenticate(username: str, password: str) -> SalesOfficerAccount | None:
    """checks submitted credentials against the configured user database."""
    ensure_default_users()
    normalized_username = (username or "").strip().lower()
    row = get_state_repository().get_user_by_username(normalized_username)
    if not row or not verify_password(password, str(row.get("hashed_password") or "")):
        return None
    return _account_from_row(row)


def get_account(identity: str | None) -> SalesOfficerAccount | None:
    """finds an account by UUID, with legacy username-session compatibility."""
    normalized_identity = (identity or "").strip()
    if not normalized_identity:
        return None
    ensure_default_users()
    repository = get_state_repository()
    try:
        user_id = str(UUID(normalized_identity))
    except ValueError:
        row = repository.get_user_by_username(normalized_identity.lower())
    else:
        row = repository.get_user_by_id(user_id)
    return _account_from_row(row) if row else None


def ensure_default_users() -> None:
    """seeds first-run users once per process if they are missing."""
    repository = get_state_repository()
    repository_id = id(repository)
    if repository_id in _seeded_repository_ids:
        return
    with _seed_lock:
        if repository_id in _seeded_repository_ids:
            return
        for seed in DEFAULT_USER_SEEDS:
            if repository.get_user_by_username(seed.username):
                continue
            repository.upsert_user(
                {
                    "username": seed.username,
                    "email": seed.email,
                    "hashed_password": hash_password(seed.password),
                    "level": normalize_level(seed.level),
                }
            )
        _seeded_repository_ids.add(repository_id)


def _account_from_row(row: UserRow) -> SalesOfficerAccount:
    """maps stored user rows to the account shape used by routes/templates."""
    username = str(row.get("username") or "").strip().lower()
    profile = DEFAULT_USER_PROFILES.get(username, {})
    name = str(profile.get("name") or _display_name(username))
    initials = str(profile.get("initials") or _initials(name))
    return SalesOfficerAccount(
        user_id=str(row.get("user_id") or ""),
        username=username,
        email=str(row.get("email") or ""),
        name=name,
        level=normalize_level(str(row.get("level") or "")),
        initials=initials,
    )


def _display_name(username: str) -> str:
    """turns ad-hoc usernames into readable sidebar names."""
    return (username or "Sales User").replace(".", " ").replace("_", " ").title()


def _initials(name: str) -> str:
    """derives compact initials for users not present in the seed profile."""
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "SU"


def current_account(request: Request) -> SalesOfficerAccount | None:
    """returns the account stored in the current signed session."""
    return get_account(request.session.get(SESSION_USER_KEY))


def open_session(request: Request, account: SalesOfficerAccount) -> None:
    """stores the signed-in sales officer in the session."""
    request.session[SESSION_USER_KEY] = account.user_id


def clear_session(request: Request) -> None:
    """clears the signed-in sales officer session."""
    request.session.pop(SESSION_USER_KEY, None)


def require_sales_officer(request: Request) -> SalesOfficerAccount:
    """requires a signed-in sales officer for reviewer actions."""
    account = current_account(request)
    if account:
        return account
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sales officer login required.",
    )
