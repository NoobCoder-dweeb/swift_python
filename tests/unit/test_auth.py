import httpx

from app.main import app


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
