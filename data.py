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
import json
from pathlib import Path

@dataclass
class Draft:
    draft_id: str
    sender: str
    subject: str
    body: str
    status: str
    created: str
    updated: str
    revisions: int = 0

    @property
    def customer_inquiry(self) -> str:
        return self.body

    @property
    def ai_draft(self) -> str:
        revision_note = f"\n\nRevision note: updated draft v{self.revisions}." if self.revisions else ""
        lower_subject = self.subject.lower()
        lower_inquiry = self.customer_inquiry.lower()

        if 'pricing' in lower_subject or 'pricing' in lower_inquiry:
            return (
                "Hi,\n\n"
                "Yes, we can share pricing for Product X. The current standard pricing is "
                "$120 per unit for orders under 100 units, and $95 per unit for orders of 100 units or more. "
                "Our typical delivery timeline is 7 to 10 business days from order confirmation.\n\n"
                "If you send over your expected quantity and target delivery date, we can confirm the exact quote."
                f"{revision_note}\n\n"
                "Best regards,\n"
                "Swift Support"
            )

        if 'demo' in lower_subject or 'demo' in lower_inquiry:
            return (
                "Hi,\n\n"
                "Yes, we can arrange a demo next week. We currently have openings on Tuesday at 10:00 AM "
                "and Thursday at 2:00 PM, and the session usually runs for 30 minutes.\n\n"
                "If either slot works for you, reply with your preferred time and we will send the calendar invite."
                f"{revision_note}\n\n"
                "Best regards,\n"
                "Swift Support"
            )

        return (
            "Hi,\n\n"
            "Thanks for your inquiry. We can support this request and our current standard turnaround time is "
            "3 business days. Once you confirm the required quantity, preferred timeline, and any budget constraints, "
            "we will send the final recommendation and next steps."
            f"{revision_note}\n\n"
            "Best regards,\n"
            "Swift Support"
        )

    @property
    def created_display(self) -> str:
        return _format_human_datetime(self.created)

    @property
    def updated_display(self) -> str:
        return _format_human_datetime(self.updated)

    def to_dict(self):
        payload = asdict(self)
        payload['customer_inquiry'] = self.customer_inquiry
        payload['ai_draft'] = self.ai_draft
        payload['created_display'] = self.created_display
        payload['updated_display'] = self.updated_display
        return payload

DRAFTS: list[Draft] = []

AUDITS: list[dict[str, Any]] = []

DATA_STORE = Path(__file__).parent / 'data_store.json'


def _format_human_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return value
    return parsed.strftime('%b %d, %Y, %I:%M %p').replace(' 0', ' ')


def _draft_version_number(revisions: int) -> int:
    return revisions + 1


def _draft_version_id(draft_id: str, revisions: int) -> str:
    return f'{draft_id}-v{_draft_version_number(revisions)}'


def save_state() -> None:
    payload = {
        'drafts': [d.to_dict() for d in DRAFTS],
        'audits': AUDITS,
    }
    try:
        DATA_STORE.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def load_state() -> None:
    if not DATA_STORE.exists():
        return
    try:
        raw = DATA_STORE.read_text()
        payload = json.loads(raw)
        drafts = payload.get('drafts', [])
        audits = payload.get('audits', [])
        audits = [a for a in audits if (a.get('action') or '').lower() in {'approved', 'rejected'}]
        DRAFTS.clear()
        for d in drafts:
            # reconstruct Draft objects
            DRAFTS.append(Draft(
                draft_id=d['draft_id'],
                sender=d['sender'],
                subject=d['subject'],
                body=d['body'],
                status=d['status'],
                created=d['created'],
                updated=d['updated'],
                revisions=d.get('revisions', 0),
            ))
        AUDITS.clear()
        AUDITS.extend(audits)
    except Exception:
        # ignore corrupt file
        return


def next_draft_id() -> str:
    highest = max([int(d.draft_id.split('-')[1]) for d in DRAFTS], default=100)
    return f'DFT-{highest + 1}'


def add_draft_from_email(email_payload: dict[str,str]) -> Draft:
    # Deduplicate by exact sender+subject+body for pending drafts
    sender = email_payload.get('from', 'noreply@example.com')
    subject = email_payload.get('subject','No subject')
    body = email_payload.get('body','')

    # Normalize sender display name
    sender_name = sender.split('@')[0].replace('.', ' ').title()

    # If the incoming body is short, expand it into a more structured email-like body
    if len((body or '').strip()) < 80:
        body = (
            f"Hi,\n\n{body}\n\n"
            "Could you share a few more details about your request? Specifically:\n"
            "- What quantity do you need?\n"
            "- Desired timeline?\n"
            "- Any budget constraints?\n\n"
            f"Thanks,\n{sender_name}\n{sender}"
        )

    existing = next((d for d in DRAFTS if d.sender == sender and d.subject == subject and d.body == body and d.status == 'pending'), None)
    if existing:
        # update timestamp and return existing
        existing.updated = datetime.now().isoformat()
        save_state()
        try:
            publish_event({'type': 'draft_updated', 'payload': existing.to_dict()})
        except Exception:
            pass
        return existing

    draft = Draft(
        draft_id = next_draft_id(),
        sender = sender,
        subject = subject,
        body = body,
        status = 'pending',
        created = datetime.now().isoformat(),
        updated = datetime.now().isoformat(),
        revisions = 0,
    )
    DRAFTS.insert(0, draft)
    save_state()
    try:
        publish_event({'type': 'draft_created', 'payload': draft.to_dict()})
    except Exception:
        pass
    return draft


def get_drafts() -> list[Draft]:
    return [d for d in DRAFTS if d.status == 'pending']


def get_audits() -> list[dict]:
    enriched: list[dict] = []
    for audit in AUDITS:
        if (audit.get('action') or '').lower() not in {'approved', 'rejected'}:
            continue
        entry = dict(audit)
        entry['timestamp_display'] = _format_human_datetime(audit.get('timestamp', ''))
        enriched.append(entry)
    return enriched


def approve_draft(draft_id: str, approver: str, emailed_to: str | None = None) -> dict | None:
    draft = next((d for d in DRAFTS if d.draft_id == draft_id), None)
    if not draft:
        return None
    # If already approved, return existing approval audit (idempotent)
    existing = next((a for a in AUDITS if a.get('draft_id') == draft_id and a.get('action') == 'approved'), None)
    if existing:
        if draft in DRAFTS:
            DRAFTS.remove(draft)
        save_state()
        try:
            publish_event({'type': 'approved', 'payload': existing})
        except Exception:
            pass
        return existing

    audit = {
        'draft_id': draft.draft_id,
        'version_id': _draft_version_id(draft.draft_id, draft.revisions),
        'subject': draft.subject,
        'approver': approver,
        'action': 'approved',
        'timestamp': datetime.now().isoformat(),
        'emailed_to': emailed_to or 'simulated-user@example.com',
        'sent': True,
        'content': (
            f"Approved version {_draft_version_id(draft.draft_id, draft.revisions)} "
            f"and sent it to {emailed_to or 'simulated-user@example.com'}."
        ),
        'customer_inquiry': draft.customer_inquiry,
        'ai_draft': draft.ai_draft,
    }
    AUDITS.insert(0, audit)
    DRAFTS.remove(draft)
    save_state()
    try:
        publish_event({'type': 'approved', 'payload': audit})
    except Exception:
        pass
    return audit


def reject_and_regenerate_draft(draft_id: str, requester: str) -> dict | None:
    """
    Simulate asking the agent to regenerate a draft. Updates the draft body/subject and records a regeneration audit.
    Returns the updated draft as dict or None if not found.
    """
    draft = next((d for d in DRAFTS if d.draft_id == draft_id), None)
    if not draft:
        return None
    reviewed_version_id = _draft_version_id(draft.draft_id, draft.revisions)
    draft.revisions = getattr(draft, 'revisions', 0) + 1
    # Simulate regeneration by revising the AI reply while preserving the customer inquiry.
    draft.subject = f"{draft.subject.split(' (Regenerated')[0]} (Regenerated v{draft.revisions})"
    draft.status = 'pending'
    draft.updated = datetime.now().isoformat()
    regenerated_version_id = _draft_version_id(draft.draft_id, draft.revisions)

    rejection_audit = {
        'draft_id': draft.draft_id,
        'version_id': reviewed_version_id,
        'next_version_id': regenerated_version_id,
        'subject': draft.subject,
        'approver': requester,
        'action': 'rejected',
        'timestamp': datetime.now().isoformat(),
        'emailed_to': None,
        'sent': False,
        'content': (
            f"Rejected version {reviewed_version_id}. "
            f"A new draft was generated as {regenerated_version_id}."
        ),
        'customer_inquiry': draft.customer_inquiry,
        'ai_draft': draft.ai_draft,
    }
    AUDITS.insert(0, rejection_audit)
    save_state()
    try:
        publish_event({'type': 'regenerated', 'payload': {'draft': draft.to_dict(), 'audit': rejection_audit}})
    except Exception:
        pass
    return draft.to_dict()


# Background email listener (simulated with hardcoded emails)
import threading
import time

# Simple in-process event queue and condition for server-sent events
EVENTS_QUEUE: list[dict] = []
events_cond = threading.Condition()

def publish_event(event: dict) -> None:
    """Append an event to the queue and notify listeners (SSE)."""
    with events_cond:
        EVENTS_QUEUE.append(event)
        events_cond.notify_all()


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

# load persisted state on import
load_state()
