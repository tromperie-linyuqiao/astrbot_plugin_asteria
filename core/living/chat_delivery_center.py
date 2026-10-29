"""Read-only delivery projection over the existing queue, SDK history and receipts.

This module owns no journal namespace, worker, retry, retention or send authority.
The HTTP caller must first obtain the owned private SDK session and its history.
Every queue read is bounded and rechecks the same current scope and link grant.
"""
from __future__ import annotations

import json
import math

from .chat_identity import identity_service
from .chat_receipts import ChatReceipts, PHASES
from .chat_workspace import ChatWorkspace, actual_app_scope
from .delivery_store import ACTIVE, TERMINAL
from .models import private_scope, scope_key
from .reminders import LANE as REMINDER_LANE

LIMIT = 32
_STATES = ACTIVE | TERMINAL
_REASONS = {
    'candidate': 'awaiting_approval', 'approved': 'awaiting_queue',
    'queued': 'awaiting_dispatch', 'claimed': 'worker_claimed',
    'sending': 'dispatch_in_progress', 'retry_wait': 'original_queue_backoff',
    'paused': 'original_queue_paused', 'confirmed': 'original_sender_confirmed',
    'failed': 'original_sender_failed', 'unknown': 'dispatch_outcome_unknown',
    'cancelled': 'original_queue_cancelled', 'expired': 'delivery_expired',
    'quarantined': 'original_queue_quarantined',
}
_CODES = frozenset({'authorization_denied', 'authorization_revoked', 'revoked_before_dispatch',
    'adapter_unavailable', 'prepare_unavailable', 'route_unavailable', 'platform_timeout',
    'ambiguous_receipt', 'dispatch_cancelled', 'platform_exception', 'sdk_confirmed',
    'adapter_capacity', 'frequency_gate', 'service_stopping', 'waiting_for_real_scope',
    'image_required', 'attempts_exhausted', 'policy_deferred'})


def _time(value):
    return value if (not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and value >= 0) else None


def _identity(value):
    value = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ''
    return value if value and len(value) <= 160 and not any(ord(c) < 32 for c in value) else None


def _stage(observed=False, at=None):
    return dict(observed=observed, at=_time(at))


def _queue_rows(store, scope, *, source, destination, authorize):
    """Only retained live rows, including terminal failures; never rehydrate archives.

    Query IDs and lifecycle fields from the original store's existing tables,
    then use its reader. Private bodies/tokens/paths never enter this projection.
    """
    if authorize() is not True:
        raise PermissionError('delivery read authority changed')
    sk = scope_key(private_scope(scope))
    with store._read_snapshot() as db:
        counts = {row[0]: row[1] for row in db.execute(
            'SELECT t.state,COUNT(*) FROM tls_delivery_tasks t '
            'LEFT JOIN tls_delivery_tombstones x ON x.task=t.id '
            'WHERE t.scope=? AND x.task IS NULL GROUP BY t.state', (sk,)) if row[0] in _STATES}
        rows = db.execute('SELECT t.id,t.state,t.data FROM tls_delivery_tasks t '
            'LEFT JOIN tls_delivery_tombstones x ON x.task=t.id '
            'WHERE t.scope=? AND x.task IS NULL ORDER BY '
            "CASE WHEN t.state IN ('failed','unknown','quarantined','paused') THEN 0 "
            "WHEN t.state IN ('confirmed','cancelled','expired') THEN 2 ELSE 1 END, "
            't.due DESC,t.id DESC LIMIT ?', (sk, LIMIT)).fetchall()
        items = []
        for raw in rows:
            task = store._read(raw)
            identity = _identity(task.get('id'))
            state = task.get('state')
            if not identity or state not in _STATES:
                continue
            # Expose only fixed reason categories, never exception strings or
            # caller-controlled result_code identifiers from the durable task.
            events = db.execute('SELECT occurred,event,state,details FROM tls_delivery_audit '
                'WHERE task=? ORDER BY seq DESC LIMIT 64', (identity,)).fetchall()
            queued = next((r['occurred'] for r in events if r['event'] == 'enqueued'), None)
            sent = next((r['occurred'] for r in events
                if r['event'] == 'dispatch_result' and r['state'] == 'confirmed'), None)
            selected_destination = 'qq' if (source == 'linked_qq' and
                (destination == 'qq' or destination == 'chat_text' and
                    (task.get('images') or task.get('audio')))) else 'chat'
            stages = dict(created=_stage(True, task.get('created_at')),
                queued=_stage(queued is not None, queued), sent=_stage(sent is not None, sent))
            stages.update({phase: _stage() for phase in PHASES})
            reason = _REASONS[state]
            if events:
                latest = events[0]
                details = json.loads(latest['details'])
                code = details.get('code') if isinstance(details, dict) else None
                if code in _CODES:
                    reason = code
                elif latest['event'] in _CODES:
                    reason = latest['event']
            items.append(dict(task_id=identity, source=source, destination=selected_destination,
                kind='reminder' if task.get('delivery_lane') == REMINDER_LANE else 'proactive',
                state=state, reason=reason,
                available_at=_time(task.get('available_at')),
                expires_at=_time(task.get('expires_at')), stages=stages))
    if authorize() is not True:
        raise PermissionError('delivery read authority changed')
    return counts, items


def delivery_center_view(plugin, username, session_id, snapshot, session, journal, current):
    """Projection for an already SDK-owned private session; callable in a thread."""
    if current() is not True:
        raise PermissionError('delivery read authority changed')
    host = getattr(getattr(plugin, '_presence', None), 'living_host', None)
    runtime = getattr(host, 'runtime', None)
    links = identity_service(plugin)
    settings = ChatWorkspace(links).settings(username, session_id)
    link = links.get(username, session_id)
    app_scope = actual_app_scope(plugin, username, session)

    def still_current():
        return bool(current() is True and links.current() is True
            and getattr(getattr(plugin, '_presence', None), 'living_host', None) is host
            and getattr(host, 'runtime', None) is runtime
            and actual_app_scope(plugin, username, session) == app_scope
            and links.get(username, session_id) == link
            and ChatWorkspace(links).settings(username, session_id) == settings)

    scopes = [('chat', app_scope)] if app_scope else []
    # The same explicit grant that permits Chat routing or the existing QQ
    # notification copy is required to inspect the linked source queue.
    if link and (settings['values']['proactive_destination'] in {'chat_text', 'chat_all'}
            or link.get('notifications') is True):
        linked = private_scope(link['qq_scope'])
        if host is not None and host.authorized_scope(linked) is True:
            scopes.append(('linked_qq', linked))
    owners, seen = [], set()
    for name in ('delivery', 'reminders'):
        owner = getattr(runtime, name, None)
        store = getattr(owner, 'store', None)
        if (store is not None and getattr(owner, 'active', False) is True
                and id(store) not in seen):
            owners.append((name, owner, store))
            seen.add(id(store))
    queue_items, counts, sources = [], {}, []
    limited = False
    for name, owner, store in owners:
        for source, selected_scope in scopes:
            def authorized():
                return bool(still_current() and getattr(runtime, name, None) is owner
                    and owner.active is True and getattr(owner, 'store', None) is store
                    and host.authorized_scope(selected_scope) is True)
            # Reuse the reminder service's more restrictive original read ACL.
            reminder_check = getattr(owner, '_authorized', None) if name == 'reminders' else None
            if callable(reminder_check) and reminder_check(selected_scope) is not True:
                continue
            selected_counts, items = _queue_rows(store, selected_scope, source=source,
                destination=settings['values']['proactive_destination'], authorize=authorized)
            sources.append(dict(source=source, lane=name, state='available'))
            for state, count in selected_counts.items():
                counts[state] = counts.get(state, 0) + count
            limited = limited or sum(selected_counts.values()) > len(items)
            queue_items.extend(items)
    queue_items.sort(key=lambda row: (row['state'] not in {'failed', 'unknown', 'quarantined', 'paused'},
        row['state'] in {'confirmed', 'cancelled', 'expired'}, -(row['available_at'] or 0)))
    limited = limited or len(queue_items) > LIMIT
    queue_items = queue_items[:LIMIT]
    receipt_view = ChatReceipts(journal, current=current).view(username, session_id, snapshot)
    receipts = {item['message_id']: item for item in receipt_view['messages']}
    by_task = {item['task_id']: item for item in queue_items}
    messages = []
    # Only real saved SDK assistant IDs; local drafts and stream placeholders
    # cannot become server delivery evidence.
    for saved in snapshot.get('history', []):
        if not isinstance(saved, dict) or not isinstance(saved.get('content'), dict):
            continue
        identity = _identity(saved.get('id'))
        if saved['content'].get('type') != 'bot' or not identity:
            continue
        refs = saved['content'].get('refs')
        refs = refs if isinstance(refs, dict) else {}
        task = by_task.get(_identity(refs.get('tls_proactive_task')))
        stages = dict(created=_stage(True), queued=_stage(), sent=_stage())
        if task:
            stages.update({name: dict(task['stages'][name]) for name in stages})
        reported = receipts.get(identity, {})
        stages.update({phase: _stage(_time(reported.get(phase + '_at')) is not None,
            reported.get(phase + '_at')) for phase in PHASES})
        notice = refs.get('tls_notice')
        kind = notice.get('kind') if isinstance(notice, dict) and notice.get('schema') == 1 else None
        messages.append(dict(message_id=identity, server_saved=True,
            kind=kind if kind in {'proactive', 'reminder'} else 'reply', stages=stages,
            # History proves persistence, never transport completion or a read.
            user_read_proven=False))
    if still_current() is not True:
        raise PermissionError('delivery read authority changed')
    return dict(schema=1, supported=True, read_only=True, limit=LIMIT,
        messages=messages[-LIMIT:], history_window_only=True,
        server_queue=dict(state='available' if sources else 'scope_unavailable' if not scopes else 'unavailable',
            counts=counts, items=queue_items, limited=limited, sources=sources,
            retained_live_rows_only=True),
        workspace=dict(values=settings['values'], linked=bool(link)),
        receipt_reporting='authenticated_client_claim', user_read_proven=False,
        server_push=False,
        message_sync=ChatReceipts.capability()['message_sync'],
        reliability=dict(server_history='durable_original_sdk',
            background_transport='user_enabled_periodic_check', server_push_configured=False,
            process_exit_delivery_guaranteed=False, server_sent_is_phone_received=False,
            client_reports_are_observations=True, known_gap_recovery='bounded_saved_id_catchup'))
