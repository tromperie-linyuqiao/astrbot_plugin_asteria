"""Use the existing scoped TLS context outlet with the TLS-owned MC service.

This is an owned service, not a fabricated legacy registration or adoption of
an old RAM fence. The original request proof, P5, ACL, revision and final
assembler checks are inherited unchanged from the existing context runtime.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from .native_mc_takeover_runtime import NativeMCTakeoverRuntime
from .native_companion_takeover_context import METHODS, NativeCompanionTakeoverFence
from .native_companion_takeover_materials import CompanionTakeoverError, NativeCompanionTakeoverProvider
from .native_explicit_memory import NativeExplicitMemory
from .native_profile_capture import NativeProfileCapture
from .native_mc.capture_router import NativeMCCaptureRouter


class NativeOwnedMCContextRuntime(NativeMCTakeoverRuntime):
    def __init__(self, plugin, host, companion):
        super().__init__(plugin, host)
        self.companion = companion
        self.service = companion.service
        if self.service is None:
            raise RuntimeError('prepare native memory service first')
        self.store = self.service.store
        self._service_config = self.service.config
        self._native_sources = {}
        package = type(self.service).__module__.rsplit('.', 1)[0]
        for name, module in tuple(sys.modules.items()):
            if name == package or name.startswith(package + '.'):
                filename = getattr(module, '__file__', None)
                if filename and str(filename).endswith('.py'):
                    path = Path(filename)
                    st = path.stat()
                    self._native_sources[path] = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def _source_current(self):
        try:
            owner = getattr(self.plugin, '_native_server_integrations', None)
            if (owner is None or owner._closed or getattr(owner, 'mc_full', None) is not self.companion
                    or self.companion.closed or self.companion.service is not self.service
                    or self.service.store is not self.store or self.service.config is not self._service_config
                    or self.service._closed or self.service._closing
                    or self.store._closed or self.store._closing
                    or self.companion.legacy_quiesced() is not True):
                return False
            for path, identity in self._native_sources.items():
                st = path.stat()
                if path.is_symlink() or (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != identity:
                    return False
            return True
        except Exception:
            return False

    def _install_guard(self, service):
        return (service is self.service and self._objects_current() and self._source_current())

    def _scan(self):
        # No pre-existing implementation is adopted. prepare exposes no hooks
        # or workers; calls start only after this runtime is installed.
        if not self._source_current():
            raise CompanionTakeoverError('native_memory_source_changed')

    async def activate(self):
        if self._closed.is_set() or not self._objects_current() or not self._source_current():
            raise CompanionTakeoverError('current_native_memory_service_required')
        if self._active:
            return self.status()
        if vars(self.service).get('_tls_native_companion_context_fence') is not None:
            raise CompanionTakeoverError('native_context_already_owned')
        self.provider = NativeCompanionTakeoverProvider(self.store.db_path,
            binding_for=self._binding_for, authorize=self._authorize,
            authorize_read=self._authorize_read, clock=self.memory.clock)
        self.fence = NativeCompanionTakeoverFence(self.service, self.provider,
            assembler=self.unified.assembler, binding_for_legacy=self._legacy_binding,
            legacy_allowed=lambda ctx, event, method: False,
            install_guard=self._install_guard).install()
        self.fence._tls_mc_runtime_owner = self
        self.memory.mc_context_provider = self.provider
        self.memory.mc_context_runtime = self
        setattr(self.context, '_tls_mc_context_runtime', self)
        self._generation += 1
        self._active = True
        self._phase = 'native_memory_companion'
        candidates = getattr(self.runtime, 'profile_candidates', None)
        capture = NativeProfileCapture(self.memory, candidates)
        self.explicit = NativeMCCaptureRouter(NativeExplicitMemory(self.memory),
            profile_capture=capture, owned_selector=self._explicit_owned,
            scope_for=self._explicit_scope, native_write_allowed=self._explicit_write_allowed,
            relationship_owned=True, profile_owned=True)
        self.companion.bind_capture_router(self.explicit)
        return self.status()

    async def start(self):
        return await self.activate()

    def explicit_installed(self):
        return self.explicit is not None and self.companion.capture_router is self.explicit

    async def prepare_explicit(self, *, relationship=False, profile=False):
        if not self.explicit_installed() or not self._live():
            raise CompanionTakeoverError('native_capture_router_unavailable')
        return self.explicit

    def open_claims(self):
        if not self._live() or self.explicit is None:
            raise CompanionTakeoverError('native_capture_router_unavailable')
        self.explicit.open()
        return self.status()

    async def restore_explicit(self):
        if self.explicit is not None:
            self.explicit.close()
            await self.explicit.wait_drained(timeout=30)
        # Already-owned typed slices stay partitioned; disabling writes cannot
        # restart the companion-store writer for those same records.
        return self.status()

    def _summary_projection(self):
        owned = self._source_current()
        active = bool(self._active and owned and self.companion.active)
        return dict(active=active, algorithm_active=active, configured=self.summary_requested(),
            phase='native_owned_pipeline' if active else 'closed', owner='tls_native_memory_companion',
            source_current=owned, controller_retained=False, recovery_required=False,
            algorithm_only=False, stop_requires_full_service_stop=True,
            responsibilities={key:'native' for key in
                ('algorithm','timeline','provider_selection','store','worker','audit_static_calls')})

    async def inspect_summary(self):
        return dict(self._summary_projection(), ready_for_activation=False,
            explanation='摘要随TLS原生记忆服务运行，不再切换旧插件算法实例')

    async def activate_summary(self):
        if not self._source_current():
            raise RuntimeError('native memory service unavailable')
        return self.status()

    async def restore_summary(self):
        raise RuntimeError('stop_native_memory_service_to_restore_legacy_owner')

    async def restore_legacy(self):
        raise RuntimeError('stop_full_native_memory_service_before_enabling_legacy')

    async def close(self):
        self.stop()
        if self.explicit is not None:
            await self.explicit.wait_drained(timeout=30)
        self._closed.set()
        if getattr(self.context, '_tls_mc_context_runtime', None) is self:
            delattr(self.context, '_tls_mc_context_runtime')

    def status(self):
        router = self.explicit.status() if self.explicit is not None else {}
        capture = dict(router, installed=self.explicit_installed(),
            pending_captures=router.get('pending',0),
            pending_native_operations=router.get('native_pending',0),
            original_slots=0, ownership='native_service_partition',
            fence_open=router.get('active') is True)
        result = dict(active=self._live(), phase=self._phase, generation=self._generation,
            fence_installed=self.fence is not None and self.fence.installed,
            pending_requests=len(self._requests), counts=dict(self._counts),
            last_feedback=self._last_feedback, crud_owner_changed=True,
            full_native=True, legacy_capture_profile_summary='native_service',
            summary=self._summary_projection())
        for key, enabled in (('explicit',self.explicit_requested()),
                ('relationship',self.relationship_requested()),('profile',self.profile_requested())):
            result[key] = dict(capture, configured=enabled,
                active=enabled and capture['fence_open'] and self._live(), initialization_error=None)
        return result
