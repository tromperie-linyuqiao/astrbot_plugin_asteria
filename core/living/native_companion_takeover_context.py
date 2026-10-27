"""RAM-only MC final-context replacement; no plugin file or Store mutation.

The installer is not an owner transition. The Host first proves the exact live
service/source/config, drains old context calls and supplies its current owner
callbacks. MC capture/profile/summary and storage continue unchanged adapters.
Ordinary injection is suppressed here; the existing TLS UnifiedSystem consumes
the provider's raw materials and owns the single final ContextAssembler emit.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import re
from types import MethodType

from .native_companion_takeover_materials import CompanionTakeoverError, MCContextBinding


HEADER, FOOTER = '<MemoryCompanion-Context>', '</MemoryCompanion-Context>'
METHODS = ('inject_memories','_compose_memory_injection','bridge_compose_injection',
           'bridge_compose_context','_bridge_compose_schedule_fast_context')
_REMOVED = object()


def discover_mc_service(bridge):
    """Resolve only the audited existing object slots, not plugin discovery.

    Root must separately pin source hashes and the core-tool owner before use.
    No Store constructor, service initialization, property or legacy getter is
    called to create an apparently compatible instance.
    """
    values=vars(bridge)
    service=values.get('_plugin')
    if (service is None or type(service).__name__!='MemoryCompanionService'
            or not type(service).__module__.endswith('.core.service')):
        raise CompanionTakeoverError('actual_mc_service_required')
    store=vars(service).get('store')
    if (store is None or type(store).__name__!='MemoryStore'
            or not type(store).__module__.endswith('.core.store') or 'db_path' not in vars(store)):
        raise CompanionTakeoverError('actual_mc_store_required')
    return service,store,vars(store)['db_path']


def _strip(text,known):
    if type(text) is not str:
        return text,0
    count=0
    for owned in known:
        found=text.count(owned)
        if found:
            text=text.replace(owned,'');count+=found
    if HEADER not in text and FOOTER not in text:
        return text,count
    if len(text)>131072:
        raise CompanionTakeoverError('legacy_context_surface_capacity')
    start,ranges=None,[]
    for match in re.finditer(re.escape(HEADER)+'|'+re.escape(FOOTER),text):
        if match.group()==HEADER:
            if start is not None:
                raise CompanionTakeoverError('legacy_context_range_unknown')
            start=match.start()
        elif start is None:
            raise CompanionTakeoverError('legacy_context_range_unknown')
        else:
            ranges.append((start,match.end()));start=None
    if start is not None:
        raise CompanionTakeoverError('legacy_context_range_unknown')
    chunks=[];cursor=0
    for a,b in ranges:
        chunks.append(text[cursor:a]);cursor=b
    chunks.append(text[cursor:])
    return ''.join(chunks),count+len(ranges)


def clear_legacy_mc_context(req,*,known_native_bridge_text=()):
    """Clone known text surfaces and apply only after complete validation.

    The system/persona prompt, metadata, URLs and non-text media payloads are
    never traversed. This is compatibility cleanup, not proof of the author of
    historic marker text. Ambiguous marker/object shapes block the protected
    request rather than silently retaining a second legacy context packet.
    """
    known=tuple(known_native_bridge_text)
    if len(known)>64 or any(type(x)is not str or not x or len(x)>6000 for x in known):
        raise CompanionTakeoverError('invalid_bridge_projection_cleanup')
    report={'removed_blocks':0};visiting=set();visited=0
    def clean(value,depth=0):
        nonlocal visited
        visited+=1
        if visited>4096 or depth>24:
            raise CompanionTakeoverError('legacy_context_surface_capacity')
        if isinstance(value,str):
            result,n=_strip(value,known);report['removed_blocks']+=n
            return (_REMOVED if not result.strip() else result) if n else value
        if isinstance(value,(list,dict)):
            if id(value) in visiting:
                raise CompanionTakeoverError('legacy_context_cycle')
            visiting.add(id(value))
            try:
                if isinstance(value,list):
                    items=[clean(item,depth+1) for item in value]
                    if all(a is b for a,b in zip(items,value)):
                        return value
                    return [item for item in items if item is not _REMOVED]
                if value.get('role')=='system':
                    return value
                result=None
                for key in ('text','content'):
                    if key not in value or not isinstance(value[key],(str,list)):
                        continue
                    item=clean(value[key],depth+1)
                    if item is value[key]:continue
                    if result is None:result=dict(value)
                    result[key]=('' if isinstance(value[key],str) else []) if item is _REMOVED else item
                if result is None:return value
                if set(value)<={'role','type','text','content'} and not any(result.get(k) for k in ('text','content')):
                    return _REMOVED
                return result
            finally:
                visiting.remove(id(value))
        text=getattr(value,'text',None)
        if isinstance(text,str) and getattr(value,'type','text') in ('text','plain'):
            result,n=_strip(text,known)
            if not n:return value
            try:
                clone=deepcopy(value);setattr(clone,'text',result)
            except Exception as exc:
                raise CompanionTakeoverError('legacy_context_object_unknown') from exc
            report['removed_blocks']+=n
            return _REMOVED if not result.strip() else clone
        return value
    replacements={}
    prompt=getattr(req,'prompt',None)
    if isinstance(prompt,str):
        text,n=_strip(prompt,known)
        if n:replacements['prompt']=text;report['removed_blocks']+=n
    for name in ('extra_user_content_parts','contexts'):
        value=getattr(req,name,None)
        if isinstance(value,list):
            result=clean(value)
            if result is not value:replacements[name]=result
    for name,value in replacements.items():setattr(req,name,value)
    return report


class NativeCompanionTakeoverFence:
    """Five scoped instance methods, with exact-CAS restoration only.

    ``binding_for_legacy(ctx,event,method,arguments)`` may be async to consume
    the original P5/read attestation; it returns a live MCContextBinding or None.
    ``legacy_allowed`` must consult Root's owner, including incomplete owned
    sessions. It must not default to True because selected proof is unavailable.
    ``install_guard`` proves exact source/objects and drained old coroutines.
    """
    def __init__(self,service,provider,*,assembler,binding_for_legacy,legacy_allowed,install_guard):
        if not all(callable(x) for x in (binding_for_legacy,legacy_allowed,install_guard)):
            raise CompanionTakeoverError('explicit_context_owner_required')
        self.service,self.provider,self.assembler=service,provider,assembler
        self.binding_for_legacy,self.legacy_allowed,self.install_guard=binding_for_legacy,legacy_allowed,install_guard
        self._original={};self._wrappers={};self._own={};self._installed=False;self._active=True
        self._bridge_text=[]

    @property
    def installed(self):return self._installed

    def install(self):
        if not self._active or self._installed or vars(self.service).get('_tls_native_companion_context_fence') is not None:
            raise CompanionTakeoverError('context_fence_already_attached')
        if self.install_guard(self.service) is not True:
            raise CompanionTakeoverError('actual_sources_and_drain_required')
        for name in METHODS:
            original=getattr(self.service,name,None)
            if not inspect.ismethod(original) or original.__self__ is not self.service or not inspect.iscoroutinefunction(original):
                raise CompanionTakeoverError('actual_mc_context_method_required')
            self._original[name]=original;self._own[name]=name in vars(self.service)
        try:
            for name in METHODS:
                wrapper=MethodType(self._make_wrapper(name),self.service)
                self._wrappers[name]=wrapper;setattr(self.service,name,wrapper)
            self.service._tls_native_companion_context_fence=self
            if self.install_guard(self.service) is not True:
                raise CompanionTakeoverError('context_owner_changed_during_install')
            self._installed=True
        except BaseException:
            self._restore_slots();raise
        return self

    def close(self):
        # Keep the legacy fence attached. Closing native is not permission to
        # resurrect old compose while Root reconciles ownership/reload.
        self._active=False

    def _restore_slots(self):
        for name,wrapper in self._wrappers.items():
            if vars(self.service).get(name) is wrapper:
                if self._own[name]:setattr(self.service,name,self._original[name])
                else:delattr(self.service,name)
        if vars(self.service).get('_tls_native_companion_context_fence') is self:
            delattr(self.service,'_tls_native_companion_context_fence')

    def uninstall(self,*,legacy_restored=False):
        if (legacy_restored is not True or not self._installed
                or self.install_guard(self.service) is not True
                or vars(self.service).get('_tls_native_companion_context_fence') is not self
                or any(vars(self.service).get(name) is not wrapper for name,wrapper in self._wrappers.items())):
            raise CompanionTakeoverError('verified_legacy_owner_and_exact_slots_required')
        self._restore_slots();self._installed=False;self._active=False;self._bridge_text.clear()

    def cleanup_request(self,req):
        return clear_legacy_mc_context(req,known_native_bridge_text=tuple(self._bridge_text))

    def _mark(self,event,req):
        marker=getattr(self.service,'_mark_memory_companion_injection_state',None)
        if callable(marker):
            marker(event,req,injected=False,conversation_memory=False,slot_map={})
        if req is not None:
            setattr(req,'_tls_mc_takeover_context_state',{'legacy_suppressed':True,'outlet':'tls.unified.context'})

    @staticmethod
    def _matches(ctx,binding):
        if type(binding)is not MCContextBinding:return False
        def field(name):return ctx.get(name) if isinstance(ctx,dict) else getattr(ctx,name,None)
        return all(field(key)==value for key,value in binding.mc_scope.items())

    def _make_wrapper(self,name):
        async def wrapper(_service,*args,**kwargs):
            ctx=(args[0] if args else kwargs.get('ctx')) if name in ('inject_memories','_compose_memory_injection') else kwargs.get('session_context')
            event=kwargs.get('event');req=(args[1] if len(args)>1 else kwargs.get('req')) if name=='inject_memories' else kwargs.get('req')
            binding=self.binding_for_legacy(ctx,event,name,dict(kwargs))
            if inspect.isawaitable(binding):binding=await binding
            if binding is None:
                if self._active and self.legacy_allowed(ctx,event,name) is True:
                    return await self._original[name](*args,**kwargs)
            elif not self._matches(ctx,binding):
                raise CompanionTakeoverError('legacy_mc_context_binding_mismatch')
            if name=='inject_memories':
                try:self.cleanup_request(req)
                except CompanionTakeoverError:
                    if req is not None:setattr(req,'_tls_mc_takeover_blocked',True)
                    stop=getattr(event,'stop_event',None)
                    if callable(stop):stop()
                    raise
                self._mark(event,req)
                return None
            if not self._active or not self._installed or binding is None or not self.provider.current(binding):
                return ''
            query=kwargs.get('explicit_query','') or kwargs.get('query','')
            if name=='bridge_compose_injection' and args:query=args[0]
            if not query:query=ctx.get('message_text','') if isinstance(ctx,dict) else getattr(ctx,'message_text','')
            budget=kwargs.get('max_chars')
            budget=900 if budget is None else budget
            if type(budget)is not int or not 120<=budget<=2400:
                raise CompanionTakeoverError('invalid_bridge_context_budget')
            profile=kwargs.get('retrieval_profile','')
            kind='outfit' if profile=='outfit_fast' or kwargs.get('context_kind')=='outfit' else 'schedule' if profile=='schedule_fast' or name=='_bridge_compose_schedule_fast_context' else 'continuity'
            text=await self.provider.compose(dict(binding.tls_scope),assembler=self.assembler,
                query=query,kind=kind,max_chars=budget,binding=binding)
            if not self._active or not self._installed:return ''
            if text and text not in self._bridge_text:
                self._bridge_text.append(text)
                if len(self._bridge_text)>64:self._bridge_text.pop(0)
            return text
        return wrapper
