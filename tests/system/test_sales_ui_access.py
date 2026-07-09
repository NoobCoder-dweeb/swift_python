import httpx

from app.main import app


async def test_sales_reviewer_and_manager_ui_access_journey():
    """sales and manager users should see the correct pages across the UI."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        home_response = await client.get("/")
        assert home_response.status_code == 307
        assert home_response.headers["location"] == "/dashboard"

        anonymous_dashboard = await client.get("/dashboard")
        assert anonymous_dashboard.status_code == 303
        assert anonymous_dashboard.headers["location"].startswith("/login?next=")

        sales_login = await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/audit"},
        )
        assert sales_login.status_code == 303
        assert sales_login.headers["location"] == "/dashboard"

        sales_dashboard = await client.get("/dashboard")
        assert sales_dashboard.status_code == 200
        assert "Dashboard" in sales_dashboard.text
        assert "Pending Drafts" in sales_dashboard.text
        assert "Audit Log" not in sales_dashboard.text

        sales_pending = await client.get("/pending")
        assert sales_pending.status_code == 200
        assert "Pending Drafts" in sales_pending.text

        blocked_audit = await client.get("/audit")
        assert blocked_audit.status_code == 403

        logout = await client.post("/logout")
        assert logout.status_code == 303

        manager_login = await client.post(
            "/login",
            data={"username": "manager", "password": "swift123", "next": "/audit"},
        )
        assert manager_login.status_code == 303
        assert manager_login.headers["location"] == "/audit"

        manager_audit = await client.get("/audit")
        assert manager_audit.status_code == 200
        assert "Audit Log" in manager_audit.text

        manager_dashboard = await client.get("/dashboard")
        assert manager_dashboard.status_code == 200
        assert "Audit Log" in manager_dashboard.text
