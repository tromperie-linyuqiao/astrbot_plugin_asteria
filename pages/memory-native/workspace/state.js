/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */


export const asteriaWorkspaceState = {};

export const UI_CONTRACT_VERSION = "memory.page.ui.v2";

export const UI_DYNAMIC_ENDPOINTS = new Set([
  "/companion/personal-photo-data",
  "/maintenance/audit/apply",
  "/maintenance/audit/rollback",
]);

export const TRANSPARENT_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

export const VIEWS = {
  objects: { title: "知识图谱", hint: "查看关系边、跨窗口线程、时间线、记忆节点和互动协同概览。" },
  film: { title: "群聊记忆", hint: "查看群聊范围内可召回、可管理的结构化记忆。顶部开关作用于所有群聊窗口；单个窗口请到权限拓扑设置。" },
  microscope: { title: "检索与召回", hint: "对比全库管理检索与指定会话中的实际召回和过滤。" },
  relations: { title: "用户档案与记忆", hint: "按用户统一查看私聊、画像、偏好、称呼和关系记忆。顶部开关作用于所有私聊窗口；单个窗口请到权限拓扑设置。" },
  review: { title: "个人记忆", hint: "查看 Bot 自身的每日生活日程、相册、主观记忆和细化片段。" },
  archive: { title: "维护与配置", hint: "先选择维护任务或配置领域；编辑和审核继续使用当前记忆库。" },
  maintain: { title: "私聊记忆", hint: "查看私聊范围内的对话、偏好、事实和稳定记忆。顶部开关作用于所有私聊窗口；单个窗口请到权限拓扑设置。" },
};

export const PERSONAL_MEMORY_VIEW = {
  available: {
    title: "个人记忆",
    hint: "查看 Bot 自身的每日生活日程、相册、主观记忆和细化片段。",
    small: "日程 · 相册 · 主观",
  },
  unavailable: {
    title: "个人记忆不可用",
    hint: "Asteria 陪伴服务尚未提供当前范围的日程与细化，请在系统服务查看运行状态。",
    small: "等待陪伴服务",
  },
  error: {
    title: "个人记忆检测失败",
    hint: "陪伴服务状态暂时无法读取，请查看错误并重试。",
    small: "检测失败 · 可重试",
  },
};

export const SECONDARY_NAV = {
  objects: [
    { id: "overview", label: "图谱总览", sublabel: "关系、线程与时间线", badge: "总览" },
    { id: "relations", label: "图谱边", sublabel: "人物、话题、事实与记忆关联", badge: "图谱" },
    { id: "identity-relations", label: "身份关系", sublabel: "关系声明与原始依据", badge: "关系" },
    { id: "threads", label: "跨窗口线程", sublabel: "不同私聊/群聊之间的待办线索", badge: "线程" },
    { id: "timeline", label: "时间线", sublabel: "最近记录的事件节点", badge: "时间" },
    { id: "logs", label: "注入记录", sublabel: "当时选中资料与过滤原因", badge: "记录" },
    { id: "persona", label: "互动协同", sublabel: "表达权威 · 记忆触动 · 情绪连续性", badge: "协同" },
  ],
  microscope: [
    { id: "query", label: "召回测试", sublabel: "输入一句话模拟检索", badge: "测试" },
    { id: "hits", label: "命中记忆", sublabel: "查看检索结果", badge: "命中" },
    { id: "blocked", label: "过滤原因", sublabel: "查看被挡下的记忆", badge: "过滤" },
  ],
  archive: [
    { id: "maintenance", label: "维护 / 迁移 / 清理", sublabel: "维护、修复、导入与清理", badge: "维护" },
    { id: "conversation-import", label: "历史聊天导入", sublabel: "QQ 直读、文件与最近任务", badge: "导入" },
    { id: "core-memory", label: "长期约定与旧核心", sublabel: "当前维护入口 · 旧记录只读", badge: "资料" },
    { id: "config:core_memory", label: "核心记忆参数", sublabel: "启用状态、块数与字数预算", badge: "参数" },
    { id: "config:memory_capture", label: "记忆捕获", sublabel: "记录用户消息与稳定事实", badge: "捕获" },
    { id: "config:memory_summary", label: "长期总结", sublabel: "私聊 / 群聊模型与阈值", badge: "总结" },
    { id: "config:historical_chat_import", label: "导入参数", sublabel: "QQ 分页与分段上限", badge: "参数" },
    { id: "config:conversation_memory", label: "连续对话", sublabel: "群聊片段与低信息保护", badge: "连续" },
    { id: "retrieval", label: "检索召回", sublabel: "候选、Embedding、Rerank", badge: "召回" },
    { id: "config:memory_injection", label: "记忆注入", sublabel: "注入数量、字数与日志", badge: "注入" },
    { id: "config:context_orchestration", label: "注入编排", sublabel: "分槽调度与当前状态保护", badge: "编排" },
    { id: "config:private_companion_bridge", label: "记忆与陪伴协同", sublabel: "自身服务之间的状态协调与去重", badge: "联动" },
    { id: "config:visibility", label: "可见性", sublabel: "跨窗口默认边界", badge: "权限" },
    { id: "topology", label: "权限拓扑", sublabel: "可视化记忆权限矩阵", badge: "拓扑" },
    { id: "config:knowledge_graph", label: "图谱关联", sublabel: "节点、边与检索扩展", badge: "图谱" },
    { id: "config:memory_tools", label: "主动工具", sublabel: "回忆、记住、陪伴笔记", badge: "工具" },
    { id: "config:maintenance", label: "维护策略", sublabel: "备份、保留与自然衰减", badge: "维护" },
    { id: "config:appearance", label: "外观", sublabel: "拓展页主题", badge: "主题" },
  ],
};

export const CONFIG_ADVANCED_MODULES = {
  conversation_memory: "conversation_memory_advanced",
  context_orchestration: "context_orchestration_advanced",
  maintenance: "maintenance_decay",
};

export const CONFIG_ADVANCED_FALLBACKS = {
  "config:conversation_memory_advanced": "config:conversation_memory",
  "config:context_orchestration_advanced": "config:context_orchestration",
  "config:maintenance_decay": "config:maintenance",
  "config:livingmemory_migration": "maintenance",
  migration: "maintenance",
  clear: "maintenance",
};

export const CONFIG_MODULE_GUIDES = {
  retrieval: {
    purpose: "决定候选记忆怎么被找出来：本地检索负责稳，Embedding 负责语义补召回，Rerank 负责二阶段重排。",
    tune: "召回太少时启用 Embedding 或提高候选；召回太杂时提高相似度阈值或切回本地检索。",
    avoid: "权限问题不要用召回参数解决；无权限记忆不会进入候选池。",
  },
  memory_capture: {
    purpose: "控制是否把用户消息、Bot 回复、稳定事实和关系边写入记忆流水。",
    tune: "想减少数据库增长时先调最短记录字数或关闭普通消息记录；稳定事实通常建议保留。",
    avoid: "不要随意关闭稳定事实抽取，否则偏好、称呼、生日等长期信息会断档。",
  },
  memory_summary: {
    purpose: "把时间线整理成长期可召回的阶段性记忆，是从流水到长期记忆的主要入口。",
    tune: "可为私聊和群聊分别选择总结 Provider；总结太慢时提高触发阈值，总结不及时或连续性弱时降低最少事件数和触发条数。",
    avoid: "不要把单次总结事件上限调得过大，输入太长会降低总结质量。",
  },
  historical_chat_import: {
    purpose: "控制历史聊天的 QQ 分页读取、单次范围、分段和模型打包上限。",
    tune: "接口读取不完整时先缩短页面里的时间范围；只有确认适配器稳定后再提高分页扫描页数。",
    avoid: "不要把消息与打包上限同时拉满，过大的批次会增加接口等待、模型超时和人工核对成本。",
  },
  memory_injection: {
    purpose: "控制每轮主链请求前注入多少记忆、最多多少字，以及是否记录注入日志。",
    tune: "模型忽略记忆时提高条数或字数；被旧事带偏时降低 TopK 或关闭原始事件注入。",
    avoid: "记忆只是辅助资料，不应该替代当前用户消息。",
  },
  conversation_memory: {
    purpose: "记录连续对话线索，用于承接“继续”“还有呢”“刚才那个”等短句。",
    tune: "群聊承接弱时保留群聊普通发言记录；旧话题污染时加强低信息和新话题保护。",
    avoid: "它不是把最近 N 轮原文硬塞回模型，而是用于后续总结和检索。",
  },
  context_orchestration: {
    purpose: "把自我时间线、用户画像、当前窗口、阶段总结和稳定记忆分槽编排进注入包。",
    tune: "需要更强陪伴线索时调高对应分槽；当前状态问题被旧记忆抢答时保持相关性保护开启。",
    avoid: "不要让所有分槽都过大，总注入仍应服务当前问题。",
  },
  private_companion_bridge: {
    purpose: "由 Asteria 记忆与陪伴服务协调自我状态、私聊上下文和历史提示，减少重复注入。",
    tune: "看到主动提示或当前状态重复时保持去重开启；排障要看原始上下文时再临时保留外部片段。",
    avoid: "同一类当前状态保持单一来源，避免重复注入或把临时状态当作长期事实。",
  },
  visibility: {
    purpose: "控制私聊、群聊、自我时间线之间的默认可见边界。",
    tune: "跨窗口共享优先用权限拓扑配置对象级规则；全局开关只适合明确要整体放宽时使用。",
    avoid: "不要用全局共享解决单个群或单个人的问题。",
  },
  memory_tools: {
    purpose: "允许模型主动回忆、写入长期记忆或整理 Bot 自己的陪伴笔记。",
    tune: "需要模型自主记录时开启记住工具；担心误写时先只开回忆工具并观察日志。",
    avoid: "主动记忆工具不应替代阶段性总结，二者用途不同。",
  },
  knowledge_graph: {
    purpose: "从阶段性记忆中建立人物、话题和事实关联，用于图谱展示和检索扩展。",
    tune: "搜索人物/话题时漏召回可开启图谱一跳扩展；召回过宽时降低扩展上限。",
    avoid: "图谱扩展不会绕过权限，不要把它当权限共享开关。",
  },
  livingmemory_migration: {
    purpose: "控制 LivingMemory 旧库导入路径和单次导入上限。",
    tune: "迁移前先预览；旧库很大时分批导入并观察跳过原因。",
    avoid: "不要直接复制旧 SQLite 覆盖当前数据库。",
  },
  maintenance: {
    purpose: "控制备份、原始事件保留和长期旧记忆自然衰减。",
    tune: "数据库增长快时调整原始事件保留；旧碎片太多时开启自然衰减并设置合理阈值。",
    avoid: "自然衰减会归档旧碎片，首次开启前建议备份。",
  },
  appearance: {
    purpose: "控制拓展页主题显示。",
    tune: "只影响管理页外观，不影响记忆行为。",
    avoid: "外观配置不会改变召回、注入或权限逻辑。",
  },
};

export const OVERVIEW_LAYOUT_KEY = "memory_companion_overview_layout";

export const state = {
  stats: {},
  buckets: [],
  overviewLayout: document.documentElement.dataset.overviewLayout === "cinema" ? "cinema" : "standard",
  uiCapabilities: null,
  uiContractWarning: "",
  activeView: "objects",
  activeBucketId: "all",
  userMemoryFilter: "all",
  portraitProfiles: [],
  selectedPortraitPersonId: "",
  portraitGovernanceDetail: null,
  portraitGovernanceLoading: false,
  microscopeBucketId: "all",
  microscopeSearchToken: 0,
  bucketLoadToken: 0,
  activeMemoryId: "",
  secondaryNav: {},
  companionPersonalAvailable: null,
  companionPersonalError: "",
  personalDates: [],
  selectedPersonalDate: "",
  selectedScheduleIndex: "",
  selectedPersonalAlbumIndex: "",
  selectedSubjectiveMemoryIndex: "",
  personalViewport: "schedule",
  personalViewportSwitching: false,
  secondaryNavSwitching: false,
  animatePersonalViewportRail: false,
  personalSnapshot: null,
  personalData: null,
  animatePersonalDateRail: false,
  pendingPersonalFilmReveal: false,
  personalEntranceRevealRequested: false,
  personalAlignTimer: 0,
  historicalChatPreview: null,
  historicalChatPreviewSource: "",
  historicalChatBatchId: "",
  historicalChatBatches: [],
  historicalChatBatchQuery: "",
  historicalChatBatchFilter: "all",
  historicalChatBatchPage: 0,
  historicalChatBatchView: null,
  historicalChatOutcomes: new Map(),
  historicalChatTargetContextId: "",
  historicalChatTargetBuckets: [],
  historicalChatPollTimer: 0,
  historicalChatPollAttempts: 0,
  historicalChatPollStartedAt: 0,
  historicalChatFile: null,
  conversationImportSource: "qq",
  qqHistoryCapabilities: null,
  qqHistoryCapabilitiesLoading: false,
  memoryAuditBatch: null,
  memoryAuditUnconfirmedBatchId: "",
  coreMemoryBlocks: [],
  scopeControl: {
    private_capture_enabled: true,
    group_capture_enabled: true,
    private_recall_enabled: true,
    group_recall_enabled: true,
    private_topology_enabled: true,
    group_topology_enabled: true,
  },
  windowScopePolicies: {},
};

export const DEFAULT_THEME = "yuebai";

export const THEME_OPTIONS = [
  "huangbaiyou", "tianpiao", "haitianxia", "yingying", "oubi", "qingming", "zipu",
  "shanlan", "qielan", "tuihong", "congqing", "yuebai", "mocan", "gupiao",
];

export const THEME_ALIASES = {
  黄白游: "huangbaiyou",
  天缥: "tianpiao",
  海天霞: "haitianxia",
  盈盈: "yingying",
  欧碧: "oubi",
  青冥: "qingming",
  紫蒲: "zipu",
  山岚: "shanlan",
  窃蓝: "qielan",
  退红: "tuihong",
  葱倩: "congqing",
  月白: "yuebai",
  墨黪: "mocan",
  骨缥: "gupiao",
};

export const TRANSITION_FACES = [
  "(๑•̀ㅂ•́)و✧",
  "(。・ω・。)",
  "(*´▽`*)",
  "( •̀ ω •́ )✧",
  "(｡･∀･)ﾉﾞ",
  "(｀・ω・´)",
  "(つ≧▽≦)つ",
  "(＾▽＾)",
  "(´｡• ᵕ •｡`)",
  "(๑˃̵ᴗ˂̵)و",
  "(￣▽￣)ノ",
  "(ง •_•)ง",
  "喵~",
  "你瞅啥",
  "这是一个彩蛋",
];

export const SCREEN_FILM_EXTRA_HOLD_MS = 300;

export const OVERVIEW_TO_WORKSPACE_WIPE_WAIT_MS = 520 + SCREEN_FILM_EXTRA_HOLD_MS;

export const WORKSPACE_WIPE_CLEANUP_MS = 620 + SCREEN_FILM_EXTRA_HOLD_MS;

export const HOME_WIPE_SWAP_WAIT_MS = 320 + SCREEN_FILM_EXTRA_HOLD_MS;

export const HOME_WIPE_TOTAL_WAIT_MS = 980 + SCREEN_FILM_EXTRA_HOLD_MS;

asteriaWorkspaceState.railCoverflowFrame = 0;

asteriaWorkspaceState.workspaceTransitionToken = 0;

asteriaWorkspaceState.homeReturnRunning = false;

export const $ = (selector) => document.querySelector(selector);

export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export const MEMORY_PAGE_SIZE = 12;

export const KNOWLEDGE_SECTIONS = {
  relations: { title: "图谱边", path: "/graph", note: "保存的节点关联与来源依据；存在关联不代表来源当前可用或实际召回。", range: "按当前范围、会话和群标识查询；用户标识不单独过滤图谱边。" },
  "identity-relations": { title: "身份关系", path: "/relations", note: "已记录的关系声明；阅读原依据后再判断，不将推断当作确认事实。", range: "按当前对象、范围、会话和群标识查询。" },
  threads: { title: "跨窗口线程", path: "/threads", note: "阅读待续线索，按需标记完成或重新打开。状态只维护此条记录，不代表发送、撤回消息或取消后台任务。", range: "按起点或终点会话查询；未指定会话时返回近期线程，不按单个用户或群标识筛选。" },
  timeline: { title: "时间线", path: "/timeline", note: "原消息、事件与整理记录按记录时间排列；记录本身不等于长期记忆。", range: "按当前对象、范围和会话查询。" },
  logs: { title: "注入记录", path: "/logs", note: "查看当时查询、选中记忆和过滤原因；日志不证明模型已经使用或采纳资料。", range: "按当前范围和会话查询，不按单个用户或群标识筛选。" },
};

asteriaWorkspaceState.knowledgeReadSerial = 0;

asteriaWorkspaceState.knowledgeBrowse = null;

export const portraitBrowse = {query: "", mode: "", page: 0, factQuery: "", factStatus: "", factPage: 0, expanded: false};

asteriaWorkspaceState.portraitListRequest = 0;

asteriaWorkspaceState.portraitDetailRequest = 0;

asteriaWorkspaceState._topologyState = { data: null, selectedNode: null, selectedPair: null, busy: false };

export const CORE_MEMORY_KIND_LABELS = {
  rule: "规则",
  boundary: "边界",
  preference: "偏好",
  profile: "画像",
  fact: "事实",
  state: "稳定状态",
};

export const CORE_MEMORY_SCOPE_LABELS = {
  global: "全局 / Bot",
  private: "私聊用户",
  group: "群聊",
};

export const coreHistory = {query: "", kind: "", scope: "", enabled: "", page: 0, request: 0};
