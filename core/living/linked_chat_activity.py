"""Read the existing paired activity counter, never mirror messages or leases."""
import math

from .chat_expressions import ChatExpressionError
from .chat_identity import identity_service
from .chat_workspace import ChatWorkspace
from .models import private_scope


def linked_activity_at(plugin, scope, store, now):
    scope = private_scope(scope)
    try:
        links = identity_service(plugin)
    except ChatExpressionError:
        return 0.0  # Optional sharing is unavailable, not an invented peer.
    if scope['platform'] == scope['bot_id'] == 'webchat':
        origin = scope['session_id'].split(':', 2)[-1]
        prefix = 'webchat!' + scope['user_id'] + '!'
        if not origin.startswith(prefix): return 0.0
        link = links.get(scope['user_id'], origin[len(prefix):])
        if not link or link.get('app_scope') != scope: return 0.0
        peer = link['qq_scope']
    else:
        link = links.for_qq(scope)
        if not link: return 0.0
        peer = link.get('app_scope')
        if not peer: return 0.0
    settings = ChatWorkspace(links)
    if not settings.settings(link['username'], link['session_id'])['values']['linked_activity']:
        return 0.0
    peer = private_scope(peer)
    observed = store.activity(peer)
    if type(observed) not in (int, float) or not math.isfinite(observed) or not 0 <= observed <= now + 30:
        return 0.0
    fresh = links.get(link['username'], link['session_id'])
    if (not fresh or fresh['link_id'] != link['link_id'] or fresh['qq_scope'] != link['qq_scope']
            or fresh.get('app_scope') != link.get('app_scope')
            or not settings.settings(link['username'], link['session_id'])['values']['linked_activity']):
        return 0.0
    return float(observed)
