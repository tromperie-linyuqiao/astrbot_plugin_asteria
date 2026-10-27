"""Resolve the actual TLS-owned Companion, without a legacy Star alias."""
from __future__ import annotations


def native_companion(context, *, memory_service=None):
    """Return selected, actual service, actual extension API; never a lease."""
    try:
        rows = context.get_all_stars()
        if not isinstance(rows, (list, tuple)) or len(rows) > 256:
            return False, None, None
        matches = [row for row in rows if getattr(row, 'root_dir_name', None) == 'astrbot_plugin_virtual_body']
        if len(matches) != 1 or getattr(matches[0], 'activated', None) is not True:
            return False, None, None
        plugin = getattr(matches[0], 'star_cls', None)
        integrations = getattr(plugin, '_native_server_integrations', None)
        if (plugin is None or getattr(plugin, 'context', None) is not context
                or integrations is None or integrations.plugin is not plugin
                or integrations.context is not context):
            return False, None, None
        selected = plugin.config.get('living_pc_full_native_enabled', False) is True
        if not selected:
            return False, None, None
        if integrations._closed:
            return True, None, None
        from ..native_pc_full_owner import NativePCFullOwner
        from ..native_pc_service import NativePCService
        from ..native_pc_business.main import PrivateCompanionExtensionAPI
        owner = getattr(integrations, 'pc_full', None)
        service = getattr(owner, 'service', None)
        api = getattr(service, 'extension_api', None)
        if (type(owner) is not NativePCFullOwner or owner.integrations is not integrations
                or owner.context is not context or owner.plugin is not plugin
                or owner.active is not True or owner.legacy_closed() is not True
                or type(service) is not NativePCService or service.context is not context
                or service.active is not True or service.native_source_current() is not True
                or type(api) is not PrivateCompanionExtensionAPI or api._plugin is not service):
            return True, None, None
        if memory_service is not None:
            memory = getattr(integrations, 'mc_full', None)
            if (memory is None or memory.service is not memory_service
                    or memory.context is not context or memory.active is not True
                    or memory.closed is not False
                    or plugin.config.get('living_mc_full_native_enabled', False) is not True):
                return True, None, None
        return True, service, api
    except Exception:
        return True, None, None
