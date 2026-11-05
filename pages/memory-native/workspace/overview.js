/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet} from './client.js';
import {hydratePersonalAlbumImages} from './configuration.js';
import {clearDetail} from './editors.js';
import {formatFileSize} from './maintenance.js';
import {loadActiveView,playInitialOverviewEntrance,selectBucket} from './memory.js';
import {syncNativeMemoryNavigation} from './personal.js';
import {alignPersonalScheduleToReel,bindPersonalMemoryWorkspace,loadPersonalMemory,renderPersonalMemoryWorkspace,retractScheduleFilmBeforeDateMove,switchPersonalAlbumDate,syncPersonalLayoutForUiMode} from './portraits.js';
import {$,$$,OVERVIEW_LAYOUT_KEY,VIEWS,asteriaWorkspaceState,state} from './state.js';
import {activeBucket,activeSecondaryItem,bucketLabel,cleanWindowDisplayName,compact,escapeHtml,formatTime,isWindowBucket,prefersReducedMotion,renderScopeControls,secondaryNavItems,setMessage,splitWindowBucketTitle,windowDisplayLabel,windowIdentifierLabel,windowKindLabel,withBusy} from './workspace.js';

export async function selectSecondaryNav(id) {
  const view = state.activeView;
  if (!secondaryNavItems(view).some((item) => item.id === id)) return;
  const prevActive = state.secondaryNav[view];
  if (prevActive === id || state.secondaryNavSwitching) return;
  state.secondaryNav[view] = id;
  syncNativeMemoryNavigation(view);
  try {
    state.secondaryNavSwitching = true;
    const list = $("#bucketList");
    if (list) {
      list.querySelectorAll(".secondary-nav-item").forEach((el) => {
        const isActive = el.dataset.secondaryNav === id;
        el.classList.toggle("is-active", isActive);
        el.setAttribute("aria-current", isActive ? "true" : "false");
      });
      const activeItem = activeSecondaryItem(view);
      $("#activeTarget").textContent = activeItem ? `${VIEWS[view]?.title || "二级页"} · ${activeItem.label}` : (VIEWS[view]?.title || "二级页");
    }
    moveSecondaryNavToStandard(false);
    clearDetail();
    await loadActiveView();
    scrollActiveWorkspaceToTop({ immediate: true });
  } finally {
    state.secondaryNavSwitching = false;
  }
}

export function moveSecondaryNavToStandard(immediate = false) {
  if (state.activeView === "review") return;
  const app = $("#app");
  const list = $("#bucketList");
  const rail = document.querySelector(".object-rail.is-secondary-nav");
  if (!app || !list || !rail) return;
  const items = Array.from(list.querySelectorAll(".secondary-nav-item"));
  const active = list.querySelector(".secondary-nav-item.is-active");
  if (!active || !items.length) return;
  if (document.documentElement.dataset.nativeWorkspace) {
    const box = rail.getBoundingClientRect();
    const selected = active.getBoundingClientRect();
    if (selected.top < box.top || selected.bottom > box.bottom) {
      rail.scrollTop += selected.top - box.top - 12;
    }
    return;
  }
  const currentShift = parseFloat(getComputedStyle(app).getPropertyValue("--secondary-nav-shift")) || 0;
  const standard = items[Math.min(1, items.length - 1)];
  const activeTop = active.getBoundingClientRect().top - currentShift;
  const standardTop = standard.getBoundingClientRect().top - currentShift;
  list.style.transition = immediate ? "none" : "";
  app.style.setProperty("--secondary-nav-shift", `${Math.round(standardTop - activeTop)}px`);
  if (immediate) {
    list.offsetHeight;
    list.style.transition = "";
  }
}

export function scrollActiveWorkspaceToTop(options = {}) {
  const behavior = options.immediate || prefersReducedMotion() ? "auto" : "smooth";
  const activeView = document.querySelector(`#view-${state.activeView}`);
  const candidates = [
    activeView?.querySelector(".archive-grid"),
    activeView?.querySelector(".config-panel-stack"),
    activeView?.querySelector(".page-panel-stack"),
    activeView?.querySelector(".row-list"),
    activeView?.querySelector(".track-strip"),
    activeView,
    document.querySelector(".workspace-main"),
  ].filter(Boolean);
  const seen = new Set();
  candidates.forEach((element) => {
    if (seen.has(element)) return;
    seen.add(element);
    if (typeof element.scrollTo === "function") {
      element.scrollTo({ top: 0, left: 0, behavior });
    }
  });
}

export function contextParams(extra = {}) {
  const bucket = activeBucket();
  const params = new URLSearchParams();
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      params.set(key, String(value).trim());
    }
  });
  if (!bucket || bucket.id === "all") return params;
  if (bucket.id === "self") {
    params.set("visibility", "bot_self");
    return params;
  }
  if (bucket.scope) params.set("scope", bucket.scope);
  if (bucket.scope === "private") {
    if (bucket.target_id) params.set("entity_id", bucket.target_id);
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  } else if (bucket.scope === "group") {
    if (bucket.group_id) {
      params.set("group_id", bucket.group_id);
    } else if (bucket.target_id) {
      params.set("entity_id", bucket.target_id);
    }
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  }
  return params;
}

export function microscopeContextId(bucket, botId = "") {
  if (!bucket || bucket.id === "all" || !botId) return bucket?.id || "all";
  return JSON.stringify([bucket.id, botId]);
}

export function microscopeBuckets() {
  const contexts = [];
  state.buckets.filter(isWindowBucket).forEach((bucket) => {
    const samples = (bucket.microscope_contexts || []).filter(
      (item) => Number(item.searchable_count || 0) > 0,
    );
    const botSamples = samples.filter((item) => item.bot_id);
    const selectable = botSamples.length ? botSamples : samples.slice(0, 1);
    selectable.forEach((sample) => {
      contexts.push({
        ...bucket,
        microscope_id: microscopeContextId(bucket, sample.bot_id),
        session_id: sample.session_id || bucket.session_id || "",
        group_id: sample.group_id || bucket.group_id || "",
        bot_id: sample.bot_id || "",
        searchable_count: Number(sample.searchable_count || 0),
      });
    });
  });
  return contexts;
}

export function microscopeBucket() {
  return microscopeBuckets().find((bucket) => (
    bucket.microscope_id === state.microscopeBucketId
  )) || state.buckets.find((bucket) => bucket.id === "all") || {
    id: "all",
    label: "全部可检索记忆",
  };
}

export function microscopeBucketLabel(bucket = microscopeBucket()) {
  if (!bucket || bucket.id === "all") return "全部可检索记忆";
  const title = splitWindowBucketTitle(bucket);
  return [title.primary, title.secondary, bucket.bot_id ? `Bot ${bucket.bot_id}` : ""]
    .filter(Boolean)
    .join(" · ");
}

export function updateMicroscopeContextMeta() {
  const meta = $("#microscopeContextMeta");
  if (!meta) return;
  const bucket = microscopeBucket();
  if (bucket.id === "all") {
    meta.textContent = "管理检索 · 全部可检索记忆";
    return;
  }
  meta.textContent = `${windowKindLabel(bucket.scope)}上下文 · ${microscopeBucketLabel(bucket)}`;
}

export function renderMicroscopeContexts() {
  const select = $("#microscopeContext");
  if (!select) return;
  const windows = microscopeBuckets();
  if (!windows.some((bucket) => bucket.microscope_id === state.microscopeBucketId)) {
    state.microscopeBucketId = "all";
  }
  const groups = ["private", "group"].map((scope) => {
    const options = windows.filter((bucket) => bucket.scope === scope);
    if (!options.length) return "";
    return `
      <optgroup label="${scope === "group" ? "群聊" : "私聊"}">
        ${options.map((bucket) => `
          <option value="${escapeHtml(bucket.microscope_id)}">${escapeHtml(`${microscopeBucketLabel(bucket)} · ${bucket.searchable_count || 0} 条候选`)}</option>
        `).join("")}
      </optgroup>
    `;
  }).join("");
  select.innerHTML = `<option value="all">全部可检索记忆（管理检索）</option>${groups}`;
  select.value = state.microscopeBucketId;
  updateMicroscopeContextMeta();
}

export function clearMicroscopeResults(message = "选择范围并输入内容后开始检索。") {
  const result = $("#searchResult");
  if (!result) return;
  result.setAttribute("aria-busy", "false");
  result.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

export function setMicroscopeSearchBusy(busy) {
  const button = $("#runSearchBtn");
  if (!button) return;
  button.disabled = Boolean(busy);
  button.classList.toggle("is-loading", Boolean(busy));
  button.textContent = busy ? "检索中" : "开始检索";
}

export function invalidateMicroscopeSearch(message) {
  state.microscopeSearchToken += 1;
  setMicroscopeSearchBusy(false);
  clearMicroscopeResults(message);
}

export function contextPayload(query, bucket = microscopeBucket()) {
  const payload = { query, top_k: 8, context_mode: "all" };
  if (!bucket || bucket.id === "all") return payload;
  payload.context_mode = "session";
  payload.scope = bucket.scope || "unknown";
  payload.session_id = bucket.session_id || "";
  payload.bot_id = bucket.bot_id || "";
  if (bucket.scope === "private") {
    payload.user_id = bucket.target_id || "";
  }
  if (bucket.scope === "group") {
    payload.group_id = bucket.group_id || bucket.target_id || "";
  }
  return payload;
}

export function normalizeOverviewLayout(layout) {
  return layout === "cinema" ? "cinema" : "standard";
}

export function syncOverviewLayoutControls() {
  const layout = normalizeOverviewLayout(state.overviewLayout);
  state.overviewLayout = layout;
  document.documentElement.dataset.overviewLayout = layout;
  $("#app")?.setAttribute("data-ui-mode", layout);
  const eyebrow = $("#workspaceEyebrow");
  if (eyebrow) eyebrow.textContent = layout === "cinema" ? "Locked Frame" : "Memory Management";
  $$(".overview-layout-option").forEach((button) => {
    const active = button.dataset.overviewLayout === layout;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-checked", active ? "true" : "false");
    button.tabIndex = active ? 0 : -1;
  });
}

export function setOverviewLayout(layout, { persist = true, announce = true } = {}) {
  const next = normalizeOverviewLayout(layout);
  const changed = next !== state.overviewLayout;
  state.overviewLayout = next;
  if (persist) {
    try {
      window.localStorage.setItem(OVERVIEW_LAYOUT_KEY, next);
    } catch (_) {
      // 本地存储不可用时，本次页面内的切换仍然有效。
    }
  }
  syncOverviewLayoutControls();
  if (!changed) return;

  const app = $("#app");
  app?.classList.remove("is-overview-restoring", "is-overview-booting", "is-standard-overview-entering");
  if (app && !app.classList.contains("is-workspace")) {
    if (next === "cinema") {
      playInitialOverviewEntrance();
    } else if (!prefersReducedMotion()) {
      app.classList.add("is-standard-overview-entering");
      window.setTimeout(() => app.classList.remove("is-standard-overview-entering"), 420);
    }
  }
  if (app?.classList.contains("is-workspace") && state.activeView === "review") {
    syncPersonalLayoutForUiMode();
  }
  if (announce) {
    const live = $("#overviewLayoutAnnouncement");
    if (live) live.textContent = next === "cinema" ? "已切换到放映馆界面" : "已切换到简洁管理界面";
  }
}

export function memoryStatsItems(stats) {
  const currentFiles = stats.memory_storage || stats.wal?.current_files || stats.wal || {};
  const databaseBytes = Math.max(0, Number(currentFiles.database_bytes ?? currentFiles.db_bytes ?? 0));
  const walBytes = Math.max(0, Number(currentFiles.wal_bytes ?? 0));
  const shmBytes = Math.max(0, Number(currentFiles.shm_bytes ?? 0));
  const reportedBytes = Number(stats.memory_storage_bytes ?? currentFiles.total_bytes);
  const storageBytes = Number.isFinite(reportedBytes)
    ? Math.max(0, reportedBytes)
    : databaseBytes + walBytes + shmBytes;
  return [
    { key: "memory-count", label: "记忆", value: stats.total_memories ?? 0 },
    {
      key: "memory-storage",
      label: "记忆大小",
      value: formatFileSize(storageBytes),
      title: `数据库 ${formatFileSize(databaseBytes)} · WAL ${formatFileSize(walBytes)} · SHM ${formatFileSize(shmBytes)}`,
    },
    { key: "private-memory", label: "私聊记忆", value: stats.by_scope?.private ?? 0 },
    { key: "group-memory", label: "群聊记忆", value: stats.by_scope?.group ?? 0 },
  ];
}

export function renderStats(stats) {
  const items = memoryStatsItems(stats);
  const filmStats = $("#stats");
  if (filmStats) filmStats.innerHTML = items.map(({ key, label, value, title = "" }) => `
    <article class="stat ${key === "memory-storage" ? "is-storage" : ""}" data-stat="${escapeHtml(key)}"${title ? ` title="${escapeHtml(title)}"` : ""}>
      <b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span>
    </article>
  `).join("");
  const standardStats = $("#standardStats");
  if (standardStats) standardStats.innerHTML = items.map(({ key, label, value, title = "" }) => `
    <article class="overview-kpi ${key === "memory-storage" ? "is-storage" : ""}" data-stat="${escapeHtml(key)}"${title ? ` title="${escapeHtml(title)}"` : ""}>
      <span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b>
    </article>
  `).join("");
}

export function normalizeBuckets(rawBuckets) {
  const normalized = [
    {
      id: "all",
      label: "全部记忆",
      sublabel: "不限定对象",
      memory_count: state.stats.total_memories || 0,
      latest_at: "",
    },
    {
      id: "self",
      label: "Bot 自己",
      sublabel: "行动、创作、搜索、阅读",
      memory_count: 0,
      latest_at: "",
    },
  ];
  for (const item of rawBuckets || []) {
    const scope = compact(item.scope, "unknown");
    const targetId = compact(item.target_id, "");
    if (!targetId) continue;
    const targetKind = compact(item.target_kind, "");
    const name = cleanWindowDisplayName(item.target_name || item.display_name || "");
    const label = windowDisplayLabel(scope, targetId, name, targetKind);
    const identifierLabel = windowIdentifierLabel(scope, targetId, targetKind);
    const microscopeContexts = (Array.isArray(item.sample_contexts) ? item.sample_contexts : []).map((context) => ({
      bot_id: compact(context.bot_id, ""),
      session_id: compact(context.session_id, ""),
      group_id: compact(context.group_id, ""),
      memory_count: Number(context.memory_count || 0),
      archived_count: Number(context.archived_count || 0),
      searchable_count: Number(
        context.searchable_count
        ?? Math.max(0, Number(context.memory_count || 0) - Number(context.archived_count || 0)),
      ),
    }));
    if (!microscopeContexts.length) {
      microscopeContexts.push({
        bot_id: compact(item.sample_bot_id, ""),
        session_id: compact(item.sample_session_id, ""),
        group_id: compact(item.sample_group_id, ""),
        memory_count: Number(item.memory_count || 0),
        archived_count: Number(item.archived_count || 0),
        searchable_count: Number(
          item.searchable_count
          ?? Math.max(0, Number(item.memory_count || 0) - Number(item.archived_count || 0)),
        ),
      });
    }
    normalized.push({
      id: `${scope}:${targetId}`,
      scope,
      target_id: targetId,
      target_kind: targetKind,
      display_name: name,
      identifier_label: identifierLabel,
      group_id: item.sample_group_id || (scope === "group" ? targetId : ""),
      session_id: item.sample_session_id || "",
      bot_id: item.sample_bot_id || "",
      microscope_contexts: microscopeContexts,
      label,
      sublabel: identifierLabel,
      memory_count: item.memory_count || 0,
      archived_count: item.archived_count || 0,
      latest_at: item.latest_at || "",
    });
  }
  return normalized;
}

export function renderStandardRecentBuckets() {
  const host = $("#standardRecentBuckets");
  const meta = $("#overviewScopeMeta");
  if (!host) return;
  const windows = state.buckets.filter(isWindowBucket);
  const privateCount = windows.filter((bucket) => bucket.scope === "private").length;
  const groupCount = windows.filter((bucket) => bucket.scope === "group").length;
  if (meta) meta.textContent = `${privateCount} 个私聊 · ${groupCount} 个群聊`;

  const recent = [...windows]
    .sort((left, right) => String(right.latest_at || "").localeCompare(String(left.latest_at || "")))
    .slice(0, 5);
  if (!recent.length) {
    host.innerHTML = '<p class="overview-empty">还没有私聊或群聊记忆</p>';
    return;
  }
  host.innerHTML = recent.map((bucket) => {
    const view = bucket.scope === "group" ? "film" : "maintain";
    const kind = bucket.scope === "group" ? "群" : "私";
    return `
      <button class="overview-scope-row" data-overview-view="${view}" data-overview-bucket="${escapeHtml(bucket.id)}" type="button">
        <span class="overview-scope-kind is-${escapeHtml(bucket.scope)}" aria-hidden="true">${kind}</span>
        <span class="overview-scope-copy">
          <b>${escapeHtml(bucket.label)}</b>
          <small>${escapeHtml(formatTime(bucket.latest_at))}</small>
        </span>
        <span class="overview-scope-count">${escapeHtml(bucket.memory_count || 0)} 条</span>
      </button>
    `;
  }).join("");
}

export function bucketCard(bucket) {
  const active = bucket.id === state.activeBucketId ? " is-active" : "";
  const windowTitle = isWindowBucket(bucket) ? splitWindowBucketTitle(bucket) : null;
  const title = windowTitle ? `
      <span class="bucket-title-lines">
        <b>${escapeHtml(windowTitle.primary)}</b>
        <em>${escapeHtml(windowTitle.secondary)}</em>
      </span>
    ` : `<b>${escapeHtml(bucket.label)}</b>`;
  return `
    <article class="bucket${active}${windowTitle ? " bucket-window-card" : ""}" data-bucket-id="${escapeHtml(bucket.id)}" role="button" tabindex="0" aria-current="${bucket.id === state.activeBucketId ? "true" : "false"}">
      ${title}
      ${windowTitle ? "" : `<small>${escapeHtml(bucket.sublabel || "")}</small>`}
      <div class="badges">
        <span class="badge blue">${escapeHtml(bucket.memory_count || 0)} 条</span>
      </div>
    </article>
  `;
}

export function scopedRailConfig(scope) {
  if (scope === "group") {
    return { title: "群聊列表", clear: "全部群聊", label: "全部群聊", sublabel: "不限定群聊", badge: "群聊" };
  }
  return { title: "私聊用户", clear: "全部私聊", label: "全部私聊", sublabel: "不限定用户", badge: "私聊" };
}

export function bindBucketListInteractions() {
  $$("#bucketList [data-bucket-id]").forEach((item) => {
    item.addEventListener("click", (event) => {
      selectBucket(item.dataset.bucketId);
    });
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectBucket(item.dataset.bucketId);
      }
    });
  });
}

export function currentRailScope() {
  if (state.activeView === "film") return "group";
  if (state.activeView === "relations") return "private";
  if (state.activeView === "maintain") return "private";
  return "";
}

export function scopedViewScope(view = state.activeView) {
  if (view === "film") return "group";
  if (view === "relations") return "private";
  if (view === "maintain") return "private";
  return "";
}

export function scopedViewTarget(view = state.activeView) {
  if (view === "film") return "#groupMemoryList";
  if (view === "relations") return "#relationList";
  if (view === "maintain") return "#privateMemoryList";
  return "";
}

export function renderScopedModeControls(view = state.activeView) {
  const scope = scopedViewScope(view);
  if (!scope) return;
  const title = view === "film" ? $("#groupMemoryTitle") : view === "relations" ? $("#userMemoryTitle") : $("#privateMemoryTitle");
  const hint = view === "film" ? $("#groupMemoryHint") : view === "relations" ? $("#userMemoryHint") : $("#privateMemoryHint");
  if (title) title.textContent = view === "relations" ? "用户档案与记忆" : `${windowKindLabel(scope)}记忆`;
  if (hint) hint.textContent = VIEWS[view]?.hint || "";
  updateScopedClearButton(view);
}

export function updateScopedClearButton(view = state.activeView) {
  const button = view === "film" ? $("#clearCurrentGroupMemoryBtn") : ["relations", "maintain"].includes(view) ? $("#clearCurrentPrivateMemoryBtn") : null;
  const bucket = activeBucket();
  const scope = scopedViewScope(view);
  const canClear = Boolean(bucket && bucket.id !== "all" && bucket.scope === scope && bucket.target_id);
  if (button) {
    button.disabled = !canClear;
    button.title = canClear ? `清空 ${bucket.label} 的记忆` : `请先选择具体${scope === "group" ? "群聊" : "私聊用户"}`;
  }
  if (view === "film") {
    const memberInput = $("#clearGroupMemberUserId");
    const memberButton = $("#clearGroupMemberMemoryBtn");
    if (memberInput) {
      memberInput.disabled = !canClear;
      memberInput.placeholder = canClear ? "群成员 QQ" : "先选择具体群聊";
    }
    if (memberButton) {
      memberButton.disabled = !canClear;
      memberButton.title = canClear ? `清空 ${bucket.label} 中某个成员的记忆` : "请先选择具体群聊";
    }
  }
}

export function renderScopedBucketRail(scope) {
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.add("is-scoped-rail");
  $("#app")?.style.removeProperty("--secondary-nav-shift");
  renderScopedModeControls();
  const config = scopedRailConfig(scope);
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  if (railTitle) railTitle.textContent = config.title;
  if (clearButton) clearButton.textContent = config.clear;

  const scopedBuckets = state.buckets.filter((bucket) => bucket.scope === scope);
  if (state.activeBucketId !== "all" && !scopedBuckets.some((bucket) => bucket.id === state.activeBucketId)) {
    state.activeBucketId = "all";
  }
  renderScopeControls();
  const totalCount = scopedBuckets.reduce((sum, bucket) => sum + Number(bucket.memory_count || 0), 0);
  const allBucket = {
    id: "all",
    label: config.label,
    sublabel: config.sublabel,
    memory_count: totalCount,
  };
  $("#bucketList").innerHTML = [allBucket, ...scopedBuckets].map((bucket) => bucketCard(bucket)).join("");
  bindBucketListInteractions();
  $("#activeTarget").textContent = state.activeBucketId === "all" ? config.label : bucketLabel();
  updateScopedClearButton();
  requestRailCoverflow();
  centerActiveBucket();
}

export function renderBuckets() {
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.remove("is-scoped-rail");
  $("#app")?.style.removeProperty("--secondary-nav-shift");
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  if (railTitle) railTitle.textContent = "观察对象";
  if (clearButton) clearButton.textContent = "全部";
  $("#bucketList").innerHTML = state.buckets.map(bucketCard).join("");
  const objectCards = $("#objectCards");
  if (objectCards) {
    objectCards.innerHTML = state.buckets.map((bucket) => `
      <article class="object-card${bucket.id === state.activeBucketId ? " is-active" : ""}" data-bucket-id="${escapeHtml(bucket.id)}" role="button" tabindex="0" aria-current="${bucket.id === state.activeBucketId ? "true" : "false"}">
        <span class="item-title">${escapeHtml(bucket.label)}</span>
        <div class="item-meta">${escapeHtml(bucket.sublabel || "全局范围")} · 最近 ${escapeHtml(formatTime(bucket.latest_at))}</div>
        <div class="badges">
          <span class="badge blue">${escapeHtml(bucket.memory_count || 0)} 条记忆</span>
        </div>
      </article>
    `).join("");
  }
  bindBucketListInteractions();
  // Event delegation: single handler for all bucket cards
  if (objectCards) {
    objectCards.onclick = (event) => {
      const card = event.target.closest("[data-bucket-id]");
      if (card && objectCards.contains(card)) {
        selectBucket(card.dataset.bucketId);
      }
    };
    objectCards.onkeydown = (event) => {
      const card = event.target.closest("[data-bucket-id]");
      if (card && objectCards.contains(card) && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        selectBucket(card.dataset.bucketId);
      }
    };
  }
  $("#activeTarget").textContent = bucketLabel();
  requestRailCoverflow();
  centerActiveBucket();
}

export function renderPersonalDateRail(dates, selectedDate) {
  const app = $("#app");
  const list = $("#bucketList");
  const rail = document.querySelector(".object-rail");
  rail?.classList.remove("is-secondary-nav", "is-looped-secondary-nav");
  rail?.classList.remove("is-scoped-rail");
  app?.style.removeProperty("--secondary-nav-shift");
  const animate = state.animatePersonalDateRail && !prefersReducedMotion();
  const keepReelMotion = state.animatePersonalViewportRail && !prefersReducedMotion();
  if (app && list && !animate && !keepReelMotion) {
    list.style.transition = "none";
    app.style.removeProperty("--personal-reel-shift");
    list.offsetHeight;
    list.style.transition = "";
  }
  state.personalDates = Array.isArray(dates) ? dates : [];
  state.selectedPersonalDate = selectedDate || state.personalDates[0] || "";
  const railTitle = document.querySelector(".rail-head b");
  const clearButton = $("#clearTargetBtn");
  if (railTitle) railTitle.textContent = "日期胶卷";
  if (clearButton) clearButton.textContent = "今天";
  $("#bucketList").innerHTML = state.personalDates.length ? state.personalDates.map((date) => {
    const active = date === state.selectedPersonalDate ? " is-active" : "";
    const label = date === todayKey() ? "今天" : formatDateLabel(date);
    return `
      <button class="bucket date-reel${active}" data-personal-date="${escapeHtml(date)}" type="button" aria-current="${date === state.selectedPersonalDate ? "true" : "false"}">
        <b>${escapeHtml(label)}</b>
        <small>${escapeHtml(date)}</small>
      </button>
    `;
  }).join("") : `<div class="empty-state">还没有可选择的日期。</div>`;
  $$("#bucketList [data-personal-date]").forEach((item) => {
    item.addEventListener("click", () => withBusy("正在切换个人记忆日期...", () => selectPersonalDate(item.dataset.personalDate)));
  });
  $("#activeTarget").textContent = state.selectedPersonalDate ? `个人记忆 · ${state.selectedPersonalDate}` : "个人记忆";
  resetRailCoverflow();
  state.pendingPersonalFilmReveal = animate;
  state.animatePersonalDateRail = false;
  requestAnimationFrame(() => movePersonalDateToStandard(!animate));
}

export async function selectPersonalDate(date) {
  const nextDate = date || "";
  const changed = nextDate && nextDate !== state.selectedPersonalDate;
  if (!changed) return;
  const previous = {
    date: state.selectedPersonalDate,
    schedule: state.selectedScheduleIndex,
    album: state.selectedPersonalAlbumIndex,
    subjective: state.selectedSubjectiveMemoryIndex,
    snapshot: state.personalSnapshot,
    data: state.personalData,
  };
  try {
    if (state.personalViewport !== "album") {
      await retractScheduleFilmBeforeDateMove();
    }
    state.selectedPersonalDate = nextDate;
    state.selectedScheduleIndex = "";
    state.selectedPersonalAlbumIndex = "";
    state.selectedSubjectiveMemoryIndex = "";
    state.animatePersonalDateRail = true;
    if (state.personalViewport === "album") {
      await switchPersonalAlbumDate();
      resetRailCoverflow();
      return;
    }
    clearDetail();
    await loadPersonalMemory();
    resetRailCoverflow();
  } catch (error) {
    state.selectedPersonalDate = previous.date;
    state.selectedScheduleIndex = previous.schedule;
    state.selectedPersonalAlbumIndex = previous.album;
    state.selectedSubjectiveMemoryIndex = previous.subjective;
    state.personalSnapshot = previous.snapshot;
    state.personalData = previous.data;
    state.animatePersonalDateRail = false;
    renderPersonalDateRail(state.personalDates, previous.date);
    const target = $("#personalMemoryList");
    if (target && previous.snapshot && previous.data) {
      target.innerHTML = renderPersonalMemoryWorkspace(previous.snapshot, previous.data);
      bindPersonalMemoryWorkspace(target, previous.snapshot, previous.data);
      hydratePersonalAlbumImages(target);
    }
    throw error;
  }
}

export function movePersonalDateToStandard(immediate = false) {
  if (state.activeView !== "review") return;
  const app = $("#app");
  const list = $("#bucketList");
  if (!app || !list) return;
  const reels = Array.from(list.querySelectorAll(".bucket.date-reel"));
  const active = list.querySelector(".bucket.date-reel.is-active");
  if (!active || !reels.length) return;
  const currentShift = parseFloat(getComputedStyle(app).getPropertyValue("--personal-reel-shift")) || 0;
  const standard = reels[Math.min(1, reels.length - 1)];
  const activeTop = active.getBoundingClientRect().top - currentShift;
  const standardTop = standard.getBoundingClientRect().top - currentShift;
  list.style.transition = immediate ? "none" : "";
  app.style.setProperty("--personal-reel-shift", `${Math.round(standardTop - activeTop)}px`);
  if (immediate) {
    list.offsetHeight;
    list.style.transition = "";
  }
  schedulePersonalScheduleAlign(immediate);
}

export function schedulePersonalScheduleAlign(immediate = false) {
  const list = $("#bucketList");
  window.clearTimeout(state.personalAlignTimer);
  if (immediate || !list) {
    requestAnimationFrame(alignPersonalScheduleToReel);
    return;
  }
  const finish = (event) => {
    if (event.target !== list || event.propertyName !== "transform") return;
    window.clearTimeout(state.personalAlignTimer);
    alignPersonalScheduleToReel();
  };
  list.addEventListener("transitionend", finish, { once: true });
  state.personalAlignTimer = window.setTimeout(alignPersonalScheduleToReel, 780);
}

export function todayKey() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function formatDateLabel(date) {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date || "-";
  return parsed.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export function centerActiveBucket() {
  const active = $("#bucketList .bucket.is-active");
  if (!active || !$("#app").classList.contains("is-workspace") || state.activeView === "review" || document.querySelector(".object-rail")?.classList.contains("is-secondary-nav")) return;
  window.setTimeout(() => {
    if (state.activeView === "review" || document.querySelector(".object-rail")?.classList.contains("is-secondary-nav")) return;
    active.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
    requestRailCoverflow();
  }, 40);
}

export function requestRailCoverflow() {
  if (document.documentElement.dataset.nativeWorkspace) return;
  const rail = document.querySelector(".object-rail");
  if (
    state.activeView === "review"
    || rail?.classList.contains("is-secondary-nav")
    || rail?.classList.contains("is-scoped-rail")
  ) {
    resetRailCoverflow();
    return;
  }
  if (asteriaWorkspaceState.railCoverflowFrame) return;
  asteriaWorkspaceState.railCoverflowFrame = window.requestAnimationFrame(() => {
    asteriaWorkspaceState.railCoverflowFrame = 0;
    updateRailCoverflow();
  });
}

export function resetRailCoverflow() {
  $("#bucketList")?.querySelectorAll(".bucket").forEach((bucket) => {
    ["--cf-rot", "--cf-scale", "--cf-z", "--cf-x", "--cf-opacity"].forEach((name) => {
      bucket.style.removeProperty(name);
    });
    bucket.style.removeProperty("z-index");
    bucket.classList.remove("is-cover-center");
  });
}

export function updateRailCoverflow() {
  const list = $("#bucketList");
  if (!list || !$("#app").classList.contains("is-workspace") || state.activeView === "review") return;
  const listRect = list.getBoundingClientRect();
  const centerY = listRect.top + listRect.height / 2;
  const half = listRect.height / 2 || 1;
  list.querySelectorAll(".bucket").forEach((bucket) => {
    const rect = bucket.getBoundingClientRect();
    const bucketY = rect.top + rect.height / 2;
    const distance = Math.max(-1, Math.min(1, (bucketY - centerY) / half));
    const amount = Math.abs(distance);
    const rotate = Math.max(-58, Math.min(58, distance * 62));
    const scale = 1.08 - amount * 0.22;
    const depth = -amount * 110;
    const shift = -amount * 12;
    bucket.style.setProperty("--cf-rot", `${rotate.toFixed(2)}deg`);
    bucket.style.setProperty("--cf-scale", scale.toFixed(3));
    bucket.style.setProperty("--cf-z", `${depth.toFixed(1)}px`);
    bucket.style.setProperty("--cf-x", `${shift.toFixed(1)}px`);
    bucket.style.setProperty("--cf-opacity", String((1 - amount * 0.42).toFixed(3)));
    bucket.style.zIndex = String(1000 - Math.round(amount * 900));
    bucket.classList.toggle("is-cover-center", amount < 0.23);
  });
}

export async function loadStats() {
  const data = await apiGet("/stats");
  state.stats = data.stats || {};
  renderStats(state.stats);
  setMessage("");
}
