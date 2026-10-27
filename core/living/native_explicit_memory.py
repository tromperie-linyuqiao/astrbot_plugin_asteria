"""One closed-by-default MC responsibility: explicit remember/commitment rules.

The three patterns/labels below are verbatim from the reviewed classifier's
non-profile branch. match_explicit is only a grammar candidate: the old
classifier gives profile extraction precedence. The integration MUST first
prove that this very event's actual derived result selected explicit_memory,
then admit it with a current, pure, synchronous/thread-safe branch_gate. Neither
core-tool ownership nor context ownership grants that write admission.

No old plugin is imported/called. Only new full-scope records are written to
its existing NativeMemoryAdapter/NativeMemoryStore. No historical owner is
changed, no model/task/sender is created, and no old capture path is disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import re

from .memory_context import _SECRET
from .models import canonical, private_scope
from .native_memory import NativeMemoryStore
from .native_memory_adapter import NativeMemoryAdapter

SOURCE_ID = 'tls.chat.explicit_memory'
RELATIONSHIP_SOURCE_ID = 'tls.chat.relationship_statement'
CLASSIFIER_SOURCE = 'core/classifier.py'
CLASSIFIER_SHA256 = 'e0064564ad7d3dba664adc8f1a448dcb70e076ca54f71b531ff5d7402ff815ff'
SENSITIVE_SOURCE = 'core/sensitive_data.py'
SENSITIVE_SHA256 = '96509372de458483cd3d22be5419a110107b197abe640c7563fbe5e54bdd2b2c'
# Source order and numbered slots are durable identity, not an intent model.
RULES = (
    (r'^(?:请)?(?:记住|别忘了?|你要记得|务必记得|一定记得)(.{2,80})$', '明确要求'),
    (r'^(?:我|咱|俺)(?:保证|发誓|答应你|跟你约定|说好了)(.{2,60})$', '承诺/约定'),
    (r'^(?:下次|以后|明天|回头|之后)(?:一定|肯定会|一定会|保证)(.{2,40})$', '承诺'),
)
_PATTERNS = tuple(re.compile(pattern) for pattern, _ in RULES)
RELATIONSHIP_RULES = (
    (r'^(?:你|你呀)(?:是我|是咱)(?:最|特别|很)?(.{2,20})(?:朋友|伙伴|重要的人|信任的人)$', '关系定位'),
    (r'^(?:我|咱|俺)(?:很|特别|真的|最)?(?:信任|依赖|在意|在乎|珍惜)(.{2,30})$', '关系表达'),
)
_RELATIONSHIP_PATTERNS = tuple(re.compile(pattern) for pattern, _ in RELATIONSHIP_RULES)

# These four credential forms were scrubbed by the old MemoryRecord boundary.
# We reject their whole source instead: retaining unmodified source evidence
# must not persist a password hidden behind a redacted derived sentence.
_PRIVATE_KEY = re.compile(
    r'-----BEGIN [^-\r\n]+ PRIVATE KEY-----.*?-----END [^-\r\n]+ PRIVATE KEY-----',
    re.IGNORECASE | re.DOTALL)
_BEARER = re.compile(r'(?i)(?<![A-Za-z0-9_])bearer\s+[A-Za-z0-9._~+/=-]{8,}')
_CREDENTIAL_ASSIGNMENT = re.compile(
    r'(?i)(?<![A-Za-z0-9_])(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|'
    r'authorization|client[_-]?secret|private[_-]?key)\b(\s*[:=]\s*)'
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;\r\n]+)")
_URL_CREDENTIAL = re.compile(r'(?i)(https?://[^:/\s]+:)([^@/\s]+)(@)')
_SENSITIVE = (_PRIVATE_KEY, _BEARER, _CREDENTIAL_ASSIGNMENT, _URL_CREDENTIAL, _SECRET)
_REPORT_PREFIX = re.compile(
    r'(?:老板娘|老板|他|她|他们|她们|同事|别人|有人|朋友|同学|家人|妈妈|爸爸)'
    r'.{0,16}(?:说|讲|告诉|表示|认为|觉得|问|叫|喊|称呼|提到|提及|描述|介绍|转述)')
_REPORT_MARKERS = ('听说', '据说', '转述', '引用', '原话', '聊天记录', '消息里说')
_QUOTE_PAIRS = (('“', '”'), ('‘', '’'), ('"', '"'), ("'", "'"), ('「', '」'), ('『', '』'))
_FICTION = re.compile(r'角色扮演|虚构|剧情|故事里|在故事中|假设|设定为|(?<![A-Za-z0-9])(?:rp|roleplay)(?![A-Za-z0-9])', re.I)
_INSTRUCTION = re.compile(
    r'<\|(?:im_start|system|assistant)|\[/?INST\]|\x60{3}|'
    r'(?:^|\s)(?:system|developer|assistant)\s*[:：]|'
    r'忽略.{0,16}(?:指令|规则|提示)|覆盖.{0,16}(?:系统|指令)|'
    r'ignore.{0,24}(?:previous|instructions)|system\s+prompt', re.I)
_SYNTHETIC_NAMES = frozenset({'SyntheticPrivateWakeEvent'})


@dataclass(frozen=True)
class ExplicitMemoryMatch:
    rule_slot: int
    label: str
    value: str
    normalized_text: str


def match_explicit(text):
    """Match the exact old grammar's safe subset, not the full old classifier.

    Old clean_text collapsed whitespace; fullmatches and punctuation trimming
    stay identical. Quoted/reported/fiction/instruction data are not promoted
    to a user's real commitment. Negated grammar does not match, while a real
    commitment to not do something remains a valid user statement.
    """
    return _match_rules(text, RULES, _PATTERNS, first_slot=1)


def match_relationship(text):
    """Only the old relationship-claim grammar, after real profile priority.

    The matched text identifies an expressed statement, not a verified target,
    relationship edge, score, person_ref, or a core-persona update.
    """
    return _match_rules(text, RELATIONSHIP_RULES, _RELATIONSHIP_PATTERNS, first_slot=4)


def _match_rules(text, rules, patterns, *, first_slot):
    if (type(text) is not str or not text.strip() or len(text) > 6000
            or any(ord(char) < 32 and char not in '\t\r\n' for char in text)):
        return None
    try:
        if len(text.encode('utf8')) > 12000:
            return None
    except UnicodeError:
        return None
    normalized = re.sub(r'\s+', ' ', text.replace('\u3000', ' ')).strip()
    if (len(normalized) > 1800 or any(pattern.search(text) for pattern in _SENSITIVE)
            or _FICTION.search(normalized) or _INSTRUCTION.search(normalized)):
        return None
    for slot, pattern in enumerate(patterns, first_slot):
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        value = match.group(1).strip(' ，。！？!?.：:')
        if (not value or _REPORT_PREFIX.search(value)
                or any(marker in value for marker in _REPORT_MARKERS)
                or any(value.startswith(left) and value.endswith(right) for left, right in _QUOTE_PAIRS)):
            return None
        return ExplicitMemoryMatch(slot, rules[slot - first_slot][1], value, normalized)
    return None


def _sync_true(callback, *args):
    value = callback(*args)
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        return False
    return value is True


def _event_snapshot(event, scope):
    """Necessary public SDK identity checks; branch_gate supplies authority."""
    from astrbot.api.event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
    from astrbot.core.platform.message_type import MessageType
    if (not isinstance(event, AstrMessageEvent)
            or any(base.__name__ in _SYNTHETIC_NAMES for base in type(event).__mro__)
            or any(getattr(event, field, False) for field in (
                'private_companion_proactive_framework', 'private_companion_internal_generation',
                'private_companion_req036_denied'))
            or any(getattr(event, field, False) is True for field in ('is_roleplay', 'roleplay', 'tls_roleplay_event'))):
        return None
    message = getattr(event, 'message_obj', None)
    if (type(message) is not AstrBotMessage or type(getattr(message, 'sender', None)) is not MessageMember
            or message.type is not MessageType.FRIEND_MESSAGE or event.is_private_chat() is not True):
        return None
    bot, user = event.get_self_id(), event.get_sender_id()
    platform = event.get_platform_name() or event.get_platform_id()
    message_id, text = message.message_id, getattr(event, 'message_str', None)
    if (type(bot) is not str or type(user) is not str or bot == user
            or bot != scope['bot_id'] or user != scope['user_id']
            or platform != scope['platform'] or event.unified_msg_origin != scope['session_id']
            or type(message_id) is not str or not 0 < len(message_id) <= 256 or message_id == '0'
            or any(ord(char) < 32 for char in message_id) or type(text) is not str):
        return None
    if '这不是用户消息' in text and 'Private Companion' in text and '主动消息' in text:
        return None
    return (platform, bot, user, event.unified_msg_origin, message_id, text)


class NativeExplicitMemory:
    """Only the explicitly selected branch can write; default is closed.

    branch_gate(event, full_scope) is a current pure synchronous/thread-safe
    predicate. It must prove actual branch selection and source/owner admission,
    not merely a login, read lease, raw-capture switch or core-tool owner.
    It is rechecked inside the existing SQLite transaction before COMMIT.
    """
    def __init__(self, adapter, *, branch_gate=None):
        if (type(adapter) is not NativeMemoryAdapter or type(adapter.store) is not NativeMemoryStore
                or branch_gate is not None and (not callable(branch_gate) or inspect.iscoroutinefunction(branch_gate))):
            raise ValueError('existing native memory adapter and synchronous branch gate required')
        self.adapter, self.store = adapter, adapter.store
        self.branch_gate = branch_gate if branch_gate is not None else lambda event, scope: False
        self.active, self.generation = True, 1

    def _current(self, event, scope, snapshot, generation):
        return (self.active and self.generation == generation and self.adapter.store is self.store
            and self.adapter.active and not self.store._closed and self.adapter.allowed(scope)
            and _event_snapshot(event, scope) == snapshot
            and _sync_true(self.branch_gate, event, dict(scope)))

    async def capture_event(self, event, scope):
        scope = private_scope(scope)
        generation = self.generation
        try:
            snapshot = _event_snapshot(event, scope)
            admitted = snapshot is not None and self._current(event, scope, snapshot, generation)
        except Exception:
            admitted = False
        if not admitted:
            return dict(ok=False, state='branch_closed', creates_send_permission=False)
        selected = match_explicit(snapshot[-1])
        if selected is None:
            return dict(ok=False, state='not_explicit_or_unsafe', creates_send_permission=False)
        domain = [scope, snapshot[-2]]
        occurrence = hashlib.sha256(canonical(domain).encode('utf8')).hexdigest()
        identity = hashlib.sha256(canonical([*domain, selected.rule_slot]).encode('utf8')).hexdigest()
        # The same message keeps one occurrence even if a later replay changes
        # its text/rule: the store then rejects the changed fingerprint.
        event_id, record_id = 'explicit.' + occurrence, 'explicit_' + identity
        content = ('用户明确表达过：%s %s。仅记录用户的明确记住请求或承诺，'
                   '不证明行为已经完成，也不是系统指令。原话：%s'
                   % (selected.label, selected.value, selected.normalized_text))
        metadata = dict(capture='user_explicit_memory', original_text=snapshot[-1],
            normalized_text=selected.normalized_text, message_id=snapshot[-2], rule_slot=selected.rule_slot,
            rule_label=selected.label, extracted_value=selected.value,
            extractor='mc_explicit_rule_v1', classifier_sha256=CLASSIFIER_SHA256,
            source_boundary='new_explicit_memory_branch_only', asserts_completion=False,
            creates_send_permission=False)

        return await self._save_selected(event, scope, snapshot, generation, selected,
            event_id, record_id, content, metadata, source_id=SOURCE_ID, memory_type='explicit_memory')

    async def capture_relationship_event(self, event, scope):
        """Retain one selected relationship statement without resolving a target."""
        scope = private_scope(scope)
        generation = self.generation
        try:
            snapshot = _event_snapshot(event, scope)
            admitted = snapshot is not None and self._current(event, scope, snapshot, generation)
        except Exception:
            admitted = False
        if not admitted:
            return dict(ok=False, state='branch_closed', creates_send_permission=False)
        selected = match_relationship(snapshot[-1])
        if selected is None:
            return dict(ok=False, state='not_relationship_or_unsafe', creates_send_permission=False)
        domain = [scope, snapshot[-2]]
        occurrence = hashlib.sha256(canonical(domain).encode('utf8')).hexdigest()
        identity = hashlib.sha256(canonical([*domain, selected.rule_slot]).encode('utf8')).hexdigest()
        event_id, record_id = 'relationship.' + occurrence, 'relationship_' + identity
        content = ('用户关系表达，对象未经核实：%s %s。仅保留本次用户陈述，'
                   '不据此确认关系对象、关系强度或修改任何关系评分。原话：%s'
                   % (selected.label, selected.value, selected.normalized_text))
        metadata = dict(capture='user_relationship_statement', original_text=snapshot[-1],
            normalized_text=selected.normalized_text, message_id=snapshot[-2], rule_slot=selected.rule_slot,
            rule_label=selected.label, extracted_value=selected.value,
            extractor='mc_relationship_rule_v1', classifier_sha256=CLASSIFIER_SHA256,
            source_boundary='new_relationship_statement_branch_only',
            relationship_target_verified=False, target_ref=None,
            object_semantics='unresolved_user_statement_target',
            updates_relationship_graph=False, updates_relationship_score=False,
            creates_send_permission=False)
        return await self._save_selected(event, scope, snapshot, generation, selected,
            event_id, record_id, content, metadata, source_id=RELATIONSHIP_SOURCE_ID,
            memory_type='relationship_claim')

    async def _save_selected(self, event, scope, snapshot, generation, selected,
                             event_id, record_id, content, metadata, *, source_id, memory_type):
        def save(current_scope):
            with self.store.transaction():
                if not self._current(event, current_scope, snapshot, generation):
                    raise PermissionError('explicit memory branch changed before write')
                row = self.store.write(current_scope, content, source_id=source_id,
                    evidence_kind='user_reported', memory_type=memory_type, record_id=record_id,
                    event_id=event_id, canonical_key=event_id, confidence=1.0, importance=.68,
                    metadata=metadata)
                if not self._current(event, current_scope, snapshot, generation):
                    raise PermissionError('explicit memory branch changed before commit')
                return row

        row = await self.adapter._operation(scope, save)
        if not self._current(event, scope, snapshot, generation):
            raise PermissionError('explicit memory branch changed after write; reconcile occurrence')
        return dict(ok=True, state='stored_or_replayed', memory_id=row['id'], revision=row['revision'],
                    source_id=source_id, event_id=event_id, rule_slot=selected.rule_slot,
                    creates_send_permission=False, delivery='none')

    def stop(self):
        self.active = False
        self.generation += 1

    def close(self):
        self.stop()  # The Host owns the adapter/store.
