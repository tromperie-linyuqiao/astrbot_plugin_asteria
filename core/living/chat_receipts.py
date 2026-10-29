"""Bounded, client-reported Chat receipts in the existing workflow journal.

SDK history is the authority for a committed message. A successful history GET
does not prove that an Android process received or displayed its response.
Only explicit client reports add those observations; none authorize a send.
"""
from __future__ import annotations

from .chat_expressions import ChatExpressions

NAMESPACE = 'tls.chat.client_receipts'
PHASES = ('client_received', 'system_notification_posted', 'user_opened')
MAX_REPORT = 32
MAX_RECORDS = 64


def assistant_messages(snapshot):
    result = {}
    for row in snapshot.get('history', []):
        if not isinstance(row, dict) or not isinstance(row.get('content'), dict):
            continue
        if row['content'].get('type') != 'bot' or row.get('id') is None:
            continue
        identity = str(row['id'])
        if not identity or len(identity) > 160 or any(ord(c) < 32 for c in identity):
            continue
        refs = row['content'].get('refs')
        notice = refs.get('tls_notice') if isinstance(refs, dict) else None
        kind = notice.get('kind') if isinstance(notice, dict) and notice.get('schema') == 1 else None
        result[identity] = dict(message_id=identity, server_committed=True,
            kind=kind if kind in {'reminder', 'proactive'} else 'reply')
    return result


class ChatReceipts:
    def __init__(self, journal, *, current):
        self.journal, self.current = journal, current

    @staticmethod
    def capability():
        from .chat_sync import capability as sync_capability
        return dict(schema=1, supported=True, report_limit=MAX_REPORT,
            retained_messages=MAX_RECORDS, reporting='authenticated_client_claim',
            server_push=False, user_read_proven=False, message_sync=sync_capability())

    def view(self, username, session_id, snapshot):
        scope = ChatExpressions.message_scope(username, session_id)
        record = self.journal.fetch(NAMESPACE, 'session', scope)
        saved = (record['data'].get('messages') or {}) if record else {}
        items = list(assistant_messages(snapshot).values())[-MAX_REPORT:]
        for item in items:
            previous = saved.get(item['message_id'], {})
            for phase in PHASES:
                item[phase + '_at'] = previous.get(phase + '_at')
            item['user_read_proven'] = False
        return dict(self.capability(), messages=items,
            history_window_only=True, last_report_at=record['updated_at'] if record else None)

    def report(self, username, session_id, snapshot, phase, message_ids):
        if phase not in PHASES:
            raise ValueError('收件状态无效')
        if (not isinstance(message_ids, list) or not 1 <= len(message_ids) <= MAX_REPORT
                or any(not isinstance(x, str) or not x or len(x) > 160
                    or any(ord(c) < 32 for c in x) for x in message_ids)):
            raise ValueError('收件消息编号无效')
        ids = list(dict.fromkeys(message_ids))
        known = assistant_messages(snapshot)
        if any(identity not in known for identity in ids):
            raise ValueError('仅能确认当前已保存的本会话助手消息')
        scope = ChatExpressions.message_scope(username, session_id)
        with self.journal._transaction():
            if not self.current():
                raise PermissionError('收件服务已变化')
            prior = self.journal.fetch(NAMESPACE, 'session', scope)
            data = dict(prior['data']) if prior else dict(messages={})
            messages = {k: dict(v) for k, v in data['messages'].items()}
            now, changed = self.journal.clock(), False
            for identity in ids:
                row = messages.setdefault(identity, {})
                # A notification was built from an actually received save row.
                for selected in dict.fromkeys(('client_received', phase)):
                    field = selected + '_at'
                    if field not in row:
                        row[field] = now
                        changed = True
            if changed:
                # This is receipt metadata retention, never history deletion.
                messages = dict(sorted(messages.items(),
                    key=lambda item: max(item[1].values()))[-MAX_RECORDS:])
                data = dict(messages=messages, reporting='authenticated_client_claim')
                # The outer transaction supplies the same capacity/CAS and
                # authorization contract without nesting another BEGIN.
                from .models import canonical, scope_key
                db = self.journal._db
                if prior is None and db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
                    raise RuntimeError('receipt journal capacity reached')
                db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope) '
                    'DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data',
                    (NAMESPACE, 'session', scope_key(scope), (prior['revision'] if prior else 0) + 1, now, canonical(data)))
            if not self.current():
                raise PermissionError('收件服务已变化')
        return self.view(username, session_id, snapshot)
