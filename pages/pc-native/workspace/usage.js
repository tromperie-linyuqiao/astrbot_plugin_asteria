/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {formatHourKey,formatNumber,formatRecentTime,renderTokenMemoryPluginProviderTable,renderTokenMemoryPluginRecentTable,renderTokenMemoryPluginTaskTable,tokenCacheText,tokenTable,tokenTaskLabel} from './learning.js';
import {renderTokenResetNotice} from './navigation.js';
import {formatCompactNumber} from './setup.js';
import {$,state} from './state.js';
import {escapeHtml} from './workspace.js';

export function groupTopicThreadsView(threads) {
  const items = Array.isArray(threads) ? threads : [];
  if (!items.length) {
    return `<div class="empty small">暂无话题线</div>`;
  }
  return `
    <div class="group-topic-list">
      ${items.map((item) => {
        const examples = Array.isArray(item.recent_examples) ? item.recent_examples : [];
        const participants = Array.isArray(item.participants) ? item.participants : [];
        const heat = Math.max(0, Math.min(100, Number(item.heat || 0)));
        return `
          <article class="group-topic-card ${item.status === "活跃" ? "active" : ""}">
            <div class="group-topic-rail">
              <span>${escapeHtml(item.rank || "")}</span>
              <i style="height:${escapeHtml(Math.max(14, heat))}%"></i>
            </div>
            <div class="group-topic-main">
              <header>
                <div>
                  <span class="group-topic-status">${escapeHtml(item.status || "话题")}</span>
                  <h3>${escapeHtml(item.title || "未命名话题")}</h3>
                </div>
                <dl>
                  <div><dt>消息</dt><dd>${escapeHtml(item.message_count || 0)}</dd></div>
                  <div><dt>参与</dt><dd>${escapeHtml(item.participant_count || participants.length || 0)}</dd></div>
                  <div><dt>持续</dt><dd>${escapeHtml(item.duration || "-")}</dd></div>
                </dl>
              </header>
              ${item.summary ? `<p class="group-topic-summary">${escapeHtml(item.summary)}</p>` : ""}
              <div class="group-topic-meta">
                <span>最近 ${escapeHtml(item.last_seen || "-")}</span>
                <span>开始 ${escapeHtml(item.started || "-")}</span>
                ${item.bot_joined ? `<span>Bot 参与过</span>` : ""}
              </div>
              ${participants.length ? `
                <div class="group-topic-people">
                  ${participants.slice(0, 6).map((person) => `<span title="${escapeHtml(person.id || "")}">${escapeHtml(person.name || person.id || "-")}</span>`).join("")}
                  ${participants.length > 6 ? `<span>+${escapeHtml(participants.length - 6)}</span>` : ""}
                </div>
              ` : ""}
              ${examples.length ? `
                <div class="group-topic-examples">
                  ${examples.map((example) => `
                    <p><b>${escapeHtml(example.name || "群友")}</b><span>${escapeHtml(example.text || "")}</span><small>${escapeHtml(example.time || "")}</small></p>
                  `).join("")}
                </div>
              ` : ""}
            </div>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

export function renderActivityHeatmap() {
  const now = Math.floor(Date.now() / 1000);
  const buckets = Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0 }));
  [...state.users, ...state.groups].forEach((item) => {
    const ts = Number(item.last_seen_ts || 0);
    if (!ts || now - ts > 86400) return;
    buckets[new Date(ts * 1000).getHours()].count += 1;
  });
  const max = Math.max(1, ...buckets.map((item) => item.count));
  $("#activityHeatmap").innerHTML = buckets.map((item) => {
    const level = Math.min(4, Math.ceil((item.count / max) * 4));
    return `<span class="heat level-${level}" title="${item.hour}:00-${item.hour + 1}:00 · ${item.count}">${item.hour}</span>`;
  }).join("");
}

export function horizontalBars(data, total) {
  return Object.entries(data).map(([label, count]) => {
    const pct = Math.round((count / total) * 100);
    return `
      <div class="meter-row">
        <span>${escapeHtml(label)}</span>
        <div class="meter"><i style="width:${pct}%"></i></div>
        <b>${escapeHtml(count)}</b>
      </div>
    `;
  }).join("");
}

export function renderTokens() {
  const stats = state.tokenStats || {};
  const source = tokenSelectedScope(stats);
  const scope = source.scope || {};
  const totals = source.totals || {};
  const totalTokens = Number(totals.total_tokens || 0);
  const calls = Number(totals.calls || 0);
  const errors = Number(totals.errors || 0);
  const estimatedRatio = Number(totals.estimated_ratio || 0);
  const cachedTokens = Number(totals.cached_tokens || 0);
  const cacheReadTokens = Number(totals.cache_read_tokens || 0);
  const cacheWriteTokens = Number(totals.cache_write_tokens || 0);
  const cachedRatio = Number(totals.cached_ratio || 0);
  const comparison = tokenSourceComparison(stats, source);
  const budget = stats.budget || {};
  const dailyLimit = Number(budget.limit || 0);
  const dailyUsed = Number(budget.used || 0);
  const softLimit = Number(budget.soft_limit || 0);
  const softRemaining = budget.soft_remaining == null ? null : Number(budget.soft_remaining || 0);
  const exemptUsed = Number(budget.exempt_used || 0);
  const dailyRemaining = budget.remaining == null ? null : Number(budget.remaining || 0);
  const tokenLoadingNote = state.tokenStatsPartial
    ? `<div class="empty small">已先显示总览中的 Token 摘要，正在加载完整明细...</div>`
    : (!state.tokenStats && !state.lazyLoaded.tokenStats ? `<div class="empty small">正在加载 Token 统计...</div>` : "");
  renderTokenToolbar(stats, source.dateRows || []);
  renderTokenSourceVisibility(source);
  renderTokenBalanceStatus(stats.balance || {});
  renderTokenResetNotice();
  const showHourlyTrend = state.tokenView === "total" && (source.hours || []).length > 0;
  const hourlyPanel = $("#tokenHourlyPanel");
  if (hourlyPanel) hourlyPanel.hidden = !showHourlyTrend;
  $("#tokenSummary").innerHTML = `${tokenLoadingNote}${tokenSummaryBoard({
    source,
    scope,
    totalTokens,
    comparison,
    totals,
    calls,
    errors,
    estimatedRatio,
    cachedTokens,
    cacheReadTokens,
    cacheWriteTokens,
    cachedRatio,
    dailyLimit,
    dailyUsed,
    dailyRemaining,
    softLimit,
    softRemaining,
    softEnabled: Boolean(budget.soft_enabled),
    softActive: Boolean(budget.soft_active),
    deferredCalls: Number(budget.deferred_calls || 0),
    exemptUsed,
  })}`;

  renderTokenChart("#tokenProviderChart", source.providers || [], `暂无${source.shortLabel} Provider 消耗数据`, (item) => item.key || "default");
  const taskChartRows = source.chartSecondaryRows || source.tasks || [];
  renderTokenChart(
    "#tokenTaskChart",
    taskChartRows,
    source.secondaryChartEmpty || `暂无${source.shortLabel}任务消耗数据`,
    source.secondaryChartLabeler || ((item) => tokenTaskLabel(item.key)),
  );
  const taskChartHint = $("#tokenTaskChartHint");
  if (taskChartHint) {
    const hasUnclassifiedCalls = source.source === "companion"
      && taskChartRows.some((item) => String(item?.key || "").trim() === "other");
    taskChartHint.hidden = !hasUnclassifiedCalls;
    taskChartHint.textContent = hasUnclassifiedCalls
      ? "“未分类模型调用”只保留没有有效任务标识的旧版记录或异常链路；当前内置调用已逐项标注。历史 Token 无法反推用途；新调用沿当前任务标识累计，无需为分类清空原记录。"
      : "";
  }
  if (showHourlyTrend) {
    renderTokenHourlyChart(source.hours || []);
  } else {
    $("#tokenHourlyChart").innerHTML = "";
  }
  renderTokenDailyChart(source.dateRows || []);
  renderTokenDailyTable(source.dateRows || []);
  renderTokenProviderTable(source.providers || []);
  renderTokenTaskTable(source.tasks || [], source.source);
  renderTokenRecentTable(source.recent || [], source.source);
  renderTokenExternalSessionTable(source.sessions || []);
  renderTokenExternalRecentTable(source.recent || []);
  renderTokenMemoryPluginSummary(source.source === "memory" ? scope : { available: false }, stats.memory_plugin || {});
  renderTokenMemoryPluginTaskTable(source.source === "memory" ? (source.tasks || []) : [], source.source === "memory" && source.available !== false);
  renderTokenMemoryPluginProviderTable(source.source === "memory" ? (source.providers || []) : [], source.source === "memory" && source.available !== false);
  renderTokenMemoryPluginRecentTable(source.source === "memory" ? (source.recent || []) : [], source.source === "memory" && source.available !== false);
}

export function renderTokenBalanceStatus(balance = {}) {
  const box = $("#tokenBalanceStatus");
  const card = $("#tokenBalanceCard");
  if (!box || !card) return;
  const enabled = Boolean(balance.enabled);
  const configured = Boolean(balance.configured);
  const manualConfigured = Boolean(balance.manual_configured);
  const autoDiscoveryAvailable = Boolean(balance.auto_discovery_available);
  const available = Boolean(balance.available);
  const amount = balance.amount == null ? null : Number(balance.amount);
  const percent = balance.remaining_percent == null ? null : Number(balance.remaining_percent);
  const currency = String(balance.currency_label || "元");
  const tierLabels = { normal: "充足", low: "偏低", critical: "危急", unknown: "未知" };
  const tier = tierLabels[String(balance.tier || "unknown")] || "未知";
  const amountText = amount == null || !Number.isFinite(amount)
    ? "等待首次成功拉取"
    : `${amount.toLocaleString("zh-CN", { maximumFractionDigits: 4 })}${currency}${percent != null && Number.isFinite(percent) ? ` · 约剩 ${Math.max(0, percent).toFixed(0)}%` : ""}`;
  let note = "余额感知未开启。可在配置 → 功能开关 → 环境感知 → 余额与补给中启用。";
  if (enabled && !configured) note = "余额感知已开启，但没有可自动复用的 Provider，也没有填写自定义余额接口。";
  else if (enabled && configured && !available) note = balance.last_error
    ? `最近拉取失败：${String(balance.last_error)}`
    : (manualConfigured ? "正在通过自定义余额接口首次拉取。" : "正在从 AstrBot Provider 自动发现余额查询方式。");
  else if (available) {
    const modeText = balance.query_mode === "auto"
      ? `自动查询${balance.source_label ? ` · ${String(balance.source_label)}` : ""}`
      : "自定义接口";
    note = `${modeText} · 最近成功 ${formatRecentTime(balance.last_success_at)}${balance.next_check_at ? ` · 下次检查 ${formatRecentTime(balance.next_check_at)}` : ""}`;
  }
  box.innerHTML = `
    <div class="token-plugin-note">
      <b>${escapeHtml(amountText)}</b>
      <span>${escapeHtml(note)}</span>
    </div>
    <div class="token-plugin-stats">
      ${tokenMetricCard("感知开关", enabled ? "已开启" : "未开启")}
      ${tokenMetricCard("查询方式", manualConfigured ? "自定义接口" : autoDiscoveryAvailable ? "自动发现" : "不可用")}
      ${tokenMetricCard("当前状态", available ? tier : "暂无数据")}
      ${tokenMetricCard("最近检查", balance.last_check_at ? formatRecentTime(balance.last_check_at) : "尚未检查")}
      ${tokenMetricCard("连续失败", formatNumber(balance.consecutive_failures || 0))}
    </div>
  `;
}

export function normalizedTokenSource(value = state.tokenSource) {
  const source = String(value || "companion").trim().toLowerCase();
  return ["companion", "memory", "main"].includes(source) ? source : "companion";
}

export function ensureTokenDateForRows(rows, today) {
  const dates = (Array.isArray(rows) ? rows : []).map((item) => String(item.key || "")).filter(Boolean);
  if (!state.tokenDate || !dates.includes(state.tokenDate)) {
    state.tokenDate = dates.includes(today) ? today : (dates[dates.length - 1] || today);
  }
  return dates;
}

export function tokenSelectedScope(stats) {
  const source = normalizedTokenSource();
  state.tokenSource = source;
  const view = state.tokenView || "today";
  const today = stats.budget?.day || todayKeyLocal();
  if (source === "memory") return tokenMemorySourceScope(stats, view, today);
  if (source === "main") return tokenMainSourceScope(stats, view, today);
  return tokenCompanionSourceScope(stats, view, today);
}

export function tokenCompanionSourceScope(stats, view, today) {
  const dayRows = stats.by_day_detail || stats.by_day || [];
  ensureTokenDateForRows(dayRows, today);
  const scope = tokenScopeData(stats);
  return {
    source: "companion",
    shortLabel: "陪伴插件",
    title: "陪伴插件 Token",
    description: "本页统计陪伴插件内部模型任务，今日限额只作用于这一侧。",
    scope,
    totals: scope.totals || {},
    providers: scope.providers || [],
    tasks: scope.tasks || [],
    dateRows: dayRows,
    hours: scope.hours || [],
    recent: scope.recent || [],
    available: true,
  };
}

export function tokenMemorySourceScope(stats, view, today) {
  const plugin = stats.memory_plugin || {};
  const displayName = plugin.display_name || "记忆插件";
  const dayRows = plugin.by_day_detail || plugin.by_day || [];
  ensureTokenDateForRows(dayRows, today);
  const available = plugin.available !== false;
  if (view === "total") {
    return {
      source: "memory",
      shortLabel: displayName,
      title: `${displayName} Token`,
      description: "只读展示记忆插件自身模型消耗，不计入陪伴插件每日限额。",
      scope: {
        mode: "total",
        label: `${displayName}累计`,
        displayName,
        available,
        totals: plugin.totals || {},
      },
      totals: plugin.totals || {},
      providers: plugin.by_provider || [],
      tasks: plugin.by_task || [],
      dateRows: dayRows,
      hours: plugin.by_hour || [],
      recent: plugin.recent || [],
      available,
      unavailableReason: plugin.reason || "",
    };
  }
  const selectedDay = view === "date" ? state.tokenDate : today;
  const day = dayRows.find((item) => String(item.key || "") === selectedDay) || { key: selectedDay };
  return {
    source: "memory",
    shortLabel: displayName,
    title: selectedDay === today ? `${displayName}今日 Token` : `${displayName} ${selectedDay}`,
    description: "只读展示记忆插件自身模型消耗，不计入陪伴插件每日限额。",
    scope: {
      mode: view,
      label: selectedDay === today ? `${displayName}今日` : `${displayName}同日`,
      displayName,
      available,
      totals: day,
    },
    totals: day,
    providers: day.providers || [],
    tasks: day.tasks || [],
    dateRows: dayRows,
    hours: (plugin.by_hour || []).filter((item) => String(item.key || "").startsWith(`${selectedDay}T`)),
    recent: (plugin.recent || []).filter((item) => recentItemDayKey(item) === selectedDay),
    available,
    unavailableReason: plugin.reason || "",
  };
}

export function tokenMainSourceScope(stats, view, today) {
  const external = stats.external || {};
  const dayRows = external.by_day_detail || external.by_day || [];
  ensureTokenDateForRows(dayRows, today);
  if (view === "total") {
    return {
      source: "main",
      shortLabel: "LLM 主链",
      title: "LLM 主链 Token",
      description: "AstrBot 普通私聊/群聊主回复链路统计，独立于陪伴插件内部任务。",
      scope: { mode: "total", label: "LLM 主链累计", totals: external.totals || {} },
      totals: external.totals || {},
      providers: external.by_provider || [],
      tasks: external.by_task || [],
      sessions: external.by_session || [],
      dateRows: dayRows,
      hours: external.by_hour || [],
      recent: external.recent || [],
      chartSecondaryRows: external.by_session || [],
      secondaryChartEmpty: "暂无主链会话消耗数据",
      secondaryChartLabeler: (item) => tokenSessionLabel(item.key),
      available: true,
    };
  }
  const selectedDay = view === "date" ? state.tokenDate : today;
  const day = dayRows.find((item) => String(item.key || "") === selectedDay) || { key: selectedDay };
  return {
    source: "main",
    shortLabel: "LLM 主链",
    title: selectedDay === today ? "LLM 主链今日 Token" : `LLM 主链 ${selectedDay}`,
    description: "AstrBot 普通私聊/群聊主回复链路统计，独立于陪伴插件内部任务。",
    scope: { mode: view, label: selectedDay === today ? "LLM 主链今日" : "LLM 主链同日", totals: day },
    totals: day,
    providers: day.providers || [],
    tasks: day.tasks || [],
    sessions: day.sessions || [],
    dateRows: dayRows,
    hours: (external.by_hour || []).filter((item) => String(item.key || "").startsWith(`${selectedDay}T`)),
    recent: (external.recent || []).filter((item) => recentItemDayKey(item) === selectedDay),
    chartSecondaryRows: day.sessions || [],
    secondaryChartEmpty: "暂无主链会话消耗数据",
    secondaryChartLabeler: (item) => tokenSessionLabel(item.key),
    available: true,
  };
}

export function tokenSourceComparison(stats, currentSource = {}) {
  const memory = stats.memory_plugin || {};
  const main = stats.external || {};
  const view = state.tokenView || "today";
  const today = stats.budget?.day || todayKeyLocal();
  const selectedDay = view === "date" ? state.tokenDate : today;
  const pickTotals = (root, dayRows) => {
    if (view === "total") return root?.totals || {};
    const rows = Array.isArray(dayRows) ? dayRows : [];
    return rows.find((item) => String(item.key || "") === selectedDay) || { key: selectedDay };
  };
  return [
    ["陪伴插件", pickTotals(stats, stats.by_day_detail || stats.by_day || [])],
    [memory.display_name || "记忆插件", memory.available === false ? null : pickTotals(memory, memory.by_day_detail || memory.by_day || [])],
    ["LLM 主链", pickTotals(main, main.by_day_detail || main.by_day || [])],
  ].map(([label, totals]) => ({
    label: currentSource.source === "companion" && label === "陪伴插件"
      ? "当前来源"
      : currentSource.source === "memory" && label === (memory.display_name || "记忆插件")
        ? "当前来源"
        : currentSource.source === "main" && label === "LLM 主链"
          ? "当前来源"
          : label,
    value: totals ? Number(totals.total_tokens || 0) : null,
  }));
}

export function renderTokenSourceVisibility(source) {
  const sourceKey = source.source || "companion";
  document.querySelectorAll("[data-token-source]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tokenSource === sourceKey);
  });
  const setText = (selector, text) => {
    const node = $(selector);
    if (node) node.textContent = text;
  };
  setText("#tokenProviderChartTitle", `${source.shortLabel} Provider 排行`);
  setText("#tokenTaskChartTitle", sourceKey === "main" ? "主链会话排行" : `${source.shortLabel}任务排行`);
  setText("#tokenDailyChartTitle", `${source.shortLabel}每日统计`);
  setText("#tokenDailyTableTitle", `${source.shortLabel}每日明细`);
  setText("#tokenProviderTableTitle", `${source.shortLabel} Provider 明细`);
  setText("#tokenTaskTableTitle", sourceKey === "main" ? "主链任务明细" : `${source.shortLabel}任务明细`);
  setText("#tokenRecentTableTitle", `${source.shortLabel}最近调用`);
  const showMain = sourceKey === "main";
  const showMemory = sourceKey === "memory";
  $("#tokenTaskTableCard").hidden = false;
  $("#tokenRecentTableCard").hidden = showMain;
  $("#tokenExternalSessionCard").hidden = !showMain;
  $("#tokenExternalRecentCard").hidden = !showMain;
  $("#tokenMemoryPluginSummaryCard").hidden = !showMemory;
  $("#tokenMemoryPluginDetailCard").hidden = true;
  $("#tokenMemoryPluginRecentCard").hidden = true;
}

export function tokenSummaryBoard({
  source,
  scope,
  totalTokens,
  comparison,
  totals,
  calls,
  errors,
  estimatedRatio,
  cachedTokens,
  cacheReadTokens,
  cacheWriteTokens,
  cachedRatio,
  dailyLimit,
  dailyUsed,
  dailyRemaining,
  softLimit,
  softRemaining,
  softEnabled,
  softActive,
  deferredCalls,
  exemptUsed,
}) {
  if (source?.available === false) {
    return `<section class="token-summary-board"><article class="token-primary-card"><span>${escapeHtml(source.title)}</span><b>统计不可用</b><small>${escapeHtml(source.unavailableReason || "当前记忆统计来源未连接")}</small><small>没有读取到用量，不能按0次调用或0 Token判断。</small></article><div class="token-metric-grid">${(comparison || []).map((item) => tokenMetricCard(item.label, item.value == null ? "未接入" : formatNumber(item.value))).join("")}</div></section>`;
  }
  const avgTokens = Math.round(Number(totals.avg_tokens || 0));
  const avgLatency = Math.round(Number(totals.avg_latency_ms || 0));
  const isCompanion = source?.source === "companion";
  const hardPercent = dailyLimit > 0 ? Math.min(100, Math.round((dailyUsed / Math.max(1, dailyLimit)) * 100)) : 0;
  const remainingValue = dailyRemaining == null
    ? (dailyLimit > 0 ? Math.max(0, dailyLimit - dailyUsed) : null)
    : dailyRemaining;
  const softUsed = softEnabled && softLimit > 0 && softRemaining != null ? Math.max(0, softLimit - softRemaining) : 0;
  const softPercent = softEnabled && softLimit > 0 ? Math.min(100, Math.round((softUsed / Math.max(1, softLimit)) * 100)) : 0;
  const scopeNote = isCompanion && scope.isToday
    ? (dailyLimit > 0 ? `硬限额 ${formatCompactNumber(dailyLimit)} · 剩 ${formatCompactNumber(remainingValue)}` : "今日不限额")
    : `${scope.mode === "total" ? "当前留存累计" : "选定日期"} · ${formatNumber(calls)} 次调用`;
  const hasKnownCacheStats = totalTokens > 0 && estimatedRatio < 1;
  return `
    <section class="token-summary-board">
      <article class="token-primary-card">
        <span>${escapeHtml(source?.title || scope.label)}</span>
        <b>${escapeHtml(formatNumber(totalTokens))}</b>
        <small>${escapeHtml(source?.description || scopeNote)}</small>
        <small>${escapeHtml(scopeNote)}</small>
        ${isCompanion && scope.isToday && dailyLimit > 0 ? `<div class="token-progress"><i style="width:${hardPercent}%"></i></div>` : ""}
      </article>
      <article class="token-budget-card ${isCompanion ? "" : "is-source-note"}">
        <div class="token-budget-head">
          <span>${escapeHtml(isCompanion ? "预算" : "来源说明")}</span>
          <b>${escapeHtml(isCompanion && scope.isToday && dailyLimit > 0 ? `${hardPercent}%` : source?.shortLabel || "概览")}</b>
        </div>
        ${isCompanion ? `<div class="token-budget-lines">
          ${tokenBudgetLine("今日上限", dailyLimit > 0 ? formatCompactNumber(dailyLimit) : "不限", hardPercent, scope.isToday && dailyLimit > 0)}
          ${tokenBudgetLine("今日剩余", remainingValue == null ? "不限" : formatCompactNumber(remainingValue), dailyLimit > 0 ? 100 - hardPercent : 0, scope.isToday && dailyLimit > 0)}
          ${tokenBudgetLine(
            softActive ? "软限额接管" : "每日软限额",
            softEnabled && softLimit > 0 ? (softActive ? `暂缓 ${formatNumber(deferredCalls)} 次` : `剩 ${formatCompactNumber(softRemaining)}`) : "关闭",
            softPercent,
            softEnabled && softLimit > 0,
            softActive ? "warn" : "",
          )}
        </div>` : `<p class="token-source-note">${escapeHtml(source?.source === "memory" ? "记忆插件统计来自桥接接口，仅用于观察记忆整理、检索和索引成本。" : "LLM 主链统计来自 AstrBot 普通回复请求，不参与陪伴插件内部任务排行。")}</p>`}
      </article>
      <div class="token-metric-grid">
        ${(comparison || []).map((item) => tokenMetricCard(item.label, item.value == null ? "未接入" : formatNumber(item.value))).join("")}
        ${isCompanion ? tokenMetricCard("今日免计限额 Token", formatCompactNumber(exemptUsed)) : ""}
        ${hasKnownCacheStats ? tokenMetricCard("缓存命中", `${formatCompactNumber(cachedTokens || cacheReadTokens)} · ${Math.round(cachedRatio * 100)}%`) : ""}
        ${cacheReadTokens > 0 || cacheWriteTokens > 0 ? tokenMetricCard("缓存读 / 写", `${formatCompactNumber(cacheReadTokens)} / ${formatCompactNumber(cacheWriteTokens)}`) : ""}
        ${tokenMetricCard("调用次数", formatNumber(calls))}
        ${tokenMetricCard("平均 Token", formatNumber(avgTokens))}
        ${tokenMetricCard("平均延迟", `${formatNumber(avgLatency)} ms`)}
        ${tokenMetricCard("估算 / 失败", `${Math.round(estimatedRatio * 100)}% · ${formatNumber(errors)}`)}
      </div>
    </section>
  `;
}

export function tokenBudgetLine(label, value, percent, active, tone = "") {
  return `
    <div class="token-budget-line ${active ? "active" : "off"} ${escapeHtml(tone)}">
      <span>${escapeHtml(label)}</span>
      <b>${escapeHtml(value)}</b>
      <em><i style="width:${Math.max(0, Math.min(100, Number(percent || 0)))}%"></i></em>
    </div>
  `;
}

export function tokenMetricCard(label, value) {
  return `
    <span class="token-metric-card">
      <small>${escapeHtml(label)}</small>
      <b>${escapeHtml(value)}</b>
    </span>
  `;
}

export function externalTokenScopeData(stats, pluginScope) {
  const external = stats.external || {};
  const view = state.tokenView || "today";
  const today = stats.budget?.day || todayKeyLocal();
  if (view === "total") {
    return {
      label: "非插件累计",
      totals: external.totals || {},
      sessions: external.by_session || [],
      recent: external.recent || [],
    };
  }
  const selectedDay = pluginScope?.mode === "date" ? state.tokenDate : today;
  const dayRows = external.by_day_detail || external.by_day || [];
  const day = dayRows.find((item) => String(item.key || "") === selectedDay) || { key: selectedDay };
  return {
    label: selectedDay === today ? "非插件今日" : "非插件同日",
    totals: day,
    sessions: day.sessions || [],
    recent: (external.recent || []).filter((item) => recentItemDayKey(item) === selectedDay),
  };
}

export function memoryPluginTokenScopeData(stats, pluginScope) {
  const plugin = stats.memory_plugin || {};
  const view = state.tokenView || "today";
  const today = stats.budget?.day || todayKeyLocal();
  const displayName = plugin.display_name || "我会牢牢记住你";
  const available = plugin.available !== false;
  if (view === "total") {
    return {
      mode: "total",
      label: `${displayName}累计`,
      displayName,
      available,
      totals: plugin.totals || {},
      providers: plugin.by_provider || [],
      tasks: plugin.by_task || [],
      recent: plugin.recent || [],
    };
  }
  const selectedDay = pluginScope?.mode === "date" ? state.tokenDate : today;
  const dayRows = plugin.by_day_detail || plugin.by_day || [];
  const day = dayRows.find((item) => String(item.key || "") === selectedDay) || { key: selectedDay };
  return {
    mode: pluginScope?.mode || "today",
    label: selectedDay === today ? `${displayName}今日` : `${displayName}同日`,
    displayName,
    available,
    totals: day,
    providers: day.providers || [],
    tasks: day.tasks || [],
    recent: (plugin.recent || []).filter((item) => recentItemDayKey(item) === selectedDay),
  };
}

export function tokenScopeData(stats) {
  const view = state.tokenView || "today";
  const today = stats.budget?.day || todayKeyLocal();
  const dayRows = stats.by_day_detail || stats.by_day || [];
  const availableDates = dayRows.map((item) => String(item.key || "")).filter(Boolean);
  if (!state.tokenDate || !availableDates.includes(state.tokenDate)) {
    state.tokenDate = availableDates.includes(today) ? today : (availableDates[availableDates.length - 1] || today);
  }
  if (view === "total") {
    return {
      mode: "total",
      label: "累计 Token",
      totals: stats.totals || {},
      providers: stats.by_provider || [],
      tasks: stats.by_task || [],
      hours: stats.by_hour || [],
      recent: stats.recent || [],
      isToday: false,
    };
  }
  const selectedDay = view === "date" ? state.tokenDate : today;
  const day = dayRows.find((item) => String(item.key || "") === selectedDay) || { key: selectedDay };
  const recent = (stats.recent || []).filter((item) => recentItemDayKey(item) === selectedDay);
  const hours = (stats.by_hour || []).filter((item) => String(item.key || "").startsWith(`${selectedDay}T`));
  return {
    mode: view,
    label: selectedDay === today ? "今日 Token" : `${selectedDay} Token`,
    totals: day,
    providers: day.providers || [],
    tasks: day.tasks || [],
    hours,
    recent,
    isToday: selectedDay === today,
  };
}

export function renderTokenToolbar(stats, sourceDateRows = null) {
  const dayRows = Array.isArray(sourceDateRows) ? sourceDateRows : (stats.by_day_detail || stats.by_day || []);
  const dates = dayRows.map((item) => String(item.key || "")).filter(Boolean);
  const fallbackDate = todayKeyLocal();
  const select = $("#tokenDateSelect");
  if (select) {
    select.innerHTML = dates.length
      ? dates.slice().reverse().map((date) => `<option value="${escapeHtml(date)}" ${date === state.tokenDate ? "selected" : ""}>${escapeHtml(date)}</option>`).join("")
      : `<option value="${escapeHtml(fallbackDate)}">${escapeHtml(fallbackDate)}</option>`;
    select.disabled = state.tokenView !== "date";
  }
  document.querySelectorAll("[data-token-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tokenView === state.tokenView);
  });
  document.querySelectorAll("[data-token-source]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tokenSource === normalizedTokenSource());
  });
}

export function todayKeyLocal() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function recentItemDayKey(item) {
  const ts = Number(item?.ts || 0);
  if (ts > 0) {
    const date = new Date(ts * 1000);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
  return String(item?.time || "").slice(0, 10);
}

export function renderTokenChart(selector, rows, emptyText, labeler) {
  const topRows = rows.slice(0, 8);
  const max = Math.max(1, ...topRows.map((item) => Number(item.total_tokens || 0)));
  $(selector).innerHTML = topRows.length
    ? topRows.map((item) => {
      const tokens = Number(item.total_tokens || 0);
      const pct = Math.max(2, Math.round((tokens / max) * 100));
      return `
        <div class="token-rank-row">
          <span title="${escapeHtml(labeler(item))}">${escapeHtml(labeler(item))}</span>
          <div class="meter"><i style="width:${pct}%"></i></div>
          <b>${escapeHtml(formatNumber(tokens))}</b>
        </div>
      `;
    }).join("")
    : `<div class="empty small">${escapeHtml(emptyText)}</div>`;
}

export function renderTokenHourlyChart(rows) {
  const normalized = rows.slice(-48);
  const max = Math.max(1, ...normalized.map((item) => Number(item.total_tokens || 0)));
  $("#tokenHourlyChart").innerHTML = normalized.length
    ? tokenHourlySvg(normalized, max)
    : `<div class="empty small">暂无小时趋势数据</div>`;
}

export function renderTokenDailyChart(rows) {
  const normalized = rows.slice(-30);
  const max = Math.max(1, ...normalized.map((item) => Number(item.total_tokens || 0)));
  $("#tokenDailyChart").innerHTML = normalized.length
    ? tokenDailySvg(normalized, max)
    : `<div class="empty small">暂无每日统计数据</div>`;
}

export function tokenDailySvg(rows, max) {
  const chartHeight = 176;
  const chartTop = 12;
  const chartBottom = 36;
  const axisLeft = 74;
  const rightPad = 18;
  const barStep = 34;
  const width = Math.max(760, axisLeft + rightPad + rows.length * barStep);
  const height = chartHeight + chartTop + chartBottom;
  const plotHeight = chartHeight - chartTop;
  const plotBottom = chartTop + plotHeight;
  const labelStep = Math.max(1, Math.ceil(rows.length / 10));
  const ticks = [1, 0.75, 0.5, 0.25, 0];
  const grid = ticks.map((ratio) => {
    const y = chartTop + (1 - ratio) * plotHeight;
    const value = Math.round(max * ratio);
    return `
      <line class="token-grid-line" x1="${axisLeft}" y1="${y}" x2="${width - rightPad}" y2="${y}"></line>
      <text class="token-axis-label y" x="${axisLeft - 10}" y="${y + 4}">${escapeHtml(formatNumber(value))}</text>
    `;
  }).join("");
  const bars = rows.map((item, index) => {
    const tokens = Number(item.total_tokens || 0);
    const barHeight = Math.max(tokens > 0 ? 4 : 0, Math.round((tokens / max) * (plotHeight - 4)));
    const x = axisLeft + index * barStep + 8;
    const y = plotBottom - barHeight;
    const label = String(item.key || "");
    const labelNode = index % labelStep === 0 || index === rows.length - 1
      ? `<text class="token-axis-label x" x="${x + 8}" y="${height - 8}">${escapeHtml(label.slice(5))}</text>`
      : "";
    return `
      <g class="token-hour-group">
        <title>${escapeHtml(label)} · ${escapeHtml(formatNumber(tokens))} token · ${escapeHtml(item.calls || 0)} 次</title>
        <rect x="${x}" y="${y}" width="18" height="${barHeight}" rx="5"></rect>
        ${labelNode}
      </g>
    `;
  }).join("");
  return `
    <svg class="token-hourly-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="每日 Token 消耗趋势">
      <line class="token-axis-line" x1="${axisLeft}" y1="${chartTop}" x2="${axisLeft}" y2="${plotBottom}"></line>
      <line class="token-axis-line" x1="${axisLeft}" y1="${plotBottom}" x2="${width - rightPad}" y2="${plotBottom}"></line>
      ${grid}
      ${bars}
    </svg>
  `;
}

export function tokenHourlySvg(rows, max) {
  const chartHeight = 176;
  const chartTop = 12;
  const chartBottom = 34;
  const axisLeft = 74;
  const rightPad = 18;
  const barStep = 30;
  const width = Math.max(760, axisLeft + rightPad + rows.length * barStep);
  const height = chartHeight + chartTop + chartBottom;
  const plotHeight = chartHeight - chartTop;
  const plotBottom = chartTop + plotHeight;
  const labelStep = Math.max(1, Math.ceil(rows.length / 12));
  const ticks = [1, 0.75, 0.5, 0.25, 0];
  const grid = ticks.map((ratio) => {
    const y = chartTop + (1 - ratio) * plotHeight;
    const value = Math.round(max * ratio);
    return `
      <line class="token-grid-line" x1="${axisLeft}" y1="${y}" x2="${width - rightPad}" y2="${y}"></line>
      <text class="token-axis-label y" x="${axisLeft - 10}" y="${y + 4}">${escapeHtml(formatNumber(value))}</text>
    `;
  }).join("");
  const bars = rows.map((item, index) => {
      const tokens = Number(item.total_tokens || 0);
    const barHeight = Math.max(tokens > 0 ? 4 : 0, Math.round((tokens / max) * (plotHeight - 4)));
      const label = formatHourKey(item.key);
    const x = axisLeft + index * barStep + 7;
    const y = plotBottom - barHeight;
    const labelNode = index % labelStep === 0 || index === rows.length - 1
      ? `<text class="token-axis-label x" x="${x + 8}" y="${height - 8}">${escapeHtml(label.slice(-5))}</text>`
      : "";
      return `
      <g class="token-hour-group">
        <title>${escapeHtml(label)} · ${escapeHtml(formatNumber(tokens))} token · ${escapeHtml(item.calls || 0)} 次</title>
        <rect x="${x}" y="${y}" width="16" height="${barHeight}" rx="5"></rect>
        ${labelNode}
      </g>
      `;
  }).join("");
  return `
    <svg class="token-hourly-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="近 48 小时 Token 消耗趋势">
      <line class="token-axis-line" x1="${axisLeft}" y1="${chartTop}" x2="${axisLeft}" y2="${plotBottom}"></line>
      <line class="token-axis-line" x1="${axisLeft}" y1="${plotBottom}" x2="${width - rightPad}" y2="${plotBottom}"></line>
      ${grid}
      ${bars}
    </svg>
  `;
}

export function renderTokenProviderTable(rows) {
  $("#tokenProviderTable").innerHTML = tokenTable(
    ["Provider", "总 Token", "缓存", "输入", "输出", "调用", "估算", "平均延迟"],
    rows,
    (item) => [
      item.key || "default",
      formatNumber(item.total_tokens),
      tokenCacheText(item),
      formatNumber(item.prompt_tokens),
      formatNumber(item.completion_tokens),
      formatNumber(item.calls),
      `${Math.round(Number(item.estimated_ratio || 0) * 100)}%`,
      `${formatNumber(Math.round(Number(item.avg_latency_ms || 0)))} ms`,
    ],
    "暂无 Provider 明细"
  );
}

export function renderTokenTaskTable(rows) {
  $("#tokenTaskTable").innerHTML = tokenTable(
    ["任务", "累计 Token", "缓存", "输入", "输出", "累计调用", "失败", "平均 Token"],
    rows,
    (item) => [
      tokenTaskLabel(item.key),
      formatNumber(item.total_tokens),
      tokenCacheText(item),
      formatNumber(item.prompt_tokens),
      formatNumber(item.completion_tokens),
      formatNumber(item.calls),
      formatNumber(item.errors),
      formatNumber(Math.round(Number(item.avg_tokens || 0))),
    ],
    "暂无任务明细"
  );
}

export function renderTokenDailyTable(rows) {
  $("#tokenDailyTable").innerHTML = tokenTable(
    ["日期", "总 Token", "调用", "失败", "主要任务", "主要 Provider"],
    rows.slice().reverse(),
    (item) => [
      item.key || "-",
      formatNumber(item.total_tokens),
      formatNumber(item.calls),
      formatNumber(item.errors),
      tokenTopList(item.tasks, tokenTaskLabel),
      tokenTopList(item.providers, (key) => key || "default"),
    ],
    "暂无每日明细"
  );
}

export function tokenTopList(rows, labeler) {
  if (!Array.isArray(rows) || !rows.length) return "-";
  return rows.slice(0, 3).map((item) => `${labeler(item.key)} ${formatCompactNumber(item.total_tokens)}`).join(" / ");
}

export function tokenSessionLabel(raw) {
  const text = String(raw || "").trim();
  if (!text) return "-";
  const parsed = parseTokenSessionId(text);
  if (parsed.type === "private") {
    const user = state.users.find((item) => tokenIdentityMatches(item, parsed.id, text, "user_id"));
    const name = user?.display_name || user?.nickname || user?.name || parsed.id || compactTokenSession(text);
    const suffix = parsed.id && !String(name).includes(parsed.id) ? ` · ${tailId(parsed.id)}` : "";
    return `私聊 · ${name}${suffix}`;
  }
  if (parsed.type === "group") {
    const group = state.groups.find((item) => tokenIdentityMatches(item, parsed.id, text, "group_id"));
    const name = group?.display_name || group?.name || group?.group_name || group?.title || parsed.id || compactTokenSession(text);
    const suffix = parsed.id && !String(name).includes(parsed.id) ? ` · ${tailId(parsed.id)}` : "";
    return `群聊 · ${name}${suffix}`;
  }
  return compactTokenSession(text);
}

export function parseTokenSessionId(text) {
  const raw = String(text || "");
  const privateMatch = raw.match(/(?:^|:)(?:FriendMessage|PrivateMessage|Friend|Private):([^:]+)/i);
  if (privateMatch) return { type: "private", id: cleanTokenSessionId(privateMatch[1]) };
  const groupMatch = raw.match(/(?:^|:)(?:GroupMessage|Group):([^:]+)/i);
  if (groupMatch) return { type: "group", id: cleanTokenSessionId(groupMatch[1]) };
  const lower = raw.toLowerCase();
  const numbers = raw.match(/\d{5,}/g) || [];
  if (lower.includes("friend") || lower.includes("private")) return { type: "private", id: numbers[numbers.length - 1] || "" };
  if (lower.includes("group")) return { type: "group", id: numbers[numbers.length - 1] || "" };
  return { type: "", id: numbers[numbers.length - 1] || "" };
}

export function cleanTokenSessionId(value) {
  const text = String(value || "").trim();
  const decoded = (() => {
    try {
      return decodeURIComponent(text);
    } catch {
      return text;
    }
  })();
  const numeric = decoded.match(/\d{5,}/);
  if (numeric) return numeric[0];
  return decoded.replace(/^[^\w]+|[^\w]+$/g, "").slice(0, 80);
}

export function tokenIdentityMatches(item, id, rawSession, idKey) {
  if (!item || typeof item !== "object") return false;
  const target = String(id || "").trim();
  const raw = String(rawSession || "").toLowerCase();
  const primary = String(item[idKey] || "").trim();
  if (target && primary && primary === target) return true;
  if (target && String(item.umo || "").includes(target)) return true;
  if (primary && raw.includes(primary.toLowerCase())) return true;
  const aliases = Array.isArray(item.alias_user_ids) ? item.alias_user_ids : [];
  return Boolean(target && aliases.some((alias) => String(alias || "").trim() === target));
}

export function compactTokenSession(text) {
  const raw = String(text || "").trim();
  if (!raw) return "-";
  const parsed = parseTokenSessionId(raw);
  if (parsed.id) {
    if (parsed.type === "private") return `私聊 · ${tailId(parsed.id)}`;
    if (parsed.type === "group") return `群聊 · ${tailId(parsed.id)}`;
  }
  const parts = raw.split(":").filter(Boolean);
  const tail = parts.slice(-2).join(":") || raw;
  return tail.length > 30 ? `${tail.slice(0, 14)}...${tail.slice(-10)}` : tail;
}

export function tailId(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.length > 8 ? `*${text.slice(-4)}` : text;
}

export function renderTokenRecentTable(rows) {
  $("#tokenRecentTable").innerHTML = tokenTable(
    ["时间", "任务", "Provider", "Token", "缓存", "延迟", "状态"],
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
    "暂无最近调用"
  );
}

export function renderTokenExternalSessionTable(rows) {
  $("#tokenExternalSessionTable").innerHTML = tokenTable(
    ["会话", "总 Token", "缓存", "调用", "失败", "平均延迟"],
    rows,
    (item) => [
      tokenSessionLabel(item.key),
      formatNumber(item.total_tokens),
      tokenCacheText(item),
      formatNumber(item.calls),
      formatNumber(item.errors),
      `${formatNumber(Math.round(Number(item.avg_latency_ms || 0)))} ms`,
    ],
    "暂无 AstrBot 主链会话统计"
  );
}

export function renderTokenExternalRecentTable(rows) {
  $("#tokenExternalRecentTable").innerHTML = tokenTable(
    ["时间", "会话", "发送者", "类型", "Provider", "Token", "缓存", "延迟", "状态"],
    rows,
    (item) => [
      formatRecentTime(item.ts, item.time),
      tokenSessionLabel(item.session),
      item.sender || "-",
      item.message_type === "private" ? "私聊" : (item.message_type === "group" ? "群聊" : "-"),
      item.provider || "default",
      `${formatNumber(item.total_tokens)}${item.estimated ? " 估" : ""}`,
      tokenCacheText(item),
      `${formatNumber(Math.round(Number(item.elapsed_ms || item.latency_ms || 0)))} ms`,
      item.success ? "成功" : `失败 ${item.error || ""}`.trim(),
    ],
    "暂无 AstrBot 主链最近对话"
  );
}

export function renderTokenMemoryPluginSummary(scope, plugin) {
  const box = $("#tokenMemoryPluginSummary");
  if (!box) return;
  const available = scope?.available !== false;
  if (!available) {
    box.innerHTML = `
      <div class="empty small">
        未检测到可读取的“${escapeHtml(plugin?.display_name || "我会牢牢记住你")}”Token 统计。
        ${plugin?.reason ? `原因：${escapeHtml(plugin.reason)}` : ""}
      </div>
    `;
    return;
  }
  const totals = scope?.totals || {};
  const displayName = scope?.displayName || plugin?.display_name || "我会牢牢记住你";
  const totalTokens = Number(totals.total_tokens || 0);
  const calls = Number(totals.calls || 0);
  const errors = Number(totals.errors || 0);
  const avgTokens = Math.round(Number(totals.avg_tokens || 0));
  const estimatedRatio = Math.round(Number(totals.estimated_ratio || 0) * 100);
  const updatedAt = plugin?.updated_at ? `最近更新：${plugin.updated_at}` : "还没有统计更新时间";
  box.innerHTML = `
    <div class="token-plugin-note">
      <b>${escapeHtml(displayName)}</b>
      <span>${escapeHtml(plugin?.note || "仅展示记忆插件自身模型消耗，不计入陪伴插件每日 Token 限额。")}</span>
    </div>
    <div class="token-plugin-stats">
      ${tokenMetricCard("Token", formatNumber(totalTokens))}
      ${tokenMetricCard("调用次数", formatNumber(calls))}
      ${tokenMetricCard("平均 Token", formatNumber(avgTokens))}
      ${tokenMetricCard("估算 / 失败", `${estimatedRatio}% · ${formatNumber(errors)}`)}
    </div>
    <p class="muted small">${escapeHtml(updatedAt)}</p>
  `;
}
