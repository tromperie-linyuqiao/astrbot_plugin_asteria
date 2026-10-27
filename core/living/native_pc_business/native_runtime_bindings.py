"""Use the actual TLS-owned services; never import or start another plugin."""
from __future__ import annotations


def integrations_for(owner):
    context = getattr(owner, 'context', None)
    try: rows = context.get_all_stars()
    except Exception: return None
    if not isinstance(rows, (list, tuple)) or len(rows) > 256: return None
    matches = [row for row in rows if getattr(row, 'root_dir_name', None) == 'astrbot_plugin_virtual_body']
    if len(matches) != 1 or getattr(matches[0], 'activated', None) is not True: return None
    plugin = getattr(matches[0], 'star_cls', None)
    integrations = getattr(plugin, '_native_server_integrations', None)
    if (plugin is None or getattr(plugin, 'context', None) is not context or integrations is None
            or getattr(integrations, 'plugin', None) is not plugin
            or getattr(integrations, 'context', None) is not context): return None
    return integrations


def native_service(owner, kind):
    """Return (native selected, live service/bridge). Selected-unavailable denies.

    The selection flag is not used to claim liveness: actual owner, service,
    context and running state must all agree. No old fallback after takeover.
    """
    integrations = integrations_for(owner)
    if integrations is None: return False, None
    flags = {'memory': 'living_mc_full_native_enabled', 'phone': 'living_phone_native_enabled',
             'insight': 'living_insight_native_enabled'}
    if kind not in flags: raise ValueError('known TLS native service kind required')
    selected = integrations.plugin.config.get(flags[kind], False) is True
    if not selected: return False, None
    if getattr(integrations, '_closed', True): return True, None
    if kind == 'memory':
        full = getattr(integrations, 'mc_full', None)
        service = getattr(full, 'service', None)
        if (full is None or getattr(full, 'active', False) is not True
                or getattr(full, 'context', None) is not owner.context
                or service is None or getattr(service, 'context', None) is not owner.context): return True, None
        getter = getattr(full, 'get_bridge', None)
        if not callable(getter): return True, None
        try: return True, getter()
        except Exception: return True, None
    service = getattr(integrations, kind, None)
    active = getattr(service, '_active', False) if kind == 'phone' else getattr(service, 'active', False)
    actual_context = getattr(service, 'context', None)
    if kind == 'insight': actual_context = getattr(getattr(service, 'plugin', None), 'context', None)
    return True, service if active is True and actual_context is owner.context else None
