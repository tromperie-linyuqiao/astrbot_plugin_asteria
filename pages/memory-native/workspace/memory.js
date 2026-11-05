/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet} from './client.js';
import {applyMicroscopeView,loadArchive,showMemory} from './configuration.js';
import {clearDetail,memoryOption} from './editors.js';
import {loadContextPanel,loadUserMemory} from './knowledge.js';
import {contextParams,currentRailScope,invalidateMicroscopeSearch,microscopeBuckets,normalizeBuckets,renderBuckets,renderMicroscopeContexts,renderScopedBucketRail,renderScopedModeControls,renderStandardRecentBuckets,requestRailCoverflow,scopedViewScope} from './overview.js';
import {syncNativeMemoryNavigation} from './personal.js';
import {alignPersonalScheduleToReel,loadPersonalMemory,removeRailMountedScheduleFilm,retractScheduleFilmBeforeDateMove} from './portraits.js';
import {$,$$,HOME_WIPE_SWAP_WAIT_MS,HOME_WIPE_TOTAL_WAIT_MS,MEMORY_PAGE_SIZE,OVERVIEW_TO_WORKSPACE_WIPE_WAIT_MS,VIEWS,WORKSPACE_WIPE_CLEANUP_MS,asteriaWorkspaceState,state} from './state.js';
import {activeBucket,compact,escapeHtml,formatTime,loadingState,memorySignalBadges,panelError,prefersReducedMotion,refreshTransitionFace,renderSecondaryNav,shortId,showToast,waitForMotion} from './workspace.js';

export async function loadBuckets() {
  const loadToken = ++state.bucketLoadToken;
  const hadLoadedBuckets = state.buckets.length > 0;
  const data = await apiGet("/buckets?limit=180");
  if (loadToken !== state.bucketLoadToken) return false;
  state.buckets = normalizeBuckets(data.buckets || []);
  if (!state.buckets.some((bucket) => bucket.id === state.activeBucketId)) {
    state.activeBucketId = "all";
  }
  const microscopeContextStillAvailable = state.microscopeBucketId === "all"
    || microscopeBuckets().some((bucket) => bucket.microscope_id === state.microscopeBucketId);
  if (!microscopeContextStillAvailable) state.microscopeBucketId = "all";
  if (hadLoadedBuckets) {
    invalidateMicroscopeSearch(
      microscopeContextStillAvailable
        ? "记忆范围已刷新，请重新检索。"
        : "原检索范围已失效，请重新选择。",
    );
  }
  const scope = currentRailScope();
  if ($("#app")?.classList.contains("is-workspace") && scope) {
    renderScopedBucketRail(scope);
  } else if ($("#app")?.classList.contains("is-workspace") && state.activeView !== "review") {
    renderSecondaryNav(state.activeView, true);
  } else if (state.activeView !== "review") {
    renderBuckets();
  }
  renderMicroscopeContexts();
  renderStandardRecentBuckets();
  return true;
}

export async function selectBucket(id) {
  state.activeBucketId = id || "all";
  const scope = currentRailScope();
  if (scope) {
    renderScopedBucketRail(scope);
  } else {
    renderBuckets();
  }
  clearDetail();
  await loadActiveView();
  requestRailCoverflow();
}

export function prepareOverviewStripReturn() {
  $$(".filmstrip").forEach((strip, index) => {
    const style = strip.getAttribute("style") || "";
    const off = parseFloat((style.match(/--off:\s*(-?[\d.]+)px/) || [0, 0])[1]);
    const direction = off < 0 ? -1 : 1;
    strip.style.removeProperty("transition");
    strip.style.removeProperty("transform");
    strip.style.removeProperty("--exit-axis");
    strip.style.removeProperty("--exit-y");
    strip.style.removeProperty("--exit-delay");
    strip.style.setProperty("--return-from-off", `${off + direction * 720}px`);
    strip.style.setProperty("--return-delay", `${Math.min(index * 42, 260)}ms`);
  });
}

export function prepareOverviewStripExit(view) {
  const distance = Math.max(window.innerWidth || 0, window.innerHeight || 0, 960) + 5200;
  $$(".filmstrip").forEach((strip) => {
    const style = strip.getAttribute("style") || "";
    const axis = parseFloat((style.match(/--tx:\s*(-?[\d.]+)px/) || [0, 0])[1]);
    strip.style.removeProperty("transition");
    strip.style.removeProperty("transform");
    strip.style.setProperty("--exit-axis", `${axis + distance}px`);
    strip.style.removeProperty("--exit-y");
    strip.style.setProperty("--exit-delay", "0ms");
  });
}

export function playInitialOverviewEntrance() {
  const app = $("#app");
  if (!app || state.overviewLayout !== "cinema" || prefersReducedMotion() || app.classList.contains("is-workspace")) return;
  prepareOverviewStripReturn();
  app.classList.add("is-overview-restoring", "is-overview-booting");
  window.setTimeout(() => {
    app.classList.remove("is-overview-restoring", "is-overview-booting");
  }, 1180);
}

export async function playOverviewToWorkspace(view) {
  const app = $("#app");
  if (!app || state.overviewLayout !== "cinema" || prefersReducedMotion()) return;
  prepareOverviewStripExit(view);
  refreshTransitionFace();
  app.offsetHeight;
  app.classList.add("is-overview-exiting", "is-workspace-wipe");
  await waitForMotion(OVERVIEW_TO_WORKSPACE_WIPE_WAIT_MS);
}

export async function playWorkspaceSwitchOut() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || state.overviewLayout !== "cinema" || prefersReducedMotion()) return;
  app.classList.add("is-view-switching", "is-view-exiting");
  rail?.classList.add("is-reel-rolling-out");
  await waitForMotion(210);
  app.classList.remove("is-view-exiting");
  rail?.classList.remove("is-reel-rolling-out");
}

export function playWorkspaceSwitchIn() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || state.overviewLayout !== "cinema" || prefersReducedMotion()) return;
  app.classList.add("is-view-entering");
  rail?.classList.add("is-reel-rolling-in");
  window.setTimeout(() => {
    app.classList.remove("is-view-entering", "is-view-switching");
    rail?.classList.remove("is-reel-rolling-in");
  }, 560);
}

export async function playScopedRailSwitchOut() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || state.overviewLayout !== "cinema" || prefersReducedMotion()) return;
  app.classList.add("is-scoped-view-switching", "is-scoped-view-exiting");
  rail?.classList.add("is-reel-rolling-out");
  await waitForMotion(210);
  app.classList.remove("is-scoped-view-exiting");
  rail?.classList.remove("is-reel-rolling-out");
}

export function playScopedRailSwitchIn() {
  const app = $("#app");
  const rail = document.querySelector(".object-rail");
  if (!app || state.overviewLayout !== "cinema" || prefersReducedMotion()) return;
  app.classList.add("is-scoped-view-entering");
  rail?.classList.add("is-reel-rolling-in");
  window.setTimeout(() => {
    app.classList.remove("is-scoped-view-entering", "is-scoped-view-switching");
    rail?.classList.remove("is-reel-rolling-in");
  }, 560);
}

export async function playRailRefreshTransition(task) {
  const app = $("#app");
  const button = $("#refreshBtn");
  const isWorkspace = app?.classList.contains("is-workspace");
  const cinemaMotion = isWorkspace && state.overviewLayout === "cinema" && !prefersReducedMotion();
  const isPersonalRefresh = cinemaMotion && state.activeView === "review";
  let armedPersonalRefresh = false;
  button.disabled = true;
  button.classList.add("is-loading");
  try {
    if (isPersonalRefresh) {
      await retractScheduleFilmBeforeDateMove();
      state.animatePersonalDateRail = true;
      armedPersonalRefresh = true;
    }
    if (cinemaMotion) {
      document.querySelector(".object-rail")?.classList.add("is-reel-refreshing-out");
      await waitForMotion(180);
    }
    await task();
    armedPersonalRefresh = false;
    if (cinemaMotion) {
      const rail = document.querySelector(".object-rail");
      rail?.classList.remove("is-reel-refreshing-out");
      rail?.classList.add("is-reel-refreshing-in");
      requestRailCoverflow();
      await waitForMotion(540);
      rail?.classList.remove("is-reel-refreshing-in");
      if (isPersonalRefresh) requestAnimationFrame(alignPersonalScheduleToReel);
    }
    showToast(state.overviewLayout === "cinema" ? "胶卷已刷新" : "数据已刷新");
  } catch (error) {
    showToast(error.message || "刷新失败", "error");
  } finally {
    if (armedPersonalRefresh) state.animatePersonalDateRail = false;
    button.disabled = false;
    button.classList.remove("is-loading");
    document.querySelector(".object-rail")?.classList.remove("is-reel-refreshing-out", "is-reel-refreshing-in");
  }
}

export async function openView(view, { preserveBucket = false } = {}) {
  if (view === "maintain") {
    view = "relations";
    state.userMemoryFilter = "private";
    preserveBucket = true;
  }
  const app = $("#app");
  const wasWorkspace = app.classList.contains("is-workspace");
  const switchingWorkspaceView = wasWorkspace && state.activeView !== view;
  const scopedRailSwitch = switchingWorkspaceView && Boolean(scopedViewScope(state.activeView)) && Boolean(scopedViewScope(view));
  const enteringPersonalMemory = view === "review" && (!wasWorkspace || state.activeView !== "review");
  const token = ++asteriaWorkspaceState.workspaceTransitionToken;
  if (wasWorkspace && state.activeView === view) return;
  if (!wasWorkspace) {
    await playOverviewToWorkspace(view);
    if (token !== asteriaWorkspaceState.workspaceTransitionToken) return;
  } else if (scopedRailSwitch) {
    await playScopedRailSwitchOut();
    if (token !== asteriaWorkspaceState.workspaceTransitionToken) return;
  } else if (switchingWorkspaceView) {
    await playWorkspaceSwitchOut();
    if (token !== asteriaWorkspaceState.workspaceTransitionToken) return;
  }
  if (view !== "review") removeRailMountedScheduleFilm();
  state.personalEntranceRevealRequested = enteringPersonalMemory;
  state.activeView = view;
  syncNativeMemoryNavigation(view);
  if (view !== "review" && !preserveBucket) state.activeBucketId = "all";
  app.classList.add("is-workspace");
  app.classList.toggle("is-workspace-entering", !wasWorkspace);
  app.classList.remove("is-workspace-ready");
  if (!wasWorkspace) app.classList.remove("is-workspace-settled");
  app.classList.toggle("is-personal-memory", view === "review");
  app.dataset.workspaceView = view;
  $("#backHomeBtn").classList.remove("hidden");
  $$(".filmstrip").forEach((strip) => {
    strip.classList.toggle("is-locked", strip.dataset.view === view);
  });
  $$(".view").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `view-${view}`);
  });
  $("#workspaceTitle").textContent = VIEWS[view]?.title || "记忆面板";
  $("#workspaceHint").textContent = VIEWS[view]?.hint || "";
  renderScopedModeControls(view);
  if (view === "film") {
    renderScopedBucketRail("group");
  } else if (view === "relations" || view === "maintain") {
    renderScopedBucketRail("private");
  } else if (view !== "review") {
    renderSecondaryNav(view, !switchingWorkspaceView);
  }
  const loading = loadActiveView();
  requestRailCoverflow();
  await loading;
  if (!wasWorkspace) {
    app.offsetHeight;
    app.classList.add("is-workspace-ready", "is-workspace-settled");
  }
  if (scopedRailSwitch) {
    playScopedRailSwitchIn();
  } else if (switchingWorkspaceView) {
    playWorkspaceSwitchIn();
  }
  if (!wasWorkspace) {
    window.setTimeout(() => {
      app.classList.remove("is-overview-exiting", "is-workspace-wipe", "is-workspace-entering", "is-workspace-ready");
    }, prefersReducedMotion() ? 0 : WORKSPACE_WIPE_CLEANUP_MS);
  }
}

export async function returnHome() {
  const app = $("#app");
  if (!app.classList.contains("is-workspace") || asteriaWorkspaceState.homeReturnRunning) return;
  const cinemaMotion = state.overviewLayout === "cinema" && !prefersReducedMotion();
  asteriaWorkspaceState.homeReturnRunning = true;
  asteriaWorkspaceState.workspaceTransitionToken++;
  $("#backHomeBtn").disabled = true;
  if (cinemaMotion) {
    refreshTransitionFace();
    app.classList.add("is-home-wipe");
    await waitForMotion(HOME_WIPE_SWAP_WAIT_MS);
  }
  removeRailMountedScheduleFilm();
  app.classList.remove("is-workspace");
  app.classList.remove("is-personal-memory");
  app.classList.remove("is-conversation-import");
  app.classList.remove("is-workspace-entering", "is-workspace-ready", "is-workspace-settled");
  app.classList.remove("is-view-switching", "is-view-exiting", "is-view-entering");
  app.classList.remove("is-scoped-view-switching", "is-scoped-view-exiting", "is-scoped-view-entering");
  app.style.removeProperty("--secondary-nav-shift");
  delete app.dataset.workspaceView;
  syncNativeMemoryNavigation("overview");
  if (cinemaMotion) prepareOverviewStripReturn();
  $("#backHomeBtn").classList.add("hidden");
  $("#backHomeBtn").disabled = false;
  $$(".filmstrip").forEach((strip) => strip.classList.remove("is-locked"));
  requestRailCoverflow();
  if (cinemaMotion) {
    app.classList.add("is-overview-restoring");
    await waitForMotion(HOME_WIPE_TOTAL_WAIT_MS);
  }
  app.classList.remove("is-overview-restoring", "is-home-wipe");
  asteriaWorkspaceState.homeReturnRunning = false;
}

export async function loadActiveView() {
  try {
    if (state.activeView === "objects") {
      await loadContextPanel();
    } else if (state.activeView === "film") {
      await loadScopedMemories("#groupMemoryList", "group", "正在读取群聊记忆...", "还没有群聊范围内的记忆。");
    } else if (state.activeView === "microscope") {
      applyMicroscopeView();
    } else if (state.activeView === "relations") {
      await loadUserMemory();
    } else if (state.activeView === "review") {
      await loadPersonalMemory();
    } else if (state.activeView === "maintain") {
      await loadScopedMemories("#privateMemoryList", "private", "正在读取私聊记忆...", "还没有私聊范围内的记忆。");
    } else if (state.activeView === "archive") {
      await loadArchive();
    }
  } catch (error) {
    renderViewError(error);
    showToast(error.message || "读取失败", "error");
  }
}

export function renderViewError(error) {
  const targets = {
    objects: "#contextPanel",
    film: "#groupMemoryList",
    relations: "#relationList",
    review: "#personalMemoryList",
    maintain: "#privateMemoryList",
    archive: "#importResult",
  };
  const selector = targets[state.activeView];
  if (!selector) return;
  const target = $(selector);
  if (!target) return;
  if (target.hidden) target.hidden = false;
  target.innerHTML = panelError(error);
  const retry = target.querySelector("[data-retry-active]");
  if (retry) retry.addEventListener("click", () => loadActiveView());
}

export function memoryFieldLabel(field, value) {
  const labels = {
    memory_type: {conversation_summary: "对话摘要", explicit_memory: "明确记住", user_profile: "用户画像", user_preference: "偏好", relationship_claim: "关系信息", fact: "事实", event: "经历", core_memory: "核心记忆"},
    validity_status: {active: "有效", superseded: "已被替代", expired: "已过期", archived: "已归档", quarantined: "隔离待确认"},
    visibility: {private_pair: "私聊可见", group_public: "群聊可见", bot_self: "自我档案", internal: "内部", shareable: "可共享"},
    lifecycle: {stable_memory: "稳定记忆", raw_event: "原始事件", archived: "归档"},
    reality_level: {real: "现实", rp: "角色扮演", fictional: "虚构", uncertain: "待确认"},
    scope: {private: "私聊", group: "群聊", self: "角色自身", global: "全局"},
  };
  return labels[field]?.[value] || value || "未标记";
}

export function memorySourceSummary(memory) {
  const person = (item) => item?.name ? `${item.name}${item.id ? ` · ${item.id}` : ""}` : item?.id || "未标记";
  return `<section class="memory-source-summary" aria-label="来源与有效范围">
    <h4>来源与有效范围</h4>
    <dl>
      <div><dt>记录来源</dt><dd>${escapeHtml(memory.source_plugin || "未标记来源")}</dd></div>
      <div><dt>所属范围</dt><dd>${escapeHtml(memoryFieldLabel("scope", memory.scope))}${memory.group_id ? ` · ${escapeHtml(memory.group_id)}` : ""}</dd></div>
      <div><dt>主体</dt><dd>${escapeHtml(person(memory.subject))}</dd></div>
      <div><dt>关联对象</dt><dd>${escapeHtml(person(memory.object))}</dd></div>
      <div><dt>生效时间</dt><dd>${escapeHtml(memory.valid_from ? formatTime(memory.valid_from) : "未设置")}</dd></div>
      <div><dt>失效时间</dt><dd>${escapeHtml(memory.valid_to ? formatTime(memory.valid_to) : "未设置截止")}</dd></div>
      ${memory.import_batch_id ? `<div><dt>导入批次</dt><dd>${escapeHtml(memory.import_batch_id)}</dd></div>` : ""}
    </dl>
    <p class="item-meta">来源名称保留原记录，不表示该旧插件仍在运行。实际召回还取决于有效期、权限与当前会话。</p>
  </section>`;
}

export function memoryRow(memory) {
  const content = compact(memory.content, "(空内容)");
  const canonical = compact(memory.canonical_summary, "");
  const keyFacts = Array.isArray(memory.key_facts) ? memory.key_facts.filter(Boolean).slice(0, 2) : [];
  const evidence = compact(memory.evidence_preview, "");
  const previewParts = [];
  if (canonical && canonical !== content) previewParts.push(canonical);
  keyFacts.forEach((fact) => {
    if (fact && fact !== content && !previewParts.includes(fact)) previewParts.push(fact);
  });
  if (evidence && evidence !== content && !previewParts.includes(evidence)) previewParts.push(evidence);
  const preview = previewParts.join(" / ");
  const topicTags = Array.isArray(memory.topics) ? memory.topics.filter(Boolean).slice(0, 2) : [];
  return `
    <article class="row-item memory-frame" data-memory-id="${escapeHtml(memory.id)}">
      <div class="memory-frame-time">
        <b>${escapeHtml(formatTime(memory.occurred_at || memory.created_at))}</b>
        <span>${escapeHtml(shortId(memory.id))}</span>
      </div>
      <div class="memory-frame-main">
        <div class="memory-frame-text">
          <span class="item-title">${escapeHtml(content)}</span>
          ${preview ? `<p class="memory-preview">${escapeHtml(preview)}</p>` : ""}
        </div>
        <div class="badges">
          <span class="badge teal">${escapeHtml(memoryFieldLabel("memory_type", memory.memory_type))}</span>
          <span class="badge blue">${escapeHtml(memoryFieldLabel("visibility", memory.visibility))}</span>
          <span class="badge gold">${escapeHtml(memoryFieldLabel("reality_level", memory.reality_level))}</span>
          <span class="badge">${escapeHtml(memoryFieldLabel("validity_status", memory.validity_status))}</span>
          <span class="badge">来源 · ${escapeHtml(memory.source_plugin || "未标记")}</span>
          ${memorySignalBadges(memory, 3)}
          ${topicTags.map((tag) => `<span class="badge blue">${escapeHtml(tag)}</span>`).join("")}
        </div>
      </div>
    </article>
  `;
}

export async function loadMemories(extra = {}) {
  const query = $("#globalSearch").value.trim();
  const params = contextParams({ limit: extra.limit || 80, q: query, ...extra });
  const data = await apiGet(`/memories?${params.toString()}`);
  return data.memories || [];
}

export function scopedMemoryParams(scope, extra = {}) {
  const query = $("#globalSearch").value.trim();
  const params = new URLSearchParams();
  params.set("limit", String(extra.limit || 100));
  if (query) params.set("q", query);
  if (scope) params.set("scope", scope);
  Object.entries(extra).forEach(([key, value]) => {
    if (key !== "limit" && value !== undefined && value !== null && String(value).trim()) {
      params.set(key, String(value).trim());
    }
  });

  const bucket = activeBucket();
  if (!bucket || bucket.id === "all") return { params, incompatible: false };
  if (bucket.id === "self") return { params, incompatible: Boolean(scope) };
  if (scope && bucket.scope && bucket.scope !== scope) return { params, incompatible: true };

  if (bucket.scope) params.set("scope", bucket.scope);
  if (bucket.scope === "private") {
    if (bucket.target_id) params.set("entity_id", bucket.target_id);
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  } else if (bucket.scope === "group") {
    if (bucket.group_id) params.set("group_id", bucket.group_id);
    if (bucket.session_id) params.set("session_id", bucket.session_id);
  }
  return { params, incompatible: false };
}

export function renderMemoryList(selector, memories, emptyText, windowLimit = 120) {
  const target = $(selector);
  if (!target) return;
  target.className = "row-list memory-browser";
  let page = 0;
  const filter = {status: "", source: "", order: "recent"};
  const openMemory = async (id) => {
    await showMemory(id);
    if (state.activeMemoryId === id) $("#detailDrawer").scrollIntoView({block: "start"});
  };
  const sources = [...new Set(memories.map(item => item.source_plugin || ""))];
  const statuses = [...new Set(memories.map(item => item.validity_status || ""))];
  target.innerHTML = `<div class="memory-browser-tools">
    <p>当前范围最近最多 ${windowLimit} 条非待审核记录，本次分类 ${memories.length} 条。筛选、排序和分页仅作用于这批结果；查找更早内容请使用顶部搜索。</p>
    <div class="memory-browser-filters">
      <label>记录状态<select data-memory-filter="status"><option value="">全部状态</option>${statuses.filter(Boolean).map(value => memoryOption(value, memoryFieldLabel("validity_status", value), "")).join("")}</select></label>
      <label>来源<select data-memory-filter="source"><option value="">全部来源</option>${sources.filter(Boolean).map(value => memoryOption(value, value, "")).join("")}</select></label>
      <label>顺序<select data-memory-filter="order"><option value="recent">最近在前</option><option value="oldest">较早在前</option><option value="importance">重要度优先</option></select></label>
    </div>
    <p class="memory-browser-count" role="status"></p>
  </div><div class="memory-browser-rows"></div><nav class="memory-browser-pages" aria-label="本批记忆分页"></nav>`;
  const render = () => {
    let rows = memories.filter(item => (!filter.status || item.validity_status === filter.status) && (!filter.source || item.source_plugin === filter.source));
    if (filter.order === "oldest") rows.reverse();
    if (filter.order === "importance") rows.sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0));
    const pages = Math.max(1, Math.ceil(rows.length / MEMORY_PAGE_SIZE));
    page = Math.max(0, Math.min(page, pages - 1));
    target.querySelector(".memory-browser-count").textContent = `筛选后 ${rows.length} 条 · 第 ${page + 1} / ${pages} 页`;
    const list = target.querySelector(".memory-browser-rows");
    list.innerHTML = rows.length ? rows.slice(page * MEMORY_PAGE_SIZE, (page + 1) * MEMORY_PAGE_SIZE).map(memoryRow).join("") : `<div class="empty-state">${escapeHtml(memories.length ? "当前筛选没有匹配记录，可调整状态或来源。" : emptyText)}</div>`;
    list.querySelectorAll("[data-memory-id]").forEach(row => { row.tabIndex = 0; row.setAttribute("role", "button"); row.setAttribute("aria-label", `查看记忆 ${row.textContent.trim()}`); });
    target.querySelector(".memory-browser-pages").innerHTML = `<button type="button" data-memory-page="previous"${page === 0 ? " disabled" : ""}>上一页</button><span>${page + 1} / ${pages}</span><button type="button" data-memory-page="next"${page + 1 >= pages ? " disabled" : ""}>下一页</button>`;
  };
  target.onchange = (event) => {
    const name = event.target.dataset.memoryFilter;
    if (!Object.prototype.hasOwnProperty.call(filter, name)) return;
    filter[name] = event.target.value; page = 0; render();
  };
  target.onclick = (event) => {
    const button = event.target.closest("[data-memory-page]");
    if (button && target.contains(button)) { page += button.dataset.memoryPage === "next" ? 1 : -1; render(); target.querySelector(".memory-browser-count").scrollIntoView({block: "nearest"}); return; }
    const row = event.target.closest("[data-memory-id]");
    if (row && target.contains(row)) openMemory(row.dataset.memoryId);
  };
  target.onkeydown = (event) => {
    if (!["Enter", " "].includes(event.key) || !event.target.matches("[data-memory-id]")) return;
    event.preventDefault(); openMemory(event.target.dataset.memoryId);
  };
  render();
}

export function relationTypesForSecondary() {
  const active = state.userMemoryFilter || "all";
  const map = {
    profile: ["user_profile"],
    preference: ["user_preference"],
    relationship: ["relationship_claim"],
    explicit: ["explicit_memory"],
  };
  return map[active] || [];
}

export function syncUserMemoryFilterControls() {
  $$('[data-user-memory-filter]').forEach((button) => {
    if (!button.closest('#view-relations')) return;
    const active = button.dataset.userMemoryFilter === state.userMemoryFilter;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

export async function selectUserMemoryFilter(filter) {
  const allowed = new Set(['all', 'profile', 'preference', 'relationship', 'explicit', 'private']);
  state.userMemoryFilter = allowed.has(filter) ? filter : 'all';
  syncUserMemoryFilterControls();
  if (state.activeView === 'relations') await loadUserMemory();
}

export async function loadScopedMemories(selector, scope, loadingText, emptyText, extra = {}) {
  const target = $(selector);
  if (!target) return;
  target.className = "row-list";
  target.innerHTML = loadingState(loadingText);
  const { params, incompatible } = scopedMemoryParams(scope, { limit: 120, ...extra });
  if (incompatible) {
    const label = scope === "group" ? "群聊" : "私聊";
    target.innerHTML = `<div class="empty-state">当前观察对象不属于${escapeHtml(label)}范围。请选择${escapeHtml(label)}对象或切回全部。</div>`;
    return;
  }
  const data = await apiGet(`/memories?${params.toString()}`);
  renderMemoryList(selector, data.memories || [], emptyText);
}

export function hasMemoryType(memory, types) {
  return types.includes(memory.memory_type);
}

export function isUserMemory(memory) {
  return hasMemoryType(memory, ["user_profile", "user_preference", "explicit_memory", "relationship_claim"]);
}

export function isPersonalMemory(memory) {
  return memory.visibility === "bot_self"
    && (
      hasMemoryType(memory, [
        "schedule_fragment",
        "persona_life",
        "self_action",
        "proactive_message",
        "search_action",
        "creative_work",
        "image_action",
        "qzone_action",
        "reading_memory",
      ])
      || memory.source_plugin === "private_companion"
      || (memory.tags || []).includes("schedule")
      || (memory.tags || []).includes("persona_life")
      || (memory.tags || []).includes("qzone")
      || (memory.tags || []).includes("qzone_publish")
    );
}
