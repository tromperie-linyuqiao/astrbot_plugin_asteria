"""Manual shared-event definitions using the existing native memory revisions.

Registration is an action_result; its manually selected evidence category never
silently promotes an inference, archive item or RP into a real user fact. This
panel never promotes its stored action_result into generic real-memory recall.
Confirmed, enabled records have one separately typed unified-context outlet.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import html
import json
import re

from .models import private_scope, scope_key
from .native_memory import NativeMemoryStore, MemoryConflict, _epoch, _tokens, _normal
from .memory_context import _SECRET

SOURCE = 'tls.shared_timeline.panel'
SCHEMA = 'tls.native.shared_timeline.v1'
TYPE = 'shared_experience_definition'
CATEGORIES = {'user_confirmed': '用户明确确认', 'historical_material': '历史资料待核',
              'model_inference': '模型推断，未确认为真实', 'roleplay': 'RP虚构经历'}
FIELDS = frozenset(('title', 'content', 'occurred_at', 'evidence_category', 'source_ref', 'enabled', 'user_confirmed'))
MAX_RECORDS = 1000
RECENT_SECONDS = 14 * 86400
CONTEXT_CANDIDATES = 32
_REQUEST = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}\Z')


def _text(value, maximum, *, empty=False):
    if (type(value) is not str or len(value) > maximum or not empty and not value.strip()
            or any(ord(c) < 32 and c not in '\r\n\t' for c in value) or _SECRET.search(value)):
        raise ValueError('bounded explicit timeline text required')
    return value.strip()


def edit_fields(value, now):
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError('exact shared timeline fields required')
    category = value['evidence_category']
    if type(category) is not str or category not in CATEGORIES:
        raise ValueError('explicit evidence category required')
    if type(value['enabled']) is not bool or type(value['user_confirmed']) is not bool:
        raise ValueError('exact timeline flags required')
    if value['user_confirmed'] is not (category == 'user_confirmed'):
        raise ValueError('user confirmation must match the explicit evidence category')
    if type(value['occurred_at']) is not str:
        raise ValueError('explicit zoned event time required')
    occurred = _epoch(value['occurred_at'])
    if occurred > _epoch(now):
        raise ValueError('shared timeline is not a future plan')
    return dict(title=_text(value['title'], 120), content=_text(value['content'], 3000),
        occurred_at=datetime.fromtimestamp(occurred, timezone.utc).isoformat().replace('+00:00', 'Z'),
        evidence_category=category, source_ref=_text(value['source_ref'], 256),
        enabled=value['enabled'], user_confirmed=value['user_confirmed'])


class NativeSharedTimeline:
    backend = 'native_shared_timeline'

    def __init__(self, store, *, authorize, clock=None):
        if not isinstance(store, NativeMemoryStore) or not callable(authorize):
            raise ValueError('existing native memory store and scope authorization required')
        self.store, self.authorize = store, authorize
        self.clock = store.clock if clock is None else clock
        if not callable(self.clock): raise ValueError('clock required')
        self._bindings = (store, authorize, self.clock, store._db, store._lock, store.path)
        self.active = True

    def check(self, scope):
        scope = private_scope(scope)
        current = (self.store, self.authorize, self.clock, self.store._db, self.store._lock, self.store.path)
        if (not self.active or any(a is not b for a, b in zip(self._bindings[:5], current[:5]))
                or self._bindings[5] != current[5] or self.authorize(dict(scope)) is not True):
            raise PermissionError('shared timeline scope unavailable')
        self.store._check_open()
        return scope

    def _record(self, scope, identity):
        row = self.store.get(scope, identity, include_deleted=True)
        meta = row.get('metadata') if isinstance(row, dict) else None
        if (not isinstance(meta, dict) or set(meta) != {'schema', 'managed_by', 'title', 'evidence_category', 'source_ref', 'enabled', 'user_confirmed', 'evidence_kind'}
                or meta.get('schema') != SCHEMA or meta.get('managed_by') != SOURCE
                or meta.get('evidence_kind') != 'action_result' or row.get('evidence_kind') != 'action_result'
                or row.get('source_id') != SOURCE or row.get('memory_type') != TYPE
                or row.get('source_plugin') != 'texas_living_system' or row.get('reality_level') != 'action_result'
                or row.get('scope') != 'private' or row.get('visibility') != 'private_pair'
                or row.get('owner_bot_id') != scope['bot_id'] or row.get('persona_id') != scope['character_id']
                or row.get('platform') != scope['platform'] or row.get('session_id') != scope['session_id']
                or row.get('subject') != {'kind': 'user', 'id': scope['user_id']}
                or row.get('object') != {'kind': 'bot', 'id': scope['bot_id']}
                or row.get('lifecycle') not in {'stable_memory', 'deleted'}):
            raise KeyError('shared timeline record absent')
        self._project(row)
        return row

    def _project(self, row):
        meta = row['metadata']
        values = edit_fields(dict(title=meta['title'], content=row['content'], occurred_at=row['occurred_at'],
            **{key: meta[key] for key in ('evidence_category', 'source_ref', 'enabled', 'user_confirmed')}), self.clock())
        return dict(id=row['id'], revision=row['revision'], fields=values, archived=row['lifecycle'] == 'deleted',
            created_at=row['created_at'], updated_at=row['updated_at'], source=SOURCE,
            evidence_label=CATEGORIES[values['evidence_category']], registration_evidence_kind='action_result',
            automatic_recall=False, context_eligible=(row['lifecycle'] != 'deleted'
                and values['enabled'] is True and values['evidence_category'] == 'user_confirmed'
                and values['user_confirmed'] is True),
            requires_runtime_authorization=True, actually_used='unknown')

    @staticmethod
    def _metadata(fields):
        return dict(schema=SCHEMA, managed_by=SOURCE,
                    **{key: value for key, value in fields.items() if key not in {'content', 'occurred_at'}})

    @staticmethod
    def _revision(value):
        if type(value) is not int or not 1 <= value <= 2147483647:
            raise ValueError('exact positive revision required')

    def _readback(self, scope, row):
        saved = self._record(scope, row['id'])
        if saved != row: raise RuntimeError('shared timeline write readback mismatch')
        self.check(scope)
        return self._project(saved)

    def create(self, scope, request_id, **fields):
        scope = self.check(scope); fields = edit_fields(fields, self.clock())
        if type(request_id) is not str or not _REQUEST.fullmatch(request_id): raise ValueError('stable request ID required')
        event = 'shared_timeline_' + hashlib.sha256(request_id.encode()).hexdigest()
        with self.store.transaction():
            self.check(scope)
            existing = self.store._db.execute('SELECT 1 FROM tls_native_memory_events WHERE scope=? AND id=?', (scope_key(scope), event)).fetchone()
            if existing is None and self._count(scope) >= MAX_RECORDS: raise RuntimeError('shared timeline capacity reached')
            row = self.store.write(scope, fields['content'], source_id=SOURCE, evidence_kind='action_result',
                memory_type=TYPE, occurred_at=fields['occurred_at'], metadata=self._metadata(fields), event_id=event)
            result = self._readback(scope, row)
            self.check(scope)
        return result

    def get(self, scope, identity):
        scope = self.check(scope)
        row = self._record(scope, identity); self.check(scope)
        return self._project(row)

    def update(self, scope, identity, *, expected_revision, **fields):
        scope = self.check(scope); self._revision(expected_revision); fields = edit_fields(fields, self.clock())
        with self.store.transaction():
            self.check(scope); old = self._record(scope, identity)
            if old['lifecycle'] == 'deleted': raise MemoryConflict('restore archived event before editing')
            row = self.store.write(scope, fields['content'], source_id=SOURCE, evidence_kind='action_result',
                memory_type=TYPE, occurred_at=fields['occurred_at'], metadata=self._metadata(fields),
                record_id=identity, expected_revision=expected_revision)
            result = self._readback(scope, row); self.check(scope)
        return result

    def _change(self, scope, identity, expected_revision, operation):
        scope = self.check(scope); self._revision(expected_revision)
        with self.store.transaction():
            self.check(scope); self._record(scope, identity)
            row = getattr(self.store, operation)(scope, identity, expected_revision=expected_revision)
            result = self._readback(scope, row); self.check(scope)
        return result

    def archive(self, scope, identity, *, expected_revision): return self._change(scope, identity, expected_revision, 'delete')
    def restore(self, scope, identity, *, expected_revision): return self._change(scope, identity, expected_revision, 'restore')

    def _where(self, scope):
        return ("scope=? AND json_extract(data,'$.source_id')=? AND json_extract(data,'$.metadata.schema')=? AND json_extract(data,'$.memory_type')=?", [scope_key(scope), SOURCE, SCHEMA, TYPE])

    def _count(self, scope):
        where, args = self._where(scope)
        return self.store._db.execute('SELECT COUNT(*) FROM tls_native_memories WHERE ' + where, args).fetchone()[0]

    def list(self, scope, *, include_archived=False, category='', query='', limit=50, offset=0):
        scope = self.check(scope)
        if type(include_archived) is not bool or type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or not 0 <= offset <= MAX_RECORDS:
            raise ValueError('bounded timeline pagination required')
        if type(category) is not str or category and category not in CATEGORIES: raise ValueError('invalid evidence category')
        query = _text(query, 200, empty=True)
        where, args = self._where(scope)
        if not include_archived: where += " AND lifecycle!='deleted'"
        if category: where += " AND json_extract(data,'$.metadata.evidence_category')=?"; args.append(category)
        if query:
            where += " AND (instr(json_extract(data,'$.content'),?)>0 OR instr(json_extract(data,'$.metadata.title'),?)>0 OR instr(json_extract(data,'$.metadata.source_ref'),?)>0)"; args += [query] * 3
        with self.store._lock:
            self.store._check_open(); self.check(scope)
            if self.store._db.in_transaction: raise MemoryConflict('independent timeline snapshot required')
            self.store._db.execute('BEGIN')
            try:
                total = self.store._db.execute('SELECT COUNT(*) FROM tls_native_memories WHERE ' + where, args).fetchone()[0]
                if total > MAX_RECORDS: raise RuntimeError('timeline capacity exceeded')
                raw = self.store._db.execute('SELECT id FROM tls_native_memories WHERE ' + where + ' ORDER BY occurred DESC,id LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
                records = [self._project(self._record(scope, row[0])) for row in raw]
                self.check(scope)
            finally: self.store._db.execute('ROLLBACK')
        return dict(records=records, total=total, limit=limit, offset=offset, automatic_recall=False)

    def context_generation(self, scope):
        """Existing persistent revision counter plus external-connection epoch."""
        scope = self.check(scope)
        with self.store._lock:
            self.store._check_open()
            if self.store._db.in_transaction:
                raise MemoryConflict('independent timeline context generation required')
            now = _epoch(self.clock())
            where, args = self._where(scope)
            timed = self.store._db.execute('SELECT count(*),coalesce(sum(occurred>=?),0) FROM tls_native_memories WHERE ' + where +
                " AND lifecycle!='deleted' AND occurred<=? AND (expires IS NULL OR expires>?)"
                " AND json_type(data,'$.metadata.enabled')='true'"
                " AND json_extract(data,'$.metadata.evidence_category')='user_confirmed'"
                " AND json_type(data,'$.metadata.user_confirmed')='true'",
                (now-RECENT_SECONDS, *args, now, now)).fetchone()
            value = (id(self), id(self.store), id(self.store._db), self.store.data_generation(scope),
                     self.store._db.execute('PRAGMA data_version').fetchone()[0],
                     timed[0], timed[1])
            self.check(scope)
            return value

    def context_material(self, scope, *, query='', limit=4, max_chars=600):
        """Read a bounded, typed manual-reference snapshot; never change facts.

        Reuses the existing lexical terms, rather than another index/model.
        With no query only the newest two records within fourteen days qualify.
        """
        scope = self.check(scope)
        query = _text(query, 2000, empty=True)
        if type(limit) is not int or not 1 <= limit <= 4 or type(max_chars) is not int or not 160 <= max_chars <= 600:
            raise ValueError('bounded timeline context budget required')
        now = _epoch(self.clock())
        before = self.context_generation(scope)
        where, args = self._where(scope)
        where += (" AND lifecycle!='deleted' AND occurred<=? AND (expires IS NULL OR expires>?)"
                  " AND json_type(data,'$.metadata.enabled')='true'"
                  " AND json_extract(data,'$.metadata.evidence_category')='user_confirmed'"
                  " AND json_type(data,'$.metadata.user_confirmed')='true'")
        args += [now, now]
        terms = _tokens(query)
        if any(not term.startswith('c:') for term in terms):
            terms = {term: weight for term, weight in terms.items() if not term.startswith('c:')}
        terms = dict(tuple(terms.items())[:64])
        with self.store._lock:
            self.check(scope)
            if self.store._db.in_transaction: raise MemoryConflict('independent timeline material snapshot required')
            self.store._db.execute('BEGIN')
            try:
                if query and terms:
                    marks = ','.join('(?,?)' for _ in terms)
                    weights = tuple(value for item in terms.items() for value in item)
                    # Filter the source and exact eligibility before the bound,
                    # so unrelated action_result records cannot crowd it out.
                    rows = self.store._db.execute('WITH query_terms(token,weight) AS (VALUES ' + marks +
                        ') SELECT m.id,sum(q.weight) score FROM query_terms q JOIN tls_native_memory_terms t ON t.token=q.token '
                        'JOIN tls_native_memories m ON m.scope=t.scope AND m.id=t.record_id WHERE ' +
                        where.replace('scope=?', 'm.scope=?', 1) +
                        ' GROUP BY m.scope,m.id ORDER BY score DESC,m.occurred DESC,m.id LIMIT ?',
                        (*weights, *args, CONTEXT_CANDIDATES)).fetchall()
                    identities = [row['id'] for row in rows]
                    # Titles use the existing bounded metadata, not a new index.
                    if len(query) <= 120:
                        title_rows = self.store._db.execute('SELECT id FROM tls_native_memories WHERE ' + where +
                            " AND instr(lower(json_extract(data,'$.metadata.title')),?)>0 ORDER BY occurred DESC,id LIMIT ?",
                            (*args, query.casefold(), CONTEXT_CANDIDATES)).fetchall()
                        identities += [row['id'] for row in title_rows if row['id'] not in identities]
                elif not query:
                    rows = self.store._db.execute('SELECT id FROM tls_native_memories WHERE ' + where +
                        ' AND occurred>=? ORDER BY occurred DESC,id LIMIT ?', (*args, now - RECENT_SECONDS, 2)).fetchall()
                    identities = [row['id'] for row in rows]
                else:
                    identities = []
                records = []
                for identity in identities[:CONTEXT_CANDIDATES]:
                    raw = self._record(scope, identity)
                    records.append((self._project(raw), raw.get('expires_at')))
                self.check(scope)
            finally:
                self.store._db.execute('ROLLBACK')
        if self.context_generation(scope) != before:
            raise MemoryConflict('timeline changed during context snapshot')
        sections, selected, seen = [], [], set()
        used = 0
        for row, expires_at in records:
            if not row['context_eligible']: continue
            fields = row['fields']
            identity = _normal(fields['content'])
            if identity in seen: continue
            # Only display data. Escape markup so a record cannot terminate the
            # assembler's owned context block or masquerade as another source.
            prefix = '人工登记确认的经历参考（非传感目击、非逐字引语，不能改人格）：'
            body = html.escape(fields['title'] + '；' + fields['content'], quote=False)
            text = prefix + fields['occurred_at'] + ' ' + body
            remaining = max_chars - used
            if remaining < len(prefix) + 40: break
            text = text if len(text) <= remaining else text[:remaining - 1] + '…'
            expiry = min(now + 60, _epoch(expires_at)) if expires_at is not None else now + 60
            if not query: expiry = min(expiry, _epoch(fields['occurred_at']) + RECENT_SECONDS)
            if expiry <= now: continue
            sections.append(dict(id='timeline.' + hashlib.sha256(row['id'].encode()).hexdigest(), text=text, evidence_kind='user_reported',
                record_id=row['id'], revision=row['revision'], expires_at=expiry,
                content_key=hashlib.sha256(_normal(fields['content']).encode()).hexdigest()))
            selected.append(row['id']); seen.add(identity); used += len(text)
            if len(sections) == min(limit, 2 if not query else limit): break
        self.check(scope)
        if self.context_generation(scope) != before:
            raise MemoryConflict('timeline changed after context projection')
        return dict(sections=sections, selected_ids=selected, chars=used, generation=list(before),
            automatic_recall=False, requires_runtime_authorization=True,
            context_mode='confirmed_manual_reference', actually_used='unknown', source='tls.timeline')

    def history(self, scope, identity):
        scope = self.check(scope); self._record(scope, identity)
        rows = self.store.history(scope, identity)
        self.check(scope)
        return [dict(revision=row['revision'], operation=row['operation'], changed_at=row['changed_at'], record=self._project(row['record'])) for row in rows]

    def export(self, scope):
        scope = self.check(scope)
        result = self.list(scope, include_archived=True, limit=MAX_RECORDS)
        self.check(scope)
        return dict(schema='tls.native.shared_timeline.export.v1', scope=scope, records=result['records'],
                    generated_at=self.clock(), automatic_recall=False, sends=0, legacy_migrated=False)

    def stop(self): self.active = False
    def close(self): self.stop()  # Shared memory store remains caller-owned.
