"""Small, versioned fictional possessions and interests on the life journal.

No separate database, background work, network lookup, delivery or model call.
Operator citations are stored as provided; they never establish verified canon.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import ipaddress
from urllib.parse import urlsplit

from .autonomous_life import (AutonomousLife, EVIDENCE, _digest, _epoch, _id,
    _ids, _literal_excerpt, _query_terms, _revision, _text, _NS as _LIFE_NS,
    _LIMIT as _LIFE_LIMIT)
from .journal import JournalConflict
from .models import canonical, plain, private_scope, scope_key
from .personal_resources import valid_resource_identity

SOURCE = 'tls.personal_space'
KINDS = ('space', 'item', 'interest', 'exploration', 'collection')
_NS = {kind: 'tls.personal.' + kind + '.v1' for kind in KINDS}
_HISTORY = 'tls.personal.history.v1'
_EFFECTS = 'tls.personal.effects.v1'
_LIMIT = dict(space=32, item=256, interest=64, exploration=128, collection=256)
_SOURCE_KINDS = {'terra_canon', 'public_reference', 'original_fiction', 'model_inference'}
_DEFAULTS = dict(
    space=dict(environment='', area=''),
    item=dict(space_id='', origin='ordinary', giver='', gifted_at=None, message_ref=''),
    interest=dict(status='active', questions=[], explored=[], last_attended_at=None,
                  worth_continuing=True, shared_event_id='', origin_note='',
                  attention='steady', next_direction=''),
    exploration=dict(interest_id='', status='planned', goal='', findings=[],
                     source_kind='original_fiction', sources=[]),
    collection=dict(category='note', resource_id='', resource_type='', interest_id=''))


def _kind(value):
    if type(value) is not str or value not in KINDS:
        raise ValueError('supported personal-space kind required')
    return value


def _texts(value):
    if type(value) is not list or len(value) > 12:
        raise ValueError('bounded personal-space text list required')
    result = [_text(item, 400) for item in value]
    if len(result) != len(set(result)):
        raise ValueError('duplicate personal-space text')
    return result


def _optional_id(value):
    return '' if value == '' and type(value) is str else _id(value)


def _choice(value, choices):
    if type(value) is not str or value not in choices:
        raise ValueError('explicit supported personal-space choice required')
    return value


def _citation(value):
    if type(value) is not dict or set(value) != {'title', 'url', 'kind'}:
        raise ValueError('provided citation title, URL and kind required')
    title = _text(value['title'], 120)
    url = _text(value['url'], 2048)
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme not in {'http', 'https'} or not host or parsed.username
                or parsed.password or any(char.isspace() for char in url)
                or host.casefold() == 'localhost' or host.casefold().endswith('.local')
                or '.' not in host):
            raise ValueError('provided public HTTP citation required')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError('provided public HTTP citation required')
        parsed.port
    except (ValueError, TypeError) as exc:
        raise ValueError('provided public HTTP citation required') from exc
    return dict(title=title, url=url, kind=_choice(value['kind'], _SOURCE_KINDS))


class PersonalSpace:
    """Composition over AutonomousLife with its current private authority."""
    backend = 'personal_space'

    def __init__(self, life: AutonomousLife):
        if not isinstance(life, AutonomousLife):
            raise ValueError('existing AutonomousLife required')
        self.life, self.journal = life, life.journal
        life.personal_space = self

    def _scope(self, scope, operation='read'):
        return self.life._scope(scope, operation)

    def _fields(self, kind, value):
        _kind(kind)
        defaults = dict(description='', event_ids=[], character_ids=[], **deepcopy(_DEFAULTS[kind]))
        if (type(value) is not dict or 'name' not in value
                or set(value) - ({'name'} | set(defaults) | ({'resource_scope', 'resource_revision'} if kind == 'collection' else set()))):
            raise ValueError('supported personal-space fields and name required')
        fields = {**defaults, **deepcopy(value)}
        fields.update(name=_text(fields['name'], 120),
                      description=_text(fields['description'], 1200, empty=True),
                      event_ids=_ids(fields['event_ids']), character_ids=_ids(fields['character_ids']))
        if kind == 'space':
            for key in ('environment', 'area'):
                fields[key] = _text(fields[key], 400, empty=True)
        elif kind == 'item':
            fields['space_id'] = _optional_id(fields['space_id'])
            fields['giver'] = _text(fields['giver'], 120, empty=True)
            fields['message_ref'] = _text(fields['message_ref'], 256, empty=True)
            if fields['gifted_at'] is not None:
                fields['gifted_at'] = _epoch(fields['gifted_at'])
                if fields['gifted_at'] > self.life._now() + 30:
                    raise ValueError('recorded gift timestamp required')
            _choice(fields['origin'], {'ordinary', 'selected', 'user_gift', 'event'})
            if fields['origin'] == 'user_gift' and not all(
                    fields[key] for key in ('giver', 'gifted_at', 'message_ref')):
                raise ValueError('operator-reported giver, gift time and message reference required')
            if fields['origin'] == 'event' and not fields['event_ids']:
                raise ValueError('event-acquired item must cite a recorded life event')
        elif kind == 'interest':
            _choice(fields['status'], {'active', 'paused', 'completed'})
            for key in ('questions', 'explored'):
                fields[key] = _texts(fields[key])
            if fields['last_attended_at'] is not None:
                fields['last_attended_at'] = _epoch(fields['last_attended_at'])
                if fields['last_attended_at'] > self.life._now() + 30:
                    raise ValueError('recorded interest timestamp required')
            if type(fields['worth_continuing']) is not bool:
                raise ValueError('exact interest continuation flag required')
            fields['shared_event_id'] = _optional_id(fields['shared_event_id'])
            _choice(fields['attention'], {'growing', 'steady', 'fading'})
            for key in ('origin_note', 'next_direction'):
                fields[key] = _text(fields[key], 800, empty=True)
        elif kind == 'exploration':
            fields['interest_id'] = _optional_id(fields['interest_id'])
            fields['goal'] = _text(fields['goal'], 800, empty=True)
            fields['findings'] = _texts(fields['findings'])
            _choice(fields['status'], {'planned', 'active', 'completed', 'paused', 'cancelled'})
            _choice(fields['source_kind'], _SOURCE_KINDS)
            if type(fields['sources']) is not list or len(fields['sources']) > 8:
                raise ValueError('at most eight provided citations required')
            fields['sources'] = [_citation(value) for value in fields['sources']]
        else:
            _choice(fields['category'], {'music', 'book', 'image', 'place', 'note', 'event', 'topic'})
            fields['resource_id'] = _text(fields['resource_id'], 128, empty=True)
            fields['resource_type'] = _text(fields['resource_type'], 40, empty=True)
            fields['interest_id'] = _optional_id(fields['interest_id'])
            if 'resource_scope' in fields:
                fields['resource_scope'] = private_scope(fields['resource_scope'])
            if 'resource_revision' in fields:
                _revision(fields['resource_revision'])
                if not valid_resource_identity(fields['resource_type'], fields['resource_id']):
                    raise ValueError('versioned native resource identity and type required')
        return fields

    def _resource(self, scope, fields, cache=None):
        if not fields.get('resource_id'):
            return None
        resources = getattr(self.life, 'personal_resources', None)
        if resources is not None:
            key = ('resource', canonical(fields))
            if cache is not None and key in cache:
                return deepcopy(cache[key])
            result = resources.resolve(scope, fields)
            if cache is not None:
                cache[key] = deepcopy(result)
            return result
        return dict(id=fields['resource_id'], type=fields.get('resource_type', ''),
            status='unverified', state='unverified', available=False, revision=None,
            expected_revision=fields.get('resource_revision'), name='', description='', metadata={})

    @staticmethod
    def _identity(kind, scope, request_id):
        return 'personal.' + kind + '.' + _digest([scope, request_id])[:40]

    def _row(self, scope, kind, identity):
        row = self.journal.fetch(_NS[_kind(kind)], _id(identity), scope)
        if row is None:
            return None
        data = row['data']
        if (type(data) is not dict or data.get('schema') != 1 or data.get('kind') != kind
                or data.get('id') != identity or data.get('scope') != scope
                or data.get('evidence_kind') != EVIDENCE or type(data.get('archived')) is not bool
                or type(data.get('deleted')) is not bool or type(data.get('dependencies')) is not list):
            raise RuntimeError('invalid personal-space record')
        _revision(data.get('version'))
        self._fields(kind, data['fields'])
        return row

    def _invalid(self, scope, data, seen=None, cache=None):
        cache = {} if cache is None else cache
        key = (data['kind'], data['id'], data['version'])
        if key in cache:
            return deepcopy(cache[key])
        seen = set() if seen is None else set(seen)
        if key in seen:
            return [dict(kind=data['kind'], id=data['id'], reason='dependency_cycle')]
        seen.add(key)
        invalid = []
        for ref in data['dependencies']:
            if (type(ref) is not dict or set(ref) != {'kind', 'id', 'version'}
                    or ref['kind'] not in {'event', 'character', 'space', 'interest'}):
                raise RuntimeError('invalid personal-space dependency')
            life_ref = ref['kind'] in {'event', 'character'}
            target = self.life._row(ref['kind'], scope, ref['id']) if life_ref else self._row(scope, ref['kind'], ref['id'])
            if target is None:
                reason = 'missing_source'
            elif target['data']['archived'] or target['data'].get('deleted'):
                reason = 'archived_source'
            elif target['data'].get('identity_revision' if ref['kind'] == 'character' else 'version') != ref['version']:
                reason = 'source_corrected'
            elif ref['kind'] == 'event' and self.life._invalid(scope, target['data']):
                reason = 'source_needs_review'
            elif not life_ref and self._invalid(scope, target['data'], seen, cache):
                reason = 'source_needs_review'
            else:
                continue
            invalid.append(dict(ref, reason=reason))
        resource = self._resource(scope, data['fields'], cache) if data['kind'] == 'collection' else None
        if resource and data['fields'].get('resource_revision') is not None and resource['status'] != 'available':
            invalid.append(dict(kind='resource', id=resource['id'], version=data['fields']['resource_revision'],
                reason={'changed': 'source_corrected', 'missing': 'missing_source',
                        'archived': 'archived_source', 'denied': 'denied_source',
                        'unverified': 'unverified_source'}[resource['status']]))
        cache[key] = deepcopy(invalid)
        return invalid

    def _references(self, scope, fields, pending=None):
        if fields.get('resource_scope') is not None and fields['resource_scope'] != scope and fields.get('resource_revision') is None:
            raise ValueError('foreign resources require verified native metadata revision')
        if fields.get('resource_revision') is not None:
            resource = self._resource(scope, fields)
            if resource is None or resource['status'] != 'available':
                raise ValueError('current authorized resource metadata revision required')
        refs = self.life._references('thread', scope, dict(
            event_ids=list(dict.fromkeys(fields['event_ids'] + ([fields['shared_event_id']] if fields.get('shared_event_id') else []))),
            character_ids=fields['character_ids']))
        for field, kind in (('space_id', 'space'), ('interest_id', 'interest')):
            if not fields.get(field):
                continue
            staged = None if pending is None else pending.get((kind, fields[field]))
            row = dict(data=staged) if staged is not None else self._row(scope, kind, fields[field])
            if row is None or row['data']['archived'] or row['data']['deleted'] or self._invalid(scope, row['data']):
                raise ValueError('current personal-space reference required')
            refs.append(dict(kind=kind, id=fields[field], version=row['data']['version']))
        return refs

    def _project(self, scope, row, cache=None):
        if row is None:
            return None
        cache = {} if cache is None else cache
        data = deepcopy(row['data'])
        data.pop('source_snapshots', None)
        invalid = self._invalid(scope, data, cache=cache)
        data.update(revision=row['revision'], updated_at=row['updated_at'],
                    valid=not data['archived'] and not data['deleted'] and not invalid,
                    invalid_reasons=invalid, fictional=True)
        if data['kind'] == 'item' and data['fields']['origin'] == 'user_gift':
            data['attribution'] = dict(status='operator_reported', verified=False,
                **{key: data['fields'][key] for key in ('giver', 'gifted_at', 'message_ref')})
        if data['kind'] == 'exploration':
            data.update(source_verification='provided_unverified', canon_verified=False)
        if data['kind'] == 'collection':
            # Retained provider snapshots are internal review provenance.
            # Do not expose stale remote metadata after source revocation.
            data.pop('resource_snapshot', None)
            resource = self._resource(scope, data['fields'], cache)
            if resource is not None:
                data['resource'] = resource
        return data

    def _capture_sources(self, scope, dependencies, pending=None):
        # Retain exact checkpoint revisions, not another copy of up to sixteen
        # full source texts. The journal already preserves their old snapshots.
        snapshots = []
        for ref in dependencies:
            staged = None if pending is None else pending.get((ref['kind'], ref['id']))
            if staged is not None:
                revision = staged['version']
            else:
                row = (self.life._row(ref['kind'], scope, ref['id']) if ref['kind'] in {'event', 'character'}
                       else self._row(scope, ref['kind'], ref['id']))
                revision = None if row is None else row['revision']
            snapshots.append(dict(**ref, revision=revision))
        return snapshots

    def _new(self, scope, kind, request_id, fields, source):
        if kind == 'item' and fields['origin'] == 'user_gift' and source['kind'] not in {'operator', 'user_correction'}:
            raise ValueError('user gifts require operator-reported attribution')
        data = dict(schema=1, id=self._identity(kind, scope, request_id), kind=kind, scope=scope,
            fields=fields, source=source, evidence_kind=EVIDENCE, archived=False, deleted=False,
            version=1, created_at=self.life._now(), dependencies=self._references(scope, fields),
            request_id=request_id, request_fingerprint=_digest([fields, source]))
        if kind == 'collection' and fields.get('resource_revision') is not None:
            data['resource_snapshot'] = self._resource(scope, fields)
        data['source_snapshots'] = self._capture_sources(scope, data['dependencies'])
        return data

    def _write(self, db, scope, pending, *, reason, actor, receipt=None):
        """Called inside exactly one journal transaction; history and rows commit together."""
        actor, reason = _text(actor, 120), _text(reason, 400)
        if not self.life._allowed(scope, 'write'):
            raise PermissionError('personal-space authority changed')
        def check_resources():
            for kind, data, _ in pending:
                if (kind == 'collection' and not data['archived'] and not data['deleted']
                        and data['fields'].get('resource_revision') is not None):
                    resource = self._resource(scope, data['fields'])
                    if resource is None or resource['status'] != 'available':
                        raise PermissionError('current resource authority or revision changed')
        check_resources()
        normalized, now = scope_key(scope), self.life._now()
        histories = []
        for kind, data, old in pending:
            if old:
                key = kind + '.' + data['id'] + '.' + str(old['revision'])
                histories.append((key, dict(kind=kind, id=data['id'], revision=old['revision'], snapshot=old['data'],
                    replaced_at=now, reason=reason, actor=actor)))
        required = sum(old is None for _, _, old in pending) + len(histories) + (receipt is not None)
        count = db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
        if count + required > self.journal.max_records:
            raise RuntimeError('journal capacity reached; personal-space history retained')
        for kind in KINDS:
            count = db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?', (_NS[kind], normalized)).fetchone()[0]
            if count + sum(k == kind and old is None for k, _, old in pending) > _LIMIT[kind]:
                raise RuntimeError('personal-space record capacity reached')
        for key, data in histories:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                (_HISTORY, key, normalized, 1, now, canonical(plain(data, 65536))))
        for kind, data, old in pending:
            data['last_edit'] = dict(actor=actor, reason=reason, at=now)
            encoded = canonical(plain(data, 65536))
            if old:
                changed = db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND key=? AND scope=? AND revision=?',
                    (old['revision'] + 1, now, encoded, _NS[kind], data['id'], normalized, old['revision']))
                if changed.rowcount != 1:
                    raise JournalConflict('personal-space revision changed')
            else:
                db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)', (_NS[kind], data['id'], normalized, 1, now, encoded))
        if receipt is not None:
            key, data = receipt
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)', (_EFFECTS, key, normalized, 1, now, canonical(plain(data, 65536))))
        if not self.life._allowed(scope, 'write'):
            raise PermissionError('personal-space authority changed')
        check_resources()

    def create(self, scope, kind, request_id, fields, source=None):
        scope, kind = self._scope(scope, 'write'), _kind(kind)
        request_id = _text(request_id, 128)
        fields, source = self._fields(kind, fields), self.life._source(source, request_id)
        identity = self._identity(kind, scope, request_id)
        with self.journal._transaction() as db:
            old = self._row(scope, kind, identity)
            if old:
                if old['data']['request_fingerprint'] != _digest([fields, source]):
                    raise JournalConflict('personal-space request already has different content')
            else:
                data = self._new(scope, kind, request_id, fields, source)
                self._write(db, scope, [(kind, data, None)], reason='created personal-space record', actor=source['kind'])
            self._scope(scope, 'write')
        return self.get_record(scope, kind, identity)

    def update(self, scope, kind, id, expected_revision, changes, reason, actor='operator'):
        scope, kind = self._scope(scope, 'write'), _kind(kind)
        _revision(expected_revision)
        if type(changes) is not dict or not changes:
            raise ValueError('explicit personal-space changes required')
        with self.journal._transaction() as db:
            old = self._row(scope, kind, id)
            if old is None:
                raise KeyError('personal-space record missing')
            if old['revision'] != expected_revision:
                raise JournalConflict('personal-space revision changed')
            if old['data']['deleted']:
                raise ValueError('restore deleted personal-space record before editing')
            fields = self._fields(kind, {**old['data']['fields'], **changes})
            if kind == 'item' and fields['origin'] == 'user_gift' and actor not in {'operator', 'user', 'user_correction'}:
                raise ValueError('user gifts require operator-reported attribution')
            data = deepcopy(old['data'])
            data.update(fields=fields, dependencies=self._references(scope, fields), version=data['version'] + 1)
            data['source_snapshots'] = self._capture_sources(scope, data['dependencies'])
            if kind == 'collection' and fields.get('resource_revision') is not None:
                data['resource_snapshot'] = self._resource(scope, fields)
            self._write(db, scope, [(kind, data, old)], reason=reason, actor=actor)
        return self.get_record(scope, kind, id)

    def archive(self, scope, kind, id, expected_revision, archived=True, reason='archive state changed', actor='operator'):
        scope, kind = self._scope(scope, 'write'), _kind(kind)
        _revision(expected_revision)
        if type(archived) is not bool:
            raise ValueError('exact archive state required')
        with self.journal._transaction() as db:
            old = self._row(scope, kind, id)
            if old is None:
                raise KeyError('personal-space record missing')
            if old['revision'] != expected_revision:
                raise JournalConflict('personal-space revision changed')
            if old['data']['archived'] != archived or not archived and old['data']['deleted']:
                data = deepcopy(old['data'])
                data.update(archived=archived, deleted=old['data']['deleted'] if archived else False, version=data['version'] + 1)
                self._write(db, scope, [(kind, data, old)], reason=reason, actor=actor)
            self._scope(scope, 'write')
        return self.get_record(scope, kind, id)

    def delete(self, scope, kind, id, expected_revision, reason, actor='operator'):
        scope, kind = self._scope(scope, 'write'), _kind(kind)
        _revision(expected_revision)
        with self.journal._transaction() as db:
            old = self._row(scope, kind, id)
            if old is None:
                raise KeyError('personal-space record missing')
            if old['revision'] != expected_revision:
                raise JournalConflict('personal-space revision changed')
            if not old['data']['deleted']:
                data = deepcopy(old['data'])
                data.update(archived=True, deleted=True, version=data['version'] + 1)
                self._write(db, scope, [(kind, data, old)], reason=reason, actor=actor)
            self._scope(scope, 'write')
        return self.get_record(scope, kind, id)

    def get_record(self, scope, kind, id):
        scope = self._scope(scope)
        result = self._project(scope, self._row(scope, kind, id))
        self._scope(scope)
        return result

    def list_records(self, scope, kind, query='', include_archived=False, include_invalid=False, limit=30, offset=0, status='', category='', sort='updated'):
        scope = self._scope(scope)
        kinds = KINDS if type(kind) is str and kind == 'all' else (_kind(kind),)
        query = _text(query, 300, empty=True)
        if type(include_archived) is not bool or type(include_invalid) is not bool:
            raise ValueError('exact personal-space list flags required')
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 1000:
            raise ValueError('bounded personal-space page required')
        _choice(status, {'', 'active', 'paused', 'completed', 'planned', 'cancelled'})
        _choice(category, {'', 'music', 'book', 'image', 'place', 'note', 'event', 'topic'})
        _choice(sort, {'updated', 'created', 'name'})
        records, cache, terms = [], {}, _query_terms(query)
        with self.journal._lock:
            for selected_kind in kinds:
                for row in self.journal.list(_NS[selected_kind], scope, limit=_LIMIT[selected_kind] + 1):
                    record = self._project(scope, self._row(scope, selected_kind, row['key']), cache)
                    if (not include_archived and (record['archived'] or record['deleted'])
                            or not include_invalid and record['invalid_reasons']):
                        continue
                    if status and record['fields'].get('status') != status or category and record['fields'].get('category') != category:
                        continue
                    text = canonical(record['fields']).casefold()
                    if query and not (terms and any(term in text for term in terms) or query.casefold() in text):
                        continue
                    records.append(record)
            records.sort(key=lambda record: ((record['fields']['name'].casefold() if sort == 'name' else
                -record['created_at'] if sort == 'created' else -record['updated_at']), record['id']))
            self._scope(scope)
        return dict(records=records[offset:offset + limit], total=len(records), limit=limit, offset=offset, evidence_kind=EVIDENCE)

    def archive_links(self, scope, record):
        """Current same-scope archive edges; no copied resources or inferred interests."""
        scope = self._scope(scope)
        fields, identity, kind = record['fields'], record['id'], record['kind']
        result = []
        with self.journal._lock:
            for target_kind, field in (('space', 'space_id'), ('interest', 'interest_id')):
                if fields.get(field):
                    target = self.get_record(scope, target_kind, fields[field])
                    if target and not target['archived'] and not target['deleted']:
                        result.append(target)
            incoming = ('collection', 'exploration') if kind == 'interest' else ('item',) if kind == 'space' else ()
            for target_kind in incoming:
                # Page the retained store, including records needing source review.
                rows = self.list_records(scope, target_kind, include_invalid=True, limit=200)['records']
                if _LIMIT[target_kind] > 200:
                    rows += self.list_records(scope, target_kind, include_invalid=True, limit=200, offset=200)['records']
                field = 'interest_id' if kind == 'interest' else 'space_id'
                result.extend(row for row in rows if row['fields'].get(field) == identity)
            self._scope(scope)
        return result

    def history(self, scope, kind, id, limit=20):
        scope, kind = self._scope(scope), _kind(kind)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('bounded personal-space history required')
        current = self._row(scope, kind, id)
        records = []
        if current:
            for revision in range(current['revision'] - 1, max(0, current['revision'] - 1 - limit), -1):
                row = self.journal.fetch(_HISTORY, kind + '.' + id + '.' + str(revision), scope)
                if row:
                    entry = deepcopy(row['data'])
                    # Provider snapshots stay in retained provenance, while
                    # the review facade controls fresh source authorization.
                    entry.get('snapshot', {}).pop('resource_snapshot', None)
                    entry.get('snapshot', {}).pop('source_snapshots', None)
                    records.append(entry)
        self._scope(scope)
        return dict(records=records, total=current['revision'] - 1 if current else 0)

    def generation(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            values = [_digest([[kind, row['key'], row['revision']]
                for row in self.journal.list(_NS[kind], scope, limit=_LIMIT[kind] + 1)]) for kind in KINDS]
            # Life's aggregate token may include this module. Read source
            # revisions directly so neither aggregate recursively calls itself.
            life_values = [_digest([[kind, row['key'], row['revision']]
                for row in self.journal.list(_LIFE_NS[kind], scope, limit=_LIFE_LIMIT.get(kind, 1) + 1)])
                for kind in ('event', 'character', 'thread', 'policy')]
            resources, seen = [], set()
            for row in self.journal.list(_NS['collection'], scope, limit=_LIMIT['collection'] + 1):
                fields = row['data']['fields']
                if not fields.get('resource_revision') or not fields.get('resource_id'):
                    continue
                key = canonical([fields.get('resource_scope', scope), fields.get('resource_type'),
                                 fields['resource_id'], fields['resource_revision']])
                if key not in seen:
                    seen.add(key)
                    resource = self._resource(scope, fields)
                    resources.append([key, resource['status'], resource['revision']])
            self._scope(scope)
            return _digest([values, life_values, resources])

    def list_review(self, scope, query='', limit=30, offset=0):
        """Only active records whose captured sources need human review."""
        scope = self._scope(scope)
        query = _text(query, 300, empty=True)
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 1000:
            raise ValueError('bounded personal-space review page required')
        records, cache = [], {}
        with self.journal._lock:
            for kind in KINDS:
                for row in self.journal.list(_NS[kind], scope, limit=_LIMIT[kind] + 1):
                    record = self._project(scope, self._row(scope, kind, row['key']), cache)
                    if record['archived'] or record['deleted'] or not record['invalid_reasons']:
                        continue
                    if query and query.casefold() not in canonical(record['fields']).casefold():
                        continue
                    records.append(record)
            records.sort(key=lambda row: (-row['updated_at'], row['id']))
            self._scope(scope)
        return dict(records=records[offset:offset + limit], total=len(records), limit=limit,
                    offset=offset, evidence_kind=EVIDENCE)

    @staticmethod
    def _review_snapshot(data, revision=None):
        if data is None:
            return None
        keys = ('kind', 'id', 'version', 'identity_revision', 'fields', 'dependencies', 'archived', 'deleted')
        result = {key: deepcopy(data[key]) for key in keys if key in data}
        if revision is not None:
            result['revision'] = revision
        return result

    def _previous_source(self, scope, ref, current, captured_revision=None):
        """Read retained provenance; unavailable snapshots are explicit."""
        version_key = 'identity_revision' if ref['kind'] == 'character' else 'version'
        namespace = _LIFE_NS['history'] if ref['kind'] in {'event', 'character'} else _HISTORY
        if captured_revision is not None:
            if current and current['revision'] == captured_revision:
                return self._review_snapshot(current['data'], current['revision'])
            old = self.journal.fetch(namespace, ref['kind'] + '.' + ref['id'] + '.' + str(captured_revision), scope)
            if old and old['data'].get('snapshot', {}).get(version_key) == ref['version']:
                return self._review_snapshot(old['data']['snapshot'], old['data'].get('revision'))
            return dict(kind=ref['kind'], id=ref['id'], version=ref['version'], snapshot_available=False)
        if current and current['data'].get(version_key) == ref['version']:
            return self._review_snapshot(current['data'], current['revision'])
        # Event/personal version and revision advance together. Character
        # identity revisions deliberately do not advance on every text edit.
        if ref['kind'] != 'character':
            old = self.journal.fetch(namespace, ref['kind'] + '.' + ref['id'] + '.' + str(ref['version']), scope)
            if old and old['data'].get('snapshot', {}).get(version_key) == ref['version']:
                return self._review_snapshot(old['data']['snapshot'], old['data'].get('revision'))
        else:
            rows = self.journal._db.execute(
                'SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key LIKE ? ORDER BY revision DESC LIMIT ?',
                (namespace, scope_key(scope), ref['kind'] + '.' + ref['id'] + '.%', self.journal.max_records)).fetchall()
            import json
            for row in rows:
                history = json.loads(row['data'])
                snapshot = history.get('snapshot', {})
                if (snapshot.get(version_key) == ref['version'] and snapshot.get('id') == ref['id']
                        and snapshot.get('kind') == ref['kind']):
                    return self._review_snapshot(snapshot, history.get('revision'))
        return dict(kind=ref['kind'], id=ref['id'], version=ref['version'], snapshot_available=False)

    def _review_payload(self, scope, kind, identity):
        row = self._row(scope, kind, identity)
        if row is None:
            raise KeyError('personal-space record missing')
        record, sources, blocked, seen = self._project(scope, row), [], [], set()
        if record['archived'] or record['deleted']:
            blocked.append(dict(kind=kind, id=identity, reason='record_archived'))

        def visit(data):
            captured = {(value['kind'], value['id'], value['version']): value.get('revision')
                        for value in data.get('source_snapshots', [])}
            for ref in data['dependencies']:
                key = (ref['kind'], ref['id'], ref['version'])
                if key in seen:
                    continue
                seen.add(key)
                life_ref = ref['kind'] in {'event', 'character'}
                target = self.life._row(ref['kind'], scope, ref['id']) if life_ref else self._row(scope, ref['kind'], ref['id'])
                current = None if target is None else self._review_snapshot(target['data'], target['revision'])
                if target is None:
                    status = 'missing'
                elif target['data']['archived'] or target['data'].get('deleted'):
                    status = 'archived'
                else:
                    invalid = (self.life._invalid(scope, target['data']) if life_ref else self._invalid(scope, target['data']))
                    current['invalid_reasons'] = invalid
                    actual_version = target['data'].get('identity_revision' if ref['kind'] == 'character' else 'version')
                    status = ('needs_review' if invalid else 'changed' if actual_version != ref['version'] else 'available')
                previous = self._previous_source(scope, ref, target, captured.get(key))
                sources.append(dict(kind=ref['kind'], id=ref['id'], previous=deepcopy(previous),
                                    current=current, status=status))
                if status not in {'available', 'changed'}:
                    blocked.append(dict(kind=ref['kind'], id=ref['id'], reason=status))
                if target is not None:
                    visit(target['data'])

        visit(row['data'])
        resource = record.get('resource')
        if resource:
            previous = deepcopy(row['data'].get('resource_snapshot', dict(
                id=resource['id'], type=resource['type'], revision=resource['expected_revision'], snapshot_available=False)))
            if resource['status'] not in {'available', 'changed'}:
                previous = {key: previous[key] for key in ('id', 'type', 'revision', 'snapshot_available') if key in previous}
            sources.append(dict(kind='resource', id=resource['id'], previous=previous,
                                current=deepcopy(resource), status=resource['status']))
            if resource['status'] not in {'available', 'changed'}:
                blocked.append(dict(kind='resource', id=resource['id'], reason=resource['status']))
        # Hash each bounded snapshot independently: the retained dependency
        # graph can legitimately exceed one JSON object's validation budget.
        token = _digest([scope, kind, identity, row['revision']])
        for value in [*sources, *blocked]:
            token = _digest([token, value])
        return dict(record=record, sources=sources, source_token=token, can_confirm=not blocked,
                    blocked_reasons=blocked, semantic_rewrite=False, evidence_kind=EVIDENCE)

    def review_preview(self, scope, kind, id):
        scope, kind = self._scope(scope), _kind(kind)
        with self.journal._lock:
            result = self._review_payload(scope, kind, id)
            self._scope(scope)
            return result

    def confirm_review(self, scope, kind, id, expected_revision, source_token, reason,
                       changes=None, confirmed=True, actor='operator'):
        """Explicit human acknowledgement; no model/semantic rewriting occurs."""
        scope, kind = self._scope(scope, 'write'), _kind(kind)
        if confirmed is not True:
            raise ValueError('literal explicit review confirmation required')
        _revision(expected_revision)
        source_token, reason, actor = _text(source_token, 64), _text(reason, 400), _text(actor, 120)
        changes = {} if changes is None else deepcopy(changes)
        if type(changes) is not dict:
            raise ValueError('explicit personal-space review changes required')
        if 'resource_revision' in changes:
            raise ValueError('resource revision is refreshed from actual metadata only')
        with self.journal._transaction() as db:
            preview = self._review_payload(scope, kind, id)
            if preview['record']['revision'] != expected_revision or preview['source_token'] != source_token:
                raise JournalConflict('personal-space review sources changed; preview again')
            if not preview['can_confirm']:
                raise ValueError('current available valid review sources required')
            old = self._row(scope, kind, id)
            data = deepcopy(old['data'])
            fields = self._fields(kind, {**data['fields'], **changes})
            if kind == 'collection' and fields.get('resource_revision') is not None:
                resource = self._resource(scope, fields)
                if resource is None or resource['status'] not in {'available', 'changed'}:
                    raise ValueError('current authorized resource metadata required')
                fields['resource_revision'] = resource['revision']
                data['resource_snapshot'] = self._resource(scope, fields)
            data.update(fields=fields, dependencies=self._references(scope, fields), version=data['version'] + 1)
            data['source_snapshots'] = self._capture_sources(scope, data['dependencies'])
            # Recheck the complete original source graph before the single
            # write, including authority callbacks that can be revoked live.
            if self._review_payload(scope, kind, id)['source_token'] != source_token:
                raise JournalConflict('personal-space review sources changed; preview again')
            self._write(db, scope, [(kind, data, old)], reason=reason, actor=actor)
            if kind == 'collection' and fields.get('resource_revision') is not None:
                resource = self._resource(scope, fields)
                if resource is None or resource['status'] != 'available':
                    raise PermissionError('resource source authority changed during review')
            self._scope(scope, 'write')
        return self.get_record(scope, kind, id)

    def context_material(self, scope, query='', max_chars=600, limit=3):
        scope = self._scope(scope)
        query = _text(query, 300, empty=True)
        if type(max_chars) is not int or not 64 <= max_chars <= 4000 or type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError('bounded personal-space context required')
        with self.journal._lock:
            generation = self.generation(scope)
            records = [record for kind in KINDS for record in self.list_records(scope, kind, query=query, limit=200)['records']]
            terms = _query_terms(query)
            records.sort(key=lambda row: (-sum(term in canonical(row['fields']).casefold() for term in terms),
                KINDS.index(row['kind']), -row['updated_at'], row['id']))
            sections, refs, used = [], [], 0
            selected = records[:limit]
            for index, record in enumerate(selected):
                remaining = max_chars - used - (1 if sections else 0)
                remaining //= len(selected) - index
                prefix = '[虚构个人空间 ' + record['kind'] + '；引用未核验] '
                excerpt = _literal_excerpt(canonical(record['fields']), remaining - len(prefix))
                if not excerpt:
                    break
                text = prefix + excerpt
                ref = dict(kind=record['kind'], id=record['id'], version=record['version'], revision=record['revision'])
                sections.append(dict(id='personal.' + _digest([record['kind'], record['id']])[:32], text=text,
                    source=SOURCE, source_kind=record['kind'], source_id=record['id'], source_version=record['version'],
                    source_revision=record['revision'], source_refs=[ref, *deepcopy(record['dependencies'])],
                    evidence_kind=EVIDENCE, expires_at=self.life._now() + 300))
                refs.extend([ref, *deepcopy(record['dependencies'])])
                used += len(text) + (1 if len(sections) > 1 else 0)
            self._scope(scope)
            text = '\n'.join(section['text'] for section in sections)
            return dict(text=text, sections=sections, source_versions=refs,
                selected_record_ids=[section['source_id'] for section in sections], generation=generation,
                evidence_kind=EVIDENCE, deterministic=True, writes_memory=False, chars=len(text))

    def decision(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            now = self.life._now()
            events = self.life.list_events(scope, limit=200)['records']
            # The list ABI pages at 200 while the retained event ledger is
            # bounded at 512. Include older real thread sources in the preview.
            for offset in range(200, _LIFE_LIMIT['event'], 200):
                events.extend(self.life.list_events(scope, limit=200, offset=offset)['records'])
            threads = self.life.list_threads(scope, status='open', limit=128)['records']
            people = self.life.list_characters(scope, limit=64)['records']
            interests = self.list_records(scope, 'interest', limit=64)['records']
            explorations = self.list_records(scope, 'exploration', limit=128)['records']
            collections = self.list_records(scope, 'collection', limit=200)['records']
            candidates = []
            def option(action, record, priority, eligible, reason):
                candidates.append(dict(action=action, kind=record['kind'], id=record['id'], version=record['version'],
                    revision=record['revision'], name=record['fields'].get('name', record['fields'].get('title', '')),
                    priority=priority, eligible=eligible, reason=reason))
            event_times = {row['id']: row['fields']['occurred_at'] for row in events}
            for row in explorations:
                if row['fields']['status'] not in {'planned', 'active'}:
                    continue
                attended = max([event_times.get(id, row['updated_at']) for id in row['fields']['event_ids']] + [row['updated_at']])
                due = now - attended >= 6 * 3600
                option('continue_exploration', row, 75, due, 'recorded_exploration_due' if due else 'exploration_cooldown')
            for row in threads:
                age = now - max([event_times.get(id, now) for id in row['fields']['event_ids']] + [row['updated_at']])
                option('continue_thread', row, 40, age >= 6 * 3600, 'recorded_open_thread' if age >= 6 * 3600 else 'thread_cooldown')
            for row in interests:
                fields = row['fields']
                if fields['status'] != 'active' or not fields['worth_continuing']:
                    continue
                attended = fields['last_attended_at']
                due = attended is None or now - attended >= 86400
                option('attend_interest', row, {'growing': 35, 'steady': 30, 'fading': 15}.get(fields.get('attention'), 30), due, 'active_interest_due' if due else 'interest_cooldown')
            for row in collections:
                due = now - row['updated_at'] >= 2 * 86400
                option('organize_collection', row, 20, due, 'saved_collection_housekeeping' if due else 'collection_cooldown')
            for row in people:
                due = now - row['updated_at'] >= 3 * 86400
                option('revisit_person', row, 10, due, 'existing_person_due' if due else 'person_cooldown')
            candidates.sort(key=lambda value: (not value['eligible'], -value['priority'], value['id']))
            options = candidates[:6]
            latest = max((row['fields']['occurred_at'] for row in events), default=None)
            ordinary_due = latest is None or now - latest >= 86400
            options.append(dict(action='ordinary_life', kind=None, id=None, version=None, priority=5,
                eligible=ordinary_due, reason='ordinary_day_available' if ordinary_due else 'ordinary_day_cooldown'))
            options.append(dict(action='idle', kind=None, id=None, version=None, priority=0, eligible=True, reason='quiet_day_allowed'))
            selected = next(value for value in options if value['eligible'])
            self._scope(scope)
            return dict(action=selected['action'], selected=deepcopy(selected), options=options,
                deterministic=True, model_required=selected['action'] != 'idle', evidence_kind=EVIDENCE,
                timezone=self.life.timezone_name, local_date=datetime.fromtimestamp(now, self.life.timezone).date().isoformat(),
                source_versions=[{key: value[key] for key in ('kind', 'id', 'version', 'revision')}
                    for value in options if value['id'] is not None])

    def overview(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            # One bounded current projection for the visual archive. This is a
            # view over existing records, never a second ledger or life event.
            rows, cache = {}, {}
            for kind in KINDS:
                values = [self._project(scope, self._row(scope, kind, row['key']), cache) for row in
                          self.journal.list(_NS[kind], scope, limit=_LIMIT[kind] + 1)]
                rows[kind] = sorted((row for row in values if not row['archived'] and not row['deleted']),
                                   key=lambda row: (-row['updated_at'], row['id']))
            valid = {kind: [row for row in values if row['valid']] for kind, values in rows.items()}
            result = dict(spaces=valid['space'][:8], recent_collections=valid['collection'][:8],
                active_interests=[row for row in valid['interest'] if row['fields']['status'] == 'active'][:8],
                planned_explorations=[row for row in valid['exploration'] if row['fields']['status'] in {'planned', 'active'}][:8],
                counts={kind: len(valid[kind]) for kind in KINDS}, decision=self.decision(scope),
                generation=self.generation(scope), evidence_kind=EVIDENCE, fictional=True)
            # Small text-only cards contain no resource scope, URL, media bytes
            # or new inference. Detail views still resolve the authoritative ID.
            def brief(row):
                fields = row['fields']
                names = ('name', 'description', 'area', 'status', 'category', 'attention',
                         'goal', 'next_direction', 'space_id', 'interest_id')
                return dict(id=row['id'], kind=row['kind'], revision=row['revision'],
                    created_at=row['created_at'], updated_at=row['updated_at'], valid=row['valid'],
                    fields={key: value[:180] if isinstance(value, str) else value
                            for key in names if (value := fields.get(key)) is not None})
            spaces = []
            for space in rows['space']:
                items = [row for row in rows['item'] if row['fields'].get('space_id') == space['id']]
                spaces.append(dict(record=brief(space), item_count=len(items), items=[brief(row) for row in items[:4]]))
            space_ids = {row['id'] for row in rows['space']}
            unplaced = [row for row in rows['item'] if row['fields'].get('space_id') not in space_ids]
            interests = []
            for interest in rows['interest']:
                collections = [row for row in rows['collection'] if row['fields'].get('interest_id') == interest['id']]
                explorations = [row for row in rows['exploration'] if row['fields'].get('interest_id') == interest['id']]
                interests.append(dict(record=brief(interest), collection_count=len(collections),
                    exploration_count=len(explorations), collections=[brief(row) for row in collections[:3]],
                    explorations=[brief(row) for row in explorations[:3]]))
            def group(kind, field, values):
                return [dict(value=value, count=len(matched), records=[brief(row) for row in matched[:4]])
                        for value in values if (matched := [row for row in rows[kind] if row['fields'].get(field) == value])]
            recent = sorted((row for values in rows.values() for row in values), key=lambda row: (-row['updated_at'], row['kind'], row['id']))
            review_count = sum(not row['valid'] for row in recent)
            result['display_counts'] = {kind: len(rows[kind]) for kind in KINDS}
            result['review_count'] = review_count
            result['visual'] = dict(generated_at=self.life._now(), last_updated_at=recent[0]['updated_at'] if recent else None,
                spaces=spaces, unplaced_items=dict(count=len(unplaced), records=[brief(row) for row in unplaced[:4]]),
                interests=interests[:12], interest_count=len(interests),
                exploration_states=group('exploration', 'status', ('planned', 'active', 'paused', 'completed', 'cancelled')),
                collection_categories=group('collection', 'category', ('music', 'image', 'book', 'place', 'note', 'event', 'topic')),
                recent_updates=[brief(row) for row in recent[:10]], review_count=review_count)
            self._scope(scope)
            return result

    def apply_effects(self, scope, event, request_id, effects):
        """Atomically store <=4 effects of an already persisted current event.

        This transaction does not include the caller's earlier event creation.
        Repeated requests return their original receipt; changed retries conflict.
        Model effects cannot manufacture gifts or verified external findings.
        """
        scope = self._scope(scope, 'write')
        request_id = _text(request_id, 96)
        if type(event) is not dict or not {'id', 'version'} <= set(event):
            raise ValueError('persisted current event identity and version required')
        event_id, event_version = _id(event['id']), _revision(event['version'])
        if type(effects) is not list or len(effects) > 4:
            raise ValueError('at most four sourced personal-space effects required')
        effects = plain(deepcopy(effects), 32768)
        fingerprint = _digest([event_id, event_version, effects])
        key = 'effects.' + _digest([scope, request_id])[:48]
        with self.journal._transaction() as db:
            saved = self.journal.fetch(_EFFECTS, key, scope)
            if saved:
                if saved['data']['fingerprint'] != fingerprint:
                    raise JournalConflict('personal-space effect request changed')
                result = deepcopy(saved['data'])
                result['created'] = False
            else:
                current = self.life._row('event', scope, event_id)
                if (current is None or current['data']['archived'] or self.life._invalid(scope, current['data'])
                        or current['data']['version'] != event_version):
                    raise ValueError('current valid persisted effect event required')
                pending, seen = [], set()
                for index, effect in enumerate(effects):
                    if type(effect) is not dict or set(effect) - {'kind', 'id', 'expected_revision', 'fields', 'changes'} or 'kind' not in effect:
                        raise ValueError('explicit bounded personal-space effect required')
                    kind = _kind(effect['kind'])
                    old = None
                    if 'id' in effect:
                        if 'fields' in effect or set(effect) != {'kind', 'id', 'expected_revision', 'changes'}:
                            raise ValueError('existing effect ID, revision and changes required')
                        old = self._row(scope, kind, effect['id'])
                        if old is None or old['data']['archived'] or old['data']['deleted'] or self._invalid(scope, old['data']):
                            raise ValueError('current personal-space effect target required')
                        if old['revision'] != _revision(effect['expected_revision']):
                            raise JournalConflict('personal-space effect target changed')
                        if type(effect['changes']) is not dict or not effect['changes']:
                            raise ValueError('explicit personal-space effect changes required')
                        proposed = {**old['data']['fields'], **effect['changes']}
                    else:
                        if set(effect) != {'kind', 'fields'} or type(effect['fields']) is not dict:
                            raise ValueError('new personal-space effect fields required')
                        proposed = deepcopy(effect['fields'])
                    event_ids = proposed.get('event_ids', [])
                    if type(event_ids) is not list:
                        raise ValueError('bounded effect event references required')
                    proposed['event_ids'] = list(dict.fromkeys([*event_ids, event_id]))
                    fields = self._fields(kind, proposed)
                    if kind == 'collection':
                        if fields.get('resource_scope') is not None and fields['resource_scope'] != scope:
                            link_fields=('resource_type','resource_id','resource_scope','resource_revision')
                            if old is None or any(fields.get(key)!=old['data']['fields'].get(key) for key in link_fields):
                                raise ValueError('model effects cannot create or change foreign resource links')
                        if fields.get('resource_revision') is not None:
                            resource = self._resource(scope, fields)
                            if resource is None or resource['status'] != 'available':
                                raise ValueError('model effects require actual current resource metadata')
                    if kind == 'item' and (fields['origin'] == 'user_gift' or old and old['data']['fields']['origin'] == 'user_gift'):
                        raise ValueError('model effects cannot create or change user gifts')
                    if kind == 'exploration':
                        if fields['source_kind'] in {'terra_canon', 'public_reference'}:
                            raise ValueError('model effects cannot assert researched or canonical findings')
                        if old and old['data']['fields']['sources'] != fields['sources'] or not old and fields['sources']:
                            raise ValueError('model effects cannot invent external citations')
                    if kind == 'interest':
                        fields['last_attended_at'] = current['data']['fields']['occurred_at']
                    if old:
                        data = deepcopy(old['data'])
                        data.update(fields=fields, dependencies=self._references(scope, fields), version=data['version'] + 1)
                        if kind == 'collection' and fields.get('resource_revision') is not None:
                            data['resource_snapshot'] = self._resource(scope, fields)
                    else:
                        data = self._new(scope, kind, request_id + '.effect.' + str(index), fields,
                            dict(kind='model_generated', ref=event_id))
                    identity = (kind, data['id'])
                    if identity in seen:
                        raise ValueError('duplicate personal-space effect target')
                    seen.add(identity)
                    pending.append((kind, data, old))
                staged = {(kind, data['id']): data for kind, data, _ in pending}
                for _, data, _ in pending:
                    data['dependencies'] = self._references(scope, data['fields'], staged)
                    data['source_snapshots'] = self._capture_sources(scope, data['dependencies'], staged)
                result = dict(schema=1, state='complete', request_id=request_id, fingerprint=fingerprint,
                    event_id=event_id, event_version=event_version, records=[dict(kind=kind, id=data['id']) for kind, data, _ in pending],
                    evidence_kind=EVIDENCE, created=True, at=self.life._now())
                self._write(db, scope, pending, reason='recorded sourced life effects', actor='model_generated', receipt=(key, result))
            self._scope(scope, 'write')
        return result
