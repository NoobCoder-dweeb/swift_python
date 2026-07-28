import httpx

from app.repositories.state_repository import MemoryStateRepository
from app.main import app
from app.services import auth_service
from app.services.auth_service import hash_password, normalize_level, verify_password


def test_memory_user_repository_stores_hashed_login_users():
    """user rows are stored with bcrypt hashes and case-insensitive lookup."""
    repository = MemoryStateRepository()
    stored = repository.upsert_user(
        {
            "username": "Casey",
            "email": "casey@example.com",
            "hashed_password": hash_password("safe-password"),
            "level": "sales officer",
        }
    )

    assert stored["username"] == "casey"
    assert stored["hashed_password"] != "safe-password"
    assert verify_password("safe-password", stored["hashed_password"])

    loaded = repository.get_user_by_username("CASEY")
    assert loaded is not None
    assert loaded["email"] == "casey@example.com"
    assert loaded["level"] == "sales officer"


def test_legacy_sales_person_role_normalizes_to_sales_officer():
    """old stored role names should keep working after the role rename."""
    assert normalize_level("sales person") == "sales officer"


async def test_login_queries_database_user_rows(monkeypatch):
    """login authenticates against repository users instead of hard-coded accounts."""
    repository = MemoryStateRepository()
    repository.upsert_user(
        {
            "username": "db.sales",
            "email": "db.sales@example.com",
            "hashed_password": hash_password("database-password"),
            "level": "sales officer",
        }
    )
    monkeypatch.setattr(auth_service, "get_state_repository", lambda: repository)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        login = await client.post(
            "/login",
            data={
                "username": "db.sales",
                "password": "database-password",
                "next": "/pending",
            },
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/pending"

        pending = await client.get("/pending")
        assert pending.status_code == 200
        assert "Db Sales" in pending.text


async def test_sales_officer_login_and_logout_gate_ui_pages():
    """reviewer UI pages require a signed-in sales officer session."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        anonymous = await client.get("/pending")
        assert anonymous.status_code == 303
        assert anonymous.headers["location"].startswith("/login?next=")

        login = await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/pending"},
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/pending"

        signed_in = await client.get("/pending")
        assert signed_in.status_code == 200
        assert "John Doe" in signed_in.text

        logout = await client.post("/logout")
        assert logout.status_code == 303
        assert logout.headers["location"] == "/login"

        signed_out = await client.get("/pending")
        assert signed_out.status_code == 303


async def test_regular_sales_users_cannot_view_manager_pages():
    """regular sales accounts only see dashboard and pending drafts."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        login = await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/audit"},
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/dashboard"

        dashboard = await client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "Dashboard" in dashboard.text
        assert "Pending Drafts" in dashboard.text
        assert "Audit Log" not in dashboard.text
        assert "Audit Logs" not in dashboard.text

        pending = await client.get("/pending")
        assert pending.status_code == 200

        audit = await client.get("/audit")
        assert audit.status_code == 403


async def test_admin_and_sales_manager_can_view_all_pages():
    """admins and sales managers keep access to the audit page."""
    for username in ("manager", "admin"):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            login = await client.post(
                "/login",
                data={"username": username, "password": "swift123", "next": "/audit"},
            )
            assert login.status_code == 303
            assert login.headers["location"] == "/audit"

            audit = await client.get("/audit")
            assert audit.status_code == 200
            assert "Audit Log" in audit.text


async def test_login_page_uses_template_card_and_stacked_controls():
    """login should be a public card page without private app navigation."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/login")

    assert response.status_code == 200
    assert 'class="card login-card"' in response.text
    assert 'class="login-form"' in response.text
    assert 'class="login-body"' in response.text
    assert 'class="page-header"' not in response.text
    assert 'class="sidebar"' not in response.text
    assert 'class="app-footer"' not in response.text
    assert "Dashboard" not in response.text
    assert "Pending Drafts" not in response.text
    assert "Audit Log" not in response.text
    assert "Audit Logs" not in response.text
    assert "John Doe" not in response.text
    assert "Aisha Sales" not in response.text
    assert "Mira Tan" not in response.text
    assert 'value="john"' not in response.text
    assert "swift123" not in response.text
    assert response.text.index('name="username"') < response.text.index(
        'name="password"'
    )
    assert response.text.index('name="password"') < response.text.index(
        'class="btn btn-primary login-submit"'
    )
