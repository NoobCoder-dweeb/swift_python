import httpx

from app.crews.agent_config import (
    get_agent_definition,
    reset_agent_prompt_config_cache,
)
from app.main import app
from app.repositories.state_repository import get_state_repository


async def test_settings_page_saves_user_theme():
    """theme choices should be stored per signed-in user and rendered on reload."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/settings"},
        )

        save = await client.post("/api/settings/theme", json={"theme": "dark"})
        assert save.status_code == 200
        assert save.json()["theme"] == "dark"

        page = await client.get("/settings")

    assert page.status_code == 200
    assert '<html lang="en" data-theme="dark">' in page.text
    assert "AI Agent And Task Prompts" in page.text


async def test_regular_sales_user_cannot_save_prompt_settings():
    """shared agent prompts should require manager/admin access."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        await client.post(
            "/login",
            data={"username": "john", "password": "swift123", "next": "/settings"},
        )
        response = await client.post(
            "/api/settings/prompts",
            json={"groups": {}},
        )

    assert response.status_code == 403


async def test_manager_can_save_and_reset_prompt_overrides():
    """prompt edits should affect runtime agent config until reset."""
    repository = get_state_repository()
    repository.delete_setting("agent_prompt_overrides")
    reset_agent_prompt_config_cache()
    default_role = get_agent_definition("sales_processing").role
    updated_role = "Custom Sales Processing Agent"

    groups = {
        "processing": {
            "role": updated_role,
            "goal": "Extract safe sales details from customer messages.",
            "backstory": "You are precise and careful.",
            "task_description": "Analyse sender $sender, subject $subject, and body $body.",
            "task_expected_output": "Strict JSON only.",
        },
        "drafting": {
            "role": "Custom Email Drafting Agent",
            "goal": "Draft grounded customer responses.",
            "backstory": "You write concise replies.",
            "task_description": "Draft from $inquiry_json and $product_context_json.",
            "task_expected_output": "A customer email.",
        },
        "supervision": {
            "role": "Custom Supervisor",
            "goal": "Validate generated sales replies.",
            "backstory": "You check safety and correctness.",
            "task_description": "Validate $validation_payload.",
            "task_expected_output": "Strict validation JSON.",
        },
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        await client.post(
            "/login",
            data={"username": "manager", "password": "swift123", "next": "/settings"},
        )
        save = await client.post("/api/settings/prompts", json={"groups": groups})
        assert save.status_code == 200

        reset_agent_prompt_config_cache()
        assert get_agent_definition("sales_processing").role == updated_role

        reset = await client.post("/api/settings/prompts/reset")
        assert reset.status_code == 200

    reset_agent_prompt_config_cache()
    assert get_agent_definition("sales_processing").role == default_role
