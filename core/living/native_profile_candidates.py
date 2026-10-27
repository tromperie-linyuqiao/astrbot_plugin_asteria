"""Typed new-scope profile candidates in the existing native-memory database.

Actual classifier snapshots are inputs, never imports or an extraction request.
Old-domain records/evidence are not migrated. Automatic quality and explicit
administrator review remain distinct; ordinary NativeMemoryStore.write is not
used because its manual status is not an automatic profile review.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import re

from .models import canonical, plain, private_scope, scope_key
from .native_memory import NativeMemoryStore, NativeMemoryConflict, _normal, _tokens, _epoch, _iso
from .native_explicit_memory import _SENSITIVE, _FICTION, _INSTRUCTION

SOURCE_ID = 'tls.chat.profile_candidates'
STATUSES = ('pending', 'active', 'rejected', 'superseded')
PROFILE_TYPES = frozenset({'user_profile', 'user_preference', 'user_habit'})
SINGLE_VALUE_DIMENSIONS = frozenset({'preferred_address', 'name', 'birthday', 'birth_date',
    'occupation', 'profession', 'education', 'major', 'zodiac', 'zodiac_or_blood_type', 'blood_type'})
MAX_CANDIDATES, MAX_EVIDENCE = 200, 64
_P = 'tls_native_profile_'


def _text(value, limit, *, empty=False):
    if (type(value) is not str or len(value) > limit or not empty and not value.strip()
            or any(ord(char) < 32 and char not in '\t\n\r' for char in value)):
        raise ValueError('bounded profile text required')
    value.encode('utf8')
    return value


def _digest(value): return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()



def _profile_normal(value):
    # Same default _clean_value/normalize_profile_value path as old rule_v2;
    # do not reinterpret an SDK Persona or rewrite a value into another form.
    text = re.sub(r'\s+', ' ', value.replace('\u3000',' ')).strip()
    if len(text) > 112: text = text[:111].rstrip() + '…'
    trim = ' \t\r\n，,。！？!?；;：:、'
    text = text.strip(trim)
    pairs = (('“','”'),('‘','’'),('"','"'),("'","'"),('「','」'),('『','』'))
    while len(text) > 1 and any(text.startswith(a) and text.endswith(b) for a,b in pairs):
        text = text[1:-1].strip()
    return re.sub(r'\s+', ' ', text.strip(trim)[:80].casefold()).strip()


def _quality(metadata, value):
    score = metadata.get('extraction_quality_score')
    score = float(score) if type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1 else None
    proof = dict(extractor=metadata.get('extractor'), extraction_quality=metadata.get('extraction_quality'),
        evidence_strength=metadata.get('evidence_strength'), extraction_quality_score=score,
        quality_gate_passed=metadata.get('quality_gate_passed') is True,
        requested_state=metadata.get('profile_state') or metadata.get('profile_status'))
    qualified = (proof['extractor'] in ('rule_v1', 'rule_v2') and score is not None and score >= .75
        and proof['extraction_quality'] in ('explicit', 'confirmed', 'corroborated', 'inferred')
        and proof['evidence_strength'] in ('direct_statement', 'user_confirmed', 'multiple_independent_evidence', 'independent_evidence')
        and proof['quality_gate_passed'] and metadata.get('normalized_value') == _profile_normal(value))
    direct = (qualified and proof['requested_state'] == 'active' and proof['extraction_quality'] == 'explicit'
        and proof['evidence_strength'] == 'direct_statement' and score >= .8)
    required = metadata.get('required_evidence_count', 2)
    required = max(2, min(10, required)) if type(required) is int else 2
    return proof, bool(qualified), bool(direct), required


class NativeProfileCandidates:
    backend = 'native_profile_candidates'

    def __init__(self, existing_store, clock=None):
        if type(existing_store) is not NativeMemoryStore:
            raise ValueError('existing native memory store required')
        self.store = existing_store
        self.clock = self.store.clock if clock is None else clock
        if not callable(self.clock): raise ValueError('profile clock required')
        self.active = True
        statements = (
            'CREATE TABLE IF NOT EXISTS tls_native_profile_candidates(scope TEXT,id TEXT,dimension TEXT,status TEXT,revision INTEGER,updated REAL,data TEXT,PRIMARY KEY(scope,id))',
            'CREATE TABLE IF NOT EXISTS tls_native_profile_evidence(scope TEXT,id TEXT,message_id TEXT,statement TEXT,source_text TEXT,qualified INTEGER,quality TEXT,PRIMARY KEY(scope,id,message_id,statement))',
            'CREATE TABLE IF NOT EXISTS tls_native_profile_messages(scope TEXT,message_id TEXT,fingerprint TEXT,PRIMARY KEY(scope,message_id))',
            'CREATE TABLE IF NOT EXISTS tls_native_profile_operations(scope TEXT,kind TEXT,event_id TEXT,fingerprint TEXT,ids TEXT,PRIMARY KEY(scope,kind,event_id))',
            'CREATE TABLE IF NOT EXISTS tls_native_profile_reviews(scope TEXT,event_id TEXT,id TEXT,revision INTEGER,reviewer TEXT,action TEXT,created REAL,PRIMARY KEY(scope,event_id))',
            'CREATE TABLE IF NOT EXISTS tls_native_profile_terms(scope TEXT,id TEXT,term TEXT,weight REAL,PRIMARY KEY(scope,id,term))',
            'CREATE TABLE IF NOT EXISTS tls_native_profile_history(seq INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT,id TEXT,revision INTEGER,operation TEXT,data TEXT)',
        )
        with self.store.transaction():
            self._check()
            for statement in statements: self.store._db.execute(statement)

    def _check(self):
        if not self.active or self.store._closed: raise PermissionError('profile candidates closed')

    def _scope(self, scope):
        self._check(); return private_scope(scope)

    def _authorize(self, authorize):
        self._check()
        if not callable(authorize): raise PermissionError('current selected profile branch required')
        value = authorize()
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value): value.close()
            raise PermissionError('synchronous profile authorization required')
        if value is not True: raise PermissionError('profile branch unavailable')

    def _raw(self, key, identity):
        row = self.store._db.execute('SELECT data FROM tls_native_profile_candidates WHERE scope=? AND id=?',
                                     (key, identity)).fetchone()
        return json.loads(row[0]) if row is not None else None

    def _sources(self, key, identity):
        return [dict(message_id=row[0], statement_fingerprint=row[1], source_text=row[2], qualified=bool(row[3]),
                     quality=json.loads(row[4]), source_id=SOURCE_ID)
                for row in self.store._db.execute('SELECT message_id,statement,source_text,qualified,quality FROM tls_native_profile_evidence WHERE scope=? AND id=? ORDER BY rowid', (key, identity)).fetchall()]

    def _public(self, key, row):
        return dict(row, sources=self._sources(key, row['id']))

    def _save(self, key, row, operation):
        row = dict(row); row['revision'] += 1; row['updated_at'] = _epoch(self.clock())
        encoded = canonical(plain(row, 65536))
        self.store._db.execute('INSERT INTO tls_native_profile_candidates VALUES(?,?,?,?,?,?,?) ON CONFLICT(scope,id) DO UPDATE SET status=excluded.status,revision=excluded.revision,updated=excluded.updated,data=excluded.data',
            (key, row['id'], row['dimension'], row['status'], row['revision'], row['updated_at'], encoded))
        self.store._db.execute('DELETE FROM tls_native_profile_terms WHERE scope=? AND id=?', (key,row['id']))
        if row['status'] == 'active':
            self.store._db.executemany('INSERT INTO tls_native_profile_terms VALUES(?,?,?,?)',
                [(key,row['id'],term,weight) for term,weight in _tokens(row['content']).items()])
        self.store._db.execute('INSERT INTO tls_native_profile_history(scope,id,revision,operation,data) VALUES(?,?,?,?,?)',
            (key,row['id'],row['revision'],operation,encoded))
        return row

    def _activate(self, key, row):
        if row['dimension'] in SINGLE_VALUE_DIMENSIONS:
            others = self.store._db.execute('SELECT data FROM tls_native_profile_candidates WHERE scope=? AND dimension=? AND status=? AND id!=?',
                (key,row['dimension'],'active',row['id'])).fetchall()
            for item in others:
                old = json.loads(item[0]); old['status'] = old['review_status'] = 'superseded'
                old['superseded_by'] = row['id']; self._save(key,old,'superseded')
        row['status'] = 'active'

    def _record(self, scope, raw):
        if type(raw) is not dict or raw.get('memory_type') not in PROFILE_TYPES:
            raise ValueError('actual typed profile record required')
        metadata = raw.get('metadata')
        if type(metadata) is not dict: raise ValueError('profile metadata required')
        if (raw.get('scope') != 'private' or raw.get('platform') != scope['platform']
                or raw.get('session_id') != scope['session_id']
                or metadata.get('owner_bot_id',raw.get('owner_bot_id')) != scope['bot_id']
                or type(raw.get('subject')) is not dict or raw['subject'].get('kind') != 'user'
                or raw['subject'].get('id') != scope['user_id']
                or type(raw.get('object')) is not dict or raw['object'].get('kind') != 'user'
                or raw['object'].get('id') != scope['user_id']):
            raise PermissionError('actual classifier identity does not match private scope')
        dimension = _text(metadata.get('profile_dimension'),80).strip().lower()
        value = _text(metadata.get('profile_value'),240).strip()
        normalized = _text(metadata.get('normalized_value'),240)
        if normalized != _profile_normal(value): raise ValueError('profile normalized value mismatch')
        polarity = _text(metadata.get('profile_polarity'),40,empty=True).strip().lower()
        quality, qualified, direct, required = _quality(metadata,value)
        return dict(memory_type=raw['memory_type'],dimension=dimension,value=value,normalized_value=normalized,
                    polarity=polarity,quality=quality,qualified=qualified,direct=direct,required=required)

    def observe(self, scope, records, *, event_id, source_text, message_id, authorize=None):
        scope = self._scope(scope); key = scope_key(scope)
        event_id = _text(event_id,160); message_id = _text(message_id,256)
        source_text = _text(source_text,6000)
        if len(source_text.encode('utf8')) > 18000 or any(rule.search(source_text) for rule in _SENSITIVE) or _FICTION.search(source_text) or _INSTRUCTION.search(source_text):
            raise ValueError('unsafe profile source')
        if type(records) is not list or not 1 <= len(records) <= 16: raise ValueError('bounded profile batch required')
        selected = [self._record(scope,raw) for raw in records]
        fingerprint = _digest([message_id,source_text,selected]); statement = _digest(_normal(source_text))
        message_fingerprint = _digest(source_text)
        with self.store.transaction():
            self._authorize(authorize)
            old = self.store._db.execute('SELECT fingerprint,ids FROM tls_native_profile_operations WHERE scope=? AND kind=? AND event_id=?', (key,'observe',event_id)).fetchone()
            if old is not None:
                if old[0] != fingerprint: raise NativeMemoryConflict('profile event reused with changed input')
                identities = json.loads(old[1])
            else:
                previous_message = self.store._db.execute('SELECT fingerprint FROM tls_native_profile_messages WHERE scope=? AND message_id=?', (key,message_id)).fetchone()
                if previous_message is not None and previous_message[0] != message_fingerprint:
                    raise NativeMemoryConflict('profile message reused with changed source')
                self.store._db.execute('INSERT OR IGNORE INTO tls_native_profile_messages VALUES(?,?,?)', (key,message_id,message_fingerprint))
                identities = []
                for item in selected:
                    identity = 'profile_' + _digest([scope,item['memory_type'],item['dimension'],item['normalized_value'],item['polarity']])
                    if identity in identities: continue
                    identities.append(identity); row = self._raw(key,identity)
                    if row is None:
                        count = self.store._db.execute('SELECT COUNT(*) FROM tls_native_profile_candidates WHERE scope=?',(key,)).fetchone()[0]
                        if count >= MAX_CANDIDATES: raise ValueError('profile candidate capacity reached')
                        now = _epoch(self.clock())
                        row = dict(id=identity,scope=scope,source_id=SOURCE_ID,memory_type=item['memory_type'],
                            dimension=item['dimension'],value=item['value'],normalized_value=item['normalized_value'],polarity=item['polarity'],
                            content='用户画像陈述：%s %s' % (item['dimension'],item['value']),status='pending',review_status='pending',
                            revision=0,created_at=now,updated_at=now,reviewer=None,reviewed_at=None,review_event_id=None,
                            quality=item['quality'],reasons=['awaiting_qualified_evidence_or_review'],evidence_count=0,
                            evidence_refs=[],statement_fingerprints=[],superseded_by=None)
                    evidence = self.store._db.execute('SELECT 1 FROM tls_native_profile_evidence WHERE scope=? AND id=? AND message_id=? AND statement=?',(key,identity,message_id,statement)).fetchone()
                    if evidence is not None: continue
                    if len(self._sources(key,identity)) >= MAX_EVIDENCE: raise ValueError('profile evidence capacity reached')
                    self.store._db.execute('INSERT INTO tls_native_profile_evidence VALUES(?,?,?,?,?,?,?)',
                        (key,identity,message_id,statement,source_text,int(item['qualified']),canonical(item['quality'])))
                    sources = self._sources(key,identity); good = [part for part in sources if part['qualified']]
                    row['evidence_refs'] = list(dict.fromkeys(part['message_id'] for part in good))
                    row['statement_fingerprints'] = list(dict.fromkeys(part['statement_fingerprint'] for part in good))
                    row['evidence_count'] = min(len(row['evidence_refs']),len(row['statement_fingerprints']))
                    if row['status'] not in ('rejected','superseded') and row['review_status'] != 'approved':
                        if item['direct'] or row['evidence_count'] >= item['required']:
                            self._activate(key,row); row['review_status'] = 'auto'; row['reasons'] = ['direct_qualified_statement' if item['direct'] else 'independent_qualified_evidence']
                            best = max(good,key=lambda part:part['quality']['extraction_quality_score'])['quality']
                            row['quality'] = dict(best, **({} if item['direct'] else dict(extraction_quality='corroborated',evidence_strength='multiple_independent_evidence')))
                        elif row['status'] != 'active': row['reasons'] = ['awaiting_qualified_evidence_or_review']
                    self._save(key,row,'observe')
                self.store._db.execute('INSERT INTO tls_native_profile_operations VALUES(?,?,?,?,?)',(key,'observe',event_id,fingerprint,canonical(identities)))
            self._authorize(authorize)
            rows = [self._public(key,self._raw(key,identity)) for identity in identities]
        return dict(ok=True,state='observed_or_replayed',records=rows,candidate_ids=identities,source_id=SOURCE_ID)

    def get(self, scope, identity):
        scope = self._scope(scope); key = scope_key(scope); _text(identity,100)
        with self.store._lock:
            self._check(); row = self._raw(key,identity)
            return self._public(key,row) if row is not None else None

    def list(self, scope, *, status=None, query='', limit=100):
        scope = self._scope(scope); key = scope_key(scope)
        if status is not None and status not in STATUSES: raise ValueError('invalid profile status')
        _text(query,2000,empty=True)
        if type(limit) is not int or not 1 <= limit <= 100: raise ValueError('bounded profile list required')
        with self.store._lock:
            self._check()
            rows = self.store._db.execute('SELECT data FROM tls_native_profile_candidates WHERE scope=? ORDER BY updated DESC,id',(key,)).fetchall()
            values = [json.loads(row[0]) for row in rows]
            return [self._public(key,row) for row in values if (status is None or row['status']==status)
                    and (not query.strip() or _normal(query) in _normal(row['content']))][:limit]

    def review(self, scope, identity, *, action, expected_revision, reviewer, event_id):
        scope = self._scope(scope); key = scope_key(scope)
        _text(identity,100); _text(reviewer,120); _text(event_id,160)
        if action not in ('approve','reject') or type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('exact profile review action and revision required')
        fingerprint = _digest([identity,action,expected_revision,reviewer])
        with self.store.transaction():
            self._check()
            previous = self.store._db.execute('SELECT fingerprint FROM tls_native_profile_operations WHERE scope=? AND kind=? AND event_id=?',(key,'review',event_id)).fetchone()
            row = self._raw(key,identity)
            if row is None: raise KeyError(identity)
            if previous is not None:
                if previous[0] != fingerprint: raise NativeMemoryConflict('review event reused')
                return self._public(key,row)
            if row['revision'] != expected_revision: raise NativeMemoryConflict('stale profile review')
            row['reviewer'],row['reviewed_at'],row['review_event_id'] = reviewer,_epoch(self.clock()),event_id
            if action == 'approve':
                # This is new administrator evidence, not a rewrite of any
                # original classifier/source quality or its qualified count.
                original_quality = dict(row['quality'])
                score = original_quality.get('extraction_quality_score')
                score = float(score) if type(score) in (int,float) and math.isfinite(score) else .75
                row['quality'] = dict(original_quality, extraction_quality='confirmed',
                    evidence_strength='user_confirmed', quality_gate_passed=True,
                    extraction_quality_score=max(.75,min(1.,score)))
                self._activate(key,row); row['review_status']='approved'; row['reasons']=['administrator_approved']
            else: row['status']=row['review_status']='rejected'; row['reasons']=['administrator_rejected']
            row = self._save(key,row,'review_'+action)
            self.store._db.execute('INSERT INTO tls_native_profile_reviews VALUES(?,?,?,?,?,?,?)',(key,event_id,identity,row['revision'],reviewer,action,row['reviewed_at']))
            self.store._db.execute('INSERT INTO tls_native_profile_operations VALUES(?,?,?,?,?)',(key,'review',event_id,fingerprint,canonical([identity])))
            self._check(); return self._public(key,row)

    def data_generation(self, scope):
        try:
            scope = self._scope(scope); key = scope_key(scope)
            with self.store._lock:
                self._check(); row = self.store._db.execute('SELECT COALESCE(MAX(seq),0),COUNT(*) FROM tls_native_profile_history WHERE scope=?',(key,)).fetchone()
                return ('native_profile_candidates.v1',row[0],row[1])
        except (PermissionError,ValueError): return None

    def active_single_dimensions(self, scope):
        scope = self._scope(scope); key = scope_key(scope)
        with self.store._lock:
            self._check()
            rows = self.store._db.execute('SELECT dimension FROM tls_native_profile_candidates WHERE scope=? AND status=?', (key,'active')).fetchall()
            return frozenset(row[0] for row in rows if row[0] in SINGLE_VALUE_DIMENSIONS)

    def search(self, scope, query, *, limit=8):
        scope = self._scope(scope); key = scope_key(scope)
        _text(query,2000,empty=True)
        if type(limit) is not int or not 1 <= limit <= 64: raise ValueError('bounded profile search required')
        query_tokens = _tokens(query)
        tokens = set(sorted(query_tokens,key=lambda term:(-query_tokens[term],term))[:64])
        with self.store._lock:
            self._check(); rows = self.store._db.execute('SELECT data FROM tls_native_profile_candidates WHERE scope=? AND status=? ORDER BY updated DESC,id',(key,'active')).fetchall()
            result=[]
            for encoded in rows:
                row=json.loads(encoded[0])
                if row['review_status'] not in ('auto','approved'): continue
                score=sum(weight for term,weight in self.store._db.execute('SELECT term,weight FROM tls_native_profile_terms WHERE scope=? AND id=?',(key,row['id'])).fetchall() if term in tokens)
                if query.strip() and score<=0: continue
                quality=row['quality']; metadata=dict(quality,
                    profile_state='active',profile_status='active',profile_dimension=row['dimension'],profile_value=row['value'],
                    normalized_value=row['normalized_value'],profile_polarity=row['polarity'],independent_evidence_count=row['evidence_count'],
                    profile_qualified_evidence_refs=row['evidence_refs'],profile_qualified_statement_fingerprints=row['statement_fingerprints'],
                    native_profile_candidates=dict(schema=1,id=row['id'],revision=row['revision'],status=row['status'],
                        review_status=row['review_status'],evidence_count=row['evidence_count'],reviewer=row['reviewer'],review_event_id=row['review_event_id']))
                result.append((score,dict(id=row['id'],content=row['content'],memory_type=row['memory_type'],scope='private',
                    visibility='private_pair',owner_bot_id=scope['bot_id'],persona_id=scope['character_id'],platform=scope['platform'],session_id=scope['session_id'],
                    subject=dict(kind='user',id=scope['user_id']),object=dict(kind='bot',id=scope['bot_id']),source_id=SOURCE_ID,source_plugin='texas_living_system',
                    evidence_kind='user_reported',evidence=SOURCE_ID,reality_level='real_user_fact',confidence=quality.get('extraction_quality_score') or .75,
                    importance=.68,canonical_key=row['id'],occurred_at=_iso(row['created_at']),created_at=_iso(row['created_at']),updated_at=_iso(row['updated_at']),
                    valid_from=_iso(row['created_at']),valid_to='',expires_at=None,lifecycle='stable_memory',validity_status='active',review_status=row['review_status'],
                    sensitivity='private',sayability='direct',mention_policy='direct',revision=row['revision'],metadata=metadata)))
            return [row for _,row in sorted(result,key=lambda pair:-pair[0])[:limit]]

    def close(self):
        with self.store._lock: self.active=False
