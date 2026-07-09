from __future__ import annotations

from dataclasses import asdict, dataclass
import secrets

from fastapi import HTTPException, Request, status


SESSION_USER_KEY = "swift_sales_officer"


@dataclass(frozen=True)
class SalesOfficerAccount:
    """represents a local sales officer account for reviewer login."""

    username: str
    password: str
    name: str
    role: str
    initials: str

    @property
    def can_view_all_pages(self) -> bool:
        """distinguishes managers/admins from regular sales reviewers."""
        return role_can_view_all_pages(self.role)

    def public_dict(self) -> dict[str, str | bool]:
        """returns fields safe for templates and session display."""
        payload = asdict(self)
        payload.pop("password", None)
        payload["can_view_all_pages"] = self.can_view_all_pages
        return payload


ACCOUNTS: tuple[SalesOfficerAccount, ...] = (
    SalesOfficerAccount("john", "swift123", "John Doe", "Sales Officer", "JD"),
    SalesOfficerAccount("aisha", "swift123", "Aisha Sales", "Sales Officer", "AS"),
    SalesOfficerAccount("mira", "swift123", "Mira Tan", "Sales Officer", "MT"),
    SalesOfficerAccount("manager", "swift123", "Sales Manager", "Sales Manager", "SM"),
    SalesOfficerAccount("admin", "swift123", "Admin User", "Admin", "AU"),
)


FULL_PAGE_ACCESS_ROLES = {"admin", "administrator", "sales manager"}


def role_can_view_all_pages(role: str) -> bool:
    """returns true for roles allowed to view every UI page."""
    return (role or "").strip().lower() in FULL_PAGE_ACCESS_ROLES


def list_accounts() -> list[dict[str, str | bool]]:
    """lists selectable local sales officer accounts."""
    return [account.public_dict() for account in ACCOUNTS]


def authenticate(username: str, password: str) -> SalesOfficerAccount | None:
    """checks local sales officer credentials."""
    normalized_username = (username or "").strip().lower()
    password = password or ""
    for account in ACCOUNTS:
        username_matches = secrets.compare_digest(account.username, normalized_username)
        password_matches = secrets.compare_digest(account.password, password)
        if username_matches and password_matches:
            return account
    return None


def get_account(username: str | None) -> SalesOfficerAccount | None:
    """finds a local account by username."""
    normalized_username = (username or "").strip().lower()
    return next(
        (account for account in ACCOUNTS if account.username == normalized_username),
        None,
    )


def current_account(request: Request) -> SalesOfficerAccount | None:
    """returns the account stored in the current signed session."""
    return get_account(request.session.get(SESSION_USER_KEY))


def open_session(request: Request, account: SalesOfficerAccount) -> None:
    """stores the signed-in sales officer in the session."""
    request.session[SESSION_USER_KEY] = account.username


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
