"""Small scoped action controls and execution receipts in the existing Journal.

Rest and deferral are not fictional events, growth, model budget or permission.
No scheduler, provider calls, or separate persistence lives here.
"""
from copy import deepcopy

from .autonomous_life import _digest, _id, _text
from .journal import JournalConflict
from .models import canonical, plain, scope_key

NAMESPACE = 'tls.life.choices.v1'
RECEIPTS = 'tls.life.choice.receipts.v1'
TARGET_KINDS = {'interest', 'exploration', 'collection', 'character', 'thread'}
MAX_DEFERRED = 64


class LifeChoices:
    def __init__(self, life, personal=None):
        self.life, self.journal = life, life.journal
        if personal is None:
            from .personal_space import PersonalSpace
            personal = PersonalSpace(life)
        self.personal = personal

    def _row(self, scope):
        return self.journal.fetch(NAMESPACE, 'current', scope)

    def revision(self, scope):
        scope = self.life._scope(scope)
        row = self._row(scope)
        return row['revision'] if row else 0

    def _target(self, scope, kind, identity):
        if kind not in TARGET_KINDS:
            raise ValueError('supported current life choice target required')
        _id(identity)
        if kind == 'character': return self.life.get_character(scope, identity)
        if kind == 'thread': return self.life.get_thread(scope, identity)
        return self.personal.get_record(scope, kind, identity)

    def snapshot(self, scope):
        scope = self.life._scope(scope)
        with self.journal._lock:
            row = self._row(scope)
            data = row['data'] if row else {}
            now = self.life._now()
            rest = deepcopy(data.get('rest'))
            if rest: rest['active'] = rest['until'] > now
            deferred = []
            for value in data.get('deferred', []):
                record = self._target(scope, value['kind'], value['id'])
                valid = bool(record and record['valid'])
                stale = not valid or record['revision'] != value['source_revision']
                deferred.append(dict(value, valid=valid, stale=stale,
                    active=value['until'] > now and not stale))
            receipts = self.journal.list(RECEIPTS, scope, limit=12)
            recent = []
            for receipt in receipts:
                value = deepcopy(receipt['data'])
                for key in ('fingerprint', 'controls', 'record'):
                    value.pop(key, None)
                recent.append(value)
            self.life._scope(scope)
            return dict(revision=row['revision'] if row else 0, rest=rest,
                deferred=deferred, recent_actions=recent, model_called=False,
                changes_budget=False, limits=dict(deferred=MAX_DEFERRED, recent_actions=12))

    def _put(self, db, scope, namespace, key, data, old=None):
        if not self.life._allowed(scope, 'write'):
            raise PermissionError('life choice authority changed')
        if old is None and db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
            raise RuntimeError('journal capacity reached; choice receipts retained')
        encoded = canonical(plain(data, 65536))
        revision = old['revision'] + 1 if old else 1
        db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope) '
            'DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data',
            (namespace, key, scope_key(scope), revision, self.life._now(), encoded))

    @staticmethod
    def _revision(value):
        if type(value) is not int or value < 0:
            raise ValueError('current life choice revision required')
        return value

    def control(self, scope, *, action, request_id, expected_revision, target_kind=None,
                target_id=None, expected_target_revision=None, minutes=None, reason='', actor='operator'):
        scope = self.life._scope(scope, 'write')
        if action not in {'rest', 'defer', 'restart'}:
            raise ValueError('rest, defer or restart action required')
        request_id, reason, actor = _text(request_id, 128), _text(reason, 400, empty=True), _text(actor, 120)
        self._revision(expected_revision)
        has_target = target_kind is not None or target_id is not None
        if has_target and (target_kind not in TARGET_KINDS or not target_id):
            raise ValueError('complete life action target required')
        if action == 'defer' and not has_target or action == 'rest' and has_target:
            raise ValueError('this action requires its correct target scope')
        if has_target: self._revision(expected_target_revision)
        elif expected_target_revision is not None:
            raise ValueError('target revision without target')
        if action == 'restart':
            if minutes is not None: raise ValueError('restart does not accept duration')
        else:
            minutes = (120 if action == 'rest' else 1440) if minutes is None else minutes
            if type(minutes) is not int or not 15 <= minutes <= (1440 if action == 'rest' else 10080):
                raise ValueError('bounded rest or deferral duration required')
        fingerprint = _digest([action, expected_revision, target_kind, target_id,
            expected_target_revision, minutes, reason, actor])
        key = 'control.' + _digest([scope, request_id])[:48]
        with self.journal._transaction() as db:
            saved = self.journal.fetch(RECEIPTS, key, scope)
            if saved:
                if saved['data']['fingerprint'] != fingerprint:
                    raise JournalConflict('life action request changed')
                result = deepcopy(saved['data']); result['created'] = False
                self.life._scope(scope, 'write')
                return result
            old = self._row(scope)
            if (old['revision'] if old else 0) != expected_revision:
                raise JournalConflict('life action controls changed')
            data = deepcopy(old['data']) if old else dict(rest=None, deferred=[])
            record, target = None, None
            now = self.life._now()
            if has_target:
                record = self._target(scope, target_kind, target_id)
                if not record or not record['valid']:
                    raise ValueError('current valid life action target required')
                if record['revision'] != expected_target_revision:
                    raise JournalConflict('life action target changed')
                target = dict(kind=target_kind, id=target_id, source_revision=record['revision'],
                    source_version=record['version'])
            if action == 'rest':
                data['rest'] = dict(until=now + minutes*60, reason=reason, at=now, actor=actor)
            elif action == 'defer':
                values = [item for item in data['deferred'] if (item['kind'], item['id']) != (target_kind, target_id)
                          and item['until'] > now]
                if len(values) >= MAX_DEFERRED: raise RuntimeError('too many deferred life choices')
                data['deferred'] = [*values, dict(target, until=now + minutes*60, reason=reason, at=now, actor=actor)]
            elif not has_target:
                data['rest'] = None
            else:
                data['deferred'] = [item for item in data['deferred'] if (item['kind'], item['id']) != (target_kind, target_id)]
                if target_kind in {'interest', 'exploration'} and record['fields'].get('status') == 'paused':
                    previous = self.personal._row(scope, target_kind, target_id)
                    updated = deepcopy(previous['data'])
                    updated.update(fields=dict(updated['fields'], status='active'), version=updated['version']+1)
                    self.personal._write(db, scope, [(target_kind, updated, previous)],
                        reason=reason or 'explicitly restarted paused activity', actor=actor)
                elif record['fields'].get('status') in {'completed', 'cancelled', 'resolved'}:
                    raise ValueError('completed or cancelled activity cannot be silently reopened')
            self._put(db, scope, NAMESPACE, 'current', data, old)
            controls = self.snapshot(scope)
            result = dict(created=True, request_id=request_id, fingerprint=fingerprint,
                action=action, at=now, target=target, reason=reason, actor=actor, controls=controls)
            if has_target: result['record'] = self._target(scope, target_kind, target_id)
            self._put(db, scope, RECEIPTS, key, result)
            self.life._scope(scope, 'write')
        return result

    def record_outcome(self, scope, request_id, outcome):
        """Persist what happened; quiet never silently becomes a defer action."""
        scope = self.life._scope(scope, 'write')
        request_id = _text(request_id, 128)
        value = plain(deepcopy(outcome), 8192)
        fingerprint = _digest(value)
        key = 'outcome.' + _digest([scope, request_id])[:48]
        with self.journal._transaction() as db:
            saved = self.journal.fetch(RECEIPTS, key, scope)
            if saved:
                if saved['data']['fingerprint'] != fingerprint: raise JournalConflict('life outcome changed')
                return deepcopy(saved['data'])
            result = dict(value, request_id=request_id, fingerprint=fingerprint, action='evaluation', at=self.life._now())
            self._put(db, scope, RECEIPTS, key, result)
            self.life._scope(scope, 'write')
        return result
