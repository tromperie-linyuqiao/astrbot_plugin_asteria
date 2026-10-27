"""Lifecycle wiring for the existing MC data service and TLS final outlet.

Root hooks: await begin_request(req,event) immediately after the genuine
selected-Persona finish boundary; cleanup_before_final(req,event) immediately
before PresenceIntegration.inject; await response(event) on a real LLM response.
UnifiedSystem calls record_selection/record_emitted, never the preview route.
No identity, permission table, scheduler, model, index or MC CRUD owner is made.
The original MC capture/profile/summary/maintenance remain data adapters.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import replace
import inspect
import logging
from pathlib import Path
import threading
import weakref

from . import native_core_handoff as audit
from .models import private_scope
from .native_memory_adapter import NativeMemoryAdapter
from .native_companion_takeover_materials import (
    CompanionTakeoverError,MCContextBinding,NativeCompanionTakeoverProvider,
    read_mc_private_recall_switch)
from .native_companion_takeover_context import (
    METHODS,NativeCompanionTakeoverFence,discover_mc_service)


FLAG='living_mc_context_native_enabled'
EXPLICIT_FLAG='living_mc_explicit_native_enabled'
RELATIONSHIP_FLAG='living_mc_relationship_native_enabled'
PROFILE_FLAG='living_mc_profile_native_enabled'
SUMMARY_FLAG='living_mc_summary_native_enabled'
_SUMMARY_SLOT='_tls_native_mc_summary_algorithm'
_SUMMARY_RECOVERY_SLOT='_tls_native_mc_summary_recovery'
_SLOT='_tls_mc_context_runtime'


def _same_method(left,right):
    return (inspect.ismethod(left) and inspect.ismethod(right)
        and left.__self__ is right.__self__ and left.__func__ is right.__func__)


def _physical(ctx):
    def field(key):return ctx.get(key) if isinstance(ctx,dict) else getattr(ctx,key,None)
    result={key:field(key) for key in ('scope','platform','bot_id','user_id','session_id','persona_id')}
    if (result['scope']!='private' or any(type(result[k])is not str or not result[k]
            or len(result[k])>4096 for k in ('platform','bot_id','user_id','session_id','persona_id'))):
        return None
    return result


class NativeMCTakeoverRuntime:
    """Separate RAM context owner. Configuration persistence belongs to Root.

    start requires FLAG strictly True. activate installs but never saves it;
    an explicit operator must persist True before reads become usable.
    stop/close retain a closed legacy fence. Only restore_legacy releases it.
    """
    def __init__(self,plugin,host):
        from .host import LivingHost
        if type(host)is not LivingHost or host.plugin is not plugin:
            raise CompanionTakeoverError('exact_existing_host_required')
        self.plugin,self.host,self.context=plugin,host,host.context
        self.runtime=host.runtime
        self.memory=getattr(self.runtime,'memory',None)
        self.unified=getattr(self.runtime,'unified',None)
        self.observer=host.selected_persona
        if (type(self.memory)is not NativeMemoryAdapter or self.unified is None
                or self.observer is None or self.memory.backend!='native'):
            raise CompanionTakeoverError('native_memory_and_selected_observer_required')
        self.provider=self.fence=self.service=self.store=self.snapshot=None
        self.explicit=None
        self._explicit_error=None
        self.summary=None
        self._summary_error=None
        self._summary_recovery_required=False
        self._summary_lock=asyncio.Lock()
        self._summary_closing=False
        self._closed=threading.Event();self._active=False;self._generation=0
        self._current=ContextVar('tls_mc_context_request',default=None)
        self._requests={};self._events={};self._files={};self._codes=()
        self._phase='inactive';self._last_feedback='none'
        self._counts=dict(begun=0,denied=0,emitted=0,feedback=0,feedback_unknown=0)

    def _flag(self):
        return self.plugin._cfg(FLAG,False)is True

    def _objects_current(self):
        try:
            return (not self._closed.is_set() and not self.host._closed
                and not getattr(self.plugin,'_stopping',False)
                and self.plugin.context is self.context and self.host.context is self.context
                and self.host.plugin is self.plugin and self.host.runtime is self.runtime
                and self.runtime.active is True and self.runtime.memory is self.memory
                and self.runtime.unified is self.unified and self.memory.active is True
                and self.host.selected_persona is self.observer and self.observer.active is True
                and getattr(self.plugin._presence,'living_host',None)is self.host)
        except Exception:return False

    def _source_current(self):
        """Cheap same-object/file identity guard; exact hashes checked at install.

        It is not a claim that filesystem metadata constitutes an immutable
        source attestation. All privileged source edits still require a new
        reviewed activation; no changed-file fallback is attempted.
        """
        try:
            s=self.snapshot
            if (s is None or vars(s.owner).get('service')is not self.service
                    or vars(self.service).get('store')is not self.store
                    or vars(self.store).get('_conn')is not s.connection
                    or vars(self.store).get('_closed')is not False
                    or vars(self.store).get('_closing')is not False
                    or vars(self.service).get('config')is not s.config
                    or audit._config_digest(vars(s.config).get('raw'))!=s.config_hash):
                return False
            for filename,identity in self._files.items():
                st=filename.stat()
                if filename.is_symlink() or (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)!=identity:
                    return False
            return True
        except Exception:return False

    def _live(self):
        return (self._active and self._flag() and self._objects_current() and self._source_current()
            and self.fence is not None and self.fence.installed
            and vars(self.fence).get('_tls_mc_runtime_owner')is self
            and self.memory.mc_context_provider is self.provider
            and self.memory.mc_context_runtime is self)

    def _host_allowed(self,scope):
        return (self.host.authorized_scope(dict(scope))is True
            and self.memory.allowed(dict(scope))is True)

    def _state(self,*,req=None,event=None):
        state=self._requests.get(id(req)) if req is not None else self._events.get(id(event)) if event is not None else self._current.get()
        if state is None or not state['active']:
            return None
        if req is not None and state['req']()is not req:return None
        if event is not None and state['event']()is not event:return None
        return state

    def _authorize(self,binding):
        state=self._current.get()
        if (not self._live() or state is None or not state['active'] or state.get('binding')is not binding
                or self._requests.get(state['request_id'])is not state
                or asyncio.current_task()is not state['task']):
            return False
        req,event=state['req'](),state['event']()
        return (req is not None and event is not None and self._host_allowed(binding.tls_scope)
            and self.observer.current(req,event)is state['proof'] and self._live())

    def _authorize_read(self,binding,mc_scope):
        # Worker-safe snapshot only. The owning Task checks the real sealed
        # proof before/after await and again immediately before final emit.
        state=self._requests.get(next((key for key,s in tuple(self._requests.items())
            if s.get('binding')is binding),None))
        return bool(self._live() and state is not None and state['active']
            and state.get('binding')is binding and dict(binding.mc_scope)==mc_scope
            and state['owner_generation']==self._generation and not state['task'].done()
            and not state['task'].cancelling() and self._host_allowed(binding.tls_scope))

    def _binding_for(self,scope):
        state=self._current.get()
        binding=state.get('binding') if state is not None else None
        return binding if binding is not None and dict(binding.tls_scope)==scope and self._authorize(binding) else None

    def _scan(self):
        _,active,unknown=audit._tasks(self._codes)
        threaded,thread_unknown,queued=audit._threads(replace(self.snapshot,codes=self._codes))
        if active or unknown or threaded or thread_unknown or queued:
            raise CompanionTakeoverError('old_mc_context_drain_not_proven')

    def _install_guard(self,service):
        try:
            if service is not self.service or not self._objects_current() or not self._source_current():return False
            self._scan()
            return True
        except Exception:return False

    async def start(self):
        if not self._flag():return self.status()
        await self.activate()
        if (self.explicit_requested() or self.relationship_requested() or self.profile_requested()
                or vars(self.service).get('_tls_native_mc_explicit_fence') is not None):
            try:
                await self.prepare_explicit(relationship=self.relationship_requested(),profile=self.profile_requested())
                if self.explicit_requested() or self.relationship_requested() or self.profile_requested():self.open_claims()
            except Exception as exc:
                self._explicit_error=type(exc).__name__
                if self.explicit is not None:self.explicit.close()
        if self.summary_requested():
            try:await self.activate_summary()
            except Exception as exc:
                self._summary_error=type(exc).__name__
        return self.status()

    def summary_requested(self):
        return self.plugin._cfg(SUMMARY_FLAG,False) is True

    def _summary_physical_current(self,service):
        """Actual MC registration and original data objects, including shutdown.

        Unlike _live this must stay usable after Host admission has closed so
        the exact owned algorithm can be restored before its references go away.
        It grants no data read, capture, model, or sending permission.
        """
        if service is not self.service or not self._source_current():return False
        try:
            rows=[row for row in self.context.get_all_stars()
                if getattr(row,'root_dir_name',None)=='astrbot_plugin_memory_companion']
            return (len(rows)==1 and getattr(rows[0],'activated',False)is True
                and getattr(rows[0],'star_cls',None)is self.snapshot.owner
                and vars(self.snapshot.owner).get('service')is service)
        except Exception:return False

    def _summary_retained(self):
        record=getattr(self.context,_SUMMARY_RECOVERY_SLOT,None)
        return record if type(record)is dict and record.get('context')is self.context else None

    async def inspect_summary(self):
        """Explicit bounded source/instance inspection; never install a gate."""
        from .native_mc_summary_algorithm import NativeMCSummaryAlgorithm,SummaryAlgorithmError
        async with self._summary_lock:
            result=self._summary_projection()
            result.update(source_current=False,legacy_registration_current=False,
                ready_for_activation=False,scope_or_send_granted=False,
                algorithm_only=True,original_pipeline_changed=False,
                entrypoints=['maybe_summarize_session','_summarize_decay_records_with_provider'])
            physical=self._summary_physical_current(self.service)
            result['legacy_registration_current']=physical
            if not physical:
                result['preflight_error']='current_mc_source_required_for_summary'
                return result
            if self.summary is not None:
                controller=self.summary
                if type(controller)is not NativeMCSummaryAlgorithm:
                    result['preflight_error']='summary_recovery_required_no_adoption'
                    return result
            else:
                if vars(self.service).get(_SUMMARY_SLOT)is not None:
                    result['preflight_error']='summary_recovery_required_no_adoption'
                    return result
                controller=NativeMCSummaryAlgorithm(self.service,
                    source_current=self._summary_physical_current)
                try:controller._prepare()
                except (SummaryAlgorithmError,RuntimeError,ValueError,TypeError,OSError) as exc:
                    result['preflight_error']=str(exc)[:160] if isinstance(exc,SummaryAlgorithmError) else type(exc).__name__
                    return result
            try:
                result.update(controller.status())
                result['algorithm_active']=result.get('active')is True
                result['source_current']=controller._current() and controller._loaded_current()
                result['parameters']=dict(controller._parameters or {})
                tasks=asyncio.all_tasks(asyncio.get_running_loop())
                active=unknown=0
                if len(tasks)>audit.MAX_TASKS:
                    result['preflight_error']='task_scan_capacity'
                else:
                    future_iter=type(asyncio.get_running_loop().create_future().__await__())
                    for task in tasks:
                        if task is asyncio.current_task() or task.done():continue
                        found,unresolved=audit._task_chain(task,controller._codes,future_iter)
                        active+=int(found);unknown+=int(unresolved)
                    result['inflight']={'audited_summary_calls':active,'unknown_task_chains':unknown,
                        'quiescent_observed':active==0 and unknown==0}
                    result['ready_for_activation']=bool(result['source_current'] and self._live()
                        and not self._summary_closing and not result.get('recovery_required')
                        and not result.get('algorithm_active') and active==0 and unknown==0)
            except Exception as exc:result['preflight_error']=type(exc).__name__
            return result

    def _summary_projection(self):
        from .native_mc_summary_algorithm import NativeMCSummaryAlgorithm
        anchor=vars(self.service).get(_SUMMARY_SLOT) if self.service is not None else None
        if self.summary is None:
            result=dict(active=False,phase='recovery_required' if anchor is not None else 'disabled')
        elif type(self.summary) is NativeMCSummaryAlgorithm:
            result=dict(self.summary.status())
        else:result=dict(active=False,phase='recovery_required')
        result['algorithm_active']=result.get('active') is True
        result['active']=result['algorithm_active'] and self._live()
        result.update(configured=self.summary_requested(),error_type=self._summary_error,
            controller_retained=self.summary is not None,
            recovery_required=(self._summary_recovery_required or anchor is not None and anchor is not self.summary
                or self.summary is not None and type(self.summary) is not NativeMCSummaryAlgorithm))
        retained=self._summary_retained()
        physical=self._summary_physical_current(self.service)
        try:
            source_proven=(physical and type(self.summary)is NativeMCSummaryAlgorithm
                and self.summary.old is not None and self.summary._current() and self.summary._loaded_current())
        except Exception:source_proven=False
        result.update(source_current=bool(source_proven),legacy_registration_current=physical,
            retained_recovery_available=bool(retained is not None
                and retained.get('service')is self.service and retained.get('controller')is anchor),
            responsibilities={'algorithm':'native' if result['algorithm_active'] else 'legacy',
                'timeline':'legacy','provider_selection':'legacy','store':'legacy','worker':'legacy',
                'audit_static_calls':'legacy'},
            algorithm_only=True,stop_requires_restore=True)
        result['active']=result['algorithm_active'] and self._live() and result['source_current']
        result['configuration_mismatch']=result['algorithm_active'] and not result['configured']
        return result

    async def activate_summary(self):
        async with self._summary_lock:
            return await self._activate_summary_locked()

    async def _activate_summary_locked(self):
        from .native_mc_summary_algorithm import NativeMCSummaryAlgorithm
        if self._summary_closing or not self._objects_current() or not self._source_current() or not self._live():
            raise CompanionTakeoverError('current_mc_source_required_for_summary')
        anchor=vars(self.service).get(_SUMMARY_SLOT)
        if anchor is not None and anchor is not self.summary:
            self._summary_recovery_required=True
            raise CompanionTakeoverError('summary_recovery_required_no_adoption')
        if self.summary is None:
            self.summary=NativeMCSummaryAlgorithm(self.service,
                source_current=self._summary_physical_current)
        elif type(self.summary) is not NativeMCSummaryAlgorithm:
            self._summary_recovery_required=True
            raise CompanionTakeoverError('summary_recovery_required_no_adoption')
        try:
            await self.summary.activate()
            self._summary_error=None;self._summary_recovery_required=False
        except BaseException as exc:
            self._summary_error=type(exc).__name__
            self._summary_recovery_required=True
            raise
        return self.status()

    async def restore_summary(self):
        async with self._summary_lock:
            return await self._restore_summary_locked()

    async def _restore_summary_locked(self):
        from .native_mc_summary_algorithm import NativeMCSummaryAlgorithm
        anchor=vars(self.service).get(_SUMMARY_SLOT) if self.service is not None else None
        if self.summary is None:
            if anchor is not None:
                await self._restore_retained_summary_locked(anchor)
            return self.status()
        if type(self.summary) is not NativeMCSummaryAlgorithm:
            self._summary_recovery_required=True
            raise CompanionTakeoverError('summary_recovery_required_no_adoption')
        try:
            controller=self.summary
            unused=(anchor is None and controller.old is None and controller.native is None
                and vars(controller).get('_active')is False and not vars(controller).get('_wrappers'))
            if unused or self.summary.status().get('owner')=='original_algorithm' and anchor is None:
                pass  # A refused activation never changed the original owner.
            else:await self.summary.restore()
            retained=self._summary_retained()
            if retained is not None and retained.get('controller')is controller:
                if getattr(self.context,_SUMMARY_RECOVERY_SLOT,None)is retained:
                    delattr(self.context,_SUMMARY_RECOVERY_SLOT)
            self.summary=None;self._summary_error=None;self._summary_recovery_required=False
        except BaseException as exc:
            self._summary_error=type(exc).__name__;self._summary_recovery_required=True
            raise
        return self.status()

    async def _restore_retained_summary_locked(self,anchor):
        """Recover only our retained old controller; never adopt an unknown slot.

        The original bound restore method remains the executor. A reload may
        replace class identities, so every class method must still have exactly
        the unchanged controller code before this retained reference is used.
        """
        from .native_mc_summary_algorithm import NativeMCSummaryAlgorithm
        record=self._summary_retained()
        controller=record.get('controller') if record is not None else None
        old_runtime=record.get('runtime') if record is not None else None
        restore=record.get('restore') if record is not None else None
        if (controller is not anchor or controller is None or record.get('service')is not self.service
                or vars(controller).get('service')is not self.service
                or old_runtime is None or vars(old_runtime).get('summary')is not controller
                or vars(old_runtime).get('context')is not self.context
                or not inspect.ismethod(restore) or restore.__self__ is not controller
                or restore.__func__ is not vars(type(controller)).get('restore')
                or type(controller).__module__!=NativeMCSummaryAlgorithm.__module__
                or not self._summary_physical_current(self.service)):
            self._summary_recovery_required=True
            raise CompanionTakeoverError('summary_recovery_required_no_adoption')
        for name,expected in vars(NativeMCSummaryAlgorithm).items():
            current=vars(type(controller)).get(name)
            expected_func=expected.__func__ if isinstance(expected,(staticmethod,classmethod)) else expected
            current_func=current.__func__ if isinstance(current,(staticmethod,classmethod)) else current
            if inspect.isfunction(expected_func) and (name in vars(controller) or not inspect.isfunction(current_func)
                    or expected_func.__code__!=current_func.__code__):
                raise CompanionTakeoverError('retained_summary_controller_code_changed')
        await restore()
        if vars(self.service).get(_SUMMARY_SLOT)is not None:
            raise CompanionTakeoverError('retained_summary_restore_not_complete')
        if getattr(self.context,_SUMMARY_RECOVERY_SLOT,None)is record:
            delattr(self.context,_SUMMARY_RECOVERY_SLOT)
        if vars(old_runtime).get('summary')is controller:
            old_runtime.summary=None
            old_runtime._summary_recovery_required=False
            old_runtime._summary_error=None
        self._summary_recovery_required=False;self._summary_error=None

    def explicit_requested(self):
        return self.plugin._cfg(EXPLICIT_FLAG,False) is True

    def relationship_requested(self):
        return self.plugin._cfg(RELATIONSHIP_FLAG,False) is True

    def profile_requested(self):
        return self.plugin._cfg(PROFILE_FLAG,False) is True

    def _profile_current(self):
        from .native_profile_candidates import NativeProfileCandidates
        service=getattr(self.runtime,'profile_candidates',None)
        return (type(service) is NativeProfileCandidates and service is self.memory.profile_candidates
            and service.active is True and service.store is self.memory.store and not service.store._closed)

    def explicit_installed(self):
        return self.explicit is not None and self.explicit.status().get('installed') is True

    def _explicit_owned(self,ctx,event,req):
        # Selection of a configured capture target is separate from write
        # admission. Missing leases cannot reopen the old selected branch.
        if getattr(ctx,'scope',None)!='private':return False
        user=str(event.get_sender_id() or '')
        if self.plugin._resolve_session(user) is None:return False
        sessions=self.plugin._cfg('living_memory_sessions',[])
        if type(sessions) is not list or any(type(item)is not str for item in sessions):return None
        return not sessions or getattr(event,'unified_msg_origin',None) in sessions

    def _explicit_scope(self,ctx,event,req):
        if not self._objects_current():return None
        scope=self.host.presence.scope_for_event(event)
        if not isinstance(scope,dict) or getattr(ctx,'scope',None)!='private':return None
        # TLS's real profile binding supplies character_id; no SDK Persona-name
        # alias or administrator login is used to invent it.
        if any(getattr(ctx,key,None)!=scope.get(key) for key in ('platform','bot_id','user_id','session_id')):
            return None
        return private_scope(scope) if self.host._native_memory_allowed(scope) else None

    def _explicit_write_allowed(self,ctx,event,req,scope,record):
        kind=getattr(record,'memory_type',None)
        enabled=(self.explicit_requested() if kind=='explicit_memory' else
            self.relationship_requested() if kind=='relationship_claim' else
            self.profile_requested() and self._profile_current() if kind in ('user_profile','user_preference','user_habit')
                and getattr(record,'metadata',{}).get('profile_dimension') else False)
        return (enabled and self._live()
            and self._explicit_scope(ctx,event,req)==scope
            and kind in ('explicit_memory','relationship_claim','user_profile','user_preference','user_habit'))

    async def prepare_explicit(self,*,relationship=False,profile=False):
        if type(relationship) is not bool:raise TypeError('relationship selection must be boolean')
        if type(profile) is not bool:raise TypeError('profile selection must be boolean')
        if not self._live():raise CompanionTakeoverError('current_native_mc_context_required')
        if self.explicit_installed():
            self.explicit.close()
            await self.explicit.wait_drained()
            if relationship:self.explicit.enable_relationship_selection()
            if profile:self.explicit.enable_profile_selection()
            return self.explicit
        from .native_explicit_memory import NativeExplicitMemory
        from .native_mc_explicit_fence import NativeMCExplicitFence
        from .native_profile_candidates import NativeProfileCandidates
        from .native_profile_capture import NativeProfileCapture
        business=NativeExplicitMemory(self.memory)
        candidates=getattr(self.runtime,'profile_candidates',None)
        capture=(NativeProfileCapture(self.memory,candidates) if type(candidates) is NativeProfileCandidates
            and candidates is self.memory.profile_candidates and candidates.store is self.memory.store else None)
        if profile and capture is None:raise CompanionTakeoverError('same_native_profile_authority_required')
        selected=NativeMCExplicitFence(self.service,business,
            source_current=lambda service:service is self.service and self._objects_current() and self._source_current(),
            owned_selector=self._explicit_owned,scope_for=self._explicit_scope,
            native_write_allowed=self._explicit_write_allowed,relationship_selected=self._explicit_owned,
            profile_selected=self._explicit_owned,profile_capture=capture)
        self.explicit=selected
        await selected.install()
        if relationship:selected.enable_relationship_selection()
        if profile:selected.enable_profile_selection()
        self._explicit_error=None
        return selected

    def open_explicit(self):
        if not self.explicit_requested():
            raise CompanionTakeoverError('separate_explicit_write_switch_required')
        return self.open_claims()

    def open_relationship(self):
        if not self.relationship_requested():
            raise CompanionTakeoverError('separate_relationship_write_switch_required')
        return self.open_claims()

    def open_profile(self):
        if not self.profile_requested():raise CompanionTakeoverError('separate_profile_write_switch_required')
        return self.open_claims()

    def open_claims(self):
        if (not (self.explicit_requested() or self.relationship_requested() or self.profile_requested())
                or not self._live() or self.explicit is None):
            raise CompanionTakeoverError('current_independent_claim_write_switch_required')
        return self.explicit.open()

    def stop_explicit(self):
        if not self.relationship_requested() and not self.profile_requested():self.close_claims()

    def stop_relationship(self):
        if not self.explicit_requested() and not self.profile_requested():self.close_claims()

    def stop_profile(self):
        if not self.explicit_requested() and not self.relationship_requested():self.close_claims()

    def close_claims(self):
        if self.explicit is not None:self.explicit.close()

    async def restore_explicit(self):
        if self.explicit_requested() or self.relationship_requested() or self.profile_requested():
            raise CompanionTakeoverError('stop_both_claim_branches_before_shared_restore')
        if self.explicit is None:return self.status()
        await self.explicit.restore(legacy_restored=True)
        self.explicit=None;self._explicit_error=None
        return self.status()

    async def activate(self):
        if self._closed.is_set():raise CompanionTakeoverError('mc_runtime_closed')
        if self._active:return self.status()
        if not self._objects_current():raise CompanionTakeoverError('host_not_current')
        s=audit._snapshot(self.context)
        if (s.tool_enabled or not s.explicit_disabled or not s.context_enabled
                or s.config_hash!=s.persisted_config_hash):
            raise CompanionTakeoverError('original_mc_data_adapter_not_reviewed')
        bridge=vars(s.owner).get('memory_companion')
        service,store,path=discover_mc_service(bridge)
        if service is not s.service or store is not s.store:
            raise CompanionTakeoverError('actual_mc_bridge_mismatch')
        self.snapshot,self.service,self.store=s,service,store
        self._files={}
        for module in (s.module,s.service_module,s.config_module,s.store_module):
            filename=Path(vars(module)['__file__']);st=filename.stat()
            self._files[filename]=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        filename=Path(vars(s.service_module)['__file__'])
        cls=audit._child(audit._compiled(audit._regular_file(filename),str(filename)),'MemoryCompanionService')
        codes=[]
        for name in METHODS:
            method=vars(type(service)).get(name)
            if (not inspect.iscoroutinefunction(method)
                    or method.__globals__ is not vars(s.service_module)
                    or method.__code__!=audit._child(cls,name)):
                raise CompanionTakeoverError('exact_mc_context_code_required')
            codes.append(method.__code__)
        self._codes=tuple(codes)
        # The original P5 and bookkeeping methods are data/auth adapters only;
        # pin their actual loaded code as part of this same source contract.
        for name in ('_p5_gate','_mark_injected_memories','_p5_record_observed'):
            audit._method(service,name,audit._child(cls,name),filename)
        self._scan()
        previous=getattr(self.context,_SLOT,None)
        existing=vars(service).get('_tls_native_companion_context_fence')
        old_provider=getattr(existing,'provider',None) if existing is not None else None
        self.provider=NativeCompanionTakeoverProvider(path,binding_for=self._binding_for,
            authorize=self._authorize,authorize_read=self._authorize_read,clock=self.memory.clock)
        try:
            if existing is not None:
                # Reload continuity: adopt only the known closed predecessor's
                # exact wrapper slots/code. Never transiently reopen legacy.
                if (previous is None or vars(previous).get('fence')is not existing
                        or vars(previous).get('service')is not service
                        or vars(previous).get('_active')is not False
                        or vars(existing).get('_active')is not False
                        or old_provider is None or not old_provider._closed.is_set()
                        or not getattr(existing,'installed',False)
                        or type(existing).__module__!=NativeCompanionTakeoverFence.__module__
                        or type(existing).install.__code__!=NativeCompanionTakeoverFence.install.__code__
                        or any(vars(service).get(name)is not wrapper
                            for name,wrapper in vars(existing).get('_wrappers',{}).items())
                        or set(vars(existing).get('_wrappers',{}))!=set(METHODS)):
                    raise CompanionTakeoverError('closed_mc_predecessor_not_proven')
                self.fence=existing
                existing.provider=self.provider;existing.assembler=self.unified.assembler
                existing.binding_for_legacy=self._legacy_binding;existing.legacy_allowed=self._legacy_allowed
                existing.install_guard=self._install_guard
                existing._active=True
            else:
                self.fence=NativeCompanionTakeoverFence(service,self.provider,assembler=self.unified.assembler,
                    binding_for_legacy=self._legacy_binding,legacy_allowed=self._legacy_allowed,
                    install_guard=self._install_guard).install()
            self.fence._tls_mc_runtime_owner=self
            self.memory.mc_context_provider=self.provider
            self.memory.mc_context_runtime=self
            setattr(self.context,_SLOT,self)
            self._generation+=1;self._active=True;self._phase='native_context'
            return self.status()
        except BaseException:
            self.provider.close()
            if self.fence is not None:self.fence.close()
            self._phase='closed_error'
            raise

    def sync_proof(self,req,event):
        state=self._state(req=req,event=event)
        if state is None:return False
        token=self._current.set(state)
        if (state['task']is not asyncio.current_task() or state['owner_generation']!=self._generation
                or state.get('binding')is None or not self._authorize(state['binding'])):
            self._current.reset(token)
            self._drop(state)
            return False
        return True

    def _persona_exists(self,identity):
        from astrbot.core.persona_mgr import PersonaManager
        manager=self.context.persona_manager
        getter=getattr(manager,'get_persona_v3_by_id',None)
        if (type(identity)is not str or not identity or len(identity)>256
                or type(manager)is not PersonaManager
                or not _same_method(getter,PersonaManager.get_persona_v3_by_id.__get__(manager,type(manager)))):
            return False
        return getter(identity)is not None

    async def begin_request(self,req,event):
        previous=self._state(event=event)
        if previous is not None:self._drop(previous)
        if not self._live():return False
        state=None
        try:
            scope=private_scope(self.host.presence.scope_for_event(event))
            proof=self.observer.current(req,event)
            if (proof is None or not self._host_allowed(scope)
                    or not self._persona_exists(proof.persona_id)
                    or getattr(event,'private_companion_proactive_framework',False)
                    or self.service.config.bool('memory_injection.enabled',True)is not True):
                return False
            mc=dict(scope='private',platform=scope['platform'],bot_id=scope['bot_id'],user_id=scope['user_id'],
                session_id=scope['session_id'],persona_id=proof.persona_id)
            gate=await self.service._p5_gate(event=event,sink='memory_recall')
            if not isinstance(gate,dict) or gate.get('ok')is not True:return False
            configured=self.service.config.bool('scope_control.private_recall_enabled',True)
            acl=await asyncio.to_thread(read_mc_private_recall_switch,self.store.db_path,mc,
                configured_recall_enabled=configured)
            if (not self._live() or self.observer.current(req,event)is not proof
                    or not self._host_allowed(scope) or acl.get('known')is not True
                    or acl.get('recall_enabled')is not True):
                return False
            task=asyncio.current_task()
            if task is None or task.cancelling():return False
            if len(self._requests)>=64:self._drop(next(iter(self._requests.values())))
            state=dict(active=True,req=weakref.ref(req),event=weakref.ref(event),request_id=id(req),
                event_id=id(event),task=task,proof=proof,scope=scope,owner_generation=self._generation,
                binding=MCContextBinding(scope,mc,proof,(self,self._generation),read_revision=acl['revision']),
                p5_snapshot=gate.get('snapshot'),pairs=[],ticket=None,emitted=())
            self._requests[id(req)]=state;self._events[id(event)]=state;self._current.set(state)
            if not self._authorize(state['binding']):self._drop(state);return False
            self._counts['begun']+=1
            return True
        except asyncio.CancelledError:
            if state is not None:self._drop(state)
            raise
        except Exception:
            if state is not None:self._drop(state)
            self._counts['denied']+=1
            return False

    def _legacy_allowed(self,ctx,event,method):
        # Missing/unknown scope is never a way around the native owner. A
        # complete other scope keeps its original independently gated adapter.
        physical=_physical(ctx)
        if physical is None:return False
        try:
            # A configured TLS user's missing lease/proof is a closed native
            # owner, not permission to resurrect the old private selector.
            if self.plugin._resolve_session(physical['user_id'])is not None:return False
        except Exception:return False
        scope=self.host.presence.peek_scope_for_session(physical['session_id'])
        if not isinstance(scope,dict):return True
        if any(scope[key]!=physical[key] for key in ('platform','bot_id','user_id','session_id')):return False
        return not self._host_allowed(scope)

    async def _legacy_binding(self,ctx,event,method,arguments):
        state=self._current.get()
        if state is None or state.get('binding')is None or not self._authorize(state['binding']):return None
        if method in ('bridge_compose_injection','bridge_compose_context','_bridge_compose_schedule_fast_context'):
            gate=await self.service._p5_gate(sink='bridge_serialization',
                attestation=arguments.get('p5_attestation'),consumer=arguments.get('p5_attestation_consumer'))
            if not isinstance(gate,dict) or gate.get('ok')is not True or not self._authorize(state['binding']):return None
        return state['binding']

    def cleanup_before_final(self,req,event):
        if self.fence is None:return True
        try:
            self.fence.cleanup_request(req)
            state=self._state(req=req,event=event)
            if state is not None and not self.sync_proof(req,event):return False
            if getattr(req,'_tls_mc_takeover_blocked',False):raise CompanionTakeoverError('mc_cleanup_blocked')
            return True
        except Exception:
            setattr(req,'_tls_mc_takeover_blocked',True)
            stop=getattr(event,'stop_event',None)
            if callable(stop):stop()
            return False

    def record_selection(self,scope,material):
        state=self._current.get()
        binding=self._binding_for(private_scope(scope))
        if state is None or binding is None:return
        ids,sections=material.get('selected_ids'),material.get('sections')
        if not isinstance(ids,list) or not isinstance(sections,list) or len(ids)!=len(sections):return
        for identity,section in zip(ids,sections):
            if isinstance(section,dict) and type(section.get('id'))is str:
                pair=(identity,section['id'])
                if pair not in state['pairs'] and len(state['pairs'])<64:state['pairs'].append(pair)

    def record_emitted(self,req,scope,material):
        state=self._state(req=req)
        if (state is None or state['scope']!=private_scope(scope)
                or not self._authorize(state['binding'])):return
        ids=material.get('selected',[])
        if not isinstance(ids,list):return
        state['emitted']=tuple(ids)
        state['ticket']=self.provider.feedback_candidates(scope,
            [pair for pair in state['pairs'] if pair[1] in ids],binding=state['binding'])
        if state['ticket'] is not None:self._counts['emitted']+=1

    async def response(self,event,req=None):
        state=self._state(req=req,event=event)
        if state is None:return dict(ok=False,state='no_native_mc_request')
        request=state['req']()
        try:
            if request is None or not self.sync_proof(request,event) or state['ticket'] is None:
                return dict(ok=False,state='no_confirmable_native_mc_emission')
            result=await self.provider.confirm_feedback(state['ticket'],emitted_ids=list(state['emitted']),
                service=self.service,configured_recall_enabled=self.service.config.bool(
                    'scope_control.private_recall_enabled',True),p5_snapshot=state['p5_snapshot'])
            self._last_feedback=result['state']
            self._counts['feedback' if result.get('ok')is True else 'feedback_unknown']+=1
            return result
        finally:self._drop(state)

    def _drop(self,state):
        state['active']=False
        if self._requests.get(state['request_id'])is state:self._requests.pop(state['request_id'],None)
        if self._events.get(state['event_id'])is state:self._events.pop(state['event_id'],None)
        if self._current.get()is state:self._current.set(None)

    def stop(self):
        self.close_claims()
        self._active=False;self._generation+=1;self._phase='native_closed'
        for state in tuple(self._requests.values()):self._drop(state)
        if self.provider is not None:self.provider.close()
        if self.fence is not None and vars(self.fence).get('_tls_mc_runtime_owner')is self:self.fence.close()
        if self.memory.mc_context_provider is self.provider:self.memory.mc_context_provider=None
        if self.memory.mc_context_runtime is self:self.memory.mc_context_runtime=None

    async def close(self):
        from .native_mc_summary_algorithm import NativeMCSummaryAlgorithm
        summary_error=close_cancel=None
        self._summary_closing=True
        # A pending activation must finish before recovery inspects its owner.
        # Cancellation cannot abandon that operation and permit a late CAS
        # after close returns. Preserve it until local recovery/cleanup ends.
        while True:
            try:
                await self._summary_lock.acquire()
                break
            except asyncio.CancelledError as exc:
                if close_cancel is None:close_cancel=exc
        try:
            try:await self._restore_summary_locked()
            except BaseException as exc:
                summary_error=exc
                self._summary_error=type(exc).__name__;self._summary_recovery_required=True
                if type(self.summary)is NativeMCSummaryAlgorithm and vars(self.service).get(_SUMMARY_SLOT)is self.summary:
                    setattr(self.context,_SUMMARY_RECOVERY_SLOT,dict(context=self.context,
                        service=self.service,controller=self.summary,runtime=self,
                        restore=self.summary.restore))
                logging.getLogger(__name__).warning('MC summary recovery retained: %s',type(exc).__name__)
        finally:self._summary_lock.release()
        try:
            self.stop()
            if self.explicit_installed():await self.explicit.wait_drained()
        finally:self._closed.set()
        if close_cancel is not None:raise close_cancel
        if summary_error is not None and not isinstance(summary_error,Exception):raise summary_error
        return self.status()

    async def restore_legacy(self):
        if self.summary is not None or self.service is not None and vars(self.service).get(_SUMMARY_SLOT) is not None:
            raise CompanionTakeoverError('restore_summary_algorithm_first')
        if self.explicit_installed():raise CompanionTakeoverError('restore_explicit_branch_first')
        self.stop()
        if self.fence is None:return self.status()
        # stop deliberately retains exact legacy wrapper slots. This explicit
        # call alone reopens them after the reviewed objects/drain check.
        if not self._install_guard(self.service):raise CompanionTakeoverError('legacy_restore_not_proven')
        self.fence.uninstall(legacy_restored=True)
        if getattr(self.context,_SLOT,None)is self:delattr(self.context,_SLOT)
        self._phase='legacy_restored'
        return self.status()

    def status(self):
        explicit=dict(self.explicit.status()) if self.explicit is not None else dict(
            active=False,installed=False,phase='disabled',pending_captures=0,pending_native_operations=0)
        explicit['fence_open']=explicit.get('active') is True
        relationship=dict(explicit)
        relationship['active']=(relationship['fence_open'] and self.relationship_requested() and self._live()
            and relationship.get('relationship_owned') is True)
        relationship.update(configured=self.relationship_requested(),initialization_error=self._explicit_error)
        profile=dict(explicit)
        profile['active']=(profile['fence_open'] and self.profile_requested() and self._live()
            and profile.get('profile_owned') is True and self._profile_current())
        profile.update(configured=self.profile_requested(),initialization_error=self._explicit_error)
        explicit['active']=(explicit['fence_open'] and self.explicit_requested() and self._live())
        explicit.update(configured=self.explicit_requested(),initialization_error=self._explicit_error)
        return dict(active=self._live(),phase=self._phase,generation=self._generation,
            fence_installed=self.fence is not None and self.fence.installed,
            pending_requests=len(self._requests),counts=dict(self._counts),last_feedback=self._last_feedback,
            config_persistence='operator',crud_owner_changed=False,model_calls=0,sends=0,
            legacy_capture_profile_summary='existing_data_adapters_except_selected_user_claims'
                if explicit.get('active') is True or relationship.get('active') is True or profile.get('active') is True
                else 'existing_data_adapters',explicit=explicit,relationship=relationship,profile=profile,
            summary=self._summary_projection())
