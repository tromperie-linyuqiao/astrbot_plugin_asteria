/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {moveSecondaryNavToStandard,renderBuckets,resetRailCoverflow,selectSecondaryNav} from './overview.js';
import {$,$$,CONFIG_ADVANCED_FALLBACKS,DEFAULT_THEME,SECONDARY_NAV,THEME_ALIASES,THEME_OPTIONS,TRANSITION_FACES,UI_CONTRACT_VERSION,UI_DYNAMIC_ENDPOINTS,VIEWS,state} from './state.js';
import {loadAclTopology} from './topology.js';

export function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
}

export function waitForMotion(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, prefersReducedMotion() ? 0 : ms));
}

export function refreshTransitionFace() {
  const face = $("#transitionFace");
  if (!face) return;
  face.textContent = TRANSITION_FACES[Math.floor(Math.random() * TRANSITION_FACES.length)];
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function compact(value, fallback = "-") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

export function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function number(value) {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? Math.max(0, parsed).toLocaleString("zh-CN") : "0";
}

export function percentLabel(value) {
  return `${Math.round(Math.max(0, Math.min(1, finiteNumber(value))) * 100)}%`;
}

export function mentionPolicyLabel(policy) {
  if (policy === "direct") return "可直接提及";
  if (policy === "soft_echo") return "轻触回声";
  if (policy === "tone_only") return "只作语气";
  if (policy === "avoid_unless_asked") return "被问再说";
  return policy ? String(policy) : "未评估";
}

export function mentionPolicyTone(policy) {
  if (policy === "direct") return "teal";
  if (policy === "soft_echo") return "blue";
  if (policy === "tone_only") return "gold";
  if (policy === "avoid_unless_asked") return "red";
  return "violet";
}

export function dimensionLabel(name) {
  const labels = {
    persona_importance: "拟人权重",
    relationship: "关系",
    relationship_weight: "关系",
    emotional: "情绪",
    emotional_weight: "情绪",
    promise: "承诺",
    promise_weight: "承诺",
    open_loop: "未完成",
    open_loop_weight: "未完成",
    creative: "创作",
    creative_weight: "创作",
    preference: "偏好",
    preference_weight: "偏好",
    self_continuity: "自我连续",
    self_continuity_weight: "自我连续",
    freshness_weight: "新鲜感",
    scar_weight: "伤痕感",
    emotional_debt_weight: "情感债务",
    intimacy: "亲密信任",
    intimacy_weight: "亲密信任",
    vulnerability: "脆弱时刻",
    vulnerability_weight: "脆弱时刻",
  };
  return labels[name] || name;
}

export function decayModeLabel(mode) {
  const labels = {
    normal: "普通衰减",
    slow_decay: "慢衰减",
    no_decay: "不衰减",
    scar_slow_decay: "伤痕慢衰减",
    creative_milestone: "创作节点",
    ephemeral: "短期淡化",
  };
  return labels[mode] || mode;
}

export function reactionLabel(reaction) {
  const labels = {
    accepted: "接受",
    comforted: "被安慰到",
    touched: "感动",
    nostalgic: "怀念",
    awkward: "尴尬",
    denied: "否认",
    corrected: "纠正",
  };
  return labels[reaction] || reaction;
}

export function personaWeights(memory) {
  const source = memory.persona_weights || memory.metadata || {};
  const keys = [
    "persona_importance",
    "relationship_weight",
    "emotional_weight",
    "promise_weight",
    "open_loop_weight",
    "creative_weight",
    "preference_weight",
    "self_continuity_weight",
    "freshness_weight",
    "scar_weight",
    "emotional_debt_weight",
    "intimacy_weight",
    "vulnerability_weight",
  ];
  return keys
    .map((key) => ({ key, value: finiteNumber(source[key], NaN) }))
    .filter((item) => Number.isFinite(item.value) && item.value > 0.01);
}

export function memorySignalBadges(memory, max = 4) {
  const metadata = memory.metadata || {};
  const policy = memory.mention_policy || metadata.mention_policy || "";
  const mentionability = memory.mentionability_score ?? metadata.mentionability_score;
  const weights = personaWeights(memory)
    .filter((item) => item.key !== "persona_importance" && item.value >= 0.35)
    .sort((a, b) => b.value - a.value)
    .slice(0, Math.max(0, max - (policy ? 1 : 0)));
  const badges = [];
  if (policy) {
    const score = mentionability !== undefined && mentionability !== null ? ` ${percentLabel(mentionability)}` : "";
    badges.push(`<span class="badge ${escapeHtml(mentionPolicyTone(policy))}">${escapeHtml(mentionPolicyLabel(policy) + score)}</span>`);
  }
  weights.forEach((item) => {
    badges.push(`<span class="badge violet">${escapeHtml(`${dimensionLabel(item.key)} ${percentLabel(item.value)}`)}</span>`);
  });
  return badges.join("");
}

export function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortId(value) {
  const text = compact(value, "");
  if (!text) return "-";
  if (text.length <= 14) return text;
  return `${text.slice(0, 8)}...${text.slice(-4)}`;
}

export function isNumericOnlyContent(value) {
  return /^[0-9]+$/.test(String(value ?? "").trim());
}

export function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function setMessage(text) {
  $("#subtitle").textContent = text;
}

export function setBusy(active, text = "正在处理...") {
  const app = $("#app");
  const layer = $("#busyLayer");
  if (!app || !layer) return;
  app.classList.toggle("is-busy", active);
  layer.setAttribute("aria-hidden", active ? "false" : "true");
  $("#busyText").textContent = text;
}

export function normalizeTheme(theme) {
  const value = String(theme || "").trim();
  return THEME_OPTIONS.includes(value) ? value : (THEME_ALIASES[value] || DEFAULT_THEME);
}

export function applyTheme(theme, { explicit = false } = {}) {
  const next = normalizeTheme(theme);
  document.documentElement.dataset.theme = next;
  $("#app")?.setAttribute("data-theme", next);
  if (explicit) {
    const url = new URL(location.href);
    url.searchParams.delete("theme");
    history.replaceState(history.state, "", url);
  }
  if (!new URLSearchParams(location.search).has("theme")) document.documentElement.dataset.adminTheme = "custom";
}

export async function loadConfiguredTheme() {
  applyTheme(DEFAULT_THEME);
  try {
    const data = await apiGet("/context/config");
    applyTheme(data.appearance?.theme_key || data.appearance?.theme);
    state.scopeControl = {
      ...state.scopeControl,
      ...(data.scope_control || {}),
    };
    renderScopeControls();
    void loadScopeFeatureOverrides();
  } catch (error) {
    applyTheme(DEFAULT_THEME);
    renderScopeControls();
  }
}

export function scopeControlTarget(key) {
  const bucket = activeBucket();
  const scope = key.startsWith("group_") ? "group" : key.startsWith("private_") ? "private" : "";
  return scope && isWindowBucket(bucket) && bucket.scope === scope ? bucket : null;
}

export function scopeControlFeature(key) {
  return key.includes("capture") ? "capture" : key.includes("recall") ? "recall" : "";
}

export function scopeControlValue(key) {
  const target = scopeControlTarget(key);
  const feature = scopeControlFeature(key);
  const policy = target ? state.windowScopePolicies[`${target.scope}:${target.target_id}`] : null;
  const override = policy && feature ? policy[`${feature}_enabled`] : null;
  return override === null || override === undefined ? Boolean(state.scopeControl[key]) : Boolean(override);
}

export function scopeControlStatus(key) {
  const target = scopeControlTarget(key);
  const feature = scopeControlFeature(key);
  const policy = target ? state.windowScopePolicies[`${target.scope}:${target.target_id}`] : null;
  const override = policy && feature ? policy[`${feature}_enabled`] : null;
  return target && override !== null && override !== undefined
    ? (override ? "本窗口已启用" : "本窗口已停用")
    : (scopeControlValue(key) ? "已启用" : "已停用");
}

export async function loadScopeFeatureOverrides() {
  try {
    const data = await apiGet("/acl/matrix");
    state.windowScopePolicies = {};
    for (const policy of data.policies || []) {
      const scope = String(policy.window_scope || "").trim();
      const id = String(policy.window_id || "").trim();
      if (scope && id) state.windowScopePolicies[`${scope}:${id}`] = policy;
    }
    renderScopeControls();
  } catch (_) {
    // Global controls remain usable if per-window policy loading is unavailable.
  }
}

export function renderScopeControlHost(host, keys, options = {}) {
  if (!host) return;
  const title = String(options.title || "").trim();
  const hint = String(options.hint || "").trim();
  host.innerHTML = `
    <div class="scope-control-shell">
      ${title ? `<div class="scope-control-copy"><b>${escapeHtml(title)}</b>${hint ? `<small>${escapeHtml(hint)}</small>` : ""}</div>` : ""}
      <div class="scope-control-grid">
      ${keys.map((item) => `
        <label class="scope-control-item">
          <span>${escapeHtml(item.label)}<small data-scope-status="${escapeHtml(item.key)}">${scopeControlStatus(item.key)}</small></span>
          <input type="checkbox" data-scope-control="${escapeHtml(item.key)}"${scopeControlValue(item.key) ? " checked" : ""} />
        </label>
      `).join("")}
      </div>
    </div>
  `;
  host.querySelectorAll("input[data-scope-control]").forEach((input) => {
    input.addEventListener("change", () => updateScopeControl(input));
  });
}

export function renderScopeControls() {
  const groupTarget = scopeControlTarget("group_capture_enabled");
  const privateTarget = scopeControlTarget("private_capture_enabled");
  const groupLabel = groupTarget ? "本窗口记录" : "全局记录";
  const groupRecallLabel = groupTarget ? "本窗口召回" : "全局召回";
  const privateLabel = privateTarget ? "本窗口记录" : "全局记录";
  const privateRecallLabel = privateTarget ? "本窗口召回" : "全局召回";
  renderScopeControlHost($("#groupScopeControl"), [
    { key: "group_capture_enabled", label: groupLabel },
    { key: "group_recall_enabled", label: groupRecallLabel },
  ], { title: groupTarget ? `当前窗口：${bucketLabel(groupTarget)}` : "群聊范围开关", hint: groupTarget ? "只控制当前选中的群聊" : "所有未单独覆盖的群聊窗口" });
  renderScopeControlHost($("#privateScopeControl"), [
    { key: "private_capture_enabled", label: privateLabel },
    { key: "private_recall_enabled", label: privateRecallLabel },
  ], { title: privateTarget ? `当前窗口：${bucketLabel(privateTarget)}` : "私聊范围开关", hint: privateTarget ? "只控制当前选中的私聊窗口" : "所有未单独覆盖的私聊窗口" });
  renderScopeControlHost($("#privateLegacyScopeControl"), [
    { key: "private_capture_enabled", label: privateLabel },
    { key: "private_recall_enabled", label: privateRecallLabel },
  ], { title: privateTarget ? `当前窗口：${bucketLabel(privateTarget)}` : "私聊范围开关", hint: privateTarget ? "只控制当前选中的私聊窗口" : "所有未单独覆盖的私聊窗口" });
  renderScopeControlHost($("#topologyScopeControl"), [
    { key: "group_topology_enabled", label: "群聊参与" },
    { key: "private_topology_enabled", label: "私聊参与" },
  ], { title: "拓扑参与范围", hint: "关闭后该范围不参与跨窗口权限" });
}

export async function updateScopeControl(input) {
  const key = input?.dataset?.scopeControl || "";
  if (!key || !(key in state.scopeControl) || input.disabled) return;
  const previous = scopeControlValue(key);
  const next = Boolean(input.checked);
  const target = scopeControlTarget(key);
  const feature = scopeControlFeature(key);
  input.disabled = true;
  try {
    if (target && feature) {
      await apiPost("/acl/policy", {
        scope: target.scope,
        id: target.target_id,
        [`${feature}_enabled`]: next,
      });
      const policyKey = `${target.scope}:${target.target_id}`;
      state.windowScopePolicies[policyKey] = {
        ...(state.windowScopePolicies[policyKey] || { window_scope: target.scope, window_id: target.target_id }),
        [`${feature}_enabled`]: next,
      };
    } else {
      await apiPost("/config/module/update", { module: "scope_control", values: { [key]: next } });
      state.scopeControl[key] = next;
    }
    renderScopeControls();
    if (key.endsWith("_topology_enabled")) {
      await loadAclTopology();
    }
    showToast(`${target ? "已单独" : ""}${next ? "启用" : "停用"} ${target ? bucketLabel(target) : (key.startsWith("group_") ? "群聊" : "私聊")}${feature === "capture" ? "记录" : feature === "recall" ? "召回" : "拓扑参与"}`);
  } catch (error) {
    input.checked = previous;
    showToast(error?.message || "开关保存失败", "error");
  } finally {
    input.disabled = false;
  }
}

export function showToast(text, tone = "info") {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = text;
  toast.dataset.tone = tone;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.classList.remove("is-visible");
  }, tone === "error" ? 4200 : 2400);
}

export function renderUiCompatibilityBanner(message = "") {
  const banner = $("#uiCompatibilityBanner");
  if (!banner) return;
  state.uiContractWarning = String(message || "");
  banner.hidden = !state.uiContractWarning;
  banner.classList.toggle("is-visible", Boolean(state.uiContractWarning));
  banner.textContent = state.uiContractWarning;
}

export async function loadUiCapabilities() {
  try {
    const data = await apiGet("/ui/capabilities");
    state.uiCapabilities = data;
    const modes = new Set((data.modes || []).map((item) => item.id));
    const views = new Set((data.views || []).map((item) => item.id));
    const endpoints = new Set((data.endpoints || []).map((item) => item.path));
    const missingModes = ["standard", "cinema"].filter((item) => !modes.has(item));
    const missingViews = ["overview", "users", "groups", "personal", "knowledge", "microscope", "archive"]
      .filter((item) => !views.has(item));
    const missingDynamic = [...UI_DYNAMIC_ENDPOINTS].filter((item) => !endpoints.has(item));
    const compatible = data.contract_version === UI_CONTRACT_VERSION
      && !missingModes.length
      && !missingViews.length
      && !missingDynamic.length;
    document.documentElement.dataset.uiContract = compatible ? "ready" : "mismatch";
    if (!compatible) {
      renderUiCompatibilityBanner("界面与后端能力版本不一致，部分管理操作可能不可用。请刷新插件缓存或确认前后端版本一致。");
      return false;
    }
    renderUiCompatibilityBanner("");
    return true;
  } catch (error) {
    state.uiCapabilities = null;
    document.documentElement.dataset.uiContract = "unavailable";
    renderUiCompatibilityBanner(`无法校验界面功能：${error.message || "能力接口不可用"}。当前页面仅按已知安全功能运行。`);
    return false;
  }
}

export function loadingState(text = state.overviewLayout === "cinema" ? "正在读取胶片..." : "正在读取数据...") {
  return `<div class="loading-state"><span></span><b>${escapeHtml(text)}</b></div>`;
}

export function panelError(error, retryLabel = "重试") {
  return `
    <div class="empty-state error-state">
      <b>读取失败</b>
      <span>${escapeHtml(error?.message || error || "未知错误")}</span>
      <button data-retry-active type="button">${escapeHtml(retryLabel)}</button>
    </div>
  `;
}

export async function withBusy(text, task) {
  try {
    setBusy(true, text);
    return await task();
  } catch (error) {
    showToast(error.message || "操作失败", "error");
    return undefined;
  } finally {
    setBusy(false);
  }
}

export async function withButton(button, text, task) {
  const original = button.textContent;
  button.disabled = true;
  button.classList.add("is-loading");
  button.textContent = text;
  try {
    return await task();
  } catch (error) {
    showToast(error.message || "操作失败", "error");
    return undefined;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.textContent = original;
  }
}

export function activeBucket() {
  return state.buckets.find((bucket) => bucket.id === state.activeBucketId) || state.buckets[0];
}

export function bucketLabel(bucket = activeBucket()) {
  return bucket?.label || "全部记忆";
}

export function isWindowBucket(bucket) {
  return Boolean(bucket && ["group", "private"].includes(bucket.scope) && bucket.target_id);
}

export function windowKindLabel(scope) {
  return scope === "group" ? "群聊" : "私聊";
}

export function bucketByWindow(scope, id) {
  return state.buckets.find((bucket) => bucket.scope === scope && bucket.target_id === id);
}

export function windowIdentifierLabel(scope, id, targetKind = "") {
  if (!id) return scope === "group" ? "群号未知" : "会话 ID 未知";
  if (scope === "group") return `群号 ${id}`;
  if (targetKind === "legacy_live2d") return `Live2D 会话 ${id}`;
  if (targetKind === "internal") return `内部会话 ${id}`;
  if (targetKind === "legacy_session") return `旧会话 ${id}`;
  if (targetKind === "qq" || /^\d+$/.test(String(id))) return `QQ ${id}`;
  return `私聊会话 ${id}`;
}

export function stripLabeledPrefix(value) {
  return String(value ?? "")
    .replace(/\b(?:Group\s*ID|Group\s*Name|Name|User\s*ID|User\s*Name|QQ)\s*[:：]\s*/gi, "")
    .trim();
}

export function cleanWindowDisplayName(value) {
  return stripLabeledPrefix(value)
    .replace(/\s+(?:Avatar|Owner\s*ID|Admin\s*IDs?|Member\s*Count|Max\s*Member\s*Count|Description)\s*[:：].*$/i, "")
    .trim();
}

export function splitWindowBucketTitle(bucket = {}) {
  const scope = bucket.scope || "";
  const targetId = compact(bucket.target_id || bucket.group_id, "");
  const targetKind = compact(bucket.target_kind, "");
  const rawLabel = cleanWindowDisplayName(bucket.label || "");
  const rawSublabel = cleanWindowDisplayName(bucket.sublabel || "");
  const escapedId = targetId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const nameFromLabel = escapedId
    ? rawLabel.replace(new RegExp(`\\b${escapedId}\\b`, "g"), "").replace(/\s+/g, " ").trim()
    : rawLabel;
  const explicitName = cleanWindowDisplayName(bucket.target_name || bucket.display_name || "");
  const inferredName = cleanWindowDisplayName(nameFromLabel || "");
  const genericNames = new Set(["群聊", "私聊", "用户", "好友", "旧 Live2D 会话", "旧私聊会话", "内部会话", "私聊会话"]);
  const name = explicitName || (genericNames.has(inferredName) ? "" : inferredName);
  if (scope === "group") {
    return {
      primary: targetId ? `群号 ${targetId}` : "群号未知",
      secondary: name && name !== targetId ? name : (rawSublabel && rawSublabel !== targetId ? rawSublabel : "未记录群名"),
    };
  }
  if (scope === "private") {
    if (targetKind === "legacy_live2d") {
      return {
        primary: "旧 Live2D 会话",
        secondary: name && name !== targetId ? name : `ID ${targetId || "未知"}`,
      };
    }
    if (targetKind === "internal") {
      return {
        primary: "内部会话",
        secondary: name && name !== targetId ? name : (targetId || "未记录标识"),
      };
    }
    if (targetKind === "legacy_session") {
      return {
        primary: "旧私聊会话",
        secondary: name && name !== targetId ? name : `ID ${targetId || "未知"}`,
      };
    }
    if (targetKind !== "qq" && !/^\d+$/.test(String(targetId))) {
      return {
        primary: "私聊会话",
        secondary: name && name !== targetId ? name : (targetId || "未记录标识"),
      };
    }
    return {
      primary: targetId ? `QQ ${targetId}` : "QQ 未知",
      secondary: name && name !== targetId ? name : (rawSublabel && rawSublabel !== targetId ? rawSublabel : "未记录昵称"),
    };
  }
  return { primary: rawLabel || bucket.label || "未命名", secondary: rawSublabel || "" };
}

export function windowDisplayLabel(scope, id, name = "", targetKind = "") {
  const displayName = compact(name, "");
  if (displayName && displayName !== id) return displayName;
  if (scope === "group") return `群聊 ${id || "未知群聊"}`;
  if (targetKind === "legacy_live2d") return "旧 Live2D 会话";
  if (targetKind === "internal") return "内部会话";
  if (targetKind === "legacy_session") return "旧私聊会话";
  return `私聊 ${id || "未知用户"}`;
}

export function secondaryNavItems(view = state.activeView) {
  return SECONDARY_NAV[view] || [];
}

export function defaultSecondaryNav(view = state.activeView) {
  return secondaryNavItems(view)[0]?.id || "";
}

export function activeSecondaryNav(view = state.activeView) {
  const items = secondaryNavItems(view);
  if (!items.length) return "";
  const active = state.secondaryNav[view];
  if (view === "archive" && active === "repair") {
    state.secondaryNav[view] = "maintenance";
    return "maintenance";
  }
  if (view === "archive" && CONFIG_ADVANCED_FALLBACKS[active]) {
    state.secondaryNav[view] = CONFIG_ADVANCED_FALLBACKS[active];
    return state.secondaryNav[view];
  }
  if (items.some((item) => item.id === active)) return active;
  state.secondaryNav[view] = items[0].id;
  return items[0].id;
}

export function activeSecondaryItem(view = state.activeView) {
  const active = activeSecondaryNav(view);
  return secondaryNavItems(view).find((item) => item.id === active) || null;
}

export function secondaryNavRenderItems(view = state.activeView) {
  const items = secondaryNavItems(view);
  const active = activeSecondaryNav(view);
  return items.map((item, index) => ({
    ...item,
    renderKey: `${item.id}-${index}`,
    isActiveLoopItem: item.id === active,
  }));
}

export function renderSecondaryNav(view = state.activeView, immediate = false) {
  if (view === "review") return;
  const items = secondaryNavItems(view);
  if (!items.length) {
    renderBuckets();
    return;
  }
  const rail = document.querySelector(".object-rail");
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  rail?.classList.remove("is-scoped-rail");
  rail?.classList.add("is-secondary-nav", "is-looped-secondary-nav");
  if (railTitle) railTitle.textContent = view === "archive" ? "维护与配置" : "二级导航";
  if (clearButton) clearButton.textContent = view === "archive" ? "回到顶部" : "默认";
  const renderItems = secondaryNavRenderItems(view);
  const archiveGroups = {
    maintenance: "资料维护", "core-memory": "采集与整理", retrieval: "检索与上下文",
    "config:visibility": "权限与关联", "config:maintenance": "运行与外观",
  };
  $("#bucketList").innerHTML = renderItems.map((item) => `
    ${view === "archive" && archiveGroups[item.id] ? `<h3 class="aw-secondary-heading">${archiveGroups[item.id]}</h3>` : ""}
    <button class="bucket secondary-nav-item${item.isActiveLoopItem ? " is-active" : ""}" data-secondary-nav="${escapeHtml(item.id)}" data-loop-key="${escapeHtml(item.renderKey)}" type="button" aria-current="${item.isActiveLoopItem ? "true" : "false"}">
      <b>${escapeHtml(item.label)}</b>
      <small>${escapeHtml(item.sublabel)}</small>
      <div class="badges"><span class="badge blue">${escapeHtml(item.badge)}</span></div>
    </button>
  `).join("");
  $$("#bucketList [data-secondary-nav]").forEach((item) => {
    item.addEventListener("click", () => selectSecondaryNav(item.dataset.secondaryNav));
  });
  const activeItem = activeSecondaryItem(view);
  $("#activeTarget").textContent = activeItem ? `${VIEWS[view]?.title || "二级页"} · ${activeItem.label}` : (VIEWS[view]?.title || "二级页");
  resetRailCoverflow();
  requestAnimationFrame(() => moveSecondaryNavToStandard(immediate));
}
