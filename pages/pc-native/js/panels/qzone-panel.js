/** Credited view panel, maintained as an Asteria ES module; see frontend provenance. */
import asteriaOutfit from '../features/daily-outfit.js';
const panel = (() => {
  const state = {
    initialized: false,
    status: null,
    scope: "friends",
    targetUin: "",
    posts: [],
    selectedId: "",
    loading: false,
    loaded: false,
    page: 1,
    actionResults: new Map(),
    unconfirmed: new Set(),
    publishing: false,
    pendingComments: new Set(),
    pendingLikes: new Set(),
    pendingDeletes: new Set(),
    deleteConfirmId: "",
    deleteConfirmAt: 0,
    detailLoadingId: "",
    context: null,
  };

  function text(value) {
    return String(value ?? "");
  }

  function postById(id) {
    return state.posts.find((item) => item.id === id) || null;
  }

  function setNotice(message = "", tone = "info") {
    const notice = document.getElementById("qzoneNotice");
    if (!notice) return;
    notice.hidden = !message;
    notice.textContent = message;
    notice.dataset.tone = tone;
  }

  function isRouteMissingError(error) {
    return /未找到该路由|找不到该路由|路由不存在|route\s*(?:not\s*found|missing)|not\s*found.*route|^not\s*found$|HTTP\s*404|\b404\b/i.test(String(error?.message || "").trim());
  }

  async function qzoneFetch(paths) {
    const candidates = Array.isArray(paths) ? paths : [paths];
    let lastError = null;
    for (const path of candidates) {
      try {
        return await state.context.fetchJson(path);
      } catch (error) {
        lastError = error;
        if (!isRouteMissingError(error)) break;
      }
    }
    throw lastError || new Error("QQ 空间请求失败");
  }

  async function qzonePost(paths, body = {}) {
    // The current native owner registers the canonical path. An upstream 404
    // is not evidence that a write was never dispatched; never replay aliases.
    return state.context.postJson(Array.isArray(paths) ? paths[0] : paths, body);
  }

  function recordAction(key, message, tone = "info", detail = "") {
    state.actionResults.set(key, { message, tone, detail });
    const node = document.getElementById("qzoneActionResults");
    if (node) {
      const e = state.context.escapeHtml;
      node.hidden = false;
      node.innerHTML = `<h3>本页操作结果</h3>${Array.from(state.actionResults, ([id, r]) => `<article data-qzone-result="${e(id)}" data-tone="${e(r.tone)}"><b>${e(r.message)}</b>${r.detail ? `<p>${e(r.detail)}</p>` : ""}</article>`).join("")}<p class="muted">仅本页留存，刷新或离页后不保留。结果未确认时先到 QQ 空间核实，刷新动态也不能证明上次操作完成；本页不会自动重交。</p>`;
    }
    const button = document.querySelector("#qzonePublishForm button[type=submit]");
    if (button) button.disabled = state.publishing || state.unconfirmed.has("publish");
    const refresh = document.getElementById("qzoneRefreshCookiesBtn");
    if (refresh) refresh.disabled = state.unconfirmed.has("cookies") || state.actionResults.get("cookies")?.tone === "pending";
  }

  function unknownAction(key, label, error) {
    state.unconfirmed.add(key);
    recordAction(key, `${label}结果未确认`, "warn", `${key.includes(":") ? `目标 ${key.slice(key.indexOf(":") + 1)} · ` : ""}${error?.message || "返回字段不完整或目标不匹配"}。服务端可能已经执行，请先核实。`);
    state.context.showToast(`${label}结果未确认，保留输入与原记录，请先核实`, "warn");
  }

  async function refreshCookies() {
    return qzonePost([
      "/qzone/refresh_cookies",
      "/qzone/refresh-cookies",
      "/qzone/cookies/refresh",
      "/qzone/refresh",
      "/qzone/cookie/refresh",
    ], {});
  }

  function renderAccount() {
    const login = state.status?.login || {};
    const summary = state.status?.summary || {};
    const name = document.getElementById("qzoneAccountName");
    const meta = document.getElementById("qzoneAccountMeta");
    const accountName = login.nickname || (login.uin ? `QQ ${login.uin}` : "未绑定");
    if (name) name.textContent = accountName;
    const avatar = document.getElementById("qzoneAccountAvatar");
    const avatarFallback = document.getElementById("qzoneAccountAvatarFallback");
    const avatarUrl = text(login.avatar).trim();
    if (avatar) {
      if (avatarUrl) avatar.src = avatarUrl;
      else avatar.removeAttribute("src");
      avatar.hidden = !avatarUrl;
    }
    if (avatarFallback) {
      avatarFallback.hidden = Boolean(avatarUrl);
      avatarFallback.textContent = Array.from(accountName.trim())[0] || "Q";
    }
    const accountStatus = document.getElementById("qzoneAccountStatus");
    if (accountStatus) {
      const tone = !state.status ? "idle" : (summary.enabled && login.bound ? "ready" : (summary.available ? "warn" : "error"));
      const label = !state.status ? "同步中" : (!summary.available ? "接口不可用" : !summary.enabled ? "未启用" : login.bound ? "凭据已取得" : "凭据未确认");
      accountStatus.dataset.tone = tone;
      accountStatus.textContent = label;
    }
    if (meta) {
      meta.textContent = !state.status
        ? "正在读取 QQ 空间状态"
        : summary.enabled
        ? `QQ 空间已启用 · ${login.bound ? "凭据可解析，动态访问以读取结果为准" : "本次未取得有效登录信息"}`
        : (summary.available ? "QQ 空间模块已加载，但整合开关未开启" : "QQ 空间模块不可用");
    }
    const summaryBox = document.getElementById("qzoneQuickSummary");
    if (summaryBox) {
      const imageStatus = summary.last_life_publish_generated_image_status || "";
      const imageNote = summary.last_life_publish_generated_image_note || "";
      const imageLabel = summary.last_life_publish_images > 0
        ? `${summary.last_life_publish_images} 张`
        : (imageStatus ? imageStatus.replace(/^skipped:/, "跳过:").replace(/^failed:/, "失败:") : "无留存记录");
      const referenceMeta = summary.last_life_publish_generated_image_reference
        ? `参考图${summary.last_life_publish_generated_image_reference_exists ? "可用" : "不可用"}`
        : "";
      const designMeta = [summary.last_life_publish_generated_image_anchor, summary.last_life_publish_generated_image_composition]
        .filter(Boolean)
        .join(" / ");
      const imageMeta = summary.generated_image_enabled
        ? ([imageNote, designMeta, referenceMeta].filter(Boolean).join(" · ") || `配图概率 ${Math.round(Number(summary.generated_image_probability || 0) * 100)}%`)
        : "说说配图关闭";
      summaryBox.innerHTML = `
        <article data-state="${summary.life_publish_enabled ? "ready" : "idle"}"><span>生活说说</span><b>${summary.life_publish_enabled ? "开启" : "关闭"}</b></article>
        <article data-state="${summary.comment_inbox_enabled ? "ready" : "idle"}"><span>评论收件箱</span><b>${summary.comment_inbox_enabled ? "开启" : "关闭"}</b></article>
        <article data-state="info" title="${state.context.escapeHtml(imageMeta)}"><span>最近配图</span><b>${state.context.escapeHtml(imageLabel)}</b></article>
      `;
    }
  }

  function postAuthorName(post) {
    return post.author?.nickname || post.author?.uin || "QQ空间用户";
  }

  function renderPostIdentity(post) {
    const { escapeHtml } = state.context;
    const author = postAuthorName(post);
    const initial = Array.from(String(author).trim())[0] || "Q";
    return `
      <div class="qzone-post-identity">
        <span class="qzone-author-mark" aria-hidden="true">${escapeHtml(initial)}</span>
        <div>
          <b>${escapeHtml(author)}</b>
          <small>${escapeHtml(post.created_at_text || "刚刚")}</small>
        </div>
      </div>
    `;
  }

  function renderPostMetrics(post) {
    const { escapeHtml } = state.context;
    return `
      <div class="qzone-post-feedback" aria-label="互动数据">
        <span>${escapeHtml(post.stats?.likes ?? 0)} 赞</span>
        <span>${escapeHtml(post.stats?.comments ?? 0)} 评论</span>
      </div>
    `;
  }

  function qzoneImageItems(post) {
    const rawItems = Array.isArray(post?.image_items) && post.image_items.length
      ? post.image_items
      : (Array.isArray(post?.images) ? post.images : []);
    return rawItems.map((item) => {
      if (item && typeof item === "object") {
        const previewUrl = text(item.preview_url || item.thumbnail_url || item.thumb_url || item.url || item.src || item.image_url).trim();
        const fullUrl = text(item.full_url || item.original_url || item.origin_url || item.raw_url || item.large_url || item.url || item.src || item.image_url).trim();
        return { previewUrl: previewUrl || fullUrl, fullUrl: fullUrl || previewUrl };
      }
      const source = text(item).trim();
      return { previewUrl: source, fullUrl: source };
    }).filter((item) => item.previewUrl || item.fullUrl);
  }

  function renderPreviewImage(item, post) {
    const { escapeHtml } = state.context;
    const author = postAuthorName(post);
    const alt = `${author}的说说图片`;
    const meta = ["QQ 空间图片", author, post.created_at_text || "刚刚"].filter(Boolean).join(" · ");
    const previewUrl = text(item?.previewUrl).trim();
    const fullUrl = text(item?.fullUrl || previewUrl).trim();
    if (!previewUrl || !fullUrl) return "";
    return `<img class="qzone-preview-image" src="${escapeHtml(previewUrl)}" alt="${escapeHtml(alt)}" loading="lazy" data-qzone-preview-image data-qzone-preview-src="${escapeHtml(fullUrl)}" data-qzone-preview-fallback-src="${escapeHtml(previewUrl)}" data-qzone-preview-meta="${escapeHtml(meta)}" tabindex="0" role="button" title="点击放大预览，滚轮缩放" />`;
  }

  function openImagePreview(image) {
    if (!image || !state.context) return false;
    const preview = asteriaOutfit?.openImagePreview;
    const source = image.dataset.qzonePreviewSrc || image.currentSrc || image.src || image.getAttribute("src") || "";
    const fallbackSrc = image.dataset.qzonePreviewFallbackSrc || image.currentSrc || image.src || image.getAttribute("src") || "";
    if (!preview || !source) return false;
    return preview({ ...state.context, document }, {
      src: source,
      fallbackSrc,
      alt: image.alt || "QQ 空间图片",
      meta: image.dataset.qzonePreviewMeta || image.alt || "QQ 空间图片",
    });
  }

  function renderFeed() {
    const feed = document.getElementById("qzoneFeed");
    const meta = document.getElementById("qzoneFeedMeta");
    const feedState = document.getElementById("qzoneFeedState");
    if (!feed || !meta) return;
    if (feedState) {
      feedState.dataset.state = state.loading ? "loading" : (state.loaded ? "ready" : "idle");
      feedState.textContent = state.loading ? "同步中" : (state.loaded ? "已同步" : "待同步");
    }
    meta.textContent = state.loading
      ? "正在同步动态..."
      : `${state.scope === "profile" ? (state.targetUin || "指定 QQ") : state.scope === "friends" ? "好友动态" : "我的空间"} · ${state.posts.length} 条`;
    if (!state.posts.length) {
      feed.innerHTML = state.loading
        ? `<div class="qzone-feed-skeleton" role="status" aria-label="正在同步空间动态"><span></span><span></span><span></span></div>`
        : `<div class="qzone-empty"><b>暂无可显示的说说</b><span>可以先刷新，或切换到指定 QQ 试试。</span></div>`;
      renderDetail();
      return;
    }
    const { escapeHtml } = state.context;
    feed.innerHTML = state.posts.map((post) => `
      <article class="qzone-post-card ${state.selectedId === post.id ? "is-active" : ""}" data-qzone-open="${escapeHtml(post.id)}">
        <header>
          ${renderPostIdentity(post)}
          <span class="qzone-post-badge">${post.can_delete ? "我的说说" : "动态"}</span>
        </header>
        <p class="qzone-post-text">${escapeHtml(post.content || "无正文")}</p>
        ${qzoneImageItems(post).length ? `
          <div class="qzone-post-media">
            ${qzoneImageItems(post).slice(0, 4).map((item) => renderPreviewImage(item, post)).join("")}
          </div>
        ` : ""}
        <footer>
          ${renderPostMetrics(post)}
          <div class="qzone-post-actions">
            <button type="button" data-qzone-like="${escapeHtml(post.id)}" ${state.pendingLikes.has(post.id) || state.unconfirmed.has(`like:${post.id}`) ? "disabled" : ""}>点赞</button>
            <button type="button" data-qzone-open="${escapeHtml(post.id)}">评论</button>
            ${post.can_delete ? `<button type="button" class="danger-outline" data-qzone-delete="${escapeHtml(post.id)}" ${state.pendingDeletes.has(post.id) || state.unconfirmed.has(`delete:${post.id}`) ? "disabled" : ""}>删除</button>` : ""}
          </div>
        </footer>
      </article>
    `).join("");
    renderDetail();
  }

  function renderDetail() {
    const empty = document.getElementById("qzoneDetailEmpty");
    const detail = document.getElementById("qzoneDetailContent");
    if (!empty || !detail) return;
    const post = postById(state.selectedId);
    if (!post) {
      empty.hidden = false;
      detail.hidden = true;
      detail.innerHTML = "";
      return;
    }
    empty.hidden = true;
    detail.hidden = false;
    const oldInput = detail.querySelector("#qzoneCommentInput");
    const draft = detail.dataset.postId === post.id ? (oldInput?.value || "") : "";
    detail.dataset.postId = post.id;
    const { escapeHtml } = state.context;
    detail.innerHTML = `
      <div class="qzone-detail-card">
        <div class="qzone-detail-head">
          ${renderPostIdentity(post)}
          <div class="qzone-detail-actions">
            <button type="button" data-qzone-like="${escapeHtml(post.id)}" ${state.pendingLikes.has(post.id) || state.unconfirmed.has(`like:${post.id}`) ? "disabled" : ""}>点赞这条</button>
            ${post.can_delete ? `<button type="button" class="danger-outline" data-qzone-delete="${escapeHtml(post.id)}" ${state.pendingDeletes.has(post.id) || state.unconfirmed.has(`delete:${post.id}`) ? "disabled" : ""}>删除说说</button>` : ""}
          </div>
        </div>
        <p class="qzone-detail-text">${escapeHtml(post.content || "无正文")}</p>
        ${qzoneImageItems(post).length ? `
          <div class="qzone-detail-media">
            ${qzoneImageItems(post).map((item) => renderPreviewImage(item, post)).join("")}
          </div>
        ` : ""}
        ${renderPostMetrics(post)}
      </div>
      <div class="qzone-comment-block">
        <div class="qzone-comment-head">
          <b>当前返回的评论</b>
          <span>${escapeHtml(post.comments?.length ?? 0)} 条</span>
        </div>
        <div class="qzone-comment-list">
          ${(post.comments || []).length ? post.comments.map((comment) => `
            <article class="qzone-comment-item">
              <b>${escapeHtml(comment.author?.nickname || comment.author?.uin || "QQ空间用户")}</b>
              <p>${escapeHtml(comment.content || "")}</p>
            </article>
          `).join("") : `<div class="qzone-empty compact"><span>本次未返回评论，不代表全部历史为空。</span></div>`}
        </div>
        <form id="qzoneCommentForm" class="qzone-comment-form">
          <label for="qzoneCommentInput">评论到 QQ ${escapeHtml(post.author?.uin || "未知")} · ${escapeHtml(post.tid || post.id)}</label>
          <textarea id="qzoneCommentInput" rows="3" placeholder="写一条 QQ 空间评论（最多 120 字）">${escapeHtml(draft)}</textarea>
          <button type="submit" ${state.pendingComments.has(post.id) || state.unconfirmed.has(`comment:${post.id}`) ? "disabled" : ""}>发送到这条说说</button>
        </form>
      </div>
    `;
    const form = document.getElementById("qzoneCommentForm");
    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.getElementById("qzoneCommentInput");
      const content = input?.value || "";
      await sendComment(content);
    });
  }

  async function loadStatus(force = false) {
    if (state.status && !force) return state.status;
    try {
      state.status = await qzoneFetch(["/qzone/status", "/qzone/summary", "/qzone/state", "/qzone/health"]);
      renderAccount();
      return state.status;
    } catch (error) {
      state.status = state.status || { login: { bound: false, uin: 0, nickname: "", avatar: "" }, summary: { enabled: false, available: false } };
      setNotice(`状态加载失败：${error.message}`, "error");
      renderAccount();
      throw error;
    }
  }

  async function loadFeed(force = false) {
    if (state.scope === "profile" && !state.targetUin.trim()) {
      state.posts = [];
      state.loaded = false;
      state.loading = false;
      setNotice("输入 QQ 号后查看指定空间。", "warn");
      renderFeed();
      return state.posts;
    }
    if (state.loaded && !force) {
      renderFeed();
      return state.posts;
    }
    state.loading = true;
    setNotice("", "info");
    renderFeed();
    try {
      const params = new URLSearchParams();
      params.set("scope", state.scope);
      params.set("page", String(state.page || 1));
      if (state.scope === "profile" && state.targetUin.trim()) params.set("hostuin", state.targetUin.trim());
      const query = params.toString();
      const payload = await qzoneFetch([
        `/qzone/feed?${query}`,
        `/qzone/feeds?${query}`,
        `/qzone/list?${query}`,
      ]);
      state.posts = Array.isArray(payload.items) ? payload.items : [];
      state.loaded = true;
      if (!state.selectedId && state.posts[0]) state.selectedId = state.posts[0].id;
      renderAccount();
      renderFeed();
      return state.posts;
    } catch (error) {
      state.posts = [];
      state.loaded = false;
      state.selectedId = "";
      setNotice(`动态加载失败：${error.message}`, "error");
      renderFeed();
      throw error;
    } finally {
      state.loading = false;
      renderFeed();
    }
  }

  async function openDetail(id) {
    if (!id) return;
    state.selectedId = id;
    state.detailLoadingId = id;
    renderFeed();
    try {
      const encodedId = encodeURIComponent(id);
      const payload = await qzoneFetch([
        `/qzone/detail?id=${encodedId}`,
        `/qzone/post?id=${encodedId}`,
        `/qzone/item?id=${encodedId}`,
      ]);
      const post = payload.post;
      if (post) {
        state.posts = state.posts.map((item) => (item.id === id ? post : item));
      }
    } finally {
      state.detailLoadingId = "";
      renderFeed();
    }
  }

  async function likePost(id) {
    const post = postById(id), key = `like:${id}`;
    if (!post || state.pendingLikes.has(id) || state.unconfirmed.has(key)) return;
    state.pendingLikes.add(id); renderFeed();
    try {
      const payload = await qzonePost("/qzone/like", { id });
      if (payload?.id !== id || typeof payload.liked !== "boolean" || typeof payload.verified !== "boolean") throw Error("点赞返回目标或字段不匹配");
      if (payload.verified) {
        state.posts = state.posts.map(item => item.id === id ? { ...item, liked: payload.liked } : item);
        recordAction(key, payload.liked ? "点赞已反查确认" : "反查未确认已点赞", payload.liked ? "success" : "warn", `目标 ${id} · ${payload.verify_message || "点赞数量仍为上次读取值"}`);
      } else {
        state.unconfirmed.add(key);
        recordAction(key, "点赞请求已返回，尚未反查确认", "warn", `目标 ${id} · ${payload.verify_message || "请先到 QQ 空间核实"}`);
      }
      state.context.showToast(payload.verified ? "已取得点赞反查结果" : "点赞尚未反查确认", payload.verified ? "success" : "warn");
    } catch (error) { unknownAction(key, "点赞", error); }
    finally { state.pendingLikes.delete(id); renderFeed(); }
  }

  async function sendComment(content) {
    const post = postById(state.selectedId), value = text(content).trim();
    if (!post || !value) return;
    if (Array.from(value).length > 120) { state.context.showToast("评论最多 120 字，请缩短后再发送；当前内容保留", "warn"); return; }
    const id = post.id, key = `comment:${id}`;
    if (state.pendingComments.has(id) || state.unconfirmed.has(key)) return;
    state.pendingComments.add(id); renderDetail();
    recordAction(key, "正在发送评论", "pending", `目标 ${id}`);
    try {
      const payload = await qzonePost("/qzone/comment", { id, content: value });
      if (payload?.post?.id !== id || !Array.isArray(payload.post.comments)) throw Error("评论返回目标或字段不匹配");
      state.posts = state.posts.map(item => item.id === id ? payload.post : item);
      const input = document.getElementById("qzoneCommentInput");
      if (state.selectedId === id && input?.value === content) input.value = "";
      recordAction(key, "评论发送接口已返回成功", "success", `目标 ${id} · 新评论由服务端在本次结果中补入，非完整评论历史或额外反查证明。`);
      state.context.showToast("评论发送接口已返回成功");
    } catch (error) { unknownAction(key, "评论", error); }
    finally { state.pendingComments.delete(id); renderFeed(); }
  }

  function confirmDeletePost(id, button = null) {
    const now = Date.now();
    if (state.deleteConfirmId === id && now - state.deleteConfirmAt <= 6000) return true;
    state.deleteConfirmId = id;
    state.deleteConfirmAt = now;
    if (button) {
      if (!button.dataset.originalText) button.dataset.originalText = button.textContent || "删除";
      button.textContent = "再次点击删除";
      button.classList.add("is-confirming");
      window.setTimeout(() => {
        if (state.deleteConfirmId === id && Date.now() - state.deleteConfirmAt >= 5900) {
          state.deleteConfirmId = "";
          state.deleteConfirmAt = 0;
        }
        if (button.isConnected && button.dataset.originalText) {
          button.textContent = button.dataset.originalText;
          delete button.dataset.originalText;
          button.classList.remove("is-confirming");
        }
      }, 6000);
    }
    state.context.showToast("再次点击会删除这条说说", "warn");
    return false;
  }

  async function deletePost(id, button = null) {
    const cleanId = text(id).trim();
    if (!cleanId) {
      state.context.showToast("没有拿到说说 ID，请刷新动态后重试", "error");
      return;
    }
    const post = postById(cleanId);
    if (!post) {
      state.context.showToast("这条说说的页面引用已失效，请刷新动态后重试", "error");
      return;
    }
    if (!post.can_delete) {
      state.context.showToast("只能删除当前登录 QQ 自己发布的说说", "error");
      return;
    }
    if (state.pendingDeletes.has(cleanId) || state.unconfirmed.has(`delete:${cleanId}`)) return;
    if (!confirmDeletePost(cleanId, button)) return;
    state.deleteConfirmId = "";
    state.deleteConfirmAt = 0;
    state.pendingDeletes.add(cleanId);
    renderFeed();
    try {
      state.context.showToast("正在删除说说...");
      const payload = await qzonePost("/qzone/delete", { id: cleanId });
      if (payload?.deleted !== true || payload.id !== cleanId) throw Error("删除返回目标或字段不匹配");
      recordAction(`delete:${cleanId}`, "删除接口已返回成功", "success", `目标 ${cleanId} · 删除当前登录 QQ 的这条说说，不是仅移除本页卡片。`);
      state.posts = state.posts.filter((item) => item.id !== cleanId);
      if (state.selectedId === cleanId) state.selectedId = state.posts[0]?.id || "";
      state.context.showToast("说说已删除");
    } catch (error) {
      unknownAction(`delete:${cleanId}`, "删除", error);
    } finally {
      state.pendingDeletes.delete(cleanId);
      renderAccount();
      renderFeed();
    }
  }

  async function publish() {
    if (state.publishing || state.unconfirmed.has("publish")) return;
    const input = document.getElementById("qzonePublishContent"), submitted = text(input?.value), content = submitted.trim();
    if (!content || Array.from(content).length > 300) {
      state.context.showToast(content ? "说说最多 300 字，请缩短后再发布；当前内容保留" : "说说内容不能为空", "warn"); return;
    }
    state.publishing = true;
    recordAction("publish", "正在发布到 QQ 空间", "pending", "沿原配置可能生成配图，请等待当前结果。");
    try {
      const payload = await qzonePost("/qzone/publish", { content });
      if (payload?.success !== true || !text(payload.tid) || !text(payload.uin) || typeof payload.verified !== "boolean") throw Error("发布返回缺少目标或验证结果");
      const target = `QQ ${payload.uin} · 说说 ${payload.tid}`;
      if (payload.verified) {
        if (input?.value === submitted) input.value = "";
        recordAction("publish", "发布已反查确认", "success", `${target} · ${payload.verify_message || "发布内容已在反查结果中匹配"}${payload.image_fallback ? "；配图失败后按原规则改为纯文字" : ""}`);
        state.context.showToast("发布已反查确认；可手动刷新动态查看");
      } else {
        state.unconfirmed.add("publish");
        recordAction("publish", "发布接口已返回成功，尚未反查确认", "warn", `${target} · ${payload.verify_message || "请先到 QQ 空间核实"}`);
        state.context.showToast("发布尚未反查确认，保留输入，请先核实", "warn");
      }
    } catch (error) { unknownAction("publish", "发布", error); }
    finally {
      state.publishing = false;
      const button = document.querySelector("#qzonePublishForm button[type=submit]");
      if (button) button.disabled = state.unconfirmed.has("publish");
    }
  }

  function bindDeleteEvents() {
    const panel = document.getElementById("panel-qzone");
    if (!panel || panel.dataset.qzoneDeleteBound === "1") return;
    panel.dataset.qzoneDeleteBound = "1";
    panel.addEventListener("click", async (event) => {
      const element = event.target instanceof Element ? event.target : null;
      const deleteButton = element?.closest("[data-qzone-delete]");
      if (!deleteButton || !panel.contains(deleteButton)) return;
      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
      await deletePost(deleteButton.dataset.qzoneDelete || "", deleteButton);
    }, true);
  }

  function bindEvents() {
    const panel = document.getElementById("panel-qzone");
    if (!panel || panel.dataset.bound === "1") return;
    panel.dataset.bound = "1";
    panel.addEventListener("click", async (event) => {
      const element = event.target instanceof Element ? event.target : null;
      const previewImage = element?.closest("[data-qzone-preview-image]");
      if (previewImage && panel.contains(previewImage)) {
        event.preventDefault();
        event.stopPropagation();
        openImagePreview(previewImage);
        return;
      }
      const like = element?.closest("[data-qzone-like]");
      if (like) {
        await likePost(like.dataset.qzoneLike || "");
        return;
      }
      const deleteButton = element?.closest("[data-qzone-delete]");
      if (deleteButton) {
        event.preventDefault();
        event.stopPropagation();
        await deletePost(deleteButton.dataset.qzoneDelete || "", deleteButton);
        return;
      }
      const open = element?.closest("[data-qzone-open]");
      if (open) {
        await openDetail(open.dataset.qzoneOpen || "");
        return;
      }
      const scopeButton = element?.closest("[data-qzone-scope]");
      if (scopeButton) {
        state.scope = scopeButton.dataset.qzoneScope || "self";
        state.page = 1;
        document.querySelectorAll("[data-qzone-scope]").forEach((item) => {
          const active = item === scopeButton;
          item.classList.toggle("active", active);
          item.setAttribute("aria-pressed", String(active));
        });
        state.loaded = false;
        try {
          await loadFeed(true);
        } catch (error) {
          state.context.showToast(`动态加载失败：${error.message}`, "error");
        }
        return;
      }
    });
    panel.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const element = event.target instanceof Element ? event.target : null;
      const previewImage = element?.closest("[data-qzone-preview-image]");
      if (!previewImage || !panel.contains(previewImage)) return;
      event.preventDefault();
      event.stopPropagation();
      openImagePreview(previewImage);
    });
    document.getElementById("qzoneTargetForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const target = document.getElementById("qzoneTargetUin");
      state.targetUin = text(target?.value).trim();
      state.scope = "profile";
      state.page = 1;
      document.querySelectorAll("[data-qzone-scope]").forEach((item) => {
        const active = item.dataset.qzoneScope === "profile";
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      state.loaded = false;
      try {
        await loadFeed(true);
      } catch (error) {
        state.context.showToast(`查询失败：${error.message}`, "error");
      }
    });
    document.getElementById("qzonePublishForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      await publish();
    });
    document.getElementById("qzoneRefreshBtn")?.addEventListener("click", async () => {
      try {
        await loadStatus(true);
        await loadFeed(true);
      } catch (error) {
        state.context.showToast(`刷新失败：${error.message}`, "error");
      }
    });
    document.getElementById("qzoneRefreshCookiesBtn")?.addEventListener("click", async () => {
      if (state.unconfirmed.has("cookies") || state.actionResults.get("cookies")?.tone === "pending") return;
      recordAction("cookies", "正在刷新登录凭据", "pending");
      try {
        const payload = await refreshCookies();
        if (payload?.refreshed !== true || !Number(payload.uin) || typeof payload.has_skey !== "boolean" || typeof payload.has_p_skey !== "boolean") throw Error("凭据刷新结果不完整");
        recordAction("cookies", "登录凭据刷新接口已返回成功", "success", `QQ ${payload.uin} · 尚未证明动态可访问。需要时手动刷新动态，不会自动发布。`);
        state.context.showToast("凭据刷新已返回，可手动读取动态核实访问");
      } catch (error) { unknownAction("cookies", "凭据刷新", error); }
    });
    document.getElementById("qzoneAccountAvatar")?.addEventListener("error", (event) => {
      const avatar = event.currentTarget;
      const avatarFallback = document.getElementById("qzoneAccountAvatarFallback");
      avatar.hidden = true;
      if (avatarFallback) avatarFallback.hidden = false;
    });
  }

  async function render(context) {
    state.context = context;
    bindDeleteEvents();
    bindEvents();
    renderAccount();
    renderFeed();
    try {
      await loadStatus();
      await loadFeed();
    } catch (error) {
      setNotice(error.message || "QQ 空间面板初始化失败", "error");
    }
  }

  return { render };
})();

export default panel;
