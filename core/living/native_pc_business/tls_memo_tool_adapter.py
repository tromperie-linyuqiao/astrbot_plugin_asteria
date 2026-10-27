"""Thin PC memo routing. No registry mutation, owner creation or storage.

The original registered pc_manage_memo remains the only SDK tool. The TLS host
dispatcher must persist request claims and cover actual old coroutine lifetime.
Never remove this compatibility shim after native claims merely to roll back.
"""
from __future__ import annotations

import asyncio
import json
import math

PROTOCOL = 'tls.native.memo_tool.pc_router.v1'
TLS_ROOT = 'astrbot_plugin_virtual_body'
MAX_STARS = 128
MAX_REPLY = 262144
_CREATE = frozenset(('', 'create', 'add', '新增', '添加', '创建', '记录')) - {''}
_LIST = frozenset(('', 'list', '查看', '列表', '查询'))


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _unknown(code, *, action=''):
    return _json(dict(status='unavailable', saved=False, action=action, code=code,
        legacy_fallback_permitted=False, native_result_unknown=True,
        schedules_reminder=False, external_completion_confirmed=False))


def _kind(payload):
    selector=payload.get('selector','')
    if type(selector) is str and selector.startswith('memo.'):
        return 'native_id'
    action=payload.get('action','list')
    if type(action) is not str:
        return 'legacy'
    action=action.strip().lower()
    if action in _LIST:
        return 'list'
    if action not in _CREATE:
        return 'legacy'
    due, repeat, remind=payload.get('due_at',''),payload.get('repeat',''),payload.get('remind_enabled')
    # Explicit time/reminder/recurrence belongs to the unchanged old slice.
    # Ambiguous or malformed flags cannot turn an untracked create into old.
    if remind is True:
        return 'legacy'
    if type(repeat) is str and repeat.strip().lower() not in ('','none'):
        return 'legacy'
    if type(due) is str and due.strip():
        return 'legacy'
    if type(due) in (int,float) and math.isfinite(due) and due != 0:
        return 'legacy'
    return 'create'


def _resolve(pc):
    context=getattr(pc,'context',None)
    getter=getattr(context,'get_all_stars',None)
    if not callable(getter):
        return None
    rows=getter()
    if type(rows) not in (list,tuple) or len(rows)>MAX_STARS:
        return None
    matches=[row for row in rows if getattr(row,'root_dir_name',None)==TLS_ROOT]
    if len(matches)!=1:
        return None
    metadata=matches[0]
    host=getattr(metadata,'star_cls',None)
    if (getattr(metadata,'activated',None) is not True or host is None
            or getattr(host,'context',None) is not context):
        return None
    router=getattr(host,'_native_memo_tool_router',None)
    if (getattr(router,'protocol',None)!=PROTOCOL or getattr(router,'active',None) is not True
            or not callable(getattr(router,'dispatch',None))):
        return None
    return metadata,host,router


def _same(pc, resolution):
    try:
        current=_resolve(pc)
        return current is not None and all(a is b for a,b in zip(current,resolution))
    except Exception:
        return False


async def _old(pc,event,payload,legacy):
    # The callback is the exact renamed old body and performs its own existing
    # primary-user private-chat check. No old data/logic is copied here.
    return await legacy(event,**payload)


async def _partial_legacy_list(pc,event,payload,legacy):
    raw=await _old(pc,event,payload,legacy)
    try:
        if type(raw) is not str or len(raw)>MAX_REPLY:
            raise ValueError('bounded original result required')
        old=json.loads(raw)
        if type(old) is not dict:
            raise ValueError('original result object required')
    except (ValueError,TypeError):
        return _unknown('memo_legacy_list_result_invalid',action='list')
    if old.get('action')!='list' or old.get('status')!='success':
        return raw
    # Preserve all original fields and old section numbering. Its count remains
    # the old-store count; no cross-store total or native absence is asserted.
    result=dict(old)
    result.update(partial=True,list_scope='legacy_only_native_unknown',
        combined_count=None,legacy_count=old.get('count'),
        numbering_scope='legacy_section_only',native_selectors='exact_tls_id_only',
        native_section=dict(status='unavailable',records=None,count=None,
                            code='tls_memo_router_unavailable'))
    return _json(result)


async def dispatch_memo_tool(pc,event,payload,legacy):
    """Preserve unaffected old operations; protected routes fail closed.

    Expected reviewed host object: _native_memo_tool_router with exact protocol,
    active=True, async dispatch(pc,event,payload,legacy_callable)->JSON string.
    The host must merge/partition list results and hold admissions until the
    supplied original coroutine actually completes; it is not a boolean flag.
    """
    if type(payload) is not dict or not callable(legacy):
        return _unknown('memo_router_contract_invalid')
    kind=_kind(payload)
    if kind=='legacy':
        return await _old(pc,event,payload,legacy)
    try:
        resolution=_resolve(pc)
    except Exception:
        resolution=None
    if resolution is None:
        if kind=='list':
            return await _partial_legacy_list(pc,event,payload,legacy)
        return _unknown('tls_memo_router_unavailable',action=payload.get('action',''))
    if not _same(pc,resolution):
        return _unknown('tls_memo_router_changed',action=payload.get('action',''))
    router=resolution[2]
    try:
        result=await router.dispatch(pc,event,dict(payload),legacy)
        if not _same(pc,resolution):
            return _unknown('tls_memo_router_changed_after_dispatch',action=payload.get('action',''))
        if type(result) is not str or len(result)>MAX_REPLY or type(json.loads(result)) is not dict:
            return _unknown('tls_memo_router_result_invalid',action=payload.get('action',''))
        value=json.loads(result)
        if kind=='list' and value.get('status')=='success':
            native=value.get('native_section')
            if (value.get('action')!='list' or value.get('list_scope')!='legacy_and_native_partitioned'
                    or value.get('numbering_scope')!='legacy_section_only'
                    or value.get('native_selectors')!='exact_tls_id_only'
                    or value.get('combined_count','missing') is not None
                    or type(value.get('partial')) is not bool or type(value.get('legacy_section')) is not dict
                    or type(native) is not dict
                    or native.get('status')=='success' and type(native.get('records')) is not list
                    or native.get('status')!='success' and value.get('partial') is not True):
                return _unknown('tls_memo_list_partition_required',action='list')
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        # The call may already have persisted a claim or mutation. Never invoke
        # the old create after an exception, timeout or response uncertainty.
        return _unknown('tls_memo_router_result_unknown',action=payload.get('action',''))
