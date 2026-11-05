/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {fetchJson} from './client.js';
import {renderGroupDetail,renderGroups} from './learning.js';
import {switchTab} from './navigation.js';
import {formatBytes,imageCacheScopeLabel} from './relationships.js';
import {formatProactiveLimit,proactiveLimitUnlimited} from './schema.js';
import {$,TRANSPARENT_IMAGE,asteriaWorkspaceState,imageCachePreviewCache,imageCachePreviewPending,state} from './state.js';
import {horizontalBars} from './usage.js';
import {escapeHtml} from './workspace.js';

export function invalidateImageCachePreviews() {
  asteriaWorkspaceState.imageCachePreviewEpoch++;
  imageCachePreviewCache.clear(); imageCachePreviewPending.clear(); asteriaWorkspaceState.imageCachePreviewChars = 0;
  asteriaWorkspaceState.imageCachePreviewObserver?.disconnect(); asteriaWorkspaceState.imageCachePreviewObserver = null;
}

export async function imageCachePreviewData(key, epoch) {
  if (imageCachePreviewCache.has(key)) {
    const value = imageCachePreviewCache.get(key);
    imageCachePreviewCache.delete(key); imageCachePreviewCache.set(key, value);
    return value;
  }
  if (imageCachePreviewPending.has(key)) return imageCachePreviewPending.get(key);
  const task = (async () => {
    const result = await fetchJson(`/image_cache/preview_data?key=${encodeURIComponent(key)}`);
    const value = result?.data_url;
    if (typeof value !== "string" || value.length > Math.ceil(2 * 1024 * 1024 / 3) * 4 + 32
      || !/^data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value)) {
      throw Error("预览响应不可用");
    }
    if (epoch === asteriaWorkspaceState.imageCachePreviewEpoch) {
      while (imageCachePreviewCache.size >= 12 || asteriaWorkspaceState.imageCachePreviewChars + value.length > 8 * 1024 * 1024) {
        const oldest = imageCachePreviewCache.keys().next().value;
        asteriaWorkspaceState.imageCachePreviewChars -= imageCachePreviewCache.get(oldest).length; imageCachePreviewCache.delete(oldest);
      }
      imageCachePreviewCache.set(key, value); asteriaWorkspaceState.imageCachePreviewChars += value.length;
    }
    return value;
  })();
  imageCachePreviewPending.set(key, task);
  try { return await task; }
  finally { if (imageCachePreviewPending.get(key) === task) imageCachePreviewPending.delete(key); }
}

export async function hydrateImageCachePreview(image) {
  const key = image.dataset.imageCachePreviewKey, epoch = asteriaWorkspaceState.imageCachePreviewEpoch;
  if (!key || !image.isConnected || image.dataset.previewLoading === "1") return;
  image.dataset.previewLoading = "1";
  const valid = () => image.isConnected && image.dataset.imageCachePreviewKey === key && epoch === asteriaWorkspaceState.imageCachePreviewEpoch;
  const status = image.parentElement?.querySelector("[data-image-cache-preview-status]");
  const unavailable = () => {
    if (!valid()) return;
    image.onerror = null; image.src = TRANSPARENT_IMAGE; image.hidden = true; image.style.display = "none"; image.alt = "预览不可用";
    if (status) { status.textContent = "预览不可用"; status.hidden = false; }
  };
  try {
    const value = await imageCachePreviewData(key, epoch);
    if (!valid()) return;
    image.onerror = unavailable;
    image.src = value; image.hidden = false; image.style.display = "";
    if (status) status.hidden = true;
  } catch (_) { unavailable(); }
  finally { if (valid()) image.dataset.previewLoading = "0"; }
}

export function hydrateImageCachePreviews() {
  asteriaWorkspaceState.imageCachePreviewObserver?.disconnect();
  const list = $("#imageCacheList"), detail = $("#imageCacheDetail");
  const images = list ? [...list.querySelectorAll("img[data-image-cache-preview-key]")] : [];
  if (typeof IntersectionObserver === "function") {
    asteriaWorkspaceState.imageCachePreviewObserver = new IntersectionObserver((entries, observer) => {
      for (const entry of entries) if (entry.isIntersecting) {
        observer.unobserve(entry.target);
        const image = entry.target.querySelector("img[data-image-cache-preview-key]");
        if (image) void hydrateImageCachePreview(image);
      }
    });
    // Hidden images have no box to intersect. Observe their visible thumbnail slot.
    images.forEach(image => asteriaWorkspaceState.imageCachePreviewObserver.observe(image.parentElement));
  } else {
    // Old engines still show the selected record; do not eagerly fetch a
    // 300-record list just to replace the browser's lazy-image behavior.
    images.slice(0, 12).forEach(image => { void hydrateImageCachePreview(image); });
  }
  detail?.querySelectorAll("img[data-image-cache-preview-key]").forEach(image => { void hydrateImageCachePreview(image); });
}

export function renderImageCache() {
  const summaryEl = $("#imageCacheSummary");
  const listEl = $("#imageCacheList");
  const detailEl = $("#imageCacheDetail");
  if (!summaryEl || !listEl || !detailEl) return;
  const overviewCache = state.overview?.cache?.private_image_vision || {};
  const items = state.imageCacheItems || [];
  const selected = items.find((item) => item.key === state.selectedImageCacheKey) || null;
  const hasActiveCacheQuery = Boolean(state.imageCacheLoaded || state.imageCacheFilter || (state.imageCacheScope && state.imageCacheScope !== "all") || state.imageCacheTotal || items.length);
  const totalDisplay = hasActiveCacheQuery ? state.imageCacheTotal : (overviewCache.items || 0);
  summaryEl.innerHTML = `
    <div class="image-cache-stat">
      <b>${escapeHtml(String(totalDisplay))}</b>
      <span>缓存条目</span>
    </div>
    <div class="image-cache-stat">
      <b>${escapeHtml(overviewCache.max_items ? `${overviewCache.max_items}` : "不限")}</b>
      <span>上限</span>
    </div>
    <div class="image-cache-stat ${overviewCache.enabled ? "ok" : "warn"}">
      <b>${escapeHtml(overviewCache.enabled ? "开启" : "关闭")}</b>
      <span>重复图片缓存</span>
    </div>
    <div class="image-cache-stat">
      <b>${escapeHtml(String(items.reduce((sum, item) => sum + Number(item.hits || 0), 0)))}</b>
      <span>当前列表命中</span>
    </div>
  `;
  const scopeSelect = $("#imageCacheScope");
  if (scopeSelect) {
    const current = state.imageCacheScope || "all";
    scopeSelect.innerHTML = [
      `<option value="all">全部范围</option>`,
      ...state.imageCacheScopes.map((scope) => `<option value="${escapeHtml(scope)}">${escapeHtml(imageCacheScopeLabel(scope))}</option>`),
    ].join("");
    scopeSelect.value = current;
  }
  const filterInput = $("#imageCacheFilter");
  if (filterInput && filterInput.value !== state.imageCacheFilter) {
    filterInput.value = state.imageCacheFilter || "";
  }
  listEl.innerHTML = items.length
    ? items.map((item) => imageCacheListItemMarkup(item)).join("")
    : `<div class="empty image-cache-empty"><b>暂无缓存条目</b><span>收到图片或表情包并完成视觉转述后会出现在这里。</span></div>`;
  detailEl.innerHTML = selected ? imageCacheDetailMarkup(selected) : `
    <div class="empty image-cache-empty">
      <b>选择一条缓存</b>
      <span>左侧点击图片/表情包缓存后，可以编辑摘要或删除。</span>
    </div>
  `;
  hydrateImageCachePreviews();
}

export function imageCacheListItemMarkup(item) {
  const selected = item.key === state.selectedImageCacheKey;
  const title = item.image_type || imageCacheScopeLabel(item.scope);
  const preview = item.visible || item.intent || item.text || "无摘要";
  const ownership = item.ownership ? `<span>${escapeHtml(item.ownership)}</span>` : "";
  const thumb = item.preview_url
    ? `<span class="image-cache-thumb has-image"><img data-image-cache-preview-key="${escapeHtml(item.key)}" src="${TRANSPARENT_IMAGE}" style="display:none" alt="${escapeHtml(title)}" loading="lazy" /><span data-image-cache-preview-status style="font-size:10px;line-height:1.2">读取中</span></span>`
    : `<span class="image-cache-thumb">${escapeHtml((item.image_type || "图").slice(0, 2))}</span>`;
  return `
    <button type="button" class="image-cache-row ${selected ? "is-active" : ""}" data-image-cache-key="${escapeHtml(item.key)}">
      ${thumb}
      <span class="image-cache-row-main">
        <b>${escapeHtml(title)}</b>
        <small>${escapeHtml(preview)}</small>
        <i>${escapeHtml(imageCacheScopeLabel(item.scope))} · 命中 ${escapeHtml(item.hits || 0)} · ${escapeHtml(item.last_hit || item.created || "未知时间")}</i>
      </span>
      ${ownership}
    </button>
  `;
}

export function imageCacheDetailMarkup(item) {
  const aliases = Array.isArray(item.image_aliases) ? item.image_aliases : [];
  const keys = Array.isArray(item.image_keys) ? item.image_keys : [];
  const previewMeta = item.preview_url
    ? [
        item.preview_width && item.preview_height ? `${item.preview_width}x${item.preview_height}` : "",
        item.preview_size ? formatBytes(item.preview_size) : "",
      ].filter(Boolean).join(" · ")
    : "";
  return `
    <form class="image-cache-editor" data-image-cache-editor="${escapeHtml(item.key)}">
      <header>
        <div>
          <span class="module-badge">${escapeHtml(imageCacheScopeLabel(item.scope))}</span>
          <h3>${escapeHtml(item.image_type || "图片缓存")}</h3>
          <p>${escapeHtml(item.intent || item.visible || "可编辑这张图片/表情包的视觉摘要。")}</p>
        </div>
        <button type="button" class="danger" data-image-cache-delete="${escapeHtml(item.key)}">删除缓存</button>
      </header>
      ${item.preview_url ? `
        <figure class="image-cache-preview">
          <img data-image-cache-preview-key="${escapeHtml(item.key)}" src="${TRANSPARENT_IMAGE}" style="display:none" alt="${escapeHtml(item.image_type || "图片缓存预览")}" />
          <span data-image-cache-preview-status>正在读取预览…</span>
          ${previewMeta ? `<figcaption>${escapeHtml(previewMeta)} · 压缩预览</figcaption>` : `<figcaption>压缩预览</figcaption>`}
        </figure>
      ` : ""}
      <div class="image-cache-meta">
        <div><dt>Provider</dt><dd>${escapeHtml(item.provider_id || "未记录")}</dd></div>
        <div><dt>创建</dt><dd>${escapeHtml(item.created || "-")}</dd></div>
        <div><dt>最近命中</dt><dd>${escapeHtml(item.last_hit || "未命中")}</dd></div>
        <div><dt>编辑</dt><dd>${escapeHtml(item.edited || "未编辑")}</dd></div>
        <div><dt>图片数</dt><dd>${escapeHtml(item.image_count || keys.length || 1)}</dd></div>
        <div><dt>Prompt</dt><dd>${escapeHtml(item.prompt_sig || "-")}</dd></div>
      </div>
      <label>缓存范围
        <select name="scope">
          ${["private_image", "private_image_query", "forward_image", "screen_peek"].map((scope) => `
            <option value="${escapeHtml(scope)}" ${item.scope === scope ? "selected" : ""}>${escapeHtml(imageCacheScopeLabel(scope))}</option>
          `).join("")}
        </select>
      </label>
      <label>Provider ID
        <input name="provider_id" value="${escapeHtml(item.provider_id || "")}" />
      </label>
      <label class="wide-field">视觉摘要
        <textarea name="text" rows="10">${escapeHtml(item.text || "")}</textarea>
      </label>
      <details class="image-cache-keys wide-field">
        <summary>缓存键和别名</summary>
        <code>${escapeHtml(item.key)}</code>
        ${keys.length ? `<p>${keys.map((key) => `<span>${escapeHtml(key)}</span>`).join("")}</p>` : ""}
        ${aliases.length ? `<p>${aliases.map((alias) => `<span>${escapeHtml(alias)}</span>`).join("")}</p>` : ""}
      </details>
      <div class="actions">
        <button type="button" data-copy-text="${escapeHtml(item.text || "")}">复制摘要</button>
        <button type="submit">保存缓存</button>
      </div>
    </form>
  `;
}

export function renderRelationshipChart() {
  const buckets = { 亲近: 0, 熟悉: 0, 陌生: 0, 未分层: 0 };
  state.users.forEach((user) => {
    const stage = user.relationship_stage || "未分层";
    buckets[Object.prototype.hasOwnProperty.call(buckets, stage) ? stage : "未分层"] += 1;
  });
  $("#relationshipChart").innerHTML = horizontalBars(buckets, Math.max(1, state.users.length));
}

export function renderQuotaChart() {
  const quotaUsers = state.users.filter((user) => user.is_qq_user);
  const rows = (quotaUsers.length ? quotaUsers : state.users).slice(0, 12).map((user) => {
    const used = Number(user.sent_today || 0);
    const limit = Number(user.effective_daily_limit || state.overview?.proactive_intensity?.effective?.max_daily_messages || state.overview?.private?.max_daily_messages || 0);
    const unlimited = proactiveLimitUnlimited(limit, user.effective_daily_limit_unlimited || state.overview?.proactive_intensity?.effective?.max_daily_messages_unlimited);
    const meterMax = unlimited ? Math.max(1, used + 1) : limit;
    const pct = meterMax > 0 ? Math.min(100, Math.round((used / meterMax) * 100)) : 0;
    const limitText = user.effective_daily_limit_text || formatProactiveLimit(limit, unlimited);
    return `
      <div class="meter-row">
        <span title="${escapeHtml(user.user_id || "")}">${escapeHtml(userQuotaLabel(user))}</span>
        <div class="meter"><i style="width:${pct}%"></i></div>
        <b>${escapeHtml(used)}${limitText !== "0" ? `/${escapeHtml(limitText)}` : ""}</b>
      </div>
    `;
  });
  $("#quotaChart").innerHTML = rows.length ? rows.join("") : `<div class="empty small">暂无私聊对象</div>`;
}

export function userQuotaLabel(user) {
  const id = String(user?.user_id || "");
  if (user?.display_name && !String(user.display_name).startsWith("临时会话")) return user.display_name;
  if (user?.display_name && !user?.is_qq_user) return user.display_name;
  const nickname = String(user?.nickname || "").trim();
  const genericNames = new Set(["用户", "主人", "主要用户", "默认用户"]);
  if (!nickname || genericNames.has(nickname)) return id || "未命名";
  return id ? `${nickname} · ${id.slice(-4)}` : nickname;
}

export function renderGroupBubbleChart() {
  const groups = state.groups.slice(0, 12);
  if (!groups.length) {
    $("#groupBubbleChart").innerHTML = `<div class="empty small">暂无群聊数据</div>`;
    return;
  }
  const enabledCount = groups.filter((group) => group.enabled).length;
  const totalMessages = groups.reduce((sum, group) => sum + Number(group.message_count || 0), 0);
  const totalTopics = groups.reduce((sum, group) => sum + Number(group.topic_count || 0), 0);
  const maxMessages = Math.max(1, ...groups.map((group) => Number(group.message_count || 0)));
  $("#groupBubbleChart").innerHTML = `
    <div class="group-observe-summary">
      <section><span>观测中</span><b>${escapeHtml(enabledCount)} / ${escapeHtml(groups.length)}</b></section>
      <section><span>累计消息</span><b>${escapeHtml(totalMessages)}</b></section>
      <section><span>话题线</span><b>${escapeHtml(totalTopics)}</b></section>
    </div>
    <div class="group-observe-list">
      ${groups.map((group) => renderGroupObserveRow(group, maxMessages)).join("")}
    </div>
  `;
  document.querySelectorAll("[data-observe-group]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedGroupId = button.dataset.observeGroup;
      switchTab("group");
      renderGroups();
      renderGroupDetail(true);
    });
  });
}

export function renderGroupObserveRow(group, maxMessages) {
  const messageCount = Number(group.message_count || 0);
  const pct = Math.max(4, Math.round((messageCount / Math.max(1, maxMessages)) * 100));
  const name = group.name || group.group_name || group.title || group.group_id || "未命名群";
  const metrics = [
    `${messageCount} 消息`,
    `${Number(group.episode_count || 0)} 片段`,
    `${Number(group.topic_count || 0)} 话题`,
    `${Number(group.slang_count || 0)} 黑话`,
  ];
  return `
    <button type="button" class="group-observe-row ${group.enabled ? "" : "off"}" data-observe-group="${escapeHtml(group.group_id)}">
      <div class="group-observe-main">
        <span class="group-observe-state">${group.enabled ? "开启" : "停用"}</span>
        <b>${escapeHtml(name)}</b>
        <small>${escapeHtml(group.group_id || "")}</small>
      </div>
      <div class="group-observe-meter">
        <i style="width:${pct}%"></i>
      </div>
      <div class="group-observe-meta">
        ${metrics.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
      </div>
      <small class="group-observe-time">${escapeHtml(group.last_seen || "暂无活跃")}</small>
    </button>
  `;
}
