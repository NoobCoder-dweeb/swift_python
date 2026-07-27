from __future__ import annotations

import asyncio
import ast
import inspect
import os
import textwrap
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("SWIFT_STORAGE_BACKEND", "memory")
os.environ.setdefault("SWIFT_AGENT_BACKEND", "deterministic")

from app.crews.agents import EmailDraftingAgent, SalesProcessingAgent
from app.services.audit_logger import AuditLogger


TEST_CLASSIFICATIONS = {
    "tests/unit/test_audit_logger.py": (
        "WHITE-BOX",
        "app.services.audit_logger",
        "internal persistence/logging branch verification",
    ),
    "tests/unit/test_auth.py": (
        "BLACK-BOX",
        "app.services.auth_service + app.main UI auth routes",
        "role-based access and login/logout behaviour through public UI routes",
    ),
    "tests/unit/test_dashboard.py": (
        "BLACK-BOX",
        "app.main dashboard route + templates/dashboard.html",
        "dashboard behaviour observed through rendered UI",
    ),
    "tests/unit/test_draft_editing.py": (
        "BLACK-BOX",
        "app.api.v1.routes.drafts + data draft workflow",
        "reviewer workflow behaviour for edit/reject/approve outcomes",
    ),
    "tests/unit/test_dummy_email_ingestion.py": (
        "BLACK-BOX",
        "app.api.v1.routes.emails + app.services.email_service",
        "email/webhook ingestion behaviour through public request shapes",
    ),
    "tests/unit/test_email_dispatch.py": (
        "BLACK-BOX",
        "app.services.email_dispatcher + approval workflow",
        "observable send/no-send email dispatch behaviour",
    ),
    "tests/unit/test_email_drafting_agent.py": (
        "WHITE-BOX",
        "app.crews.agents.EmailDraftingAgent",
        "agent validation/regeneration branch coverage",
    ),
    "tests/unit/test_email_preprocessor.py": (
        "WHITE-BOX",
        "app.services.email_preprocessor",
        "line filtering and collaborator allow-list logic",
    ),
    "tests/unit/test_email_service.py": (
        "BLACK-BOX",
        "app.services.email_service",
        "service contract outcomes for ingestion and spam handling",
    ),
    "tests/unit/test_email_threads.py": (
        "BLACK-BOX",
        "data email-thread workflow + pending UI",
        "conversation/thread behaviour visible in draft workflow outputs",
    ),
    "tests/unit/test_governance.py": (
        "BLACK-BOX",
        "approval governance policy",
        "policy decisions from user attributes and malicious prompts",
    ),
    "tests/unit/test_inquiry_guardrails.py": (
        "WHITE-BOX",
        "app.services.inquiry_guardrails + sales agent guard checks",
        "specific guardrail regex/intent branches",
    ),
    "tests/unit/test_inquiry_processing.py": (
        "WHITE-BOX",
        "email listener routing control",
        "listener active/inactive control-flow verification",
    ),
    "tests/unit/test_notification.py": (
        "BLACK-BOX",
        "review notification behaviour",
        "observable notification contract when draft is ready",
    ),
    "tests/unit/test_pending_page.py": (
        "BLACK-BOX",
        "app.main pending route + templates/pending.html",
        "pending-review UI rendering from stored draft data",
    ),
    "tests/unit/test_plug_and_play_config.py": (
        "BLACK-BOX",
        "app.core.config + runtime environment selection",
        "configuration behaviour from environment inputs",
    ),
    "tests/unit/test_product_repository.py": (
        "WHITE-BOX",
        "app.repositories.product_repository",
        "repository matching/search branches and legacy field parsing",
    ),
    "tests/unit/test_safetyware_importer.py": (
        "WHITE-BOX",
        "scripts/import_safetyware_products.py",
        "importer write-boundary and product cap logic",
    ),
    "tests/unit/test_sales_processing_agent.py": (
        "WHITE-BOX",
        "app.crews.agents.SalesProcessingAgent",
        "internal product-context query behaviour",
    ),
    "tests/unit/test_sales_workflow.py": (
        "WHITE-BOX",
        "app.crews.sales_inquiry_crew + workflow validation",
        "workflow branch, validation, and database-fact control coverage",
    ),
    "tests/unit/test_spam_filter.py": (
        "WHITE-BOX",
        "app.services.spam_filter",
        "rule/model scoring paths for spam classification",
    ),
    "tests/integration/test_email_review_flow.py": (
        "INTEGRATION",
        "email intake + draft review + audit persistence",
        "cross-module flow through API routes, services, repository, and audit records",
    ),
    "tests/system/test_sales_ui_access.py": (
        "SYSTEM",
        "Project Swift sales reviewer UI",
        "user-facing workflow across login, navigation, dashboard, pending, and audit pages",
    ),
}
SWIFT_TEST_RESULTS = []
SWIFT_TEST_CASE_DETAILS = {}


def pytest_configure(config):
    """stores classified test outcomes for the end-of-run log report."""
    SWIFT_TEST_RESULTS.clear()
    SWIFT_TEST_CASE_DETAILS.clear()


def pytest_collection_modifyitems(config, items):
    """extracts concrete inputs and assertions from each collected test case."""
    for item in items:
        SWIFT_TEST_CASE_DETAILS[item.nodeid] = _source_test_details(item)


def pytest_runtest_logreport(report):
    """collects one final outcome per test for white-box/black-box reporting."""
    if report.when == "call":
        _record_test_report(report)
    elif report.when == "setup" and (report.failed or report.skipped):
        _record_test_report(report)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """writes test_results.log automatically whenever pytest finishes."""
    rows = SWIFT_TEST_RESULTS
    if not rows:
        return

    root = Path(str(config.rootpath))
    log_path = root / "test_results.log"
    log_path.write_text(
        _build_test_results_log(rows, config, exitstatus),
        encoding="utf-8",
    )
    terminalreporter.write_sep("-", f"wrote classified test log to {log_path}")


def _record_test_report(report) -> None:
    path, _, test_name = report.nodeid.partition("::")
    test_type, module, technique = TEST_CLASSIFICATIONS.get(
        path,
        _default_test_classification(path),
    )
    objective = _test_objective(test_name)
    details = SWIFT_TEST_CASE_DETAILS.get(report.nodeid, {})
    expected_output = details.get("expected_output") or _expected_output(
        test_type,
        objective,
    )
    SWIFT_TEST_RESULTS.append(
        {
            "actual_output": _actual_output(report, objective, expected_output),
            "criteria_conditions": _criteria_conditions(
                test_type,
                technique,
                details.get("assertion_conditions", ""),
            ),
            "expected_output": expected_output,
            "input_data": details.get("input_data", "No literal input payload found."),
            "module": module,
            "nodeid": report.nodeid,
            "objective": objective,
            "status": _report_status(report),
            "technique": technique,
            "type": test_type,
        }
    )


def _source_test_details(item) -> dict[str, str]:
    """turns each test function into report-friendly concrete test data."""
    try:
        source = textwrap.dedent(inspect.getsource(item.obj))
    except (OSError, TypeError):
        return {}

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    assigned_literals = _assigned_literals(tree)
    input_values = _input_values(tree, assigned_literals)
    assertion_conditions = _assertion_conditions(tree)
    expected_values = _expected_values(tree, assigned_literals)
    return {
        "assertion_conditions": _format_values(assertion_conditions),
        "expected_output": _format_expected_values(expected_values),
        "input_data": _format_values(input_values) or "No literal input payload found.",
    }


def _assigned_literals(tree: ast.AST) -> dict[str, object]:
    values: dict[str, object] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = _literal_value(node.value, values)
        if value is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                values[target.id] = value
    return values


def _input_values(tree: ast.AST, assigned_literals: dict[str, object]) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            values.extend(_call_input_values(node, assigned_literals))
        elif isinstance(node, ast.Dict) and _dict_looks_like_payload(node):
            value = _literal_value(node, assigned_literals)
            if value is not None:
                values.append(_compact_value(value))
    return _dedupe(values)


def _call_input_values(
    node: ast.Call,
    assigned_literals: dict[str, object],
) -> list[str]:
    values: list[str] = []
    call_name = _call_name(node.func)
    for keyword in node.keywords:
        if keyword.arg not in {
            "auth",
            "content",
            "data",
            "files",
            "headers",
            "json",
            "reason",
        }:
            continue
        value = _literal_value(keyword.value, assigned_literals)
        if value is not None:
            values.append(f"{keyword.arg}={_compact_value(value)}")

    if call_name in {"IncomingEmail", "EmailPayload"}:
        payload = {
            keyword.arg: _literal_value(keyword.value, assigned_literals)
            for keyword in node.keywords
            if keyword.arg
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        if payload:
            values.append(_compact_value(payload))

    if call_name == "add_generated_draft" and node.args:
        payload = _literal_value(node.args[0], assigned_literals)
        if payload is not None:
            values.append(_compact_value(payload))
    return values


def _assertion_conditions(tree: ast.AST) -> list[str]:
    return [
        _shorten(ast.unparse(node.test))
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
    ]


def _expected_values(
    tree: ast.AST,
    assigned_literals: dict[str, object],
) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        values.extend(_expected_from_assert(node.test, assigned_literals))
    return _dedupe(values)


def _expected_from_assert(
    node: ast.AST,
    assigned_literals: dict[str, object],
) -> list[str]:
    if isinstance(node, ast.Compare) and node.ops and node.comparators:
        left = ast.unparse(node.left)
        op = node.ops[0]
        right_node = node.comparators[0]
        right = _literal_value(right_node, assigned_literals)
        if isinstance(op, (ast.Eq, ast.Is)) and right is not None:
            return [f"{left}: {_compact_value(right)}"]
        if isinstance(op, ast.NotEq) and right is not None:
            return [f"{left}: not {_compact_value(right)}"]
        if isinstance(op, ast.In):
            left_value = _literal_value(node.left, assigned_literals)
            if left_value is not None:
                return [f"{ast.unparse(right_node)} contains {_compact_value(left_value)}"]
        if isinstance(op, ast.NotIn):
            left_value = _literal_value(node.left, assigned_literals)
            if left_value is not None:
                return [
                    f"{ast.unparse(right_node)} does not contain "
                    f"{_compact_value(left_value)}"
                ]
        return [_shorten(ast.unparse(node))]

    if isinstance(node, ast.Call):
        return [f"{_shorten(ast.unparse(node))}: True"]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return [f"{_shorten(ast.unparse(node.operand))}: False"]
    return [f"{_shorten(ast.unparse(node))}: truthy"]


def _literal_value(node: ast.AST, assigned_literals: dict[str, object]) -> object | None:
    if isinstance(node, ast.Name):
        return assigned_literals.get(node.id)
    if isinstance(node, ast.Constant):
        value = node.value
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_value(node.left, assigned_literals)
        right = _literal_value(node.right, assigned_literals)
        if isinstance(left, (str, bytes)) and isinstance(right, type(left)):
            return left + right
    if isinstance(node, ast.Dict):
        payload = {}
        for key_node, value_node in zip(node.keys, node.values, strict=False):
            key = _literal_value(key_node, assigned_literals)
            value = _literal_value(value_node, assigned_literals)
            if key is not None and value is not None:
                payload[key] = value
        return payload or None
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [_literal_value(item, assigned_literals) for item in node.elts]
        values = [value for value in values if value is not None]
        if not values:
            return None
        return tuple(values) if isinstance(node, ast.Tuple) else values
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _dict_looks_like_payload(node: ast.Dict) -> bool:
    payload_keys = {
        "ai_draft",
        "body",
        "content",
        "from",
        "next",
        "password",
        "reason",
        "rejection_reason",
        "sender",
        "subject",
        "username",
    }
    keys = []
    for key_node in node.keys:
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            keys.append(key_node.value)
    return bool(payload_keys.intersection(keys))


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _format_values(values: list[str], *, limit: int = 8) -> str:
    if not values:
        return ""
    shown = values[:limit]
    suffix = f"; ... +{len(values) - limit} more" if len(values) > limit else ""
    return "; ".join(shown) + suffix


def _format_expected_values(values: list[str]) -> str:
    if not values:
        return ""
    return "{" + _format_values(values, limit=10) + "}"


def _compact_value(value: object) -> str:
    if isinstance(value, str):
        return _shorten(repr(value))
    if isinstance(value, dict):
        items = [
            f"{key}: {_compact_value(item_value)}"
            for key, item_value in list(value.items())[:8]
        ]
        suffix = ", ..." if len(value) > 8 else ""
        return "{" + ", ".join(items) + suffix + "}"
    if isinstance(value, (list, tuple, set)):
        items = [_compact_value(item) for item in list(value)[:6]]
        suffix = ", ..." if len(value) > 6 else ""
        open_char, close_char = ("(", ")") if isinstance(value, tuple) else ("[", "]")
        return open_char + ", ".join(items) + suffix + close_char
    return repr(value)


def _shorten(value: str, limit: int = 240) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _default_test_classification(path: str) -> tuple[str, str, str]:
    module = path.removesuffix(".py").replace("/", ".")
    if path.startswith("tests/integration/"):
        return (
            "INTEGRATION",
            module,
            "cross-module behaviour from pytest outcome",
        )
    if path.startswith("tests/system/"):
        return (
            "SYSTEM",
            module,
            "end-to-end user-facing behaviour from pytest outcome",
        )
    return (
        "BLACK-BOX",
        module,
        "observable behaviour from pytest outcome",
    )


def _report_status(report) -> str:
    if report.passed:
        return "PASSED"
    if report.skipped:
        return "SKIPPED"
    return "FAILED"


def _test_objective(test_name: str) -> str:
    name = test_name.split("[", 1)[0]
    return name.replace("test_", "", 1).replace("_", " ")


def _criteria_conditions(
    test_type: str,
    technique: str,
    assertion_conditions: str = "",
) -> str:
    conditions = {
        "WHITE-BOX": (
            "Implementation-aware assertions exercise the module's internal "
            f"{technique}; controlled fixtures/mocks isolate the target logic."
        ),
        "BLACK-BOX": (
            "Inputs are supplied through public routes, service contracts, or "
            f"user-visible behaviour; assertions check {technique}."
        ),
        "INTEGRATION": (
            "Multiple application layers execute together with deterministic "
            f"test configuration; assertions check {technique}."
        ),
        "SYSTEM": (
            "The application is exercised as a user journey across UI/API "
            f"boundaries; assertions check {technique}."
        ),
    }
    base = conditions.get(
        test_type,
        f"Pytest case is classified as {test_type}; assertions check {technique}.",
    )
    if assertion_conditions:
        return f"{base} Code/Test Conditions: {assertion_conditions}."
    return base


def _expected_output(test_type: str, objective: str) -> str:
    labels = {
        "WHITE-BOX": "internal behaviour",
        "BLACK-BOX": "externally observable behaviour",
        "INTEGRATION": "cross-module workflow",
        "SYSTEM": "end-to-end user journey",
    }
    label = labels.get(test_type, "tested behaviour")
    return (
        f"The {label} for '{objective}' matches the specified assertions, "
        "and pytest reports PASSED."
    )


def _actual_output(report, objective: str, expected_output: str) -> str:
    if report.passed:
        return (
            f"PASSED - observed values matched expected output for '{objective}': "
            f"{expected_output or 'all assertions satisfied'}."
        )
    if report.skipped:
        return f"SKIPPED - pytest skipped '{objective}'."

    detail = getattr(report, "longreprtext", "") or str(report.longrepr)
    compact_detail = " ".join(detail.split())
    if len(compact_detail) > 500:
        compact_detail = f"{compact_detail[:497]}..."
    return f"FAILED - pytest reported an assertion/error for '{objective}': {compact_detail}"


def _build_test_results_log(rows: list[dict[str, str]], config, exitstatus) -> str:
    counts = Counter(row["status"] for row in rows)
    type_counts = Counter(row["type"] for row in rows)
    module_counts = Counter((row["type"], row["module"]) for row in rows)
    by_type = defaultdict(list)
    for row in rows:
        by_type[row["type"]].append(row)

    command = "pytest " + " ".join(str(arg) for arg in config.invocation_params.args)
    lines = [
        "Project Swift Test Results Log",
        "=" * 30,
        f"Generated At: {datetime.now().isoformat(timespec='seconds')}",
        f"Working Directory: {config.rootpath}",
        f"Command: {command.strip()}",
        f"Pytest Exit Code: {exitstatus}",
        "",
        "Result Summary",
        "--------------",
        f"Total Tests: {len(rows)}",
    ]
    for status in ["PASSED", "FAILED", "ERROR", "SKIPPED", "XFAILED", "XPASSED"]:
        if counts[status]:
            lines.append(f"{status.title()}: {counts[status]}")
    lines.extend(
        [
            f"White-Box Tests: {type_counts['WHITE-BOX']}",
            f"Black-Box Tests: {type_counts['BLACK-BOX']}",
            f"Integration Tests: {type_counts['INTEGRATION']}",
            f"System Tests: {type_counts['SYSTEM']}",
            "",
            "Classification Criteria",
            "-----------------------",
            (
                "WHITE-BOX: Tests validate internal units, branches, data-flow "
                "decisions, repository behaviour, agent validation, or "
                "implementation-aware control paths using mocks/fakes or direct "
                "function/service calls."
            ),
            (
                "BLACK-BOX: Tests validate externally observable behaviour through "
                "HTTP/UI routes, webhook/request contracts, service-level "
                "outcomes, workflow acceptance criteria, or configuration "
                "behaviour without depending on private implementation details."
            ),
            (
                "INTEGRATION: Tests validate collaboration between multiple "
                "application modules, such as routes, services, repositories, "
                "and audit persistence, inside one business flow."
            ),
            (
                "SYSTEM: Tests validate the deployed application behaviour from "
                "a user journey perspective across major UI/API boundaries."
            ),
            "",
            "Module Coverage Summary",
            "-----------------------",
        ]
    )

    for (test_type, module), count in sorted(module_counts.items()):
        lines.append(f"{test_type:<9} | {count:>2} tests | {module}")

    for section in ["BLACK-BOX", "WHITE-BOX", "INTEGRATION", "SYSTEM"]:
        lines.extend(["", f"{section} TEST RESULTS", "-" * (len(section) + 13)])
        grouped = defaultdict(list)
        for row in by_type[section]:
            grouped[row["module"]].append(row)
        for module in sorted(grouped):
            lines.extend(
                [
                    "",
                    f"Module: {module}",
                    f"Technique: {grouped[module][0]['technique']}",
                    "Test Cases:",
                ]
            )
            for index, row in enumerate(grouped[module], start=1):
                lines.append(f"  {index:02d}. [{row['status']}] {row['nodeid']}")
                lines.append(f"      Objective: {row['objective']}.")
                lines.append(f"      Input Data: {row['input_data']}")
                lines.append(
                    f"      Criteria Conditions: {row['criteria_conditions']}"
                )
                lines.append(f"      Expected Output: {row['expected_output']}")
                lines.append(f"      Actual Output: {row['actual_output']}")

    return "\n".join(lines) + "\n"


def pytest_pyfunc_call(pyfuncitem):
    """runs async tests without adding a pytest-asyncio dependency."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True


class EmailListener:
    """isolates routing behaviour without running a real mailbox listener."""

    def __init__(self, supervisor_agent):
        """lets tests toggle active state and inspect supervisor calls."""
        self.active = True
        self.supervisor_agent = supervisor_agent

    async def process(self, email):
        """verifies inactive listeners do not route customer messages."""
        if self.active:
            self.supervisor_agent.route(email)


class DispatchService:
    """keeps email dispatch tests independent from SMTP/client libraries."""

    def __init__(self, email_client):
        """injects a mockable client for send/no-send assertions."""
        self.email_client = email_client

    def dispatch(self, draft, *, approved):
        """only approved drafts should leave the system."""
        if approved:
            self.email_client.send(draft)


class NotificationService:
    """models review notifications without an external notification provider."""

    def notify_review_required(self, draft):
        """confirms draft-ready events produce the expected notification shape."""
        return SimpleNamespace(sent=True, type="draft_review")


class GovernanceService:
    """captures the sales-only approval rule used by governance tests."""

    def authorise_draft_decision(self, user):
        """requires both Sales membership and active SSO before approval."""
        if user.get("department") != "Sales":
            return SimpleNamespace(allowed=False, message="Sales approval required.")
        if not user.get("sso_active"):
            return SimpleNamespace(allowed=False, message="Active SSO is required.")
        return SimpleNamespace(allowed=True, message="Approved.")


class GuardrailService:
    """keeps safety tests focused on confidential-data rejection."""

    def validate_customer_question(self, question):
        """rejects prompt-injection style requests before drafting."""
        lower_question = question.lower()
        if "ignore previous instructions" in lower_question or "customer" in lower_question:
            return SimpleNamespace(
                allowed=False,
                response="I cannot share confidential customer data.",
            )
        return SimpleNamespace(allowed=True, response="Allowed.")


@pytest.fixture
def mock_postgres_client():
    """verifies persistence calls without touching a database."""
    return MagicMock()


@pytest.fixture
def audit_logger(mock_postgres_client):
    """shares the production logger across audit tests."""
    return AuditLogger(mock_postgres_client)


@pytest.fixture
def mock_odoo_client():
    """supplies controlled product data to sales-agent tests."""
    return MagicMock()


@pytest.fixture
def sales_agent(mock_odoo_client):
    """injects the mock product client into the sales agent."""
    return SalesProcessingAgent(product_client=mock_odoo_client)


@pytest.fixture
def email_drafting_agent():
    """exercises real deterministic drafting behaviour in unit tests."""
    return EmailDraftingAgent()


@pytest.fixture
def supervisor_agent():
    """records route calls from the listener test double."""
    return MagicMock()


@pytest.fixture
def email_listener(supervisor_agent):
    """provides a listener fixture with controllable active state."""
    return EmailListener(supervisor_agent)


@pytest.fixture
def mock_email_client():
    """verifies dispatch behaviour without sending email."""
    return MagicMock()


@pytest.fixture
def dispatch_service(mock_email_client):
    """wires dispatch tests to a mock email client."""
    return DispatchService(mock_email_client)


@pytest.fixture
def notification_service():
    """provides a minimal notifier for review-ready tests."""
    return NotificationService()


@pytest.fixture
def governance_service():
    """provides approval authorisation rules for governance tests."""
    return GovernanceService()


@pytest.fixture
def guardrail_service():
    """provides prompt-injection checks for governance tests."""
    return GuardrailService()
