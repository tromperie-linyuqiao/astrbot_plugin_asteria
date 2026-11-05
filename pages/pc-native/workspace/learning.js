/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {fetchJson,postJson} from './client.js';
import {normalizeDailyStateForDisplay,renderDiaryCards,renderDreamCard,renderDreamFragments,renderLifeHero,renderPersonalGoals,renderSkillGrowth,renderStatePillBoard} from './library.js';
import {renderDailyTimeline,renderInteractionImpact,renderMemoryComposition,renderSlangCloud,slangTermText} from './life.js';
import {switchTab} from './navigation.js';
import {copyTextToClipboard,detailBlock,renderDl,requireSecondClick,runAction,setActionBusy,showToast} from './persona.js';
import {groupMessageActivityView,miniStat,relationshipGraphView,scoreGauge,shortName} from './providers.js';
import {livingMemoryStatusText} from './relationships.js';
import {featureLockedByProactiveOnlyMode,featureTemporarilyUnlockedByProactiveOnly,formatProactiveLimit,proactiveGaugeMax,toBool} from './schema.js';
import {formatCompactNumber} from './setup.js';
import {$,EXPRESSION_LIBRARY_PAGE_SIZES,expressionScopeDefinitions,state,tokenTaskLabels} from './state.js';
import {groupTopicThreadsView} from './usage.js';
import {applyOverviewData,cleanInterjectionText,escapeHtml} from './workspace.js';

export function renderTokenMemoryPluginTaskTable(rows, available) {
  const box = $("#tokenMemoryPluginTaskTable");
  if (!box) return;
  if (!available) {
    box.innerHTML = `<div class="empty small">记忆插件 Token 统计未接入</div>`;
    return;
  }
  box.innerHTML = tokenTable(
    ["记忆任务", "总 Token", "输入", "输出", "调用", "失败"],
    rows,
    (item) => [
      tokenTaskLabel(item.key),
      formatNumber(item.total_tokens),
      formatNumber(item.prompt_tokens),
      formatNumber(item.completion_tokens),
      formatNumber(item.calls),
      formatNumber(item.errors),
    ],
    "暂无记忆插件任务明细"
  );
}

export function renderTokenMemoryPluginProviderTable(rows, available) {
  const box = $("#tokenMemoryPluginProviderTable");
  if (!box) return;
  if (!available) {
    box.innerHTML = `<div class="empty small">记忆插件 Token 统计未接入</div>`;
    return;
  }
  box.innerHTML = tokenTable(
    ["Provider", "总 Token", "缓存", "调用", "估算", "平均延迟"],
    rows,
    (item) => [
      item.key || "default",
      formatNumber(item.total_tokens),
      tokenCacheText(item),
      formatNumber(item.calls),
      `${Math.round(Number(item.estimated_ratio || 0) * 100)}%`,
      `${formatNumber(Math.round(Number(item.avg_latency_ms || 0)))} ms`,
    ],
    "暂无记忆插件 Provider 明细"
  );
}

export function renderTokenMemoryPluginRecentTable(rows, available) {
  const box = $("#tokenMemoryPluginRecentTable");
  if (!box) return;
  if (!available) {
    box.innerHTML = `<div class="empty small">记忆插件 Token 统计未接入</div>`;
    return;
  }
  box.innerHTML = tokenTable(
    ["时间", "记忆任务", "Provider", "Token", "缓存", "延迟", "状态"],
    rows,
    (item) => [
      formatRecentTime(item.ts, item.time),
      tokenTaskLabel(item.task),
      item.provider || "default",
      `${formatNumber(item.total_tokens)}${item.estimated ? " 估" : ""}`,
      tokenCacheText(item),
      `${formatNumber(Math.round(Number(item.elapsed_ms || item.latency_ms || 0)))} ms`,
      item.success ? "成功" : `失败 ${item.error || ""}`.trim(),
    ],
    "暂无记忆插件最近调用"
  );
}

export function tokenCacheText(item) {
  const cached = Number(item?.cached_tokens || 0);
  const read = Number(item?.cache_read_tokens || 0);
  const write = Number(item?.cache_write_tokens || 0);
  const total = Number(item?.total_tokens || 0);
  if (cached <= 0 && read <= 0 && write <= 0) {
    const estimated = Boolean(item?.estimated) || Number(item?.estimated_ratio || 0) >= 1;
    return total > 0 && !estimated ? "0 · 0%" : "-";
  }
  const ratio = Number(item?.cached_ratio || 0) || (total > 0 ? (cached || read) / total : 0);
  const hit = cached || read;
  const parts = [`命中 ${formatCompactNumber(hit)}`];
  if (ratio > 0) parts.push(`${Math.round(ratio * 100)}%`);
  if (read > 0 || write > 0) parts.push(`读/写 ${formatCompactNumber(read)}/${formatCompactNumber(write)}`);
  return parts.join(" · ");
}

export function tokenTable(headers, rows, mapper, emptyText) {
  if (!rows.length) return `<div class="empty small">${escapeHtml(emptyText)}</div>`;
  return `
    <table>
      <thead><tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((row) => `<tr>${mapper(row).map((value) => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")}
      </tbody>
    </table>
  `;
}

export function tokenTaskLabel(key) {
  const normalized = String(key || "").trim();
  if (!normalized) return "未分类模型调用";
  if (tokenTaskLabels[normalized]) return tokenTaskLabels[normalized];
  if (normalized.startsWith("qzone_") && normalized.endsWith("_photo_prompt")) return "空间配图提示";
  if (normalized.startsWith("qzone_")) return "QQ 空间任务";
  if (normalized.startsWith("astrbot_")) return "AstrBot 主回复";
  if (normalized.startsWith("private_image_")) return "私聊图片处理";
  if (normalized.startsWith("web_exploration_")) return "主动搜索";
  return normalized;
}

export function formatNumber(value) {
  return Number(value || 0).toLocaleString("zh-CN");
}

export function formatPercent(value) {
  const num = Number(value || 0);
  return `${Math.round(num * 100)}%`;
}

export function formatHourKey(key) {
  const text = String(key || "");
  if (!text.includes("T")) return text || "-";
  return text.replace("T", " ");
}

export function formatRecentTime(ts, fallback) {
  const num = Number(ts || 0);
  if (!num) return fallback || "-";
  return new Date(num * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function expressionScopeItems(kind, selectedIds = []) {
  const selected = new Set((selectedIds || []).map((item) => String(item || "").trim()).filter(Boolean));
  const known = kind === "group"
    ? state.groups.map((group) => ({
      id: String(group.group_id || "").trim(),
      label: groupDisplayName(group),
      meta: groupIdText(group),
    }))
    : state.users.map((user) => ({
      id: String(user.user_id || "").trim(),
      label: user.display_name || user.nickname || user.user_id,
      meta: user.relationship_role_label || "私聊对象",
    }));
  const knownIds = new Set(known.map((item) => item.id));
  selected.forEach((id) => {
    if (!knownIds.has(id)) known.push({ id, label: id, meta: "已配置，当前列表未载入" });
  });
  return known.filter((item) => item.id);
}

export function renderExpressionScopeChecklist(definition, selectedIds) {
  const selected = new Set((selectedIds || []).map((item) => String(item || "")));
  const items = expressionScopeItems(definition.itemKind, selectedIds);
  if (!items.length) {
    return `<p class="expression-scope-empty">暂无可选${definition.itemKind === "group" ? "群聊" : "私聊对象"}，产生会话记录后会出现在这里。</p>`;
  }
  return `
    <div class="expression-selected-toolbar">
      <span>已选 <b data-expression-selected-count>${selected.size}</b> / ${items.length}</span>
      <input type="search" data-expression-scope-search placeholder="筛选${definition.itemKind === "group" ? "群聊" : "私聊"}" aria-label="筛选${escapeHtml(definition.title)}对象" />
    </div>
    <div class="expression-scope-checklist" data-expression-id-list="${escapeHtml(definition.idsKey)}">
      ${items.map((item) => `
        <label class="expression-scope-check">
          <input type="checkbox" value="${escapeHtml(item.id)}" ${selected.has(item.id) ? "checked" : ""} />
          <span><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.meta || item.id)}</small></span>
        </label>
      `).join("")}
    </div>
  `;
}

export function renderExpressionScopeManager() {
  const root = $("#expressionScopeManager");
  if (!root) return;
  const scope = state.overview?.expression_scope || {};
  const voice = scope.voice || {};
  const groupBudget = scope.group_budget || {};
  root.classList.toggle("is-disabled", scope.enabled === false);
  root.innerHTML = `
    <header class="expression-scope-head">
      <h3>表达范围</h3>
      <div class="expression-voice-status" aria-label="当前表达底色统计">
        <strong>${escapeHtml(voice.sample_count || 0)}</strong><span>证据</span>
        <small>私聊 ${escapeHtml(voice.private_source_count || 0)} · 群聊 ${escapeHtml(voice.group_source_count || 0)} · 今日归纳 ${escapeHtml(groupBudget.used_today || 0)}/${escapeHtml(groupBudget.daily_limit || 6)}</small>
      </div>
    </header>
    <details class="dashboard-disclosure expression-scope-disclosure" ${state.expressionScopeOpen ? "open" : ""}>
      <summary>
        <span><b>范围设置</b><small>${scope.enabled === false ? "当前关闭" : "来源与应用位置"}</small></span>
      </summary>
      <div class="expression-budget-panel" aria-label="群聊语义归纳预算">
        <div>
          <b>群聊语义归纳预算</b>
          <span>控制每天最多整理多少批群聊。</span>
        </div>
        <label>
          <span>每天最多批次</span>
          <input type="number" min="1" max="50" step="1" value="${escapeHtml(groupBudget.daily_limit || 6)}" data-expression-budget-key="expression_group_learning_daily_batch_limit" />
        </label>
        <label>
          <span>每批最少新增</span>
          <input type="number" min="5" max="80" step="5" value="${escapeHtml(groupBudget.min_new_messages || 20)}" data-expression-budget-key="expression_group_learning_min_new_messages" />
        </label>
      </div>
      <div class="expression-scope-grid">
        ${expressionScopeDefinitions.map((definition) => {
        const current = scope[definition.sourceKey] || {};
        const validModes = definition.modes.map(([value]) => value);
        const fallback = definition.defaultMode;
        const mode = validModes.includes(current.mode) ? current.mode : fallback;
        const selectedIds = Array.isArray(current.ids) ? current.ids : [];
        return `
          <fieldset class="expression-scope-field" data-expression-scope-field="${escapeHtml(definition.id)}" data-selected-mode="${mode === "selected" ? "1" : "0"}">
            <legend>${escapeHtml(definition.title)}</legend>
            <p>${escapeHtml(definition.description)}</p>
            <div class="expression-mode-control" role="radiogroup" aria-label="${escapeHtml(definition.title)}">
              ${definition.modes.map(([value, label]) => `
                <label>
                  <input type="radio" name="${escapeHtml(definition.modeKey)}" value="${escapeHtml(value)}" ${mode === value ? "checked" : ""} />
                  <span>${escapeHtml(label)}</span>
                </label>
              `).join("")}
            </div>
            <div class="expression-selected-list">
              ${renderExpressionScopeChecklist(definition, selectedIds)}
            </div>
            <p class="expression-empty-warning" data-expression-empty-warning ${mode === "selected" && selectedIds.length === 0 ? "" : "hidden"} aria-live="polite">尚未勾选对象，当前指定范围不会生效。</p>
          </fieldset>
        `;
        }).join("")}
      </div>
      <footer class="expression-scope-footer">
        <button type="button" data-save-expression-scope>保存范围</button>
      </footer>
    </details>
  `;
  root.querySelector(".expression-scope-disclosure")?.addEventListener("toggle", (event) => {
    state.expressionScopeOpen = Boolean(event.currentTarget.open);
  });
  root.querySelectorAll("[data-expression-scope-field] input[type='radio']").forEach((input) => {
    input.addEventListener("change", () => {
      const field = input.closest("[data-expression-scope-field]");
      if (field) {
        field.dataset.selectedMode = input.value === "selected" ? "1" : "0";
        const warning = field.querySelector("[data-expression-empty-warning]");
        const checkedCount = field.querySelectorAll(".expression-scope-check input[type='checkbox']:checked").length;
        if (warning) warning.hidden = input.value !== "selected" || checkedCount > 0;
      }
    });
  });
  root.querySelectorAll("[data-expression-scope-search]").forEach((input) => {
    input.addEventListener("input", () => {
      const query = String(input.value || "").trim().toLowerCase();
      const field = input.closest("[data-expression-scope-field]");
      field?.querySelectorAll(".expression-scope-check").forEach((item) => {
        item.hidden = Boolean(query) && !String(item.textContent || "").toLowerCase().includes(query);
      });
    });
  });
  root.querySelectorAll(".expression-scope-check input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", () => {
      const field = input.closest("[data-expression-scope-field]");
      const count = field?.querySelector("[data-expression-selected-count]");
      if (count && field) {
        const checkedCount = field.querySelectorAll(".expression-scope-check input[type='checkbox']:checked").length;
        count.textContent = String(checkedCount);
        const selectedMode = field.querySelector("input[type='radio']:checked")?.value === "selected";
        const warning = field.querySelector("[data-expression-empty-warning]");
        if (warning) warning.hidden = !selectedMode || checkedCount > 0;
      }
    });
  });
  const saveButton = root.querySelector("[data-save-expression-scope]");
  saveButton?.addEventListener("click", async () => {
    const settings = {};
    expressionScopeDefinitions.forEach((definition) => {
      const modeInput = root.querySelector(`input[name="${definition.modeKey}"]:checked`);
      const list = root.querySelector(`[data-expression-id-list="${definition.idsKey}"]`);
      settings[definition.modeKey] = modeInput?.value || definition.modes[0][0];
      settings[definition.idsKey] = Array.from(list?.querySelectorAll("input[type='checkbox']:checked") || [])
        .map((input) => String(input.value || "").trim())
        .filter(Boolean);
    });
    root.querySelectorAll("[data-expression-budget-key]").forEach((input) => {
      settings[input.dataset.expressionBudgetKey] = Number(input.value || 0);
    });
    const emptySelected = expressionScopeDefinitions.find((definition) => (
      settings[definition.modeKey] === "selected" && settings[definition.idsKey].length === 0
    ));
    if (emptySelected) {
      showToast(`“${emptySelected.title}”选择了指定范围，但还没有勾选对象`, "error");
      return;
    }
    const updated = await runAction(
      () => postJson("/settings/update", { settings }),
      "已保存表达方式学习范围",
      saveButton,
    );
    if (updated) {
      state.expressionLibrary = null;
      void renderExpressionLibrary(true);
    }
  });
}

export function renderLearningSummary() {
  const root = $("#learningSummary");
  if (!root) return;
  const library = state.expressionLibrary || {};
  const growth = state.overview?.skill_growth || {};
  const skills = Array.isArray(growth.items) ? growth.items : [];
  const ruleCount = Number(library.rule_group_count ?? library.rule_count ?? library.pattern_count ?? (Array.isArray(library.rule_groups) ? library.rule_groups.length : 0));
  const pendingCount = Number(library.pending_rule_group_count ?? library.pending_rule_count ?? library.pending_count ?? (Array.isArray(library.pending_rule_groups) ? library.pending_rule_groups.length : 0));
  const skillCount = Number(growth.skill_count || skills.length || 0);
  const worldbook = state.overview?.worldbook || {};
  const relationshipCount = Number(worldbook.member_count || 0);
  const pendingObservationCount = Number(worldbook.pending_observation_total || 0);
  root.innerHTML = `
    <button id="learningTabSocial" type="button" role="tab" aria-controls="learningPanelSocial" data-learning-section="social" class="learning-summary-card" aria-label="关系网，共 ${escapeHtml(relationshipCount)} 个节点">
      <b>${escapeHtml(relationshipCount)}</b>
      <span>关系网</span>
      <small id="worldbookNavSummary">${escapeHtml(pendingObservationCount)} 条待确认</small>
    </button>
    <button id="learningTabSkills" type="button" role="tab" aria-controls="learningPanelSkills" data-learning-section="skills" class="learning-summary-card" aria-label="技能，共 ${escapeHtml(skillCount)} 项">
      <b>${escapeHtml(skillCount)}</b>
      <span>技能</span>
      <small id="skillGrowthSummary">成长与熟练度</small>
    </button>
    <div class="learning-summary-card learning-summary-expression-card" data-learning-expression-card role="presentation">
      <button id="learningTabExpressions" type="button" role="tab" aria-controls="learningPanelExpressions" data-learning-section="expressions" data-expression-nav-view="library" class="learning-summary-expression-main" aria-label="表达，共 ${escapeHtml(ruleCount)} 个已启用规则组">
        <b>${escapeHtml(ruleCount)}</b>
        <span>表达</span>
        <small id="expressionLibrarySummary">已启用规则组</small>
      </button>
      <button type="button" class="learning-summary-review-action ${pendingCount > 0 ? "has-attention" : ""}" data-learning-review-shortcut aria-controls="learningPanelExpressions" aria-pressed="false" aria-label="审核队列，共 ${escapeHtml(pendingCount)} 组待审核">
        <b>${escapeHtml(pendingCount)}</b>
        <span>审核</span>
        <small>${pendingCount ? "待处理" : "已清空"}</small>
      </button>
    </div>
  `;
  root.querySelector("[data-learning-review-shortcut]")?.addEventListener("click", () => {
    state.expressionWorkspaceView = "review";
    switchLearningSection("expressions");
  });
  bindLearningNavigation();
  syncLearningNavigationState();
  const expressionSummary = $("#expressionLibrarySummary");
  if (expressionSummary) expressionSummary.textContent = `${ruleCount} 个规则组`;
  const skillSummary = $("#skillGrowthSummary");
  if (skillSummary) {
    skillSummary.textContent = growth.enabled === false
      ? "未开启"
      : (growth.frozen_count ? `${growth.frozen_count} 项冻结` : "成长与熟练度");
  }
  const reviewCount = $("#expressionReviewCount");
  if (reviewCount) reviewCount.textContent = String(pendingCount);
  const worldbookSummary = $("#worldbookNavSummary");
  if (worldbookSummary) {
    worldbookSummary.textContent = worldbook.pending_observation_total
      ? `${worldbook.pending_observation_total} 条待确认`
      : "身份与边界";
  }
}

export function switchLearningSection(section, options = {}) {
  const next = ["skills", "expressions", "social"].includes(section) ? section : "expressions";
  state.learningSection = next;
  syncLearningNavigationState();
  document.querySelectorAll("[data-learning-section-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.learningSectionPanel !== next;
  });
  if (next === "expressions") {
    syncExpressionWorkspaceView();
    void renderExpressionLibrary();
  } else if (next === "social") {
    renderWorldbook();
  } else {
    renderSkillGrowth();
  }
  if (options.focus) {
    document.querySelector(`[data-learning-section="${next}"]`)?.focus();
  }
}

export function syncLearningNavigationState() {
  document.querySelectorAll("[data-learning-section]").forEach((button) => {
    const selected = button.dataset.learningSection === state.learningSection;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
    button.tabIndex = selected ? 0 : -1;
  });
  const expressionSelected = state.learningSection === "expressions";
  document.querySelector("[data-learning-expression-card]")?.classList.toggle("is-active", expressionSelected);
  const reviewShortcut = document.querySelector("[data-learning-review-shortcut]");
  const reviewSelected = expressionSelected && state.expressionWorkspaceView === "review";
  reviewShortcut?.classList.toggle("is-active", reviewSelected);
  reviewShortcut?.setAttribute("aria-pressed", reviewSelected ? "true" : "false");
}

export function syncExpressionWorkspaceView() {
  const next = state.expressionWorkspaceView === "review" ? "review" : "library";
  document.querySelectorAll("[data-expression-view]").forEach((button) => {
    const selected = button.dataset.expressionView === next;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", selected ? "true" : "false");
    button.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll("[data-expression-view-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.expressionViewPanel !== next;
  });
  if (next === "review") renderExpressionReviewWorkspace();
}

export function switchExpressionWorkspaceView(view, options = {}) {
  state.expressionWorkspaceView = view === "review" ? "review" : "library";
  syncExpressionWorkspaceView();
  syncLearningNavigationState();
  if (options.focus) {
    document.querySelector(`[data-expression-view="${state.expressionWorkspaceView}"]`)?.focus();
  }
}

export function bindLearningNavigation() {
  document.querySelectorAll("[data-learning-section]").forEach((button) => {
    if (button.dataset.bound === "1") return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => {
      if (button.dataset.expressionNavView) state.expressionWorkspaceView = button.dataset.expressionNavView;
      switchLearningSection(button.dataset.learningSection || "expressions");
    });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...document.querySelectorAll("[data-learning-section]")];
      const current = buttons.indexOf(button);
      const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      const next = buttons[nextIndex];
      if (next) switchLearningSection(next.dataset.learningSection || "expressions", { focus: true });
    });
  });
  document.querySelectorAll("[data-expression-view]").forEach((button) => {
    if (button.dataset.bound === "1") return;
    button.dataset.bound = "1";
    button.addEventListener("click", () => switchExpressionWorkspaceView(button.dataset.expressionView || "library"));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "ArrowLeft" || event.key === "Home" ? "library" : "review";
      switchExpressionWorkspaceView(next, { focus: true });
    });
  });
}

export function renderLearning() {
  renderLearningSummary();
  bindLearningNavigation();
  renderExpressionScopeManager();
  void renderExpressionLibrary();
  renderSkillGrowth();
  switchLearningSection(state.learningSection);
}

export function renderUsers(refreshDetail = true) {
  const keyword = ($("#userFilter").value || "").trim().toLowerCase();
  const rows = state.users.filter((user) => {
    const text = `${user.user_id} ${user.nickname} ${user.display_name || ""} ${user.umo} ${(user.alias_user_ids || []).join(" ")}`.toLowerCase();
    const status = $("#userStatusFilter").value;
    return (!keyword || text.includes(keyword)) && (status === "all" || Boolean(user.enabled) === (status === "enabled"));
  });
  $("#userListCoverage").textContent = `本次载入 ${state.users.length} 个对象 · 符合筛选 ${rows.length} 个。列表最多返回 300 个近期对象。`;
  $("#userRows").innerHTML = rows.length
    ? rows.map((user) => `
      <tr data-user-id="${escapeHtml(user.user_id)}" class="${user.user_id === state.selectedUserId ? "is-selected" : ""}">
        <td class="user-cell identity"><button type="button" class="aw-user-open" title="查看对象资料">${escapeHtml(user.display_name || user.nickname || user.user_id)}</button>${user.is_qq_user ? "" : ` <span class="badge off">非 QQ</span>`}${Array.isArray(user.alias_user_ids) && user.alias_user_ids.length ? ` <span class="badge ok" title="${escapeHtml(user.alias_user_ids.join("\\n"))}">已合并 ${escapeHtml(user.alias_user_ids.length)} 个身份</span>` : ""}<br><span class="user-id-line"><span class="muted mono" title="${escapeHtml(user.user_id)}">${escapeHtml(user.user_id)}</span><button type="button" class="copy-id-btn" data-copy-user-id="${escapeHtml(user.user_id)}">复制</button></span></td>
        <td class="user-cell relation"><span class="badge ${user.enabled ? "" : "off"}">${escapeHtml(user.enabled ? "启用" : "停用")}</span> <span class="badge">${escapeHtml(user.relationship_role_label || "次要用户")}</span> <span class="muted">${escapeHtml(user.relationship_stage || "未分层")}</span><br><span>分数 ${escapeHtml(user.relationship_score)}</span></td>
        <td class="user-cell compact">入站 ${escapeHtml(user.inbound_count)} · 回复 ${escapeHtml(user.reply_count)}<br><span class="muted">记忆 ${escapeHtml(user.memory_items)} 条</span></td>
        <td class="user-cell proactive"><span>今日 ${escapeHtml(user.sent_today)} · 总计 ${escapeHtml(user.proactive_sent_count)}</span><br><span class="muted truncate" title="${escapeHtml(user.next_proactive || "")}">${escapeHtml(user.next_proactive)}</span></td>
        <td class="user-cell recent">${escapeHtml(user.last_seen)}<br><span class="muted">上次主动 ${escapeHtml(user.last_sent)}</span></td>
        <td class="user-cell action"><button type="button" class="table-action ${user.enabled ? "danger-outline" : ""}" data-user-toggle="${escapeHtml(user.user_id)}">${escapeHtml(user.enabled ? "停用" : "启用")}</button></td>
      </tr>
    `).join("")
    : `<tr><td class="empty" colspan="6">暂无私聊对象</td></tr>`;
  document.querySelectorAll("[data-user-toggle]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const user = state.users.find((item) => item.user_id === button.dataset.userToggle);
      if (!user) return;
      await runAction(() => postJson("/user/update", {
        user_id: user.user_id,
        enabled: !user.enabled,
      }), !user.enabled ? "已启用私聊对象" : "已停用私聊对象", button);
    });
  });
  document.querySelectorAll("[data-copy-user-id]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await copyTextToClipboard(button.dataset.copyUserId || "", "已复制用户 ID");
    });
  });
  document.querySelectorAll("#userRows tr[data-user-id]").forEach((row) => {
    row.addEventListener("click", async () => {
      if (state.selectedUserId !== row.dataset.userId) state.userDetailSection = "profile";
      state.selectedUserId = row.dataset.userId;
      renderUsers(false);
      await renderUserDetail(true);
    });
  });
  if (refreshDetail) void renderUserDetail();
}

export async function renderUserDetail(forceFetch = false) {
  const box = $("#userDetail"), id = String(state.selectedUserId || "");
  if (!forceFetch && box.dataset.detailUserId === id && box.querySelector('#userEditForm')?.dataset.dirty === "true") return;
  const serial = ++state.userDetailSerial;
  const current = () => serial === state.userDetailSerial && String(state.selectedUserId || "") === id;
  box.dataset.detailUserId = id;
  if (!id) {box.innerHTML = '<p class="muted">选择一个对象查看资料与互动记录。</p>'; return;}
  box.innerHTML = `<p class="muted" role="status">正在读取 ${escapeHtml(id)} 的资料…</p>`;
  let detail = state.users.find(user => String(user.user_id) === id);
  if (forceFetch || !detail?.formatted) {
    try {
      detail = await fetchJson(`/user?user_id=${encodeURIComponent(id)}`);
      if (!current()) return;
      if (String(detail?.user_id || "") !== id) throw new Error("返回对象不匹配，请重新读取");
    } catch (error) {
      if (!current()) return;
      box.innerHTML = `<p class="muted" role="alert">详情读取失败：${escapeHtml(error.message)}</p><button type="button" data-user-retry>重新读取</button>`;
      box.querySelector('[data-user-retry]').addEventListener('click', () => {if (current()) void renderUserDetail(true);});
      return;
    }
  }
  if (!current()) return;
  box.innerHTML = `
    <header class="aw-user-heading"><div><h3>${escapeHtml(detail.display_name || detail.nickname || id)}</h3><p>对象 ${escapeHtml(id)} · ${escapeHtml(detail.relationship_role_label || "次要用户")}</p></div>
      <span class="badge ${detail.enabled ? "ok" : "off"}">${detail.enabled ? "陪伴已启用" : "陪伴已停用"}</span></header>
    <div class="aw-user-tabs" role="group" aria-label="对象资料分区">
      <button type="button" data-user-section="profile">资料与偏好</button>
      <button type="button" data-user-section="records">互动与关系</button>
      <button type="button" data-user-section="maintenance">维护操作</button>
    </div>
    <section class="aw-user-section" data-user-panel="profile">
      <details class="aw-user-editor"><summary>编辑称呼、语气与主动额度</summary>
      <p class="muted">-1 沿用默认额度，0 不生成主动内容；实际额度仍受全局规则约束。主要用户包含原管理权限，请按真实关系设置。</p>
    <form id="userEditForm" class="inline-form">
      <label>称呼 <input name="nickname" value="${escapeHtml(detail.nickname || "")}" placeholder="例如 昵称 / 名字" /></label>
      <label>语气 <input name="style" value="${escapeHtml(detail.style || "")}" placeholder="温柔 / 活泼 / 工作" /></label>
      <label>关系角色
        <select name="relationship_role">
          <option value="owner" ${detail.relationship_role === "owner" ? "selected" : ""}>主要用户（含管理权限）</option>
          <option value="friend" ${detail.relationship_role !== "owner" ? "selected" : ""}>次要用户</option>
        </select>
      </label>
      <label>每日主动 <input name="proactive_daily_limit" type="number" min="-1" max="30" step="1" value="${escapeHtml(detail.proactive_daily_limit ?? -1)}" /></label>
      <button type="submit">保存</button>
    </form>
      <p class="aw-user-draft" role="status">修改后点击保存。关闭页面或换到其他对象会丢弃未保存内容。</p></details>
      <div class="toolbar"><button type="button" data-user-action="toggle">${detail.enabled ? "停用私聊陪伴" : "启用私聊陪伴"}</button></div>
    <div class="visual-strip">
      ${scoreGauge("关系分", detail.relationship_score || 0, -20, 40)}
      ${scoreGauge("今日主动", detail.sent_today || 0, 0, proactiveGaugeMax(detail.sent_today, detail.effective_daily_limit, detail.effective_daily_limit_unlimited, state.overview?.private?.max_daily_messages || 8))}
      ${miniStat("片段", detail.dialogue_episode_count || (detail.dialogue_episodes || []).length)}
      ${miniStat("未完话头", Array.isArray(detail.open_loops) ? activeOpenLoopItems(detail.open_loops).length : (detail.open_loop_count || 0))}
      ${miniStat("习惯", detail.habit_count || detail.behavior_habits?.items?.length || 0)}
    </div>
      ${detailBlock("关系和主动", detail.formatted?.relationship || "", [["角色", detail.relationship_role_label || ""], ["有效主动上限", `${detail.effective_daily_limit_text || formatProactiveLimit(detail.effective_daily_limit, detail.effective_daily_limit_unlimited)} / 天`], ["下次主动", detail.formatted?.next_proactive || detail.next_proactive], ["动作偏好", detail.formatted?.action_affinity || ""]])}
    </section>
    <section class="aw-user-section" data-user-panel="records" hidden>
      <p class="muted">以下为陪伴模块当前返回的关系、近期对话与整理片段，不是全部聊天历史或完整长期记忆。</p>
    <div class="detail-grid">
      ${renderPrivateBehaviorHabits(detail)}
      ${emotionGateBlock(detail)}
      ${userWorldbookBlock(detail.worldbook_member)}
      ${detailBlock("最近对话", "", [["用户消息", detail.last_user_message || ""], ["陪伴回复", detail.last_companion_message || ""]])}
      ${renderOpenLoopBlock(detail)}
    </div>
    <div class="private-dialogue-section">
      ${renderPrivateDialogueEpisodes(detail)}
    </div>
    </section>
    <section class="aw-user-section" data-user-panel="maintenance" hidden>
      <h3>当前对象的维护操作</h3>
      <p>重置今日额度会重置该对象的当日计数；清空计划处理本模块的待执行计划，不能撤回已经开始或发送的消息。</p>
      <p>重置情绪只清理原扮演状态。删除对象还会处理原目标名单、身份与发送映射、表达学习范围；不会替你清空其他系统的数据。</p>
    <div class="toolbar">
      <button data-user-action="reset_daily">重置今日额度</button>
      <button data-user-action="clear_schedule">清空主动计划</button>
      <button data-user-action="clear_emotion_state">重置情绪状态</button>
      <button data-user-action="delete" class="danger">删除私聊用户</button>
    </div>
    </section>
  `;
  const showSection = name => {
    state.userDetailSection = ["profile", "records", "maintenance"].includes(name) ? name : "profile";
    box.querySelectorAll('[data-user-panel]').forEach(panel => {panel.hidden = panel.dataset.userPanel !== state.userDetailSection;});
    box.querySelectorAll('[data-user-section]').forEach(button => {button.setAttribute('aria-pressed', String(button.dataset.userSection === state.userDetailSection));});
  };
  box.querySelectorAll('[data-user-section]').forEach(button => button.addEventListener('click', () => showSection(button.dataset.userSection)));
  showSection(state.userDetailSection);
  box.querySelector('#userEditForm').addEventListener('input', event => {
    event.currentTarget.dataset.dirty = "true";
    box.querySelector('.aw-user-draft').textContent = "有未保存修改；切换分区或筛选列表会保留当前输入。";
  });
  bindUserActions(detail);
}

export function renderPrivateDialogueEpisodes(detail) {
  const episodes = Array.isArray(detail?.dialogue_episodes) ? detail.dialogue_episodes : [];
  const episodePairs = episodes.length
    ? episodes.map((item, index) => [
      item.title || `片段 ${index + 1}`,
      item.summary || item.content || JSON.stringify(item),
    ])
    : [["-", "暂无已整理对话片段"]];
  const note = episodes.length ? `当前保留 ${episodes.length} 个私聊片段` : "私聊积累到整理条件后会显示在这里";
  return detailBlock("对话片段", note, episodePairs);
}

export function renderPrivateBehaviorHabits(detail) {
  const habits = detail?.behavior_habits || {};
  const pairs = userHabitPairs(habits);
  const updatedAt = habits.updated_at ? `更新于 ${habits.updated_at}` : (habits.enabled ? "等待形成稳定样本" : "习惯学习未开启");
  return `
    <section class="detail-block private-habit-block">
      <header class="private-habit-head">
        <div>
          <h2>行为习惯</h2>
          <span>${escapeHtml(updatedAt)}</span>
        </div>
        <button type="button" class="danger-outline" data-private-learning-clear>清空</button>
      </header>
      <dl>${pairs.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value || "-")}</dd>`).join("")}</dl>
    </section>
  `;
}

export function userWorldbookBlock(item) {
  if (!item) {
    return `
      <section class="detail-block user-worldbook-block">
        <h2>关系网词条</h2>
        <div class="empty small">暂无对应关系节点</div>
      </section>
    `;
  }
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  const observed = Array.isArray(item.observed_names) ? item.observed_names : [];
  const memories = Array.isArray(item.important_memories) ? item.important_memories : [];
  const chips = [
    ...aliases.map((name) => `别名：${name}`),
    ...observed.map((name) => `群名片：${name}`),
    ...(Array.isArray(item.external_ids) ? item.external_ids.map((id) => `外部身份：${id}`) : []),
  ].slice(0, 12);
  const previewItems = worldbookMemberPreviewItems(item, memories);
  return `
    <section class="detail-block user-worldbook-block">
      <div class="user-worldbook-head">
        <div>
          <h2>关系网词条</h2>
          <p>${escapeHtml(item.name || item.user_id || "未命名成员")}</p>
        </div>
        <span class="badge ${item.enabled ? "ok" : "off"}">${escapeHtml(item.enabled ? "启用" : "停用")}</span>
      </div>
      <div class="worldbook-compact-meta">
        <span>${escapeHtml(item.identity_type === "external" ? "外部身份" : "身份 QQ")} ${escapeHtml(item.user_id || "-")}</span>
        <span>优先级 ${escapeHtml(item.priority ?? "-")}</span>
        ${item.gender ? `<span>性别：${escapeHtml(item.gender)}</span>` : ""}
        ${item.pending_observation_count ? `<span>${escapeHtml(item.pending_observation_count)} 条待确认观察</span>` : ""}
      </div>
      <div class="worldbook-chip-row">
        ${chips.length ? chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("") : `<span>暂无别名记录</span>`}
      </div>
      ${previewItems.length ? `
        <div class="worldbook-member-preview-list">
          ${previewItems.map(([label, value]) => `<p><b>${escapeHtml(label)}</b><span>${escapeHtml(value)}</span></p>`).join("")}
        </div>
      ` : `<div class="empty small">暂无词条正文或记忆</div>`}
      ${memories.length ? `
        <div class="user-worldbook-memory-list">
          ${memories.slice(0, 4).map((memory) => `
            <p><b>${escapeHtml(memory.title || "重要记忆")}</b><span>${escapeHtml(memory.content || "")}</span></p>
          `).join("")}
        </div>
      ` : ""}
    </section>
  `;
}

export function emotionGateBlock(detail) {
  const rel = detail.relationship_state && typeof detail.relationship_state === "object" ? detail.relationship_state : {};
  const intent = detail.intent_profile && typeof detail.intent_profile === "object" ? detail.intent_profile : {};
  const mode = rel.mode || "normal";
  const moodScore = Number(rel.mood_score || 0);
  const dims = rel.emotion_dimensions && typeof rel.emotion_dimensions === "object" ? rel.emotion_dimensions : {};
  const dimensionText = Object.keys(dims).length
    ? `愉快 ${Number(dims.pleasantness ?? 0)}｜紧张 ${Number(dims.tension ?? 0)}｜激动 ${Number(dims.arousal ?? 0)}｜确信 ${Number(dims.certainty ?? 0)}`
    : "-";
  const plutchik = rel.plutchik_profile && typeof rel.plutchik_profile === "object" ? rel.plutchik_profile : {};
  const activeEmotionText = Array.isArray(plutchik.active) && plutchik.active.length
    ? plutchik.active.map((item) => `${item.label || item.key || "-"} ${Number(item.value || 0)}`).join("｜")
    : "-";
  const blendText = [plutchik.dominant_label ? `${plutchik.dominant_label} ${Number(plutchik.dominant_value || 0)}` : "", plutchik.blend_label || ""]
    .filter(Boolean)
    .join("｜") || "-";
  const regulation = rel.emotion_regulation && typeof rel.emotion_regulation === "object" ? rel.emotion_regulation : {};
  const strategyStack = Array.isArray(regulation.strategy_stack) ? regulation.strategy_stack : [];
  const regulationText = regulation.strategy && regulation.strategy !== "none"
    ? `${regulation.strategy_label || regulation.strategy}｜强度 ${Number(regulation.intensity || 0)}${regulation.reason ? `｜${regulation.reason}` : ""}`
    : "-";
  const strategyStackText = strategyStack.length
    ? strategyStack.map((item) => `${item.strategy_label || item.strategy || "-"} ${Number(item.intensity || 0)}`).join("｜")
    : "-";
  const pendingJudgement = detail.pending_emotion_judgement && typeof detail.pending_emotion_judgement === "object" ? detail.pending_emotion_judgement : {};
  const judgementError = String(detail.last_emotion_judgement_error || "").trim();
  const judgementText = pendingJudgement.text
    ? `等待模型复核｜${pendingJudgement.text}${pendingJudgement.created_at_text ? `｜${pendingJudgement.created_at_text}` : ""}`
    : (judgementError ? `上次复核失败｜${judgementError}` : "本地快判或已完成");
  const hurtUntil = Number(rel.hurt_until || 0);
  const now = Math.floor(Date.now() / 1000);
  const remaining = hurtUntil > now ? `${Math.ceil((hurtUntil - now) / 60)} 分钟` : "无";
  const pairs = [
    ["状态", mode],
    ["模型复核", judgementText],
    ["余波值", moodScore ? String(moodScore) : "0"],
    ["四维", dimensionText],
    ["基本/复合", blendText],
    ["活跃情绪", activeEmotionText],
    ["调节策略", regulationText],
    ["策略候选", strategyStackText],
    ["收敛轮数", rel.silence_turns || 0],
    ["剩余收敛", remaining],
    ["上次事件", rel.last_emotion_event || intent.emotion_event || "neutral"],
    ["对象", rel.last_emotion_target || intent.emotion_target || "-"],
    ["规则", rel.last_emotion_rule || intent.emotion_rule || "-"],
    ["强度", rel.last_emotion_intensity ?? intent.emotion_intensity ?? 0],
    ["意图置信度", rel.last_intent_confidence ?? intent.confidence ?? "-"],
    ["情绪置信度", rel.last_emotion_confidence ?? intent.emotion_confidence ?? "-"],
    ["原因", rel.last_emotion_reason || intent.emotion_reason || rel.last_hurt_reason || ""],
  ];
  const preText = rel.last_hurt_text ? `最近留下余波的话：${rel.last_hurt_text}` : "";
  return detailBlock("情绪余波", preText, pairs);
}

export function userHabitPairs(habits) {
  const items = Array.isArray(habits?.items) ? habits.items : [];
  return items.length
    ? items.map((item) => [
      `${item.bucket || "-"} ${item.avg_time || ""}`,
      `${item.category || "习惯"}｜${item.topic || "-"}｜${item.count || 0} 次${item.last_seen ? `｜最近 ${item.last_seen}` : ""}${item.last_seen_text ? `｜${item.last_seen_text}` : ""}`,
    ])
    : [["-", habits?.enabled ? "暂无达到阈值的习惯样本" : "习惯学习未开启"]];
}

export function normalizeOpenLoopItem(item) {
  const raw = item && typeof item === "object" ? item : {};
  return {
    text: String(raw.text || raw.topic || raw.summary || "").trim(),
    status: String(raw.status || "待自然延续").trim() || "待自然延续",
    source: String(raw.source || "").trim(),
  };
}

export function activeOpenLoopItems(items) {
  return (Array.isArray(items) ? items : [])
    .map(normalizeOpenLoopItem)
    .filter((item) => item.text && !["已完成", "已取消"].includes(item.status));
}

export function resolvedOpenLoopItems(items) {
  return (Array.isArray(items) ? items : [])
    .map(normalizeOpenLoopItem)
    .filter((item) => item.text && ["已完成", "已取消"].includes(item.status));
}

export function openLoopStatusClass(status) {
  if (status === "已完成") return "ok";
  if (status === "已取消") return "off";
  return "";
}

export function openLoopStatusText(item) {
  const parts = [item.status || "待自然延续"];
  if (item.source === "dialogue_episode") parts.push("片段整理");
  if (item.source === "user_message") parts.push("即时记录");
  return parts.join("｜");
}

export function renderOpenLoopBlock(detail) {
  const activeItems = activeOpenLoopItems(detail?.open_loops);
  const resolvedItems = resolvedOpenLoopItems(detail?.open_loops);
  return `
    <section class="detail-block open-loop-block">
      <div class="detail-block-head">
        <h2>未完话头</h2>
        ${activeItems.length ? `
          <div class="open-loop-actions">
            <button type="button" class="danger-outline" data-open-loop-clear="${escapeHtml(detail.user_id || "")}">清空未完话头</button>
          </div>
        ` : ""}
      </div>
      ${activeItems.length ? `
        <div class="open-loop-list">
          ${activeItems.map((item, index) => `
            <article class="open-loop-item">
              <div class="open-loop-main">
                <b class="open-loop-text">${escapeHtml(item.text)}</b>
                <span class="badge ${openLoopStatusClass(item.status)}">${escapeHtml(openLoopStatusText(item))}</span>
              </div>
              <button type="button" class="danger-outline" data-open-loop-remove="${escapeHtml(item.text)}" data-open-loop-index="${index}">删除</button>
            </article>
          `).join("")}
        </div>
      ` : `<div class="empty small">暂无未完话头</div>`}
      ${resolvedItems.length ? `
        <details class="open-loop-archive">
          <summary>已结束话头 ${escapeHtml(resolvedItems.length)}</summary>
          <div class="open-loop-list archived">
            ${resolvedItems.map((item) => `
              <article class="open-loop-item archived">
                <div class="open-loop-main">
                  <b class="open-loop-text">${escapeHtml(item.text)}</b>
                  <span class="badge ${openLoopStatusClass(item.status)}">${escapeHtml(openLoopStatusText(item))}</span>
                </div>
              </article>
            `).join("")}
          </div>
        </details>
      ` : ""}
    </section>
  `;
}

export function expressionLibrarySourceText(item) {
  const kind = item?.source_kind_label || (item?.source_type === "group" ? "群聊" : "私聊");
  const name = item?.source_name || item?.source_id || "未知来源";
  const id = item?.source_id || "";
  return `${kind} ${name} ${id}`.trim();
}

export function normalizeExpressionRuleGroup(value, fallbackIndex = 0) {
  const raw = value && typeof value === "object" ? value : {};
  const components = (Array.isArray(raw.items) ? raw.items : (Array.isArray(raw.component_rules) ? raw.component_rules : [raw]))
    .filter((item) => item && typeof item === "object");
  const styleRule = raw.style_rule && typeof raw.style_rule === "object"
    ? raw.style_rule
    : components.find((item) => item.kind === "style") || null;
  const grammarRule = raw.grammar_rule && typeof raw.grammar_rule === "object"
    ? raw.grammar_rule
    : components.find((item) => item.kind === "grammar") || null;
  const familyId = String(raw.family_id || raw.id || components[0]?.family_id || components[0]?.id || `rule-group-${fallbackIndex}`);
  const examples = [];
  components.forEach((item) => {
    (Array.isArray(item.evidence_examples) ? item.evidence_examples : []).forEach((example) => {
      if (example && !examples.includes(example)) examples.push(example);
    });
  });
  return {
    ...(components[0] || {}),
    ...raw,
    id: familyId,
    family_id: familyId,
    kind: styleRule && grammarRule ? "combined" : (styleRule ? "style" : "grammar"),
    kind_label: styleRule && grammarRule ? "组合规则" : (styleRule ? "情境表达" : "语法习惯"),
    label: raw.label || styleRule?.label || grammarRule?.label || styleRule?.situation || grammarRule?.situation || "未命名规则组",
    situation: raw.situation || styleRule?.situation || grammarRule?.situation || "",
    items: components,
    component_rules: components,
    component_count: components.length,
    component_kinds: [styleRule ? "style" : "", grammarRule ? "grammar" : ""].filter(Boolean),
    style_rule: styleRule,
    grammar_rule: grammarRule,
    evidence_count: Math.max(0, ...components.map((item) => Number(item.evidence_count) || 0), Number(raw.evidence_count) || 0),
    evidence_examples: Array.isArray(raw.evidence_examples) && raw.evidence_examples.length ? raw.evidence_examples : examples,
  };
}

export function expressionRuleGroups(library, pending = false) {
  const groupKey = pending ? "pending_rule_groups" : "rule_groups";
  const flatKey = pending ? "pending_rules" : "rules";
  const provided = Array.isArray(library?.[groupKey]) ? library[groupKey] : [];
  if (provided.length) return provided.map((item, index) => normalizeExpressionRuleGroup(item, index));
  const flatRules = Array.isArray(library?.[flatKey]) ? library[flatKey] : [];
  const buckets = new Map();
  flatRules.forEach((rule, index) => {
    const familyId = String(rule?.family_id || rule?.id || `rule-${index}`);
    const sourceKey = `${rule?.source_type || "private"}:${rule?.source_id || "unknown"}:${familyId}`;
    if (!buckets.has(sourceKey)) buckets.set(sourceKey, []);
    buckets.get(sourceKey).push(rule);
  });
  return Array.from(buckets.values()).map((items, index) => normalizeExpressionRuleGroup({
    ...(items[0] || {}),
    family_id: items[0]?.family_id || items[0]?.id || `rule-group-${index}`,
    items,
  }, index));
}

export function expressionLibraryItemMatches(item, filter, type, query) {
  if (filter !== "all" && String(item?.source_type || "") !== filter) return false;
  const components = Array.isArray(item?.items)
    ? item.items
    : (Array.isArray(item?.component_rules) ? item.component_rules : []);
  const componentKinds = new Set([
    String(item?.kind || ""),
    ...(Array.isArray(item?.component_kinds) ? item.component_kinds.map(String) : []),
    ...components.map((component) => String(component?.kind || "")),
  ]);
  if (type !== "all" && !componentKinds.has(type)) return false;
  if (!query) return true;
  const componentSearch = components.flatMap((component) => [
    component?.label,
    component?.situation,
    component?.pattern,
    component?.instruction,
    component?.avoid,
    ...(Array.isArray(component?.signals) ? component.signals : []),
    ...(Array.isArray(component?.evidence_examples) ? component.evidence_examples : []),
  ]);
  const searchable = [
    expressionLibrarySourceText(item),
    item?.text,
    item?.phrase,
    item?.ending,
    item?.label,
    item?.scene,
    item?.pattern,
    item?.pattern_label,
    item?.instruction,
    item?.kind_label,
    item?.avoid,
    item?.intent,
    ...(Array.isArray(item?.channels) ? item.channels : []),
    ...(Array.isArray(item?.relationship_stages) ? item.relationship_stages : []),
    ...(Array.isArray(item?.emotion_gates) ? item.emotion_gates : []),
    ...(Array.isArray(item?.features) ? item.features : []),
    ...(Array.isArray(item?.signals) ? item.signals : []),
    ...(Array.isArray(item?.tags) ? item.tags : []),
    ...(Array.isArray(item?.evidence_examples) ? item.evidence_examples : []),
    ...componentSearch,
  ].filter(Boolean).join(" ").toLowerCase();
  return searchable.includes(query);
}

export function resetExpressionLibraryVisibleCounts() {
  state.expressionLibraryVisibleCounts = { ...EXPRESSION_LIBRARY_PAGE_SIZES };
}

export function expressionLibraryVisibleCount(section) {
  const fallback = EXPRESSION_LIBRARY_PAGE_SIZES[section] || 12;
  return Math.max(fallback, Number(state.expressionLibraryVisibleCounts?.[section]) || fallback);
}

export function expressionLibraryResultCounts(library) {
  return {
    rules: expressionRuleGroups(library, true).length + expressionRuleGroups(library, false).length,
    observations: (Array.isArray(library?.pending_samples) ? library.pending_samples.length : 0)
      + (Array.isArray(library?.samples) ? library.samples.length : 0),
  };
}

export async function renderExpressionLibrary(forceFetch = false) {
  const root = $("#expressionLibrary");
  const reviewRoot = $("#expressionReviewWorkspace");
  if (!root) return;
  if (!forceFetch && state.expressionLibrary) {
    renderExpressionLibraryView();
    return;
  }
  if (state.expressionLibraryLoading && !forceFetch) return;
  const requestSeq = ++state.expressionLibraryRequestSeq;
  state.expressionLibraryLoading = true;
  state.expressionLibraryError = "";
  root.innerHTML = `<div class="learning-detail-loading" role="status" aria-label="正在读取统一表达学习库"><span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span></div>`;
  if (reviewRoot) reviewRoot.innerHTML = `<div class="learning-detail-loading" role="status" aria-label="正在读取表达审核队列"><span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span></div>`;
  try {
    const library = await fetchJson("/expression-library");
    if (requestSeq !== state.expressionLibraryRequestSeq) return;
    state.expressionLibrary = library;
    renderExpressionLibraryView();
  } catch (error) {
    if (requestSeq !== state.expressionLibraryRequestSeq) return;
    state.expressionLibraryError = error.message || "统一表达学习库读取失败";
    root.innerHTML = `
      <div class="learning-detail-empty is-error" role="alert">
        <b>统一表达学习库读取失败</b>
        <span>${escapeHtml(state.expressionLibraryError)}</span>
        <button type="button" data-expression-library-retry>重试</button>
      </div>
    `;
    root.querySelector("[data-expression-library-retry]")?.addEventListener("click", () => {
      void renderExpressionLibrary(true);
    });
    if (reviewRoot) {
      reviewRoot.innerHTML = `
        <div class="learning-detail-empty is-error" role="alert">
          <b>表达审核队列读取失败</b>
          <span>${escapeHtml(state.expressionLibraryError)}</span>
          <button type="button" data-expression-review-retry>重试</button>
        </div>
      `;
      reviewRoot.querySelector("[data-expression-review-retry]")?.addEventListener("click", () => {
        void renderExpressionLibrary(true);
      });
    }
  } finally {
    if (requestSeq === state.expressionLibraryRequestSeq) state.expressionLibraryLoading = false;
  }
}

export function renderExpressionLibraryView() {
  const root = $("#expressionLibrary");
  const library = state.expressionLibrary;
  if (!root || !library) return;
  renderLearningSummary();
  const filter = ["all", "private", "group"].includes(state.expressionLibraryFilter)
    ? state.expressionLibraryFilter
    : "all";
  const type = ["all", "style", "grammar"].includes(state.expressionLibraryType)
    ? state.expressionLibraryType
    : "all";
  const query = String(state.expressionLibraryQuery || "").trim().toLowerCase();
  const filterItems = (items) => (Array.isArray(items) ? items : []).filter((item) => expressionLibraryItemMatches(item, filter, type, query));
  const allRuleGroups = expressionRuleGroups(library, false);
  const allPendingRuleGroups = expressionRuleGroups(library, true);
  const matchedLibrary = {
    ...library,
    samples: filterItems(library.samples),
    pending_samples: filterItems(library.pending_samples),
    pending_rules: filterItems(library.pending_rules),
    rules: filterItems(library.rules),
    pending_rule_groups: filterItems(allPendingRuleGroups),
    rule_groups: filterItems(allRuleGroups),
  };
  const filteredLibrary = {
    ...matchedLibrary,
    samples: matchedLibrary.samples,
    pending_samples: matchedLibrary.pending_samples,
    pending_rules: [],
    pending_rule_groups: [],
    rules: matchedLibrary.rules,
    rule_groups: matchedLibrary.rule_groups,
  };
  const totalCounts = expressionLibraryResultCounts({ ...library, pending_rules: [], pending_rule_groups: [] });
  const resultCounts = expressionLibraryResultCounts(filteredLibrary);
  const activeFilterCount = Number(filter !== "all") + Number(type !== "all") + Number(Boolean(query));
  const resultText = `${resultCounts.rules} 组规则${resultCounts.observations ? ` · ${resultCounts.observations} 条观察` : ""}`;
  root.innerHTML = `
    <div class="expression-library-toolbar">
      <div class="expression-library-filter-groups">
        <div class="expression-library-filter-block">
          <span>来源</span>
          <div class="expression-library-segments" role="group" aria-label="筛选表达来源类型">
            ${[["all", "全部"], ["private", "私聊"], ["group", "群聊"]].map(([value, label]) => `
              <button type="button" class="${filter === value ? "is-active" : ""}" data-expression-library-filter="${value}" aria-pressed="${filter === value}">${label}</button>
            `).join("")}
          </div>
        </div>
        <div class="expression-library-filter-block">
          <span>类型</span>
          <div class="expression-library-segments expression-library-kind-segments" role="group" aria-label="筛选表达学习类型">
            ${[["all", "全部"], ["style", "情境表达"], ["grammar", "语法习惯"]].map(([value, label]) => `
              <button type="button" class="${type === value ? "is-active" : ""}" data-expression-library-type="${value}" aria-pressed="${type === value}">${label}</button>
            `).join("")}
          </div>
        </div>
      </div>
      <div class="expression-library-search-tools">
        <div class="expression-library-search-wrap">
          <input type="search" value="${escapeHtml(state.expressionLibraryQuery)}" data-expression-library-search placeholder="搜索情境、表达、标签或来源" aria-label="筛选统一表达学习库" />
          ${query ? `<button type="button" data-expression-search-clear aria-label="清空搜索">清除</button>` : ""}
        </div>
        <div class="expression-library-result-row" aria-live="polite">
          <span>${escapeHtml(resultText)}</span>
          ${activeFilterCount ? `<button type="button" data-expression-filter-reset>清除 ${escapeHtml(activeFilterCount)} 项筛选</button>` : `<span>审核后使用</span>`}
        </div>
      </div>
    </div>
    ${renderExpressionLibraryBlock(filteredLibrary, {
      hasAnyData: totalCounts.rules + totalCounts.observations > 0,
      hasActiveFilters: activeFilterCount > 0,
      pendingRuleCount: allPendingRuleGroups.length,
      mode: "library",
    })}
  `;
  root.querySelectorAll("[data-expression-library-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.expressionLibraryFilter = button.dataset.expressionLibraryFilter || "all";
      resetExpressionLibraryVisibleCounts();
      renderExpressionLibraryView();
    });
  });
  root.querySelectorAll("[data-expression-library-type]").forEach((button) => {
    button.addEventListener("click", () => {
      state.expressionLibraryType = button.dataset.expressionLibraryType || "all";
      resetExpressionLibraryVisibleCounts();
      renderExpressionLibraryView();
    });
  });
  root.querySelector("[data-expression-library-search]")?.addEventListener("input", (event) => {
    const selectionStart = event.currentTarget.selectionStart;
    state.expressionLibraryQuery = event.currentTarget.value || "";
    resetExpressionLibraryVisibleCounts();
    renderExpressionLibraryView();
    const nextInput = root.querySelector("[data-expression-library-search]");
    nextInput?.focus();
    if (nextInput && selectionStart !== null) nextInput.setSelectionRange(selectionStart, selectionStart);
  });
  root.querySelector("[data-expression-search-clear]")?.addEventListener("click", () => {
    state.expressionLibraryQuery = "";
    resetExpressionLibraryVisibleCounts();
    renderExpressionLibraryView();
    root.querySelector("[data-expression-library-search]")?.focus();
  });
  root.querySelectorAll("[data-expression-filter-reset]").forEach((button) => {
    button.addEventListener("click", () => {
      state.expressionLibraryFilter = "all";
      state.expressionLibraryType = "all";
      state.expressionLibraryQuery = "";
      resetExpressionLibraryVisibleCounts();
      renderExpressionLibraryView();
    });
  });
  root.querySelectorAll("[data-expression-show-more]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = button.dataset.expressionShowMore || "";
      const step = EXPRESSION_LIBRARY_PAGE_SIZES[section] || 12;
      state.expressionLibraryVisibleCounts = {
        ...state.expressionLibraryVisibleCounts,
        [section]: expressionLibraryVisibleCount(section) + step,
      };
      renderExpressionLibraryView();
    });
  });
  root.querySelector("[data-open-expression-review]")?.addEventListener("click", () => {
    switchExpressionWorkspaceView("review", { focus: true });
  });
  bindExpressionLibraryActions(library, root);
  renderExpressionReviewWorkspace();
}

export function expressionReviewRuleKey(ruleGroup, index = 0) {
  return String(ruleGroup?.family_id || ruleGroup?.id || `${ruleGroup?.source_type || "private"}:${ruleGroup?.source_id || "unknown"}:group:${index}`);
}

export function expressionReviewQueueItem(ruleGroup, index, selected) {
  const group = normalizeExpressionRuleGroup(ruleGroup, index);
  const key = expressionReviewRuleKey(group, index);
  const source = group?.source_name || group?.source_id || "未知来源";
  const preview = group.style_rule?.pattern || group.grammar_rule?.pattern || "尚无可复用结构";
  return `
    <button type="button" class="expression-review-queue-item ${selected ? "is-selected" : ""}" data-expression-review-rule="${escapeHtml(key)}" aria-pressed="${selected ? "true" : "false"}">
      <span class="expression-review-queue-top">
        <span class="expression-review-queue-kinds">
          ${group.style_rule ? `<span class="expression-kind-badge is-style">表达</span>` : ""}
          ${group.grammar_rule ? `<span class="expression-kind-badge is-grammar">语法</span>` : ""}
        </span>
        <small>${escapeHtml(group?.evidence_count || 0)} 条证据</small>
      </span>
      <b>${escapeHtml(group?.label || group?.situation || "未命名规则组")}</b>
      <span>${escapeHtml(preview)}</span>
      <small>${escapeHtml(source)}</small>
    </button>
  `;
}

export function renderExpressionReviewWorkspace() {
  const root = $("#expressionReviewWorkspace");
  const library = state.expressionLibrary;
  if (!root) return;
  const reviewCount = $("#expressionReviewCount");
  const allRules = expressionRuleGroups(library, true);
  if (reviewCount) reviewCount.textContent = String(allRules.length);
  if (!library) {
    if (!state.expressionLibraryLoading && state.expressionLibraryError) {
      root.innerHTML = `
        <div class="learning-detail-empty is-error" role="alert">
          <b>表达审核队列读取失败</b>
          <span>${escapeHtml(state.expressionLibraryError)}</span>
          <button type="button" data-expression-review-retry>重试</button>
        </div>
      `;
      root.querySelector("[data-expression-review-retry]")?.addEventListener("click", () => void renderExpressionLibrary(true));
    }
    return;
  }
  const source = ["all", "private", "group"].includes(state.expressionReviewSource) ? state.expressionReviewSource : "all";
  const type = ["all", "style", "grammar"].includes(state.expressionReviewType) ? state.expressionReviewType : "all";
  const query = String(state.expressionReviewQuery || "").trim().toLowerCase();
  const rules = allRules.filter((rule) => expressionLibraryItemMatches(rule, source, type, query));
  const keyedRules = rules.map((rule, index) => ({ rule, key: expressionReviewRuleKey(rule, index), index }));
  if (!keyedRules.some((item) => item.key === state.selectedExpressionReviewRuleId)) {
    state.selectedExpressionReviewRuleId = keyedRules[0]?.key || "";
  }
  const selectedItem = keyedRules.find((item) => item.key === state.selectedExpressionReviewRuleId) || keyedRules[0] || null;
  const activeFilterCount = Number(source !== "all") + Number(type !== "all") + Number(Boolean(query));
  root.innerHTML = `
    <header class="expression-review-hero">
      <div>
        <span>REVIEW QUEUE</span>
        <h3>表达审核</h3>
        <p>按同一情境整组核对可复用表达、句法习惯和支持片段；一次通过或拒绝整组，避免重复审核。</p>
      </div>
      <div class="expression-review-hero-actions">
        <span><b>${escapeHtml(allRules.length)}</b> 组待审核</span>
        ${allRules.length ? `<button type="button" class="danger-outline" data-expression-action="clear_all_pending">清空队列</button>` : ""}
      </div>
    </header>
    <div class="expression-review-toolbar">
      <div class="expression-library-filter-block">
        <span>来源</span>
        <div class="expression-library-segments" role="group" aria-label="筛选待审核规则来源">
          ${[["all", "全部"], ["private", "私聊"], ["group", "群聊"]].map(([value, label]) => `
            <button type="button" class="${source === value ? "is-active" : ""}" data-expression-review-source="${value}" aria-pressed="${source === value}">${label}</button>
          `).join("")}
        </div>
      </div>
      <div class="expression-library-filter-block">
        <span>类型</span>
        <div class="expression-library-segments" role="group" aria-label="筛选待审核规则类型">
          ${[["all", "全部"], ["style", "情境表达"], ["grammar", "语法习惯"]].map(([value, label]) => `
            <button type="button" class="${type === value ? "is-active" : ""}" data-expression-review-type="${value}" aria-pressed="${type === value}">${label}</button>
          `).join("")}
        </div>
      </div>
      <label class="expression-review-search">
        <span>搜索</span>
        <input type="search" value="${escapeHtml(state.expressionReviewQuery)}" data-expression-review-search placeholder="情境、表达或来源" />
      </label>
      ${activeFilterCount ? `<button type="button" class="expression-review-reset" data-expression-review-reset>清除筛选</button>` : ""}
    </div>
    ${allRules.length === 0 ? `
      <div class="expression-review-empty" role="status">
        <span aria-hidden="true">✓</span>
        <b>审核队列已清空</b>
        <p>新的情境表达与语法习惯会按同源情境合并后出现在这里。</p>
        <button type="button" data-open-expression-library>查看已启用表达</button>
      </div>
    ` : (rules.length === 0 ? `
      <div class="expression-review-empty" role="status">
        <span aria-hidden="true">⌕</span>
        <b>没有匹配的待审核规则</b>
        <p>当前队列还有 ${escapeHtml(allRules.length)} 个规则组，可以清除筛选后继续审核。</p>
        <button type="button" data-expression-review-reset>清除筛选</button>
      </div>
    ` : `
      <div class="expression-review-layout">
        <aside class="expression-review-queue" aria-label="待审核规则列表">
          <div class="expression-review-queue-head"><b>待审核</b><span>${escapeHtml(rules.length)}/${escapeHtml(allRules.length)}</span></div>
          <div class="expression-review-queue-list">
            ${keyedRules.map((item) => expressionReviewQueueItem(item.rule, item.index, item.key === state.selectedExpressionReviewRuleId)).join("")}
          </div>
        </aside>
        <section class="expression-review-detail" aria-live="polite">
          <div class="expression-review-detail-head">
            <div><span>当前规则组</span><b>${escapeHtml((selectedItem?.index || 0) + 1)} / ${escapeHtml(rules.length)}</b></div>
            <small>一次处理整组，完成后自动进入下一组</small>
          </div>
          <div class="expression-review-detail-body">
            ${selectedItem ? expressionRuleGroupItem(selectedItem.rule, true, true) : ""}
          </div>
        </section>
      </div>
    `)}
  `;
  root.querySelectorAll("[data-expression-review-source]").forEach((button) => {
    button.addEventListener("click", () => {
      state.expressionReviewSource = button.dataset.expressionReviewSource || "all";
      state.selectedExpressionReviewRuleId = "";
      renderExpressionReviewWorkspace();
    });
  });
  root.querySelectorAll("[data-expression-review-type]").forEach((button) => {
    button.addEventListener("click", () => {
      state.expressionReviewType = button.dataset.expressionReviewType || "all";
      state.selectedExpressionReviewRuleId = "";
      renderExpressionReviewWorkspace();
    });
  });
  root.querySelector("[data-expression-review-search]")?.addEventListener("input", (event) => {
    const selectionStart = event.currentTarget.selectionStart;
    state.expressionReviewQuery = event.currentTarget.value || "";
    state.selectedExpressionReviewRuleId = "";
    renderExpressionReviewWorkspace();
    const input = root.querySelector("[data-expression-review-search]");
    input?.focus();
    if (input && selectionStart !== null) input.setSelectionRange(selectionStart, selectionStart);
  });
  root.querySelectorAll("[data-expression-review-reset]").forEach((button) => {
    button.addEventListener("click", () => {
      state.expressionReviewSource = "all";
      state.expressionReviewType = "all";
      state.expressionReviewQuery = "";
      state.selectedExpressionReviewRuleId = "";
      renderExpressionReviewWorkspace();
    });
  });
  root.querySelectorAll("[data-expression-review-rule]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedExpressionReviewRuleId = button.dataset.expressionReviewRule || "";
      renderExpressionReviewWorkspace();
    });
    button.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...root.querySelectorAll("[data-expression-review-rule]")];
      const current = buttons.indexOf(button);
      const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, current + (event.key === "ArrowDown" ? 1 : -1)));
      const next = buttons[nextIndex];
      if (next) {
        state.selectedExpressionReviewRuleId = next.dataset.expressionReviewRule || "";
        renderExpressionReviewWorkspace();
        [...root.querySelectorAll("[data-expression-review-rule]")]
          .find((item) => item.dataset.expressionReviewRule === state.selectedExpressionReviewRuleId)
          ?.focus();
      }
    });
  });
  root.querySelector("[data-open-expression-library]")?.addEventListener("click", () => switchExpressionWorkspaceView("library", { focus: true }));
  bindExpressionLibraryActions(library, root);
}

export function expressionLibraryMoreButton(section, visible, total, label) {
  if (visible >= total) return "";
  return `
    <div class="expression-library-more">
      <span>已显示 ${escapeHtml(visible)}/${escapeHtml(total)}</span>
      <button type="button" data-expression-show-more="${escapeHtml(section)}">继续显示${escapeHtml(label)}</button>
    </div>
  `;
}

export function renderExpressionLibraryBlock(profile, options = {}) {
  const pending = Array.isArray(profile.pending_samples) ? profile.pending_samples : [];
  const pendingRuleGroups = expressionRuleGroups(profile, true);
  const samples = Array.isArray(profile.samples) ? profile.samples : [];
  const ruleGroups = expressionRuleGroups(profile, false);
  const visiblePendingRuleGroups = pendingRuleGroups.slice(0, expressionLibraryVisibleCount("pending"));
  const visibleRuleGroups = ruleGroups.slice(0, expressionLibraryVisibleCount("rules"));
  const observationLimit = expressionLibraryVisibleCount("observation");
  const visiblePendingSamples = pending.slice(0, observationLimit);
  const visibleSamples = samples.slice(0, Math.max(0, observationLimit - visiblePendingSamples.length));
  const visibleObservationCount = visiblePendingSamples.length + visibleSamples.length;
  const observationCount = samples.length;
  const pendingRuleCount = Math.max(pendingRuleGroups.length, Number(options.pendingRuleCount || 0));
  const totalItemCount = ruleGroups.length + pendingRuleGroups.length + samples.length + pending.length;
  const usage = profile?.usage && typeof profile.usage === "object" ? profile.usage : {};
  const lastInjection = usage?.last_injection && typeof usage.last_injection === "object" ? usage.last_injection : {};
  const visibleSignals = Array.isArray(lastInjection.visible_signals) ? lastInjection.visible_signals : [];
  return `
    <section class="detail-block expression-profile-block">
      ${lastInjection?.rule_id ? `
        <details class="expression-last-injection">
          <summary><b>最近使用：${escapeHtml(lastInjection.label || lastInjection.scene || "已学习场景")}</b><span>${escapeHtml(lastInjection.time || lastInjection.at || "刚刚")}</span></summary>
          <small>证据 ${escapeHtml(lastInjection.evidence_count || 0)} 条 · 置信度 ${escapeHtml(Math.round(Number(lastInjection.confidence || 0) * 100))}%${lastInjection.instruction ? ` · ${escapeHtml(lastInjection.instruction)}` : ""}${visibleSignals.length ? ` · 回复中检测到 ${escapeHtml(visibleSignals.join(" / "))}` : ""}</small>
        </details>
      ` : ""}
      ${profile.enabled === false ? `<div class="empty small">表达学习当前已关闭，已有资料仍可检视和清理。</div>` : ""}
      ${totalItemCount === 0 ? `
        <div class="expression-library-empty" role="status">
          <b>${options.hasAnyData ? "没有匹配结果" : (pendingRuleCount ? "暂无已启用表达" : "暂无表达学习资料")}</b>
          <span>${options.hasAnyData ? "可以放宽来源、类型或搜索条件。" : (pendingRuleCount ? "待审核规则不会混入表达库，请先完成审核。" : "产生足够的私聊或群聊片段后，归纳结果会先进入待审核区。")}</span>
          ${options.hasActiveFilters ? `<button type="button" data-expression-filter-reset>清除筛选</button>` : ""}
          ${pendingRuleCount && !options.hasActiveFilters ? `<button type="button" data-open-expression-review>前往审核队列</button>` : ""}
        </div>
      ` : ""}
      ${pendingRuleGroups.length ? `
        <div id="expressionPendingSection" class="expression-section-head">
          <div><h3>待审核规则组</h3><p>同源表达和语法会一起审核；支持片段通过前绝不会进入回复。</p></div>
          <span>${escapeHtml(pendingRuleGroups.length)} 组</span>
        </div>
        <div class="expression-rule-list">
          ${visiblePendingRuleGroups.map((group, index) => expressionPendingRuleItem(group, index)).join("")}
        </div>
        ${expressionLibraryMoreButton("pending", visiblePendingRuleGroups.length, pendingRuleGroups.length, "待审核规则组")}
      ` : ""}
      ${ruleGroups.length ? `
        <div id="expressionRuleGroupSection" class="expression-section-head">
          <div><h3>已启用规则</h3><p>先看核心用法；适用范围、反馈、证据和管理操作默认收起。</p></div>
          <div class="expression-section-actions">
            <span>${escapeHtml(ruleGroups.length)} 组</span>
            ${pendingRuleCount && options.mode === "library" ? `<button type="button" data-open-expression-review>审核 ${escapeHtml(pendingRuleCount)} 组</button>` : ""}
          </div>
        </div>
        <div class="expression-rule-list expression-rule-group-list">
          ${visibleRuleGroups.map((group) => expressionRuleGroupItem(group, false)).join("")}
        </div>
        ${expressionLibraryMoreButton("rules", visibleRuleGroups.length, ruleGroups.length, "规则组")}
      ` : ""}
      ${pending.length || observationCount ? `
        <details class="open-loop-archive expression-observation-archive" data-expression-sample-archive ${state.expressionLibraryArchiveOpen ? "open" : ""}>
          <summary>原始观察（不参与回复） ${escapeHtml(observationCount)}${pending.length ? ` · 待收录 ${escapeHtml(pending.length)}` : ""}</summary>
          <p class="muted small expression-observation-note"><b>这不是情境表达或语法习惯。</b>这里只保存来源、场景、句长和特征，供下一次模型归纳与人工排查；不会直接改变 Bot 的说法。</p>
          ${visiblePendingSamples.length ? `<div class="expression-observation-list">${visiblePendingSamples.map((item, index) => expressionSampleItem(item, index, true)).join("")}</div>` : ""}
          ${visibleSamples.length ? `<div class="expression-observation-list is-archived">${visibleSamples.map((item, index) => expressionSampleItem(item, index, false)).join("")}</div>` : ""}
          ${expressionLibraryMoreButton("observation", visibleObservationCount, pending.length + samples.length, "观察素材")}
        </details>
      ` : ""}
    </section>
  `;
}

export function expressionPendingRuleItem(ruleGroup, index = 0) {
  return expressionRuleGroupItem(ruleGroup, true, index === 0);
}

export function expressionRuleItem(rule, pending = false, evidenceOpen = false) {
  return expressionRuleGroupItem(normalizeExpressionRuleGroup(rule), pending, evidenceOpen);
}

export function expressionRuleComponent(rule, kind, groupSituation) {
  if (!rule) return "";
  const isGrammar = kind === "grammar";
  const componentSituation = String(rule?.situation || "").trim();
  return `
    <section class="expression-rule-component is-${kind}" aria-label="${isGrammar ? "语法习惯" : "情境表达"}">
      <div class="expression-rule-component-label">
        <span class="expression-kind-badge is-${kind}">${isGrammar ? "语法习惯" : "情境表达"}</span>
        <small>${isGrammar ? "控制句法，不复制内容" : "匹配情境后自然改写"}</small>
      </div>
      ${componentSituation && componentSituation !== String(groupSituation || "").trim() ? `<p class="expression-rule-component-scene">适用：${escapeHtml(componentSituation)}</p>` : ""}
      <div class="expression-rule-template">
        <span>${isGrammar ? "句法结构" : "可复用表达"}</span>
        <strong>${escapeHtml(rule?.pattern || "-")}</strong>
      </div>
      <p class="expression-rule-instruction">${escapeHtml(rule?.instruction || "")}</p>
    </section>
  `;
}

export function expressionRuleGroupItem(ruleGroup, pending = false, evidenceOpen = false) {
  const group = normalizeExpressionRuleGroup(ruleGroup);
  const needsReview = pending && group?.review_status === "needs_review";
  const examples = Array.isArray(group?.evidence_examples) ? group.evidence_examples.filter(Boolean) : [];
  const signals = Array.isArray(group?.signals) ? group.signals.filter(Boolean) : [];
  const familyId = group?.family_id || group?.id || "";
  const signalTags = signals.length ? `<div class="expression-rule-tags" aria-label="召回标签">${signals.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : "";
  const evidenceDetails = examples.length ? `
    <details class="expression-rule-evidence" ${evidenceOpen ? "open" : ""}>
      <summary>支持片段 ${escapeHtml(examples.length)} 条</summary>
      <div>${examples.map((item) => `<blockquote>${escapeHtml(item)}</blockquote>`).join("")}</div>
    </details>
  ` : "";
  const deleteAction = `<div class="expression-rule-actions"><button type="button" class="danger-outline" data-expression-action="delete_rule_group" data-expression-source-type="${escapeHtml(group?.source_type || "private")}" data-expression-source-id="${escapeHtml(group?.source_id || "")}" data-expression-rule-family-id="${escapeHtml(familyId)}">删除规则组</button></div>`;
  return `
    <article class="expression-rule-item expression-rule-group-item ${pending ? "is-pending" : "is-approved"} ${needsReview ? "needs-review" : ""}">
      <div class="expression-rule-head">
        <div class="expression-rule-title">
          ${pending ? `<span class="expression-rule-group-kinds">
            ${group.style_rule ? `<span class="expression-kind-badge is-style">表达</span>` : ""}
            ${group.grammar_rule ? `<span class="expression-kind-badge is-grammar">语法</span>` : ""}
          </span>` : ""}
          <b class="open-loop-text">${escapeHtml(group?.label || group?.situation || "未命名表达规则组")}</b>
        </div>
        <span class="badge ${needsReview ? "warn" : ""}">${escapeHtml(group?.evidence_count || 0)} 条证据${pending ? ` · ${needsReview ? "反馈后复审" : "待审核"}` : ""}</span>
      </div>
      ${expressionSourceBadge(group, !pending)}
      ${group?.review_reason ? `<p class="expression-rule-review-reason">${escapeHtml(group.review_reason)}</p>` : ""}
      <div class="expression-rule-components">
        ${expressionRuleComponent(group.style_rule, "style", group.situation)}
        ${expressionRuleComponent(group.grammar_rule, "grammar", group.situation)}
      </div>
      ${pending ? `
        ${signalTags}
        ${expressionRuleContext(group)}
        ${evidenceDetails}
        <div class="expression-rule-actions">
          <button type="button" data-expression-action="approve_rule_group" data-expression-source-type="${escapeHtml(group?.source_type || "private")}" data-expression-source-id="${escapeHtml(group?.source_id || "")}" data-expression-rule-family-id="${escapeHtml(familyId)}">${needsReview ? "重新通过整组" : "通过并启用整组"}</button>
          <button type="button" class="danger-outline" data-expression-action="reject_rule_group" data-expression-source-type="${escapeHtml(group?.source_type || "private")}" data-expression-source-id="${escapeHtml(group?.source_id || "")}" data-expression-rule-family-id="${escapeHtml(familyId)}">拒绝整组</button>
        </div>
      ` : `
        <details class="expression-rule-details">
          <summary><span>范围、证据与管理</span><small>${escapeHtml(signals.length)} 个标签 · ${escapeHtml(examples.length)} 条片段</small></summary>
          <div class="expression-rule-details-body">
            ${signalTags}
            ${expressionRuleContext(group)}
            ${evidenceDetails}
            ${deleteAction}
          </div>
        </details>
      `}
    </article>
  `;
}

export function expressionRuleContext(rule) {
  const labels = {
    private: "私聊",
    group: "群聊",
    proactive: "主动",
    qzone: "空间",
    tts: "语音",
    any: "不限",
    stranger: "陌生",
    familiar: "熟悉",
    close: "亲近",
    normal: "普通",
    positive: "轻松",
    low: "安抚",
    guarded: "边界",
    acknowledgement: "确认",
    question: "提问",
    request: "请求",
    help: "求助",
    comfort: "安抚",
    play: "玩笑",
    tease: "逗趣",
    intimacy: "亲近",
    boundary: "边界",
    emotion: "情绪",
    casual: "闲聊",
  };
  const chips = [];
  (Array.isArray(rule?.channels) ? rule.channels : []).forEach((item) => chips.push(labels[item] || item));
  (Array.isArray(rule?.relationship_stages) ? rule.relationship_stages : []).forEach((item) => {
    if (item !== "any") chips.push(labels[item] || item);
  });
  (Array.isArray(rule?.emotion_gates) ? rule.emotion_gates : []).forEach((item) => {
    if (item !== "any") chips.push(labels[item] || item);
  });
  if (rule?.intent && rule.intent !== "any") chips.push(labels[rule.intent] || rule.intent);
  if (Number(rule?.use_count) > 0) chips.push(`使用 ${Number(rule.use_count)} 次`);
  const positive = Number(rule?.positive_feedback) || 0;
  const negative = Number(rule?.negative_feedback) || 0;
  return `
    <div class="expression-rule-context">
      ${chips.length ? `<div class="expression-rule-chips">${Array.from(new Set(chips)).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
      <div class="expression-rule-feedback" aria-label="规则反馈">
        <span class="is-positive">正向 ${escapeHtml(positive)}</span>
        <span class="${negative ? "is-negative" : ""}">负向 ${escapeHtml(negative)}</span>
        ${rule?.last_used_time ? `<span>最近使用 ${escapeHtml(rule.last_used_time)}</span>` : ""}
        ${rule?.persona_conflict ? `<strong>与人格/事实边界冲突，不会自动使用</strong>` : ""}
      </div>
      ${rule?.avoid ? `<details class="expression-rule-guard"><summary>适用边界</summary><p>${escapeHtml(rule.avoid)}</p></details>` : ""}
    </div>
  `;
}

export function expressionSourceBadge(item, compact = false) {
  const kind = item?.source_kind_label || (item?.source_type === "group" ? "群聊" : "私聊");
  const name = item?.source_name || item?.source_id || "未知来源";
  const id = item?.source_id || "";
  if (compact) {
    return `
      <div class="expression-source-line is-compact" title="${escapeHtml(id || name)}">
        <span>${escapeHtml(kind)}</span>
        <b>${escapeHtml(name)}</b>
        <small>${item?.source_active ? "当前来源" : "未参与学习"}</small>
      </div>
    `;
  }
  return `
    <div class="expression-source-line">
      <span class="badge ${item?.source_type === "group" ? "" : "ok"}">${escapeHtml(kind)}</span>
      <b>${escapeHtml(name)}</b>
      ${id ? `<span class="mono">${escapeHtml(id)}</span>` : ""}
      <span class="badge ${item?.source_active ? "ok" : "off"}">${item?.source_active ? "当前来源" : "未参与学习"}</span>
    </div>
  `;
}

export function expressionSampleItem(item, index, pending) {
  const text = item?.text || item?.phrase || item?.ending || "";
  const featureText = Array.isArray(item?.features) ? item.features.filter(Boolean).join(" / ") : "";
  const sceneText = item?.scene || "未分类场景";
  const displayText = text || featureText || "尚无可归纳特征";
  const sourceIndex = Number.isInteger(Number(item?.index)) ? Number(item.index) : index;
  const meta = [
    item?.time || "",
    item?.length ? `${item.length} 字` : "",
    item?.punctuation ? `标点 ${item.punctuation}` : "",
    item?.ending ? `句尾 ${item.ending}` : "",
    Number(item?.evidence_count) > 0 ? `${item.evidence_count} 条证据` : "",
  ].filter(Boolean).join("｜");
  const patternStatus = item?.source_type === "group"
    ? `<span class="badge ${item?.observation_status === "supported" ? "ok" : ""}">${item?.observation_status === "supported" ? "重复证据" : "单次观察"}</span>`
    : "";
  return `
    <article class="expression-observation-item ${pending ? "is-pending" : "is-archived"}">
      <div class="expression-observation-main">
        <div class="expression-observation-title">
          <span class="badge ${pending ? "warn" : "off"}">${pending ? "待收录观察" : "未归纳观察"}</span>
          <b>${escapeHtml(sceneText)}</b>
          ${patternStatus}
        </div>
        <p><span>观察特征</span>${escapeHtml(displayText)}</p>
        <span class="expression-observation-meta">${escapeHtml(meta || `#${index + 1}`)}</span>
        ${expressionSourceBadge(item)}
      </div>
      <div class="expression-observation-actions">
        ${pending ? `<button type="button" data-expression-action="approve" data-expression-source-type="${escapeHtml(item?.source_type || "private")}" data-expression-source-id="${escapeHtml(item?.source_id || "")}" data-expression-sample-id="${escapeHtml(item?.id || "")}" data-expression-sample-index="${escapeHtml(sourceIndex)}">保留素材</button>` : ""}
        <button type="button" class="danger-outline" data-expression-action="${pending ? "reject" : "delete_sample"}" data-expression-source-type="${escapeHtml(item?.source_type || "private")}" data-expression-source-id="${escapeHtml(item?.source_id || "")}" data-expression-sample-id="${escapeHtml(item?.id || "")}" data-expression-sample-index="${escapeHtml(sourceIndex)}">删除</button>
      </div>
    </article>
  `;
}

export function bindExpressionLibraryActions(library, root) {
  if (!root) return;
  root.querySelector("[data-expression-sample-archive]")?.addEventListener("toggle", (event) => {
    state.expressionLibraryArchiveOpen = Boolean(event.currentTarget.open);
  });
  root.querySelectorAll("[data-expression-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.expressionAction || "";
      const sourceType = button.dataset.expressionSourceType || "";
      const sourceId = button.dataset.expressionSourceId || "";
      state.expressionLibraryArchiveOpen = Boolean(root.querySelector("[data-expression-sample-archive]")?.open);
      if (action === "clear_all_pending" && !requireSecondClick(button, "expression-clear-all", "再次点击清空全部来源的待审核规则和待整理素材", "再次点击清空")) return;
      if (action === "delete_sample" && !requireSecondClick(button, `expression-delete:${sourceType}:${sourceId}:${button.dataset.expressionSampleId || button.dataset.expressionSampleIndex || ""}`, "再次点击删除这条观察素材", "再次点击删除")) return;
      if (action === "delete_rule" && !requireSecondClick(button, `expression-rule-delete:${sourceType}:${sourceId}:${button.dataset.expressionRuleId || ""}`, "再次点击删除这条表达规则", "再次点击删除")) return;
      if (action === "delete_rule_group" && !requireSecondClick(button, `expression-rule-group-delete:${sourceType}:${sourceId}:${button.dataset.expressionRuleFamilyId || ""}`, "再次点击删除整个规则组", "再次点击删除整组")) return;
      const updatedLibrary = await runAction(
        () => postJson("/expression-library/update", {
          source_type: sourceType,
          source_id: sourceId,
          expression_action: action,
          sample_id: button.dataset.expressionSampleId || "",
          rule_id: button.dataset.expressionRuleId || "",
          rule_family_id: button.dataset.expressionRuleFamilyId || "",
          sample_index: Number(button.dataset.expressionSampleIndex || -1),
        }),
        "",
        button,
        { reload: false },
      );
      if (!updatedLibrary) return;
      state.expressionLibrary = updatedLibrary;
      try {
        const overview = await fetchJson("/overview");
        applyOverviewData(overview);
      } catch (error) {
        console.warn("[PrivateCompanionPage] 表达画像操作后刷新总览失败", error);
      }
      renderExpressionScopeManager();
      renderExpressionLibraryView();
    });
  });
}

export function bindUserActions(detail) {
  const refreshSelectedUserDetail = async () => {
    if (state.selectedUserId === detail.user_id) {
      await renderUserDetail(true);
    }
  };
  document.querySelector("[data-private-learning-clear]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!requireSecondClick(button, `private-learning-clear:${detail.user_id}`, "再次点击清空该用户的行为习惯", "再次点击清空")) return;
    const updated = await runAction(
      () => postJson("/user/update", { user_id: detail.user_id, clear_behavior_habits: true }),
      "已清空该用户的行为习惯",
      button,
      { reload: false },
    );
    if (!updated) return;
    await refreshSelectedUserDetail();
    try {
      const overview = await fetchJson("/overview");
      applyOverviewData(overview);
    } catch (error) {
      console.warn("[PrivateCompanionPage] 清空行为习惯后刷新总览失败", error);
    }
  });
  $("#userEditForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const selectedRole = form.get("relationship_role");
    const updated = await runAction(() => postJson("/user/update", {
      user_id: detail.user_id,
      nickname: form.get("nickname"),
      style: form.get("style"),
      relationship_role: selectedRole,
      proactive_daily_limit: Number(form.get("proactive_daily_limit") || -1),
    }), "已保存私聊对象", event.submitter);
    if (updated) await refreshSelectedUserDetail();
  });
  document.querySelectorAll("[data-user-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.userAction;
      const body = { user_id: detail.user_id };
      if (action === "toggle") body.enabled = !detail.enabled;
      if (action === "reset_daily") body.reset_daily = true;
      if (action === "clear_schedule") body.clear_schedule = true;
      if (action === "clear_emotion_state") {
        if (!requireSecondClick(button, `user-clear-emotion:${detail.user_id}`, "再次点击重置该用户的情绪状态", "再次点击重置")) return;
        body.clear_emotion_state = true;
      }
      if (action === "delete") {
        if (!requireSecondClick(button, `user-delete:${detail.user_id}`, "再次点击删除该私聊用户、目标名单和相关映射", "再次点击删除")) return;
        await runAction(async () => {
          const result = await postJson("/user/delete", body);
          if (state.selectedUserId === detail.user_id) state.selectedUserId = "";
          return result;
        }, "", button);
        return;
      }
      await runAction(() => postJson("/user/update", body), "已更新私聊对象", button);
      await refreshSelectedUserDetail();
    });
  });
  document.querySelectorAll("[data-open-loop-remove]").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = String(button.dataset.openLoopRemove || "").trim();
      if (!text) return;
      if (!requireSecondClick(button, `open-loop:${detail.user_id}:${text}`, "再次点击删除这条未完话头", "再次点击删除")) return;
      await runAction(
        () => postJson("/user/update", { user_id: detail.user_id, remove_open_loop_text: text }),
        "",
        button,
      );
      await refreshSelectedUserDetail();
    });
  });
  document.querySelectorAll("[data-open-loop-clear]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!requireSecondClick(button, `open-loop-clear:${detail.user_id}`, "再次点击清空该用户的未完话头", "再次点击清空")) return;
      await runAction(
        () => postJson("/user/update", { user_id: detail.user_id, clear_open_loops: true }),
        "",
        button,
      );
      await refreshSelectedUserDetail();
    });
  });
}

export function renderGroups(refreshDetail = true) {
  const keyword = ($("#groupFilter").value || "").trim().toLowerCase();
  const rows = state.groups.filter((group) => {
    const haystack = [
      group.group_id,
      group.name,
      group.group_name,
      group.display_name,
      group.atmosphere?.mood,
      group.atmosphere?.last_summary,
    ].join(" ").toLowerCase();
    const status = $("#groupStatusFilter").value;
    return (!keyword || haystack.includes(keyword)) && (status === "all" ||
      (status === "blocked" ? group.allowed_by_mode === false : Boolean(group.enabled) === (status === "enabled")));
  });
  if (!state.groups.some(group => String(group.group_id) === String(state.selectedGroupId))) {
    state.selectedGroupId = state.groups[0]?.group_id || "";
  }
  const outside = state.selectedGroupId && !rows.some(group => String(group.group_id) === String(state.selectedGroupId));
  $("#groupListCoverage").textContent = `本次载入 ${state.groups.length} 个群，符合筛选 ${rows.length} 个。最多返回300个近期群聊。${outside ? "当前详情保留在筛选外。" : ""}`;
  const count = $("#groupListCount");
  if (count) {
    count.textContent = `${rows.length}/${state.groups.length} 个群`;
  }
  $("#groupRows").innerHTML = rows.length
    ? rows.map((group) => `
      <button type="button" data-group-id="${escapeHtml(group.group_id)}" class="group-card ${String(group.group_id) === String(state.selectedGroupId) ? "is-selected" : ""} ${group.enabled ? "" : "is-off"} ${group.allowed_by_mode ? "" : "is-blocked"}">
        <header>
          <span class="group-card-title">
            <b>${escapeHtml(groupDisplayName(group))}</b>
            <small>${escapeHtml(groupIdText(group))}</small>
          </span>
          <span class="badge ${group.enabled ? "" : "off"}">${escapeHtml(group.enabled ? "本群已启用" : "本群已停用")}</span>
        </header>
        <p class="group-card-summary">${escapeHtml(group.atmosphere?.last_summary || group.atmosphere?.mood || "暂无群聊氛围摘要")}</p>
        <div class="group-card-metrics">
          <span>消息 <b>${escapeHtml(group.message_count || 0)}</b></span>
          <span>群友 <b>${escapeHtml(group.member_count || 0)}</b></span>
          <span>话题 <b>${escapeHtml(group.topic_count || 0)}</b></span>
        </div>
        ${groupWakeupCardLine(group)}
        <footer>
          <span class="${group.allowed_by_mode ? "" : "warn-text"}">${escapeHtml(group.allowed_by_mode ? "名单允许" : "名单拦截")}</span>
          <span>插话 ${escapeHtml(group.interject_today || 0)}</span>
          <span>${escapeHtml(group.last_seen || "暂无活跃")}</span>
        </footer>
      </button>
    `).join("")
    : `<div class="empty small">暂无群聊观测数据</div>`;
  document.querySelectorAll("#groupRows [data-group-id]").forEach((row) => {
    row.addEventListener("click", async () => {
      if (String(state.selectedGroupId) !== row.dataset.groupId) state.groupDetailSection = "status";
      state.selectedGroupId = row.dataset.groupId;
      renderGroups(false);
      await renderGroupDetail(true);
    });
  });
  if (refreshDetail) void renderGroupDetail();
}

export function groupDisplayName(group) {
  const id = String(group?.group_id || "").trim();
  const name = String(group?.display_name || group?.name || group?.group_name || "").trim();
  if (name && name !== id && name !== `群 ${id}`) return name;
  return "未命名群聊";
}

export function groupIdText(group) {
  const id = String(group?.group_id || "").trim();
  return id ? `群号 ${id}` : "群号未知";
}

export function groupWakeupCardLine(group) {
  const wake = group.last_group_wakeup || {};
  const fatigue = group.wakeup_fatigue || {};
  if (!wake.word && !group.wakeup_log_count && !fatigue.value) return "";
  const wakeText = wake.word
    ? `${wake.strength_label || "唤醒"}｜${wake.word}｜${wake.time || ""}`
    : "暂无命中";
  const fatigueText = fatigue.label ? `疲劳 ${fatigue.label}${fatigue.value ? ` ${fatigue.value}/${fatigue.limit || "-"}` : ""}` : "";
  return `
    <div class="group-card-wakeup">
      <span>${escapeHtml(wakeText)}</span>
      <span>${escapeHtml(fatigueText)}</span>
    </div>
  `;
}

export async function renderGroupDetail(forceFetch = false) {
  const box = $("#groupDetail"), id = String(state.selectedGroupId || "");
  const serial = ++state.groupDetailSerial;
  const current = () => serial === state.groupDetailSerial && String(state.selectedGroupId || "") === id;
  box.dataset.detailGroupId = id;
  if (!id) {box.innerHTML = '<p class="muted">选择一个群，查看参与状态、记录与维护入口。</p>'; return;}
  box.innerHTML = `<p role="status" class="muted">正在读取群 ${escapeHtml(id)}…</p>`;
  let detail = state.groups.find(group => String(group.group_id) === id);
  if (forceFetch || !detail?.formatted) {
    try {
      detail = await fetchJson(`/group?group_id=${encodeURIComponent(id)}`);
      if (!current()) return;
      if (String(detail?.group_id || "") !== id) throw new Error("返回群不匹配，请重新读取");
    } catch (error) {
      if (!current()) return;
      box.innerHTML = `<p role="alert" class="muted">详情读取失败：${escapeHtml(error.message)}</p><button type="button" data-group-retry>重新读取</button>`;
      box.querySelector('[data-group-retry]').addEventListener('click', () => {if (current()) void renderGroupDetail(true);});
      return;
    }
  }
  if (!current()) return;
  const globalGroup = state.overview?.group || {};
  const globalLabel = globalGroup.enabled === true ? "已开启" : globalGroup.enabled === false ? "已关闭" : "未读取";
  box.innerHTML = `
    <header class="group-detail-hero">
      <div class="group-detail-title"><span class="eyebrow">当前群聊</span><h2>${escapeHtml(groupDisplayName(detail))}</h2>
        <div class="group-detail-status"><span>${escapeHtml(groupIdText(detail))}</span><span>最近 ${escapeHtml(detail.last_seen || "暂无")}</span></div>
      </div>
    </header>
    <div class="aw-group-tabs" role="group" aria-label="群聊资料分区">
      <button type="button" data-group-section="status">参与状态</button><button type="button" data-group-section="records">群聊记录</button>
      <button type="button" data-group-section="slang">黑话维护</button><button type="button" data-group-section="maintenance">管理操作</button>
    </div>
    <section class="aw-group-section" data-group-panel="status">
      <div class="aw-group-gates">
        <article><small>群陪伴总开关</small><b>${globalLabel}</b></article>
        <article><small>本群设置</small><b>${detail.enabled ? "已启用" : "已停用"}</b></article>
        <article><small>当前名单</small><b>${detail.allowed_by_mode ? "允许" : "拦截"}</b></article>
      </div>
      <p>以上是当前配置状态，启用本群仍须满足总开关、名单和原有唤醒/频率规则；不表示已经发送消息。</p>
      <div class="aw-group-actions"><button type="button" data-group-action="toggle">${detail.enabled ? "停用本群" : "启用本群"}</button><button type="button" data-group-access>管理群聊名单</button></div>
      <div class="detail-grid group-detail-grid">
        ${groupDetailPanel("近期氛围", groupStateOverview(detail), {wide:true,className:"group-state-panel"})}
        ${groupDetailPanel("插话反馈", groupInterjectionFeedbackView(detail), {wide:true})}
      </div>
    </section>
    <section class="aw-group-section" data-group-panel="records" hidden>
      <p>当前返回的近期观测和整理资料；消息最多30条、片段最多12条，不是全部聊天历史。</p>
      <div class="detail-grid group-detail-grid">
        ${groupDetailPanel("活跃群友", groupActiveMembersView(detail.members || {}), {wide:true})}
        ${groupDetailPanel("消息活跃", groupMessageActivityView(detail.recent_messages || []), {wide:true})}
        ${groupDetailPanel("群聊片段", groupEpisodesView(detail.group_episodes || []), {wide:true,collapsed:true,meta:`${(detail.group_episodes || []).length} 条`})}
        ${groupDetailPanel("唤醒记录", groupWakeupPanel(detail), {wide:true,collapsed:true,meta:`${detail.wakeup_log_count || (detail.group_wakeup_logs || []).length} 条`})}
        ${groupDetailPanel("话题线", groupTopicThreadsView(detail.topic_threads || []), {wide:true,collapsed:true,meta:`${(detail.topic_threads || []).length} 条`})}
        ${groupDetailPanel("关系网", relationshipGraphView(detail.relationship_edges || {}, detail.members || {}), {wide:true,collapsed:true,meta:`${Object.keys(detail.relationship_edges || {}).length} 条关系`})}
      </div>
    </section>
    <section class="aw-group-section" data-group-panel="slang" hidden>
      <p>保留本群释义、来源与证据，保存后用于本群的表达理解。分区和列表筛选保留当前输入；换群、主动刷新或关闭页面会丢弃未保存内容。</p>
      ${groupSlangManagerView(detail.slang_items || [])}
    </section>
    <section class="aw-group-section" data-group-panel="maintenance" hidden>
      <article class="aw-group-maintenance"><h3>重置插话状态</h3><p>清除本群插话时间、当日计数、最近插话及反馈。后续机会仍按原规则判断。</p><button type="button" data-group-action="reset_interjection">重置插话</button></article>
      <article class="aw-group-maintenance"><h3>清空观测资料</h3><p>清除群友、消息、黑话、话题、片段、关系和唤醒等观测数据；保留本群启停状态，不修改群聊名单。</p><button type="button" class="danger" data-group-action="clear_observation">清空观测</button></article>
      <article class="aw-group-maintenance"><h3>删除群聊记录</h3><p>移除群观测、白名单/黑名单ID和表达学习范围。不是退群或永久屏蔽；后续接收仍按名单和参与规则处理。</p><button type="button" class="danger" data-group-action="delete">删除群聊</button></article>
      <p>维护操作不会撤回已发消息，也不能取消已经开始的外部调用。</p>
    </section>`;
  const selectSection = name => {
    state.groupDetailSection = ['status','records','slang','maintenance'].includes(name) ? name : 'status';
    box.querySelectorAll('[data-group-panel]').forEach(panel => panel.hidden = panel.dataset.groupPanel !== state.groupDetailSection);
    box.querySelectorAll('[data-group-section]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.groupSection === state.groupDetailSection)));
  };
  box.querySelectorAll('[data-group-section]').forEach(button => button.addEventListener('click', () => selectSection(button.dataset.groupSection)));
  box.querySelector('[data-group-access]').addEventListener('click', () => {
    switchTab('config');
    const form = $('#accessForm');
    for (let element = form; element; element = element.parentElement) if (element.tagName === 'DETAILS') element.open = true;
    form.scrollIntoView({block:'center'});form.querySelector('button[type=submit]')?.focus({preventScroll:true});
  });
  selectSection(state.groupDetailSection);
  bindGroupActions(detail);
}

export function groupDetailPanel(title, content, options = {}) {
  const className = ["detail-block", options.wide ? "wide" : "", options.className || "", options.collapsed ? "group-collapsible" : ""]
    .filter(Boolean)
    .join(" ");
  if (options.collapsed) {
    return `
      <details class="${escapeHtml(className)}">
        <summary><h2>${escapeHtml(title)}</h2>${options.meta ? `<span>${escapeHtml(options.meta)}</span>` : ""}</summary>
        <div class="detail-block-body">${content}</div>
      </details>
    `;
  }
  return `<section class="${escapeHtml(className)}"><h2>${escapeHtml(title)}</h2>${content}</section>`;
}

export function groupStateOverview(detail) {
  const atmosphere = detail.atmosphere || {};
  const chips = [
    ["气氛", atmosphere.mood || "暂无", ""],
    ["节奏", atmosphere.heat || atmosphere.pace || "暂无", ""],
    ["最近", detail.last_seen || "暂无", ""],
  ];
  const summary = atmosphere.last_summary || "这个群还没有形成稳定的氛围摘要。";
  return `
    <div class="group-state-overview">
      <div class="group-state-chips">
        ${chips.map(([label, value, tone]) => `<span class="${escapeHtml(tone || "")}"><small>${escapeHtml(label)}</small><b>${escapeHtml(value)}</b></span>`).join("")}
      </div>
      <p>${escapeHtml(summary)}</p>
      <div class="group-state-metrics">
        ${groupMetricTile("累计消息", detail.message_count || 0)}
        ${groupMetricTile("群友", detail.member_count || Object.keys(detail.members || {}).length)}
        ${groupMetricTile("已识别", detail.recognized_member_count || 0)}
        ${groupMetricTile("话题线", detail.topic_count || (detail.topic_threads || []).length)}
        ${groupMetricTile("黑话", detail.slang_count || (detail.slang_terms || []).length)}
      </div>
    </div>
  `;
}

export function groupMetricTile(label, value) {
  return `<article><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></article>`;
}

export function groupSlangTermsView(items) {
  const terms = (Array.isArray(items) ? items : [])
    .map((item) => ({
      text: slangTermText(item),
      count: Number(item?.count || 0),
    }))
    .filter((item) => item.text)
    .sort((a, b) => b.count - a.count)
    .slice(0, 18);
  if (!terms.length) return `<div class="empty small">暂无常用词</div>`;
  const max = Math.max(1, ...terms.map((item) => item.count));
  return `
    <div class="group-chip-cloud">
      ${terms.map((item) => `<span style="--weight:${Math.max(0.72, Math.min(1.12, 0.72 + item.count / max * 0.4)).toFixed(2)}">${escapeHtml(item.text)}${item.count ? `<small>${escapeHtml(item.count)}</small>` : ""}</span>`).join("")}
    </div>
  `;
}

export function groupSlangManagerView(items) {
  const rows = Array.isArray(items) ? items : [];
  const counts = rows.reduce((acc, item) => {
    const status = item.status || "pending";
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  const summary = rows.length
    ? `${rows.length} 个候选，${counts.injectable || 0} 个会注入，${counts.pending || 0} 个待释义`
    : "暂无已学习黑话";
  return `
    <div class="group-slang-manager">
      <header>
        <div>
          <p>${escapeHtml(summary)}</p>
          <small>这里展示群内学到的词、模型释义、联网参考和是否会进入提示词。</small>
        </div>
        <details class="group-slang-add">
          <summary>手动补一条</summary>
          <div class="group-slang-editor" data-slang-new>
            ${groupSlangInput("term", "词", "")}
            ${groupSlangInput("meaning", "含义", "")}
            ${groupSlangInput("usage", "用法", "")}
            ${groupSlangInput("type", "类型", "")}
            ${groupSlangInput("confidence", "置信度", "0.85", "number")}
            <button type="button" data-slang-add>保存</button>
          </div>
        </details>
      </header>
      ${rows.length ? `<div class="group-slang-list">${rows.map(groupSlangRow).join("")}</div>` : `<div class="empty small">还没有学到群内黑话。开启群黑话学习后，常见梗、简称和特殊称呼会出现在这里。</div>`}
    </div>
  `;
}

export function groupSlangRow(item) {
  const sourceLabel = {
    llm_slang: "模型释义",
    explicit_correction: "群内纠正",
    manual: "手动校正",
  }[item.source] || item.source || "未释义";
  const statusClass = `status-${item.status || "pending"}`;
  const webMatch = Number(item.web_match || 0);
  return `
    <details class="group-slang-row ${escapeHtml(statusClass)}" data-slang-term="${escapeHtml(item.term || "")}">
      <summary class="group-slang-main">
        <div>
          <b>${escapeHtml(item.term || "-")}</b>
          <span>${escapeHtml(item.status_label || "待确认")}</span>
        </div>
        <p>${escapeHtml(item.meaning || "还没有稳定释义")}</p>
        <footer>
          <span>出现 ${escapeHtml(item.count || 0)} 次</span>
          <span>最近 ${escapeHtml(item.last_seen || "暂无")}</span>
          <span>${escapeHtml(sourceLabel)}</span>
          ${item.type ? `<span>${escapeHtml(item.type)}</span>` : ""}
          <span>置信度 ${escapeHtml(Math.round(Number(item.confidence || 0) * 100))}%</span>
          ${webMatch ? `<span>联网匹配 ${escapeHtml(Math.round(webMatch * 100))}%</span>` : ""}
        </footer>
      </summary>
      <div class="group-slang-body">
        ${item.usage || item.evidence || item.web_evidence || item.not_owner ? `
          <div class="group-slang-notes">
            ${item.usage ? `<p><b>用法</b>${escapeHtml(item.usage)}</p>` : ""}
            ${item.not_owner ? `<p><b>不是</b>${escapeHtml(item.not_owner)}</p>` : ""}
            ${item.evidence ? `<p><b>群内证据</b>${escapeHtml(item.evidence)}</p>` : ""}
            ${item.web_evidence ? `<p><b>联网参考</b>${escapeHtml(item.web_evidence)}</p>` : ""}
          </div>
        ` : `<div class="empty small">暂无更多证据或用法说明</div>`}
        <details class="group-slang-edit">
          <summary>编辑</summary>
          <div class="group-slang-editor">
            ${groupSlangInput("meaning", "含义", item.meaning || "")}
            ${groupSlangInput("usage", "用法", item.usage || "")}
            ${groupSlangInput("type", "类型", item.type || "")}
            ${groupSlangInput("not_owner", "不是谁", item.not_owner || "")}
            ${groupSlangInput("evidence", "群内证据", item.evidence || "")}
            ${groupSlangInput("web_evidence", "联网参考", item.web_evidence || "")}
            ${groupSlangInput("confidence", "置信度", item.confidence || 0.85, "number")}
            ${groupSlangInput("web_match", "联网匹配", item.web_match || 0, "number")}
            <div class="group-slang-actions">
              <button type="button" data-slang-save>保存校正</button>
              <button type="button" class="danger-outline" data-slang-delete>删除</button>
            </div>
          </div>
        </details>
      </div>
    </details>
  `;
}

export function groupSlangInput(name, label, value, type = "text") {
  const multiline = ["meaning", "usage", "not_owner", "evidence", "web_evidence"].includes(name);
  if (multiline) {
    return `<label>${escapeHtml(label)} <textarea data-slang-field="${escapeHtml(name)}" rows="2">${escapeHtml(value ?? "")}</textarea></label>`;
  }
  const attrs = type === "number" ? ` type="number" min="0" max="1" step="0.01"` : "";
  return `<label>${escapeHtml(label)} <input data-slang-field="${escapeHtml(name)}"${attrs} value="${escapeHtml(value ?? "")}" /></label>`;
}

export function groupSlangPayloadFromEditor(editor, groupId, term = "") {
  const payload = { group_id: groupId, term };
  editor.querySelectorAll("[data-slang-field]").forEach((input) => {
    const key = input.dataset.slangField;
    if (!key) return;
    payload[key] = input.value;
  });
  if (!payload.term) payload.term = "";
  return payload;
}

export function groupActiveMembersView(members) {
  const items = Object.entries(members || {})
    .map(([id, raw]) => {
      const item = raw && typeof raw === "object" ? raw : {};
      return {
        id,
        name: item.identity_name || item.display_name || item.nickname || item.name || item.card || id,
        count: Number(item.count || item.message_count || 0),
        known: Boolean(item.identity_known),
        phrase: Array.isArray(item.recent_phrases) ? item.recent_phrases[0] : "",
      };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);
  if (!items.length) return `<div class="empty small">暂无活跃群友</div>`;
  return `
    <div class="group-member-list">
      ${items.map((item) => `
        <article>
          <div class="relation-avatar">${escapeHtml(shortName(item.name, 2))}</div>
          <div>
            <b>${escapeHtml(item.name)}</b>
            <small>${escapeHtml(item.known ? "已识别" : item.id)}${item.phrase ? ` · ${escapeHtml(item.phrase)}` : ""}</small>
          </div>
          <span>${escapeHtml(item.count)}</span>
        </article>
      `).join("")}
    </div>
  `;
}

export function groupInterjectionFeedbackView(detail) {
  const feedback = detail.interjection_feedback || {};
  const last = detail.last_bot_interjection || {};
  const replies = Number(feedback.replies_after || 0);
  const positive = Number(feedback.positive || 0);
  const negative = Number(feedback.negative || 0);
  const total = Math.max(1, positive + negative);
  return `
    <div class="group-feedback-panel">
      <div class="group-feedback-score">
        <article><span>后续回复</span><b>${escapeHtml(replies)}</b></article>
        <article><span>正向</span><b>${escapeHtml(positive)}</b></article>
        <article><span>负向</span><b>${escapeHtml(negative)}</b></article>
      </div>
      <div class="group-feedback-meter" title="正向 / 负向">
        <i style="width:${Math.round((positive / total) * 100)}%"></i>
      </div>
      ${cleanInterjectionText(last.text) ? `<p><span>上次插话</span>${escapeHtml(cleanInterjectionText(last.text))}</p>` : `<p class="muted">暂无最近插话内容</p>`}
      ${last.reason ? `<p><span>插话原因</span>${escapeHtml(last.reason)}</p>` : ""}
    </div>
  `;
}

export function groupEpisodesView(episodes) {
  const items = (Array.isArray(episodes) ? episodes : []).slice(0, 5);
  if (!items.length) return `<div class="empty small">暂无群聊片段</div>`;
  return `
    <div class="group-episode-list">
      ${items.map((item, index) => {
        const title = item.title || `片段 ${index + 1}`;
        const summary = item.summary || item.content || JSON.stringify(item);
        return `<article><b>${escapeHtml(title)}</b><p>${escapeHtml(summary)}</p></article>`;
      }).join("")}
    </div>
  `;
}

export function groupWakeupPanel(detail) {
  const logs = Array.isArray(detail.group_wakeup_logs) ? detail.group_wakeup_logs : [];
  const fatigue = detail.wakeup_fatigue || {};
  const high = fatigue.high_intensity || {};
  const ratio = Math.max(0, Math.min(100, Number(fatigue.ratio || 0) * 100));
  const last = detail.last_group_wakeup || {};
  const highTitle = high.active
    ? high.merge_active
      ? "合并等待中"
      : "仅降载中"
    : "未触发";
  const highMeta = high.active
    ? [
        `近期 ${Number(high.recent_wakeups || 0)}/${Number(high.threshold || 0)}`,
        high.merge_recent_floor ? `合并门槛 ${Number(high.merge_recent_floor)}` : "",
        high.reason ? `原因 ${high.reason}` : "",
        high.remaining_seconds ? `剩余 ${Number(high.remaining_seconds).toFixed(0)}s` : "",
      ].filter(Boolean).join(" · ")
    : "只有近期连续叫到 Bot 时才会合并等待";
  return `
    <div class="group-wakeup-overview">
      <article>
        <span>最近唤醒</span>
        <b>${escapeHtml(last.word || "暂无")}</b>
        <small>${escapeHtml([last.strength_label, last.sender_name, last.time].filter(Boolean).join(" · ") || "还没有记录")}</small>
        ${last.reason_detail || last.reason_label ? `<small>${escapeHtml(last.reason_detail || last.reason_label)}</small>` : ""}
      </article>
      <article>
        <span>唤醒疲劳</span>
        <b>${escapeHtml(fatigue.label || "无")}</b>
        <div class="fatigue-meter"><i style="width:${ratio}%"></i></div>
        <small>${escapeHtml(`${fatigue.value || 0}/${fatigue.limit || "-"} · ${fatigue.updated || "暂无"}`)}</small>
      </article>
      <article>
        <span>高强度状态</span>
        <b>${escapeHtml(highTitle)}</b>
        <small>${escapeHtml(highMeta)}</small>
      </article>
      <article>
        <span>记录数</span>
        <b>${escapeHtml(detail.wakeup_log_count || logs.length || 0)}</b>
        <small>命中、冷却、阈值未达和概率未触发</small>
      </article>
    </div>
    ${logs.length ? `
      <div class="group-wakeup-log-list">
        ${logs.map(groupWakeupLogItem).join("")}
      </div>
    ` : `<div class="empty small">暂无群聊唤醒记录</div>`}
  `;
}

export function groupWakeupLogItem(item) {
  const resultLabel = {
    woke: "已唤醒",
    blocked: "冷却拦截",
    missed: "未触发",
  }[item.result] || item.result || "记录";
  const isDim = item.result !== "woke";
  const topicWeight = item.topic_weight || {};
  const weightText = topicWeight.reason
    ? `权重 ${Math.round(Number(topicWeight.multiplier || 1) * 100)}%：${topicWeight.reason}`
    : "";
  const reasonText = item.reason_detail || item.reason_label || item.reason || "";
  return `
    <article class="group-wakeup-log ${isDim ? "is-dim" : ""}">
      <header>
        <b>${escapeHtml(resultLabel)}</b>
        <span>${escapeHtml(item.strength_label || item.type || "-")}</span>
        <time>${escapeHtml(item.time || "")}</time>
      </header>
      <p>${escapeHtml(item.text || "-")}</p>
      <footer>
        <span>${escapeHtml(item.sender_name || item.sender_id || "-")}</span>
        <span>${escapeHtml(item.word ? `词：${item.word}` : item.reason || "")}</span>
        ${reasonText ? `<span>${escapeHtml(`原因：${reasonText}`)}</span>` : ""}
        ${item.probability ? `<span>${escapeHtml(`概率 ${Math.round(Number(item.probability || 0) * 100)}%`)}</span>` : ""}
        ${item.score ? `<span>${escapeHtml(`强度 ${item.score}/${item.threshold || "-"}`)}</span>` : ""}
        ${item.help_type ? `<span>${escapeHtml(`类型 ${item.help_type}`)}</span>` : ""}
        ${weightText ? `<span>${escapeHtml(weightText)}</span>` : ""}
        ${item.fatigue_label ? `<span>${escapeHtml(`疲劳 ${item.fatigue_label}`)}</span>` : ""}
      </footer>
      ${item.note ? `<small>${escapeHtml(item.note)}</small>` : ""}
    </article>
  `;
}

export function bindGroupActions(detail) {
  document.querySelectorAll("[data-group-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.groupAction;
      const body = { group_id: detail.group_id };
      if (action === "toggle") body.enabled = !detail.enabled;
      if (action === "reset_interjection") body.reset_interjection = true;
      if (action === "clear_observation") {
        if (!requireSecondClick(button, `group-clear:${detail.group_id}`, "再次点击清空该群的观测数据", "再次点击清空")) return;
        body.clear_observation = true;
      }
      if (action === "delete") {
        if (!requireSecondClick(button, `group-delete:${detail.group_id}`, "再次点击删除该群聊记录和名单 ID", "再次点击删除")) return;
        await runAction(async () => {
          const result = await postJson("/group/delete", body);
          if (String(state.selectedGroupId) === String(detail.group_id)) state.selectedGroupId = "";
          return result;
        }, "", button);
        return;
      }
      const message = action === "toggle" ? (body.enabled ? "已启用本群，仍受总开关和名单约束" : "已停用本群") :
        action === "clear_observation" ? "已清空群观测资料" : "已重置插话状态";
      await runAction(() => postJson("/group/update", body), message, button);
    });
  });
  document.querySelectorAll("[data-slang-add]").forEach((button) => {
    button.addEventListener("click", async () => {
      const editor = button.closest("[data-slang-new]");
      if (!editor) return;
      const payload = groupSlangPayloadFromEditor(editor, detail.group_id);
      if (!String(payload.term || "").trim()) {
        button.textContent = "先填词";
        setTimeout(() => { button.textContent = "保存"; }, 1200);
        return;
      }
      const serial = state.groupDetailSerial;
      const saved = await runAction(() => postJson("/group/slang/update", payload), "已保存黑话", button, {reload:false});
      if (saved && serial === state.groupDetailSerial && String(state.selectedGroupId) === String(detail.group_id)) {
        const index = state.groups.findIndex(group => String(group.group_id) === String(detail.group_id));
        if (index >= 0) state.groups[index] = {...state.groups[index], ...saved};
        renderGroups(false);
        await renderGroupDetail(true);
      }
    });
  });
  document.querySelectorAll("[data-slang-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest("[data-slang-term]");
      const editor = button.closest(".group-slang-editor");
      if (!row || !editor) return;
      const payload = groupSlangPayloadFromEditor(editor, detail.group_id, row.dataset.slangTerm || "");
      const serial = state.groupDetailSerial;
      const saved = await runAction(() => postJson("/group/slang/update", payload), "已保存黑话校正", button, {reload:false});
      if (saved && serial === state.groupDetailSerial && String(state.selectedGroupId) === String(detail.group_id)) {
        const index = state.groups.findIndex(group => String(group.group_id) === String(detail.group_id));
        if (index >= 0) state.groups[index] = {...state.groups[index], ...saved};
        renderGroups(false);
        await renderGroupDetail(true);
      }
    });
  });
  document.querySelectorAll("[data-slang-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest("[data-slang-term]");
      const term = row?.dataset?.slangTerm || "";
      if (!term) return;
      if (!requireSecondClick(button, `group-slang-delete:${detail.group_id}:${term}`, "再次点击删除这条黑话", "再次点击删除")) return;
      const serial = state.groupDetailSerial;
      const saved = await runAction(() => postJson("/group/slang/update", { group_id: detail.group_id, term, delete: true }), "已删除黑话", button, {reload:false});
      if (saved && serial === state.groupDetailSerial && String(state.selectedGroupId) === String(detail.group_id)) {
        const index = state.groups.findIndex(group => String(group.group_id) === String(detail.group_id));
        if (index >= 0) state.groups[index] = {...state.groups[index], ...saved};
        renderGroups(false);
        await renderGroupDetail(true);
      }
    });
  });
}

export function renderWorldbook() {
  const worldbook = state.overview?.worldbook || {};
  const members = Array.isArray(worldbook.members) ? worldbook.members : [];
  const groups = Array.isArray(worldbook.groups) ? worldbook.groups : [];
  const keyword = ($("#worldbookMemberFilter")?.value || "").trim().toLowerCase();
  const observationFilter = $("#worldbookObservationFilter")?.value || "all";
  const filteredMembers = members.filter((item) => {
    const pending = Array.isArray(item.pending_observations) ? item.pending_observations : [];
    if (observationFilter === "pending" && !(item.pending_observation_count > 0)) return false;
    if (["historical", "group", "other"].includes(observationFilter) && !pending.some(obs => worldbookObservationSource(obs).kind === observationFilter)) return false;
    const haystack = [
      item.user_id,
      item.name,
      item.identity_type,
      item.linked_qq_user_id,
      item.linked_bili_profile_id,
      ...(Array.isArray(item.external_ids) ? item.external_ids : []),
      ...(Array.isArray(item.aliases) ? item.aliases : []),
      ...(Array.isArray(item.observed_names) ? item.observed_names : []),
      item.content,
    ].join(" ").toLowerCase();
    return !keyword || haystack.includes(keyword);
  }).sort((left, right) => {
    const leftPending = Array.isArray(left.pending_observations) ? left.pending_observations.length : 0;
    const rightPending = Array.isArray(right.pending_observations) ? right.pending_observations.length : 0;
    if (rightPending !== leftPending) return rightPending - leftPending;
    if (Boolean(right.enabled) !== Boolean(left.enabled)) return Number(Boolean(right.enabled)) - Number(Boolean(left.enabled));
    const priorityDiff = Number(right.priority || 0) - Number(left.priority || 0);
    if (priorityDiff) return priorityDiff;
    return String(left.name || left.user_id || "").localeCompare(String(right.name || right.user_id || ""), "zh-CN");
  });

  $("#worldbookSummary").innerHTML = [
    worldbookStat("可用身份", worldbook.enabled_member_count || 0, `${worldbook.member_count || 0} 个节点已登记`),
    worldbookStat("待确认", worldbook.pending_observation_total || 0, worldbook.pending_observation_total ? "确认后写入对应关系节点" : "当前没有待审核观察"),
    worldbookStat("群资料", worldbook.group_count || 0, "原群聊身份与关系资料"),
    worldbookStat("匹配策略", worldbook.enabled ? "QQ 精确" : "未启用", worldbook.match_aliases ? "称呼辅助已开启" : "仅按身份键确认"),
  ].join("");
  const clearPendingButton = $("#worldbookClearPendingBtn");
  if (clearPendingButton) clearPendingButton.disabled = !(worldbook.pending_observation_total > 0);
  $("#worldbookSourceFiles").textContent = Array.isArray(worldbook.source_files) && worldbook.source_files.length
    ? `资料路径：${worldbook.source_files.join("；")}`
    : "资料路径：默认路径尚未读取到可用配置";
  $("#worldbookMemberCount").textContent = `${filteredMembers.length}/${members.length} 个成员`;
  renderDl("#worldbookImportState", {
    last_import: worldbook.last_import || "未导入",
    auto_import: worldbook.auto_import ? "开启" : "关闭",
    self_registration: worldbook.self_registration ? "开启" : "关闭",
    self_registration_block_word_count: worldbook.self_registration_block_word_count || 0,
    inject_limit: worldbook.inject_limit || 0,
  });
  $("#worldbookMembers").innerHTML = filteredMembers.length
    ? filteredMembers.map(worldbookMemberCard).join("")
    : `<div class="empty small">暂无匹配关系节点</div>`;
  $("#worldbookGroups").innerHTML = groups.length
    ? groups.map((item) => `
      <section class="worldbook-group-card">
        <div class="worldbook-member-head">
          <div>
            <b>${escapeHtml(item.group_id || "-")}</b>
            <span>${escapeHtml(item.name || "未命名群资料")} · 优先级 ${escapeHtml(item.priority ?? "-")}</span>
          </div>
          <button type="button" data-worldbook-group-delete="${escapeHtml(item.group_id || "")}" class="danger-outline">删除</button>
        </div>
        <div class="worldbook-compact-meta">
          <span>${escapeHtml(item.content ? "有群资料正文" : "无群资料正文")}</span>
        </div>
        <details class="worldbook-editor">
          <summary>编辑群资料</summary>
          <label>名称 <input data-worldbook-group-name="${escapeHtml(item.group_id || "")}" value="${escapeHtml(item.name || "")}" /></label>
          <label>优先级 <input data-worldbook-group-priority="${escapeHtml(item.group_id || "")}" type="number" value="${escapeHtml(item.priority ?? 110)}" /></label>
          <label>资料正文 <textarea data-worldbook-group-content="${escapeHtml(item.group_id || "")}" rows="5">${escapeHtml(item.content || "")}</textarea></label>
          <button type="button" data-worldbook-group-save="${escapeHtml(item.group_id || "")}">保存群资料</button>
        </details>
      </section>
    `).join("")
    : `<div class="empty small">暂无群资料</div>`;
}

export function worldbookStat(label, value, note) {
  return `
    <article class="worldbook-stat">
      <span>${escapeHtml(label)}</span>
      <b>${escapeHtml(value)}</b>
      <small>${escapeHtml(note)}</small>
    </article>
  `;
}

export function worldbookMemberCard(item) {
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  const observed = Array.isArray(item.observed_names) ? item.observed_names : [];
  const externalIds = Array.isArray(item.external_ids) ? item.external_ids : [];
  const memories = Array.isArray(item.important_memories) ? item.important_memories : [];
  const pending = Array.isArray(item.pending_observations) ? item.pending_observations : [];
  const chips = [...aliases.map((name) => `别名：${name}`), ...observed.map((name) => `群名片：${name}`)].slice(0, 12);
  const sourceEntries = Array.isArray(item.source_entries) ? item.source_entries : [];
  const detailId = `worldbook-editor-${String(item.user_id || "").replace(/[^A-Za-z0-9_-]/g, "_")}`;
  const previewItems = worldbookMemberPreviewItems(item, memories);
  const isExternal = item.identity_type === "external" || !/^\d+$/.test(String(item.user_id || ""));
  const identityLabel = isExternal ? "外部身份" : "身份 QQ";
  const genderText = String(item.gender || "").trim();
  const bindLine = item.linked_qq_user_id
    ? ` · 已绑定 QQ ${escapeHtml(item.linked_qq_user_id)}`
    : (item.linked_bili_profile_id ? ` · B站 ${escapeHtml(item.linked_bili_profile_id)}` : "");
  return `
    <section class="worldbook-member-card ${item.enabled ? "" : "off"}" data-worldbook-user-id="${escapeHtml(item.user_id || "")}">
      <div class="worldbook-member-head">
        <div>
          <b>${escapeHtml(item.name || item.user_id || "未命名成员")}</b>
          <span>${identityLabel} ${escapeHtml(item.user_id || "-")} · 优先级 ${escapeHtml(item.priority ?? "-")}${bindLine}</span>
        </div>
        <div class="worldbook-card-actions">
          <button type="button" data-worldbook-living-memory="${escapeHtml(item.user_id || "")}">长期记忆</button>
          <button type="button" data-worldbook-edit="${escapeHtml(detailId)}">编辑</button>
          <button type="button" data-worldbook-member="${escapeHtml(item.user_id || "")}" data-enabled="${item.enabled ? "0" : "1"}">
            ${escapeHtml(item.enabled ? "停用" : "启用")}
          </button>
          <button type="button" data-worldbook-delete="${escapeHtml(item.user_id || "")}" class="danger-outline">删除</button>
        </div>
      </div>
      <div class="worldbook-compact-meta">
        <span>${escapeHtml(aliases.length)} 个别名</span>
        <span>${escapeHtml(observed.length)} 个曾见群名片</span>
        ${genderText ? `<span>性别：${escapeHtml(genderText)}</span>` : ""}
        ${externalIds.length ? `<span>${escapeHtml(externalIds.length)} 个外部身份</span>` : ""}
        <span>${escapeHtml((item.important_memories || []).length)} 条记忆</span>
        ${item.pending_observation_count ? `<span>${escapeHtml(item.pending_observation_count)} 条待确认观察</span>` : ""}
        ${sourceEntries.length ? `<span>${escapeHtml(sourceEntries.slice(0, 2).join(" / "))}</span>` : ""}
      </div>
      ${previewItems.length ? `
        <div class="worldbook-member-preview-list">
          ${previewItems.map(([label, value]) => `
            <p><b>${escapeHtml(label)}</b><span>${escapeHtml(value)}</span></p>
          `).join("")}
        </div>
      ` : ""}
      <div data-worldbook-living-memory-panel="${escapeHtml(item.user_id || "")}">
        ${worldbookLivingMemoryPanel(item.user_id || "")}
      </div>
      ${pending.length ? `<details class="worldbook-observation-review"><summary>待确认观察 · 已展示 ${pending.length} / ${escapeHtml(item.pending_observation_count ?? pending.length)}</summary><p>先阅读来源，再确认或忽略。忽略只移除此条待确认记录；确认后的记忆保留来源信息。收起不改变记录。</p><div class="worldbook-memory-list">${pending.map(obs => worldbookPendingObservationCard(item.user_id || "", obs)).join("")}</div></details>` : ""}
      <details class="worldbook-editor" id="${escapeHtml(detailId)}">
        <summary>编辑关系节点</summary>
        <div class="worldbook-chip-row">
          ${chips.length ? chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("") : `<span>暂无别名记录</span>`}
        </div>
        <label>别名
          <textarea data-worldbook-aliases="${escapeHtml(item.user_id || "")}" rows="3">${escapeHtml(aliases.join("\n"))}</textarea>
        </label>
        <label>名称
          <input data-worldbook-name="${escapeHtml(item.user_id || "")}" value="${escapeHtml(item.name || "")}" />
        </label>
        <label>性别
          <input data-worldbook-gender="${escapeHtml(item.user_id || "")}" placeholder="可填男、女、未知或自定义描述" value="${escapeHtml(item.gender || "")}" />
        </label>
        <label>注入优先级
          <input data-worldbook-priority="${escapeHtml(item.user_id || "")}" type="number" value="${escapeHtml(item.priority ?? 120)}" />
        </label>
        <label>资料正文
          <textarea data-worldbook-content="${escapeHtml(item.user_id || "")}" rows="5">${escapeHtml(item.content || "")}</textarea>
        </label>
        <label>身份说明
          <textarea data-worldbook-identity-note="${escapeHtml(item.user_id || "")}" rows="3">${escapeHtml(item.identity_note || "")}</textarea>
        </label>
        <label>互动边界（可选）
          <textarea data-worldbook-boundary-note="${escapeHtml(item.user_id || "")}" rows="3">${escapeHtml(item.boundary_note || "")}</textarea>
        </label>
        ${isExternal ? `
          <label>绑定到已有 QQ（可选）
            <input data-worldbook-linked-qq="${escapeHtml(item.user_id || "")}" placeholder="填已有 QQ 后保存，会合并到该关系节点" value="${escapeHtml(item.linked_qq_user_id || "")}" />
          </label>
        ` : `
          <label>已关联外部身份
            <input readonly value="${escapeHtml(externalIds.join(" / ") || item.linked_bili_profile_id || "暂无")}" />
          </label>
        `}
        <div class="worldbook-memory-list">
          ${memories.length ? memories.map((memory, index) => worldbookMemoryCard(item.user_id || "", memory, index)).join("") : `<div class="empty small">暂无重要记忆</div>`}
        </div>
        <div class="worldbook-editor-actions">
          <button type="button" data-worldbook-save="${escapeHtml(item.user_id || "")}">保存关系节点</button>
          <button type="button" data-worldbook-delete="${escapeHtml(item.user_id || "")}" class="danger-outline">删除节点</button>
        </div>
      </details>
    </section>
  `;
}

export function worldbookObservationSource(obs) {
  if (obs.source === "memory_companion_historical_chat") return {kind:"historical", label:"历史聊天导入"};
  if (obs.source === "group_observation") return {kind:"group", label:"群聊观察"};
  return {kind:"other", label:obs.source ? `其他来源 · ${obs.source}` : "来源未标明"};
}

export function worldbookObservationEvidence(obs) {
  const ids = Array.isArray(obs.source_event_ids) ? obs.source_event_ids : [];
  const rows = [["来源",worldbookObservationSource(obs).label], ["导入批次",obs.import_batch_id],
    ["来源消息标识",ids.join(" / ")], ["群号",obs.group_id], ["原观察时间",obs.observed_at], ["依据",obs.evidence]];
  return `<details class="aw-worldbook-evidence"><summary>查看来源与依据</summary><dl>${rows.filter(([,value])=>value).map(([label,value])=>`<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl><p>这里只展示原记录已保存的来源；缺失字段不推断，也不代表已核验全部原聊天。</p></details>`;
}

export function worldbookPendingObservationCard(userId, obs) {
  return `<section class="worldbook-memory-card pending"><div>
    <span>${escapeHtml(worldbookObservationSource(obs).label)} · ${escapeHtml(obs.created_at || "")}${obs.count > 1 ? ` · ${escapeHtml(obs.count)} 次` : ""}</span>
    <b>${escapeHtml(obs.title || "待确认观察")}</b><p>${escapeHtml(obs.content || obs.evidence || "")}</p>
    ${worldbookObservationEvidence(obs)}</div><div class="actions compact">
    <button type="button" data-worldbook-observation-accept="${escapeHtml(userId)}" data-observation-id="${escapeHtml(obs.id || "")}">确认到节点</button>
    <button type="button" class="danger-outline" data-worldbook-observation-reject="${escapeHtml(userId)}" data-observation-id="${escapeHtml(obs.id || "")}">忽略此条</button></div></section>`;
}

export function worldbookObservationNotice(message, unconfirmed = null) {
  state.worldbookObservationUnconfirmed = unconfirmed;
  const notice = $("#worldbookObservationNotice");
  notice.hidden = !message;
  notice.querySelector("span").textContent = message;
  $("#worldbookObservationCheckBtn").hidden = !unconfirmed;
}

export async function reviewWorldbookObservation(button, userId, observationId, accepting) {
  setActionBusy(button, true);
  showToast("正在提交观察维护", "info");
  const pending = {userId, observationId};
  try {
    const result = await postJson("/worldbook/member/update", {user_id:userId,
      [accepting ? "accept_pending_observation_id" : "reject_pending_observation_id"]:observationId});
    const receipt = result?.observation_result;
    if (!receipt || receipt.id !== observationId || receipt.user_id !== userId || !["accepted","rejected","missing"].includes(receipt.status)
        || (receipt.status !== "missing" && receipt.status !== (accepting ? "accepted" : "rejected"))) {
      worldbookObservationNotice("本次结果未确认，请先核对当前记录；不会自动重复提交。", pending);
      showToast("观察维护结果未确认", "warning");return;
    }
    worldbookObservationNotice("");
    if (result.worldbook && state.overview) {state.overview.worldbook=result.worldbook;renderWorldbook();}
    showToast(result.message || (receipt.status === "missing" ? "观察已不在待确认列表；本次未修改" : "已完成观察维护"), receipt.status === "missing" ? "warning" : "success");
  } catch (error) {
    worldbookObservationNotice(`本次结果未确认：${error?.message || error}。先核对当前记录，不会自动重复提交。`, pending);
    showToast("观察维护未确认，请核对记录", "warning");
  } finally {setActionBusy(button, false);}
}

export async function checkWorldbookObservation() {
  const pending=state.worldbookObservationUnconfirmed;if(!pending)return;
  const button=$("#worldbookObservationCheckBtn");setActionBusy(button,true);
  try {
    const overview=await fetchJson("/overview");
    if (!overview?.worldbook || !Array.isArray(overview.worldbook.members)) throw new Error("未返回关系记录");
    if (state.worldbookObservationUnconfirmed !== pending) return;
    state.overview.worldbook=overview.worldbook;renderWorldbook();
    const member=overview.worldbook.members.find(item=>String(item.user_id)===pending.userId);
    const present=member?.pending_observations?.some(obs=>obs.id===pending.observationId);
    worldbookObservationNotice(present ? "该观察仍在当前待确认窗口中；先核对原操作状态，再决定是否手动操作。" : "当前窗口未见该观察；可能已被处理或不在返回范围内，不能据此认定确认成功。",pending);
  } catch(error) {if(state.worldbookObservationUnconfirmed===pending)worldbookObservationNotice(`核对失败：${error?.message||error}。原操作结果仍未确认，不自动重试。`,pending);}
  finally {setActionBusy(button,false);}
}

export function worldbookMemberPreviewItems(item, memories = []) {
  const rows = [];
  const add = (label, value, limit = 120) => {
    const text = shortName(String(value || "").trim(), limit);
    if (text && !rows.some(([, existing]) => existing === text)) rows.push([label, text]);
  };
  add("资料", item.content || item.note, 130);
  add("性别", item.gender, 60);
  add("身份", item.identity_note, 120);
  add("边界", item.boundary_note, 110);
  const memory = memories.find((entry) => entry && entry.enabled !== false && String(entry.content || "").trim());
  if (memory) add("记忆", `${memory.title ? `${memory.title}：` : ""}${memory.content || ""}`, 120);
  return rows.slice(0, 4);
}

export function worldbookMemoryCard(userId, memory, index) {
  return `
    <section class="worldbook-memory-card ${memory.enabled === false ? "off" : ""}">
      <div>
        <b>${escapeHtml(memory.title || "重要记忆")}</b>
        <p>${escapeHtml(memory.content || "")}</p>
        <span>${escapeHtml(memory.privacy || "internal")} · 权重 ${escapeHtml(memory.weight ?? 50)}${memory.source ? ` · ${escapeHtml(memory.source)}` : ""}</span>
        ${worldbookObservationEvidence(memory)}
      </div>
      <div class="actions compact">
        <button type="button" data-worldbook-memory-toggle="${escapeHtml(userId)}" data-memory-index="${escapeHtml(index)}">
          ${escapeHtml(memory.enabled === false ? "启用" : "停用")}
        </button>
        <button type="button" class="danger-outline" data-worldbook-memory-delete="${escapeHtml(userId)}" data-memory-index="${escapeHtml(index)}">删除</button>
      </div>
    </section>
  `;
}

export function worldbookLivingMemoryPanel(userId) {
  const result = state.worldbookLivingMemory?.[userId];
  if (!result) return "";
  if (result.loading) {
    return `
      <section class="worldbook-livingmemory-panel">
        <div class="worldbook-livingmemory-head">
          <div>
            <b>LivingMemory</b>
            <span>正在检索对应记忆...</span>
          </div>
          <button type="button" data-worldbook-living-memory-close="${escapeHtml(userId)}" aria-label="收起 LivingMemory">收起</button>
        </div>
      </section>
    `;
  }
  if (result.error) {
    return `
      <section class="worldbook-livingmemory-panel error">
        <div class="worldbook-livingmemory-head">
          <div>
            <b>LivingMemory</b>
            <span>${escapeHtml(result.error)}</span>
          </div>
          <button type="button" data-worldbook-living-memory-close="${escapeHtml(userId)}" aria-label="收起 LivingMemory">收起</button>
        </div>
      </section>
    `;
  }
  const items = Array.isArray(result.items) ? result.items : [];
  const tokens = Array.isArray(result.tokens) ? result.tokens : [];
  const primaryTokens = Array.isArray(result.primary_tokens) ? result.primary_tokens : [];
  return `
    <section class="worldbook-livingmemory-panel">
      <div class="worldbook-livingmemory-head">
        <div>
          <b>LivingMemory 相关记忆</b>
          <span>${escapeHtml(result.available === false ? (result.message || "未找到 LivingMemory 数据库") : `${items.length} 条结果 · 严格匹配`)}</span>
        </div>
        <button type="button" data-worldbook-living-memory-close="${escapeHtml(userId)}" aria-label="收起 LivingMemory">收起</button>
      </div>
      ${result.filter_note ? `<p class="worldbook-livingmemory-note">${escapeHtml(result.filter_note)}</p>` : ""}
      ${tokens.length ? `
        <div class="worldbook-livingmemory-tokens">
          ${tokens.slice(0, 12).map((token) => `<span class="${primaryTokens.includes(token) ? "primary" : ""}">${escapeHtml(token)}</span>`).join("")}
        </div>
      ` : ""}
      <div class="worldbook-livingmemory-list">
        ${items.length ? items.map(worldbookLivingMemoryCard).join("") : `<div class="empty small">没有检索到对应 LivingMemory 记忆</div>`}
      </div>
    </section>
  `;
}

export function worldbookLivingMemoryCard(item) {
  const tags = [
    item.source_label || item.source,
    item.persona_id,
    item.session_id,
    item.importance !== undefined && item.importance !== null ? `重要性 ${Number(item.importance).toFixed(2)}` : "",
    item.confidence !== undefined && item.confidence !== null ? `置信 ${Number(item.confidence).toFixed(2)}` : "",
    item.score !== undefined && item.score !== null ? `命中 ${Number(item.score).toFixed(1)}` : "",
  ].filter(Boolean);
  const topics = Array.isArray(item.topics) ? item.topics : [];
  const keyFacts = Array.isArray(item.key_facts) ? item.key_facts : [];
  const matchedTokens = Array.isArray(item.matched_tokens) ? item.matched_tokens : [];
  const content = String(item.content || "");
  const preview = item.preview || shortName(content, 260);
  const canExpand = content && content !== preview;
  return `
    <article class="worldbook-livingmemory-card">
      <div class="worldbook-livingmemory-card-meta">
        ${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
      </div>
      ${matchedTokens.length ? `<div class="worldbook-livingmemory-tags matched">${matchedTokens.map((tag) => `<span>${escapeHtml(`命中：${tag}`)}</span>`).join("")}</div>` : ""}
      <p>${escapeHtml(preview || "无内容")}</p>
      ${topics.length ? `<div class="worldbook-livingmemory-tags">${topics.slice(0, 6).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
      ${keyFacts.length ? `<ul>${keyFacts.slice(0, 4).map((fact) => `<li>${escapeHtml(fact)}</li>`).join("")}</ul>` : ""}
      ${canExpand ? `
        <details>
          <summary>展开片段</summary>
          <pre>${escapeHtml(content)}</pre>
        </details>
      ` : ""}
    </article>
  `;
}

export function getWorldbookMember(userId) {
  const members = state.overview?.worldbook?.members || [];
  return members.find((item) => item.user_id === userId);
}

export function findWorldbookLivingMemoryPanel(userId) {
  return Array.from(document.querySelectorAll("[data-worldbook-living-memory-panel]"))
    .find((panel) => panel.dataset.worldbookLivingMemoryPanel === userId);
}

export function closeWorldbookLivingMemory(userId) {
  if (!userId) return;
  delete state.worldbookLivingMemory[userId];
  const panel = findWorldbookLivingMemoryPanel(userId);
  if (panel) panel.innerHTML = "";
}

export async function loadWorldbookLivingMemory(userId, button) {
  if (!userId) return;
  if (state.worldbookLivingMemory[userId] && !state.worldbookLivingMemory[userId].loading) {
    closeWorldbookLivingMemory(userId);
    return;
  }
  const panel = findWorldbookLivingMemoryPanel(userId);
  const requestId = ++state.worldbookLivingMemoryRequestSeq;
  state.worldbookLivingMemory[userId] = { loading: true, requestId };
  if (panel) panel.innerHTML = worldbookLivingMemoryPanel(userId);
  setActionBusy(button, true);
  try {
    const result = await fetchJson(`/worldbook/member/livingmemory?user_id=${encodeURIComponent(userId)}&limit=24`);
    if (state.worldbookLivingMemory[userId]?.requestId !== requestId) return;
    state.worldbookLivingMemory[userId] = result || { items: [] };
    if (panel) panel.innerHTML = worldbookLivingMemoryPanel(userId);
    showToast(result?.message || "LivingMemory 查询完成");
  } catch (error) {
    if (state.worldbookLivingMemory[userId]?.requestId !== requestId) return;
    state.worldbookLivingMemory[userId] = { error: error.message || "查询失败", items: [] };
    if (panel) panel.innerHTML = worldbookLivingMemoryPanel(userId);
    showToast(`查询失败：${error.message}`, "error");
  } finally {
    setActionBusy(button, false);
  }
}

export async function handleWorldbookMemberAction(button) {
  const editTarget = button.dataset.worldbookEdit;
  if (editTarget) {
    const details = document.getElementById(editTarget);
    if (details) {
      details.open = true;
      details.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    return;
  }
  if (button.dataset.worldbookLivingMemory !== undefined) {
    await loadWorldbookLivingMemory(button.dataset.worldbookLivingMemory, button);
    return;
  }
  if (button.dataset.worldbookLivingMemoryClose !== undefined) {
    closeWorldbookLivingMemory(button.dataset.worldbookLivingMemoryClose);
    return;
  }
  if (button.dataset.worldbookMember !== undefined) {
    const userId = button.dataset.worldbookMember;
    if (!userId) return;
    await runAction(() => postJson("/worldbook/member/update", {
      user_id: userId,
      enabled: button.dataset.enabled === "1",
    }), button.dataset.enabled === "1" ? "已启用关系节点" : "已停用关系节点", button);
    return;
  }
  if (button.dataset.worldbookSave !== undefined) {
    const userId = button.dataset.worldbookSave;
    if (!userId) return;
    const aliasBox = findWorldbookField("aliases", userId);
    const identityInput = findWorldbookField("identity-note", userId);
    const boundaryInput = findWorldbookField("boundary-note", userId);
    const nameInput = findWorldbookField("name", userId);
    const genderInput = findWorldbookField("gender", userId);
    const priorityInput = findWorldbookField("priority", userId);
    const contentInput = findWorldbookField("content", userId);
    const linkedQqInput = findWorldbookField("linked-qq", userId);
    const aliases = String(aliasBox?.value || "")
      .split(/[\n,，;；]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    const payload = {
      user_id: userId,
      name: nameInput?.value || "",
      gender: genderInput?.value || "",
      priority: Number(priorityInput?.value || 120),
      content: contentInput?.value || "",
      identity_note: identityInput?.value || "",
      boundary_note: boundaryInput?.value || "",
      aliases,
    };
    if (linkedQqInput && String(linkedQqInput.value || "").trim()) {
      payload.linked_qq_user_id = String(linkedQqInput.value || "").trim();
    }
    await runAction(() => postJson("/worldbook/member/update", payload), "已保存关系节点", button);
    return;
  }
  if (button.dataset.worldbookMemoryToggle !== undefined) {
    const userId = button.dataset.worldbookMemoryToggle;
    const index = Number(button.dataset.memoryIndex || -1);
    const member = getWorldbookMember(userId);
    const memories = Array.isArray(member?.important_memories) ? member.important_memories.map((item) => ({ ...item })) : [];
    if (!userId || index < 0 || index >= memories.length) return;
    memories[index].enabled = memories[index].enabled === false;
    await runAction(() => postJson("/worldbook/member/update", { user_id: userId, important_memories: memories }), "已更新重要记忆", button);
    return;
  }
  if (button.dataset.worldbookMemoryDelete !== undefined) {
    const userId = button.dataset.worldbookMemoryDelete;
    const index = Number(button.dataset.memoryIndex || -1);
    const member = getWorldbookMember(userId);
    const memories = Array.isArray(member?.important_memories) ? member.important_memories.map((item) => ({ ...item })) : [];
    if (!userId || index < 0 || index >= memories.length) return;
    memories.splice(index, 1);
    await runAction(() => postJson("/worldbook/member/update", { user_id: userId, important_memories: memories }), "已删除重要记忆", button);
    return;
  }
  if (button.dataset.worldbookObservationAccept !== undefined || button.dataset.worldbookObservationReject !== undefined) {
    const accepting = button.dataset.worldbookObservationAccept !== undefined;
    const userId = accepting ? button.dataset.worldbookObservationAccept : button.dataset.worldbookObservationReject;
    const observationId = button.dataset.observationId || "";
    if (!userId || !observationId) return;
    await reviewWorldbookObservation(button, userId, observationId, accepting);
    return;
  }
  if (button.dataset.worldbookDelete !== undefined) {
    const userId = button.dataset.worldbookDelete || button.closest("[data-worldbook-user-id]")?.dataset.worldbookUserId || "";
    if (!userId) {
      showToast("没有找到要删除的关系节点 ID", "error");
      return;
    }
    const now = Date.now();
    const armed = button.dataset.deleteArmed === userId && now - Number(button.dataset.deleteArmedAt || 0) < 6000;
    if (!armed) {
      button.dataset.deleteArmed = userId;
      button.dataset.deleteArmedAt = String(now);
      button.dataset.originalText = button.textContent || "删除";
      button.textContent = "再次点击删除";
      showToast(`再次点击删除关系节点 ${userId}`);
      window.clearTimeout(button._deleteArmedTimer);
      button._deleteArmedTimer = window.setTimeout(() => {
        if (button.dataset.deleteArmed === userId) {
          delete button.dataset.deleteArmed;
          delete button.dataset.deleteArmedAt;
          button.textContent = button.dataset.originalText || "删除";
          delete button.dataset.originalText;
        }
      }, 6000);
      return;
    }
    delete button.dataset.deleteArmed;
    delete button.dataset.deleteArmedAt;
    await runAction(() => postJson("/worldbook/member/update", { user_id: userId, delete: true }), "已删除关系节点", button);
  }
}

export function findWorldbookField(field, id) {
  return [...document.querySelectorAll(`[data-worldbook-${field}]`)]
    .find((item) => item.getAttribute(`data-worldbook-${field}`) === id);
}

export function findWorldbookGroupField(field, id) {
  return [...document.querySelectorAll(`[data-worldbook-group-${field}]`)]
    .find((item) => item.getAttribute(`data-worldbook-group-${field}`) === id);
}

export async function handleWorldbookGroupAction(button) {
  if (button.dataset.worldbookGroupSave !== undefined) {
    const groupId = button.dataset.worldbookGroupSave;
    if (!groupId) return;
    await runAction(() => postJson("/worldbook/group/update", {
      group_id: groupId,
      name: findWorldbookGroupField("name", groupId)?.value || "",
      priority: Number(findWorldbookGroupField("priority", groupId)?.value || 110),
      content: findWorldbookGroupField("content", groupId)?.value || "",
    }), "已保存群资料", button);
    return;
  }
  if (button.dataset.worldbookGroupDelete !== undefined) {
    const groupId = button.dataset.worldbookGroupDelete;
    if (!groupId) return;
    const now = Date.now();
    const armed = button.dataset.deleteArmed === groupId && now - Number(button.dataset.deleteArmedAt || 0) < 6000;
    if (!armed) {
      button.dataset.deleteArmed = groupId;
      button.dataset.deleteArmedAt = String(now);
      button.dataset.originalText = button.textContent || "删除";
      button.textContent = "再次点击删除";
      showToast(`再次点击删除群资料 ${groupId}`);
      window.clearTimeout(button._deleteArmedTimer);
      button._deleteArmedTimer = window.setTimeout(() => {
        if (button.dataset.deleteArmed === groupId) {
          delete button.dataset.deleteArmed;
          delete button.dataset.deleteArmedAt;
          button.textContent = button.dataset.originalText || "删除";
          delete button.dataset.originalText;
        }
      }, 6000);
      return;
    }
    delete button.dataset.deleteArmed;
    delete button.dataset.deleteArmedAt;
    await runAction(() => postJson("/worldbook/group/update", { group_id: groupId, delete: true }), "已删除群资料", button);
  }
}

export function renderMemory() {
  const overview = state.overview || {};
  const daily = overview.daily_state || {};
  const life = overview.life_observation || {};
  $("#livingMemoryBox").textContent = livingMemoryStatusText(overview.livingmemory);
  renderLifeHero(daily, life);
  renderDreamCard(life.dream || {});
  renderStatePillBoard(daily);
  renderDiaryCards(life.diaries || []);
  renderDreamFragments(life.dream_fragments || []);
  renderDl("#dailyState", normalizeDailyStateForDisplay(daily));
  renderDailyTimeline();
  renderPersonalGoals();
  renderInteractionImpact();
  renderMemoryComposition();
  renderSlangCloud();
}

export function foodMenuFeaturePanelHtml() {
  const menu = state.overview?.food_menu || {};
  const items = Array.isArray(menu.items) ? menu.items : [];
  const availableIds = new Set(items.map((item) => String(item?.id || "")).filter(Boolean));
  state.selectedFoodMenuIds = new Set(
    [...state.selectedFoodMenuIds].filter((itemId) => availableIds.has(itemId)),
  );
  const selectedCount = state.selectedFoodMenuIds.size;
  const allSelected = Boolean(items.length) && selectedCount === items.length;
  const enabled = toBool(state.featureDraft?.enable_food_menu_recommendation)
    || featureTemporarilyUnlockedByProactiveOnly("enable_food_menu_recommendation");
  return `
    <article class="feature-detail-card food-feature-panel">
      <div class="food-feature-hero">
        <div>
          <span class="module-badge">私聊陪伴</span>
          <h3>候选菜单</h3>
          <p>把常吃的几样东西收在这里。用户纠结吃什么时，只挑最贴合的几个给回复做参考。</p>
        </div>
        <div class="food-feature-status ${enabled ? "on" : "off"}">
          <b>${enabled ? "参与回复" : "仅管理"}</b>
          <span>${enabled ? "问到吃什么时会参考" : "关闭后不会进入回复参考"}</span>
          ${featureLockedByProactiveOnlyMode("enable_food_menu_recommendation") ? "" : `<button type="button" data-food-feature-save-toggle>保存开关</button>`}
        </div>
      </div>
      <div class="food-feature-stats">
        <span>${escapeHtml(menu.visible_count || 0)} 个可用</span>
        <span>${escapeHtml(menu.favorite_count || 0)} 个常吃</span>
        <span>${escapeHtml(menu.hidden_count || 0)} 个收起</span>
        <span>更新 ${escapeHtml(menu.updated || "-")}</span>
      </div>
      ${items.length ? `
        <div class="food-selection-toolbar" data-food-selection-toolbar>
          <label class="food-select-all">
            <input type="checkbox" data-food-select-all ${allSelected ? "checked" : ""} />
            <span>全选当前 ${escapeHtml(items.length)} 项</span>
          </label>
          <span class="food-selection-count" data-food-selection-count>已选 ${escapeHtml(selectedCount)} 项</span>
          <button type="button" class="danger-outline" data-food-bulk-delete ${selectedCount ? "" : "disabled"}>删除所选</button>
        </div>
      ` : ""}
      <div class="food-feature-entry">
        <form id="foodMenuFeatureAddForm" class="food-quick-add-form">
          <label>快速添加
            <input name="name" maxlength="40" placeholder="兰州拉面 / 黄焖鸡 / 楼下麻辣烫" required />
          </label>
          <button type="submit">加入</button>
          <details class="food-extra-drawer">
            <summary>补充信息</summary>
            <div class="food-feature-add-form">
              <label>类型
                <select name="type">${foodMenuTypeOptions("")}</select>
              </label>
              <label>分类 <input name="category" maxlength="24" placeholder="可不填，会自动猜" /></label>
              <label>标签 <input name="tags" maxlength="160" placeholder="热乎、快、清淡" /></label>
              <label class="wide-field">适合时段
                <div class="food-time-picks">${foodMenuTimeCheckboxes([], { name: "times" })}</div>
              </label>
              <label class="wide-field">备注 <input name="note" maxlength="100" placeholder="不想纠结时直接选" /></label>
              <label class="check-field"><input name="favorite" type="checkbox" /> 常吃</label>
            </div>
          </details>
        </form>
        <form id="foodMenuBulkForm" class="food-bulk-form">
          <label>批量粘贴
            <textarea name="text" rows="5" placeholder="一行一个就行：&#10;兰州拉面&#10;黄焖鸡&#10;楼下麻辣烫&#10;也可以：煎饼果子｜早餐｜快、便宜｜早餐"></textarea>
          </label>
          <div class="food-bulk-actions">
            <label><input name="favorite" type="checkbox" /> 标为常吃</label>
            <button type="button" data-food-preset="basic">填入常见模板</button>
            <button type="submit">批量加入</button>
          </div>
        </form>
      </div>
      <div class="food-feature-list">
        ${items.length ? renderFoodMenuGroups(items) : `
          <div class="food-menu-empty">
            <b>先放几样常吃的东西</b>
            <span>比如一道菜、一家店、一份外卖。候选越具体，问“吃什么”时越容易给出像样建议。</span>
          </div>
        `}
      </div>
    </article>
  `;
}

export function renderFoodMenuGroups(items) {
  const groups = new Map();
  items.forEach((item) => {
    const label = String(item.type_label || "候选").trim() || "候选";
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(item);
  });
  return Array.from(groups.entries()).map(([label, groupItems]) => `
    <section class="food-menu-group">
      <header>
        <b>${escapeHtml(label)}</b>
        <span>${escapeHtml(groupItems.length)} 个</span>
      </header>
      <div class="food-menu-list">
        ${groupItems.map(renderFoodMenuCard).join("")}
      </div>
    </section>
  `).join("");
}

export function renderFoodMenuCard(item) {
  const tags = Array.isArray(item.tags) ? item.tags : [];
  const times = Array.isArray(item.time_labels) ? item.time_labels : [];
  const timeKeys = Array.isArray(item.times) ? item.times : [];
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  const avoid = Array.isArray(item.avoid) ? item.avoid : [];
  const id = String(item.id || "");
  const selected = state.selectedFoodMenuIds.has(id);
  return `
    <article class="food-menu-card ${item.hidden ? "is-hidden-food" : ""} ${item.favorite ? "is-favorite-food" : ""} ${selected ? "is-selected-food" : ""}" data-food-card-id="${escapeHtml(id)}">
      <header>
        <label class="food-card-select" title="选择 ${escapeHtml(item.name || "候选")}">
          <input type="checkbox" data-food-select="${escapeHtml(id)}" ${selected ? "checked" : ""} aria-label="选择 ${escapeHtml(item.name || "候选")}" />
        </label>
        <div class="food-card-heading">
          <span>${escapeHtml(item.category || item.type_label || "候选")}</span>
          <h3>${escapeHtml(item.name || "未命名")}</h3>
        </div>
        <em>${item.favorite ? "常吃" : item.hidden ? "已收起" : "候选"}</em>
      </header>
      <p>${escapeHtml(item.note || "没有备注")}</p>
      <div class="food-menu-tags">
        ${tags.slice(0, 5).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
        ${times.slice(0, 4).map((time) => `<span>${escapeHtml(time)}</span>`).join("")}
        ${item.use_count ? `<span>吃过 ${escapeHtml(item.use_count)} 次</span>` : ""}
        ${item.last_recommended && !["-", "从未"].includes(item.last_recommended) ? `<span>推荐 ${escapeHtml(item.last_recommended)}</span>` : ""}
      </div>
      <details class="food-menu-editor">
        <summary>整理</summary>
        <div class="food-menu-editor-grid">
          <label>名称 <input data-food-name="${escapeHtml(id)}" value="${escapeHtml(item.name || "")}" maxlength="40" /></label>
          <label>类型
            <select data-food-type="${escapeHtml(id)}">
              ${foodMenuTypeOptions(item.type)}
            </select>
          </label>
          <label>分类 <input data-food-category="${escapeHtml(id)}" value="${escapeHtml(item.category || "")}" maxlength="24" /></label>
          <label>标签 <input data-food-tags="${escapeHtml(id)}" value="${escapeHtml(tags.join(", "))}" maxlength="160" /></label>
          <label class="wide-field">适合时段
            <div class="food-time-picks">${foodMenuTimeCheckboxes(timeKeys, { dataAttr: "data-food-time", id })}</div>
          </label>
          <label>别名 <input data-food-aliases="${escapeHtml(id)}" value="${escapeHtml(aliases.join(", "))}" maxlength="160" /></label>
          <label class="wide-field">避开场景 <input data-food-avoid="${escapeHtml(id)}" value="${escapeHtml(avoid.join(", "))}" maxlength="160" placeholder="胃不舒服、太晚" /></label>
          <label class="wide-field">备注 <input data-food-note="${escapeHtml(id)}" value="${escapeHtml(item.note || "")}" maxlength="100" /></label>
          <label class="check-field"><input data-food-favorite="${escapeHtml(id)}" type="checkbox" ${item.favorite ? "checked" : ""} /> 常吃</label>
          <label class="check-field"><input data-food-hidden="${escapeHtml(id)}" type="checkbox" ${item.hidden ? "checked" : ""} /> 暂时收起</label>
        </div>
        <div class="food-menu-actions">
          <button type="button" data-food-save="${escapeHtml(id)}">保存</button>
          <button type="button" class="danger-outline" data-food-delete="${escapeHtml(id)}">删除</button>
        </div>
      </details>
    </article>
  `;
}

export function foodMenuTypeOptions(selected) {
  const options = [
    ["", "自动判断"],
    ["dish", "菜品"],
    ["restaurant", "菜馆"],
    ["takeout", "外卖"],
    ["drink_snack", "饮品/零食"],
    ["emergency", "应急"],
  ];
  return options.map(([value, label]) => `<option value="${value}" ${String(selected || "") === value ? "selected" : ""}>${label}</option>`).join("");
}

export function foodMenuTimeChoices() {
  return [
    ["breakfast", "早餐"],
    ["lunch", "午餐"],
    ["dinner", "晚餐"],
    ["late_night", "夜宵"],
    ["snack", "加餐"],
  ];
}

export function foodMenuTimeCheckboxes(selected = [], options = {}) {
  const selectedSet = new Set((Array.isArray(selected) ? selected : [selected]).map((item) => String(item || "")));
  const attr = options.dataAttr && options.id
    ? `${options.dataAttr}="${escapeHtml(options.id)}"`
    : `name="${escapeHtml(options.name || "times")}"`;
  return foodMenuTimeChoices().map(([value, label]) => `
    <label>
      <input type="checkbox" ${attr} value="${escapeHtml(value)}" ${selectedSet.has(value) ? "checked" : ""}>
      <span>${escapeHtml(label)}</span>
    </label>
  `).join("");
}

export function foodField(id, field) {
  return document.querySelector(`[data-food-${field}="${CSS.escape(id)}"]`);
}

export function foodTimeValues(id) {
  return [...document.querySelectorAll(`[data-food-time="${CSS.escape(id)}"]:checked`)].map((input) => input.value);
}

export function resetFoodBulkDeleteConfirmation() {
  const button = document.querySelector("[data-food-bulk-delete]");
  if (!(button instanceof HTMLButtonElement) || !button.dataset.confirmKey) return;
  window.clearTimeout(button._confirmTimer);
  delete button.dataset.confirmKey;
  delete button.dataset.confirmAt;
  button.textContent = button.dataset.originalText || "删除所选";
  delete button.dataset.originalText;
}

export function syncFoodMenuSelectionUi({ resetConfirmation = false } = {}) {
  const checkboxes = [...document.querySelectorAll("[data-food-select]")];
  const availableIds = new Set(
    checkboxes.map((input) => String(input.dataset.foodSelect || "")).filter(Boolean),
  );
  const selectedIds = state.selectedFoodMenuIds instanceof Set
    ? state.selectedFoodMenuIds
    : new Set();
  state.selectedFoodMenuIds = new Set(
    [...selectedIds].filter((itemId) => availableIds.has(itemId)),
  );

  checkboxes.forEach((input) => {
    const itemId = String(input.dataset.foodSelect || "");
    const selected = state.selectedFoodMenuIds.has(itemId);
    input.checked = selected;
    input.closest("[data-food-card-id]")?.classList.toggle("is-selected-food", selected);
  });

  const selectedCount = state.selectedFoodMenuIds.size;
  const selectAll = document.querySelector("[data-food-select-all]");
  if (selectAll instanceof HTMLInputElement) {
    selectAll.checked = Boolean(checkboxes.length) && selectedCount === checkboxes.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
    selectAll.disabled = !checkboxes.length;
  }
  const count = document.querySelector("[data-food-selection-count]");
  if (count) count.textContent = `已选 ${selectedCount} 项`;
  const deleteButton = document.querySelector("[data-food-bulk-delete]");
  if (deleteButton instanceof HTMLButtonElement) deleteButton.disabled = selectedCount === 0;
  if (resetConfirmation) resetFoodBulkDeleteConfirmation();
}
