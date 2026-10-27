"""Optional narrow branch before the unchanged R38 memo dispatcher.

Only explicitly bound native timed/repeating completion is selected here.
Original IDs, ambiguous selectors, old due parsing and unbound notes are never
silently converted; they continue through the existing router contract.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
import re
from ..journal import JournalConflict
from ..native_memo_tools import occurrence, _ACTIONS
from ..native_memo_notes import NativeMemoNotes, edit_fields, _time
from .memo_scheduler import NAMESPACE, ACTIONS, digest


async def try_bound_memo_completion(integration, controller, event, payload):
    if type(payload) is not dict: return None
    raw=payload.get('action',''); selector=payload.get('selector','')
    action=_ACTIONS.get(raw.strip().lower()) if type(raw) is str else None
    if action!='complete' or type(selector) is not str or re.fullmatch(r'memo\.[a-f0-9]{64}',selector) is None:
        return None
    if controller is None or controller.ready_for_event(event) is not True: return None
    request_id=None
    try:
        router=controller.router
        scope=router.tools._scope(event)
        integration.memos._scope(scope)
        binding=integration.memos._read(NAMESPACE,selector,scope)
        if binding is None: return None
        normalized=router.tools._payload(payload,'complete')
        request_id,_,_=occurrence(event,scope,normalized)
        note=integration.memos.notes.get(scope,selector)
        if note is None: raise KeyError('bound native note absent')
        with integration.memos.journal._lock:
            owner=router.ownership.owner_for_scope(scope)
            if owner['mode']!='native': raise PermissionError('native memo tool owner required')
            # Existing R38 durable claim and exact real-event checks remain in
            # force; no new tool owner, identity alias or request claim table.
            router.ownership.admit_native(scope,request_id,expected_generation=owner['generation'])
        prior=integration.memos._read(ACTIONS,digest(['complete',scope,request_id]),scope)
        revision=prior['data']['expected_revision'] if prior else note['revision']
        result=await integration.memos.complete_memo(scope,selector,expected_revision=revision,request_id=request_id)
        return json.dumps(dict(status='success',action='complete',saved=True,note=result,
            storage='tls_native_memo_notes',scheduler='tls_native_pc_integration',
            next_due_at=result['fields']['due_at'] if result['fields']['repeat']!='none' else None,
            delivery_confirmed=False,external_record_modified=False,legacy_fallback=False),ensure_ascii=False)
    except asyncio.CancelledError: raise
    except PermissionError:
        return json.dumps(dict(status='forbidden',saved=False,code='current_native_memo_source_owner_required',legacy_fallback=False))
    except (ValueError,TypeError,KeyError):
        return json.dumps(dict(status='invalid',saved=False,code='bound_native_memo_completion_rejected',legacy_fallback=False))
    except JournalConflict:
        return json.dumps(dict(status='conflict',saved=False,code='memo_revision_or_delivery_requires_reconciliation',
            request_id=request_id,legacy_fallback=False))
    except Exception:
        return json.dumps(dict(status='unknown',saved=None,result_unknown=True,code='native_memo_completion_not_confirmed',
            request_id=request_id,legacy_fallback=False))



def _absolute_due(value):
    if type(value) is str:
        if not value or len(value)>80 or value!=value.strip():raise ValueError('explicit ISO or epoch seconds required')
        if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',value):value=float(value)
        else:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})',value):
                raise ValueError('ISO due time requires a timezone')
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError('explicit timezone required')
            value=parsed.timestamp()
    return _time(value,zero=False)


def _explicit_current_reminder_request(event):
    text=getattr(event,'message_str',None)
    if type(text) is not str or not 1<=len(text)<=6000:return False
    if re.search(r'(?:不要|不用|别|停止|取消)(?:再|给我|为我|帮我|这个|该|所有)?(?:提醒|通知|叫我|闹钟|定时)',text):return False
    return bool(re.search(r'提醒我|提醒一下|提醒下|叫我|喊我|通知我|(?:帮我|请|麻烦|给我|为我).{0,20}(?:提醒|设|记|定时)|(?:设置|设定|添加|创建|安排).{0,10}(?:提醒|定时|闹钟|备忘)',text))


async def schedule_native_memo(integration,controller,event,*,title,due_at,content='',repeat='none',
                               remind_enabled=True,slot=1,user_requested=False):
    """Separate real-user scheduling tool; the old nonreminder tool is unchanged.

    slot is the user's stable 1..8 ordinal within this actual inbound message,
    never a random retry token. Changing a same-slot definition conflicts in
    NativeMemoNotes' existing immutable creation signature.
    """
    request_id=None;scope=None
    def reply(status,**values):
        return json.dumps(dict(status=status,scheduler='tls_native_pc_integration',request_id=request_id,
            legacy_fallback=False,external_record_modified=False,human_visible_confirmed=False,**values),ensure_ascii=False)
    try:
        if (user_requested is not True or remind_enabled is not True or type(slot) is not int or not 1<=slot<=8
                or not _explicit_current_reminder_request(event)):
            return reply('invalid',saved=False,code='current_user_explicit_reminder_request_required')
        if controller is None or controller.ready_for_event(event) is not True:
            return reply('forbidden',saved=False,code='genuine_current_native_memo_owner_required')
        router=controller.router;scope=router.tools._scope(event);integration.memos._scope(scope)
        _,message_ref,instruction_ref=occurrence(event,scope,dict(tool='tls_schedule_memo',slot=slot))
        request_id='memo_'+digest(['tls.schedule.memo.v1',scope,message_ref,slot])
        fields=edit_fields(dict(title=title,content=content,due_at=_absolute_due(due_at),repeat=repeat,
            color='yellow',pinned=False,remind_enabled=True))
        with integration.memos.journal._lock:
            owner=router.ownership.owner_for_scope(scope)
            if owner['mode']!='native':raise PermissionError('current native memo tool owner required')
            router.ownership.admit_native(scope,request_id,expected_generation=owner['generation'])
        def guard():
            try:
                return (controller.ready_for_event(event) is True and router.tools._scope(event)==scope
                    and router.ownership.owner_for_scope(scope)==owner and integration.memos._scope(scope)==scope)
            except Exception:return False
        def create_and_bind():
            if not guard():raise PermissionError('memo tool operation revoked')
            old=integration.memos.notes.get_request(scope,request_id)
            if old is None and not integration.memos.clock()<=fields['due_at']<=integration.memos.clock()+366*86400:
                raise ValueError('new reminder needs an explicit future time within one year')
            consent=integration.memos.prepare_explicit_new_consent(scope,source='memo_note',consent=True,operation_guard=guard)
            view=NativeMemoNotes(integration.memos.journal,authorize=lambda candidate:candidate==scope and guard(),clock=integration.memos.clock)
            try:
                # AI organization is labelled as such. This shares create()'s
                # stable native ID and signature/replay machinery, not a new DB.
                note=view.create_from_tool(scope,request_id,message_ref=message_ref,instruction_ref=instruction_ref,**fields)
                binding=integration.memos.bind_memo(scope,note['id'],expected_revision=note['revision'],
                    consent_id=consent['consent_id'],legacy_disposition='not_pending',operation_guard=guard)
            finally:view.stop()
            stored=integration.memos._read(NAMESPACE,note['id'],scope)
            if not guard() or stored is None or stored['data']!=binding:raise RuntimeError('memo binding readback not confirmed')
            current=next((row for row in integration.memos.status(scope)['records'] if row['memo_id']==note['id']),None)
            if current is None:raise RuntimeError('memo status readback absent')
            return dict(note=note,binding=binding,binding_revision=stored['revision'],binding_verified=True,
                current=current,replayed=old is not None,consent_recorded=consent['consent_recorded'])
        # Existing owned thread/cancellation lifecycle: no detached worker and
        # no retry of a write when its caller is cancelled or loses the result.
        result=await integration.memos.reminders._run(create_and_bind)
        if not guard():return reply('unknown',saved=None,result_unknown=True,code='memo_authority_changed_after_operation')
        return reply('success',saved=True,delivery_confirmed=result['current']['delivery_confirmed'],
            readback=dict(path='/astrbot_plugin_virtual_body/page/memo-notes/request',request_id=request_id),**result)
    except asyncio.CancelledError:raise
    except PermissionError:return reply('forbidden',saved=False,code='current_native_source_owner_required')
    except JournalConflict:return reply('conflict',saved=False,code='same_message_slot_definition_or_queue_state_conflict')
    except (ValueError,TypeError,KeyError,OverflowError):return reply('invalid',saved=False,code='explicit_reminder_fields_rejected')
    except Exception:return reply('unknown',saved=None,result_unknown=True,code='native_memo_schedule_not_confirmed')
