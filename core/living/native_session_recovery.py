"""One-use same-process continuity of already observed private identities.

No disk bootstrap, fabricated event or binding-code grant. A full process restart
still needs real ingress. Current role, SDK persona and all execution gates are
checked again by the new owner before it resumes any work.
"""
from copy import deepcopy
import time

from .models import private_scope

SLOT = '_tls_private_reload_continuity'


def capture(plugin, *, clock=time.monotonic):
    integration = getattr(plugin, '_presence', None)
    api = getattr(integration, 'api', None)
    host = getattr(integration, 'living_host', None)
    if api is None or host is None or getattr(plugin, '_stopping', False):
        return False
    rows = [private_scope(s) for s in api.known_private_scopes() if host.authorized_scope(s)]
    owner = getattr(getattr(plugin, '_native_server_integrations', None), 'pc_full', None)
    service = getattr(owner, 'service', None)
    source = getattr(service, '_tls_source', None)
    bound = getattr(service, '_tls_primary_scope', None)
    pc = None
    if (bound in rows and isinstance(source, dict) and source.get('source') == 'genuine_inbound_sdk_selection'
            and source.get('event_id') and source.get('persona_id')):
        pc = dict(scope=deepcopy(bound), event_id=source['event_id'], persona_id=source['persona_id'])
    setattr(plugin.context, SLOT, dict(plugin=plugin, api=api, created=clock(), scopes=rows, pc=pc,
        trusted=deepcopy(getattr(host, '_trusted_scope', None))))
    return True


async def restore(plugin, *, clock=time.monotonic):
    context = plugin.context
    proof = getattr(context, SLOT, None)
    result = dict(restored_scopes=0, pc_bound=False, state='no_same_process_handoff')
    if not isinstance(proof, dict): return result
    # Consume once even on rejection. No later administrative request can revive it.
    delattr(context, SLOT)
    old = proof.get('plugin')
    old_api = proof.get('api')
    if (old is not plugin and getattr(old,'context',None) is context
            and getattr(old,'_stopping',False) is True
            and 0 <= clock()-proof.get('created',-1e9) <= 900
            and not getattr(old_api,'_closed',True)):
        # A failed memory drain used to skip Presence cleanup. Only after the
        # new Host has closed the stopped predecessor's exact queue workers
        # may its genuine same-process lease snapshot be handed over. Close
        # ingress synchronously; do not close stores with unfinished memory.
        previous=getattr(old,'_presence',None)
        old_host=getattr(previous,'living_host',None)
        runtime=getattr(old_host,'runtime',None)
        lanes=[getattr(runtime,name,None) for name in ('reminders','delivery')]
        def queue_stopped(lane):
            if lane is None:return True
            driver=getattr(lane,'driver',lane)
            worker=getattr(driver,'_worker',None)
            return (getattr(driver,'active',True) is False
                and getattr(getattr(driver,'sender',None),'active',True) is False
                and (worker is None or worker.done()))
        if (getattr(previous,'api',None) is old_api and old_host is not None
                and old_host.plugin is old and runtime is not None
                and all(queue_stopped(lane) for lane in lanes)):
            previous.close()
    if (old is plugin or getattr(old, 'context', None) is not context or not getattr(old, '_stopping', False)
            or not getattr(old_api, '_closed', False) or not 0 <= clock() - proof.get('created', -1e9) <= 900):
        return dict(result, state='handoff_expired_or_old_owner_not_closed')
    integration = getattr(plugin, '_presence', None)
    api = getattr(integration, 'api', None)
    host = getattr(integration, 'living_host', None)
    if api is None or host is None: return dict(result, state='new_host_unavailable')
    for saved in proof['scopes']:
        scope = private_scope(saved)
        resolved = plugin._resolve_session(scope['user_id'])
        if resolved is None or resolved[0] != scope['character_id']: continue
        if api.remember_scope(scope) and host.authorized_scope(scope): result['restored_scopes'] += 1
    trusted = proof.get('trusted')
    if trusted is not None and host.authorized_scope(trusted): host.remember_scope(trusted)
    pc = proof.get('pc')
    owner = getattr(getattr(plugin, '_native_server_integrations', None), 'pc_full', None)
    service = getattr(owner, 'service', None)
    if pc and owner is not None and owner.active and service is not None and host.authorized_scope(pc['scope']):
        try:
            # bind_scope resolves the actual current SDK selection again and
            # rejects persona/config/owner changes; this is not a fake message.
            await service.bind_scope(pc['scope'], pc['event_id'], pc['persona_id'])
            owner._bound_source = dict(source='genuine_inbound_same_process_reload',
                scope=deepcopy(pc['scope']), persona_id=pc['persona_id'])
            host.remember_scope(pc['scope'])
            result['pc_bound'] = True
            binding = getattr(getattr(host.runtime, 'native_services', None), 'persona_binding', None)
            if binding is not None: binding.bind(pc['scope'], pc['persona_id'])
            daily = getattr(host.runtime, 'pc_daily_lifecycle', None)
            if daily is not None: await daily.resume_scope(pc['scope'], pc['event_id'])
        except (PermissionError, ValueError, RuntimeError):
            result['pc_bound'] = False
    return dict(result, state='same_process_handoff_restored')
