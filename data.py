from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any


@dataclass
class User:
    initials: str
    name: str
    email: str
    role: str
    department: str
    status: str
    joined: str
    accent_bg: str
    accent_fg: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Record:
    record_id: str
    title: str
    category: str
    priority: str
    status: str
    assignee_name: str
    updated: str
    created: str
    due_date: str
    description: str

    @property
    def status_label(self) -> str:
        return self.status.replace('-', ' ').title()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload['status_label'] = self.status_label
        return payload


USERS: list[User] = [
    User('JD', 'Jane Doe', 'jane.doe@company.com', 'Administrator', 'Operations', 'Online', 'Jan 2024', 'var(--primary-light)', 'var(--primary)'),
    User('AC', 'Alex Chen', 'alex.chen@company.com', 'Editor', 'Engineering', 'Online', 'Feb 2024', 'hsl(200, 80%, 92%)', 'hsl(200, 80%, 42%)'),
    User('SM', 'Sarah Miller', 'sarah.miller@company.com', 'Editor', 'Marketing', 'Away', 'May 2024', 'hsl(145, 63%, 90%)', 'hsl(145, 63%, 42%)'),
    User('LP', 'Lisa Park', 'lisa.park@company.com', 'Viewer', 'Finance', 'Offline', 'Aug 2024', 'hsl(45, 93%, 92%)', 'hsl(45, 93%, 38%)'),
    User('MK', 'Mike Kim', 'mike.kim@company.com', 'Administrator', 'Platform', 'Online', 'Oct 2025', 'hsl(348, 83%, 94%)', 'hsl(348, 83%, 47%)'),
    User('TC', 'Thomas Clinton', 'thomas.clinton@company.com', 'Viewer', 'Frontend', 'Online', 'Dec 2025', 'hsl(280, 60%, 90%)', 'hsl(280, 60%, 50%)'),
]

RECORDS: list[Record] = [
    Record('REC-1084', 'API Gateway Refactor', 'Engineering', 'Critical', 'active', 'Alex Chen', 'Today, 9:15 AM', 'April 10, 2026', 'June 30, 2026', 'Refactor the existing API Gateway to improve performance, scalability, and maintainability.'),
    Record('REC-1083', 'Customer Onboarding Flow', 'Design', 'High', 'pending', 'Sarah Miller', 'Today, 8:40 AM', 'April 8, 2026', 'May 14, 2026', 'Refresh the onboarding journey to reduce friction across the first-run experience.'),
    Record('REC-1082', 'Q2 Campaign Metrics Audit', 'Marketing', 'Medium', 'in-progress', 'Lisa Park', 'Yesterday', 'April 7, 2026', 'May 5, 2026', 'Audit campaign tracking and attribution events ahead of the Q2 review.'),
    Record('REC-1081', 'Payroll Exception Review', 'Finance', 'High', 'active', 'Jane Doe', 'Apr 9, 2026', 'April 5, 2026', 'April 28, 2026', 'Investigate payroll exceptions and reconcile missing approvals.'),
    Record('REC-1080', 'Team Access Cleanup', 'Operations', 'Low', 'archived', 'Mike Kim', 'Apr 6, 2026', 'March 28, 2026', 'April 12, 2026', 'Remove stale access, update group memberships, and document exceptions.'),
]

EVENTS: dict[str, list[dict[str, Any]]] = {
    '2026-04-10': [
        {'title': 'Quarterly Review', 'time': '2:00 PM', 'hour': 14, 'type': 'danger', 'meta': 'Executive'},
        {'title': 'Sprint Retro', 'time': '4:00 PM', 'hour': 16, 'type': 'warning', 'meta': 'Engineering'},
    ],
    '2026-04-14': [
        {'title': 'Client Presentation', 'time': '10:00 AM', 'hour': 10, 'type': 'danger', 'meta': 'Sales'},
    ],
    '2026-04-15': [
        {'title': 'UX Workshop', 'time': '9:00 AM', 'hour': 9, 'type': 'secondary', 'meta': 'Design'},
        {'title': 'Database Migration', 'time': '3:00 PM', 'hour': 15, 'type': 'primary', 'meta': 'Engineering'},
    ],
}

SETTINGS: dict[str, Any] = {
    'theme': 'light',
    'accent_hue': 250,
    'compact_sidebar': False,
    'dense_tables': False,
    'animations': True,
}


ANALYTICS: dict[str, Any] = {
    'total_views': 24589,
    'conversion_rate': 3.24,
    'avg_session': '4m 32s',
    'bounce_rate': 32.1,
    'traffic_sources': {'Direct': 38, 'Organic': 24, 'Referral': 18, 'Social': 20},
}


def next_record_id() -> str:
    highest = max(int(r.record_id.split('-')[1]) for r in RECORDS)
    return f'REC-{highest + 1}'


def add_record(payload: dict[str, str]) -> Record:
    record = Record(
        record_id=next_record_id(),
        title=payload.get('title') or 'Untitled Record',
        category=(payload.get('category') or 'Operations').title(),
        priority=(payload.get('priority') or 'Medium').title(),
        status='pending',
        assignee_name=_resolve_assignee(payload.get('assignee')),
        updated='Just now',
        created=date.today().strftime('%B %d, %Y'),
        due_date=payload.get('dueDate') or 'TBD',
        description=payload.get('description') or 'No description supplied.',
    )
    RECORDS.insert(0, record)
    return record


def add_user_invite(email: str, role: str) -> dict[str, str]:
    initials = ''.join(part[0] for part in email.split('@')[0].replace('.', ' ').split()[:2]).upper() or 'NU'
    user = User(initials, email.split('@')[0].replace('.', ' ').title(), email, role.title(), 'Invited', 'Pending Invite', datetime.now().strftime('%b %Y'), 'var(--primary-light)', 'var(--primary)')
    USERS.append(user)
    return user.to_dict()


def _resolve_assignee(code: str | None) -> str:
    mapping = {
        'ac': 'Alex Chen',
        'sm': 'Sarah Miller',
        'lp': 'Lisa Park',
        'mk': 'Mike Kim',
        'tc': 'Thomas Clinton',
        'jd': 'Jane Doe',
    }
    return mapping.get((code or '').lower(), 'Jane Doe')


# Draft and audit models for email processing (in-memory)
@dataclass
class Draft:
    draft_id: str
    sender: str
    subject: str
    body: str
    status: str
    created: str
    updated: str

    def to_dict(self):
        return asdict(self)

DRAFTS: list[Draft] = []

AUDITS: list[dict[str, Any]] = []


def next_draft_id() -> str:
    highest = max([int(d.draft_id.split('-')[1]) for d in DRAFTS], default=100)
    return f'DFT-{highest + 1}'


def add_draft_from_email(email_payload: dict[str,str]) -> Draft:
    draft = Draft(
        draft_id = next_draft_id(),
        sender = email_payload.get('from', 'noreply@example.com'),
        subject = email_payload.get('subject','No subject'),
        body = email_payload.get('body',''),
        status = 'pending',
        created = datetime.now().isoformat(),
        updated = datetime.now().isoformat()
    )
    DRAFTS.insert(0, draft)
    return draft


def get_drafts() -> list[Draft]:
    return DRAFTS


def get_audits() -> list[dict]:
    return AUDITS


def approve_draft(draft_id: str, approver: str) -> dict | None:
    draft = next((d for d in DRAFTS if d.draft_id == draft_id), None)
    if not draft:
        return None
    draft.status = 'approved'
    draft.updated = datetime.now().isoformat()
    audit = {
        'draft_id': draft.draft_id,
        'subject': draft.subject,
        'approver': approver,
        'action': 'approved',
        'timestamp': datetime.now().isoformat(),
        'emailed_to': 'simulated-user@example.com',
        'sent': True,
        'content': f"Approved draft sent to simulated user for draft {draft.draft_id}"
    }
    AUDITS.insert(0, audit)
    return audit


# Background email listener (simulated with hardcoded emails)
import threading
import time


def start_email_listener(poll_interval: int = 15):
    sample_emails = [
        {'from': 'alice@example.com', 'subject': 'Product pricing request', 'body': 'Can I get pricing for product X?'},
        {'from': 'bob@example.com', 'subject': 'Demo request', 'body': 'We would like a demo next week.'},
    ]
    def run():
        idx = 0
        while True:
            payload = sample_emails[idx % len(sample_emails)]
            add_draft_from_email(payload)
            idx += 1
            time.sleep(poll_interval)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread

