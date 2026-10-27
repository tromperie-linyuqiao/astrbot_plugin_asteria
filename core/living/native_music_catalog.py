"""TLS-owned exact lookup of an existing local music metadata index.

The index remains a source artifact. This reader does not collect playback,
infer preferences, rewrite the catalog, or import a legacy plugin. Callers
perform filesystem work off the host event loop and retain their own grants.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat
import threading
import unicodedata


SCHEMA_VERSION = 1
MAX_INDEX_BYTES = 16 * 1024 * 1024


def display_text(value):
    """Use the catalog's Unicode and whitespace rules, without guessing."""
    if not isinstance(value, str):
        return ''
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def normalize_text(value):
    return display_text(value).casefold()


def title_artist_key(title, artist):
    return json.dumps([normalize_text(title), normalize_text(artist)],
                      ensure_ascii=False, separators=(',', ':'))


def _unknown(reason):
    return dict(status='unknown', song_id='', song_info={}, candidate_count=0,
                match_method='', reason=reason)


def match_music(index, title, artist=''):
    """Resolve one unique exact title/artist or one unique exact title.

    Player track IDs are not catalog IDs. Every index pointer must resolve
    back to the requested normalized fields before any metadata is returned.
    """
    title_key, artist_key = normalize_text(title), normalize_text(artist)
    if not title_key:
        return _unknown('missing_title')
    if (not isinstance(index, dict) or type(index.get('schema_version')) is not int
            or index['schema_version'] != SCHEMA_VERSION):
        return _unknown('invalid_index')
    table_name = 'by_title_artist' if artist_key else 'by_title'
    query_key = title_artist_key(title, artist) if artist_key else title_key
    table = index.get(table_name)
    ids = table.get(query_key, []) if isinstance(table, dict) else []
    if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
        return _unknown('invalid_index')
    if not ids:
        return _unknown('no_exact_match')
    if len(ids) > 1:
        result = _unknown('multiple_exact_matches')
        result.update(status='ambiguous', candidate_count=len(ids))
        return result
    positions, songs = index.get('by_song_id'), index.get('songs')
    position = positions.get(ids[0]) if isinstance(positions, dict) else None
    if type(position) is not int or not isinstance(songs, list) or not 0 <= position < len(songs):
        return _unknown('invalid_index')
    row = songs[position]
    if (not isinstance(row, dict) or row.get('song_id') != ids[0]
            or normalize_text(row.get('title')) != title_key
            or artist_key and normalize_text(row.get('artist')) != artist_key):
        return _unknown('invalid_index')
    return dict(status='matched', song_id=ids[0], song_info=deepcopy(row), candidate_count=1,
                match_method='title_artist_exact' if artist_key else 'unique_title_exact')


class NativeMusicCatalog:
    """A bounded, read-only reader with detached get/match return values.

    ``get``, ``match`` and ``error_type`` retain the existing index API shape.
    A missing, invalid or changing replacement clears old metadata immediately;
    it never represents a retained earlier catalog as a current successful read.
    No age TTL is invented for a metadata artifact with no freshness contract.
    """
    backend = 'tls_native_music_catalog'

    def __init__(self, path=None, *, index=None):
        self.path = Path(path) if path is not None else None
        self._index = deepcopy(index) if isinstance(index, dict) else {}
        self._signature = None
        self._lock = threading.RLock()
        self.error_type = ''
        self.state = 'ready' if self._index else 'empty'

    @staticmethod
    def _file_signature(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def _refresh(self):
        if self.path is None:
            return
        try:
            before = self.path.stat()
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_INDEX_BYTES:
                raise ValueError('invalid catalog file')
            signature = self._file_signature(before)
            if signature != self._signature:
                with self.path.open('rb') as handle:
                    # Reading MAX+1 also bounds a file that grows after stat.
                    raw = handle.read(MAX_INDEX_BYTES + 1)
                after = self.path.stat()
                if (self._file_signature(after) != signature or len(raw) != before.st_size
                        or len(raw) > MAX_INDEX_BYTES):
                    raise ValueError('catalog changed while reading')
                data = json.loads(raw.decode('utf-8-sig'))
                if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
                        or data['schema_version'] != SCHEMA_VERSION):
                    raise ValueError('invalid catalog schema')
                self._index, self._signature = data, signature
            self.error_type, self.state = '', 'ready'
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
            self._index, self._signature = {}, None
            self.error_type = type(exc).__name__
            self.state = 'missing' if isinstance(exc, FileNotFoundError) else 'unavailable'

    def get(self):
        with self._lock:
            self._refresh()
            return deepcopy(self._index)

    def match(self, title, artist=''):
        with self._lock:
            self._refresh()
            return match_music(self._index, title, artist)


# The name is an API alias for adapters accepting the existing index shape;
# it never imports or subclasses the old plugin's implementation.
MusicIndex = NativeMusicCatalog
