from __future__ import annotations

from flask import Flask, jsonify, redirect, render_template, request, flash, url_for, Response, stream_with_context
import json
from datetime import datetime

from data import ANALYTICS, EVENTS, RECORDS, SETTINGS, USERS, DRAFTS, AUDITS, add_record, add_user_invite, add_draft_from_email, approve_draft, get_drafts, get_audits, start_email_listener, EVENTS_QUEUE, events_cond, publish_event

app = Flask(__name__)
app.secret_key = 'dev-secret-key'


def _get_sort_order() -> str:
    order = (request.args.get('order') or 'desc').strip().lower()
    return 'asc' if order == 'asc' else 'desc'


def _parse_sort_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.min


def _sort_items(items, timestamp_key: str, order: str):
    reverse = order != 'asc'
    return sorted(items, key=lambda item: _parse_sort_datetime(item.get(timestamp_key)), reverse=reverse)


@app.get('/')
def home():
    return redirect(url_for('dashboard'))


@app.get('/dashboard.html')
def dashboard():
    stats = {
        'total_records': len(RECORDS),
        'active_users': len(USERS),
        'pending_reviews': sum(1 for r in RECORDS if r.status == 'pending'),
        'resolved_issues': 847,
    }
    return render_template('dashboard.html', stats=stats, records=RECORDS[:5])


@app.route('/filter-list.html', methods=['GET'])
def records_list():
    return render_template('filter-list.html', records=RECORDS)


@app.route('/create-record.html', methods=['GET', 'POST'])
def create_record():
    if request.method == 'POST':
        record = add_record(request.form.to_dict())
        flash(f"Record {record.record_id} was created successfully.", 'success')
        return redirect(url_for('record_details', record_id=record.record_id))
    return render_template('create-record.html')


@app.get('/record-details.html')
def record_details():
    record_id = request.args.get('record_id', RECORDS[0].record_id)
    record = next((r for r in RECORDS if r.record_id == record_id), RECORDS[0])
    return render_template('record-details.html', record=record)


@app.get('/users.html')
def users_page():
    return render_template('users.html', users=USERS)


@app.get('/analytics.html')
def analytics_page():
    return render_template('analytics.html', analytics=ANALYTICS)


@app.get('/calendar.html')
def calendar_page():
    return render_template('calendar.html', events=EVENTS)


@app.get('/settings.html')
def settings_page():
    return render_template('settings.html', settings=SETTINGS)


@app.get('/api/records')
def api_records():
    return jsonify([r.to_dict() for r in RECORDS])


@app.post('/api/records')
def api_create_record():
    record = add_record(request.get_json(silent=True) or request.form.to_dict())
    return jsonify(record.to_dict()), 201


@app.get('/api/users')
def api_users():
    return jsonify([u.to_dict() for u in USERS])


@app.post('/api/users/invite')
def api_invite_user():
    payload = request.get_json(silent=True) or request.form.to_dict()
    email = payload.get('email', '').strip()
    role = payload.get('role', 'Viewer').strip() or 'Viewer'
    if not email:
        return jsonify({'error': 'email is required'}), 400
    user = add_user_invite(email, role)
    return jsonify(user), 201


@app.get('/api/calendar/events')
def api_calendar_events():
    return jsonify(EVENTS)


@app.get('/api/analytics')
def api_analytics():
    return jsonify(ANALYTICS)


@app.get('/api/drafts')
def api_drafts():
    order = _get_sort_order()
    drafts = [d.to_dict() for d in get_drafts()]
    return jsonify(_sort_items(drafts, 'created', order))


@app.post('/api/drafts/<draft_id>/approve')
def api_approve_draft(draft_id):
    approver = None
    send_to = None
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        approver = payload.get('approver')
        send_to = payload.get('send_to')
    approver = approver or request.form.get('approver') or 'Admin'
    send_to = send_to or request.form.get('send_to')

    audit = approve_draft(draft_id, approver, send_to)
    if not audit:
        # draft not found
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'draft not found'}), 404
        flash(f"Draft {draft_id} not found.", 'info')
        return redirect(url_for('pending_page'))

    # If audit exists (idempotent), inform user and redirect
    if audit.get('action') == 'approved' and audit in AUDITS:
        # flash message and redirect to pending page to show updated state
        flash(f"Draft {draft_id} approved and processed.", 'success')
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(audit), 200
        return redirect(url_for('pending_page'))


@app.post('/api/drafts/<draft_id>/reject')
def api_reject_draft(draft_id):
    requester = request.form.get('approver') or 'Admin'
    result = None
    try:
        from data import reject_and_regenerate_draft
        result = reject_and_regenerate_draft(draft_id, requester)
    except Exception:
        result = None
    if not result:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'draft not found'}), 404
        flash(f"Draft {draft_id} not found.", 'info')
        return redirect(url_for('pending_page'))
    # regeneration successful
    flash(f"Draft {draft_id} regenerated by agent.", 'error')
    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(result), 200
    return redirect(url_for('pending_page'))


@app.get('/api/audits')
def api_audits():
    order = _get_sort_order()
    return jsonify(_sort_items(get_audits(), 'timestamp', order))


@app.get('/stream')
def stream():
    """Server-Sent Events stream for draft and audit events."""
    def event_stream():
        while True:
            with events_cond:
                events_cond.wait()
                while EVENTS_QUEUE:
                    ev = EVENTS_QUEUE.pop(0)
                    # ev expected to be {'type': 'name', 'payload': {...}}
                    try:
                        payload = ev.get('payload', ev)
                    except Exception:
                        payload = ev
                    yield f"event: {ev.get('type', 'message')}\n"
                    yield f"data: {json.dumps(payload)}\n\n"
    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')


@app.get('/pending.html')
def pending_page():
    order = _get_sort_order()
    drafts = _sort_items([d.to_dict() for d in get_drafts()], 'created', order)
    return render_template('pending.html', drafts=drafts, sort_order=order)


@app.get('/audit.html')
def audit_page():
    order = _get_sort_order()
    audits = _sort_items(get_audits(), 'timestamp', order)
    return render_template('audit.html', audits=audits, sort_order=order)


@app.get('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    # start background email listener
    try:
        start_email_listener()
    except Exception:
        pass
    app.run(debug=True)
