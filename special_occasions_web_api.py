"""Authenticated editing of an explicitly selected existing PC user's calendar."""
from copy import deepcopy
from astrbot.api.web import error_response, json_response, request
from .core.living.models import private_scope
from .core.living.journal import JournalConflict
from .core.living.native_pc_business.helpers import validate_special_changes


class SpecialOccasionsWebApi:
    def __init__(self, plugin): self.plugin = plugin

    def register_routes(self):
        for suffix, callback, methods in (('settings', self.settings, ['GET']), ('save', self.save, ['POST']),
                ('preview', self.preview, ['POST']), ('delivery', self.delivery, ['POST'])):
            self.plugin.context.register_web_api('/astrbot_plugin_virtual_body/page/special-occasions/' + suffix,
                callback, methods, 'TLS课表、生日与节日消息')

    def service(self, scope):
        plugin = self.plugin
        owner = getattr(getattr(plugin, '_native_server_integrations', None), 'pc_full', None)
        service = getattr(owner, 'service', None)
        selected = plugin._resolve_session(scope['user_id'])
        if (getattr(plugin, '_stopping', True) or owner is None or not owner.active or service is None
                or not service.active or not service.native_source_current()
                or selected is None or selected[0] != scope['character_id']):
            raise PermissionError('请选择已配置角色的现有私聊用户')
        return owner, service

    async def respond(self, write, *, delivery=False, preview=False):
        try:
            if not str(getattr(request, 'username', '') or '').strip():
                return error_response('请通过AstrBot后台登录', status_code=401)
            data = await request.json(default=None) if write else dict(getattr(request, 'query', None) or {})
            if type(data) is not dict: raise ValueError('请求需要JSON对象')
            fields = ('platform', 'bot_id', 'user_id', 'character_id', 'session_id')
            raw_scope = data.get('scope') if write else {k: data.get(k) for k in fields}
            scope = private_scope(dict(raw_scope, private=True))
            owner, service = self.service(scope)
            from .core.living.chat_identity import identity_service
            from .core.living.chat_workspace import ChatWorkspace
            from .core.living.chat_expressions import ChatExpressionError
            try:
                links = identity_service(self.plugin)
                link = links.for_qq(scope)
            except ChatExpressionError:
                links, link = None, None
            routing = None
            if delivery:
                required = {'scope','destination','expected_revision'}
                if not required <= set(data) or set(data) - required - {'linked_activity'} or not link:
                    raise ValueError('请选择实际已确认绑定的QQ会话')
                if data['destination'] not in {'qq','chat_text','chat_all'}: raise ValueError('发送位置无效')
                changes = dict(proactive_destination=data['destination'])
                if 'linked_activity' in data:
                    if type(data['linked_activity']) is not bool: raise ValueError('两端聊天互相免打扰须为开关')
                    changes['linked_activity'] = data['linked_activity']
                routing = ChatWorkspace(links).save(link['username'],link['session_id'],
                    changes,data['expected_revision'])
            def authorize():
                try: return self.service(scope) == (owner, service)
                except (PermissionError, ValueError, RuntimeError): return False
            if write and not delivery:
                if set(data) != {'scope', 'changes', 'expected_revision'}: raise ValueError('保存字段不完整')
                if preview:
                    changes = validate_special_changes(data['changes'])
                    revision = data['expected_revision']
                    if type(revision) is not int or revision < 0: raise ValueError('请先读取当前设置版本')
                    async with service._data_lock:
                        user = service._special_user(scope['user_id'], authorize)
                        if user.get('special_settings_revision', 0) != revision:
                            raise JournalConflict('设置已变化，请刷新后预览')
                        detached = deepcopy(user); detached.update(changes)
                        result = service._special_view(detached)
                        service._special_user(scope['user_id'], authorize)
                else:
                    result = await service.update_special_settings(scope['user_id'], data['changes'], data['expected_revision'], authorize=authorize)
            else:
                result = await service.get_special_settings(scope['user_id'], authorize=authorize)
            if link:
                routing = ChatWorkspace(links).settings(link['username'],link['session_id'])
            return json_response(dict(ok=True, scope=scope, settings=result,
                routing=routing,
                preview_only=preview,
                administration_does_not_grant_runtime_scope=True), headers={'Cache-Control': 'no-store'})
        except JournalConflict:
            return error_response('设置已变化，请刷新后再保存', status_code=409)
        except KeyError:
            return error_response('该用户还没有陪伴资料，请选择现有用户', status_code=404)
        except PermissionError as exc:
            return error_response(str(exc), status_code=403)
        except (ValueError, TypeError) as exc:
            return error_response(str(exc), status_code=400)
        except (RuntimeError, OSError):
            return error_response('课表服务暂不可用；保存结果不明确时先重新读取', status_code=503)

    async def settings(self): return await self.respond(False)
    async def save(self): return await self.respond(True)
    async def preview(self): return await self.respond(True, preview=True)
    async def delivery(self): return await self.respond(True, delivery=True)
