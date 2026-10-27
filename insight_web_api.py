"""AstrBot-authenticated, read-only native Insight endpoints.
Private analysis requires the same current full TLS scope as ordinary tools.
"""
from __future__ import annotations
from astrbot.api.web import request, json_response, error_response
from .memory_web_api import SCOPE_FIELDS, _scope, _InvalidRequest
from .core.living.native_insight_center import NativeInsightCenter
from .core.living.native_insight_source import InsightSourceUnavailable

PREFIX='/astrbot_plugin_virtual_body/page/insight'


class NativeInsightWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        for action,name in [('overview','overview'),('usage','usage'),('chat-pattern','chat_pattern'),
                            ('memory','memory'),('gather','gather'),('mood','mood')]:
            self.plugin.context.register_web_api(PREFIX+'/'+action,getattr(self,name),['GET'],
                'TLS native read-only Insight '+action)

    async def _respond(self,action):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过AstrBot管理后台认证',status_code=401)
        service=getattr(self.plugin,'_native_insight',None)
        if not isinstance(service,NativeInsightCenter) or service.active is not True:
            return error_response('原生数据洞察暂不可用',status_code=503)
        try:
            query=dict(getattr(request,'query',None) or {})
            if set(query)-set(SCOPE_FIELDS)-{'days','q'}:raise _InvalidRequest('未知洞察参数')
            supplied=any(field in query for field in SCOPE_FIELDS)
            scope=_scope({field:query.get(field) for field in SCOPE_FIELDS}) if supplied else None
            if scope is None and action not in {'overview','usage'}:
                raise _InvalidRequest('请选择真实完整私聊范围')
            days=query.get('days','7')
            if not isinstance(days,(int,str)) or isinstance(days,bool) or not str(days).isdigit():
                raise _InvalidRequest('天数必须是整数')
            days=int(days)
            if not 1<=days<=(90 if action=='usage' else 30):raise _InvalidRequest('天数超出范围')
            result=await service.report(action,scope=scope,days=days,query=query.get('q',''),administrator=True)
            if getattr(self.plugin,'_native_insight',None) is not service or not service.active:
                raise RuntimeError('insight lifecycle changed')
            return json_response(result,headers={'Cache-Control':'no-store'})
        except (_InvalidRequest,ValueError,TypeError):
            return error_response('请选择完整私聊范围及有效查询参数',status_code=400)
        except PermissionError:
            return error_response('当前真实私聊权限不可用，请在对应会话正常聊天后再查看',status_code=403)
        except InsightSourceUnavailable:
            return error_response('数据源缺失、结构不兼容或超出有界样本；不显示伪零统计',status_code=503)
        except Exception:
            return error_response('数据洞察读取暂不可用，不会修改数据或调用模型',status_code=503)

    async def overview(self):return await self._respond('overview')
    async def usage(self):return await self._respond('usage')
    async def chat_pattern(self):return await self._respond('chat-pattern')
    async def memory(self):return await self._respond('memory')
    async def gather(self):return await self._respond('gather')
    async def mood(self):return await self._respond('mood')
