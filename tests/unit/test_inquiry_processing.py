import pytest


@pytest.mark.asyncio
async def test_email_listener_routes_valid_inquiry(email_listener, supervisor_agent):
    """confirms active listeners pass valid inquiries to supervision."""
    email = {
        "from": "customer@example.com",
        "subject": "Safety helmet stock",
        "body": "What is the stock availability of safety helmet?",
    }

    await email_listener.process(email)

    supervisor_agent.route.assert_called_once()


@pytest.mark.asyncio
async def test_email_listener_inactive_does_not_route(email_listener, supervisor_agent):
    """prevents paused listeners from triggering workflow actions."""
    email_listener.active = False

    await email_listener.process({"body": "helmet stock?"})

    supervisor_agent.route.assert_not_called()
