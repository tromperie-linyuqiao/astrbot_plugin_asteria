"""Register migrated tools through AstrBot's existing FunctionTool API.

Tools are installed only after the original plugin has retired. This keeps the
original names without replacing a live legacy tool during candidate loading.
"""
from astrbot.core.agent.tool import FunctionTool


class NativeIntegratedTool(FunctionTool):
    def __init__(self, controller, kind, name, description, parameters, method):
        super().__init__(name=name, description=description, parameters=parameters)
        self._controller, self._kind, self._method = controller, kind, method

    async def call(self, context, **kwargs):
        controller = self._controller
        service = getattr(controller, self._kind, None)
        active = (getattr(service, 'active', False) if self._kind == 'insight'
                  else getattr(service, '_active', False))
        if controller._closed or not active:
            return '原生服务已停止，未执行操作。'
        event = context.context.event
        return await getattr(service, self._method)(event, **kwargs)


def _parameters(**properties):
    return {'type':'object', 'properties':properties, 'additionalProperties':False}


def insight_tools(controller):
    days={'type':'integer','minimum':1,'maximum':90,'description':'最近几天，默认7天'}
    specs=[
        ('usage_analytics','分析当前私聊模型用量、token与延迟，不推算未配置的价格。',_parameters(days=days),'usage_analytics'),
        ('gather_context','从当前私聊的记忆、日程、便签与经历聚合相关资料。',
            dict(_parameters(query={'type':'string','minLength':1,'maxLength':512,'description':'要查询的问题或关键词'}),required=['query']),'gather_context'),
        ('chat_pattern','分析当前私聊近期对话模式，不读取其他人的会话。',_parameters(days=dict(days,maximum=30)),'chat_pattern'),
        ('memory_insight','检查当前私聊TLS记忆来源、重复候选及容量，不自动删除。',_parameters(),'memory_insight'),
        ('mood_timeline','查看当前私聊的情绪趋势参考，不把模型推断当成事实。',_parameters(days=dict(days,maximum=30)),'mood_timeline'),
    ]
    return [NativeIntegratedTool(controller,'insight',*spec) for spec in specs]


def phone_tools(controller):
    return [
        NativeIntegratedTool(controller,'phone','phone_perception_query','读取已授权PPB手机当前状态，不猜测未授权定位。',
            _parameters(aspect={'type':'string','description':'如电量、屏幕、App、音乐；留空查询状态'}),'phone_perception_query'),
        NativeIntegratedTool(controller,'phone','phone_perception_diary','读取已授权手机感知日记。',
            _parameters(days_ago={'type':'integer','minimum':0,'maximum':30,'description':'几天前，默认今天'}),'phone_perception_diary'),
        NativeIntegratedTool(controller,'phone','phone_perception_insight','分析已授权手机最近活动与使用状态。',
            _parameters(hours={'type':'integer','minimum':1,'maximum':72,'description':'最近几小时，默认6'}),'phone_perception_insight'),
        NativeIntegratedTool(controller,'phone','playlist_annotate','给指定曲目添加用户明确提供的备注。',
            dict(_parameters(song={'type':'string','description':'明确曲名'}, note={'type':'string','description':'用户提供的备注'}),required=['song','note']),'playlist_annotate'),
    ]


class NativeMCServiceTool(FunctionTool):
    def __init__(self, controller, spec):
        super().__init__(name=spec['name'], description=spec['description'], parameters=spec['parameters'])
        self.controller = controller

    async def call(self, context, **kwargs):
        owner = getattr(self.controller, 'mc_full', None)
        if self.controller._closed or owner is None or not owner.active or owner.closed:
            return '{"ok":false,"error":"native_memory_service_inactive"}'
        return await owner.dispatch_tool(self.name, context.context.event, **kwargs)


def memory_companion_tools(controller):
    owner = controller.mc_full
    if owner is None or not owner.active:
        return []
    # Core material already has the existing TLS revision-aware tool. Keeping
    # the old disabled core writer in the model's list would duplicate that
    # responsibility and advertise an operation which deliberately cannot run.
    return [NativeMCServiceTool(controller, spec) for spec in owner.tool_definitions().values()
        if spec['name']!='memory_companion_core_memory']
