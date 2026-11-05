/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {showMemory} from './configuration.js';
import {blockedReasonBadges,blockedReasonLabel} from './knowledge.js';
import {loadHistoricalChatBatchList,refreshAll,renderHistoricalChatPreview,setHistoricalChatStep} from './maintenance.js';
import {loadActiveView} from './memory.js';
import {loadStats,normalizeBuckets} from './overview.js';
import {$,$$,state} from './state.js';
import {compact,decayModeLabel,dimensionLabel,escapeHtml,formatTime,isWindowBucket,mentionPolicyLabel,number,percentLabel,personaWeights,reactionLabel,shortId,showToast,withBusy,withButton} from './workspace.js';

export function renderMemoryRevisions(history, open = false) {
  if (!history?.total) return "";
  const items = history.items || [];
  const offset = Number(history.offset) || 0;
  return `<details class="memory-raw-detail"${open ? " open" : ""}>
    <summary>修改历史 · ${Number(history.total)} 次（历史版本不参与召回）</summary>
    ${items.map(item => `<section class="memory-structured-block">
      <b>第 ${Number(item.revision)} 次修改前</b>
      <p class="item-meta">${escapeHtml(formatTime(item.created_at))} · ${escapeHtml(item.actor === "astrbot_admin" ? "后台手动修改" : item.actor)}</p>
      <p style="white-space:pre-wrap;overflow-wrap:anywhere">${escapeHtml(item.before?.content || "")}</p>
      <details><summary>当时的证据与来源</summary><pre>${escapeHtml(JSON.stringify({ evidence: item.before?.evidence, source: item.before?.source_plugin, metadata: item.before?.metadata }, null, 2))}</pre></details>
    </section>`).join("")}
    ${offset ? `<button type="button" data-revision-offset="${Math.max(0, offset - 10)}">较新的修改</button>` : ""}
    ${offset + items.length < history.total ? `<button type="button" data-revision-offset="${offset + items.length}">更早的修改</button>` : ""}
  </details>`;
}

export function displayMemoryMetadata(memory) {
  const metadata = { ...(memory.metadata || {}) };
  const timeRange = memory.time_range || {};
  if (metadata.start_at && !metadata.start_at_local) {
    metadata.start_at_local = timeRange.start_at_local || formatTime(metadata.start_at);
  }
  if (metadata.end_at && !metadata.end_at_local) {
    metadata.end_at_local = timeRange.end_at_local || formatTime(metadata.end_at);
  }
  if ((metadata.start_at || metadata.end_at) && !metadata.timezone) {
    metadata.timezone = timeRange.timezone || "Asia/Shanghai";
  }
  return metadata;
}

export function renderMemoryStructuredMetadata(memory) {
  const metadata = memory.metadata || {};
  const timeRange = memory.time_range || {};
  const startLocal = compact(timeRange.start_at_local || metadata.start_at_local, "");
  const endLocal = compact(timeRange.end_at_local || metadata.end_at_local, "");
  const hasTimeRange = Boolean(startLocal || endLocal || metadata.start_at || metadata.end_at);
  const keyFacts = Array.isArray(metadata.key_facts) ? metadata.key_facts.filter(Boolean) : [];
  const routineCheckNotes = Array.isArray(metadata.routine_check_notes) ? metadata.routine_check_notes.filter(Boolean) : [];
  const topics = Array.isArray(metadata.topics) ? metadata.topics.filter(Boolean) : [];
  const participants = Array.isArray(metadata.participants) ? metadata.participants.filter(Boolean) : [];
  const canonical = compact(metadata.canonical_summary, "");
  const policy = memory.mention_policy || metadata.mention_policy || "";
  const mentionability = memory.mentionability_score ?? metadata.mentionability_score;
  const memoryReason = memory.memory_reason || metadata.memory_reason || "";
  const phase = memory.relationship_phase || metadata.relationship_phase || "";
  const decayMode = memory.decay_mode || metadata.decay_mode || "";
  const activeDimensions = Array.isArray(memory.active_dimensions) && memory.active_dimensions.length
    ? memory.active_dimensions
    : (Array.isArray(metadata.active_dimensions) ? metadata.active_dimensions : []);
  const weights = personaWeights(memory).sort((a, b) => b.value - a.value);
  const feedback = memory.mention_feedback || metadata.mention_feedback || {};
  const correction = metadata.user_correction || {};
  const hasPersona = policy || memoryReason || phase || decayMode || activeDimensions.length || weights.length || feedback.last_reaction || correction.text;
  if (!hasTimeRange && !keyFacts.length && !routineCheckNotes.length && !topics.length && !participants.length && !canonical && !hasPersona) return "";
  return `
    <section class="memory-structured-panel">
      ${hasTimeRange ? `
        <div class="memory-structured-block">
          <b>总结范围</b>
          <p>${escapeHtml(`${startLocal || formatTime(metadata.start_at)}${endLocal || metadata.end_at ? " 至 " : ""}${endLocal || formatTime(metadata.end_at)}`)} <em>${escapeHtml(timeRange.timezone || metadata.timezone || "Asia/Shanghai")}</em></p>
        </div>
      ` : ""}
      ${hasPersona ? `
        <div class="memory-structured-block">
          <b>提及策略</b>
          <div class="memory-diagnostics-grid">
            ${policy ? `<span><em>策略</em><strong>${escapeHtml(mentionPolicyLabel(policy))}</strong></span>` : ""}
            ${mentionability !== undefined && mentionability !== null ? `<span><em>可提及性</em><strong>${escapeHtml(percentLabel(mentionability))}</strong></span>` : ""}
            ${phase ? `<span><em>当时关系情境</em><strong>${escapeHtml(phase)}</strong></span>` : ""}
            ${decayMode ? `<span><em>衰减</em><strong>${escapeHtml(decayModeLabel(decayMode))}</strong></span>` : ""}
            ${feedback.last_reaction ? `<span><em>上次反馈</em><strong>${escapeHtml(reactionLabel(feedback.last_reaction))}</strong></span>` : ""}
          </div>
          ${memoryReason ? `<p class="memory-reason">${escapeHtml(memoryReason)}</p>` : ""}
          ${activeDimensions.length ? `<div class="memory-structured-tags">${activeDimensions.slice(0, 8).map((item) => `<span class="badge violet">${escapeHtml(dimensionLabel(item))}</span>`).join("")}</div>` : ""}
          ${weights.length ? `
            <div class="weight-meter-list">
              ${weights.slice(0, 8).map((item) => `
                <span class="weight-meter">
                  <i style="--w:${Math.round(Math.max(0, Math.min(1, item.value)) * 100)}%"></i>
                  <b>${escapeHtml(dimensionLabel(item.key))}</b>
                  <em>${escapeHtml(percentLabel(item.value))}</em>
                </span>
              `).join("")}
            </div>
          ` : ""}
          ${correction.text ? `<p class="memory-reason is-warning">用户纠正：${escapeHtml(correction.text)}</p>` : ""}
        </div>
      ` : ""}
      ${canonical ? `
        <div class="memory-structured-block">
          <b>检索摘要</b>
          <p>${escapeHtml(canonical)}</p>
        </div>
      ` : ""}
      ${keyFacts.length ? `
        <div class="memory-structured-block">
          <b>关键事实</b>
          <ul>${keyFacts.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${routineCheckNotes.length ? `
        <div class="memory-structured-block">
          <b>例行检查记录</b>
          <ul>${routineCheckNotes.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
        </div>
      ` : ""}
      ${topics.length || participants.length ? `
        <div class="memory-structured-tags">
          ${topics.map((item) => `<span class="badge blue">${escapeHtml(item)}</span>`).join("")}
          ${participants.map((item) => `<span class="badge teal">${escapeHtml(item)}</span>`).join("")}
        </div>
      ` : ""}
    </section>
  `;
}

export function memoryOption(value, label, current) {
  return `<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(label)}</option>`;
}

export async function saveMemoryManagement(id, form) {
  const data = new FormData(form);
  const num = (name, fallback) => {
    const value = Number(data.get(name));
    return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : fallback;
  };
  const validFrom = String(data.get("valid_from") || "").trim();
  const validTo = String(data.get("valid_to") || "").trim();
  if (validFrom && validTo) {
    const start = Date.parse(validFrom);
    const end = Date.parse(validTo);
    if (Number.isFinite(start) && Number.isFinite(end) && start > end) {
      throw new Error("生效时间不能晚于失效时间");
    }
  }
  const result = await apiPost("/memory/update", {
    id,
    memory_type: String(data.get("memory_type") || ""),
    content: String(data.get("content") || ""),
    evidence: String(data.get("evidence") || ""),
    importance: num("importance", 0.3),
    confidence: num("confidence", 0.5),
    visibility: String(data.get("visibility") || "internal"),
    lifecycle: String(data.get("lifecycle") || "stable_memory"),
    validity_status: String(data.get("validity_status") || "active"),
    valid_from: validFrom,
    valid_to: validTo,
    salience: num("salience", 0.3),
    durability: String(data.get("durability") || "normal"),
    sensitivity: String(data.get("sensitivity") || "private"),
  });
  if (result?.updated !== true) throw new Error("保存结果未确认，请重新读取当前记录核对，不要重复提交。");
  showToast("这条记忆已保存");
  // A completed write belongs to its original form; do not reopen it over another record.
  if (state.activeMemoryId !== id || !form.isConnected) return;
  await showMemory(id);
  try {
    await loadStats();
    if (state.activeMemoryId === id) await loadActiveView();
  } catch (error) {
    showToast("这条记忆已保存，但列表或统计暂未刷新；可稍后手动刷新。", "error");
  }
}

export function showInjectionLogDetail(payload) {
  const selected = Array.isArray(payload.selected_memories) ? payload.selected_memories : [];
  const blocked = Array.isArray(payload.blocked_reasons) ? payload.blocked_reasons : [];
  $("#detailDrawer").className = "detail-drawer";
  $("#detailDrawer").innerHTML = `
    <div class="memory-manage-head">
      <div>
        <h3>注入记录</h3>
        <p class="item-meta">${escapeHtml(formatTime(payload.created_at))} · ${escapeHtml(payload.scope || "unknown")} · ${escapeHtml(shortId(payload.session_id || "-"))}</p>
      </div>
      <div class="badges">
        <span class="badge blue">选中 ${escapeHtml((payload.selected_memory_ids || []).length)} 条</span>
        <span class="badge teal">过滤 ${escapeHtml(blocked.length)} 条</span>
        <span class="badge gold">${escapeHtml(payload.injection_chars || 0)} chars</span>
      </div>
    </div>
    <section class="memory-structured-panel">
      <div class="memory-structured-block">
        <b>本轮查询</b>
        <p>${escapeHtml(payload.query || "未记录查询文本")}</p>
      </div>
      ${selected.length ? `
        <div class="memory-structured-block">
          <b>进入注入的记忆</b>
          <div class="log-memory-list">
            ${selected.map((memory) => `
              <button type="button" class="log-memory-item" data-memory-id="${escapeHtml(memory.id)}">
                <span>${escapeHtml(compact(memory.canonical_summary || memory.content, memory.id))}</span>
                <small>${escapeHtml(memory.memory_type || "memory")} · ${escapeHtml(mentionPolicyLabel(memory.mention_policy || ""))}</small>
              </button>
            `).join("")}
          </div>
        </div>
      ` : `<div class="empty-state">这一轮没有实际注入长期记忆。</div>`}
      ${blocked.length ? `
        <div class="memory-structured-block">
          <b>过滤原因</b>
          <div class="badges">${blockedReasonBadges(blocked)}</div>
          <ul class="log-blocked-list">
            ${blocked.slice(0, 12).map((item) => `<li><b>${escapeHtml(blockedReasonLabel(item.reason || item))}</b><span>${escapeHtml(item.reason || JSON.stringify(item))}</span></li>`).join("")}
          </ul>
        </div>
      ` : ""}
    </section>
    <details class="memory-raw-detail">
      <summary>原始日志</summary>
      <pre>${escapeHtml(JSON.stringify(payload || {}, null, 2))}</pre>
    </details>
  `;
  $$("#detailDrawer [data-memory-id]").forEach((button) => {
    button.addEventListener("click", () => showMemory(button.dataset.memoryId));
  });
}

export function showGenericDetail(title, payload) {
  if (title === "注入记录详情") {
    showInjectionLogDetail(payload || {});
    return;
  }
  $("#detailDrawer").classList.remove("empty");
  $("#detailDrawer").innerHTML = `
    <h3>${escapeHtml(title)}</h3>
    <pre>${escapeHtml(JSON.stringify(payload || {}, null, 2))}</pre>
  `;
}

export function clearDetail() {
  $("#detailDrawer").className = "detail-drawer empty";
  $("#detailDrawer").innerHTML = `
    <div class="detail-empty">
      <b>等待选片</b>
      <span>选择左侧对象，再点一条记忆或记录查看详情。</span>
    </div>
  `;
}

export function livingMemoryPathValue(kind = "import") {
  return $(kind === "repair" ? "#livingMemoryRepairPath" : "#livingMemoryImportPath")?.value.trim() || "";
}

export function archiveTransferFields(fields) {
  return `<dl class="archive-transfer-fields">${fields.filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
}

export function bindArchiveTransferPaths(host) {
  const box = $(host);
  box?.querySelectorAll("[data-use-portable-path]").forEach((button) => button.addEventListener("click", () => {
    $("#portableArchivePath").value = button.dataset.usePortablePath;
    $("#portableArchivePath").focus();
    showToast("已填入路径；可先预览，不会自动导入");
  }));
  box?.querySelectorAll("[data-use-living-path]").forEach((button) => button.addEventListener("click", () => {
    $("#livingMemoryImportPath").value = button.dataset.useLivingPath;
    $("#livingMemoryImportPath").focus();
    showToast("已填入导入来源；内容修复栏保持独立");
  }));
}

export function showArchiveTransferUnknown(host, path, error) {
  const box = $(host);
  if (!box) return;
  box.hidden = false;
  box.innerHTML = `<section class="archive-result-panel"><b>操作结果未确认</b>
    <p>没有收到完整结果，不代表服务端未写入。不要重复提交；先在记忆列表与服务器记录中核对。再次预览文件只能确认其内容，不能证明上次操作已完成。</p>
    ${archiveTransferFields([["请求来源", path || "自动扫描"]])}<p>${escapeHtml(error?.message || error || "结果缺失")}</p></section>`;
  showToast("结果未确认，请先核对，不要重复提交", "error");
}

export async function refreshAfterArchiveTransfer(host) {
  try { await refreshAll(); return true; }
  catch (error) {
    const note = document.createElement("p");
    note.dataset.transferRefresh = "";
    note.className = "archive-transfer-warning";
    note.textContent = `操作结果已返回，但统计或列表读取失败：${error?.message || error}。上方结果仍保留，无需重新提交。`;
    $(host)?.append(note);
    return false;
  }
}

export function sumLivingMemoryRows(tables = [], importable = true) {
  return tables
    .filter((table) => Boolean(table.importable) === importable)
    .reduce((total, table) => total + Math.max(0, Number(table.count) || 0), 0);
}

export function archiveResultCard(label, value, note = "", tone = "blue") {
  return `
    <article class="archive-result-card">
      <span class="badge ${escapeHtml(tone)}">${escapeHtml(label)}</span>
      <b>${escapeHtml(value)}</b>
      ${note ? `<small>${escapeHtml(note)}</small>` : ""}
    </article>
  `;
}

export function renderArchiveResultDetails(value) {
  return `
    <details class="memory-raw-detail archive-raw-detail">
      <summary>原始结果</summary>
      <pre>${escapeHtml(JSON.stringify(value || {}, null, 2))}</pre>
    </details>
  `;
}

export function renderLivingMemoryPreview(report = {}) {
  const candidates = Array.isArray(report.candidates) ? report.candidates : [];
  return `<section class="archive-result-panel"><div class="archive-result-head"><b>LivingMemory 来源预览</b>
    <span>${candidates.length ? `找到 ${candidates.length} 个候选库；原导入优先使用第一项，可将其他候选填入来源栏。` : "未找到 LivingMemory 数据库，可填写服务器路径后重新预览。"}</span></div>
    <p class="archive-note">预览行数不等于最终导入数，单次上限与审核状态沿当前配置；空内容、重复内容及不支持的表按原规则处理。</p>
    ${candidates.map((item, index) => {
      const tables = Array.isArray(item.tables) ? item.tables : [];
      return `<details class="archive-transfer-source" data-living-source ${index === 0 ? "open" : ""}>
        <summary>${index + 1}. ${escapeHtml(item.path || "未记录来源")}<small>${item.error ? "无法读取" : `可导入 ${sumLivingMemoryRows(tables, true)} 行 · 跳过 ${sumLivingMemoryRows(tables, false)} 行`}</small></summary>
        ${item.error ? `<p class="archive-transfer-warning">${escapeHtml(item.error)}</p>` : `<div class="archive-table-list">${tables.map((table) => `<span><strong>${escapeHtml(table.name || "-")}</strong><em>${escapeHtml(table.count || 0)} 行 · ${table.importable ? "可导入" : "跳过"}</em></span>`).join("")}</div>`}
        <button type="button" data-use-living-path="${escapeHtml(item.path || "")}" ${!item.path || item.error ? "disabled" : ""}>将此库填入导入来源</button>
      </details>`;
    }).join("")}${renderArchiveResultDetails(report)}</section>`;
}

export function renderLivingMemoryImportResult(result = {}) {
  if (result.reason && !result.source_path) {
    return `
      <section class="archive-result-panel">
        <div class="archive-result-head">
          <b>导入未执行</b>
          <span>${escapeHtml(result.reason)}</span>
        </div>
        ${renderArchiveResultDetails(result)}
      </section>
    `;
  }
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>LivingMemory 导入完成</b>
        <span>${escapeHtml(result.source_path || "未记录来源路径")}</span>
      </div>
      ${archiveTransferFields([["来源数据库", result.source_path], ["导入批次", result.batch_id], ["单次导入上限", result.import_limit]])}
      <p class="archive-note">旧库导入是否备份沿当前配置；此接口不返回备份路径，请在服务器记录中核对，不把 JSONL 档案当成整库备份。</p>
      <div class="archive-result-grid">
        ${archiveResultCard("已导入", `${result.imported || 0} 条`, result.batch_id ? `批次 ${shortId(result.batch_id)}` : "", "teal")}
        ${archiveResultCard("异常跳过", `${result.skipped || 0} 条`, "空内容或无法识别", Number(result.skipped || 0) ? "gold" : "blue")}
        ${archiveResultCard("审核状态", `${result.default_review_status || "auto"}`, "导入策略", "violet")}
      </div>
      ${Array.isArray(result.importable_tables) && result.importable_tables.length ? `
        <div class="archive-table-list">
          <b>导入明细</b>
          ${result.importable_tables.map((table) => `
            <span><strong>${escapeHtml(table.name || "-")}</strong><em>${escapeHtml(table.imported || 0)} / ${escapeHtml(table.count || 0)}</em></span>
          `).join("")}
        </div>
      ` : ""}
      ${renderArchiveResultDetails(result)}
    </section>
  `;
}

export function renderLivingMemoryRepairResult(result = {}) {
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>内容修复结果</b>
        <span>${escapeHtml(result.source_path || result.reason || "未记录来源路径")}</span>
      </div>
      <div class="archive-result-grid">
        ${archiveResultCard("已修复", `${result.updated || 0} 条`, "旧编号内容已替换", "teal")}
        ${archiveResultCard("跳过", `${result.skipped || 0} 条`, result.error || "没有匹配内容", Number(result.skipped || 0) ? "gold" : "blue")}
      </div>
      ${renderArchiveResultDetails(result)}
    </section>
  `;
}

export function renderPortableArchiveResult(value = {}, kind) {
  const sum = (counts) => Object.values(counts || {}).reduce((total, count) => total + (Number(count) || 0), 0);
  const importing = kind === "portable-import";
  const skipped = sum(value.skipped);
  const errors = Array.isArray(value.errors) ? value.errors : [];
  const warnings = Array.isArray(value.warnings) ? value.warnings : [];
  const title = importing ? (skipped || errors.length ? "导入完成，部分记录未导入" : "档案已导入")
    : kind === "portable-preview" ? "档案预览" : "档案已导出";
  return `<section class="archive-result-panel">
    <div class="archive-result-head"><b>${escapeHtml(title)}</b><span>修订历史仅供查阅，不重新进入记忆检索。</span></div>
    ${archiveTransferFields([["格式", value.format ? `${value.format}${value.version ? ` v${value.version}` : ""}` : ""], ["导出时间", value.exported_at], ["导入批次", value.batch_id]])}
    ${value.path ? `<div class="archive-transfer-path"><span>服务器文件位置</span><code data-archive-path>${escapeHtml(value.path)}</code>${kind === "portable-export" ? `<button type="button" data-use-portable-path="${escapeHtml(value.path)}">填入预览路径</button>` : ""}</div>` : ""}
    ${value.backup ? `${archiveTransferFields([["导入前记忆库备份", value.backup]])}<p class="archive-note">这是服务器上当前 MC 单库备份，不是异地备份或整个 TLS 跨库快照。</p>` : ""}
    <div class="archive-result-grid">
      ${archiveResultCard(importing ? "成功核对 / 导入" : "资料", sum(importing ? value.imported : value.counts), "条", "blue")}
      ${archiveResultCard("修订历史", Number(value.revision_count) || 0, "条（包含已存在的同一修订）", "blue")}
      ${importing ? archiveResultCard("跳过", skipped, "保留当前资料，查看下方原因", "blue") : ""}
    </div>
    <details class="archive-transfer-counts"><summary>各类资料数量</summary>
      ${archiveTransferFields(Object.entries(importing ? value.imported || {} : value.counts || {}).map(([key, count]) => [({memory:"记忆",identity:"身份",relationship:"关系",timeline:"时间线",acl_rule:"权限规则",acl_policy:"权限策略"})[key] || key, count]))}
    </details>
    ${value.conflict_policy ? `<p>${escapeHtml(value.conflict_policy)}</p>` : ""}
    ${warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join("")}
    ${errors.length ? `<ul>${errors.map((error) => `<li>${escapeHtml(error)}</li>`).join("")}</ul>` : ""}
    ${renderArchiveResultDetails(value)}
  </section>`;
}

export function renderGenericArchiveResult(value = {}, title = "执行结果") {
  const entries = Object.entries(value || {}).filter(([, item]) => typeof item !== "object");
  return `
    <section class="archive-result-panel">
      <div class="archive-result-head">
        <b>${escapeHtml(title)}</b>
        <span>操作已返回结果。</span>
      </div>
      ${entries.length ? `
        <div class="archive-result-grid">
          ${entries.slice(0, 6).map(([key, item]) => archiveResultCard(key, String(item), "", "blue")).join("")}
        </div>
      ` : ""}
      ${renderArchiveResultDetails(value)}
    </section>
  `;
}

export function renderMemoryPipeline(report = {}) {
  const pipeline = report.pipeline;
  if (!pipeline || pipeline.schema !== 1) {
    return `<p class="archive-note">服务端尚未提供后台任务状态，请核对当前服务版本。</p>`;
  }
  const taskLabels = {
    running: "任务存活", not_started: "未启动", finished: "任务已结束",
    failed: "任务已失败", cancelled: "任务已取消", unknown: "状态未知",
  };
  const stateLabels = { ready: "可接纳请求", closing: "正在关闭", closed: "已关闭" };
  const observedCount = (value) => Number.isInteger(value) && value >= 0 ? String(value) : "未知";
  const flagLabel = (value) => value === true ? "开启" : value === false ? "关闭" : "未知";
  const capture = pipeline.capture || {};
  const summary = pipeline.summary || {};
  const failures = report.memory?.summary_failures || {};
  const workerCard = (key, title) => {
    const worker = pipeline[key] || {};
    const live = taskLabels[worker.task_state] || "状态未知";
    const configured = worker.enabled === true ? "配置开启" : worker.enabled === false ? "配置关闭" : "配置未知";
    const problem = worker.task_state === "failed" || worker.last_error_present;
    return archiveResultCard(title, live,
      `${configured}；最近完成：${worker.last_completed_at ? formatTime(worker.last_completed_at) : "暂无记录"}${problem ? "；有错误记录，请展开原始结果" : ""}`,
      problem ? "gold" : worker.task_state === "running" ? "teal" : "blue");
  };
  return `
    <div class="archive-result-head">
      <b>记忆运行与后台任务</b>
      <span>${escapeHtml(formatTime(pipeline.observed_at))} · 当前实例快照</span>
    </div>
    <div class="archive-result-grid">
      ${archiveResultCard("服务", stateLabels[pipeline.state] || "状态未知", "运行快照不等于本轮捕获、模型或召回已验证", pipeline.state === "ready" ? "teal" : "gold")}
      ${archiveResultCard("原话捕获", capture.enabled === true ? "配置开启" : capture.enabled === false ? "配置关闭" : "配置未知", `用户原话：${flagLabel(capture.user_messages)}；助手回复：${flagLabel(capture.bot_responses)}`, "blue")}
      ${archiveResultCard("增量摘要", summary.enabled === true ? "配置开启" : summary.enabled === false ? "配置关闭" : "配置未知", `正在执行 ${observedCount(summary.running_workers)}；等待补偿 ${observedCount(summary.pending_sessions)}；待处理失败批次 ${observedCount(failures.total)}`, failures.total || summary.failed_workers ? "gold" : "blue")}
      ${workerCard("portrait", "综合画像")}
      ${workerCard("maintenance", "记忆维护")}
      ${workerCard("wal_checkpoint", "数据库整理")}
    </div>
    <p class="archive-note">此处只读取已有任务，不会启动摘要、画像或维护。配置已开、任务存活与实际业务完成分别展示；空闲摘要没有常驻任务属于正常情况。失败批次来自原库，不会因内存任务已结束而清零${failures.last_updated_at ? `；最近记录：${escapeHtml(formatTime(failures.last_updated_at))}` : ""}。</p>
  `;
}

export function renderOperationsDiagnostics(report = {}) {
  const warnings = Array.isArray(report.warnings) ? report.warnings : [];
  const usage = report.model_usage || {};
  return `<section class="archive-result-panel">
    ${renderMemoryPipeline(report)}
    <div class="archive-result-grid">
      ${archiveResultCard("检索方式", report.retrieval?.mode || "未知", "使用当前已配置的检索器", "blue")}
      ${archiveResultCard("记忆条数", Number.isInteger(report.memory?.total_memories) ? String(report.memory.total_memories) : "未知", "原记忆库统计，不代表全部资料已审核", "blue")}
      ${archiveResultCard("已记录模型调用", Number.isInteger(usage.calls) ? String(usage.calls) : "未知", Number.isInteger(usage.errors) ? `失败 ${usage.errors}` : "尚无错误统计", usage.errors ? "gold" : "blue")}
    </div>
    ${warnings.length ? `<ul class="archive-note">${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>` : ""}
    ${renderArchiveResultDetails(report)}
  </section>`;
}

export function showArchiveResult(value, kind = "generic", host = "#importResult") {
  const box = typeof host === "string" ? $(host) : host;
  if (!box) return;
  box.hidden = false;
  if (kind === "preview") {
    box.innerHTML = renderLivingMemoryPreview(value);
  } else if (kind === "import") {
    box.innerHTML = renderLivingMemoryImportResult(value);
  } else if (kind === "repair") {
    box.innerHTML = renderLivingMemoryRepairResult(value);
  } else if (kind === "diagnostics") {
    box.innerHTML = renderOperationsDiagnostics(value);
  } else if (["portable-export", "portable-preview", "portable-import"].includes(kind)) {
    box.innerHTML = renderPortableArchiveResult(value, kind);
  } else {
    box.innerHTML = renderGenericArchiveResult(value, kind === "maintenance" ? "维护结果" : "执行结果");
  }
}

export function showInlineConfirmation({
  host,
  title,
  message,
  confirmLabel = "确认执行",
  busyText = "正在执行...",
  dangerous = false,
  onConfirm,
  onCancel,
}) {
  const box = typeof host === "string" ? $(host) : host;
  if (!box || typeof onConfirm !== "function") return;
  if (box.id === "detailDrawer") {
    box.className = "detail-drawer";
  } else {
    box.hidden = false;
  }
  box.innerHTML = `
    <div class="clear-confirm inline-confirm">
      <b>${escapeHtml(title || "确认操作")}</b>
      <p>${escapeHtml(message || "请确认是否继续。")}</p>
      <div class="inline-actions">
        <button data-inline-confirm type="button" class="${dangerous ? "danger" : ""}">${escapeHtml(confirmLabel)}</button>
        <button data-inline-cancel type="button">取消</button>
      </div>
    </div>
  `;
  const confirmButton = box.querySelector("[data-inline-confirm]");
  const cancelButton = box.querySelector("[data-inline-cancel]");
  confirmButton?.addEventListener("click", () => withBusy(busyText, onConfirm));
  cancelButton?.addEventListener("click", async () => {
    if (typeof onCancel === "function") {
      await onCancel();
    } else {
      box.innerHTML = "";
      if (box.id !== "detailDrawer") box.hidden = true;
    }
    showToast("已取消操作");
  });
  confirmButton?.focus();
}

export async function runMaintenance() {
  const data = await apiPost("/maintenance");
  await refreshAll();
  showArchiveResult(data.result, "maintenance");
  showToast("维护已完成");
}

export async function runOperationsDiagnostics() {
  const data = await apiGet("/operations/diagnostics");
  showArchiveResult(data.diagnostics, "diagnostics");
  showToast("运维诊断已生成");
}

export async function applyOperationPreset(preset) {
  const labels = { light: "轻量", standard: "标准", companion: "陪伴" };
  const label = labels[preset] || preset;
  showInlineConfirmation({
    host: "#importResult",
    title: `应用${label}预设`,
    message: "将调整检索、图谱、总结阈值和注入预算；已有模型 Provider 选择会保留。",
    confirmLabel: "应用预设",
    busyText: "正在应用运行预设...",
    onConfirm: () => executeOperationPreset(preset, label),
  });
}

export async function executeOperationPreset(preset, label) {
  const data = await apiPost("/operations/preset", { preset });
  await refreshAll();
  showArchiveResult(data.preset, "preset");
  showToast(`已应用${label}预设`);
}

export function portableArchivePath() {
  return String($("#portableArchivePath")?.value || "").trim();
}

export async function exportPortableArchive() {
  const data = await apiPost("/data/export", {});
  showArchiveResult(data.result, "portable-export", "#portableArchiveResult");
  bindArchiveTransferPaths("#portableArchiveResult");
  showToast("可移植档案已导出");
}

export async function previewPortableArchive() {
  const path = portableArchivePath();
  if (!path) {
    showToast("请先填写 JSONL 路径", "error");
    return;
  }
  const params = new URLSearchParams({ path });
  const data = await apiGet(`/data/import/preview?${params.toString()}`);
  showArchiveResult(data.result, "portable-preview", "#portableArchiveResult");
  showToast("可移植档案预览已生成");
}

export async function importPortableArchive() {
  const path = portableArchivePath();
  if (!path) {
    showToast("请先填写 JSONL 路径", "error");
    return;
  }
  showInlineConfirmation({
    host: "#portableArchiveResult",
    title: "导入可移植档案",
    message: `将从 ${path} 导入记忆及修订、身份、关系、时间线和 ACL；执行前自动备份。同ID记忆冲突会跳过，不覆盖当前修改。`,
    confirmLabel: "执行导入",
    busyText: "正在导入可移植档案...",
    onConfirm: () => executePortableArchiveImport(path),
  });
}

export async function executePortableArchiveImport(path) {
  const host = "#portableArchiveResult";
  let result;
  try {
    result = (await apiPost("/data/import/run", { path })).result;
    if (!result?.batch_id || !result.imported || !result.skipped || !Array.isArray(result.errors)) throw new Error("导入收据不完整");
  } catch (error) { showArchiveTransferUnknown(host, path, error); return; }
  showArchiveResult(result, "portable-import", host);
  const refreshed = await refreshAfterArchiveTransfer(host);
  const skipped = Object.values(result.skipped).reduce((n, v) => n + (Number(v) || 0), 0);
  showToast(skipped || result.errors.length ? "导入完成，部分记录未导入；请查看原因"
    : refreshed ? "可移植档案已导入" : "档案已导入，统计读取失败；结果已保留", skipped || result.errors.length || !refreshed ? "error" : "success");
}

export function localDateTimeInputValue(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function initializeQQHistoryRange() {
  const end = $("#qqHistoryEndAt");
  const start = $("#qqHistoryStartAt");
  if (!end || !start || (end.value && start.value)) return;
  const now = new Date();
  end.value = localDateTimeInputValue(now);
  start.value = localDateTimeInputValue(new Date(now.getTime() - 24 * 60 * 60 * 1000));
}

export function conversationImportSource() {
  return state.conversationImportSource || "qq";
}

export function showHistoricalChatOutput(hasContent) {
  const empty = $("#historicalChatEmptyState");
  if (empty) empty.hidden = Boolean(hasContent);
}

export function clearConversationImportResult() {
  const box = $("#conversationImportResult");
  if (!box) return;
  box.hidden = true;
  box.innerHTML = "";
}

export function showConversationImportError(title, error, retryTask) {
  const box = $("#conversationImportResult");
  if (!box) return;
  const message = String(error?.message || error || "操作失败");
  box.hidden = false;
  box.innerHTML = `
    <div class="chat-import-callout is-warning" role="alert">
      <b>${escapeHtml(title || "读取失败")}</b>
      <span>${escapeHtml(message)}</span>
      <small>请检查文件格式、大小和来源后重试；已生成的记忆不会受到影响。</small>
    </div>
    ${typeof retryTask === "function" ? '<div class="chat-import-primary-actions"><button id="conversationImportRetryBtn" type="button">重新尝试</button></div>' : ""}
  `;
  showHistoricalChatOutput(true);
  $("#conversationImportRetryBtn")?.addEventListener("click", (event) => {
    withButton(event.currentTarget, "重试中", retryTask);
  });
}

export function applyConversationImportSource() {
  const source = conversationImportSource();
  $$('[data-import-source]').forEach((panel) => {
    panel.hidden = panel.dataset.importSource !== source;
  });
  $$('[data-import-source-tab]').forEach((button) => {
    const active = button.dataset.importSourceTab === source;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
    button.setAttribute("tabindex", active ? "0" : "-1");
  });
  initializeQQHistoryRange();
}

export async function selectConversationImportSource(source) {
  if (!["qq", "file", "recent"].includes(source)) return;
  const changed = state.conversationImportSource !== source;
  state.conversationImportSource = source;
  applyConversationImportSource();
  if (changed) {
    clearConversationImportResult();
    const matchingPreview = state.historicalChatPreviewSource === source ? state.historicalChatPreview : null;
    renderHistoricalChatPreview(matchingPreview);
    if (!matchingPreview && !state.historicalChatBatchId) setHistoricalChatStep(0);
  }
  if (source === "qq") {
    await loadQQHistoryCapabilities();
  } else if (source === "recent") {
    await loadHistoricalChatBatchList();
  }
}

export async function loadConversationImportView() {
  await loadHistoricalChatTargets();
  applyConversationImportSource();
  const source = conversationImportSource();
  if (source === "qq") {
    await loadQQHistoryCapabilities();
  } else if (source === "recent") {
    await loadHistoricalChatBatchList();
  }
  showHistoricalChatOutput(Boolean(state.historicalChatPreview || state.historicalChatBatchId));
}

export async function loadHistoricalChatTargets() {
  try {
    const data = await apiGet("/conversation-import/targets");
    state.historicalChatTargetBuckets = normalizeBuckets(data.buckets || []).filter(isWindowBucket);
  } catch (error) {
    state.historicalChatTargetBuckets = [];
    showToast(error.message || "读取目标私聊失败，暂用当前窗口列表", "error");
  }
}

export function qqHistoryImplementationLabel(adapter = {}) {
  const implementation = [adapter.implementation, adapter.implementation_version].filter(Boolean).join(" ");
  const bot = adapter.bot_id
    ? `${adapter.bot_name || "Bot"}（${adapter.bot_id}）`
    : "未识别登录账号";
  return implementation ? `${bot} · ${implementation}` : bot;
}

export function renderQQHistoryCapabilities(result = {}) {
  const box = $("#qqHistoryCapability");
  const select = $("#qqHistoryPlatform");
  if (!box || !select) return;
  const adapters = Array.isArray(result.adapters) ? result.adapters : [];
  const ready = adapters.filter((item) => item.connected && item.history_status === "ready");
  select.innerHTML = ready.length
    ? ready.map((item) => `<option value="${escapeHtml(item.platform_id)}">${escapeHtml(qqHistoryImplementationLabel(item))}</option>`).join("")
    : '<option value="">没有可用的 QQ 连接</option>';
  select.disabled = ready.length === 0;
  box.classList.toggle("is-ready", ready.length > 0);
  box.classList.toggle("is-error", ready.length === 0);
  if (ready.length) {
    const limits = result.limits || {};
    box.innerHTML = `
      <b>连接可用</b>
      <span>检测到 ${number(ready.length)} 个 aiocqhttp/OneBot 连接，具备好友历史读取条件。</span>
      <small>单次最多 ${number(limits.max_range_days || 31)} 天、${number(limits.max_messages || 5000)} 条；读取前仍会由接口做一次实际验证。</small>
    `;
  } else {
    const reason = adapters.find((item) => item.error)?.error || "没有发现已登录的 aiocqhttp/OneBot 连接";
    box.innerHTML = `<b>当前不能直读</b><span>${escapeHtml(reason)}</span><small>仍可切换到“文件导入”继续。</small>`;
  }
  updateQQHistoryValidation();
}

export async function loadQQHistoryCapabilities(force = false) {
  if (state.qqHistoryCapabilitiesLoading) return;
  if (state.qqHistoryCapabilities && !force) {
    renderQQHistoryCapabilities(state.qqHistoryCapabilities);
    return;
  }
  const box = $("#qqHistoryCapability");
  if (box) {
    box.className = "qq-history-capability is-loading";
    box.textContent = "正在检测当前 QQ 连接...";
  }
  state.qqHistoryCapabilitiesLoading = true;
  try {
    const data = await apiGet("/conversation-import/qq/capabilities");
    state.qqHistoryCapabilities = data.result || { available: false, adapters: [] };
    renderQQHistoryCapabilities(state.qqHistoryCapabilities);
  } catch (error) {
    state.qqHistoryCapabilities = null;
    if (box) {
      box.className = "qq-history-capability is-error";
      box.innerHTML = `<b>检测失败</b><span>${escapeHtml(error.message || "无法读取 QQ 连接状态")}</span><small>可重新检测，或改用文件导入。</small>`;
    }
    updateQQHistoryValidation();
  } finally {
    state.qqHistoryCapabilitiesLoading = false;
  }
}

export function qqHistoryValidationMessage() {
  const capabilities = state.qqHistoryCapabilities || {};
  const adapterId = String($("#qqHistoryPlatform")?.value || "").trim();
  const userId = String($("#qqHistoryUserId")?.value || "").trim();
  const startValue = $("#qqHistoryStartAt")?.value || "";
  const endValue = $("#qqHistoryEndAt")?.value || "";
  if (!capabilities.available || !adapterId) return { valid: false, message: "当前没有可用的 QQ 直读连接" };
  if (!/^\d{5,20}$/.test(userId)) return { valid: false, message: "目标 QQ 必须是 5 到 20 位纯数字" };
  const adapter = (capabilities.adapters || []).find((item) => item.platform_id === adapterId) || {};
  if (String(adapter.bot_id || "") === userId) return { valid: false, message: "目标 QQ 不能与当前 Bot QQ 相同" };
  if (!startValue || !endValue) return { valid: false, message: "请选择开始时间和结束时间" };
  const start = new Date(startValue);
  const end = new Date(endValue);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return { valid: false, message: "时间格式无效" };
  if (end <= start) return { valid: false, message: "结束时间必须晚于开始时间" };
  const maxDays = Number(capabilities.limits?.max_range_days || 31);
  if (end.getTime() - start.getTime() > maxDays * 24 * 60 * 60 * 1000) {
    return { valid: false, message: `单次读取范围不能超过 ${maxDays} 天` };
  }
  if (end.getTime() > Date.now() + 5 * 60 * 1000) return { valid: false, message: "结束时间不能晚于当前时间" };
  return { valid: true, message: `将读取 QQ ${userId} 在该时段的私聊记录` };
}

export function updateQQHistoryValidation() {
  const result = qqHistoryValidationMessage();
  const box = $("#qqHistoryValidation");
  const button = $("#qqHistoryPreviewBtn");
  if (box) {
    box.textContent = result.message;
    box.classList.toggle("is-valid", result.valid);
    box.classList.toggle("is-error", !result.valid);
  }
  if (button) button.disabled = !result.valid;
  return result;
}

export async function previewQQHistoryImport() {
  const validation = updateQQHistoryValidation();
  if (!validation.valid) {
    showToast(validation.message, "error");
    return;
  }
  clearConversationImportResult();
  setHistoricalChatStep(1);
  let data;
  try {
    data = await apiPost("/conversation-import/qq/preview", {
      platform_id: $("#qqHistoryPlatform").value,
      user_id: $("#qqHistoryUserId").value.trim(),
      start_at: $("#qqHistoryStartAt").value,
      end_at: $("#qqHistoryEndAt").value,
    });
  } catch (error) {
    setHistoricalChatStep(0);
    state.historicalChatPreview = null;
    state.historicalChatPreviewSource = "";
    renderHistoricalChatPreview(null);
    showConversationImportError("QQ 历史读取失败", error, previewQQHistoryImport);
    throw error;
  }
  state.historicalChatPreview = data.result || null;
  state.historicalChatPreviewSource = "qq";
  state.historicalChatBatchId = "";
  state.historicalChatTargetContextId = "";
  renderHistoricalChatPreview(state.historicalChatPreview);
  setHistoricalChatStep(2);
  showToast("QQ 历史读取预览已生成");
}
