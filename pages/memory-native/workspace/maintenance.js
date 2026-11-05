/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {bindArchiveJumpButtons,runSearch,showMemory} from './configuration.js';
import {applyOperationPreset,bindArchiveTransferPaths,clearConversationImportResult,clearDetail,conversationImportSource,exportPortableArchive,importPortableArchive,livingMemoryPathValue,loadQQHistoryCapabilities,previewPortableArchive,previewQQHistoryImport,refreshAfterArchiveTransfer,runMaintenance,runOperationsDiagnostics,selectConversationImportSource,showArchiveResult,showArchiveTransferUnknown,showConversationImportError,showGenericDetail,showHistoricalChatOutput,showInlineConfirmation,updateQQHistoryValidation} from './editors.js';
import {loadActiveView,loadBuckets,openView,playRailRefreshTransition,returnHome,selectBucket,selectUserMemoryFilter} from './memory.js';
import {currentRailScope,invalidateMicroscopeSearch,loadStats,requestRailCoverflow,selectPersonalDate,selectSecondaryNav,setOverviewLayout,todayKey,updateMicroscopeContextMeta} from './overview.js';
import {loadCompanionAvailability} from './portraits.js';
import {$,$$,VIEWS,state} from './state.js';
import {activeBucket,compact,defaultSecondaryNav,escapeHtml,formatTime,number,panelError,secondaryNavItems,shortId,showToast,splitWindowBucketTitle,withBusy,withButton} from './workspace.js';

export function historicalChatBatchStateLabel(value) {
  return {
    prepared: "已准备",
    running: "整理中",
    reconciling: "去重整理中",
    enriching: "细节补全中",
    indexing: "向量索引中",
    paused: "已暂停",
    failed: "失败",
    completed: "已完成",
    completed_with_warnings: "完成但有警告",
    rolled_back: "已回滚",
  }[value] || value || "未知";
}

export async function loadHistoricalChatBatchList() {
  const target = $("#historicalChatRecentList");
  if (!target) return;
  try {
    const data = await apiGet("/conversation-import/status");
    if (!Array.isArray(data.result?.batches)) throw new Error("未返回完整批次列表");
    state.historicalChatBatches = data.result.batches;
    renderHistoricalChatBatchList();
  } catch (error) {
    showToast(`批次列表读取失败；保留上次列表。${error.message || ""}`, "error");
    if (!state.historicalChatBatches.length) target.innerHTML = panelError(error);
    target.querySelector("[data-retry-active]")?.addEventListener("click", loadHistoricalChatBatchList);
  }
}

export function renderHistoricalChatBatchList() {
  const target = $("#historicalChatRecentList");
  if (!target) return;
  const query = $("#historicalChatBatchQuery"), filter = $("#historicalChatBatchFilter");
  if (query) {
    query.value = state.historicalChatBatchQuery;
    query.oninput = () => { state.historicalChatBatchQuery = query.value; state.historicalChatBatchPage = 0; renderHistoricalChatBatchList(); };
  }
  if (filter) {
    const values = [...new Set(state.historicalChatBatches.map(b => b.state))];
    filter.innerHTML = '<option value="all">全部状态</option>' + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(historicalChatBatchStateLabel(value))}</option>`).join("");
    if (!values.includes(state.historicalChatBatchFilter)) state.historicalChatBatchFilter = "all";
    filter.value = state.historicalChatBatchFilter;
    filter.onchange = () => { state.historicalChatBatchFilter = filter.value; state.historicalChatBatchPage = 0; renderHistoricalChatBatchList(); };
  }
  const needle = state.historicalChatBatchQuery.trim().toLocaleLowerCase();
  const rows = state.historicalChatBatches.filter(b => (state.historicalChatBatchFilter === "all" || b.state === state.historicalChatBatchFilter)
    && [b.id, b.source_name, b.user_id, b.user_name, b.bot_id, b.bot_name, b.session_id].join(" ").toLocaleLowerCase().includes(needle));
  const pages = Math.max(1, Math.ceil(rows.length / 8));
  state.historicalChatBatchPage = Math.min(state.historicalChatBatchPage, pages - 1);
  const selectedOutside = state.historicalChatBatchId && !rows.some(b => b.id === state.historicalChatBatchId);
  target.innerHTML = `<p class="import-window-note">本次读取 ${number(state.historicalChatBatches.length)} 个留存批次，匹配 ${number(rows.length)} 个。按服务端更新时间排列；查找和翻页不会启动导入。${selectedOutside ? "当前任务在筛选外，详情仍保留。" : ""}</p>`
    + rows.slice(state.historicalChatBatchPage * 8, (state.historicalChatBatchPage + 1) * 8).map(batch => `
    <button class="chat-import-recent-item${batch.id === state.historicalChatBatchId ? " is-active" : ""}" data-chat-import-batch="${escapeHtml(batch.id)}" type="button">
      <span><b>${escapeHtml(batch.source_name || "历史聊天")}</b><small>${escapeHtml(batch.user_name || batch.user_id || "未记录对象")} · ${escapeHtml(batch.bot_name || batch.bot_id || "未记录 Bot")}</small><small>${escapeHtml(formatTime(batch.updated_at || batch.created_at))}</small></span>
      <span><strong>${escapeHtml(historicalChatBatchStateLabel(batch.state))}</strong><small>${escapeHtml(shortId(batch.id))}</small></span>
    </button>`).join("")
    + (!rows.length ? '<div class="empty-state">没有匹配的批次。</div>' : "")
    + `<div class="import-pagination"><button data-import-page="prev" type="button" ${!state.historicalChatBatchPage ? "disabled" : ""}>上一页</button><span>${state.historicalChatBatchPage + 1} / ${pages}</span><button data-import-page="next" type="button" ${state.historicalChatBatchPage >= pages - 1 ? "disabled" : ""}>下一页</button></div>`;
  target.querySelectorAll('[data-chat-import-batch]').forEach(button => button.addEventListener("click", () => withBusy("正在读取任务状态...", () => loadHistoricalChatBatch(button.dataset.chatImportBatch))));
  target.querySelectorAll('[data-import-page]').forEach(button => button.addEventListener("click", () => { state.historicalChatBatchPage += button.dataset.importPage === "next" ? 1 : -1; renderHistoricalChatBatchList(); }));
}

export async function loadHistoricalChatBatch(batchId) {
  state.historicalChatBatchId = String(batchId || "");
  if (state.historicalChatOutcomes.get(state.historicalChatBatchId)?.unknown) return reconcileHistoricalChatAction();
  const result = await refreshHistoricalChatStatus();
  showHistoricalChatOutput(Boolean(result));
  if (!new Set(["completed", "completed_with_warnings", "rolled_back", "paused", "failed"]).has(result?.batch?.state)) {
    scheduleHistoricalChatPoll();
  }
  await loadHistoricalChatBatchList();
  return result;
}

export function fileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

export function formatFileSize(bytes) {
  const size = Math.max(0, Number(bytes || 0));
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size >= 100 * 1024 ? 0 : 1)} KiB`;
  if (size < 1024 * 1024 * 1024) {
    const mib = size / (1024 * 1024);
    return `${mib.toFixed(mib >= 100 ? 0 : mib >= 10 ? 1 : 2)} MiB`;
  }
  const gib = size / (1024 * 1024 * 1024);
  return `${gib.toFixed(gib >= 100 ? 0 : gib >= 10 ? 1 : 2)} GiB`;
}

export function setHistoricalChatStep(activeIndex, completed = false) {
  const steps = $$(".chat-import-steps span");
  steps.forEach((step, index) => {
    step.classList.toggle("is-active", !completed && index === activeIndex);
    step.classList.toggle("is-complete", completed || index < activeIndex);
  });
}

export function selectHistoricalChatFile(file) {
  const meta = $("#historicalChatFileMeta");
  const button = $("#historicalChatPreviewBtn");
  const dropzone = $("#historicalChatDropzone");
  const validExtension = /\.(txt|log|md|json)$/i.test(String(file?.name || ""));
  const validSize = Number(file?.size || 0) > 0 && Number(file?.size || 0) <= 8 * 1024 * 1024;
  if (!file || !validExtension || !validSize) {
    state.historicalChatFile = null;
    if (button) button.disabled = true;
    dropzone?.classList.remove("has-file");
    if (meta) {
      meta.textContent = file && !validExtension
        ? "仅支持 TXT、LOG、Markdown 或 QQChatExporter JSON 文件"
        : file && !validSize
          ? "文件必须大于 0 且不能超过 8 MiB"
          : "支持 TXT、LOG、Markdown 和 QQChatExporter JSON，最大 8 MiB";
    }
    if (file) showToast(meta?.textContent || "文件不可用", "error");
    return;
  }
  state.historicalChatFile = file;
  state.historicalChatPreview = null;
  state.historicalChatPreviewSource = "";
  state.historicalChatBatchId = "";
  state.historicalChatTargetContextId = "";
  clearConversationImportResult();
  renderHistoricalChatPreview(null);
  setHistoricalChatStep(0);
  if (button) button.disabled = false;
  dropzone?.classList.add("has-file");
  if (meta) meta.textContent = `${file.name} · ${formatFileSize(file.size)} · 已准备解析`;
}

export function historicalChatSavedIdentity() {
  try {
    const value = JSON.parse(window.localStorage.getItem("memoryCompanionHistoricalIdentity") || "{}");
    return value && typeof value === "object" ? value : {};
  } catch (error) {
    return {};
  }
}

export function saveHistoricalChatIdentity(payload) {
  try {
    window.localStorage.setItem("memoryCompanionHistoricalIdentity", JSON.stringify({
      user_id: payload.user_id,
      user_name: payload.user_name,
      bot_id: payload.bot_id,
      bot_name: payload.bot_name,
    }));
  } catch (error) {
    // WebView 禁用 localStorage 时不影响导入主流程。
  }
}

export async function previewHistoricalChatImport() {
  const file = state.historicalChatFile || $("#historicalChatFile")?.files?.[0];
  if (!file) {
    showToast("请先选择聊天记录文件", "error");
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    showToast("对话文件不能超过 8 MiB", "error");
    return;
  }
  clearConversationImportResult();
  const baseYear = Number.parseInt($("#historicalChatBaseYear")?.value || "0", 10) || 0;
  setHistoricalChatStep(1);
  const contentBase64 = await fileAsDataUrl(file);
  let data;
  try {
    data = await apiPost("/conversation-import/upload", {
      filename: file.name,
      content_base64: contentBase64,
      base_year: baseYear,
    });
  } catch (error) {
    setHistoricalChatStep(0);
    state.historicalChatPreview = null;
    state.historicalChatPreviewSource = "";
    renderHistoricalChatPreview(null);
    showConversationImportError("聊天文件解析失败", error, previewHistoricalChatImport);
    throw error;
  }
  state.historicalChatPreview = data.result || null;
  state.historicalChatPreviewSource = "file";
  state.historicalChatBatchId = "";
  state.historicalChatTargetContextId = "";
  renderHistoricalChatPreview(state.historicalChatPreview);
  setHistoricalChatStep(2);
  showToast("对话解析预览已生成");
}

export function historicalChatSuggestedTarget(preview) {
  const identity = preview?.identity_context || {};
  const targetUsers = Array.isArray(identity.target_users) ? identity.target_users : [];
  const suggestions = Array.isArray(preview?.speaker_suggestions) ? preview.speaker_suggestions : [];
  for (const item of suggestions) {
    if (item.suggested_role !== "user") continue;
    const candidates = Array.isArray(item.relationship_candidates) ? item.relationship_candidates : [];
    if (candidates.length === 1) {
      return { user_id: candidates[0].user_id || "", name: candidates[0].name || item.speaker || "" };
    }
  }
  return targetUsers[0] || { user_id: "", name: "" };
}

export function historicalChatContextId(context) {
  return JSON.stringify([
    context?.target_id || "",
    context?.session_id || "",
    context?.bot_id || "",
  ]);
}

export function historicalChatPrivateContexts() {
  const contexts = [];
  const seen = new Set();
  const targetBuckets = state.historicalChatTargetBuckets.length
    ? state.historicalChatTargetBuckets
    : state.buckets;
  targetBuckets
    .filter((bucket) => bucket.scope === "private" && !["internal", "legacy_live2d"].includes(bucket.target_kind))
    .forEach((bucket) => {
      const samples = Array.isArray(bucket.microscope_contexts) && bucket.microscope_contexts.length
        ? bucket.microscope_contexts
        : [{ session_id: bucket.session_id, bot_id: bucket.bot_id }];
      samples.forEach((sample) => {
        const context = {
          ...bucket,
          target_id: bucket.target_id || "",
          session_id: sample.session_id || bucket.session_id || "",
          bot_id: sample.bot_id || bucket.bot_id || "",
        };
        if (!context.target_id || !context.session_id || !context.bot_id) return;
        context.context_id = historicalChatContextId(context);
        if (seen.has(context.context_id)) return;
        seen.add(context.context_id);
        contexts.push(context);
      });
    });
  return contexts.sort((left, right) => String(right.latest_at || "").localeCompare(String(left.latest_at || "")));
}

export function historicalChatContextModel(preview, defaults) {
  const contexts = historicalChatPrivateContexts();
  const exact = contexts.filter((context) => context.target_id === defaults.user_id);
  const botIds = new Set(
    (Array.isArray(preview?.identity_context?.bot?.self_ids) ? preview.identity_context.bot.self_ids : [])
      .map((value) => String(value || "").trim())
      .filter(Boolean),
  );
  const exactBot = exact.filter((context) => botIds.has(context.bot_id));
  // 导出侧 Bot QQ 与官方 Bot ID 可能不同；有 Bot 证据时必须同时匹配才可自动绑定。
  const exactChoices = botIds.size ? exactBot : exact;
  const normalizedName = String(defaults.user_name || "").trim().toLocaleLowerCase();
  const sameNameIds = new Set(
    contexts
      .filter((context) => normalizedName && String(context.display_name || "").trim().toLocaleLowerCase() === normalizedName)
      .map((context) => context.context_id),
  );
  let selectedId = state.historicalChatTargetContextId;
  if (!contexts.some((context) => context.context_id === selectedId)) {
    selectedId = exactChoices.length === 1 ? exactChoices[0].context_id : "";
  }
  state.historicalChatTargetContextId = selectedId;
  return { contexts, selectedId, sameNameIds };
}

export function historicalChatContextLabel(context, sameName = false) {
  const title = splitWindowBucketTitle(context);
  return [
    title.primary,
    title.secondary,
    context.bot_id ? `Bot ${shortId(context.bot_id)}` : "",
    sameName ? "同名候选" : "",
  ].filter(Boolean).join(" · ");
}

export function historicalChatSelectedContext() {
  const selectedId = String($("#historicalChatTargetContext")?.value || state.historicalChatTargetContextId || "");
  return historicalChatPrivateContexts().find((context) => context.context_id === selectedId) || null;
}

export function historicalChatContextHint(context, model) {
  if (context) return `将合并到 ${historicalChatContextLabel(context)}，无需手动填写 openid 或会话 ID。`;
  if (model.sameNameIds.size) return "发现同名私聊候选。请确认后手动选择，系统不会只按昵称自动合并。";
  if (!model.contexts.length) return "尚未发现可绑定的现有私聊，将使用导出身份创建或匹配窗口。";
  return "已有私聊请直接选择目标窗口；只有确实是新用户时才使用导出身份。";
}

export function historicalChatContextPicker(model) {
  const options = model.contexts.map((context) => `
    <option value="${escapeHtml(context.context_id)}" ${context.context_id === model.selectedId ? "selected" : ""}>${escapeHtml(historicalChatContextLabel(context, model.sameNameIds.has(context.context_id)))}</option>
  `).join("");
  const selected = model.contexts.find((context) => context.context_id === model.selectedId) || null;
  return `
    <div class="chat-import-context-picker">
      <label for="historicalChatTargetContext">
        <span><b>记忆归属</b><small>优先选择已经聊过的私聊窗口</small></span>
        <select id="historicalChatTargetContext">
          <option value="" ${model.selectedId ? "" : "selected"}>使用导出身份（新用户）</option>
          ${options ? `<optgroup label="已有私聊窗口">${options}</optgroup>` : ""}
        </select>
      </label>
      <p id="historicalChatContextHint">${escapeHtml(historicalChatContextHint(selected, model))}</p>
    </div>
  `;
}

export function historicalChatResolvedDefaults(defaults, context) {
  if (!context) return defaults;
  return {
    ...defaults,
    user_id: context.target_id,
    user_name: context.display_name || defaults.user_name,
    bot_id: context.bot_id,
  };
}

export function historicalChatIdentityDefaults(preview) {
  const identity = preview?.identity_context || {};
  const target = historicalChatSuggestedTarget(preview);
  const bot = identity.bot || {};
  const botIds = Array.isArray(bot.self_ids) ? bot.self_ids : [];
  const saved = historicalChatSavedIdentity();
  return {
    user_id: target.user_id || saved.user_id || "",
    user_name: target.name || saved.user_name || "",
    bot_id: botIds.length === 1 ? botIds[0] : (saved.bot_id || ""),
    bot_name: bot.name || saved.bot_name || "",
  };
}

export function historicalChatSuggestedRole(item) {
  return ["user", "bot"].includes(item?.suggested_role) ? item.suggested_role : "";
}

export function historicalChatConfidenceLabel(value) {
  if (value === "high") return "高置信建议";
  if (value === "medium") return "中等置信建议";
  return "低置信，仅供参考";
}

export function renderHistoricalChatPreview(preview) {
  const panel = $("#historicalChatPanel");
  if (!panel) return;
  if (!preview) {
    panel.hidden = true;
    panel.innerHTML = "";
    showHistoricalChatOutput(Boolean(state.historicalChatBatchId));
    return;
  }
  const stats = preview.stats || {};
  const defaults = historicalChatIdentityDefaults(preview);
  const contextModel = historicalChatContextModel(preview, defaults);
  const selectedContext = contextModel.contexts.find((context) => context.context_id === contextModel.selectedId) || null;
  const resolvedDefaults = historicalChatResolvedDefaults(defaults, selectedContext);
  const suggestions = Array.isArray(preview.speaker_suggestions) ? preview.speaker_suggestions : [];
  const segmentPreview = Array.isArray(preview.segment_preview) ? preview.segment_preview : [];
  const warningParts = [];
  if (Number(stats.inferred_year_count || 0) > 0) warningParts.push(`${stats.inferred_year_count} 条时间由系统补推年份`);
  if (Number(stats.time_inversion_count || 0) > 0) warningParts.push(`${stats.time_inversion_count} 处原文件时间倒序，已按绝对时间稳定重排`);
  if (Number(stats.duplicate_timestamp_groups || 0) > 0) warningParts.push(`${stats.duplicate_timestamp_groups} 组相同时间戳将按原文件顺序保留`);
  if (Array.isArray(preview.warnings)) warningParts.push(...preview.warnings.filter(Boolean));
  const directQQ = preview.source_kind === "qq_history";
  const readStats = preview.read_stats || {};
  panel.hidden = false;
  showHistoricalChatOutput(true);
  panel.innerHTML = `
    <div class="chat-import-section-head">
      <span><b>${directQQ ? "QQ 读取完成" : "文件解析完成"}</b><small>${escapeHtml(preview.source_name || "历史对话")}</small></span>
      <span class="chat-import-ready-badge">等待身份确认</span>
    </div>
    <div class="chat-import-summary">
      <span><b>${number(stats.message_count)}</b><small>原始消息</small></span>
      <span><b>${number(stats.logical_turn_count)}</b><small>逻辑发言</small></span>
      <span><b>${number(stats.candidate_segment_count)}</b><small>候选片段</small></span>
      <span><b>${number(stats.dialogue_chars)}</b><small>正文字符</small></span>
      <span><b>${number(stats.estimated_summary_calls)}</b><small>预计首轮调用</small></span>
      <span><b>${number(stats.estimated_reconcile_calls)}</b><small>预计整理调用</small></span>
    </div>
    <div class="chat-import-callout ${warningParts.length ? "is-warning" : "is-safe"}">
      <b>时间检查</b>
      <span>${escapeHtml(stats.first_at || "-")} → ${escapeHtml(stats.last_at || "-")}</span>
      <small>${escapeHtml(warningParts.join("；") || "未发现明显时间异常，原文件顺序与绝对时间一致")}</small>
    </div>
    ${directQQ ? `
      <div class="chat-import-callout ${preview.truncated ? "is-warning" : "is-safe"}">
        <b>读取范围${preview.truncated ? "可能不完整" : "完整"}</b>
        <span>扫描 ${number(readStats.scanned_messages)} 条 · 选中 ${number(readStats.selected_messages)} 条 · ${number(readStats.pages)} 页</span>
        <small>分页去重 ${number(readStats.duplicates_removed)} 条；${preview.truncated ? "请缩短时间范围后重试，以获得完整记录。" : "已覆盖所选时段或读到历史末尾。"}</small>
      </div>
    ` : ""}
    <div class="chat-import-callout is-info">
      <b>预计模型工作量</b>
      <span>约 ${number(Number(stats.estimated_summary_calls || 0) + Number(stats.estimated_reconcile_calls || 0))} 次调用</span>
      <small>模型会分包处理，不会把整份长记录一次发送；实际次数可能因失败重试略有增加。</small>
    </div>
    <div class="chat-import-subhead">
      <span><b>确认谁是用户、谁是 Bot</b><small>必须恰好选择一个 Bot；身份选反会让事件归属全部颠倒。</small></span>
      <button id="historicalChatApplySuggestionsBtn" class="subtle" type="button">重新应用智能建议</button>
    </div>
    <div class="chat-import-speakers">
      ${suggestions.map((item, index) => {
        const candidates = Array.isArray(item.relationship_candidates) ? item.relationship_candidates : [];
        const role = historicalChatSuggestedRole(item);
        const reasons = Array.isArray(item.reasons) ? item.reasons.filter(Boolean) : [];
        return `
          <div class="chat-import-speaker ${role ? "has-suggestion" : "needs-choice"}" data-chat-speaker-index="${index}">
            <span class="chat-import-speaker-name">
              <strong>${escapeHtml(item.speaker || "未知")}</strong>
              <small>${number(item.message_count)} 条消息</small>
            </span>
            <label>身份
              <select id="chatRole${index}" data-chat-role>
                <option value="" ${role ? "" : "selected"}>请选择</option>
                <option value="user" ${role === "user" ? "selected" : ""}>用户</option>
                <option value="bot" ${role === "bot" ? "selected" : ""}>Bot</option>
              </select>
            </label>
            <span class="chat-import-confidence" data-confidence="${escapeHtml(item.confidence || "low")}">
              <b>${escapeHtml(historicalChatConfidenceLabel(item.confidence))}</b>
              <small>${escapeHtml(reasons[0] || (candidates.length === 1 ? "关系网名称唯一命中" : "请根据聊天内容人工判断"))}</small>
            </span>
          </div>
        `;
      }).join("")}
    </div>
    <div class="chat-import-subhead">
      <span><b>绑定到当前 AstrBot 身份</b><small>这里只填写一次，系统会自动应用到上面的用户/Bot 说话人。</small></span>
    </div>
    ${historicalChatContextPicker(contextModel)}
    <details class="chat-import-advanced-identity" ${selectedContext ? "" : "open"}>
      <summary>高级身份信息</summary>
      <div class="chat-import-target-grid">
        <label>目标用户 ID<input id="chatImportUserId" type="text" value="${escapeHtml(resolvedDefaults.user_id)}" placeholder="QQ 或平台用户 ID" autocomplete="off" ${selectedContext ? "readonly" : ""} /><small>选择已有私聊后自动填写</small></label>
        <label>用户稳定称呼<input id="chatImportUserName" type="text" value="${escapeHtml(resolvedDefaults.user_name)}" placeholder="例如 烛雨" autocomplete="off" /><small>用于生成自然回忆，不会修改平台昵称</small></label>
        <label>目标 Bot ID<input id="chatImportBotId" type="text" value="${escapeHtml(resolvedDefaults.bot_id)}" placeholder="当前 Bot 平台 ID" autocomplete="off" ${selectedContext ? "readonly" : ""} /><small>用于多 Bot 隔离，不能与用户 ID 相同</small></label>
        <label>Bot 人格称呼<input id="chatImportBotName" type="text" value="${escapeHtml(resolvedDefaults.bot_name)}" placeholder="例如 星缘" autocomplete="off" /><small>填写聊天里对应的人格名称</small></label>
      </div>
    </details>
    ${segmentPreview.length ? `
      <details class="chat-import-segment-preview">
        <summary>抽查分段预览（${number(stats.candidate_segment_count)} 个片段）</summary>
        <div>
          ${segmentPreview.slice(0, 4).map((item) => `
            <span><b>${escapeHtml(item.start_local || "-")}</b><small>${number(item.turn_count)} 个逻辑发言 · ${number(item.char_count)} 字</small><em>${escapeHtml(item.preview || "无预览")}</em></span>
          `).join("")}
        </div>
      </details>
    ` : ""}
    <label class="chat-import-confirm-check">
      <input id="historicalChatIdentityConfirmed" type="checkbox" />
      <span><b>我已核对用户与 Bot 身份</b><small>身份一旦选反，所有历史事件和关系归属都会相反。</small></span>
    </label>
    <div id="historicalChatValidation" class="chat-import-validation" role="status"></div>
    <div class="chat-import-primary-actions">
      <button id="historicalChatStartBtn" type="button" disabled>确认身份并开始整理</button>
      <button id="historicalChatRecentBtn" class="subtle" type="button">查看最近批次</button>
    </div>
    <div id="historicalChatStatus"></div>
  `;
  $("#historicalChatStartBtn")?.addEventListener("click", prepareHistoricalChatImport);
  $("#historicalChatRecentBtn")?.addEventListener("click", loadRecentHistoricalChatBatch);
  $("#historicalChatApplySuggestionsBtn")?.addEventListener("click", applyHistoricalChatSuggestions);
  $("#historicalChatTargetContext")?.addEventListener("change", applyHistoricalChatTargetContext);
  $$('[data-chat-role], #chatImportUserId, #chatImportUserName, #chatImportBotId, #chatImportBotName, #historicalChatIdentityConfirmed').forEach((control) => {
    control.addEventListener("change", updateHistoricalChatValidation);
    control.addEventListener("input", updateHistoricalChatValidation);
  });
  updateHistoricalChatValidation();
}

export function applyHistoricalChatTargetContext() {
  const select = $("#historicalChatTargetContext");
  state.historicalChatTargetContextId = String(select?.value || "");
  const preview = state.historicalChatPreview;
  if (!preview) return;
  const defaults = historicalChatIdentityDefaults(preview);
  const context = historicalChatSelectedContext();
  const resolved = historicalChatResolvedDefaults(defaults, context);
  const values = {
    chatImportUserId: resolved.user_id,
    chatImportUserName: resolved.user_name,
    chatImportBotId: resolved.bot_id,
    chatImportBotName: resolved.bot_name,
  };
  Object.entries(values).forEach(([id, value]) => {
    const input = $("#" + id);
    if (input) input.value = value || "";
  });
  for (const id of ["chatImportUserId", "chatImportBotId"]) {
    const input = $("#" + id);
    if (input) input.readOnly = Boolean(context);
  }
  const advancedIdentity = $(".chat-import-advanced-identity");
  if (advancedIdentity) advancedIdentity.open = !context;
  const model = historicalChatContextModel(preview, defaults);
  const hint = $("#historicalChatContextHint");
  if (hint) hint.textContent = historicalChatContextHint(context, model);
  const confirmed = $("#historicalChatIdentityConfirmed");
  if (confirmed) confirmed.checked = false;
  updateHistoricalChatValidation();
}

export function applyHistoricalChatSuggestions() {
  const preview = state.historicalChatPreview;
  if (!preview) return;
  const defaults = historicalChatIdentityDefaults(preview);
  const resolvedDefaults = historicalChatResolvedDefaults(defaults, historicalChatSelectedContext());
  const suggestions = Array.isArray(preview.speaker_suggestions) ? preview.speaker_suggestions : [];
  suggestions.forEach((item, index) => {
    const select = $("#chatRole" + index);
    if (select) select.value = historicalChatSuggestedRole(item);
  });
  const fields = {
    chatImportUserId: resolvedDefaults.user_id,
    chatImportUserName: resolvedDefaults.user_name,
    chatImportBotId: resolvedDefaults.bot_id,
    chatImportBotName: resolvedDefaults.bot_name,
  };
  Object.entries(fields).forEach(([id, value]) => {
    const input = $("#" + id);
    if (input) input.value = value || "";
  });
  const confirmed = $("#historicalChatIdentityConfirmed");
  if (confirmed) confirmed.checked = false;
  updateHistoricalChatValidation();
  showToast("已重新应用身份建议，请再次人工核对");
}

export function historicalChatImportPayload({ requireConfirmation = true } = {}) {
  const preview = state.historicalChatPreview;
  if (!preview) throw new Error("请先生成导入预览");
  if (state.historicalChatPreviewSource !== conversationImportSource()) {
    throw new Error("当前预览来自其他导入来源，请切回原来源或重新生成预览");
  }
  const suggestions = Array.isArray(preview.speaker_suggestions) ? preview.speaker_suggestions : [];
  const selectedContext = historicalChatSelectedContext();
  const userId = selectedContext?.target_id || String($("#chatImportUserId")?.value || "").trim();
  const botId = selectedContext?.bot_id || String($("#chatImportBotId")?.value || "").trim();
  const userName = String($("#chatImportUserName")?.value || "").trim();
  const botName = String($("#chatImportBotName")?.value || "").trim();
  const speakerMap = {};
  suggestions.forEach((item, index) => {
    const role = $("#chatRole" + index)?.value || "";
    speakerMap[item.speaker] = {
      role,
      entity_id: role === "bot" ? botId : userId,
      display_name: role === "bot" ? (botName || item.speaker) : (userName || item.speaker),
    };
  });
  if (requireConfirmation && !$("#historicalChatIdentityConfirmed")?.checked) {
    throw new Error("请先勾选“我已核对用户与 Bot 身份”");
  }
  return {
    upload_id: preview.upload_id,
    speaker_map: speakerMap,
    platform: selectedContext?.session_id?.includes(":")
      ? selectedContext.session_id.split(":", 1)[0]
      : "qq",
    session_id: selectedContext?.session_id || "",
    user_id: userId,
    user_name: userName,
    bot_id: botId,
    bot_name: botName,
    // 分段参数由插件配置统一管理，避免页面常量覆盖管理员调优值。
    options: {},
  };
}

export function historicalChatValidationMessage() {
  const preview = state.historicalChatPreview;
  const chatType = String(preview?.source_metadata?.chat_type || "").toLowerCase();
  if (preview?.source_kind === "qq_chat_exporter" && chatType && chatType !== "private") {
    return { valid: false, message: "该 JSON 是群聊记录，当前不能导入单用户私聊记忆" };
  }
  let payload;
  try {
    payload = historicalChatImportPayload({ requireConfirmation: false });
  } catch (error) {
    return { valid: false, message: error.message || "导入参数不完整" };
  }
  const roles = Object.values(payload.speaker_map).map((item) => item.role);
  if (roles.some((role) => !["user", "bot"].includes(role))) {
    return { valid: false, message: "还有说话人没有选择身份" };
  }
  if (roles.filter((role) => role === "bot").length !== 1) {
    return { valid: false, message: "必须恰好选择一个 Bot" };
  }
  if (!roles.includes("user")) return { valid: false, message: "至少需要一个用户说话人" };
  if (!payload.user_id || !payload.bot_id) return { valid: false, message: "请填写目标用户 ID 和 Bot ID" };
  if (payload.user_id === payload.bot_id) return { valid: false, message: "用户 ID 和 Bot ID 不能相同" };
  if (!payload.user_name || !payload.bot_name) return { valid: false, message: "请填写用户稳定称呼和 Bot 人格称呼" };
  if (!$("#historicalChatIdentityConfirmed")?.checked) {
    return { valid: false, message: "最后请勾选身份确认，避免整批归属选反" };
  }
  const mapping = Object.entries(payload.speaker_map)
    .map(([speaker, item]) => `${speaker}＝${item.role === "bot" ? "Bot" : "用户"}`)
    .join("，");
  return { valid: true, message: `身份检查通过：${mapping}` };
}

export function updateHistoricalChatValidation() {
  const result = historicalChatValidationMessage();
  const box = $("#historicalChatValidation");
  const start = $("#historicalChatStartBtn");
  if (box) {
    box.textContent = result.message;
    box.classList.toggle("is-valid", result.valid);
    box.classList.toggle("is-error", !result.valid);
  }
  if (start) start.disabled = !result.valid;
  return result;
}

export function prepareHistoricalChatImport() {
  const validation = updateHistoricalChatValidation();
  if (!validation.valid) {
    showToast(validation.message, "error");
    return;
  }
  let payload;
  try {
    payload = historicalChatImportPayload();
  } catch (error) {
    showToast(error.message || "导入参数不完整", "error");
    return;
  }
  const mapping = Object.entries(payload.speaker_map)
    .map(([speaker, item]) => `${speaker} → ${item.role === "bot" ? `Bot ${payload.bot_name}` : `用户 ${payload.user_name}`}`)
    .join("；");
  const stats = state.historicalChatPreview?.stats || {};
  showInlineConfirmation({
    host: "#conversationImportResult",
    title: "开始整理历史对话",
    message: `${mapping}。将归档 ${number(stats.message_count)} 条原始消息、整理 ${number(stats.candidate_segment_count)} 个片段，预计约 ${number(Number(stats.estimated_summary_calls || 0) + Number(stats.estimated_reconcile_calls || 0))} 次模型调用。执行前会自动备份数据库。`,
    confirmLabel: "开始导入",
    busyText: "正在建立历史档案...",
    onConfirm: () => executeHistoricalChatImport(payload),
  });
}

export async function executeHistoricalChatImport(payload) {
  const data = await apiPost("/conversation-import/start", payload);
  const result = data.result || {};
  const batch = result.batch || {};
  state.historicalChatBatchId = batch.id || "";
  clearConversationImportResult();
  saveHistoricalChatIdentity(payload);
  setHistoricalChatStep(3);
  renderHistoricalChatStatus(result);
  scheduleHistoricalChatPoll();
  showToast("历史对话已进入后台整理队列");
}

export async function loadRecentHistoricalChatBatch() {
  const data = await apiGet("/conversation-import/status");
  const batches = data.result?.batches || [];
  if (!batches.length) {
    showToast("还没有历史对话导入批次");
    return;
  }
  await loadHistoricalChatBatch(batches[0].id || "");
}

export async function refreshHistoricalChatStatus() {
  if (!state.historicalChatBatchId) return;
  const params = new URLSearchParams({
    batch_id: state.historicalChatBatchId,
    upgrade_legacy: "0",
  });
  const data = await apiGet(`/conversation-import/status?${params.toString()}`);
  renderHistoricalChatStatus(data.result || {});
  const finalStates = new Set(["completed", "completed_with_warnings", "rolled_back", "paused", "failed"]);
  if (finalStates.has(data.result?.batch?.state)) stopHistoricalChatPoll();
  return data.result || {};
}

export function scheduleHistoricalChatPoll() {
  stopHistoricalChatPoll();
  state.historicalChatPollAttempts = 0;
  state.historicalChatPollStartedAt = Date.now();
  state.historicalChatPollTimer = window.setInterval(() => {
    state.historicalChatPollAttempts += 1;
    const elapsed = Date.now() - state.historicalChatPollStartedAt;
    if (state.historicalChatPollAttempts > 120 || elapsed > 10 * 60 * 1000) {
      stopHistoricalChatPoll();
      showToast("历史导入轮询已达到上限，请手动刷新任务状态", "error");
      return;
    }
    refreshHistoricalChatStatus().catch(() => stopHistoricalChatPoll());
  }, 3000);
}

export function stopHistoricalChatPoll() {
  if (state.historicalChatPollTimer) window.clearInterval(state.historicalChatPollTimer);
  state.historicalChatPollTimer = 0;
  state.historicalChatPollStartedAt = 0;
}

export function historicalChatSegmentStatusLabel(value) {
  return {
    pending: "待整理",
    processing: "处理中",
    retry: "等待重试",
    completed: "已生成记忆",
    archived_only: "仅保留原文",
    failed: "失败",
  }[value] || value;
}

export function historicalChatRebindContexts(batch) {
  return historicalChatPrivateContexts().filter((context) => !(
    context.target_id === String(batch?.user_id || "")
    && context.session_id === String(batch?.session_id || "")
    && context.bot_id === String(batch?.bot_id || "")
  ));
}

export function historicalChatRebindPanel(batch) {
  if (!["completed", "completed_with_warnings"].includes(batch?.state)) return "";
  const contexts = historicalChatRebindContexts(batch);
  if (!contexts.length) return "";
  return `
    <details class="chat-import-rebind">
      <summary>归属不对？修正到已有私聊</summary>
      <div>
        <label for="historicalChatRebindContext">目标私聊窗口
          <select id="historicalChatRebindContext">
            <option value="">请选择已有私聊</option>
            ${contexts.map((context) => `<option value="${escapeHtml(context.context_id)}">${escapeHtml(historicalChatContextLabel(context))}</option>`).join("")}
          </select>
        </label>
        <p>升级前已完成的批次也可修正；仅调整当前批次归属，不重新生成记忆，也不影响其他批次。</p>
        <button id="historicalChatRebindBtn" class="subtle" type="button" disabled>修正本批归属</button>
      </div>
    </details>
  `;
}

export function updateHistoricalChatRebindButton() {
  const button = $("#historicalChatRebindBtn");
  if (button) button.disabled = !$("#historicalChatRebindContext")?.value;
}

export function prepareHistoricalChatRebind() {
  const batchId = state.historicalChatBatchId;
  const selectedId = String($("#historicalChatRebindContext")?.value || "");
  const context = historicalChatPrivateContexts().find((item) => item.context_id === selectedId);
  if (!batchId || !context) {
    showToast("请先选择目标私聊窗口", "error");
    return;
  }
  showInlineConfirmation({
    host: "#conversationImportResult",
    title: "修正本批记忆归属",
    message: `将当前导入批次合并到 ${historicalChatContextLabel(context)}。不会重新调用模型，也不会移动其他记忆。`,
    confirmLabel: "确认修正",
    busyText: "正在修正本批归属...",
    onConfirm: () => executeHistoricalChatRebind(context),
  });
}

export async function executeHistoricalChatRebind(context) {
  clearConversationImportResult();
  const data = await apiPost("/conversation-import/rebind", {
    batch_id: state.historicalChatBatchId,
    user_id: context.target_id,
    user_name: context.display_name || "",
    session_id: context.session_id,
    platform: context.session_id.includes(":") ? context.session_id.split(":", 1)[0] : "",
    bot_id: context.bot_id,
  });
  await refreshAll();
  await refreshHistoricalChatStatus();
  const relationshipStatus = data.result?.relationship_observations?.status || "";
  const relationshipNeedsReview = ["failed", "unsupported", "completed_with_warnings"].includes(relationshipStatus);
  showToast(
    relationshipNeedsReview
      ? "记忆已合并；关系候选需要人工核对"
      : "本批记忆已合并到目标私聊",
    relationshipNeedsReview ? "warning" : "success",
  );
}

export function historicalChatRollbackSummary(report) {
  if (!report || report.state !== "rolled_back") return "记忆库已标记回滚；旧批次没有完整回滚结果，关系候选需人工核对。";
  const relationship = report.relationship_observations || {};
  const complete = report.rollback_status === "completed" && ["completed", "not_needed"].includes(relationship.status);
  const label = complete ? "本批已回滚" : "回滚部分完成：记忆库已回滚";
  return `${label}。移除记忆 ${number(report.deleted?.memories)}、时间线 ${number(report.deleted?.timeline)}、片段 ${number(report.deleted?.segments)}。${relationship.message || "关系候选结果未确认，请人工核对。"}`;
}

export function renderHistoricalChatStatus(result) {
  const panel = $("#historicalChatPanel");
  if (!panel) return;
  state.historicalChatBatchView = result;
  panel.hidden = false;
  panel.innerHTML = '<div class="chat-import-section-head"><span><b>当前导入任务</b><small>阅读来源、当前进度与本批操作结果</small></span><button id="historicalChatNewImportBtn" class="subtle" type="button">导入另一份记录</button></div><div id="historicalChatStatus"></div>';
  $("#historicalChatNewImportBtn").addEventListener("click", resetHistoricalChatImportView);
  const box = $("#historicalChatStatus"), batch = result.batch || {};
  const completed = Number(batch.completed_segments || 0), total = Number(batch.total_segments || 0);
  const isFinished = ["completed", "completed_with_warnings"].includes(batch.state), rolledBack = batch.state === "rolled_back";
  const statusCounts = result.segment_status || {}, memoryCounts = batch.stats?.memory_counts || {};
  const errors = (result.recent_segments || []).filter(item => item.error);
  const progress = isFinished ? 100 : ({indexing:94,enriching:86,reconciling:78}[batch.state] || Math.round((total ? Math.min(1, completed / total) : 0) * 70));
  const identityLinks = batch.stats?.identity_links || {}, identityRebind = batch.stats?.identity_rebind || {};
  const relationshipRebind = batch.stats?.relationship_observation_rebind || {}, summaryPerspective = batch.stats?.summary_perspective || {}, detailQuality = batch.stats?.detail_quality || {};
  const report = batch.stats?.rollback_report;
  const outcome = rolledBack ? historicalChatRollbackSummary(report) : batch.state === "completed_with_warnings" ? "整理完成，但仍有警告。请核对任务提示和诊断；不能据此认定全部内容均已建立索引或可召回。" : batch.state === "completed" ? "整理完成。关系候选需在陪伴管理中人工确认；记忆是否使用仍受范围、有效状态和检索规则约束。" : batch.state === "paused" ? "已登记暂停。正在进行的片段可能继续收尾；不是撤销已经写入的内容。" : "当前任务尚未完成，可按需要查看进度或维护。";
  showHistoricalChatOutput(true); setHistoricalChatStep(3, isFinished);
  box.innerHTML = `
    <div class="chat-import-progress">
      <div class="chat-import-progress-head"><span><b>${escapeHtml(historicalChatBatchStateLabel(batch.state))}</b><small>${escapeHtml(batch.source_name || "未记录来源")}</small></span><small>${escapeHtml(formatTime(batch.updated_at))}</small></div>
      <div data-import-outcome class="chat-import-callout ${batch.state === "completed" || report?.rollback_status === "completed" ? "is-safe" : "is-warning"}"><span>${escapeHtml(outcome)}</span></div>
      ${batch.error ? `<div class="chat-import-callout is-warning"><b>任务提示</b><span>${escapeHtml(batch.error)}</span></div>` : ""}
      ${!rolledBack ? `<div class="import-stage"><span>阶段进度（估算） ${progress}% · 已整理 ${number(completed)}/${number(total)} 个片段</span><progress max="100" value="${progress}" aria-label="估算阶段进度"></progress></div>` : ""}
      <details data-import-provenance class="import-detail"><summary>来源与目标私聊</summary><dl>${[
        ["来源文件",batch.source_name],["批次",batch.id],["用户",[batch.user_name,batch.user_id].filter(Boolean).join(" · ")],["Bot",[batch.bot_name,batch.bot_id].filter(Boolean).join(" · ")],
        ["会话",batch.session_id],["平台 / 范围",[batch.platform,batch.scope].filter(Boolean).join(" / ")],["创建时间",formatTime(batch.created_at)],["更新时间",formatTime(batch.updated_at)],["导入前备份",batch.backup_path]
      ].map(([label,value])=>`<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || "未记录")}</dd></div>`).join("")}</dl><p>备份路径仅表示原批次记录，不证明文件目前仍存在。打开运行中任务会沿原接口接续中断的工作；“仅核对记录”不接续工作。</p></details>
      <details data-import-diagnostics class="import-detail"><summary>导入时统计与处理记录</summary><p>以下保留批次生成时的统计和处理记录，不代表当前仍可用或已召回；回滚后也保留这些来源记录。</p>
        <div class="chat-import-status-summary"><span><b>${number(batch.stats?.message_count)}</b><small>导入时消息数</small></span><span><b>${number(memoryCounts.total ?? batch.summary_memory_count)}</b><small>生成记忆统计</small></span><span><b>${number(batch.relationship_observation_count)}</b><small>批次记录的关系候选</small></span></div>
        <div class="chat-import-memory-breakdown"><span>片段回忆 ${number(memoryCounts.conversation_summary)}</span><span>重要事件 ${number(memoryCounts.important_event)}</span><span>日摘要 ${number(memoryCounts.daily_digest)}</span><span>稳定事实 ${number(memoryCounts.stable_fact)}</span><span>相处经历摘要 ${number(memoryCounts.relationship_phase_summary)}</span></div>
        ${Object.entries(statusCounts).map(([key,value])=>`<span class="import-segment">${escapeHtml(historicalChatSegmentStatusLabel(key))} ${number(value)}</span>`).join(" ")}
        ${batch.stats?.embedding?.enabled ? `<p>向量索引 ${number(batch.stats.embedding.indexed)}/${number(batch.stats.embedding.eligible)} · ${escapeHtml(batch.stats.embedding.status || "处理中")}</p>` : ""}
              ${identityRebind.to ? `<div class="chat-import-callout is-safe"><b>本批归属已修正</b><span>已合并到 ${escapeHtml(identityRebind.to.user_name || identityRebind.to.user_id || "目标用户")} 的私聊窗口，不影响其他批次和现有记忆。</span></div>` : ""}
      ${["failed", "unsupported", "completed_with_warnings"].includes(relationshipRebind.status) ? `<div class="chat-import-callout is-warning"><b>关系候选需人工核对</b><span>${escapeHtml(relationshipRebind.message || "记忆归属已修正，但陪伴插件中的关系候选未完全自动移动。")}</span></div>` : ""}
      ${Number(identityLinks.version || 0) > 0 ? `<div class="chat-import-callout is-safe"><b>私聊归属已统一</b><span>本批记忆已合并到用户 ${escapeHtml(identityLinks.target_user_id || batch.user_id || "-")} 的现有私聊窗口${Number(identityLinks.repaired_entities || 0) > 0 ? `，修复 ${number(identityLinks.repaired_entities)} 条实体关联` : ""}。</span></div>` : ""}
      ${Number(summaryPerspective.version || 0) > 0 ? `<div class="chat-import-callout is-safe"><b>记忆视角已校正</b><span>可召回正文统一使用明确称呼的第三人称摘要，不会把用户的“我”误认成 Bot。</span></div>` : ""}
      ${Number(detailQuality.version || 0) > 0 ? `<div class="chat-import-callout is-safe"><b>详细回忆已整理</b><span>片段回忆 ${number(detailQuality.conversation_summaries_enriched ?? detailQuality.conversation_summaries ?? batch.summary_memory_count)}/${number(detailQuality.conversation_summaries ?? batch.summary_memory_count)}，日摘要 ${number(detailQuality.daily_digests_enriched ?? detailQuality.daily_digests ?? memoryCounts.daily_digest)}/${number(detailQuality.daily_digests ?? memoryCounts.daily_digest)}；事件与稳定事实继续保持原子化，避免重复和混淆。</span></div>` : ""}

        ${errors.map(item=>`<p>片段 ${number(Number(item.segment_index || 0)+1)} · ${escapeHtml(item.error)}</p>`).join("")}
      </details>
      <div class="chat-import-primary-actions">
        ${batch.state === "running" ? '<button id="historicalChatPauseBtn" type="button">暂停</button>' : ""}
        ${["paused","failed","prepared"].includes(batch.state) ? '<button id="historicalChatResumeBtn" type="button">恢复</button>' : ""}
        ${!rolledBack ? '<button id="historicalChatRefreshBtn" class="subtle" type="button">读取任务进度</button>' : ""}
        <button data-import-reconcile class="subtle" type="button">仅核对记录</button>
      </div>
      <details data-import-maintenance class="import-detail"><summary>归属修正与回滚</summary><p>回滚删除本批记忆库记录，并尝试移除本批待确认关系观察。已确认关系、原始文件和备份不在清理范围。记忆库和关系资料分别处理，可能部分完成；不撤回聊天消息。</p>
        ${historicalChatRebindPanel(batch)}
        ${!rolledBack ? '<button id="historicalChatRollbackBtn" class="danger subtle" type="button">整批回滚</button>' : '<p>已回滚批次没有重复回滚入口。部分结果请在对应资料中核对。</p>'}
      </details>
    </div>`;
  $("#historicalChatPauseBtn")?.addEventListener("click", () => withBusy("正在暂停...", pauseHistoricalChatImport));
  $("#historicalChatResumeBtn")?.addEventListener("click", () => withBusy("正在恢复...", resumeHistoricalChatImport));
  $("#historicalChatRefreshBtn")?.addEventListener("click", () => withBusy("正在读取进度...", refreshHistoricalChatStatus));
  box.querySelector('[data-import-reconcile]')?.addEventListener("click", () => withBusy("正在核对批次记录...", reconcileHistoricalChatAction));
  $("#historicalChatRollbackBtn")?.addEventListener("click", prepareHistoricalChatRollback);
  $("#historicalChatRebindContext")?.addEventListener("change", updateHistoricalChatRebindButton);
  $("#historicalChatRebindBtn")?.addEventListener("click", prepareHistoricalChatRebind);
  renderHistoricalChatActionResult();
}

export function resetHistoricalChatImportView() {
  stopHistoricalChatPoll();
  state.historicalChatPreview = null;
  state.historicalChatPreviewSource = "";
  state.historicalChatBatchId = "";
  state.historicalChatTargetContextId = "";
  clearConversationImportResult();
  renderHistoricalChatPreview(null);
  setHistoricalChatStep(0);
  showHistoricalChatOutput(false);
  document.querySelector(`[data-import-source="${conversationImportSource()}"]`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

export function renderHistoricalChatActionResult() {
  const outcome = state.historicalChatOutcomes.get(state.historicalChatBatchId);
  const host = $("#conversationImportResult");
  if (!host) return;
  // A status read must not erase an unsubmitted confirmation.
  if (host.querySelector('[data-inline-confirm]')) return;
  if (!outcome) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.innerHTML = `<div data-import-action-result role="status" class="chat-import-callout ${outcome.unknown || outcome.warning ? "is-warning" : "is-safe"}"><span>${escapeHtml(outcome.message)}</span></div>`;
  if (outcome.unknown) {
    ['#historicalChatPauseBtn','#historicalChatResumeBtn','#historicalChatRollbackBtn','#historicalChatRebindBtn','#historicalChatRefreshBtn','#historicalChatRebindContext'].forEach(selector => { const control = $(selector); if (control) control.disabled = true; });
  }
}

export async function reconcileHistoricalChatAction() {
  const id = state.historicalChatBatchId, previous = state.historicalChatOutcomes.get(id);
  try {
    // No batch_id: the original list read does not repair legacy batches or
    // restart workers, unlike the detail status endpoint.
    const data = await apiGet("/conversation-import/status");
    if (!Array.isArray(data.result?.batches)) throw new Error("批次列表未完整返回");
    state.historicalChatBatches = data.result.batches;
    renderHistoricalChatBatchList();
    const batch = data.result.batches.find(item => item.id === id);
    if (!batch) throw new Error("列表未找到该批次，操作结果仍需核对");
    const terminal = ["completed","completed_with_warnings","rolled_back"].includes(batch.state);
    const resolved = !previous?.unknown || (previous.kind === "rollback" ? batch.state === "rolled_back" : previous.kind === "pause" ? batch.state === "paused" || terminal : ["running","reconciling","enriching","indexing"].includes(batch.state) || terminal);
    const message = `当前批次：${historicalChatBatchStateLabel(batch.state)}。${batch.state === "rolled_back" ? historicalChatRollbackSummary(batch.stats?.rollback_report) : "已核对保存的记录，未启动工作。"}${resolved ? "" : "先前操作结果仍未确认，请稍后仅核对记录；不要重复提交。"}`;
    state.historicalChatOutcomes.set(id, {kind:previous?.kind, unknown:!resolved, warning:!resolved || batch.stats?.rollback_report?.rollback_status === "partial", message});
    if (state.historicalChatBatchId === id) renderHistoricalChatStatus({batch});
    return {batch};
  } catch (error) {
    state.historicalChatOutcomes.set(id, {...previous, warning:true, message:`${previous?.message || "未更改任务。"} 记录读取失败：${error.message || "未知错误"}。可使用“仅核对记录”，不会自动重试操作。`});
    if (state.historicalChatBatchId === id) renderHistoricalChatActionResult();
    return null;
  }
}

export async function historicalChatControl(kind, id = state.historicalChatBatchId) {
  if (!id || state.historicalChatOutcomes.get(id)?.unknown) return;
  clearConversationImportResult();
  stopHistoricalChatPoll();
  let result;
  try {
    const data = await apiPost(`/conversation-import/${kind}`, {batch_id:id});
    result = data.result;
    const returnedId = kind === "rollback" ? result?.batch_id : result?.batch?.id;
    if (returnedId !== id || (kind === "rollback" ? result?.state !== "rolled_back" : !result?.batch?.state)) throw new Error("接口未返回完整批次结果");
    if (kind === "rollback" && !["memories", "timeline", "segments"].every(key => Number.isInteger(result.deleted?.[key]) && result.deleted[key] >= 0)) throw new Error("回滚结果缺少已处理记录数量");
  } catch (error) {
    state.historicalChatOutcomes.set(id, {kind, unknown:true, warning:true, message:`操作结果未确认：${error.message || "未收到结果"}。请先“仅核对记录”，不会自动重试提交。`});
    if (state.historicalChatBatchId === id) renderHistoricalChatActionResult();
    return;
  }
  if (kind === "rollback") {
    const old = state.historicalChatBatchView?.batch || {};
    state.historicalChatOutcomes.set(id, {kind, warning:result.rollback_status !== "completed", message:historicalChatRollbackSummary(result)});
    if (state.historicalChatBatchId === id) {
      renderHistoricalChatStatus({batch:{...old,id,state:"rolled_back",completed_segments:0,summary_memory_count:0,relationship_observation_count:0,stats:{...old.stats,rollback_report:result}}});
      await reconcileHistoricalChatAction();
    }
    return;
  }
  const current = result.batch.state;
  const active = ["running","reconciling","enriching","indexing"].includes(current);
  const message = kind === "pause" && current === "paused" ? "已暂停；当前片段可能继续收尾。" : kind === "resume" && active ? "已恢复，任务按原后台流程继续。" : `当前为${historicalChatBatchStateLabel(current)}，未重新启动或改变终态。`;
  state.historicalChatOutcomes.set(id, {kind, message});
  if (state.historicalChatBatchId === id) {
    renderHistoricalChatStatus(result);
    if (active) scheduleHistoricalChatPoll();
    showToast(message);
  }
}

export async function pauseHistoricalChatImport() { return historicalChatControl("pause"); }

export async function resumeHistoricalChatImport() { return historicalChatControl("resume"); }

export function prepareHistoricalChatRollback() {
  const id = state.historicalChatBatchId;
  showInlineConfirmation({
    host: "#conversationImportResult", title: "回滚历史对话导入",
    message: `将回滚批次 ${shortId(id)} 的记忆库记录，并尝试移除本批待确认关系观察；已确认关系、原始文件和备份不删除。其它批次不受影响，可能部分完成。`,
    confirmLabel: "确认回滚", busyText: "正在整批回滚...", dangerous: true,
    onConfirm: () => historicalChatControl("rollback", id),
  });
}

export async function repairLivingMemoryContent() {
  const path = livingMemoryPathValue("repair"), host = "#livingMemoryRepairResult";
  let result;
  try {
    result = (await apiPost("/maintenance/repair_livingmemory_content", { path })).result;
    if (!result || !Number.isInteger(result.updated) || !Number.isInteger(result.skipped)) throw new Error("修复收据不完整");
  } catch (error) { showArchiveTransferUnknown(host, path, error); return; }
  showArchiveResult(result, "repair", host);
  const refreshed = result.reason ? true : await refreshAfterArchiveTransfer(host);
  showToast(result.reason ? `修复未执行：${result.reason}` : result.error ? "修复未全部完成，请查看结果"
    : `已修复 ${result.updated} 条${refreshed ? "" : "，统计读取失败"}`, result.reason || result.error || !refreshed ? "error" : "success");
}

export async function clearAllMemoryData() {
  const box = $("#importResult");
  const warning = "这会清空全部记忆、权限规则、关系、时间线、身份、注入日志和导入批次。执行前会自动备份数据库。";
  if (!box) return;
  box.hidden = false;
  box.innerHTML = `
    <div class="clear-confirm">
      <b>确认清空全部记忆</b>
      <p>${escapeHtml(warning)}</p>
      <input id="clearAllConfirmText" type="text" placeholder="输入 清空 后执行" autocomplete="off" />
      <div class="inline-actions">
        <button id="executeClearAllMemoryBtn" class="danger" type="button" disabled>执行清空</button>
        <button id="cancelClearAllMemoryBtn" type="button">取消</button>
      </div>
    </div>
  `;
  const input = $("#clearAllConfirmText");
  const execute = $("#executeClearAllMemoryBtn");
  const cancel = $("#cancelClearAllMemoryBtn");
  const update = () => {
    execute.disabled = input.value.trim() !== "清空";
  };
  input.addEventListener("input", update);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !execute.disabled) {
      withBusy("正在清空全部记忆...", executeClearAllMemoryData);
    }
  });
  execute.addEventListener("click", () => withBusy("正在清空全部记忆...", executeClearAllMemoryData));
  cancel.addEventListener("click", () => {
    box.innerHTML = "";
    showToast("已取消清空操作");
  });
  input.focus();
  showToast("请在下方输入“清空”确认");
}

export async function executeClearAllMemoryData() {
  const confirmText = $("#clearAllConfirmText")?.value.trim();
  if (confirmText !== "清空") {
    showToast("请输入“清空”后再执行", "error");
    return;
  }
  const data = await apiPost("/maintenance/clear_all", { confirm: "清空" });
  state.activeBucketId = "all";
  clearDetail();
  await refreshAll();
  showArchiveResult(data.result);
  showToast("全部记忆已清空");
}

export function scopedClearPayload(scope) {
  const bucket = activeBucket();
  const requiredScope = scope === "group_member" ? "group" : scope;
  if (!bucket || bucket.id === "all" || bucket.scope !== requiredScope || !bucket.target_id) return null;
  if (scope === "group" || scope === "group_member") {
    const groupId = bucket.group_id || bucket.target_id;
    if (scope === "group_member") {
      const userId = String($("#clearGroupMemberUserId")?.value || "").trim();
      if (!userId) return null;
      return {
        target_type: "group_member",
        group_id: groupId,
        user_id: userId,
        label: `${bucket.label} 中的用户 ${userId}`,
      };
    }
    return {
      target_type: "group",
      group_id: groupId,
      label: bucket.label,
    };
  }
  return {
    target_type: "private",
    user_id: bucket.target_id,
    label: bucket.label,
  };
}

export function clearScopeCountsText(counts = {}) {
  const labels = {
    memories: "长期记忆",
    timeline: "时间线",
    relationship_edges: "关系边",
    knowledge_nodes: "图谱节点",
    knowledge_edges: "图谱边",
    injection_logs: "注入日志",
    summary_failures: "总结失败记录",
    cross_window_threads: "跨窗口线程",
  };
  return Object.entries(labels)
    .map(([key, label]) => `${label} ${Number(counts[key] || 0)}`)
    .join(" / ");
}

export function showScopedClearConfirm(payload, counts = {}) {
  const drawer = $("#detailDrawer");
  if (!drawer) return;
  drawer.className = "detail-drawer";
  drawer.innerHTML = `
    <div class="clear-confirm scoped-clear-confirm">
      <b>确认清空范围记忆</b>
      <p>将清空：<strong>${escapeHtml(payload.label || "当前范围")}</strong></p>
      <p class="scoped-clear-counts">${escapeHtml(clearScopeCountsText(counts))}</p>
      <input id="clearScopeConfirmText" type="text" placeholder="输入 清空 后执行" autocomplete="off" />
      <div class="inline-actions">
        <button id="executeClearScopeMemoryBtn" class="danger" type="button" disabled>执行清空</button>
        <button id="cancelClearScopeMemoryBtn" type="button">取消</button>
      </div>
    </div>
  `;
  const input = $("#clearScopeConfirmText");
  const execute = $("#executeClearScopeMemoryBtn");
  const cancel = $("#cancelClearScopeMemoryBtn");
  const update = () => {
    execute.disabled = input.value.trim() !== "清空";
  };
  input.addEventListener("input", update);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !execute.disabled) {
      withBusy("正在清空范围记忆...", () => executeScopedClearMemory(payload));
    }
  });
  execute.addEventListener("click", () => withBusy("正在清空范围记忆...", () => executeScopedClearMemory(payload)));
  cancel.addEventListener("click", () => {
    clearDetail();
    showToast("已取消清空操作");
  });
  input.focus();
  showToast("请在右侧输入“清空”确认");
}

export async function executeScopedClearMemory(payload) {
  const confirmText = $("#clearScopeConfirmText")?.value.trim();
  if (confirmText !== "清空") {
    showToast("请输入“清空”后再执行", "error");
    return;
  }
  const data = await apiPost("/maintenance/clear_scope", { ...payload, confirm: "清空" });
  state.activeBucketId = "all";
  await refreshAll();
  showGenericDetail("范围清理结果", data.result);
  showToast("范围记忆已清空");
}

export async function clearCurrentScopedMemory(scope) {
  const payload = scopedClearPayload(scope);
  if (!payload) {
    const message = scope === "group_member" ? "请先选择具体群聊并填写群成员 QQ" : `请先选择具体${scope === "group" ? "群聊" : "私聊用户"}`;
    showToast(message, "error");
    return;
  }
  const preview = await apiPost("/maintenance/clear_scope", { ...payload, preview: true });
  const counts = preview.result?.counts || {};
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
  if (total <= 0) {
    showToast("这个范围内没有可清理的数据");
    return;
  }
  showScopedClearConfirm(payload, counts);
}

export async function previewImport() {
  const path = livingMemoryPathValue();
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  const data = await apiGet(`/import/livingmemory/preview?${params.toString()}`);
  showArchiveResult(data.report, "preview", "#livingMemoryResult");
  bindArchiveTransferPaths("#livingMemoryResult");
  showToast("预览已生成");
}

export async function runImport() {
  const path = livingMemoryPathValue();
  showInlineConfirmation({
    host: "#livingMemoryResult",
    title: "导入 LivingMemory",
    message: path
      ? `将从 ${path} 按原规则导入可用摘要表，跳过派生碎片；是否备份沿当前配置。若路径不可用，原扫描可能选择其他库，请核对执行结果。`
      : "将从自动发现的 LivingMemory 数据库按原规则导入可用摘要表，跳过派生碎片；是否备份沿当前配置。若路径不可用，原扫描可能选择其他库，请核对执行结果。",
    confirmLabel: "执行导入",
    busyText: "正在导入 LivingMemory...",
    onConfirm: () => executeLivingMemoryImport(path),
  });
}

export async function executeLivingMemoryImport(path) {
  const host = "#livingMemoryResult";
  let result;
  try {
    result = (await apiPost("/import/livingmemory/run", { path })).result;
    if (!result || !Number.isInteger(result.imported) || !Number.isInteger(result.skipped)) throw new Error("导入收据不完整");
  } catch (error) { showArchiveTransferUnknown(host, path, error); return; }
  showArchiveResult(result, "import", host);
  if (result.reason && !result.source_path) { showToast(`导入未执行：${result.reason}`, "error"); return; }
  const refreshed = await refreshAfterArchiveTransfer(host);
  showToast(refreshed ? "LivingMemory 导入完成，请查看实际数量与来源" : "导入完成，统计读取失败；结果已保留", refreshed ? "success" : "error");
}

export function installMemoryAuditOwnerControls() {
  const host = $("#memoryAuditPreviewBtn")?.closest(".memory-audit-controls");
  if (!host || $("#memoryAuditOwnerScope")) return;
  const controls = document.createElement("div");
  controls.className = "memory-audit-controls";
  controls.innerHTML = `
    <label>已确证的完整归属范围
      <select id="memoryAuditOwnerScope"><option value="">请先读取归属</option></select>
    </label>
    <button id="memoryAuditOwnersRefresh" class="subtle" type="button">刷新归属</button>
    <label><input id="memoryAuditAllScopes" type="checkbox" /> 跨全部已确认范围（不含待归属）</label>
    <label id="memoryAuditAllScopesConfirmBox" hidden>再次确认
      <input id="memoryAuditAllScopesConfirm" type="text" placeholder="所有已确认归属" autocomplete="off" />
    </label>
    <p id="memoryAuditOwnerSummary" class="archive-note" aria-live="polite">旧档案缺少完整角色归属时继续待处理，不按称呼或当前聊天推断。</p>`;
  host.before(controls);
  $("#memoryAuditOwnersRefresh")?.addEventListener("click", (event) =>
    withButton(event.currentTarget, "读取中", loadMemoryAuditOwners));
  $("#memoryAuditAllScopes")?.addEventListener("change", () => {
    const all = Boolean($("#memoryAuditAllScopes")?.checked);
    $("#memoryAuditOwnerScope").disabled = all;
    $("#memoryAuditAllScopesConfirmBox").hidden = !all;
    $("#memoryAuditAllScopesConfirm").value = "";
  });
}

export async function loadMemoryAuditOwners() {
  installMemoryAuditOwnerControls();
  const select = $("#memoryAuditOwnerScope");
  if (!select) return;
  const previous = select.value;
  const limit = Math.max(0, Math.min(100, Number($("#memoryAuditLimit")?.value || 0)));
  try {
    const data = await apiGet(`/maintenance/audit/owners?limit=${encodeURIComponent(limit)}`);
    const result = data.result || {};
    state.memoryAuditOwnerScopes = Array.isArray(result.owner_scopes) ? result.owner_scopes : [];
    select.innerHTML = '<option value="">请选择；不自动采用当前会话</option>' + state.memoryAuditOwnerScopes.map((row) => {
      const owner = row.owner_scope || {};
      const label = `${owner.platform || ""} · ${owner.user_id || ""} · ${owner.character_id || ""} · ${owner.session_id || ""}（${Number(row.candidate_count || 0)} 条）`;
      return `<option value="${escapeHtml(JSON.stringify(owner))}">${escapeHtml(label)}</option>`;
    }).join("");
    select.value = [...select.options].some((option) => option.value === previous) ? previous : "";
    $("#memoryAuditOwnerSummary").textContent = `本次检查 ${Number(result.scanned_count || 0)} 条（上限 ${Number(result.scan_limit || 0)}），待归属 ${Number(result.pending_unassigned || 0)} 条；${state.memoryAuditOwnerScopes.length} 个已有明确来源的范围。${result.scan_complete ? "" : "这不是全库总数。"}待归属原文不发送给模型。`;
  } catch (error) {
    state.memoryAuditOwnerScopes = [];
    select.innerHTML = '<option value="">归属读取失败</option>';
    $("#memoryAuditOwnerSummary").textContent = `无法读取归属：${error.message || "请求失败"}；不会据当前聊天补造归属。`;
    throw error;
  }
}

export function memoryAuditOutcome(batch, action = "") {
  const items = Array.isArray(batch.items) ? batch.items.filter(Boolean) : [];
  const applied = Array.isArray(batch.applied_results) ? batch.applied_results.filter(Boolean) : [];
  const rolled = Array.isArray(batch.rollback_results) ? batch.rollback_results.filter(Boolean) : [];
  const rollback = action ? action === "rollback" : Boolean(rolled.length || batch.rolled_back_at || batch.status === "rolled_back");
  const rows = rollback ? rolled : applied;
  const expected = rollback ? applied.filter(row => row.status === "applied") : items;
  const expectedIds = new Set(expected.map(row => String(row.memory_id || "")));
  const resultIds = new Set(rows.map(row => String(row.memory_id || "")));
  const success = rollback ? "rolled_back" : "applied";
  const done = rows.filter(row => row.status === success).length;
  const completeRows = rows.length === expected.length && resultIds.size === rows.length
    && expectedIds.size === expected.length && [...resultIds].every(id => id && expectedIds.has(id));
  const complete = batch.status === success && completeRows && done === expected.length;
  const verb = rollback ? "回滚" : "应用";
  const message = complete ? (expected.length ? `已${verb} ${done} 项，全部完成。` : "本批没有需要应用的变更。")
    : !completeRows ? `结果不完整：已${verb} ${done} 项，请读取状态核对。`
    : `部分完成：已${verb} ${done} / ${expected.length} 项，其余未完成，请查看逐条结果。`;
  return {rollback, rows, applied, done, total: expected.length, resultsComplete: completeRows, complete, message};
}

export function memoryAuditResultInfo(status) {
  return ({
    applied: ["已应用", "success", "该项已写入当前记忆。"],
    rolled_back: ["已回滚", "success", "该项已恢复到本批应用前的内容。"],
    stale: ["记录已更新", "attention", "本次跳过，保留后来修改；请查看当前记录。"],
    missing: ["记录已不存在", "attention", "本次未修改，不能恢复已删除的记录。"],
    failed: ["未完成", "attention", "该项未完成，请先读取状态并核对当前记录。"],
    invalid_action: ["操作不受支持", "attention", "本次未修改，请重新检查审计预览。"],
  })[status] || ["结果待核对", "attention", "当前返回未说明完成情况，请读取状态核对。"];
}

export function renderMemoryAuditBatch(batch) {
  const host = $("#memoryAuditResult");
  if (!host) return;
  state.memoryAuditBatch = batch && typeof batch === "object" ? batch : null;
  if (!state.memoryAuditBatch) {
    host.innerHTML = '<div class="empty-state">尚未读取审计批次。</div>';
    return;
  }
  const items = Array.isArray(batch.items) ? batch.items : [];
  const status = String(batch.status || "unknown");
  const outcome = memoryAuditOutcome(batch);
  const unconfirmed = state.memoryAuditUnconfirmedBatchId === batch.batch_id;
  const statusLabel = unconfirmed || (status !== "preview" && !outcome.resultsComplete) ? "结果待核对"
    : ({preview: "待确认预览", applied: "已应用", partial: "部分完成", rolled_back: "已回滚"})[status] || "状态待核对";
  const itemMap = new Map(items.map(item => [String(item.memory_id || ""), item]));
  const resultRows = (rows) => rows.map(row => {
    const [label, tone, hint] = memoryAuditResultInfo(row.status);
    const id = String(row.memory_id || "");
    const proposal = itemMap.get(id);
    return `<article class="memory-audit-result-row" data-memory-audit-result-status="${escapeHtml(row.status || "unknown")}">
      <div><span class="memory-audit-status" data-tone="${tone}">${label}</span><code>${escapeHtml(shortId(id))}</code></div>
      <p>${hint}</p>${proposal?.reason ? `<small>${escapeHtml(compact(proposal.reason, ""))}</small>` : ""}
      ${id && row.status !== "missing" ? `<button type="button" class="subtle" data-memory-audit-open="${escapeHtml(id)}">查看当前记录</button>` : ""}
    </article>`;
  }).join("");
  const resultSection = outcome.rows.length ? `<section class="memory-audit-results" aria-label="${outcome.rollback ? "回滚" : "应用"}结果">
    <h4>${outcome.rollback ? "回滚" : "应用"}结果 · 已完成 ${outcome.done} / ${outcome.total}</h4>${resultRows(outcome.rows)}</section>` : "";
  const canRollback = ["applied", "partial"].includes(status) && outcome.resultsComplete && outcome.applied.some(row => row.status === "applied");
  host.innerHTML = `
    <div class="memory-audit-summary">
      <span><em>批次</em><strong>${escapeHtml(batch.batch_id || "-")}</strong></span>
      <span><em>状态</em><strong>${escapeHtml(statusLabel)}</strong></span>
      <span><em>候选</em><strong>${escapeHtml(batch.candidate_count || 0)}</strong></span>
      <span><em>建议</em><strong>${escapeHtml(items.length)}</strong></span>
    </div>
    ${unconfirmed ? '<p class="memory-audit-notice" data-tone="attention" role="status">操作结果未确认。请先读取状态，不要重复提交；读取只查询已有批次。</p>'
      : status !== "preview" ? `<p class="memory-audit-notice" data-tone="${outcome.complete ? "success" : "attention"}" role="status">${escapeHtml(outcome.message)}</p>` : ""}
    ${typeof batch.pending_unassigned === "number" ? `<p class="archive-note">本次检查 ${Number(batch.scanned_count || 0)} 条，待归属 ${Number(batch.pending_unassigned)} 条，其他范围未选 ${Number(batch.excluded_other_scope || 0)} 条；${batch.model_requested ? "仅已确证归属且有引用证据的材料参与模型预览" : "本批未调用模型"}。${batch.owner_scope ? `当前范围：${escapeHtml(batch.owner_scope.platform || "")} · ${escapeHtml(batch.owner_scope.character_id || "")} · ${escapeHtml(batch.owner_scope.session_id || "")}` : batch.all_scopes ? "已明确确认跨全部已确证范围，不含待归属材料。" : "尚未选择完整归属范围。"}</p>` : ""}
    ${resultSection}
    ${outcome.rollback && outcome.applied.length ? `<details class="memory-audit-prior"><summary>查看应用时的结果（${outcome.applied.length} 项）</summary>${resultRows(outcome.applied)}</details>` : ""}
    ${items.length ? `<details class="memory-audit-proposals" ${status === "preview" && !unconfirmed ? "open" : ""}><summary>原审计建议（${items.length} 项）</summary><div class="memory-audit-items">${items.map((item) => `
      <article>
        <div><b>${escapeHtml(item.action === "archive" ? "建议归档" : "建议修正")}</b><code>${escapeHtml(shortId(item.memory_id || ""))}</code></div>
        <p>${escapeHtml(item.reason || "未提供原因")}</p>
        ${item.proposed_content ? `<small>${escapeHtml(compact(item.proposed_content, ""))}</small>` : ""}
      </article>
    `).join("")}</div></details>` : '<div class="empty-state">该批次没有需要修改的建议。</div>'}
    <div class="inline-actions memory-audit-result-actions">
      ${batch.batch_id ? '<button data-memory-audit-refresh type="button">读取最新状态</button>' : ""}
      ${!unconfirmed && status === "preview" && items.length ? '<button data-memory-audit-action="apply" class="danger subtle" type="button">应用此批次</button>' : ""}
      ${!unconfirmed && canRollback ? '<button data-memory-audit-action="rollback" class="danger subtle" type="button">回滚已应用项</button>' : ""}
    </div>
  `;
  host.querySelector('[data-memory-audit-action="apply"]')?.addEventListener("click", () => confirmMemoryAuditAction("apply"));
  host.querySelector('[data-memory-audit-action="rollback"]')?.addEventListener("click", () => confirmMemoryAuditAction("rollback"));
  host.querySelector('[data-memory-audit-refresh]')?.addEventListener("click", () => {
    $("#memoryAuditBatchId").value = batch.batch_id;
    withBusy("正在核对审计结果...", loadMemoryAuditStatus);
  });
  host.querySelectorAll('[data-memory-audit-open]').forEach(button => button.addEventListener("click", () =>
    withBusy("正在读取当前记忆...", async () => {
      await showMemory(button.dataset.memoryAuditOpen);
      $("#detailDrawer")?.scrollIntoView({block: "start"});
    })));
}

export async function previewMemoryAudit() {
  const limit = Math.max(0, Math.min(100, Number($("#memoryAuditLimit")?.value || 0)));
  await loadMemoryAuditOwners();
  const allScopes = Boolean($("#memoryAuditAllScopes")?.checked);
  const selected = $("#memoryAuditOwnerScope")?.value || "";
  const owner = selected === "" ? null : state.memoryAuditOwnerScopes?.find((row) => JSON.stringify(row.owner_scope) === selected)?.owner_scope;
  const confirm = String($("#memoryAuditAllScopesConfirm")?.value || "");
  if (allScopes && confirm !== "所有已确认归属") throw new Error("请填写‘所有已确认归属’，待归属材料仍不会发送给模型");
  if (!allScopes && !owner && state.memoryAuditOwnerScopes?.length) throw new Error("请明确选择完整归属范围，不会自动采用当前会话");
  const data = await apiPost("/maintenance/audit/preview", {
    limit, owner_scope: allScopes ? null : owner || null,
    all_scopes: allScopes, confirm_all_scopes: allScopes ? confirm : "",
  });
  const batch = data.result || {};
  if ($("#memoryAuditBatchId")) $("#memoryAuditBatchId").value = batch.batch_id || "";
  renderMemoryAuditBatch(batch);
  showToast("审计预览已生成");
}

export async function loadMemoryAuditStatus() {
  const batchId = String($("#memoryAuditBatchId")?.value || "").trim();
  if (!batchId) throw new Error("请先填写审计批次 ID");
  const data = await apiGet(`/maintenance/audit/status?batch_id=${encodeURIComponent(batchId)}`);
  if (data.result?.batch_id !== batchId) throw new Error("返回的批次不匹配，请重新读取状态");
  if (state.memoryAuditUnconfirmedBatchId === batchId) state.memoryAuditUnconfirmedBatchId = "";
  renderMemoryAuditBatch(data.result || {});
}

export function confirmMemoryAuditAction(action) {
  const batch = state.memoryAuditBatch;
  if (!batch?.batch_id) return;
  if (state.memoryAuditUnconfirmedBatchId === batch.batch_id) return;
  const rollback = action === "rollback";
  showInlineConfirmation({
    host: "#memoryAuditResult",
    title: rollback ? "回滚记忆审计" : "应用记忆审计",
    message: rollback
      ? "将按该批次保存的变更前快照恢复记录。执行前会再次备份当前数据库。"
      : `将应用 ${Array.isArray(batch.items) ? batch.items.length : 0} 条证据约束建议。执行前会自动备份数据库。`,
    confirmLabel: rollback ? "确认回滚" : "确认应用",
    busyText: rollback ? "正在回滚审计..." : "正在应用审计...",
    dangerous: true,
    onConfirm: () => executeMemoryAuditAction(action, batch.batch_id),
    onCancel: () => renderMemoryAuditBatch(batch),
  });
}

export async function executeMemoryAuditAction(action, batchId) {
  const endpoint = action === "rollback" ? "/maintenance/audit/rollback" : "/maintenance/audit/apply";
  let batch;
  try {
    const data = await apiPost(endpoint, { batch_id: batchId, confirm: "确认" });
    if (data.result?.batch_id !== batchId) throw new Error("返回的批次不匹配");
    batch = data.result;
  } catch (error) {
    state.memoryAuditUnconfirmedBatchId = batchId;
    renderMemoryAuditBatch(state.memoryAuditBatch);
    showToast(`操作结果未确认，请读取状态：${error.message || "连接中断"}`, "error");
    return;
  }
  state.memoryAuditUnconfirmedBatchId = "";
  renderMemoryAuditBatch(batch);
  const outcome = memoryAuditOutcome(batch, action);
  let statsFailed = false;
  try { await loadStats(); } catch (_) { statsFailed = true; }
  showToast(outcome.message + (statsFailed ? " 统计暂未刷新。" : ""), outcome.complete && !statsFailed ? "info" : "error");
}

export async function refreshAll() {
  await loadCompanionAvailability();
  await loadStats();
  const bucketsLoaded = await loadBuckets();
  if (!bucketsLoaded) return;
  await loadActiveView();
}

export function bindActions() {
  installMemoryAuditOwnerControls();
  bindArchiveJumpButtons(document);
  const stage = document.querySelector(".projection-stage");
  const layoutButtons = $$(".overview-layout-option");
  layoutButtons.forEach((button, index) => {
    button.addEventListener("click", () => setOverviewLayout(button.dataset.overviewLayout));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + layoutButtons.length) % layoutButtons.length;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % layoutButtons.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = layoutButtons.length - 1;
      const next = layoutButtons[nextIndex];
      setOverviewLayout(next?.dataset.overviewLayout);
      next?.focus();
    });
  });
  $("#standardOverview")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-overview-view]");
    if (!button || !$("#standardOverview").contains(button)) return;
    const view = button.dataset.overviewView;
    if (!VIEWS[view]) return;
    if (button.dataset.userMemoryFilter) state.userMemoryFilter = button.dataset.userMemoryFilter;
    const bucketId = button.dataset.overviewBucket || "";
    if (bucketId && state.buckets.some((bucket) => bucket.id === bucketId)) {
      state.activeBucketId = bucketId;
      void openView(view, { preserveBucket: true });
      return;
    }
    void openView(view);
  });
  $$(".filmstrip").forEach((strip) => {
    const style = strip.getAttribute("style") || "";
    const ang = parseFloat((style.match(/--a:\s*(-?[\d.]+)deg/) || [0,0])[1]);
    const off = parseFloat((style.match(/--off:\s*(-?[\d.]+)px/) || [0,0])[1]);
    const initialAxis = parseFloat((style.match(/--tx:\s*(-?[\d.]+)px/) || [0,0])[1]);
    const a   = ang * Math.PI / 180;
    const label = strip.querySelector(".strip-label");
    let baseAxisOffset = 0;
    let labelBaseShift = 0;
    const measureStrip = () => {
      const r = stage.getBoundingClientRect();
      const s = strip.getBoundingClientRect();
      const cx = s.left + s.width / 2 - r.left - r.width / 2;
      const cy = s.top + s.height / 2 - r.top - r.height / 2;
      baseAxisOffset = cx * Math.cos(a) + cy * Math.sin(a);
      const labelCenter = label ? label.offsetLeft + label.offsetWidth / 2 : strip.clientWidth / 2;
      labelBaseShift = strip.clientWidth / 2 - labelCenter;
    };
    measureStrip();
    const setStripTransform = (offset, axis = initialAxis, duration = ".86s") => {
      strip.style.transition = `transform ${duration} cubic-bezier(.16,.72,.18,1)`;
      strip.style.transform = `rotate(${ang}deg) translateY(${offset}px) translateX(${axis}px)`;
    };
    strip.addEventListener("mouseenter", measureStrip);
    strip.addEventListener("mousemove", (e) => {
      const r = stage.getBoundingClientRect();
      const dx = e.clientX - r.left - r.width/2;
      const dy = e.clientY - r.top  - r.height/2;
      // 仅沿胶卷轴向移动，并把胶卷标签带到鼠标投影位置。
      const raw = dx * Math.cos(a) + dy * Math.sin(a) - baseAxisOffset;
      const axis = initialAxis + raw + labelBaseShift;
      setStripTransform(off, axis, ".86s");
    });
    strip.addEventListener("mouseleave", () => {
      strip.style.transition = "transform .95s cubic-bezier(.18,.88,.22,1)";
      strip.style.transform  = `rotate(${ang}deg) translateY(${off}px) translateX(${initialAxis}px)`;
    });
    strip.addEventListener("click", () => {
      if (strip.dataset.userMemoryFilter) state.userMemoryFilter = strip.dataset.userMemoryFilter;
      openView(strip.dataset.view);
    });
  });
  $("#backHomeBtn").addEventListener("click", returnHome);
  $("#refreshBtn").addEventListener("click", () => playRailRefreshTransition(refreshAll));
  $("#loadActiveBtn").addEventListener("click", () => withBusy("正在重载当前帧...", loadActiveView));
  $("#clearTargetBtn").addEventListener("click", () => {
    if (state.activeView === "review") {
      selectPersonalDate(todayKey());
    } else if (currentRailScope()) {
      selectBucket("all");
    } else if (secondaryNavItems(state.activeView).length) {
      selectSecondaryNav(defaultSecondaryNav(state.activeView));
    } else {
      selectBucket("all");
    }
  });
  $("#runSearchBtn").addEventListener("click", runSearch);
  $$('[data-user-memory-filter]').forEach((button) => {
    if (!button.closest('#view-relations')) return;
    button.addEventListener('click', () => selectUserMemoryFilter(button.dataset.userMemoryFilter));
  });
  $("#microscopeContext")?.addEventListener("change", (event) => {
    state.microscopeBucketId = event.currentTarget.value || "all";
    updateMicroscopeContextMeta();
    invalidateMicroscopeSearch("检索范围已切换，请重新检索。");
    $("#searchQuery")?.focus();
  });
  $("#searchQuery")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || (!event.ctrlKey && !event.metaKey)) return;
    event.preventDefault();
    const button = $("#runSearchBtn");
    if (button && !button.disabled) runSearch();
  });
  $("#searchQuery")?.addEventListener("input", () => {
    invalidateMicroscopeSearch("检索内容已修改，请重新检索。");
  });
  $("#maintenanceBtn").addEventListener("click", () => withBusy("正在运行维护...", runMaintenance));
  $("#operationsDiagnosticsBtn").addEventListener("click", () => withBusy("正在生成运维诊断...", runOperationsDiagnostics));
  $("#memoryAuditPreviewBtn")?.addEventListener("click", () => withBusy("正在生成记忆审计预览...", previewMemoryAudit));
  $("#memoryAuditStatusBtn")?.addEventListener("click", () => withBusy("正在读取审计批次...", loadMemoryAuditStatus));
  $$('[data-operation-preset]').forEach((button) => {
    button.addEventListener("click", () => withBusy("正在应用运行预设...", () => applyOperationPreset(button.dataset.operationPreset)));
  });
  $("#portableExportBtn").addEventListener("click", () => withBusy("正在导出可移植档案...", exportPortableArchive));
  $("#portablePreviewBtn").addEventListener("click", () => withBusy("正在读取可移植档案...", previewPortableArchive));
  $("#portableImportBtn").addEventListener("click", () => withBusy("正在导入可移植档案...", importPortableArchive));
  const conversationImportTabs = $$('[data-import-source-tab]');
  conversationImportTabs.forEach((button, index) => {
    button.addEventListener("click", async () => {
      try {
        await selectConversationImportSource(button.dataset.importSourceTab);
      } catch (error) {
        showToast(error.message || "切换导入来源失败", "error");
      }
    });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = conversationImportTabs[(index + offset + conversationImportTabs.length) % conversationImportTabs.length];
      next?.focus();
      next?.click();
    });
  });
  $("#qqHistoryCapabilityBtn")?.addEventListener("click", (event) => withButton(event.currentTarget, "检测中", () => loadQQHistoryCapabilities(true)));
  $("#qqHistoryPreviewBtn")?.addEventListener("click", () => withBusy("正在读取 QQ 历史...", previewQQHistoryImport));
  $("#historicalChatRecentRefreshBtn")?.addEventListener("click", (event) => withButton(event.currentTarget, "刷新中", loadHistoricalChatBatchList));
  $$("#qqHistoryPlatform, #qqHistoryUserId, #qqHistoryStartAt, #qqHistoryEndAt").forEach((control) => {
    control.addEventListener("change", updateQQHistoryValidation);
    control.addEventListener("input", updateQQHistoryValidation);
  });
  $("#qqHistoryUserId")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !$("#qqHistoryPreviewBtn")?.disabled) {
      event.preventDefault();
      $("#qqHistoryPreviewBtn")?.click();
    }
  });
  $("#historicalChatPreviewBtn")?.addEventListener("click", () => withBusy("正在解析历史对话...", previewHistoricalChatImport));
  $("#historicalChatRecentTopBtn")?.addEventListener("click", () => withBusy("正在读取最近任务...", loadRecentHistoricalChatBatch));
  $("#historicalChatFile")?.addEventListener("change", (event) => selectHistoricalChatFile(event.target.files?.[0]));
  $("#historicalChatBaseYear")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !$("#historicalChatPreviewBtn")?.disabled) {
      event.preventDefault();
      $("#historicalChatPreviewBtn")?.click();
    }
  });
  const historicalDropzone = $("#historicalChatDropzone");
  historicalDropzone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    historicalDropzone.classList.add("is-dragging");
  });
  historicalDropzone?.addEventListener("dragleave", () => historicalDropzone.classList.remove("is-dragging"));
  historicalDropzone?.addEventListener("drop", (event) => {
    event.preventDefault();
    historicalDropzone.classList.remove("is-dragging");
    selectHistoricalChatFile(event.dataTransfer?.files?.[0]);
  });
  historicalDropzone?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      $("#historicalChatFile")?.click();
    }
  });
  $("#repairLivingMemoryBtn").addEventListener("click", () => withBusy("正在修复 LivingMemory 内容...", repairLivingMemoryContent));
  $("#clearAllMemoryBtn").addEventListener("click", clearAllMemoryData);
  $("#clearCurrentGroupMemoryBtn")?.addEventListener("click", () => withBusy("正在预览范围清理...", () => clearCurrentScopedMemory("group")));
  $("#clearGroupMemberMemoryBtn")?.addEventListener("click", () => withBusy("正在预览群成员记忆清理...", () => clearCurrentScopedMemory("group_member")));
  $("#clearCurrentPrivateMemoryBtn")?.addEventListener("click", () => withBusy("正在预览范围清理...", () => clearCurrentScopedMemory("private")));
  $("#previewImportBtn").addEventListener("click", () => withBusy("正在扫描 LivingMemory...", previewImport));
  $("#runImportBtn").addEventListener("click", () => withBusy("正在导入 LivingMemory...", runImport));
  $("#globalSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadActiveView();
  });
  $("#bucketList").addEventListener("scroll", requestRailCoverflow, { passive: true });
  $("#bucketList").addEventListener("pointermove", requestRailCoverflow, { passive: true });
  window.addEventListener("resize", requestRailCoverflow);
}
