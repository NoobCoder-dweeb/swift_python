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

    def public_dict(self) -> dict[str, str]:
        """returns fields safe for templates and session display."""
        payload = asdict(self)
        payload.pop("password", None)
        return payload


ACCOUNTS: tuple[SalesOfficerAccount, ...] = (
    SalesOfficerAccount("john", "swift123", "John Doe", "Sales Officer", "JD"),
    SalesOfficerAccount("aisha", "swift123", "Aisha Sales", "Sales Officer", "AS"),
    SalesOfficerAccount("mira", "swift123", "Mira Tan", "Sales Officer", "MT"),
)


def list_accounts() -> list[dict[str, str]]:
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
