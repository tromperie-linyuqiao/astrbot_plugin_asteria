/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {renderProviderSaveNotice} from './navigation.js';
import {featureDescription,featureLabel,featurePublicKey} from './persona.js';
import {configLabel,renderProviders} from './providers.js';
import {PHOTO_API_PLATFORM_OPTIONS,PROACTIVE_UNLIMITED_LIMIT,configDescriptions,embeddedFeatureKeys,embeddedFeatureParentByKey,featureGroups,featureSettingGroups,featureSwitchExcludedKeys,hiddenCompatibilityConfigKeys,percentSettingKeys,pluginIntegrationAvailabilityRules,privateReadingConfigKeys,proactiveOnlyLockedFeatureKeys,probabilitySettingKeys,providerGuides,providerLabels,quickProviderKeys,state} from './state.js';
import {escapeHtml} from './workspace.js';

export function isProviderConfigKey(key) {
  return Object.prototype.hasOwnProperty.call(providerLabels, key);
}

export function normalizeModelTimeoutOverrides(raw) {
  let source = raw;
  if (typeof source === "string") {
    try { source = JSON.parse(source || "{}"); } catch (_error) { source = {}; }
  }
  if (!source || typeof source !== "object" || Array.isArray(source)) return {};
  const result = {};
  Object.entries(source).forEach(([key, value]) => {
    if (!isProviderConfigKey(key)) return;
    const timeout = Math.round(Number(value));
    if (Number.isFinite(timeout) && timeout >= 5 && timeout <= 600) result[key] = timeout;
  });
  return result;
}

export function normalizeModelFallbackOverrides(raw) {
  let source = raw;
  if (typeof source === "string") {
    try { source = JSON.parse(source || "{}"); } catch (_error) { source = {}; }
  }
  if (!source || typeof source !== "object" || Array.isArray(source)) return {};
  const result = {};
  Object.entries(source).forEach(([key, value]) => {
    const providerId = String(value || "").trim();
    if (isProviderConfigKey(key) && providerId) result[key] = providerId;
  });
  return result;
}

export function providerNeedsLowLatency(key) {
  const guide = providerGuides[key] || {};
  return guide.preference === "speed" || ["direct", "conditional"].includes(guide.passiveImpact || "");
}

export function normalizeProviderConfigMode(value) {
  const text = String(value || "").trim().toLowerCase();
  const aliases = {
    fast: "quick",
    simple: "quick",
    "快速": "quick",
    "快速配置": "quick",
    precise: "precision",
    advanced: "precision",
    "精准": "precision",
    "精准配置": "precision",
    "分流": "precision",
  };
  const normalized = aliases[text] || text;
  return normalized === "precision" ? "precision" : "quick";
}

export function inferProviderConfigMode(overview = state.overview || {}) {
  const settings = overview.settings || {};
  const explicit = String(settings.provider_config_mode || "").trim();
  if (explicit) return normalizeProviderConfigMode(explicit);
  const providers = {
    ...(overview.providers || {}),
    ...(state.providerDraft || {}),
  };
  const hasPrecisionProvider = Object.keys(providerLabels)
    .some((key) => !quickProviderKeys.has(key) && visibleConfigKey(key) && Boolean(providers[key]));
  return hasPrecisionProvider ? "precision" : "quick";
}

export function currentProviderConfigMode() {
  return normalizeProviderConfigMode(state.providerConfigMode || inferProviderConfigMode());
}

export function providerAllowedInCurrentMode(key) {
  const mode = currentProviderConfigMode();
  return mode === "quick" ? quickProviderKeys.has(key) : !quickProviderKeys.has(key);
}

export function syncProviderConfigModeControls() {
  const mode = currentProviderConfigMode();
  const quick = mode === "quick";
  document.querySelectorAll("[data-provider-config-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.providerConfigMode === mode);
  });
  const toolbar = document.querySelector(".provider-toolbar");
  toolbar?.classList.toggle("is-quick-mode", quick);
  const filter = document.getElementById("providerFilter");
  if (filter && quick) filter.value = "";
  document.querySelectorAll("[data-provider-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.providerMode === (state.providerMode || "all"));
  });
  const hint = document.getElementById("providerConfigModeHint");
  if (hint) {
    hint.textContent = quick
      ? "快速配置编辑 4 个场景入口；保存时会按原规则覆盖相应细分任务，两套配置一起更新。"
      : "精准配置编辑各任务的分配；保存沿原规则同步快速入口，不受搜索筛选限制。";
  }
  renderProviderSaveNotice();
}

export function setProviderConfigMode(mode, { render = true } = {}) {
  state.providerConfigMode = normalizeProviderConfigMode(mode);
  if (state.providerConfigMode === "quick") {
    state.providerMode = "all";
    state.providerFilter = "";
    const filter = document.getElementById("providerFilter");
    if (filter) filter.value = "";
  }
  syncProviderConfigModeControls();
  if (render) renderProviders();
}

export function isPrivateReadingAvailable() {
  return Boolean(state.overview?.private_reading?.available);
}

export function toBool(value) {
  if (typeof value === "string") {
    const text = value.trim().toLowerCase();
    if (["true", "1", "yes", "y", "on", "enable", "enabled", "启用", "开启", "开", "是"].includes(text)) return true;
    if (["false", "0", "no", "n", "off", "disable", "disabled", "停用", "关闭", "关", "否", ""].includes(text)) return false;
  }
  return Boolean(value);
}

export function normalizeFeatureDraft(features = {}) {
  return Object.fromEntries(Object.entries(features || {}).map(([key, value]) => [key, toBool(value)]));
}

export function featureDraftFromOverview(overview = {}) {
  const draft = normalizeFeatureDraft(overview.features || {});
  hiddenCompatibilityConfigKeys.forEach((key) => {
    delete draft[key];
  });
  const settings = overview.settings || {};
  const settingBackedFeatureKeys = [
    "enable_rest_reply_simulation",
    "enable_worldview_perception",
    "enable_group_injection_guard",
    "enable_group_persona_denoise",
    "auto_voice_enabled",
    "enable_tts_local_playback",
    "enable_tts_local_playback_live_only",
    "enable_tts_live_subtitle_sync",
    "group_repeat_count_distinct_users_only",
  ];
  settingBackedFeatureKeys.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(settings, key)) {
      draft[key] = toBool(settings[key]);
    }
  });
  return draft;
}

export function unavailablePluginIntegrationOwner(key) {
  if (pluginIntegrationAvailabilityRules[key]) {
    return pluginIntegrationAvailabilityRules[key]() ? "" : key;
  }
  for (const [featureKey, settingKeys] of Object.entries(featureSettingGroups || {})) {
    if (!pluginIntegrationAvailabilityRules[featureKey]) continue;
    if ((settingKeys || []).includes(key) && !pluginIntegrationAvailabilityRules[featureKey]()) {
      return featureKey;
    }
  }
  return "";
}

export function visibleConfigKey(key) {
  if (hiddenCompatibilityConfigKeys.has(key)) return false;
  if (unavailablePluginIntegrationOwner(key)) return false;
  return isPrivateReadingAvailable() || !privateReadingConfigKeys.has(key);
}

export function proactiveOnlyModeEnabled() {
  return toBool(state.featureDraft?.enable_proactive_only_mode);
}

export function featureLockedByProactiveOnlyMode(key) {
  if (key === "enable_proactive_only_mode") return false;
  return proactiveOnlyModeEnabled() && (
    proactiveOnlyLockedFeatureKeys.has(key)
    || proactiveOnlyLockedFeatureKeys.has(topLevelFeatureKey(key))
  );
}

export function proactiveOnlyUnlockedKeys() {
  const items = state.overview?.proactive_only?.unlocked || [];
  return new Set((Array.isArray(items) ? items : []).map((item) => String(item.key || item || "").trim()).filter(Boolean));
}

export function featureTemporarilyUnlockedByProactiveOnly(key) {
  if (!proactiveOnlyModeEnabled()) return false;
  const unlocks = proactiveOnlyUnlockedKeys();
  return unlocks.has("all") || unlocks.has(key) || unlocks.has(topLevelFeatureKey(key));
}

export function proactiveOnlyRelatedUnlocks(key) {
  const related = state.overview?.proactive_only?.related || {};
  return Array.isArray(related[key]) ? related[key] : [];
}

export function visibleFeatureSwitchKey(key) {
  if (key === "enable_proactive_only_mode") return false;
  if (hiddenCompatibilityConfigKeys.has(key)) return false;
  if (featureSwitchExcludedKeys.has(key)) return false;
  const detailSettingKeys = new Set(Object.values(featureSettingGroups || {}).flat());
  const groupedFeatureKeys = new Set(featureGroups.flatMap((group) => group.keys));
  if (detailSettingKeys.has(key) && !groupedFeatureKeys.has(key)) return false;
  const looksLikeFeatureToggle = key.startsWith("enable_") || key === "creative_hidden_mode" || key === "group_repeat_count_distinct_users_only";
  return visibleConfigKey(key) && !embeddedFeatureKeys.has(key) && (looksLikeFeatureToggle || !detailSettingKeys.has(key));
}

export function topLevelFeatureKey(key) {
  let current = key;
  const seen = new Set();
  while (embeddedFeatureParentByKey[current] && !seen.has(current)) {
    seen.add(current);
    current = embeddedFeatureParentByKey[current];
  }
  return current;
}

export function visibleTopLevelFeatureKeys(source = state.featureDraft || {}) {
  return Object.keys(source || {}).filter(visibleFeatureSwitchKey);
}

export function featureSearchText(key) {
  const childText = Object.entries(embeddedFeatureParentByKey)
    .filter(([childKey]) => topLevelFeatureKey(childKey) === key)
    .map(([childKey]) => `${childKey} ${featureLabel(childKey)} ${featureDescription(childKey)}`)
    .join(" ");
  const settingText = (featureSettingGroups[key] || [])
    .map((settingKey) => `${settingKey} ${configLabel(settingKey)} ${configDescriptions[settingKey] || ""}`)
    .join(" ");
  return `${key} ${featurePublicKey(key)} ${featureLabel(key)} ${featureDescription(key)} ${childText} ${settingText}`.toLowerCase();
}

export function isFractionalPercentSetting(key) {
  return probabilitySettingKeys.has(key);
}

export function isPercentInputSetting(key) {
  return isFractionalPercentSetting(key) || percentSettingKeys.has(key);
}

export function displaySettingValue(key, value) {
  if (isPercentInputSetting(key)) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return value ?? "";
    if (numeric < 0) return String(numeric);
    const percent = numeric <= 1 ? numeric * 100 : numeric;
    return Number.isInteger(percent) ? String(percent) : String(Number(percent.toFixed(2)));
  }
  if (["private_user_aliases", "private_user_delivery_aliases"].includes(key) && value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value)
      .map(([alias, target]) => `${String(alias || "").trim()}=${String(target || "").trim()}`)
      .filter((line) => line !== "=")
      .join("\n");
  }
  return value ?? "";
}

export function proactiveLimitUnlimited(value, explicit = false) {
  return Boolean(explicit) || Number(value || 0) >= PROACTIVE_UNLIMITED_LIMIT;
}

export function formatProactiveLimit(value, explicit = false) {
  if (proactiveLimitUnlimited(value, explicit)) return "不限";
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? String(numeric) : "-";
}

export function formatProactiveDailyQuota(value, explicit = false, presetText = "") {
  const text = presetText || formatProactiveLimit(value, explicit);
  return text === "不限" ? "不限" : `${text} 条/天`;
}

export function formatProactiveDailyLabel(value, explicit = false, presetText = "") {
  const text = presetText || formatProactiveLimit(value, explicit);
  return text === "不限" ? "每日不限" : `每日 ${text} 条`;
}

export function proactiveGaugeMax(used, limit, explicit = false, fallback = 8) {
  const usedCount = Number(used || 0);
  if (proactiveLimitUnlimited(limit, explicit)) return Math.max(8, usedCount + 1);
  return Math.max(1, Number(limit || fallback || 8));
}

export function collectSettingValue(key, input) {
  if (!input) return "";
  if (input.type === "checkbox") return input.checked;
  if (input.type === "number") {
    const raw = input.value === "" ? 0 : Number(input.value);
    if (isFractionalPercentSetting(key)) {
      return Math.max(0, Math.min(1, raw / 100));
    }
    return raw;
  }
  return input.value;
}

export function normalizePhotoApiPlatform(value) {
  const text = String(value || "auto").trim().toLowerCase();
  const aliases = {
    "openai-compatible": "openai",
    "openai_compatible": "openai",
    "openai兼容": "openai",
    "sensenova": "sensenova",
    "sense-nova": "sensenova",
    "日日新": "sensenova",
    "百炼": "bailian",
    "阿里云百炼": "bailian",
    "dashscope": "bailian",
    "modelscope": "modelscope",
    "model_scope": "modelscope",
    "魔搭": "modelscope",
    "魔搭社区": "modelscope",
    "豆包": "doubao",
    "火山": "doubao",
    "火山引擎": "doubao",
    "seedream": "doubao",
    "google": "gemini",
    "谷歌": "gemini",
  };
  const normalized = aliases[text] || text;
  return PHOTO_API_PLATFORM_OPTIONS.some(([option]) => option === normalized) ? normalized : "auto";
}

export function normalizePhotoApiEndpoint(item = {}, index = 0) {
  const endpoint = item && typeof item === "object" ? item : {};
  const timeout = Number(endpoint.timeout_seconds ?? endpoint.timeout ?? 180);
  return {
    name: String(endpoint.name || endpoint.label || `在线 API ${index + 1}`).trim().slice(0, 80) || `在线 API ${index + 1}`,
    enabled: endpoint.enabled === undefined ? true : toBool(endpoint.enabled),
    platform: normalizePhotoApiPlatform(endpoint.platform || endpoint.external_image_api_platform || "auto"),
    base_url: String(endpoint.base_url || endpoint.api_base || endpoint.endpoint || endpoint.EXTERNAL_IMAGE_API_BASE_URL || "").trim(),
    api_key: String(endpoint.api_key || endpoint.key || endpoint.EXTERNAL_IMAGE_API_KEY || "").trim(),
    model: String(endpoint.model || endpoint.model_name || endpoint.EXTERNAL_IMAGE_API_MODEL || "").trim(),
    size: String(endpoint.size || endpoint.external_image_api_size || "1024x1024").trim() || "1024x1024",
    timeout_seconds: Math.max(20, Math.min(600, Number.isFinite(timeout) ? Math.round(timeout) : 180)),
    custom_headers: String(endpoint.custom_headers || endpoint.headers || endpoint.external_image_api_custom_headers || "").trim(),
  };
}

export function parsePhotoApiEndpoints(raw) {
  if (Array.isArray(raw)) return raw.map(normalizePhotoApiEndpoint).filter(Boolean);
  if (raw && typeof raw === "object") {
    const items = raw.items || raw.endpoints || raw.apis || [];
    return Array.isArray(items) ? items.map(normalizePhotoApiEndpoint).filter(Boolean) : [];
  }
  const text = String(raw || "").trim();
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    return parsePhotoApiEndpoints(parsed);
  } catch {
    return [];
  }
}

export function legacyPhotoApiEndpointFromSettings(settings = {}, backup = false) {
  const prefix = backup ? "backup_" : "";
  return normalizePhotoApiEndpoint({
    name: backup ? "备选在线 API" : "主在线 API",
    enabled: backup ? toBool(settings.enable_backup_external_image_api) : true,
    platform: settings[`${prefix}external_image_api_platform`] || "auto",
    base_url: backup ? settings.BACKUP_EXTERNAL_IMAGE_API_BASE_URL : settings.EXTERNAL_IMAGE_API_BASE_URL,
    api_key: backup ? settings.BACKUP_EXTERNAL_IMAGE_API_KEY : settings.EXTERNAL_IMAGE_API_KEY,
    model: backup ? settings.BACKUP_EXTERNAL_IMAGE_API_MODEL : settings.EXTERNAL_IMAGE_API_MODEL,
    size: settings[`${prefix}external_image_api_size`] || "1024x1024",
    timeout_seconds: settings[`${prefix}external_image_api_timeout_seconds`] || 180,
    custom_headers: settings[`${prefix}external_image_api_custom_headers`] || "",
  }, backup ? 1 : 0);
}

export function photoApiEndpointInitialList(settings = state.overview?.settings || {}) {
  const configured = parsePhotoApiEndpoints(settings.external_image_api_endpoints);
  if (configured.length) return configured;
  const primary = legacyPhotoApiEndpointFromSettings(settings, false);
  const backup = legacyPhotoApiEndpointFromSettings(settings, true);
  const list = [];
  if (primary.base_url || primary.api_key || primary.model) list.push(primary);
  if (backup.base_url || backup.api_key || backup.model) list.push(backup);
  return list.length ? list : [primary];
}

export function photoApiEndpointDraft() {
  if (!Array.isArray(state.imageApiEndpointDraft)) {
    state.imageApiEndpointDraft = photoApiEndpointInitialList();
  }
  return state.imageApiEndpointDraft;
}

export function photoApiEndpointComplete(endpoint = {}) {
  return Boolean(endpoint.enabled && endpoint.base_url && endpoint.api_key && endpoint.model);
}

export function photoApiEndpointEditorHiddenValue(endpoints) {
  return JSON.stringify((endpoints || []).map((item, index) => normalizePhotoApiEndpoint(item, index)));
}

export function photoApiEndpointEditorHtml() {
  const endpoints = photoApiEndpointDraft();
  const hidden = escapeHtml(photoApiEndpointEditorHiddenValue(endpoints));
  return `
    <section class="feature-param-section image-api-endpoint-panel" data-image-api-editor>
      <header>
        <b>在线 API 优先级队列</b>
        <span>从上到下依次尝试；上一条失败或超时后自动换下一条。保存后第一条会同步为旧“主用”，第二条同步为旧“备选”。</span>
      </header>
      <input type="hidden" data-feature-param="external_image_api_endpoints" value="${hidden}">
      <div class="image-api-endpoint-list">
        ${endpoints.map((endpoint, index) => photoApiEndpointCardHtml(endpoint, index, endpoints.length)).join("")}
      </div>
      <div class="image-api-endpoint-actions">
        <button type="button" class="soft" data-image-api-action="add">新增备用 API</button>
        <small>建议每条单独设置超时；队列过长时，完整失败链路会相应变慢。</small>
      </div>
    </section>
  `;
}

export function photoApiEndpointCardHtml(endpoint, index, total) {
  const item = normalizePhotoApiEndpoint(endpoint, index);
  const ready = photoApiEndpointComplete(item);
  return `
    <article class="image-api-endpoint-card ${ready ? "ready" : "incomplete"}" data-image-api-index="${index}">
      <header>
        <div>
          <span class="image-api-endpoint-rank">#${index + 1}</span>
          <b>${escapeHtml(item.name || `在线 API ${index + 1}`)}</b>
          <small>${escapeHtml(ready ? "配置完整" : "需要地址、Key 和图片模型")}</small>
        </div>
        <div class="image-api-endpoint-buttons">
          <button type="button" title="上移" data-image-api-action="up" data-index="${index}" ${index <= 0 ? "disabled" : ""}>↑</button>
          <button type="button" title="下移" data-image-api-action="down" data-index="${index}" ${index >= total - 1 ? "disabled" : ""}>↓</button>
          <button type="button" title="删除" data-image-api-action="delete" data-index="${index}" ${total <= 1 ? "disabled" : ""}>删除</button>
        </div>
      </header>
      <div class="image-api-endpoint-grid">
        <label>
          <span>启用</span>
          <input type="checkbox" data-image-api-field="enabled" data-index="${index}" ${item.enabled ? "checked" : ""}>
        </label>
        <label>
          <span>名称</span>
          <input type="text" data-image-api-field="name" data-index="${index}" value="${escapeHtml(item.name)}" placeholder="例如 主用 / 备用1">
        </label>
        <label>
          <span>平台</span>
          <select data-image-api-field="platform" data-index="${index}">
            ${PHOTO_API_PLATFORM_OPTIONS.map(([value, label]) => `<option value="${escapeHtml(value)}"${item.platform === value ? " selected" : ""}>${escapeHtml(label)}</option>`).join("")}
          </select>
        </label>
        <label>
          <span>尺寸</span>
          <input type="text" data-image-api-field="size" data-index="${index}" value="${escapeHtml(item.size)}" placeholder="1024x1024">
        </label>
        <label class="wide">
          <span>API 地址</span>
          <input type="text" data-image-api-field="base_url" data-index="${index}" value="${escapeHtml(item.base_url)}" placeholder="https://.../v1/images/generations">
        </label>
        <label>
          <span>API Key</span>
          <input type="password" data-image-api-field="api_key" data-index="${index}" value="${escapeHtml(item.api_key)}" placeholder="sk-...">
        </label>
        <label>
          <span>图片模型</span>
          <input type="text" data-image-api-field="model" data-index="${index}" value="${escapeHtml(item.model)}" placeholder="gpt-image-1 / qwen-image / seedream / imagen">
        </label>
        <label>
          <span>超时秒数</span>
          <input type="number" min="20" max="600" step="10" data-image-api-field="timeout_seconds" data-index="${index}" value="${escapeHtml(item.timeout_seconds)}">
        </label>
        <label class="wide">
          <span>自定义请求头</span>
          <textarea rows="2" data-image-api-field="custom_headers" data-index="${index}" placeholder="X-Custom-Header: value">${escapeHtml(item.custom_headers)}</textarea>
        </label>
      </div>
    </article>
  `;
}

export function collectPhotoApiEndpointEditor(root = document) {
  const editor = root.querySelector?.("[data-image-api-editor]");
  if (!editor) return null;
  const cards = Array.from(editor.querySelectorAll("[data-image-api-index]"));
  const endpoints = cards.map((card, cardIndex) => {
    const endpoint = {};
    card.querySelectorAll("[data-image-api-field]").forEach((input) => {
      const field = input.dataset.imageApiField;
      if (!field) return;
      if (input.type === "checkbox") endpoint[field] = input.checked;
      else if (field === "timeout_seconds") endpoint[field] = Number(input.value || 180);
      else endpoint[field] = input.value;
    });
    return normalizePhotoApiEndpoint(endpoint, cardIndex);
  });
  state.imageApiEndpointDraft = endpoints;
  const hidden = editor.querySelector('[data-feature-param="external_image_api_endpoints"]');
  if (hidden) hidden.value = photoApiEndpointEditorHiddenValue(endpoints);
  return endpoints;
}
