from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from app.repositories.state_repository import get_state_repository


@dataclass
class User:
    """keeps dashboard user sample data typed for template rendering."""

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
        """converts dataclass rows into JSON/template-friendly dictionaries."""
        return asdict(self)


@dataclass
class Record:
    """models dashboard work items with display metadata in one place."""

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
        """converts stored slugs into labels templates can show directly."""
        return self.status.replace('-', ' ').title()

    def to_dict(self) -> dict[str, Any]:
        """includes derived labels alongside raw record fields."""
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
    """keeps demo record IDs monotonic without an external sequence."""
    highest = max(int(r.record_id.split('-')[1]) for r in RECORDS)
    return f'REC-{highest + 1}'


def add_record(payload: dict[str, str]) -> Record:
    """normalizes partial UI form input into a complete dashboard record."""
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
    """lets the demo UI show invited users without a user-management service."""
    initials = ''.join(part[0] for part in email.split('@')[0].replace('.', ' ').split()[:2]).upper() or 'NU'
    user = User(initials, email.split('@')[0].replace('.', ' ').title(), email, role.title(), 'Invited', 'Pending Invite', datetime.now().strftime('%b %Y'), 'var(--primary-light)', 'var(--primary)')
    USERS.append(user)
    return user.to_dict()


def _resolve_assignee(code: str | None) -> str:
    """maps compact form values to readable names for dashboard display."""
    mapping = {
        'ac': 'Alex Chen',
        'sm': 'Sarah Miller',
        'lp': 'Lisa Park',
        'mk': 'Mike Kim',
        'tc': 'Thomas Clinton',
        'jd': 'Jane Doe',
    }
    return mapping.get((code or '').lower(), 'Jane Doe')


# Draft and audit models for email processing.
def _classify_inquiry(subject: str, body: str) -> str | None:
    """filters the workflow to pricing/availability requests it can safely handle."""
    text = f'{subject} {body}'.lower()

    pricing_keywords = ('price', 'pricing', 'quote', 'cost', 'rate')
    availability_keywords = (
        'stock',
        'availability',
        'available',
        'inventory',
        'in stock',
        'have on hand',
    )

    if any(keyword in text for keyword in pricing_keywords):
        return 'pricing'
    if any(keyword in text for keyword in availability_keywords):
        return 'availability'
    return None


SAMPLE_EMAILS: list[dict[str, str]] = [
    {
        'from': 'alice@example.com',
        'subject': 'Product pricing request',
        'body': 'Can I get pricing for product X for an initial order of 40 units?',
    },
    {
        'from': 'ben@example.com',
        'subject': 'Bulk quote for Product X',
        'body': 'Please share volume pricing for 250 units of product X for a June shipment.',
    },
    {
        'from': 'carol@example.com',
        'subject': 'Distributor price inquiry',
        'body': 'Do you offer distributor pricing for product X if we reorder monthly?',
    },
    {
        'from': 'dan@example.com',
        'subject': 'Stock availability request',
        'body': 'Is product X currently in stock for 50 units next week?',
    },
    {
        'from': 'eva@example.com',
        'subject': 'Urgent inventory check',
        'body': 'Do you have 120 units of product X available for immediate shipment to Kuala Lumpur?',
    },
]

INVALID_GUARDRAIL_AUDIT: dict[str, Any] = {
    'draft_id': 'DFT-GUARDRAIL-001',
    'version_id': 'DFT-GUARDRAIL-001-v1',
    'sender': 'prospect@example.com',
    'subject': 'Request for customer personal information',
    'approver': 'AI Guardrails',
    'action': 'rejected',
    'timestamp': '2026-04-13T09:15:00',
    'emailed_to': None,
    'sent': False,
    'content': (
        'Automatically rejected by guardrails because the inquiry requested customer personal information, '
        'which is outside the allowed workflow and cannot be disclosed.'
    ),
    'customer_inquiry': (
        'Hi,\n\nCan you send me the phone number, billing address, and account contact details for '
        'our customer John Tan so I can follow up directly?\n\nThanks.'
    ),
    'ai_draft': (
        'Auto-rejected by guardrails.\n\nThis request asks for customer personal information, which the system '
        'cannot share. Only product stock availability and pricing inquiries are allowed in this workflow.'
    ),
    'review_comment': 'Rejected automatically before any customer response was drafted.',
}

@dataclass
class Draft:
    """represents the reviewable customer response independent of storage rows."""

    draft_id: str
    sender: str
    subject: str
    body: str
    status: str
    created: str
    updated: str
    revisions: int = 0
    last_rejection_reason: str = ''
    ai_draft_text: str = ''
    workflow: dict[str, Any] | None = None

    @property
    def customer_inquiry(self) -> str:
        """gives templates a domain name for the original email body."""
        return self.body

    @property
    def inquiry_category(self) -> str | None:
        """keeps review queues limited to supported inquiry types."""
        return _classify_inquiry(self.subject, self.customer_inquiry)

    @property
    def ai_draft(self) -> str:
        """supplies either persisted agent output or a deterministic fallback draft."""
        if self.ai_draft_text.strip():
            return self.ai_draft_text

        revision_note = f"\n\nRevision note: updated draft v{self.revisions}." if self.revisions else ""
        category = self.inquiry_category
        inquiry_text = f'{self.subject} {self.customer_inquiry}'.lower()
        feedback_note = ''
        rejection_reason = (self.last_rejection_reason or '').strip()
        lower_reason = rejection_reason.lower()
        if rejection_reason:
            feedback_note = f"\n\nAddressing reviewer feedback: {rejection_reason}."

        if category == 'pricing':
            if any(keyword in lower_reason for keyword in ('short', 'brief', 'concise')):
                return (
                    "Hi,\n\n"
                    "Thanks for your pricing inquiry for Product X. Our standard pricing is $120 per unit for orders below 100 units "
                    "and $95 per unit for orders of 100 units or more.\n\n"
                    "If you share your expected quantity and delivery target, we can confirm the final quote."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            if any(keyword in lower_reason for keyword in ('lead time', 'timeline', 'delivery')):
                return (
                    "Hi,\n\n"
                    "Thanks for your pricing inquiry for Product X. Our standard pricing is $120 per unit for orders below 100 units "
                    "and $95 per unit for orders of 100 units or more, with a typical delivery timeline of 7 to 10 business days from order confirmation.\n\n"
                    "If you share your target quantity and delivery date, we can confirm the exact quote and schedule."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            if any(keyword in inquiry_text for keyword in ('250', 'bulk', 'volume')):
                return (
                    "Hi,\n\n"
                    "Thanks for your bulk pricing inquiry for Product X. For an order size around 250 units, "
                    "our indicative rate is $92 per unit, subject to final confirmation on delivery terms and order timing.\n\n"
                    "If you confirm the target ship date and delivery address, we can prepare the final bulk quote for you."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            if any(keyword in inquiry_text for keyword in ('distributor', 'reseller', 'monthly reorder')):
                return (
                    "Hi,\n\n"
                    "Yes, we can discuss distributor pricing for Product X. For repeat monthly orders, we usually review "
                    "forecasted volume, order frequency, and territory before confirming the commercial rate.\n\n"
                    "Please send your estimated monthly demand and target market, and we will share the appropriate pricing structure."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            return (
                "Hi,\n\n"
                "Yes, we can share pricing for Product X. The current standard pricing is "
                "$120 per unit for orders under 100 units, and $95 per unit for orders of 100 units or more. "
                "Our typical delivery timeline is 7 to 10 business days from order confirmation.\n\n"
                "If you send over your expected quantity and target delivery date, we can confirm the exact quote."
                f"{feedback_note}{revision_note}\n\n"
                "Best regards,\n"
                "Swift Support"
            )

        if category == 'availability':
            if any(keyword in lower_reason for keyword in ('warehouse', 'location', 'ship from')):
                return (
                    "Hi,\n\n"
                    "Thanks for checking stock availability for Product X. We can confirm inventory against the nearest warehouse once we have your requested quantity and delivery location.\n\n"
                    "Please send the delivery address and quantity needed, and we will confirm stock allocation and dispatch timing."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            if any(keyword in lower_reason for keyword in ('specific', 'exact quantity', 'confirm quantity')):
                return (
                    "Hi,\n\n"
                    "Thanks for checking availability for Product X. We can confirm whether the exact quantity you need is available once you share the required units and requested ship date.\n\n"
                    "Please reply with the quantity and delivery schedule, and we will confirm stock status right away."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            if any(keyword in inquiry_text for keyword in ('urgent', 'immediate', 'asap')):
                return (
                    "Hi,\n\n"
                    "We can support an urgent stock check for Product X. Based on current inventory, we should be able "
                    "to review availability for immediate shipment once we confirm the exact quantity and delivery destination.\n\n"
                    "Please reply with your shipping address and required delivery date, and we will confirm the fastest available dispatch option."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            if any(keyword in inquiry_text for keyword in ('kuala lumpur', 'singapore', 'warehouse', 'location')):
                return (
                    "Hi,\n\n"
                    "Thanks for checking regional stock availability for Product X. We can verify inventory against the nearest warehouse "
                    "and confirm whether we can fulfill your requested quantity within your delivery window.\n\n"
                    "If you send the delivery address and required quantity, we will confirm stock allocation and lead time."
                    f"{feedback_note}{revision_note}\n\n"
                    "Best regards,\n"
                    "Swift Support"
                )

            return (
                "Hi,\n\n"
                "Thanks for checking on stock availability for Product X. We currently have inventory available "
                "and can usually reserve stock once we receive your required quantity and requested ship date.\n\n"
                "If you share the quantity you need and your delivery location, we can confirm availability and "
                "hold timing for your order."
                f"{feedback_note}{revision_note}\n\n"
                "Best regards,\n"
                "Swift Support"
            )

        return (
            "Hi,\n\n"
            "Thanks for your message. At the moment, this workflow only supports customer inquiries about "
            "product stock availability and pricing. Please resend your request with the product name and either "
            "the quantity needed, availability question, or pricing details you want confirmed."
            f"{feedback_note}{revision_note}\n\n"
            "Best regards,\n"
            "Swift Support"
        )

    @property
    def created_display(self) -> str:
        """avoids date formatting logic in templates."""
        return _format_human_datetime(self.created)

    @property
    def updated_display(self) -> str:
        """keeps template timestamps consistent with created_display."""
        return _format_human_datetime(self.updated)

    def to_dict(self):
        """enriches stored fields with display fields expected by the UI."""
        payload = asdict(self)
        payload['customer_inquiry'] = self.customer_inquiry
        payload['ai_draft'] = self.ai_draft
        payload['created_display'] = self.created_display
        payload['updated_display'] = self.updated_display
        return payload

def _format_human_datetime(value: str) -> str:
    """makes ISO timestamps readable while tolerating legacy text values."""
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return value
    return parsed.strftime('%b %d, %Y, %I:%M %p').replace(' 0', ' ')


def _draft_version_number(revisions: int) -> int:
    """exposes human-facing versions as one-based numbers."""
    return revisions + 1


def _draft_version_id(draft_id: str, revisions: int) -> str:
    """creates stable audit identifiers for each reviewed draft version."""
    return f'{draft_id}-v{_draft_version_number(revisions)}'


def save_state() -> None:
    """Compatibility hook retained for callers; state now lives in PostgreSQL."""
    return None


def load_state() -> None:
    """Compatibility hook retained for callers; state now lives in PostgreSQL."""
    get_state_repository().initialize()


def _row_to_draft(row: dict[str, Any]) -> Draft:
    """converts repository dictionaries back into domain objects."""
    return Draft(
        draft_id=str(row['draft_id']),
        sender=str(row['sender']),
        subject=str(row['subject']),
        body=str(row['body']),
        status=str(row['status']),
        created=str(row['created']),
        updated=str(row['updated']),
        revisions=int(row.get('revisions', 0)),
        last_rejection_reason=str(row.get('last_rejection_reason') or ''),
        ai_draft_text=str(row.get('ai_draft_text') or ''),
        workflow=row.get('workflow'),
    )


def _draft_to_row(draft: Draft) -> dict[str, Any]:
    """stores only serializable fields in PostgreSQL-backed repositories."""
    return {
        'draft_id': draft.draft_id,
        'sender': draft.sender,
        'subject': draft.subject,
        'body': draft.body,
        'status': draft.status,
        'created': draft.created,
        'updated': draft.updated,
        'revisions': draft.revisions,
        'last_rejection_reason': draft.last_rejection_reason,
        'ai_draft_text': draft.ai_draft_text,
        'workflow': draft.workflow,
    }


def _store_draft(draft: Draft) -> Draft:
    """keeps all draft writes behind the configured repository."""
    return _row_to_draft(get_state_repository().upsert_draft(_draft_to_row(draft)))


def next_draft_id() -> str:
    """supports legacy numeric IDs for drafts created outside the workflow."""
    numeric_ids: list[int] = []
    for row in get_state_repository().list_drafts():
        try:
            numeric_ids.append(int(str(row.get('draft_id', '')).split('-')[1]))
        except Exception:
            continue
    highest = max(numeric_ids, default=100)
    return f'DFT-{highest + 1}'


def add_draft_from_email(email_payload: dict[str, object]) -> Draft | None:
    """turns simulated/listener emails into pending review drafts."""
    # Deduplicate by exact sender+subject+body for pending drafts
    sender = str(email_payload.get('from', 'noreply@example.com'))
    subject = str(email_payload.get('subject', 'No subject'))
    body = str(email_payload.get('body', ''))
    expand_short_body = bool(email_payload.get('expand_short_body', True))

    # Normalize sender display name
    sender_name = sender.split('@')[0].replace('.', ' ').title()

    # If the incoming body is short, expand it into a more structured email-like body
    if expand_short_body and len((body or '').strip()) < 80:
        body = (
            f"Hi,\n\n{body}\n\n"
            "Could you share a few more details about your request? Specifically:\n"
            "- What quantity do you need?\n"
            "- Desired timeline?\n"
            "- Any budget constraints?\n\n"
            f"Thanks,\n{sender_name}\n{sender}"
        )

    if _classify_inquiry(subject, body) is None:
        return None

    existing_row = get_state_repository().find_draft(
        sender=sender,
        subject=subject,
        body=body,
        status='pending',
    )
    if existing_row:
        existing = _row_to_draft(existing_row)
        # update timestamp and return existing
        existing.updated = datetime.now().isoformat()
        _store_draft(existing)
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
        last_rejection_reason = '',
    )
    _store_draft(draft)
    try:
        publish_event({'type': 'draft_created', 'payload': draft.to_dict()})
    except Exception:
        pass
    return draft


def add_generated_draft(
    email_payload: dict[str, object],
    *,
    ai_draft: str,
    status: str = 'pending',
    workflow: dict[str, Any] | None = None,
    draft_id: str | None = None,
) -> Draft | None:
    """persists agent-generated drafts and blocks unsupported inquiries."""
    sender = str(email_payload.get('from') or email_payload.get('sender') or 'noreply@example.com')
    subject = str(email_payload.get('subject') or 'No subject')
    body = str(email_payload.get('body') or '')
    normalized_status = status if status in {'pending', 'blocked'} else 'pending'

    if _classify_inquiry(subject, body) is None and normalized_status == 'pending':
        return None

    existing_row = get_state_repository().find_draft(
        sender=sender,
        subject=subject,
        body=body,
        status=normalized_status,
    )
    if existing_row:
        existing = _row_to_draft(existing_row)
        existing.ai_draft_text = ai_draft
        existing.workflow = workflow
        existing.updated = datetime.now().isoformat()
        _store_draft(existing)
        if existing.status == 'pending':
            try:
                publish_event({'type': 'draft_updated', 'payload': existing.to_dict()})
            except Exception:
                pass
        return existing

    now = datetime.now().isoformat()
    draft = Draft(
        draft_id=draft_id or next_draft_id(),
        sender=sender,
        subject=subject,
        body=body,
        status=normalized_status,
        created=now,
        updated=now,
        revisions=0,
        last_rejection_reason='',
        ai_draft_text=ai_draft,
        workflow=workflow,
    )
    _store_draft(draft)
    if draft.status == 'pending':
        try:
            publish_event({'type': 'draft_created', 'payload': draft.to_dict()})
        except Exception:
            pass
    return draft


def get_drafts() -> list[Draft]:
    """returns only supported pending drafts for sales review."""
    return [
        d for d in (_row_to_draft(row) for row in get_state_repository().list_drafts())
        if d.status == 'pending' and d.inquiry_category in {'pricing', 'availability'}
    ]


def get_audits() -> list[dict]:
    """enriches persisted decision rows with display timestamps for the UI."""
    enriched: list[dict] = []
    for audit in get_state_repository().list_audits():
        if (audit.get('action') or '').lower() not in {'approved', 'rejected', 'edited'}:
            continue
        entry = dict(audit)
        entry['timestamp_display'] = _format_human_datetime(audit.get('timestamp', ''))
        enriched.append(entry)
    return enriched


def approve_draft(draft_id: str, approver: str, emailed_to: str | None = None) -> dict | None:
    """records approval once and removes the draft from the active queue."""
    draft_row = get_state_repository().get_draft(draft_id)
    draft = _row_to_draft(draft_row) if draft_row else None
    if not draft or draft.inquiry_category not in {'pricing', 'availability'}:
        return None
    # If already approved, return existing approval audit (idempotent)
    existing = get_state_repository().find_audit(draft_id=draft_id, action='approved')
    if existing:
        get_state_repository().delete_draft(draft_id)
        try:
            publish_event({'type': 'approved', 'payload': existing})
        except Exception:
            pass
        return existing

    audit = {
        'audit_id': f"AUD-{uuid4().hex[:8].upper()}",
        'draft_id': draft.draft_id,
        'version_id': _draft_version_id(draft.draft_id, draft.revisions),
        'sender': draft.sender,
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
    audit = get_state_repository().insert_audit(audit)
    get_state_repository().delete_draft(draft.draft_id)
    try:
        publish_event({'type': 'approved', 'payload': audit})
    except Exception:
        pass
    return audit


def reject_and_regenerate_draft(draft_id: str, requester: str, rejection_reason: str = '') -> dict | None:
    """
    records rejection feedback and keeps the draft available for another review.
    """
    draft_row = get_state_repository().get_draft(draft_id)
    if not draft_row:
        return None
    draft = _row_to_draft(draft_row)
    reviewed_version_id = _draft_version_id(draft.draft_id, draft.revisions)
    draft.revisions = getattr(draft, 'revisions', 0) + 1
    draft.last_rejection_reason = (rejection_reason or '').strip()
    # Simulate regeneration by revising the AI reply while preserving the customer inquiry.
    draft.subject = f"{draft.subject.split(' (Regenerated')[0]} (Regenerated v{draft.revisions})"
    draft.status = 'pending'
    draft.updated = datetime.now().isoformat()
    regenerated_version_id = _draft_version_id(draft.draft_id, draft.revisions)

    rejection_audit = {
        'audit_id': f"AUD-{uuid4().hex[:8].upper()}",
        'draft_id': draft.draft_id,
        'version_id': reviewed_version_id,
        'next_version_id': regenerated_version_id,
        'sender': draft.sender,
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
        'review_comment': draft.last_rejection_reason or None,
        'customer_inquiry': draft.customer_inquiry,
        'ai_draft': draft.ai_draft,
    }
    _store_draft(draft)
    rejection_audit = get_state_repository().insert_audit(rejection_audit)
    try:
        publish_event({'type': 'regenerated', 'payload': {'draft': draft.to_dict(), 'audit': rejection_audit}})
    except Exception:
        pass
    return draft.to_dict()


# Background email listener (simulated with hardcoded emails)
# Simple in-process event queue and condition for server-sent events
EVENTS_QUEUE: list[dict] = []
events_cond = threading.Condition()

def publish_event(event: dict) -> None:
    """notifies connected browsers when review state changes."""
    with events_cond:
        EVENTS_QUEUE.append(event)
        events_cond.notify_all()


def start_email_listener(poll_interval: int = 15):
    """simulates background email intake for demos without mail infrastructure."""
    def run():
        """repeatedly seeds sample inquiries so the review UI stays active."""
        idx = 0
        while True:
            payload = SAMPLE_EMAILS[idx % len(SAMPLE_EMAILS)]
            add_draft_from_email(payload)
            idx += 1
            time.sleep(poll_interval)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def ensure_sample_drafts() -> None:
    """gives a fresh database enough pending data for the demo UI."""
    for payload in SAMPLE_EMAILS:
        add_draft_from_email(payload)


def ensure_guardrail_audit_example() -> None:
    """demonstrates rejected unsafe requests in the audit screen."""
    existing = get_state_repository().find_audit(
        draft_id=INVALID_GUARDRAIL_AUDIT['draft_id'],
        action=INVALID_GUARDRAIL_AUDIT['action'],
    )
    if existing:
        return

    audit = dict(INVALID_GUARDRAIL_AUDIT)
    audit['audit_id'] = f"AUD-{uuid4().hex[:8].upper()}"
    get_state_repository().insert_audit(audit)

# initialize configured state backend and seed deterministic demo data
load_state()
ensure_sample_drafts()
ensure_guardrail_audit_example()
