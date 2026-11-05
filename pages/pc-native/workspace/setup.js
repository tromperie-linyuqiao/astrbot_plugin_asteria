/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {fetchJson,postJson} from './client.js';
import {renderGroupBubbleChart,renderRelationshipChart} from './image-cache.js';
import {formatNumber} from './learning.js';
import {normalizeRoleplayStateText,roleplayEnergyLabel} from './library.js';
import {detailSegmentStatusLabel,proactiveActionLabel,renderGroupStrategyOverview,renderLongTermStrategyOverview,renderPrivateStrategyOverview,scheduleLifecycleLabel,statusText} from './life.js';
import {runAction,setActionBusy,showToast} from './persona.js';
import {configLabel} from './providers.js';
import {renderWebExplorationPanel,troubleshootingChainPreviewMarkup,troubleshootingChainStepsMarkup} from './relationships.js';
import {displaySettingValue,featureDraftFromOverview,isFractionalPercentSetting,isPercentInputSetting,isProviderConfigKey,photoApiEndpointComplete,photoApiEndpointInitialList,visibleTopLevelFeatureKeys} from './schema.js';
import {$,SETUP_GUIDE_PROACTIVE_TEST_TIMEOUT_MS,asteriaWorkspaceState,providerLabels,roleplayPersonaParts,roleplayWorldParts,setupGuideAdvancedBlockMap,setupGuideAdvancedBlocks,setupGuideAdvancedItems,setupGuideDraftDefaults,setupGuideIntensityPresets,setupGuideQuickProviderKeys,setupGuideQuickProviderMeta,setupGuideRequiredProviderTestKeys,setupGuideSteps,state} from './state.js';
import {renderActivityHeatmap} from './usage.js';
import {escapeHtml,loadAll,renderAll} from './workspace.js';

export function setupGuideAdvancedItemKeys() {
  return Object.values(setupGuideAdvancedItems)
    .flat()
    .flatMap((item) => [item.key, ...(item.settings || []).map((setting) => setting.key)]);
}

export function setupRunStatusLabel(level) {
  const labels = {
    ok: "可跑通",
    warn: "待处理",
    info: "建议测试",
    skip: "已跳过",
  };
  return labels[level] || "建议测试";
}

export function setupGuideDraft() {
  if (!state.setupGuideDraft) {
    const settings = state.overview?.settings || {};
    const providers = state.overview?.providers || {};
    const features = state.overview?.features || {};
    const intensity = state.overview?.proactive_intensity || {};
    const effective = intensity.effective || {};
    const configured = intensity.configured || {};
    const targetIds = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
    const savedWorldKnowledgePersona = String(settings.schedule_persona_prompt || "").trim();
    const savedWorldKnowledgeWorld = String(settings.schedule_worldview_prompt || "").trim();
    const savedWorldKnowledgeUser = String(settings.roleplay_user_profile_prompt || "").trim();
    const savedWorldKnowledgeExtra = [
      String(settings.private_image_self_recognition_hint || "").trim()
        ? `自我识别提示：${String(settings.private_image_self_recognition_hint || "").trim()}`
        : "",
      String(settings.worldview_adaptation_mode || "").trim() === "custom" && String(settings.worldview_adaptation_prompt || "").trim()
        ? `翻译词：\n${String(settings.worldview_adaptation_prompt || "").trim()}`
        : "",
    ].filter(Boolean).join("\n\n");
    state.setupGuideDraft = {
      ...setupGuideDraftDefaults,
      targetUserIds: targetIds.join("\n"),
      targetPlatform: String(settings.target_platform || "aiocqhttp").trim() || "aiocqhttp",
      quietHours: String(settings.quiet_hours || setupGuideDraftDefaults.quietHours).trim() || setupGuideDraftDefaults.quietHours,
      requirePrivateOptIn: setupGuideBoolValue(settings.require_private_opt_in, setupGuideDraftDefaults.requirePrivateOptIn),
      privateIntensity: String(settings.proactive_intensity_preset || intensity.preset || setupGuideDraftDefaults.privateIntensity || "off"),
      privateMaxDailyMessages: effective.max_daily_messages ?? configured.max_daily_messages ?? setupGuideDraftDefaults.privateMaxDailyMessages,
      privateIdleMinutes: effective.idle_minutes ?? configured.idle_minutes ?? setupGuideDraftDefaults.privateIdleMinutes,
      privateMinIntervalMinutes: effective.min_interval_minutes ?? configured.min_interval_minutes ?? setupGuideDraftDefaults.privateMinIntervalMinutes,
      privatePersonaJudgeThreshold: effective.proactive_persona_judge_send_threshold ?? configured.proactive_persona_judge_send_threshold ?? setupGuideDraftDefaults.privatePersonaJudgeThreshold,
      privateReviewStrength: effective.proactive_review_strength ?? configured.proactive_review_strength ?? setupGuideDraftDefaults.privateReviewStrength,
      privateIgnoreTokenSoftLimit: setupGuideBoolValue(effective.ignore_token_soft_limit, false),
      privateIgnoreDailyLimit: setupGuideBoolValue(effective.ignore_daily_limit, false),
      groupWakeDirectWords: String(settings.group_wakeup_direct_words || setupGuideDraftDefaults.groupWakeDirectWords),
      groupWakeContextWords: String(settings.group_wakeup_context_words || setupGuideDraftDefaults.groupWakeContextWords),
      groupWakeInterestKeywords: String(settings.group_wakeup_interest_keywords || setupGuideDraftDefaults.groupWakeInterestKeywords),
      groupWakeInterestProbability: setupGuidePercentValue(settings.group_wakeup_interest_probability, effective.group_wakeup_interest_probability, setupGuideDraftDefaults.groupWakeInterestProbability),
      groupWakeEnhancement: setupGuideBoolValue(settings.enable_group_wakeup_enhancement, setupGuideDraftDefaults.groupWakeEnhancement),
      groupWakeQuestion: setupGuideBoolValue(settings.enable_group_wakeup_question, setupGuideDraftDefaults.groupWakeQuestion),
      groupWakeQuestionThreshold: settings.group_wakeup_question_threshold ?? effective.group_wakeup_question_threshold ?? setupGuideDraftDefaults.groupWakeQuestionThreshold,
      groupWakeColdGroup: setupGuideBoolValue(settings.enable_group_wakeup_cold_group, setupGuideDraftDefaults.groupWakeColdGroup),
      groupWakeColdGroupThreshold: settings.group_wakeup_cold_group_threshold ?? effective.group_wakeup_cold_group_threshold ?? setupGuideDraftDefaults.groupWakeColdGroupThreshold,
      groupWakeColdGroupIdleMinutes: settings.group_wakeup_cold_group_idle_minutes ?? setupGuideDraftDefaults.groupWakeColdGroupIdleMinutes,
      groupWakeCooldownSeconds: settings.group_wakeup_cooldown_seconds ?? effective.group_wakeup_cooldown_seconds ?? setupGuideDraftDefaults.groupWakeCooldownSeconds,
      groupWakeGeneratedKeywordLimit: settings.group_wakeup_generated_keyword_limit ?? setupGuideDraftDefaults.groupWakeGeneratedKeywordLimit,
      groupWakeTopicInterestMaxBoost: setupGuidePercentValue(settings.group_wakeup_topic_interest_max_boost, null, setupGuideDraftDefaults.groupWakeTopicInterestMaxBoost),
      groupWakeDebouncePendingPenalty: setupGuidePercentValue(settings.group_wakeup_debounce_pending_penalty, null, setupGuideDraftDefaults.groupWakeDebouncePendingPenalty),
      groupWakeFatigueLimit: settings.group_wakeup_fatigue_limit ?? setupGuideDraftDefaults.groupWakeFatigueLimit,
      groupWakeFatigueDecayMinutes: settings.group_wakeup_fatigue_decay_minutes ?? setupGuideDraftDefaults.groupWakeFatigueDecayMinutes,
      groupWakeShortTextWaitSeconds: settings.group_wakeup_short_text_wait_seconds ?? setupGuideDraftDefaults.groupWakeShortTextWaitSeconds,
      groupInterjectMinIntervalMinutes: effective.group_interject_min_interval_minutes ?? configured.group_interject_min_interval_minutes ?? setupGuideDraftDefaults.groupInterjectMinIntervalMinutes,
      groupInterjectMaxDaily: effective.group_interject_max_daily ?? configured.group_interject_max_daily ?? setupGuideDraftDefaults.groupInterjectMaxDaily,
      groupInterjectionFeedback: setupGuideBoolValue(settings.enable_group_interjection_feedback, setupGuideDraftDefaults.groupInterjectionFeedback),
      worldKnowledgePersona: savedWorldKnowledgePersona,
      worldKnowledgeWorld: savedWorldKnowledgeWorld,
      worldKnowledgeUser: savedWorldKnowledgeUser,
      worldKnowledgeExtra: savedWorldKnowledgeExtra,
      worldKnowledgeConfirmed: Boolean(savedWorldKnowledgePersona || savedWorldKnowledgeWorld || savedWorldKnowledgeUser || savedWorldKnowledgeExtra),
      worldbookEnabled: setupGuideBoolValue(settings.enable_worldbook_member_recognition, setupGuideDraftDefaults.worldbookEnabled),
      worldbookSelfRegistration: setupGuideBoolValue(settings.worldbook_self_registration, setupGuideDraftDefaults.worldbookSelfRegistration),
      worldbookUserId: targetIds[0] || "",
      ...Object.fromEntries(setupGuideQuickProviderKeys.map((key) => [key, String(providers[key] || "").trim()])),
    };
    setupGuideAdvancedItemKeys().forEach((key) => {
      if (!key || Object.prototype.hasOwnProperty.call(state.setupGuideDraft, key)) return;
      if (Object.prototype.hasOwnProperty.call(settings, key)) {
        state.setupGuideDraft[key] = setupGuideDraftDisplayValue(key, settings[key]);
      } else if (Object.prototype.hasOwnProperty.call(features, key)) {
        state.setupGuideDraft[key] = features[key];
      } else if (Object.prototype.hasOwnProperty.call(providers, key)) {
        state.setupGuideDraft[key] = providers[key];
      }
    });
  }
  return state.setupGuideDraft;
}

export function setupGuideDraftDisplayValue(key, value) {
  return isPercentInputSetting(key) ? displaySettingValue(key, value) : value;
}

export function setupGuidePayloadValue(key, value) {
  if (!isPercentInputSetting(key)) return value;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  if (isFractionalPercentSetting(key)) {
    return Math.max(0, Math.min(1, numeric / 100));
  }
  return numeric;
}

export function setupGuidePercentValue(primary, fallback, defaultValue = 0) {
  const raw = primary !== undefined && primary !== null && primary !== "" ? primary : fallback;
  const number = Number(raw);
  if (!Number.isFinite(number)) return defaultValue;
  return Math.round(number <= 1 ? number * 100 : number);
}

export function setupGuideBoolValue(value, fallback = false) {
  if (value === undefined || value === null || value === "") return Boolean(fallback);
  if (typeof value === "boolean") return value;
  const text = String(value).trim().toLowerCase();
  if (["false", "0", "off", "no", "否", "关闭", "关"].includes(text)) return false;
  if (["true", "1", "on", "yes", "是", "开启", "开"].includes(text)) return true;
  return Boolean(value);
}

export function setupGuidePlanItems(plan) {
  const rawItems = Array.isArray(plan?.items) ? plan.items : Array.isArray(plan?.schedule) ? plan.schedule : [];
  return rawItems
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      time: item.time || item.start || item.window || item.period || "",
      activity: item.activity || item.event || item.content || item.title || item.summary || item.text || "",
      mood: item.mood || item.emotion || item.state || "",
    }));
}

export function setupGuideParseWindowMinutes(windowText) {
  const match = String(windowText || "").match(/(\d{1,2}):(\d{2})\s*[-~—]\s*(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const start = Number(match[1]) * 60 + Number(match[2]);
  let end = Number(match[3]) * 60 + Number(match[4]);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  if (end <= start) end += 24 * 60;
  return { start, end };
}

export function setupGuideCurrentDetailSegments(segments) {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  return (Array.isArray(segments) ? segments : []).filter((segment) => {
    const windowRange = setupGuideParseWindowMinutes(segment?.window || segment?.key || "");
    if (!windowRange) return false;
    const compareMinutes = minutes < windowRange.start && windowRange.end > 24 * 60 ? minutes + 24 * 60 : minutes;
    return compareMinutes >= windowRange.start && compareMinutes < windowRange.end;
  });
}

export function setupGuideFieldValue(name) {
  return setupGuideDraft()[name];
}

export function setupGuideOption(name, value, label, description) {
  const checked = String(setupGuideFieldValue(name) ?? "") === String(value);
  return `
    <label class="setup-guide-choice setup-guide-option-choice ${checked ? "selected" : ""}">
      <input type="radio" name="${escapeHtml(name)}" value="${escapeHtml(value)}" data-setup-guide-field="${escapeHtml(name)}" ${checked ? "checked" : ""}>
      <span>
        <b>${escapeHtml(label)}</b>
        <small>${escapeHtml(description)}</small>
      </span>
    </label>
  `;
}

export function setupGuideCheck(name, label, description) {
  const checked = Boolean(setupGuideFieldValue(name));
  return `
    <label class="setup-guide-choice setup-guide-toggle-choice ${checked ? "selected" : ""}">
      <input type="checkbox" data-setup-guide-field="${escapeHtml(name)}" ${checked ? "checked" : ""}>
      <span>
        <b>${escapeHtml(label)}</b>
        <small>${escapeHtml(description)}</small>
      </span>
    </label>
  `;
}

export function setupGuideHint(text, tone = "info") {
  return `<p class="setup-guide-hint ${escapeHtml(tone)}">${escapeHtml(text)}</p>`;
}

export function setupGuideText(name, label, placeholder = "", multiline = false, meta = {}) {
  const value = setupGuideFieldValue(name) ?? "";
  const required = Boolean(meta.required);
  const badge = meta.badge ? `<i class="${escapeHtml(meta.badgeTone || "info")}">${escapeHtml(meta.badge)}</i>` : "";
  const description = meta.description ? `<small>${escapeHtml(meta.description)}</small>` : "";
  const inputType = ["text", "password", "url"].includes(String(meta.inputType || "")) ? String(meta.inputType) : "text";
  return `
    <label class="setup-guide-input ${required && !String(value).trim() ? "needs-value" : ""}">
      <span>${escapeHtml(label)}${badge}</span>
      ${description}
      ${multiline
        ? `<textarea rows="3" data-setup-guide-field="${escapeHtml(name)}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value)}</textarea>`
        : `<input type="${escapeHtml(inputType)}" data-setup-guide-field="${escapeHtml(name)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}">`}
    </label>
  `;
}

export function setupGuideNumber(name, label, placeholder = "", meta = {}) {
  const value = setupGuideFieldValue(name) ?? "";
  const badge = meta.badge ? `<i class="${escapeHtml(meta.badgeTone || "info")}">${escapeHtml(meta.badge)}</i>` : "";
  const description = meta.description ? `<small>${escapeHtml(meta.description)}</small>` : "";
  const min = meta.min !== undefined ? ` min="${escapeHtml(meta.min)}"` : "";
  const max = meta.max !== undefined ? ` max="${escapeHtml(meta.max)}"` : "";
  const step = meta.step !== undefined ? ` step="${escapeHtml(meta.step)}"` : "";
  return `
    <label class="setup-guide-input">
      <span>${escapeHtml(label)}${badge}</span>
      ${description}
      <input type="number" data-setup-guide-field="${escapeHtml(name)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}"${min}${max}${step}>
    </label>
  `;
}

export function setupGuideSelect(name, label, options, meta = {}) {
  const value = String(setupGuideFieldValue(name) ?? "");
  const badge = meta.badge ? `<i class="${escapeHtml(meta.badgeTone || "info")}">${escapeHtml(meta.badge)}</i>` : "";
  const description = meta.description ? `<small>${escapeHtml(meta.description)}</small>` : "";
  return `
    <label class="setup-guide-input">
      <span>${escapeHtml(label)}${badge}</span>
      ${description}
      <select data-setup-guide-field="${escapeHtml(name)}">
        ${options.map(([optionValue, labelText]) => `
          <option value="${escapeHtml(optionValue)}" ${String(optionValue) === value ? "selected" : ""}>${escapeHtml(labelText)}</option>
        `).join("")}
      </select>
    </label>
  `;
}

export function setupGuideStepSummaryHtml(items) {
  return `
    <div class="setup-guide-step-summary" data-setup-guide-step-summary>
      ${items.map((item) => `
        <span class="${escapeHtml(item.tone || "info")}">
          <b>${escapeHtml(item.label)}</b>
          ${escapeHtml(item.value)}
        </span>
      `).join("")}
    </div>
  `;
}

export function setupGuideAdvancedBlockHtml(block) {
  const items = setupGuideAdvancedItems[block.id] || [];
  const enabledCount = items.filter((item) => Boolean(setupGuideFieldValue(item.key))).length;
  const selected = state.setupGuideAdvancedBlock === block.id;
  const icons = {
    common: "🔧",
    experimental: "🧪",
    private: "💬",
    group: "👥",
    proactive: "🌟",
  };
  const icon = icons[block.id] || "📋";
  return `
    <button type="button" class="setup-guide-advanced-block ${selected ? "selected" : ""}" data-setup-guide-advanced-block="${escapeHtml(block.id)}">
      <div class="block-header">
        <span class="block-icon">${icon}</span>
        <span class="block-title">${escapeHtml(block.title)}</span>
        <div class="block-status ${enabledCount > 0 ? "has-content" : "empty"}">
          ${enabledCount > 0 ? `<b>${enabledCount}/${items.length}</b>` : `<b class="empty-badge">0</b>`}
        </div>
      </div>
      <p class="block-desc">${escapeHtml(block.body)}</p>
      ${enabledCount > 0 ? `
        <div class="block-preview">
          ${items.filter((item) => Boolean(setupGuideFieldValue(item.key))).slice(0, 3).map((item) => `
            <span class="block-preview-tag">${escapeHtml(item.title)}</span>
          `).join("")}
          ${enabledCount > 3 ? `<span class="block-preview-more">+${enabledCount - 3}</span>` : ""}
        </div>
      ` : ""}
    </button>
  `;
}

export function setupGuideAdvancedHomeHtml() {
  return `
    <div class="setup-guide-question">
      <h4>选择要配置的板块</h4>
      ${setupGuideHint("一次配置一个板块。选中后逐项决定是否开启，保存后再切换其他板块。")}
      <div class="setup-guide-advanced-grid">
        ${setupGuideAdvancedBlocks.map(setupGuideAdvancedBlockHtml).join("")}
      </div>
    </div>
    <div class="setup-guide-question">
      <h4>建议顺序</h4>
      <div class="setup-guide-pill-row">
        <span class="ok"><b>1</b> 通用能力</span>
        <span class="info"><b>2</b> 私聊增强</span>
        <span class="info"><b>3</b> 群聊增强</span>
        <span class="warn"><b>4</b> 主动增强</span>
        <span class="warn"><b>5</b> 实验性功能</span>
      </div>
      ${setupGuideHint("实验性功能放在最后逐项观察；QQ 空间发布、主动带图、本机识屏会触发外部动作，建议基础链路稳定后再开。", "warn")}
    </div>
  `;
}

export function setupGuideAdvancedStepIndex(blockId = state.setupGuideAdvancedBlock) {
  const items = setupGuideAdvancedItems[blockId] || [];
  if (!items.length) return 0;
  const raw = Number(state.setupGuideAdvancedStep || 0);
  const value = Number.isFinite(raw) ? raw : 0;
  return Math.max(0, Math.min(items.length - 1, value));
}

export function setupGuideAdvancedEnabledCount(blockId) {
  return (setupGuideAdvancedItems[blockId] || []).filter((item) => Boolean(setupGuideFieldValue(item.key))).length;
}

export function setupGuideAdvancedEnabledSummaryHtml(blockId) {
  const items = setupGuideAdvancedItems[blockId] || [];
  const enabledItems = items.filter((item) => Boolean(setupGuideFieldValue(item.key)));
  return `
    <div class="setup-guide-advanced-summary">
      <span class="${enabledItems.length ? "ok" : "info"}"><b>已选择</b>${escapeHtml(enabledItems.length)} / ${escapeHtml(items.length)} 项</span>
      ${enabledItems.length ? enabledItems.slice(0, 6).map((item) => `<i>${escapeHtml(item.title)}</i>`).join("") : `<i>还没有开启本板块功能</i>`}
      ${enabledItems.length > 6 ? `<i>+${escapeHtml(enabledItems.length - 6)}</i>` : ""}
    </div>
  `;
}

export function setupGuideAdvancedStepProgressHtml(blockId, activeIndex) {
  const items = setupGuideAdvancedItems[blockId] || [];
  return `
    <div class="setup-guide-advanced-step-progress" aria-label="板块内问卷进度">
      ${items.map((item, index) => {
        const enabled = Boolean(setupGuideFieldValue(item.key));
        return `<button type="button" class="${[index === activeIndex ? "active" : "", enabled ? "done" : ""].filter(Boolean).join(" ")}" data-setup-guide-advanced-step="${index}" title="${escapeHtml(item.title)}"><span>${escapeHtml(index + 1)}</span></button>`;
      }).join("")}
    </div>
  `;
}

export function setupGuideModeHomeHtml() {
  const overview = state.overview || {};
  const settings = overview.settings || {};
  const providers = overview.providers || {};
  const privateInfo = overview.private || {};
  const group = overview.group || {};
  const creative = overview.creative || {};
  const features = overview.features || {};
  const bili = overview.bilibili || {};
  const qzone = overview.qzone || {};
  const worldbook = overview.worldbook || {};
  const intensity = overview.proactive_intensity || {};

  const targetUsers = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const fastProvider = String(providers.FAST_RESPONSE_PROVIDER_ID || "").trim();
  const complexProvider = String(providers.COMPLEX_REASONING_PROVIDER_ID || "").trim();
  const proactiveMax = intensity.effective?.max_daily_messages ?? privateInfo.max_daily_messages ?? 0;
  const hasUsers = targetUsers.length > 0;
  const hasProviders = fastProvider && complexProvider;
  const hasProactive = Number(proactiveMax || 0) > 0;
  const hasGroup = Boolean(features.enable_group_companion);
  const hasWorldbook = Boolean(features.enable_worldbook_member_recognition);
  const hasCreative = Boolean(features.enable_creative_writing);
  const hasNews = Boolean(features.enable_news_integration);
  const hasBili = Boolean(features.enable_bilibili_integration);
  const hasQzone = Boolean(features.enable_qzone_integration);
  const hasMemory = Boolean(features.enable_companion_memory);

  const firstGuideSteps = [
    { title: "基础连通", icon: "🔗", done: hasUsers },
    { title: "核心模型", icon: "🧠", done: hasProviders },
    { title: "主动功能", icon: "🎯", done: hasProactive },
    { title: "其他配置", icon: "⚙️", done: hasGroup || hasWorldbook || hasCreative },
    { title: "主动测试", icon: "✅", done: setupGuideProactiveTestPassed() },
  ];
  const firstGuideDoneCount = firstGuideSteps.filter((s) => s.done).length;
  const firstGuidePct = Math.round((firstGuideDoneCount / firstGuideSteps.length) * 100);

  const advancedIcons = { common: "🔧", private: "💬", group: "👥", proactive: "🌟" };
  const advancedBlocks = setupGuideAdvancedBlocks.map((block) => {
    const items = setupGuideAdvancedItems[block.id] || [];
    return {
      id: block.id,
      title: block.title,
      icon: advancedIcons[block.id] || "📋",
      desc: block.body,
      total: items.length,
      current: items.filter((item) => Boolean(features[item.key] ?? settings[item.key])).length,
    };
  });

  const totalAdvanced = advancedBlocks.reduce((sum, b) => sum + b.total, 0);
  const currentAdvanced = advancedBlocks.reduce((sum, b) => sum + b.current, 0);

  return `
    <div class="setup-guide-question">
      <h4>选择引导类型</h4>
    </div>
    <div class="setup-guide-mode-choice-grid">
      <button type="button" class="setup-guide-mode-choice ${state.setupGuideMode === "first" ? "active" : ""}" data-setup-guide-mode="first">
        <div class="choice-topline">
          <span class="choice-icon">🎯</span>
          <div class="choice-status ${firstGuidePct === 100 ? "complete" : "incomplete"}">
            <i>${firstGuidePct === 100 ? "✓" : "○"}</i>
            <span>${firstGuidePct}%</span>
          </div>
        </div>
        <div class="choice-copy">
          <b>初次引导</b>
          <p class="choice-desc">跑通基础链路：目标用户 ID → 核心模型 → 主动测试</p>
          <small>5 分钟内完成 4 个核心步骤，从零让 Bot 动起来</small>
        </div>
        <ul class="choice-checklist">
          ${firstGuideSteps.map((s) => `<li class="${s.done ? "done" : "todo"}"><i>${s.icon}</i><span><b>${s.title}</b></span><em>${s.done ? "已完成" : "待配置"}</em></li>`).join("")}
        </ul>
      </button>
      <button type="button" class="setup-guide-mode-choice ${state.setupGuideMode === "advanced" ? "active" : ""}" data-setup-guide-mode="advanced">
        <div class="choice-topline">
          <span class="choice-icon">🔧</span>
          <div class="choice-status ${totalAdvanced > 0 && currentAdvanced === totalAdvanced ? "complete" : currentAdvanced > 0 ? "incomplete" : "fresh"}">
            <i>${totalAdvanced > 0 && currentAdvanced === totalAdvanced ? "✓" : currentAdvanced > 0 ? "▸" : "○"}</i>
            <span>${totalAdvanced > 0 ? `${currentAdvanced}/${totalAdvanced}` : "未开启"}</span>
          </div>
        </div>
        <div class="choice-copy">
          <b>进阶引导</b>
          <p class="choice-desc">按板块开启更多能力：通用 · 私聊 · 群聊 · 主动</p>
          <small>${totalAdvanced > 0 ? `已开启 ${currentAdvanced}/${totalAdvanced} 项` : "逐步开满新闻、TTS、读图、空间等能力"}</small>
        </div>
        <ul class="choice-checklist">
          ${advancedBlocks.map((b) => `<li class="${b.current > 0 ? "done" : "todo"}"><i>${b.icon}</i><span><b>${b.title}</b><small>${b.desc}</small></span><em>${b.current > 0 ? `${b.current}/${b.total}` : "未开启"}</em></li>`).join("")}
        </ul>
      </button>
    </div>
    ${setupGuideHint("第一次先走「初次引导」跑通核心链路；之后再用「进阶引导」逐步加功能。")}
  `;
}

export function setupGuideAdvancedSettingHtml(setting) {
  if (!setting || !setting.key) return "";
  if (setting.type === "bool") {
    return setupGuideCheck(setting.key, setting.label || configLabel(setting.key), setting.description || "开启后跟随该功能一起生效。");
  }
  if (setting.type === "number") {
    return setupGuideNumber(setting.key, setting.label || configLabel(setting.key), setting.placeholder || "", {
      min: setting.min,
      max: setting.max,
      step: setting.step,
      description: setting.description,
    });
  }
  if (setting.type === "select") {
    return setupGuideSelect(setting.key, setting.label || configLabel(setting.key), setting.options || [], {
      description: setting.description,
    });
  }
  return setupGuideText(setting.key, setting.label || configLabel(setting.key), setting.placeholder || "", setting.type === "textarea", {
    description: setting.description,
    inputType: setting.type === "password" ? "password" : "text",
  });
}

export function setupGuideAdvancedSettingVisible(setting) {
  if (!setting || typeof setting.showWhen !== "function") return true;
  try {
    return Boolean(setting.showWhen(setupGuideDraft()));
  } catch (_) {
    return true;
  }
}

export function setupGuideAdvancedDependenciesHtml(item) {
  const dependencies = Array.isArray(item.dependencies) ? item.dependencies : [];
  if (!dependencies.length) return "";
  return `
    <div class="setup-guide-advanced-deps">
      ${dependencies.map((dependency) => {
        const label = typeof dependency === "string" ? "前置" : dependency.label || "前置";
        const text = typeof dependency === "string" ? dependency : dependency.text || "";
        const tone = typeof dependency === "object" && dependency.tone ? dependency.tone : "info";
        return `<span class="${escapeHtml(tone)}"><b>${escapeHtml(label)}</b>${escapeHtml(text)}</span>`;
      }).join("")}
    </div>
  `;
}

export function setupGuideAdvancedExtraActionsHtml(item, enabled) {
  if (!enabled || item?.key !== "enable_photo_text_action") return "";
  const settings = state.overview?.settings || {};
  const endpoints = photoApiEndpointInitialList(settings);
  const readyEndpoints = endpoints.filter(photoApiEndpointComplete);
  const queueText = endpoints.length
    ? endpoints.slice(0, 4).map((endpoint, index) => `${index + 1}.${endpoint.name || endpoint.model || "在线 API"}`).join(" / ")
    : "未配置";
  const actionLabel = "交换前两项";
  return `
    <div class="setup-guide-advanced-tools">
      <div>
        <b>在线 API 优先级</b>
        <small>队列：${escapeHtml(queueText)}。已配置完整 ${readyEndpoints.length}/${endpoints.length} 条；点击后交换前两条优先级。</small>
      </div>
      <button type="button" data-swap-image-api>${escapeHtml(actionLabel)}</button>
    </div>
  `;
}

export function setupGuideAdvancedItemHtml(item) {
  const enabled = Boolean(setupGuideFieldValue(item.key));
  const settings = Array.isArray(item.settings) ? item.settings : [];
  const visibleSettings = settings.filter(setupGuideAdvancedSettingVisible);
  return `
    <article class="setup-guide-advanced-item ${enabled ? "enabled" : "disabled"}">
      <header>
        <div>
          <span>${escapeHtml(item.title)}</span>
          <b>${escapeHtml(item.ask)}</b>
        </div>
      </header>
      <div class="setup-guide-advanced-explain">
        <p>${escapeHtml(item.description)}</p>
        <small>${escapeHtml(item.caution)}</small>
      </div>
      ${setupGuideAdvancedDependenciesHtml(item)}
      <div class="setup-guide-advanced-choice-row">
        <label class="${enabled ? "selected" : ""}">
          <input type="radio" name="advanced_${escapeHtml(item.key)}" value="true" data-setup-guide-advanced-toggle="${escapeHtml(item.key)}" ${enabled ? "checked" : ""}>
          <span><b>需要</b><small>在本板块保存时开启，并应用下面参数。</small></span>
        </label>
        <label class="${!enabled ? "selected" : ""}">
          <input type="radio" name="advanced_${escapeHtml(item.key)}" value="false" data-setup-guide-advanced-toggle="${escapeHtml(item.key)}" ${!enabled ? "checked" : ""}>
          <span><b>暂不需要</b><small>保持关闭；已经填过的参数不会被清空。</small></span>
        </label>
      </div>
      ${setupGuideAdvancedExtraActionsHtml(item, enabled)}
      ${enabled && visibleSettings.length ? `
        <div class="setup-guide-advanced-settings">
          ${visibleSettings.map(setupGuideAdvancedSettingHtml).join("")}
        </div>
      ` : enabled ? `
        ${setupGuideHint("本步没有必填项；保存板块后按当前全局设置运行。")}
      ` : ""}
    </article>
  `;
}

export function setupGuideAdvancedQuestionnaireHtml() {
  const blockId = state.setupGuideAdvancedBlock || "";
  const block = setupGuideAdvancedBlockMap[blockId];
  if (!block) return setupGuideAdvancedHomeHtml();
  const items = setupGuideAdvancedItems[blockId] || [];
  if (!items.length) {
    return `
      <div class="setup-guide-question">
        <div class="setup-guide-advanced-title">
          <div>
            <h4>${escapeHtml(block.title)}</h4>
            <p>${escapeHtml(block.body)}</p>
          </div>
          <button type="button" data-setup-guide-advanced-home>返回板块选择</button>
        </div>
        ${setupGuideHint("这个板块暂时没有可配置的问卷项，可以返回选择其他板块。")}
      </div>
    `;
  }
  const stepIndex = setupGuideAdvancedStepIndex(blockId);
  const item = items[stepIndex] || items[0];
  const enabledCount = items.filter((item) => Boolean(setupGuideFieldValue(item.key))).length;
  const nextTitle = stepIndex >= items.length - 1 ? "保存后返回板块选择" : `下一项：${items[stepIndex + 1]?.title || "继续配置"}`;
  return `
    <div class="setup-guide-advanced-rail">
      <div>
        <span>${escapeHtml(block.title)}</span>
        <b>${escapeHtml(stepIndex + 1)} / ${escapeHtml(items.length)} · ${escapeHtml(item.title)}</b>
        <small>已选 ${escapeHtml(enabledCount)} 项 · ${escapeHtml(nextTitle)}</small>
      </div>
      <button type="button" data-setup-guide-advanced-home>返回板块</button>
    </div>
    <div class="setup-guide-question setup-guide-question--compact">
      ${setupGuideAdvancedStepProgressHtml(blockId, stepIndex)}
      ${setupGuideAdvancedEnabledSummaryHtml(blockId)}
    </div>
    <div class="setup-guide-advanced-list single">
      ${setupGuideAdvancedItemHtml(item)}
    </div>
  `;
}

export function setupGuideAdvancedPayload(blockId = state.setupGuideAdvancedBlock) {
  const overviewSettings = state.overview?.settings || {};
  const items = setupGuideAdvancedItems[blockId] || [];
  const draft = setupGuideDraft();
  const features = {};
  const settings = {};
  const providers = {};
  const putValue = (key, value, kind = "") => {
    if (!key) return;
    if (isProviderConfigKey(key)) {
      providers[key] = String(value || "").trim();
    } else if (kind === "feature" || (!Object.prototype.hasOwnProperty.call(overviewSettings, key) && Object.prototype.hasOwnProperty.call(state.featureDraft || {}, key))) {
      features[key] = Boolean(value);
    } else if (kind === "setting" || Object.prototype.hasOwnProperty.call(overviewSettings, key) || !String(key).startsWith("enable_")) {
      settings[key] = setupGuidePayloadValue(key, value);
    } else {
      features[key] = Boolean(value);
    }
  };
  items.forEach((item) => {
    putValue(item.key, draft[item.key], item.kind);
    (item.settings || []).forEach((setting) => {
      if (Object.prototype.hasOwnProperty.call(draft, setting.key)) {
        putValue(setting.key, draft[setting.key], setting.kind || "setting");
      }
    });
  });
  return { features, settings, providers };
}

export async function saveSetupGuideAdvancedBlock(control = null) {
  const blockId = state.setupGuideAdvancedBlock || "";
  const block = setupGuideAdvancedBlockMap[blockId];
  if (!block) {
    showToast("请先选择一个进阶配置板块", "error");
    return false;
  }
  state.setupGuideApplying = true;
  renderSetupGuideOverlay();
  try {
    const result = await runAction(
      () => postJson("/settings/update", setupGuideAdvancedPayload(blockId)),
      `已保存${block.title}`,
      control,
    );
    if (result) {
      state.overview = result;
      state.featureDraft = featureDraftFromOverview(result);
      state.providerConfigMode = result.settings?.provider_config_mode || state.providerConfigMode;
      showToast(result.config_saved === false ? "已写入运行态，但配置持久化可能失败" : `已保存${block.title}`);
      return true;
    }
  } catch (error) {
    showToast(`保存进阶配置失败：${error.message}`, "error");
  } finally {
    state.setupGuideApplying = false;
    if (state.setupGuideOpen) renderSetupGuideOverlay();
  }
  return false;
}

export function setupGuidePersonaSelectHtml() {
  const draft = setupGuideDraft();
  const current = String(draft.personaId || "");
  const personas = state.roleplayPersonas || [];
  const options = personas.length
    ? personas.map((item) => {
      const id = String(item.id || "");
      const label = `${item.label || id}${item.source ? ` · ${item.source}` : ""}`;
      return `<option value="${escapeHtml(id)}" ${id === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }).join("")
    : `<option value="">继承 AstrBot 当前配置人格</option>`;
  const currentLabel = personas.length
    ? (personas.find((p) => String(p.id || "") === current) || {}).label || (current ? current : "继承 AstrBot 当前配置人格")
    : "继承 AstrBot 当前配置人格";
  return `
    <div class="wk-persona-select">
      <label class="setup-guide-input">
        <span>选择用于推导的人格</span>
        <small>只读取人格文本生成草稿，不会切换 AstrBot 对话人格。</small>
        <select data-setup-guide-field="personaId">${options}</select>
      </label>
      <div class="wk-persona-current">当前选择：<b>${escapeHtml(currentLabel)}</b></div>
    </div>
  `;
}

export function setupGuideDraftMapText(map, entries) {
  const source = map && typeof map === "object" ? map : {};
  return entries
    .map(([key, label]) => {
      const value = String(source[key] || "").trim();
      return value ? `${label}：${value}` : "";
    })
    .filter(Boolean)
    .join("\n");
}

export function setupGuideApplyRoleplayDraft(result) {
  const draft = setupGuideDraft();
  const roleplay = result?.draft || {};
  const userPartEntries = [
    ["nickname", "称呼"],
    ["user_gender", "用户性别"],
    ["user_age", "用户年龄"],
    ["user_occupation", "用户身份/职业"],
    ["role_relation", "关系定位"],
    ["interaction", "相处方式"],
    ["extra", "其他补充"],
  ];
  draft.worldKnowledgePersona = setupGuideDraftMapText(roleplay.persona_parts, roleplayPersonaParts);
  draft.worldKnowledgeWorld = setupGuideDraftMapText(roleplay.world_parts, roleplayWorldParts);
  draft.worldKnowledgeUser = setupGuideDraftMapText(roleplay.user_parts, userPartEntries);
  const translations = roleplay.translations && typeof roleplay.translations === "object"
    ? Object.entries(roleplay.translations)
      .map(([key, value]) => String(value || "").trim() ? `${key}：${String(value || "").trim()}` : "")
      .filter(Boolean)
      .join("\n")
    : "";
  draft.worldKnowledgeExtra = [
    roleplay.image_self_recognition_hint ? `自我识别提示：${roleplay.image_self_recognition_hint}` : "",
    translations ? `翻译词：\n${translations}` : "",
    Array.isArray(roleplay.notes) && roleplay.notes.length ? `生成备注：\n${roleplay.notes.join("\n")}` : "",
  ].filter(Boolean).join("\n\n");
  if (
    !String(draft.worldKnowledgePersona || "").trim()
    && !String(draft.worldKnowledgeWorld || "").trim()
    && !String(draft.worldKnowledgeUser || "").trim()
    && String(result?.source_preview || "").trim()
  ) {
    draft.worldKnowledgePersona = `待整理：模型没有整理出有效角色资料，请根据主回复人格原文手动删改。\n人格摘要：${String(result.source_preview || "").trim()}`;
    draft.worldKnowledgeExtra = [
      draft.worldKnowledgeExtra,
      "生成备注：\n模型返回的草稿为空，已填入人格摘要供手动确认。",
    ].filter(Boolean).join("\n\n");
  }
  draft.worldKnowledgeConfirmed = false;
  state.setupGuideRoleplayDraft = {
    result,
    generatedAt: Date.now(),
    personaId: result?.persona_id || draft.personaId || "",
  };
}

export function setupGuideHasWorldKnowledgeDraft(draft = setupGuideDraft()) {
  return [
    draft.worldKnowledgePersona,
    draft.worldKnowledgeWorld,
    draft.worldKnowledgeUser,
    draft.worldKnowledgeExtra,
  ].some((value) => String(value || "").trim());
}

export function setupGuideWorldKnowledgeEditorHtml() {
  const draft = setupGuideDraft();
  if (!state.setupGuideRoleplayDraft && !setupGuideHasWorldKnowledgeDraft(draft)) {
    return `<div class="setup-guide-empty wk-empty-pending"><span class="wk-empty-icon">⏳</span>等待生成草稿。完成上方第 1 步后，草稿会自动显示在这里。</div>`;
  }
  const result = state.setupGuideRoleplayDraft?.result || {};
  const providerRoleLabel = (role) => {
    if (role === "FAST_RESPONSE_PROVIDER_ID") return "快速响应模型";
    if (role === "COMPLEX_REASONING_PROVIDER_ID") return "复杂推理模型";
    if (role === "LLM_PROVIDER_ID") return "主模型";
    if (role === "CUSTOM_PROVIDER_ID") return "指定模型";
    return "";
  };
  const providerText = [
    providerRoleLabel(result.provider_role),
    result.provider_id || "AstrBot 默认模型",
  ].filter(Boolean).join(" · ");
  const repairText = result.repair_provider_id
    ? `；JSON 修复：${[providerRoleLabel(result.repair_provider_role), result.repair_provider_id].filter(Boolean).join(" · ")}`
    : "";
  const parseNote = String(result.parse_note || "").trim();
  const personaText = String(draft.worldKnowledgePersona || "").trim();
  const worldText = String(draft.worldKnowledgeWorld || "").trim();
  const userText = String(draft.worldKnowledgeUser || "").trim();
  const extraText = String(draft.worldKnowledgeExtra || "").trim();
  const fieldCount = [personaText, worldText, userText, extraText].filter(Boolean).length;
  return `
    <div class="setup-guide-world-editor">
      <div class="wk-draft-meta">
        <span class="wk-draft-meta-item">模型：${escapeHtml(providerText || "未返回模型信息")}${escapeHtml(repairText)}</span>
        ${parseNote ? `<span class="wk-draft-meta-item wk-draft-note">${escapeHtml(parseNote)}</span>` : ""}
        <span class="wk-draft-meta-item wk-field-count">已提取 ${fieldCount}/4 项</span>
      </div>
      ${setupGuideText("worldKnowledgePersona", "① 角色资料", "角色外观、身份、性格等。可直接修改。", true)}
      ${setupGuideText("worldKnowledgeWorld", "② 世界观 / 生活背景", "世界设定、时代、活动场景等。", true)}
      ${setupGuideText("worldKnowledgeUser", "③ 用户关系", "只保留人格中明确写出的用户关系。", true)}
      ${setupGuideText("worldKnowledgeExtra", "④ 其他补充", "识图自我识别、翻译词、生成备注等。", true)}
      <div class="setup-guide-provider-test-actions wk-confirm-bar">
        <button type="button" data-setup-guide-world-confirm>${draft.worldKnowledgeConfirmed ? "✓ 已确认，重新确认" : "确认使用这份草稿"}</button>
        <span>${draft.worldKnowledgeConfirmed ? "已确认。完成引导时会写入世界知识配置。" : "确认是可选的——直接「下一步」也可以，草稿会自动保存。"}</span>
      </div>
    </div>
  `;
}

export function setupGuideProviderValue(key, providers = state.overview?.providers || {}) {
  const draft = setupGuideDraft();
  if (Object.prototype.hasOwnProperty.call(draft, key)) {
    return String(draft[key] || "").trim();
  }
  return String(providers[key] || "").trim();
}

export function setupGuideProviderTest(key) {
  return state.setupGuideProviderTests?.[key] || null;
}

export function setupGuideProviderTestOk(key, providerId = setupGuideProviderValue(key)) {
  const test = setupGuideProviderTest(key);
  return Boolean(test && test.status === "ok" && String(test.provider_id || "") === String(providerId || "") && providerId);
}

export function setupGuideProviderTestRequired(key) {
  return setupGuideRequiredProviderTestKeys.includes(key);
}

export function setupGuideProviderTestLabel(key, providerId = setupGuideProviderValue(key)) {
  const test = setupGuideProviderTest(key);
  const required = setupGuideProviderTestRequired(key);
  if (!providerId) return required ? "未选择，无法测试" : "可后补";
  if (!test || String(test.provider_id || "") !== String(providerId || "")) return required ? "未测试" : "可选测试";
  if (test.status === "running") return "测试中...";
  if (test.status === "ok") return `测试通过${test.elapsed_ms ? ` · ${test.elapsed_ms}ms` : ""}`;
  if (test.status === "fail") return `测试失败：${test.error || "未返回有效结果"}`;
  return required ? "未测试" : "可选测试";
}

export function setupGuideAllProviderTestsPassed() {
  return setupGuideRequiredProviderTestKeys.every((key) => setupGuideProviderTestOk(key));
}

export function setupGuideProviderTestMissingLabels() {
  return setupGuideRequiredProviderTestKeys
    .filter((key) => !setupGuideProviderTestOk(key))
    .map((key) => providerLabels[key] || key);
}

export function invalidateSetupGuideProviderTest(key) {
  if (!setupGuideQuickProviderKeys.includes(key)) return;
  const tests = state.setupGuideProviderTests || {};
  if (tests[key]) {
    state.setupGuideProviderTests = { ...tests, [key]: { status: "idle", provider_id: setupGuideProviderValue(key) } };
  }
}

export function setupGuideProviderOptionLabel(item) {
  return `${item.name || item.id}${item.model ? ` · ${item.model}` : ""}${item.is_default ? " · 默认" : ""}`;
}

export function setupGuideProviderSelectOptionsHtml(key, current, required = false) {
  const known = state.availableProviders.some((item) => item.id === current);
  const options = [
    `<option value="">${required ? "请选择一个 Provider" : "不单独指定，先留空"}</option>`,
    ...state.availableProviders.map((item) => {
      const label = setupGuideProviderOptionLabel(item);
      return `<option value="${escapeHtml(item.id)}" ${item.id === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }),
  ];
  if (current && !known) {
    options.splice(1, 0, `<option value="${escapeHtml(current)}" selected>当前配置：${escapeHtml(current)}（未出现在 Provider 列表）</option>`);
  }
  return options.join("");
}

export function setupGuideProviderField(key, providers = state.overview?.providers || {}) {
  const meta = setupGuideQuickProviderMeta[key] || {};
  const label = providerLabels[key] || key;
  const value = setupGuideProviderValue(key, providers);
  const requiredForStep = setupGuideProviderTestRequired(key);
  const selectedProvider = state.availableProviders.find((item) => item.id === value);
  const testOk = setupGuideProviderTestOk(key, value);
  const test = setupGuideProviderTest(key);
  const testing = Boolean(test && test.status === "running" && String(test.provider_id || "") === value);
  const statusText = value
    ? `当前 Provider ID：${value}${selectedProvider ? `（${setupGuideProviderOptionLabel(selectedProvider)}）` : ""}`
    : requiredForStep ? "继续前需要选择一个 Provider，并完成模型测试。" : "可先留空，后续需要对应能力时再补。";
  const fieldClass = [
    "setup-guide-provider-card",
    value ? "filled" : "empty",
    requiredForStep && !value ? "needs-value" : "",
    testOk ? "tested" : "",
  ].filter(Boolean).join(" ");
  return `
    <article class="${fieldClass}" data-setup-guide-provider-card="${escapeHtml(key)}">
      <span class="setup-guide-provider-head">
        <b>${escapeHtml(label)}</b>
        <i class="${escapeHtml(meta.tone || "optional")}">${escapeHtml(meta.requirement || "可选")}</i>
      </span>
      <small>${escapeHtml(meta.intro || "")}</small>
      ${state.availableProviders.length ? `
        <select data-setup-guide-field="${escapeHtml(key)}" aria-label="${escapeHtml(label)}">
          ${setupGuideProviderSelectOptionsHtml(key, value, requiredForStep)}
        </select>
      ` : `
        <input
          type="text"
          data-setup-guide-field="${escapeHtml(key)}"
          value="${escapeHtml(value)}"
          placeholder="${escapeHtml(meta.placeholder || "输入 Provider ID")}"
          autocomplete="off"
        >
      `}
      <em data-setup-guide-provider-status>${escapeHtml(statusText)}</em>
      <div class="setup-guide-provider-test-row">
        <button type="button" data-setup-guide-provider-test="${escapeHtml(key)}" ${value && !testing ? "" : "disabled"}>${testing ? "测试中..." : testOk ? "重新测试" : "测试模型"}</button>
        <span class="${testOk ? "ok" : test?.status === "fail" ? "warn" : "info"}" data-setup-guide-provider-test-status="${escapeHtml(key)}">${escapeHtml(setupGuideProviderTestLabel(key, value))}</span>
      </div>
    </article>
  `;
}

export function setupGuideModelSummaryHtml(providers = state.overview?.providers || {}) {
  const fastProvider = setupGuideProviderValue("FAST_RESPONSE_PROVIDER_ID", providers);
  const complexProvider = setupGuideProviderValue("COMPLEX_REASONING_PROVIDER_ID", providers);
  const creativeProvider = setupGuideProviderValue("CREATIVE_MODEL_PROVIDER_ID", providers);
  const visionProvider = setupGuideProviderValue("PLUGIN_VISION_PROVIDER_ID", providers);
  const itemHtml = (key, label, providerId) => {
    const ok = setupGuideProviderTestOk(key, providerId);
    const required = setupGuideProviderTestRequired(key);
    const tone = ok ? "ok" : required ? "warn" : providerId ? "info" : "skip";
    const value = providerId ? `${providerId} · ${setupGuideProviderTestLabel(key, providerId)}` : "未选择";
    return `<span class="${tone}"><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`;
  };
  return `
    <div class="setup-guide-model-summary" data-setup-guide-model-summary>
      ${itemHtml("FAST_RESPONSE_PROVIDER_ID", "快速响应", fastProvider)}
      ${itemHtml("COMPLEX_REASONING_PROVIDER_ID", "复杂推理", complexProvider)}
      ${itemHtml("CREATIVE_MODEL_PROVIDER_ID", "创作", creativeProvider)}
      ${itemHtml("PLUGIN_VISION_PROVIDER_ID", "视觉", visionProvider)}
    </div>
  `;
}

export function setupGuideLaterStepSummaryHtml(index) {
  if (index === 2) {
    const personaSource = String(setupGuideFieldValue("personaSource") || "astrbot");
    const inferWorldKnowledge = Boolean(setupGuideFieldValue("inferWorldKnowledge"));
    const worldKnowledgeNote = String(setupGuideFieldValue("worldKnowledgeNote") || "").trim();
    return setupGuideStepSummaryHtml([
      { label: "人格来源", value: personaSource === "astrbot" ? "继承 AstrBot" : "插件草稿", tone: "ok" },
      { label: "世界知识", value: inferWorldKnowledge ? "生成草稿" : "跳过推导", tone: inferWorldKnowledge ? "ok" : "skip" },
      { label: "补充提示", value: worldKnowledgeNote ? "已填写" : "可后续补", tone: worldKnowledgeNote ? "ok" : "info" },
      { label: "聊天人格", value: "不改 AstrBot", tone: "ok" },
    ]);
  }
  if (index === 3) {
    const privateEnabled = Boolean(setupGuideFieldValue("proactivePrivate"));
    const groupEnabled = Boolean(setupGuideFieldValue("proactiveGroup"));
    return setupGuideStepSummaryHtml([
      { label: "私聊主动", value: privateEnabled ? "参与首次测试" : "跳过私聊测试", tone: privateEnabled ? "ok" : "skip" },
      { label: "群聊主动", value: groupEnabled ? "进入群聊配置" : "群聊配置可跳过", tone: groupEnabled ? "ok" : "skip" },
      { label: "进阶能力", value: "暂不配置", tone: "info" },
      { label: "安全边界", value: "仍需发送闸", tone: "ok" },
    ]);
  }
  if (index === 4) {
    const shouldGenerate = Boolean(setupGuideFieldValue("generateSchedule"));
    const shouldRefine = Boolean(setupGuideFieldValue("refineSchedule"));
    return setupGuideStepSummaryHtml([
      { label: "粗日程", value: shouldGenerate ? "将生成" : "跳过", tone: shouldGenerate ? "ok" : "skip" },
      { label: "当前细化", value: shouldRefine ? "将细化" : "跳过", tone: shouldRefine ? "ok" : "skip" },
      { label: "观察页", value: "查看日程/状态", tone: "info" },
      { label: "主动页", value: "查看候选/发送闸", tone: "info" },
    ]);
  }
  if (index === 5) {
    const intensity = String(setupGuideFieldValue("privateIntensity") || "balanced");
    const preset = setupGuideIntensityPresets[intensity] || setupGuideIntensityPresets.off;
    return setupGuideStepSummaryHtml([
      { label: "当前强度", value: preset.label || intensity, tone: intensity === "off" ? "skip" : "ok" },
      { label: "免打扰", value: "继续生效", tone: "ok" },
      { label: "发送闸", value: "仍会复核", tone: "ok" },
      { label: "私聊页", value: "看对象/关系/话题", tone: "info" },
    ]);
  }
  if (index === 6) {
    const wakeWords = String(setupGuideFieldValue("groupWakeDirectWords") || "").trim();
    const wakeEnhancement = Boolean(setupGuideFieldValue("groupWakeEnhancement"));
    const interjection = String(setupGuideFieldValue("groupInterjection") || "observe");
    const worldbookReady = Boolean(String(setupGuideFieldValue("worldbookUserId") || "").trim() && String(setupGuideFieldValue("worldbookNickname") || "").trim());
    return setupGuideStepSummaryHtml([
      { label: "唤醒词", value: wakeWords ? "已填写" : "可后续补", tone: wakeWords ? "ok" : "info" },
      { label: "唤醒增强", value: wakeEnhancement ? "开启" : "关闭", tone: wakeEnhancement ? "ok" : "skip" },
      { label: "插话策略", value: interjection === "off" ? "关闭" : interjection === "low" ? "低频" : "观察", tone: interjection === "low" ? "warn" : interjection === "off" ? "skip" : "ok" },
      { label: "关系词条", value: worldbookReady ? "基础齐备" : "建议补齐", tone: worldbookReady ? "ok" : "info" },
    ]);
  }
  const testMode = String(setupGuideFieldValue("proactiveTestMode") || "candidate");
  const canTest = Boolean(setupGuideFieldValue("proactivePrivate"));
  return setupGuideStepSummaryHtml([
    { label: "私聊主动", value: canTest ? "可测试" : "未开启", tone: canTest ? "ok" : "skip" },
    { label: "测试方式", value: testMode === "confirm_send" ? "确认后发送" : "只生成候选", tone: testMode === "confirm_send" ? "warn" : "ok" },
      { label: "复核结果", value: "下方展示", tone: "info" },
    { label: "完成报告", value: "列出待处理项", tone: "info" },
  ]);
}

export function setupGuideQuickProviderGridHtml(providers = state.overview?.providers || {}) {
  return `
    <div class="setup-guide-provider-grid">
      ${setupGuideQuickProviderKeys.map((key) => setupGuideProviderField(key, providers)).join("")}
    </div>
    <div class="setup-guide-provider-test-actions">
      <button type="button" data-setup-guide-provider-test-all ${setupGuideRequiredProviderTestKeys.every((key) => setupGuideProviderValue(key, providers)) ? "" : "disabled"}>测试必需模型</button>
      <span>${setupGuideAllProviderTestsPassed() ? "快速响应和复杂推理已测试通过，可以进入下一步。创作和识图可按需单独测试。" : "继续前只需要让快速响应和复杂推理测试通过；创作和识图可先选择、不强制测试。"}</span>
    </div>
  `;
}

export function setupGuideStatusPills(overview = state.overview || {}) {
  const settings = overview.settings || {};
  const providers = overview.providers || {};
  const configuredTargets = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const draftTargets = String(setupGuideFieldValue("targetUserIds") || "").split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean);
  const targetCount = draftTargets.length || configuredTargets.length;
  const quickReady = setupGuideAllProviderTestsPassed();
  const targetPlatform = String(setupGuideFieldValue("targetPlatform") || settings.target_platform || "aiocqhttp").trim() || "aiocqhttp";
  const pills = [
    ["页面 API", overview.plugin ? "已连接" : "待确认", overview.plugin ? "ok" : "warn"],
    ["目标用户", targetCount ? `${targetCount} 个` : "未配置", targetCount ? "ok" : "warn"],
    ["target_platform", targetPlatform, targetPlatform ? "ok" : "warn"],
    ["基础模型", quickReady ? "必测通过" : "待测试", quickReady ? "ok" : "warn"],
  ];
  return `<div class="setup-guide-pill-row" data-setup-guide-status-pills>${pills.map(([label, value, tone]) => `
    <span class="${escapeHtml(tone)}"><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>
  `).join("")}</div>`;
}

export function setupGuideBasicConnectionStatus(overview = state.overview || {}) {
  const settings = overview.settings || {};
  const configuredTargets = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const draftTargets = String(setupGuideFieldValue("targetUserIds") || "").split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean);
  const targetPlatform = String(setupGuideFieldValue("targetPlatform") || settings.target_platform || "aiocqhttp").trim();
  const quietHours = String(setupGuideFieldValue("quietHours") || settings.quiet_hours || "").trim();
  const ok = Boolean(overview.plugin && (configuredTargets.length || draftTargets.length) && targetPlatform && quietHours);
  const missing = [];
  if (!overview.plugin) missing.push("插件页面 API");
  if (!(configuredTargets.length || draftTargets.length)) missing.push("目标用户 ID");
  if (!targetPlatform) missing.push("target_platform");
  if (!quietHours) missing.push("免打扰时段");
  return {
    ok,
    title: "基础连接检测",
    status: ok ? "通过" : "未通过",
    text: ok ? "插件基本连接已通过，可以继续首次配置。" : `还需要补齐：${missing.join("、") || "基础信息"}。`,
  };
}

export function setupGuideRunSnapshotHtml(index, overview = state.overview || {}) {
  const item = index === 0 ? setupGuideBasicConnectionStatus(overview) : (setupGuideRunThroughItems(overview)[index] || null);
  if (!item) return "";
  return `
    <section class="setup-guide-run-snapshot ${item.ok === true || item.level === "ok" ? "ok" : item.level === "skip" ? "skip" : "warn"}" data-setup-guide-run-snapshot>
      <header>
        <b>${escapeHtml(item.title)}</b>
        <span>${escapeHtml(item.status || setupRunStatusLabel(item.level))}</span>
      </header>
      <p>${escapeHtml(item.text || item.pass || "")}</p>
    </section>
  `;
}

export function updateSetupGuideSelectedStates(root = document) {
  root.querySelectorAll(".setup-guide-choice").forEach((label) => {
    const input = label.querySelector("input");
    if (input instanceof HTMLInputElement) {
      label.classList.toggle("selected", input.checked);
    }
  });
}

export function updateSetupGuideStatusViews() {
  const modal = document.querySelector(".setup-guide-modal");
  if (!modal) return;
  const statusRoot = modal.querySelector("[data-setup-guide-status-pills]");
  if (statusRoot) statusRoot.outerHTML = setupGuideStatusPills(state.overview || {});
  const snapshotRoot = modal.querySelector("[data-setup-guide-run-snapshot]");
  if (snapshotRoot) snapshotRoot.outerHTML = setupGuideRunSnapshotHtml(setupGuideStepIndex(), state.overview || {});
  const modelSummaryRoot = modal.querySelector("[data-setup-guide-model-summary]");
  if (modelSummaryRoot) modelSummaryRoot.outerHTML = setupGuideModelSummaryHtml(state.overview?.providers || {});
  const stepSummaryRoot = modal.querySelector("[data-setup-guide-step-summary]");
  if (stepSummaryRoot) stepSummaryRoot.outerHTML = setupGuideLaterStepSummaryHtml(setupGuideStepIndex());
  modal.querySelectorAll("[data-setup-guide-provider-card]").forEach((card) => {
    const key = card.getAttribute("data-setup-guide-provider-card") || "";
    const value = setupGuideProviderValue(key, state.overview?.providers || {});
    const selectedProvider = state.availableProviders.find((item) => item.id === value);
    const testOk = setupGuideProviderTestOk(key, value);
    const test = setupGuideProviderTest(key);
    const testing = Boolean(test && test.status === "running" && String(test.provider_id || "") === value);
    const statusText = value
      ? `当前 Provider ID：${value}${selectedProvider ? `（${setupGuideProviderOptionLabel(selectedProvider)}）` : ""}`
      : setupGuideProviderTestRequired(key) ? "继续前需要选择一个 Provider，并完成模型测试。" : "可先留空，后续需要对应能力时再补。";
    card.classList.toggle("filled", Boolean(value));
    card.classList.toggle("empty", !value);
    card.classList.toggle("needs-value", setupGuideProviderTestRequired(key) && !value);
    card.classList.toggle("tested", testOk);
    const status = card.querySelector("[data-setup-guide-provider-status]");
    if (status) status.textContent = statusText;
    const testStatus = card.querySelector(`[data-setup-guide-provider-test-status="${key}"]`);
    if (testStatus) {
      testStatus.textContent = setupGuideProviderTestLabel(key, value);
      testStatus.className = testOk ? "ok" : test?.status === "fail" ? "warn" : "info";
    }
    const button = card.querySelector(`[data-setup-guide-provider-test="${key}"]`);
    if (button instanceof HTMLButtonElement) {
      button.disabled = !value || testing;
      button.textContent = testing ? "测试中..." : testOk ? "重新测试" : "测试模型";
    }
  });
  const testAllButton = modal.querySelector("[data-setup-guide-provider-test-all]");
  if (testAllButton instanceof HTMLButtonElement) {
    const allSelected = setupGuideRequiredProviderTestKeys.every((key) => setupGuideProviderValue(key, state.overview?.providers || {}));
    const anyRunning = setupGuideRequiredProviderTestKeys.some((key) => setupGuideProviderTest(key)?.status === "running");
    testAllButton.disabled = !allSelected || anyRunning;
    testAllButton.textContent = anyRunning ? "测试中..." : setupGuideAllProviderTestsPassed() ? "重新测试必需模型" : "测试必需模型";
  }
  const testAllStatus = modal.querySelector(".setup-guide-provider-test-actions span");
  if (testAllStatus) {
    testAllStatus.textContent = setupGuideAllProviderTestsPassed()
      ? "快速响应和复杂推理已测试通过，可以进入下一步。创作和识图可按需单独测试。"
      : "继续前只需要让快速响应和复杂推理测试通过；创作和识图可先选择、不强制测试。";
  }
  const nextButton = modal.querySelector("[data-setup-guide-next]");
  if (nextButton instanceof HTMLButtonElement) {
    if (state.setupGuideMode === "advanced") {
      nextButton.disabled = Boolean(state.setupGuideApplying) || !state.setupGuideAdvancedBlock;
    } else if (setupGuideStepIndex() === 1) {
      nextButton.disabled = !setupGuideAllProviderTestsPassed();
    } else if (setupGuideStepIndex() >= setupGuideSteps.length - 1) {
      nextButton.disabled = !setupGuideProactiveTestPassed();
    }
  }
}

export function setupGuideApplyIntensityPreset(presetValue) {
  const draft = setupGuideDraft();
  const preset = setupGuideIntensityPresets[presetValue] || setupGuideIntensityPresets.off;
  const effects = preset.effects || {};
  if (presetValue === "off") {
    const configured = state.overview?.proactive_intensity?.configured || {};
    draft.privateMaxDailyMessages = configured.max_daily_messages ?? draft.privateMaxDailyMessages;
    draft.privateIdleMinutes = configured.idle_minutes ?? draft.privateIdleMinutes;
    draft.privateMinIntervalMinutes = configured.min_interval_minutes ?? draft.privateMinIntervalMinutes;
    draft.privatePersonaJudgeThreshold = configured.proactive_persona_judge_send_threshold ?? draft.privatePersonaJudgeThreshold;
    draft.privateReviewStrength = configured.proactive_review_strength ?? draft.privateReviewStrength;
    draft.groupWakeCooldownSeconds = configured.group_wakeup_cooldown_seconds ?? draft.groupWakeCooldownSeconds;
    draft.groupWakeInterestProbability = setupGuidePercentValue(configured.group_wakeup_interest_probability, null, draft.groupWakeInterestProbability);
    draft.groupWakeQuestionThreshold = configured.group_wakeup_question_threshold ?? draft.groupWakeQuestionThreshold;
    draft.groupWakeColdGroupThreshold = configured.group_wakeup_cold_group_threshold ?? draft.groupWakeColdGroupThreshold;
    draft.groupInterjectMinIntervalMinutes = configured.group_interject_min_interval_minutes ?? draft.groupInterjectMinIntervalMinutes;
    draft.groupInterjectMaxDaily = configured.group_interject_max_daily ?? draft.groupInterjectMaxDaily;
    draft.privateIgnoreTokenSoftLimit = false;
    draft.privateIgnoreDailyLimit = false;
    return;
  }
  draft.privateMaxDailyMessages = effects.max_daily_messages ?? draft.privateMaxDailyMessages;
  draft.privateIdleMinutes = effects.idle_minutes ?? draft.privateIdleMinutes;
  draft.privateMinIntervalMinutes = effects.min_interval_minutes ?? draft.privateMinIntervalMinutes;
  draft.privatePersonaJudgeThreshold = effects.proactive_persona_judge_send_threshold ?? draft.privatePersonaJudgeThreshold;
  draft.privateReviewStrength = effects.proactive_review_strength ?? draft.privateReviewStrength;
  draft.privateUnansweredSlowdownStart = effects.unanswered_slowdown_start ?? draft.privateUnansweredSlowdownStart;
  draft.privateUnansweredMaxIntervalMultiplier = effects.unanswered_max_interval_multiplier ?? draft.privateUnansweredMaxIntervalMultiplier;
  draft.privateFriendUnansweredMaxCooldownHours = effects.friend_unanswered_max_cooldown_hours ?? draft.privateFriendUnansweredMaxCooldownHours;
  draft.privateDelayFactor = effects.delay_factor ?? draft.privateDelayFactor;
  draft.privateIgnoreTokenSoftLimit = Boolean(effects.ignore_token_soft_limit);
  draft.privateIgnoreDailyLimit = Boolean(effects.ignore_daily_limit);
  draft.groupWakeCooldownSeconds = effects.group_wakeup_cooldown_seconds ?? draft.groupWakeCooldownSeconds;
  draft.groupWakeInterestProbability = effects.group_wakeup_interest_probability ?? draft.groupWakeInterestProbability;
  draft.groupWakeQuestionThreshold = effects.group_wakeup_question_threshold ?? draft.groupWakeQuestionThreshold;
  draft.groupWakeColdGroupThreshold = effects.group_wakeup_cold_group_threshold ?? draft.groupWakeColdGroupThreshold;
  draft.groupInterjectMinIntervalMinutes = effects.group_interject_min_interval_minutes ?? draft.groupInterjectMinIntervalMinutes;
  draft.groupInterjectMaxDaily = effects.group_interject_max_daily ?? draft.groupInterjectMaxDaily;
}

export function setupGuideDailyResultHtml() {
  const result = state.setupGuideDailyResult || {};
  if (result.loading) {
    const loadingDetail = result.mode === "detail";
    return `
      <div class="setup-guide-daily-simple is-loading">
        <b>${loadingDetail ? "正在细化" : "正在生成"}</b>
        <span>${loadingDetail ? "正在补充当前时段细化，这一步会比粗日程更慢。" : "正在快速生成今日日程；若模型较慢，会先用兜底粗日程放行，后台继续生成。"}</span>
      </div>
    `;
  }
  if (result.error) {
    return `
      <div class="setup-guide-daily-simple is-error">
        <b>生成失败</b>
        <span>${escapeHtml(result.error)}</span>
      </div>
    `;
  }
  const plan = result.plan || state.overview?.daily_plan || {};
  const items = setupGuidePlanItems(plan);
  const timeline = result.daily_timeline || state.overview?.daily_timeline || {};
  const segments = Array.isArray(timeline.segments) ? timeline.segments : [];
  const currentSegments = setupGuideCurrentDetailSegments(segments);
  const currentText = String(result.current_detail_text || "").trim();
  const usefulCurrentText = currentText && !/(还没有|没有生成|没有落地|暂无|未生成出可展示|当前时间段还没有)/.test(currentText)
    ? currentText
    : "";
  if (!items.length && !segments.length && !currentText) {
    return `<div class="setup-guide-empty">还没有生成结果。点击上方按钮后，只会先展示一条简要结果。</div>`;
  }
  const currentSegment = currentSegments[0] || null;
  const currentSummary = usefulCurrentText
    ? usefulCurrentText.split(/\n+/).map((line) => line.trim()).filter(Boolean)[0]
    : currentSegment
      ? (currentSegment.summary || detailSegmentStatusLabel(currentSegment))
      : "";
  const planLabel = items.length ? `${items.length} 个日程点` : "粗日程无可展示条目";
  const detailLabel = currentSummary ? "当前时段已细化" : segments.length ? `已生成 ${segments.length} 个细化片段` : "当前时段未细化";
  const pending = Boolean(result.pending);
  const detailPending = Boolean(result.detail_pending);
  const detailError = String(result.detail_error || "").trim();
  const statusClass = pending || detailPending || detailError ? "is-warn" : currentSummary || segments.length || items.length ? "is-ok" : "is-warn";
  const title = pending ? "已先生成兜底日程" : detailPending ? "细化已转入后台" : "日程生成完成";
  const statusText = pending ? "正式日程仍在后台生成，首次配置可先继续" : detailPending ? "当前细化仍在后台生成，可先继续" : "";
  return `
    <div class="setup-guide-daily-simple ${statusClass}">
      <b>${escapeHtml(title)}</b>
      <span>${escapeHtml([plan.date || "", planLabel, detailLabel, statusText].filter(Boolean).join(" · "))}</span>
      ${detailError ? `<small>${escapeHtml(detailError)}</small>` : ""}
      ${currentSummary ? `<small>当前：${escapeHtml(currentSummary)}</small>` : ""}
      <details>
        <summary>查看详细日程和细化内容</summary>
        <div class="setup-guide-result-panel compact">
          <h4>今日粗日程${plan.date ? ` · ${escapeHtml(plan.date)}` : ""}</h4>
          <div class="setup-guide-mini-timeline">
            ${items.length ? items.slice(0, 8).map((item) => `
              <p><b>${escapeHtml(item.end ? `${item.time || "-"}-${item.end}` : item.time || "-")}</b><span>${escapeHtml([item.activity, item.mood].filter(Boolean).join(" · ") || "未命名日程")}</span></p>
            `).join("") : `<p><span>粗日程还没有可展示条目。</span></p>`}
          </div>
          <h4>当前细化</h4>
          ${usefulCurrentText ? `<pre class="setup-guide-detail-text">${escapeHtml(usefulCurrentText)}</pre>` : `
            <div class="setup-guide-mini-timeline">
              ${currentSegments.length ? currentSegments.slice(0, 3).map((segment) => `
                <p><b>${escapeHtml(segment.window || segment.key || "-")}</b><span>${escapeHtml(segment.summary || detailSegmentStatusLabel(segment))}</span></p>
              `).join("") : `<p><span>${segments.length ? `当前时段还没有可展示细化；已生成 ${segments.length} 个其他时段片段。` : "当前时段还没有细化结果。"}</span></p>`}
            </div>
          `}
        </div>
      </details>
    </div>
  `;
}

export function setupGuideDailyRunLabel() {
  const result = state.setupGuideDailyResult || {};
  if (result.loading) return "生成中...";
  if (result.ok) return "重新生成今日日程";
  return "快速生成今日日程";
}

export function setupGuideDailyRunHint() {
  const result = state.setupGuideDailyResult || {};
  if (result.loading) return "正在运行日程链路，完成后只显示简要结果。";
  if (result.ok) return "已跑通日程链路；当前细化可选，不再阻塞首次配置。";
  if (result.error) return "上次生成失败，修正模型或配置后可重试。";
  return "只强制生成今日粗日程，通常比完整细化快很多。";
}

export function setupGuidePrivateIntensityHtml() {
  const draft = setupGuideDraft();
  const preset = setupGuideIntensityPresets[draft.privateIntensity] || setupGuideIntensityPresets.off;
  return `
    <div class="setup-guide-question">
      <h4>选择预设</h4>
      <div class="setup-guide-choice-grid">
        ${setupGuideOption("privateIntensity", "off", "关闭预设", "沿用手动参数，不做运行态覆盖。")}
        ${setupGuideOption("privateIntensity", "balanced", "标准偏主动", "推荐首次使用。频率更有存在感，但仍克制。")}
        ${setupGuideOption("privateIntensity", "high_private", "私聊高频", "更常找目标用户，适合已经确认不会打扰。")}
        ${setupGuideOption("privateIntensity", "high_group", "群聊活跃", "侧重群聊唤醒和插话，私聊轻度增强。")}
        ${setupGuideOption("privateIntensity", "live", "在线陪伴", "最高档，不省主动成本；仍受硬边界约束。")}
      </div>
      ${setupGuideHint(`${preset.label}：${preset.description} 保存引导时会写入当前预设和下方参数。`)}
    </div>
    <div class="setup-guide-question">
      <h4>私聊影响参数</h4>
      <div class="setup-guide-grid-2">
        ${setupGuideNumber("privateMaxDailyMessages", "每日私聊主动上限", "9", { min: 0, description: "999999 表示不限；0 表示不主动发私聊。" })}
        ${setupGuideNumber("privateIdleMinutes", "空闲多久后可主动（分钟）", "40", { min: 0 })}
        ${setupGuideNumber("privateMinIntervalMinutes", "两次主动最小间隔（分钟）", "75", { min: 0 })}
        ${setupGuideNumber("privatePersonaJudgeThreshold", "人格发送判断阈值", "54", { min: 0, max: 100, description: "越低越容易通过主动发送判断。" })}
        ${setupGuideSelect("privateReviewStrength", "主动复核强度", [["lenient", "宽松"], ["balanced", "标准"], ["strict", "严格"]])}
        ${setupGuideNumber("privateDelayFactor", "主动延迟系数", "0.72", { min: 0, step: 0.01, description: "越低越不拖延。" })}
        ${setupGuideNumber("privateUnansweredSlowdownStart", "连续未回复降速起点", "2", { min: 0 })}
        ${setupGuideNumber("privateUnansweredMaxIntervalMultiplier", "未回复最大间隔倍率", "1.65", { min: 1, step: 0.05 })}
        ${setupGuideNumber("privateFriendUnansweredMaxCooldownHours", "次要用户未回复最长冷却（小时）", "30", { min: 0 })}
      </div>
      <div class="setup-guide-choice-grid">
        ${setupGuideCheck("privateIgnoreTokenSoftLimit", "忽略 Token 软限额降载", "只适合最高在线陪伴档；仍不会绕过每日 Token 硬限额。")}
        ${setupGuideCheck("privateIgnoreDailyLimit", "忽略每日主动次数上限", "只影响预设运行态，不绕过免打扰、隐私和用户拒绝。")}
      </div>
    </div>
    <div class="setup-guide-question">
      <h4>联动影响参数</h4>
      <div class="setup-guide-grid-2">
        ${setupGuideNumber("groupWakeCooldownSeconds", "群唤醒冷却（秒）", "50", { min: 0 })}
        ${setupGuideNumber("groupWakeInterestProbability", "兴趣唤醒概率（%）", "24", { min: 0, max: 100 })}
        ${setupGuideNumber("groupWakeQuestionThreshold", "解惑唤醒阈值", "60", { min: 0, max: 100 })}
        ${setupGuideNumber("groupWakeColdGroupThreshold", "冷群唤醒阈值", "62", { min: 0, max: 100 })}
        ${setupGuideNumber("groupInterjectMinIntervalMinutes", "群插话最小间隔（分钟）", "90", { min: 0 })}
        ${setupGuideNumber("groupInterjectMaxDaily", "群插话每日上限", "4", { min: 0 })}
      </div>
    </div>
  `;
}

export function setupGuideGroupConfigHtml() {
  const draft = setupGuideDraft();
  return `
    <div class="setup-guide-question">
      <h4>群聊唤醒入口</h4>
      ${setupGuideText("groupWakeDirectWords", "强唤醒词", "Bot 名字、昵称、固定称呼；多个词可用逗号或换行分隔。", true, {
        badge: "建议填写",
        badgeTone: "recommended",
        description: "消息中出现这些词时，会被视为明确叫到 Bot。",
      })}
      <div class="setup-guide-choice-grid">
        ${setupGuideCheck("groupWakeEnhancement", "开启唤醒增强", "结合弱相关词、兴趣词、问题句和冷群场景判断是否进入回复链。")}
      </div>
    </div>
    ${draft.groupWakeEnhancement ? `
      <div class="setup-guide-question">
        <h4>唤醒增强基础配置</h4>
        <div class="setup-guide-grid-2">
          ${setupGuideText("groupWakeContextWords", "弱相关唤醒词", "机器人, bot, 角色名, 作品名", true, {
            description: "命中后不会直接回复，会结合上下文判断是否自然接话。",
          })}
          ${setupGuideText("groupWakeInterestKeywords", "兴趣关键词", "游戏, 日常, 学习", true, {
            description: "命中后按概率进入回复链，不会每次都抢话。",
          })}
          ${setupGuideNumber("groupWakeInterestProbability", "兴趣唤醒概率（%）", "18", { min: 0, max: 100 })}
          ${setupGuideNumber("groupWakeCooldownSeconds", "唤醒冷却（秒）", "90", { min: 0 })}
          ${setupGuideNumber("groupWakeGeneratedKeywordLimit", "自动兴趣词上限", "8", { min: 0 })}
          ${setupGuideNumber("groupWakeTopicInterestMaxBoost", "话题兴趣权重上限（%）", "50", { min: 0, max: 200 })}
          ${setupGuideNumber("groupWakeDebouncePendingPenalty", "补话等待降权（%）", "30", { min: 0, max: 100 })}
          ${setupGuideNumber("groupWakeShortTextWaitSeconds", "短唤醒补话等待（秒）", "8", { min: 0 })}
          ${setupGuideNumber("groupWakeFatigueLimit", "唤醒疲劳阈值", "5", { min: 0 })}
          ${setupGuideNumber("groupWakeFatigueDecayMinutes", "疲劳恢复分钟", "20", { min: 1 })}
        </div>
        <div class="setup-guide-choice-grid">
          ${setupGuideCheck("groupWakeQuestion", "开启解惑唤醒", "群里有人求助或开放提问时，按强度阈值判断是否回复。")}
          ${setupGuideCheck("groupWakeColdGroup", "开启冷群唤醒", "群聊安静一段时间后有人重新开口时，按强度阈值判断是否接话。")}
        </div>
        <div class="setup-guide-grid-2">
          ${draft.groupWakeQuestion ? setupGuideNumber("groupWakeQuestionThreshold", "解惑强度阈值", "65", { min: 0, max: 100 }) : ""}
          ${draft.groupWakeColdGroup ? setupGuideNumber("groupWakeColdGroupThreshold", "冷群强度阈值", "65", { min: 0, max: 100 }) : ""}
          ${draft.groupWakeColdGroup ? setupGuideNumber("groupWakeColdGroupIdleMinutes", "冷群判定分钟", "45", { min: 1 }) : ""}
        </div>
      </div>
    ` : ""}
    <div class="setup-guide-question">
      <h4>群聊主动插话</h4>
      <div class="setup-guide-choice-grid">
        ${setupGuideOption("groupInterjection", "off", "关闭插话", "只响应明确唤醒。")}
        ${setupGuideOption("groupInterjection", "observe", "先观察", "推荐首次配置。建立群资料，不主动插话。")}
        ${setupGuideOption("groupInterjection", "low", "低频插话", "谨慎开启，限制间隔和每日次数。")}
      </div>
      <div class="setup-guide-grid-2">
        ${setupGuideNumber("groupInterjectMinIntervalMinutes", "插话最小间隔（分钟）", "180", { min: 0 })}
        ${setupGuideNumber("groupInterjectMaxDaily", "每日插话上限", "2", { min: 0 })}
      </div>
      <div class="setup-guide-choice-grid">
        ${setupGuideCheck("groupInterjectionFeedback", "开启插话反馈学习", "记录群友对插话的反馈，后续用于降低打扰感。")}
      </div>
    </div>
  `;
}

export function setupGuideWorldbookDraftHtml() {
  const draft = setupGuideDraft();
  const aliases = String(draft.worldbookAliases || "").split(/[\n,，;；]+/).map((item) => item.trim()).filter(Boolean);
  return `
    <div class="worldbook-member-card setup-guide-worldbook-card ${draft.worldbookEnabled ? "" : "off"}">
      <div class="worldbook-member-head">
        <div>
          <b>${escapeHtml(draft.worldbookNickname || draft.worldbookUserId || "新关系节点")}</b>
          <span>身份 QQ ${escapeHtml(draft.worldbookUserId || "-")}</span>
        </div>
        <span class="badge">${draft.worldbookDraftConfirmed ? "草稿已确认" : "草稿未确认"}</span>
      </div>
      <div class="worldbook-chip-row">
        ${aliases.length ? aliases.slice(0, 10).map((name) => `<span>别名：${escapeHtml(name)}</span>`).join("") : `<span>暂无别名</span>`}
      </div>
      <div class="worldbook-editor setup-guide-worldbook-editor">
        <div class="setup-guide-choice-grid">
          ${setupGuideCheck("worldbookEnabled", "启用这个关系节点", "启用后才会参与关系网识别和上下文注入。")}
          ${setupGuideCheck("worldbookSelfRegistration", "介绍自登记方法", "完成首次配置后，可以告诉群友如何按规则自登记，再由你审核。")}
        </div>
        <div class="setup-guide-grid-2">
          ${setupGuideText("worldbookUserId", "身份 QQ / 节点 ID", "10001", false, { badge: "必填", badgeTone: "required" })}
          ${setupGuideText("worldbookNickname", "名称 / 昵称", "朋友", false, { badge: "必填", badgeTone: "required" })}
          ${setupGuideText("worldbookGender", "性别", "可填男、女、未知或自定义描述")}
        </div>
        ${setupGuideText("worldbookAliases", "别名", "每行一个：群名片、常用昵称、缩写", true)}
        ${setupGuideText("worldbookContent", "资料正文", "稳定身份、兴趣、关系定位、常见互动方式。", true, {
          description: "只写稳定事实，不把一次玩笑写成长期设定。",
        })}
        ${setupGuideText("worldbookIdentityNote", "身份说明", "例如：现实朋友、群友、同学、同事等。", true)}
        ${setupGuideText("worldbookBoundaryNote", "互动边界", "例如：不公开聊隐私；不拿某个话题开玩笑。", true)}
        <div class="setup-guide-provider-test-actions">
          <button type="button" data-setup-guide-worldbook-confirm>${draft.worldbookDraftConfirmed ? "重新确认词条草稿" : "确认词条草稿"}</button>
          <span>完成引导时会写入关系网词条；确认按钮用于标记你已经检查过草稿。</span>
        </div>
      </div>
    </div>
  `;
}

export function setupGuideProactiveTestPassed() {
  const current = state.setupGuideProactiveTest;
  if (current && ["starting", "waiting", "polling", "error"].includes(current.status || "")) {
    const currentResult = current.result || {};
    return Boolean(current.status === "ok" && currentResult.ok && !currentResult.pending);
  }
  const result = current?.result || state.troubleshooting?.chain_tests?.proactive_message || {};
  return Boolean(result && result.ok && !result.pending);
}

export function setupGuideProactiveTestHtml() {
  const testState = state.setupGuideProactiveTest || {};
  const hasCurrentState = Boolean(state.setupGuideProactiveTest);
  const result = hasCurrentState ? (testState.result || {}) : (state.troubleshooting?.chain_tests?.proactive_message || {});
  const status = testState.status || (result.ran_at_text ? (result.pending ? "pending" : result.ok ? "ok" : "error") : "idle");
  const passed = Boolean(result.ok && !result.pending);
  const applying = Boolean(state.setupGuideApplying);
  const meta = [
    result.umo ? `会话 ${result.umo}` : "",
    result.ran_at_text || "",
    result.elapsed_ms ? `${result.elapsed_ms}ms` : "",
  ].filter(Boolean).join(" · ");
  const message = (() => {
    if (status === "starting") return "正在预约 15 秒后的主动消息链路测试。";
    if (status === "waiting") {
      const countdown = Number(testState.countdown || 0);
      return countdown > 0 ? `已预约，${Math.max(0, countdown)} 秒后开始检查结果。` : "已预约，正在等待主动循环完成完整测试。";
    }
    if (status === "polling") return "主动循环已到测试窗口，正在刷新完整链路结果。";
    if (passed) return "主动消息链路测试通过，首次配置可以完成。";
    if (status === "error") return result.error || testState.error || "主动消息链路测试失败。";
    if (result.pending) return result.detail || "主动消息链路测试已预约，等待主动循环执行。";
    if (result.ran_at_text && !result.ok) return result.error || result.detail || "主动消息链路测试未通过。";
    return "点击按钮后，会复用排障页的主动消息测试链路，预约 15 秒后的临时主动任务。";
  })();
  return `
    <div class="setup-guide-test-panel ${escapeHtml(passed ? "ok" : status === "error" || (result.ran_at_text && !result.ok && !result.pending) ? "error" : status)}">
      <header>
        <div>
          <b>主动消息链路测试</b>
          <span>${escapeHtml(message)}</span>
          ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
        </div>
        <button type="button" data-setup-guide-proactive-test ${["starting", "waiting", "polling"].includes(status) ? "disabled" : ""}>
          ${passed ? "重新测试主动消息" : status === "idle" || status === "error" ? "测试主动消息" : "测试中..."}
        </button>
      </header>
      ${troubleshootingChainStepsMarkup(result.steps)}
      ${troubleshootingChainPreviewMarkup("proactive_message", result)}
      ${passed ? `
        <div class="setup-guide-completion-choice">
          <b>首次配置已通过</b>
          <span>点击下方按钮会把弹窗中的配置写入插件配置和关系网，再结束首次引导。</span>
          <div>
            <button type="button" data-setup-guide-finish-explore ${applying ? "disabled" : ""}>${applying ? "保存中..." : "保存并自行探索"}</button>
            <button type="button" data-setup-guide-advanced ${applying ? "disabled" : ""}>${applying ? "保存中..." : "保存并继续进阶功能引导"}</button>
          </div>
          ${state.setupGuideAdvancedRequested ? `<small>已选择继续进阶功能引导；进阶问卷入口会接在这个完成状态后。</small>` : ""}
        </div>
      ` : ""}
    </div>
  `;
}

export function rerenderSetupGuideOverlayPreserveScroll() {
  const modal = document.querySelector(".setup-guide-modal");
  const scrollTop = modal ? modal.scrollTop : 0;
  renderSetupGuideOverlay();
  const nextModal = document.querySelector(".setup-guide-modal");
  if (nextModal) nextModal.scrollTop = scrollTop;
}

export function setupGuideQuestionnaireHtml(index, overview = state.overview || {}) {
  const settings = overview.settings || {};
  const providers = overview.providers || {};
  const targetUsers = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  if (index === 0) {
    return `
      ${setupGuideStatusPills(overview)}
      <div class="setup-guide-question">
        <h4>插件基本连接</h4>
        ${setupGuideHint(overview.plugin ? "页面 API 已连接。平台默认 aiocqhttp；不是 OneBot 时修改下方 target_platform。" : "页面 API 未连接。先刷新拓展页，或检查插件是否加载。", overview.plugin ? "ok" : "warn")}
      </div>
      <div class="setup-guide-question">
        <h4>目标用户</h4>
        ${setupGuideHint(targetUsers.length ? `已预填 ${targetUsers.length} 个目标用户。检查用户 ID 和平台后继续。` : "未找到目标用户。请先填写要陪伴的用户 ID。", targetUsers.length ? "ok" : "warn")}
        ${setupGuideText("targetUserIds", "目标用户 ID", "每行一个用户 ID；OneBot 填 QQ，官方机器人填 openid；私聊 UMO 会自动提取", true)}
        ${setupGuideText("targetPlatform", "target_platform", "aiocqhttp / qq_official")}
      </div>
      <div class="setup-guide-question">
        <h4>运行策略与权限</h4>
        ${setupGuideText("quietHours", "免打扰时段", "23:00-08:30")}
        <div class="setup-guide-choice-grid">
          ${setupGuideCheck("requirePrivateOptIn", "管理命令仅限私聊执行", "群聊中不响应状态修改指令，降低误操作风险。")}
        </div>
      </div>
    `;
  }
  if (index === 1) {
    const loadedProviderCount = state.availableProviders.length;
    return `
      <div class="setup-guide-question">
        <h4>填写快捷模型</h4>
        ${setupGuideHint(loadedProviderCount ? `已读取 ${loadedProviderCount} 个 Provider。分别选择模型，并完成必测项。` : "未读取到 Provider 列表。可先手动输入 Provider ID，再测试连通。", loadedProviderCount ? "ok" : "warn")}
        ${setupGuideQuickProviderGridHtml(providers)}
      </div>
      <div class="setup-guide-question">
        <h4>当前选择结果</h4>
        ${setupGuideModelSummaryHtml(providers)}
      </div>
      ${setupGuideHint("需要更细分工时，之后到模型页切换为精准模式。")}
    `;
  }
  if (index === 2) {
    const hasDraft = Boolean(state.setupGuideRoleplayDraft) || setupGuideHasWorldKnowledgeDraft();
    const draftConfirmed = Boolean(setupGuideDraft().worldKnowledgeConfirmed);
    const stepDone = (label) => `<span class="wk-step-done">${escapeHtml(label)}</span>`;
    return `
      <div class="setup-guide-boundary compact">
        <b>世界知识 ≠ 聊天人格</b>
        <span>这里生成的草稿只供陪伴插件的日程、状态、主动消息、识图等功能参考；实际聊天仍使用 AstrBot 配置的人格。</span>
      </div>
      <div class="wk-step-flow">
        <div class="wk-step-card ${hasDraft ? "done" : "active"}">
          <div class="wk-step-card-head">
            <span class="wk-step-num">${hasDraft ? "✓" : "1"}</span>
            <h4>选择人格来源</h4>
            ${hasDraft ? stepDone("已生成") : ""}
          </div>
          <div class="wk-step-card-body">
            ${setupGuidePersonaSelectHtml()}
            ${setupGuideText("worldKnowledgeNote", "补充推导提示（可选）", "例如：更重视校园日常、工作作息、现实关系边界；不希望主动聊太私密的话题。", true, {
              badge: "可选",
              description: "会参与本次推导；完成引导时随草稿保存。",
            })}
          </div>
          <div class="wk-step-card-foot">
            <button type="button" data-setup-guide-roleplay-draft>${hasDraft ? "重新生成草稿" : "从人格推导世界知识草稿"}</button>
            <span class="wk-time-hint">⏱ 生成通常需要 1-2 分钟，请耐心等待</span>
          </div>
        </div>
        <div class="wk-step-card ${hasDraft ? (draftConfirmed ? "done" : "active") : ""}">
          <div class="wk-step-card-head">
            <span class="wk-step-num">${draftConfirmed ? "✓" : "2"}</span>
            <h4>${hasDraft ? "检查并确认草稿" : "等待生成草稿"}</h4>
            ${draftConfirmed ? stepDone("已确认") : ""}
          </div>
          <div class="wk-step-card-body">
            ${setupGuideWorldKnowledgeEditorHtml()}
          </div>
        </div>
      </div>
      ${hasDraft ? setupGuideHint("草稿已生成。确认内容无误后继续；改动较多时先点「确认使用这份草稿」。", "ok") : ""}
    `;
  }
  if (index === 3) {
    return `
      <div class="setup-guide-question">
        <h4>主动能力</h4>
        <div class="setup-guide-choice-grid">
          ${setupGuideCheck("proactivePrivate", "私聊主动", "推荐首次开启。允许 Bot 在合适时机主动找目标用户，仍受免打扰、发送闸和强度限制。")}
          ${setupGuideCheck("proactiveGroup", "群聊主动", "按需开启。允许群聊唤醒增强或主动插话；下一步会单独配置群聊边界。")}
        </div>
      </div>
      ${setupGuideHint("这里只配置核心主动边界；新闻、搜索、QQ 空间、生图、TTS 放到进阶引导。")}
    `;
  }
  if (index === 4) {
    const dailyBusy = Boolean(state.setupGuideDailyResult?.loading);
    const dailyReady = Boolean(state.setupGuideDailyResult?.ok || state.overview?.daily_plan?.date);
    return `
      <div class="setup-guide-question">
        <h4>快速初始化今日生活节奏</h4>
        <div class="setup-guide-provider-test-actions">
          <button type="button" data-setup-guide-daily-run="plan" ${dailyBusy ? "disabled" : ""}>${setupGuideDailyRunLabel()}</button>
          <button type="button" data-setup-guide-daily-run="detail" ${dailyBusy || !dailyReady ? "disabled" : ""}>补充当前细化</button>
          <span>${escapeHtml(setupGuideDailyRunHint())} “补充当前细化”会多跑一次模型，慢一些，但不是首次配置必需。</span>
        </div>
      </div>
      <div class="setup-guide-question">
        <h4>运行结果</h4>
        ${setupGuideDailyResultHtml()}
      </div>
      ${setupGuideHint("首次只要求今日粗日程可用；当前场景细化可稍后到观察页刷新。")}
    `;
  }
  if (index === 5) {
    return setupGuidePrivateIntensityHtml();
  }
  if (index === 6) {
    return `
      ${setupGuideGroupConfigHtml()}
      ${setupGuideHint("保存后到群聊页查看群资料、话题线程、唤醒记录和插话效果。")}
    `;
  }
  if (index === 7) {
    return `
      <div class="setup-guide-question">
        <h4>关系网第一条用户词条</h4>
        ${setupGuideHint("先填一个稳定用户，用来对应 QQ、昵称、群名片和关系备注。")}
      </div>
      ${setupGuideWorldbookDraftHtml()}
      ${setupGuideHint("保存后到关系网页继续导入资料、审核观察、编辑记忆。")}
    `;
  }
  return `
    <div class="setup-guide-question">
      <h4>主动消息测试</h4>
      ${setupGuideProactiveTestHtml()}
    </div>
    ${setupGuideHint("测试会真实走主动生成、复核、发送和归档链路；点击后等待 15 秒再检查结果。", "warn")}
  `;
}

export function setupGuideRunThroughItems(overview = state.overview || {}) {
  const settings = overview.settings || {};
  const providers = overview.providers || {};
  const draft = setupGuideDraft();
  const targetUsers = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const draftTargetUsers = String(draft.targetUserIds || "").split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean);
  const fastProvider = setupGuideProviderValue("FAST_RESPONSE_PROVIDER_ID", providers);
  const complexProvider = setupGuideProviderValue("COMPLEX_REASONING_PROVIDER_ID", providers);
  const creativeProvider = setupGuideProviderValue("CREATIVE_MODEL_PROVIDER_ID", providers);
  const visionProvider = setupGuideProviderValue("PLUGIN_VISION_PROVIDER_ID", providers);
  const requiredQuickProvidersReady = setupGuideAllProviderTestsPassed();
  const hasTargetUsers = Boolean(targetUsers.length || draftTargetUsers.length);
  const hasGroupConfig = Boolean(String(draft.groupWakeDirectWords || "").trim() || draft.proactiveGroup || draft.groupInterjection !== "off");
  const hasWorldbookDraft = Boolean(String(draft.worldbookUserId || draft.worldbookNickname || draft.worldbookContent || "").trim());

  const items = [
    {
      level: hasTargetUsers ? "ok" : "warn",
      title: "基础连通",
      tab: "dashboard",
      action: "检查插件页面 API、目标用户 ID、target_platform、免打扰时段和管理命令权限。",
      pass: hasTargetUsers ? "基础项齐备，可以继续首次配置。" : "需要补齐目标用户 ID。",
    },
    {
      level: requiredQuickProvidersReady ? "ok" : "warn",
      title: "快捷模型",
      tab: "models",
      action: "在弹窗内填写快速响应、复杂推理、创作和插件识图四类 Provider。",
      pass: requiredQuickProvidersReady
        ? "快速响应和复杂推理已完成测试，可以进入下一步；创作和识图模型可按需后补测试。"
        : `需要先选择并测试通过快速响应和复杂推理。当前选择：快速${fastProvider ? "已选" : "缺失"}、复杂${complexProvider ? "已选" : "缺失"}、创作${creativeProvider ? "已选" : "可后补"}、视觉${visionProvider ? "已选" : "可后补"}。`,
    },
    {
      level: draft.inferWorldKnowledge ? "info" : "skip",
      title: "人格与世界知识",
      tab: "roleplay",
      action: "从 AstrBot 人格推导世界知识草稿，并解释插件世界知识与回复人格的边界。",
      pass: draft.inferWorldKnowledge ? "生成草稿并等待用户确认，完成引导时写入世界知识。" : "用户选择不推导世界知识。",
    },
    {
      level: draft.proactivePrivate ? "info" : "warn",
      title: "主动功能",
      tab: "proactive",
      action: "按私聊主动、群聊主动选择生成首轮主动配置建议。",
      pass: draft.proactivePrivate ? "已开启私聊主动，可以完成主动消息链路测试。" : "首次配置需要开启私聊主动。",
    },
    {
      level: draft.generateSchedule ? "info" : "skip",
      title: "日程与观察",
      tab: "memory",
      action: "生成今日粗日程并按需细化当前日程。",
      pass: draft.generateSchedule ? "已提供日程生成入口，结果会直接写入今日运行态。" : "用户选择跳过日程初始化。",
    },
    {
      level: draft.privateIntensity === "off" ? "skip" : "info",
      title: "私聊强度",
      tab: "private",
      action: "根据强度选择生成私聊主动频率和免打扰边界。",
      pass: draft.privateIntensity === "off" ? "私聊主动强度关闭。" : "完成引导时写入强度预设和可持久化参数。",
    },
    {
      level: hasGroupConfig || hasWorldbookDraft ? "info" : "skip",
      title: "群聊配置",
      tab: "group",
      action: "生成群唤醒和插话配置。",
      pass: hasGroupConfig ? "已填写群聊配置草稿。" : "群聊配置未填写，可以稍后补充。",
    },
    {
      level: hasWorldbookDraft ? "info" : "skip",
      title: "关系网词条",
      tab: "worldbook",
      action: "准备一条关系网用户词条。",
      pass: hasWorldbookDraft ? "已填写关系网词条草稿。" : "关系网词条未填写，可以稍后补充。",
    },
    {
      level: draft.proactivePrivate && requiredQuickProvidersReady ? "info" : "warn",
      title: "主动测试",
      tab: "proactive",
      action: "生成一次主动候选并展示复核、发送闸和是否真实发送。",
      pass: draft.proactivePrivate ? "主动测试会走完整私聊排障链路，完成引导时保存配置。" : "未开启私聊主动，无法完成主动测试。",
    },
  ];
  return items;
}

export function setupGuideStepIndex() {
  const maxIndex = setupGuideSteps.length - 1;
  const index = Number(state.setupGuideStep || 0);
  return Math.max(0, Math.min(maxIndex, Number.isFinite(index) ? index : 0));
}

export function setupGuideCanLeaveCurrentStep(targetIndex) {
  return !setupGuideStepBlockMessage(targetIndex);
}

export function setupGuideStepBlockMessage(targetIndex) {
  const draft = setupGuideDraft();
  const nextIndex = Number(targetIndex);
  if (nextIndex > 0) {
    const targetUsers = String(draft.targetUserIds || "").split(/[\s,，;；、]+/).map((item) => item.trim()).filter(Boolean);
    if (!targetUsers.length) return "请先填写目标用户 ID";
    if (!String(draft.targetPlatform || "").trim()) return "请先填写 target_platform";
  }
  if (Number(targetIndex) > 1 && !setupGuideAllProviderTestsPassed()) {
    const missing = setupGuideProviderTestMissingLabels();
    return `请先完成模型测试：${missing.join("、")}`;
  }
  return "";
}

export async function testSetupGuideProvider(key, control = null) {
  if (!setupGuideQuickProviderKeys.includes(key)) return false;
  const providerId = setupGuideProviderValue(key, state.overview?.providers || {});
  if (!providerId) {
    showToast(`请先选择${providerLabels[key] || key}`, "error");
    return false;
  }
  state.setupGuideProviderTests = {
    ...(state.setupGuideProviderTests || {}),
    [key]: { status: "running", provider_id: providerId },
  };
  updateSetupGuideStatusViews();
  if (control instanceof HTMLButtonElement) setActionBusy(control, true);
  try {
    const result = await postJson("/provider/test", { key, provider_id: providerId });
    const ok = Boolean(result?.ok);
    state.setupGuideProviderTests = {
      ...(state.setupGuideProviderTests || {}),
      [key]: {
        status: ok ? "ok" : "fail",
        provider_id: providerId,
        elapsed_ms: result?.elapsed_ms || 0,
        sample: result?.sample || "",
        error: result?.error || (ok ? "" : "未返回有效结果"),
      },
    };
    updateSetupGuideStatusViews();
    if (!ok) showToast(`${providerLabels[key] || key}测试失败：${result?.error || "未返回有效结果"}`, "error");
    return ok;
  } catch (error) {
    state.setupGuideProviderTests = {
      ...(state.setupGuideProviderTests || {}),
      [key]: {
        status: "fail",
        provider_id: providerId,
        error: error.message || "请求失败",
      },
    };
    updateSetupGuideStatusViews();
    showToast(`${providerLabels[key] || key}测试失败：${error.message}`, "error");
    return false;
  } finally {
    if (control instanceof HTMLButtonElement) setActionBusy(control, false);
    updateSetupGuideStatusViews();
  }
}

export async function testAllSetupGuideProviders(control = null) {
  const missing = setupGuideRequiredProviderTestKeys.filter((key) => !setupGuideProviderValue(key, state.overview?.providers || {}));
  if (missing.length) {
    showToast(`请先选择：${missing.map((key) => providerLabels[key] || key).join("、")}`, "error");
    return;
  }
  if (control instanceof HTMLButtonElement) setActionBusy(control, true);
  try {
    for (const key of setupGuideRequiredProviderTestKeys) {
      const ok = await testSetupGuideProvider(key);
      if (!ok) return;
    }
    showToast("必需模型测试通过");
  } finally {
    if (control instanceof HTMLButtonElement) setActionBusy(control, false);
    updateSetupGuideStatusViews();
  }
}

export async function generateSetupGuideRoleplayDraft(control = null) {
  const draft = setupGuideDraft();
  const personaId = String(draft.personaId || "").trim();
  if (control instanceof HTMLButtonElement) setActionBusy(control, true);
  showToast("正在从人格推导世界知识草稿，通常需要 1-2 分钟...");
  try {
    const result = await postJson("/roleplay/draft_from_persona", {
      persona_id: personaId,
      scopes: ["persona", "world", "user"],
      extra_prompt: String(draft.worldKnowledgeNote || "").trim(),
    });
    setupGuideApplyRoleplayDraft(result);
    renderSetupGuideOverlay();
    showToast("世界知识草稿已生成，可直接进入下一步");
  } catch (error) {
    showToast(`生成失败：${error.message}`, "error");
  } finally {
    if (control instanceof HTMLButtonElement) setActionBusy(control, false);
  }
}

export async function runSetupGuideDailyGeneration(control = null) {
  const draft = setupGuideDraft();
  const mode = control instanceof HTMLElement ? String(control.dataset.setupGuideDailyRun || "plan") : "plan";
  const forceDetail = mode === "detail";
  state.setupGuideDailyResult = { ...(state.setupGuideDailyResult || {}), loading: true, mode };
  rerenderSetupGuideOverlayPreserveScroll();
  if (control instanceof HTMLButtonElement) setActionBusy(control, true);
  showToast(forceDetail ? "正在补充当前日程细化..." : "正在快速生成今日日程...");
  try {
    const result = await postJson("/setup/daily/run", {
      generate_schedule: forceDetail ? false : Boolean(draft.generateSchedule),
      refine_schedule: forceDetail ? true : false,
      force_detail: forceDetail,
      timeout_seconds: forceDetail ? 45 : 18,
    });
    if (!result?.ok) {
      state.setupGuideDailyResult = { error: result?.error || "生成失败" };
      rerenderSetupGuideOverlayPreserveScroll();
      showToast(`日程生成失败：${result?.error || "未返回有效结果"}`, "error");
      return;
    }
    state.setupGuideDailyResult = result;
    state.overview = {
      ...(state.overview || {}),
      daily_state: result.daily_state || state.overview?.daily_state || {},
      daily_timeline: result.daily_timeline || state.overview?.daily_timeline || {},
      daily_plan: result.plan || state.overview?.daily_plan || {},
    };
    rerenderSetupGuideOverlayPreserveScroll();
    if (forceDetail && result.detail_pending) showToast("当前细化已转入后台，可先继续配置");
    else if (forceDetail && result.detail_error) showToast(result.detail_error, "error");
    else showToast(forceDetail ? "当前日程细化已生成" : "今日日程已生成");
  } catch (error) {
    state.setupGuideDailyResult = { error: error.message || "请求失败" };
    rerenderSetupGuideOverlayPreserveScroll();
    showToast(`日程生成失败：${error.message}`, "error");
  } finally {
    if (control instanceof HTMLButtonElement) setActionBusy(control, false);
  }
}

export function clearSetupGuideProactivePoll() {
  if (asteriaWorkspaceState.setupGuideProactivePollTimer) {
    window.clearInterval(asteriaWorkspaceState.setupGuideProactivePollTimer);
    asteriaWorkspaceState.setupGuideProactivePollTimer = null;
  }
}

export async function refreshSetupGuideProactiveTestResult() {
  const data = await fetchJson("/troubleshooting");
  state.troubleshooting = data || state.troubleshooting || {};
  const result = state.troubleshooting?.chain_tests?.proactive_message || {};
  if (result.ran_at_text && !result.pending) {
    state.setupGuideProactiveTest = {
      status: result.ok ? "ok" : "error",
      result,
      countdown: 0,
      checkedAt: Date.now(),
    };
    clearSetupGuideProactivePoll();
    rerenderSetupGuideOverlayPreserveScroll();
    showToast(result.ok ? "主动消息测试通过，首次配置可以完成" : `主动消息测试失败：${result.error || result.detail || "未返回有效结果"}`, result.ok ? "success" : "error");
    return result;
  }
  const deadlineAt = Number(state.setupGuideProactiveTest?.deadlineAt || 0);
  if (result.pending && deadlineAt > 0 && Date.now() >= deadlineAt) {
    const errorText = "主动消息测试等待超时。请确认主动循环已启动、目标用户有私聊会话，或稍后重新测试。";
    state.setupGuideProactiveTest = {
      ...(state.setupGuideProactiveTest || {}),
      status: "error",
      result: { ...result, pending: false, ok: false, error: result.error || errorText },
      countdown: 0,
      error: result.error || errorText,
      checkedAt: Date.now(),
    };
    clearSetupGuideProactivePoll();
    rerenderSetupGuideOverlayPreserveScroll();
    showToast(`主动消息测试失败：${result.error || errorText}`, "error");
    return state.setupGuideProactiveTest.result;
  }
  state.setupGuideProactiveTest = {
    ...(state.setupGuideProactiveTest || {}),
    status: "polling",
    result,
    countdown: 0,
  };
  rerenderSetupGuideOverlayPreserveScroll();
  return result;
}

export async function runSetupGuideProactiveTest(control = null) {
  if (!setupGuideFieldValue("proactivePrivate")) {
    showToast("主动消息测试需要先开启私聊主动", "error");
    return;
  }
  const savedForTest = await applySetupGuide({
    close: false,
    control,
    applyingMessage: "正在保存当前配置以运行主动消息测试...",
    successMessage: "配置已保存，开始主动消息测试",
  });
  if (!savedForTest) return;
  clearSetupGuideProactivePoll();
  state.setupGuideProactiveTest = { status: "starting", countdown: 15, result: null };
  rerenderSetupGuideOverlayPreserveScroll();
  if (control instanceof HTMLButtonElement) setActionBusy(control, true);
  try {
    const result = await postJson("/troubleshooting/test", {
      type: "proactive_message",
      delay_seconds: 15,
    });
    state.troubleshooting = state.troubleshooting || {};
    state.troubleshooting.chain_tests = {
      ...(state.troubleshooting.chain_tests || {}),
      proactive_message: result,
    };
    state.setupGuideProactiveTest = {
      status: result.pending ? "waiting" : result.ok ? "ok" : "error",
      result,
      countdown: result.pending && !String(result.detail || "").includes("已有一个排障临时主动任务") ? 15 : 0,
      startedAt: Date.now(),
      deadlineAt: result.pending ? Date.now() + SETUP_GUIDE_PROACTIVE_TEST_TIMEOUT_MS : 0,
      lastPollAt: 0,
    };
    rerenderSetupGuideOverlayPreserveScroll();
    if (!result.pending) {
      showToast(result.ok ? "主动消息测试通过" : `主动消息测试失败：${result.error || "未返回有效结果"}`, result.ok ? "success" : "error");
      return;
    }
    showToast("主动消息链路测试已预约，15 秒后自动检查结果");
    asteriaWorkspaceState.setupGuideProactivePollTimer = window.setInterval(() => {
      const current = state.setupGuideProactiveTest || {};
      const nextCountdown = Math.max(0, Number(current.countdown || 0) - 1);
      state.setupGuideProactiveTest = {
        ...current,
        status: nextCountdown > 0 ? "waiting" : "polling",
        countdown: nextCountdown,
      };
      rerenderSetupGuideOverlayPreserveScroll();
      if (nextCountdown <= 0) {
        const now = Date.now();
        const deadlineAt = Number((state.setupGuideProactiveTest || {}).deadlineAt || 0);
        const lastPollAt = Number((state.setupGuideProactiveTest || {}).lastPollAt || 0);
        if (lastPollAt && now - lastPollAt < 5000 && (!deadlineAt || now < deadlineAt)) return;
        state.setupGuideProactiveTest = {
          ...(state.setupGuideProactiveTest || {}),
          lastPollAt: now,
        };
        refreshSetupGuideProactiveTestResult().catch((error) => {
          state.setupGuideProactiveTest = {
            ...(state.setupGuideProactiveTest || {}),
            status: "error",
            error: error.message || "刷新结果失败",
          };
          clearSetupGuideProactivePoll();
          rerenderSetupGuideOverlayPreserveScroll();
          showToast(`刷新测试结果失败：${error.message}`, "error");
        });
      }
    }, 1000);
  } catch (error) {
    state.setupGuideProactiveTest = { status: "error", error: error.message || "请求失败", result: null };
    rerenderSetupGuideOverlayPreserveScroll();
    showToast(`主动消息测试失败：${error.message}`, "error");
  } finally {
    if (control instanceof HTMLButtonElement) setActionBusy(control, false);
  }
}

export function setupGuideApplyPayload() {
  return {
    draft: { ...setupGuideDraft() },
    provider_tests: state.setupGuideProviderTests || {},
    daily_result: state.setupGuideDailyResult || null,
    proactive_test: state.setupGuideProactiveTest || null,
  };
}

export async function applySetupGuide({ close = true, advanced = false, control = null, applyingMessage = "正在保存首次配置...", successMessage = "" } = {}) {
  if (state.setupGuideApplying) return false;
  state.setupGuideApplying = true;
  if (control instanceof HTMLButtonElement) setActionBusy(control, true);
  rerenderSetupGuideOverlayPreserveScroll();
  showToast(applyingMessage);
  try {
    const result = await postJson("/setup/apply", setupGuideApplyPayload());
    const overview = result && result.plugin ? result : result?.overview;
    if (overview && overview.plugin) {
      state.overview = overview;
      state.featureDraft = featureDraftFromOverview(overview);
      state.providerDraft = { ...(state.providerDraft || {}), ...(overview.providers || {}) };
      state.providerConfigMode = overview.settings?.provider_config_mode || state.providerConfigMode;
    } else {
      await loadAll();
    }
    clearSetupGuideProactivePoll();
    state.setupGuideAdvancedRequested = Boolean(advanced);
    if (close) state.setupGuideOpen = false;
    renderAll();
    renderSetupGuideOverlay();
    if (result?.config_saved === false || overview?.config_saved === false) {
      showToast("首次配置已应用到运行态，但配置持久化失败；请查看日志", "error");
    } else {
      showToast(successMessage || (advanced ? "首次配置已保存，接下来可以继续进阶配置" : "首次配置已保存，可以开始使用"));
    }
    return true;
  } catch (error) {
    showToast(`首次配置保存失败：${error.message}`, "error");
    return false;
  } finally {
    state.setupGuideApplying = false;
    if (control instanceof HTMLButtonElement) setActionBusy(control, false);
    if (state.setupGuideOpen) rerenderSetupGuideOverlayPreserveScroll();
    updateSetupGuideStatusViews();
  }
}

export function setupGuideModalHtml() {
  if (!state.setupGuideOpen) return "";
  const mode = state.setupGuideMode === "advanced" ? "advanced" : state.setupGuideMode === "first" ? "first" : "home";
  const index = setupGuideStepIndex();
  const step = setupGuideSteps[index] || setupGuideSteps[0];
  const advancedBlock = setupGuideAdvancedBlockMap[state.setupGuideAdvancedBlock || ""];
  const advancedItems = setupGuideAdvancedItems[state.setupGuideAdvancedBlock || ""] || [];
  const advancedStepIndex = setupGuideAdvancedStepIndex(state.setupGuideAdvancedBlock || "");
  const advancedLastStep = advancedBlock && advancedItems.length ? advancedStepIndex >= advancedItems.length - 1 : false;
  const proactiveTestPassed = setupGuideProactiveTestPassed();
  const applying = Boolean(state.setupGuideApplying);
  const firstNextDisabled = applying || (index === 1 && !setupGuideAllProviderTestsPassed());
  const nextDisabled = mode === "advanced" ? applying || !advancedBlock : firstNextDisabled;
  const nextLabel = mode === "advanced"
    ? applying ? "保存中..." : advancedBlock ? (advancedLastStep ? "保存本板块" : "下一项") : "先选择板块"
    : applying ? "保存中..." : index >= setupGuideSteps.length - 1 ? "保存并完成" : "下一步";
  const advancedCurrentItem = advancedItems[advancedStepIndex] || null;
  const title = mode === "home" ? "配置引导" : mode === "advanced" ? (advancedBlock ? `${advancedBlock.title} · ${advancedCurrentItem?.title || "问卷"}` : "选择进阶配置板块") : step.title;
  const tag = mode === "home" ? "选择引导类型" : mode === "advanced" ? (advancedBlock ? `进阶配置 · ${advancedStepIndex + 1}/${advancedItems.length || 1}` : "进阶配置") : `首次配置 · ${step.tag}`;
  const body = mode === "home"
    ? "先选择本次要做初次引导还是进阶引导。初次引导负责把核心链路跑通；进阶引导负责按板块打开更多能力。"
    : mode === "advanced"
    ? (advancedCurrentItem?.ask || advancedBlock?.body || "先选择一个板块，然后按问卷逐项确认需要哪些功能。每个功能都会说明它做什么，以及开启后要注意什么。")
    : step.body;
  return `
    <div class="setup-guide-overlay" role="presentation">
      <section class="setup-guide-modal" role="dialog" aria-modal="true" aria-label="配置引导">
        <header class="setup-guide-modal-head ${mode === "advanced" ? "compact" : ""}">
          <div>
            <span>${escapeHtml(tag)}</span>
            <h3>${escapeHtml(title)}</h3>
          </div>
          <button type="button" data-setup-guide-close aria-label="关闭引导">×</button>
        </header>
        <div class="setup-guide-mode-tabs" aria-label="配置模式">
          <button type="button" class="${mode === "home" ? "active" : ""}" data-setup-guide-mode="home">选择引导</button>
          <button type="button" class="${mode === "first" ? "active" : ""}" data-setup-guide-mode="first">首次配置</button>
          <button type="button" class="${mode === "advanced" ? "active" : ""}" data-setup-guide-mode="advanced">进阶配置</button>
        </div>
        ${mode === "home" || mode === "advanced" ? "" : `<div class="setup-guide-progress" aria-label="引导进度">
          ${mode === "advanced" ? setupGuideAdvancedBlocks.map((item) => {
            const active = item.id === state.setupGuideAdvancedBlock;
            const done = (setupGuideAdvancedItems[item.id] || []).some((feature) => Boolean(setupGuideFieldValue(feature.key)));
            return `
            <button type="button" class="${[active ? "active" : "", done ? "done" : ""].filter(Boolean).join(" ")}" data-setup-guide-advanced-block="${escapeHtml(item.id)}" title="${escapeHtml(item.title)}"></button>
          `;
          }).join("") : setupGuideSteps.map((item, itemIndex) => {
            const done = itemIndex < index || (itemIndex === setupGuideSteps.length - 1 && proactiveTestPassed);
            return `
            <button type="button" class="${[itemIndex === index ? "active" : "", done ? "done" : ""].filter(Boolean).join(" ")}" data-setup-guide-step="${itemIndex}" title="${escapeHtml(item.title)}"></button>
          `;
          }).join("")}
        </div>`}
        ${mode === "advanced" ? "" : `<p>${escapeHtml(body)}</p>`}
        <form class="setup-guide-form" data-setup-guide-form>
          ${mode === "home" ? setupGuideModeHomeHtml() : mode === "advanced" ? setupGuideAdvancedQuestionnaireHtml() : setupGuideQuestionnaireHtml(index, state.overview || {})}
        </form>
        ${mode === "home" ? "" : `<footer class="setup-guide-actions">
          <button type="button" data-setup-guide-prev ${mode === "first" ? (index <= 0 || applying ? "disabled" : "") : applying ? "disabled" : ""}>${mode === "advanced" ? (advancedBlock ? (advancedStepIndex > 0 ? "上一项" : "返回板块") : "返回选择") : "上一步"}</button>
          <button type="button" data-setup-guide-next ${nextDisabled ? "disabled" : ""}>${nextLabel}</button>
        </footer>`}
      </section>
    </div>
  `;
}

export function renderSetupGuideOverlay() {
  const root = $("#setupGuideOverlayRoot");
  if (!root) return;
  root.innerHTML = setupGuideModalHtml();
}

export function renderStats() {
  const overview = state.overview || {};
  const privateInfo = overview.private || {};
  const groupInfo = overview.group || {};
  const daily = overview.daily_state || {};
  const budget = state.tokenStats?.budget || {};
  const dailyUsed = Number(budget.used || 0);
  const dailyLimit = Number(budget.limit || 0);
  const featureKeys = visibleTopLevelFeatureKeys(overview.features || {});
  const enabledFeatures = featureKeys.filter((key) => overview.features?.[key]).length;
  const energyLabel = roleplayEnergyLabel(daily.energy);
  const energyNumber = daily.energy === undefined || daily.energy === "" ? "" : `${formatNumber(Number(daily.energy || 0))}/100`;
  const mood = normalizeRoleplayStateText(daily.mood_bias) || daily.note || "暂无状态";
  $("#stats").innerHTML = [
    statCard(`私聊 ${privateInfo.enabled_user_count || 0} · 群聊 ${groupInfo.enabled_group_count || 0}`, `总数：对象 ${privateInfo.user_count || 0} · 群聊 ${groupInfo.group_count || 0}`, "private"),
    statCard(dailyLimit > 0 ? `${formatCompactNumber(dailyUsed)} / ${formatCompactNumber(dailyLimit)}` : `${formatCompactNumber(dailyUsed)} / 不限`, "今日 Token 消耗 / 上限", "tokens"),
    statCard(energyLabel || "-", `心理能量${energyNumber ? ` ${energyNumber}` : ""} · ${mood}`, "memory"),
    statCard(`${enabledFeatures}/${featureKeys.length}`, "开启主开关 / 主开关总数", "config"),
  ].join("");
  updateSetupGuideBadge(overview);
}

export function updateSetupGuideBadge(overview) {
  const btn = document.getElementById("setupGuideStartBtn");
  if (!btn) return;
  const settings = overview?.settings || {};
  const providers = overview?.providers || {};
  const privateInfo = overview?.private || {};
  const intensity = overview?.proactive_intensity || {};
  const proactiveMax = intensity.effective?.max_daily_messages ?? privateInfo.max_daily_messages ?? 0;
  const targetUsers = Array.isArray(settings.target_user_ids) ? settings.target_user_ids.filter(Boolean) : [];
  const fastProvider = String(providers.FAST_RESPONSE_PROVIDER_ID || "").trim();
  const complexProvider = String(providers.COMPLEX_REASONING_PROVIDER_ID || "").trim();
  const criticalMissing = [
    !targetUsers.length,
    !(fastProvider && complexProvider),
    !Number(proactiveMax || 0),
  ].filter(Boolean).length;
  let badge = btn.querySelector(".setup-guide-badge");
  if (criticalMissing > 0) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "setup-guide-badge";
      btn.appendChild(badge);
    }
    badge.textContent = String(criticalMissing);
    btn.classList.add("has-badge");
  } else {
    if (badge) badge.remove();
    btn.classList.remove("has-badge");
  }
}

export function statCard(value, label, jumpTab = "") {
  return `<article class="stat ${jumpTab ? "is-link" : ""}" ${jumpTab ? `data-jump-tab="${escapeHtml(jumpTab)}"` : ""}><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span></article>`;
}

export function renderDashboard() {
  renderDashboardPulse();
  renderStrategyOverview();
  renderRelationshipChart();
  renderGroupBubbleChart();
  renderNewsInsightPanel();
  renderWebExplorationPanel();
  renderActivityHeatmap();
}

export function renderStrategyOverview() {
  const overview = state.overview || {};
  renderPrivateStrategyOverview("#privateConfig", overview.private || {});
  renderGroupStrategyOverview("#groupConfig", overview.group || {});
  renderLongTermStrategyOverview("#longTermConfig", {
    creative: overview.creative || {},
    bili: overview.bilibili || {},
    qzone: overview.qzone || {},
    privateReading: overview.private_reading || {},
  });
}

export function dashboardRefreshLabel() {
  const refreshedAt = Number(state.overviewRefreshedAt || 0);
  if (!refreshedAt) return "等待刷新";
  return `已刷新 ${new Date(refreshedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

export function dashboardLifeText(value, fallback = "暂无数据") {
  if (Array.isArray(value)) {
    const joined = value.map((item) => dashboardLifeText(item, "")).filter(Boolean).join("、");
    return joined || fallback;
  }
  if (value && typeof value === "object") {
    const picked = value.label || value.summary || value.status || value.phase || value.name || value.text;
    return dashboardLifeText(picked, fallback);
  }
  const text = String(value ?? "").trim();
  return text || fallback;
}

export function renderDashboardLifeDesk(overview = {}) {
  const daily = overview.daily_state || {};
  const life = overview.life_observation || {};
  const current = life.current_plan || {};
  const timeline = overview.daily_timeline || {};
  const outfit = overview.daily_outfit || {};
  const worldbook = overview.worldbook || {};
  const livingmemory = overview.livingmemory || {};
  const date = daily.date || timeline.plan_date || new Date().toLocaleDateString("zh-CN");
  const dateNode = $("#dashboardLifeDate");
  if (dateNode) dateNode.textContent = `${date} · ${dashboardRefreshLabel()}`;

  const factRoot = $("#dashboardTodayFacts");
  if (factRoot) {
    const facts = [
      ["天气", daily.weather],
      ["地点", daily.location],
      ["心情", normalizeRoleplayStateText(daily.mood_bias) || daily.note],
      ["日程", `${timeline.segment_count || 0} 个时间段`],
      ["健康", daily.health],
      ["穿搭", outfit.available ? "今日穿搭已生成" : (outfit.error || "暂无穿搭图")],
      ["睡眠", daily.sleep_phase || daily.sleep],
      ["身体", daily.body_cycle || daily.hunger],
    ];
    factRoot.innerHTML = facts.map(([label, value]) => `
      <div class="life-fact-item">
        <span>${escapeHtml(label)}</span>
        <b title="${escapeHtml(dashboardLifeText(value))}">${escapeHtml(dashboardLifeText(value))}</b>
      </div>
    `).join("");
  }

  const currentRoot = $("#dashboardCurrentState");
  if (currentRoot) {
    const energy = Math.max(0, Math.min(100, Number(daily.energy || 0)));
    const activityMeta = [
      current.end ? `${current.time || "--:--"}-${current.end}` : current.time,
      scheduleLifecycleLabel(current.lifecycle),
      current.mood,
    ].filter(Boolean).join(" · ");
    const states = [
      ["体力", daily.energy === undefined || daily.energy === "" ? "暂无" : `${Math.round(energy)}/100`],
      ["状态", daily.health],
      ["睡眠", daily.sleep_phase || daily.sleep],
      ["饥饿", daily.hunger],
      ["梦境", daily.dream],
      ["位置", daily.location],
    ];
    currentRoot.innerHTML = `
      <div class="life-current-activity">
        <small>${escapeHtml(activityMeta || "当前日程")}</small>
        <b>${escapeHtml(dashboardLifeText(current.activity, "暂无当前日程"))}</b>
        <span>${escapeHtml(dashboardLifeText(current.message_seed || daily.note, "暂无状态补充"))}</span>
      </div>
      <div class="life-energy-track" role="meter" aria-label="当前体力" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(energy)}"><i style="width:${energy}%"></i></div>
      <div class="life-state-grid">${states.map(([label, value]) => `
        <div><span>${escapeHtml(label)}</span><b>${escapeHtml(dashboardLifeText(value, "暂无"))}</b></div>
      `).join("")}</div>
    `;
  }

  const timelineRoot = $("#dashboardTimelinePreview");
  if (timelineRoot) {
    const segments = Array.isArray(timeline.segments) ? timeline.segments : [];
    const storyEvents = Array.isArray(timeline.story_today_events) ? timeline.story_today_events : [];
    const adjustments = Array.isArray(timeline.adjustments) ? timeline.adjustments : [];
    const timeMinutes = (value) => {
      const match = String(value || "").match(/(?:^|\s)(\d{1,2}):(\d{2})/);
      if (!match) return null;
      const hour = Number(match[1]);
      const minute = Number(match[2]);
      return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59 ? hour * 60 + minute : null;
    };
    const segmentIsCurrent = (segment) => {
      const lifecycle = String(segment?.lifecycle || "").toLowerCase();
      return lifecycle === "active"
        || Boolean(current.time && String(segment?.window || "").startsWith(String(current.time)));
    };
    const currentSegmentIndex = segments.findIndex(segmentIsCurrent);
    const timelineMeta = $("#dashboardTimelineMeta");
    if (timelineMeta) {
      timelineMeta.textContent = currentSegmentIndex >= 0
        ? `当前第 ${currentSegmentIndex + 1} / ${segments.length} 段`
        : `全天 ${segments.length} 段`;
    }
    const scheduleEntries = segments.slice(0, 24).map((segment, index) => ({
      kind: "schedule",
      sort: Number.isFinite(Number(segment.start)) ? Number(segment.start) : (timeMinutes(segment.window) ?? 2000 + index),
      segment,
    }));
    const changeEntries = [
      ...adjustments.map((item) => ({
        label: item.date || item.at || item.window || "变动",
        text: item.reaction || item.note || item.content || "生活节奏发生调整",
      })),
      ...storyEvents.map((item) => ({
        label: item.window || item.time || "事件",
        text: item.text || item.summary || item.activity || item.title || "生活事件",
      })),
    ].filter((item) => String(item.text || "").trim()).slice(-10).map((item, index) => ({
      kind: "change",
      sort: timeMinutes(item.label) ?? 3000 + index,
      item,
    }));
    const entries = [...scheduleEntries, ...changeEntries].sort((left, right) => left.sort - right.sort);
    timelineRoot.innerHTML = entries.length ? entries.map((entry) => {
      if (entry.kind === "change") {
        return `
          <li class="life-timeline-row is-change">
            <time class="life-timeline-time is-change-time"><strong>${escapeHtml(entry.item.label)}</strong></time>
            <div class="life-timeline-content">
              <b>${escapeHtml(entry.item.text)}</b>
              <span><em class="life-schedule-status is-change-status">生活变化</em></span>
            </div>
          </li>
        `;
      }
      const segment = entry.segment;
      const lifecycle = String(segment.lifecycle || "planned").toLowerCase();
      const isCurrent = segmentIsCurrent(segment);
      const summary = segment.summary || segment.activity || "这一段尚未细化";
      const windowText = String(segment.window || "未定");
      const windowMatch = windowText.match(/^(\d{1,2}:\d{2})\s*[-~至]\s*(\d{1,2}:\d{2})$/);
      const startText = windowMatch ? windowMatch[1] : windowText;
      const endText = windowMatch ? windowMatch[2] : "";
      return `
        <li class="life-timeline-row is-${escapeHtml(lifecycle)}${isCurrent ? " is-current" : ""}"${isCurrent ? ' aria-current="step"' : ""}>
          <time class="life-timeline-time">
            <strong>${escapeHtml(startText)}</strong>
            ${endText ? `<small>至 ${escapeHtml(endText)}</small>` : ""}
          </time>
          <div class="life-timeline-content">
            <b>${escapeHtml(summary)}</b>
            <span>${isCurrent
              ? '<em class="life-current-marker">当前日程</em>'
              : `<em class="life-schedule-status is-${escapeHtml(lifecycle)}">${escapeHtml(scheduleLifecycleLabel(lifecycle) || "计划中")}</em>`}</span>
          </div>
        </li>
      `;
    }).join("") : `<li class="life-desk-empty">暂无时间轴</li>`;
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        const active = timelineRoot.querySelector(".is-current");
        if (!active || timelineRoot.clientHeight <= 0) return;
        timelineRoot.scrollTop = Math.max(
          0,
          active.offsetTop - (timelineRoot.clientHeight - active.offsetHeight) / 2,
        );
      });
    }
  }

  const memoryRoot = $("#dashboardMemoryDrawer");
  if (memoryRoot) {
    const diaryCount = Array.isArray(life.diaries) ? life.diaries.length : 0;
    const fragmentCount = Array.isArray(life.dream_fragments) ? life.dream_fragments.length : 0;
    const memoryPlugin = livingmemory.selected_plugin_name
      || livingmemory.memory_companion_display_name
      || (livingmemory.compatible_available ? "长期记忆可用" : "未接入长期记忆");
    const rows = [
      ["worldbook", "关系", `${worldbook.enabled_member_count || 0}/${worldbook.member_count || 0} 个已启用`],
      ["worldbook", "待整理观察", `${worldbook.pending_observation_total || 0} 条`],
      ["memory", "生活记录", `${diaryCount} 篇日记 · ${fragmentCount} 个梦境片段`],
      ["memory", "长期记忆", memoryPlugin],
    ];
    memoryRoot.innerHTML = `
      <div class="life-memory-list">${rows.map(([tab, label, value]) => `
        <button type="button" data-jump-tab="${escapeHtml(tab)}"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></button>
      `).join("")}</div>
      ${livingmemory.conflict ? `<p class="life-memory-warning">${escapeHtml(livingmemory.conflict_warning || "检测到多个长期记忆来源")}</p>` : ""}
    `;
  }

  const capabilityRoot = $("#dashboardCapabilitySummary");
  if (capabilityRoot) {
    const privateInfo = overview.private || {};
    const groupInfo = overview.group || {};
    const intensity = overview.proactive_intensity || {};
    const providers = overview.providers || {};
    const proactiveLimit = intensity.effective?.max_daily_messages ?? privateInfo.max_daily_messages ?? 0;
    const fastProvider = String(providers.FAST_RESPONSE_PROVIDER_ID || "").trim();
    const complexProvider = String(providers.COMPLEX_REASONING_PROVIDER_ID || "").trim();
    const capabilities = [
      {
        tab: "private",
        label: "私聊陪伴",
        value: `${privateInfo.enabled_user_count || 0}/${privateInfo.user_count || 0} 个对象`,
        ready: Number(privateInfo.enabled_user_count || 0) > 0,
      },
      {
        tab: "group",
        label: "群聊观察",
        value: `${groupInfo.enabled_group_count || 0}/${groupInfo.group_count || 0} 个群`,
        ready: Boolean(groupInfo.enabled) && Number(groupInfo.enabled_group_count || 0) > 0,
      },
      {
        tab: "proactive",
        label: "主动消息",
        value: Number(proactiveLimit || 0) > 0 ? `每日上限 ${proactiveLimit}` : "当前未启用",
        ready: Number(proactiveLimit || 0) > 0,
      },
      {
        tab: "models",
        label: "模型分流",
        value: fastProvider && complexProvider ? "快速与复杂模型已配置" : "需要补充模型",
        ready: Boolean(fastProvider && complexProvider),
      },
    ];
    capabilityRoot.innerHTML = capabilities.map((item) => `
      <button type="button" class="${item.ready ? "is-ready" : "is-pending"}" data-jump-tab="${escapeHtml(item.tab)}">
        <i aria-hidden="true"></i>
        <span>${escapeHtml(item.label)}</span>
        <b>${escapeHtml(item.value)}</b>
      </button>
    `).join("");
  }
}

export function renderDashboardPulse() {
  const overview = state.overview || {};
  renderDashboardLifeDesk(overview);
  const proactive = overview.proactive_candidates || {};
  const proactiveCounts = proactive.counts || {};
  const creative = overview.creative || {};
  const news = overview.news || {};
  const exploration = overview.web_exploration || {};
  const nextUser = state.users
    .filter((item) => Number(item.next_proactive_ts || 0) > 0)
    .sort((a, b) => Number(a.next_proactive_ts || 0) - Number(b.next_proactive_ts || 0))[0];
  const creativeTitle = creative.latest_title || "";
  const newsTitle = news.last_digest?.headline || news.last_digest?.topic || "";
  const explorationTitle = exploration.last_digest?.topic || exploration.last_query?.query || "";
  const latestContent = creativeTitle
    || newsTitle
    || explorationTitle
    || "暂无新内容";
  const latestContentNote = creativeTitle
    ? `长线创作 · ${creative.active_projects || 0} 个项目进行中`
    : (newsTitle
      ? `新闻 · ${news.last_read_at || "未标记时间"}`
      : (explorationTitle
        ? `主动搜索 · ${exploration.last_explore_at || "未标记时间"}`
        : "新闻、搜索与创作暂无更新"));
  const cards = [
    {
      tone: "proactive",
      layout: "compact",
      label: "下一次主动",
      value: nextUser ? (nextUser.nickname || nextUser.user_id) : "暂无计划",
      note: nextUser ? `${nextUser.next_proactive} · ${proactiveActionLabel(nextUser.planned_action || "message")}` : `${proactiveCounts.accepted || 0} 个候选已进入计划`,
      jump: "proactive",
    },
    {
      tone: "news",
      layout: "compact",
      label: "最新内容",
      value: latestContent,
      note: latestContentNote,
      jump: creativeTitle ? "bookshelf" : "dashboard",
      scrollTarget: !creativeTitle && newsTitle
        ? "dashboardNewsCard"
        : (!creativeTitle && explorationTitle ? "dashboardWebExplorationCard" : ""),
    },
  ];
  const pulseRoot = $("#dashboardPulse");
  if (!pulseRoot) return;
  pulseRoot.innerHTML = cards.map((card) => `
    <button type="button" class="pulse-card ${escapeHtml(card.tone)} ${escapeHtml(card.layout || "")}" data-pulse-kind="${escapeHtml(card.tone)}" ${card.scrollTarget ? `data-scroll-target="${escapeHtml(card.scrollTarget)}"` : `data-jump-tab="${escapeHtml(card.jump || "dashboard")}"`}>
      <span><em class="pulse-card-label">${escapeHtml(card.label)}</em><em class="pulse-card-freshness">${escapeHtml(dashboardRefreshLabel())}</em></span>
      <b title="${escapeHtml(card.value)}">${escapeHtml(card.value)}</b>
      <small>${escapeHtml(card.note)}</small>
    </button>
  `).join("");

}

export function formatCompactNumber(value) {
  const number = Number(value || 0);
  if (number >= 1000000) return `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)}M`;
  if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}K`;
  return String(Math.round(number));
}

export function insightStatus(value) {
  const text = String(value || "").trim();
  const labels = {
    read: "已阅读",
    explored: "已搜索",
    no_items: "暂无候选",
    no_results: "无结果",
    search_failed: "搜索失败",
    digest_failed: "整理失败",
    web_search_disabled_or_unconfigured: "搜索未配置",
    waiting_schedule: "等待定时",
    all_sources_done: "今日来源已处理",
    waiting_window: "等待窗口",
    checking: "正在检查",
    waiting_today_video: "等待今日视频",
    today_video_without_text: "今日视频暂无文字版",
    already_read_today_video: "今日已读",
    missed_today_ai_daily: "今日窗口已过",
  };
  return labels[text] || text || "暂无";
}

export function browsingHistoryItemHtml(item, fallbackLabel) {
  const sourceLabel = item.source_label || fallbackLabel;
  const queryText = item.query ? `搜索：${item.query}` : "";
  const sourceText = item.source_title ? `来源：${item.source_title}` : "";
  return `
    <li class="browsing-history-item ${escapeHtml(item.source || "web_exploration")}">
      <div>
        <span class="history-badge">${escapeHtml(sourceLabel)}</span>
        <small>${escapeHtml(item.generated_at || item.date || "")}</small>
      </div>
      <b>${escapeHtml(item.title || item.query || "浏览记录")}</b>
      <p>${escapeHtml(item.intro || item.content || "这次没有留下详细记录。")}</p>
      ${queryText || sourceText ? `<footer>${escapeHtml([queryText, sourceText].filter(Boolean).join(" · "))}</footer>` : ""}
    </li>
  `;
}

export function historyWithoutLatest(items) {
  return items.length > 1 ? items.slice(0, -1).reverse() : [];
}

export function renderNewsInsightPanel() {
  const news = state.overview?.news || {};
  const digest = news.last_digest || {};
  const items = Array.isArray(news.latest_items) ? news.latest_items : [];
  const newsHistory = (Array.isArray(news.history) ? news.history : [])
    .filter((item) => item && item.source === "news");
  const earlierNewsHistory = historyWithoutLatest(newsHistory);
  const enabled = Boolean(news.enabled);
  const dailyHot = Boolean(news.daily_hot_enabled);
  const aiDaily = news.ai_daily || {};
  const aiDailyTextStatus = news.ai_daily_enabled
    ? (aiDaily.last_text_readable
      ? `文字版 ${formatCompactNumber(aiDaily.last_text_chars || 0)}字`
      : (aiDaily.last_video_subtitle_readable
        ? `字幕 ${formatCompactNumber(aiDaily.last_video_subtitle_chars || 0)}字`
        : (aiDaily.last_video_link
          ? (aiDaily.last_video_context_chars
            ? `视频信息 ${formatCompactNumber(aiDaily.last_video_context_chars || 0)}字`
            : (aiDaily.last_video_subtitle_status === "missing" ? "字幕暂无，按视频公开信息" : "视频正文暂无"))
          : (aiDaily.last_text_link ? "文字版未读到正文" : "文字版暂无"))))
    : "";
  const aiDailyBasisStatus = news.ai_daily_enabled && aiDaily.last_read_basis
    ? `依据：${aiDaily.last_read_basis}`
    : "";
  const headline = digest.headline || digest.topic || "暂无新闻见闻";
  const impression = digest.impression || (enabled ? "暂无整理结果。" : "新闻阅读未开启");
  const itemHtml = items.length
    ? items.slice(0, 6).map((item) => `
      <li>
        <span>${escapeHtml(item.source || "来源")}</span>
        <b>${escapeHtml(item.title || "未命名")}</b>
      </li>
    `).join("")
    : `<li class="empty-line">暂无候选记录</li>`;
  const historyHtml = earlierNewsHistory.length
    ? `
      <div class="insight-history-head">
        <b>更早见闻</b>
        <span>共 ${escapeHtml(news.history_count ?? newsHistory.length)} 条</span>
      </div>
      <ul class="browsing-history-list compact-history-list">
        ${earlierNewsHistory.map((item) => browsingHistoryItemHtml(item, "新闻阅读")).join("")}
      </ul>
    `
    : "";
  $("#newsInsightPanel").innerHTML = `
    <div class="insight-head">
      <div>
        <span class="eyebrow">${enabled ? "新闻阅读" : "未开启"}</span>
        <b>${escapeHtml(headline)}</b>
      </div>
      <small>${escapeHtml(news.last_read_at || "未阅读")}</small>
    </div>
    <p>${escapeHtml(impression)}</p>
    <div class="insight-meta">
      <span>${escapeHtml(insightStatus(news.last_status))}</span>
      <span>${dailyHot ? "每日热点开启" : "每日热点关闭"}</span>
      <span>${news.ai_daily_enabled ? `AI日报/早报：${escapeHtml(insightStatus(aiDaily.status))}` : "AI日报/早报关闭"}</span>
      ${aiDailyTextStatus ? `<span>${escapeHtml(aiDailyTextStatus)}</span>` : ""}
      ${aiDailyBasisStatus ? `<span>${escapeHtml(aiDailyBasisStatus)}</span>` : ""}
      <span>${news.boredom_read_enabled ? "空档阅读开启" : "空档阅读关闭"}</span>
    </div>
    <ul class="insight-list">${itemHtml}</ul>
    ${historyHtml}
  `;
}
