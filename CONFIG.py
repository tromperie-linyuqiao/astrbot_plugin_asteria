# astrbot_plugin_virtual_body 全参数集中地。
# 纪律：改参数只改这个文件；其他模块只读不写；每轮迭代在 CHANGELOG 追加一行。

VERSION = "0.66.1"   # Chat原生准入状态与自有记忆修订接线

CHANGELOG = [
    "0.66.0 Chat按当前自有会话读取主动准入、查看来源修订并纠正自有原生记忆；QQ共享不变为写入权限。",
    "0.65.4 共享陪伴读取区分默认未手动额外开启与明确停用，不再误拦已配置启用对象；真实手动关闭保持。",
    "0.65.3 主动触发返回实际准入与投递结果，手动与定时触发共享在途占位；管理面板保留真实错误和未知保存核对。",
    "0.65.2 原PC音乐工具和上下文读取授权原生资料；感知页沿原桥按需读取当前来源，不启动新采集。",
    "0.65.1 会话设置入口接受并持久化已声明的表达格式，保留原权限与版本冲突检查。",
    "0.65.0 感知统一状态、记忆分层路由、任务模型路由及有来源的结构化表达。",
    "0.64.2 保存真实主动/日程消息类型，保护长期会话删除，身体暂不可用时仍可维护原动作定义。",
    "0.64.1 多段安静时段接通独立主动、音乐与共享发送队列；保留旧默认、提醒和原有消息权限。",
    "0.64.0 真实切歌候选进入原生统一队列，Chat内置PPB经现有认证与已分配设备上报；采集与发送分别授权。",
    "0.63.4 提醒暂缺真实会话时在原有效期内等待、投递授权和陪伴拦截原因可查、主动免打扰时段可维护。",
    "0.63.3 真实APP主动来源接续、共享PPB与音乐读取及可撤回授权、原节奏与投递通道接线；保留旧过期和未知任务。",
    "0.63.2 修复实际 AstrBot 查询参数容器导致 App 感知规则管理页返回400；不改变规则和发送权限。",
    "0.63.1 原生管理页全链路修复：冷管理员编辑、稳定请求核对、跨范围草稿、真实保存回读、完整主动面板与旧入口收拢、主题和导航。",
    "0.63.0 首页下一步事项、单次停课调课预览、普通记忆批量软归档恢复、绑定两端免打扰与重复上下文节省；Chat接入周期日程与全媒体位置。",
    "0.62.1 维护中心复用原管理员历史资料权限；真实APP范围按显式绑定和日程共享读取课表。",
    "0.62.0 周期日程与时区、资料逻辑备份恢复和索引维护、背景配置继承、课表节日管理与原生主动消息接线。",
    "0.61.3 声明并固定农历节日与节气计算依赖，缺少依赖时明确显示不可用。",
    "0.61.2 生日与节日沿原主动通道发送，教学周课表接入Chat日程、课前提醒和上课免打扰。",
    "0.61.1 绑定和解绑直接回执，会话未授权时给出明确说明。",
    "0.61.0 Chat复用原生日程、可撤回查阅权限；已绑定用户可将纯文本主动消息改发Chat，保留原队列与不明结果隔离。",
    "0.60.10 QQ绑定与解绑命令在身体文本观察前退出，不把一次性绑定码交给身体模型兜底。",
    "0.60.9 APP一次性绑定码经QQ真实私聊确认，双方长期记忆按来源共享；可选接续已确认主动消息，不增加QQ发送权限。",
    "0.60.8 Chat肚皮显示别名接到同一原生腹部，解析使用独立资料视图，不修改原角色配置和QQ词表。",
    "0.60.7 Chat自定义触觉说明保留原否定/引用规则，修复明确角色名隔开动作与部位时漏判；不改QQ解析或执行权。",
    "0.60.6 修复动作编号重复合并导致的原生互动创建与自定义动作编辑失败。",
    "0.60.5 Chat自定义动作接通原触觉解析、只读身体状态与独立账户头像；保留原业务执行权。",
    "0.60.4 Chat复用TLS原生触觉动作与部位、批量组合和聊天表情语义；保留旧历史及业务执行者。",
    "0.60.3 Chat复用TLS原生触觉动作与部位、批量组合和聊天表情语义；保留旧历史及业务执行者。",
    "0.60.2 Chat固定长期连接、原消息引用收藏及语音附件MIME接续；保留旧历史和既有TLS业务执行者。",
    "0.60.1 Chat表达偏好继承、引用与组合片段、会话模式剧情/归档、真实流式回复和保留原记录的再作答；既有TLS业务执行者保持。",
    "0.60.0 MC原话/画像/摘要/关系与历史、PC角色日常/目标行动、独立主动消息及统一语音发送的原生接线；保留原业务数据与原有执行账本，真实接管和验收以运行结果为准。",
    "0.59.0 原生记忆摘要算法管理接线（默认关闭）、手工有归属目标日计划与管理界面；保留R58共享表情/组合消息，不自动切换旧摘要或目标执行权。",
    "0.58.2 Chat共享人工表情库与双偏好、结构化动作/话语/表情及同SDK历史回读；无额外选图模型调用，旧QQ/MC/PC执行权保持。",
    "0.53.0 原生聊天核心约定工具、来源分层与管理员交权；保留已确认记忆优先级，核心字数预算不变；新增两项可兼容旧库的写入索引，旧MC业务按实际开关分批保留。",
    "0.52.0 管理员可维护明确私聊范围的原图、说明及标签，不依赖新聊天；原实时授权接口和发送权限保持，用户素材默认停用待复核。",
    "0.50.0 新增明确的管理员历史资料导入导出入口与原请求对账，不授予运行时发送权限。",
    "0.49.0 人工审阅历史材料保持未核实来源标记，不当作用户原话；移动端资料操作与缺真实会话提示更清晰，原库和执行权保留。",
    "0.38.1 手机本地短句扩至五App各100条；补零记忆会话目录与真实模块卡；记忆数据修订跨连接撤回旧上下文，修复同Windows时钟tick写完不能立即召回的微秒舍入。",
    "0.38.0 原生统一控制台、历史档案与表达反馈；App候选/独立新图/统一队列宿主接线；新增一次性日程与显式剧情管理，数据版本变化撤回旧上下文。旧插件未迁移业务保留原执行者。",
    "0.35.1 修复重试上下文、并发初始化与卸载清理；天气读取移出事件循环；修复规则草稿、档案导入、重复保存和场景词契约；材质覆盖独立存储并修复方式参数接线，保留既有接口及角色配置。",
    "0.35.0 私有统一感知版：新增可选 Presence API 与分段状态缓存、音乐/设备/时间/天气/阅读适配、临时 Context 去重与按需查询、来源失效与会话隔离；保留原身体空间演算、人格 Prompt 和提醒规则。",
    "0.34.0 私有存在层可靠性增强：接触元数据和推进锚点持久化、迟到抵达时间与移动归属、感知时效和会话隔离、异步取消及消息去重、兜底日额度持久化与同请求合并、完整注入护栏、面板保存反馈与运行健康；保留既有角色数值、提醒规则及数据协议。",
    "0.33.1 停止接触后旧异步抽取不得重建持续接触；按部位/会话失效，调度前预留、完成/取消回收。",
    "0.33.0 私有RP维护版：修复位置续期与重复移动、剩余ETA、重启字段、过载接触、绑定缓存、面板参数接线与内部块清理；支持明确结束持续接触；天气请求取消shell和城市库eval，失败不覆盖有效天气，当前观测与未来预报分离。",
    "0.32.1 死代码清理：移除 sleep_touch 读取链与 CS_* 同眠未实现常量簇（行为等价，该分支恒为False）；material层经核实为活链路，保留；P4心绪规则精简——内置 rules.json 7→4 条（删 mood_low 双重死因/rain_care/rain_veranda TTL易过期，保留 presence_room_changed/longing_invite/mood_warm/reading_new_chapter），引擎多信号语义由内联规则测试锁定",
    "0.32.0 线上实测三修（P0）：①天气 TTL——快照超过 MO_WEATHER_TTL_SECONDS（6h）未更新视为过期不当真：read_weather 返回 available=False/is_rain=None/stale=True（0.29.1 引擎机制自动封死 rain_care/rain_veranda 的 eq/ne/changed），main._weather_is_rainy 同口径且 TTL 判定先于缓存命中（mtime 不变但时间流逝过期同样拦截）——过期雨天动线不再把户外房映射室内；无快照的未激活形态 stale=False（是'从未有'不是'过期'）；②他位置兜底——read_presence：he.room 未知而她已落位 → 推断他在她身边（he_room=she_room/he_confidence=MO_HE_INFER_CONFIDENCE 0.5/he_inferred=True），same_room 从恒 False 变为可达 True（mood_warm 由此复活，降优先级 3→4 让位确定信号）；render_injection 同口径：he 位置未知且她稳定在房 → 渲染'他在身边'（与正常同室措辞一致不暴露推断细节；她移动中不推断——沿 0.27.9 伪陈述封口口径）；③心绪规则与信号修剪——mood_low 阈值 -0.4→-0.3（实测 score 0.1-0.8 波动原值几乎不可达）、default_schedule 14-18 书房拆为 14-16 书房+16-18 檐廊（veranda 原不在动线 rain_veranda 永不可达；veranda 在 L1 雨天不迁移）、read_reading 完本保护（当前书 chapter_count 全消化 → book_title='[已完本]'+available=False，防误导模型说她还在读书；换新书 meta mtime 更新即恢复）；+11 测试（334→345 全绿）；配套 PC 侧 5.10.2 大扫除：remember_you_adapter.py（629 行零引用）+memory_companion_adapter.py（1666 行目标插件未装）移入 _archive/，main.py 改 try/except+22 方法兜底桩（仿 self_timeline 先例，行为等同'插件未安装'降级态）",
    "0.31.0 体验修复轮（用户实测：单次揉耳尖 0.144 低于注意档完全无感/重咬仅 notice/必须每句重复'揉耳朵'/最重 30s×2 才 react）——与同眠模式同版合流：①持续接触（新模块 core/persist_contact.py）——接触从一次性事件升格为可延续状态：直接事件落账 state.active_contact[pid]={action,s,since,last_renew,last_msg,last_tick}（normalize 兼容补空 dict+坏条目剔除），双通道延续：消息驱动（每条消息给 s×cs_persist_rate 默认 0.4 的延续增益并刷新续期锚点——纯聊天也续期，观察器/注入双推进由 CS_PERSIST_MSG_MIN_GAP=20s 防双算）+tick 补充（每 cs_persist_tick_every=3 个 tick 一发、不刷锚点）；否定面 events.extract_stops（否定前缀+部位词 8 字符邻近、引号内不算）→ main 观察器清除对应接触；过期（距最近对话超 cs_persist_max_gap 默认 300s）清除、overload 进余韵清全部；延续事件 src='persist' 特判：不计 events_today/不积耐受/不进 history/不动习惯化·敏化·冷却·传导——只增加值与 arousal；②亲密语境增益——decay.intimacy_boost：arousal>0.15 或 verbal>0.05 → ×1.3、arousal>0.35 → ×1.5、同眠体温（sleep_touch active）→ ×1.2，三条件取最大不叠乘；advance_state 入场兴奋快照定档，本轮所有事件（含延续）event_gain 结果统一乘 boost；③阈值微调——内置 profile tiers react 0.35→0.30、lose 0.60→0.50（用户覆盖层不动，面板可改回）：1 次重咬(0.9)+1 次延续即到 react；面板新五键 cs_persist_enabled/cs_persist_rate/cs_persist_max_gap/vb_intimacy_boost_l1/vb_intimacy_boost_l2；+15 测试（317→332 全绿）",
    "0.30.1 联动修复轮（审计三断六修）：①MO_SRC_MOOD_FILE 目录修正+read_mood 键名兜底 final；②vb_verbal_emotions 改 PC 实际枚举亲密子集(praise/comfort/comfort_need)——原 love/flirty 集与 PC 枚举交集空致语言调情恒 0；③read_reading 进度路径修正为顶层 digests/；④PC presence_snapshot 补身体兜底+消费 proactive_intent；⑤schema 默认值同步",
    "0.30.0 存在深化轮（第一梯队三件套 + 语言调情→身体兴奋）：①语言调情→身体兴奋——新信号源 mood_signals.read_verbal 只读 PC companions.json 的 users.<QQ>.intent_profile.emotion（mtime 缓存、绝不写入），emotion 命中亲密情绪集（vb_verbal_emotions，默认 love/intimate/flirty/happy/excited/撒娇/心动/喜欢）→ is_intimate；decay.verbal_arousal_step 纯函数（intimate 每次 +rate 钳 cap / 非 intimate 按 τ 指数衰减，锚点 verbal_at）；arousal_of 合成 max(physical, verbal×weight)——语言把兴奋度'托底'到可感知但不产生部位事件/不计 events_today/不积累耐受；verbal>0.1 时注入头部渲染'语言撩拨 X.X'；②长期身体记忆（日级适应层）——新模块 core/adaptation.py：history 流水扩容 20→200 条（normalize 兼容），近 7 天直接命中（src 非传导且正向变更）>阈值→部位长效敏感化 +1%/天（钳 +30%），零触碰且原 sens≥5→迟钝化 -0.8%/天（钳 -20%），产出 state.longterm_mult；decay event_gain 部位系数乘 longterm_mult（无键=1.0 行为不变）；main 每日一次（时区统一入口日键防重入）+落盘日志；③情绪↔身体耦合——decay.apply_mood_coupling：insight mood score<-0.3 全局增益×0.92+overload 阈值+8%（低落绷着）、>0.5 ×1.05（愉悦），临时系数 advance 内消费即清（不持久化残留）；身体→情绪：overload 进余韵时 main 写 mood/body_mood_hint.json {ts,hint:warm}，read_mood 融合 recent warm hint（2h 线性衰减，+0.15 封顶，无标定数据时 hint 单独可用）；④主动触碰意图——新模块 core/proactive_intent.py：building 且 arousal≥0.45 且 verbal_arousal>0.15 且冷却 4h 外→从五模板池随机出意图短语（含最活跃部位占位），写 state.proactive_intent={ts,hint}；注入渲染出口加'她<短语>'尾巴（≤14字，mark_as_temp 通道自然携带，PC 快照若只拼 phrase 也能从 state 文件读到该字段）；+25 测试（291 基线 → 316 全绿）；全部新参数进 _conf_schema.json 与 TERMS 第十节",
    "0.29.1 心绪层根因修复+部位级细调轮（线上实测：mood/signals 三源 null、触发 0 条）：①信号兜底——presence 以 .space.json 为唯一入口，白名单会话未触发过空间事件时文件不存在→返回 null→5/7 内置规则短路（根因）；现按三层迹象兜底（身体状态文件取 phase/arousal 真值>profile 覆盖层>已加载庄园 manor），插件服役即给中性默认（available=true/she_room=null/arousal=0），she_room=null 成为 changed 可比基线——她首次落位即触发『她移动了』；weather/mood/reading 无源数据（未问过天气/insight 未标定/书柜未装）改返回 available=false 未激活形态（is_rain/score/chapter_index=null），面板区分『未激活』与『信号不存在』；②引擎加固——_cond_ok 对 available=false 的源一律不成立（eq/ne/changed 全封死，未激活≠值不等），render_hint 的 {score}/{chapter} 空值守卫；③触发引擎调用链排查确认完好（tick_all→_tick_mood→evaluate 每 tick 在跑，triggers.json 71B 空结构即证据）——0 触发是信号 null 的下游而非断链；+7 心绪测试（含端到端：可用信号→建基线→信号变化→触发→triggers/history/cooldowns 三处落盘断言）；④部位级细调五键（parts[] 可选，缺省中性 1.0=行为逐位不变，profile_param 同风格坏值回中性）——gain_mult(0.3-3.0 部位总增益，直接事件乘源部位/传导落点乘目标自己的)、tolerance_mult(0.2-3.0 耐受积累)、windup_mult(0.3-3.0 敏感化累积)、type_mults{type:0.3-3.0 部位×类别交互，键∈五类}、material_affinity{材质id:0.4-2.5 部位×材质亲和}；validate_parts 保存口显式校验值域/类型/枚举键，web_api /profiles parts 投影透传五键（页面重构侧可消费）；+10 参数测试（中性逐位不变/五键各自生效/传导目标倍率/坏值回中性/校验与透传）；291 pytest 全绿（273 基线）",
    "0.29.0 参数体系深化轮（用户要求：加更多参数——动作参数、材质参数）：①动作词参数化（向后兼容）——action_words 值支持两种形态：旧数字 s=强度（等价 {\"s\":v}）与新 dict {s,method,freq_hz,speed_cm_s,depth,temp_c,cooldown_s,type}（全键可选）；events._action_words 归一化、命中时把方式/频率/速度/深度/温度附到事件、decay 的 material_gain 用事件级参数；②type 语义类别 touch(默认)/pain/temp/air/constrain——pain 对 sens≤4 低敏部位 ×1.2（痛觉广谱受体分布均匀，Derbyshire/Olausson 系常识锚）、temp 受材质 thermal 调制 ×(1+0.4×thermal)、air 对 flags 含 exposed 部位 ×1.1——倍率全部 CONFIG 可调（TYPE_*），默认值下旧词表行为逐位不变；③动作词级 cooldown_s 冷却——同词冷却内命中增益 ×0.5（防复读刷值），默认无冷却（旧行为）；state 新增 word_cd 账本；④材质四参数——friction 摩擦（0-1，中性 0.5，rub 增益 ×(0.7+friction×0.6)）、thickness 厚度（tap 高频 ×(1-thickness×0.4)）、warm_hold 保温（blow 舒适窗 ×(1+0.6×warm_hold)、temp 类增益 ×(1+0.3×warm_hold)）、pattern_mm 纹理间距（>2mm 粗纹理与 Pacinian 频带交互强化 tap ×(1+0.25×归一)）——默认缺省即中性，现行为不变；⑤材质级 method_gains {tap:1.3,rub:0.8} 方式乘数覆盖（0.4-1.8）；⑥status 页快速添加卡扩展（方式下拉/频率/速度/深度滑条/类别/冷却）+ 专家表格动作词编辑弹层；材质工坊四参数滑条+方式微调折叠行+新材质自动 slug；⑦联动预览带材质/方式示例乘数（页面侧 bridge 采样，不复制公式）；+18 核心测试（273 基线）；TERMS 自定义总表加动作词参数/材质参数两节",
    "0.28.1 UX 简化+联动可视化轮（用户反馈：添加复杂/规则不直观/联动不能自定义）：①status 页顶部『怎么用』三行说明卡+各编辑卡配白话副标题+参数键名全部配中文标签；②『快速添加（推荐）』卡——部位输中文名一步完成（拼音 id/默认 sens 5/半衰 1200s/自动落点/直接保存热生效），动作词输词拉强度一步并入 action_words，toast 报生成 id 与下一步提示；③『联动编辑器』卡——2D 人体图点两个部位画传导连线（浮层 0.05-1 滑条定倍率写入源部位 radiate），点连线可改倍率/删除，双向传导紫线单向蓝线带倍率标签，联动预览文字版（耳尖→尾根 0.3→腰 0.06 链式描述，复刻后端 BFS 语义）；④自定义联动算法——profile.params 新增 radiate_hops（最大跳数 1-3，默认 2）与 radiate_mode（mul 连乘取最强路径默认/sum 多路径求和），decay.radiate_map 参数化（纯函数加参，默认行为逐位不变），advance_state 经 profile_param 链注入；web_api params 校验补 radiate_hops 值域与 radiate_mode 枚举；+5 核心测试（参数化/默认不变/求和/advance 链路/坏值回退）；TERMS 自定义总表加快捷入口两节",
    "0.27.9b 端到端注入审查轮（LLM 视角→页面五段）：①空间块伪陈述修复——她移动离开出发房而他仍在该房时 distance_band 按 she.room（=出发地）判同室渲染『他在身边』，与移动行矛盾；改渲染『他还在<房>』；②门控①数据流补全——tick/注入/where 三路径 advance 产生的日程/兜底换房与移动落位此前不写 _last_change，10 分钟近变化窗对 tick 路径失明（LLM 拿不到她刚换房底色）；③/hermove 粘滞修复——source 原 'manual' 不受 advance rp_fresh 保护，落地即被日程拽回、导演指令形同虚设，改 'rp' 享 RP 覆盖窗（manual 的瞬态语义为 test_advance_rainy 锁定设计，故不动 core）；④/hermove、/spacestatus 补中文别名（移动她/空间状态）+ 观察器跳过清单同步；⑤/put 带房间参数未识别时明确报错（原静默落到他所在房=物品错放）；/hermove 未知房提示补 /map 一致口径；⑥manor 页 load 失败除 toast 外把 meta 位留持久错误（原 3.2s 即逝只剩空白编辑器）；+3 封口测试（移动离开伪陈述/双块静默总闸/约束行措辞锁定）。审查结论：紧凑形态裸英文阶段词、双块各自带快照护栏、余韵期体感平稳行——经评估保留（0.19.0 token 纪律与独立门控的设计权衡，报告备查）",
    "0.27.9 结构健康+全参数下放轮：①覆盖层版本化（save_profile_override 写 base_version；_load_profiles 对无版本/旧代覆盖层按 half_life<内置1/4 判旧代固化→数值回内置、label/aliases/radiate 用户自定义保留并回写，manor 覆盖层同机制只对 rooms/edges 数值字段）——封死 0.27.8『覆盖层旧 τ 压制内置新 τ』事故的复发路径；②硬编码体验参数面板化：vb_afterglow_seconds/cooldown_seconds/afterglow_mult/cooldown_mult（decay phase 机器）、vb_night_window（昼夜窗口支持跨午夜）、vb_constraint_text（注入约束行）、vb_feel_word_ttl（材质感受词时效）、sp_eta_thresholds（距离档阈值）、sp_hearing_same_floor/adjacent（听觉文案）；materials.json 顶层 method_params（stroke/press/rub/tap/blow 方式曲线参数，material.py 读用缺省回内置）",
    "0.27.8 点位失效修复轮：三层叠加——①unpkg CDN 在国内/沙箱加载失败→slugLabel 兜底生成光杆 part（无意义id，二次添加撞名）→pinyin-pro 本地化进页面目录（content 服务端点用本页 token 供应，沙箱内可载）；②覆盖层(plugin_data/profiles/texas.json)是 0.23.2 时代保存的旧 τ(60-150)且优先级高于内置→τ×10 从未对 texas 生效→按映射升级到 600-1500（0.23.3 验证只看了内置文件没查覆盖层，教训）；③内置交付基线确认完好(600-1500)",
    "0.27.7 沙箱免疫导航轮（v2跳转失败根治）：根因三环——iframe sandbox 无 allow-same-origin（fetch 跨域即死）+ content 端点按页校验 token（复用票 401）+ 面板创建的 API key 因 WAL 僵尸文件（启动后 -wal 被删，进程写已删 inode）永不持久。修复：web_api 新增 /nav 路由（?api_key= 查询参数鉴权→读 dashboard.jwt_secret 铸目标页 60s token→302 重定向，纯导航零 fetch）；key 行 CLI 直插主库绕开僵尸 WAL；垫片 v3 互跳统一走 /page/nav。实测五页 302→200 全通。遗留：WAL 删除元凶待查（面板运行期 DB 写入全不持久，独立 bug）",
    "0.27.6 部署窗口页面适配轮：五页注入双模式适配层v2——①独立标签（直达链接）绕过postMessage桥直连扩展API（官方bridge-sdk的ready()等父窗口context消息，无父窗口即永久挂起——直达链接卡加载中的根因）；②iframe内.xnav互跳改为入口API换content_path自导航（原实现弹沙箱限制toast，面板内切页打不开的根因），capture阶段拦截旧toast绑定。备份 vb_pages_pre_standalone_0921/",
    "0.27.5 终审修复（独立审查 21 项）：P0 身体层 list_states 排除 .space.json（每夜日切覆写空间状态的数据损坏）；P1 mood 目录自建（全新安装不再静默死亡）+ _safe_json 自递归修复（心绪规则保存恢复）；P2 嵌套数组雨词识别 + 删除混入的面板凭据文件 cmd_config.json 与死模板 t2i_templates；P3 mood 规则 mtime 缓存真实现/混合宽窄标签清洗/set_room 同目标幂等/delete_state 清缓存/{phase} 占位符/CHANGELOG 去重/TERMS 三处口径修正/删 req.prompt 旧通道。+5 封口测试（207 项）",
    "0.27.4 第二三轮优化：web_api request.json 统一兜底（坏 body→400 而非 500）；room_words import 模块级提升；README 重写为 0.27.x 大成版（五模块/联动网/文档索引）；全插件定向自查（裸 except 0/TODO 0/静默降级 10 处均设计内）；交付净化——清除子代理混入插件目录的验证脚本（58 文件标准结构）",
    "0.27.3 第一轮性能优化：空间状态指纹跳写（state_fingerprint 对齐身体层纪律，tick 空推进不再全量落盘）；观察器合并读（空间段 st 复用给场景增益，一轮一读）；mood 规则 mtime 缓存（每 tick 免读盘）",
    "0.27.2 联动深化：环境底色（18 房 mood_bias=[valence,arousal] Russell 环形/PAD——房间氛围对心理的量化），presence 信号合成 env_valence/env_arousal/mood_word/same_room；新默认三规则——渴慕邀约（双控模型：arousal≥0.55 且 building 期→主动邀约情境，表达权在 PC 人格）/氛围动机（高效价+同室→亲近动机）/雨声檐下（天气×空间组合示例）；占位符+env_valence/mood_word/same_room；修冷却 or-0.0 语义 bug（新账本被误判冷却中）",
    "0.27.1 自定义联动迭代：房间场景互动词（manor.json 房间 scene_words:[{word,gain}]，观察器与 /touch 命中即事件增益+scene 标记——自定义房间→自定义互动→身体反应）；心绪规则 hint 变量化（{she_room}/{city}/{is_rain}/{book}/{score}/{phase} 占位符，evaluate 自动渲染）；总览页『当前联动』卡（雨天动线生效态/活动触发数）",
    "0.27.0 大成合体：心绪编排层并入（core/mood_signals+mood_engine+mood_store，数据落 mood/，页面 pages/mood，六路由挂 /mood*，tick 并入主循环空间之后）+天气并入（weather_detail llm_tool + ez_weather/ node 工具 + 落盘 data_dir/weather/，雨天动线改读内部优先+旧路径回退）——一个插件 = 身体+空间+材质+天气+心绪，模块进程内互相配合；12→8 插件",
    "0.26.1 四页 WebUI 审查修复：manor 双击新增落点偏移(toM 缺 viewMin)+空数据卡死兜底；status 命名表跨角色串层+3D 拖拽未定义变量；home esc 误用；全页加导航条与跨页引导",
    "0.26.0 WebUI 双页+激活：材质工坊页（12 材质编辑+后端采样乘数曲线 SVG+文献页尾+保存热生效）；存在层总览页（位置/移动/距离档/身体态/材质事件一屏）；web_api 13→17 路由（materials 三件+presence/overview）；ACTION_WORDS 补擦（轻触 0.4 档）；weather_ez 落盘改造激活雨天动线（查后写 weather_last.json，端到端验证）；PC {{presence_layer}} 死键清理",
    "0.25.0 B 项存在层深化：雨天动线（weather 前瞻探测+rainy_fallback 户外→室内映射，数据缺失安全降级）；刚到房间氛围短句上注入（18 字截断，稳定期不带）；听觉规则（异层难闻声息/隔壁可闻动静）；桥补他离开语义（on_departure 0.02 独立冷却）",
    "0.25.0 神经触觉材质层：12 材质库 materials.json（13 条文献锚点 _refs：CT 纤维 1-10cm/s/32°C、Meissner 5-50Hz、Merkel 0.4-4Hz、Pacinian 100-300Hz、两点辨别阈、织物粗糙度）+ core/material.py 计算模型（纹理感知阈 sens^1.2/log 粗糙度、刺痒通道、五方式乘数 stroke/press/rub/tap/blow）+ events 材质词就近配对+ decay 增益接线 + inject 材质感受词（丝绸·细滑 等，600s 时效）",
    "0.24.0 存在层整合：manor 0.7.2 并入（core 五模块+data/manor.json+平面图页 pages/manor+43 测试）；单壳合一——九指令/单观察器（空间抽取先行）/单注入点 inject_presence_state（空间块前·身体块后，硬编码顺序）/单出站清洗双正则/合一 tick（空间先行）；状态分立 state/<角色>_<会话>.space.json；web_api 13 路由（空间挂 /manor* 子路径）；旧 manor plugin_data 自动回退迁移（.migrated 标记不删旧）；L2-B 桥 core/bridge.py（同室落位→敏感微升/离开→回落，300s 按类冷却，默认 0.05 级绝不自动过载）",
    # ---- 并入 manor CHANGELOG（存在层合并 P0）----
    "0.23.3 衰减终调轮（用户补充节奏：一轮对话1-2分钟、长消息5分钟，档位须扛住间隔）：τ 再 ×2×1.25（总计 ×10）——half_life 600-1500s、DECAY_TAU_DEFAULT 900、WebUI 预设/默认同步。单次强摸耳朵：注意档稳过 5 分钟（0.155）、余温至 ~20 分钟、45 分钟散尽；5 分钟间隔两触即叠进反应档",
    "0.23.2 衰减节奏轮（用户反馈：兴奋度下降太快）：部位衰减 τ 全套 ×4——两 profile 全部 half_life（60-150s→240-600s，分层比例不变）+ DECAY_TAU_DEFAULT 90→360 + WebUI 预设 hl 与新部位默认同步 ×4。校准前强摸耳朵 1 分钟即跌破注意档、3 分钟归零；校准后注意档约 2-3 分钟、余温(v>0.05)约 10 分钟、30 分钟彻底平静，消息间隔内的堆积终于可累积。wind-up/习惯化等短窗机制不动",
    "0.23.1 部署审查轮（安装窗口）：①命名层烤入修复——/page/profiles 与 /profile/save 原用合并命名后的 profile，WebUI 保存会把用户命名烤进参数覆盖文件且清空命名删不掉；_load_profiles 现保留 _profiles_base（参数层基底），编辑器展示与保存合并均以基底为准，命名只经命名层管理；②命名层支持整体清空（空对象=清空，前端两步确认）；③/vbody 白名单前置（非白名单不再看到角色清单，与 /vbstatus /touch 同口径）；④消息观察器指令跳过清单补 vbstatus/vbs/身体状态查询",
    "0.23.0 合规终验轮：core 源码链路审查发现 user 侧 req.prompt 注入会随 assemble_context 永久落历史（过时快照污染+token 累积）——改走官方 mark_as_temp() 通道（TextPart extra_user_content_parts，provider-facing only not persisted），dump_messages_with_checkpoints 实测验证块被剔除；README 补部署节与月耗估算（谷价 1h/天 ≈ 51 万 input/月 ≈ ¥0.26）",
    "0.22.0 动作可行性轮：自身可达性固定行（AAOS ROM 常识：颈后中/背中/骶尾自手不可及，注入块新增 可及： 行）；身高差姿态提示（profile.body.height_cm × vb_user_height_cm，差>15cm 条件注入俯身/踮脚，texas 178/matcha 155）；PHASE_HINTS 补姿态（余韵四肢发软/不应期全身乏力）；3D 模型按身高比例缩放（换角色即时刷新）；+2 测试至 91 绿",
    "0.21.0 命名分层轮：命名层独立文件 <id>.names.json（label/aliases 与参数层物理分离——参数迭代零读写名称，内容边界清晰）；load/save/apply_names_overlay 三函数+main 加载合并+web_api /profile/names/save（校验+热载）；WebUI「部位命名」批量快速区（占位待命名高亮/已有名半透明可覆盖）；占位点位双侧合并 8→5（01 中枢/02 腹股沟/03 大腿内侧/04 骶尾/05 臀内下，居中坐标+radiate 重连）；+1 测试至 89 绿",
    "0.20.0 占位点位轮：S2-S4 皮节 8 参数占位部位写入双 profile（label=01-08 数字编号，sens 8-10/τ 60-90/radiate 沿皮节传导/精确三维坐标就位，名称用户 3D 模型自行改写）；3D 加骨盆底会阴几何（椭球）+bodyRadiusAt 骨盆底段（落点吸附精度）",
    "0.19.0 低token轮：注入块紧凑形态默认启用（RENDER_COMPACT）——一位小数锚点（LLM 对数编码下两位无增益）、裸阶段词、精简头尾护栏、约束行去冗余；204→152 字符（-26%）；compact=False 完整形态保留对照测试；修 guard 双定义残留",
    "0.18.0 虚拟身体轮（医学联动）：筋膜链层（Myers Anatomy Trains 四链：后侧/前侧/侧/臂，链张力=活跃段≥2 的 sens 加权均值，绷紧链上部位衰减 τ×1.2——肌肉紧张让敏感消退变慢）；自主神经体感行（呼吸/心跳三级分档派生+肌肉轻颤=boost 或链张力超阈，注入块新增 体感： 行，204 字符样例）——全部派生渲染不增状态存储",
    "0.17.0 文献细化双轮：①触觉重平衡（神经科学文献）——敏感化 wind-up 机制三翼（窗口 45s 累积：中和耐受 50%/放大增益 50%/减缓衰减 60%，SENS_GAIN=0.24 CAP=1.0 TAU=90s 锚 Hollins 1990 中枢感知适应；overload 清 boost；normalize 补字段），修基线发现的过载不可达（三部位 20s 重度连击 14 轮可达，轻柔零散不误触，正反回归门锁定）；高敏部位 τ 60→90 校准至文献区间 90-120s；基础公式测试 no_sens fixture 隔离+τ 动态解耦。②LLM 注入改进（注入研究）——注入位置迁移 user 消息深度注入（前缀缓存全命中，vb_inject_position 可回退 system）；约束行全正向措辞+区间语义（句长改'二十字上下'式，硬边界留 profile 覆盖）；标签加 快照=临时 属性；护栏改正向临时快照语义",
    "0.16.0 查漏补缺轮：强度修饰词（狠狠×1.45/用力×1.3/轻轻×0.55 等 9 词，动作词前 3 字内乘算钳制）；/vbstatus 聊天侧状态查询指令（查询前推进，活跃部位+档位）；TZ 时区部署口面板化（vb_tz_utc_offset 配置键，-1=容器时区，initialize 时覆盖 CONFIG）；CQ 表情码剥离防误触发；/touch 反馈带档位名；编辑器悬空 radiate 行内标红提示",
    "0.15.0 预设字典轮（GitHub 调研落地）：56 条常规部位预设（REDCap painmap 键+标签模式，sens 按 TPD 映射，敏感区不预置）；落点气泡升级——按落点坐标智能预选最近 5 个预设 chips、ID 实时灰字预览、回车跳过命名（numbered marker 模式，双击+回车两步添加）；调研来源 Sketchfab/REDCap/NN/g 见 ITERATION 调研备忘",
    "0.14.1 对称部位轮：选中部位一键镜像复制（x→200-x 自动落对侧，label 加·右，id 自动，清空 radiate 待重连）——左右对称部位不再重复建",
    "0.14.0 添加流程轮：id 全自动（中文 label→拼音 slug，pinyin-pro CDN 懒加载失败回退 part_N；表格 id 列留空即自动；后端 _auto_part_ids 兜底）；落点即点即命名气泡（2D/3D 双击原地弹输入框，输中文名回车即建，id 自动）；删 addPartAt 死代码；+1 测试至 80 绿",
    "0.13.1 自由定位轮：3D 双击未命中网格时自动吸附体表最近点（任意点击都有合理落点，摆脱预制几何形状限制）；节点 3D 自由拖拽（相机平行平面求交，立体移动）；参数面板新增深度 z 滑杆（-40..40，正=体前）；肩/髋球补几何覆盖",
    "0.13.0 3D+agent 轮：人体神经图新增 3D 视图（three.js CDN 懒加载、程序化人体半透明+线框、拖拽旋转/滚轮缩放/双击体表射线落点新增、部位球+传导线+标签、皮节参考环 C4/T4/T10/L1；离线回退 2D）；viz 扩三维 [x,y,(z)]；AI 快速填写通道（页面粘贴 JSON 批量合并 + README agent 工作流）",
    "0.12.1 找bug轮：修 0.11.0 引入的页面 JS 语法错误（renderEditor 被提前闭合，动作词表段悬空成孤儿代码→整页脚本不执行白屏）；新增 node --check 页面校验脚本并写入硬性纪律",
    "0.12.0 消耗优化轮：StateStore mtime 缓存（命中省 json.load+normalize，深拷贝防污染，外部改盘 mtime 变自动重读）；注入路径指纹跳写（空闲请求不再无谓落盘）；tick 静默降频（连续 5 轮无变化会话跳过，事件路径即时唤醒）；save 紧凑 JSON（-26% 字节）。基准：60 轮 tick 1017→150ms、200 次注入路径 1090→160ms；+1 测试至 79 绿",
    "0.11.0 神经拟真轮：WebUI 人体神经图（SVG 正面剪影+部位节点按 sens 着色+传导箭头链+拖拽定位 viz 持久化+双击新增+右侧参数面板）；神经学参考数据落地——TPD 两点辨别觉映射公式（Weinstein/Sato/Won 系，CONFIG.TPD_REFERENCE 表）+ 皮节走向（StatPearls/Kenhub），texas/matcha 常规部位 sens 按数据重校准（本能区保留 RP 加成），测试期望与 profile 值解耦",
    "0.10.0 神经链+直观化轮：传导升级为多跳神经链（BFS ≤2 跳、最强路径、环安全，texas 演示链耳尖→尾根 0.3→腰 0.06）；sens 1-10 语义标尺（麻木→末梢聚集，每档直觉描述+系数说明）后端下发；WebUI 编辑器直观化（sens 滑杆+实时档名、标尺色带图例、神经联动预览面板）；+2 测试至 78 绿",
    "0.9.0 双子代理审查修复轮（19 项发现全处置）：P0 指令 *args 签名被 AstrBot 参数绑定判死→改 (self,event)+message_str 解析（两条指令真机复活）；P1 沙箱禁 confirm/alert→两步确认+toast；P1 部位只锚定最早出现丢后半句动作→逐出现位置匹配；P2 指令文本观察器双计+bot 自回流守卫、profile id 下划线错拆状态文件（加载时校验）、reset session 路径字符白名单；P3×8：NaN/Inf 双守卫、动作词显式 0=禁用、跨部位别名查重、引号内动作词、overload 保留耐受增量、全角标签对、terminate 清 fb_tasks、_new 不入档/导入补全键/事件委托消注入面",
    "0.8.1 全量审查轮：修出站清洗正则分支顺序（孤立标签模式先命中导致完整块内容泄漏进用户消息，测试同步锁死）；web_api reset/delete 补非 dict body 守卫；兜底 create_task 持引用防 GC；删 parse_touch_command 死代码（并入 parse_touch_multi）；README WebUI 节改 bridge 约定",
    "0.8.0 WebUI 合规轮：web_api.py 全量改用 astrbot.api.web（request/json_response/error_response，弃 quart 原生对象）；页面 API 调用全量改走 window.AstrBotPluginPage bridge（裸 fetch 401 的根因修复，官方 plugin-pages 约定）；部署实测 overview 200 + 登录鉴权 + 错误信封",
    "0.7.2 部署验证轮（P0 修复）：core 全部绝对导入改相对导入——AstrBot 以 data.plugins.<插件名> 命名空间加载插件，绝对包名 ModuleNotFoundError（PC 用相对导入的深层原因，本地冒烟抓不到、完整实例才能暴露）；新实例验证：插件加载/profile/API 六条路由注册/WebUI overview-profiles-bindings-reset 全链路 HTTP 200",
    "0.7.1 细化轮：接触类型显示时效（10 分钟外的\"·舔\"类标签不再渲染，防过时信息）；/touch 多部位（+ 连接共享强度类型，任一非法整条拒绝）；WebUI profile 导出/导入 JSON（自填部位备份迁移，导入经人工确认才落盘）",
    "0.7.0 调研落地轮：出站标签清洗（on_decorating_result 剥除模型模仿的〈身体状态〉残留，借鉴 clean_chatter 污染教训）；数值变更流水（history 环形 20 条：时间/部位/旧值→新值/来源含传导，借鉴 Favour_Ultra display_data），WebUI 卡片可展开回放",
    "0.6.1 找bug+补充轮：编辑器动作词重名合并防护；会话绑定管理闭环（/bindings 查看 + /binding/delete 解绑 API + 页面绑定表）",
    "0.6.0 部位扩充轮：texas/matcha 扩至全身 18/17 个常规部位（头脸颈肩背腰腹四肢脚，敏感区不做留白给用户自填）；arousal 改活跃部位归一（抗稀释，静息不参与分母）；低值注入例外（60s 内有直接事件即使低值也放行）；WebUI 编辑 API（/profile/save 校验+备份+热生效）与部位/动作词编辑面板（行内编辑/新增删除/覆盖保存）",
    "0.5.1 找bug轮：WebUI esc() 补单引号转义（onclick 注入面）；数值细化评估——规范公式框架内已满（黏滞衰减等候选会破坏验收基准公式），记录后不再凑数",
    "0.5.0 WebUI 筹备轮：web_api.py 注册官方拓展页面 API（overview/profiles/state/reset，照搬 PC register_web_api 模式+未提供时降级）；pages/status/index.html 状态总览页（进度条/趋势/平复标注/重置）；数值细化——部位敏感度参与增益（sens→0.6-1.0 系数，传导目标用自身系数）",
    "0.4.4 自由度轮：冷却部位渲染\"平复中\"标注（模型可读恢复状态）",
    "0.4.3 减污染轮：文本抽取词法升级——动作词与部位邻近配对（支持后置语序\"对着尾巴吹气\"）、否定前缀拒绝（\"别摸耳朵\"不再是刺激）、动作词窗口标点截断防跨句误配；+3 测试至 62 绿",
    "0.4.2 找bug轮：审查传导/习惯化交互（辐射环/档位实时性/坏倍率/setdefault 边界），无新缺陷；文档同步",
    "0.4.1 补充+自由度轮：生理传导 radiate（如耳尖带动尾根 0.3 倍，间接刺激不积累耐受/不触发冷却/不计数）；习惯化参数 habit_streak/window/factor 下放 profile",
    "0.4.0 优化+找bug轮：过载临近预警（距阈值<0.10 时提示模型）；profile.params.night_mult 角色化夜间倍率；刺激习惯化（同部位 60s 窗口第 3 次起 ×0.7）；profile 加载优先级修正（plugin_data 最高）；时区统一为 TZ_UTC_OFFSET（节律+日切共用）",
    "0.3.5 找bug轮：今日累计入写盘指纹；耐受增量改用 s_eff，与增益同步放大（对齐文档语义）",
    "0.3.4 补充能力轮（ST 借鉴）：今日接触累计，注入首行显示，日切自动清零；平稳部位省略趋势箭头",
    "0.3.3 逻辑增强轮（ST 借鉴）：昼夜节律——深夜敏感度 ×1.1，含 UTC 偏移部署口防容器时区错位",
    "0.3.2 逻辑增强轮：补算事件按所处 phase 时间区间取敏感倍率，cooldown 终点反推余韵上界",
    "0.3.1 补充能力轮（ST 借鉴）：趋势箭头 ↑/↓（窗口增量>0.01），模型可读升降方向",
    "0.3.0 找bug轮：兜底缓存 key 补角色维度，防多角色串事件映射",
    "0.2.9 减token+减污染轮：LLM 兜底同文本当日缓存；注入块加防事实化护栏（素材自述）",
    "0.2.8 优化轮：README 样例重生成与全量同步",
    "0.2.7 逻辑增强轮：补算事件按所处 phase 时间区间取敏感倍率，cooldown 终点反推余韵上界",
    "0.2.6 自由度轮：profile.expressions 覆盖档位句长约束",
    "0.2.5 补充能力轮：afterglow/cooldown 约束行带阶段指向（余韵未散/不应期迟钝）",
    "0.2.4 找bug轮：会话绑定的角色失效时回退默认角色；引号内首现不再埋没引号外的真实命中",
    "0.2.3 减token+减污染轮：LLM 兜底提示词瘦身 30%；引号（“”/\")内命中一律跳过（歌词/诗词/转述约定）",
    "0.2.2 逻辑增强轮：接触类型渲染进部位标签（耳尖 0.62（失控·舔））",
    "0.2.1 自由度轮：profile.params 可覆盖 gain/cool_seconds/tolerance_gain（换 profile 即换手感）",
    "0.2.0 补充能力轮：/vbody 指令多角色会话绑定，绑定持久化 state/bindings.json",
    "0.1.9 找bug轮：get_or_create 以调用方锚定 character/session，防文件错位失真",
    "0.1.8 找bug轮：部位折叠阈值入 CONFIG、档位门控对坏 tiers 配置防炸、\"含\"字动作词因高频歧义移除",
    "0.1.7 优化轮：tick 静止会话按变化指纹跳写盘（衰减从旧锚点补算无损）",
    "0.1.6 减污染轮：building 期 arousal 未过第一档不注入，余韵期不受门控",
    "0.1.5 减token轮：近零且无档位的部位不再渲染进注入块",
    "0.1.4 逻辑增强轮：部位词匹配精确优先+最长命中占优，alias 包含关系（腰/腰侧）不双计不误配",
    "0.1.3 自由度轮：profile.action_words 可覆盖全局动作词强度/追加角色专属词",
    "0.1.2 补充能力轮：动作词 8→21 个，补全轻→重梯度（蹭拂吹抚拨挠搓亲捏拽揪吮）",
    "0.1.1 找bug轮：overload 余韵与 cooldown 终点锚定事件/余韵时刻（停机跨期不再多卡 20 分钟），phase 补算一次推进到位；清理 inject.py 死代码",
    "0.1.0 初始构建：decay/state/events/inject 四模块 + /touch 指令 + 每分钟 tick 衰减 + 白名单私聊注入 + LLM 兜底抽取（默认关）",
]

# ---- tick 与演算 ----
TICK_INTERVAL_SECONDS = 60          # 定时推进周期（秒），无消息也照跑
DECAY_TAU_DEFAULT = 900.0            # 部位缺省 τ（秒）；profile 里 part.half_life 优先于本值
GAIN_DEFAULT = 0.25                 # 事件增益系数 gain
SENS_GAIN_MIN = 0.6                 # 部位增益系数下限（数值细化：敏感部位升得更快）
SENS_GAIN_SPAN = 0.4                # 部位增益系数跨度：系数 = MIN + (sens/10) × SPAN，sens 9 → 0.96、sens 6 → 0.84
RADIATE_MAX_HOPS = 2                # 神经链传导最大跳数（耳尖→尾根→腰 = 2 跳；防环防噪声）
RADIATE_HOPS_RANGE = (1, 3)         # 0.28.1 自定义联动：profile.params.radiate_hops 可调范围（默认 2）
RADIATE_MODES = ("mul", "sum")      # 0.28.1 传导聚合模式：mul=连乘取最强路径（默认）/ sum=多路径求和
# sens 直观判定标尺（WebUI 图例与编辑器共用；增益系数 = 0.6+0.04×sens，arousal 权重 = sens/10）
SENS_SCALE = [
    (1, "麻木", "几乎无感，重刺激也只有微弱反应"),
    (2, "迟钝", "要很用力才有可察觉的变化"),
    (3, "偏钝", "普通触碰基本无感，持续刺激才累积"),
    (4, "常规", "普通人的平均水平，稳定但不出挑"),
    (5, "略敏", "轻碰就有感觉，容易慢慢升温"),
    (6, "敏感", "日常动作就能引起明显反应"),
    (7, "很敏感", "轻触即颤，躲避反应强烈"),
    (8, "极敏感", "几乎一碰就藏不住，容易过档"),
    (9, "神经密集", "本能反射区，碰一下就到注意档边缘"),
    (10, "末梢聚集", "全身神经最尖端，轻触即强烈反应"),
]

# 神经学参考数据（两点辨别觉 TPD，经典 Weinstein 系测量；用于 sens 校准与自填部位参考）
# 映射公式：sens = round(10 - 8 × log(mm/2) / log(45/2))——2mm→10、45mm→2 的对数刻度
# 来源：Weinstein 1968（经典卡尺系）；Sato 1999（舌1.7/上唇2.4/下颌5.5/掌7.5）；
# Won 2017 PMC5595116（唇~6/舌尖~5/指尖~5，力控仪器，提示卡尺值可能高估）；
# 汇总见 Physiopedia Weber 2PD 词条；指尖静态 2PD <6mm 为临床正常（Washington University Nerve Surgery）
TPD_REFERENCE = {   # 部位 → (典型 mm, 映射 sens)
    "唇": (3.2, 9), "指尖": (3.0, 9), "舌尖": (1.7, 10),
    "面颊": (5.5, 7), "手掌": (9.0, 6), "前额": (15.0, 5),
    "颈": (17.0, 5), "锁骨区": (20.0, 4), "肩": (22.0, 4),
    "腕": (20.0, 4), "膝": (25.0, 4), "踝/足背": (23.0, 4),
    "脚底": (20.0, 4), "胸": (30.0, 3), "腹": (32.0, 3),
    "上臂/前臂": (35.0, 3), "小腿": (35.0, 3), "背": (38.0, 3),
    "腰": (36.0, 3), "大腿": (42.0, 2),
}
# 皮节神经链走向（相邻脊神经节段 = 天然传导链；来源 StatPearls Dermatomes / Kenhub / Medscape，
# Keegan&Garrett 1948 与 Foerster 1933 两图系并存有个体差异）：C4 锁骨→T4 乳头→T6 剑突→T10 脐→L1 腹股沟；
# 颈 C2-C4；臂 C5-T1；S2 大腿后侧-小腿。建 radiate 建议：同链相邻节段 0.2-0.3，跨链 0.1 左右
DERMATOME_NOTES = "C4=锁骨线 T4=乳头线 T6=剑突 T10=脐 L1=腹股沟 S2=大腿后-小腿；相邻节段传导 0.2-0.3"
TOLERANCE_GAIN = 0.03               # 每次事件耐受增量 = TOLERANCE_GAIN * S
TOLERANCE_FALL_PER_MIN = 0.01       # 耐受每分钟回落量
TOLERANCE_MAX = 0.6
COOL_SECONDS_AFTER_LOSE = 20        # lose 档后部位冷却时长（秒）
COOL_GAIN_FACTOR = 0.5              # 冷却内 gain 减半
HABITUATION_STREAK = 3              # 同一部位连续快速刺激达到此次数后触发习惯化
HABITUATION_WINDOW = 60             # 习惯化计数窗口（秒）：间隔超过则重新计数；同刻事件同组不重复计数
HABITUATION_FACTOR = 0.7            # 习惯化后 gain 乘数（收益递减，防连击堆数值）
# 敏感化 wind-up（文献：频率依赖时间总和，C 纤维 wind-up；重标定到 RP 分钟尺度——
# 突触 τ_rec≈0.75s→行为层 60s 的重标定同思路）：短间隔连击累积增益放大，与习惯化对偶，
# 使"重度持续刺激→过载"路径可达（修复基线发现的三重压制下过载不可达）
SENS_WINDOW = 45                    # 敏感化累积窗口：与前次事件间隔在此内才累积
SENS_GAIN = 0.24                    # 每次窗口内事件累积量 ×S（校准：三部位 20s 重度连击 ~15 轮可达过载）
SENS_CAP = 1.0                      # 敏感化上限（增益最多 ×2.0）
SENS_TAU = 90.0                     # 敏感化衰减 τ（文献锚：中枢感知适应 90-120s，Hollins 1990）
AFTERGLOW_SECONDS = 30 * 60         # overload 后余韵时长（秒）——面板键 vb_afterglow_seconds（300-7200）的常量默认
AFTERGLOW_SENS_MULT = 1.4           # 余韵期敏感度倍数（乘在刺激 S 上）——面板键 vb_afterglow_mult（1.0-2.0）默认
COOLDOWN_SECONDS = 20 * 60          # 余韵后不应期时长（秒）——面板键 vb_cooldown_seconds（300-7200）的常量默认
COOLDOWN_SENS_MULT = 0.6            # 不应期敏感度倍数，结束后回 baseline——面板键 vb_cooldown_mult（0.2-1.0）默认
OVERLOAD_AROUSAL = 0.85             # arousal 达到该值触发 overload（与 profile tiers.overload 对齐）
ACTIVE_AROUSAL_MIN = 0.05           # 部位参与 arousal 归一的活跃下限（静息部位不稀释权重）
OVERLOAD_WARN_MARGIN = 0.10         # building 期 arousal 距 overload 阈值不足此值时注入"快到极限"预警

# ---- 事件解析 ----
ACTION_WORDS = {                    # 动作词 → 强度 S（0-1）；只认词表，不做猜测。profile 可用同名键覆盖/追加
    "戳": 0.3, "碰": 0.4, "摸": 0.5, "拍": 0.5, "揉": 0.6,
    "抓": 0.7, "舔": 0.8, "掐": 0.8, "咬": 0.9,
    # 0.1.2 扩充：轻→重梯度补全
    "蹭": 0.3, "拂": 0.3, "吹": 0.25,
    "抚": 0.4, "拨": 0.4, "擦": 0.4,   # "擦"覆盖"擦过/擦拭"（单字子串命中）；档位同"抚"轻触档
    "挠": 0.5, "搓": 0.6, "亲": 0.6,
    "捏": 0.7, "拽": 0.7, "揪": 0.7,
    "吮": 0.9,
}   # "含"字因"包含/含有"高频歧义于 0.1.7 移除
TOUCH_INTENSITY_WORDS = {"轻": 0.3, "中": 0.6, "重": 1.0}   # /touch 强度词；也接受 0-1 数字
NEGATION_PREFIXES = ("别", "不要", "不准", "不许", "禁止", "莫", "勿", "不可以")   # 动作词前出现即视为拒绝，不触发事件
# 强度修饰词：出现在动作词邻域时乘算强度（查漏补缺——"狠狠揉"≠"轻轻揉"）
INTENSITY_MODIFIERS = {
    "轻轻": 0.55, "轻柔": 0.6, "慢慢": 0.75, "稍": 0.8,
    "用力": 1.3, "狠狠": 1.45, "大力": 1.3, "使劲": 1.35, "死死": 1.4,
}
EVENT_TYPE_DEFAULT = "touch"

# ---- 动作词参数化（0.29.0）----
# action_words 值支持两种形态（向后兼容）：旧 "揉": 0.6 等价 {"揉": {"s": 0.6}}；
# 新形态全键可选：{"s","method","freq_hz","speed_cm_s","depth","temp_c","cooldown_s","type"}
ACTION_WORD_TYPES = ("touch", "pain", "temp", "air", "constrain")   # type 语义类别枚举
ACTION_WORD_METHODS = ("stroke", "press", "rub", "tap", "blow")   # method 可选值（页面"自动"=不落该键，按词判定）
# 事件级参数值域（越界键丢弃、回词默认——与 _action_words 归一化约定一致）
ACTION_WORD_PARAM_LIMITS = {
    "freq_hz": (0.0, 500.0),        # Hz——揉搓 Meissner 带 5-50 / 拍打 Pacinian 带 100-300
    "speed_cm_s": (0.0, 200.0),     # cm/s——抚摸 CT 速度窗 1-10
    "depth": (0.0, 1.0),            # 压深 0-1（按压方式）
    "temp_c": (0.0, 60.0),          # °C——吹气/温度类，32°C 肤温峰
    "cooldown_s": (0.0, 3600.0),    # 词级冷却秒（0=无冷却，旧行为）
}
# type 语义类别增益微调（全部 CONFIG 可调；默认值保证旧词表——全 touch——行为逐位不变）
TYPE_PAIN_LOW_SENS_MAX = 4.0       # sens ≤ 此值视为低敏部位
TYPE_PAIN_LOW_SENS_MULT = 1.2      # 痛类对低敏部位倍率——痛觉广谱受体（nociceptor）全身分布均匀，
                                   # 钝区对触碰迟钝但对痛不迟钝（Derbyshire 2000 系综述的方向性常识）
TYPE_TEMP_THERMAL_COEFF = 0.4      # 温度类受材质热导调制：×(1+系数×thermal)——金属/冰放大温差感
TYPE_TEMP_WARM_COEFF = 0.3         # 温度类受材质保温性放大：×(1+系数×warm_hold)——保温材质让温感停留更久
TYPE_AIR_EXPOSED_MULT = 1.1        # 气流类对 flags 含 exposed 的暴露部位倍率——裸露皮肤气流感受更直接
ACTION_WORD_CD_FACTOR = 0.5        # 词级冷却内命中增益乘数（防复读同一词刷值）

# ---- 注入渲染 ----
RENDER_MAX_CHARS = 400              # 注入块字符上限（含标签）
SHOW_NUMBERS_TO_MODEL = True
RENDER_MIN_AROUSAL = 0.15           # building 期低于该兴奋度不注入（无档位可报，纯噪音）；余韵期不受此门控
RENDER_FOLD_BELOW = 0.05            # 部位数值低于该值且无档位时不渲染（token 纪律）
RENDER_COMPACT = True               # 注入用紧凑形态（一位小数锚点+精简头尾，LLM 对数编码下两位小数无增益）
TREND_EPS = 0.01                    # 趋势判定阈值：窗口增量超过此值显示 ↑/↓，否则 →（借鉴 ST 状态系统）

# ---- 时区与昼夜节律（借鉴 ST 状态系统的时段维度）----
TZ_UTC_OFFSET = None               # None=用容器本地时区；Docker 容器为 UTC 时设 8（北京时间）。昼夜节律与"今日"日切共用

# ---- 筋膜链与体感（医学依据：Myers《Anatomy Trains》肌筋膜经线；链上缺部位自动跳过）----
FASCIA_CHAINS = {
    "后侧链": ["sole", "calf", "thigh", "tail_root", "lower_back", "spine", "nape", "head_top"],   # 浅背线
    "前侧链": ["instep", "shin", "thigh", "belly", "chest", "neck_front"],                          # 浅前线
    "侧链":   ["ankle", "waist", "flank_l", "flank_r", "shoulder", "nape"],                          # 侧线
    "臂链":   ["shoulder", "arm", "elbow_l", "elbow_r", "forearm_l", "forearm_r", "wrist", "palm"],  # 臂线（前后合并）
}
FASCIA_TENSION_TAU_MULT = 1.2       # 链张力>阈值时该链部位衰减 τ 放缓（肌肉紧张让敏感消退变慢）
FASCIA_TENSION_THRESHOLD = 0.35     # 链张力阈值（链上静息部位会稀释加权均值，阈值得留灵敏度）
# 自主神经体感分级（派生自 arousal/部位状态，渲染进注入块）
AUTONOMIC_BREATH = [(0.6, "呼吸急促"), (0.35, "呼吸变浅"), (0.0, "呼吸平稳")]
AUTONOMIC_HEART = [(0.6, "心跳很快"), (0.35, "心跳偏快"), (0.0, "心跳平稳")]
TREMOR_THRESHOLD = 0.4              # 颤抖：链张力或部位 boost 超阈即轻颤

# ---- 动作可行性层（依据：AAOS 关节活动度标准 + 人体测量常识）----
SELF_REACH_HINT = "自身双手可及正面与腿前；颈后中段、背中、骶尾自手不可及（需对方或借物）"   # 注入用固定短行（措辞避开部位名，防折叠断言误触）
POSTURE_DIFF_MIN = 15               # 身高差超过该值（cm）才注入姿态提示
# phase 专属约束追加（overload 后两阶段给模型行为指向——含姿态信息，building 无追加）
PHASE_HINTS = {
    "afterglow": "；余韵未散，此刻格外敏感，四肢发软",
    "cooldown": "；不应期，刺激反应迟钝，全身乏力",
}
CIRCADIAN_ENABLED = True
CIRCADIAN_NIGHT_MULT = 1.1          # 深夜刺激敏感度倍数（乘在 s_eff 上）
CIRCADIAN_NIGHT_WINDOW = (23, 5)    # 夜间窗口（小时）：23:00-次日 05:00，跨午夜
# 面板键 vb_night_window 的默认文案（"起-止"小时，止<=起视为跨午夜）；解析在 decay.parse_night_window
VB_NIGHT_WINDOW_DEFAULT = "23-5"
TIER_LABELS = {"notice": "注意", "react": "反应", "lose": "失控", "overload": "过载"}
TYPE_STALE_SECONDS = 600            # 接触类型显示时效：超过该时长不再渲染"·舔"类标签（防过时信息误导模型）
# 约束行固定文案 + 按档位追加句长约束。措辞纪律（LLM 注入调研）：
# 全正向表述（否定式指令遵循差，DECRIM/MonitorBench）；句长用区间语义不用硬边界（字符级计数最不可靠，46 模型实测）
RENDER_CONSTRAINT_FIXED = "把反应藏进动作里；动作先于台词；状态由系统跟踪，回复只含对话与动作"
# 面板键 vb_constraint_text 的默认即上行（用户改文案后紧凑/完整两形态的固定段都换成自定义文本）
# 面板键 vb_feel_word_ttl 的常量默认沿用 MATERIAL_STALE_SECONDS（600，60-3600）

# 档位 → 表达/语音参数（第 9 节映射表）；接 TTS 时原样输出该 dict 作为参数字典
TIER_EXPRESSION = {
    "notice":   {"max_sentence_len": 30, "speech_rate": 1.0,  "breath_ratio": 0.0, "pauses": 0},
    "react":    {"max_sentence_len": 24, "speech_rate": 0.95, "breath_ratio": 0.1, "pauses": 1},
    "lose":     {"max_sentence_len": 16, "speech_rate": 0.85, "breath_ratio": 0.3, "pauses": 2},
    "overload": {"max_sentence_len": 10, "speech_rate": 0.7,  "breath_ratio": 0.5, "pauses": 3},
}
# 档位句长约束追加进注入"约束"行（区间语义，非硬边界——LLM 数值/字符级计数不可靠）
TIER_SENTENCE_HINT = {
    "notice": "", "react": "；句子短促，二十字上下",
    "lose": "；句子破碎，十字出头", "overload": "；只吐几个词",
}

# ---- LLM 兜底抽取 ----
LLM_FALLBACK_DAILY_LIMIT = 20       # 每日上限（省额度铁律：超限直接跳过，不重试）
LLM_FALLBACK_TIMEOUT_SECONDS = 12
LLM_FALLBACK_PROMPT = (
    '从消息抽取身体接触事件，只输出JSON：{"part":"部位","intensity":0-1,"type":"类型"}；无接触则输出{"none":true}'
)

# ---- 状态存储 ----
STATE_SCHEMA = 1
STATE_DIR_NAME = "state"
STATE_FILE_FMT = "{character}_{session}.json"
BINDINGS_FILE = "bindings.json"     # session→character 会话绑定表（/vbody 指令维护）

# ---- phase 敏感度倍数查表（overload 后两阶段；building 恒 1.0）----
PHASE_SENS_MULT = {"building": 1.0, "afterglow": AFTERGLOW_SENS_MULT, "cooldown": COOLDOWN_SENS_MULT}

# ---- 空间层常量（并入自 manor CONFIG，P0 前缀化防撞） ----
SP_DEFAULT_MOVE_SPEED_MPS = 1.2        # 兜底步速（米/秒）——边缺 seconds 时按几何距离折算
SP_GATE_ROOM_WORDS = ("哪", "哪里", "位置", "过来", "在哪", "在吗")   # 门控④：位置类问题词
SP_INJECT_RECENT_CHANGE_SECONDS = 600  # 门控①：位置/同室状态 10 分钟内变过
SP_MANOR_OVERRIDE_DIR = "manor"        # plugin_data 下用户覆盖层目录（manor.json 用户版）
SP_PLAN_STALE_MINUTES = 90             # PC 日程项超过该时长无更新视为失效
SP_RENDER_MAX_CHARS = 160              # 注入块上限（规范 4.3）
SP_ROOM_ID_RE = r"[a-z][a-z0-9-]*"     # 房间 id 规则（禁下划线——状态文件名前科）
SP_RP_CONFIDENCE_DIRECT = 0.9          # 显式陈述（"我在书房"）
SP_RP_CONFIDENCE_INFER = 0.6           # 上下文推断（她说"过来"后他回复）
SP_RP_CONFIDENCE_MOVE = 0.7            # 文本抽取移动的置信度
SP_RP_OVERRIDE_MINUTES = 120           # RP 覆盖有效期（分钟），过期回落日程/兜底
SP_SESSION_RE = r"[A-Za-z0-9_:\-]+"    # session 白名单（防路径穿越）
SP_STATE_DIR_NAME = "state"
SP_STATE_SCHEMA = 1
SP_TICK_SECONDS = 60                   # 定时推进周期（秒），无消息也照跑
# ---- 空间渲染文案/阈值的面板键默认（0.27.9 下放；解析与消费在 core/render.py）----
SP_ETA_THRESHOLDS_DEFAULT = "15,60"          # 距离档阈值（秒，升序两档：马上就到/还要一会儿/得走一阵）
SP_HEARING_SAME_FLOOR_DEFAULT = "隔着楼层，难闻声息"   # 异层听觉文案（键名沿用面板历史口径）
SP_HEARING_ADJACENT_DEFAULT = "隔壁，可闻动静"         # 隔壁听觉文案

# ---- L2-B 存在桥（锚点 8：空间事件→身体体感联动；强度默认轻微，绝不自动触发过载）----
PRESENCE_BRIDGE_ENABLED = True         # 桥总开关（面板键 presence_bridge_enabled 与此相与，任一 False 即关）
PRESENCE_PROXIMITY_GAIN = 0.05         # 她落位到他所在房间 → 最敏感非占位部位一条 proximity 事件（type=space）的刺激强度
PRESENCE_LEAVE_FALL = 0.03             # 她离开他所在房间 → 该部位体感直接回落量（decay 事件通道只有正向，回落由 bridge 直接施加）
PRESENCE_COOLDOWN_SECONDS = 300        # 同室反复进出不重复计（进出共用一本账）；兼作"刚落位"新鲜窗——久处同室不重计

# ---- 材质触觉层（神经触觉深化：材质×部位×接触方式×频率的医学文献量化；数字锚点与文献 URL 见 data/materials.json _refs）----
# CT 情感触觉 1-10cm/s 慢扫峰/肤温 32°C 峰（Ackerley 2014）、Meissner 5-50Hz、Pacinian 100-300Hz、
# Weinstein 2PD 部位差（sens 即其对数映射）、羊毛 ≥30µm 纤维刺痒阈值——乘数模型见 core/material.py
MATERIAL_ENABLED = True          # 材质层总开关：False 时材质识别/增益/感受词标签全部旁路（回无材质行为）
MATERIAL_MATCH_WINDOW = 10       # 文本抽取：材质词与部位词的就近配对窗口（字符）——跨句/远处的材质不算
MATERIAL_STALE_SECONDS = 600     # 注入渲染：材质感受词显示时效（秒），与 TYPE_STALE_SECONDS 同量级防过时
MATERIAL_GAIN_MIN = 0.4          # 材质乘数下限（刺痒/重压过载感的增益地板）
MATERIAL_GAIN_MAX = 1.8          # 材质乘数上限（CT 峰值慢扫的天花板）

# ---- 材质参数扩展（0.29.0）：四可选参数 + 方式级覆盖，缺省即中性值、现行为逐位不变 ----
# friction 摩擦系数 0-1：织物-皮肤摩擦系数 µ 约 0.5-0.7（Temel 2023 体区测绘的方向锚）——
# 中性值 0.5（缺省即 0.5），rub 增益 ×(0.7+friction×0.6)：0→×0.7 打滑（冰面）、0.5→×1.0 中性、1→×1.3 涩滞（橡胶）
MATERIAL_FRICTION_NEUTRAL = 0.5
MATERIAL_FRICTION_RUB_LO = 0.7
MATERIAL_FRICTION_RUB_SPAN = 0.6
# thickness 厚度 0-1：厚织物吸收高频振动（衬垫减振常识）——tap 增益 ×(1-thickness×0.4)：0→×1.0、1→×0.6
MATERIAL_THICK_TAP_DAMP = 0.4
# warm_hold 保温性 0-1：保温层让皮肤-气流温差衰减变慢（热扩散时间常数随热阻增大，传热学常识）——
# blow 舒适窗宽 ×(1+0.6×warm_hold)；temp 类事件增益 ×(1+TYPE_TEMP_WARM_COEFF×warm_hold)
MATERIAL_WARM_HOLD_WINDOW = 0.6
# pattern_mm 纹理间距 mm：>2mm 为宏观粗纹理（两点辨别阈上限量级，Weinstein 系）——
# 拍打时粗纹理冲击面产生宏观振动、与 Pacinian 频带交互强化：tap 增益 ×(1+0.25×clamp01((mm-2)/10))
MATERIAL_PATTERN_BASE_MM = 2.0
MATERIAL_PATTERN_SPAN_MM = 10.0
MATERIAL_PATTERN_TAP_COEFF = 0.25
# method_gains 材质级方式乘数覆盖（如羽毛 tap 放大、皮革 rub 抑制）：{方式: 0.4-1.8}，缺省 1.0
MATERIAL_METHOD_GAIN_RANGE = (0.4, 1.8)

# ---- 部位级细调参数（0.29.1）：parts[] 可选键，缺省中性 1.0 = 行为逐位不变 ----
# 五键接口契约（键名一字不差）：gain_mult 部位总增益倍率（event_gain 里乘）；
# tolerance_mult 该部位耐受积累倍率；windup_mult 该部位敏感化累积倍率；
# type_mults {type: 倍率} 部位×类别交互（键∈ACTION_WORD_TYPES 五类，如尾根 {"air":1.5}）；
# material_affinity {材质id: 倍率} 部位×材质亲和（如舌尖 {"silk":1.4}）。
# 演算接入 core/decay.py（坏值/越界回中性 1.0），校验 state.validate_parts + web_api 保存链路
PART_GAIN_MULT_RANGE = (0.3, 3.0)          # gain_mult 值域
PART_TOLERANCE_MULT_RANGE = (0.2, 3.0)     # tolerance_mult 值域
PART_WINDUP_MULT_RANGE = (0.3, 3.0)        # windup_mult 值域
PART_TYPE_MULT_RANGE = (0.3, 3.0)          # type_mults 值域（键须为五类 type 之一）
PART_MATERIAL_AFFINITY_RANGE = (0.4, 2.5)  # material_affinity 值域（键=材质 id）

# ---- 心绪编排常量（0.27.0 并入，数据落 plugin_data/mood/） ----
MO_TICK_SECONDS = 60
MO_TRIGGER_TTL_SECONDS = 1800
MO_RULES_FILE = "rules.json"
MO_TRIGGER_FILE = "triggers.json"
MO_LAST_STATE_FILE = "mood_last_state.json"
MO_COOLDOWNS_FILE = "mood_cooldowns.json"
MO_HISTORY_FILE = "mood_history.json"
MO_HISTORY_LIMIT = 100
MO_DATA_SUBDIR = "mood"

# ---- 天气常量（0.27.0 并入 weather_ez） ----
WEATHER_TOOL_DIR_NAME = "ez_weather"
WEATHER_DEFAULT_CITY = "东莞"
WEATHER_SNAPSHOT_SUBDIR = "weather"
WEATHER_SNAPSHOT_FILE = "weather_last.json"
WEATHER_SNAPSHOT_MAX_CHARS = 500
WEATHER_QUERY_TIMEOUT = 40

# ---- 心绪信号源路径（跨插件只读：洞察/书柜；天气与存在层为内部读取） ----
MO_LEGACY_WEATHER_DIR = "astrbot_plugin_weather_ez"    # 旧插件数据回退（迁移期）
MO_SRC_MOOD_FILE = "insight_center/insight_center/mood_calibration.json"
MO_SRC_BOOKSHELF_DIR = "astrbot_plugin_bookshelf"
MO_RAIN_WORDS = ("雨", "rain", "shower", "drizzle", "thunder", "storm")
MO_WEATHER_TEXT_KEYS = ("weather", "condition", "dayText", "text")
# 0.32.0 天气 TTL：快照超过该时长未更新视为过期——read_weather 返回 available=False/is_rain=None
# （过期不当真：rain_care/rain_veranda 不触发、雨天动线不映射室内），stale=True 标注过期形态
MO_WEATHER_TTL_SECONDS = 6 * 3600
# 0.32.0 他位置兜底：he.room 未知而她已落位 → 推断他在她身边（he_room=she_room），
# 该推断的置信度（低于显式陈述 0.9/上下文推断 0.6——只是默认假设）
MO_HE_INFER_CONFIDENCE = 0.5

# ---- 语言调情→身体兴奋（0.30.0：用户核心诉求"两个人语言上调情会让身体兴奋度提高"） ----
# 信号源：PC companions.json 的 users.<QQ>.intent_profile.emotion（用户当前情绪标签），
# 命中亲密情绪集 → is_intimate=True → verbal_arousal 爬升。读法只读+mtime 缓存，绝不写 PC 目录。
VERBAL_AROUSAL_RATE = 0.006           # intimate 时每次调用的爬升量（tick 60s 一轮，~10 分钟聊满一半）
VERBAL_AROUSAL_CAP = 0.35             # verbal 单独撑起的兴奋上限（合成后 ×weight，托底不越界）
VERBAL_AROUSAL_TAU = 900.0            # 非 intimate 时指数衰减 τ（秒）——氛围散去半小时内回落
VERBAL_AROUSAL_WEIGHT = 0.8           # 合成权重：arousal = max(physical, verbal × weight)
VERBAL_AROUSAL_TAU_RANGE = (300.0, 7200.0)   # 面板/参数链值域
VERBAL_AROUSAL_RATE_RANGE = (0.0, 0.05)
VERBAL_AROUSAL_CAP_RANGE = (0.1, 0.6)
VERBAL_AROUSAL_WEIGHT_RANGE = (0.2, 1.5)
VERBAL_RENDER_MIN = 0.1               # verbal 高于此值才渲染"语言撩拨"段（token 纪律）
VERBAL_INTIMATE_EMOTIONS = ("praise", "comfort", "comfort_need",
                            "love", "intimate", "flirty", "happy", "excited",
                            "撒娇", "心动", "喜欢")   # 亲密情绪集（匹配小写化；vb_verbal_emotions 覆盖）
# 0.30.1：前三项是 PC 实际枚举的亲密子集（原 love/flirty 集与 PC 枚举交集空致语言调情恒 0）

# ---- 长期身体记忆（0.30.0 日级适应层：身体会"记住"近一周的触碰模式） ----
ADAPT_ENABLED = True                  # 总开关（面板键 vb_adaptation_enabled 与此相与）
ADAPT_WINDOW_DAYS = 7                 # 统计窗口（天）——history 流水扩容到 200 条供回溯
ADAPT_FREQ_THRESHOLD = 12             # 窗口内直接命中次数 > 此值 → 长效敏感化
ADAPT_SENSITIZE_PER_DAY = 1.01        # 高频部位 +1%/天
ADAPT_DULL_PER_DAY = 0.992            # 零触碰部位（原 sens≥5）-0.8%/天
ADAPT_MULT_RANGE = (0.8, 1.3)         # 长效系数钳制（-20% ~ +30%）
ADAPT_DULL_MIN_SENS = 5.0             # 迟钝化只作用于原本就有感觉的部位（sens≥5）
ADAPT_HISTORY_LIMIT = 200             # history 流水上限（长期记忆的数据面；旧 20 条兼容裁剪）

# ---- 情绪↔身体耦合（0.30.0 双向轻管道） ----
MOOD_COUPLE_ENABLED = True            # 总开关（面板键 vb_mood_coupling_enabled 与此相与）
MOOD_COUPLE_LOW = -0.3                # mood score 低于此 → 低落：全局增益×0.92、overload 阈值+8%（绷着）
MOOD_COUPLE_LOW_GAIN = 0.92
MOOD_COUPLE_LOW_THR = 0.08
MOOD_COUPLE_HIGH = 0.5                # 高于此 → 愉悦：全局增益×1.05
MOOD_COUPLE_HIGH_GAIN = 1.05
MO_BODY_HINT_FILE = "body_mood_hint.json"   # 身体→情绪：overload 进余韵时写 mood/ 下（read_mood 融合）
MO_BODY_HINT_TTL = 7200.0             # warm hint 有效期（2h 内线性衰减）
MO_BODY_HINT_BOOST = 0.15             # 满强度加成（余韵刚结束时最大）

# ---- 持续接触（0.31.0 体验修复一：接触一旦建立就自动延续，不需要每句都重新描述） ----
# 建立：直接事件落账 state.active_contact[pid]（core/persist_contact）；延续：双通道——
# 消息驱动（对话在场每条消息给一次 s×rate 延续增益并刷新续期锚点）+ tick 补充
# （每 tick_every 个 tick 一发、不刷锚点）；否定："别摸耳朵"经 events.extract_stops 清除；
# 过期：距最近一次对话超 max_gap 清除；overload 进余韵时 decay 清全部。
CS_PERSIST_ENABLED = True             # 总开关（面板键 cs_persist_enabled 与此相与）
CS_PERSIST_RATE = 0.4                 # 延续增益 = 原强度 × 此率（每次延续给原强度的 40%）
CS_PERSIST_RATE_RANGE = (0.2, 0.8)
CS_PERSIST_MAX_GAP = 300              # 消息间隔窗（秒）：超出即过期清除（默认 5 分钟）
CS_PERSIST_MAX_GAP_RANGE = (60, 600)
CS_PERSIST_TICK_EVERY = 3             # tick 通道频率：每 N 个 tick 叠一次延续
CS_PERSIST_MSG_MIN_GAP = 20.0         # 消息通道最小间隔（秒）：同一条消息的观察器/注入双推进只计一次增益

# ---- 亲密语境增益加成（0.31.0 体验修复二：她已经有感觉时新刺激更容易被推高） ----
# advance_state 对本轮每个事件（含持续接触延续事件）的 event_gain 结果乘 boost——
# 两条件取最大值不叠乘；无命中回 1.0（行为不变）。倍率面板键 vb_intimacy_boost_l1/l2。
# 0.32.1 死代码清理：INTIMACY_BOOST_SLEEP 同眠档移除（state 白名单封死写入，恒不触发）。
INTIMACY_BOOST_L1 = 1.3               # arousal > 0.15 或 verbal_arousal > 0.05（已经有感觉）
INTIMACY_BOOST_L2 = 1.5               # arousal > 0.35（接近 react，敏感度放大）
INTIMACY_BOOST_L1_RANGE = (1.0, 2.0)
INTIMACY_BOOST_L2_RANGE = (1.0, 2.5)
INTIMACY_BOOST_AROUSAL_L1 = 0.15      # L1 的 arousal 门槛（语义锚，不进面板）
INTIMACY_BOOST_VERBAL_MIN = 0.05      # L1 的 verbal_arousal 门槛
INTIMACY_BOOST_AROUSAL_L2 = 0.35      # L2 的 arousal 门槛

# ---- 主动触碰意图（0.30.0：对话氛围到了她也会想要） ----
PROACTIVE_TOUCH_ENABLED = True        # 总开关（面板键 vb_proactive_touch_enabled 与此相与）
PROACTIVE_TOUCH_AROUSAL = 0.45        # arousal ≥ 此值（且 building）才有主动意愿
PROACTIVE_TOUCH_VERBAL_MIN = 0.15     # verbal_arousal 须 > 此值（对话氛围在场，防纯数值驱动）
PROACTIVE_TOUCH_COOLDOWN = 4 * 3600   # 同一会话意图冷却（state 记 ts）
PROACTIVE_TOUCH_TTL = 1800.0          # 意图短语渲染时效（30 分钟内"她想…"才新鲜）
PROACTIVE_TOUCH_TEMPLATES = (         # 模板池（{part}=最活跃部位 label；渲染尾巴 ≤14 字）
    "想被他碰{part}",
    "想主动蹭他的手",
    "想让他抚摸{part}",
    "想被他多碰碰{part}",
    "盼他把手贴上{part}",
)
