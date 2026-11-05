/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {clearDetail,displayMemoryMetadata,loadConversationImportView,memoryOption,renderMemoryRevisions,renderMemoryStructuredMetadata,saveMemoryManagement,showInlineConfirmation} from './editors.js';
import {contextField,contextSwitch,providerStateLabel,retrievalModeLabel} from './knowledge.js';
import {loadMemoryAuditOwners,refreshAll} from './maintenance.js';
import {memoryFieldLabel,memorySourceSummary} from './memory.js';
import {clearMicroscopeResults,contextPayload,microscopeBucket,microscopeBucketLabel,renderMicroscopeContexts,selectSecondaryNav,setMicroscopeSearchBusy} from './overview.js';
import {loadCoreMemoryBlocks} from './personal.js';
import {$,$$,CONFIG_ADVANCED_MODULES,CONFIG_MODULE_GUIDES,TRANSPARENT_IMAGE,state} from './state.js';
import {loadAclTopology} from './topology.js';
import {activeSecondaryNav,applyTheme,escapeHtml,formatTime,isNumericOnlyContent,loadingState,memorySignalBadges,panelError,percentLabel,shortId,showToast,withButton} from './workspace.js';

export function renderAlbumCard(item, index = 0, active = false) {
  const title = item.title || "照片";
  const meta = [item.generated_at, item.backend].filter(Boolean).join(" · ");
  const image = item.exists && (item.image_data_url || item.url)
    ? albumImageTag(item, title)
    : `<div class="album-missing">${escapeHtml(item.error || "图片文件不可用")}</div>`;
  return `
    <article class="album-card${active ? " is-active" : ""}" style="--album-i:${escapeHtml(index)}" data-album-index="${escapeHtml(index)}" role="button" tabindex="0">
      <div class="album-image">${image}</div>
      <div class="album-caption">
        <b>${escapeHtml(title)}</b>
        ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
        ${item.note ? `<small>${escapeHtml(item.note)}</small>` : ""}
      </div>
    </article>
  `;
}

export function albumImageTag(item, title) {
  const source = item?.image_data_url || item?.url || "";
  if (!source) return `<div class="album-missing">图片文件不可用</div>`;
  return `<img src="${TRANSPARENT_IMAGE}" data-album-image-src="${escapeHtml(source)}" alt="${escapeHtml(title)}" loading="lazy">`;
}

export function albumImageDataPath(source) {
  const raw = String(source || "");
  if (!raw || raw.startsWith("data:")) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.pathname.endsWith("/companion/personal-photo-data")) {
      return `/companion/personal-photo-data${url.search}`;
    }
    if (url.pathname.endsWith("/companion/personal-photo")) {
      return `/companion/personal-photo-data${url.search}`;
    }
  } catch (error) {
    const dataMarker = "/companion/personal-photo-data?";
    const photoMarker = "/companion/personal-photo?";
    const dataIndex = raw.indexOf(dataMarker);
    if (dataIndex >= 0) return `/companion/personal-photo-data?${raw.slice(dataIndex + dataMarker.length)}`;
    const photoIndex = raw.indexOf(photoMarker);
    if (photoIndex >= 0) return `/companion/personal-photo-data?${raw.slice(photoIndex + photoMarker.length)}`;
  }
  return raw;
}

export async function hydratePersonalAlbumImages(root = document) {
  const images = [...root.querySelectorAll("img[data-album-image-src]")];
  await Promise.all(images.map(async (img) => {
    if (img.dataset.loaded === "1" || img.dataset.loading === "1") return;
    const source = img.dataset.albumImageSrc || "";
    if (!source) return;
    img.dataset.loading = "1";
    const endpoint = albumImageDataPath(source);
    try {
      if (endpoint.startsWith("data:")) {
        img.src = endpoint;
      } else if (endpoint.startsWith("/companion/personal-photo-data")) {
        const result = await apiGet(endpoint);
        if (!result?.data_url) throw new Error("图片数据为空");
        img.src = result.data_url;
      } else {
        img.src = source;
      }
      img.dataset.loaded = "1";
    } catch (error) {
      img.dataset.loaded = "0";
      const fallback = document.createElement("div");
      fallback.className = "album-missing";
      fallback.textContent = "图片加载失败";
      img.replaceWith(fallback);
    } finally {
      img.dataset.loading = "0";
    }
  }));
}

export function activeAlbumIndex(album) {
  if (!album.length) {
    state.selectedPersonalAlbumIndex = "";
    return "";
  }
  const current = String(state.selectedPersonalAlbumIndex || "");
  if (current && album[Number(current)]) return current;
  state.selectedPersonalAlbumIndex = "0";
  return "0";
}

export function renderCompanionSchedulePanel(snapshot, status) {
  const plan = snapshot.plan || {};
  const items = Array.isArray(plan.items) ? plan.items : [];
  const visualItems = items.map((item, index) => ({ item, index })).reverse();
  const activeIndex = activeScheduleIndex(items);
  const active = selectedScheduleItem(items, activeIndex);
  return `
    <section class="personal-zone companion-overview">
      <div class="personal-zone-head">
        <h4>${state.overviewLayout === "cinema" ? "时间胶片" : "日程时间表"}</h4>
        <span>${escapeHtml(snapshot.bot_name || "Bot")} · ${escapeHtml(plan.date || status.selected_date || "-")}</span>
      </div>
      <div class="schedule-summary" data-schedule-summary>
        ${renderScheduleSummary(active.item, items, active.index)}
      </div>
      <div class="schedule-film" data-schedule-film>
        <div class="schedule-film-track" data-schedule-track>
        ${visualItems.length ? visualItems.map(({ item, index }) => {
          const itemIndex = scheduleIndex(item, index);
          return `
          <button class="schedule-frame${itemIndex === activeIndex ? " is-active" : ""}" data-schedule-index="${escapeHtml(itemIndex)}" type="button">
            <span>${escapeHtml(scheduleRange(items, index))}</span>
          </button>
        `}).join("") : `<div class="empty-state">这一天没有日程。</div>`}
        </div>
        <div class="schedule-marker" aria-hidden="true"></div>
      </div>
    </section>
  `;
}

export function updateScheduleSummary(target, snapshot, options = {}) {
  const summary = target.querySelector("[data-schedule-summary]");
  if (!summary) return;
  const plan = snapshot.plan || {};
  const items = Array.isArray(plan.items) ? plan.items : [];
  const active = selectedScheduleItem(items, activeScheduleIndex(items));
  const render = () => {
    summary.innerHTML = renderScheduleSummary(active.item, items, active.index);
  };
  if (options.animate) {
    swapPanelContent(summary, render);
  } else {
    render();
  }
}

export function swapPanelContent(element, render) {
  if (!element) return;
  window.clearTimeout(element._swapTimer);
  window.clearTimeout(element._swapDoneTimer);
  element.classList.add("is-switching");
  element._swapTimer = window.setTimeout(() => {
    render();
    element.classList.add("is-switching");
    element.offsetHeight;
    requestAnimationFrame(() => {
      element.classList.remove("is-switching");
      element.classList.add("is-switch-settling");
      element._swapDoneTimer = window.setTimeout(() => {
        element.classList.remove("is-switch-settling");
      }, 220);
    });
  }, 120);
}

export function selectedScheduleItem(items, selectedIndex) {
  const index = items.findIndex((item, fallback) => scheduleIndex(item, fallback) === String(selectedIndex));
  return {
    item: index >= 0 ? items[index] : null,
    index,
  };
}

export function renderScheduleSummary(item, items, index) {
  if (!item) {
    return `<b>未选择时段</b><span>${state.overviewLayout === "cinema" ? "拖动胶片" : "点击时间段"}选择一段日程。</span>`;
  }
  const range = index >= 0 ? scheduleRange(items, index) : (item.time || "");
  const meta = [item.mood, item.message_seed].filter(Boolean).join(" · ");
  return `
    <b>${escapeHtml(range)}</b>
    <span>${escapeHtml(item.activity || "未命名日程")}</span>
    ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
  `;
}

export function scheduleIndex(item, fallback) {
  const value = item?.index;
  if (value !== undefined && value !== null && String(value) !== "") return String(value);
  return String(fallback);
}

export function activeScheduleIndex(items) {
  if (!items.length) return "";
  const available = items.map((item, index) => scheduleIndex(item, index));
  if (available.includes(String(state.selectedScheduleIndex))) return String(state.selectedScheduleIndex);
  state.selectedScheduleIndex = available[0] || "";
  return state.selectedScheduleIndex;
}

export function firstMinute(value) {
  const match = String(value || "").match(/(\d{1,2}):(\d{2})/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isFinite(hour) || !Number.isFinite(minute)) return null;
  return hour * 60 + minute;
}

export function scheduleWindowForIndex(items, selectedIndex) {
  const index = items.findIndex((candidate, fallback) => scheduleIndex(candidate, fallback) === String(selectedIndex));
  const item = index >= 0 ? items[index] : null;
  const start = firstMinute(item?.time);
  const end = firstMinute(items[index + 1]?.time);
  return { start, end };
}

export function detailMatchesSchedule(detail, item, selectedIndex, window = {}) {
  if (!detail || !item || !selectedIndex) return false;
  const index = String(selectedIndex);
  const key = String(detail.key || "");
  const time = String(item.time || "");
  const detailStart = firstMinute(detail.time || key);
  return String(detail.index) === index
    || (
      window.start !== null
      && detailStart !== null
      && detailStart >= window.start
      && (window.end === null || detailStart < window.end)
    )
    || key.includes(`:${index}:`)
    || Boolean(time && (key.includes(`:${time}`) || String(detail.time || "").startsWith(time)));
}

export function detailsForSchedule(details, item, selectedIndex, items = []) {
  if (!item || !selectedIndex || !Array.isArray(details)) return [];
  const window = scheduleWindowForIndex(items, selectedIndex);
  const matched = details
    .filter((detail) => detailMatchesSchedule(detail, item, selectedIndex, window))
    .sort((a, b) => (firstMinute(a?.time || a?.key) ?? 99999) - (firstMinute(b?.time || b?.key) ?? 99999));
  if (matched.length) return matched;
  const fallback = details.find((detail) => String(detail.index) === String(selectedIndex))
    || details.find((detail) => String(detail.key || "").includes(`:${selectedIndex}:`))
    || details.find((detail) => item.time && String(detail.key || "").includes(`:${item.time}`));
  return fallback ? [fallback] : [];
}

export function scheduleRange(items, index) {
  const item = items[index] || {};
  const start = item.time || "--:--";
  const next = items[index + 1]?.time || "";
  return next ? `${start} - ${next}` : `${start} 后`;
}

export function showPersonalScheduleDetail(snapshot, status, options = {}) {
  if (state.activeView !== "review") return;
  const plan = snapshot.plan || {};
  const items = Array.isArray(plan.items) ? plan.items : [];
  const details = Array.isArray(snapshot.details) ? snapshot.details : [];
  const selectedIndex = activeScheduleIndex(items);
  const selectedItem = items.find((item, index) => scheduleIndex(item, index) === selectedIndex) || null;
  const selectedDetails = detailsForSchedule(details, selectedItem, selectedIndex, items);
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selectedItem ? "detail-drawer is-schedule-detail" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderSelectedDetail(selectedItem, selectedDetails, items)}</div>`;
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

export function renderSelectedDetail(item, details, items) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>选择日程段</b>
        <span>点击上方日程表里的时间段，在这里查看对应细化。</span>
      </div>
    `;
  }
  const selectedDetails = Array.isArray(details) ? details.filter(Boolean) : (details ? [details] : []);
  if (!selectedDetails.length) {
    return `
      <div class="empty-state">这个时间段还没有细化。</div>
    `;
  }
  return `
    <article class="selected-detail">
      ${selectedDetails.length > 1 ? `<span class="detail-count">${escapeHtml(selectedDetails.length)} 条细化</span>` : ""}
      <div class="detail-segment-list">
        ${selectedDetails.map((detail) => renderDetailSegment(detail)).join("")}
      </div>
    </article>
  `;
}

export function renderDetailSegment(detail) {
  const detailTime = detail?.time ? detail.time : "";
  return `
    <section class="detail-segment">
      ${detailTime ? `<span class="detail-time">${escapeHtml(detailTime)}</span>` : ""}
      ${detail.summary ? `<b class="detail-summary">${escapeHtml(detail.summary)}</b>` : ""}
      ${renderDetailLines(detail)}
    </section>
  `;
}

export function renderSubjectiveMemories(snapshot, options = {}) {
  const memories = Array.isArray(snapshot.subjective_memories) ? snapshot.subjective_memories : [];
  const selected = options.selectable ? activeSubjectiveIndex(memories) : "";
  if (!memories.length) {
    return `
      <article class="subjective-memory empty-subjective">
        <b>主观记忆</b>
        <span>这一天还没有 Bot 日记或主观片段。</span>
      </article>
    `;
  }
  return `
    <section class="subjective-memory">
      <div class="subjective-head">
        <b>主观记忆</b>
        <span>${escapeHtml(memories[0].date || "")}</span>
      </div>
      ${memories.map((item, index) => `
        <article class="subjective-card${options.selectable && String(index) === selected ? " is-active" : ""}"${options.selectable ? ` data-subjective-index="${escapeHtml(index)}" role="button" tabindex="0"` : ""}>
          ${item.summary ? `<b>${escapeHtml(item.summary)}</b>` : ""}
          ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ""}
          ${item.share_seed ? `<small>${escapeHtml(item.share_seed)}</small>` : ""}
          ${renderSubjectiveTags(item.tags)}
          ${renderSubjectiveLines(item)}
        </article>
      `).join("")}
    </section>
  `;
}

export function renderSubjectiveMemoryPanel(snapshot, status) {
  const date = status.selected_date || snapshot.plan?.date || "";
  return `
    <section class="personal-zone subjective-memory-panel">
      <div class="personal-zone-head">
        <h4>主观记忆</h4>
        <span>${escapeHtml(date || "-")} · Bot 日记</span>
      </div>
      ${renderSubjectiveMemories(snapshot, { selectable: true })}
    </section>
  `;
}

export function activeSubjectiveIndex(memories) {
  if (!memories.length) {
    state.selectedSubjectiveMemoryIndex = "";
    return "";
  }
  const current = String(state.selectedSubjectiveMemoryIndex || "");
  if (current && memories[Number(current)]) return current;
  state.selectedSubjectiveMemoryIndex = "0";
  return "0";
}

export function showPersonalAlbumDetail(snapshot, status, options = {}) {
  if (state.activeView !== "review") return;
  const album = Array.isArray(snapshot.album) ? snapshot.album : [];
  const selectedIndex = activeAlbumIndex(album);
  const selected = album[Number(selectedIndex)] || null;
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selected ? "detail-drawer is-album-detail" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderAlbumDetail(selected, status)}</div>`;
    requestAnimationFrame(() => hydratePersonalAlbumImages(drawer));
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

export function renderAlbumDetail(item, status) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>相册为空</b>
        <span>${escapeHtml(status.selected_date || "这一天")} 还没有照片。</span>
      </div>
    `;
  }
  const title = item.title || "照片";
  const meta = [item.generated_at, item.backend].filter(Boolean).join(" · ");
  const image = item.exists && (item.image_data_url || item.url)
    ? albumImageTag(item, title)
    : `<div class="album-missing">${escapeHtml(item.error || "图片文件不可用")}</div>`;
  return `
    <article class="album-detail">
      <div class="album-detail-image">${image}</div>
      <div class="album-detail-copy">
        <b>${escapeHtml(title)}</b>
        ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
        ${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}
      </div>
    </article>
  `;
}

export function showPersonalSubjectiveDetail(snapshot, status, options = {}) {
  if (state.activeView !== "review") return;
  const memories = Array.isArray(snapshot.subjective_memories) ? snapshot.subjective_memories : [];
  const selectedIndex = activeSubjectiveIndex(memories);
  const selected = memories[Number(selectedIndex)] || null;
  const drawer = $("#detailDrawer");
  const render = () => {
    drawer.className = selected ? "detail-drawer" : "detail-drawer empty";
    drawer.innerHTML = `<div class="personal-detail-content">${renderSubjectiveDetail(selected, status)}</div>`;
  };
  if (options.animate) {
    swapPanelContent(drawer, render);
  } else {
    render();
  }
}

export function showPersonalActionsDetail(status) {
  if (state.activeView !== "review") return;
  const actions = Array.isArray(status.actions) ? status.actions : [];
  const drawer = $("#detailDrawer");
  drawer.className = "detail-drawer empty";
  drawer.innerHTML = `
    <div class="detail-empty">
      <b>${actions.length ? "选择一条行动" : "行动记忆为空"}</b>
      <span>${actions.length ? "点击左侧行动卡片查看完整记录、标签和元数据。" : `${status.selected_date || "这一天"} 还没有 Bot 行动记忆。`}</span>
    </div>
  `;
}

export function renderSubjectiveDetail(item, status) {
  if (!item) {
    return `
      <div class="detail-empty">
        <b>主观记忆为空</b>
        <span>${escapeHtml(status.selected_date || "这一天")} 还没有 Bot 日记或主观片段。</span>
      </div>
    `;
  }
  return `
    <article class="selected-detail subjective-detail">
      ${item.date ? `<span class="detail-time">${escapeHtml(item.date)}</span>` : ""}
      ${item.summary ? `<b class="detail-summary">${escapeHtml(item.summary)}</b>` : ""}
      ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ""}
      ${item.share_seed ? `<small>${escapeHtml(item.share_seed)}</small>` : ""}
      ${renderSubjectiveTags(item.tags)}
      ${renderSubjectiveLines(item)}
    </article>
  `;
}

export function renderSubjectiveTags(tags) {
  if (!Array.isArray(tags) || !tags.length) return "";
  return `<div class="subjective-tags">${tags.slice(0, 6).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>`;
}

export function renderSubjectiveLines(item) {
  const lines = [
    ...(item.today_events || []),
    ...(item.proactive_events || []),
    ...(item.long_term_events || []),
  ].slice(0, 5);
  if (!lines.length) return "";
  return `<ul class="detail-lines subjective-lines">${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
}

export function renderDetailLines(item) {
  const lines = [
    ...(item.today_events || []),
    ...(item.proactive_events || []),
    ...(item.state_variables || []),
  ];
  if (!lines.length) return "";
  return `<ul class="detail-lines">${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
}

export function applyMicroscopeView() {
  const active = activeSecondaryNav("microscope");
  const box = $("#view-microscope .microscope-box");
  const result = $("#searchResult");
  if (!box || !result) return;
  renderMicroscopeContexts();
  box.classList.toggle("hidden", active !== "query");
  result.dataset.microscopeSection = active;
  if (!result.innerHTML.trim()) {
    clearMicroscopeResults(
      active === "query" ? "选择范围并输入内容后开始检索。" : "先在“召回测试”里运行一次检索。",
    );
  }
}

export async function runSearch() {
  const query = $("#searchQuery").value.trim();
  const resultHost = $("#searchResult");
  if (!resultHost) return;
  if (!query) {
    clearMicroscopeResults("先输入一句要测试的话。");
    return;
  }
  const requestedBucket = microscopeBucket();
  const requestedLabel = microscopeBucketLabel(requestedBucket);
  const searchToken = ++state.microscopeSearchToken;
  setMicroscopeSearchBusy(true);
  resultHost.setAttribute("aria-busy", "true");
  resultHost.innerHTML = loadingState("正在模拟召回...");
  try {
    const data = await apiPost("/search", contextPayload(query, requestedBucket));
    if (searchToken !== state.microscopeSearchToken) return;
    const results = data.results || [];
    const blocked = data.blocked || [];
    const returnedContext = data.search_context || {};
    const retrieval = data.retrieval || {};
    const slotCounts = retrieval.slot_counts || {};
    const slotLimits = retrieval.slot_limits || {};
    const cappedSlots = new Set(retrieval.capped_slots || []);
    const slotLabels = {
      open_loop: "未完成事项",
      self_timeline: "日程 / 行动",
      user_profile: "用户事实",
      current_window: "当前窗口",
      conversation_summary: "对话总结",
      stable_memory: "稳定记忆",
    };
    const slotOrder = [
      "open_loop",
      "self_timeline",
      "user_profile",
      "current_window",
      "conversation_summary",
      "stable_memory",
    ];
    const slotParts = retrieval.orchestration_enabled
      ? slotOrder
        .filter((slot) => Object.prototype.hasOwnProperty.call(slotLimits, slot))
        .map((slot) => ({
          slot,
          label: slotLabels[slot] || slot,
          count: Number(slotCounts[slot] || 0),
          limit: Number(slotLimits[slot] || 0),
          capped: cappedSlots.has(slot),
        }))
      : [];
    const contextLabel = returnedContext.mode === "all" ? "全部可检索记忆" : requestedLabel;
    const contextKind = returnedContext.mode === "all" ? "管理检索" : "会话模拟";
    resultHost.innerHTML = `
      <div class="microscope-result-context">
        <span><b>${escapeHtml(contextLabel)}</b><small>${escapeHtml(contextKind)}</small></span>
        <em>${escapeHtml(results.length)} 命中 · ${escapeHtml(blocked.length)} 过滤</em>
      </div>
      ${slotParts.length ? `
        <div class="microscope-slot-summary" aria-label="召回分槽">
          ${slotParts.map((item) => {
            const flexible = !item.capped && item.limit > 0;
            const budgetText = `${item.count}/${item.limit}${flexible ? "+" : ""}`;
            const detail = item.capped
              ? `${item.label}：${item.count} 条，当前按 ${item.limit} 条封顶`
              : `${item.label}：${item.count} 条，基础预算 ${item.limit} 条，可按相关性补位`;
            return `
            <span class="${item.count ? "is-hit" : ""} ${flexible ? "is-flexible" : "is-capped"}" title="${escapeHtml(detail)}" aria-label="${escapeHtml(detail)}">
              <b>${escapeHtml(item.label)}</b>
              <em>${escapeHtml(budgetText)}</em>
            </span>
          `}).join("")}
        </div>
      ` : ""}
      <section class="result-section film-panel" data-result-section="hits">
        <div class="personal-zone-head">
          <h4>命中记忆</h4>
          <span>${escapeHtml(results.length)} Hits</span>
        </div>
        ${results.length ? results.map((item) => `
          <article class="search-card" data-memory-id="${escapeHtml(item.id)}">
            <span class="item-title">${escapeHtml(item.content)}</span>
            <div class="item-meta">score ${escapeHtml(item.score)} · ${escapeHtml(item.reason || "")}</div>
            <div class="badges">
              <span class="badge teal">${escapeHtml(item.memory_type)}</span>
              <span class="badge blue">${escapeHtml(item.visibility)}</span>
              ${memorySignalBadges(item, 4)}
            </div>
          </article>
        `).join("") : `<div class="empty-state">没有命中可读取记忆。</div>`}
      </section>
      <section class="result-section film-panel" data-result-section="blocked">
        <div class="personal-zone-head">
          <h4>过滤原因</h4>
          <span>${escapeHtml(blocked.length)} Blocked</span>
        </div>
        ${blocked.length ? blocked.map((item) => `
          <article class="search-card">
            <span class="item-title">${escapeHtml(item.memory_id || item.id || "blocked")}</span>
            <div class="item-meta">${escapeHtml(item.reason || JSON.stringify(item))}</div>
          </article>
        `).join("") : `<div class="empty-state">没有过滤记录。</div>`}
      </section>
    `;
    $$("#searchResult [data-memory-id]").forEach((card) => {
      card.addEventListener("click", () => showMemory(card.dataset.memoryId));
    });
    applyMicroscopeView();
  } catch (error) {
    if (searchToken !== state.microscopeSearchToken) return;
    resultHost.innerHTML = `<div class="empty-state">检索失败：${escapeHtml(error.message || "未知错误")}。输入内容仍已保留，可直接重试。</div>`;
    showToast(error.message || "检索失败", "error");
  } finally {
    if (searchToken === state.microscopeSearchToken) {
      resultHost.setAttribute("aria-busy", "false");
      setMicroscopeSearchBusy(false);
    }
  }
}

export async function loadArchive() {
  const section = activeSecondaryNav("archive");
  setArchiveSection(section);
  if (section.startsWith("config:")) {
    const module = section.slice("config:".length);
    $("#selfMemoryList").innerHTML = loadingState("正在读取模块配置...");
    const data = await apiGet("/config/schema");
    $("#selfMemoryList").innerHTML = renderSchemaConfigModule(data, module);
    bindSchemaConfigForm($("#selfMemoryList"), data);
    return;
  }
  if (section === "topology") {
    await loadAclTopology();
    return;
  }
  if (section === "conversation-import") {
    await loadConversationImportView();
    return;
  }
  if (section === "core-memory") {
    await loadCoreMemoryBlocks();
    return;
  }
  if (section === "maintenance") {
    await loadMemoryAuditOwners();
    return;
  }
  if (section !== "retrieval") return;
  $("#selfMemoryList").innerHTML = loadingState("正在读取检索配置...");
  const config = await apiGet("/context/config");
  $("#selfMemoryList").innerHTML = renderArchiveConfig(config);
  bindRetrievalConfigForm($("#selfMemoryList"));
}

export function bindArchiveJumpButtons(root = document) {
  root.querySelectorAll("[data-archive-jump]").forEach((button) => {
    button.addEventListener("click", () => selectSecondaryNav(button.dataset.archiveJump));
  });
}

export function setArchiveSection(section) {
  const visibleSection = section.startsWith("config:") ? "retrieval" : section;
  $("#app")?.classList.toggle("is-conversation-import", visibleSection === "conversation-import");
  $$("#view-archive [data-archive-section]").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.archiveSection === visibleSection);
  });
  const result = $("#importResult");
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
}

export function renderArchiveConfig(config) {
  const retrieval = config.retrieval || {};
  const rerankOptions = Array.isArray(config.rerank_provider_options) ? config.rerank_provider_options : [];
  const embeddingOptions = Array.isArray(config.embedding_provider_options) ? config.embedding_provider_options : [];
  return renderRetrievalConfigForm(retrieval, rerankOptions, embeddingOptions);
}

export function renderSchemaConfigModule(data = {}, module = "") {
  const schema = data.schema?.[module];
  const values = data.values?.[module] || {};
  if (!schema?.items) {
    return `<div class="empty-state error-state"><b>配置模块不存在</b><span>${escapeHtml(module || "unknown")}</span></div>`;
  }
  const advancedModule = CONFIG_ADVANCED_MODULES[module] || "";
  const advancedSchema = advancedModule ? data.schema?.[advancedModule] : null;
  const advancedValues = advancedModule ? (data.values?.[advancedModule] || {}) : {};
  const fields = Object.entries(schema.items)
    .map(([key, item]) => renderSchemaConfigField(module, key, item || {}, values[key], data))
    .join("");
  const advancedFields = advancedSchema?.items
    ? Object.entries(advancedSchema.items)
      .map(([key, item]) => renderSchemaConfigField(advancedModule, key, item || {}, advancedValues[key], data))
      .join("")
    : "";
  return `
    <form class="context-form schema-config-form" data-config-module="${escapeHtml(module)}" data-config-advanced-module="${escapeHtml(advancedFields ? advancedModule : "")}" autocomplete="off">
      <section class="context-form-section">
        <div class="context-form-section-head">
          <b>${escapeHtml(schema.description || module)}</b>
          <span>${escapeHtml(schema.hint || "沿原配置定义显示，保存到当前 TLS 原生记忆配置。")}</span>
        </div>
        ${renderConfigInlineGuide(module)}
        ${fields}
      </section>
      ${advancedFields ? `
        <details class="context-advanced">
          <summary>${escapeHtml(advancedSchema.description || "高级参数")}</summary>
          <div class="context-advanced-note">${escapeHtml(advancedSchema.hint || "日常使用可保持默认。")}</div>
          ${advancedFields}
        </details>
      ` : ""}
      <div class="context-form-actions">
        <span>${advancedFields ? "普通参数与高级参数分别保存。若后一步失败，前一步不会自动回滚。" : "只提交当前模块，沿原配置来源保存。"} 输入仅保留在当前页面，切换或刷新前请确认结果。</span>
        <button type="submit">保存${escapeHtml(schema.description || "配置")}</button>
      </div>
      <section class="config-save-result" data-config-save-result aria-live="polite" hidden></section>
    </form>
  `;
}

export function renderConfigInlineGuide(module) {
  const guide = CONFIG_MODULE_GUIDES[module];
  if (!guide) return "";
  return `
    <div class="config-inline-guide">
      <dl>
        <div><dt>作用</dt><dd>${escapeHtml(guide.purpose)}</dd></div>
        <div><dt>什么时候调</dt><dd>${escapeHtml(guide.tune)}</dd></div>
        <div><dt>注意点</dt><dd>${escapeHtml(guide.avoid)}</dd></div>
      </dl>
    </div>
  `;
}

export function renderSchemaConfigField(module, key, item = {}, value, data = {}) {
  const type = item.type || "string";
  const label = item.description || key;
  const hint = item.hint || `${module}.${key}`;
  const current = value ?? item.default ?? "";
  let control = "";
  if (type === "bool") {
    control = contextSwitch(key, Boolean(current));
  } else if (type === "int") {
    control = `<input name="${escapeHtml(key)}" type="number" step="1" value="${escapeHtml(current)}" />`;
  } else if (type === "float") {
    control = `<input name="${escapeHtml(key)}" type="number" step="0.01" value="${escapeHtml(current)}" />`;
  } else if (Array.isArray(item.options) && item.options.length) {
    control = `
      <select name="${escapeHtml(key)}">
        ${item.options.map((option) => `<option value="${escapeHtml(option)}"${String(option) === String(current) ? " selected" : ""}>${escapeHtml(option)}</option>`).join("")}
      </select>
    `;
  } else if (item._special === "select_provider") {
    const options = Array.isArray(data.provider_options) ? [...data.provider_options] : [];
    if (current && !options.some((option) => option.id === current)) {
      options.push({ id: current, label: `${current}（当前配置）` });
    }
    const providerPlaceholder = key === "private_provider_id" || key === "group_provider_id"
      ? "留空沿用通用总结模型"
      : key === "private_fallback_provider_id" || key === "group_fallback_provider_id"
        ? "留空沿用通用备用模型"
        : "留空使用当前会话模型";
    control = `
      <div class="provider-inline retrieval-provider-picker">
        <select data-config-provider-select="${escapeHtml(key)}">
          ${options.map((option) => `<option value="${escapeHtml(option.id || "")}"${String(option.id || "") === String(current || "") ? " selected" : ""}>${escapeHtml(option.label || option.id || "不指定")}</option>`).join("")}
        </select>
        <input name="${escapeHtml(key)}" type="text" value="${escapeHtml(current)}" placeholder="${providerPlaceholder}" />
      </div>
    `;
  } else {
    control = `<input name="${escapeHtml(key)}" type="text" value="${escapeHtml(current)}" />`;
  }
  return contextField({ label, hint, control, wide: type === "string" && !Array.isArray(item.options) });
}

export function bindSchemaConfigForm(root, schemaData = {}) {
  const form = root.querySelector(".schema-config-form");
  if (!form) return;
  form.querySelectorAll("[data-config-provider-select]").forEach((select) => {
    const input = form.querySelector(`[name='${select.dataset.configProviderSelect}']`);
    bindProviderPicker(select, input);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (form._configSaveReceipt?.busy || form._configSaveReceipt?.steps.some(step => step.status === "unknown")) return;
    await withButton(form.querySelector("button[type='submit']"), "保存中", () => saveSchemaConfigModule(form, schemaData));
    // The shared button helper restores its original state; an unconfirmed write stays blocked here.
    if (form._configSaveReceipt?.steps.some(step => step.status === "unknown")) {
      const button = form.querySelector("button[type='submit']");
      button.disabled = true;
      button.textContent = "结果未确认，请先核对";
    }
  });
}

export function completeSchemaConfigValues(values, schema = {}) {
  if (!values || typeof values !== "object" || Array.isArray(values)) return false;
  return Object.entries(schema).every(([key, item]) => {
    const value = values[key], type = item?.type || "string";
    if (type === "bool") return typeof value === "boolean";
    if (type === "int") return Number.isInteger(value);
    if (type === "float") return typeof value === "number" && Number.isFinite(value);
    return typeof value === "string";
  });
}

export function renderSchemaConfigReceipt(form, receipt) {
  if (!form.isConnected || form._configSaveReceipt !== receipt) return;
  const host = form.querySelector("[data-config-save-result]");
  const confirmed = receipt.steps.filter(step => step.status === "confirmed").length;
  const unknown = receipt.steps.some(step => step.status === "unknown");
  const title = receipt.busy ? "正在分别保存" : confirmed === receipt.steps.length ? "保存已确认" : confirmed ? "部分保存已确认" : "保存结果未确认";
  const fieldValue = value => value === undefined ? "尚未读取" : typeof value === "boolean" ? (value ? "开启" : "关闭") : value === "" ? "（空）" : String(value);
  host.hidden = false;
  host.innerHTML = `<h4>${title}</h4>
    <p>输入已保留，保存期间继续修改的输入也不会被回读覆盖。以下结果对应点击保存时的内容。</p>
    <ol>${receipt.steps.map(step => `<li data-config-step="${escapeHtml(step.module)}">
      <div><b>${escapeHtml(step.label)}</b><strong>${({confirmed:"已确认保存",unknown:"结果未确认",sending:"等待保存响应",pending:"未提交"})[step.status]}</strong></div>
      ${step.error ? `<p>${escapeHtml(step.error)}</p>` : ""}
      ${step.current ? `<p>${Object.keys(step.schema).every(key => step.current[key] === (step.returned || step.submitted)[key]) ? "当前读取与" + (step.returned ? "已确认返回一致" : "本次提交一致") : "当前读取与" + (step.returned ? "已确认返回不同" : "本次提交不同")}</p>` : ""}
      <details class="config-result-values"><summary>本次提交${step.returned ? " / 服务端确认" : ""}${step.current ? " / 当前读取" : ""} · ${Object.keys(step.schema).length} 项</summary>
        <dl>${Object.entries(step.schema).map(([key, item]) => `<div><dt>${escapeHtml(item.description || key)}</dt><dd>提交：${escapeHtml(fieldValue(step.submitted[key]))}${step.returned ? `<br>确认：${escapeHtml(fieldValue(step.returned[key]))}` : ""}${step.current ? `<br>当前：${escapeHtml(fieldValue(step.current[key]))}` : ""}</dd></div>`).join("")}</dl>
      </details></li>`).join("")}</ol>
    ${unknown ? `<p class="config-result-warning">未确认的操作可能已开始。请先核对当前值，不要重复提交；核对不证明未确认的保存已经完成或写入磁盘，也不会补交未提交的模块。</p>` : ""}
    ${receipt.reading ? "<p>正在读取当前配置…</p>" : receipt.readError ? `<p class="config-result-warning">配置回读失败：${escapeHtml(receipt.readError)}。已确认的保存结果仍保留。</p>` : ""}
    <button type="button" data-config-readback${receipt.busy || receipt.reading ? " disabled" : ""}>仅核对当前值</button>`;
  host.querySelector("[data-config-readback]").addEventListener("click", () => readSchemaConfigReceipt(form, receipt));
}

export async function readSchemaConfigReceipt(form, receipt) {
  if (receipt.reading || receipt.busy || !form.isConnected || form._configSaveReceipt !== receipt) return;
  receipt.reading = true;
  receipt.readError = "";
  // A prior read is not a new observation when the following GET fails.
  receipt.steps.forEach(step => { step.current = null; });
  renderSchemaConfigReceipt(form, receipt);
  try {
    const data = await apiGet("/config/schema");
    if (!receipt.steps.every(step => completeSchemaConfigValues(data.values?.[step.module], step.schema))) {
      throw new Error("返回的模块字段不完整，无法核对当前配置");
    }
    receipt.steps.forEach(step => { step.current = data.values[step.module]; });
  } catch (error) {
    receipt.readError = error.message || String(error);
  } finally {
    receipt.reading = false;
    renderSchemaConfigReceipt(form, receipt);
  }
}

export async function saveSchemaConfigModule(form, schemaData = {}) {
  const data = new FormData(form);
  const steps = [form.dataset.configModule, form.dataset.configAdvancedModule].filter(Boolean).map(module => ({
    module, label: schemaData.schema?.[module]?.description || module,
    schema: schemaData.schema?.[module]?.items || {},
    submitted: schemaValuesFromForm(data, schemaData.schema?.[module]?.items || {}), status: "pending",
  }));
  const receipt = { steps, busy: true, reading: false, readError: "" };
  form._configSaveReceipt = receipt;
  for (const step of steps) {
    step.status = "sending";
    renderSchemaConfigReceipt(form, receipt);
    try {
      const result = await apiPost("/config/module/update", { module: step.module, values: step.submitted });
      if (result.module !== step.module || !completeSchemaConfigValues(result.values, step.schema)) {
        throw new Error("保存返回的模块或字段不完整，后续模块未继续提交");
      }
      step.returned = result.values;
      step.status = "confirmed";
      if (step.module === "appearance" && form.isConnected) applyTheme(result.values.theme, { explicit: true });
    } catch (error) {
      step.status = "unknown";
      step.error = error.message || String(error);
      break;
    }
  }
  receipt.busy = false;
  renderSchemaConfigReceipt(form, receipt);
  if (steps.every(step => step.status === "confirmed")) {
    await readSchemaConfigReceipt(form, receipt);
  }
  if (form.isConnected) showToast(steps.every(step => step.status === "confirmed")
    ? (receipt.readError ? "保存已确认，配置回读失败" : "保存已确认，请查看各模块结果")
    : (steps.some(step => step.status === "confirmed") ? "部分保存已确认，其余结果请核对" : "保存结果未确认，请先核对"));
}

export function schemaValuesFromForm(data, schema = {}) {
  const values = {};
  for (const [key, item] of Object.entries(schema)) {
    const type = item?.type || "string";
    if (type === "bool") {
      values[key] = data.get(key) === "on";
    } else if (type === "int") {
      const value = Number(data.get(key));
      values[key] = Number.isFinite(value) ? Math.round(value) : Number(item.default || 0);
    } else if (type === "float") {
      const value = Number(data.get(key));
      values[key] = Number.isFinite(value) ? value : Number(item.default || 0);
    } else {
      values[key] = String(data.get(key) ?? "");
    }
  }
  return values;
}

export function renderRetrievalConfigForm(retrieval = {}, rerankOptions = [], embeddingOptions = []) {
  const currentProvider = retrieval.rerank_provider_id || "";
  const options = Array.isArray(rerankOptions) ? [...rerankOptions] : [];
  const hasProvider = options.some((item) => item.id);
  const currentEmbeddingProvider = retrieval.embedding_provider_id || "";
  const embeddingProviderOptions = Array.isArray(embeddingOptions) ? [...embeddingOptions] : [];
  const hasEmbeddingProvider = embeddingProviderOptions.some((item) => item.id);
  const mode = retrieval.mode || "auto";
  if (currentProvider && !options.some((item) => item.id === currentProvider)) {
    options.push({ id: currentProvider, label: `${currentProvider}（当前配置）` });
  }
  if (currentEmbeddingProvider && !embeddingProviderOptions.some((item) => item.id === currentEmbeddingProvider)) {
    embeddingProviderOptions.push({ id: currentEmbeddingProvider, label: `${currentEmbeddingProvider}（当前配置）` });
  }
  const rerankState = providerStateLabel(currentProvider, hasProvider);
  const embeddingState = providerStateLabel(currentEmbeddingProvider, hasEmbeddingProvider, Boolean(retrieval.embedding_enabled));
  return `
    <form id="retrievalConfigForm" class="context-form retrieval-config-form" autocomplete="off">
      <nav class="config-module-switcher" aria-label="配置模块">
        <button type="button" class="is-active">
          <b>检索召回</b>
          <span>候选、Embedding、Rerank</span>
        </button>
        <button type="button" data-archive-jump="topology">
          <b>权限边界</b>
          <span>窗口读取关系</span>
        </button>
        <button type="button" data-archive-jump="maintenance">
          <b>维护迁移</b>
          <span>修复、导入、清理</span>
        </button>
      </nav>
      <div class="retrieval-hero">
        <div class="retrieval-hero-copy">
          <b>检索配置</b>
          <p>控制记忆候选、向量补召回和二阶段重排。窗口间读取权限请在权限拓扑中调整。</p>
        </div>
        <div class="retrieval-status-grid">
          <span><em>路径</em><strong data-retrieval-status="mode">${escapeHtml(retrievalModeLabel(mode))}</strong></span>
          <span><em>Rerank</em><strong data-retrieval-status="rerank">${escapeHtml(rerankState)}</strong></span>
          <span><em>Embedding</em><strong data-retrieval-status="embedding">${escapeHtml(embeddingState)}</strong></span>
          <span><em>候选</em><strong data-retrieval-status="candidates">${escapeHtml(`${retrieval.rerank_candidate_limit ?? 32} / ${retrieval.embedding_top_k ?? 32}`)}</strong></span>
        </div>
        <div class="retrieval-flow">
          <span>权限过滤</span>
          <span>本地/向量候选</span>
          <span>可选重排</span>
          <span>注入组织</span>
        </div>
      </div>
      ${renderConfigInlineGuide("retrieval")}
      <section class="retrieval-quick-panel">
        <div class="context-form-section-head">
          <b>推荐档位</b>
          <span>预设只会填入当前表单，保存后才生效。</span>
        </div>
        <div class="retrieval-preset-grid">
          <button type="button" data-retrieval-preset="safe">
            <b>保守</b>
            <span>本地优先，少调用模型</span>
          </button>
          <button type="button" data-retrieval-preset="balanced">
            <b>平衡</b>
            <span>自动重排，启用向量补召回</span>
          </button>
          <button type="button" data-retrieval-preset="deep">
            <b>深召回</b>
            <span>扩大候选，适合旧记忆库</span>
          </button>
        </div>
      </section>
      <section class="context-form-section retrieval-core-section">
        <div class="context-form-section-head">
          <b>核心路径</b>
          <span>日常只需要调这里；高级参数可保持默认。</span>
        </div>
        ${contextField({
          label: "检索实现路径",
          hint: "推荐自动选择。没有候选、没有 provider、超时或报错时会回退本地检索。",
          control: `
            <select name="mode">
              <option value="auto"${(retrieval.mode || "auto") === "auto" ? " selected" : ""}>自动选择</option>
              <option value="rerank"${retrieval.mode === "rerank" ? " selected" : ""}>强制重排</option>
              <option value="basic"${retrieval.mode === "basic" ? " selected" : ""}>本地检索</option>
            </select>
          `,
        })}
        ${contextField({
          label: "启用嵌入召回",
          hint: "在关键词之外补充语义相近记忆；没有 Embedding Provider 或调用失败时会自动回退。",
          control: contextSwitch("embedding_enabled", Boolean(retrieval.embedding_enabled)),
        })}
      </section>
      <section class="context-form-section retrieval-provider-section">
        <div class="context-form-section-head">
          <b>模型选择</b>
          <span>下拉用于快速选择，右侧输入框支持手动填写 Provider ID。</span>
        </div>
        ${contextField({
          label: "Rerank Provider",
          hint: "只列出具备 rerank() 能力的提供商。留空时自动扫描可用重排 Provider。",
          control: `
            <div class="provider-inline retrieval-provider-picker">
              <select name="rerank_provider_select">
                <option value="">自动探测 / 不指定</option>
                ${options.map((option) => `<option value="${escapeHtml(option.id || "")}"${(option.id || "") === currentProvider ? " selected" : ""}>${escapeHtml(option.label || option.id || "自动探测 / 不指定")}</option>`).join("")}
              </select>
              <input name="rerank_provider_id" type="text" value="${escapeHtml(currentProvider)}" placeholder="留空自动选择可用重排 Provider" />
            </div>
          `,
          wide: true,
        })}
        ${contextField({
          label: "Embedding Provider",
          hint: "只列出尽量检测到的嵌入提供商。留空时自动扫描第一个可用 Provider。",
          control: `
            <div class="provider-inline retrieval-provider-picker">
              <select name="embedding_provider_select">
                <option value="">自动探测 / 不指定</option>
                ${embeddingProviderOptions.map((option) => `<option value="${escapeHtml(option.id || "")}"${(option.id || "") === currentEmbeddingProvider ? " selected" : ""}>${escapeHtml(option.label || option.id || "自动探测 / 不指定")}</option>`).join("")}
              </select>
              <input name="embedding_provider_id" type="text" value="${escapeHtml(currentEmbeddingProvider)}" placeholder="留空自动选择可用嵌入 Provider" />
            </div>
          `,
          wide: true,
        })}
      </section>
      <details class="context-advanced retrieval-advanced">
        <summary>高级重排参数</summary>
        <div class="context-advanced-note">候选倍率和上限只影响送给 rerank 的候选池大小，不改变最终读取 TopK；TopK 仍沿用记忆注入配置中的条数。</div>
        ${contextField({
          label: "重排候选倍率",
          hint: "实际读取 TopK 的多少倍进入重排。建议 3-5。",
          control: `<input name="rerank_candidate_multiplier" type="number" min="1" step="1" value="${escapeHtml(retrieval.rerank_candidate_multiplier ?? 4)}" />`,
        })}
        ${contextField({
          label: "重排候选上限",
          hint: "每轮最多送入重排模型的候选数量。建议 24-40。",
          control: `<input name="rerank_candidate_limit" type="number" min="1" step="1" value="${escapeHtml(retrieval.rerank_candidate_limit ?? 32)}" />`,
        })}
        ${contextField({
          label: "重排超时毫秒",
          hint: "超时会回退本地检索。建议 1200-2000。",
          control: `<input name="rerank_timeout_ms" type="number" min="0" step="100" value="${escapeHtml(retrieval.rerank_timeout_ms ?? 1200)}" />`,
        })}
      </details>
      <details class="context-advanced retrieval-advanced">
        <summary>高级嵌入参数</summary>
        <div class="context-advanced-note">嵌入只负责补充候选和软加分，最终仍会经过可见性过滤、本地排序和可选重排。</div>
        ${contextField({
          label: "向量候选扫描上限",
          hint: "每轮最多扫描多少条已有向量。记忆库较大时可降低；想扩大旧记忆覆盖面可提高。",
          control: `<input name="embedding_candidate_limit" type="number" min="1" step="50" value="${escapeHtml(retrieval.embedding_candidate_limit ?? 1200)}" />`,
        })}
        ${contextField({
          label: "向量合并数量",
          hint: "相似度最高的多少条进入候选池。建议 24-48。",
          control: `<input name="embedding_top_k" type="number" min="1" step="1" value="${escapeHtml(retrieval.embedding_top_k ?? 32)}" />`,
        })}
        ${contextField({
          label: "相似度阈值",
          hint: "建议 0.30-0.42；过高会漏召回，过低会引入无关记忆。",
          control: `<input name="embedding_score_threshold" type="number" min="0" max="1" step="0.01" value="${escapeHtml(retrieval.embedding_score_threshold ?? 0.34)}" />`,
        })}
        ${contextField({
          label: "向量评分权重",
          hint: "向量相似度在本地评分中的软加分。建议 0.45-0.75。",
          control: `<input name="embedding_weight" type="number" min="0" max="2" step="0.05" value="${escapeHtml(retrieval.embedding_weight ?? 0.55)}" />`,
        })}
        ${contextField({
          label: "嵌入超时毫秒",
          hint: "查询向量或记忆向量生成超时后会回退/跳过。0 表示不限制；OpenAI 兼容公益站建议 4000-8000。",
          control: `<input name="embedding_timeout_ms" type="number" min="0" step="100" value="${escapeHtml(retrieval.embedding_timeout_ms ?? 5000)}" />`,
        })}
        ${contextField({
          label: "单条记忆字符上限",
          hint: "送入 Embedding Provider 的单条记忆文本长度上限。",
          control: `<input name="embedding_max_text_chars" type="number" min="200" step="100" value="${escapeHtml(retrieval.embedding_max_text_chars ?? 1200)}" />`,
        })}
        ${contextField({
          label: "后台补齐旧记忆向量",
          hint: "开启后检索时会小批量补齐旧记忆向量索引，不阻塞当前回复。",
          control: contextSwitch("embedding_backfill_enabled", retrieval.embedding_backfill_enabled !== false),
        })}
        ${contextField({
          label: "补索引批量",
          hint: "每次后台最多补齐多少条旧记忆向量。",
          control: `<input name="embedding_backfill_batch_size" type="number" min="1" step="1" value="${escapeHtml(retrieval.embedding_backfill_batch_size ?? 50)}" />`,
        })}
      </details>
      <div class="context-form-actions">
        <span>保存后下一次检索或工具读取生效；注入日志会显示实际路径。</span>
        <button id="saveRetrievalConfigBtn" type="submit">保存检索配置</button>
      </div>
    </form>
  `;
}

export function bindRetrievalConfigForm(root) {
  const form = root.querySelector("#retrievalConfigForm");
  if (!form) return;
  bindArchiveJumpButtons(form);
  const select = form.querySelector("[name='rerank_provider_select']");
  const input = form.querySelector("[name='rerank_provider_id']");
  bindProviderPicker(select, input);
  bindProviderPicker(
    form.querySelector("[name='embedding_provider_select']"),
    form.querySelector("[name='embedding_provider_id']"),
  );
  form.querySelectorAll("input, select").forEach((field) => {
    field.addEventListener("input", () => updateRetrievalDraftStatus(form));
    field.addEventListener("change", () => updateRetrievalDraftStatus(form));
  });
  form.querySelectorAll("[data-retrieval-preset]").forEach((button) => {
    button.addEventListener("click", () => applyRetrievalPreset(form, button.dataset.retrievalPreset));
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton(form.querySelector("#saveRetrievalConfigBtn"), "保存中", () => saveRetrievalConfig(form));
  });
  updateRetrievalDraftStatus(form);
}

export function setFormValue(form, name, value) {
  const field = form.querySelector(`[name='${name}']`);
  if (!field) return;
  if (field.type === "checkbox") {
    field.checked = Boolean(value);
  } else {
    field.value = String(value);
  }
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
}

export function applyRetrievalPreset(form, preset) {
  const presets = {
    safe: {
      mode: "basic",
      embedding_enabled: false,
      rerank_candidate_multiplier: 3,
      rerank_candidate_limit: 24,
      rerank_timeout_ms: 1000,
      embedding_candidate_limit: 800,
      embedding_top_k: 24,
      embedding_score_threshold: 0.38,
      embedding_weight: 0.45,
      embedding_timeout_ms: 4000,
      embedding_backfill_enabled: false,
      embedding_backfill_batch_size: 24,
    },
    balanced: {
      mode: "auto",
      embedding_enabled: true,
      rerank_candidate_multiplier: 4,
      rerank_candidate_limit: 32,
      rerank_timeout_ms: 1400,
      embedding_candidate_limit: 1200,
      embedding_top_k: 32,
      embedding_score_threshold: 0.34,
      embedding_weight: 0.55,
      embedding_timeout_ms: 5000,
      embedding_backfill_enabled: true,
      embedding_backfill_batch_size: 50,
    },
    deep: {
      mode: "auto",
      embedding_enabled: true,
      rerank_candidate_multiplier: 5,
      rerank_candidate_limit: 48,
      rerank_timeout_ms: 2000,
      embedding_candidate_limit: 2200,
      embedding_top_k: 48,
      embedding_score_threshold: 0.30,
      embedding_weight: 0.70,
      embedding_timeout_ms: 8000,
      embedding_backfill_enabled: true,
      embedding_backfill_batch_size: 80,
    },
  };
  const values = presets[preset];
  if (!values) return;
  Object.entries(values).forEach(([name, value]) => setFormValue(form, name, value));
  form.querySelectorAll("[data-retrieval-preset]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.retrievalPreset === preset);
  });
  updateRetrievalDraftStatus(form);
  showToast("已套用预设，保存后生效");
}

export function updateRetrievalDraftStatus(form) {
  const value = (name, fallback = "") => String(form.querySelector(`[name='${name}']`)?.value ?? fallback);
  const checked = (name) => Boolean(form.querySelector(`[name='${name}']`)?.checked);
  const set = (key, text) => {
    const target = form.querySelector(`[data-retrieval-status='${key}']`);
    if (target) target.textContent = text;
  };
  set("mode", retrievalModeLabel(value("mode", "auto")));
  set("rerank", value("rerank_provider_id") || "自动探测");
  set("embedding", checked("embedding_enabled") ? (value("embedding_provider_id") || "自动探测") : "未启用");
  set("candidates", `${value("rerank_candidate_limit", "32")} / ${value("embedding_top_k", "32")}`);
}

export function bindProviderPicker(select, input) {
  if (!select || !input) return;
  select.addEventListener("change", () => {
    input.value = select.value || "";
  });
  input.addEventListener("input", () => {
    const matched = Array.from(select.options).some((option) => option.value === input.value);
    if (matched) select.value = input.value;
  });
}

export async function saveRetrievalConfig(form) {
  const data = new FormData(form);
  const num = (name, fallback = 0) => {
    const value = Number(data.get(name));
    return Number.isFinite(value) ? value : fallback;
  };
  const payload = {
    mode: String(data.get("mode") || "auto"),
    rerank_provider_id: String(data.get("rerank_provider_id") || ""),
    rerank_candidate_multiplier: Math.max(1, Math.round(num("rerank_candidate_multiplier", 4))),
    rerank_candidate_limit: Math.max(1, Math.round(num("rerank_candidate_limit", 32))),
    rerank_timeout_ms: Math.max(0, Math.round(num("rerank_timeout_ms", 1200))),
    embedding_enabled: data.get("embedding_enabled") === "on",
    embedding_provider_id: String(data.get("embedding_provider_id") || ""),
    embedding_candidate_limit: Math.max(1, Math.round(num("embedding_candidate_limit", 1200))),
    embedding_top_k: Math.max(1, Math.round(num("embedding_top_k", 32))),
    embedding_score_threshold: Math.min(1, Math.max(0, num("embedding_score_threshold", 0.34))),
    embedding_weight: Math.min(2, Math.max(0, num("embedding_weight", 0.55))),
    embedding_timeout_ms: Math.max(0, Math.round(num("embedding_timeout_ms", 5000))),
    embedding_max_text_chars: Math.max(200, Math.round(num("embedding_max_text_chars", 1200))),
    embedding_backfill_enabled: data.get("embedding_backfill_enabled") === "on",
    embedding_backfill_batch_size: Math.max(1, Math.round(num("embedding_backfill_batch_size", 50))),
  };
  const result = await apiPost("/retrieval/config/update", payload);
  if (!result?.retrieval) throw new Error("检索配置未返回确认结果");
  showToast("检索配置已保存");
  try {
    await loadArchive();
  } catch (error) {
    showToast("检索配置已保存，但刷新页面数据失败", "error");
  }
}

export async function showMemory(id) {
  state.activeMemoryId = id;
  $("#detailDrawer").className = "detail-drawer memory-record-detail";
  $("#detailDrawer").innerHTML = loadingState("正在展开详情...");
  let memory;
  try {
    const data = await apiGet(`/memory?id=${encodeURIComponent(id)}`);
    memory = data.memory;
    if (state.activeMemoryId !== id) return;
  } catch (error) {
    if (state.activeMemoryId !== id) return;
    $("#detailDrawer").innerHTML = panelError(error, "重新读取");
    const retry = $("#detailDrawer [data-retry-active]");
    if (retry) retry.addEventListener("click", () => showMemory(id));
    showToast(error.message || "详情读取失败", "error");
    return;
  }
  $("#detailDrawer").classList.remove("empty");
  $("#detailDrawer").innerHTML = `
    <div class="memory-manage-head">
      <div>
        <h3>${escapeHtml(memoryFieldLabel("memory_type", memory.memory_type))}</h3>
        <button type="button" data-memory-back>返回当前列表</button>
        <p class="item-meta">${escapeHtml(memory.id)} · ${escapeHtml(formatTime(memory.occurred_at || memory.created_at))}</p>
      </div>
      <div class="badges">
        <span class="badge teal">${escapeHtml(memoryFieldLabel("visibility", memory.visibility))}</span>
        <span class="badge blue">${escapeHtml(memoryFieldLabel("reality_level", memory.reality_level))}</span>
        <span class="badge gold">${escapeHtml(memoryFieldLabel("lifecycle", memory.lifecycle))}</span>
        <span class="badge ${memory.validity_status === "active" ? "teal" : "violet"}">${escapeHtml(memoryFieldLabel("validity_status", memory.validity_status))}</span>
      </div>
    </div>
    ${memory.source_plugin === "livingmemory" && isNumericOnlyContent(memory.content) ? `<div class="empty-state error-state"><b>导入内容未修复</b><span>这条记录目前只有旧库编号，请先在维护工具中执行“修复 LivingMemory 内容”。</span></div>` : ""}
    <section class="memory-reading" aria-label="当前记忆正文"><h4>当前正文</h4><p>${escapeHtml(memory.content || "（空内容）")}</p></section>
    ${memorySourceSummary(memory)}
    <details class="memory-record-section"><summary>证据与关联摘要</summary><p class="memory-evidence">${escapeHtml(memory.evidence || "未记录证据文本")}</p>${renderMemoryStructuredMetadata(memory)}</details>
    <div id="memoryRevisions">${renderMemoryRevisions(memory.revisions)}</div>
    <details class="memory-record-section"><summary>系统归属与使用反馈</summary><section class="memory-atom-panel" aria-label="Memory Atom v2">
      <div class="memory-atom-panel-head"><b>Memory Atom v2</b><span>归属与系统反馈字段为只读</span></div>
      <div class="memory-atom-readonly-grid">
        <span><em>Owner Bot</em><strong>${escapeHtml(memory.owner_bot_id || "未标记")}</strong></span>
        <span><em>Persona</em><strong>${escapeHtml(memory.persona_id || "未标记")}</strong></span>
        <span><em>强化分</em><strong>${escapeHtml(percentLabel(memory.reinforcement_score || 0))}</strong></span>
        <span><em>实际注入</em><strong>${escapeHtml(memory.injection_count || 0)} 次</strong></span>
        <span><em>最近注入</em><strong>${escapeHtml(formatTime(memory.last_injected_at) || "从未")}</strong></span>
        <span><em>Canonical</em><strong title="${escapeHtml(memory.canonical_key || "")}">${escapeHtml(shortId(memory.canonical_key || "未生成"))}</strong></span>
      </div>
    </section></details>
    <details class="memory-record-section memory-editor" data-memory-editor><summary>编辑内容与有效状态</summary>
    <p class="item-meta">收起保留本页输入；切换记录、刷新或离开页面会丢失未保存修改。</p>
    <form id="memoryManageForm" class="memory-manage-form" autocomplete="off">
      <label>
        <span>内容</span>
        <textarea name="content" rows="6">${escapeHtml(memory.content || "")}</textarea>
        ${memory.memory_type === "conversation_summary" ? '<small>修改摘要正文后会同步更新检索内容，旧的自动要点与关联索引停止使用。修改前的版本保留在修改历史中。</small>' : ""}
      </label>
      <label>
        <span>证据</span>
        <textarea name="evidence" rows="4">${escapeHtml(memory.evidence || "")}</textarea>
      </label>
      <div class="memory-manage-grid">
        <label>
          <span>有效状态</span>
          <select name="validity_status">
            ${memoryOption("active", "有效", memory.validity_status)}
            ${memoryOption("superseded", "已被新事实替代", memory.validity_status)}
            ${memoryOption("expired", "已过期", memory.validity_status)}
            ${memoryOption("archived", "已归档", memory.validity_status)}
            ${memoryOption("quarantined", "隔离待确认", memory.validity_status)}
          </select>
        </label>
        <label>
          <span>可见性</span>
          <select name="visibility">
            ${memoryOption("private_pair", "私聊可见", memory.visibility)}
            ${memoryOption("group_public", "群聊可见", memory.visibility)}
            ${memoryOption("bot_self", "自我档案", memory.visibility)}
            ${memoryOption("internal", "内部", memory.visibility)}
            ${memoryOption("shareable", "可共享", memory.visibility)}
          </select>
        </label>
      </div>
      <details class="memory-record-section"><summary>高级属性、有效期与召回权重</summary>
      <label>
        <span>记忆类型</span>
        <input name="memory_type" type="text" value="${escapeHtml(memory.memory_type || "")}" />
      </label>
      <div class="memory-manage-grid">
        <label>
          <span>生命周期</span>
          <select name="lifecycle">
            ${memoryOption("stable_memory", "稳定记忆", memory.lifecycle)}
            ${memoryOption("raw_event", "原始事件", memory.lifecycle)}
            ${memoryOption("archived", "归档", memory.lifecycle)}
          </select>
        </label>
        <label>
          <span>重要度</span>
          <input name="importance" type="number" min="0" max="1" step="0.01" value="${escapeHtml(memory.importance ?? 0.3)}" />
        </label>
        <label>
          <span>显著性</span>
          <input name="salience" type="number" min="0" max="1" step="0.01" value="${escapeHtml(memory.salience ?? memory.importance ?? 0.3)}" />
        </label>
        <label>
          <span>置信度</span>
          <input name="confidence" type="number" min="0" max="1" step="0.01" value="${escapeHtml(memory.confidence ?? 0.5)}" />
        </label>
        <label>
          <span>耐久度</span>
          <select name="durability">
            ${memoryOption("ephemeral", "短暂流水", memory.durability)}
            ${memoryOption("short", "短期", memory.durability)}
            ${memoryOption("normal", "普通", memory.durability)}
            ${memoryOption("durable", "耐久", memory.durability)}
            ${memoryOption("pinned", "固定保护", memory.durability)}
          </select>
        </label>
        <label>
          <span>敏感级别</span>
          <select name="sensitivity">
            ${memoryOption("public", "公开", memory.sensitivity)}
            ${memoryOption("internal", "内部", memory.sensitivity)}
            ${memoryOption("private", "私密", memory.sensitivity)}
            ${memoryOption("restricted", "严格限制", memory.sensitivity)}
          </select>
        </label>
        <label>
          <span>生效时间（ISO-8601）</span>
          <input name="valid_from" type="text" value="${escapeHtml(memory.valid_from || "")}" placeholder="2026-08-16T00:00:00+08:00" />
        </label>
        <label>
          <span>失效时间（ISO-8601）</span>
          <input name="valid_to" type="text" value="${escapeHtml(memory.valid_to || "")}" placeholder="留空表示不设截止" />
        </label>
      </div>
      </details>
      <div class="memory-manage-actions">
        <button id="saveMemoryBtn" type="submit">保存这条记忆</button>
      </div>
    </form></details>
    <details class="memory-record-section"><summary data-memory-maintenance>删除与底层资料</summary>
    <p class="item-meta">归档请在编辑区修改有效状态；删除会移除记录及其修改历史，仍需再次确认。</p>
    <button class="danger" data-delete="1" type="button">删除这条记忆</button>
    <details class="memory-raw-detail">
      <summary>归属与元数据</summary>
      <h4>归属</h4>
      <pre>${escapeHtml(JSON.stringify({ subject: memory.subject, object: memory.object, scope: memory.scope, session_id: memory.session_id, group_id: memory.group_id }, null, 2))}</pre>
      <h4>元数据</h4>
      <pre>${escapeHtml(JSON.stringify(displayMemoryMetadata(memory), null, 2))}</pre>
    </details></details>
  `;
  const form = $("#memoryManageForm");
  $("[data-memory-back]").addEventListener("click", () => {
    ($(".view.is-active .memory-browser") || $("#workspace")).scrollIntoView({block: "start"});
  });
  $("#memoryRevisions")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-revision-offset]");
    if (!button) return;
    await withButton(button, "读取中", async () => {
      const result = await apiGet(`/memory?id=${encodeURIComponent(id)}&revision_offset=${Number(button.dataset.revisionOffset)}`);
      if (state.activeMemoryId !== id) return;
      $("#memoryRevisions").innerHTML = renderMemoryRevisions(result.memory.revisions, true);
    });
  });
  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    withButton($("#saveMemoryBtn"), "保存中", () => saveMemoryManagement(id, form));
  });
  $("#detailDrawer [data-delete]").addEventListener("click", () => {
    showInlineConfirmation({
      host: "#detailDrawer",
      title: "删除这条记忆",
      message: "删除后会同时清理修改历史、关联的向量、关系边和知识图谱边。",
      confirmLabel: "确认删除",
      busyText: "正在删除记忆...",
      dangerous: true,
      onConfirm: async () => {
        await apiPost("/memory/delete", { id });
        clearDetail();
        await refreshAll();
      },
      onCancel: () => showMemory(id),
    });
  });
}
