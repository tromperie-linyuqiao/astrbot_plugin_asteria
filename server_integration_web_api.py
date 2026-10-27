"""Normal AstrBot administrator operations for the integrated native services."""
from __future__ import annotations
from astrbot.api.web import request, json_response, error_response

PREFIX='/astrbot_plugin_virtual_body/page/server-integration'


class NativeServerIntegrationWebApi:
    def __init__(self, plugin): self.plugin=plugin
    def register_routes(self):
        self.plugin.context.register_web_api(PREFIX+'/status', self.status, ['GET'], 'TLS integrated service runtime')
        self.plugin.context.register_web_api(PREFIX+'/mc/summary/status', self.summary_status, ['GET'], 'TLS summary algorithm current ownership')
        self.plugin.context.register_web_api(PREFIX+'/mc/summary/inspect', self.inspect_mc_summary, ['GET'], 'TLS bounded summary source and inflight inspection')
        for route, handler in [('insight/activate', self.activate_insight), ('insight/stop', self.stop_insight),
                               ('phone/prepare', self.prepare_phone), ('phone/activate', self.activate_phone),
                               ('phone/stop', self.stop_phone),('phone/restore-helpers',self.restore_phone_helpers),
                               ('mc/activate',self.activate_mc),('mc/stop',self.stop_mc),
                               ('mc/explicit/activate',self.activate_mc_explicit),
                               ('mc/explicit/stop',self.stop_mc_explicit),
                               ('mc/explicit/restore',self.restore_mc_explicit),
                               ('mc/relationship/activate',self.activate_mc_relationship),
                               ('mc/relationship/stop',self.stop_mc_relationship),
                               ('mc/relationship/restore',self.restore_mc_relationship),
                               ('mc/profile/activate',self.activate_mc_profile),
                               ('mc/profile/stop',self.stop_mc_profile),
                               ('mc/profile/restore',self.restore_mc_profile),
                               ('mc/summary/activate',self.activate_mc_summary),
                               ('mc/summary/stop',self.restore_mc_summary),
                               ('mc/summary/restore',self.restore_mc_summary),
                               ('mc/full/activate',self.activate_mc_full),('mc/full/stop',self.stop_mc_full),
                               ('mc/full/restore',self.restore_mc_full),
                               ('pc/full/activate',self.activate_pc_full),('pc/full/stop',self.stop_pc_full),
                               ('pc/full/restore',self.restore_pc_full),
                               ('proactive/full/activate',self.activate_proactive_full),
                               ('proactive/full/stop',self.stop_proactive_full),
                               ('proactive/full/restore',self.restore_proactive_full),
                               ('mc/restore',self.restore_mc),('pc/activate',self.activate_pc),('pc/stop',self.stop_pc)]:
            self.plugin.context.register_web_api(PREFIX+'/'+route, handler, ['POST'], 'TLS native service ownership operation')
    def _service(self):
        try: username=getattr(request,'username',None)
        except RuntimeError: username=None
        if not isinstance(username,str) or not username.strip(): raise PermissionError('native dashboard authentication required')
        service=getattr(self.plugin,'_native_server_integrations',None)
        if service is None or service._closed: raise RuntimeError('integrations unavailable')
        return service
    async def status(self):
        try: return json_response(self._service().status(),headers={'Cache-Control':'no-store'})
        except PermissionError: return error_response('请登录AstrBot管理后台',status_code=401)
        except RuntimeError: return error_response('原生服务暂不可用',status_code=503)
    async def summary_status(self):
        try:
            service=self._service()
            mc=service.mc
            state=mc.status().get('summary',{}) if mc is not None else {'active':False,'phase':'unavailable'}
            return json_response({'ok':True,'summary':state},headers={'Cache-Control':'no-store'})
        except PermissionError:return error_response('请登录AstrBot管理后台',status_code=401)
        except RuntimeError:return error_response('摘要服务暂不可用',status_code=503)
    async def inspect_mc_summary(self):
        try:return json_response(await self._service().inspect_mc_summary(),headers={'Cache-Control':'no-store'})
        except PermissionError:return error_response('请登录AstrBot管理后台',status_code=401)
        except RuntimeError:return error_response('当前MC实例或来源不可用',status_code=409)
    async def _operation(self,name):
        try:
            service=self._service()
            body=await request.json(default=None)
            if body not in ({},None): return error_response('此操作不接受额外参数',status_code=400)
            return json_response(await getattr(service,name)(),headers={'Cache-Control':'no-store'})
        except PermissionError: return error_response('请登录AstrBot管理后台',status_code=401)
        except (RuntimeError,ValueError,TypeError):
            return error_response('旧服务尚未完成退出，或状态已变化；请核对接管状态',status_code=409)
        except Exception:
            return error_response('服务移交暂未完成，请读取状态后处理，不要重复提交',status_code=503)
    async def activate_insight(self): return await self._operation('activate_insight')
    async def stop_insight(self): return await self._operation('stop_insight')
    async def prepare_phone(self): return await self._operation('prepare_phone')
    async def activate_phone(self): return await self._operation('activate_phone')
    async def stop_phone(self): return await self._operation('stop_phone')

    async def restore_phone_helpers(self): return await self._operation('restore_phone_helpers')
    async def activate_mc(self): return await self._operation('activate_mc')
    async def stop_mc(self): return await self._operation('stop_mc')
    async def activate_mc_explicit(self): return await self._operation('activate_mc_explicit')
    async def stop_mc_explicit(self): return await self._operation('stop_mc_explicit')
    async def restore_mc_explicit(self): return await self._operation('restore_mc_explicit')
    async def activate_mc_relationship(self): return await self._operation('activate_mc_relationship')
    async def stop_mc_relationship(self): return await self._operation('stop_mc_relationship')
    async def restore_mc_relationship(self): return await self._operation('restore_mc_relationship')
    async def activate_mc_profile(self): return await self._operation('activate_mc_profile')
    async def stop_mc_profile(self): return await self._operation('stop_mc_profile')
    async def restore_mc_profile(self): return await self._operation('restore_mc_profile')
    async def activate_mc_summary(self): return await self._operation('activate_mc_summary')
    async def restore_mc_summary(self): return await self._operation('restore_mc_summary')
    async def activate_mc_full(self): return await self._operation('activate_mc_full')
    async def stop_mc_full(self): return await self._operation('stop_mc_full')
    async def restore_mc_full(self): return await self._operation('restore_mc_full')
    async def activate_pc_full(self): return await self._operation('activate_pc_full')
    async def stop_pc_full(self): return await self._operation('stop_pc_full')
    async def restore_pc_full(self): return await self._operation('restore_pc_full')
    async def activate_proactive_full(self): return await self._operation('activate_proactive_full')
    async def stop_proactive_full(self): return await self._operation('stop_proactive_full')
    async def restore_proactive_full(self): return await self._operation('restore_proactive_full')
    async def restore_mc(self): return await self._operation('restore_mc')
    async def activate_pc(self): return await self._operation('activate_pc')
    async def stop_pc(self): return await self._operation('stop_pc')
