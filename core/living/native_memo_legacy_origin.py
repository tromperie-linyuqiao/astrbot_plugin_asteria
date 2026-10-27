"""Isolated source proof for the PC's real internal private wake event.

This proves an identity domain, never permission to execute legacy business.
The caller must still hold the existing admission/drain lock, preserve every
native claim, and apply the native-domain exclusion in the real native tool.
No current router, owner, SDK slot, file, configuration or session is changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import inspect
from pathlib import Path
import re
import sys
import types


PC_ROOT = 'astrbot_plugin_private_companion'
SOURCE_SHA256 = 'b26d068d386b3acb3f5f57bebdd35d3249bc2e978c438c72776ffb9d325f1ac4'
CLASS_NAME = 'SyntheticPrivateWakeEvent'
_LIMIT = 4 * 1024**2


def _identifier(value, *, platform=False):
    return (type(value) is str and 0 < len(value) <= 256
        and not any(ord(char) < 32 for char in value)
        and (not platform or ':' not in value))


def _true(callback, *args):
    value = callback(*args)
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value): value.close()
        return False
    return value is True


@dataclass(frozen=True)
class LegacyMemoIdentityDomain:
    """No character ID is inferred; history must be checked across characters."""
    platform_id: str
    bot_id: str
    user_id: str
    session_id: str


@dataclass(frozen=True)
class LegacyMemoOriginProof:
    identity: LegacyMemoIdentityDomain
    message_ref: str
    source_sha256: str
    constructor_sha256: str
    kind: str = field(default='pc.synthetic_private_wake.identity.v1', init=False)
    requires_native_domain_guard: bool = field(default=True, init=False)
    execution_authorized: bool = field(default=False, init=False)
    legacy_fallback_authorized: bool = field(default=False, init=False)


class NativeMemoLegacyOriginInspector:
    """Exact captured source + loaded constructor + actual current PC/context.

    ``source_current()`` is the independent existing PC source/slot proof; it
    must not recursively invoke this inspector. ``native_history_clear`` in
    prove() must synchronously establish no native owner/claim/history for the
    four-field domain across *all* characters, under the caller's admission
    lock. Missing, partial, asynchronous or stale history evidence is denied.
    The proof is not an old admission lease and cannot itself bypass routing.
    """
    def __init__(self, pc, context, *, source_current):
        from astrbot.api.event import AstrMessageEvent
        from astrbot.api.message_components import Plain
        from astrbot.api.star import Context
        from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
        from astrbot.core.platform.message_session import MessageSession
        from astrbot.core.platform.message_type import MessageType
        from astrbot.core.platform.platform_metadata import PlatformMetadata
        from .native_memo_runtime_bridge import code_fingerprint, _find_code

        if (type(context) is not Context or getattr(pc, 'context', None) is not context
                or not callable(source_current) or inspect.iscoroutinefunction(source_current)):
            raise ValueError('exact SDK context and independent current PC proof required')
        self.pc, self.context, self.source_current = pc, context, source_current
        self._sdk_event, self._message, self._member = AstrMessageEvent, AstrBotMessage, MessageMember
        self._session, self._private, self._metadata = MessageSession, MessageType.FRIEND_MESSAGE, PlatformMetadata
        self._fingerprint = code_fingerprint
        self._globals = {'AstrMessageEvent': AstrMessageEvent, 'AstrBotMessage': AstrBotMessage,
            'MessageMember': MessageMember, 'PlatformMetadata': PlatformMetadata, 'Plain': Plain}
        main = sys.modules.get(type(pc).__module__)
        path = Path(getattr(main, '__file__', ''))
        if (type(main) is not types.ModuleType or path.name != 'main.py'
                or path.parent.name != PC_ROOT or path.is_symlink()):
            raise ValueError('exact loaded PC main module required')
        self._main, self._directory = main, path.parent.resolve()
        name = main.__name__.rsplit('.', 1)[0] + '.proactive'
        module = sys.modules.get(name)
        if type(module) is not types.ModuleType:
            raise ValueError('actual loaded PC proactive module required')
        self._module = module
        self._class = vars(module).get(CLASS_NAME)
        if (type(self._class) is not type(AstrMessageEvent) or self._class.__module__ != name
                or self._class.__bases__ != (AstrMessageEvent,)):
            raise ValueError('exact original SDK event subclass required')
        source = self._read()
        compiled = compile(source, '<reviewed-PC-proactive>', 'exec', dont_inherit=True)
        constructor = _find_code(_find_code(compiled, CLASS_NAME), '__init__')
        self.constructor_sha256 = code_fingerprint(constructor)
        if not self.current():
            raise ValueError('current loaded PC event source not proven')

    def _read(self):
        path = Path(getattr(self._module, '__file__', ''))
        expected = self._directory / 'proactive.py'
        if (path != expected or path.is_symlink() or not path.is_file()
                or path.stat().st_size > _LIMIT):
            raise ValueError('bounded exact proactive source required')
        with path.open('rb') as stream: raw = stream.read(_LIMIT + 1)
        if len(raw) > _LIMIT or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
            raise ValueError('reviewed proactive source changed')
        return raw

    def current(self):
        try:
            from .native_memo_runtime_bridge import _metadata
            constructor = vars(self._class).get('__init__')
            return (sys.modules.get(type(self.pc).__module__) is self._main
                and getattr(self.pc, 'context', None) is self.context
                and _metadata(self.context, PC_ROOT, self.pc)[1] is self.pc
                and sys.modules.get(self._module.__name__) is self._module
                and vars(self._module).get(CLASS_NAME) is self._class
                and self._class.__bases__ == (self._sdk_event,)
                and inspect.isfunction(constructor)
                and constructor.__globals__ is vars(self._module)
                and self._fingerprint(constructor.__code__) == self.constructor_sha256
                and all(vars(self._module).get(name) is value for name, value in self._globals.items())
                and _true(self.source_current) and bool(self._read()))
        except Exception:
            return False

    def _shape(self, event):
        if type(event) is not self._class or getattr(event, 'context_obj', None) is not self.context:
            return None
        session = getattr(event, 'session', None)
        message = getattr(event, 'message_obj', None)
        meta = getattr(event, 'platform_meta', None)
        if (type(session) is not self._session or type(message) is not self._message
                or type(getattr(message, 'sender', None)) is not self._member
                or type(meta) is not self._metadata
                or getattr(event, 'platform', None) is not meta
                or session.message_type is not self._private or message.type is not self._private
                or getattr(message, 'group', None) is not None
                or meta.description != 'SyntheticPrivateWake'
                or getattr(event, 'is_wake', None) is not True
                or getattr(event, 'is_at_or_wake_command', None) is not True):
            return None
        platform, actor = session.platform_id, session.session_id
        if (not _identifier(platform, platform=True) or not _identifier(actor)
                or session.platform_name != platform or meta.name != platform or meta.id != platform
                or message.self_id != actor or message.session_id != actor or message.sender.user_id != actor):
            return None
        identity = getattr(message, 'message_id', None)
        if type(identity) is not str or re.fullmatch(r'private_companion_[0-9a-f]{32}', identity) is None:
            return None
        domain = LegacyMemoIdentityDomain(platform, actor, actor, str(session))
        return domain, hashlib.sha256(identity.encode('utf8')).hexdigest()

    def prove(self, event, *, native_history_clear=None):
        """Return a typed identity proof, or None; never an execution grant."""
        try:
            if not callable(native_history_clear) or not self.current(): return None
            before = self._shape(event)
            if before is None or not _true(native_history_clear, before[0]): return None
            if (not self.current() or self._shape(event) != before
                    or not _true(native_history_clear, before[0])): return None
            if not self.current() or self._shape(event) != before: return None
            return LegacyMemoOriginProof(before[0], before[1], SOURCE_SHA256, self.constructor_sha256)
        except Exception:
            return None

    def native_identity_domain(self, event):
        """Necessary identity restriction only, not a native authorization API.

        Exact reviewed synthetic class and its subclasses stay excluded even
        when mutable framework flags or message identity fields are changed.
        The normal native path must additionally retain all its current scope,
        occurrence, owner, source, authorization and transaction checks.
        """
        try:
            if (isinstance(event, self._class) or not isinstance(event, self._sdk_event)
                    or not self.current()): return False
            message, session = getattr(event, 'message_obj', None), getattr(event, 'session', None)
            if (type(message) is not self._message or type(session) is not self._session
                    or type(getattr(message, 'sender', None)) is not self._member
                    or message.type is not self._private or session.message_type is not self._private): return False
            bot, user = message.self_id, message.sender.user_id
            return (_identifier(bot) and _identifier(user) and bot != user
                and _identifier(session.session_id) and session.session_id == user)
        except Exception:
            return False


class NativeMemoSuccessorOriginInspector:
    """Real SDK identity domain for the TLS-native PC successor.

    There is deliberately no synthetic legacy fallback after full retirement.
    Existing native memo ownership/intent/lease checks remain in the router.
    """
    def __init__(self, pc, context, *, source_current):
        from astrbot.api.event import AstrMessageEvent
        from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
        from astrbot.core.platform.message_session import MessageSession
        from astrbot.core.platform.message_type import MessageType
        from .native_pc_business.proactive import SyntheticPrivateWakeEvent
        self.pc, self.context, self.source_current = pc, context, source_current
        self._sdk_event, self._message, self._member = AstrMessageEvent, AstrBotMessage, MessageMember
        self._session, self._private = MessageSession, MessageType.FRIEND_MESSAGE
        self._synthetic = SyntheticPrivateWakeEvent

    def current(self):
        return getattr(self.pc, 'context', None) is self.context and _true(self.source_current)

    def prove(self, event, *, native_history_clear=None):
        return None

    def native_identity_domain(self, event):
        try:
            if not self.current() or not isinstance(event, self._sdk_event) or isinstance(event, self._synthetic): return False
            if any(base.__name__ == 'SyntheticPrivateWakeEvent' for base in type(event).__mro__): return False
            message, session = getattr(event, 'message_obj', None), getattr(event, 'session', None)
            if (type(message) is not self._message or type(session) is not self._session
                    or type(getattr(message, 'sender', None)) is not self._member
                    or message.type is not self._private or session.message_type is not self._private): return False
            bot, user = message.self_id, message.sender.user_id
            return (_identifier(bot) and _identifier(user) and bot != user
                    and _identifier(session.session_id) and session.session_id == user)
        except Exception: return False
