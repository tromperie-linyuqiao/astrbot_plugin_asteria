"""Pure capability/ownership presentation over current TLS snapshots.

This catalog is not a second capability registry. It never registers handlers,
invokes business logic, reads files, polls devices, changes ownership, or starts
work. Historical responsibility references are separated from live evidence.
"""
from __future__ import annotations

from copy import deepcopy

DOMAINS = (
    {'id': 'interaction', 'label': '交互与陪伴'},
    {'id': 'memory', 'label': '记忆与资料'},
    {'id': 'perception', 'label': '感知与上下文'},
    {'id': 'role', 'label': '角色与RP'},
    {'id': 'actions', 'label': '任务与行动'},
    {'id': 'system', 'label': '系统与扩展'},
)

# Scope is a business responsibility, never a whole-plugin replacement claim.
# API entries are only existing route families, not a promise that every user
# or conversation currently has permission to mutate them.
CATALOG = (
 ('tls.memory.full_service','完整原生记忆服务','memory','memory','memory','native',
  '由TLS管理记忆捕获、画像、摘要、关系图谱、原历史与原生管理接口的完整生命周期。',
  ('原MC配置与原历史路径','同库来源与审核状态'),('旧MC正常停用与实际排空','真实运行对象和原P5策略'),
  ('server-integration/status',),('astrbot_plugin_memory_companion',),'full_runtime',
  '完整运行实例接管与具体记忆命中分别记录；不因部署成功而声称新QQ样本或长测已通过。'),
 ('tls.pc.full_service','完整原生角色陪伴服务','role','pc_daily','pc_daily_native','native',
  'TLS原生承载原PC角色状态、日记、穿搭、技能、创作、查询、工具与管理能力。',
  ('原PC持久状态与配置副本','明确来源的新角色计划'),('原PC唯一执行者退休','真实SDK事件与人格选择','现有统一发送'),
  ('server-integration/status','pc-daily-native/status'),('astrbot_plugin_private_companion',),'full_runtime',
  '保留原全局历史与未决任务；不按旧无归属计划猜用户，也不重启旧随机、便签或日期发送链。'),
 ('tls.pc.virtual_daily','角色日常、日记与穿搭','role','pc_daily','pc_daily_native','native',
  '在实际绑定的会话中准备未来虚构日常，沿成熟业务生成日记、穿搭与角色生活资料。',
  ('当前真实范围的新计划投影','原PC历史保持独立'),('真实私聊来源','实际人格选择','原模型与文件接口'),
  ('pc-daily-native/status','pc-daily-native/generate'),('astrbot_plugin_private_companion',),'native_full_source',
  '角色活动均为虚构证据；历史未迁为新scope，新生成产物与具体用户可见效果仍需实测。'),
 ('tls.personal_goals.automatic','目标自动推进与有来源分享','actions','pc_daily','pc_daily_native','native',
  '真实范围未来计划到时形成角色事件，调用同一目标实例；分享由原统一通道确认后消费。',
  ('同一journal的计划发生与目标收据','持久分享候选映射'),('唯一目标执行者','当前真实会话与来源','原冷却与最终发送许可'),
  ('pc-daily-native/status','pc-daily-native/settings','pc-daily-native/tick'),('astrbot_plugin_private_companion',),'native_source',
  '自动开关、实例、真实来源、旧职责交接分别核对；UNKNOWN不重发，不提前把排队当作已分享。'),
 ('tls.proactive.independent','原生独立主动聊天','interaction','proactive_chat','status','native',
  '原生管理独立主动聊天的会话计划，复用现TLS生成、统一发送和真实平台确认。',
  ('原session_data与会话覆盖配置','现持久投递状态'),('旧独立插件停止','真实会话范围','统一发送许可'),
  ('proactive-chat/status',),('astrbot_plugin_proactive_chat',),'full_runtime',
  '活动宿主与每条任务的来源、排队、确认、等待复核分别展示；不是手机后台推送验收。'),
 ('tls.personal_goals.plan','目标专用日计划','role','scoped_daily_plans','scoped_daily_plan','native',
  '管理未来的角色目标活动，明确完成后通过既有目标实例推进并回读上下文。',
  ('同一原生日志中的新范围计划','原生个人目标'),('完整管理范围','进度写入时的真实当前会话授权'),
  ('scoped-daily-plan/list','scoped-daily-plan/create','scoped-daily-plan/generate',
   'scoped-daily-plan/item/complete','scoped-daily-plan/apply'),
  ('astrbot_plugin_private_companion',),'partial',
  '只接新明确范围的目标计划，不认领旧全局计划，不自动触发时钟或主动分享。'),
 ('tls.phone.service','手机感知与关怀','perception','phone_service','phone_service','native',
  '在TLS内部管理现有PPB连接、设备感知、音乐事实、关怀和历史查询。',
  ('既有PPB上报','原Phone状态与音乐累计'),('现有PPB协议','明确设备和用户归属'),
  ('/astrbot_plugin_virtual_body/phone-integration/connection','/astrbot_plugin_virtual_body/phone-integration/read/state'),('astrbot_plugin_phone_perception',),'native_host',
  '仅在实际原生服务活动后标记运行；设备是否在线、消息是否可见须分别验收。'),
 ('tls.phone.flow','聊天节奏与手动免打扰','interaction','phone_flow','phone_flow','native',
  '原生管理连续短消息、倾听方式、回复长度及会话手动安静。',
  ('原节奏偏好SQLite','冷却和事件记录'),('当前允许的私聊范围','唯一节奏执行者'),
  ('/astrbot_plugin_virtual_body/phone-integration/flow/settings','/astrbot_plugin_virtual_body/phone-integration/flow/session'),('astrbot_plugin_phone_perception',),'native_host',
  '保留既有偏好、冷却和租约；每项主动来源仍须按实际接口接入，未宣称全局统一限流。'),
 ('tls.insight.native','原生数据洞察','system','insight','insight','native',
  '只读查看模型用量、聊天统计、记忆体检、信息聚合和情绪线索。',
  ('AstrBot既有统计与会话','TLS已归属资料'),('后台管理员认证','明确私聊范围'),
  ('insight/overview','insight/usage','insight/chat-pattern','insight/memory','insight/gather','insight/mood'),
  ('astrbot_plugin_insight_center',),'native_host',
  '管理员历史查询不建立聊天权限；有界统计与推断不当事实，来源不可用不填伪零。'),
 ('tls.core_memory.manage','对话维护核心约定','memory','core_tools','memory','native',
  '在已交权的完整私聊范围维护TLS工具整理约定；材料不是用户原话或事实确认。',
  ('TLS工具来源的核心约定与请求收据',),('真实会话授权','已关闭的旧工具门禁','准确归属修订'),
  ('core-tools/status',),('astrbot_plugin_memory_companion',),'partial',
  '只接已交权范围的新工具资料；旧历史召回保留，旧工具全局开关交接须另行核验。'),
 ('tls.proactive.random','随机主动陪伴','interaction','proactive','phone','native',
  '按当前频率生成克制短句和一张新图，进入原生投递链。',
  ('原生任务与投递记录',),('原生记忆','统一上下文','AstrBot 模型与平台适配器'),
  ('console/overview',),('astrbot_plugin_private_companion',),'partial',
  '仅接管配置会话中的随机来源；PC 非随机与独立主动聊天仍保留。'),
 ('tls.phone.app_entry','打开 App 后互动','interaction','phone_companion','phone','native',
  '使用真实 App 事件、本地或自定义短句及一张新图。',
  ('手机观察投影','App 规则','原生任务'),('PPB 手机协议适配器','原生投递'),
  ('phone/state','phone/config','app-rules/config'),('astrbot_plugin_phone_perception',),'partial',
  '仅 App 入场业务迁入 TLS，采集协议及音乐映射仍保留。'),
 ('tls.expression.feedback','表达反馈学习','interaction','expression','expression','native',
  '把明确措辞反馈保存为可编辑、可撤回规则。',('表达规则',),('统一上下文',),
  ('expression/list',),(),'native_host','显式反馈学习；不宣称自主无限自学习。'),
 ('tls.expression.assets','表情与图片素材','interaction','expression_assets','assets','native',
  '维护人工图片与标签，QQ 普通私聊回复后可独立发送一张表情，遵守冷却和去重。',('人工图片与标签',),('AstrBot 回复组件',),
  ('assets/list',),(),'native_host','空素材库不发图；用户尚未提供的表情不虚构。'),
 ('tls.memory.manage','原生记忆管理','memory','memory','memory','native',
  '管理明确归属的记忆，支持搜索、修正、删除与版本化恢复。',('原生记忆与修订记录',),(),
  ('memory/list','memory/add','memory/correct','memory/delete','memory/restore'),
  ('astrbot_plugin_memory_companion',),'partial','不等同于旧自动画像、总结、向量或图谱整体替代。'),
 ('tls.memory.transfer','资料导入与导出','memory','memory_transfer','data','native',
  '预览文本、JSON、CSV 后明确确认导入，按当前范围分页导出。',('同一原生记忆库','导入幂等收据'),
  ('原生记忆管理',),('memory-transfer/preview','memory-transfer/import','memory-transfer/export'),
  ('astrbot_plugin_memory_companion',),'partial','人工材料保持来源标签，不冒充用户亲口陈述或传感事实。'),
 ('tls.history.review','旧资料审阅与收录','memory','history','history','native',
  '只读审阅旧档案，人工确认归属后逐条收录。',('只读历史档案','原生记忆'),('人工归属确认',),
  ('history/stats','history-adoption/preview'),('astrbot_plugin_memory_companion',),'partial',
  '缺少 persona 的记录不自动猜测归属，原档案不改。'),
 ('tls.personal.materials','长期约定','memory','memory','personal','native',
  '手动维护自己的长期约定，编辑、停用、归档恢复、只读预览确认导入与分页导出。',
  ('同一原生记忆库中的TLS自有约定',),('当前真实会话授权','私人统一上下文'),
  ('personal-materials/list','personal-materials/create','personal-materials/update','personal-materials/archive','personal-materials/restore','personal-materials/export','personal-materials/import/preview','personal-materials/import/confirm','personal-materials/export-batch'),
  ('astrbot_plugin_memory_companion',),'partial',
  '仅自有人工长期约定；不导入旧MC核心或画像，不等于自动记忆整体替代，实际LLM使用单独观察。'),
 ('tls.memory.capture','原生自动捕获','memory','memory','','native',
  '只有显式启用且范围授权有效时才捕获新的事件。',('原生记忆',),('原生记忆管理','有效会话授权'),
  (),('astrbot_plugin_memory_companion',),'partial','关闭该功能不关闭人工记忆；不接管旧 MC 的全部自动路径。'),
 ('tls.memory.explicit_capture','明确记住与承诺提取','memory','memory','memory','native',
  '在真实授权范围内，把原分类器已确认的明确记住或承诺交给TLS原生记忆保存。',
  ('当前明确语句的原始来源','同一原生记忆库'),('实际两槽交接实例','当前完整私聊授权','独立写入门禁'),
  ('memory/list','memory/search'),('astrbot_plugin_memory_companion',),'partial',
  '仅接管明确记住与承诺提取；画像、总结和其他旧捕获职责保留。挂载与授权不代表本次已写入，实际写入仍逐事件复核。'),
 ('tls.memory.relationship_statement','关系表达记忆','memory','memory','memory','native',
  '保存用户原文中的关系态度与所指对象，作为未经核实的个人陈述供当前授权范围检索。',
  ('用户原文关系表达','同一原生记忆库'),('实际两槽交接实例','独立关系分支','当前完整私聊授权'),
  ('memory/list','memory/search'),('astrbot_plugin_memory_companion',),'partial',
  '只保存用户关系表达，不把陈述当已核实关系事实；不更新关系评分、图谱或画像，不等于整个MC关系系统替代。'),
 ('tls.memory.profile_candidates','画像候选与审核','memory','profile_candidates','profile_candidates','native',
  '查看原始证据、候选原因、审核及单值替代；只有真正生效的画像进入上下文。',
  ('同库画像候选与证据','实际审核来源'),('原生记忆库','当前管理范围'),
  ('profile-candidates/list','profile-candidates/detail','profile-candidates/approve','profile-candidates/reject'),
  ('astrbot_plugin_memory_companion',),'partial','只管理TLS新画像候选，不猜迁旧画像归属。'),
 ('tls.memory.profile_capture','新入站画像候选','memory','profile_candidates','profile_candidates','native',
  '把实际选定的新画像交给同库证据、审核和质量晋升；不是普通manual记忆。',
  ('当前真实入站','实际分类器多画像结果'),('当前完整范围授权','独立画像执行权'),
  (),('astrbot_plugin_memory_companion',),'partial','旧历史画像、原始时间线、portrait及摘要仍有保留职责。'),
 ('tls.memory.summary_algorithm','记忆摘要算法','system','memory_summary','mc_summary','native',
  '沿用原时间线、模型选择和存储，只把当前MC摘要算法实例交给TLS原生实现。',
  ('旧MC摘要输入与原参数',),('准确运行实例','固定来源与已排空的摘要调用'),
  ('server-integration/mc/summary/status','server-integration/mc/summary/inspect',
   'server-integration/mc/summary/activate','server-integration/mc/summary/restore'),
  ('astrbot_plugin_memory_companion',),'partial',
  '默认关闭，须明确交接；摘要worker、时间线、provider、旧库和audit静态调用仍保留原实现。'),
 ('legacy.memory.automatic','旧自动记忆与画像','memory','','','legacy',
  '旧自动捕获、画像、核心记忆、总结及既有桥仍保留原实现。',('旧记忆数据',),
  ('原记忆插件',),(),('astrbot_plugin_memory_companion',),'none','责任来自既有迁移矩阵，未由本投影验证其当前进程状态。'),
 ('tls.presence.read','环境状态融合','perception','presence','presence','native',
  '汇总已登记且仍有效的感知状态，不另开采集器。',('Presence 有效状态与有效期',),
  ('已注册感知来源',),('presence/overview',),('astrbot_plugin_phone_perception',),'partial',
  '已注册来源不等于设备当前在线或音乐正在播放。'),
 ('adapter.phone.protocol','手机与音乐协议','perception','','phone','external_adapter',
  '保留手机上报、音乐识别与设备协议连接。',('外部观察的有效投影',),('PPB 与手机端',),
  ('phone/state',),('astrbot_plugin_phone_perception',),'partial','采集协议仍为轻适配器；此页不轮询设备或证明手机可见。'),
 ('tls.media.resolve','音乐曲库精确解析','perception','music_resolver','sources','native',
  '原生读取本地曲库，规范化标题歌手、识别唯一匹配和歧义，不推断正在播放。',
  ('既有只读音乐索引',),('目录读取授权',),('console/overview',),
  ('astrbot_plugin_phone_perception',),'partial',
  'TLS目录链已不依赖旧解析类；旧手机播放provider和采集协议仍保留。'),
 ('tls.music.library.manage','音乐资料库','perception','music_library','music_library','native',
  '维护音乐元数据、标签、版本、归档和导入导出，并预览当前原生匹配结果。',('TLS 原生日志内的音乐资料',),('原生曲目匹配器','后台管理员与明确资料归属'),
  ('music-library/list','music-library/detail','music-library/create','music-library/update',
   'music-library/archive','music-library/restore','music-library/export','music-library/match',
   'music-library/import/preview','music-library/import/confirm'),
  ('astrbot_plugin_phone_perception',),'partial','仅接管手动音乐资料维护与匹配；手机实时播放来源、旧播放累计和自动目录写入仍保留。'),
 ('tls.media.catalog','其他媒体与书籍资料','perception','','','not_implemented',
  '其他媒体、书籍和视频资料尚未完整迁入；音乐维护使用独立原生资料库入口。',('既有媒体索引',),('旧媒体来源',),(),
  ('astrbot_plugin_phone_perception','astrbot_plugin_bookshelf'),'none','音乐元数据维护不代表通用媒体资料 CRUD 或真实播放来源已替代。'),
 ('tls.personal_goals.manage','个人目标资料与手动进度','role','personal_goals','personal_goals','native',
  '管理角色自己的生活、学习与习惯目标，手动更新进度、核对来源和预览导入。',
  ('当前完整范围的TLS个人目标定义','手动进度记录与导入收据'),('后台管理员认证','明确完整资料范围'),
  ('personal-goals/list','personal-goals/detail','personal-goals/create','personal-goals/update',
   'personal-goals/pause','personal-goals/resume','personal-goals/complete','personal-goals/abandon',
   'personal-goals/archive','personal-goals/restore','personal-goals/export','personal-goals/search',
   'personal-goals/import/preview','personal-goals/import/confirm'),
  ('astrbot_plugin_private_companion',),'partial',
  '仅原生资料管理、来源和手动进度；活动自动推进、主动分享待旧职责交接，旧PC原目标和消费者不自动切换。'),
 ('tls.narrative.context','剧情与互动偏好','role','narrative','narrative','native',
  '管理虚构场景、线索与明确偏好，保持核心人格。',('剧情与偏好记录',),('统一上下文',),
  ('narrative/state',),(),'native_host','虚构剧情与真实生活证据分开。'),
 ('tls.body.state','身体状态','role','body','body','native',
  '读取和调整角色身体状态。',('身体状态',),(),('overview',),(),'native_host','按当前模块开关运行。'),
 ('tls.space.state','庄园与空间','role','space','space','native',
  '维护庄园、房间、物件与空间状态。',('庄园配置与空间状态',),(),('manor/overview',),(),'native_host','本地原生空间引擎，不需要旧插件转发。'),
 ('tls.mood.state','心绪状态','role','mood','mood','native',
  '维护心绪规则、信号与角色状态。',('心绪状态与规则',),(),('mood/rules',),(),'native_host','角色心绪不等同于推断用户真实情绪。'),
 ('tls.agenda.once','一次性日程','actions','agenda','agenda','native',
  '维护明确时间的一次性日程与版本化取消、恢复。',('原生日程与发生记录',),('原生提醒调度',),
  ('agenda/list','agenda/create','agenda/update','agenda/cancel'),('astrbot_plugin_private_companion','astrbot_plugin_notepad'),'partial',
  '周期日程和原始便签完成接口仍未整体接管。'),
 ('tls.important_dates.manage','重要日期与纪念日','actions','important_dates','important-dates','native',
  '管理员维护明确归属的日期定义，按实际时区投影未来日期并接入统一上下文。',
  ('同一journal中的TLS自有日期定义','人工归属的导入收据'),('管理员资料权限','自动读取仍需真实会话授权'),
  ('important-dates/list','important-dates/detail','important-dates/create','important-dates/update','important-dates/archive','important-dates/restore','important-dates/export','important-dates/import/preview','important-dates/import/confirm'),
  ('astrbot_plugin_private_companion',),'partial',
  '实现结构化资料管理与未来日期投影；旧PC记录不自动迁入，旧日期consumer与发送仍保留。'),
 ('tls.reminders.once','明确提醒调度','actions','reminders','tasks','native',
  '将明确的一次性提醒送入持久化队列。',('提醒发生记录与任务账本',),('有效授权','AstrBot 平台适配器'),
  ('console/tasks','console/tasks/cancel'),('astrbot_plugin_private_companion',),'partial','不导入或重放旧在途任务。'),
 ('tls.delivery.native','统一调度与发送','actions','delivery','tasks','native',
  '处理原生任务认领、许可、队列、发送确认和不确定结果。',('任务、租约与投递审计',),
  ('AstrBot 平台适配器',),('console/tasks',),('astrbot_plugin_private_companion',),'partial',
  '平台确认不是手机可见；UNKNOWN 不无条件重发。'),
 ('legacy.pc.nonrandom','原 PC 非随机业务','actions','','','legacy',
  '原聊天、RP、便签、定时器、维护及非随机主动来源继续保留。',('原 PC 业务数据',),('原 PC 插件',),(),
  ('astrbot_plugin_private_companion',),'none','随机来源窄切不关闭这些职责，也不将全局每日上限设为零。'),
 ('legacy.proactive_chat','独立主动聊天','actions','','','legacy',
  '独立主动事件、日程、工具及平台桥仍由原插件负责。',('原主动聊天数据',),('独立主动插件',),(),
  ('astrbot_plugin_proactive_chat',),'none','未在此处验证其当前启用状态，不等同于 PC 随机源。'),
 ('tls.memo.manage','便签与待办','actions','memo_notes','memo_notes','native',
  '维护明确归属的便签与待办，支持聊天整理一次性无提醒便签；聊天执行须具备当前真实会话与持久归属。',
  ('TLS原生便签资料与修订',),('LivingJournal','统一上下文'),
  ('memo-notes/list','memo-notes/detail','memo-notes/request','memo-notes/create','memo-notes/update',
   'memo-notes/complete','memo-notes/reopen','memo-notes/archive','memo-notes/restore',
   'memo-notes/import/preview','memo-notes/import/confirm','memo-notes/export','memo-tools/status'),
  ('astrbot_plugin_private_companion',),'partial','原生资料完成不等于旧PC原记录已完成；循环推进、真实提醒与旧消费者仍保留。'),
 ('tls.agenda.recurring','周期日程','actions','agenda','agenda','native',
  '日、周、月、年规则复用原提醒服务；确认或过期后推进，未知和失败保留待核对。',('TLS日程与修订',),('原生提醒','统一发送'),
  ('agenda/list','agenda/create','agenda/update','agenda/cancel','agenda/restore'),
  ('astrbot_plugin_private_companion',),'native_host','明确时区；月底和闰日保留日期锚点，没有第二调度器。'),
 ('tls.memo.recurring','周期便签完成与下一次','actions','memo_notes','memo_notes','native',
  '按真实范围与显式执行绑定完成本次，沿现有周期推进器安排下一次。',('TLS便签及执行绑定',),('原生提醒',),
  ('pc-integration/memo/bind','pc-integration/memo/complete'),('astrbot_plugin_private_companion',),'native_host','不自动领取旧待发或未知记录。'),
 ('tls.special_occasions','课表、生日与节日','actions','important_dates','special_occasions','native',
  '维护现有用户课表、生日和节日，课前及当天理由进入同一原生主动消息链。',('PC现有用户资料',),('原生PC','原生主动通道'),
  ('special-occasions/settings','special-occasions/save','chat/occasions'),(),'native_host','配置读取不制造真实会话授权，普通主动仍受配额、冷却与免打扰控制。'),
 ('tls.context.preview','统一上下文装配','system','context','status','native',
  '按授权融合相关状态、记忆与剧情，过滤重复信息。',('临时上下文投影',),('CapabilityRegistry','原生记忆','Presence'),
  ('console/overview',),('astrbot_plugin_memory_companion','astrbot_plugin_private_companion'),'partial',
  '不改写核心人格，已挂载不代表所有旧上下文出口已迁移。'),
 ('tls.capabilities.registry','能力注册与诊断','system','context','status','native',
  '使用同一能力注册器显示依赖、代次和运行状态。',('当前注册器内存状态',),('CapabilityRegistry',),
  ('console/overview',),(),'native_host','本页只读；不注册第二套业务或改变执行权。'),
 ('tls.config.console','原生管理与配置','system','','config','native',
  '使用现有 AstrBot 认证读取工作台和有限动态设置。',('现有插件配置',),('AstrBot 后台认证',),
  ('console/config','console/config/save','console/config/inheritance','console/config/inheritance/save'),(),'native_host','三项背景显示参数已支持默认、全局、平台、角色、会话继承；其他权限与配置沿原作用范围。'),
 ('tls.memory.recall','相关记忆检索','memory','memory','memory','native',
  '通过现有注册能力检索当前授权范围中的记忆。',('当前授权记忆',),('原生记忆管理',),
  ('memory/search',),('astrbot_plugin_memory_companion',),'partial','仅表示当前检索出口，不宣称所有旧记忆业务已接管。'),
 ('tls.private_memory.context','自有长期约定上下文（部分）','memory','context','status','native',
  '将TLS自有已启用长期约定限量加入同一临时上下文。',('授权私人资料投影',),('统一上下文',),(),
  ('astrbot_plugin_memory_companion',),'partial','只接TLS自有长期约定，不读取或假装MC来源；旧MC私人profile/corememory提供方尚未原生接入并保留原实现。'),
 ('tls.feature.context','自有日程、日期与待办上下文（部分）','perception','context','status','native',
  '将TLS自有有效日程、日期定义和未完成便签接入同一临时上下文。',('TLS自有日程与日期定义投影',),('原生日程与重要日期','统一上下文'),(),
  ('astrbot_plugin_private_companion',),'partial','只接自有日程、日期与未完成便签；导入的旧便签副本不重复注入，旧PC consumer保留；旧媒体、穿搭完整provider尚未接管，私人profile/corememory仍保留原实现。'),
 ('tls.interaction.strategy','互动模式策略','interaction','context','narrative','native',
  '按明确偏好选择当前互动方式。',('明确互动偏好',),('剧情与偏好',),('narrative/state',),(),
  'native_host','不推断沉默情绪，不另建发送任务。'),
 ('tls.material.diagnostics','资料体检','system','memory','maintenance','native',
  '只读查看当前授权资料的数量、软删、来源、重复候选和引用可用性。',
  ('当前范围原生记忆','独立管理员历史档案样本'),('真实当前会话授权','现有资料存储'),
  ('material-maintenance/preview',),('astrbot_plugin_insight_center',),'partial',
  '接管TLS自有资料体检入口；去重候选和引用是原生增强，不修复、不清库、不等于完整维护中心。'),
 ('tls.maintenance.full','资料备份与维护','system','memory','maintenance','native',
  '当前授权资料的分页逻辑备份、追加恢复、普通记忆多选软归档与恢复，以及可确证的派生索引修复。',('原生记忆','长期约定','只读目标定义'),('同一资料管理器','LivingJournal'),
  ('material-maintenance/status','material-maintenance/records','material-maintenance/bulk/preview','material-maintenance/bulk/confirm','material-maintenance/export','material-maintenance/restore/preview','material-maintenance/restore/confirm','material-maintenance/repair/preview','material-maintenance/repair/confirm','material-maintenance/receipt'),(),
  'native_host','不是整机或跨库原子快照；不回放进度、发送账本、任务、租约或UNKNOWN。'),
)

IMPLEMENTATION_LOCATIONS = {
 'tls.memory.full_service':['core/living/native_mc_full_owner.py:NativeMCFullOwner','core/living/native_mc/host_adapter.py:NativeMemoryCompanion'],
 'tls.pc.full_service':['core/living/native_pc_full_owner.py:NativePCFullOwner','core/living/native_pc_service.py:NativePCService'],
 'tls.pc.virtual_daily':['core/living/native_pc_service.py:NativePCService','core/living/native_pc_business/daily_state.py:DailyStateMixin'],
 'tls.personal_goals.automatic':['core/living/native_pc_daily_lifecycle.py:NativePCDailyLifecycle','core/living/native_personal_goals.py:NativePersonalGoals'],
 'tls.proactive.independent':['core/living/native_proactive_chat_host.py:NativeProactiveChatHost'],
 'tls.personal_goals.plan':['core/living/native_scoped_daily_plan.py:NativeScopedDailyPlans','scoped_daily_plan_web_api.py:NativeScopedDailyPlanWebApi'],
 'tls.personal_goals.manage':['core/living/native_personal_goals.py:NativePersonalGoals','personal_goals_web_api.py:NativePersonalGoalsWebApi'],
 'tls.phone.service':['core/living/native_phone_service/runtime.py:NativePhoneService','core/living/native_phone_integration_device.py:NativePhoneIntegration'],
 'tls.phone.flow':['core/living/native_phone_flow/runtime.py:NativePhoneFlow','core/living/native_phone_flow/store.py:PreferenceStore'],
 'tls.insight.native':['core/living/native_insight_center.py:NativeInsightCenter','insight_web_api.py:NativeInsightWebApi'],
 'tls.core_memory.manage':['main.py:VirtualBodyPlugin.tls_core_memory','core/living/native_core_tools.py:NativeCoreTools','core/living/native_core_handoff.py:capture_core_handoff'],
 'tls.memo.manage':['core/living/native_memo_notes.py:NativeMemoNotes','memo_notes_web_api.py:NativeMemoNotesWebApi'],
 'tls.music.library.manage':['core/living/native_music_library.py:NativeMusicLibrary','music_library_web_api.py:NativeMusicLibraryWebApi'],
 'tls.media.resolve':['core/living/native_music_catalog.py:NativeMusicCatalog','core/living/connectors.py:MusicCatalogConnector','core/living/coordinator.py:CatalogCoordinator'],
 'tls.proactive.random':['core/living/native_proactive_companion.py:NativeProactiveCompanion.tick','core/living/native_proactive_generation.py:NativeProactiveGeneration.generate'],
 'tls.phone.app_entry':['core/living/native_phone_companion.py:NativePhoneCompanion.tick','core/living/native_phone_messages.py:NativePhoneMessages'],
 'tls.expression.feedback':['core/living/native_expression_learning.py:NativeExpressionLearning'],
 'tls.expression.assets':['core/living/native_expression_assets.py:NativeExpressionAssets'],
 'tls.memory.manage':['core/living/native_memory.py:NativeMemoryStore','memory_web_api.py:NativeMemoryWebApi'],
 'tls.personal.materials':['core/living/native_personal_materials.py:NativePersonalMaterials','personal_materials_web_api.py:NativePersonalMaterialsWebApi'],
 'tls.memory.transfer':['core/living/native_memory_transfer.py:NativeMemoryTransfer','memory_transfer_web_api.py:NativeMemoryTransferWebApi'],
 'tls.history.review':['core/living/native_history_archive.py:NativeHistoryArchive','core/living/native_history_adoption.py:NativeHistoryAdoption'],
 'tls.memory.capture':['core/living/native_memory_adapter.py:NativeMemoryAdapter.capture_event'],
 'tls.memory.explicit_capture':['core/living/native_explicit_memory.py:NativeExplicitMemory',
     'core/living/native_mc_explicit_fence.py:NativeMCExplicitFence',
     'core/living/native_mc_takeover_runtime.py:NativeMCTakeoverRuntime'],
 'tls.memory.relationship_statement':['core/living/native_explicit_memory.py:NativeExplicitMemory',
     'core/living/native_mc_explicit_fence.py:NativeMCExplicitFence',
     'core/living/native_mc_takeover_runtime.py:NativeMCTakeoverRuntime'],
 'tls.memory.profile_candidates':['core/living/native_profile_candidates.py:NativeProfileCandidates','profile_candidates_web_api.py:NativeProfileCandidatesWebApi'],
 'tls.memory.profile_capture':['core/living/native_profile_capture.py:NativeProfileCapture','core/living/native_mc_explicit_fence.py:NativeMCExplicitFence'],
 'tls.memory.summary_algorithm':['core/living/native_memory_summarizer.py:NativeMemorySummarizer',
     'core/living/native_mc_summary_algorithm.py:NativeMCSummaryAlgorithm',
     'core/living/native_mc_takeover_runtime.py:NativeMCTakeoverRuntime'],
 'legacy.memory.automatic':['astrbot_plugin_memory_companion/main.py（既有迁移矩阵；当前仅观察实例启停）'],
 'tls.presence.read':['core/presence.py:PresenceLayer.read','core/living/unified_system.py:UnifiedSystem._read_presence'],
 'adapter.phone.protocol':['phone_web_api.py:NativePhoneWebApi（TLS已接入的只读观察出口）','astrbot_plugin_phone_perception/main.py（协议仍属外部适配器）'],
 'tls.narrative.context':['core/living/narrative.py:NarrativeStore','narrative_web_api.py:NativeNarrativeWebApi'],
 'tls.body.state':['core/state.py:StateStore'],
 'tls.space.state':['core/store.py:ManorStore'],
 'tls.mood.state':['core/mood_engine.py:evaluate','core/mood_store.py:save_triggers'],
 'tls.agenda.once':['core/living/native_agenda.py:NativeAgenda','agenda_web_api.py:NativeAgendaWebApi'],
 'tls.important_dates.manage':['core/living/native_important_dates.py:NativeImportantDates','important_dates_web_api.py:NativeImportantDatesWebApi'],
 'tls.reminders.once':['core/living/reminders.py:ReminderService'],
 'tls.delivery.native':['core/living/delivery_scheduler.py:NativeScheduler','core/living/delivery_sender.py:NativeSender.deliver'],
 'legacy.pc.nonrandom':['astrbot_plugin_private_companion/daily_state.py（仅随机源窄切，非随机保留）'],
 'legacy.proactive_chat':['astrbot_plugin_proactive_chat/main.py（既有迁移矩阵；当前仅观察实例启停）'],
 'tls.context.preview':['core/living/unified_system.py:UnifiedSystem','core/living/context_engine.py:ContextAssembler'],
 'tls.capabilities.registry':['core/living/capability_registry.py:CapabilityRegistry.status_snapshot'],
 'tls.material.diagnostics':['core/living/native_material_diagnostics.py:NativeMaterialDiagnostics.preview','material_maintenance_web_api.py:NativeMaterialMaintenanceWebApi.preview'],
 'tls.config.console':['console_web_api.py:NativeConsoleWebApi'],
 'tls.memory.recall':['core/living/unified_system.py:UnifiedSystem._recall','core/living/native_memory_adapter.py:NativeMemoryAdapter.recall'],
 'tls.private_memory.context':['core/living/unified_system.py:UnifiedSystem._read_private_context'],
 'tls.feature.context':['core/living/unified_system.py:UnifiedSystem._read_feature_context'],
 'tls.interaction.strategy':['core/living/unified_system.py:UnifiedSystem._strategy'],
}

TEST_ENTRIES = {
 'tls.personal_goals.manage':'tests.test_personal_goals_console_r51',
 'tls.phone.service':'tests.test_native_phone_service',
 'tls.phone.flow':'tests.test_native_phone_flow',
 'tls.insight.native':'tests.test_native_insight_center',
 'tls.core_memory.manage':'tests.test_native_core_tools',
 'tls.media.resolve':'tests.test_native_music_catalog_flow',
 'tls.music.library.manage':'tests.test_native_music_library_web_api',
 'tls.memo.manage':'tests.test_native_memo_notes_web_api',
 'tls.proactive.random':'tests.test_native_proactive_companion',
 'tls.phone.app_entry':'tests.test_native_phone_companion',
 'tls.expression.feedback':'tests.test_native_expression_learning',
 'tls.expression.assets':'tests.test_native_expression_assets',
 'tls.memory.manage':'tests.test_native_memory_store',
 'tls.memory.transfer':'tests.test_native_memory_transfer_web_api',
 'tls.history.review':'tests.test_native_history_adoption_web_api',
 'tls.memory.capture':'tests.test_native_memory_chat',
 'tls.memory.explicit_capture':'tests.test_native_explicit_memory_capability_r53',
 'tls.memory.relationship_statement':'tests.test_native_relationship_capability_r54',
 'adapter.phone.protocol':'tests.test_native_phone_web_api',
 'tls.body.state':'tests.test_core_quality',
 'tls.space.state':'tests.test_manor_floor_hub_save',
 'tls.mood.state':'tests.test_mood',
 'tls.agenda.once':'tests.test_native_agenda_web_api',
 'tls.important_dates.manage':'tests.test_native_important_dates_host_integration',
 'tls.reminders.once':'tests.test_stage9_reminders',
 'tls.delivery.native':'tests.test_living_delivery_scheduler',
 'tls.capabilities.registry':'tests.test_living_capability_registry',
 'tls.config.console':'tests.test_native_console_api',
 'tls.material.diagnostics':'tests.test_native_material_maintenance_web_api',
 'tls.personal.materials':'tests.test_native_personal_materials_web_api',
}

_LABELS = {'source_unavailable':'曲库读取异常','implemented':'已实现，尚未运行','unknown':'当前状态待核验','disabled':'已关闭','ready':'运行时已挂载',
    'warming':'过渡等待中','awaiting_scope':'等待真实会话授权','legacy_scope':'原实现仍挂载',
    'unavailable':'运行时未挂载','not_implemented':'尚未完整实现','native_full':'TLS原生运行',
    'preparing':'准备或交接中','blocked':'存在未解决阻塞'}
_IMPLEMENTATIONS = {'native':'TLS 原生业务','legacy':'原插件业务',
    'external_adapter':'外部协议适配器','not_implemented':'待迁移能力'}


def build_capability_catalog(*, modules=(), registry_snapshot=None, flags=None,
        presence=None, proactive=None, random_handoff=None, scope_available=False,
        authenticated=False, legacy_plugins=None, core_tools=None, scope_selected=False,
        explicit_memory=None, relationship_memory=None,profile_memory=None,summary_algorithm=None,
        mc_full=None,pc_full=None,pc_daily=None,independent_proactive=None):
    """Project bounded facts; ready/configured never means a delivered message."""
    modules = {row.get('id'): row for row in (modules if isinstance(modules,(list,tuple)) else ())[:64] if isinstance(row, dict)}
    flags = flags if isinstance(flags, dict) else {}
    presence = presence if isinstance(presence, dict) else {}
    proactive = proactive if isinstance(proactive, dict) else {}
    registry_snapshot = registry_snapshot if isinstance(registry_snapshot, dict) else {}
    registered = {row.get('capability_id'):row for row in (registry_snapshot.get('entries') or [])[:128]
        if isinstance(row,dict) and isinstance(row.get('capability_id'),str)}
    runtime = proactive.get('runtime'); runtime = runtime if isinstance(runtime,dict) else {}
    legacy = proactive.get('legacy'); legacy = legacy if isinstance(legacy,dict) else {}
    random_handoff = random_handoff if isinstance(random_handoff,dict) else {}
    legacy_plugins = legacy_plugins if isinstance(legacy_plugins,dict) else {}
    core_tools = core_tools if isinstance(core_tools,dict) else {}
    explicit_memory = explicit_memory if isinstance(explicit_memory,dict) else {}
    relationship_memory = relationship_memory if isinstance(relationship_memory,dict) else {}
    profile_memory=profile_memory if isinstance(profile_memory,dict) else {}
    summary_algorithm=summary_algorithm if isinstance(summary_algorithm,dict) else {}
    mc_full=mc_full if isinstance(mc_full,dict) else {}
    pc_full=pc_full if isinstance(pc_full,dict) else {}
    pc_daily=pc_daily if isinstance(pc_daily,dict) else {}
    independent_proactive=independent_proactive if isinstance(independent_proactive,dict) else {}
    def legacy_plugin_active(name):
        old=legacy_plugins.get(name) or {}
        return old.get('activated') if old.get('loaded') is True and type(old.get('activated')) is bool else None
    def owner_state(value, original, *, requires_scope=False):
        phase=value.get('phase','not_observed')
        active=value.get('active')
        original_off=original is False or value.get('original_plugin_active') is False or value.get('legacy_closed') is True
        if active is True and (original is True or value.get('source_current') is False):return 'blocked'
        if active is True and original_off:
            if requires_scope and not value.get('real_scope_bound'):return 'awaiting_scope'
            return 'native_full'
        if original is True:return 'legacy_scope'
        if value.get('last_error') or phase in {'blocked','turnoff_unknown','restore_unknown','closed_pending','draining'}:return 'blocked'
        if phase in {'preparing','old_admission_closed','draining_original','turning_off_original','prepared','restoring_original'}:return 'preparing'
        if value.get('configured') is False and active is False:return 'disabled'
        return 'implemented' if phase in {'not_requested','inactive','new','not_observed'} else 'unknown'
    result = []
    for identity,label,domain,module,entry,implementation,purpose,data,deps,api,refs,replacement,detail in CATALOG:
        row = dict(id=identity,label=label,purpose=purpose,domain=domain,entry=entry,
            implementation=implementation,implementation_label=_IMPLEMENTATIONS[implementation],
            implementation_location=list(IMPLEMENTATION_LOCATIONS.get(identity,())),
            data=list(data),dependencies=list(deps),api=[path if path.startswith('/astrbot_plugin_virtual_body/')
                 else '/astrbot_plugin_virtual_body/page/'+path for path in api],
            legacy_refs=list(refs),replacement=dict(scope=replacement,whole_plugin_replaced=False,detail=detail),
            detail=detail,registered=identity in registered,enabled=None,runtime_active=None,
            owner='TLS 原生模块' if implementation=='native' else '原插件（职责参考）' if implementation=='legacy'
                else '外部协议适配器' if implementation=='external_adapter' else '尚未完成迁移',
            evidence=[],tests=dict(entry=registered.get(identity,{}).get('test_entry') or TEST_ENTRIES.get(identity),state='not_observed_here'),
            delivery=dict(platform_ack='not_observed_here',phone_visible='not_observed_here'))
        status='unknown'; state=modules.get(module)
        if state is not None:
            row['runtime_active']=state.get('active') if type(state.get('active')) is bool else None
            if row['runtime_active'] is True: status='ready'
            elif row['runtime_active'] is False: status='unavailable'
            row['evidence'].append('当前控制台模块快照')
        spec=registered.get(identity)
        if spec is not None:
            row['enabled']=spec.get('enabled') if type(spec.get('enabled')) is bool else None
            row['registry']= {key:deepcopy(spec.get(key)) for key in
                ('version','generation','health','inflight','successes','failures','dependencies')}
            row['evidence'].append('当前同一 CapabilityRegistry 元数据（不调用能力）')
            if registry_snapshot.get('closed') is True: status='unavailable'
            elif row['enabled'] is False: status='disabled'
        if identity in {'tls.memory.recall','tls.private_memory.context','tls.feature.context',
                'tls.interaction.strategy','tls.context.preview','tls.presence.read','tls.narrative.context'} and spec is None:
            status='unavailable'
        configured_key={'tls.body.state':'vb_enabled','tls.space.state':'sp_enabled',
            'tls.mood.state':'mo_enabled'}.get(identity)
        if configured_key and type(flags.get(configured_key)) is bool:
            row['enabled']=flags[configured_key]
            if row['enabled'] is False: status='disabled'
        if identity=='tls.core_memory.manage':
            row['runtime_active']=core_tools.get('active') if type(core_tools.get('active')) is bool else None
            row['owner_mode']=core_tools.get('owner_mode','unknown')
            row['owner_generation']=core_tools.get('owner_generation')
            row['enabled']=row['owner_mode']=='native' if row['owner_mode'] in {'native','closed'} else None
            status=('unavailable' if row['runtime_active'] is not True else 'disabled' if row['owner_mode']=='closed'
                else 'awaiting_scope' if not scope_available else 'ready' if row['owner_mode']=='native'
                and core_tools.get('scope_allowed') is True and core_tools.get('gate_current') is True else 'unknown')
            row['owner']='TLS准确范围归属；旧工具全局开关须经过受控交接'
            row['evidence']=['当前NativeCoreTools实例、持久化范围归属、当前授权与MC绑定门禁；不由配置猜测']
        elif identity in {'tls.phone.service','tls.phone.flow','tls.insight.native'}:
            old_name='astrbot_plugin_insight_center' if identity=='tls.insight.native' else 'astrbot_plugin_phone_perception'
            old=legacy_plugins.get(old_name) or {}
            old_active=old.get('activated') if old.get('loaded') is True else None
            row['legacy_runtime_active']=old_active if type(old_active) is bool else None
            if row['runtime_active'] is True:
                status='unknown' if old_active is True else 'ready'
                row['owner']='TLS原生服务；旧实例仍活动，需核对职责交接' if old_active is True else 'TLS原生服务'
            elif old_active is True:
                status='legacy_scope';row['owner']='旧实例仍活动；TLS原生服务未运行'
            row['evidence'].append('本次真实原生对象类型与active状态；旧实例仅观察注册表，不由配置推断')
        elif implementation=='not_implemented': status='not_implemented'
        elif identity=='tls.memory.profile_candidates':
            selected=scope_selected is True
            management=authenticated is True and selected and row['runtime_active'] is True
            if row['runtime_active'] is True:status='ready' if management else 'awaiting_scope'
            row['administration']={'available':management,'scope_selected':selected,
                'access':'authenticated_administrator_materials_only'}
            row['runtime_scope_authorized']=scope_available is True if selected else None
            row['owner']='TLS同库画像候选、证据与审核；历史画像和原portrait保留'
        elif identity=='tls.memory.profile_capture':
            active=profile_memory.get('active');installed=profile_memory.get('installed')
            row['runtime_active']=active if type(active) is bool else None
            row['enabled']=row['runtime_active']
            status=('unavailable' if registry_snapshot.get('closed') is True else
                'ready' if active is True and installed is True and scope_selected is True and scope_available is True else
                'awaiting_scope' if active is True and installed is True else 'implemented')
            row['owner']='TLS新真实入站画像候选；旧画像历史、时间线、portrait和总结保留'
        elif identity=='tls.memory.summary_algorithm':
            active=summary_algorithm.get('active');algorithm_active=summary_algorithm.get('algorithm_active')
            row['runtime_active']=active if type(active)is bool else None
            row['enabled']=summary_algorithm.get('configured') if type(summary_algorithm.get('configured'))is bool else None
            row['algorithm_owner']=('TLS原生算法' if algorithm_active is True else
                '旧MC算法' if summary_algorithm.get('owner')=='original_algorithm'
                or summary_algorithm.get('phase')=='disabled' else '待核对')
            row['recovery_required']=summary_algorithm.get('recovery_required')is True
            row['source_current']=summary_algorithm.get('source_current')is True
            status=('unavailable' if registry_snapshot.get('closed')is True else
                'unknown' if row['recovery_required'] else 'ready' if active is True
                and row['source_current'] else 'legacy_scope' if algorithm_active is False
                else 'implemented')
            row['owner']=row['algorithm_owner']+'；旧MC继续拥有时间线、模型选择、存储和摘要worker'
            row['evidence']=['实际算法指针、所属控制器、当前MC注册实例和来源校验；不由开关推断，不调用模型或摘要业务']
        elif identity=='tls.personal_goals.plan':
            selected=scope_selected is True
            management=authenticated is True and selected and row['runtime_active']is True
            if row['runtime_active']is True:status='ready' if management else 'awaiting_scope'
            row['administration']={'available':management,'scope_selected':selected,
                'access':'authenticated_administrator_materials_only'}
            row['runtime_scope_authorized']=scope_available is True if selected else None
            row['automatic_progression']={'active':False,'source_hook_installed':False}
            row['proactive_share']={'active':False,'claims_share':False}
            row['owner']='TLS新范围计划及明确虚构完成事件；旧PC全局日常和无归属历史保留'
        elif identity=='tls.personal_goals.manage':
            selected=scope_selected is True
            management=authenticated is True and selected and row['runtime_active'] is True
            if row['runtime_active'] is True:
                status='ready' if management else 'awaiting_scope' if authenticated is True else 'unknown'
            row['administration']={'available':management,'scope_selected':selected,
                'access':'authenticated_administrator_materials_only'}
            row['runtime_scope_authorized']=bool(scope_available) if selected else None
            row['automatic_progression']={'state':'awaiting_legacy_handoff','active':False}
            row['proactive_share']={'state':'awaiting_legacy_handoff','active':False,
                'queued_by_this_projection':False}
            old=legacy_plugins.get('astrbot_plugin_private_companion') or {}
            row['legacy_runtime_active']=old.get('activated') if old.get('loaded') is True and type(old.get('activated')) is bool else None
            row['owner']='TLS原生目标资料与手动进度；旧PC原目标、自动推进与分享职责保留'
            row['evidence'].append('实际NativePersonalGoals活动实例及同一journal挂载；后台资料权限与实时私聊授权分别显示，不调用活动推进或分享消费')
        elif identity=='tls.important_dates.manage':
            if state is None: status='implemented'
            row['owner']='TLS日期定义与未来投影；旧PC日期consumer和发送保留'
            row['evidence'].append('管理员仅管理明确完整范围的资料；自动上下文仍复核真实会话授权')
        elif identity in {'tls.feature.context','tls.private_memory.context'}:
            # Registration and module attachment do not establish a usable private scope.
            # Preserve closed/disabled/unavailable precedence; never invoke the provider here.
            if (spec is not None and row['enabled'] is True
                    and row['runtime_active'] is True
                    and registry_snapshot.get('closed') is not True and not scope_available):
                status='awaiting_scope'
            row['evidence'].append('仅 TLS 自有未来活动日程与日期投影；真实会话授权缺失时不可读')
        elif identity in {'tls.material.diagnostics','tls.personal.materials','tls.maintenance.full'}:
            if row['runtime_active'] is True: status='ready' if scope_available else 'awaiting_scope'
            row['owner']=('TLS自有资料体检' if identity=='tls.material.diagnostics' else
                'TLS同一资料管理器与现有审计回执' if identity=='tls.maintenance.full' else 'TLS自有长期约定管理')
            row['evidence'].append('当前原生记忆挂载与真实会话授权；实际资料结果由各自鉴权API回读')
        elif identity=='tls.media.resolve':
            configured=flags.get('living_exploration_enabled')
            row['enabled']=configured if type(configured) is bool else None
            reader_state=state.get('reader_state') if state is not None else 'not_attached'
            row['reader_state']=reader_state if reader_state in {'empty','ready','missing','unavailable','not_attached'} else 'unknown'
            status=('disabled' if configured is False
                else 'source_unavailable' if state is not None and state.get('native_backend') is True and row['reader_state'] in {'missing','unavailable'}
                else 'awaiting_scope' if configured is True and not scope_available
                else 'ready' if state is not None and state.get('active') is True and state.get('native_backend') is True
                else 'implemented')
            row['owner']='TLS目录解析；手机播放provider仍由原适配器负责'
            row['evidence'].append('当前宿主coordinator和NativeMusicCatalog实例类型；不读文件、不推断播放')
        elif identity=='tls.memory.explicit_capture':
            active=explicit_memory.get('active')
            row['runtime_active']=active if type(active) is bool else None
            row['enabled']=row['runtime_active']
            full_scope=scope_selected is True and scope_available is True
            row['runtime_scope_authorized']=full_scope
            status=('unavailable' if registry_snapshot.get('closed') is True
                else 'ready' if row['runtime_active'] is True and full_scope
                else 'awaiting_scope' if row['runtime_active'] is True
                else 'unavailable' if row['runtime_active'] is False else 'unknown')
            row['owner']='TLS明确记住与承诺提取；旧画像、总结及其他捕获职责保留'
            row['evidence']=['实际NativeMCTakeoverRuntime.explicit两槽交接状态和当前完整范围授权；不由配置开关推断，也不调用捕获业务']
        elif identity=='tls.memory.relationship_statement':
            active=relationship_memory.get('active'); installed=relationship_memory.get('installed')
            row['runtime_active']=active if type(active) is bool else None
            row['runtime_installed']=installed if type(installed) is bool else None
            row['enabled']=row['runtime_active']
            full_scope=scope_selected is True and scope_available is True
            row['runtime_scope_authorized']=full_scope
            status=('unavailable' if registry_snapshot.get('closed') is True
                or row['runtime_installed'] is False or row['runtime_active'] is False
                else 'unknown' if row['runtime_installed'] is not True or row['runtime_active'] is not True
                else 'ready' if full_scope else 'awaiting_scope')
            row['owner']='TLS关系表达原文记忆；旧关系评分、图谱和画像职责保留'
            row['evidence']=['实际NativeMCTakeoverRuntime.relationship分支的installed/active状态及完整范围授权；不凭配置推断，不调用捕获或评分业务']
        elif identity=='tls.memory.capture':
            configured=flags.get('living_memory_capture_enabled')
            row['enabled']=configured if type(configured) is bool else None
            status='disabled' if configured is False else 'awaiting_scope' if configured is True and not scope_available else 'ready' if configured is True and row['runtime_active'] else 'unknown'
            row['evidence'].append('当前捕获开关；旧 MC 自动路径独立保留')
        elif identity=='tls.proactive.random':
            configured=proactive.get('configured')
            row['enabled']=configured if type(configured) is bool else None
            row['runtime_active']=runtime.get('active') if type(runtime.get('active')) is bool else None
            if configured is False: status='disabled'
            elif configured is not True or row['runtime_active'] is not True: status='unknown'
            elif runtime.get('transition_active') is True: status='warming'
            elif not scope_available: status='awaiting_scope'
            elif random_handoff.get('random_gate_confirmed') is True and random_handoff.get('state')=='quiescent_observed': status='ready'
            else: status='unknown'
            row['owner']='TLS 原生已挂载；随机执行归属仍需当前范围门禁核验'
            row['evidence']=['当前原生陪伴诊断','当前事件循环中的随机来源交接观察；缺失即未知']
            row['ownership_observed']=bool(configured is True and row['runtime_active'] is True
                and runtime.get('transition_active') is False
                and random_handoff.get('random_gate_confirmed') is True
                and random_handoff.get('state')=='quiescent_observed' and scope_available)
        elif identity=='tls.phone.app_entry':
            row['owner']='TLS 原生 + PPB 协议协同；旧入场归属未实时核验'
            configured=flags.get('living_phone_companion_enabled')
            row['enabled']=configured if type(configured) is bool else None
            if configured is False: status='disabled'
            elif row['runtime_active'] is True: status='ready' if scope_available else 'awaiting_scope'
        elif identity in {'legacy.memory.automatic','legacy.proactive_chat'}:
            plugin_name='astrbot_plugin_memory_companion' if identity=='legacy.memory.automatic' else 'astrbot_plugin_proactive_chat'
            observed=legacy_plugins.get(plugin_name) or {}
            if observed.get('loaded') is True:
                row['runtime_active']=observed.get('activated') if type(observed.get('activated')) is bool else None
                status='legacy_scope' if row['runtime_active'] is True else 'disabled' if row['runtime_active'] is False else 'unknown'
                row['evidence'].append('当前 AstrBot 插件注册表；仅证明实例启停，不证明每项业务已执行')
        elif identity=='legacy.pc.nonrandom':
            row['runtime_active']=legacy.get('loaded') if type(legacy.get('loaded')) is bool else None
            if row['runtime_active'] is True:
                status='legacy_scope';row['evidence'].append('当前旧 PC 加载实例观察；不推断每项业务正在执行')
                legacy_runtime=legacy.get('runtime') or {}
                if legacy_runtime.get('enabled') is False: status='disabled'
        elif identity=='adapter.phone.protocol':
            sources=presence.get('sources',[])
            count=sum(isinstance(source,dict) and source.get('enabled') is True
                and any(str(domain).startswith(('device.','music')) for domain in (source.get('domains') or [])) for source in sources)
            row['registered_source_count']=count
            row['evidence'].append('当前 Presence 来源登记；不检查设备连接')
            if count: status='unknown'
            row['connection_status']='not_observed_here'
        elif identity=='tls.capabilities.registry':
            status='unavailable' if registry_snapshot.get('closed') is True else 'ready' if registry_snapshot.get('closed') is False else 'unknown'
            row['evidence'].append('当前同一注册器只读状态')
        elif identity=='tls.config.console':
            status='ready' if authenticated else 'unknown'
            row['evidence'].append('本次请求已通过现有 AstrBot 管理认证' if authenticated else '尚无本次认证观察')
        # Full-native facts are supplied as actual controller/Host snapshots by
        # the calling console. This pure catalog never calls their lifecycle.
        if identity in {'tls.memory.full_service','tls.pc.full_service','tls.pc.virtual_daily'}:
            value=mc_full if identity=='tls.memory.full_service' else pc_full
            original=legacy_plugin_active('astrbot_plugin_memory_companion' if identity=='tls.memory.full_service' else 'astrbot_plugin_private_companion')
            status=owner_state(value,original,requires_scope=identity=='tls.pc.virtual_daily')
            row['enabled']=value.get('configured') if type(value.get('configured'))is bool else None
            row['runtime_active']=value.get('active') if type(value.get('active'))is bool else None
            row['legacy_runtime_active']=original
            row['ownership_phase']=value.get('phase','not_observed')
            row['runtime_scope_authorized']=scope_available is True if scope_selected else None
            row['owner']='TLS完整原生服务' if status in {'native_full','awaiting_scope'} else '旧实现仍运行' if status=='legacy_scope' else 'TLS候选；执行权尚未证实'
            row['replacement']['whole_plugin_replaced']=status in {'native_full','awaiting_scope'}
            row['evidence']=['实际完整原生owner.status、旧插件注册状态、当前范围与来源；配置为真不代表已运行']
            row['tests']['state']='not_run_for_this_development_batch'
        elif identity=='tls.personal_goals.automatic':
            active=pc_daily.get('active'); owned=pc_daily.get('effective_native_goal_owned') is True
            settings=pc_daily.get('settings') or {}; automation=settings.get('flags') or {}
            row['runtime_active']=active if type(active)is bool else None
            row['enabled']=bool(automation.get('auto_generate') or automation.get('auto_progress') or automation.get('share_enabled')) if automation else None
            row['source_registered']=pc_daily.get('genuine_scope_registered') if type(pc_daily.get('genuine_scope_registered'))is bool else None
            row['automatic_flags']={key:automation.get(key) for key in ('auto_generate','auto_progress','share_enabled','routine_enabled')}
            status=('unavailable' if active is False else 'blocked' if active is True and not owned
                else 'awaiting_scope' if active is True and (not scope_available or row['source_registered']is not True)
                else 'disabled' if active is True and row['enabled']is False
                else 'native_full' if active is True and owned and row['enabled']is True else 'implemented')
            row['owner']='TLS同一目标实例与原统一发送通道；按独立自动开关执行'
            row['evidence']=['实际pc_daily_lifecycle诊断、目标执行权、当前scope登记与独立flags，不调用推进或分享']
            row['tests']['state']='not_run_for_this_development_batch'
        elif identity=='tls.proactive.independent':
            value=independent_proactive; original=legacy_plugin_active('astrbot_plugin_proactive_chat')
            status=owner_state(value,original)
            sessions=value.get('sessions') if isinstance(value.get('sessions'),list) else []
            row['runtime_active']=value.get('active') if type(value.get('active'))is bool else None
            row['legacy_runtime_active']=original;row['ownership_phase']=value.get('phase','not_observed')
            row['scheduled_sessions']=sum(isinstance(item,dict) and item.get('scheduled')is True for item in sessions)
            row['waiting_review_sessions']=sum(isinstance(item,dict) and item.get('manual_review')is True for item in sessions)
            row['pending_operations']=value.get('pending_operations')
            row['owner']='TLS原生独立主动宿主' if status=='native_full' else '独立主动聊天执行权尚未证实'
            row['replacement']['whole_plugin_replaced']=status=='native_full'
            row['evidence']=['实际NativeProactiveChatHost.status与旧插件注册启停；不从任务数量推断发送成功']
            row['tests']['state']='not_run_for_this_development_batch'
        elif identity in {'legacy.memory.automatic','legacy.pc.nonrandom','legacy.proactive_chat'}:
            full=(mc_full if identity=='legacy.memory.automatic' else pc_full if identity=='legacy.pc.nonrandom' else independent_proactive)
            original=legacy_plugin_active('astrbot_plugin_memory_companion' if identity=='legacy.memory.automatic' else
                'astrbot_plugin_private_companion' if identity=='legacy.pc.nonrandom' else 'astrbot_plugin_proactive_chat')
            if owner_state(full,original)=='native_full':
                row['replacement']['whole_plugin_replaced']=True
                row['owner']='旧插件已退休；对应完整TLS原生服务运行'
                row['legacy_runtime_active']=False
                row['evidence'].append('实际完整原生owner/Host active与旧插件关闭证据；保留此旧ID用于历史职责索引')
        row['status']=status;row['status_label']=_LABELS[status]
        result.append(row)
    return dict(capability_domains=deepcopy(list(DOMAINS)),capabilities=result,
        capability_boundary='只读能力与职责投影；挂载、配置、注册、平台确认、手机可见分别记录。部分职责迁移不代表整插件替代。')
