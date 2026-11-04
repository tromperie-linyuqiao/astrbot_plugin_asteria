"""Metadata-only links from personal collections to existing scoped resources.

The native owners retain files and metadata. This facade neither reads image
bytes nor creates a catalog, database, playback event or new source authority.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .autonomous_life import AutonomousLife, _revision, _text
from .journal import JournalConflict
from .models import canonical, private_scope, scope_key
from .native_expression_assets import NativeExpressionAssets, MAX_ASSETS
from .native_music_library import NativeMusicLibrary

TYPES = ('music', 'image')
_NATIVE_IDS = {'music': re.compile(r'music\.[a-f0-9]{64}\Z'), 'image': re.compile(r'[a-f0-9]{64}\Z')}


def valid_resource_identity(resource_type, identity):
    return (type(resource_type) is str and resource_type in _NATIVE_IDS and type(identity) is str
            and _NATIVE_IDS[resource_type].fullmatch(identity) is not None)


class PersonalResources:
    def __init__(self, life, *, authorize_source=None, enumerate_sources=None):
        if not isinstance(life, AutonomousLife):
            raise ValueError('existing AutonomousLife required')
        for callback in (authorize_source, enumerate_sources):
            if callback is not None and not callable(callback):
                raise ValueError('explicit resource authority callback required')
        self.life, self.journal = life, life.journal
        self.authorize_source, self.enumerate_sources = authorize_source, enumerate_sources
        life.personal_resources = self

    def _allowed(self, scope, source):
        self.life._scope(scope)
        if source == scope:
            return True
        try:
            return self.authorize_source is not None and self.authorize_source(dict(scope), dict(source)) is True
        except PermissionError:
            return False

    def _source(self, scope, source_scope):
        scope = self.life._scope(scope)
        source = scope if source_scope is None else private_scope(source_scope)
        if not self._allowed(scope, source):
            raise PermissionError('confirmed resource source authority required')
        return scope, source

    def _provider(self, scope, source, resource_type):
        if resource_type not in TYPES or type(resource_type) is not str:
            raise ValueError('supported resource type required')
        authorize = lambda actual: actual == source and self._allowed(scope, source)
        if resource_type == 'music':
            return NativeMusicLibrary(self.journal, authorize=authorize, clock=self.life.clock)
        # Only get/list/scopes are used: these never open an asset file.
        return NativeExpressionAssets(self.journal, authorize=authorize, clock=self.life.clock)

    @staticmethod
    def _safe(row, resource_type, source):
        if resource_type == 'music':
            fields = row['fields']
            metadata = {key: deepcopy(fields.get(key, [] if key == 'tags' else ''))
                        for key in ('title', 'artist', 'album', 'tags')}
            name, description = fields['title'], fields.get('note', '')
            available = not row['archived'] and fields['enabled']
        else:
            metadata = {key: deepcopy(row[key]) for key in ('caption', 'tags', 'width', 'height', 'format')}
            name = (row['caption'].strip() or '图片 ' + row['id'][:12])[:120]
            description = row['caption']
            available = not row['deleted'] and row['enabled']
        return dict(id=row['id'], type=resource_type, source_scope=deepcopy(source),
                    name=name, description=description, revision=row['revision'],
                    available=available, metadata=metadata,
                    status='available' if available else 'archived')

    def _get(self, scope, resource_type, identity, source):
        provider = self._provider(scope, source, resource_type)
        raw = (provider.get(source, identity) if resource_type == 'music'
               else provider.get(source, identity, include_deleted=True))
        return None if raw is None else self._safe(raw, resource_type, source)

    def list_resources(self, scope, resource_type, source_scope=None, query='', limit=20, offset=0):
        scope, source = self._source(scope, source_scope)
        query = _text(query, 300, empty=True)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 1000:
            raise ValueError('bounded resource page required')
        provider = self._provider(scope, source, resource_type)
        with self.journal._lock:
            if resource_type == 'music':
                page = provider.search(source, query=query, include_archived=True, limit=limit, offset=offset)
                records = [self._safe(row, resource_type, source) for row in page['records']]
                self._source(scope, source)
                return dict(records=records, total=page['total'], limit=limit, offset=offset, metadata_only=True)
            else:
                rows = provider.list(source, include_deleted=True, limit=MAX_ASSETS)
            records = [self._safe(row, resource_type, source) for row in rows]
            records = [row for row in records if not query or query.casefold() in canonical(
                [row['name'], row['description'], row['metadata']]).casefold()]
            self._source(scope, source)
            return dict(records=records[offset:offset + limit], total=len(records), limit=limit,
                        offset=offset, metadata_only=True)

    def sources(self, scope):
        """Explicit authenticated maintenance directory; never inferred access."""
        scope = self.life._scope(scope)
        if self.enumerate_sources is None or self.enumerate_sources(dict(scope)) is not True:
            raise PermissionError('explicit resource source enumeration authority required')
        records = {}
        with self.journal._lock:
            for resource_type in TYPES:
                provider = self._provider(scope, scope, resource_type)
                for row in provider.scopes(limit=100):
                    source = row['scope']
                    value = records.setdefault(scope_key(source), dict(source_scope=source,
                        resource_types=[], total=0, available=0, counts={}))
                    value['resource_types'].append(resource_type)
                    value['total'] += row['total']
                    value['available'] += row['active']
                    value['counts'][resource_type] = dict(total=row['total'], available=row['active'])
            self.life._scope(scope)
            if self.enumerate_sources(dict(scope)) is not True:
                raise PermissionError('resource source enumeration authority changed')
        return dict(records=list(records.values()), metadata_only=True)

    def resolve(self, scope, fields):
        scope = self.life._scope(scope)
        if type(fields) is not dict:
            raise ValueError('explicit collection resource fields required')
        identity, resource_type = fields.get('resource_id', ''), fields.get('resource_type', '')
        source = private_scope(fields['resource_scope']) if fields.get('resource_scope') is not None else scope
        expected = fields.get('resource_revision')
        result = dict(id=identity, type=resource_type, source_scope=deepcopy(source), name='', description='',
                      revision=None, expected_revision=expected, available=False, metadata={})
        # Manual historical IDs have no verified version. Never guess their
        # type/scope or upgrade them just because a matching native ID exists.
        if expected is not None:
            _revision(expected)
        if expected is None or not valid_resource_identity(resource_type, identity):
            status = 'unverified'
        else:
            try:
                self._source(scope, source)
                row = self._get(scope, resource_type, identity, source)
                self._source(scope, source)
                if row is None:
                    status = 'missing'
                else:
                    result.update(row)
                    status = ('archived' if not row['available'] else
                              'changed' if row['revision'] != expected else 'available')
                    if status == 'archived':
                        result.update(name='', description='', metadata={})
            except PermissionError:
                status = 'denied'
        result.update(status=status, state=status)
        return result

    def collect(self, scope, request_id, resource_type, resource_id, source_scope,
                expected_resource_revision, name=None, description=None, interest_id=None):
        from .personal_space import PersonalSpace
        scope = self.life._scope(scope, 'write')
        scope, source = self._source(scope, source_scope)
        _revision(expected_resource_revision)
        personal = getattr(self.life, 'personal_space', None)
        if not isinstance(personal, PersonalSpace):
            personal = PersonalSpace(self.life)
        request_id = _text(request_id, 128)
        # Native metadata and personal reference are compared/committed under
        # the same existing SQLite writer transaction, with no file copying.
        with self.journal._transaction() as db:
            row = self._get(scope, resource_type, resource_id, source)
            if row is None or not row['available']:
                raise ValueError('available existing resource metadata required')
            if row['revision'] != expected_resource_revision:
                raise JournalConflict('resource metadata revision changed')
            values = dict(name=row['name'] if name is None else name,
                description=row['description'] if description is None else description,
                category=resource_type, resource_id=resource_id, resource_type=resource_type,
                resource_revision=row['revision'])
            if source != scope:
                values['resource_scope'] = source
            if interest_id is not None:
                values['interest_id'] = interest_id
            fields = personal._fields('collection', values)
            provenance = self.life._source(None, request_id)
            identity = personal._identity('collection', scope, request_id)
            old = personal._row(scope, 'collection', identity)
            from .autonomous_life import _digest
            if old:
                if old['data']['request_fingerprint'] != _digest([fields, provenance]):
                    raise JournalConflict('personal-space request already has different content')
            else:
                data = personal._new(scope, 'collection', request_id, fields, provenance)
                personal._write(db, scope, [('collection', data, None)],
                    reason='collected existing resource metadata', actor='operator')
            self._source(scope, source)
            self.life._scope(scope, 'write')
        return personal.get_record(scope, 'collection', identity)
