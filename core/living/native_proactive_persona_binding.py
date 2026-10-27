"""CAS bind a genuine private profile scope to its exact selected SDK persona.

The internal caller supplies the result of SDK resolve_selected_persona. The
authorization callback must include the explicit native feature opt-in and an
existing genuine inbound lease. This module cannot create or renew a lease.
"""
from __future__ import annotations

import inspect
import math
import time

from .journal import JournalConflict
from .models import private_scope

NAMESPACE = 'tls.proactive.persona_binding.v1'
SCHEMA = 'tls.proactive.persona_binding.v1'
SOURCE = 'genuine_inbound_sdk_selection'
KEY = 'selected'


def _identifier(value):
    return (isinstance(value, str) and 1 <= len(value) <= 256 and value == value.strip()
            and not any(ord(char) < 32 for char in value))


def _sync(value):
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value): value.close()
        return None
    return value


def _result(state, *, registered=False, revision=None):
    result = dict(allowed=state == 'bound', state=state, registered=registered, revision=revision)
    if state == 'bound': result['source'] = SOURCE
    return result


class NativeProactivePersonaBinding:
    def __init__(self, journal, *, authorize, expected_legacy_persona, clock=time.time):
        if not all(callable(value) for value in (authorize, expected_legacy_persona, clock)):
            raise ValueError('trusted synchronous persona binding callbacks required')
        self.journal = journal; self.authorize = authorize
        self.expected_legacy_persona = expected_legacy_persona; self.clock = clock
        self.active = True

    def stop(self):
        """Fence this owner synchronously; the shared journal remains open."""
        self.active = False

    def close(self):
        self.stop()

    def _authorized(self, scope):
        return self.active and _sync(self.authorize(scope)) is True and self.active

    def _legacy(self, scope):
        if not self.active: return None
        value = _sync(self.expected_legacy_persona(scope))
        if not self.active: return None
        if value == '': return ''
        return value if _identifier(value) else None

    @staticmethod
    def _stored(row):
        value = row.get('data') if isinstance(row, dict) else None
        if (not isinstance(value, dict) or set(value) != {'schema', 'persona_id', 'source', 'created_at'}
                or value.get('schema') != SCHEMA or value.get('source') != SOURCE
                or not _identifier(value.get('persona_id'))
                or type(value.get('created_at')) not in (int, float)
                or not math.isfinite(value['created_at'])):
            return None
        return value

    def bind(self, scope, selected):
        """Register once, or verify an existing exact binding, without aliases.

        Safe result fields intentionally omit the selected identifier and the
        scope. The private scoped journal retains the exact identifier.
        """
        if not self.active: return _result('denied')
        scope = private_scope(scope)
        if not _identifier(selected): raise ValueError('exact selected SDK persona required')
        if not self._authorized(scope): return _result('denied')
        legacy = self._legacy(scope)
        if not self.active: return _result('denied')
        if legacy is None: return _result('unknown')
        if legacy and legacy != selected: return _result('conflict')
        def guard(): return self._authorized(scope) and self._legacy(scope) == legacy and self.active
        row = self.journal.fetch(NAMESPACE, KEY, scope)
        if row is not None:
            stored = self._stored(row)
            if stored is None: return _result('unknown')
            if stored['persona_id'] != selected: return _result('conflict')
            return _result('bound', revision=row['revision']) if guard() else _result('denied')
        created = self.clock()
        if type(created) not in (int, float) or not math.isfinite(created): raise ValueError('finite binding time required')
        try:
            row = self.journal.put(NAMESPACE, KEY, scope, dict(schema=SCHEMA, persona_id=selected,
                source=SOURCE, created_at=created), expected_revision=0, authorize=guard)
        except PermissionError:
            return _result('denied')
        except JournalConflict:
            row = self.journal.fetch(NAMESPACE, KEY, scope)
            stored = self._stored(row)
            if stored is None: return _result('unknown')
            if stored['persona_id'] != selected: return _result('conflict')
            return _result('bound', revision=row['revision']) if guard() else _result('denied')
        # No async operation occurs between the post-CAS authority check and
        # returning to the SDK-selection caller. Later calls recheck everything.
        if not guard(): return _result('denied')
        return _result('bound', registered=True, revision=row['revision'])

    def allow(self, scope, selected):
        return self.bind(scope, selected)['allowed'] is True
