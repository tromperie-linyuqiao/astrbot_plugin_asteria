/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {memoryOption} from './editors.js';
import {$,CORE_MEMORY_KIND_LABELS,CORE_MEMORY_SCOPE_LABELS,asteriaWorkspaceState,coreHistory,state} from './state.js';
import {_rerenderTopology,_topologyNodeKey} from './topology.js';
import {activeSecondaryNav,escapeHtml,formatTime,loadingState,secondaryNavItems,showToast} from './workspace.js';

export async function loadPersonaState() {
  const panel = $("#personaStatePanel");
  if (!panel) return;
  panel.innerHTML = `<div class="persona-loading">正在读取互动协同数据...</div>`;
  let data;
  try {
    data = await apiGet("/persona-state");
    try {
      const traces = await apiGet("/emotion/traces?scope=private&limit=20");
      data.emotion_trace_diagnostics = traces?.result || traces || {};
    } catch (_) {
      data.emotion_trace_diagnostics = { state: "degraded", items: [], error_code: "trace_summary_unavailable" };
    }
  } catch (err) {
    panel.innerHTML = `<div class="persona-error">读取失败：${escapeHtml(err?.message || "未知错误")}</div>`;
    return;
  }
  panel.innerHTML = renderPersonaState(data || {});
  panel.querySelectorAll("[data-memory-emotion-trace]").forEach((button) => {
    button.addEventListener("click", async () => {
      const traceId = String(button.dataset.memoryEmotionTrace || "");
      const target = panel.querySelector("[data-memory-emotion-trace-detail]");
      if (!traceId || !target) return;
      target.textContent = "正在读取脱敏链路...";
      try {
        const response = await apiGet(`/emotion/trace?trace_id=${encodeURIComponent(traceId)}&scope=private`);
        const result = response?.result || response || {};
        target.textContent = JSON.stringify(result, null, 2);
      } catch (error) {
        target.textContent = `degraded: ${error?.message || "trace unavailable"}`;
      }
    });
  });
}

export function renderPersonaState(d) {
  const coordination = d.expression_coordination || {};
  const trends = d.memory_touch_trends || [];
  const events = d.memory_touch_events || [];
  const crossState = d.cross_window_emotional_state || {};
  const timeOfDay = d.time_of_day || "";
  const legacyLabels = d.legacy_context_labels || {};
  const timeLabels = d.time_of_day_labels || {};
  const traceDiagnostics = d.emotion_trace_diagnostics || {};
  const traceItems = Array.isArray(traceDiagnostics.items) ? traceDiagnostics.items.slice(0, 20) : [];

  const timeLabel = timeLabels[timeOfDay] || timeOfDay || "未知";
  const crossTotal = crossState.total || 0;
  const crossScar = crossState.scar_count || 0;
  const crossWarm = crossState.warm_count || 0;
  const crossVuln = crossState.vulnerable_count || 0;

  let html = '<div class="persona-grid">';

  html += `
    <div class="persona-card persona-card-wide">
      <div class="persona-card-head"><b>情绪链路诊断</b><span class="persona-badge">${escapeHtml(traceDiagnostics.state || "degraded")}</span></div>
      <div class="persona-card-body">
        <div class="persona-event-list">
          ${traceItems.map((item) => `<button type="button" class="persona-event-item" data-memory-emotion-trace="${escapeHtml(item.trace_id || "")}"><b>${escapeHtml(item.event_type || "neutral")} · r${escapeHtml(item.revision || 1)}</b><small>${escapeHtml(item.status || "observed")} · ${escapeHtml(item.occurred_at || "")}</small></button>`).join("") || '<p class="persona-empty">暂无可展示的脱敏 trace。</p>'}
        </div>
        <pre class="json-box" data-memory-emotion-trace-detail>选择一条 trace 查看事件 revision 与投递确认状态。</pre>
      </div>
    </div>
  `;

  html += `
    <div class="persona-card persona-card-wide">
      <div class="persona-card-head">
        <b>陪伴表达协同状态</b>
        <span class="persona-badge">只读</span>
      </div>
      <div class="persona-card-body">
        <div class="persona-cross-window">
          <span class="persona-cw-label">最终语气、称呼、互动档位由陪伴插件统一决定</span>
          <div class="persona-cw-stats">
            <span class="persona-cw-stat is-active">${escapeHtml(coordination.contract || "未检测到合同")}</span>
            <span class="persona-cw-stat">请求级消费</span>
            <span class="persona-cw-stat">不持久化表达状态</span>
          </div>
          <small class="persona-cw-empty">记忆插件只负责事实、可见性、召回和记忆提及上限，不会建立第二套好感度、互动状态或称呼系统。</small>
        </div>
      </div>
    </div>
  `;

  html += `
    <div class="persona-card persona-card-wide">
      <div class="persona-card-head">
        <b>当前时段</b>
        <span class="persona-badge persona-badge-time">${escapeHtml(timeLabel)}</span>
      </div>
      <div class="persona-card-body">
        <div class="persona-cross-window">
          <span class="persona-cw-label">跨窗口情绪余波</span>
          <div class="persona-cw-stats">
            <span class="persona-cw-stat ${crossTotal > 0 ? 'is-active' : ''}">总计 ${crossTotal}</span>
            ${crossScar > 0 ? `<span class="persona-cw-stat persona-cw-scar">伤痕 ${crossScar}</span>` : ''}
            ${crossWarm > 0 ? `<span class="persona-cw-stat persona-cw-warm">温暖 ${crossWarm}</span>` : ''}
            ${crossVuln > 0 ? `<span class="persona-cw-stat persona-cw-vuln">脆弱 ${crossVuln}</span>` : ''}
          </div>
          ${crossTotal === 0 ? '<small class="persona-cw-empty">近 30 分钟内无跨窗口情绪残留</small>' : '<small class="persona-cw-active">情绪正在跨窗口传递中</small>'}
        </div>
      </div>
    </div>
  `;

  if (trends.length === 0) {
    html += `
      <div class="persona-card persona-card-wide">
        <div class="persona-card-head"><b>记忆触动趋势</b></div>
        <div class="persona-card-body">
          <p class="persona-empty">暂无历史记忆触动记录。该区域只反映记忆被触动的趋势，不代表当前好感度或互动状态。</p>
        </div>
      </div>
    `;
  } else {
    html += `
      <div class="persona-card persona-card-wide">
        <div class="persona-card-head"><b>记忆触动趋势</b><span class="persona-badge">${trends.length} 个会话</span></div>
        <div class="persona-card-body">
          <div class="persona-phase-list">
            ${trends.map(item => renderMemoryTouchTrend(item, legacyLabels)).join('')}
          </div>
        </div>
      </div>
    `;
  }

  if (events.length > 0) {
    html += `
      <div class="persona-card persona-card-wide">
        <div class="persona-card-head"><b>记忆触动事件</b><span class="persona-badge">${events.length} 条待处理</span></div>
        <div class="persona-card-body">
          <div class="persona-event-list">
            ${events.map(e => renderPersonaEventItem(e)).join('')}
          </div>
          <small class="persona-cw-empty">这些事件只作为陪伴插件 Bot 心情与精力的输入，最终表达仍由陪伴插件裁决。</small>
        </div>
      </div>
    `;
  }

  html += '</div>';
  return html;
}

export function renderMemoryTouchTrend(p, legacyLabels) {
  const trend = p.trend_band || 'steady';
  const trendLabels = { rising: '升温触动', steady: '平稳触动', cooling: '降温触动' };
  const trendLabel = trendLabels[trend] || trend;
  const trendPercent = trend === 'rising' ? 82 : trend === 'cooling' ? 24 : 52;
  const trendClass = trend === 'rising' ? 'is-high' : trend === 'cooling' ? 'is-low' : 'is-mid';
  const touchCount = p.touch_count || 0;
  const legacyContext = p.legacy_context || '';
  const legacyLabel = legacyLabels[legacyContext] || legacyContext;
  const updatedAt = p.updated_at || '';
  const sessionKey = p.session_label || p.session_key || '';
  const shortSession = sessionKey.length > 40 ? sessionKey.slice(0, 37) + '...' : sessionKey;

  return `
    <div class="persona-phase-item">
      <div class="persona-phase-header">
        <div class="persona-phase-info">
          <span class="persona-phase-name">${escapeHtml(trendLabel)}</span>
          <small class="persona-phase-session">${escapeHtml(shortSession)}</small>
        </div>
        <div class="persona-phase-meta">
          <span class="persona-phase-touch">${touchCount} 次触动</span>
          ${legacyLabel ? `<span class="persona-phase-address">历史情境：${escapeHtml(legacyLabel)}</span>` : ''}
        </div>
      </div>
      <div class="persona-momentum">
        <span class="persona-momentum-label">触动趋势</span>
        <div class="persona-momentum-bar">
          <div class="persona-momentum-fill ${trendClass}" style="width:${trendPercent}%"></div>
        </div>
        <span class="persona-momentum-value">${escapeHtml(trendLabel)}</span>
      </div>
      ${updatedAt ? `<small class="persona-phase-updated">更新于 ${escapeHtml(updatedAt.slice(0, 16))}</small>` : ''}
    </div>
  `;
}

export function renderPersonaEventItem(e) {
  const type = e.event_type || '';
  const delta = Number(e.energy_delta) || 0;
  const hint = e.mood_hint || '';
  const preview = e.content_preview || '';
  const sessionId = e.session_id || '';
  const shortSession = sessionId.length > 30 ? sessionId.slice(0, 27) + '...' : sessionId;
  const typeLabels = {
    'scar_touched': { label: '伤痕触动', class: 'is-scar' },
    'warm_memory': { label: '温暖记忆', class: 'is-warm' },
    'vulnerable_resonance': { label: '脆弱共鸣', class: 'is-vuln' },
  };
  const typeInfo = typeLabels[type] || { label: type, class: '' };
  const deltaSign = delta >= 0 ? '+' : '';
  const deltaClass = delta >= 0 ? 'is-positive' : 'is-negative';

  return `
    <div class="persona-event-item ${typeInfo.class}">
      <div class="persona-event-head">
        <span class="persona-event-type">${escapeHtml(typeInfo.label)}</span>
        <span class="persona-event-delta ${deltaClass}">${deltaSign}${delta.toFixed(1)}</span>
      </div>
      <div class="persona-event-body">
        ${hint ? `<span class="persona-event-hint">${escapeHtml(hint)}</span>` : ''}
        ${preview ? `<small class="persona-event-preview">${escapeHtml(preview)}</small>` : ''}
        <small class="persona-event-session">${escapeHtml(shortSession)}</small>
      </div>
    </div>
  `;
}

export function _policyFor(policies, scope, id) {
  const found = policies.find(p => p.window_scope === scope && p.window_id === id);
  if (found) {
    return {
      read_mode: found.read_mode,
      share_mode: found.share_mode,
      capture_enabled: found.capture_enabled ?? null,
      recall_enabled: found.recall_enabled ?? null,
    };
  }
  const defaultMode = scope === "group" ? "blacklist" : "whitelist";
  return {
    read_mode: defaultMode,
    share_mode: defaultMode,
    capture_enabled: null,
    recall_enabled: null,
  };
}

export async function openNativePersonalMaterials(button) {
  const status = $("#coreMemoryNavigationStatus");
  button.disabled = true; status.textContent = "正在打开当前管理页...";
  try {
    const bridge = window.AstrBotPluginPage;
    if (!bridge) throw new Error("请从 AstrBot 后台重新打开此页面。");
    await bridge.ready();
    const theme = document.documentElement.dataset.adminTheme || new URLSearchParams(location.search).get("theme") || "dark";
    let result = await bridge.apiGet("page/nav", {to: "console", theme, format: "json"});
    if (result?.success === false) throw new Error(result.error || "管理入口读取失败");
    if (result?.data) result = result.data;
    const url = new URL(result?.url || "", location.href);
    if (url.origin !== location.origin || url.pathname !== "/api/plugin/page/content/astrbot_plugin_asteria/console/" || !url.searchParams.get("asset_token")) {
      throw new Error("管理入口地址未确认，请从 AstrBot 后台打开 Asteria 长期约定。");
    }
    url.hash = "personal";
    location.assign(url.href);
  } catch (error) {
    status.textContent = error?.message || "管理入口读取失败，请重试。";
  } finally { button.disabled = false; }
}

export function renderCoreMemoryBlocks() {
  const host = $("#coreMemoryList");
  if (!host) return;
  const blocks = Array.isArray(state.coreMemoryBlocks) ? state.coreMemoryBlocks : [];
  const query = coreHistory.query.trim().toLowerCase();
  const rows = blocks.filter(block => (!query || [block.id, block.label, block.content, block.target_id, block.target_name, block.bot_id, block.persona_id].join(" ").toLowerCase().includes(query))
    && (!coreHistory.kind || block.kind === coreHistory.kind) && (!coreHistory.scope || block.scope === coreHistory.scope)
    && (!coreHistory.enabled || Boolean(block.enabled) === (coreHistory.enabled === "yes")));
  const pages = Math.max(1, Math.ceil(rows.length / 12));
  coreHistory.page = Math.max(0, Math.min(coreHistory.page, pages - 1));
  const field = (label, value) => `<div><dt>${label}</dt><dd>${escapeHtml(value || "未提供")}</dd></div>`;
  host.innerHTML = rows.slice(coreHistory.page * 12, (coreHistory.page + 1) * 12).map(block => `
    <details class="core-history-record" data-core-history-id="${escapeHtml(block.id)}">
      <summary><b>${escapeHtml(block.label || block.id)}</b><span>只读 · ${escapeHtml(CORE_MEMORY_KIND_LABELS[block.kind] || block.kind)} · ${escapeHtml(CORE_MEMORY_SCOPE_LABELS[block.scope] || block.scope)} · ${block.enabled ? "旧标记启用" : "旧标记停用"}</span></summary>
      <p class="core-history-content">${escapeHtml(block.content || "未提供正文")}</p>
      <dl class="core-history-fields">${field("原编号", block.id)}${field("原修订", `r${block.revision ?? 0}`)}${field("原优先级", String(block.priority ?? 50))}${field("原目标", block.target_id)}${field("原目标名称", block.target_name)}${field("原 Bot", block.bot_id || "未限定 / self")}${field("原人格", block.persona_id)}${field("原平台", block.platform)}${field("原会话", block.session_id)}${field("更新时间", formatTime(block.updated_at))}</dl>
    </details>`).join("") || '<p class="persona-empty">当前读取窗口与筛选下没有旧核心记录；不代表长期约定管理页没有资料。</p>';
  $("#coreMemoryReadStatus").textContent = `本次读取 ${blocks.length} 条 · 筛选后 ${rows.length} 条 · 仅查询旧来源`;
  $("#coreMemoryPager").innerHTML = `<button type="button" data-core-history-page="previous"${coreHistory.page === 0 ? " disabled" : ""}>上一页</button><span>${coreHistory.page + 1} / ${pages}</span><button type="button" data-core-history-page="next"${coreHistory.page + 1 >= pages ? " disabled" : ""}>下一页</button>`;
}

export async function loadCoreMemoryBlocks() {
  const host = $("#coreMemoryList"), status = $("#coreMemoryReadStatus"), refresh = $("#legacyCoreRefresh");
  if (!host) return;
  if (!host.dataset.bound) {
    host.dataset.bound = "true";
    const open = $("[data-native-personal-open]");
    open.addEventListener("click", () => openNativePersonalMaterials(open));
    refresh.addEventListener("click", () => loadCoreMemoryBlocks());
    for (const [id, field, type] of [["legacyCoreQuery", "query", "input"], ["legacyCoreKind", "kind", "change"], ["legacyCoreScope", "scope", "change"], ["legacyCoreEnabled", "enabled", "change"]]) {
      const input = $("#" + id);
      input.addEventListener(type, () => { coreHistory[field] = input.value; coreHistory.page = 0; renderCoreMemoryBlocks(); });
    }
    $("#coreMemoryPager").addEventListener("click", event => { const button = event.target.closest("[data-core-history-page]"); if (!button) return; coreHistory.page += button.dataset.coreHistoryPage === "next" ? 1 : -1; renderCoreMemoryBlocks(); });
  }
  const ticket = ++coreHistory.request;
  refresh.disabled = true; status.textContent = "正在读取旧核心记录...";
  host.innerHTML = loadingState("正在读取旧核心记录...");
  try {
    const data = await apiGet("/core-memory");
    if (ticket !== coreHistory.request) return;
    state.coreMemoryBlocks = Array.isArray(data.blocks) ? data.blocks : [];
    for (const [id, field, labels] of [["legacyCoreKind", "kind", CORE_MEMORY_KIND_LABELS], ["legacyCoreScope", "scope", CORE_MEMORY_SCOPE_LABELS]]) {
      const select = $("#" + id), values = [...new Set(state.coreMemoryBlocks.map(block => block[field]).filter(Boolean))];
      if (coreHistory[field] && !values.includes(coreHistory[field])) values.push(coreHistory[field]);
      select.innerHTML = '<option value="">全部</option>' + values.map(value => memoryOption(value, labels[value] || value, coreHistory[field])).join("");
    }
    renderCoreMemoryBlocks();
  } catch (error) {
    if (ticket !== coreHistory.request) return;
    status.textContent = `旧记录读取失败：${error?.message || "暂不可用"}。当前长期约定仍可从上方独立进入。`;
    host.innerHTML = '<p class="persona-empty">旧记录暂未读取，未将失败解释为空库。</p>';
    $("#coreMemoryPager").replaceChildren();
  } finally { if (ticket === coreHistory.request) refresh.disabled = false; }
}

export function _windowFeatureValue(data, node, feature) {
  const policy = _policyFor(data?.policies || [], node.scope, node.id);
  const override = policy[`${feature}_enabled`];
  if (override !== null && override !== undefined) return Boolean(override);
  return Boolean(data?.scope_control?.[`${node.scope}_${feature}_enabled`]);
}

export function _renderWindowFeatureControls(data, windows) {
  const selectedKey = asteriaWorkspaceState._topologyState.selectedNode;
  const node = (windows || []).find(item => _topologyNodeKey(item) === selectedKey);
  if (!node) {
    return '<div class="topo-window-controls topo-window-controls-empty">选择一个群聊或私聊窗口，可单独调整记录和召回。</div>';
  }
  const policy = _policyFor(data?.policies || [], node.scope, node.id);
  const scopeLabel = node.scope === "group" ? "群聊" : "私聊";
  const renderFeature = (feature, label) => {
    const override = policy[`${feature}_enabled`];
    const checked = _windowFeatureValue(data, node, feature);
    const source = override === null || override === undefined ? "跟随全局" : "本窗口覆盖";
    return `
      <label class="topo-window-feature">
        <span>${label}<small>${source}</small></span>
        <input type="checkbox" data-window-feature="${feature}"${checked ? " checked" : ""} />
      </label>`;
  };
  return `
    <div class="topo-window-controls" data-window-scope="${escapeHtml(node.scope)}" data-window-id="${escapeHtml(node.id)}">
      <div class="topo-window-controls-title"><b>${escapeHtml(scopeLabel)}：${escapeHtml(_shortId(node.label || node.id, 32))}</b><small>单独窗口设置</small></div>
      <div class="topo-window-feature-grid">
        ${renderFeature("capture", "记录")}
        ${renderFeature("recall", "召回")}
      </div>
      <button type="button" class="topo-window-reset" data-window-feature-reset>恢复跟随全局</button>
    </div>`;
}

export function _findRule(rules, ownerScope, ownerId, readerScope, readerId) {
  return rules.find(r =>
    r.owner_scope === ownerScope && r.owner_id === ownerId &&
    r.reader_scope === readerScope && r.reader_id === readerId && r.enabled
  );
}

export function _permissionState(owner, reader, rules, policies) {
  const rule = _findRule(rules, owner.scope, owner.id, reader.scope, reader.id);
  if (rule) return rule.effect === "deny" ? "deny" : "allow";
  return "default";
}

export function _defaultEffect(owner, reader, policies) {
  const ownerPolicy = _policyFor(policies, owner.scope, owner.id);
  const readerPolicy = _policyFor(policies, reader.scope, reader.id);
  const requiresExplicit = owner.scope === "private" && reader.scope === "group";
  if (requiresExplicit) return "deny";
  if (ownerPolicy.share_mode === "blacklist" && readerPolicy.read_mode === "blacklist") return "allow";
  return "deny";
}

export function _permStateInfo(state, defaultEffect) {
  if (state === "allow") return { color: "var(--acl-allow, #4a9)", label: "手动允许", solid: true };
  if (state === "deny") return { color: "var(--acl-deny, #c43)", label: "手动屏蔽", solid: true };
  // default
  if (defaultEffect === "allow") return { color: "var(--acl-default-allow, #7ba)", label: "默认放行", solid: false };
  return { color: "var(--acl-default-deny, #e95)", label: "默认禁止", solid: false };
}

export function _shortId(id, max) {
  if (!id) return "";
  const s = String(id);
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

export function _layoutNodes(windows) {
  const groups = windows.filter(w => w.scope === "group");
  const privates = windows.filter(w => w.scope === "private");
  const colGap = 500;
  const rowGap = 108;
  const startY = 74;
  const groupX = 120;
  const privateX = groupX + colGap;
  const nodes = [];
  groups.forEach((w, i) => {
    nodes.push({ ...w, key: _topologyNodeKey(w), x: groupX, y: startY + i * rowGap });
  });
  privates.forEach((w, i) => {
    nodes.push({ ...w, key: _topologyNodeKey(w), x: privateX, y: startY + i * rowGap });
  });
  const maxCount = Math.max(groups.length, privates.length);
  const width = Math.max(760, privateX + 160);
  const height = Math.max(360, startY + maxCount * rowGap + 86);
  return { nodes, width, height, groupCount: groups.length, privateCount: privates.length };
}

export async function _updateWindowFeature(input) {
  const controls = input.closest("[data-window-scope][data-window-id]");
  if (!controls || asteriaWorkspaceState._topologyState.busy) return;
  const feature = input.dataset.windowFeature || "";
  if (!(feature === "capture" || feature === "recall")) return;
  asteriaWorkspaceState._topologyState.busy = true;
  input.disabled = true;
  try {
    await apiPost("/acl/policy", {
      scope: controls.dataset.windowScope,
      id: controls.dataset.windowId,
      [`${feature}_enabled`]: Boolean(input.checked),
    });
    const fresh = await apiGet("/acl/matrix");
    asteriaWorkspaceState._topologyState.data = fresh;
    asteriaWorkspaceState._topologyState.busy = false;
    _rerenderTopology();
    showToast(`已单独${input.checked ? "启用" : "停用"}${feature === "capture" ? "记录" : "召回"}`);
  } catch (err) {
    asteriaWorkspaceState._topologyState.busy = false;
    input.checked = !input.checked;
    input.disabled = false;
    showToast(err?.message || "窗口设置保存失败", "error");
  }
}

export async function _resetWindowFeatures() {
  const controls = document.querySelector("#aclTopologyContainer [data-window-scope][data-window-id]");
  if (!controls || asteriaWorkspaceState._topologyState.busy) return;
  asteriaWorkspaceState._topologyState.busy = true;
  try {
    await apiPost("/acl/policy", {
      scope: controls.dataset.windowScope,
      id: controls.dataset.windowId,
      capture_enabled: null,
      recall_enabled: null,
    });
    const fresh = await apiGet("/acl/matrix");
    asteriaWorkspaceState._topologyState.data = fresh;
    asteriaWorkspaceState._topologyState.busy = false;
    _rerenderTopology();
    showToast("已恢复跟随全局设置");
  } catch (err) {
    asteriaWorkspaceState._topologyState.busy = false;
    showToast(err?.message || "窗口设置恢复失败", "error");
  }
}

export function syncNativeMemoryNavigation(view) {
  const root = document.getElementById("nativeMemoryNavigation");
  if (!root) return;
  root.querySelectorAll("[data-native-view]").forEach((button) => {
    const active = button.dataset.nativeView === view;
    button.setAttribute("aria-current", active ? "page" : "false");
    if (active) document.getElementById("nativeMemoryNavigationTitle").textContent = button.textContent.trim();
  });
  const section = activeSecondaryNav(view);
  const hash = view === "overview" ? "" : `#view=${encodeURIComponent(view)}${section && secondaryNavItems(view).length ? `&section=${encodeURIComponent(section)}` : ""}`;
  if (location.hash !== hash) history.replaceState(history.state, "", `${location.pathname}${location.search}${hash}`);
  if (matchMedia("(max-width:760px)").matches) root.open = false;
}
