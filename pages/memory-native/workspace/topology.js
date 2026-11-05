/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {apiGet,apiPost} from './client.js';
import {_defaultEffect,_findRule,_layoutNodes,_permStateInfo,_permissionState,_renderWindowFeatureControls,_resetWindowFeatures,_updateWindowFeature} from './personal.js';
import {$,asteriaWorkspaceState} from './state.js';
import {compact,escapeHtml,loadingState,showToast,splitWindowBucketTitle,windowIdentifierLabel} from './workspace.js';

export async function loadAclTopology() {
  const container = $("#aclTopologyContainer");
  if (!container) return;
  container.innerHTML = loadingState("正在读取权限矩阵...");
  try {
    const data = await apiGet("/acl/matrix");
    asteriaWorkspaceState._topologyState.data = data;
    asteriaWorkspaceState._topologyState.selectedNode = null;
    asteriaWorkspaceState._topologyState.selectedPair = null;
    asteriaWorkspaceState._topologyState.busy = false;
    container.innerHTML = renderAclTopology(data);
    bindAclTopologyInteractions(container);
  } catch (err) {
    container.innerHTML = `<div class="persona-error">权限矩阵读取失败：${escapeHtml(err?.message || "未知错误")}</div>`;
  }
}

export function _topologyNodeKey(w) { return `${w.scope}:${w.id}`; }

export function _topologyNodeLabels(node) {
  const bucketTitle = splitWindowBucketTitle({
    scope: node.scope,
    target_id: node.id,
    group_id: node.scope === "group" ? node.id : "",
    label: node.label || "",
    sublabel: node.identifier_label || "",
    target_name: node.target_name || node.display_name || "",
    target_kind: node.target_kind || "",
  });
  const missingName = node.scope === "group" ? "未记录群名" : "未记录昵称";
  const name = bucketTitle.secondary && bucketTitle.secondary !== bucketTitle.primary
    ? bucketTitle.secondary
    : missingName;
  return {
    name,
    id: bucketTitle.primary || windowIdentifierLabel(node.scope, node.id, node.target_kind || ""),
  };
}

export function _topologyMidArrow(pathPoint, fromPoint, toPoint, ownerKey, readerKey, info, extraClass = "") {
  const angle = Math.atan2(toPoint.y - fromPoint.y, toPoint.x - fromPoint.x) * 180 / Math.PI;
  return `<text class="topo-mid-arrow ${extraClass}" x="${pathPoint.x}" y="${pathPoint.y}" transform="rotate(${angle} ${pathPoint.x} ${pathPoint.y})" fill="${info.color}" data-owner="${escapeHtml(ownerKey)}" data-reader="${escapeHtml(readerKey)}">➤</text>`;
}

export function _topologyNodeBadgeClass(node) {
  return node?.scope === "group" ? "topo-node-group-badge" : "topo-node-private-badge";
}

export function renderAclTopology(data) {
  const windows = data.windows || [];
  const rules = data.rules || [];
  const policies = data.policies || [];

  if (!windows.length) {
    return '<div class="empty-state">当前还没有可配置的群聊或私聊窗口。</div>';
  }

  const { nodes, width, height } = _layoutNodes(windows);
  const nodeMap = new Map(nodes.map(n => [n.key, n]));

  const pairs = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const ab = _permissionState(a, b, rules, policies);
      const ba = _permissionState(b, a, rules, policies);
      const abDefault = ab === "default" ? _defaultEffect(a, b, policies) : "";
      const baDefault = ba === "default" ? _defaultEffect(b, a, policies) : "";
      pairs.push({ a, b, ab, ba, abDefault, baDefault });
    }
  }

  const selectedKey = asteriaWorkspaceState._topologyState.selectedNode;
  const selectedPair = asteriaWorkspaceState._topologyState.selectedPair;

  let arrowsHtml = "";
  let arrowHitsHtml = "";
  let nodesHtml = "";

  for (const pair of pairs) {
    const { a, b, ab, ba, abDefault, baDefault } = pair;
    const isPairSelected = selectedPair && (
      (selectedPair[0] === a.key && selectedPair[1] === b.key) ||
      (selectedPair[0] === b.key && selectedPair[1] === a.key)
    );
    const involvesSelected = selectedKey && (a.key === selectedKey || b.key === selectedKey);
    const dim = !isPairSelected && !involvesSelected ? " is-dim" : "";
    const highlight = isPairSelected ? " is-highlighted" : "";
    const hitDisabled = selectedPair && !isPairSelected ? " is-disabled" : "";
    const arrowDisabled = selectedPair && !isPairSelected ? " is-locked" : "";

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const ox = -dy / dist * 18;
    const oy = dx / dist * 18;
    const ox2 = -dy / dist * 34;
    const oy2 = dx / dist * 34;

    const abInfo = _permStateInfo(ab, abDefault);
    const baInfo = _permStateInfo(ba, baDefault);

    // a -> b curve (upper)
    const ax1 = a.x + ox, ay1 = a.y + oy;
    const bx1 = b.x + ox, by1 = b.y + oy;
    const mx1 = (a.x + b.x) / 2 + ox2, my1 = (a.y + b.y) / 2 + oy2;
    const pathAb = `M ${ax1} ${ay1} Q ${mx1} ${my1} ${bx1} ${by1}`;
    const midAb = { x: 0.25 * ax1 + 0.5 * mx1 + 0.25 * bx1, y: 0.25 * ay1 + 0.5 * my1 + 0.25 * by1 };
    const abDashAttr = abInfo.solid ? "" : 'stroke-dasharray="5 4"';
    const abMarkerId = ab === "default" ? `topo-m-default-${abDefault}` : `topo-m-${ab}`;
    arrowsHtml += `<path class="topo-arrow${dim}${highlight}${arrowDisabled}" d="${pathAb}" data-owner="${escapeHtml(a.key)}" data-reader="${escapeHtml(b.key)}" data-state="${ab}" stroke="${abInfo.color}" fill="none" stroke-width="${abInfo.solid ? 2.5 : 1.8}" marker-end="url(#${abMarkerId})" ${abDashAttr}><title>${escapeHtml(a.label)} → ${escapeHtml(b.label)}: ${abInfo.label}</title></path>`;
    arrowsHtml += _topologyMidArrow(midAb, { x: ax1, y: ay1 }, { x: bx1, y: by1 }, a.key, b.key, abInfo, `${dim}${highlight}${hitDisabled}`);
    arrowHitsHtml += `<path class="topo-arrow-hit${hitDisabled}" d="${pathAb}" data-owner="${escapeHtml(a.key)}" data-reader="${escapeHtml(b.key)}" fill="none"><title>${escapeHtml(a.label)} → ${escapeHtml(b.label)}: 点击切换权限</title></path>`;

    // b -> a curve (lower)
    const ax2 = a.x - ox, ay2 = a.y - oy;
    const bx2 = b.x - ox, by2 = b.y - oy;
    const mx2 = (a.x + b.x) / 2 - ox2, my2 = (a.y + b.y) / 2 - oy2;
    const pathBa = `M ${bx2} ${by2} Q ${mx2} ${my2} ${ax2} ${ay2}`;
    const midBa = { x: 0.25 * bx2 + 0.5 * mx2 + 0.25 * ax2, y: 0.25 * by2 + 0.5 * my2 + 0.25 * ay2 };
    const baDashAttr = baInfo.solid ? "" : 'stroke-dasharray="5 4"';
    const baMarkerId = ba === "default" ? `topo-m-default-${baDefault}` : `topo-m-${ba}`;
    arrowsHtml += `<path class="topo-arrow${dim}${highlight}${arrowDisabled}" d="${pathBa}" data-owner="${escapeHtml(b.key)}" data-reader="${escapeHtml(a.key)}" data-state="${ba}" stroke="${baInfo.color}" fill="none" stroke-width="${baInfo.solid ? 2.5 : 1.8}" marker-end="url(#${baMarkerId})" ${baDashAttr}><title>${escapeHtml(b.label)} → ${escapeHtml(a.label)}: ${baInfo.label}</title></path>`;
    arrowsHtml += _topologyMidArrow(midBa, { x: bx2, y: by2 }, { x: ax2, y: ay2 }, b.key, a.key, baInfo, `${dim}${highlight}${hitDisabled}`);
    arrowHitsHtml += `<path class="topo-arrow-hit${hitDisabled}" d="${pathBa}" data-owner="${escapeHtml(b.key)}" data-reader="${escapeHtml(a.key)}" fill="none"><title>${escapeHtml(b.label)} → ${escapeHtml(a.label)}: 点击切换权限</title></path>`;
  }

  // Column headers
  nodesHtml += `
    <text class="topo-col-header" x="120" y="30" text-anchor="middle">群聊</text>
    <text class="topo-col-header" x="620" y="30" text-anchor="middle">私聊</text>`;

  // Nodes
  for (const n of nodes) {
    const isSelected = n.key === selectedKey;
    const isInPair = selectedPair && (selectedPair[0] === n.key || selectedPair[1] === n.key);
    const cls = `topo-node topo-node-${n.scope}${isSelected ? " is-selected" : ""}${isInPair ? " is-paired" : ""}`;
    const r = 24;
    const icon = n.scope === "group" ? "#" : "♡";
    const label = _topologyNodeLabels(n);
    const textX = n.scope === "group" ? 42 : -42;
    const anchor = n.scope === "group" ? "start" : "end";
    nodesHtml += `
      <g class="${cls}" data-node-key="${escapeHtml(n.key)}" transform="translate(${n.x},${n.y})">
        <circle r="${r}" />
        <text class="topo-node-icon" y="3">${escapeHtml(icon)}</text>
        <text class="topo-node-label" x="${textX}" y="-8" text-anchor="${anchor}">${escapeHtml(compact(label.name, 18))}</text>
        <text class="topo-node-id" x="${textX}" y="10" text-anchor="${anchor}">${escapeHtml(compact(label.id, 24))}</text>
        <text class="topo-node-count" x="${textX}" y="27" text-anchor="${anchor}">${n.memory_count || 0} 条记忆</text>
      </g>`;
  }

  return `
    <div class="topo-wrapper">
      <div class="topo-legend">
        <span class="topo-legend-item"><span class="topo-legend-line topo-allow"></span>手动允许</span>
        <span class="topo-legend-item"><span class="topo-legend-line topo-deny"></span>手动屏蔽</span>
        <span class="topo-legend-item"><span class="topo-legend-line topo-default-allow"></span>默认放行</span>
        <span class="topo-legend-item"><span class="topo-legend-line topo-default-deny"></span>默认禁止</span>
        <span class="topo-legend-hint">点击两个节点选中，再点击箭头切换</span>
      </div>
      <div class="topo-canvas-wrap">
        <svg class="topo-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMin meet">
          <defs>
            <marker id="topo-m-allow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-allow, #4a9)" /></marker>
            <marker id="topo-m-deny" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-deny, #c43)" /></marker>
            <marker id="topo-m-default-allow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-default-allow, #7ba)" /></marker>
            <marker id="topo-m-default-deny" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--acl-default-deny, #e95)" /></marker>
          </defs>
          <g class="topo-arrows">${arrowsHtml}</g>
          <g class="topo-arrow-hits">${arrowHitsHtml}</g>
          <g class="topo-nodes">${nodesHtml}</g>
        </svg>
      </div>
      ${_renderWindowFeatureControls(data, windows)}
    </div>`;
}

export function bindAclTopologyInteractions(container) {
  // Node click
  container.querySelectorAll("[data-node-key]").forEach(el => {
    el.addEventListener("click", () => {
      const key = el.dataset.nodeKey;
      if (asteriaWorkspaceState._topologyState.selectedNode === key) {
        asteriaWorkspaceState._topologyState.selectedNode = null;
        asteriaWorkspaceState._topologyState.selectedPair = null;
      } else if (asteriaWorkspaceState._topologyState.selectedNode && asteriaWorkspaceState._topologyState.selectedNode !== key) {
        asteriaWorkspaceState._topologyState.selectedPair = [asteriaWorkspaceState._topologyState.selectedNode, key];
        asteriaWorkspaceState._topologyState.selectedNode = null;
      } else {
        asteriaWorkspaceState._topologyState.selectedNode = key;
        asteriaWorkspaceState._topologyState.selectedPair = null;
      }
      _rerenderTopology();
    });
  });

  container.querySelectorAll("input[data-window-feature]").forEach(input => {
    input.addEventListener("change", () => _updateWindowFeature(input));
  });
  container.querySelectorAll("[data-window-feature-reset]").forEach(button => {
    button.addEventListener("click", () => _resetWindowFeatures());
  });

  // Arrow click
  container.querySelectorAll(".topo-arrow[data-owner][data-reader], .topo-arrow-hit[data-owner][data-reader], .topo-mid-arrow[data-owner][data-reader]").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (asteriaWorkspaceState._topologyState.busy) return;
      const ownerKey = el.dataset.owner;
      const readerKey = el.dataset.reader;
      if (
        asteriaWorkspaceState._topologyState.selectedPair
        && !(
          (asteriaWorkspaceState._topologyState.selectedPair[0] === ownerKey && asteriaWorkspaceState._topologyState.selectedPair[1] === readerKey)
          || (asteriaWorkspaceState._topologyState.selectedPair[0] === readerKey && asteriaWorkspaceState._topologyState.selectedPair[1] === ownerKey)
        )
      ) {
        return;
      }
      if (!asteriaWorkspaceState._topologyState.selectedPair) {
        asteriaWorkspaceState._topologyState.selectedPair = [ownerKey, readerKey];
      }
      _toggleTopologyPermission(ownerKey, readerKey);
    });
  });

}

export function _rerenderTopology() {
  const container = $("#aclTopologyContainer");
  if (!container || !asteriaWorkspaceState._topologyState.data) return;
  container.innerHTML = renderAclTopology(asteriaWorkspaceState._topologyState.data);
  bindAclTopologyInteractions(container);
}

export async function _toggleTopologyPermission(ownerKey, readerKey) {
  const data = asteriaWorkspaceState._topologyState.data;
  if (!data) return;
  if (asteriaWorkspaceState._topologyState.busy) return;
  asteriaWorkspaceState._topologyState.busy = true;
  _rerenderTopology();
  const ownerIdx = ownerKey.indexOf(":");
  const ownerScope = ownerIdx >= 0 ? ownerKey.slice(0, ownerIdx) : ownerKey;
  const ownerId = ownerIdx >= 0 ? ownerKey.slice(ownerIdx + 1) : "";
  const readerIdx = readerKey.indexOf(":");
  const readerScope = readerIdx >= 0 ? readerKey.slice(0, readerIdx) : readerKey;
  const readerId = readerIdx >= 0 ? readerKey.slice(readerIdx + 1) : "";
  const rules = data.rules || [];
  const policies = data.policies || [];
  const existing = _findRule(rules, ownerScope, ownerId, readerScope, readerId);
  const owner = { scope: ownerScope, id: ownerId };
  const reader = { scope: readerScope, id: readerId };
  const currentState = _permissionState(owner, reader, rules, policies);

  // Three-state cycle: allow → deny → default → allow → ...
  let action;
  if (currentState === "allow") {
    action = "to_deny";
  } else if (currentState === "deny") {
    action = "to_default";
  } else {
    // default → allow
    action = "to_allow";
  }

  try {
    if (action === "to_default" && existing) {
      await apiPost("/acl/delete", { id: existing.id });
      showToast("已恢复默认策略");
    } else if (action === "to_allow") {
      await apiPost("/acl/upsert", {
        owner_scope: ownerScope, owner_id: ownerId,
        reader_scope: readerScope, reader_id: readerId,
        effect: "allow", enabled: true,
      });
      showToast("已手动允许");
    } else if (action === "to_deny") {
      await apiPost("/acl/upsert", {
        owner_scope: ownerScope, owner_id: ownerId,
        reader_scope: readerScope, reader_id: readerId,
        effect: "deny", enabled: true,
      });
      showToast("已手动屏蔽");
    }
    const fresh = await apiGet("/acl/matrix");
    asteriaWorkspaceState._topologyState.data = fresh;
    asteriaWorkspaceState._topologyState.busy = false;
    _rerenderTopology();
  } catch (err) {
    asteriaWorkspaceState._topologyState.busy = false;
    _rerenderTopology();
    showToast(err?.message || "权限切换失败", "error");
  }
}
