"""Prepare one owned QQ sticker, then send it separately after the text stage.

No hook is registered here. The host calls prepare() from its final reply
decorator and after_sent() from the SDK's after-message hook. The original
text chain is never mutated. Durable attempts prevent automatic replay after
cancellation or an uncertain send; even 'sent' is not QQ delivery evidence.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re
import time
from weakref import WeakKeyDictionary

from .journal import JournalConflict
from .models import private_scope, canonical, plain, scope_key

NAMESPACE = 'tls.expression.reply.v1'
_HEX = re.compile(r'[a-f0-9]{64}\Z')
SETTINGS_DEFAULTS = {'living_expression_reply_enabled': True,
    'living_expression_reply_daily_limit': 8, 'living_expression_reply_cooldown_minutes': 10}


def validate_settings(values):
    if not isinstance(values, dict) or set(values) != set(SETTINGS_DEFAULTS):
        raise ValueError('complete expression reply settings required')
    if type(values['living_expression_reply_enabled']) is not bool:
        raise ValueError('explicit expression reply enabled flag required')
    for key, upper in [('living_expression_reply_daily_limit', 10), ('living_expression_reply_cooldown_minutes', 1440)]:
        if type(values[key]) is not int or not 1 <= values[key] <= upper:
            raise ValueError('invalid expression reply dynamic limit')
    return dict(values)


def _result(state, reason=''):
    return {'state': state, 'reason': reason, 'appended': 0,
            'send_calls': int(state == 'sent'), 'delivery_confirmed': False}


class _SelectedAssetGuard:
    """Carry one candidate through the existing claim callback contract."""
    __slots__ = ('policy', 'asset_id', 'asset_revision', 'rotation_revision', 'check')

    def __init__(self, policy, candidate, check):
        self.policy, self.check = policy, check
        self.asset_id, self.asset_revision = candidate['id'], candidate['revision']
        self.rotation_revision = candidate['rotation_revision']

    def __call__(self):
        return self.check() is True


class NativeExpressionReplyPolicy:
    """Explicit tag matches and conservative persistent sticker admission.

    Existing usage and one bounded rotation checkpoint per private scope own
    all CAS decisions. Receipts are bounded and never evicted to enable old replays;
    capacity exhaustion skips sending. No raw text or message/user ID is
    retained here. Defaults are at most three attempts per local day, spaced
    thirty minutes apart, using the configured local day. Empty/no-match
    libraries consume no allowance. Legacy attempt/appended/failed remain
    readable. The historical appended phase now also means the separate SDK
    send coroutine returned; it is never evidence of QQ delivery.
    """

    def __init__(self, journal, assets, *, authorize, clock=time.time,
                 cooldown_seconds=1800, daily_limit=3, max_events=512, tz_offset_minutes=480, settings=None):
        if not callable(authorize):
            raise ValueError('expression reply authorizer required')
        if (type(cooldown_seconds) not in (int, float) or not math.isfinite(cooldown_seconds)
                or not 1 <= cooldown_seconds <= 86400):
            raise ValueError('invalid expression reply cooldown')
        if type(daily_limit) is not int or not 1 <= daily_limit <= 10:
            raise ValueError('invalid expression reply daily limit')
        if type(max_events) is not int or not 1 <= max_events <= 512:
            raise ValueError('invalid expression reply receipt capacity')
        if type(tz_offset_minutes) is not int or not -720 <= tz_offset_minutes <= 840:
            raise ValueError('invalid expression reply timezone')
        if settings is not None and not callable(settings):
            raise ValueError('dynamic expression reply settings callback required')
        self.journal, self.assets, self.clock = journal, assets, clock
        self._authorize = authorize
        self.cooldown_seconds, self.daily_limit, self.max_events = cooldown_seconds, daily_limit, max_events
        self.tz_offset_minutes = tz_offset_minutes
        self.settings = settings
        self.active = True

    def settings_token(self):
        if self.settings is None:
            return (True, self.daily_limit, self.cooldown_seconds)
        values = validate_settings(self.settings())
        return (values['living_expression_reply_enabled'], values['living_expression_reply_daily_limit'],
                values['living_expression_reply_cooldown_minutes'] * 60)

    def _admitted(self, scope):
        return self.active and self.assets.active and self._authorize(private_scope(scope)) is True

    def allowed(self, scope):
        return self._admitted(scope) and self.settings_token()[0]

    def _scope(self, scope):
        scope = private_scope(scope)
        if not self.allowed(scope):
            raise PermissionError('expression reply scope unavailable')
        return scope

    def candidate(self, scope, text):
        """Choose a matching, least-recently SDK-returned approved image.

        Explicit tag matches precede caption-only matches. Within that relevant
        tier, never-successfully-used assets precede the least recent success.
        Public preview ranking remains unchanged; sender uses the bounded pool.
        """
        from .native_expression_assets import ExpressionAssetError
        scope = self._scope(scope)
        if not isinstance(text, str):
            raise ValueError('expression reply text required')
        if len(text) > 2000:
            return {'state': 'reply_too_long'}
        matches = getattr(self.assets, '_ranked_matches', None)
        if callable(matches):
            selected = matches(scope, text)
            ranked = selected['ranked']
        else:
            selected = self.assets.select(scope, text, limit=8)
            ranked = [(-1, row['id'], row) for row in selected['assets']]
        if selected['state'] != 'selected' or not ranked:
            return {'state': selected['state']}
        if not isinstance(ranked, list) or len(ranked) > 256:
            raise ValueError('invalid bounded expression candidate pool')
        for score, identity, row in ranked:
            if type(score) is not int or not -166 <= score < 0 or not _HEX.fullmatch(identity):
                raise ValueError('invalid expression candidate rank')
        rotation, history = self._rotation(scope)
        pending = {value['asset_id'] for value in history['pending'].values()}
        available = [item for item in ranked if item[1] not in pending]
        explicit = [item for item in available if item[0] <= -10]
        pool = explicit or available
        if not pool:
            # Preparation remains compatible for a replay of an already
            # claimed message. claim() will return duplicate for that message
            # or reject an uncertain pending asset for every new message.
            pool = [item for item in ranked if item[0] <= -10] or list(ranked)
        pool.sort(key=lambda item: (history['successful_assets'].get(item[1], 0), item[0], item[1]))
        for _, _, row in pool:
            try:
                raw = self.assets.read_bytes(scope, row['id'], expected_revision=row['revision'])
            except ExpressionAssetError:
                continue
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('expression asset bytes do not match reviewed identity')
            self._scope(scope)
            return {'state': 'selected', 'id': row['id'], 'revision': row['revision'], 'raw': raw,
                    'rotation_revision': rotation['revision'] if rotation else 0,
                    'asset_pending': row['id'] in pending}
        return {'state': 'matching_asset_files_unavailable'}

    def current(self, scope, candidate):
        """Final bounded local check after all awaits; never return a path."""
        scope = self._scope(scope)
        row = self.assets.get(scope, candidate['id'])
        return (row is not None and row['revision'] == candidate['revision']
                and row['enabled'] is True and row['deleted'] is False and self.allowed(scope))

    def _now(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now <= 253402300799:
            raise ValueError('invalid expression reply clock')
        return now

    def _usage(self, scope, day):
        checkpoint = self.journal.fetch(NAMESPACE, 'usage', scope)
        data = checkpoint['data'] if checkpoint else {
            'schema': 1, 'events': {}, 'last_attempt_at': None, 'day': day,
            'tz_offset_minutes': self.tz_offset_minutes, 'day_count': 0}
        if (not isinstance(data, dict) or set(data) != {'schema', 'events', 'last_attempt_at', 'day', 'tz_offset_minutes', 'day_count'}
                or data['schema'] != 1 or not isinstance(data['events'], dict)
                or any(not isinstance(key, str) or not _HEX.fullmatch(key) for key in data['events'])
                or any(not isinstance(value, dict) or set(value) != {'at', 'phase'}
                       or value['phase'] not in {'attempt', 'appended', 'failed'}
                       or type(value['at']) not in (int, float) or not math.isfinite(value['at']) or value['at'] < 0
                       for value in data['events'].values())
                or type(data['day_count']) is not int or not 0 <= data['day_count'] <= 10
                or data['tz_offset_minutes'] != self.tz_offset_minutes
                or not isinstance(data['day'], str)
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', data['day'])):
            raise ValueError('invalid expression reply checkpoint')
        return checkpoint, data

    def _rotation(self, scope, *, journal=None):
        journal = journal or self.journal
        row = journal.fetch(NAMESPACE, 'rotation', scope)
        data = row['data'] if row else dict(schema=1, sequence=0, successful_assets={}, pending={})
        if (type(data) is not dict or set(data) != {'schema','sequence','successful_assets','pending'}
                or type(data['schema']) is not int or data['schema'] != 1
                or type(data['sequence']) is not int or not 0 <= data['sequence'] <= 1000000
                or type(data['successful_assets']) is not dict or len(data['successful_assets']) > 256
                or any(type(key) is not str or not _HEX.fullmatch(key)
                    or type(value) is not int or not 1 <= value <= data['sequence']
                    for key,value in data['successful_assets'].items())
                or type(data['pending']) is not dict or len(data['pending']) > 64
                or any(type(key) is not str or not _HEX.fullmatch(key) or type(value) is not dict
                    or set(value) != {'asset_id','asset_revision'}
                    or type(value['asset_id']) is not str or not _HEX.fullmatch(value['asset_id'])
                    or type(value['asset_revision']) is not int or value['asset_revision'] < 1
                    for key,value in data['pending'].items())):
            raise ValueError('invalid expression rotation checkpoint')
        return row, data

    @staticmethod
    def _write_records(journal, scope, records, *, authorize=None):
        """Original journal transaction/CAS; no new table or per-event row.

        Usage v1 keeps its old shape, including after source rollback. Rotation
        has a single bounded scope checkpoint and never grants another send.
        """
        key = scope_key(private_scope(scope))
        encoded = [(name, prior['revision'] if prior else 0, canonical(plain(data,65536)))
                   for name,prior,data in records]
        with journal._transaction() as db:
            if authorize is not None and authorize() is not True:
                raise PermissionError('expression checkpoint authority changed')
            missing = 0
            for name,expected,_ in encoded:
                prior = db.execute('SELECT revision FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
                    (NAMESPACE,name,key)).fetchone()
                if (prior[0] if prior else 0) != expected:
                    raise JournalConflict('expression checkpoint revision conflict')
                missing += int(prior is None)
            if missing and db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] + missing > journal.max_records:
                raise RuntimeError('checkpoint capacity reached')
            updated = journal.clock()
            for name,expected,value in encoded:
                db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope) '
                    'DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data',
                    (NAMESPACE,name,key,expected+1,updated,value))
            if authorize is not None and authorize() is not True:
                raise PermissionError('expression checkpoint authority changed')

    def _quota(self, data, now, settings, day):
        count = data['day_count'] if data['day'] == day else 0
        if not settings[0]:
            return 'disabled', count
        previous = data['last_attempt_at']
        if previous is not None:
            if type(previous) not in (int, float) or not math.isfinite(previous) or previous < 0:
                raise ValueError('invalid expression reply checkpoint time')
            if now < previous:
                return 'clock_reversed', count
            if now - previous < settings[2]:
                return 'cooldown', count
        if count >= settings[1]:
            return 'daily_limit', count
        if len(data['events']) >= self.max_events:
            return 'receipt_capacity', count
        return 'eligible', count

    def preflight(self, scope):
        """Read current quota without a message ID, reservation or checkpoint write."""
        scope = private_scope(scope)
        if not self._admitted(scope):
            raise PermissionError('expression reply preview scope unavailable')
        settings = self.settings_token();now = self._now()
        day = datetime.fromtimestamp(now, timezone(timedelta(minutes=self.tz_offset_minutes))).strftime('%Y-%m-%d')
        _, data = self._usage(scope, day)
        state, count = self._quota(data, now, settings, day)
        if not self._admitted(scope) or self.settings_token() != settings:
            return {'checked': False, 'state': 'settings_or_authority_changed', 'eligible': False}
        return {'checked': True, 'state': state, 'eligible': state == 'eligible', 'day': day,
                'tz_offset_minutes': self.tz_offset_minutes, 'daily_limit': settings[1], 'used_today': count,
                'remaining_today': max(0, settings[1] - count), 'cooldown_seconds': settings[2],
                'wait_seconds': max(0, data['last_attempt_at'] + settings[2] - now)
                    if data['last_attempt_at'] is not None else 0,
                'message_dedup_checked': False, 'reservation_written': False}

    def claim(self, scope, message_id, *, guard):
        """CAS an attempt once; no retry after a conflicting or uncertain write."""
        scope = self._scope(scope)
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 256 or message_id == '0':
            return 'missing_message_identity'
        if not callable(guard) or guard() is not True:
            return 'context_changed'
        settings = self.settings_token();now = self._now()
        day = datetime.fromtimestamp(now, timezone(timedelta(minutes=self.tz_offset_minutes))).strftime('%Y-%m-%d')
        checkpoint, data = self._usage(scope, day)
        identity = hashlib.sha256(message_id.encode()).hexdigest()
        if identity in data['events']:
            return 'duplicate'
        state, count = self._quota(data, now, settings, day)
        if state != 'eligible':
            return state
        changed = dict(data, events={**data['events'], identity: {'at': now, 'phase': 'attempt'}},
                       last_attempt_at=now, day=day, day_count=count + 1)
        if type(guard) is _SelectedAssetGuard:
            if (guard.policy is not self or type(guard.asset_id) is not str or not _HEX.fullmatch(guard.asset_id)
                    or type(guard.asset_revision) is not int or guard.asset_revision < 1
                    or type(guard.rotation_revision) is not int or guard.rotation_revision < 0):
                raise ValueError('invalid expression selection claim')
            rotation, history = self._rotation(scope)
            if (rotation['revision'] if rotation else 0) != guard.rotation_revision:
                return 'candidate_history_changed'
            if len(history['pending']) >= 64:
                return 'rotation_receipt_capacity'
            if guard.asset_id in {value['asset_id'] for value in history['pending'].values()}:
                return 'candidate_already_pending'
            updated = dict(history,pending={**history['pending'],identity:
                dict(asset_id=guard.asset_id,asset_revision=guard.asset_revision)})
            try:
                self._write_records(self.journal,scope,[('usage',checkpoint,changed),('rotation',rotation,updated)],
                    authorize=lambda:self.allowed(scope) and self.settings_token()==settings and guard() is True)
            except JournalConflict:
                return 'concurrent_claim'
            return 'claimed'
        try:
            self.journal.put(NAMESPACE, 'usage', scope, changed,
                expected_revision=checkpoint['revision'] if checkpoint else 0,
                authorize=lambda: self.allowed(scope) and self.settings_token() == settings and guard() is True)
        except JournalConflict:
            return 'concurrent_claim'
        return 'claimed'

    def finish(self, scope, message_id, phase, *, expected_journal=None):
        """Complete only an owned attempt, including after permission withdrawal.

        This writes a receipt, not another asset decision. If a process dies or
        cancellation makes the outcome uncertain, 'attempt' remains durable and
        blocks automatic replay. Failed attempts also retain their allowance.
        """
        if phase not in {'appended', 'failed'}:
            raise ValueError('invalid expression decoration phase')
        journal = self.journal
        if expected_journal is not None and journal is not expected_journal:
            raise JournalConflict('expression receipt journal changed')
        scope = private_scope(scope)
        row = journal.fetch(NAMESPACE, 'usage', scope)
        identity = hashlib.sha256(message_id.encode()).hexdigest()
        if row is None or identity not in row['data']['events']:
            raise JournalConflict('expression decoration attempt missing')
        event = row['data']['events'][identity]
        if event['phase'] == phase:
            return
        if event['phase'] != 'attempt':
            raise JournalConflict('expression decoration attempt already completed')
        changed = dict(row['data'], events={**row['data']['events'], identity: dict(event, phase=phase)})
        rotation, history = self._rotation(scope,journal=journal)
        pending = history['pending'].get(identity)
        if pending is not None:
            remaining = dict(history['pending']);remaining.pop(identity)
            successes = dict(history['successful_assets']);sequence = history['sequence']
            if phase == 'appended':
                sequence += 1
                if sequence > 1000000 or pending['asset_id'] not in successes and len(successes) >= 256:
                    raise ValueError('expression rotation capacity reached')
                successes[pending['asset_id']] = sequence
            updated = dict(history,sequence=sequence,successful_assets=successes,pending=remaining)
            self._write_records(journal,scope,[('usage',row,changed),('rotation',rotation,updated)])
            return
        journal.put(NAMESPACE, 'usage', scope, changed, expected_revision=row['revision'])

    def stop(self):
        # Shared journal/assets are owned by the runtime, not this adapter.
        self.active = False


class NativeExpressionReplyAdapter:
    def __init__(self, policy, *, scope_for, authorize):
        if not callable(scope_for) or not callable(authorize):
            raise ValueError('trusted expression reply scope resolver required')
        self.policy, self.scope_for, self._authorize = policy, scope_for, authorize
        # Values contain no event reference. Abandoned SDK events can be collected.
        self._pending = WeakKeyDictionary()

    def _scope(self, event):
        resolved = self.scope_for(event)
        if resolved is None:
            raise PermissionError('expression reply scope unavailable')
        scope = private_scope(resolved)
        if (self._authorize(scope) is not True or not self.policy.allowed(scope)
                or scope['platform'] != event.get_platform_name()
                or scope['bot_id'] != event.get_self_id()
                or scope['user_id'] != event.get_sender_id()
                or scope['session_id'] != event.unified_msg_origin):
            raise PermissionError('expression reply event scope mismatch')
        return scope

    @staticmethod
    def _eligible(event):
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        from astrbot.core.star.filter.command import CommandFilter
        from astrbot.core.star.filter.command_group import CommandGroupFilter
        from astrbot.api.message_components import Plain
        if not isinstance(event, AiocqhttpMessageEvent):
            return None, 'not_qq_sdk_event'
        if (not event.is_private_chat() or event.get_group_id() or event.is_stopped()
                or getattr(event, 'private_companion_proactive_framework', False)
                or event.get_sender_id() == event.get_self_id()):
            return None, 'not_ordinary_private'
        # is_at_or_wake_command is also True for ordinary private chat in 4.26.6.
        if (event.message_str.lstrip().startswith('/') or event.get_extra('handlers_parsed_params', {})
                or event.get_extra('parsed_params') is not None):
            return None, 'command'
        for handler in event.get_extra('activated_handlers', []):
            if any(isinstance(item, (CommandFilter, CommandGroupFilter)) for item in handler.event_filters):
                return None, 'command'
        result = event.get_result()
        if (result is None or not result.is_llm_result() or result.async_stream is not None
                or not isinstance(result.chain, list) or not result.chain
                or any(not isinstance(item, Plain) for item in result.chain)):
            return None, 'not_plain_llm_reply'
        if not any(item.text.strip() for item in result.chain):
            return None, 'empty_reply'
        return result, ''

    def _guard(self, event, pending, *, sent):
        policy = pending['policy']
        current, _ = self._eligible(event)
        return (self.policy is policy and policy.journal is pending['journal']
            and policy.assets is pending['assets']
            and self.scope_for is pending['scope_for']
            and self._authorize is pending['authorize']
            and policy._authorize is pending['policy_authorize']
            and current is pending['result']
            # SDK segmentation replaces Plain objects and strips boundary whitespace.
            # Only Unicode whitespace is ignored; punctuation/content stay exact.
            and ''.join(''.join(item.text for item in current.chain).split()) == pending['text_token']
            and getattr(event, '_has_send_oper', None) is sent
            and getattr(event.message_obj, 'message_id', '') == pending['message_id']
            and policy.settings_token() == pending['settings']
            and self._scope(event) == pending['scope'])

    async def prepare(self, event):
        """Read a reviewed candidate without changing the text, quota or send flag."""
        from .native_expression_assets import ExpressionAssetError
        result, reason = self._eligible(event)
        if result is None:
            try:
                self._pending.pop(event, None)
            except TypeError:
                pass
            return _result('skipped', reason)
        self._pending.pop(event, None)
        if getattr(event, '_has_send_oper', None) is not False:
            return _result('skipped', 'earlier_send')
        token = object()
        self._pending[event] = token
        try:
            scope = self._scope(event)
            message_id = getattr(event.message_obj, 'message_id', '')
            if not isinstance(message_id, str) or not message_id or message_id == '0' or len(message_id) > 256:
                return _result('skipped', 'missing_message_identity')
            policy = self.policy
            pending = dict(policy=policy, journal=policy.journal, assets=policy.assets,
                scope_for=self.scope_for, authorize=self._authorize, policy_authorize=policy._authorize,
                result=result, snapshot=tuple((id(item), item.text) for item in result.chain),
                text_token=''.join(''.join(item.text for item in result.chain).split()),
                scope=scope, message_id=message_id, settings=policy.settings_token())
            candidate = await asyncio.to_thread(self.policy.candidate, scope,
                '\n'.join(value[1] for value in pending['snapshot']))
            if candidate['state'] != 'selected':
                return _result('skipped', candidate['state'])
            if (self._pending.get(event) is not token or not self._guard(event, pending, sent=False)
                    or not policy.current(scope, candidate)):
                return _result('skipped', 'context_changed')
            pending['candidate'] = candidate
            self._pending[event] = pending
            return _result('prepared')
        except (PermissionError, KeyError, JournalConflict, ExpressionAssetError):
            return _result('skipped', 'asset_or_authority_changed')
        finally:
            if self._pending.get(event) is token:
                self._pending.pop(event, None)

    async def after_sent(self, event):
        """Consume one preparation after QQ's send flag changes from False to True.

        The flag is cumulative: segmented text may only have partly succeeded.
        It is never a receipt that the whole text or sticker was seen by QQ.
        """
        from .native_expression_assets import ExpressionAssetError
        from .native_qq_sticker import build_qq_sticker_chain
        result, reason = self._eligible(event)
        if result is None:
            # Non-SDK inputs cannot be weak keys; real events may have become ineligible.
            try:
                self._pending.pop(event, None)
            except TypeError:
                pass
            return _result('skipped', reason)
        pending = self._pending.pop(event, None)
        if not isinstance(pending, dict):
            return _result('skipped', 'no_preparation')
        policy, scope = pending['policy'], pending['scope']
        message_id, candidate = pending['message_id'], pending['candidate']
        def guard():
            return self._guard(event, pending, sent=True)
        try:
            if not guard() or not policy.current(scope, candidate):
                return _result('skipped', 'context_changed')
        except (PermissionError, KeyError, JournalConflict, ExpressionAssetError):
            return _result('skipped', 'asset_or_authority_changed')
        # SDK construction errors propagate before any allowance is claimed.
        sticker = build_qq_sticker_chain(candidate['raw'])
        try:
            selected_guard = _SelectedAssetGuard(policy,candidate,
                lambda: guard() and policy.current(scope,candidate))
            claimed = await asyncio.to_thread(policy.claim, scope, message_id, guard=selected_guard)
            if claimed != 'claimed':
                return _result('skipped', claimed)
        except (PermissionError, KeyError, JournalConflict, ExpressionAssetError):
            return _result('skipped', 'asset_or_authority_changed')
        try:
            current = guard() and policy.current(scope, candidate)
        except (PermissionError, KeyError, JournalConflict, ExpressionAssetError):
            current = False
        if not current:
            await asyncio.to_thread(policy.finish, scope, message_id, 'failed', expected_journal=pending['journal'])
            return _result('skipped', 'context_changed_after_claim')
        # No await between final checks and invoking the event's own QQ transport.
        try:
            await event.send(sticker)
        except asyncio.CancelledError:
            # The transport may have accepted it. Retain attempt and never replay.
            raise
        except Exception as error:
            try:
                await asyncio.shield(asyncio.to_thread(policy.finish, scope, message_id, 'failed',
                    expected_journal=pending['journal']))
            except BaseException:
                error.add_note('Sticker receipt remains uncertain; automatic replay is blocked.')
            raise
        # Preserve the R29 storage vocabulary for source rollback compatibility.
        await asyncio.to_thread(policy.finish, scope, message_id, 'appended', expected_journal=pending['journal'])
        return _result('sent')

    async def decorate(self, event):
        """Legacy single-hook callers must not append or silently send a sticker."""
        return _result('skipped', 'separate_hooks_required')

    def stop(self):
        self._pending.clear()
        self.policy.stop()

    async def close(self):
        self.stop()
