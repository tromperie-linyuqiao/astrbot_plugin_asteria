/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {activeAlbumIndex,hydratePersonalAlbumImages,renderAlbumCard,renderCompanionSchedulePanel,renderSubjectiveMemoryPanel,showMemory,showPersonalActionsDetail,showPersonalAlbumDetail,showPersonalScheduleDetail,showPersonalSubjectiveDetail,updateScheduleSummary} from './configuration.js';
import {memoryOption,showInlineConfirmation} from './editors.js';
import {renderPersonalDateRail} from './overview.js';
import {$,PERSONAL_MEMORY_VIEW,VIEWS,asteriaWorkspaceState,portraitBrowse,state} from './state.js';
import {compact,escapeHtml,formatTime,loadingState,number,prefersReducedMotion,shortId,showToast,waitForMotion,withBusy} from './workspace.js';

export function portraitModeText(value) {
  return {disabled: "关闭", use_existing: "仅使用已有", learn_and_use: "学习并使用"}[String(value || "")] || value || "未提供模式";
}

export function portraitValueLabel(value) {
  return {active: "有效记录", archived: "已归档", exact: "精确身份", unknown: "未确认身份", base: "基础画像", intelligent: "综合画像", explicit: "明确表达", inferred: "推断", low: "低敏", medium: "中敏", high: "高敏", source_only: "仅原来源", self_low_global: "本人低敏范围", reconfirmation_pending: "等待重新确认", revoked: "已撤销", superseded: "已替代", expired: "已过期", administrator_temporary_freeze: "管理员暂时冻结", administrator_delete_or_forget: "管理员停止使用", reconfirmation_requested: "要求重新确认"}[value] || value || "未标记";
}

export function portraitPageButtons(page, pages, attribute) {
  return `<nav class="portrait-pages" aria-label="当前结果分页"><button type="button" ${attribute}="previous"${page === 0 ? " disabled" : ""}>上一页</button><span>${page + 1} / ${pages}</span><button type="button" ${attribute}="next"${page + 1 >= pages ? " disabled" : ""}>下一页</button></nav>`;
}

export function renderPortraitProfileList(items) {
  const query = portraitBrowse.query.trim().toLowerCase();
  const filtered = items.filter(item => (!query || String(item.person_id || "").toLowerCase().includes(query)) && (!portraitBrowse.mode || item.capability_summary?.portrait_mode === portraitBrowse.mode));
  const pages = Math.max(1, Math.ceil(filtered.length / 8));
  portraitBrowse.page = Math.max(0, Math.min(portraitBrowse.page, pages - 1));
  const outside = state.selectedPortraitPersonId && !filtered.some(item => item.person_id === state.selectedPortraitPersonId);
  return `<p class="portrait-window-note">当前最多 100 人 · 筛选后 ${filtered.length} 人${outside ? " · 当前详情在筛选外，继续保留" : ""}</p>
    <div class="portrait-profile-list">${filtered.slice(portraitBrowse.page * 8, (portraitBrowse.page + 1) * 8).map(item => {
      const selected = String(item.person_id || "") === state.selectedPortraitPersonId;
      return `<button type="button" class="portrait-person${selected ? " is-selected" : ""}" aria-pressed="${selected}" data-portrait-person="${escapeHtml(item.person_id || "")}">
        <b>${escapeHtml(item.person_id || "未标记")}</b><small>${escapeHtml(portraitValueLabel(item.identity_assurance))} · ${escapeHtml(portraitValueLabel(item.profile_status))}</small>
        <span>事实记录 ${number(item.fact_count || 0)} · 证据 ${number(item.evidence_count || 0)} · ${escapeHtml(portraitModeText(item.capability_summary?.portrait_mode))}</span>
        <small>同步 ${escapeHtml(formatTime(item.last_synced_at || ""))}</small></button>`;
    }).join("") || '<p class="persona-empty">当前筛选没有匹配画像。</p>'}</div>${portraitPageButtons(portraitBrowse.page, pages, "data-portrait-page")}`;
}

export function renderPortraitModeNotice(items) {
  if (!items.length || !items.every(item => item?.capability_summary?.portrait_mode === "disabled")) return "";
  return '<p class="portrait-mode-notice" role="status">当前同步结果显示统一画像能力全部关闭，不影响普通私聊记忆。模式仍由原陪伴设置的“全局智能画像模式”维护；保存后需等待身份同步。</p>';
}

export function portraitFactMarkup(fact, markers) {
  const linked = markers.filter(item => item.dimension === fact.dimension && item.normalized_claim_hash === fact.normalized_claim_hash && (!item.scope || item.scope === fact.source_scope));
  const field = (label, value) => `<div><dt>${label}</dt><dd>${escapeHtml(value || "未标记")}</dd></div>`;
  return `<article class="portrait-fact">
    <b>${escapeHtml(fact.claim_summary || fact.dimension || "未命名结论")}</b>
    <div class="portrait-tags"><span>${escapeHtml(portraitValueLabel(fact.epistemic_status))}</span><span>${escapeHtml(portraitValueLabel(fact.portrait_tier))}</span><span>${escapeHtml(portraitValueLabel(fact.status))}</span>${linked.length ? `<span>有关联治理标记 ${linked.length} 条</span>` : ""}</div>
    <details><summary data-portrait-fact-detail>来源与依据</summary><dl class="portrait-fields">
      ${field("结论编号", fact.id)}${field("维度", fact.dimension)}${field("来源范围", fact.source_scope)}${field("可用范围", portraitValueLabel(fact.usable_scope))}
      ${field("产生方式", fact.producer_kind)}${field("推导方式", fact.derivation_kind)}${field("敏感程度", portraitValueLabel(fact.sensitivity))}${field("置信度", Number(fact.confidence || 0).toFixed(2))}
      ${field("最早证据", formatTime(fact.first_evidence_at))}${field("最近证据", formatTime(fact.last_evidence_at))}${field("结论期限", fact.expires_at ? formatTime(fact.expires_at) : "未设置截止")}${field("修订", `r${fact.revision || 0}`)}
    </dl>${linked.length ? `<p class="portrait-window-note">关联治理标记包含历史。请结合下方标记状态与期限查看；记录仍存在不代表当前可用于对话。</p>` : ""}</details>
    <details class="portrait-maintenance"><summary data-portrait-maintenance>维护这条结论</summary>
      <p>冻结会暂停使用 7 天；停止使用（忘记）添加无截止的抑制标记。同来源同结论的已有标记会按本次操作更新，请先查看标记与期限。原结论与证据保留以便溯源，不会删除聊天记录。</p>
      <div class="portrait-actions"><button type="button" data-portrait-govern="freeze" data-portrait-fact-id="${escapeHtml(fact.id || "")}">冻结 7 天</button><button type="button" class="danger" data-portrait-govern="suppress" data-portrait-fact-id="${escapeHtml(fact.id || "")}">停止使用（忘记）</button></div>
    </details>
  </article>`;
}

export function renderPortraitFacts() {
  const host = $("#portraitGovernance .portrait-fact-list");
  if (!host) return;
  const detail = state.portraitGovernanceDetail;
  const query = portraitBrowse.factQuery.trim().toLowerCase();
  const rows = (detail?.facts || []).filter(item => (!query || [item.claim_summary, item.dimension, item.id, item.source_scope].join(" ").toLowerCase().includes(query)) && (!portraitBrowse.factStatus || item.status === portraitBrowse.factStatus));
  const pages = Math.max(1, Math.ceil(rows.length / 12));
  portraitBrowse.factPage = Math.max(0, Math.min(portraitBrowse.factPage, pages - 1));
  host.innerHTML = rows.slice(portraitBrowse.factPage * 12, (portraitBrowse.factPage + 1) * 12).map(item => portraitFactMarkup(item, detail.suppressions || [])).join("") || '<p class="persona-empty">当前筛选暂无结论记录。</p>';
  $("#portraitGovernance .portrait-fact-count").textContent = `本次返回 ${(detail.facts || []).length} 条 · 筛选后 ${rows.length} 条`;
  $("#portraitGovernance .portrait-fact-pages").innerHTML = portraitPageButtons(portraitBrowse.factPage, pages, "data-portrait-fact-page");
  bindPortraitGovernanceActions(host);
}

export function renderPortraitGovernanceDetail(detail, loading = false) {
  const id = state.selectedPortraitPersonId;
  if (loading) return '<div class="portrait-governance-detail-slot" aria-live="polite"><p>正在读取画像详情...</p></div>';
  if (!detail?.ok) return `<div class="portrait-governance-detail-slot" aria-live="polite"><p>${escapeHtml(detail ? `画像详情暂未读取：${detail.code === "bridge_unavailable" ? "统一画像服务不可用" : detail.code || "未知错误"}` : "选择一个精确画像标识，查看结论来源与维护记录。")}</p>${id ? '<button type="button" data-portrait-refresh>重新读取当前画像</button>' : ""}</div>`;
  const person = detail.person || {};
  const facts = detail.facts || [];
  const markers = detail.suppressions || [];
  const statuses = [...new Set(facts.map(item => item.status).filter(Boolean))];
  return `<section class="portrait-governance-detail" data-portrait-detail-person="${escapeHtml(person.person_id)}">
    <div class="portrait-detail-head"><div><h4>当前画像 · r${escapeHtml(person.portrait_revision || 0)}</h4><p>${escapeHtml(person.person_id)}</p></div><div class="portrait-actions"><button type="button" data-portrait-back>返回画像列表</button><button type="button" data-portrait-refresh>刷新此画像</button></div></div>
    <p class="portrait-window-note">${escapeHtml(portraitValueLabel(person.identity_assurance))} · ${escapeHtml(portraitValueLabel(person.profile_status))} · ${escapeHtml(portraitModeText(person.capability_summary?.portrait_mode))} · 同步 ${escapeHtml(formatTime(person.last_synced_at))}</p>
    <p class="portrait-window-note">原接口最近最多 200 条结论、200 条治理标记。这里只展示摘要和来源信息，不提供原聊天正文；实际使用仍需通过权限、有效期和抑制校验。</p>
    <div class="portrait-filters"><label>查找结论<input type="search" data-portrait-fact-query value="${escapeHtml(portraitBrowse.factQuery)}" placeholder="摘要、维度、来源范围或编号" /></label><label>结论记录状态<select data-portrait-fact-status><option value="">全部状态</option>${statuses.map(value => memoryOption(value, portraitValueLabel(value), portraitBrowse.factStatus)).join("")}</select></label></div>
    <p class="portrait-fact-count" role="status"></p><div class="portrait-fact-list"></div><div class="portrait-fact-pages"></div>
    <details class="portrait-markers"><summary data-portrait-markers>治理标记与期限 · ${markers.length} 条</summary><p class="portrait-window-note">这些是原接口返回的标记，包含历史状态；当前是否生效仍由后端校验。本页沿原接口维护标记，不删除原聊天记录。</p>
      <div class="portrait-marker-list">${markers.map(item => `<article><b>${escapeHtml(portraitValueLabel(item.reason))}</b><p>${escapeHtml(item.dimension || "未标记维度")} · ${escapeHtml(portraitValueLabel(item.status))}</p><p>来源范围：${escapeHtml(item.scope || "全部匹配范围")}</p><p>期限：${escapeHtml(item.expires_at ? formatTime(item.expires_at) : "未设置截止")} · 更新 ${escapeHtml(formatTime(item.updated_at))}</p></article>`).join("") || '<p>暂无治理标记。</p>'}</div>
    </details>
  </section>`;
}

export function bindPortraitDetailControls() {
  const target = $("#portraitGovernance");
  target.querySelectorAll("[data-portrait-refresh]").forEach(button => button.addEventListener("click", () => loadPortraitGovernanceDetail()));
  target.querySelector("[data-portrait-back]")?.addEventListener("click", () => target.querySelector(".portrait-filters").scrollIntoView({block: "start"}));
  const query = target.querySelector("[data-portrait-fact-query]");
  query?.addEventListener("input", () => { portraitBrowse.factQuery = query.value; portraitBrowse.factPage = 0; renderPortraitFacts(); });
  const status = target.querySelector("[data-portrait-fact-status]");
  status?.addEventListener("change", () => { portraitBrowse.factStatus = status.value; portraitBrowse.factPage = 0; renderPortraitFacts(); });
  const pager = target.querySelector(".portrait-fact-pages");
  pager?.addEventListener("click", event => { const button = event.target.closest("[data-portrait-fact-page]"); if (!button) return; portraitBrowse.factPage += button.dataset.portraitFactPage === "next" ? 1 : -1; renderPortraitFacts(); });
  if (target.querySelector(".portrait-fact-list")) renderPortraitFacts();
}

export function renderPortraitDetailPanel() {
  const current = $("#portraitGovernance .portrait-governance-detail, #portraitGovernance .portrait-governance-detail-slot");
  if (!current) return;
  current.outerHTML = renderPortraitGovernanceDetail(state.portraitGovernanceDetail, state.portraitGovernanceLoading);
  bindPortraitDetailControls();
}

export function updatePortraitProfileList() {
  const host = $("#portraitGovernance .portrait-profile-results");
  if (!host) return;
  host.innerHTML = renderPortraitProfileList(state.portraitProfiles);
  host.querySelectorAll("[data-portrait-person]").forEach(button => button.addEventListener("click", () => {
    state.selectedPortraitPersonId = button.dataset.portraitPerson;
    portraitBrowse.factQuery = ""; portraitBrowse.factStatus = ""; portraitBrowse.factPage = 0;
    updatePortraitProfileList(); loadPortraitGovernanceDetail(true);
  }));
  host.querySelectorAll("[data-portrait-page]").forEach(button => button.addEventListener("click", () => { portraitBrowse.page += button.dataset.portraitPage === "next" ? 1 : -1; updatePortraitProfileList(); }));
}

export async function loadPortraitGovernance() {
  const target = $("#portraitGovernance");
  if (!target) return;
  const ticket = ++asteriaWorkspaceState.portraitListRequest;
  target.innerHTML = loadingState("正在读取统一画像状态...");
  try {
    const data = await apiGet("/portrait/profiles?limit=100");
    if (ticket !== asteriaWorkspaceState.portraitListRequest) return;
    if (data.state === "bridge_unavailable") throw new Error("统一画像服务尚未连接；这不表示资料为空。");
    const items = Array.isArray(data.items) ? data.items : [];
    state.portraitProfiles = items;
    if (state.selectedPortraitPersonId && !items.some(item => item.person_id === state.selectedPortraitPersonId)) {
      state.selectedPortraitPersonId = ""; state.portraitGovernanceDetail = null; state.portraitGovernanceLoading = false; asteriaWorkspaceState.portraitDetailRequest++;
    }
    target.innerHTML = `<details class="portrait-workspace" data-portrait-workspace${portraitBrowse.expanded ? " open" : ""}><summary>统一用户画像 · 本次 ${items.length} 人</summary>
      <p class="portrait-window-note">按精确画像标识维护，与左侧普通记忆范围分别查看。画像来自原陪伴身份同步，不通过昵称猜测新建。记忆模块维护结论与证据，陪伴模块保留关系和私聊权限。</p>
      ${renderPortraitModeNotice(items)}${items.length ? "" : '<p class="persona-empty">尚无已同步的统一画像。</p>'}
      <div class="portrait-filters"><label>查找画像<input type="search" data-portrait-query value="${escapeHtml(portraitBrowse.query)}" placeholder="输入精确画像标识或其中一段" /></label><label>同步的画像模式<select data-portrait-mode><option value="">全部模式</option>${["disabled","use_existing","learn_and_use"].map(value => memoryOption(value, portraitModeText(value), portraitBrowse.mode)).join("")}</select></label></div>
      <div class="portrait-profile-results"></div>${renderPortraitGovernanceDetail(state.portraitGovernanceDetail, state.portraitGovernanceLoading)}
    </details>`;
    target.querySelector("[data-portrait-workspace]").addEventListener("toggle", event => { portraitBrowse.expanded = event.currentTarget.open; });
    const query = target.querySelector("[data-portrait-query]");
    query.addEventListener("input", () => { portraitBrowse.query = query.value; portraitBrowse.page = 0; updatePortraitProfileList(); });
    const mode = target.querySelector("[data-portrait-mode]");
    mode.addEventListener("change", () => { portraitBrowse.mode = mode.value; portraitBrowse.page = 0; updatePortraitProfileList(); });
    updatePortraitProfileList(); bindPortraitDetailControls();
  } catch (error) {
    if (ticket !== asteriaWorkspaceState.portraitListRequest) return;
    target.innerHTML = `<div class="empty-state error-state"><b>统一画像服务暂不可用</b><span>${escapeHtml(error?.message || "bridge_unavailable")}</span><button type="button" data-portrait-list-retry>重新读取画像列表</button></div>`;
    target.querySelector("[data-portrait-list-retry]").addEventListener("click", () => loadPortraitGovernance());
  }
}

export async function loadPortraitGovernanceDetail(focus = false) {
  const personId = state.selectedPortraitPersonId;
  if (!personId) return false;
  const ticket = ++asteriaWorkspaceState.portraitDetailRequest;
  const current = () => ticket === asteriaWorkspaceState.portraitDetailRequest && personId === state.selectedPortraitPersonId;
  state.portraitGovernanceDetail = null; state.portraitGovernanceLoading = true;
  renderPortraitDetailPanel();
  try {
    const data = await apiGet(`/portrait/profile?person_id=${encodeURIComponent(personId)}`);
    if (!current()) return false;
    const detail = data.result;
    if (detail?.ok && detail.person?.person_id !== personId) throw new Error("画像归属不匹配，请重新读取");
    state.portraitGovernanceDetail = detail || {ok: false, code: "未返回画像结果"};
  } catch (error) {
    if (!current()) return false;
    state.portraitGovernanceDetail = {ok: false, code: error?.message || "bridge_unavailable"};
  }
  if (!current()) return false;
  state.portraitGovernanceLoading = false; renderPortraitDetailPanel();
  if (focus) $("#portraitGovernance .portrait-governance-detail, #portraitGovernance .portrait-governance-detail-slot")?.scrollIntoView({block: "start"});
  return Boolean(state.portraitGovernanceDetail?.ok);
}

export function bindPortraitGovernanceActions(target) {
  target.querySelectorAll("[data-portrait-govern]").forEach(button => button.addEventListener("click", () => {
    const host = button.closest("[data-portrait-detail-person]");
    const personId = host?.dataset.portraitDetailPerson;
    const action = button.dataset.portraitGovern;
    const factId = button.dataset.portraitFactId;
    const current = () => state.activeView === "relations" && state.selectedPortraitPersonId === personId && state.portraitGovernanceDetail?.person?.person_id === personId;
    if (!current() || !state.portraitGovernanceDetail.facts.some(item => item.id === factId)) return;
    const label = action === "freeze" ? "冻结 7 天" : "停止使用（忘记）";
    showInlineConfirmation({host, title: `${label}这条画像结论`,
      message: action === "freeze" ? "将在原服务中写入 7 天抑制标记，同来源同结论的已有标记按本次操作更新。原结论与证据仍保留；到期后能否使用仍由权限与其他规则决定。" : "将写入无截止的停止使用标记，同来源同结论的已有标记按本次操作更新。阻止该结论继续被使用或旧证据重新写回，原结论与聊天记录不会被删除。",
      confirmLabel: `确认${label}`, busyText: "正在更新画像维护标记...", dangerous: action === "suppress",
      onCancel: () => renderPortraitDetailPanel(),
      onConfirm: async () => {
        if (!current()) return;
        let result;
        try {
          result = await apiPost("/portrait/govern", {person_id: personId, fact_id: factId, action, operation_id: `portrait.page:${Date.now()}:${factId.slice(-12)}`, expires_at: action === "freeze" ? new Date(Date.now() + 7 * 86400000).toISOString() : ""});
        } catch (error) {
          if (current()) { state.portraitGovernanceDetail = {ok: false, code: `操作结果未确认，请先重新读取。${error?.message || "请求失败"}`}; renderPortraitDetailPanel(); }
          showToast("画像操作结果未确认，请先读取核对，不要重复提交。", "error"); return;
        }
        if (!result?.result?.ok) {
          if (current()) renderPortraitDetailPanel();
          showToast(result?.result?.code === "portrait_fact_not_found" ? "该画像结论已不存在，请刷新后再维护。" : result?.result?.code || "操作未完成", "error"); return;
        }
        const done = action === "freeze" ? "已冻结该画像结论 7 天" : "已停止使用该画像结论，原记录保留";
        showToast(done);
        if (!current()) return;
        const loaded = await loadPortraitGovernanceDetail();
        if (!loaded && state.selectedPortraitPersonId === personId) showToast(`${done}，但详情暂未读取，请手动刷新。`, "error");
      },
    });
  }));
}

export async function loadPersonalMemory() {
  const target = $("#personalMemoryList");
  if (!target) return;
  removeRailMountedScheduleFilm();
  const shouldAnimateEntrance = state.personalEntranceRevealRequested;
  state.personalEntranceRevealRequested = false;
  if (state.companionPersonalAvailable === null && state.companionPersonalError) {
    updatePersonalMemoryAvailability(null, state.companionPersonalError);
    target.innerHTML = renderPersonalMemoryDetectionError(state.companionPersonalError);
    bindCompanionDetectionRetry(target);
    return;
  }
  if (state.companionPersonalAvailable === false) {
    updatePersonalMemoryAvailability(false);
    target.innerHTML = renderPersonalMemoryUnavailable("未检测到已加载的主动陪伴插件");
    return;
  }
  target.innerHTML = loadingState("正在读取个人记忆...");
  const data = await fetchPersonalMemoryData();
  updatePersonalMemoryAvailability(Boolean(data.available));
  if (!data.available) {
    target.innerHTML = renderPersonalMemoryUnavailable(data.reason || "未检测到已加载的主动陪伴插件");
    return;
  }
  state.selectedPersonalDate = data.selected_date || state.selectedPersonalDate || "";
  state.personalSnapshot = data.snapshot || {};
  state.personalData = data;
  if (shouldAnimateEntrance) state.animatePersonalDateRail = true;
  renderPersonalDateRail(data.dates || [], state.selectedPersonalDate);
  target.innerHTML = renderPersonalMemoryWorkspace(data.snapshot || {}, data);
  bindPersonalMemoryWorkspace(target, data.snapshot || {}, data);
  hydratePersonalAlbumImages(target);
}

export function personalMemoryQueryParams() {
  const query = $("#globalSearch")?.value.trim() || "";
  const params = new URLSearchParams({ limit: "80" });
  if (query) params.set("q", query);
  if (state.selectedPersonalDate) params.set("date", state.selectedPersonalDate);
  return params;
}

export async function fetchPersonalMemoryData() {
  return apiGet(`/companion/personal-memory?${personalMemoryQueryParams().toString()}`);
}

export function bindPersonalMemoryWorkspace(target, snapshot, data) {
  target.querySelectorAll("[data-personal-viewport]").forEach((button) => {
    button.addEventListener("click", async () => {
      const next = button.dataset.personalViewport || "schedule";
      if (next === state.personalViewport) return;
      await switchPersonalViewport(next, target, state.personalSnapshot || snapshot, state.personalData || data);
    });
  });

  target.querySelectorAll("[data-memory-id]").forEach((row) => {
    row.addEventListener("click", () => showMemory(row.dataset.memoryId));
  });
  bindPersonalAlbumCards(target, snapshot, data);
  target.querySelectorAll("[data-subjective-index]").forEach((card) => {
    const selectSubjective = () => {
      state.selectedSubjectiveMemoryIndex = card.dataset.subjectiveIndex || "";
      target.querySelectorAll("[data-subjective-index]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.subjectiveIndex === state.selectedSubjectiveMemoryIndex);
      });
      showPersonalSubjectiveDetail(snapshot, data, { animate: true });
    };
    card.addEventListener("click", selectSubjective);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectSubjective();
      }
    });
  });
  if (state.personalViewport !== "schedule") {
    removeRailMountedScheduleFilm();
    state.pendingPersonalFilmReveal = false;
    resetPersonalFilmLayout();
    if (state.personalViewport === "album") {
      showPersonalAlbumDetail(snapshot, data);
      hydratePersonalAlbumImages(target);
    }
    if (state.personalViewport === "subjective") showPersonalSubjectiveDetail(snapshot, data);
    if (state.personalViewport === "actions") showPersonalActionsDetail(data);
    return;
  }
  const film = target.querySelector("[data-schedule-film]");
  const selectSchedule = (index, options = {}) => {
    state.selectedScheduleIndex = index || "";
    target.querySelectorAll(".schedule-frame").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.scheduleIndex === state.selectedScheduleIndex);
    });
    updateScheduleSummary(target, snapshot, { animate: true });
    showPersonalScheduleDetail(snapshot, data, { animate: true });
    if (!options.preserveOffset) centerScheduleFrame(film, state.selectedScheduleIndex);
  };
  target.querySelectorAll("[data-schedule-index]").forEach((row) => {
    row.addEventListener("click", () => {
      if (row.closest("[data-schedule-film]")?.dataset.draggingClick === "1") return;
      selectSchedule(row.dataset.scheduleIndex);
    });
  });
  setupScheduleFilmDrag(film, selectSchedule);
  mountScheduleFilmToRail(film);
  const shouldRevealAfterReel = state.pendingPersonalFilmReveal;
  state.pendingPersonalFilmReveal = false;
  if (shouldRevealAfterReel) {
    prepareScheduleFilmPeek(film);
    revealScheduleFilmAfterReel(film);
  } else {
    requestAnimationFrame(() => applyScheduleFilmOffset(film, 0, true));
    requestAnimationFrame(alignPersonalScheduleToReel);
  }
  updateScheduleSummary(target, snapshot);
  showPersonalScheduleDetail(snapshot, data);
}

export function bindPersonalAlbumCards(target, snapshot, data) {
  target.querySelectorAll("[data-album-index]").forEach((card) => {
    const selectAlbum = () => {
      state.selectedPersonalAlbumIndex = card.dataset.albumIndex || "";
      target.querySelectorAll("[data-album-index]").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.albumIndex === state.selectedPersonalAlbumIndex);
      });
      showPersonalAlbumDetail(snapshot, data, { animate: true });
    };
    card.addEventListener("click", selectAlbum);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectAlbum();
      }
    });
  });
}

export async function switchPersonalAlbumDate() {
  const target = $("#personalMemoryList");
  const viewport = target?.querySelector(".personal-viewport[data-personal-viewport-panel='album']");
  if (!target || !viewport) {
    await loadPersonalMemory();
    return;
  }
  const currentPanel = viewport.querySelector(".companion-album");
  if (currentPanel && !prefersReducedMotion()) {
    currentPanel.classList.add("is-album-date-leaving");
    await waitForMotion(180);
  }
  const data = await fetchPersonalMemoryData();
  updatePersonalMemoryAvailability(Boolean(data.available));
  if (!data.available) {
    target.innerHTML = renderPersonalMemoryUnavailable(data.reason || "未检测到已加载的主动陪伴插件");
    return;
  }
  state.selectedPersonalDate = data.selected_date || state.selectedPersonalDate || "";
  state.selectedPersonalAlbumIndex = "";
  state.personalSnapshot = data.snapshot || {};
  state.personalData = data;
  state.animatePersonalDateRail = true;
  renderPersonalDateRail(data.dates || [], state.selectedPersonalDate);
  viewport.innerHTML = renderPersonalViewportPanel("album", data.snapshot || {}, data);
  const nextPanel = viewport.querySelector(".companion-album");
  nextPanel?.classList.add("is-album-date-entering");
  bindPersonalAlbumCards(target, data.snapshot || {}, data);
  showPersonalAlbumDetail(data.snapshot || {}, data, { animate: true });
  hydratePersonalAlbumImages(viewport);
  requestAnimationFrame(() => nextPanel?.classList.remove("is-album-date-entering"));
}

export async function switchPersonalViewport(next, target, snapshot, data) {
  if (state.personalViewportSwitching) return;
  state.personalViewportSwitching = true;
  const rail = document.querySelector(".object-rail");
  const render = () => {
    try {
      state.animatePersonalViewportRail = true;
      renderPersonalDateRail(state.personalDates, state.selectedPersonalDate);
    } finally {
      state.animatePersonalViewportRail = false;
    }
    target.innerHTML = renderPersonalMemoryWorkspace(snapshot, data);
    bindPersonalMemoryWorkspace(target, snapshot, data);
  };
  try {
    await retractScheduleFilmBeforeDateMove();
    removeRailMountedScheduleFilm();
    if (!prefersReducedMotion()) {
      rail?.classList.add("is-reel-rolling-out");
      await waitForMotion(220);
      rail?.classList.remove("is-reel-rolling-out");
    }
    state.personalViewport = next;
    state.pendingPersonalFilmReveal = next === "schedule" && !prefersReducedMotion();
    resetPersonalFilmLayout();
    render();
    if (!prefersReducedMotion()) {
      rail?.classList.add("is-reel-rolling-in");
      await waitForMotion(540);
      rail?.classList.remove("is-reel-rolling-in");
    }
    if (next === "schedule") requestAnimationFrame(alignPersonalScheduleToReel);
  } finally {
    rail?.classList.remove("is-reel-rolling-out", "is-reel-rolling-in");
    state.personalViewportSwitching = false;
  }
}

export function resetPersonalFilmLayout() {
  const app = $("#app");
  if (!app) return;
  app.style.removeProperty("--personal-film-lift");
  app.style.removeProperty("--personal-film-shift");
  app.style.removeProperty("--personal-detail-offset");
  app.style.removeProperty("--personal-main-height");
}

export function mountScheduleFilmToRail(film) {
  const rail = document.querySelector(".object-rail");
  if (state.overviewLayout !== "cinema" || !film || !rail || film.classList.contains("is-rail-mounted")) return;
  film.classList.add("is-rail-mounted");
  rail.appendChild(film);
}

export function restoreScheduleFilmToPanel(film = document.querySelector("[data-schedule-film]")) {
  const zone = document.querySelector(".personal-zone.companion-overview");
  if (!film || !zone) return;
  if (film.parentElement !== zone) zone.appendChild(film);
  film.classList.remove("is-rail-mounted", "is-peeking", "is-retracting", "is-extended", "is-dragging");
  film.style.removeProperty("width");
  film.style.removeProperty("min-width");
  film.style.removeProperty("transition");
  film.style.removeProperty("--personal-film-top");
  film.style.removeProperty("--personal-film-left");
  film.style.removeProperty("--schedule-film-pull");
  const track = film.querySelector("[data-schedule-track]");
  track?.style.removeProperty("transform");
  track?.style.removeProperty("transition");
  resetPersonalFilmLayout();
}

export function syncPersonalLayoutForUiMode() {
  const film = document.querySelector("[data-schedule-film]");
  if (!film || state.activeView !== "review") return;
  const heading = document.querySelector(".personal-zone.companion-overview .personal-zone-head h4");
  if (heading) heading.textContent = state.overviewLayout === "cinema" ? "时间胶片" : "日程时间表";
  if (state.personalSnapshot) {
    updateScheduleSummary(document, state.personalSnapshot);
  }
  if (state.overviewLayout === "standard") {
    restoreScheduleFilmToPanel(film);
    return;
  }
  mountScheduleFilmToRail(film);
  requestAnimationFrame(() => {
    centerScheduleFrame(film, state.selectedScheduleIndex, true);
    alignPersonalScheduleToReel();
  });
}

export function removeRailMountedScheduleFilm() {
  document.querySelector(".schedule-film.is-rail-mounted")?.remove();
}

export function prepareScheduleFilmPeek(film) {
  if (!film) return;
  film.classList.add("is-peeking");
  film.style.transition = "none";
  film.style.minWidth = "0px";
  film.style.width = "0px";
  film.offsetHeight;
  film.style.transition = "";
}

export function retractScheduleFilmBeforeDateMove() {
  const film = document.querySelector(".schedule-film.is-rail-mounted");
  if (!film || film.classList.contains("is-peeking")) return Promise.resolve();
  const currentWidth = Math.round(film.getBoundingClientRect().width);
  if (currentWidth <= 2) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.clearTimeout(film._retractTimer);
      film.removeEventListener("transitionend", onEnd);
      film.style.transition = "";
      resolve();
    };
    const onEnd = (event) => {
      if (event.target !== film || event.propertyName !== "width") return;
      finish();
    };
    window.clearTimeout(film._retractTimer);
    film.classList.add("is-peeking", "is-retracting");
    film.style.minWidth = "0px";
    film.style.width = `${currentWidth}px`;
    film.style.transition = "width .38s cubic-bezier(.34,.02,.18,1)";
    film.offsetHeight;
    film.addEventListener("transitionend", onEnd);
    requestAnimationFrame(() => {
      film.style.width = "0px";
    });
    film._retractTimer = window.setTimeout(finish, 460);
  });
}

export function revealScheduleFilmAfterReel(film) {
  if (!film) return;
  const list = $("#bucketList");
  let done = false;
  const reveal = () => {
    if (done) return;
    done = true;
    window.clearTimeout(film?._revealTimer);
    list?.removeEventListener("transitionend", onMotionEnd);
    list?.removeEventListener("animationend", onMotionEnd);
    alignPersonalScheduleToReel();
    requestAnimationFrame(() => revealScheduleFilmPeek(film));
  };
  const onMotionEnd = (event) => {
    if (event.target !== list) return;
    if (event.type === "transitionend" && event.propertyName !== "transform") return;
    reveal();
  };
  requestAnimationFrame(() => {
    list?.addEventListener("transitionend", onMotionEnd);
    list?.addEventListener("animationend", onMotionEnd);
    film._revealTimer = window.setTimeout(reveal, 820);
  });
}

export function revealScheduleFilmPeek(film) {
  if (!film) return;
  applyScheduleFilmOffset(film, 0, false);
  window.clearTimeout(film._peekTimer);
  film._peekTimer = window.setTimeout(() => {
    film.classList.remove("is-peeking");
    film.style.minWidth = "";
  }, 760);
}

export function alignPersonalScheduleToReel() {
  const app = $("#app");
  const film = document.querySelector("[data-schedule-film]");
  const reel = document.querySelector(".bucket.date-reel.is-active");
  if (!app || !film || !reel || state.activeView !== "review" || state.overviewLayout !== "cinema") {
    app?.style.removeProperty("--personal-film-lift");
    app?.style.removeProperty("--personal-film-shift");
    app?.style.removeProperty("--personal-detail-offset");
    app?.style.removeProperty("--personal-main-height");
    return;
  }
  const styles = getComputedStyle(app);
  const currentLift = parseFloat(styles.getPropertyValue("--personal-film-lift")) || 0;
  const currentShift = parseFloat(styles.getPropertyValue("--personal-film-shift")) || 0;
  const filmRect = film.getBoundingClientRect();
  const reelRect = reel.getBoundingClientRect();
  if (film.classList.contains("is-rail-mounted")) {
    const rail = document.querySelector(".object-rail");
    const railRect = rail?.getBoundingClientRect();
    if (!railRect) return;
    app.style.removeProperty("--personal-film-lift");
    app.style.removeProperty("--personal-film-shift");
    if (getComputedStyle(film).position !== "absolute") {
      alignPersonalPanelsAroundFilm(film.getBoundingClientRect().top, film.getBoundingClientRect().bottom);
      return;
    }
    const top = reelRect.top + reelRect.height / 2 - filmRect.height / 2 - railRect.top;
    const left = reelRect.left + 48 - railRect.left;
    film.style.setProperty("--personal-film-top", `${Math.round(top)}px`);
    film.style.setProperty("--personal-film-left", `${Math.round(left)}px`);
    alignPersonalPanelsAroundFilm(railRect.top + top, railRect.top + top + filmRect.height);
    return;
  }
  const unshiftedTop = filmRect.top - currentLift;
  const unshiftedLeft = filmRect.left - currentShift;
  const targetTop = reelRect.top + reelRect.height / 2 - filmRect.height / 2;
  const targetLeft = reelRect.left + 48;
  const lift = Math.round(targetTop - unshiftedTop);
  const shift = Math.round(targetLeft - unshiftedLeft);
  app.style.setProperty("--personal-film-lift", `${lift}px`);
  app.style.setProperty("--personal-film-shift", `${shift}px`);
  const filmTop = reelRect.top + reelRect.height / 2 - filmRect.height / 2;
  alignPersonalPanelsAroundFilm(filmTop, filmTop + filmRect.height);
}

export function alignPersonalPanelsAroundFilm(filmTop, filmBottom) {
  alignPersonalSummaryAboveFilm(filmTop);
  document.querySelector(".workspace-main")?.offsetHeight;
  alignPersonalDetailBelowFilm(filmBottom);
}

export function alignPersonalSummaryAboveFilm(filmTop) {
  const app = $("#app");
  const main = document.querySelector(".workspace-main");
  if (!app || !main || state.activeView !== "review") return;
  if (window.matchMedia("(max-width: 1080px)").matches) {
    app.style.removeProperty("--personal-main-height");
    return;
  }
  const mainRect = main.getBoundingClientRect();
  const height = Math.max(154, Math.round(filmTop - mainRect.top));
  app.style.setProperty("--personal-main-height", `${height}px`);
}

export function alignPersonalDetailBelowFilm(filmBottom) {
  const app = $("#app");
  const detail = $("#detailDrawer");
  if (!app || !detail || state.activeView !== "review") return;
  if (app.style.getPropertyValue("--personal-detail-offset")) return;
  const currentOffset = parseFloat(getComputedStyle(app).getPropertyValue("--personal-detail-offset")) || 0;
  const detailRect = detail.getBoundingClientRect();
  const unshiftedTop = detailRect.top - currentOffset;
  const targetTop = Math.round(filmBottom + 16);
  const offset = Math.round(targetTop - unshiftedTop);
  const next = window.matchMedia("(max-width: 1080px)").matches ? Math.max(0, offset) : offset;
  app.style.setProperty("--personal-detail-offset", `${next}px`);
}

export function setupScheduleFilmDrag(film, selectSchedule) {
  if (!film) return;
  const track = film.querySelector("[data-schedule-track]");
  if (!track) return;
  let isDown = false;
  let startX = 0;
  let startY = 0;
  let startOffset = 0;
  let moved = 0;
  let dragAxis = "";
  let lastSelected = "";
  const selectNearestAtMarker = () => {
    const nearest = nearestScheduleFrame(film);
    if (!nearest || nearest.dataset.scheduleIndex === lastSelected) return;
    lastSelected = nearest.dataset.scheduleIndex;
    selectSchedule(lastSelected, { preserveOffset: true });
  };
  if (state.overviewLayout === "cinema") {
    applyScheduleFilmOffset(film, Number(film.dataset.offset || 0), true);
    selectNearestAtMarker();
  }
  film.addEventListener("pointerdown", (event) => {
    if (state.overviewLayout !== "cinema") return;
    if (event.button !== undefined && event.button !== 0) return;
    isDown = true;
    moved = 0;
    dragAxis = "";
    startX = event.clientX;
    startY = event.clientY;
    startOffset = Number(film.dataset.offset || 0);
  });
  film.addEventListener("pointermove", (event) => {
    if (!isDown) return;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    if (!dragAxis) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 6) return;
      dragAxis = Math.abs(dx) > Math.abs(dy) ? "horizontal" : "vertical";
      if (dragAxis === "vertical") return;
      film.classList.add("is-dragging");
      film.setPointerCapture?.(event.pointerId);
    }
    if (dragAxis !== "horizontal") return;
    event.preventDefault();
    moved = Math.max(moved, Math.abs(dx));
    applyScheduleFilmOffset(film, startOffset + dx);
    selectNearestAtMarker();
  });
  const finish = (event) => {
    if (!isDown) return;
    isDown = false;
    const nearest = dragAxis === "horizontal" && moved > 8 ? nearestScheduleFrame(film) : null;
    film.classList.remove("is-dragging");
    if (film.hasPointerCapture?.(event.pointerId)) film.releasePointerCapture(event.pointerId);
    if (dragAxis === "horizontal" && moved > 8) {
      film.dataset.draggingClick = "1";
      if (nearest) selectSchedule(nearest.dataset.scheduleIndex, { preserveOffset: true });
      window.setTimeout(() => {
        delete film.dataset.draggingClick;
      }, 80);
    }
  };
  film.addEventListener("pointerup", finish);
  film.addEventListener("pointercancel", finish);
  film.addEventListener("mouseleave", (event) => {
    if (isDown) finish(event);
  });
  film.addEventListener("wheel", (event) => {
    if (state.overviewLayout !== "cinema") return;
    event.preventDefault();
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    applyScheduleFilmOffset(film, Number(film.dataset.offset || 0) + delta);
    selectNearestAtMarker();
    window.clearTimeout(film._snapTimer);
    film._snapTimer = window.setTimeout(() => {
      const nearest = nearestScheduleFrame(film);
      if (nearest) selectSchedule(nearest.dataset.scheduleIndex, { preserveOffset: true });
    }, 160);
  }, { passive: false });
  window.addEventListener("resize", () => {
    if (state.overviewLayout !== "cinema") return;
    applyScheduleFilmOffset(film, Number(film.dataset.offset || 0), true);
    alignPersonalScheduleToReel();
  });
}

export function nearestScheduleFrame(film) {
  const frames = Array.from(film.querySelectorAll(".schedule-frame"));
  if (!frames.length) return null;
  const filmRect = film.getBoundingClientRect();
  const focus = filmRect.left + scheduleFilmMarkerX(film);
  return frames.reduce((nearest, frame) => {
    const rect = frame.getBoundingClientRect();
    const distance = Math.abs(rect.right - focus);
    if (!nearest || distance < nearest.distance) return { frame, distance };
    return nearest;
  }, null)?.frame || frames[0];
}

export function scheduleFilmMaxOffset(film) {
  const frames = Array.from(film?.querySelectorAll(".schedule-frame") || []);
  if (!film || !frames.length) return 0;
  const latest = frames[0];
  const earliest = frames[frames.length - 1];
  const frameWidth = latest.offsetWidth || 260;
  const latestAlignOffset = earliest.offsetLeft - latest.offsetLeft;
  const max = latestAlignOffset + frameWidth;
  return Math.max(0, max);
}

export function applyScheduleFilmOffset(film, offset, immediate = false) {
  const track = film?.querySelector("[data-schedule-track]");
  if (!film || !track) return;
  const next = Math.max(0, Math.min(scheduleFilmMaxOffset(film), Number(offset) || 0));
  const base = scheduleFilmBaseWidth(film);
  const visibleWidth = base + next;
  const frames = Array.from(film.querySelectorAll(".schedule-frame"));
  const frameWidth = frames[0]?.offsetWidth || 260;
  const earliest = frames[frames.length - 1];
  const earliestEdge = earliest ? earliest.offsetLeft + frameWidth : track.scrollWidth;
  const trackShift = scheduleFilmMarkerX(film) - earliestEdge + next;
  film.dataset.offset = String(next);
  film.dataset.dragOffset = String(next);
  film.style.setProperty("--schedule-film-pull", `${next}px`);
  film.style.setProperty("--schedule-film-drag", "0px");
  film.style.transition = immediate ? "none" : "";
  film.style.width = `${visibleWidth}px`;
  film.classList.toggle("is-extended", next > 8);
  track.style.transition = immediate ? "none" : "";
  track.style.transform = `translate3d(${trackShift}px,0,0)`;
  if (immediate) {
    track.offsetHeight;
    film.style.transition = "";
    track.style.transition = "";
  }
}

export function scheduleFilmBaseWidth(film) {
  const raw = getComputedStyle(film).getPropertyValue("--schedule-film-base");
  return parseFloat(raw) || 150;
}

export function scheduleFilmMarkerX(film) {
  const raw = getComputedStyle(film).getPropertyValue("--schedule-marker-x");
  return parseFloat(raw) || scheduleFilmBaseWidth(film) / 2;
}

export function centerScheduleFrame(film, index, immediate = false) {
  if (!film || !index) return;
  const frame = Array.from(film.querySelectorAll("[data-schedule-index]"))
    .find((item) => item.dataset.scheduleIndex === String(index));
  if (!frame) return;
  const frames = Array.from(film.querySelectorAll(".schedule-frame"));
  const earliest = frames[frames.length - 1];
  const target = earliest ? earliest.offsetLeft - frame.offsetLeft : 0;
  applyScheduleFilmOffset(film, target, immediate);
}

export async function loadCompanionAvailability() {
  try {
    const data = await apiGet("/companion/personal-memory?limit=0");
    updatePersonalMemoryAvailability(Boolean(data.available), "");
  } catch (error) {
    updatePersonalMemoryAvailability(null, error?.message || "陪伴插件状态读取失败");
    if (state.activeView === "review") {
      showToast(error?.message || "陪伴插件状态读取失败", "error");
    }
  }
}

export function updatePersonalMemoryAvailability(available, error = "") {
  state.companionPersonalAvailable = available;
  state.companionPersonalError = error || "";
  const view = available === null && error
    ? PERSONAL_MEMORY_VIEW.error
    : available
      ? PERSONAL_MEMORY_VIEW.available
      : PERSONAL_MEMORY_VIEW.unavailable;
  VIEWS.review.title = view.title;
  VIEWS.review.hint = view.hint;
  const strip = document.querySelector('[data-view="review"]');
  if (strip) {
    strip.dataset.tipTitle = view.title;
    strip.dataset.tipSub = view.hint;
    const label = strip.querySelector(".strip-label b");
    const small = strip.querySelector(".strip-label small");
    if (label) label.textContent = view.title;
    if (small) small.textContent = view.small;
  }
  const head = $("#view-review .section-head");
  if (head) {
    const title = head.querySelector("h3");
    const hint = head.querySelector("p");
    if (title) title.textContent = view.title;
    if (hint) hint.textContent = view.hint;
  }
  if (state.activeView === "review") {
    $("#workspaceTitle").textContent = view.title;
    $("#workspaceHint").textContent = view.hint;
  }
}

export function renderPersonalMemoryDetectionError(error) {
  return `
    <div class="empty-state error-state">
      <b>个人记忆检测失败</b>
      <span>${escapeHtml(error || "陪伴插件状态读取失败")}</span>
      <button data-retry-companion-detection type="button">重新检测</button>
    </div>
  `;
}

export function bindCompanionDetectionRetry(root) {
  root.querySelector("[data-retry-companion-detection]")?.addEventListener("click", () => {
    withBusy("正在重新检测陪伴插件...", async () => {
      await loadCompanionAvailability();
      await loadPersonalMemory();
    });
  });
}

export function renderPersonalMemoryUnavailable(reason) {
  return `
    <div class="empty-state unavailable-state">
      <b>个人记忆不可用</b>
      <span>${escapeHtml(reason)}</span>
      <p>这里用于联动主动陪伴插件，展示 Bot 自身的每日生活日程、相册、主观记忆、日程细化片段和由陪伴插件写入的个人记忆。</p>
    </div>
  `;
}

export function renderPersonalMemoryWorkspace(snapshot, status) {
  const active = personalViewport();
  const bridgeWarning = status?.bridge_available === false
    ? `<div class="chat-import-callout is-warning" role="status"><b>联动已降级</b><span>当前展示包含陪伴插件本地数据，但记忆桥接并未健康连通（${escapeHtml(status.bridge_reason || status.bridge_state || "状态未知")}）。新数据可能尚未同步到记忆库。</span></div>`
    : "";
  return `
    <section class="personal-memory-workspace">
      ${bridgeWarning}
      ${renderPersonalViewportSwitch(active)}
      <div class="personal-viewport" data-personal-viewport-panel="${escapeHtml(active)}">
        ${renderPersonalViewportPanel(active, snapshot, status)}
      </div>
    </section>
  `;
}

export function personalViewport() {
  const views = ["schedule", "album", "subjective", "actions"];
  if (!views.includes(state.personalViewport)) state.personalViewport = "schedule";
  return state.personalViewport;
}

export function renderPersonalViewportSwitch(active) {
  const tabs = [
    { id: "schedule", label: "日程" },
    { id: "album", label: "相册" },
    { id: "subjective", label: "主观记忆" },
    { id: "actions", label: "行动" },
  ];
  return `
    <div class="personal-view-switch" role="tablist" aria-label="个人记忆视窗">
      ${tabs.map((tab) => `
        <button class="personal-view-tab${tab.id === active ? " is-active" : ""}" type="button" role="tab" aria-selected="${tab.id === active ? "true" : "false"}" data-personal-viewport="${escapeHtml(tab.id)}">
          ${escapeHtml(tab.label)}
        </button>
      `).join("")}
    </div>
  `;
}

export function renderPersonalViewportPanel(active, snapshot, status) {
  if (active === "album") return renderCompanionAlbumPanel(snapshot, status);
  if (active === "subjective") return renderSubjectiveMemoryPanel(snapshot, status);
  if (active === "actions") return renderPersonalActionsPanel(status);
  return renderCompanionSchedulePanel(snapshot, status);
}

export function renderPersonalActionsPanel(status) {
  const actions = Array.isArray(status.actions) ? status.actions : [];
  const date = status.selected_date || "";
  return `
    <section class="personal-zone personal-actions-panel">
      <div class="personal-zone-head">
        <h4>行动</h4>
        <span>${escapeHtml(date || "全部日期")} · ${escapeHtml(actions.length)} 条</span>
      </div>
      ${actions.length ? `
        <div class="personal-action-list">
          ${actions.map((item) => renderPersonalActionCard(item)).join("")}
        </div>
      ` : `
        <div class="album-empty">
          <b>这一天还没有行动记忆</b>
          <span>发说说、搜索、创作、生图、阅读和主动消息等 Bot 行动会出现在这里。</span>
        </div>
      `}
    </section>
  `;
}

export function renderPersonalActionCard(memory) {
  const metadata = memory.metadata || {};
  const tags = Array.isArray(memory.tags) ? memory.tags.filter(Boolean).slice(0, 5) : [];
  const metaParts = [
    metadata.action_label || personalActionTypeLabel(memory.memory_type),
    formatTime(memory.occurred_at || memory.created_at),
    metadata.tid ? `tid ${metadata.tid}` : "",
    Number(metadata.image_count || 0) > 0 ? `${metadata.image_count} 张图` : "",
  ].filter(Boolean);
  return `
    <article class="row-item memory-frame personal-action-card" data-memory-id="${escapeHtml(memory.id)}">
      <div class="memory-frame-time">
        <b>${escapeHtml(metaParts[0] || "行动")}</b>
        <span>${escapeHtml(metaParts.slice(1).join(" · ") || shortId(memory.id))}</span>
      </div>
      <div class="memory-frame-main">
        <div class="memory-frame-text">
          <span class="item-title">${escapeHtml(compact(memory.content, "(空内容)"))}</span>
          ${metadata.text && metadata.text !== memory.content ? `<p class="memory-preview">${escapeHtml(metadata.text)}</p>` : ""}
        </div>
        <div class="badges">
          <span class="badge teal">${escapeHtml(memory.memory_type || "action")}</span>
          <span class="badge blue">${escapeHtml(memory.reality_level || "bot_action")}</span>
          ${tags.map((tag) => `<span class="badge gold">${escapeHtml(tag)}</span>`).join("")}
        </div>
      </div>
    </article>
  `;
}

export function personalActionTypeLabel(type) {
  const labels = {
    self_action: "自我行动",
    proactive_message: "主动消息",
    search_action: "搜索",
    creative_work: "创作",
    image_action: "生图",
    qzone_action: "QQ 空间",
    reading_memory: "阅读",
    persona_life: "生活片段",
  };
  return labels[type] || type || "行动";
}

export function renderCompanionAlbumPanel(snapshot, status) {
  const album = Array.isArray(snapshot.album) ? snapshot.album : [];
  const selected = activeAlbumIndex(album);
  const kindLabels = album.map((item) => item.kind || "");
  const hasOutfit = kindLabels.some((k) => k === "daily_outfit");
  const hasLife = kindLabels.some((k) => k === "life_photo");
  const subtitleParts = [status.selected_date || snapshot.plan?.date || "-"];
  if (hasOutfit) subtitleParts.push("穿搭");
  if (hasLife) subtitleParts.push("生活分享");
  if (!hasOutfit && !hasLife) subtitleParts.push("照片");
  return `
    <section class="personal-zone companion-album">
      <div class="personal-zone-head">
        <h4>相册</h4>
        <span>${escapeHtml(subtitleParts.join(" · "))}</span>
      </div>
      ${album.length ? `
        <div class="album-strip">
          ${album.map((item, index) => renderAlbumCard(item, index, String(index) === selected)).join("")}
        </div>
      ` : `
        <div class="album-empty">
          <b>这一天还没有照片</b>
          <span>生成穿搭图或生活分享图后会出现在这里。</span>
        </div>
      `}
    </section>
  `;
}
