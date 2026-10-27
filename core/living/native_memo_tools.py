"""Bounded native memo tool routing. No tool registration or implicit handoff.

The host supplies current genuine-event binding and the separately persisted
memo owner. The old core-tool owner and Phone source grants are not authority
for this feature. An existing PC schema may use the returned `handled` flag;
only `handled=False` permits the old implementation. No old function is called.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import inspect
import re
import threading

from .journal import JournalConflict
from .models import canonical, private_scope
from .native_memo_notes import NativeMemoNotes

FEATURE = 'tls.memo.tool.nonreminder.v1'
_ID = re.compile(r'memo\.[a-f0-9]{64}\Z')
_FIELDS = frozenset(('action', 'title', 'content', 'selector', 'due_at', 'repeat', 'color',
    'remind_enabled', 'include_completed', 'status', 'query', 'clear_due', 'clear_content', 'confirmation_token'))
_ACTIONS = {'': 'list', 'add': 'create', 'create': 'create', 'list': 'list', 'get': 'get',
    'update': 'update', 'edit': 'update', 'complete': 'complete', 'done': 'complete',
    'reopen': 'reopen', 'pin': 'pin', 'unpin': 'unpin', 'delete': 'archive', 'remove': 'archive', 'archive': 'archive',
    '查看': 'list', '列表': 'list', '查询': 'list', '详情': 'get', '查看详情': 'get',
    '新增': 'create', '添加': 'create', '创建': 'create', '记录': 'create', '修改': 'update', '编辑': 'update',
    '完成': 'complete', '办完': 'complete', '恢复': 'reopen', '重新打开': 'reopen',
    '置顶': 'pin', '取消置顶': 'unpin', '删除': 'archive'}
_STATUSES = {'进行中': 'active', '未完成': 'active', '待办': 'active',
    '完成': 'completed', '已完成': 'completed', '历史': 'completed', '全部': 'all'}
_BOUNDARY = dict(storage='tls_native_memo_notes', metadata_only=True, schedules_reminder=False,
    external_completion_confirmed=False, legacy_records_included=False, legacy_listing_retained=True,
    ai_material_is_user_verbatim=False)


def _hash(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def _legacy(reason):
    return dict(handled=False, legacy_allowed=True, state='legacy', reason=reason)


def _reply(state, *, action='', saved=False, **value):
    return dict(handled=True, legacy_allowed=False, state=state,
        response=dict(status='success' if state == 'ok' else state, action=action, saved=saved,
                      **_BOUNDARY, **value))


def _text(value, maximum, *, empty=True):
    if (type(value) is not str or len(value) > maximum or not empty and not value.strip()
            or any(ord(char) < 32 and char not in '\t\r\n' for char in value)):
        raise ValueError('bounded typed memo text required')
    return value


def _zero_due(value):
    return value is None or type(value) is str and value == '' or type(value) in (int, float) and value == 0


def _eligible_create(payload):
    return (_zero_due(payload.get('due_at', '')) and payload.get('repeat', '') in ('', 'none')
        and (payload.get('remind_enabled') is None or payload.get('remind_enabled') is False))


def occurrence(event, scope, payload):
    """Stable platform message+instruction+normalized operation, never a new retry ID."""
    identity = getattr(getattr(event, 'message_obj', None), 'message_id', None)
    if type(identity) not in (str, int) or isinstance(identity, bool):
        raise PermissionError('identified genuine inbound required')
    identity = str(identity)
    text = getattr(event, 'message_str', None)
    if not identity or identity == '0' or len(identity) > 256:
        raise PermissionError('identified genuine inbound required')
    _text(text, 6000, empty=False)
    message_ref = hashlib.sha256(identity.encode('utf8')).hexdigest()
    instruction_ref = hashlib.sha256(text.encode('utf8')).hexdigest()
    request_id = 'memo_' + _hash([FEATURE, scope, message_ref, instruction_ref, payload])
    return request_id, message_ref, instruction_ref


@dataclass(eq=False)
class _Lease:
    active: bool = True
    view: object = None


class NativeMemoTools:
    """Host-owned adapter over the actual shared NativeMemoNotes service.

    `scope_for_event(event)` and `authorize_scope(scope)` are synchronous host
    callbacks. `owner_for_scope(scope)` returns exactly {mode, generation}, with
    mode legacy/native/closed and a nonnegative exact integer generation.
    Only native/generation>=1 can execute; the adapter never creates an owner.
    `current_service()` proves the captured service was not replaced.

    Generic list stays with the old tool to avoid hiding old records. The host
    may call list with internal native_only=True for an explicitly labelled
    native subsection or a separately reviewed merged list.
    """
    def __init__(self, notes, *, scope_for_event, authorize_scope, owner_for_scope,
                 current_service, native_identity, timeout_seconds=5.0):
        if (type(notes) is not NativeMemoNotes
                or any(not callable(fn) for fn in (scope_for_event, authorize_scope, owner_for_scope, current_service, native_identity))
                or type(timeout_seconds) not in (int, float) or not .05 <= timeout_seconds <= 5):
            raise ValueError('current native memo service and typed host callbacks required')
        self.notes = notes
        self.scope_for_event, self.authorize_scope = scope_for_event, authorize_scope
        self.owner_for_scope, self.current_service = owner_for_scope, current_service
        self.native_identity = native_identity
        self.timeout_seconds = float(timeout_seconds)
        self._bindings = (notes, notes.journal, notes.authorize, notes.clock,
            scope_for_event, authorize_scope, owner_for_scope, current_service, native_identity)
        self.active = True
        self._lock = threading.RLock()
        self._pending = set()

    def _resources(self):
        return (self.active and self.notes.active and self.current_service() is self.notes
            and all(a is b for a, b in zip(self._bindings, (self.notes, self.notes.journal,
                self.notes.authorize, self.notes.clock, self.scope_for_event, self.authorize_scope,
                self.owner_for_scope, self.current_service, self.native_identity))))

    def _scope(self, event):
        if (event is None or getattr(event, 'private_companion_proactive_framework', False)
                or getattr(event, 'private_companion_internal_generation', False)
                or event.is_private_chat() is not True or not self._resources()
                or str(event.get_self_id() or '') == str(event.get_sender_id() or '')):
            raise PermissionError('genuine private memo event required')
        identity = self.native_identity(event)
        if inspect.isawaitable(identity):
            if inspect.iscoroutine(identity): identity.close()
            raise PermissionError('synchronous genuine native identity required')
        if identity is not True: raise PermissionError('native identity domain denied')
        scope = private_scope(self.scope_for_event(event))
        if (str(event.get_sender_id() or '') != scope['user_id']
                or str(event.get_self_id() or '') != scope['bot_id']
                or getattr(event, 'unified_msg_origin', None) != scope['session_id']
                or self.authorize_scope(dict(scope)) is not True or not self._resources()):
            raise PermissionError('current private memo binding required')
        return scope

    def _owner(self, scope):
        value = self.owner_for_scope(dict(scope))
        if (type(value) is not dict or set(value) != {'mode', 'generation'}
                or value['mode'] not in ('legacy', 'native', 'closed')
                or type(value['generation']) is not int or value['generation'] < 0
                or value['mode'] == 'native' and value['generation'] < 1):
            raise PermissionError('memo owner unknown')
        return dict(value)

    @staticmethod
    def _payload(value, action):
        if type(value) is not dict or set(value) - _FIELDS:
            raise ValueError('known memo tool fields required')
        result = dict(action=action)
        for key, maximum in (('title', 60), ('content', 800), ('selector', 128),
                             ('color', 16), ('status', 16), ('query', 100), ('confirmation_token', 128)):
            result[key] = _text(value.get(key, ''), maximum)
        for key in ('include_completed', 'clear_due', 'clear_content'):
            result[key] = value.get(key, False)
            if type(result[key]) is not bool:
                raise ValueError('exact memo flags required')
        if not _eligible_create(value):
            raise ValueError('only no-due nonreminder one-off memo operations supported')
        result.update(due_at=0., repeat='none', remind_enabled=False)
        if result['confirmation_token']:
            raise ValueError('legacy deletion token cannot authorize native archive')
        if action != 'create' and action != 'list' and not _ID.fullmatch(result['selector']):
            raise ValueError('exact native memo ID required')
        if action == 'create' and result['selector']:
            raise ValueError('create cannot select an existing memo')
        status = result['status'].strip().lower() or ('all' if result['include_completed'] else 'active')
        status = _STATUSES.get(status, status)
        if status not in ('active', 'completed', 'all'):
            raise ValueError('typed memo status required')
        result['status'] = status
        return result

    @staticmethod
    def _record(row):
        if (type(row) is not dict or type(row.get('provenance')) is not dict
                or type(row.get('fields')) is not dict or row['provenance'].get('kind') not in
                ('user_explicit', 'user_requested_ai_tool')
                or row['fields'].get('repeat') != 'none'
                or row['fields'].get('remind_enabled') is not False
                or row['fields'].get('due_at') != 0):
            raise ValueError('imported, recurring or reminder memo is outside tool slice')
        return row

    def _execute(self, view, scope, payload, request_id, message_ref, instruction_ref, *, legacy_create=False):
        action = payload['action']
        if legacy_create:
            # A successful native create has no selector in a replayed call.
            # Preserve its durable routing across rollback: only an authorized
            # and unchanged-owner read proving absence permits the old create.
            # The host must make owner changes under this same journal lock;
            # double checks alone are not a cross-store handoff mechanism.
            with view.journal._lock:
                view._scope(scope)
                row = view.get_request(scope, request_id)
                view._scope(scope)
                if row is not None:
                    return _reply('ok', action=action, saved=False, note=row, replayed=True,
                                  receipt_is_historical=True)
                return _legacy('authorized_absent_native_create_request')
        if action == 'list':
            rows = []
            for offset in (0, 100):
                page = view.search(scope, query=payload['query'], status=payload['status'],
                                   include_archived=False, limit=100, offset=offset)
                for row in page['records']:
                    try: rows.append(self._record(row))
                    except ValueError: pass  # Explicitly labelled narrow native subsection.
                if page['total'] <= offset + 100:
                    break
            return _reply('ok', action=action, records=rows[:20], total=len(rows), truncated=len(rows) > 20,
                          scope_of_list='native_nonreminder_oneoff_only')
        if action == 'create':
            create = getattr(view, 'create_from_tool', None)
            if not callable(create):
                return _reply('unavailable', action=action, code='tool_material_provenance_interface_missing')
            row = create(scope, request_id, message_ref=message_ref, instruction_ref=instruction_ref,
                title=payload['title'], content=payload['content'], color=payload['color'] or 'yellow',
                pinned=False, due_at=0., repeat='none', remind_enabled=False)
            return _reply('ok', action=action, saved=True, note=row)
        row = view.get(scope, payload['selector'])
        if row is None:
            return _reply('not_found', action=action)
        self._record(row)
        if action == 'get':
            return _reply('ok', action=action, note=row)
        if action == 'archive':
            # The old delete token is scoped to the old record store, not this
            # store. Do not invent a second confirmation ledger or permit a
            # replayed old request to archive a subsequently restored note.
            return _reply('confirmation_required', action=action, code='archive_native_memo_in_webui',
                          deleted=False, archived=row['archived'])
        lookup = getattr(view, 'get_action_request', None)
        if not callable(lookup):
            return _reply('unavailable', action=action, code='tool_action_replay_interface_missing')
        prior = lookup(scope, request_id)
        revision = row['revision']
        if prior is not None:
            expected_action = 'update_from_tool' if action in ('update', 'pin', 'unpin') else action
            if (type(prior) is not dict or set(prior) != {'action', 'record_id', 'expected_revision'}
                    or prior['action'] != expected_action or prior['record_id'] != row['id']
                    or type(prior['expected_revision']) is not int or prior['expected_revision'] < 1):
                raise JournalConflict('native memo request evidence conflict')
            revision = prior['expected_revision']
        elif row['archived']:
            return _reply('conflict', action=action, code='restore_archived_memo_in_webui')
        if action in ('update', 'pin', 'unpin'):
            update = getattr(view, 'update_from_tool', None)
            if not callable(update):
                return _reply('unavailable', action=action, code='tool_edit_provenance_interface_missing')
            changes = {'pinned': action == 'pin'} if action in ('pin', 'unpin') else {}
            if action == 'update':
                for key in ('title', 'color'):
                    if payload[key]: changes[key] = payload[key]
                if payload['content'] or payload['clear_content']:
                    changes['content'] = '' if payload['clear_content'] else payload['content']
                if payload['clear_due']:
                    changes.update(due_at=0., repeat='none', remind_enabled=False)
            if not changes:
                return _reply('invalid', action=action, code='memo_changes_required')
            row = update(scope, row['id'], expected_revision=revision, request_id=request_id,
                         message_ref=message_ref, instruction_ref=instruction_ref, **changes)
        elif action in ('complete', 'reopen'):
            row = getattr(view, action)(scope, row['id'], expected_revision=revision, request_id=request_id)
        else:
            return _reply('invalid', action=action, code='unsupported_native_memo_action')
        return _reply('ok', action=action, saved=True, note=row)

    async def handle(self, event, payload, *, native_only=False):
        """Return a typed decision. True/unknown/denied never permits fallback."""
        if type(payload) is not dict or type(native_only) is not bool:
            return _reply('invalid', code='typed_memo_request_required')
        selector = payload.get('selector', '')
        # Reserve the whole namespace. A malformed/stale TLS ID must not be
        # reinterpreted as an old title, index or partial-match selector.
        native_id = type(selector) is str and selector.startswith('memo.')
        raw_action = payload.get('action', 'list')
        action = _ACTIONS.get(raw_action.strip().lower()) if type(raw_action) is str else None
        if not native_id and not (action == 'create' and _eligible_create(payload)) and not (action == 'list' and native_only):
            return _legacy('legacy_record_reminder_or_generic_list_retained')
        try:
            scope = self._scope(event)
            owner = self._owner(scope)
            legacy_create = False
            if owner['mode'] == 'legacy' or owner == {'mode': 'closed', 'generation': 0}:
                if native_id:
                    return _reply('denied', action=action or '', code='native_id_never_uses_legacy')
                if action != 'create':
                    return _legacy('legacy_owner')
                legacy_create = True
            elif owner['mode'] != 'native':
                return _reply('denied', action=action or '', code='native_memo_owner_closed')
            request = self._payload(payload, action)
            if action not in _ACTIONS.values():
                raise ValueError('known native action required')
            request_id, message_ref, instruction_ref = occurrence(event, scope, request)
        except (PermissionError, AttributeError, TypeError):
            return _reply('denied', action=action or '', code='memo_scope_or_owner_unavailable')
        except ValueError:
            return _reply('invalid', action=action or '', code='native_memo_request_rejected')
        except Exception:
            return _reply('unknown', action=action or '', code='memo_owner_unknown')
        lease = _Lease()
        with self._lock:
            if not self.active or len(self._pending) >= 16:
                return _reply('unavailable', action=action, code='memo_operation_capacity')
            self._pending.add(lease)
        def guard(current):
            try:
                return (lease.active and self._resources() and current == scope and self._scope(event) == scope
                    and self._owner(scope) == owner and self.notes.authorize(dict(scope)) is True)
            except Exception:
                return False
        try:
            lease.view = NativeMemoNotes(self.notes.journal, authorize=guard, clock=self.notes.clock)
            value = await asyncio.wait_for(asyncio.to_thread(self._execute, lease.view, scope, request,
                request_id, message_ref, instruction_ref, legacy_create=legacy_create), timeout=self.timeout_seconds)
            if not guard(scope):
                return _reply('unknown', action=action, code='memo_authority_changed_after_operation',
                              request_id=request_id, retry='reconcile_original_request_no_legacy_fallback')
            if value.get('handled') is True:
                value['response']['request_id'] = request_id
            return value
        except asyncio.TimeoutError:
            return _reply('unknown', action=action, code='memo_result_unknown', request_id=request_id,
                          retry='preserve_original_event_and_arguments_no_legacy_fallback')
        except (PermissionError, JournalConflict):
            return _reply('conflict', action=action, code='memo_changed_or_authority_lost', request_id=request_id)
        except (ValueError, KeyError):
            return _reply('invalid', action=action, code='native_memo_operation_rejected')
        except asyncio.CancelledError:
            raise
        except Exception:
            return _reply('unknown', action=action, code='memo_result_unknown', request_id=request_id,
                          retry='reconcile_original_request_no_legacy_fallback')
        finally:
            lease.active = False
            if lease.view is not None:
                lease.view.stop()
            with self._lock:
                self._pending.discard(lease)

    def stop(self):
        with self._lock:
            self.active = False
            for lease in self._pending:
                lease.active = False
                if lease.view is not None:
                    lease.view.stop()

    close = stop

    def diagnostics(self):
        with self._lock:
            return dict(active=self.active, pending_operations=len(self._pending),
                        feature=FEATURE, registers_tool=False, creates_owner=False,
                        opens_database=False, schedules_reminder=False)
