/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {postJson} from './client.js';
import {tokenTaskLabel} from './learning.js';
import {setActionBusy,showToast} from './persona.js';
import {formatProactiveDailyQuota,formatProactiveLimit,visibleFeatureSwitchKey,visibleTopLevelFeatureKeys} from './schema.js';
import {escapeRegExp} from './settings.js';
import {browsingHistoryItemHtml,formatCompactNumber,historyWithoutLatest,insightStatus} from './setup.js';
import {$,featureGroups,state,troubleshootingCategories} from './state.js';
import {escapeHtml,loadDiagnostics,loadTroubleshooting} from './workspace.js';

export function renderWebExplorationPanel() {
  const exploration = state.overview?.web_exploration || {};
  const digest = exploration.last_digest || {};
  const query = exploration.last_query || {};
  const history = (Array.isArray(exploration.history) ? exploration.history : [])
    .filter((item) => item && item.source !== "news");
  const enabled = Boolean(exploration.enabled);
  const recentWebHistory = history[history.length - 1] || {};
  const earlierWebHistory = historyWithoutLatest(history);
  const displayTitle = digest.topic || recentWebHistory.title || query.query || "暂无主动搜索记录";
  const displayNote = digest.note || recentWebHistory.intro || recentWebHistory.content || (enabled ? "等待下一次主动搜索留下笔记。" : "主动搜索未开启");
  const displayTime = exploration.last_explore_at || recentWebHistory.generated_at || recentWebHistory.date || "未搜索";
  const backendLabel = exploration.search_backend === "custom"
    ? "自定义搜索接口"
    : exploration.search_backend === "astrbot"
      ? "AstrBot 网页搜索"
      : "搜索未配置";
  const historyHtml = earlierWebHistory.length
    ? earlierWebHistory.map((item) => browsingHistoryItemHtml(item, "主动搜索")).join("")
    : `<li class="empty-line browsing-history-empty">暂无更早搜索记录</li>`;
  $("#webExplorationPanel").innerHTML = `
    <div class="insight-head">
      <div>
        <span class="eyebrow">${enabled ? "主动搜索" : "未开启"}</span>
        <b>${escapeHtml(displayTitle)}</b>
      </div>
      <small>${escapeHtml(displayTime)}</small>
    </div>
    <p>${escapeHtml(displayNote)}</p>
    <div class="insight-meta">
      <span>${escapeHtml(insightStatus(exploration.last_status))}</span>
      <span>${escapeHtml(backendLabel)}</span>
      <span>${exploration.boredom_search_enabled ? "空档搜索开启" : "空档搜索关闭"}</span>
      <span>搜索历史 ${escapeHtml(exploration.history_count ?? history.length)} 条</span>
    </div>
    <div class="insight-history-head">
      <b>更早搜索</b>
      <span>最近一次已在上方展示</span>
    </div>
    <ul class="browsing-history-list">${historyHtml}</ul>
  `;
}

export function moduleShortcutNote(overview) {
  const settings = overview?.settings || {};
  const features = overview?.features || {};
  const items = [
    ["主动触达", Number(settings.max_daily_messages || 0) > 0 || Boolean(features.enable_group_companion || settings.enable_group_companion)],
    ["状态日程", Boolean(features.enable_humanized_states || settings.enable_humanized_states)],
    ["群聊观察", Boolean(features.enable_group_companion || settings.enable_group_companion)],
    ["关系网", Boolean(features.enable_worldbook_member_recognition || settings.enable_worldbook_member_recognition)],
    ["记忆学习", Boolean(features.enable_companion_memory || settings.enable_companion_memory)],
    ["长期创作", Boolean(features.enable_creative_writing || settings.enable_creative_writing)],
    ["新闻阅读", Boolean(features.enable_news_integration || settings.enable_news_integration)],
    ["主动搜索", Boolean(features.enable_web_exploration || settings.enable_web_exploration)],
    ["QQ 空间", Boolean(features.enable_qzone_integration || settings.enable_qzone_integration)],
  ];
  if (overview?.private_reading?.available) {
    items.push(["夹层阅读", Boolean(features.enable_private_reading_integration || settings.enable_private_reading_integration)]);
  }
  const enabledItems = items.filter(([, enabled]) => enabled);
  const preview = enabledItems.slice(0, 3).map(([label]) => label).join(" / ");
  const external = overview?.external_abilities?.enabled_count || 0;
  const suffix = external ? ` · 外部 ${external}` : "";
  return `${enabledItems.length}/${items.length} 个主要模块开启${preview ? ` · ${preview}` : ""}${suffix}`;
}

export function providerShortcutNote(providers) {
  const configured = Object.values(providers || {}).filter((value) => String(value || "").trim()).length;
  return configured ? `${configured} 个 Provider 已指定` : "使用默认回退链";
}

export function renderHealthPanel() {
  const overview = state.overview || {};
  const providers = overview.providers || {};
  const group = overview.group || {};
  const privateInfo = overview.private || {};
  const features = overview.features || {};
  const bili = overview.bilibili || {};
  const creative = overview.creative || {};
  const cache = overview.cache || {};
  const imageCache = cache.private_image_vision || {};
  const imagePrivateMetric = imageCache.private || {};
  const imageForwardMetric = imageCache.forward || {};
  const imageHits = Number(imagePrivateMetric.hits || 0) + Number(imageForwardMetric.hits || 0);
  const imageMisses = Number(imagePrivateMetric.misses || 0) + Number(imageForwardMetric.misses || 0);
  const imageTotal = imageHits + imageMisses;
  const imageHitRate = imageTotal ? Math.round((imageHits / imageTotal) * 100) : 0;
  const proactiveEffectiveMax = state.overview?.proactive_intensity?.effective?.max_daily_messages ?? privateInfo.max_daily_messages ?? 0;
  const proactiveEffectiveMaxUnlimited = Boolean(state.overview?.proactive_intensity?.effective?.max_daily_messages_unlimited);
  const proactiveEffectiveMaxText = state.overview?.proactive_intensity?.effective?.max_daily_messages_text || formatProactiveLimit(proactiveEffectiveMax, proactiveEffectiveMaxUnlimited);
  const items = [
    {
      level: providers.LLM_PROVIDER_ID ? "ok" : "warn",
      title: providers.LLM_PROVIDER_ID ? "主模型已配置" : "主模型未单独配置",
      text: providers.LLM_PROVIDER_ID || "会回退到 AstrBot 默认模型",
    },
    {
      level: Number(proactiveEffectiveMax || 0) > 0 ? "ok" : "warn",
      title: Number(proactiveEffectiveMax || 0) > 0 ? "私聊主动可用" : "私聊主动已禁用",
      text: `每日主动上限：${proactiveEffectiveMaxText}`,
    },
    {
      level: group.enabled ? "ok" : "warn",
      title: group.enabled ? "群聊观察已开启" : "群聊观察未开启",
      text: `${group.access_mode || "whitelist"} 模式，记录 ${group.group_count || 0} 个群`,
    },
    {
      level: overview.livingmemory?.conflict
        ? "warn"
        : features.enable_livingmemory_integration && (overview.livingmemory?.compatible_available || overview.livingmemory?.available || overview.livingmemory?.memory_companion_active) ? "ok" : "info",
      title: "外部记忆插件协同",
      text: livingMemoryHealthText(overview.livingmemory),
    },
    {
      level: features.enable_bilibili_integration ? (bili.available ? "ok" : "info") : "info",
      title: "B 站主动联动",
      text: features.enable_bilibili_integration
        ? `${bili.available ? "已检测" : "未检测"} · 最新 ${bili.latest_video?.title || "暂无"}`
        : "联动开关未启用",
    },
    {
      level: imageCache.enabled ? (imageTotal ? "ok" : "info") : "info",
      title: "缓存命中",
      text: imageCache.enabled
        ? `图片视觉 ${imageCache.items || 0}/${imageCache.max_items || "不限"} 条 · 命中率 ${imageTotal ? `${imageHitRate}%` : "暂无样本"}`
        : "图片视觉缓存未开启",
    },
    {
      level: features.enable_creative_writing ? "ok" : "info",
      title: "私下创作",
      text: features.enable_creative_writing
        ? `${creative.active_projects || 0} 个进行中 · ${creative.hidden_mode ? "节点自然提起" : "普通模式"}`
        : "创作行为未启用",
    },
  ];
  const panel = $("#healthPanel");
  if (!panel) return;
  panel.innerHTML = items.map((item) => `
    <div class="health-item ${escapeHtml(item.level)}">
      <b>${escapeHtml(item.title)}</b>
      <span>${escapeHtml(item.text)}</span>
    </div>
  `).join("");
}

export function renderSetupProgress() {
  const overview = state.overview || {};
  const settings = overview.settings || {};
  const providers = overview.providers || {};
  const features = overview.features || {};
  const group = overview.group || {};
  const privateInfo = overview.private || {};
  const creative = overview.creative || {};
  const bili = overview.bilibili || {};
  const qzone = overview.qzone || {};
  const worldbook = overview.worldbook || {};
  const cache = overview.cache || {};
  const imageCache = cache.private_image_vision || {};
  const intensity = overview.proactive_intensity || {};
  const intensityEnabled = Boolean(intensity.enabled);
  const proactiveEffectiveMax = intensity.effective?.max_daily_messages ?? privateInfo.max_daily_messages ?? 0;
  const targetUsers = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const fastProvider = String(providers.FAST_RESPONSE_PROVIDER_ID || "").trim();
  const complexProvider = String(providers.COMPLEX_REASONING_PROVIDER_ID || "").trim();
  const creativeProvider = String(providers.CREATIVE_MODEL_PROVIDER_ID || "").trim();
  const visionProvider = String(providers.PLUGIN_VISION_PROVIDER_ID || "").trim();
  const hasGroupObs = Boolean(features.enable_group_companion);
  const hasWorldbook = Boolean(features.enable_worldbook_member_recognition);
  const hasMemory = Boolean(features.enable_companion_memory);
  const hasCreative = Boolean(features.enable_creative_writing);
  const hasNews = Boolean(features.enable_news_integration);
  const hasQzone = Boolean(features.enable_qzone_integration);
  const hasBili = Boolean(features.enable_bilibili_integration);

  const checklist = [
    {
      key: "target_users",
      level: targetUsers.length ? "ok" : "warn",
      title: targetUsers.length ? `目标用户已配置（${targetUsers.length} 人）` : "目标用户未配置",
      hint: targetUsers.length ? "Bot 会在私聊中服务这些用户" : "至少填写一个用户 ID，Bot 才知道服务谁",
      tab: "config",
      action: "去配置",
      critical: true,
    },
    {
      key: "providers",
      level: fastProvider && complexProvider ? "ok" : "warn",
      title: fastProvider && complexProvider ? "核心模型已配置" : "核心模型未配置",
      hint: fastProvider && complexProvider
        ? `快速响应 + 复杂推理已就位`
        : `快速响应${fastProvider ? "✓" : "✗"} · 复杂推理${complexProvider ? "✓" : "✗"}`,
      tab: "models",
      action: "去配置",
      critical: true,
    },
    {
      key: "proactive",
      level: Number(proactiveEffectiveMax || 0) > 0 ? "ok" : "warn",
      title: Number(proactiveEffectiveMax || 0) > 0 ? "私聊主动已开启" : "私聊主动未开启",
      hint: Number(proactiveEffectiveMax || 0) > 0
        ? `每日上限 ${intensity.effective?.max_daily_messages_text || proactiveEffectiveMax}`
        : "Bot 不会主动找用户聊天；建议至少设为 1-3 条/天",
      tab: "private",
      action: "去配置",
      critical: true,
    },
    {
      key: "group",
      level: hasGroupObs ? "ok" : "info",
      title: hasGroupObs ? `群聊观察已开启（${group.enabled_group_count || 0} 个群）` : "群聊观察未开启",
      hint: hasGroupObs
        ? `已观测 ${group.enabled_group_count || 0}/${group.group_count || 0} 个群`
        : "Bot 不会理解群聊上下文；需要时可以开启",
      tab: "group",
      action: hasGroupObs ? "管理" : "去配置",
      critical: false,
    },
    {
      key: "worldbook",
      level: hasWorldbook ? "ok" : "info",
      title: hasWorldbook ? `关系网已启用（${worldbook.enabled_member_count || 0} 个节点）` : "关系网未启用",
      hint: hasWorldbook
        ? "Bot 能稳定识别昵称、群名片和关系备注"
        : "Bot 无法区分群成员身份；群聊功能多时建议开启",
      tab: "worldbook",
      action: hasWorldbook ? "管理" : "去配置",
      critical: false,
    },
    {
      key: "memory",
      level: hasMemory ? "ok" : "info",
      title: hasMemory ? "记忆学习已开启" : "记忆学习未开启",
      hint: hasMemory
        ? `每 ${settings.memory_refresh_interval_minutes ?? 0} 分钟整理一次画像`
        : "Bot 不会沉淀长期记忆和相处细节",
      tab: "memory",
      action: hasMemory ? "查看" : "去配置",
      critical: false,
    },
    {
      key: "creative",
      level: hasCreative ? "ok" : "info",
      title: hasCreative ? `创作已开启（${creative.active_projects || 0} 个进行中）` : "创作未开启",
      hint: hasCreative
        ? "Bot 会自主推进写作项目"
        : "Bot 不会自主创作；书柜会保持空置",
      tab: "bookshelf",
      action: hasCreative ? "看书柜" : "去配置",
      critical: false,
    },
    {
      key: "extra",
      level: hasNews || hasQzone || hasBili ? "ok" : "info",
      title: hasNews || hasQzone || hasBili ? "外部能力已展开" : "外部能力未展开",
      hint: [
        hasNews ? "新闻" : "",
        hasQzone ? "空间" : "",
        hasBili ? "B站" : "",
      ].filter(Boolean).join(" · ") || "新闻、QQ空间、B站联动均未开启",
      tab: "config",
      action: "去配置",
      critical: false,
    },
  ];

  const doneCount = checklist.filter((item) => item.level === "ok").length;
  const totalCount = checklist.length;
  const pct = Math.round((doneCount / totalCount) * 100);
  const criticalDone = checklist.filter((item) => item.critical && item.level === "ok").length;
  const criticalTotal = checklist.filter((item) => item.critical).length;
  const allDone = doneCount === totalCount;
  const criticalDone_all = criticalDone === criticalTotal;

  const bar = $("#setupProgressBar");
  if (bar) {
    const tone = allDone ? "complete" : criticalDone_all ? "partial" : "initial";
    bar.innerHTML = `
      <div class="setup-progress-track">
        <div class="setup-progress-fill ${tone}" style="width:${pct}%"></div>
      </div>
      <div class="setup-progress-meta">
        <span class="setup-progress-pct">${pct}%</span>
        <span class="setup-progress-label">${allDone ? "全部就绪" : criticalDone_all ? `核心配置已完成，还有 ${totalCount - doneCount} 项可选` : `${criticalDone}/${criticalTotal} 项核心配置待完成`}</span>
        ${allDone ? "" : `<button type="button" class="setup-progress-guide-btn" data-setup-guide-open>打开配置引导</button>`}
      </div>
    `;
  }

  const listEl = $("#setupProgressList");
  if (listEl) {
    listEl.innerHTML = checklist.map((item) => `
      <div class="setup-progress-item ${escapeHtml(item.level)} ${item.critical ? "critical" : ""}">
        <div class="setup-progress-item-icon">
          ${item.level === "ok" ? "✓" : item.level === "warn" ? "!" : "○"}
        </div>
        <div class="setup-progress-item-body">
          <b>${escapeHtml(item.title)}</b>
          <span>${escapeHtml(item.hint)}</span>
        </div>
        <button type="button" class="setup-progress-item-action" data-jump-tab="${escapeHtml(item.tab)}">${escapeHtml(item.action)}</button>
      </div>
    `).join("");
  }
}

export function livingMemoryHealthText(livingmemory) {
  if (!livingmemory) return "未读取到外部记忆插件协同状态";
  if (livingmemory.conflict_warning) return livingmemory.conflict_warning;
  const pluginName = livingmemory.selected_plugin_name || livingmemory.selected_plugin?.display_name || "";
  if (!livingmemory.compatible_available && !livingmemory.available && !livingmemory.memory_companion_active) return "未检测到可协同记忆插件";
  if (!livingmemory.configured_enabled && !livingmemory.enabled) return `协同开关未启用${pluginName ? `；检测到 ${pluginName}` : ""}`;
  if (pluginName) return `当前使用：${pluginName}`;
  if (livingmemory.memory_companion_active) return `当前使用：${livingmemory.memory_companion_display_name || "我会牢牢记住你"}`;
  if (livingmemory.available) return `当前使用：LivingMemory · ${livingmemory.tool_name || "recall_long_term_memory"}`;
  return "协同开关未启用";
}

export function livingMemoryStatusText(livingmemory) {
  if (!livingmemory) return "未读取到外部记忆插件协同状态";
  const lines = [livingMemoryHealthText(livingmemory)];
  const activePlugins = Array.isArray(livingmemory.active_plugins) ? livingmemory.active_plugins : [];
  if (activePlugins.length) {
    lines.push(`检测到：${activePlugins.map((item) => item.display_name || item.name || item.type).filter(Boolean).join("、")}`);
  }
  if (livingmemory.selected_plugin_name) {
    lines.push(`当前使用：${livingmemory.selected_plugin_name}`);
  }
  if (livingmemory.available && livingmemory.tool_name) {
    lines.push(`LivingMemory 工具名：${livingmemory.tool_name || "recall_long_term_memory"}`);
  }
  if (livingmemory.conflict_warning) {
    lines.push("处理建议：只启用其中一个记忆插件，避免重复召回、重复写入或提示词变长。");
  }
  if (livingmemory.status) {
    lines.push("");
    lines.push(livingmemory.status);
  }
  return lines.filter((line, index, arr) => line && arr.indexOf(line) === index).join("\n");
}

export function renderDiagnostics() {
  const items = state.diagnostics || [];
  $("#diagnosticPanel").innerHTML = items.length
    ? items.map((item) => `
      <div class="diagnostic-item ${escapeHtml(item.level || "info")}">
        <span class="diag-dot"></span>
        <div>
          <b>${escapeHtml(item.title || "")}</b>
          <p>${escapeHtml(item.text || "")}</p>
          ${item.action ? `<small>${escapeHtml(item.action)}</small>` : ""}
          ${troubleshootingSuppressionButtonMarkup(item, "运行诊断")}
        </div>
      </div>
    `).join("")
    : `<div class="empty small">暂无诊断项</div>`;
}

export function renderUxReviewPanel() {
  const overview = state.overview || {};
  const settings = overview.settings || {};
  const features = overview.features || {};
  const group = overview.group || {};
  const news = overview.news || {};
  const aiDaily = news.ai_daily || {};
  const cache = overview.cache || {};
  const imageCache = cache.private_image_vision || {};
  const featureKeys = visibleTopLevelFeatureKeys(features);
  const enabledFeatureCount = featureKeys.filter((key) => features[key]).length;
  const activeFeatureGroupCount = featureGroups.filter((group) =>
    group.keys.some((key) => visibleFeatureSwitchKey(key) && features[key])
  ).length;
  const targetUsers = Array.isArray(settings.target_user_ids)
    ? settings.target_user_ids.filter(Boolean)
    : String(settings.target_user_ids || "").split(/[\s,，]+/).filter(Boolean);
  const hasPrivateTargets = targetUsers.length || state.users.some((user) => user.is_qq_user || user.user_id);
  const personaText = String(settings.schedule_persona_prompt || "");
  const roleFilled = ["姓名", "性别", "生日", "识别点", "职业/身份", "性格描述", "核心欲望/目标", "爱好"]
    .filter((label) => labeledRoleplayValuePresent(personaText, label)).length;
  const personaReady = roleFilled >= 6 || personaText.trim().length >= 220;
  const worldReady = String(settings.schedule_worldview_prompt || "").trim().length >= 40;
  const userProfileText = String(settings.roleplay_user_profile_prompt || "").trim()
    || String(settings.private_image_self_recognition_hint || "").trim();
  const userReady = userProfileText.length >= 30;
  const imageEnhanceEnabled = Boolean(settings.enable_private_image_self_recognition || features.enable_private_image_self_recognition);
  const items = [
    { level: personaReady && worldReady && userReady ? "ok" : "warn", title: "世界知识", text: personaReady && worldReady && userReady ? (roleFilled >= 6 ? `角色资料 ${roleFilled}/8 项，世界观和用户关系已补齐` : "旧版文案已完整；标准化字段可按需补齐") : `角色资料 ${roleFilled}/8 项；补齐外貌识别点、爱好、禁忌和用户关系`, tab: "roleplay" },
    { level: Number(settings.max_daily_messages || 0) <= 0 || hasPrivateTargets ? "ok" : "warn", title: "私聊主动目标", text: Number(settings.max_daily_messages || 0) <= 0 ? "私聊主动关闭，无需目标列表" : (hasPrivateTargets ? `已识别 ${targetUsers.length || state.users.length} 个私聊对象` : "主动已开启，但目标列表为空"), tab: "config" },
    { level: features.enable_group_companion ? (Number(group.enabled_group_count || 0) > 0 ? "ok" : "warn") : "info", title: "群聊入口", text: features.enable_group_companion ? `${group.enabled_group_count || 0}/${group.group_count || 0} 个群正在观测` : "群聊观察关闭，相关页仅保留管理视图", tab: "group" },
    { level: imageEnhanceEnabled ? (settings.enable_private_image_vision_cache ? "ok" : "warn") : "info", title: "图片转述增强", text: imageEnhanceEnabled ? `缓存 ${imageCache.items || 0}/${imageCache.max_items || "不限"} 条；${settings.enable_private_image_vision_cache ? "重复图会复用摘要" : "缓存关闭，重复图会重复调用"}` : "图片转述增强关闭", tab: "image-cache" },
    { level: featureKeys.length ? "ok" : "info", title: "功能开关", text: featureKeys.length ? `${enabledFeatureCount}/${featureKeys.length} 个主开关开启，归入 ${activeFeatureGroupCount}/${featureGroups.length} 个分类` : "等待功能开关数据", tab: "config" },
    { level: news.ai_daily_enabled ? (aiDaily.last_text_readable || aiDaily.status === "already_read_today_video" ? "ok" : "warn") : "info", title: "AI 日报/早报", text: news.ai_daily_enabled ? (aiDaily.last_text_readable ? `文字版已读 ${formatCompactNumber(aiDaily.last_text_chars || 0)} 字` : `状态：${insightStatus(aiDaily.status)}`) : "AI 日报/早报追踪关闭", tab: "dashboard" },
  ];
  const actionItems = items.filter((item) => item.level === "warn");
  const visibleItems = state.uxReviewShowAll ? items : actionItems;
  const root = $("#uxReviewPanel");
  if (!root) return;
  const summary = actionItems.length
    ? `发现 ${actionItems.length} 项需处理，优先完成后再查看其余状态。`
    : "当前没有必须处理的项目；其余状态可按需查看。";
  root.innerHTML = `
    <div class="ux-review-summary ${actionItems.length ? "has-actions" : "clear"}">
      <div><b>${escapeHtml(actionItems.length ? "优先处理" : "状态正常")}</b><small>${escapeHtml(summary)}</small></div>
      <button type="button" class="ux-review-toggle" data-ux-review-toggle>${state.uxReviewShowAll ? "只看待处理" : `查看全部 ${items.length} 项`}</button>
    </div>
    <div class="ux-review-items">
      ${visibleItems.length ? visibleItems.map((item) => `
        <button type="button" class="ux-review-item ${escapeHtml(item.level)}" data-jump-tab="${escapeHtml(item.tab)}">
          <span>${escapeHtml(item.level === "ok" ? "已处理" : item.level === "warn" ? "需关注" : "信息")}</span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.text)}</small>
        </button>
      `).join("") : `<div class="empty small">暂无需要处理的项目。</div>`}
    </div>
  `;
  root.querySelector("[data-ux-review-toggle]")?.addEventListener("click", () => {
    state.uxReviewShowAll = !state.uxReviewShowAll;
    renderUxReviewPanel();
  });
}

export function labeledRoleplayValuePresent(text, label) {
  const source = String(text || "");
  const escaped = escapeRegExp(label);
  const pattern = new RegExp(`(?:^|\\n)\\s*${escaped}\\s*[：:]\\s*([^\\n]+)`, "u");
  const match = source.match(pattern);
  return Boolean(match && String(match[1] || "").trim());
}

export function troubleshootingCategoryInfo(category) {
  return troubleshootingCategories[category] || troubleshootingCategories.all;
}

export function troubleshootingCategoryPickerMarkup(selected) {
  return Object.entries(troubleshootingCategories).map(([key, item]) => `
    <button type="button" class="diagnostic-category ${key === selected ? "is-active" : ""}" data-troubleshooting-category="${escapeHtml(key)}" role="tab" aria-selected="${key === selected}">
      <b>${escapeHtml(item.label)}</b><span>${escapeHtml(item.description)}</span>
    </button>
  `).join("");
}

export function troubleshootingFilterByCategory(items, category) {
  const keywords = troubleshootingCategoryInfo(category).keywords;
  if (!keywords.length) return items;
  return items.filter((item) => {
    const text = [item.title, item.text, item.detail, item.source, item.action, item.task, item.key].join(" ").toLowerCase();
    return keywords.some((keyword) => text.includes(keyword));
  });
}

export function troubleshootingSuppressionButtonMarkup(item, source) {
  if (String(item?.level || "") !== "warn" || !String(item?.warning_type || "").startsWith("warning:")) return "";
  return `
    <button
      type="button"
      class="diagnostic-warning-suppress"
      data-troubleshooting-warning-action="suppress"
      data-warning-key="${escapeHtml(item.warning_type)}"
      data-warning-code="${escapeHtml(item.warning_code || "")}"
      data-warning-title="${escapeHtml(item.title || "未命名警告类型")}"
      data-warning-source="${escapeHtml(source || item.source || "排障检查")}"
      title="以后不再显示这一类警告"
    >屏蔽此类</button>
  `;
}

export function renderTroubleshootingSuppressedWarnings(data = {}) {
  const manager = $("#troubleshootingSuppressedWarningManager");
  const countEl = $("#troubleshootingSuppressedWarningCount");
  const listEl = $("#troubleshootingSuppressedWarnings");
  if (!manager || !countEl || !listEl) return;
  const items = Array.isArray(data.suppressed_warning_types) ? data.suppressed_warning_types : [];
  manager.hidden = items.length === 0;
  countEl.textContent = String(items.length);
  listEl.innerHTML = items.length
    ? `
      <div class="diagnostic-suppressed-list-head">
        <span>${escapeHtml(items.length)} 类警告已隐藏</span>
        <button type="button" data-troubleshooting-warning-action="restore_all">全部恢复</button>
      </div>
      ${items.map((item) => `
        <div class="diagnostic-suppressed-item">
          <div>
            <b>${escapeHtml(item.title || "未命名警告类型")}</b>
            <span>${escapeHtml(item.source || "排障检查")}${Number(item.current_count || 0) > 0 ? ` · 当前命中 ${escapeHtml(item.current_count)} 条` : " · 当前未命中"}</span>
          </div>
          <button
            type="button"
            data-troubleshooting-warning-action="restore"
            data-warning-key="${escapeHtml(item.key || "")}"
          >恢复</button>
        </div>
      `).join("")}
    `
    : "";
}

export async function updateTroubleshootingWarningSuppression(control) {
  const action = String(control?.dataset?.troubleshootingWarningAction || "").trim();
  if (!action) return;
  const payload = { action };
  if (action !== "restore_all") {
    payload.key = String(control.dataset.warningKey || "").trim();
  }
  if (action === "suppress") {
    payload.code = String(control.dataset.warningCode || "").trim();
    payload.title = String(control.dataset.warningTitle || "").trim();
    payload.source = String(control.dataset.warningSource || "").trim();
  }
  setActionBusy(control, true);
  let result = null;
  try {
    result = await postJson("/troubleshooting/warnings/update", payload);
  } catch (error) {
    showToast(`更新警告屏蔽失败：${error.message}`, "error");
    setActionBusy(control, false);
    return;
  }
  try {
    const refreshResults = await Promise.allSettled([
      loadTroubleshooting({ silent: true, skipExperimentalRender: true }),
      loadDiagnostics(true, { skipExperimentalRender: true }),
    ]);
    const refreshFailed = refreshResults.some((item) => item.status === "rejected");
    renderTroubleshooting();
    if (refreshFailed) {
      showToast(`${result?.message || "警告屏蔽已保存"}，但自动刷新失败，请重新检查`, "error");
    } else {
      showToast(result?.message || (action === "suppress" ? "已屏蔽此类警告" : "已恢复警告类型"));
    }
  } finally {
    setActionBusy(control, false);
  }
}

export function renderTroubleshooting() {
  const categoriesEl = $("#troubleshootingCategories");
  const summaryEl = $("#troubleshootingSummary");
  const checksEl = $("#troubleshootingChecks");
  const eventsEl = $("#troubleshootingEvents");
  const sqliteEl = $("#troubleshootingSqlite");
  const chainEl = $("#troubleshootingChainTests");
  const injectionsEl = $("#troubleshootingPromptInjections");
  const debounceEl = $("#troubleshootingDebounceTrace");
  const faqEl = $("#troubleshootingFaq");
  const runtimeStackEl = $("#troubleshootingRuntimeStack");
  if (!summaryEl || !checksEl || !eventsEl || !sqliteEl || !chainEl || !injectionsEl) return;
  const data = state.troubleshooting || {};
  const summary = data.summary || {};
  const counts = summary.counts || {};
  const level = summary.level || "info";
  const selected = state.troubleshootingFilter || "all";
  const category = state.troubleshootingCategory || "all";
  const categoryInfo = troubleshootingCategoryInfo(category);
  const checks = Array.isArray(data.checks) ? data.checks : [];
  const events = Array.isArray(data.recent_events) ? data.recent_events : [];
  const categorizedChecks = troubleshootingFilterByCategory(checks, category);
  const categorizedEvents = troubleshootingFilterByCategory(events, category);
  const filteredChecks = selected === "all" ? categorizedChecks : categorizedChecks.filter((item) => item.level === selected);
  const filteredEvents = selected === "all" ? categorizedEvents : categorizedEvents.filter((item) => item.level === selected);
  const reasonItems = troubleshootingReasonItems(filteredChecks, filteredEvents, selected);
  renderTroubleshootingSuppressedWarnings(data);
  if (categoriesEl) categoriesEl.innerHTML = troubleshootingCategoryPickerMarkup(category);
  $("#troubleshootingChecksTitle")?.replaceChildren(document.createTextNode(`${categoryInfo.label}：需要处理的信号`));
  $("#troubleshootingChainTitle")?.replaceChildren(document.createTextNode(`${categoryInfo.label}：留存结果与运行入口`));
  $("#troubleshootingEventsTitle")?.replaceChildren(document.createTextNode(`${categoryInfo.label}：最近问题`));
  summaryEl.innerHTML = `
    <section class="troubleshooting-head-card ${escapeHtml(level)}">
      <div>
        <span>${escapeHtml(summary.generated_at || "等待检查")}</span>
        <b>${escapeHtml(summary.headline || "尚未加载排障信息")}</b>
        <small>${escapeHtml(troubleshootingSummaryText(counts, summary))}</small>
      </div>
      <button type="button" data-troubleshooting-refresh>重新检查</button>
    </section>
    ${["error", "warn", "info", "ok"].map((name) => `
      <button type="button" class="troubleshooting-count ${escapeHtml(name)} ${selected === name ? "is-active" : ""}" data-troubleshooting-filter="${escapeHtml(name)}">
        <b>${escapeHtml(counts[name] || 0)}</b>
        <span>${escapeHtml(troubleshootingLevelLabel(name))}</span>
      </button>
    `).join("")}
    ${troubleshootingProactiveIntensityMarkup(data.proactive_intensity || state.overview?.proactive_intensity || {})}
    <section class="troubleshooting-reasons">
      <header>
        <b>${escapeHtml(selected === "all" ? `近 2 小时${categoryInfo.label}待处理原因` : `${troubleshootingLevelLabel(selected)}原因`)}</b>
        <span>${escapeHtml(selected === "all" ? "只展示近期需要处理的错误和警告；普通信息可点信息查看" : "筛选同时作用于常见问题检查和最近问题")}</span>
      </header>
      ${reasonItems.length ? reasonItems.map((item) => `
        <button type="button" class="${escapeHtml(item.level || "info")}" ${item.jump ? `data-jump-tab="${escapeHtml(item.jump)}"` : ""}>
          <b>${escapeHtml(item.title || "-")}</b>
          <span>${escapeHtml(item.text || "")}</span>
        </button>
      `).join("") : `<div class="empty small">${escapeHtml(selected === "all" ? "暂无需要处理的原因" : "这个筛选下暂无原因")}</div>`}
    </section>
  `;
  document.querySelectorAll("[data-troubleshooting-filter]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.troubleshootingFilter === selected);
  });
  checksEl.innerHTML = filteredChecks.length
    ? filteredChecks.map((item) => troubleshootingCheckMarkup(item)).join("")
    : `<div class="empty small">暂无${escapeHtml(selected === "all" ? "" : troubleshootingLevelLabel(selected))}${escapeHtml(categoryInfo.label)}相关检查项</div>`;
  eventsEl.innerHTML = filteredEvents.length
    ? filteredEvents.map((item) => troubleshootingEventMarkup(item)).join("")
    : `<div class="empty small">暂无${escapeHtml(selected === "all" ? "" : troubleshootingLevelLabel(selected))}${escapeHtml(categoryInfo.label)}相关问题记录</div>`;
  const sqlite = data.sqlite || {};
  const sqliteItems = Array.isArray(sqlite.items) ? sqlite.items : [];
  sqliteEl.innerHTML = sqliteItems.length
    ? sqliteItems.map((item) => `
      <section class="troubleshooting-sqlite-row ${escapeHtml(item.level || "info")}">
        <b>${escapeHtml(item.name || "database")}</b>
        <span>${escapeHtml(item.text || "-")}</span>
        <small>${escapeHtml(item.path || "")}</small>
        ${troubleshootingSuppressionButtonMarkup(item, "SQLite 并发")}
      </section>
    `).join("")
    : `<div class="empty small">没有检测到候选 SQLite 数据库文件</div>`;
  chainEl.innerHTML = troubleshootingChainTestMarkup(
    data.chain_tests || {},
    data.recent_photo_generations || [],
    data.screen_companion || state.overview?.screen_companion || {},
    data.qzone || state.overview?.qzone || {},
    data.tts || {},
    category,
  );
  injectionsEl.innerHTML = ["all", "reply", "voice"].includes(category)
    ? troubleshootingPromptInjectionMarkup(data.prompt_injections || {})
    : `<div class="empty small">${escapeHtml(categoryInfo.label)}问题通常不需要查看提示词注入记录。</div>`;
  if (faqEl) faqEl.innerHTML = troubleshootingFaqMarkup(data, category);
  syncTroubleshootingTestButtons();
  const showSqlite = ["all", "reply"].includes(category);
  const showDebounce = ["all", "reply", "proactive"].includes(category);
  const sqliteCard = sqliteEl?.closest(".diagnostic-runtime-card");
  const debounceCard = debounceEl?.closest(".diagnostic-runtime-card");
  if (sqliteCard) sqliteCard.hidden = !showSqlite;
  if (debounceCard) debounceCard.hidden = !showDebounce;
  if (runtimeStackEl) runtimeStackEl.hidden = !showSqlite && !showDebounce;
  if (debounceEl) {
    debounceEl.innerHTML = troubleshootingDebounceTraceMarkup(state.overview?.message_debounce || {});
  }
}

export function troubleshootingProactiveIntensityMarkup(intensity = {}) {
  if (!intensity || !intensity.enabled) return "";
  const effective = intensity.effective || {};
  const maxDailyText = effective.max_daily_messages_text || formatProactiveLimit(effective.max_daily_messages, effective.max_daily_messages_unlimited);
  const interjectLimitText = effective.group_interject_max_daily_text || formatProactiveLimit(effective.group_interject_max_daily, effective.group_interject_max_daily_unlimited);
  const interestProbability = Math.round(Number(effective.group_wakeup_interest_probability || 0) * 100);
  const flags = [
    effective.ignore_daily_limit ? "每日主动不限" : "",
    effective.group_interject_max_daily_unlimited ? "群插话不限" : "",
    effective.ignore_token_soft_limit ? "忽略 Token 软限额降载" : "",
  ].filter(Boolean);
  const rows = [
    ["私聊主动", formatProactiveDailyQuota(effective.max_daily_messages, effective.max_daily_messages_unlimited, maxDailyText)],
    ["空闲判定", `${effective.idle_minutes ?? "-"} 分钟`],
    ["最小间隔", `${effective.min_interval_minutes ?? "-"} 分钟`],
    ["群唤醒冷却", `${effective.group_wakeup_cooldown_seconds ?? "-"} 秒`],
    ["群插话间隔", `${effective.group_interject_min_interval_minutes ?? "-"} 分钟`],
    ["群插话上限", interjectLimitText],
    ["兴趣唤醒", `${Number.isFinite(interestProbability) ? interestProbability : 0}%`],
  ];
  return `
    <section class="troubleshooting-intensity-card">
      <header>
        <div>
          <span>当前主动强度预设</span>
          <b>${escapeHtml(intensity.label || intensity.preset || "预设已启用")}</b>
        </div>
        <button type="button" data-jump-tab="config">修改预设</button>
      </header>
      <div class="troubleshooting-intensity-grid">
        ${rows.map(([label, value]) => `
          <p>
            <span>${escapeHtml(label)}</span>
            <b>${escapeHtml(value)}</b>
          </p>
        `).join("")}
      </div>
      <small>${escapeHtml(flags.length ? flags.join("；") : "仅覆盖运行态频率，不改写手动参数。")}；仍保留免打扰、休息、拒绝、隐私和硬限额。</small>
    </section>
  `;
}

export function troubleshootingReasonItems(checks, events, selected) {
  const importantLevels = selected === "all" ? new Set(["error", "warn"]) : new Set([selected]);
  const rows = [];
  for (const item of checks || []) {
    if (!importantLevels.has(item.level || "info")) continue;
    rows.push({
      level: item.level || "info",
      title: troubleshootingDisplayTitle(item.title || "-", item),
      text: item.action || item.text || "",
      jump: item.jump || "",
    });
  }
  for (const item of events || []) {
    if (!importantLevels.has(item.level || "info")) continue;
    rows.push({
      level: item.level || "info",
      title: troubleshootingDisplayTitle(item.title || "-", item),
      text: item.detail || item.action || "",
      jump: item.jump || "",
    });
  }
  const rank = { error: 0, warn: 1, info: 2, ok: 3 };
  rows.sort((a, b) => (rank[a.level] ?? 9) - (rank[b.level] ?? 9));
  return rows.slice(0, 6);
}

export function troubleshootingDisplayTitle(title, item = {}) {
  const rawTitle = String(title || "").trim();
  const task = String(item.task || item.key || "").trim();
  if (task) {
    const label = tokenTaskLabel(task);
    if (label && label !== task) {
      return rawTitle.includes("失败") ? `${label}失败` : label;
    }
  }
  const match = rawTitle.match(/^([A-Za-z0-9_.:-]+)\s*(失败|异常|错误|调用失败)$/);
  if (match) {
    const label = tokenTaskLabel(match[1]);
    if (label && label !== match[1]) return `${label}${match[2]}`;
  }
  return rawTitle || "-";
}

export function troubleshootingSummaryText(counts, summary = {}) {
  if (!counts) return "等待数据";
  const error = Number(counts.error || 0);
  const warn = Number(counts.warn || 0);
  const info = Number(counts.info || 0);
  const ok = Number(counts.ok || 0);
  const suppressedTypes = Number(summary.suppressed_types || 0);
  const suppressedCount = Number(summary.suppressed_count || 0);
  const suppressed = suppressedTypes > 0
    ? ` · 已屏蔽 ${suppressedTypes} 类${suppressedCount > 0 ? `（当前命中 ${suppressedCount} 条）` : ""}`
    : "";
  return `错误 ${error} · 警告 ${warn} · 信息 ${info} · 正常 ${ok}${suppressed}`;
}

export function troubleshootingLevelLabel(level) {
  return {
    error: "错误",
    warn: "警告",
    info: "信息",
    ok: "正常",
  }[level] || level || "未知";
}

export function formatBytes(value) {
  const size = Number(value || 0);
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  if (size < 1024) return `${Math.round(size)} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

export function troubleshootingCheckMarkup(item) {
  const level = item.level || "info";
  return `
    <section class="troubleshooting-check ${escapeHtml(level)}">
      <div class="troubleshooting-check-icon">${escapeHtml(level === "ok" ? "✓" : level === "error" ? "!" : level === "warn" ? "!" : "i")}</div>
      <div>
        <b>${escapeHtml(item.title || "-")}</b>
        <p>${escapeHtml(item.text || "")}</p>
        ${item.action ? `<small>${escapeHtml(item.action)}</small>` : ""}
      </div>
      <div class="troubleshooting-check-actions">
        ${item.jump ? `<button type="button" data-jump-tab="${escapeHtml(item.jump)}">查看</button>` : ""}
        ${troubleshootingSuppressionButtonMarkup(item, "常见检查")}
      </div>
    </section>
  `;
}

export function troubleshootingEventMarkup(item) {
  return `
    <section class="troubleshooting-event ${escapeHtml(item.level || "info")}">
      <header>
        <span>${escapeHtml(item.source || "事件")}</span>
        <small>${escapeHtml(item.time || "")}</small>
      </header>
      <b>${escapeHtml(item.title || "-")}</b>
      ${item.detail ? `<p>${escapeHtml(item.detail)}</p>` : ""}
      <footer>
        ${item.action ? `<span>${escapeHtml(item.action)}</span>` : ""}
        <div class="troubleshooting-event-actions">
          ${item.jump ? `<button type="button" data-jump-tab="${escapeHtml(item.jump)}">查看</button>` : ""}
          ${troubleshootingSuppressionButtonMarkup(item, item.source || "最近问题")}
        </div>
      </footer>
    </section>
  `;
}

export function troubleshootingFaqMarkup(data = {}, category = "all") {
  const chainTests = data.chain_tests || {};
  const proactiveTest = chainTests.proactive_message || {};
  const imageTest = chainTests.image_generation_text2img || chainTests.image_generation || {};
  const promptMessages = Array.isArray(data.prompt_injections?.messages) ? data.prompt_injections.messages : [];
  const proactiveMeta = proactiveTest.pending
    ? "最近主动测试：已预约，稍后刷新看结果"
    : proactiveTest.ran_at_text
      ? `最近主动测试：${proactiveTest.ok ? "通过" : "失败"} · ${proactiveTest.ran_at_text}`
      : "尚未运行主动链路测试";
  const imageMeta = imageTest.ran_at_text
    ? `最近文生图测试：${imageTest.ok ? "通过" : "失败"} · ${imageTest.ran_at_text}`
    : "尚未运行文生图链路测试";
  const injectionMeta = promptMessages.length
    ? `当前保留最近 ${Math.min(promptMessages.length, 10)} 次回复的注入链路`
    : "当前没有可展示的注入链路记录";
  const items = [
    {
      category: "proactive",
      title: "为什么没有主动消息？",
      meta: proactiveMeta,
      body: [
        "先确认私聊对象已启用，并且没有处在静默、休息、冷却、每日上限、未回复降频或主动人格判定拦截中。",
        "再看上方“最近问题”和主动审计记录：如果显示“已放弃/已延后”，通常是时间窗、关系压力、内容重复或链路依赖不可用。",
        "最直接的验证方式是点“测试主动消息”，它会预约一次临时主动，检查生成、复核、发送和归档是否完整。",
      ],
      actions: [
        { label: "看主动页", tab: "proactive" },
        { label: "看私聊对象", tab: "private" },
        { label: "测试主动消息", test: "proactive_message" },
      ],
    },
    {
      category: "image_generation",
      title: "为什么生图失败？",
      meta: imageMeta,
      body: [
        "先看在线/本地后端是否选对：在线后端要检查平台、Base URL、Key、模型名、尺寸和超时；本地 ComfyUI 要检查工作流名称和服务是否可连。",
        "如果是自拍或参考图链路，再检查参考图路径/URL 是否可读，以及本地负载保护有没有因为 CPU、内存或队列压力而延后。",
        "排障里的“测试文生图/测试自拍”会实际生成文件，比只看配置更可靠。",
      ],
      actions: [
        { label: "测试文生图", test: "image_generation_text2img", workflowKind: "text2img" },
        { label: "测试自拍", test: "image_generation_selfie", workflowKind: "selfie" },
        { label: "看模型页", tab: "models" },
      ],
    },
    {
      category: "image_recognition",
      title: "为什么图片没有被识别？",
      meta: "先确认视觉模型与图片转述路径可用",
      body: [
        "检查 AstrBot 图片转文字或插件视觉恢复候选是否可用；视觉 Provider 被冷却、图片 URL 无法下载或文件已失效都会导致识别跳过。",
        "如果是屏幕观察，先运行“测试窥屏”；如果是聊天图片，再确认图片缓存页面中对应文件可以正常打开。",
      ],
      actions: [
        { label: "看图片缓存", tab: "image-cache" },
        { label: "看模型页", tab: "models" },
      ],
    },
    {
      category: "voice",
      title: "为什么没有发送语音？",
      meta: "文本转换模型不等于语音合成 Provider",
      body: [
        "先看上方“真实语音 Provider”：只有 AstrBot 会话已启用且可取得 TTS Provider，插件才能把语音文本真正合成为音频。",
        "TTS 文本转换模型只负责判断、翻译或改写朗读内容；它不可替代真正的 TTS Provider。",
        "运行“测试 TTS 生成”会直接调用当前会话 Provider，并报告返回的音频文件或失败原因。",
      ],
      actions: [
        { label: "测试 TTS 生成", test: "tts_generation" },
        { label: "看常用配置", tab: "config" },
      ],
    },
    {
      category: "reply",
      title: "为什么回复像被注入或带偏？",
      meta: "优先看“最近注入内容”和群聊防注入记录",
      body: [
        "先点开最近回复对应的注入链路，区分真实用户消息、插件动态注入、TTS 规则和模型生成内容。",
        "群聊里如果有人要求改称呼、改设定、改格式或要求忽略人格，确认“群聊防注入”和“群聊人格降噪”开启。",
        "如果污染来自关系网自登记、黑话或成员画像，去关系网/群聊页检查对应条目。",
      ],
      actions: [
        { label: "看群聊页", tab: "group" },
        { label: "看关系网", tab: "worldbook" },
      ],
    },
    {
      category: "reply",
      title: "为什么排障页没有注入记录？",
      meta: injectionMeta,
      body: [
        "注入记录按最近回复聚合，只保留最近 10 次；需要实际发生一次主链请求或请求级提示词注入后才会出现。",
        "非陪伴私聊现在会放行默认主链，这类消息不会强行生成陪伴注入记录，这是正常现象。",
        "如果刚刚才触发回复，先点“重新检查”；如果仍没有，说明该轮可能没有进入插件被动增强链路，或被主动-only/休息/目标用户判断提前放行。",
      ],
      actions: [
        { label: "重新检查", refresh: true },
        { label: "看最近注入", anchor: "troubleshootingPromptInjections" },
      ],
    },
  ];
  const visibleItems = category === "all" ? items : items.filter((item) => item.category === category);
  if (!visibleItems.length) return `<div class="empty small">当前问题类型暂时没有额外说明；先运行上方对应的链路测试。</div>`;
  return visibleItems.map((item, index) => `
    <details class="troubleshooting-faq-item" ${index < 2 ? "open" : ""}>
      <summary>
        <span>
          <b>${escapeHtml(item.title)}</b>
          <small>${escapeHtml(item.meta)}</small>
        </span>
      </summary>
      <div class="troubleshooting-faq-body">
        ${item.body.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
        <footer>
          ${item.actions.map((action) => {
            if (action.tab) return `<button type="button" data-jump-tab="${escapeHtml(action.tab)}">${escapeHtml(action.label)}</button>`;
            if (action.test) {
              return `<button type="button" data-troubleshooting-test="${escapeHtml(action.test)}"${action.workflowKind ? ` data-troubleshooting-workflow-kind="${escapeHtml(action.workflowKind)}"` : ""}>${escapeHtml(action.label)}</button>`;
            }
            if (action.refresh) return `<button type="button" data-troubleshooting-refresh>${escapeHtml(action.label)}</button>`;
            if (action.anchor) return `<button type="button" data-scroll-target="${escapeHtml(action.anchor)}">${escapeHtml(action.label)}</button>`;
            return "";
          }).join("")}
        </footer>
      </div>
    </details>
  `).join("");
}

export function troubleshootingTestResult(type) {
  const results = state.troubleshooting?.chain_tests || {};
  return results[type] || (type === "image_generation_text2img" ? results.image_generation : null)
    || (type === "model_diagnostics" ? results.skill_similarity : null) || {};
}

export function troubleshootingTestPresentation(result) {
  const issues = (Array.isArray(result.steps) ? result.steps : []).filter(step => ["warn", "error"].includes(step?.status));
  if (result.pending === true) return {status: "info", label: "已预约，等待执行；不代表已发送", issues};
  if (result.ok === false || result.error) return {status: "error", label: "记录有失败", issues};
  if (issues.length) return {status: "warn", label: "部分步骤未完成", issues};
  if (result.ok === true) return {status: "ok", label: "检查返回完成", issues};
  return {status: "info", label: "尚无完整结果", issues};
}

export function syncTroubleshootingTestButtons() {
  document.querySelectorAll("[data-troubleshooting-test]").forEach(button => {
    const type = button.dataset.troubleshootingTest;
    const attempt = state.troubleshootingTestAttempts[type];
    const blocked = attempt && ["running", "unknown"].includes(attempt.status);
    button.disabled = Boolean(blocked || troubleshootingTestResult(type).pending);
    button.title = attempt?.status === "running" ? "本页正在等待这项操作的结果"
      : blocked ? "本次结果未确认，先核对记录和实际结果；本页不会再次提交"
      : button.disabled ? "已预约的测试尚未完成" : "";
  });
}

export function troubleshootingChainTestMarkup(results, recentPhotoGenerations = [], screenCompanion = {}, qzone = {}, tts = {}, category = "all") {
  const tests = [
    {
      category: "image_generation",
      type: "image_generation_text2img",
      workflowKind: "text2img",
      title: "文生图",
      text: "真实调用普通文生图链路，生成图片文件并记录结果；此入口不负责发送图片。",
      button: "测试文生图",
    },
    {
      category: "image_generation",
      type: "image_generation_selfie",
      workflowKind: "selfie",
      title: "自拍/参考图",
      text: "真实调用自拍/人像生成并留存图片文件；开启一致性且有参考图时使用参考图。此入口不负责发送图片。",
      button: "测试自拍",
    },
    {
      category: "voice",
      type: "tts_generation",
      title: "TTS 生成",
      text: "实际调用服务端选定私聊会话的真实 TTS，生成音频文件并记录结果；此入口不负责发送语音。优先已启用的主人会话，否则取首个可用会话。",
      button: "测试 TTS 生成",
    },
    ...(screenCompanion?.available ? [{
      category: "image_recognition",
      type: "screen_peek",
      title: "窥屏",
      text: "实际调用已连接的识屏入口，读取屏幕并取得观察摘要；可能使用识别模型，结果会留存。",
      button: "测试窥屏",
    }] : []),
    {
      category: "reply",
      type: "qzone_integration",
      title: "QQ 空间",
      text: qzone?.enabled
        ? "检查 Cookie、读取链路、发布工具空参数模拟和评论收件箱状态；不会真实发布或回复评论"
        : "检查 QQ 空间配置状态；未启用时会显示缺失原因，不会真实发布或回复评论",
      button: "测试 QQ 空间",
    },
    {
      category: "proactive",
      type: "proactive_message",
      title: "主动消息",
      text: "预约约 1 分钟后的临时主动私聊，会走真实生成、复核、发送与归档。默认优先已启用的主人，否则首个有私聊会话的对象；返回预约不代表实际已发送。",
      button: "测试主动消息",
    },
    {
      category: "reply",
      type: "model_diagnostics",
      title: "模型数据排障",
      text: "先检查技能、群黑话、关系网、长期画像与表达学习的本地候选；有候选时请求模型复核并留存建议。不会按建议自动改写这些资料；没有候选时不会调用模型。",
      button: "运行模型排障",
    },
  ];
  const visibleTests = category === "all" ? tests : tests.filter((test) => test.category === category);
  const testsMarkup = visibleTests.map((test) => {
    const result = results?.[test.type]
      || (test.type === "image_generation_text2img" ? results?.image_generation : null)
      || (test.type === "model_diagnostics" ? results?.skill_similarity : null)
      || {};
    const hasResult = Boolean(result.ran_at || result.ran_at_text || result.error || result.detail);
    const presentation = troubleshootingTestPresentation(result);
    const attempt = state.troubleshootingTestAttempts[test.type];
    const status = attempt?.status === "unknown" ? "warn" : hasResult ? presentation.status : "info";
    const meta = [
      result.backend || result.provider || "",
      result.umo ? `目标会话 ${result.umo}` : "",
      result.image_model ? `模型 ${result.image_model}` : "",
      result.workflow_kind ? `类型 ${result.workflow_kind}` : "",
      result.used_reference ? "已带参考图" : "",
      result.timeout_seconds ? `等待上限 ${result.timeout_seconds}s` : "",
      result.timeout_budget ? `预算 ${result.timeout_budget}` : "",
      result.context_chars ? `摘要 ${result.context_chars} 字` : "",
      result.elapsed_ms ? `${result.elapsed_ms}ms` : "",
      result.file_size ? `${formatBytes(result.file_size)}` : "",
      result.ran_at_text || "",
    ].filter(Boolean).join(" · ");
    const stepsMarkup = troubleshootingChainStepsMarkup(result.steps);
    const previewMarkup = troubleshootingChainPreviewMarkup(test.type, result);
    const detailText = troubleshootingChainDetailText(test, result, hasResult);
    return `
      <section class="troubleshooting-chain-test aw-chain-card ${escapeHtml(status)}">
        <div>
          <header><b>${escapeHtml(test.title)}</b><span class="aw-chain-status">${hasResult ? escapeHtml(presentation.label) : "尚无留存结果"}</span></header>
          ${attempt && attempt.status !== "returned" ? `<div class="aw-chain-notice" role="status">${attempt.status === "running" ? "正在等待本次结果；切换分类不会重新提交。" : `本次结果未确认：${escapeHtml(attempt.error)}。服务端可能已开始执行；下面的留存记录不能证明本次完成，本页不会再次提交。刷新仍会执行原诊断及恢复逻辑，不会重发测试。`}</div>` : ""}
          ${hasResult ? `<small class="aw-chain-origin">${attempt?.result === result ? "本页收到的执行返回；不证明结果已持久保存" : "服务端每类最近一次留存结果"}；不代表当前全部链路正常${attempt?.status === "unknown" ? "，也未关联到本次未确认请求" : ""}。</small><p>${escapeHtml(detailText)}</p>` : ""}
          ${presentation.issues.length ? `<div class="aw-chain-issues">${presentation.issues.map(step => `<p>${escapeHtml(step.name || "步骤")}：${escapeHtml(step.detail || step.status)}</p>`).join("")}</div>` : ""}
          ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
          ${result.path ? `<small class="path">${escapeHtml(result.path)}</small>` : ""}
          ${previewMarkup}
          ${stepsMarkup}
          <details class="aw-chain-run" data-chain-run="${escapeHtml(test.type)}">
            <summary>运行范围与操作</summary><p>${escapeHtml(test.text)}</p>
            <button type="button" data-troubleshooting-test="${escapeHtml(test.type)}" ${test.workflowKind ? `data-troubleshooting-workflow-kind="${escapeHtml(test.workflowKind)}"` : ""}>${escapeHtml(test.button)}</button>
          </details>
        </div>
      </section>
    `;
  }).join("");
  const photoHistory = ["all", "image_generation"].includes(category)
    ? troubleshootingRecentPhotoGenerationMarkup(recentPhotoGenerations)
    : "";
  const empty = visibleTests.length ? "" : `<div class="empty small">当前问题类型没有可直接运行的链路测试。</div>`;
  return `${category === "voice" ? troubleshootingTtsRuntimeMarkup(tts) : ""}${testsMarkup || empty}${photoHistory}`;
}

export function troubleshootingTtsRuntimeMarkup(tts = {}) {
  const deliveryLabels = { voice_only: "仅语音", voice_and_text: "语音 + 文字" };
  const foreignTextLabels = { original: "显示原文", translation: "显示中文", bilingual: "双语显示" };
  const scopeLabels = { partial: "局部转换", full: "全量转换" };
  const rows = [
    ["目标会话", tts.umo || "未找到已启用的私聊会话"],
    ["TTS 强化", tts.enhancement_enabled ? "已开启" : "未开启"],
    ["发送效果", deliveryLabels[tts.delivery_mode] || "语音 + 文字"],
    ["外语文字", foreignTextLabels[tts.foreign_text_mode] || "显示中文"],
    ["转换范围", scopeLabels[tts.conversion_scope] || "局部转换"],
    ["AstrBot 会话 TTS", tts.settings_enabled ? "已启用" : "未启用"],
    ["真实语音 Provider", tts.provider_available ? (tts.provider_label || "可用") : "当前不可用"],
  ];
  const hint = tts.provider_available
    ? "文本转换模型只负责判断或改写文本；这里显示的是实际生成音频的 Provider。"
    : "请在 AstrBot 目标会话中启用真实 TTS Provider；文本转换模型不能直接生成语音。";
  return `<section class="troubleshooting-tts-runtime"><header><div><span>语音运行态</span><b>${escapeHtml(tts.mode || "fast_tag")}</b></div><button type="button" data-troubleshooting-test="tts_generation">运行 TTS 生成测试</button></header><div>${rows.map(([label, value]) => `<p><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></p>`).join("")}</div><small>${escapeHtml(hint)}</small></section>`;
}

export function troubleshootingChainDetailText(test, result, hasResult) {
  if (!hasResult) return test.text;
  if (result.error) return result.error;
  if ((test.type === "skill_similarity" || test.type === "model_diagnostics") && result.ok) {
    const localCount = Number(result.local_count || 0);
    const modelCount = Number(result.model_count || 0);
    return result.detail || `本地发现 ${localCount} 条候选，模型给出 ${modelCount} 条建议`;
  }
  return result.detail || test.text;
}

export function troubleshootingChainStepsMarkup(stepsRaw) {
  const steps = Array.isArray(stepsRaw) ? stepsRaw : [];
  if (!steps.length) return "";
  return `
    <details class="chain-test-steps">
      <summary>查看链路阶段</summary>
      ${steps.map((step) => `
        <div class="chain-test-step ${escapeHtml(step.status || "info")}">
          <b>${escapeHtml(step.name || "-")}</b>
          <span>${escapeHtml(step.detail || "")}</span>
        </div>
      `).join("")}
    </details>
  `;
}

export function troubleshootingChainPreviewMarkup(type, result) {
  if (type === "screen_peek") {
    if (!result.text_preview) return "";
    return `
      <details class="chain-test-steps chain-test-preview">
        <summary>查看识屏摘要</summary>
        <p>${escapeHtml(result.text_preview || "")}</p>
      </details>
    `;
  }
  if (type === "qzone_integration") {
    if (!result.text_preview) return "";
    return `
      <details class="chain-test-steps chain-test-preview">
        <summary>查看 QQ 空间测试摘要</summary>
        <p>${escapeHtml(result.text_preview || "")}</p>
      </details>
    `;
  }
  if (type === "skill_similarity" || type === "model_diagnostics") {
    const sections = Array.isArray(result.sections) ? result.sections.filter(Boolean) : [];
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions.filter(Boolean) : [];
    if (!suggestions.length && !result.text_preview) return "";
    const sectionMarkup = sections.length ? sections.map((section) => {
      const items = Array.isArray(section.suggestions) ? section.suggestions.filter(Boolean) : [];
      const meta = [
        Number(section.local_count || 0) ? `本地 ${Number(section.local_count || 0)}` : "",
        Number(section.model_count || 0) ? `模型 ${Number(section.model_count || 0)}` : "",
      ].filter(Boolean).join(" · ");
      return `
        <div class="chain-test-preview-section">
          <b>${escapeHtml(section.title || "排障项")}${meta ? ` · ${escapeHtml(meta)}` : ""}</b>
          ${items.length ? items.map((item) => `<p>${escapeHtml(item)}</p>`).join("") : `<p class="muted">暂无明显问题</p>`}
        </div>
      `;
    }).join("") : "";
    return `
      <details class="chain-test-steps chain-test-preview">
        <summary>查看模型排障建议${result.extra_count ? `（另有 ${escapeHtml(result.extra_count)} 条未展示）` : ""}</summary>
        ${sectionMarkup || (suggestions.length ? suggestions.map((item) => `<p>${escapeHtml(item)}</p>`).join("") : `<p>${escapeHtml(result.text_preview || "")}</p>`)}
      </details>
    `;
  }
  const parts = [];
  if (result.original_text_preview || result.final_text_preview) {
    const original = result.original_text_preview || result.text_preview || "";
    const finalText = result.final_text_preview || result.text_preview || "";
    parts.push(`
      <details class="chain-test-steps chain-test-preview">
        <summary>查看主动改写对比</summary>
        ${original ? `<p><b>原候选：</b>${escapeHtml(original)}</p>` : ""}
        ${finalText ? `<p><b>最终发送：</b>${escapeHtml(finalText)}</p>` : ""}
      </details>
    `);
  }
  if (result.text_preview && !result.final_text_preview) parts.push(`<small class="path">文本预览：${escapeHtml(result.text_preview)}</small>`);
  if (result.prompt) parts.push(`<small class="path">提示词：${escapeHtml(result.prompt)}</small>`);
  const warningItems = Array.isArray(result.warning_items)
    ? result.warning_items.filter((item) => item && item.text)
    : (Array.isArray(result.warnings) ? result.warnings.filter(Boolean).map((text) => ({ text })) : []);
  if ((type === "image_generation_text2img" || type === "image_generation_selfie" || type === "image_generation") && warningItems.length) {
    parts.push(`
      <details class="chain-test-steps chain-test-preview">
        <summary>查看真实出图超时风险</summary>
        ${warningItems.map((item) => `
          <div class="diagnostic-chain-warning">
            <p>${escapeHtml(item.text || "")}</p>
            ${troubleshootingSuppressionButtonMarkup(item, item.source || "链路测试")}
          </div>
        `).join("")}
      </details>
    `);
  }
  return parts.join("");
}

export function troubleshootingRecentPhotoGenerationMarkup(itemsRaw) {
  const items = Array.isArray(itemsRaw) ? itemsRaw.filter(Boolean) : [];
  if (!items.length) {
    return `
      <section class="troubleshooting-chain-test info">
        <div>
          <b>最近提交给生图后端的提示词</b>
          <p>暂无真实生图记录；运行一次主动拍照、每日穿搭、自然语言生图或生图排障后会显示。</p>
        </div>
      </section>
    `;
  }
  return `
    <section class="troubleshooting-chain-test info">
      <div>
        <b>最近提交给生图后端的提示词</b>
        <p>展示最近 ${escapeHtml(String(items.length))} 次真实生图调用；内容已包含场景预设、自拍场景约束和固定附加提示词，不是提示词模型的上游输入。</p>
        <details class="chain-test-steps chain-test-preview photo-prompt-history">
          <summary>查看最近生图记录</summary>
          ${items.map((item) => {
            const meta = [
              item.ok ? "成功" : "失败",
              item.backend || "",
              item.kind ? `类型 ${item.kind}` : "",
              item.intent_kind ? `意图 ${item.intent_kind}` : "",
              item.trigger ? `来源 ${item.trigger}` : "",
              item.sent ? "已发送" : "",
              item.scene_preset ? `预设 ${item.scene_preset}` : "",
              item.image_size ? `尺寸 ${item.image_size}` : "",
              item.reference ? "带参考图" : "",
              item.elapsed_ms ? `${item.elapsed_ms}ms` : "",
              item.time || "",
              item.trace ? `trace ${item.trace}` : "",
            ].filter(Boolean);
            const promptText = String(item.prompt || item.prompt_preview || "").trim();
            return `
              <article class="photo-prompt-record">
                <div class="photo-prompt-meta">
                  ${(meta.length ? meta : ["生图记录"]).map((part) => `<span>${escapeHtml(part)}</span>`).join("")}
                </div>
                ${item.note ? `<p class="photo-prompt-note">${escapeHtml(item.note)}</p>` : ""}
                ${item.caption ? `<small class="photo-prompt-caption">附言：${escapeHtml(item.caption)}</small>` : ""}
                ${item.path ? `<small class="path photo-prompt-path">输出：${escapeHtml(item.path)}</small>` : ""}
                ${item.reference_path ? `<small class="path photo-prompt-path">参考图：${escapeHtml(item.reference_path)}</small>` : ""}
                <pre class="photo-prompt-text">${escapeHtml(promptText || "暂无提示词内容")}</pre>
              </article>
            `;
          }).join("")}
        </details>
      </div>
    </section>
  `;
}

export function troubleshootingDebounceTraceMarkup(data) {
  const logs = Array.isArray(data.recent_logs) ? data.recent_logs : [];
  const examples = Array.isArray(data.examples) ? data.examples : [];
  const status = data.smart_enabled
    ? `智能收口开启 · 等待 ${Number(data.smart_wait || 0).toFixed(1)}s · 学习窗口 ${Number(data.learning_window || 0).toFixed(1)}s`
    : data.enabled
      ? "消息收口开启，智能文本收口未开启"
      : "消息收口未开启";
  const provider = data.provider_id || "跟随默认模型";
  const limitText = data.enabled
    ? `最长 ${Number(data.max_wait || 0).toFixed(1)}s · 最多 ${Number(data.max_merge || 0)} 条`
    : "";
  const logMarkup = logs.length ? logs.slice(0, 8).map((item) => {
    const tone = item.outcome === "wait" || item.outcome === "extend_wait"
      ? "warn"
      : item.outcome === "reply_now"
        ? "ok"
        : item.outcome === "learned" || item.outcome === "timeout_single"
          ? "info"
          : "";
    const confidence = Number(item.confidence || 0);
    const meta = [
      debounceOutcomeLabel(item.outcome),
      item.source || "",
      confidence ? `置信 ${(confidence * 100).toFixed(0)}%` : "",
      item.wait_seconds ? `等待 ${Number(item.wait_seconds).toFixed(1)}s` : "",
      item.message_count ? `${item.message_count} 条` : "",
      item.time || "",
    ].filter(Boolean).join(" · ");
    return `
      <section class="debounce-log ${escapeHtml(tone)}">
        <header>
          <b>${escapeHtml(debounceDecisionLabel(item.decision))}</b>
          <span>${escapeHtml(item.scope || item.chat || "-")}</span>
        </header>
        <p>${escapeHtml(item.text || item.note || "-")}</p>
        <small>${escapeHtml(meta)}</small>
        ${item.reason ? `<small>原因：${escapeHtml(item.reason)}</small>` : ""}
        ${item.raw ? `<small>原始返回：${escapeHtml(item.raw)}</small>` : ""}
      </section>
    `;
  }).join("") : `<div class="empty small">暂无智能防抖决策记录</div>`;
  const exampleMarkup = examples.length ? `
    <details class="debounce-examples">
      <summary>误判学习样本 ${escapeHtml(examples.length)}</summary>
      ${examples.slice(0, 6).map((item) => `
        <section>
          <b>${escapeHtml(item.kind || "-")}</b>
          <span>${escapeHtml(item.note || "")}</span>
          <small>${escapeHtml((item.messages || []).join(" / "))}</small>
        </section>
      `).join("")}
    </details>
  ` : "";
  return `
    <div class="debounce-status">
      <span>${escapeHtml(status)}</span>
      ${limitText ? `<span>${escapeHtml(limitText)}</span>` : ""}
      <span>模型：${escapeHtml(provider)}</span>
    </div>
    <div class="debounce-log-list">${logMarkup}</div>
    ${exampleMarkup}
  `;
}

export function debounceDecisionLabel(decision) {
  return {
    complete: "放行",
    incomplete: "等待",
    fixed: "固定等待",
  }[decision] || decision || "记录";
}

export function promptInjectionKindLabel(kind) {
  return {
    request: "请求附加",
    passive: "被动回复",
    proactive: "主动消息",
    tts: "TTS 规则",
  }[kind] || kind || "注入记录";
}

export function promptInjectionMessagePreview(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "未记录触发消息";
  const internalMarkers = ["【语音消息规则】", "<pc_tts>", "</pc_tts>", "语音消息规则", "提示词片段", "当前语音正文目标语种"];
  if (internalMarkers.some((marker) => text.includes(marker))) return "未记录触发消息";
  return text.length > 72 ? `${text.slice(0, 72)}…` : text;
}

export function troubleshootingPromptInjectionMarkup(data) {
  const messages = Array.isArray(data?.messages) ? data.messages.slice(0, 10) : [];
  const total = Number(data?.message_total || messages.length || 0);
  return `
    <section class="troubleshooting-injection-group">
      <header>
        <div>
          <b>最近回复的 10 次消息</b>
          <span>按消息聚合展示注入链路；点开某条消息即可查看这次回复的完整注入模块。当前 ${escapeHtml(Math.min(total || messages.length, 10))} 条</span>
        </div>
      </header>
      ${messages.length ? messages.map((item) => troubleshootingPromptInjectionMessageMarkup(item)).join("") : `<div class="empty small">暂无可查看的注入记录</div>`}
    </section>
  `;
}

export function troubleshootingPromptInjectionMessageMarkup(message) {
  const items = Array.isArray(message?.items) ? message.items : [];
  const kinds = Array.isArray(message?.kinds) ? message.kinds.map((kind) => promptInjectionKindLabel(kind)).filter(Boolean) : [];
  const meta = [
    message?.time || "",
    message?.sender_label || "",
    items.length ? `${items.length} 段注入` : "",
    Number(message?.module_count || 0) ? `${Number(message.module_count)} 个模块` : "",
    kinds.length ? kinds.join(" / ") : "",
  ].filter(Boolean).join(" · ");
  const messagePreview = promptInjectionMessagePreview(message?.message_preview || (items[0]?.metadata?.["触发消息"]) || "");
  const metaRows = [
    ["发送者", message?.sender_label || ""],
    ["会话", message?.session || ""],
    ["跟踪", message?.trace_id || ""],
    ["首次记录", message?.first_time || ""],
    ["最后更新", message?.time || ""],
  ].filter(([, value]) => value);
  return `
    <details class="troubleshooting-injection-item troubleshooting-injection-message">
      <summary>
        <span>
          <b>${escapeHtml(messagePreview)}</b>
          <small>${escapeHtml(message?.session || "")}</small>
        </span>
        <em>${escapeHtml(meta)}</em>
      </summary>
      ${metaRows.length ? `
        <dl>
          ${metaRows.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </dl>
      ` : ""}
      ${items.map((item) => troubleshootingPromptInjectionItemMarkup(item, { nested: true })).join("")}
    </details>
  `;
}

export function troubleshootingPromptInjectionItemMarkup(item, options = {}) {
  const nested = Boolean(options?.nested);
  const metadata = item?.metadata && typeof item.metadata === "object" ? item.metadata : {};
  const metaRows = Object.entries(metadata).filter(([key, value]) => key && value);
  const modules = Array.isArray(item?.modules) ? item.modules : [];
  const meta = [
    nested ? "" : promptInjectionKindLabel(item.kind || ""),
    item.time || "",
    item.mode ? `mode=${item.mode}` : "",
    item.chars ? `${item.chars} chars` : "",
    modules.length ? `${modules.length} 个模块` : "",
    item.truncated ? "已截断" : "",
  ].filter(Boolean).join(" · ");
  const title = nested
    ? `${promptInjectionKindLabel(item.kind || "")} · ${item.title || "注入内容"}`
    : (item.title || "注入内容");
  return `
    <details class="troubleshooting-injection-item">
      <summary>
        <span>
          <b>${escapeHtml(title)}</b>
          <small>${escapeHtml(item.session || "")}</small>
        </span>
        <em>${escapeHtml(meta)}</em>
      </summary>
      ${metaRows.length ? `
        <dl>
          ${metaRows.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </dl>
      ` : ""}
      ${item.preview ? `<p>${escapeHtml(item.preview)}</p>` : ""}
      ${modules.length ? `
        <div class="troubleshooting-injection-modules">
          ${modules.map((module) => troubleshootingPromptInjectionModuleMarkup(module)).join("")}
        </div>
      ` : `<pre>${escapeHtml(item.content || "")}</pre>`}
      ${modules.length ? `
        <details class="troubleshooting-injection-raw">
          <summary>查看完整合并文本${item.truncated ? "（已截断）" : ""}</summary>
          <pre>${escapeHtml(item.content || "")}</pre>
        </details>
      ` : ""}
    </details>
  `;
}

export function troubleshootingPromptInjectionModuleMarkup(module) {
  const content = String(module?.content || "");
  const chars = Number(module?.chars || content.length || 0);
  const metadata = module?.metadata && typeof module.metadata === "object" ? module.metadata : {};
  const metaRows = Object.entries(metadata).filter(([key, value]) => key && value);
  const meta = [
    module?.source ? `source=${module.source}` : "",
    module?.key ? `key=${module.key}` : "",
    Number.isFinite(Number(module?.priority)) ? `priority=${module.priority}` : "",
    chars ? `${chars} chars` : "",
    module?.truncated ? "已截断" : "",
  ].filter(Boolean).join(" · ");
  const shouldOpen = content.length > 0 && content.length <= 900;
  return `
    <details class="troubleshooting-injection-module" ${shouldOpen ? "open" : ""}>
      <summary>
        <span>
          <b>${escapeHtml(module?.title || "提示词片段")}</b>
          ${module?.description ? `<small>${escapeHtml(module.description)}</small>` : ""}
        </span>
        <em>${escapeHtml(meta)}</em>
      </summary>
      ${metaRows.length ? `
        <dl class="troubleshooting-injection-meta">
          ${metaRows.map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </dl>
      ` : ""}
      ${module?.preview && content.length > 900 ? `<p>${escapeHtml(module.preview)}</p>` : ""}
      <pre>${escapeHtml(content)}</pre>
    </details>
  `;
}

export function debounceOutcomeLabel(outcome) {
  return {
    reply_now: "立即回复",
    wait: "进入等待",
    extend_wait: "延长等待",
    merged_followup: "等到补话",
    timeout_single: "误等样本",
    learned: "学习样本",
  }[outcome] || outcome || "";
}

export function imageCacheScopeLabel(scope) {
  const value = String(scope || "private_image");
  const labels = {
    private_image: "私聊图片",
    private_image_query: "私聊追问",
    forward_image: "合并图片",
    screen_peek: "识屏",
  };
  return labels[value] || value;
}
