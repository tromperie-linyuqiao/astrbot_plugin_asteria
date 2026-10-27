"""Scoped, editable music metadata in the existing journal, without playback.

No source file is opened, rewritten or imported as Python. External collection,
Phone binding, listening accumulation and delivery keep their existing owners.
The only exact matcher is NativeMusicCatalog; snapshots retain its v1 indexes.
All filesystem/database work belongs off a caller's event loop.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import re
import unicodedata

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope, scope_key
from .native_music_catalog import (
    NativeMusicCatalog, MAX_INDEX_BYTES, display_text, normalize_text, title_artist_key,
)

NAMESPACE = 'tls.native.music_library.v1'
BATCH_NAMESPACE = 'tls.native.music_library.import.v1'
MAX_SONGS = 1000
MAX_IMPORT_RECORDS = 50
MAX_IMPORT_BYTES = 65536
BASE_FIELDS = frozenset(('title', 'artist', 'album', 'genre', 'language', 'mood', 'lyrics', 'note', 'enabled'))
OPTIONAL_FIELDS = frozenset(('source_platform', 'external_ids', 'tags', 'meaning', 'user_preference',
                             'user_comment', 'character_comment'))
FIELDS = BASE_FIELDS | OPTIONAL_FIELDS
_ID = re.compile(r'music\.[a-f0-9]{64}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')


def _digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('bounded exact integer required')
    return value


def _text(value, maximum, *, empty=False, multiline=False):
    if type(value) is not str or any(ord(c) < 32 and c not in '\r\n\t' for c in value):
        raise ValueError('bounded plain music text required')
    value = (unicodedata.normalize('NFKC', value).replace('\r\n', '\n').replace('\r', '\n').strip()
             if multiline else display_text(value))
    if len(value) > maximum or not empty and not value:
        raise ValueError('bounded plain music text required')
    return value


def edit_fields(values):
    if type(values) is not dict or set(values) - FIELDS or not {'title', 'artist'} <= set(values):
        raise ValueError('explicit music title and artist required')
    result = {key: _text(values.get(key, ''), maximum, empty=key != 'title', multiline=key == 'lyrics')
              for key, maximum in (('title', 120), ('artist', 120), ('album', 200), ('genre', 60),
                                   ('language', 60), ('mood', 120), ('lyrics', 2000), ('note', 500))}
    result['enabled'] = values.get('enabled', True)
    if type(result['enabled']) is not bool:
        raise ValueError('exact music enabled flag required')
    # Optional additions stay absent on v1 rows; opening the old catalog must
    # not rewrite records or change their existing identity/signature.
    for key, maximum in (('source_platform', 64), ('meaning', 1000),
                         ('user_comment', 1000), ('character_comment', 1500)):
        if key in values: result[key] = _text(values[key], maximum, empty=True, multiline=key != 'source_platform')
    if 'user_preference' in values:
        if values['user_preference'] not in {'', 'neutral', 'liked', 'disliked', 'favorite'}:
            raise ValueError('explicit music preference required')
        result['user_preference'] = values['user_preference']
    if 'tags' in values:
        if type(values['tags']) is not list or len(values['tags']) > 24: raise ValueError('bounded explicit music tags required')
        result['tags'] = list(dict.fromkeys(_text(value, 48) for value in values['tags']))
    if 'external_ids' in values:
        if type(values['external_ids']) is not dict or len(values['external_ids']) > 12:
            raise ValueError('bounded external music IDs required')
        result['external_ids'] = {}
        for key, value in values['external_ids'].items():
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,48}', key):
                raise ValueError('external music ID source required')
            result['external_ids'][key] = _text(value, 256)
    return result


def _source_fields(plugin, raw):
    """Detached schema adaptation only; this never reads an external library."""
    if type(raw) is not dict:
        raise ValueError('explicit source row required')
    if plugin == 'private_companion':
        # Actual MusicLifeMixin reads these named fields from music_library.json.
        data = dict(title=raw.get('name'), artist=raw.get('artists'), album=raw.get('album', ''),
                    genre=raw.get('style', ''), language=raw.get('language', ''), mood=raw.get('mood', ''),
                    lyrics=raw.get('lyric', ''), note=raw.get('note', ''), enabled=raw.get('enabled', True))
    elif plugin == 'phone_perception':
        # Existing v1 MusicIndex songs use singular title/artist. Player track
        # IDs are not interpreted as catalog IDs, even when present in raw.
        data = {key: raw[key] for key in FIELDS if key in raw}
    else:
        raise ValueError('known detached source schema required')
    data.update({key: raw[key] for key in OPTIONAL_FIELDS if key in raw})
    return edit_fields(data)


class NativeMusicLibrary:
    backend = 'tls_native_music_library'

    def __init__(self, journal, *, authorize, clock=None):
        if not isinstance(journal, LivingJournal) or not callable(authorize):
            raise ValueError('existing journal and explicit scope authorization required')
        self.journal, self.authorize = journal, authorize
        self.clock = journal.clock if clock is None else clock
        if not callable(self.clock):
            raise ValueError('clock required')
        self.active = True

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self.active or self.authorize(dict(scope)) is not True:
            raise PermissionError('music metadata scope unavailable')
        return scope

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 253402214400:
            raise ValueError('valid explicit clock required')
        return value

    @contextmanager
    def _transaction(self, scope):
        with self.journal._transaction() as db:
            self._scope(scope)
            yield db
            self._scope(scope)  # Before COMMIT, also for replay/early returns.

    def _decode(self, row, scope):
        value = json.loads(row['data'])
        if (type(value) is not dict or value.get('schema') != 1 or type(value.get('schema')) is not int
                or value.get('id') != row['key'] or not _ID.fullmatch(value['id'])
                or type(row['revision']) is not int or not 1 <= row['revision'] <= 2**53 - 1
                or type(row['updated']) not in (int, float) or not math.isfinite(row['updated'])
                or not 0 < row['updated'] <= 253402214400
                or value.get('scope') != scope or value.get('origin') != self.backend
                or type(value.get('archived')) is not bool or edit_fields(value['fields']) != value['fields']
                or type(value.get('creation_signature')) is not str or not _HASH.fullmatch(value['creation_signature'])
                or type(value.get('created_at')) not in (int, float) or not math.isfinite(value['created_at'])
                or not 0 < value['created_at'] <= 253402214400
                or type(value.get('provenance')) is not dict
                or value['provenance'].get('kind') not in {'user_explicit', 'metadata_import'}):
            raise RuntimeError('invalid stored music metadata')
        return dict(value, revision=row['revision'], updated_at=row['updated'])

    def _rows(self, db, scope):
        rows = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? ORDER BY key LIMIT ?',
                          (NAMESPACE, scope_key(scope), MAX_SONGS + 1)).fetchall()
        if len(rows) > MAX_SONGS:
            raise RuntimeError('music scope capacity exceeded')
        return [self._decode(row, scope) for row in rows]

    def _get(self, db, scope, identity):
        identity = _text(identity, 100)
        row = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                         (NAMESPACE, scope_key(scope), identity)).fetchone()
        return self._decode(row, scope) if row else None

    def _write(self, db, scope, value, revision):
        _integer(revision, 0, 2**53 - 1)
        self._scope(scope)
        if revision == 0:
            if len(self._rows(db, scope)) >= MAX_SONGS:
                raise RuntimeError('music scope capacity reached')
            if db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self.journal.max_records:
                raise RuntimeError('journal checkpoint capacity reached')
        clean = {key: item for key, item in value.items() if key not in {'revision', 'updated_at'}}
        encoded, now = canonical(plain(clean, 65536)), self._now()
        if revision == 0:
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (NAMESPACE, value['id'], scope_key(scope), 1, now, encoded))
        else:
            changed = db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND scope=? AND key=? AND revision=?',
                                 (revision + 1, now, encoded, NAMESPACE, scope_key(scope), value['id'], revision)).rowcount
            if changed != 1:
                raise JournalConflict('music metadata revision conflict')
        saved = self._get(db, scope, value['id'])
        if saved != dict(clean, revision=revision + 1, updated_at=now):
            raise RuntimeError('music metadata write readback mismatch')
        self._scope(scope)
        return saved

    def create(self, scope, request_id, **values):
        scope = self._scope(scope)
        request_id, fields = _text(request_id, 128), edit_fields(values)
        identity, signature = 'music.' + _digest(['new', scope, request_id]), _digest(fields)
        with self._transaction(scope) as db:
            old = self._get(db, scope, identity)
            if old:
                if old['creation_signature'] != signature:
                    raise JournalConflict('music request ID reused with different metadata')
                return old
            return self._write(db, scope, dict(schema=1, id=identity, scope=scope, origin=self.backend,
                fields=fields, archived=False, created_at=self._now(), creation_signature=signature,
                provenance=dict(kind='user_explicit', source_ref=request_id)), 0)

    def get(self, scope, identity):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            row = self._get(self.journal._db, scope, identity)
        self._scope(scope)
        return row

    def search(self, scope, *, query='', artist='', genre='', language='', include_archived=False, limit=20, offset=0):
        scope = self._scope(scope)
        if type(include_archived) is not bool:
            raise ValueError('exact archive flag required')
        _integer(limit, 1, 100); _integer(offset, 0, MAX_SONGS)
        filters = {key: normalize_text(_text(value, 200, empty=True))
                   for key, value in (('query', query), ('artist', artist), ('genre', genre), ('language', language))}
        with self.journal._lock:
            self.journal._ensure_open()
            rows = self._rows(self.journal._db, scope)
        selected = []
        for row in rows:
            if row['archived'] and not include_archived:
                continue
            f = row['fields']
            if any(needle and needle not in normalize_text(f[key]) for key, needle in filters.items() if key != 'query'):
                continue
            if filters['query'] and filters['query'] not in normalize_text(' '.join(
                    [f.get(key, '') for key in ('title', 'artist', 'album', 'genre', 'language', 'mood', 'lyrics',
                                               'note', 'source_platform', 'meaning', 'user_comment', 'character_comment')]
                    + f.get('tags', []) + list(f.get('external_ids', {}).values()))):
                continue
            selected.append(row)
        self._scope(scope)
        return dict(records=selected[offset:offset + limit], total=len(selected), limit=limit, offset=offset,
                    metadata_only=True, creates_playback_evidence=False)

    def update(self, scope, identity, *, expected_revision, **changes):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2**53 - 1)
        if type(changes) is not dict or not changes or set(changes) - FIELDS:
            raise ValueError('explicit editable music fields required')
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('music metadata absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('music metadata revision conflict')
            row['fields'] = edit_fields(dict(row['fields'], **changes))
            return self._write(db, scope, row, expected_revision)

    def _archive(self, scope, identity, expected_revision, archived):
        scope = self._scope(scope)
        _integer(expected_revision, 1, 2**53 - 1)
        with self._transaction(scope) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('music metadata absent')
            if row['revision'] != expected_revision:
                raise JournalConflict('music metadata revision conflict')
            if row['archived'] == archived:
                return row
            row['archived'] = archived
            return self._write(db, scope, row, expected_revision)

    def archive(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, True)

    def restore(self, scope, identity, *, expected_revision):
        return self._archive(scope, identity, expected_revision, False)

    def _snapshot(self, scope):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            rows = self._rows(self.journal._db, scope)
        self._scope(scope)
        return rows

    def generation(self, scope):
        """Current metadata token, not a listening/event/permission token."""
        try:
            return ('native_music_library', id(self), tuple((row['id'], row['revision']) for row in self._snapshot(scope)))
        except Exception:
            return None

    @staticmethod
    def _index(rows):
        songs = [dict(song_id=row['id'], **{key: value for key, value in row['fields'].items() if key in BASE_FIELDS and key != 'enabled'},
                      source='tls_native_music_library', metadata_only=True)
                 for row in rows if not row['archived'] and row['fields']['enabled']]
        result = dict(schema_version=1, songs=songs, by_song_id={}, by_title={}, by_title_artist={},
                      metadata_only=True, creates_playback_evidence=False)
        for position, row in enumerate(songs):
            identity = row['song_id']
            result['by_song_id'][identity] = position
            result['by_title'].setdefault(normalize_text(row['title']), []).append(identity)
            result['by_title_artist'].setdefault(title_artist_key(row['title'], row['artist']), []).append(identity)
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_INDEX_BYTES:
            raise RuntimeError('native catalog snapshot too large')
        return result

    def export_index(self, scope):
        """Detached point-in-time v1 index; never a permanently live reader."""
        scope = self._scope(scope)
        result = self._index(self._snapshot(scope))
        self._scope(scope)
        return result

    def match(self, scope, title, artist=''):
        """Exact metadata lookup delegated to the existing native catalog."""
        scope = self._scope(scope)
        journal, authorize, clock = self.journal, self.authorize, self.clock
        # RLock covers this connection only. A second journal connection can
        # commit during matching; repeat the scoped rows and resource bindings
        # after the existing matcher before calling the result current.
        with journal._lock:
            journal._ensure_open()
            before = self._rows(journal._db, scope)
            result = NativeMusicCatalog(index=self._index(before)).match(title, artist)
            self._scope(scope)
            if (self.journal is not journal or self.authorize is not authorize or self.clock is not clock
                    or self._rows(journal._db, scope) != before):
                raise JournalConflict('music metadata changed during exact match')
            self._scope(scope)
            return result

    def export(self, scope):
        scope = self._scope(scope)
        result = dict(schema='tls.native.music_library.export.v1', scope=scope,
                      records=self._snapshot(scope), exported_at=self._now(), metadata_only=True,
                      creates_playback_evidence=False, creates_send_permission=False)
        self._scope(scope)
        return result

    def _preview(self, db, scope, payload):
        payload = plain(payload, MAX_IMPORT_BYTES)
        if (type(payload) is not dict or set(payload) != {'schema', 'source_plugin', 'source_ref', 'source_sha256', 'records'}
                or type(payload['schema']) is not int or payload['schema'] != 1
                or payload['source_plugin'] not in {'private_companion', 'phone_perception'}
                or type(payload['source_sha256']) is not str or not _HASH.fullmatch(payload['source_sha256'])
                or type(payload['records']) is not list or not 1 <= len(payload['records']) <= MAX_IMPORT_RECORDS):
            raise ValueError('bounded explicit music source artifact required')
        source_ref = _text(payload['source_ref'], 128)
        results, seen = [], set()
        existing_by_source = {}
        for existing in self._rows(db, scope):
            source = existing['provenance']
            if source.get('kind') == 'metadata_import':
                existing_by_source.setdefault((source.get('source_plugin'), source.get('source_id')), []).append(existing)
        for item in payload['records']:
            row = dict(status='invalid', source_id='')
            try:
                if type(item) is not dict or set(item) != {'source_id', 'record', 'target_scope'}:
                    raise ValueError('explicit source row and owner required')
                source_id = _text(item['source_id'], 128)
                row['source_id'] = source_id
                if source_id in seen:
                    row['status'] = 'duplicate_source_id'; results.append(row); continue
                seen.add(source_id)
                if item['target_scope'] is None:
                    row['status'] = 'unassigned'; results.append(row); continue
                if private_scope(item['target_scope']) != scope:
                    row['status'] = 'foreign_scope'; results.append(row); continue
                raw = item['record']
                fields = _source_fields(payload['source_plugin'], raw)
                if payload['source_plugin'] == 'phone_perception' and raw.get('song_id') != source_id:
                    raise ValueError('explicit source catalog ID mismatch')
                provenance = dict(kind='metadata_import', source_plugin=payload['source_plugin'], source_ref=source_ref,
                                  source_sha256=payload['source_sha256'], source_id=source_id,
                                  source_record_sha256=_digest(raw), attribution='operator_explicit')
                identity = 'music.' + _digest(['import', scope, payload['source_plugin'], source_ref, source_id])
                signature = _digest([fields, {key: value for key, value in provenance.items() if key != 'source_sha256'}])
                old = self._get(db, scope, identity)
                if old is None:
                    # A renamed/exported artifact is not a new song source.
                    # Keep old record IDs and edits; only a new source ID can
                    # create a new imported record, never title similarity.
                    matches = existing_by_source.get((payload['source_plugin'], source_id), [])
                    if len(matches) > 1:
                        row['status'] = 'conflict'; results.append(row); continue
                    if matches: old = matches[0]; identity = old['id']
                same_source = old is not None and old['provenance'].get('source_record_sha256') == provenance['source_record_sha256']
                row.update(status='ready' if old is None else 'existing' if same_source or old['creation_signature'] == signature else 'conflict',
                           id=identity, fields=fields, provenance=provenance, creation_signature=signature,
                           revision=old['revision'] if old else 0, archived=old['archived'] if old else False)
            except (ValueError, TypeError, KeyError, OverflowError):
                row['status'] = 'invalid'
            results.append(row)
        result = dict(schema=1, scope=scope, source_ref=source_ref, source_sha256=payload['source_sha256'],
                      records=results, counts={state: sum(row['status'] == state for row in results)
                         for state in ('ready', 'existing', 'unassigned', 'foreign_scope', 'invalid', 'conflict', 'duplicate_source_id')},
                      writes=0, metadata_only=True, creates_playback_evidence=False, creates_send_permission=False)
        # Preview fields can exceed the input byte limit due to provenance.
        result['preview_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        return result

    def preview_import(self, scope, payload):
        scope = self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            result = self._preview(self.journal._db, scope, payload)
        self._scope(scope)
        return result

    def confirm_import(self, scope, payload, *, preview_sha256, request_id, owner_confirmed):
        scope = self._scope(scope)
        if owner_confirmed is not True or type(preview_sha256) is not str or not _HASH.fullmatch(preview_sha256):
            raise PermissionError('explicit music source ownership confirmation required')
        payload = plain(payload, MAX_IMPORT_BYTES)
        identity = _digest(['music_import', scope, _text(request_id, 128)])
        signature = _digest([payload, preview_sha256])
        with self._transaction(scope) as db:
            prior = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                               (BATCH_NAMESPACE, scope_key(scope), identity)).fetchone()
            if prior:
                receipt = json.loads(prior[0])
                if receipt['signature'] != signature:
                    raise JournalConflict('music import request reused with different preview')
                return receipt
            preview = self._preview(db, scope, payload)
            if preview['preview_sha256'] != preview_sha256 or any(row['status'] not in {'ready', 'existing'} for row in preview['records']):
                raise JournalConflict('music preview changed or source ownership incomplete')
            ready = [row for row in preview['records'] if row['status'] == 'ready']
            if (len(self._rows(db, scope)) + len(ready) > MAX_SONGS
                    or db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] + len(ready) + 1 > self.journal.max_records):
                raise RuntimeError('music import capacity reached')
            created = []
            for row in ready:
                value = dict(schema=1, id=row['id'], scope=scope, origin=self.backend, fields=row['fields'], archived=False,
                             created_at=self._now(), creation_signature=row['creation_signature'], provenance=row['provenance'])
                created.append(self._write(db, scope, value, 0)['id'])
            receipt = dict(schema=1, id=identity, signature=signature, created_ids=created,
                           existing_ids=[row['id'] for row in preview['records'] if row['status'] == 'existing'],
                           source_ref=preview['source_ref'], source_sha256=preview['source_sha256'],
                           metadata_only=True, creates_playback_evidence=False, creates_send_permission=False)
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (BATCH_NAMESPACE, identity, scope_key(scope), 1, self._now(), canonical(receipt)))
            saved = db.execute('SELECT data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                               (BATCH_NAMESPACE, scope_key(scope), identity)).fetchone()
            if saved is None or json.loads(saved[0]) != receipt:
                raise RuntimeError('music import receipt readback mismatch')
            return receipt

    def stop(self):
        self.active = False

    def close(self):
        self.stop()  # Existing shared journal remains caller-owned.
