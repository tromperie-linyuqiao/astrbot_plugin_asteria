"""Small authenticated device receipts; no message sender, draft sync or timer."""
from __future__ import annotations
import re
from .chat_expressions import ChatExpressions
from .journal import JournalConflict

NAMESPACE = 'asteria.chat.device_continuity'
VISIBLE_SECONDS = 30
VOICE_SECONDS = 240


class ChatDevices:
    def __init__(self, journal, *, current):
        self.journal, self.current = journal, current

    def scope(self, username, session):
        return ChatExpressions.message_scope(username, session)

    def view(self, username, session):
        record = self.journal.fetch(NAMESPACE, 'devices', self.scope(username, session))
        data = record['data'] if record else {}
        now = self.journal.clock()
        voice = data.get('voice', {})
        return dict(schema=1, server_time=now, visible_seconds=VISIBLE_SECONDS,
            read_cursor=data.get('read_cursor', ''),
            visible=[row for row in data.get('visible', []) if now-row['at'] < VISIBLE_SECONDS],
            voice=voice if voice.get('expires_at', 0) > now else {},
            drafts='local_only', reporting='foreground_viewport_client_claim')

    def apply(self, username, session, snapshot, body):
        action, device = body.get('action'), body.get('device_id')
        if not isinstance(device, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{12,80}', device):
            raise ValueError('设备标识无效')
        fields = {'session_id', 'action', 'device_id'}
        if action == 'visible':
            fields |= {'message_ids', 'read_cursor'}
        elif action in {'voice_claim', 'voice_check', 'voice_release', 'voice_takeover'}:
            fields.add('call_id')
            if not isinstance(body.get('call_id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', body['call_id']):
                raise ValueError('通话标识无效')
        else:
            raise ValueError('设备操作无效')
        if set(body) != fields:
            raise ValueError('设备操作字段无效')
        scope = self.scope(username, session)
        prior = self.journal.fetch(NAMESPACE, 'devices', scope)
        data = dict(prior['data']) if prior else dict(visible=[], read_cursor='')
        now = self.journal.clock()
        data['visible'] = [dict(row) for row in data.get('visible', []) if now-row['at'] < VISIBLE_SECONDS]
        voice = dict(data.get('voice', {}))
        if voice.get('expires_at', 0) <= now:
            voice = {}
        owned = voice.get('device_id') == device and voice.get('call_id') == body.get('call_id')
        accepted = True
        if action == 'visible':
            known = {str(row.get('id')) for row in snapshot.get('history', []) if isinstance(row, dict)}
            ids, cursor = body.get('message_ids'), body.get('read_cursor')
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 32
                    or any(not isinstance(x, str) or x not in known for x in ids)
                    or not isinstance(cursor, str) or cursor not in ids
                    or not re.fullmatch(r'[1-9][0-9]{0,18}', cursor)):
                raise ValueError('只能确认当前会话实际展示的已保存消息')
            data['visible'] = [row for row in data['visible'] if row['device_id'] != device]
            data['visible'].append(dict(device_id=device, message_ids=list(dict.fromkeys(ids)), at=now))
            data['visible'] = data['visible'][-8:]
            if int(cursor) > int(data.get('read_cursor') or 0):
                data['read_cursor'] = cursor
        elif action == 'voice_release':
            if owned:
                voice = {}
        elif action == 'voice_takeover':
            if voice and not owned:
                voice['yield_requested'] = True
                accepted = False
            elif not voice:
                voice = dict(device_id=device, call_id=body['call_id'], expires_at=now+VOICE_SECONDS)
        elif action == 'voice_claim':
            if voice and not owned:
                accepted = False
            elif not voice:
                voice = dict(device_id=device, call_id=body['call_id'], expires_at=now+VOICE_SECONDS)
            elif voice.get('yield_requested'):
                accepted = False
        elif action == 'voice_check':
            accepted = owned and not voice.get('yield_requested', False)
            if accepted:
                voice['expires_at'] = now+VOICE_SECONDS
        data['voice'] = voice
        self.journal.put(NAMESPACE, 'devices', scope, data,
            expected_revision=prior['revision'] if prior else 0, authorize=self.current)
        return dict(self.view(username, session), accepted=accepted)
