/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {showMemory} from './configuration.js';
import {showInjectionLogDetail} from './editors.js';
import {hasMemoryType,relationTypesForSecondary,renderMemoryList,scopedMemoryParams,syncUserMemoryFilterControls} from './memory.js';
import {contextParams,selectSecondaryNav} from './overview.js';
import {loadPersonaState} from './personal.js';
import {loadPortraitGovernance} from './portraits.js';
import {$,KNOWLEDGE_SECTIONS,asteriaWorkspaceState,state} from './state.js';
import {activeBucket,activeSecondaryNav,compact,escapeHtml,formatTime,loadingState,mentionPolicyLabel,shortId,withButton} from './workspace.js';

export function knowledgeScopeKey() { return contextParams({}).toString(); }

export function knowledgeCurrent(view) {
  return asteriaWorkspaceState.knowledgeBrowse === view && state.activeView === "objects"
    && activeSecondaryNav("objects") === view.section && knowledgeScopeKey() === view.scope;
}

export async function loadContextPanel(options = {}) {
  const target = $("#contextPanel");
  if (!target) return false;
  const section = activeSecondaryNav("objects"), scope = knowledgeScopeKey();
  const serial = ++asteriaWorkspaceState.knowledgeReadSerial;
  const prior = options.preserve && asteriaWorkspaceState.knowledgeBrowse?.section === section && asteriaWorkspaceState.knowledgeBrowse?.scope === scope ? asteriaWorkspaceState.knowledgeBrowse : null;
  const current = () => serial === asteriaWorkspaceState.knowledgeReadSerial && state.activeView === "objects" && activeSecondaryNav("objects") === section && knowledgeScopeKey() === scope;
  target.className = "page-panel-stack";
  if (!prior) target.innerHTML = loadingState("正在读取知识关联...");
  if (section === "persona") {
    asteriaWorkspaceState.knowledgeBrowse = null;
    target.innerHTML = `<div id="personaStatePanel" class="persona-state-panel"></div>`;
    await loadPersonaState();
    return true;
  }
  const params = contextParams({ limit: section === "overview" ? 8 : 60 });
  const read = async (key) => {
    const query = new URLSearchParams(params);
    if (key === "threads") query.set("status", "all");
    const data = await apiGet(`${KNOWLEDGE_SECTIONS[key].path}?${query.toString()}`);
    return Array.isArray(data.items) ? data.items : [];
  };
  try {
    if (section === "overview") {
      const keys = Object.keys(KNOWLEDGE_SECTIONS);
      const results = await Promise.allSettled(keys.map(read));
      if (!current()) return false;
      asteriaWorkspaceState.knowledgeBrowse = null;
      target.innerHTML = `<section class="knowledge-workspace knowledge-overview"><h4>知识关联概览</h4>
        <p class="knowledge-note">每类最多 8 条近期记录，是本次读取窗口，不是全库数量。进入分类后可查看来源、查找记录。</p>
        <div class="knowledge-categories">${keys.map((key, i) => {
          const info = KNOWLEDGE_SECTIONS[key], result = results[i];
          return `<button type="button" data-knowledge-section="${key}"><b>${info.title}</b><strong>${result.status === "fulfilled" ? `本次 ${result.value.length} 条` : "未读取"}</strong>
            <span>${escapeHtml(result.status === "fulfilled" ? info.note : result.reason?.message || "读取失败")}</span><small>查看此类记录 →</small></button>`;
        }).join("")}</div><p class="knowledge-note">各类沿用原查询范围；范围与会话限制在分类内单独说明。互动协同保留在原入口。</p></section>`;
      target.querySelectorAll("[data-knowledge-section]").forEach(button => button.addEventListener("click", () => selectSecondaryNav(button.dataset.knowledgeSection)));
      return true;
    }
    const items = await read(section);
    if (!current()) return false;
    asteriaWorkspaceState.knowledgeBrowse = { section, scope, items, query: prior?.query || "", filter: prior?.filter || "", page: prior?.page || 1,
      notice: options.notice || "", blocked: false, busy: false, reading: false };
    renderKnowledgeWorkspace();
    return true;
  } catch (error) {
    if (!current()) return false;
    if (prior) {
      prior.reading = false;
      prior.notice = `${options.failurePrefix || "列表读取失败"}：${error.message}。保留上次读取的记录，请先只读核对。`;
      prior.blocked = true;
      renderKnowledgeWorkspace();
    } else {
      asteriaWorkspaceState.knowledgeBrowse = null;
      target.innerHTML = `<section class="knowledge-workspace"><h4>记录读取失败</h4><p class="knowledge-note">${escapeHtml(error.message)}</p><button type="button" data-knowledge-retry>重新读取</button></section>`;
      target.querySelector("[data-knowledge-retry]").addEventListener("click", () => loadContextPanel());
    }
    return false;
  }
}

export function knowledgeType(section, item) {
  if (section === "threads") return item.status || "open";
  if (section === "timeline") return item.event_type || "未分类";
  if (section === "logs") return item.scope || "未记录范围";
  return item.relation_type || "未分类";
}

export function knowledgeTypeLabel(value) { return ({ open: "待续", closed: "已完成" })[value] || value; }

export function knowledgeTitle(section, item) {
  if (section === "relations") return `${item.source_label || "未知节点"} → ${item.target_label || "未知节点"}`;
  if (section === "identity-relations") return `${item.subject_name || item.subject_id || "未知对象"} → ${item.object_name || item.object_id || "未知对象"}`;
  if (section === "threads") return item.topic || "未命名线程";
  if (section === "timeline") return compact(item.content, "空时间线记录");
  return item.query || "未记录查询文本";
}

export function knowledgeFields(item) {
  const labels = { id: "记录标识", scope: "范围", session_id: "会话", group_id: "群标识", entity_id: "对象标识", source_type: "起点类型", target_type: "终点类型",
    subject_id: "主体标识", object_id: "关联对象", source_memory_id: "来源记忆", from_session: "起点会话", to_session: "终点会话", visibility: "可见性标记",
    confidence: "记录置信度", review_status: "审核标记", occurred_at: "发生时间", created_at: "记录时间", updated_at: "更新时间" };
  return `<dl class="knowledge-fields">${Object.entries(labels).filter(([key]) => item[key] !== undefined && item[key] !== null && item[key] !== "")
    .map(([key, label]) => `<div><dt>${label}</dt><dd>${escapeHtml(String(item[key]))}</dd></div>`).join("")}</dl>`;
}

export function knowledgeRecord(view, item) {
  const type = knowledgeType(view.section, item), title = knowledgeTitle(view.section, item);
  const body = view.section === "threads" || view.section === "timeline" ? item.content : view.section === "logs" ? item.query : item.evidence;
  return `<details class="knowledge-record" data-knowledge-row><summary><b>${escapeHtml(title)}</b><span>${escapeHtml(knowledgeTypeLabel(type))} · ${escapeHtml(formatTime(item.occurred_at || item.updated_at || item.created_at))}</span></summary>
    <div class="knowledge-reading"><p>${escapeHtml(body || "没有记录正文或依据")}</p>${knowledgeFields(item)}
      ${item.source_memory_id ? `<button type="button" data-knowledge-source="${escapeHtml(item.source_memory_id)}">查看当前来源记忆</button><p class="knowledge-note">打开当前版本；来源若已删除或无权读取，会显示原接口结果。历史关联仍保留。</p>` : ""}
      ${view.section === "logs" ? `<button type="button" data-knowledge-log="${escapeHtml(item.id)}">查看选中资料与过滤原因</button>` : ""}
      ${view.section === "threads" ? `<details class="knowledge-maintenance" data-knowledge-maintenance><summary>维护这条线程</summary>
        <p class="knowledge-note">只改变此记录的完成状态，保留内容、来源和会话关联；不发送或撤回消息，不取消后台任务。</p>
        <button type="button" data-thread-id="${escapeHtml(item.id)}" data-thread-next-status="${item.status === "closed" ? "open" : "closed"}"${view.busy || view.blocked || view.reading ? " disabled" : ""}>${item.status === "closed" ? "重新打开" : "标记完成"}</button></details>` : ""}
      <details class="knowledge-raw"><summary>原始记录与附加字段</summary><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></details>
    </div></details>`;
}

export function renderKnowledgeWorkspace() {
  const view = asteriaWorkspaceState.knowledgeBrowse, target = $("#contextPanel");
  if (!view || !target || !knowledgeCurrent(view)) return;
  const info = KNOWLEDGE_SECTIONS[view.section];
  target.innerHTML = `<section class="knowledge-workspace"><header class="knowledge-head"><h4>${info.title}</h4><button type="button" data-knowledge-refresh${view.busy || view.reading ? " disabled" : ""}>${view.reading ? "读取中…" : view.blocked ? "只读核对" : "刷新记录"}</button></header>
    <p class="knowledge-note">${info.note}</p><p class="knowledge-note">原查询最多 60 条近期记录，本次 ${view.items.length} 条；搜索、分类和分页仅作用于本次窗口。${info.range}</p>
    <p class="knowledge-status" data-knowledge-status role="status">${escapeHtml(view.notice)}</p>
    <div class="knowledge-filters"><label>查找本次记录<input type="search" data-knowledge-query value="${escapeHtml(view.query)}" placeholder="内容、标识、来源或会话" /></label><label>${view.section === "threads" ? "完成状态" : "记录分类"}<select data-knowledge-filter><option value="">全部</option>${Array.from(new Set(view.items.map(item => knowledgeType(view.section, item)))).sort().map(value => `<option value="${escapeHtml(value)}"${view.filter === value ? " selected" : ""}>${escapeHtml(knowledgeTypeLabel(value))}</option>`).join("")}</select></label></div>
    <div data-knowledge-results></div></section>`;
  target.querySelector("[data-knowledge-query]").addEventListener("input", event => { view.query = event.target.value; view.page = 1; renderKnowledgeResults(view); });
  target.querySelector("[data-knowledge-filter]").addEventListener("change", event => { view.filter = event.target.value; view.page = 1; renderKnowledgeResults(view); });
  target.querySelector("[data-knowledge-refresh]").addEventListener("click", () => {
    if (view.busy || view.reading) return;
    view.reading = true;
    renderKnowledgeWorkspace();
    loadContextPanel({ preserve: true, notice: "列表已重新读取，请按当前记录核对结果。" });
  });
  renderKnowledgeResults(view);
}

export function renderKnowledgeResults(view) {
  if (!knowledgeCurrent(view)) return;
  const target = $("#contextPanel [data-knowledge-results]");
  if (!target) return;
  const query = view.query.trim().toLocaleLowerCase();
  const items = view.items.filter(item => (!view.filter || knowledgeType(view.section, item) === view.filter) && (!query || JSON.stringify(item).toLocaleLowerCase().includes(query)));
  const pages = Math.max(1, Math.ceil(items.length / 12));
  view.page = Math.min(pages, Math.max(1, view.page));
  target.innerHTML = `<p class="knowledge-note">匹配 ${items.length} / ${view.items.length} 条</p><div class="knowledge-records">${items.length ? items.slice((view.page - 1) * 12, view.page * 12).map(item => knowledgeRecord(view, item)).join("") : `<p class="empty-state">${view.items.length ? "本次窗口没有匹配记录，可调整查找条件。" : "本次查询没有返回记录。"}</p>`}</div>
    <div class="knowledge-pages"><button type="button" data-knowledge-page="prev"${view.page === 1 ? " disabled" : ""}>上一页</button><span>${view.page} / ${pages} 页 · 每页 12 条</span><button type="button" data-knowledge-page="next"${view.page === pages ? " disabled" : ""}>下一页</button></div>`;
  target.querySelectorAll("[data-knowledge-page]").forEach(button => button.addEventListener("click", () => { view.page += button.dataset.knowledgePage === "next" ? 1 : -1; renderKnowledgeResults(view); }));
  target.querySelectorAll("[data-knowledge-source]").forEach(button => button.addEventListener("click", () => withButton(button, "读取中", () => showMemory(button.dataset.knowledgeSource))));
  target.querySelectorAll("[data-knowledge-log]").forEach(button => button.addEventListener("click", () => showInjectionLogDetail(view.items.find(item => String(item.id) === button.dataset.knowledgeLog))));
  target.querySelectorAll("[data-thread-id]").forEach(button => button.addEventListener("click", () => updateThreadStatus(button.dataset.threadId, button.dataset.threadNextStatus, view)));
}

export async function updateThreadStatus(id, status, view = asteriaWorkspaceState.knowledgeBrowse) {
  if (!view || !knowledgeCurrent(view) || view.section !== "threads" || view.busy || view.reading || view.blocked) return;
  view.busy = true;
  view.notice = "正在更新这条线程…";
  renderKnowledgeWorkspace();
  let result;
  try { result = await apiPost("/thread/status", { id, status }); }
  catch (error) {
    if (!knowledgeCurrent(view)) return;
    view.busy = false;
    view.blocked = true;
    view.notice = `结果未确认：${error.message}。请先只读核对，不自动重复提交。`;
    renderKnowledgeWorkspace();
    return;
  }
  if (!knowledgeCurrent(view)) return;
  view.busy = false;
  if (result.updated !== true) {
    view.notice = "未确认更新：线程可能已不存在或未更新。保留原记录，请只读核对。";
    view.blocked = true;
    renderKnowledgeWorkspace();
    return;
  }
  const action = status === "closed" ? "已标记完成" : "已重新打开";
  view.notice = `${action}，正在重新读取列表…`;
  view.reading = true;
  renderKnowledgeWorkspace();
  await loadContextPanel({ preserve: true, notice: `${action}，列表已重新读取。`, failurePrefix: `${action}，列表回读失败` });
}

export function boolLabel(value) {
  return value ? "开启" : "关闭";
}

export function queryModeLabel(mode) {
  if (mode === "guarded_companion") return "受保护陪伴";
  if (mode === "companion_augmented") return "增强检索";
  return "当前消息";
}

export function queryModeNote(mode) {
  if (mode === "guarded_companion") return "线索与当前消息重叠时才扩展检索";
  if (mode === "companion_augmented") return "直接拼接陪伴线索，适合强联动场景";
  return "只用当前用户消息检索，记忆作为附加资料";
}

export function queryModeTone(mode) {
  if (mode === "companion_augmented") return "gold";
  if (mode === "guarded_companion") return "teal";
  return "blue";
}

export function retrievalModeLabel(mode) {
  if (mode === "basic") return "本地检索";
  if (mode === "rerank") return "强制重排";
  return "自动选择";
}

export function retrievalModeNote(retrieval = {}) {
  const mode = retrieval.mode || "auto";
  const provider = retrieval.rerank_provider_id || "自动探测";
  const limit = retrieval.rerank_candidate_limit ?? 32;
  if (mode === "basic") return "不额外调用重排模型，完全使用本地可解释排序";
  if (mode === "rerank") return `Provider ${provider} · 候选上限 ${limit}`;
  return `有 rerank provider 时二阶段重排，否则回退本地 · 候选上限 ${limit}`;
}

export function retrievalModeTone(mode) {
  if (mode === "basic") return "blue";
  if (mode === "rerank") return "violet";
  return "teal";
}

export function providerStateLabel(current, hasProvider, enabled = true) {
  if (!enabled) return "未启用";
  if (current) return current;
  return hasProvider ? "自动探测" : "未检测到";
}

export function configCard(title, value, note, tone = "blue", badge = "配置") {
  return `
    <article class="config-card">
      <div class="config-card-top">
        <span class="item-title">${escapeHtml(title)}</span>
        <span class="badge ${escapeHtml(tone)}">${escapeHtml(badge)}</span>
      </div>
      <b>${escapeHtml(value)}</b>
      <small>${escapeHtml(note)}</small>
    </article>
  `;
}

export function contextSwitch(name, checked = false) {
  return `
    <label class="context-switch">
      <input name="${escapeHtml(name)}" type="checkbox"${checked ? " checked" : ""} />
      <span></span>
    </label>
  `;
}

export function contextField({ label, hint, control, wide = false }) {
  return `
    <div class="context-form-row${wide ? " is-wide" : ""}">
      <span>
        <b>${escapeHtml(label)}</b>
        <small>${escapeHtml(hint)}</small>
      </span>
      <div class="context-control">${control}</div>
    </div>
  `;
}

export function blockedReasonLabel(reason) {
  const text = String(reason || "");
  if (text.includes("private_pair_not_current_private")) return "私聊隔离";
  if (text.includes("other_group_public")) return "其他群聊";
  if (text.includes("prefiltered_out_of_search_range")) return "范围外";
  if (text.includes("companion_current_state_overlap")) return "陪伴状态重叠";
  if (text.includes("mention_policy")) return "提及边界";
  if (text.includes("current_state_relevance_guard")) return "当前状态保护";
  if (text.includes("not_visible") || text.includes("visibility")) return "可见性";
  if (text.includes("duplicate") || text.includes("redundant")) return "重复折叠";
  return text.split(":")[0].replaceAll("_", " ") || "过滤";
}

export function blockedReasonBadges(blocked = []) {
  const counts = new Map();
  blocked.forEach((item) => {
    const label = blockedReasonLabel(item.reason || item);
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([label, count]) => `<span class="badge ${count > 20 ? "red" : "teal"}">${escapeHtml(label)} ${escapeHtml(count)}</span>`)
    .join("");
}

export function renderSelectedMemoryChips(memories = [], limit = 4) {
  return memories.slice(0, limit).map((memory) => {
    const title = compact(memory.canonical_summary || memory.content, memory.id);
    const policy = memory.mention_policy || "";
    return `
      <span class="memory-chip" title="${escapeHtml(title)}">
        ${escapeHtml(compact(memory.memory_type, "memory"))}
        ${policy ? `<small>${escapeHtml(mentionPolicyLabel(policy))}</small>` : ""}
      </span>
    `;
  }).join("");
}

export function renderContextLogs(logs) {
  return `
    <section class="context-section context-logs film-panel">
      <div class="personal-zone-head">
        <h4>最近注入记录</h4>
        <span>${escapeHtml(logs.length)} Frames</span>
      </div>
      <div class="row-list">
        ${logs.length ? logs.map((item) => `
          <article class="row-item memory-frame" data-raw="${escapeHtml(JSON.stringify(item))}" data-detail-title="注入记录详情">
            <div class="memory-frame-time">
              <b>${escapeHtml(formatTime(item.created_at))}</b>
              <span>${escapeHtml(item.scope || "unknown")}</span>
            </div>
            <div class="memory-frame-main">
              <div class="memory-frame-text">
                <span class="item-title">${escapeHtml(item.query || "未记录查询文本")}</span>
                <div class="memory-chip-row">${renderSelectedMemoryChips(item.selected_memories || [])}</div>
              </div>
              <div class="badges">
                <span class="badge blue">选中 ${escapeHtml((item.selected_memory_ids || []).length)} 条</span>
                <span class="badge teal">过滤 ${escapeHtml((item.blocked_reasons || []).length)} 条</span>
                <span class="badge gold">${escapeHtml(shortId(item.session_id || "-"))}</span>
                ${blockedReasonBadges(item.blocked_reasons || [])}
              </div>
            </div>
          </article>
        `).join("") : `<div class="empty-state">当前范围还没有注入日志。</div>`}
      </div>
    </section>
  `;
}

export async function loadUserMemory() {
  const target = $("#relationList");
  if (!target) return;
  syncUserMemoryFilterControls();
  target.innerHTML = loadingState("正在读取用户档案与记忆...");
  await loadPortraitGovernance();
  const types = relationTypesForSecondary();
  const { params, incompatible } = scopedMemoryParams("private", { limit: 180 });
  if (incompatible) {
    target.innerHTML = '<div class="empty-state">当前对象不是私聊用户，请从左侧选择用户。</div>';
    return;
  }
  // 用户工作区按精确用户身份聚合其全部私聊窗口；会话 ID 只用于旧私聊入口，
  // 不能把同一用户在其他私聊窗口中的画像/偏好切掉。
  if (activeBucket()?.target_id) params.delete("session_id");
  const data = await apiGet(`/memories?${params.toString()}`);
  const allMemories = data.memories || [];
  let memories = allMemories;
  if (types.length) memories = allMemories.filter((memory) => hasMemoryType(memory, types));
  if (state.userMemoryFilter === 'private') {
    memories = allMemories.filter((memory) => memory.scope === 'private');
  }
  renderMemoryList("#relationList", memories, "当前用户在这个分类下还没有记忆。", 180);
}
