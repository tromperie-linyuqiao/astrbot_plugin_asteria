"""Normal AstrBot administrator operations for the integrated native services."""
from __future__ import annotations
from datetime import datetime, timezone
from astrbot.api.web import request, json_response, error_response

PREFIX='/astrbot_plugin_virtual_body/page/server-integration'


class NativeServerIntegrationWebApi:
    def __init__(self, plugin): self.plugin=plugin
    def register_routes(self):
        self.plugin.context.register_web_api(PREFIX+'/status', self.status, ['GET'], 'TLS integrated service runtime')
        self.plugin.context.register_web_api(PREFIX+'/business-links', self.business_links, ['GET'], 'TLS actual business connections and execution ownership')
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
    async def business_links(self):
        """Observe current owners; this is neither an end-to-end test nor a lease."""
        try:
            service = self._service()
            state = service.status()
            rows = []
            definitions = (
                ('mc_full', '记忆与摘要', '真实入站与历史导入', 'NativeMemoryCompanion',
                 '原记忆库与原生资料库，保留历史来源', '检索、画像、摘要与统一上下文', '/tls/page/memory-native/', 'mc'),
                ('pc_full', '私人陪伴与虚拟日常', '真实会话、角色计划和活动', 'NativePCService',
                 '原陪伴资料与同一 Journal', '活动、目标、上下文与分享候选', '/tls/page/pc-native/', 'pc'),
                ('proactive_full', '主动决策与发送', '感知、日程、角色日常与既有任务', 'NativeProactiveChatHost',
                 '原主动配置、持久任务与发送账本', '同一发送通道 → QQ 或已授权 Chat', '/tls/page/console/#proactive_native', None),
                ('phone', '手机与音乐感知', '已授权 PPB / Chat 采集适配器', 'NativePhoneService',
                 '同一原生 Phone client 与 Presence 状态', '当前状态、上下文与陪伴候选', '/tls/page/console/#phone', None),
                ('insight', '数据洞察', '现有会话和原索引', 'NativeInsightService',
                 '原洞察资料和现有索引', '查询报告与原校准任务', '/tls/page/console/#insight', None),
            )
            for key, label, entry, processor, storage, outlet, url, legacy_key in definitions:
                item = state.get(key) or {}
                active = item.get('native_active' if key in ('phone', 'insight') else 'active')
                if key in ('phone', 'insight'):
                    legacy = item.get('legacy_active')
                elif legacy_key:
                    legacy = (state.get(legacy_key) or {}).get('legacy_active')
                else:
                    legacy = item.get('original_plugin_active')
                status = ('execution_conflict' if active is True and legacy is True else
                          'native_running' if active is True and legacy is False else
                          'legacy_running' if legacy is True else
                          'inactive' if active is False and legacy is False else 'unconfirmed')
                rows.append(dict(id=key, name=label, entry=entry, processor=processor,
                    storage=storage, outlet=outlet, management_url=url, state=status,
                    native_active=active, legacy_active=legacy, phase=item.get('phase'),
                    configured=item.get('configured'), has_error=bool(item.get('last_error')),
                    end_to_end_verified=False))
            host = service._host()
            runtime = getattr(host, 'runtime', None)
            daily = getattr(runtime, 'pc_daily_lifecycle', None)
            live = host is not None and getattr(host, '_closed', True) is False
            facts = dict(host_running=live, daily_service_mounted=daily is not None,
                daily_service_active=getattr(daily, 'active', False) is True,
                daily_live_scopes=len(getattr(daily, '_scopes', {})) if daily is not None else None,
                shared_delivery_mounted=getattr(service, '_business_delivery', None) is not None,
                server_completion_proves_client_received=False, reliable_background_push=False)
            # source_current on this owner describes the retired legacy file
            # identities. Cold successors need not hold that RAM snapshot.
            legacy_proof = (state.get('proactive_full') or {}).get('source_current')
            return json_response(dict(ok=True, observed_at=datetime.now(timezone.utc).isoformat(),
                read_only=True, links=rows, runtime=facts,
                retired_proactive_source_snapshot_current=legacy_proof,
                runtime_observation_only=True, creates_runtime_permission=False,
                external_dependencies=['AstrBot', 'QQ/平台适配器', '经授权的 PPB 采集设备', 'Android 系统通知与后台策略']),
                headers={'Cache-Control':'no-store'})
        except PermissionError: return error_response('请登录AstrBot管理后台',status_code=401)
        except RuntimeError: return error_response('业务联动状态暂不可用，请刷新；未执行任何交接',status_code=503)
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
