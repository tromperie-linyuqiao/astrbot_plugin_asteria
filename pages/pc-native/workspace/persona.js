/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {postJson} from './client.js';
import {formatNumber} from './learning.js';
import {needLayerLabel,proactiveCandidateIsPending,proactivePercent100,proactiveScore01} from './life.js';
import {saveExperimentalSettings} from './navigation.js';
import {configLabel} from './providers.js';
import {featureDraftFromOverview,toBool} from './schema.js';
import {featureRelatedSettings,featureSettingInput,featureSettingVisibleForCurrentMode,syncFeatureProviderInput} from './settings.js';
import {$,EXP_PLUTCHIK_LABELS,PERSONA_STYLE_REFERENCE_LIMIT,PERSONA_STYLE_SCENARIO_BATCH_SIZE,asteriaWorkspaceState,configLabels,experimentalFeatureKeys,experimentalFeatureMeta,featureDetailGuides,featureMeta,featurePublicKeyAliases,featureSettingSections,personaStandardizationStyleHints,personaStandardizationTagLabels,personaStandardizationTimeNotes,personaStandardizationToolMeta,personaVoiceChannelMeta,state} from './state.js';
import {escapeHtml,loadAll,loadRoleplayPersonas,loadUserGroupLists,renderAll,scheduleExperimentalRuntimeRefresh} from './workspace.js';

export function donutChart(data, options = {}) {
  const {
    emptyText = "暂无记忆数据",
    labelFormatter = null,
    maxSegments = 0,
    mergeBelowPercent = 0,
    otherLabel = "其他",
  } = options;
  const grouped = new Map();
  for (const [rawLabel, rawValue] of Object.entries(data || {})) {
    const value = Number(rawValue);
    if (value <= 0) continue;
    const label = String(labelFormatter ? labelFormatter(rawLabel, value) : rawLabel || "未命名");
    grouped.set(label, (grouped.get(label) || 0) + value);
  }
  let entries = Array.from(grouped.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value);
  if (!entries.length) return `<div class="empty small">${escapeHtml(emptyText)}</div>`;
  const total = entries.reduce((sum, item) => sum + item.value, 0);
  if (mergeBelowPercent > 0 || maxSegments > 0) {
    const kept = [];
    let otherValue = 0;
    entries.forEach((item, index) => {
      const pct = total > 0 ? item.value / total : 0;
      const overflow = maxSegments > 0 && index >= maxSegments;
      const tooSmall = mergeBelowPercent > 0 && pct < mergeBelowPercent;
      if (overflow || tooSmall) {
        otherValue += item.value;
      } else {
        kept.push(item);
      }
    });
    entries = kept;
    if (otherValue > 0) entries.push({ label: otherLabel, value: otherValue });
  }
  let offset = 0;
  const colors = ["#2f7566", "#8a6f3e", "#4d7ea8", "#a15f26", "#6e7f3f"];
  const circles = entries.map((item, index) => {
    const pct = (item.value / total) * 100;
    const circle = `<circle r="42" cx="60" cy="60" pathLength="100" stroke="${colors[index % colors.length]}" stroke-dasharray="${pct} ${100 - pct}" stroke-dashoffset="${-offset}"></circle>`;
    offset += pct;
    return circle;
  }).join("");
  return `
    <div class="donut-wrap">
      <svg class="donut" viewBox="0 0 120 120">
        <circle r="42" cx="60" cy="60" class="donut-bg"></circle>
        ${circles}
        <text x="60" y="64" text-anchor="middle">${escapeHtml(formatNumber(total))}</text>
      </svg>
      <div class="donut-legend">
        ${entries.map((item, index) => {
          const pct = total > 0 ? (item.value / total) * 100 : 0;
          const pctText = pct >= 1 ? `${pct.toFixed(1)}%` : (pct > 0 ? `${pct.toFixed(1)}%` : "0%");
          return `
            <span class="donut-legend-item">
              <span class="donut-legend-label"><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(item.label)}</span>
              <span class="donut-legend-value">${escapeHtml(formatNumber(item.value))} · ${escapeHtml(pctText)}</span>
            </span>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

export function detailBlock(title, preText, pairs) {
  const dl = pairs?.length
    ? `<dl>${pairs.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value || "-")}</dd>`).join("")}</dl>`
    : "";
  const pre = preText ? `<pre>${escapeHtml(preText)}</pre>` : "";
  return `<section class="detail-block"><h2>${escapeHtml(title)}</h2>${pre}${dl}</section>`;
}

export function renderDl(selector, data) {
  const entries = Object.entries(data || {});
  $(selector).innerHTML = entries.length
    ? entries.map(([key, value]) => `<dt>${escapeHtml(configLabels[key] || key)}</dt><dd>${escapeHtml(formatValue(value))}</dd>`).join("")
    : `<dt>-</dt><dd>暂无数据</dd>`;
}

export function featureLabel(key) {
  return featureMeta[key]?.[0] || key.replace(/^enable_/, "");
}

export function featurePublicKey(key) {
  return featurePublicKeyAliases[key] || key;
}

export function featureDescription(key) {
  return featureMeta[key]?.[1] || "配置开关。";
}

export function formatValue(value) {
  if (value === "inject") return "注入";
  if (value === "transcribe") return "转述";
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value, null, 2);
  return value ?? "";
}

export function showToast(message, tone = "ok") {
  const text = String(message || "").trim();
  if (!text) return;
  let toast = document.getElementById("pageToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "pageToast";
    toast.className = "page-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.classList.toggle("error", tone === "error");
  toast.classList.add("show");
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => toast.classList.remove("show"), 1800);
}

export async function copyTextToClipboard(text, successMessage = "已复制") {
  const value = String(text || "").trim();
  if (!value) {
    showToast("没有可复制的内容", "error");
    return;
  }
  const fallbackCopy = () => {
    const box = document.createElement("textarea");
    box.value = value;
    box.setAttribute("readonly", "readonly");
    box.style.position = "fixed";
    box.style.left = "-9999px";
    box.style.top = "0";
    document.body.appendChild(box);
    box.focus();
    box.select();
    try {
      box.setSelectionRange(0, box.value.length);
    } catch (error) {
      // Older engines may not support setSelectionRange on textarea in this context.
    }
    const ok = document.execCommand("copy");
    box.remove();
    return ok;
  };
  try {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(value);
      } catch (error) {
        if (!fallbackCopy()) throw error;
      }
    } else {
      if (!fallbackCopy()) throw new Error("浏览器拒绝复制");
    }
    showToast(successMessage);
  } catch (error) {
    showToast(`复制失败：${error.message}`, "error");
  }
}

export function setActionBusy(control, busy) {
  if (!(control instanceof HTMLButtonElement)) return;
  if (busy) {
    control.dataset.originalText = control.textContent || "";
    control.disabled = true;
    control.classList.add("is-busy");
    control.textContent = "处理中...";
  } else {
    control.disabled = false;
    control.classList.remove("is-busy");
    if (control.dataset.originalText) {
      control.textContent = control.dataset.originalText;
      delete control.dataset.originalText;
    }
  }
}

export function requireSecondClick(control, key, message, nextText = "再次点击确认", timeoutMs = 6000) {
  if (!(control instanceof HTMLButtonElement)) return true;
  const now = Date.now();
  const armed = control.dataset.confirmKey === key && now - Number(control.dataset.confirmAt || 0) < timeoutMs;
  if (armed) {
    delete control.dataset.confirmKey;
    delete control.dataset.confirmAt;
    return true;
  }
  control.dataset.confirmKey = key;
  control.dataset.confirmAt = String(now);
  control.dataset.originalText = control.dataset.originalText || control.textContent || "";
  control.textContent = nextText;
  showToast(message);
  window.clearTimeout(control._confirmTimer);
  control._confirmTimer = window.setTimeout(() => {
    if (control.dataset.confirmKey === key) {
      delete control.dataset.confirmKey;
      delete control.dataset.confirmAt;
      control.textContent = control.dataset.originalText || "";
      delete control.dataset.originalText;
    }
  }, timeoutMs);
  return false;
}

export async function runAction(action, successMessage = "", control = null, options = {}) {
  const { reload = true } = options;
  setActionBusy(control, true);
  showToast("正在处理...");
  try {
    const result = await action();
    if (reload) {
      if (result && typeof result === "object" && result.plugin && result.features) {
        const requestSeq = ++asteriaWorkspaceState.loadAllRequestSeq;
        state.overview = result;
        state.featureDraft = featureDraftFromOverview(result);
        state.lazyLoaded.userGroupLists = false;
        state.userGroupListPromise = null;
        renderAll();
        $("#subtitle").textContent = `${result.plugin.bot_name || "Private Companion"} · ${new Date().toLocaleString()}`;
        void loadUserGroupLists(requestSeq, { force: true });
      } else {
        await loadAll();
      }
    } else if (result && typeof result === "object" && result.plugin && result.features) {
      state.overview = result;
      state.featureDraft = featureDraftFromOverview(result);
    }
    if (result && result.config_saved === false) {
      showToast("已应用到运行态，但配置持久化失败；重启或刷新后可能恢复旧值，请查看日志", "error");
    } else {
      showToast(successMessage || result?.message || "操作已完成");
    }
    return result;
  } catch (error) {
    showToast(`操作失败：${error.message}`, "error");
  } finally {
    setActionBusy(control, false);
  }
}

export function experimentalVisualSpec(key) {
  const specs = {
    enable_emotion_simulation: {
      mark: "情",
      theme: "emotion",
      model: "伊扎德四维 × Plutchik 八情绪 × Gross 调节策略",
      question: "Bot 此刻的短期情绪余波会怎样影响回复？",
      flow: [
        ["采样", "私聊消息触发伤害、安抚、夸奖、道歉等事件。"],
        ["量化", "更新愉快/紧张/激动/确信与八种基本情绪。"],
        ["映射", "换算成收敛、低压问法、短答降压等行为倾向。"],
        ["验证", "看用户详情页情绪卡、实验页量化条和排障记录。"],
      ],
      axes: [
        ["伊扎德四维", "愉快度、紧张度、激动度、确信度", "控制语气松紧、句长、是否追问和判断是否保留余地。"],
        ["Plutchik 八情绪", "喜悦、信任、恐惧、惊讶、悲伤、厌恶、愤怒、期待", "决定主导情绪和复合情绪，例如期待/乐观、反感、亲近。"],
        ["Gross 调节", "避开高压、换低压问法、转移注意、重新理解、短答降压", "把内部情绪余波映射到更自然的外显回复策略。"],
      ],
      verify: [["私聊对象", "private"], ["排障页", "troubleshooting"]],
    },
    enable_maslow_motivation_experiment: {
      mark: "需",
      theme: "need",
      model: "马斯洛需求层级 × 主动候选排序",
      question: "这条主动念头为什么值得现在说？",
      flow: [
        ["采样", "主动候选生成时读取话题、动机、来源和语义锚点。"],
        ["分类", "归入状态、安全、归属、尊重、成长、意义。"],
        ["调权", "按需求层给评分偏移和压力偏移，不直接写进回复。"],
        ["验证", "看主动候选里的需求层、评分偏移和压力偏移。"],
      ],
      axes: [
        ["需求层", "状态 / 安全 / 归属 / 尊重 / 成长 / 意义", "解释主动念头的内在由头。"],
        ["评分偏移", "正负小数", "影响候选排序，越高越容易排到前面。"],
        ["压力偏移", "正负小数", "影响打扰感，越低越适合低打扰表达。"],
      ],
      verify: [["主动页", "proactive"], ["排障页", "troubleshooting"]],
    },
    enable_experimental_motivation_model: {
      mark: "动",
      theme: "motivation",
      model: "驱力 × 诱因 × 唤醒适配",
      question: "Bot 想开口、值得开口、适合开口，这三件事是否同时成立？",
      flow: [
        ["采样", "主动计划到点时读取状态、关系温度、候选语义和当前唤醒。"],
        ["量化", "计算驱力、关系温度、诱因和唤醒适配。"],
        ["合成", "按 25/18/37/20 权重合成综合动机分。"],
        ["验证", "看主动运行态动机和主动链路测试里的实验动机阶段。"],
      ],
      axes: [
        ["驱力", "25%", "内部想开口的推动力。"],
        ["关系温度", "18%", "当前关系是否适合靠近。"],
        ["诱因", "37%", "这条候选有没有具体外部价值。"],
        ["唤醒适配", "20%", "当前状态是否适合行动。"],
      ],
      verify: [["主动页", "proactive"], ["排障页", "troubleshooting"]],
    },
    enable_personality_iteration_experiment: {
      mark: "格",
      theme: "personality",
      model: "PEN × 大五 × 依恋风格 × 自我决定理论",
      question: "当前行为是否贴近角色基线，偏差集中在哪条心理轴？",
      flow: [
        ["采样", "读取主动频率、候选质量、沉默后行为和群聊边界。"],
        ["归因", "映射到外向性、焦虑/回避、关系感、自主感等轴。"],
        ["建议", "给出人格、世界知识或主动策略的调整方向。"],
        ["验证", "看诊断项；开启自主调节时看临时参数覆盖结果。"],
      ],
      axes: [
        ["艾森克 PEN", "外向性 / 神经质 / 精神质", "检查话多、过频、情绪波动是否偏离角色。"],
        ["大五人格", "开放性、尽责性、外向性、宜人性、神经质", "检查角色设定和实际表达是否一致。"],
        ["依恋风格", "焦虑型 / 回避型 / 安全型", "检查沉默后追问或过度退开的关系模式。"],
        ["自我决定 SDT", "关系感 / 自主感 / 能力感", "检查主动是否有具体由头和稳定关系连接。"],
      ],
      verify: [["排障页", "troubleshooting"], ["配置页", "config"]],
    },
  };
  return specs[key] || { mark: "实", theme: "default", model: "实验功能", question: "", flow: [], axes: [], verify: [] };
}

export function experimentalRuntimeSignals(key) {
  if (key === "enable_emotion_simulation") {
    const samples = expEmotionSamples();
    const pending = samples.filter((item) => item.user.pending_emotion_judgement?.text).length;
    const active = samples.filter((item) => item.score > 0).length;
    return {
      primary: `${active}/${samples.length}`,
      label: "情绪样本",
      detail: pending ? `${pending} 条等待模型复核` : (samples.length ? "已读取四维与八情绪" : "等待私聊触发"),
      tone: active ? "ok" : "idle",
      bars: [
        ["样本", samples.length, Math.max(1, samples.length)],
        ["波动", active, Math.max(1, samples.length)],
        ["复核", pending, Math.max(1, samples.length)],
      ],
    };
  }
  if (key === "enable_maslow_motivation_experiment") {
    const items = (state.overview?.proactive_candidates?.items || []).filter(proactiveCandidateIsPending);
    const layers = new Set(items.map((item) => needLayerLabel(item.need_layer || item.need_level || item.maslow_level)).filter((item) => item !== "未分类"));
    return {
      primary: String(items.length),
      label: "待处理候选",
      detail: layers.size ? `${layers.size} 个需求层有样本` : "等待主动候选刷新",
      tone: layers.size ? "ok" : "idle",
      bars: [["候选", items.length, Math.max(1, items.length)], ["需求层", layers.size, 6]],
    };
  }
  if (key === "enable_experimental_motivation_model") {
    const states = (state.overview?.proactive_tasks?.user_states || [])
      .filter((item) => item?.inner_readiness?.motivation && Object.keys(item.inner_readiness.motivation).length);
    const top = states[0]?.inner_readiness?.motivation || {};
    return {
      primary: top.score ? proactiveScore01(top.score) : "0%",
      label: "动机分",
      detail: top.label || (states.length ? "已读取主动运行态" : "等待主动计划到点"),
      tone: top.score ? "ok" : "idle",
      bars: [["样本", states.length, Math.max(1, states.length)], ["综合", Math.round(Number(top.score || 0) * 100), 100]],
    };
  }
  if (key === "enable_personality_iteration_experiment") {
    const diagnostics = (state.diagnostics || []).filter((item) =>
      String(item.title || item.text || item.detail || "").includes("角色贴合")
      || String(item.text || item.detail || "").includes("艾森克")
      || String(item.text || item.detail || "").includes("依恋")
      || String(item.text || item.detail || "").includes("SDT")
    );
    const warnCount = diagnostics.filter((item) => ["warn", "error"].includes(item.level)).length;
    return {
      primary: String(diagnostics.length),
      label: "诊断项",
      detail: warnCount ? `${warnCount} 项需要关注` : (diagnostics.length ? "当前偏差较轻" : "等待诊断刷新"),
      tone: warnCount ? "warn" : (diagnostics.length ? "ok" : "idle"),
      bars: [["诊断", diagnostics.length, Math.max(1, diagnostics.length)], ["关注", warnCount, Math.max(1, diagnostics.length)]],
    };
  }
  return { primary: "-", label: "运行态", detail: "暂无数据", tone: "idle", bars: [] };
}

export function renderExperimentalCardVisual(key) {
  const signal = experimentalRuntimeSignals(key);
  const spec = experimentalVisualSpec(key);
  const bars = (signal.bars || []).map(([label, value, max]) => `
    <div class="exp-card-mini-bar">
      <span>${escapeHtml(label)}</span>
      <i><b style="width:${Math.min(100, Math.round((Number(value || 0) / Math.max(1, Number(max || 1))) * 100))}%"></b></i>
      <em>${escapeHtml(String(value))}</em>
    </div>
  `).join("");
  return `
    <div class="exp-card-visual ${escapeHtml(spec.theme)} ${escapeHtml(signal.tone)}">
      <div class="exp-card-orbit">${escapeHtml(spec.mark)}</div>
      <div class="exp-card-signal">
        <b>${escapeHtml(signal.primary)}</b>
        <span>${escapeHtml(signal.label)}</span>
        <small>${escapeHtml(signal.detail)}</small>
      </div>
      <div class="exp-card-mini-bars">${bars}</div>
    </div>
  `;
}

export function renderExperimentalOverviewMap() {
  const features = state.featureDraft || {};
  const nodes = experimentalFeatureKeys.map((key) => {
    const meta = experimentalFeatureMeta[key];
    const spec = experimentalVisualSpec(key);
    const signal = experimentalRuntimeSignals(key);
    const enabled = toBool(features[key]);
    return `
      <button type="button" class="exp-map-node ${escapeHtml(spec.theme)} ${enabled ? "on" : "off"}" data-exp-open="${escapeHtml(key)}">
        <span class="exp-map-mark">${escapeHtml(spec.mark)}</span>
        <span class="exp-map-main">
          <b>${escapeHtml(meta.label)}</b>
          <small>${escapeHtml(spec.model)}</small>
        </span>
        <span class="exp-map-signal">
          <b>${escapeHtml(signal.primary)}</b>
          <small>${escapeHtml(signal.label)}</small>
        </span>
      </button>
    `;
  }).join("");
  return `
    <section class="exp-overview-map">
      <div class="exp-overview-map-head">
        <div>
          <b>实验功能地图</b>
          <span>按“理论模型 → 量化指标 → 行为映射 → 验证入口”查看，不再只看文字说明。</span>
        </div>
      </div>
      <div class="exp-map-line">${nodes}</div>
    </section>
  `;
}

export function renderExperimentalToolEntrances() {
  return `
    <section class="exp-tool-entry-panel">
      <div class="exp-tool-entry-head">
        <div>
          <b>一次性工具入口</b>
          <span>这些是配置、整理或审核工具，不是运行时开关；点击后直接进入流程。</span>
        </div>
      </div>
      <div class="exp-tool-grid">
        <button type="button" class="exp-tool-card" data-exp-tool-open="persona_standardization_tool">
          <span class="exp-card-index">${escapeHtml(personaStandardizationToolMeta.index)}</span>
          <b>${escapeHtml(personaStandardizationToolMeta.label)}</b>
          <small>${escapeHtml(personaStandardizationToolMeta.shortDesc)}</small>
          <em>打开问卷 →</em>
        </button>
      </div>
    </section>
  `;
}

export function renderExperimentalHero(key, enabled) {
  const meta = experimentalFeatureMeta[key] || {};
  const spec = experimentalVisualSpec(key);
  const signal = experimentalRuntimeSignals(key);
  const flow = (spec.flow || []).map(([title, text], index) => `
    <div class="exp-hero-flow-step">
      <i>${index + 1}</i>
      <b>${escapeHtml(title)}</b>
      <span>${escapeHtml(text)}</span>
    </div>
  `).join("");
  const verify = (spec.verify || []).map(([label, tab]) => `
    <button type="button" data-jump-tab="${escapeHtml(tab)}">${escapeHtml(label)}</button>
  `).join("");
  return `
    <section class="exp-research-hero ${escapeHtml(spec.theme)} ${enabled ? "on" : "off"}">
      <div class="exp-research-hero-main">
        <span class="exp-research-kicker">${escapeHtml(spec.model)}</span>
        <h2>${escapeHtml(meta.label || "")}</h2>
        <p>${escapeHtml(spec.question || meta.shortDesc || "")}</p>
        <div class="exp-hero-flow">${flow}</div>
      </div>
      <aside class="exp-signal-board ${escapeHtml(signal.tone)}">
        <span>当前运行信号</span>
        <b>${escapeHtml(signal.primary)}</b>
        <strong>${escapeHtml(signal.label)}</strong>
        <p>${escapeHtml(signal.detail)}</p>
        <div class="exp-signal-actions">${verify}</div>
      </aside>
    </section>
  `;
}

export function renderExperimentalTheoryMatrix(key) {
  const spec = experimentalVisualSpec(key);
  const axes = (spec.axes || []).map(([name, metric, impact]) => `
    <section class="exp-theory-axis-card">
      <span>${escapeHtml(name)}</span>
      <b>${escapeHtml(metric)}</b>
      <p>${escapeHtml(impact)}</p>
    </section>
  `).join("");
  return `
    <article class="exp-detail-card exp-theory-matrix-card">
      <h3>理论轴与量化口径</h3>
      <div class="exp-theory-axis-grid">${axes}</div>
    </article>
  `;
}

export function renderExperimentalPage() {
  const root = $("#experimentalRoot");
  if (!root) return;
  const subpage = state.experimentalSubpage || "";
  if (subpage && experimentalFeatureKeys.includes(subpage)) {
    root.innerHTML = renderExperimentalSubpage(subpage);
    bindExperimentalSubpageActions(subpage);
  } else if (subpage === "persona_standardization_tool") {
    const shouldLoadPersonas = !state.lazyLoaded.roleplayPersonas;
    root.innerHTML = renderPersonaStandardizationToolPage();
    bindExperimentalSubpageActions(subpage);
    if (shouldLoadPersonas) loadRoleplayPersonas(false).then(() => {
      if (state.experimentalSubpage === "persona_standardization_tool") renderExperimentalPage();
    }).catch(() => {});
  } else {
    root.innerHTML = renderExperimentalOverview();
    bindExperimentalOverviewActions();
  }
}

export function reflectExperimentalToggleChange(key, enabled) {
  const root = $("#experimentalRoot");
  if (!root) return;
  root.querySelectorAll("[data-exp-toggle]").forEach((input) => {
    if ((input.dataset.expToggle || "") !== key) return;
    input.checked = enabled;
    const label = input.closest(".exp-card-toggle, .feature-detail-toggle");
    const labelText = label?.querySelector("b");
    if (labelText) labelText.textContent = enabled ? "开启" : "关闭";
  });
  root.querySelectorAll("[data-exp-open]").forEach((item) => {
    if ((item.dataset.expOpen || "") !== key) return;
    if (item.classList.contains("exp-card") || item.classList.contains("exp-map-node")) {
      item.classList.toggle("on", enabled);
      item.classList.toggle("off", !enabled);
    }
  });
  if (state.experimentalSubpage === key) {
    const subpage = root.querySelector(".experimental-subpage");
    subpage?.classList.toggle("on", enabled);
    subpage?.classList.toggle("off", !enabled);
    const strip = root.querySelector(".exp-state-strip");
    if (strip) {
      strip.classList.toggle("on", enabled);
      strip.classList.toggle("off", !enabled);
      const meta = experimentalFeatureMeta[key] || {};
      const title = strip.querySelector("b");
      const detail = strip.querySelector("span");
      if (title) title.textContent = enabled ? "开启" : "关闭";
      if (detail) detail.textContent = `${meta.index || ""} · ${enabled ? "正在参与相关链路" : "当前未启用，相关链路保持原有行为"}`;
    }
  }
}

export function renderExperimentalOverview() {
  const features = state.featureDraft || {};
  const cards = experimentalFeatureKeys.map((key) => {
    const meta = experimentalFeatureMeta[key];
    const enabled = toBool(features[key]);
    return `
      <article class="exp-card ${enabled ? "on" : "off"}" data-exp-open="${escapeHtml(key)}">
        <div class="exp-card-head">
          <div>
            <span class="exp-card-index">${escapeHtml(meta.index)}</span>
            <h3>${escapeHtml(meta.label)}</h3>
            <code>${escapeHtml(key)}</code>
          </div>
          <label class="exp-card-toggle" onclick="event.stopPropagation()">
            <input type="checkbox" data-exp-toggle="${escapeHtml(key)}" ${enabled ? "checked" : ""}>
            <span class="feature-toggle-visual"></span>
            <b>${escapeHtml(enabled ? "开启" : "关闭")}</b>
          </label>
        </div>
        <p class="exp-card-desc">${escapeHtml(meta.shortDesc)}</p>
        ${renderExperimentalCardVisual(key)}
        <div class="exp-card-foot">
          <span class="exp-card-status ${enabled ? "on" : "off"}">${escapeHtml(enabled ? "运行中" : "默认关闭")}</span>
          <button type="button" class="exp-card-enter" data-exp-open="${escapeHtml(key)}">查看与配置 →</button>
        </div>
      </article>
    `;
  }).join("");
  const enabledCount = experimentalFeatureKeys.filter((key) => toBool(features[key])).length;
  return `
    <div class="subpage experimental-page">
      <div class="section-head">
        <div>
          <h2>实验性功能</h2>
          <span class="muted">运行时实验能力在这里开启；配置和整理类工具作为入口单独使用。</span>
        </div>
        <div class="actions compact"><span class="module-badge">${enabledCount} / ${experimentalFeatureKeys.length} 开启</span></div>
      </div>
      <div class="experimental-overview-note">
        <b>建议一次只验证一项</b>
        <span>先查看当前信号，再开启单项观察；关闭后会立即停止新增实验处理，不会把理论标签输出到聊天正文。</span>
      </div>
      ${renderExperimentalToolEntrances()}
      <div class="exp-card-grid">${cards}</div>
    </div>
  `;
}

export function renderPersonaStandardizationToolPage() {
  return `
    <div class="subpage experimental-subpage persona-tool-subpage">
      <nav class="exp-breadcrumb">
        <button type="button" data-exp-back>← 返回总览</button>
        <span>/ ${escapeHtml(personaStandardizationToolMeta.label)}</span>
      </nav>
      <div class="exp-subpage-toolbar">
        <button type="button" class="exp-toolbar-back" data-exp-back>← 返回总览</button>
      </div>
      <header class="exp-subpage-head">
        <div>
          <span class="module-badge">${escapeHtml(personaStandardizationToolMeta.index)}</span>
          <h2>${escapeHtml(personaStandardizationToolMeta.label)}</h2>
          <p>${escapeHtml(personaStandardizationToolMeta.shortDesc)}</p>
        </div>
      </header>
      <div class="experimental-overview-note">
        <b>入口说明</b>
        <span>这是一次性整理工具，不需要开启功能开关。生成结果只用于审核和复制，不会自动改写 AstrBot 人格。</span>
      </div>
      ${renderPersonaStandardizationWorkbench()}
    </div>
  `;
}

export function renderExperimentalSubpage(key) {
  const meta = experimentalFeatureMeta[key];
  if (!meta) return "";
  const features = state.featureDraft || {};
  const settings = state.overview?.settings || {};
  const enabled = toBool(features[key]);
  const guide = featureDetailGuides[key] || {};
  const theoryHtml = meta.theory.map((item) => `
    <section class="exp-theory-item">
      <div class="exp-theory-head">
        <b>${escapeHtml(item.name)}</b>
      </div>
      <p class="exp-theory-desc">${escapeHtml(item.desc)}</p>
      ${item.impact ? `<div class="exp-theory-impact"><span class="exp-theory-impact-label">→ 对 Bot 行为的影响</span><p>${escapeHtml(item.impact)}</p></div>` : ""}
    </section>
  `).join("");
  const effectsHtml = (meta.effects || []).map((item) => `
    <section class="exp-effect-chain">
      <div class="exp-effect-step">
        <span class="exp-effect-tag trigger">触发</span>
        <p>${escapeHtml(item.trigger)}</p>
      </div>
      <div class="exp-effect-arrow">→</div>
      <div class="exp-effect-step">
        <span class="exp-effect-tag behavior">内部行为</span>
        <p>${escapeHtml(item.behavior)}</p>
      </div>
      <div class="exp-effect-arrow">→</div>
      <div class="exp-effect-step">
        <span class="exp-effect-tag result">可观察结果</span>
        <p>${escapeHtml(item.result)}</p>
      </div>
    </section>
  `).join("");
  const guideRows = [
    ["功能概述", guide.summary || meta.shortDesc],
    ["何时生效", guide.trigger || "对应场景触发时生效。"],
    ["开启后", guide.enabled || "相关能力会参与判断、注入或后台整理。"],
    ["关闭后", guide.disabled || "相关能力停止新增处理，已有数据仍可在页面查看。"],
  ].map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  const settingsHtml = renderExperimentalSettings(key);
  const runtimeHtml = renderExperimentalRuntime(key);
  const visualHtml = renderExperimentalTheoryVisual(key);
  const heroHtml = renderExperimentalHero(key, enabled);
  const matrixHtml = renderExperimentalTheoryMatrix(key);
  return `
    <div class="subpage experimental-subpage ${enabled ? "on" : "off"}">
      <nav class="exp-breadcrumb">
        <button type="button" data-exp-back>← 返回总览</button>
        <span>/ ${escapeHtml(meta.label)}</span>
      </nav>
      <div class="exp-subpage-toolbar">
        <button type="button" class="exp-toolbar-back" data-exp-back>← 返回总览</button>
        <div class="exp-toolbar-jumps">
          <button type="button" data-scroll-target="experimentalSettings">参数配置</button>
          <button type="button" data-scroll-target="experimentalRuntime">运行状态</button>
        </div>
      </div>
      <div class="exp-state-strip ${enabled ? "on" : "off"}">
        <b>${escapeHtml(enabled ? "开启" : "关闭")}</b>
        <span>${escapeHtml(meta.index)} · ${escapeHtml(enabled ? "正在参与相关链路" : "当前未启用，相关链路保持原有行为")}</span>
      </div>
      <header class="exp-subpage-head">
        <div>
          <span class="module-badge">${escapeHtml(meta.index)}</span>
          <h2>${escapeHtml(meta.label)}</h2>
          <p>${escapeHtml(meta.shortDesc)}</p>
        </div>
        <label class="feature-detail-toggle">
          <input type="checkbox" data-exp-toggle="${escapeHtml(key)}" ${enabled ? "checked" : ""}>
          <span class="feature-toggle-visual"></span>
          <b>${escapeHtml(enabled ? "开启" : "关闭")}</b>
        </label>
      </header>
      ${heroHtml}
      ${meta.caution ? `<div class="exp-caution"><b>注意</b><span>${escapeHtml(meta.caution)}</span></div>` : ""}
      <div class="exp-bottom-grid exp-priority-grid">
        ${settingsHtml}
        ${runtimeHtml}
      </div>
      <details class="exp-evidence">
        <summary><span>原理与行为依据</span><small>理论口径、效果链和完整说明</small></summary>
        <div class="exp-evidence-body">
          ${visualHtml}
          ${matrixHtml}
          <article class="exp-detail-card exp-theory-card">
            <h3>理论框架与行为映射</h3>
            <div class="exp-theory-list">${theoryHtml}</div>
          </article>
          ${effectsHtml ? `<article class="exp-detail-card exp-effects-card">
            <h3>功能效果链路</h3>
            <div class="exp-effect-list">${effectsHtml}</div>
          </article>` : ""}
          <article class="exp-detail-card exp-guide-card">
            <h3>完整功能说明</h3>
            <dl>${guideRows}</dl>
          </article>
        </div>
      </details>
      <div class="exp-subpage-footer">
        <button type="button" data-exp-back>← 返回实验功能总览</button>
        <span>参数调整需要点击“保存参数”提交；返回不再自动保存，避免卡顿和误操作。</span>
      </div>
    </div>
  `;
}

export function expClamp(value, min = 0, max = 100) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return min;
  return Math.max(min, Math.min(max, num));
}

export function expPercent(value, min = 0, max = 100) {
  if (max <= min) return 0;
  return expClamp(((Number(value || 0) - min) / (max - min)) * 100, 0, 100);
}

export function expMetricBar(row) {
  const min = Number(row.min ?? 0);
  const max = Number(row.max ?? 100);
  const value = expClamp(row.value, min, max);
  const pct = expPercent(value, min, max);
  const baseline = row.baseline == null ? null : expPercent(row.baseline, min, max);
  const signed = min < 0 && value > 0 ? `+${Math.round(value)}` : `${Math.round(value)}`;
  return `
    <div class="exp-visual-meter-row ${row.tone ? escapeHtml(row.tone) : ""}">
      <div class="exp-visual-meter-head">
        <b>${escapeHtml(row.label)}</b>
        <span>${escapeHtml(row.valueText || signed)}${row.unit ? escapeHtml(row.unit) : ""}</span>
      </div>
      <div class="exp-visual-meter-track" aria-label="${escapeHtml(row.label)}">
        <i class="exp-visual-meter-fill" style="width:${pct}%"></i>
        ${baseline == null ? "" : `<em class="exp-visual-meter-baseline" style="left:${baseline}%"></em>`}
      </div>
      <div class="exp-visual-meter-scale">
        <small>${escapeHtml(row.low || String(min))}</small>
        <small>${escapeHtml(row.mid || (baseline == null ? "" : "基线"))}</small>
        <small>${escapeHtml(row.high || String(max))}</small>
      </div>
      ${row.mapping ? `<p>${escapeHtml(row.mapping)}</p>` : ""}
    </div>
  `;
}

export function expTheoryVisualShell(title, subtitle, bodyHtml, footer = "") {
  return `
    <article class="exp-detail-card exp-theory-visual-card">
      <div class="exp-visual-head">
        <div>
          <h3>${escapeHtml(title)}</h3>
          <p>${escapeHtml(subtitle)}</p>
        </div>
        ${footer ? `<span>${escapeHtml(footer)}</span>` : ""}
      </div>
      ${bodyHtml}
    </article>
  `;
}

export function expEmotionSamples() {
  return (state.users || [])
    .map((user) => {
      const rel = user.relationship_state && typeof user.relationship_state === "object" ? user.relationship_state : {};
      const dims = rel.emotion_dimensions && typeof rel.emotion_dimensions === "object" ? rel.emotion_dimensions : {};
      const plutchik = rel.plutchik_profile && typeof rel.plutchik_profile === "object" ? rel.plutchik_profile : {};
      const emotions = rel.plutchik_emotions && typeof rel.plutchik_emotions === "object" ? rel.plutchik_emotions : {};
      const regulation = rel.emotion_regulation && typeof rel.emotion_regulation === "object" ? rel.emotion_regulation : {};
      const dimStrength = ["pleasantness", "tension", "arousal", "certainty"].reduce((sum, key) => sum + Math.abs(Number(dims[key] || 0)), 0);
      const activeStrength = Object.values(emotions).reduce((max, value) => Math.max(max, Number(value || 0)), Number(plutchik.dominant_value || 0));
      const score = Math.max(Math.abs(Number(rel.mood_score || 0)), dimStrength, activeStrength, Number(regulation.intensity || 0));
      return { user, rel, dims, plutchik, emotions, regulation, score };
    })
    .filter((item) => Object.keys(item.rel).length)
    .sort((a, b) => b.score - a.score);
}

export function expIzardMapping(key, value) {
  const v = Number(value || 0);
  if (key === "pleasantness") {
    if (v <= -45) return "不愉快显著：回复应短、慢、低刺激，先稳住而不是开玩笑。";
    if (v >= 35) return "愉快度较高：可以自然靠近，但仍避免突然过度热情。";
    return "愉快度接近基线：按普通聊天节奏处理。";
  }
  if (key === "tension") {
    if (v >= 60) return "紧张度高：减少追问和长解释，优先降压。";
    if (v <= 25) return "紧张度低：语气可以更松，但不代表要主动贴近。";
    return "中等紧张：保持稳态承接。";
  }
  if (key === "arousal") {
    if (v >= 65) return "激动度高：容易外显反应过强，需要收住句长和语气。";
    if (v <= 20) return "激动度低：适合轻声、慢一点的回复。";
    return "激动度适中：可正常表达。";
  }
  if (key === "certainty") {
    if (v <= 30) return "确信度低：不要替用户下结论，多用试探和确认。";
    if (v >= 70) return "确信度高：可以更明确地承接当前关系判断。";
    return "确信度中等：表达保留余地。";
  }
  return "";
}

export function renderEmotionTheoryVisual() {
  const samples = expEmotionSamples();
  const sample = samples[0] || { user: {}, rel: {}, dims: {}, plutchik: {}, emotions: {}, regulation: {}, score: 0 };
  const userLabel = sample.user.nickname || sample.user.display_name || sample.user.user_id || "暂无样本";
  const dims = sample.dims || {};
  const dimensionRows = [
    { key: "pleasantness", label: "愉快度", value: dims.pleasantness ?? 0, min: -100, max: 100, baseline: 0, low: "受挫", mid: "中性", high: "愉快", tone: "pleasant" },
    { key: "tension", label: "紧张度", value: dims.tension ?? 12, min: 0, max: 100, baseline: 12, low: "放松", mid: "基线 12", high: "高压", tone: "tension" },
    { key: "arousal", label: "激动度", value: dims.arousal ?? 20, min: 0, max: 100, baseline: 20, low: "低唤醒", mid: "基线 20", high: "激动", tone: "arousal" },
    { key: "certainty", label: "确信度", value: dims.certainty ?? 60, min: 0, max: 100, baseline: 60, low: "不确定", mid: "基线 60", high: "确定", tone: "certainty" },
  ].map((row) => expMetricBar({ ...row, mapping: expIzardMapping(row.key, row.value) })).join("");
  const emotions = sample.emotions || {};
  const activeFromProfile = Array.isArray(sample.plutchik.active) ? sample.plutchik.active : [];
  const emotionValue = (key) => {
    if (emotions[key] != null) return Number(emotions[key] || 0);
    const active = activeFromProfile.find((item) => item.key === key);
    if (active) return Number(active.value || 0);
    if (sample.plutchik.dominant === key) return Number(sample.plutchik.dominant_value || 0);
    if (sample.plutchik.secondary === key) return Number(sample.plutchik.secondary_value || 0);
    return 0;
  };
  const plutchikRows = Object.entries(EXP_PLUTCHIK_LABELS).map(([key, label]) => expMetricBar({
    label,
    value: emotionValue(key),
    min: 0,
    max: 100,
    low: "0",
    high: "100",
    mapping: key === sample.plutchik.dominant ? "当前主导情绪，会优先影响措辞。" : "",
  })).join("");
  const regulation = sample.regulation || {};
  const stack = Array.isArray(regulation.strategy_stack) && regulation.strategy_stack.length
    ? regulation.strategy_stack
    : (regulation.strategy && regulation.strategy !== "none" ? [regulation] : []);
  const regulationRows = stack.length ? stack.map((item) => expMetricBar({
    label: item.strategy_label || item.strategy || "调节策略",
    value: item.intensity || 0,
    min: 0,
    max: 100,
    low: "弱",
    high: "强",
    mapping: item.reason || "根据当前情绪负载选择。",
  })).join("") : `<div class="exp-visual-empty">当前无需额外调节；出现高压、边界或受伤余波后会显示策略强度。</div>`;
  const body = `
    <div class="exp-visual-grid two">
      <section class="exp-visual-panel">
        <h4>伊扎德四维情绪</h4>
        <div class="exp-visual-meter-list">${dimensionRows}</div>
      </section>
      <section class="exp-visual-panel">
        <h4>Plutchik 八情绪</h4>
        <div class="exp-visual-meter-list compact">${plutchikRows}</div>
      </section>
      <section class="exp-visual-panel wide">
        <h4>Gross 调节策略</h4>
        <div class="exp-visual-meter-list">${regulationRows}</div>
      </section>
    </div>
  `;
  return expTheoryVisualShell("理论量化视图", "把短期情绪拆成四维状态、八种基本情绪和调节策略；数值越高，越会影响回复节奏。", body, `样本：${userLabel}`);
}

export function renderMaslowTheoryVisual() {
  const proactiveData = state.overview?.proactive_candidates || {};
  const pending = (proactiveData.items || []).filter(proactiveCandidateIsPending);
  const layerOrder = ["状态", "安全", "归属", "尊重", "成长", "意义"];
  const descriptions = {
    状态: "身体/精力/休息相关，偏低打扰照料。",
    安全: "边界/稳定/勿扰相关，会降低压力。",
    归属: "关系连接/陪伴相关，常见于轻关心。",
    尊重: "认可/被看见相关，避免讨好式索取。",
    成长: "探索/学习/创作相关，适合有具体内容时分享。",
    意义: "自我实现/长期目标相关，通常需要更强由头。",
  };
  const buckets = Object.fromEntries(layerOrder.map((label) => [label, { count: 0, scoreBias: 0, pressureBias: 0 }]));
  pending.forEach((item) => {
    const label = needLayerLabel(item.need_layer || item.need_level || item.maslow_level);
    const bucket = buckets[label] || (buckets[label] = { count: 0, scoreBias: 0, pressureBias: 0 });
    bucket.count += Number(item.repeat_count || 1);
    bucket.scoreBias += Number(item.need_score_bias || 0);
    bucket.pressureBias += Number(item.need_pressure_bias || 0);
  });
  const maxCount = Math.max(1, ...Object.values(buckets).map((item) => item.count));
  const rows = layerOrder.map((label) => {
    const bucket = buckets[label] || { count: 0, scoreBias: 0, pressureBias: 0 };
    const avgScore = bucket.count ? bucket.scoreBias / bucket.count : 0;
    const avgPressure = bucket.count ? bucket.pressureBias / bucket.count : 0;
    return `
      <div class="exp-need-map-row">
        <div class="exp-need-map-label">
          <b>${escapeHtml(label)}</b>
          <span>${escapeHtml(descriptions[label])}</span>
        </div>
        <div class="exp-need-map-track"><i style="width:${Math.round((bucket.count / maxCount) * 100)}%"></i></div>
        <div class="exp-need-map-meta">
          <b>${escapeHtml(String(bucket.count))}</b>
          <span>评分 ${avgScore >= 0 ? "+" : ""}${avgScore.toFixed(2)}｜压力 ${avgPressure >= 0 ? "+" : ""}${avgPressure.toFixed(2)}</span>
        </div>
      </div>
    `;
  }).join("");
  const body = `
    <div class="exp-visual-panel">
      <h4>六层需求分布与排序影响</h4>
      <div class="exp-need-map">${rows}</div>
      <div class="exp-visual-note">统计范围：当前待处理主动候选。评分偏移越高越容易提前，压力偏移越低越不打扰。</div>
    </div>
  `;
  return expTheoryVisualShell("理论量化视图", "把主动候选映射到六类需求，并显示每类候选数量、评分偏移和打扰压力偏移。", body, `候选：${pending.length}`);
}

export function renderMotivationTheoryVisual() {
  const taskData = state.overview?.proactive_tasks || {};
  const userStates = Array.isArray(taskData.user_states) ? taskData.user_states : [];
  const stateRows = userStates
    .map((item) => ({ item, motivation: item?.inner_readiness?.motivation || {} }))
    .filter((entry) => entry.motivation && Object.keys(entry.motivation).length)
    .sort((a, b) => Number(b.motivation.score || 0) - Number(a.motivation.score || 0));
  const selected = stateRows[0] || { item: {}, motivation: {} };
  const motivation = selected.motivation || {};
  const factors = [
    { label: "驱力", weight: 25, value: motivation.drive?.score ?? 0, mapping: "Bot 内部想开口的推动力，受状态、精力、关系温度影响。" },
    { label: "关系温度", weight: 18, value: motivation.temperature?.score ?? 0, mapping: "当前关系是否适合靠近；未回应、受伤或边界会降低。" },
    { label: "诱因", weight: 37, value: motivation.incentive?.score ?? 0, mapping: "这条主动有没有具体外部价值；约定、事件、内容分享会提高。" },
    { label: "唤醒适配", weight: 20, value: motivation.arousal?.score ?? 0, mapping: "当前状态是否适合行动；过高像急，过低像没劲。" },
  ];
  const rows = factors.map((item) => expMetricBar({
    label: `${item.label} · 权重 ${item.weight}%`,
    value: Math.round(Number(item.value || 0) * 100),
    min: 0,
    max: 100,
    low: "低",
    high: "高",
    mapping: item.mapping,
  })).join("");
  const composite = expMetricBar({
    label: "综合动机分",
    value: Math.round(Number(motivation.score || 0) * 100),
    min: 0,
    max: 100,
    low: "先收住",
    mid: "观望",
    high: "适合行动",
    mapping: motivation.detail || "综合分由驱力、关系温度、诱因和唤醒适配加权得到。",
  });
  const body = `
    <div class="exp-visual-grid two">
      <section class="exp-visual-panel">
        <h4>加权因子</h4>
        <div class="exp-visual-meter-list">${rows}</div>
      </section>
      <section class="exp-visual-panel">
        <h4>最终决策映射</h4>
        <div class="exp-visual-meter-list">${composite}</div>
        <div class="exp-visual-decision">
          <b>${escapeHtml(motivation.label || "暂无运行样本")}</b>
          <span>${escapeHtml(motivation.detail || "等待主动运行态或主动链路测试产生动机调度记录。")}</span>
        </div>
      </section>
    </div>
  `;
  return expTheoryVisualShell("理论量化视图", "把主动开口拆成驱力、关系温度、诱因和唤醒适配四个量化因子，并展示它们如何合成最终动机分。", body, selected.item.user_label ? `样本：${selected.item.user_label}` : "暂无样本");
}

export function renderPersonalityTheoryVisual() {
  const diagnostics = (state.diagnostics || []).filter((item) =>
    String(item.title || item.source || item.text || item.detail || "").includes("角色贴合")
    || String(item.text || item.detail || "").includes("艾森克")
    || String(item.text || item.detail || "").includes("大五")
    || String(item.text || item.detail || "").includes("依恋")
    || String(item.text || item.detail || "").includes("SDT")
    || String(item.text || item.detail || "").includes("自主感")
  );
  const axes = [
    { label: "艾森克 PEN", match: /艾森克|PEN|外向性|神经质|精神质/, mapping: "检查话多、主动过频、情绪波动是否偏离角色基线。" },
    { label: "大五人格", match: /大五|开放性|尽责性|宜人性/, mapping: "检查设定中的性格倾向与实际主动/回复风格是否一致。" },
    { label: "依恋风格", match: /依恋|焦虑型|回避型|安全型|追问|收缩/, mapping: "检查沉默后追问、过度退开或稳定承接的关系模式。" },
    { label: "自我决定 SDT", match: /SDT|自主感|关系感|能力感|动机质量/, mapping: "检查主动是否有自主由头、关系连接和具体能力感。" },
  ];
  const levelWeight = { error: 3, warn: 2, info: 1, ok: 0 };
  const rows = axes.map((axis) => {
    const hits = diagnostics.filter((item) => axis.match.test(`${item.title || ""} ${item.text || ""} ${item.detail || ""}`));
    const maxLevel = hits.reduce((level, item) => (levelWeight[item.level] || 0) > (levelWeight[level] || 0) ? item.level : level, "ok");
    const value = hits.reduce((sum, item) => sum + (levelWeight[item.level] || 1), 0);
    return `
      <div class="exp-personality-axis ${escapeHtml(maxLevel)}">
        <div>
          <b>${escapeHtml(axis.label)}</b>
          <span>${escapeHtml(axis.mapping)}</span>
        </div>
        <strong>${escapeHtml(hits.length ? `${hits.length} 项` : "平稳")}</strong>
        <div class="exp-personality-axis-track"><i style="width:${Math.min(100, value * 28)}%"></i></div>
      </div>
    `;
  }).join("");
  const body = `
    <div class="exp-visual-panel">
      <h4>角色贴合诊断轴</h4>
      <div class="exp-personality-axis-list">${rows}</div>
      <div class="exp-visual-note">这里不是给人格打绝对分，而是把排障诊断映射到理论轴：有偏差才升高，平稳时显示“平稳”。</div>
    </div>
  `;
  return expTheoryVisualShell("理论量化视图", "把诊断建议映射到 PEN、大五、依恋风格和自我决定理论四条轴，方便看偏差集中在哪里。", body, `诊断：${diagnostics.length}`);
}

export function personaStandardizationDraftState() {
  if (!state.personaStandardizationQuestionnaire) {
    state.personaStandardizationQuestionnaire = { strength: "medium", persona_id: "", source_text: "", supplement_text: "", style_reference_text: null, use_pasted_source: false, base_confirmed: false, style_choices: {}, style_custom: {}, style_feedback: {} };
  }
  return state.personaStandardizationQuestionnaire;
}

export function personaStyleReferenceText(draft = personaStandardizationDraftState()) {
  const raw = draft.style_reference_text === null || draft.style_reference_text === undefined
    ? draft.supplement_text
    : draft.style_reference_text;
  return String(raw || "").trim().slice(0, PERSONA_STYLE_REFERENCE_LIMIT);
}

export function personaStyleQuestionnaire(draft = collectPersonaStandardizationQuestionnaire()) {
  const questionnaire = {};
  personaStandardizationStyleHints.forEach(([key]) => { questionnaire[key] = draft[key] || ""; });
  questionnaire.strength = draft.strength || "medium";
  questionnaire.style_reference_text = personaStyleReferenceText(draft);
  questionnaire.style_reference_limit = PERSONA_STYLE_REFERENCE_LIMIT;
  return questionnaire;
}

export function personaStandardizationCurrentTemplate() {
  const textarea = document.querySelector("[data-persona-standard-template]");
  return textarea?.value || state.personaStandardizationDraft?.draft?.template || "";
}

export function personaStandardizationStyleSummary() {
  const styleBlock = state.personaStandardizationStyleSummaryDraft?.draft?.style_block || "";
  return personaStandardizationStripExportOnlyStyleSections(formatPersonaTemplateForEditing(styleBlock));
}

export function personaStandardizationStripExportOnlyStyleSections(text) {
  let source = String(text || "").replace(/\r\n?/g, "\n");
  ["格式示例", "预设特殊场景"].forEach((heading) => {
    source = source.replace(new RegExp(`\\n?【${heading}】[\\s\\S]*?(?=\\n【[^】]{2,36}】|$)`, "u"), "\n");
    source = source.replace(new RegExp(`\\n?#{2,6}\\s*${heading}[\\s\\S]*?(?=\\n#{1,6}\\s+|\\n【[^】]{2,36}】|$)`, "u"), "\n");
  });
  source = source
    .replace(/[（(]\s*(?:如|例如|比如)[^）)\n]{1,120}[）)]/gu, "")
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      if (/^\d+[.、]\s*/u.test(trimmed)) return false;
      if (/^(用户|回复|User|Assistant)\s*[:：]/u.test(trimmed)) return false;
      return true;
    })
    .join("\n");
  return source.replace(/\n{3,}/g, "\n\n").trim();
}

export function personaStandardizationStripConcreteExamples(text) {
  return String(text || "")
    .replace(/\r\n?/g, "\n")
    .replace(/[（(]\s*(?:如|例如|比如)[^）)\n]{1,180}[）)]/gu, "")
    .replace(/[（(]\s*[“"『「][^”"』」\n]{1,80}[”"』」]\s*[）)]/gu, "")
    .replace(
      /(?:如|例如|比如)\s*[“"『「][^”"』」\n]{1,80}[”"』」](?:[、，,]\s*[“"『「][^”"』」\n]{1,80}[”"』」]){0,4}/gu,
      "相关表达",
    )
    .replace(/[（(]\s*([。；;，,])/gu, "$1")
    .replace(/([。；;，,])\s*[）)]/gu, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function personaStandardizationSanitizeFinalExport(text) {
  let source = personaStandardizationStripConcreteExamples(
    personaStandardizationStripExportOnlyStyleSections(text),
  );
  source = source.replace(
    /\n?在对应情景下优先按以下形式回复[\s\S]*?(?=\n【格式示例】|\n【错误格式】|\n####\s*预设特殊场景|<\/Output_Constraints>|\n#\s+|\n<\/Role_Profile>|\n?$)/u,
    "\n",
  );
  source = personaStandardizationStripExportOnlyStyleSections(source);
  return source
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

export function personaStandardizationMergedTemplate() {
  const base = personaStandardizationStripConcreteExamples(personaStandardizationCurrentTemplate());
  const style = personaStandardizationStyleSummary();
  if (!base || !style) return base || style;
  let merged = base;
  const styleForConstraints = style.replace(/^【说话方式与对话习惯】\s*/u, "").trim();
  if (/####\s*对话风格[\s\S]*?(?=####\s*格式示例|####\s*错误格式|####\s*预设特殊场景|<\/Output_Constraints>)/u.test(merged)) {
    merged = merged.replace(
      /####\s*对话风格[\s\S]*?(?=####\s*格式示例|####\s*错误格式|####\s*预设特殊场景|<\/Output_Constraints>)/u,
      `#### 对话风格\n\n${styleForConstraints}\n\n`,
    );
  }
  if (/【待确认说话方式】[\s\S]*$/u.test(merged)) {
    merged = merged.replace(/【待确认说话方式】[\s\S]*$/u, "").trim();
  }
  merged = merged.replace(/^\s*[-•]?\s*\[STYLE_PENDING\]\s*$/gm, "").replace(/\n{3,}/g, "\n\n").trim();
  if (merged !== base) return `${personaStandardizationSanitizeFinalExport(merged).trim()}\n`;
  if (base.includes("【待确认说话方式】")) {
    return personaStandardizationSanitizeFinalExport(base.replace(/【待确认说话方式】[\s\S]*$/u, style));
  }
  return personaStandardizationSanitizeFinalExport(`${base.trim()}\n\n${style}`);
}

export function personaStandardizationSplitSections(text) {
  const source = formatPersonaTemplateForEditing(text);
  if (!source) return [];
  const marker = /(^|\n)(#{1,6}\s+[^\n]+|【[^】]{2,36}】)/g;
  const matches = [];
  let found;
  while ((found = marker.exec(source)) !== null) {
    matches.push({
      start: found.index + found[1].length,
      title: found[2].trim(),
    });
  }
  if (!matches.length) {
    return [{ id: "section_1", title: "未分段内容", content: source.trim() }];
  }
  const sections = [];
  const firstStart = matches[0].start;
  const prefix = source.slice(0, firstStart).trim();
  if (prefix) {
    sections.push({ id: "section_intro", title: "开头说明", content: prefix });
  }
  matches.forEach((item, index) => {
    const next = matches[index + 1]?.start ?? source.length;
    const block = source.slice(item.start, next).trim();
    const content = block.replace(item.title, "").trim();
    if (!content && !item.title) return;
    sections.push({
      id: `section_${index + 1}`,
      title: item.title.replace(/^#{1,6}\s*/u, ""),
      heading: item.title.match(/^(#{1,6})\s+/u)?.[1] || "",
      content: content || "",
    });
  });
  return sections.filter((item) => item.title || item.content);
}

export function personaStandardizationSectionKind(title, content) {
  const normalizedTitle = String(title || "").replace(/^#{1,6}\s*/u, "").trim();
  const text = `${normalizedTitle}\n${content}`;
  if (/^(基本要求|基础要求|社交距离|内容限制|对话安全|初始化|预设特殊场景)$/u.test(normalizedTitle)) return "template";
  if (/说话|对话|口癖|句式|标点|格式示例|错误格式|特殊场景|回复|主动/u.test(text)) return "style";
  if (/关系|称呼|用户|互动/u.test(text)) return "relationship";
  if (/边界|安全|禁止|约束|不可|不要/u.test(text)) return "boundary";
  if (/世界|背景|经历|设定|身份|角色|档案|Profile/u.test(text)) return "profile";
  return "normalized";
}

export function personaStandardizationSourceTags(section, context) {
  const tags = [];
  const kind = personaStandardizationSectionKind(section.title, section.content);
  if (kind === "style") {
    tags.push("scenario_calibration");
  } else if (kind === "template") {
    tags.push("template_guardrail");
    tags.push("model_normalization");
  } else {
    tags.push("original_persona");
    tags.push("model_normalization");
    if (context.hasSupplement && /补充|偏好|示例|反例|聊天|记录/u.test(section.content)) {
      tags.push("supplement_material");
    }
  }
  if (/待确认|冲突|需要审核|可能|不确定|无法判断/u.test(section.content)) tags.push("needs_review");
  if (personaStandardizationRiskHits(section.content).length) tags.push("unsafe_long_term");
  return Array.from(new Set(tags));
}

export function personaStandardizationRiskHits(text) {
  const value = String(text || "");
  const risks = [
    ["短期时间线", /今天|明天|昨天|今晚|今早|刚刚|刚才|这会儿|此刻/u],
    ["临时天气/日程", /天气|下雨|气温|日程|正在上课|下班回家|通勤/u],
    ["隐私位置", /地址|住址|小区|楼栋|门牌|定位|公司地址|学校地址/u],
    ["插件/模型配置", /插件配置|模型供应商|供应商|Provider|API|工具调用|缓存|token|QQ号|target_/iu],
    ["流程痕迹", /问卷|候选|证据|校准|第一阶段|第二阶段|用户选择/u],
  ];
  return risks.filter(([, pattern]) => pattern.test(value)).map(([label]) => label);
}

export function personaStandardizationConflictItems(baseText, styleText) {
  const base = String(baseText || "");
  const style = String(styleText || "");
  const pairs = [
    ["克制程度", /克制|沉稳|寡言|冷淡|少话/u, /撒娇|黏|热情|频繁|主动索取|高频/u],
    ["主动强度", /不主动|少主动|被动|不打扰/u, /主动|监督|提醒|索取|查岗/u],
    ["表达形式", /不用动作|无动作|不写动作|纯文字/u, /动作|摸摸|抱|亲|旁白/u],
    ["语气强度", /温柔|礼貌|柔和/u, /毒舌|威胁|讽刺|命令/u],
    ["回复长度", /详细|解释|长篇|完整/u, /短句|极简|少解释|半句/u],
  ];
  return pairs
    .filter(([, basePattern, stylePattern]) => basePattern.test(base) && stylePattern.test(style))
    .map(([title]) => title);
}

export function personaStandardizationBuildFinalEditor() {
  const finalText = personaStandardizationMergedTemplate();
  const baseText = personaStandardizationCurrentTemplate();
  const styleText = personaStandardizationStyleSummary();
  const draft = personaStandardizationDraftState();
  const context = { hasSupplement: Boolean(String(draft.supplement_text || "").trim()) };
  const conflicts = personaStandardizationConflictItems(baseText, styleText);
  const sections = personaStandardizationSplitSections(finalText).map((section, index) => {
    const tags = personaStandardizationSourceTags(section, context);
    if (conflicts.length && personaStandardizationSectionKind(section.title, section.content) === "style") {
      tags.push("conflict");
    }
    return {
      id: `final_${index + 1}`,
      title: section.title || `段落 ${index + 1}`,
      heading: section.heading || "",
      content: section.content || "",
      tags: Array.from(new Set(tags)),
      risks: personaStandardizationRiskHits(`${section.title}\n${section.content}`),
    };
  });
  const counts = {};
  sections.forEach((section) => {
    (section.tags || []).forEach((tag) => { counts[tag] = (counts[tag] || 0) + 1; });
  });
  return {
    sections,
    counts,
    conflicts,
    generated_at: new Date().toLocaleString(),
  };
}

export function personaStandardizationEnsureFinalEditor() {
  if (!state.personaStandardizationStyleSummaryDraft) return null;
  if (!state.personaStandardizationFinalEditor) {
    state.personaStandardizationFinalEditor = personaStandardizationBuildFinalEditor();
  }
  return state.personaStandardizationFinalEditor;
}

export function collectPersonaFinalEditor(root = document) {
  const editor = state.personaStandardizationFinalEditor;
  if (!editor) return "";
  const scope = root || document;
  const sections = (editor.sections || []).map((section) => {
    const titleInput = scope.querySelector(`[data-persona-final-title="${section.id}"]`);
    const contentInput = scope.querySelector(`[data-persona-final-content="${section.id}"]`);
    const title = String(titleInput?.value ?? section.title ?? "").trim();
    const content = formatPersonaTemplateForEditing(contentInput?.value ?? section.content ?? "");
    if (!title && !content) return "";
    const header = title.startsWith("#") || title.startsWith("【") ? title : `${section.heading || "#"} ${title}`;
    return `${header}\n${content}`.trim();
  }).filter(Boolean);
  return personaStandardizationSanitizeFinalExport(formatPersonaTemplateForEditing(sections.join("\n\n")));
}

export function personaStyleFingerprintText(keys, limit = 8) {
  const fingerprint = state.personaStandardizationStyleSummaryDraft?.draft?.style_fingerprint || {};
  const rows = [];
  keys.forEach((key) => {
    const items = Array.isArray(fingerprint[key]) ? fingerprint[key] : [];
    items.forEach((item) => {
      const text = String(item || "").trim();
      if (text && rows.length < limit) rows.push(text);
    });
  });
  return rows;
}

export function personaVoiceRuleLines(title, lines) {
  const clean = Array.from(new Set((lines || []).map((line) => String(line || "").trim()).filter(Boolean)));
  return [`${title}：`, ...clean.slice(0, 12).map((line) => `- ${line}`)].join("\n");
}

export function buildPersonaVoiceChannelDrafts(root = document) {
  const finalText = collectPersonaFinalEditor(root) || personaStandardizationMergedTemplate();
  const summary = state.personaStandardizationStyleSummaryDraft?.draft || {};
  const styleRules = Array.isArray(summary.style_rules) ? summary.style_rules.filter(Boolean).slice(0, 5) : [];
  const avoidRules = Array.isArray(summary.avoid_rules) ? summary.avoid_rules.filter(Boolean).slice(0, 5) : [];
  const lexical = personaStyleFingerprintText(["lexical_habits", "sentence_patterns", "length_rhythm", "punctuation"], 7);
  const relation = personaStyleFingerprintText(["relationship_tone", "emotion_expression", "opening_closing"], 7);
  const proactive = personaStyleFingerprintText(["opening_closing", "questioning", "topic_shift", "relationship_tone"], 7);
  const stableStyleHint = finalText
    .split(/\n+/)
    .map((line) => line.trim())
    .filter((line) => /口癖|句式|长度|标点|开头|收尾|主动|追问|转移|亲密|拒绝|安慰|错误格式|避免/u.test(line))
    .slice(0, 8);
  return {
    conversation: personaVoiceRuleLines("对话风格", [
      "用于私聊/群聊真正外发的聊天回复，不用于日程、创作或内部念头。",
      ...lexical,
      ...relation.slice(0, 3),
      ...styleRules.slice(0, 3),
      "复杂问题、教程、排障和用户明确要求详细说明时，信息完整性优先。",
      avoidRules.length ? `避免：${avoidRules.join("；")}` : "避免助手腔、总结腔、过度确认和硬问是否继续。",
    ]),
    creative: personaVoiceRuleLines("创作风格", [
      "用于日记、QQ 空间、私下创作和文案；可以比聊天更完整，但仍像角色本人写下的东西。",
      "保留角色观察角度、词感和节奏，不把聊天短句机械套进作品。",
      ...stableStyleHint.slice(0, 4),
      "减少排比、升华、哲理总结、万能比喻和营销文案式收尾。",
      avoidRules.length ? `避免：${avoidRules.join("；")}` : "避免 AI 作文腔、散文模板和“仿佛/像是/某种意义上”的空泛连接。",
    ]),
    planning: personaVoiceRuleLines("计划风格", [
      "用于日程、主动候选和行动倾向；描述角色会怎样安排自己，不是最终聊天台词。",
      "计划应体现角色稳定偏好、拖延/守约/探索/等待/靠近等倾向。",
      "日程里只写角色自己的行动、环境和状态，不把内心分析或用户关系写成任务清单。",
      ...relation.slice(0, 4),
      "主动候选必须有具体由头，没有切口就留空或延后。",
    ]),
    inner: personaVoiceRuleLines("内心活动风格", [
      "用于内部动机、念头、犹豫和状态余波，默认不可直接外发。",
      "可以更碎、更主观、更像脑内一闪而过，但不能写成系统分析。",
      ...relation.slice(0, 3),
      ...proactive.slice(0, 3),
      "禁止出现插件、模型、系统、策略分数、工具调用、我判断用户需要陪伴等后台措辞。",
    ]),
    proactive: personaVoiceRuleLines("主动开口风格", [
      "用于把主动动机变成最终外发的一句话或短消息。",
      "先找具体由头：眼前物、日程缝隙、刚发生的小事、共同话题或真实约定；不要泛泛问在不在。",
      ...proactive,
      "低压力、可接话，发完能自然停住；不要索取回应、汇报任务或解释为什么主动。",
      "避免“你方便聊聊吗”“我想和你分享一下”“希望你今天过得不错”“要不要继续这个话题”等 AI 味开场。",
    ]),
  };
}

export function personaVoiceDraftState(root = document) {
  if (!state.personaStandardizationVoiceDraft) {
    state.personaStandardizationVoiceDraft = buildPersonaVoiceChannelDrafts(root);
    state.personaStandardizationVoiceDraftStale = false;
  }
  return state.personaStandardizationVoiceDraft;
}

export function collectPersonaVoiceDraft(root = document) {
  const draft = { ...personaVoiceDraftState(root) };
  const scope = root || document;
  scope.querySelectorAll?.("[data-persona-voice-channel]").forEach((input) => {
    const channel = input.dataset.personaVoiceChannel || "";
    if (channel) draft[channel] = input.value || "";
  });
  state.personaStandardizationVoiceDraft = draft;
  return draft;
}

export function personaVoiceSettingsPayload(root = document) {
  const draft = collectPersonaVoiceDraft(root);
  const settings = { enable_persona_voice_channels: true };
  personaVoiceChannelMeta.forEach(([channel, , key]) => {
    settings[key] = String(draft[channel] || "").trim();
  });
  return { settings };
}

export function formatPersonaTemplateForEditing(value) {
  let text = String(value || "").replace(/\r\n/g, "\n").trim();
  if (!text) return "";
  text = text.replace(/^\s*#{1,6}\s*$/gm, "");
  text = text.replace(/^\s*[•·]\s*$/gm, "");
  text = text.replace(/^\s*(#{1,6})\s*(.+)$/gm, (_, hashes, title) => `${hashes} ${String(title || "").trim()}`);
  text = text.replace(/\s*(#{1,6}\s+)/g, "\n\n$1");
  text = text.replace(/\s*(【[^】]{2,28}】)/g, "\n\n$1\n");
  text = text.replace(/\n[ \t]*[-•]\s*\n/g, "\n");
  text = text.replace(/\n{3,}/g, "\n\n").trim();
  return text;
}

export function collectPersonaStyleEvidence() {
  const draft = personaStandardizationDraftState();
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  return scenarios.map((scenario) => {
    const selectedId = draft.style_choices?.[scenario.id] || "";
    const selected = (scenario.options || []).find((item) => item.id === selectedId) || null;
    const custom = (draft.style_custom?.[scenario.id] || "").trim();
    const feedback = (draft.style_feedback?.[scenario.id] || "").trim();
    return {
      id: scenario.id || "",
      title: scenario.title || "",
      prompt: scenario.prompt || "",
      selected_id: selected?.id || "",
      selected_label: selected?.label || "",
      chosen_text: selected?.text || "",
      custom_text: custom,
      feedback,
      traits: selected?.traits || [],
    };
  }).filter((item) => item.selected_id || item.custom_text);
}

export function personaStyleScenarioProgress() {
  const draft = personaStandardizationDraftState();
  const styleDraft = state.personaStandardizationStyleDraft || {};
  const scenarios = styleDraft?.draft?.scenarios || [];
  const scenarioTotal = Number(styleDraft.scenario_total || styleDraft?.draft?.scenario_total || 0);
  const total = Math.max(scenarios.length, Number.isFinite(scenarioTotal) ? scenarioTotal : 0);
  const hasMore = Boolean(styleDraft.has_more) || scenarios.length < total;
  let answered = 0;
  scenarios.forEach((scenario) => {
    const selected = draft.style_choices?.[scenario.id] || "";
    const custom = (draft.style_custom?.[scenario.id] || "").trim();
    if (selected || custom) answered += 1;
  });
  return {
    total,
    loaded: scenarios.length,
    answered,
    missing: Math.max(0, total - answered),
    loadedMissing: Math.max(0, scenarios.length - answered),
    hasMore,
    complete: total > 0 && answered >= total && !hasMore,
  };
}

export function personaStyleScenarioId(scenario) {
  return String(scenario?.id || "");
}

export function personaStyleScenarioAnswered(scenario, draft = personaStandardizationDraftState()) {
  const scenarioId = personaStyleScenarioId(scenario);
  if (!scenarioId) return false;
  const selected = draft.style_choices?.[scenarioId] || "";
  const custom = (draft.style_custom?.[scenarioId] || "").trim();
  return Boolean(selected || custom);
}

export function personaStyleScenarioFocusId() {
  return String(state.personaStandardizationStyleScenarioFocusId || "");
}

export function setPersonaStyleScenarioFocus(scenarioId = "") {
  state.personaStandardizationStyleScenarioFocusId = String(scenarioId || "");
}

export function personaStyleNextUnansweredScenarioId(afterScenarioId = "") {
  const draft = personaStandardizationDraftState();
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  if (!scenarios.length) return "";
  const afterIndex = scenarios.findIndex((scenario) => personaStyleScenarioId(scenario) === String(afterScenarioId || ""));
  const ordered = afterIndex >= 0
    ? [...scenarios.slice(afterIndex + 1), ...scenarios.slice(0, afterIndex + 1)]
    : scenarios;
  const next = ordered.find((scenario) => !personaStyleScenarioAnswered(scenario, draft));
  return personaStyleScenarioId(next);
}

export function personaStyleAdjacentScenarioId(scenarioId = "", direction = 1) {
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  if (!scenarios.length) return "";
  const index = scenarios.findIndex((scenario) => personaStyleScenarioId(scenario) === String(scenarioId || ""));
  const nextIndex = index + (direction < 0 ? -1 : 1);
  if (index < 0 || nextIndex < 0 || nextIndex >= scenarios.length) return "";
  return personaStyleScenarioId(scenarios[nextIndex]);
}

export function personaStyleActiveScenarioInfo() {
  const draft = personaStandardizationDraftState();
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  const focusId = personaStyleScenarioFocusId();
  let index = focusId ? scenarios.findIndex((scenario) => personaStyleScenarioId(scenario) === focusId) : -1;
  if (index < 0) index = scenarios.findIndex((scenario) => !personaStyleScenarioAnswered(scenario, draft));
  return {
    scenario: index >= 0 ? scenarios[index] : null,
    index,
    total: scenarios.length,
  };
}

export function personaStyleLoadedUnansweredCount() {
  const draft = personaStandardizationDraftState();
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  return scenarios.filter((scenario) => !personaStyleScenarioAnswered(scenario, draft)).length;
}

export function personaStyleShouldPrefetchNextBatch() {
  const styleDraft = state.personaStandardizationStyleDraft || null;
  if (!styleDraft || state.personaStandardizationStyleStale || state.personaStandardizationBaseStale) return false;
  if (state.personaStandardizationStyleBatchLoading) return false;
  const scenarios = styleDraft?.draft?.scenarios || [];
  if (!scenarios.length) return false;
  const progress = personaStyleScenarioProgress();
  const hasMore = Boolean(styleDraft.has_more) || scenarios.length < progress.total;
  return hasMore && personaStyleLoadedUnansweredCount() <= 1;
}

export function renderPersonaFinalEditor(styleSummaryResult, styleStale) {
  if (!styleSummaryResult) return "";
  const editor = personaStandardizationEnsureFinalEditor();
  if (!editor) return "";
  const voiceDraft = styleSummaryResult && !styleStale ? personaVoiceDraftState() : {};
  const voiceStale = Boolean(state.personaStandardizationVoiceDraftStale);
  const count = (key) => Number(editor.counts?.[key] || 0);
  const sourceStats = [
    ["原人格继承", count("original_persona"), "ok"],
    ["补充资料推导", count("supplement_material"), "info"],
    ["场景校准推导", count("scenario_calibration"), "style"],
    ["格式整理", count("model_normalization"), "neutral"],
    ["需确认", count("needs_review"), "warn"],
    ["冲突/风险", count("conflict") + count("unsafe_long_term"), "danger"],
  ];
  const navRows = (editor.sections || []).map((section, index) => `
    <a href="#personaFinal_${escapeHtml(section.id)}">
      <span>${escapeHtml(String(index + 1).padStart(2, "0"))}</span>
      <b>${escapeHtml(section.title || `段落 ${index + 1}`)}</b>
      <small>${escapeHtml((section.tags || []).map((tag) => personaStandardizationTagLabels[tag] || tag).slice(0, 2).join(" / ") || "待审核")}</small>
    </a>
  `).join("");
  const sectionRows = (editor.sections || []).map((section, index) => {
    const tags = (section.tags || []).map((tag) => `<span class="${escapeHtml(tag)}">${escapeHtml(personaStandardizationTagLabels[tag] || tag)}</span>`).join("");
    const risks = (section.risks || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return `
      <section class="persona-final-section ${section.tags?.includes("conflict") ? "has-conflict" : ""} ${section.tags?.includes("unsafe_long_term") ? "has-risk" : ""}" id="personaFinal_${escapeHtml(section.id)}">
        <header>
          <div>
            <span>${escapeHtml(String(index + 1).padStart(2, "0"))}</span>
            <input type="text" data-persona-final-title="${escapeHtml(section.id)}" value="${escapeHtml(section.title || "")}" aria-label="段落标题">
          </div>
          <div class="persona-final-tags">${tags}</div>
        </header>
        ${risks ? `<div class="persona-final-risk"><b>不建议直接长期写入的线索</b><ul>${risks}</ul></div>` : ""}
        <textarea rows="${Math.min(18, Math.max(5, String(section.content || "").split("\n").length + 2))}" data-persona-final-content="${escapeHtml(section.id)}" aria-label="段落正文">${escapeHtml(section.content || "")}</textarea>
      </section>
    `;
  }).join("");
  const conflictRows = (editor.conflicts || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const reviewRows = (editor.sections || [])
    .filter((section) => (section.tags || []).some((tag) => ["conflict", "unsafe_long_term", "needs_review"].includes(tag)))
    .map((section) => `<li><b>${escapeHtml(section.title)}</b><span>${escapeHtml((section.tags || []).map((tag) => personaStandardizationTagLabels[tag] || tag).join(" / "))}</span></li>`)
    .join("");
  const voiceRows = personaVoiceChannelMeta.map(([channel, label, key, desc]) => `
    <label class="persona-voice-card">
      <header>
        <div>
          <b>${escapeHtml(label)}</b>
          <span>${escapeHtml(desc)}</span>
        </div>
        <code>${escapeHtml(key)}</code>
      </header>
      <textarea rows="8" data-persona-voice-channel="${escapeHtml(channel)}" aria-label="${escapeHtml(`${label}分通道规则`)}">${escapeHtml(voiceDraft[channel] || "")}</textarea>
    </label>
  `).join("");
  return `
    <section class="persona-final-editor">
      <header class="persona-final-head">
        <div>
          <b><span class="step-badge">4</span>最终人格编辑器</b>
          <span>逐段审核来源、冲突和长期可写入性。这里的内容才是最终复制入口。</span>
        </div>
        <button type="button" data-persona-standard-copy-final ${styleSummaryResult && !styleStale ? "" : "disabled"}>复制编辑器最终稿</button>
      </header>
      <div class="persona-final-stats">
        ${sourceStats.map(([label, value, tone]) => `<span class="${escapeHtml(tone)}"><b>${escapeHtml(String(value))}</b>${escapeHtml(label)}</span>`).join("")}
      </div>
      <div class="persona-final-layout">
        <nav class="persona-final-nav">
          <b>段落导航</b>
          ${navRows || `<p>暂无可编辑段落。</p>`}
        </nav>
        <div class="persona-final-main">
          ${sectionRows || `<div class="persona-standard-empty"><b>没有可编辑内容</b><span>请先生成风格规则。</span></div>`}
        </div>
        <aside class="persona-final-audit">
          <section>
            <b>冲突提示</b>
            ${conflictRows ? `<ul>${conflictRows}</ul>` : `<p>没有检测到明显“原人格底色”和“风格推导”的方向冲突。</p>`}
          </section>
          <section>
            <b>重点复核</b>
            ${reviewRows ? `<ul class="persona-final-review-list">${reviewRows}</ul>` : `<p>暂无高风险段落。仍建议通读后再复制。</p>`}
          </section>
          <section>
            <b>写入原则</b>
            <p>最终人格只保留稳定身份、关系、边界和说话习惯。天气、日程、地址、插件配置、一次性聊天上下文应交给运行时上下文，不写入长期人格。</p>
          </section>
        </aside>
      </div>
      <section class="persona-voice-apply">
        <header class="persona-voice-head">
          <div>
            <b><span class="step-badge">5</span>应用到插件表达风格</b>
            <span>从最终人格和风格指纹里提取短规则，分别写入对话、创作、计划、内心和主动链路。只有点击保存后才会写入插件配置。</span>
          </div>
          <div class="persona-voice-actions">
            <button type="button" class="ghost" data-persona-voice-regenerate ${styleSummaryResult && !styleStale ? "" : "disabled"}>重新生成分通道草稿</button>
            <button type="button" data-persona-voice-save ${styleSummaryResult && !styleStale && !voiceStale ? "" : "disabled"}>保存到插件表达风格</button>
          </div>
        </header>
        ${voiceStale ? `<div class="setup-guide-hint warn">最终人格内容已修改，下方分通道草稿可能不再对应最新文本。请先重新生成分通道草稿，再保存到插件表达风格。</div>` : ""}
        <div class="persona-voice-notes">
          <span>只保存短规则，不保存完整人格</span>
          <span>内心活动不会直接外发</span>
          <span>创作、对话、计划、主动分别注入</span>
          <span>保存前请逐项审核</span>
        </div>
        <div class="persona-voice-grid">${voiceRows}</div>
      </section>
    </section>
  `;
}

export function invalidatePersonaStyleSummary(root) {
  state.personaStandardizationStyleSummaryDraft = null;
  state.personaStandardizationFinalEditor = null;
  state.personaStandardizationVoiceDraft = null;
  state.personaStandardizationVoiceDraftStale = false;
  const scope = root || document;
  const summary = scope.querySelector?.("[data-persona-style-summary]");
  if (summary) summary.value = "";
  scope.querySelectorAll?.("[data-persona-standard-copy-final]").forEach((button) => {
    button.disabled = true;
  });
}

export function invalidatePersonaStyleDraft(root) {
  state.personaStandardizationStyleStale = true;
  state.personaStandardizationStyleSummaryDraft = null;
  state.personaStandardizationStyleScenarioFocusId = "";
  invalidatePersonaStyleSummary(root);
  const scope = root || document;
  scope.querySelectorAll?.("[data-persona-style-summary-generate], [data-persona-style-retry]").forEach((button) => {
    button.disabled = true;
  });
}

export function invalidatePersonaStandardizationDraft(root) {
  state.personaStandardizationBaseStale = true;
  invalidatePersonaStyleDraft(root);
  const draft = personaStandardizationDraftState();
  draft.base_confirmed = false;
  const scope = root || document;
  scope.querySelectorAll?.("[data-persona-standard-copy], [data-persona-style-generate], [data-persona-style-retry]").forEach((button) => {
    button.disabled = true;
  });
}

export function personaStandardizationStepClass(status) {
  return `persona-flow-step ${status}`;
}

export function renderPersonaStandardizationWorkbench() {
  const draft = personaStandardizationDraftState();
  if (!draft.persona_id && !draft.use_pasted_source && (state.roleplayPersonas || []).length) {
    draft.persona_id = state.roleplayPersonas[0]?.id || "";
  }
  const result = state.personaStandardizationDraft || null;
  const styleResult = state.personaStandardizationStyleDraft || null;
  const baseStale = Boolean(state.personaStandardizationBaseStale);
  const styleStale = Boolean(state.personaStandardizationStyleStale || baseStale);
  const baseConfirmed = Boolean(draft.base_confirmed && result && !baseStale);
  const score = result?.draft?.score || {};
  const sc = (v) => v >= 80 ? "good" : v >= 50 ? "ok" : "low";
  const styleHintRows = personaStandardizationStyleHints.map(([key, title, hint, placeholder]) => `
    <label class="persona-standard-question">
      <span><b>${escapeHtml(title)}</b><small>${escapeHtml(hint)}</small></span>
      <textarea rows="3" data-persona-standard-field="${escapeHtml(key)}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(draft[key] || "")}</textarea>
    </label>
  `).join("");
  const summaryRows = (result?.draft?.change_summary || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const warningRows = (result?.draft?.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const checklistRows = (result?.draft?.review_checklist || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const styleWarningRows = (styleResult?.draft?.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const styleSummaryResult = state.personaStandardizationStyleSummaryDraft || null;
  const finalEditor = styleSummaryResult && !styleStale ? personaStandardizationEnsureFinalEditor() : null;
  const styleSummaryWarningRows = (styleSummaryResult?.draft?.warnings || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const styleSummaryChecklistRows = (styleSummaryResult?.draft?.review_checklist || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const fingerprintLabels = {
    lexical_habits: "口癖词",
    sentence_patterns: "句式",
    length_rhythm: "长短节奏",
    punctuation: "标点",
    opening_closing: "开头收尾",
    emotion_expression: "情绪表达",
    questioning: "追问习惯",
    topic_shift: "话题切换",
    relationship_tone: "关系语气",
  };
  const fingerprintRows = Object.entries(styleSummaryResult?.draft?.style_fingerprint || {})
    .map(([key, items]) => {
      const rows = Array.isArray(items) ? items.filter(Boolean) : [];
      if (!rows.length) return "";
      return `<section><b>${escapeHtml(fingerprintLabels[key] || key)}</b><ul>${rows.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
    })
    .filter(Boolean)
    .join("");
  const baseTemplateText = formatPersonaTemplateForEditing(result?.draft?.template || "");
  const baseResultMeta = result ? [
    result.persona_id ? `来源人格：${result.persona_id}` : "来源：当前 AstrBot 人格",
    result.provider_id || "主模型",
    `原人格 ${String(result.source_chars || 0)} 字`,
    Number(result.supplement_chars || 0) ? `参考 ${String(result.supplement_chars || 0)} 字` : "",
    Number(result.max_tokens || 0) ? `输出预算 ${String(result.max_tokens)} token` : "",
  ].filter(Boolean).join(" · ") : "";
  const scenarioCount = styleResult?.draft?.scenarios?.length || 0;
  const evidenceCount = collectPersonaStyleEvidence().length;
  const styleProgress = personaStyleScenarioProgress();
  const flowSteps = [
    ["1", "基础设定", result ? (baseStale ? "问卷已改，需重新生成" : (baseConfirmed ? "已确认基本信息" : "请先审核并确认")) : "先选择/粘贴人格并生成基础稿", result && !baseStale && baseConfirmed ? "done" : "active"],
    ["2", "情景校准", scenarioCount ? (styleStale ? "偏好已改，需重新生成" : `已完成 ${styleProgress.answered}/${styleProgress.total} 个情景`) : (baseConfirmed ? "填写风格参考后生成候选" : "等待确认基础信息"), scenarioCount && !styleStale && styleProgress.complete ? "done" : (baseConfirmed ? "active" : "locked")],
    ["3", "风格规则", styleSummaryResult ? "已归纳，进入最终审核" : (scenarioCount && !styleStale ? (styleProgress.complete ? `已有 ${evidenceCount} 条证据` : `还差 ${styleProgress.missing} 个情景`) : "等待情景选择"), styleSummaryResult ? "done" : (scenarioCount && !styleStale && styleProgress.complete ? "active" : "locked")],
    ["4", "最终编辑", finalEditor ? `可审核 ${finalEditor.sections?.length || 0} 个段落` : "等待风格规则生成", finalEditor ? "active" : "locked"],
  ].map(([index, title, desc, status]) => `
    <div class="${personaStandardizationStepClass(status)}">
      <strong>${escapeHtml(index)}</strong>
      <span><b>${escapeHtml(title)}</b><small>${escapeHtml(desc)}</small></span>
    </div>
  `).join("");
  const scenarioList = styleResult?.draft?.scenarios || [];
  const activeScenarioInfo = personaStyleActiveScenarioInfo();
  const scenarioStepperHtml = scenarioList.length ? `
    <div class="persona-style-stepper">
      ${scenarioList.map((scenario, index) => {
        const scenarioId = personaStyleScenarioId(scenario);
        const answered = personaStyleScenarioAnswered(scenario, draft);
        const active = activeScenarioInfo.scenario && scenarioId === personaStyleScenarioId(activeScenarioInfo.scenario);
        return `<button type="button" class="${[active ? "active" : "", answered ? "done" : ""].filter(Boolean).join(" ")}" data-persona-style-focus="${escapeHtml(scenarioId)}" title="${escapeHtml(`${index + 1}. ${scenario.title || scenario.id}`)}">${escapeHtml(index + 1)}</button>`;
      }).join("")}
      ${styleProgress.total > scenarioList.length ? `<em>已加载 ${escapeHtml(scenarioList.length)} / ${escapeHtml(styleProgress.total)} 个</em>` : ""}
      ${state.personaStandardizationStyleBatchLoading ? `<em>下一组生成中...</em>` : ""}
    </div>
  ` : "";
  const scenarioRows = (activeScenarioInfo.scenario ? [activeScenarioInfo.scenario] : []).map((scenario) => {
    const selected = draft.style_choices?.[scenario.id] || "";
    const custom = draft.style_custom?.[scenario.id] || "";
    const feedback = draft.style_feedback?.[scenario.id] || "";
    const answered = Boolean(selected || String(custom || "").trim());
    const typeLabels = {
      passive_one_liner: "被动接话",
      active_one_liner: "主动开口",
      continuous_scene: "连续对话",
    };
    let rawPrompt = String(scenario.prompt || "").trim();
    const legacyPromptByScenarioId = {
      passive_unfulfilled_duty_admit: "模拟用户消息：（对应上文）用户指出角色有一件约定、日常或应做的小事还没完成，带一点催促或失望；具体措辞不固定。",
      passive_reason_evasion: "模拟用户消息：（对应上文）用户追问角色不愿解释或不想继续说的原因，压力来自“需要说清楚”；不要预设角色必须软弱或撒娇。",
      passive_forced_compromise: "模拟用户消息：（对应上文）用户坚持要求角色立刻接受某个做法、安排或互动方式；角色可按设定妥协、拒绝或保留余地。",
      passive_weak_denial: "模拟用户消息：（对应上文）用户怀疑角色做了某件她不想承认、没把握或容易被误会的小事；角色需要按设定回应质疑。",
      passive_detail_report: "模拟用户消息：（对应上文）用户要求角色补充进度、时间、位置或状态细节；重点是信息压缩，不限定具体场景。",
      passive_fixed_counter: "模拟用户消息：（对应上文）用户把错误、锅或责任推向角色；角色需要用自己的方式挡一下，不展开长辩论。",
      passive_service_accept: "模拟用户消息：（对应上文）用户提供照顾、投喂、帮忙或替角色处理一件小事；不要预设服从关系或固定动作。",
      passive_preference_giveup: "模拟用户消息：（对应上文）用户要求角色在几个选项里表态；角色不想明确选、没把握，或把选择权让回去。",
      passive_lie_exposed: "模拟用户消息：（对应上文）用户发现角色刚才在嘴硬、遮掩、逞强或说法前后不一致；角色需要收住或承认。",
      passive_affection_confirm: "模拟用户消息：（对应上文）用户索要情感回应、关系确认或一句更明确的态度；亲密程度必须按基础设定决定。",
      active_daily_supervision: "模拟主动意图：角色想提醒对方一个日常节点、习惯或约定；强度、称呼和是否调侃都必须按人物关系决定。",
      active_bodylike_affection: "模拟主动意图：角色想主动表达亲近或安抚；可以是短句、表情化回应或普通关心，不预设肢体动作。",
      active_shared_activity: "模拟主动意图：角色想到一件可以一起做、之后再聊或顺手分享的小事，低压力邀请对方接住。",
      active_response_or_gift_probe: "模拟主动意图：角色想试探性地要一点回应、反馈、关注或确认；不预设礼物、奖励或服从关系。",
      active_achievement_share: "模拟主动意图：角色有一个小进展、小成就或趣事想分享；是否期待回应由人物设定决定。",
      chain_misunderstanding_repair: "模拟连续上文：上一轮可能出现理解、措辞或语气偏差，用户仍在意或需要澄清；角色按自身设定选择承认、补正、轻轻带过或重新接回话题，不预设道歉方式。",
      chain_support_followup: "模拟连续上文：用户透露求助、分享、犹豫或吐槽的信号，但信息还不完整；角色按自身设定决定先接住、问一句、给最小建议，或只是陪着对方继续说。",
      chain_boundary_adjustment: "模拟连续上文：用户对角色的能力、关系距离或互动方式有期待，但和角色设定不完全匹配；角色按自身设定调整回应范围，不预设拒绝、服从或替代方案。",
      chain_shared_plan_negotiation: "模拟连续上文：双方正在聊一个可能变化的安排、约定、共同活动或协作事项；角色按自身设定选择确认、保留余地、继续协调或先轻轻收住。",
      chain_topic_shift_continuation: "模拟连续上文：用户补充了新重点、改了方向，或把话题从上一轮自然带到别处；角色按自身设定判断顺着新重点、轻轻回扣旧话题，或先接住当下情绪。",
    };
    const canonicalTitleByScenarioId = {
      passive_unfulfilled_duty_admit: "被指出未履行事项时的回应",
      passive_reason_evasion: "被追问具体原因时的回应",
      passive_forced_compromise: "被强制要求时的边界回应",
      passive_weak_denial: "被质疑行为时的回应",
      passive_detail_report: "被要求报备细节时的简化回复",
      passive_fixed_counter: "被指责错误时的短回应",
      passive_service_accept: "被照顾或投喂时的回应",
      passive_preference_giveup: "被问及偏好时的选择回应",
      passive_lie_exposed: "被发现遮掩时的回应",
      passive_affection_confirm: "被索取情感回应时的确认方式",
      chain_misunderstanding_repair: "轻微误会后的回到正轨",
      chain_support_followup: "信息不完整时的承接",
      chain_boundary_adjustment: "期待不一致时的调整",
      chain_shared_plan_negotiation: "共同安排中的继续协商",
      chain_topic_shift_continuation: "话题转向后的自然延续",
    };
    if (legacyPromptByScenarioId[scenario.id]) {
      rawPrompt = legacyPromptByScenarioId[scenario.id];
    }
    const scenarioTitle = canonicalTitleByScenarioId[scenario.id] || scenario.title || scenario.id;
    const promptLabel = rawPrompt.startsWith("模拟用户消息")
      ? "模拟用户消息"
      : rawPrompt.startsWith("模拟主动意图")
        ? "模拟主动意图"
        : rawPrompt.startsWith("模拟连续上文")
          ? "模拟连续上文"
          : rawPrompt.startsWith("通用链路")
            ? "连续上文"
            : "校准情景";
    const promptText = rawPrompt
      .replace(/^模拟用户消息[:：]\s*/, "")
      .replace(/^模拟主动意图[:：]\s*/, "")
      .replace(/^模拟连续上文[:：]\s*/, "")
      .replace(/^通用链路[:：]\s*/, "")
      .trim();
    const currentIndex = activeScenarioInfo.index >= 0 ? activeScenarioInfo.index + 1 : 1;
    const nextLoadedId = personaStyleNextUnansweredScenarioId(scenario.id);
    const hasMore = Boolean(styleResult?.has_more) || scenarioList.length < styleProgress.total;
    const loadingNext = Boolean(state.personaStandardizationStyleBatchLoading);
    const previousLoadedId = personaStyleAdjacentScenarioId(scenario.id, -1);
    const nextLoadedSequentialId = personaStyleAdjacentScenarioId(scenario.id, 1);
    const nextButtonText = nextLoadedId
      ? "完成，进入下一个情景"
      : styleProgress.complete
        ? "全部完成，可以生成风格规则"
        : hasMore
          ? (loadingNext ? "下一组三个情景生成中" : "完成，加载下一组三个情景")
          : "完成";
    const options = (scenario.options || []).map((option) => `
      <label class="persona-style-option ${selected === option.id ? "selected" : ""}">
        <input type="radio" name="personaStyle_${escapeHtml(scenario.id)}" value="${escapeHtml(option.id)}" data-persona-style-choice="${escapeHtml(scenario.id)}" ${selected === option.id ? "checked" : ""}>
        <span>
          <b><strong>${escapeHtml(option.label || option.id)}</strong>${selected === option.id ? `<i>已选</i>` : ""}</b>
          <em>${escapeHtml(option.text || "")}</em>
          ${option.traits?.length ? `<small>${escapeHtml(option.traits.join(" / "))}</small>` : ""}
        </span>
      </label>
    `).join("");
    return `
      <section class="persona-style-scenario ${answered ? "answered" : "missing"}">
        <header>
          <div>
            <span class="persona-style-kicker">当前校准项</span>
            <b>${escapeHtml(scenarioTitle)}</b>
          </div>
          <em>${escapeHtml(typeLabels[scenario.type] || "情景")} · ${answered ? "已校准" : "待选择"}</em>
        </header>
        <div class="persona-style-simulated-context">
          <span>${escapeHtml(promptLabel)}</span>
          <p>${escapeHtml(promptText || rawPrompt || "看下面候选，选择最像角色会说的一句。")}</p>
          <small>${escapeHtml(scenario.type === "passive_one_liner" ? "下面三张卡都是角色接这个上文意图后的回复候选，不是固定台词。" : scenario.type === "active_one_liner" ? "下面三张卡都是角色按这个意图主动发出的下一句话候选。" : "下面三张卡都是这个连续场景里角色下一句该怎么接。")}</small>
        </div>
        <div class="persona-style-options">${options}</div>
        <label class="persona-standard-question">
          <span><b>自填更贴近的角色回复</b><small>如果三句都不准，直接写一句更像她会接的话。它只作为归纳证据，不会原样写进最终稿。</small></span>
          <textarea rows="2" data-persona-style-custom="${escapeHtml(scenario.id)}" placeholder="可选：按这个上文意图，写一句更像角色会说的话；填写后可不选上面的候选">${escapeHtml(custom)}</textarea>
        </label>
        <details class="persona-style-retry" ${feedback ? "open" : ""}>
          <summary>三个都不满意，写建议后重生成</summary>
          <div>
            <label>
              <span><b>重生成建议</b><small>只影响这个情景，不会改动其它情景。</small></span>
              <textarea rows="2" data-persona-style-feedback="${escapeHtml(scenario.id)}" placeholder="例如：不要太软，少解释，更像随口回一句">${escapeHtml(feedback)}</textarea>
            </label>
          <button type="button" class="ghost" data-persona-style-retry="${escapeHtml(scenario.id)}" ${styleStale ? "disabled" : ""}>重生成此情景</button>
          </div>
        </details>
        <footer class="persona-style-scenario-actions">
          <span>当前第 ${escapeHtml(currentIndex)} / ${escapeHtml(styleProgress.total || scenarioList.length || 1)} 个；每次只显示一个情景。</span>
          <div>
            <button type="button" class="ghost" data-persona-style-focus="${escapeHtml(previousLoadedId)}" ${!previousLoadedId ? "disabled" : ""}>上一个已加载</button>
            <button type="button" class="ghost" data-persona-style-focus="${escapeHtml(nextLoadedSequentialId)}" ${!nextLoadedSequentialId ? "disabled" : ""}>下一个已加载</button>
            <button type="button" data-persona-style-next="${escapeHtml(scenario.id)}" ${!answered || styleStale || (loadingNext && !nextLoadedId) ? "disabled" : ""}>${escapeHtml(nextButtonText)}</button>
          </div>
        </footer>
      </section>
    `;
  }).join("");
  const scenarioPanelHtml = scenarioRows || (scenarioCount ? `
    <div class="persona-standard-empty">
      <b>${state.personaStandardizationStyleBatchLoading ? "下一组三个情景生成中" : "当前已加载情景已完成"}</b>
      <span>${state.personaStandardizationStyleBatchLoading ? "等它回来后会自动显示下一个情景。" : "可以手动加载下一组三个情景；正常情况下完成第二个情景后会自动预取。"}</span>
      ${!state.personaStandardizationStyleBatchLoading && !styleProgress.complete ? `<button type="button" data-persona-style-load-more>加载下一组三个情景</button>` : ""}
    </div>
  ` : `<div class="persona-standard-empty"><b>还没有情景候选</b><span>确认基础信息后，模型会先生成前三个聊天场景候选。</span></div>`);
  const styleSummaryHtml = scenarioCount ? `
    <div class="persona-standard-result">
      <header>
        <div>
          <b><span class="step-badge">3</span>稳定风格规则</b>
          <span>${escapeHtml(`已完成 ${styleProgress.answered}/${styleProgress.total} 个情景，已加载 ${styleProgress.loaded}/${styleProgress.total} 个。选择和自填只作为证据，最终只提取说话习惯。`)}</span>
        </div>
      </header>
      <div class="persona-time-note">${escapeHtml(personaStandardizationTimeNotes.summary)}</div>
      ${styleStale ? `<div class="setup-guide-hint warn">问卷、基础稿或第二步偏好已经修改，当前情景/风格规则已过期。请先重新生成基础稿或情景试答。</div>` : ""}
      ${scenarioCount && !styleProgress.complete ? `<div class="setup-guide-hint warn">请先完成全部情景。每个情景需要选择一个候选，或在“自填更贴近的回复”里写一句更准的回复；后续情景会按三条一组加载。</div>` : ""}
      <div class="persona-standard-actions">
        <button type="button" data-persona-style-summary-generate ${styleStale || !styleProgress.complete ? "disabled" : ""}>生成风格规则</button>
      </div>
      ${styleSummaryResult?.parse_note ? `<div class="setup-guide-hint warn">${escapeHtml(styleSummaryResult.parse_note)}</div>` : ""}
      ${styleSummaryWarningRows ? `<div class="setup-guide-hint warn"><ul>${styleSummaryWarningRows}</ul></div>` : ""}
      <div class="persona-standard-review-grid">
        <section data-tone="info"><b>风格指纹</b>${fingerprintRows ? `<div class="persona-fingerprint-grid">${fingerprintRows}</div>` : ((styleSummaryResult?.draft?.style_rules || []).length ? `<ul>${styleSummaryResult.draft.style_rules.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>尚未归纳。选择候选或填写证据后点击生成。</p>`)}</section>
        <section data-tone="warn"><b>避免事项</b>${(styleSummaryResult?.draft?.avoid_rules || []).length ? `<ul>${styleSummaryResult.draft.avoid_rules.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>生成后会列出需要避免的句式和口吻。</p>`}</section>
        <section data-tone="check"><b>审核清单</b>${styleSummaryChecklistRows ? `<ul>${styleSummaryChecklistRows}</ul>` : `<p>确认规则没有改变角色设定，也没有固定候选原句。</p>`}</section>
      </div>
      ${renderPersonaFinalEditor(styleSummaryResult, styleStale)}
    </div>
  ` : "";
  const styleHtml = baseConfirmed ? `
      <section class="persona-style-workbench">
      <header>
        <div>
          <b><span class="step-badge">2</span>稳定对话风格校准</b>
          <span>${scenarioCount ? `已加载 ${scenarioCount}/${styleProgress.total} 个情景，已完成 ${styleProgress.answered}/${styleProgress.total}。当前只显示一个情景；完成两个后会预取下一组三个。` : "先确认上面的基础设定，再生成前三个情景候选。"}</span>
        </div>
      </header>
      <div class="persona-style-guide-strip">
        <span><b>1</b>看模拟上文</span>
        <span><b>2</b>选最像角色的一句</span>
        <span><b>3</b>不准就自填或重生成</span>
      </div>
      <div class="persona-time-note">${escapeHtml(personaStandardizationTimeNotes.scenarios)}</div>
      <section class="persona-style-hints">
        <header><b>第二步风格偏好</b><span>会使用已确认基础稿、本页偏好，以及最多 4000 字风格参考资料；只参考语气，不写入新事实。</span></header>
        <label class="persona-standard-question">
          <span><b>风格参考资料</b><small>默认可从第一步补充资料承接；这里修改只影响第二步情景候选和风格归纳，不会让基础设定稿过期。</small></span>
          <textarea rows="5" data-persona-style-reference maxlength="${escapeHtml(PERSONA_STYLE_REFERENCE_LIMIT)}" placeholder="可粘贴对话片段、像/不像的回复、常见口癖或禁用表达；最多 4000 字">${escapeHtml(personaStyleReferenceText(draft))}</textarea>
        </label>
        <div class="persona-standard-question-grid">${styleHintRows}</div>
      </section>
      <div class="persona-standard-actions">
        <button type="button" data-persona-style-generate ${baseStale ? "disabled" : ""}>${scenarioCount ? "重新开始生成情景" : "生成前三个情景"}</button>
      </div>
      ${baseStale ? `<div class="setup-guide-hint warn">基础问卷或来源已修改，当前基础稿已过期。请先重新生成基础设定稿。</div>` : ""}
      ${styleResult?.parse_note ? `<div class="setup-guide-hint warn">${escapeHtml(styleResult.parse_note)}</div>` : ""}
      ${styleWarningRows ? `<div class="setup-guide-hint warn"><ul>${styleWarningRows}</ul></div>` : ""}
      ${scenarioStepperHtml}
      ${scenarioPanelHtml}
      ${styleSummaryHtml}
    </section>
  ` : (result && !baseStale ? `
    <section class="persona-standard-empty">
      <b>确认基础信息后再校准说话方式</b>
      <span>先通读上面的基础设定稿。确认角色身份、关系、边界和长期设定无误后，再进入情景试答。</span>
    </section>
  ` : "");
  const resultHtml = result ? `
    <section class="persona-standard-result">
      <header>
        <div>
          <b><span class="step-badge">1</span>基础设定审核稿</b>
          <span>${escapeHtml(baseResultMeta)}</span>
        </div>
        <div class="persona-standard-score">
          <span class="${sc(score.completeness ?? 0)}">完整 <b>${escapeHtml(String(score.completeness ?? 0))}</b>/100</span>
          <span class="${sc(score.consistency ?? 0)}">一致 <b>${escapeHtml(String(score.consistency ?? 0))}</b>/100</span>
          <span class="${sc(score.roleplay_usability ?? 0)}">可用 <b>${escapeHtml(String(score.roleplay_usability ?? 0))}</b>/100</span>
        </div>
      </header>
      ${result.parse_note ? `<div class="setup-guide-hint warn">${escapeHtml(result.parse_note)}</div>` : ""}
      ${baseStale ? `<div class="setup-guide-hint warn">你修改了问卷、来源或整理强度。下面是旧审核稿，只能参考；继续前请重新生成。</div>` : ""}
      <label class="persona-standard-editor">
        <span><b>审核稿正文</b><small>已经按模板标题分段。你可以直接在这里改字，确认后再进入风格校准。</small></span>
        <textarea class="persona-standard-template" rows="24" data-persona-standard-template>${escapeHtml(baseTemplateText)}</textarea>
      </label>
      <div class="persona-standard-review-grid">
        <section data-tone="info"><b>改动摘要</b>${summaryRows ? `<ul>${summaryRows}</ul>` : `<p>暂无摘要。</p>`}</section>
        <section data-tone="warn"><b>需要审核</b>${warningRows ? `<ul>${warningRows}</ul>` : `<p>没有明显冲突，但仍建议通读。</p>`}</section>
        <section data-tone="check"><b>审核清单</b>${checklistRows ? `<ul>${checklistRows}</ul>` : `<p>确认角色身份、关系称呼、禁区和长期设定。</p>`}</section>
      </div>
      <div class="persona-standard-actions">
        <button type="button" data-persona-standard-copy ${baseStale ? "disabled" : ""}>复制基础稿</button>
        <button type="button" data-persona-standard-confirm ${baseStale ? "disabled" : ""}>确认基本信息，进入风格校准</button>
        <button type="button" class="ghost" data-persona-standard-clear>清空结果</button>
      </div>
      <div class="persona-time-note">${escapeHtml(personaStandardizationTimeNotes.confirm)}</div>
    </section>
  ` : `
    <section class="persona-standard-empty">
      <b>还没有生成基础设定稿</b>
      <span>在上方选择人格来源和整理强度后，点击「生成基础稿」。第一步只整理稳定设定，不生成口癖、句长等强语气内容。</span>
    </section>
  `;
  return `
    <article class="exp-detail-card persona-standard-card">
      <h3>问卷式人格标准化</h3>
      <p>先整理稳定设定，再用情景试答校准说话方式。全程只生成可编辑审核稿，不自动覆盖原人格。</p>
      <div class="persona-flow-steps">${flowSteps}</div>
      <section class="persona-config-section">
        <header>
          <b><span class="step-badge">1</span>基础设定配置</b>
          <span>选择人格来源、设定整理强度，可选补充参考材料。</span>
        </header>
        <div class="persona-standard-source">
          <label class="setup-guide-choice ${draft.use_pasted_source ? "" : "selected"}">
            <input type="radio" name="personaStandardSource" value="current" data-persona-standard-source ${draft.use_pasted_source ? "" : "checked"}>
            <span><b>选择 AstrBot 人格</b><small>从可读取的人格列表选择，不会切换实际对话人格。</small></span>
          </label>
          <label class="setup-guide-choice ${draft.use_pasted_source ? "selected" : ""}">
            <input type="radio" name="personaStandardSource" value="paste" data-persona-standard-source ${draft.use_pasted_source ? "checked" : ""}>
            <span><b>粘贴人格文本</b><small>当前人格读取不到，或想整理另一版人格时使用。</small></span>
          </label>
        </div>
        <label class="persona-standard-question ${draft.use_pasted_source ? "is-hidden" : ""}" data-persona-standard-persona-wrap>
          <span><b>人格选择</b><small>优先选择要整理的 AstrBot 人格；列表未加载时会沿用当前默认人格。</small></span>
          <select data-persona-standard-persona>
            ${(state.roleplayPersonas || []).length
              ? (state.roleplayPersonas || []).map((item) => {
                const id = String(item.id || "");
                const label = `${item.label || id}${item.source ? ` · ${item.source}` : ""}`;
                return `<option value="${escapeHtml(id)}" ${id === String(draft.persona_id || "") ? "selected" : ""}>${escapeHtml(label)}</option>`;
              }).join("")
              : `<option value="">继承 AstrBot 当前配置人格</option>`}
          </select>
        </label>
        <label class="persona-standard-question ${draft.use_pasted_source ? "" : "is-hidden"}" data-persona-standard-source-text-wrap>
          <span><b>原人格文本</b><small>只在选择粘贴人格文本时使用。</small></span>
          <textarea rows="8" data-persona-standard-source-text placeholder="把原 AstrBot 人格粘贴到这里">${escapeHtml(draft.source_text || "")}</textarea>
        </label>
        <div class="persona-standard-strength">
          ${[
            ["light", "轻度", "仅整理排版与明显冲突，改动最小"],
            ["medium", "中度", "补足缺失模块并优化表达，推荐使用"],
            ["deep", "深度", "主动重构为完整模板，性格层次更细腻"],
          ].map(([value, label, desc]) => `
            <label class="setup-guide-choice ${draft.strength === value ? "selected" : ""}">
              <input type="radio" name="personaStandardStrength" value="${escapeHtml(value)}" data-persona-standard-strength ${draft.strength === value ? "checked" : ""}>
              <span><b>${escapeHtml(label)}</b><small>${escapeHtml(desc)}</small></span>
            </label>
          `).join("")}
        </div>
        <section class="persona-reference-section">
          <header>
            <b>补充资料（可选）</b>
            <span>主要用于第一步整理基础设定，尤其是性格底色、内在驱动、亲疏变化、压力反应、矛盾感、关系、喜恶和边界。</span>
          </header>
          <label class="persona-standard-question">
            <span><b>参考材料</b><small>可以写"平时怎样、熟了怎样、被误解怎样、被要求怎样、真正害怕/在意什么"。第二步会读取前 4000 字作为风格参考。</small></span>
            <textarea rows="8" data-persona-standard-supplement placeholder="例如：
用户：你刚才这个说法好像太正式了
她：啊，那我换短一点。刚才那句不算。

补充说明：
性格底色：外表安静，熟了会有点嘴硬和捉弄人。
内在驱动：很在意被认真对待，但不喜欢把在意说得太满。
压力反应：被催或被误解时会先缩短回复，缓过来后再补一句。
关系变化：对陌生人礼貌收着，对熟人会更直接，也会保留一点边界。
矛盾感：想靠近但怕显得太主动；会照顾人，但不想被当成只会顺从。
如果资料与原人格冲突，请在审核提醒里标出来。">${escapeHtml(draft.supplement_text || "")}</textarea>
          </label>
        </section>
        <div class="persona-standard-actions">
          <button type="button" data-persona-standard-generate>${draft.use_pasted_source ? "用粘贴文本生成基础稿" : "用所选人格生成基础稿"}</button>
          <button type="button" class="ghost" data-persona-standard-fill-sample>填入示例</button>
        </div>
        <div class="persona-time-note">${escapeHtml(personaStandardizationTimeNotes.base)}</div>
      </section>
      ${resultHtml}
      ${styleHtml}
    </article>
  `;
}

export function collectPersonaStandardizationQuestionnaire() {
  const draft = personaStandardizationDraftState();
  document.querySelectorAll("[data-persona-standard-field]").forEach((input) => {
    draft[input.dataset.personaStandardField || ""] = input.value || "";
  });
  document.querySelectorAll("[data-persona-style-custom]").forEach((input) => {
    draft.style_custom = draft.style_custom || {};
    draft.style_custom[input.dataset.personaStyleCustom || ""] = input.value || "";
  });
  document.querySelectorAll("[data-persona-style-feedback]").forEach((input) => {
    draft.style_feedback = draft.style_feedback || {};
    draft.style_feedback[input.dataset.personaStyleFeedback || ""] = input.value || "";
  });
  const source = document.querySelector("[data-persona-standard-source]:checked")?.value || "current";
  draft.use_pasted_source = source === "paste";
  const personaSelect = document.querySelector("[data-persona-standard-persona]");
  const sourceTextInput = document.querySelector("[data-persona-standard-source-text]");
  const supplementInput = document.querySelector("[data-persona-standard-supplement]");
  const styleReferenceInput = document.querySelector("[data-persona-style-reference]");
  if (personaSelect) draft.persona_id = personaSelect.value || "";
  if (sourceTextInput) draft.source_text = sourceTextInput.value || "";
  if (supplementInput) draft.supplement_text = supplementInput.value || "";
  if (styleReferenceInput) draft.style_reference_text = styleReferenceInput.value || "";
  draft.strength = document.querySelector("[data-persona-standard-strength]:checked")?.value || draft.strength || "medium";
  return draft;
}

export async function generatePersonaStandardizationDraft(button) {
  const draft = collectPersonaStandardizationQuestionnaire();
  const questionnaire = {
    supplement_text: draft.supplement_text || "",
  };
  personaStandardizationStyleHints.forEach(([key]) => { questionnaire[key] = draft[key] || ""; });
  questionnaire.strength = draft.strength || "medium";
  const result = await runAction(
    () => postJson("/roleplay/standardize_persona", {
      questionnaire,
      persona_id: draft.use_pasted_source ? "" : (draft.persona_id || ""),
      source_text: draft.use_pasted_source ? draft.source_text : "",
    }),
    "已生成审核稿",
    button,
    { reload: false },
  );
  if (result) {
    state.personaStandardizationDraft = result;
    state.personaStandardizationStyleDraft = null;
    state.personaStandardizationStyleSummaryDraft = null;
    state.personaStandardizationFinalEditor = null;
    state.personaStandardizationVoiceDraft = null;
    state.personaStandardizationVoiceDraftStale = false;
    state.personaStandardizationBaseStale = false;
    state.personaStandardizationStyleStale = false;
    state.personaStandardizationStyleScenarioFocusId = "";
    state.personaStandardizationStyleBatchLoading = false;
    state.personaStandardizationStyleBatchRequestedOffset = null;
    draft.base_confirmed = false;
    draft.style_choices = {};
    draft.style_custom = {};
    draft.style_feedback = {};
    renderExperimentalPage();
  }
}

export async function generatePersonaStyleScenarios(button) {
  if (state.personaStandardizationBaseStale) {
    showToast("基础设定稿已过期，请先重新生成基础设定稿", "error");
    return;
  }
  if (!personaStandardizationDraftState().base_confirmed) {
    showToast("请先确认基础信息，再生成情景候选", "error");
    return;
  }
  const draft = collectPersonaStandardizationQuestionnaire();
  const questionnaire = personaStyleQuestionnaire(draft);

  const result = await runAction(
    () => postJson("/roleplay/persona_style_scenarios", {
      questionnaire,
      base_template: personaStandardizationCurrentTemplate(),
      batch_size: PERSONA_STYLE_SCENARIO_BATCH_SIZE,
      scenario_offset: 0,
      scenario_limit: PERSONA_STYLE_SCENARIO_BATCH_SIZE,
      timeout_seconds: 32,
    }),
    "已生成第一组情景候选",
    button,
    { reload: false },
  );
  if (result) {
    state.personaStandardizationStyleSummaryDraft = null;
    state.personaStandardizationFinalEditor = null;
    state.personaStandardizationVoiceDraft = null;
    state.personaStandardizationVoiceDraftStale = false;
    state.personaStandardizationStyleStale = false;
    const styleState = personaStandardizationDraftState();
    styleState.style_choices = {};
    styleState.style_custom = {};
    styleState.style_feedback = {};
    setPersonaStyleScenarioFocus("");
    applyPersonaStyleScenarioBatchResult(result, { append: false });
    renderExperimentalPage();
  }
}

export function personaStyleScenarioRequestPayload(offset = 0) {
  const draft = collectPersonaStandardizationQuestionnaire();
  const questionnaire = personaStyleQuestionnaire(draft);
  return {
    questionnaire,
    base_template: personaStandardizationCurrentTemplate(),
    batch_size: PERSONA_STYLE_SCENARIO_BATCH_SIZE,
    scenario_offset: Math.max(0, Number(offset || 0)),
    scenario_limit: PERSONA_STYLE_SCENARIO_BATCH_SIZE,
    timeout_seconds: 32,
  };
}

export function applyPersonaStyleScenarioBatchResult(result, { append = false } = {}) {
  const incomingScenarios = Array.isArray(result?.draft?.scenarios) ? result.draft.scenarios : [];
  const previous = append ? (state.personaStandardizationStyleDraft || {}) : {};
  const previousDraft = previous.draft || {};
  const previousScenarios = append && Array.isArray(previousDraft.scenarios) ? previousDraft.scenarios : [];
  const scenarioMap = new Map();
  [...previousScenarios, ...incomingScenarios].forEach((scenario) => {
    const scenarioId = personaStyleScenarioId(scenario);
    if (scenarioId) scenarioMap.set(scenarioId, scenario);
  });
  const mergedScenarios = Array.from(scenarioMap.values());
  const warnings = [
    ...(Array.isArray(previousDraft.warnings) && append ? previousDraft.warnings : []),
    ...(Array.isArray(result?.draft?.warnings) ? result.draft.warnings : []),
  ].filter(Boolean);
  const reviewChecklist = [
    ...(Array.isArray(previousDraft.review_checklist) && append ? previousDraft.review_checklist : []),
    ...(Array.isArray(result?.draft?.review_checklist) ? result.draft.review_checklist : []),
  ].filter(Boolean);
  const scenarioTotal = Number(result?.scenario_total || previous.scenario_total || mergedScenarios.length || 0);
  state.personaStandardizationStyleDraft = {
    ...(append ? previous : {}),
    ...result,
    scenario_total: scenarioTotal,
    next_offset: Number(result?.next_offset || mergedScenarios.length || 0),
    has_more: Boolean(result?.has_more),
    draft: {
      ...(append ? previousDraft : {}),
      ...(result?.draft || {}),
      scenarios: mergedScenarios,
      warnings: Array.from(new Set(warnings)).slice(0, 12),
      review_checklist: Array.from(new Set(reviewChecklist)).slice(0, 12),
    },
  };
  const focusId = personaStyleScenarioFocusId();
  if (!focusId || !mergedScenarios.some((scenario) => personaStyleScenarioId(scenario) === focusId)) {
    setPersonaStyleScenarioFocus(personaStyleNextUnansweredScenarioId() || personaStyleScenarioId(mergedScenarios[0]));
  }
}

export async function loadMorePersonaStyleScenarios({ silent = false, button = null } = {}) {
  if (state.personaStandardizationStyleBatchLoading) return null;
  if (state.personaStandardizationStyleStale || state.personaStandardizationBaseStale) {
    if (!silent) showToast("当前情景或基础稿已过期，请先重新生成", "error");
    return null;
  }
  const styleDraft = state.personaStandardizationStyleDraft || {};
  const scenarios = styleDraft?.draft?.scenarios || [];
  const progress = personaStyleScenarioProgress();
  const hasMore = Boolean(styleDraft.has_more) || scenarios.length < progress.total;
  if (!hasMore) return null;
  const offset = Number(styleDraft.next_offset || scenarios.length || 0);
  state.personaStandardizationStyleBatchLoading = true;
  state.personaStandardizationStyleBatchRequestedOffset = offset;
  try {
    const action = () => postJson("/roleplay/persona_style_scenarios", personaStyleScenarioRequestPayload(offset));
    const result = silent
      ? await action()
      : await runAction(action, "已加载下一组情景", button, { reload: false });
    if (result) {
      applyPersonaStyleScenarioBatchResult(result, { append: true });
      state.personaStandardizationStyleSummaryDraft = null;
      state.personaStandardizationFinalEditor = null;
      state.personaStandardizationVoiceDraft = null;
      state.personaStandardizationVoiceDraftStale = false;
      state.personaStandardizationStyleStale = false;
      if (!silent) renderExperimentalPage();
    }
    return result || null;
  } catch (error) {
    if (!silent) showToast(`加载下一组情景失败：${error.message}`, "error");
    return null;
  } finally {
    state.personaStandardizationStyleBatchLoading = false;
    state.personaStandardizationStyleBatchRequestedOffset = null;
    if (silent) renderExperimentalPage();
  }
}

export function maybePrefetchPersonaStyleScenarios() {
  if (!personaStyleShouldPrefetchNextBatch()) return;
  void loadMorePersonaStyleScenarios({ silent: true });
}

export async function retryPersonaStyleScenario(scenarioId, button) {
  if (state.personaStandardizationStyleStale || state.personaStandardizationBaseStale) {
    showToast("当前情景已过期，请先重新生成情景候选", "error");
    return;
  }
  if (!personaStandardizationDraftState().base_confirmed) {
    showToast("请先确认基础信息", "error");
    return;
  }
  const draft = collectPersonaStandardizationQuestionnaire();
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  const scenario = scenarios.find((item) => item.id === scenarioId);
  if (!scenario) {
    showToast("没有找到这个情景", "error");
    return;
  }
  const questionnaire = personaStyleQuestionnaire(draft);
  const result = await runAction(
    () => postJson("/roleplay/persona_style_scenario_retry", {
      questionnaire,
      scenario,
      feedback: draft.style_feedback?.[scenarioId] || "",
      base_template: personaStandardizationCurrentTemplate(),
    }),
    "已重生成此情景",
    button,
    { reload: false },
  );
  if (result?.scenario) {
    const nextScenarios = scenarios.map((item) => (item.id === scenarioId ? result.scenario : item));
    state.personaStandardizationStyleDraft = {
      ...state.personaStandardizationStyleDraft,
      parse_note: result.parse_note || state.personaStandardizationStyleDraft?.parse_note || "",
      draft: {
        ...(state.personaStandardizationStyleDraft?.draft || {}),
        scenarios: nextScenarios,
      },
    };
    state.personaStandardizationStyleSummaryDraft = null;
    state.personaStandardizationFinalEditor = null;
    state.personaStandardizationVoiceDraft = null;
    state.personaStandardizationVoiceDraftStale = false;
    state.personaStandardizationStyleStale = false;
    draft.style_choices = draft.style_choices || {};
    draft.style_custom = draft.style_custom || {};
    draft.style_choices[scenarioId] = "";
    draft.style_custom[scenarioId] = "";
    renderExperimentalPage();
  }
}

export async function generatePersonaStyleSummary(button) {
  if (state.personaStandardizationStyleStale || state.personaStandardizationBaseStale) {
    showToast("当前情景或基础稿已过期，请先重新生成", "error");
    return;
  }
  if (!personaStandardizationDraftState().base_confirmed) {
    showToast("请先确认基础信息", "error");
    return;
  }
  const draft = collectPersonaStandardizationQuestionnaire();
  const questionnaire = personaStyleQuestionnaire(draft);
  const evidence = collectPersonaStyleEvidence();
  const progress = personaStyleScenarioProgress();
  if (!progress.complete) {
    showToast(`请先完成全部情景，还差 ${progress.missing} 个`, "error");
    return;
  }
  if (!evidence.length) {
    showToast("请先生成情景候选并选择或自填", "error");
    return;
  }
  const result = await runAction(
    () => postJson("/roleplay/persona_style_summary", {
      questionnaire,
      evidence,
      base_template: personaStandardizationCurrentTemplate(),
    }),
    "已归纳风格规则",
    button,
    { reload: false },
  );
  if (result) {
    state.personaStandardizationStyleSummaryDraft = result;
    state.personaStandardizationFinalEditor = null;
    state.personaStandardizationVoiceDraft = null;
    state.personaStandardizationVoiceDraftStale = false;
    state.personaStandardizationStyleStale = false;
    renderExperimentalPage();
  }
}

export async function advancePersonaStyleScenario(scenarioId, button = null) {
  const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
  const scenario = scenarios.find((item) => personaStyleScenarioId(item) === String(scenarioId || ""));
  if (!scenario) {
    showToast("没有找到当前情景", "error");
    return;
  }
  if (!personaStyleScenarioAnswered(scenario)) {
    showToast("请先选择一个候选，或自填一句更贴近的回复", "error");
    return;
  }
  maybePrefetchPersonaStyleScenarios();
  const nextLoadedId = personaStyleNextUnansweredScenarioId(scenarioId);
  if (nextLoadedId) {
    setPersonaStyleScenarioFocus(nextLoadedId);
    renderExperimentalPage();
    return;
  }
  const progress = personaStyleScenarioProgress();
  if (progress.complete) {
    setPersonaStyleScenarioFocus("");
    renderExperimentalPage();
    showToast("全部情景已完成，可以生成风格规则");
    return;
  }
  if (state.personaStandardizationStyleBatchLoading) {
    showToast("下一组三个情景正在生成，稍等它回来");
    return;
  }
  const result = await loadMorePersonaStyleScenarios({ silent: false, button });
  if (result) {
    const nextAfterLoad = personaStyleNextUnansweredScenarioId(scenarioId) || personaStyleNextUnansweredScenarioId();
    if (nextAfterLoad) setPersonaStyleScenarioFocus(nextAfterLoad);
    renderExperimentalPage();
  }
}

export async function savePersonaVoiceChannelDrafts(button, root = document) {
  if (state.personaStandardizationVoiceDraftStale) {
    showToast("最终人格已修改，请先重新生成分通道草稿", "error");
    return;
  }
  const payload = personaVoiceSettingsPayload(root);
  const result = await runAction(
    () => postJson("/settings/update", payload),
    "已保存分通道人格风格",
    button,
    { reload: false },
  );
  if (result) {
    state.overview = state.overview || {};
    state.overview.settings = {
      ...(state.overview.settings || {}),
      ...(payload.settings || {}),
    };
    scheduleExperimentalRuntimeRefresh(true);
  }
}

export function fillPersonaStandardizationSample() {
  const draft = personaStandardizationDraftState();
  Object.assign(draft, {
    supplement_text: "聊天记录示例：\n用户：你刚才这个说法好像太正式了\n她：啊，那我换短一点。刚才那句不算。\n用户：你在干嘛？\n她：刚下课，脑子还没转过来。\n\n性格补充：\n底色：外表安静，熟了会有点嘴硬和捉弄人。\n内在驱动：很在意被认真对待，但不喜欢把在意说得太满。\n亲疏变化：对陌生人礼貌收着，对熟人会更直接，也会保留一点边界。\n压力反应：被催或被误解时会先缩短回复，缓过来后再补一句。\n矛盾感：想靠近但怕显得太主动；会照顾人，但不想被当成只会顺从。\n\n补充说明：\n保留原人格里的称呼和关系；不要写成客服腔；如果资料和原人格冲突，以原人格为准并提醒我审核。",
    speech: "短句为主，自然口语，少解释。避免“希望换个话题还是继续聊”“我可以帮你”等人机式句子。",
    output: "社交软件文字回复短一点、像真人打字；不用动作描写和旁白，不自称智能助手，不输出工具或系统说明。",
    examples: "示例：啥 / 没懂 / 我在哦 / 笑死。反例：（揉眼睛）早上好、我是您的智能助手、要不要继续这个话题。",
  });
  invalidatePersonaStandardizationDraft();
  renderExperimentalPage();
}

export function confirmPersonaStandardizationBase() {
  const draft = collectPersonaStandardizationQuestionnaire();
  if (!state.personaStandardizationDraft || state.personaStandardizationBaseStale) {
    showToast("请先生成并审核基础设定稿", "error");
    return;
  }
  const template = personaStandardizationCurrentTemplate();
  if (!String(template || "").trim()) {
    showToast("基础设定稿为空，无法进入风格校准", "error");
    return;
  }
  if (state.personaStandardizationDraft?.draft) {
    state.personaStandardizationDraft.draft.template = template;
  }
  draft.base_confirmed = true;
  state.personaStandardizationStyleStale = false;
  renderExperimentalPage();
  showToast("已确认基础信息，可以开始校准对话风格");
}

export function renderExperimentalTheoryVisual(key) {
  if (key === "enable_emotion_simulation") return renderEmotionTheoryVisual();
  if (key === "enable_maslow_motivation_experiment") return renderMaslowTheoryVisual();
  if (key === "enable_experimental_motivation_model") return renderMotivationTheoryVisual();
  if (key === "enable_personality_iteration_experiment") return renderPersonalityTheoryVisual();
  return "";
}

export function renderExperimentalSettings(key) {
  const sections = featureSettingSections[key] || [];
  const related = featureRelatedSettings(key);
  if (!related.length && !sections.length) {
    return `
      <article class="exp-detail-card exp-settings-card">
        <h3>参数配置</h3>
        <div class="exp-settings-empty">该功能没有额外参数，通过开关即可控制。</div>
      </article>
    `;
  }
  const settings = state.overview?.settings || {};
  const features = state.featureDraft || {};
  const providers = state.providerDraft || {};
  const relatedMap = Object.fromEntries(related.map((item) => [item.key, item]));
  const settingRow = ({ key: name, value, description }) => `
    <section class="feature-param-row">
      <div class="feature-param-main">
        <header>
          <b>${escapeHtml(configLabel(name))}</b>
          <code>${escapeHtml(name)}</code>
        </header>
        <p>${escapeHtml(description)}</p>
      </div>
      <div class="feature-param-control">
        ${featureSettingInput(name, value)}
      </div>
    </section>
  `;
  const renderedKeys = new Set();
  const groupedHtml = sections.map((section) => {
    const items = (section.keys || []).map((name) => {
      if (!featureSettingVisibleForCurrentMode(key, name, settings)) return null;
      renderedKeys.add(name);
      return relatedMap[name];
    }).filter(Boolean);
    if (!items.length) return "";
    return `
      <section class="feature-param-section">
        <header>
          <b>${escapeHtml(section.title || "参数")}</b>
          ${section.note ? `<span>${escapeHtml(section.note)}</span>` : ""}
        </header>
        ${items.map(settingRow).join("")}
      </section>
    `;
  }).join("");
  const ungroupedItems = related.filter((item) => {
    if (renderedKeys.has(item.key)) return false;
    return featureSettingVisibleForCurrentMode(key, item.key, settings);
  });
  const ungroupedHtml = ungroupedItems.map(settingRow).join("");
  return `
    <article id="experimentalSettings" class="exp-detail-card exp-settings-card">
      <h3>参数配置</h3>
      <form class="feature-param-list" data-exp-param-form="${escapeHtml(key)}">
        ${groupedHtml}
        ${ungroupedHtml}
        ${related.length ? `<button type="submit" class="feature-param-save">保存参数</button>` : ""}
      </form>
    </article>
  `;
}

export function renderExperimentalRuntime(key) {
  const overview = state.overview || {};
  const settings = overview.settings || {};
  const features = state.featureDraft || {};
  const enabled = toBool(features[key]);
  const meta = experimentalFeatureMeta[key] || {};
let statusItems = [];
let extraHtml = "";
if (key === "enable_emotion_simulation") {
    const llmJudge = toBool(features.enable_llm_emotion_judgement) || toBool(settings.enable_llm_emotion_judgement);
    const judgeMode = String(features.emotion_judgement_mode || settings.emotion_judgement_mode || "suspicious");
    const modeLabels = { suspicious: "只判断可疑消息", always: "每条普通文本都判断", off: "关闭模型复核" };
    const hurtThreshold = features.emotional_gate_hurt_threshold ?? settings.emotional_gate_hurt_threshold ?? 70;
    const refuseThreshold = features.emotional_gate_refuse_threshold ?? settings.emotional_gate_refuse_threshold ?? 90;
    const recovery = features.emotional_gate_recovery_per_hour ?? settings.emotional_gate_recovery_per_hour ?? 24;
    const ventEnabled = toBool(features.enable_qzone_emotional_vent_publish) || toBool(settings.enable_qzone_emotional_vent_publish);
    statusItems = [
      ["模型复核", llmJudge ? modeLabels[judgeMode] || judgeMode : "未启用"],
      ["受伤阈值", String(hurtThreshold)],
      ["生气阈值", String(refuseThreshold)],
      ["每小时缓和量", String(recovery)],
      ["QQ空间心情动态", ventEnabled ? "已启用" : "未启用"],
    ];
    const users = state.users || [];
    const userCount = users.length;
    const asRuntimeObject = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
    const emotionModeLabels = { normal: "平稳", hurt: "收敛中", refusing: "高压回避", attached: "贴近", warming: "缓和", backoff: "后退" };
    const emotionInfos = users.map((u) => {
      const rel = asRuntimeObject(u.relationship_state);
      const dims = asRuntimeObject(rel.emotion_dimensions);
      const plutchik = asRuntimeObject(rel.plutchik_profile);
      const regulation = asRuntimeObject(rel.emotion_regulation);
      const pending = asRuntimeObject(u.pending_emotion_judgement || rel.pending_emotion_judgement);
      const error = String(u.last_emotion_judgement_error || rel.last_emotion_judgement_error || "").trim();
      const mode = String(rel.mode || "normal");
      const moodScore = Number(rel.mood_score || 0);
      const dimStrength = ["pleasantness", "tension", "arousal", "certainty"]
        .map((k) => Math.abs(Number(dims[k] || 0)))
        .reduce((sum, value) => sum + value, 0);
      const activeItems = Array.isArray(plutchik.active)
        ? plutchik.active.filter((e) => Number(e?.value || 0) > 0).slice(0, 3)
        : [];
      const activeStrength = activeItems.reduce((max, item) => Math.max(max, Number(item.value || 0)), 0);
      const lastEvent = String(rel.last_emotion_event || "");
      const hasPending = Boolean(pending.text || pending.created_at);
      const hasError = Boolean(error);
      const hasRegulation = Boolean((regulation.strategy && regulation.strategy !== "none") || Number(regulation.intensity || 0) > 0);
      const hasSample = Object.keys(rel).length > 0 || hasPending || hasError;
      const visible = hasSample && (
        (mode && mode !== "normal") ||
        moodScore !== 0 ||
        dimStrength > 0 ||
        activeStrength > 0 ||
        hasRegulation ||
        (lastEvent && lastEvent !== "neutral") ||
        hasPending ||
        hasError
      );
      const sortScore = Math.max(
        Math.abs(moodScore),
        dimStrength,
        activeStrength,
        hasPending ? 120 : 0,
        hasError ? 90 : 0,
        mode !== "normal" ? 80 : 0,
        lastEvent && lastEvent !== "neutral" ? 60 : 0
      );
      return {
        nick: u.nickname || u.display_name || u.user_id || "-",
        mode,
        modeLabel: emotionModeLabels[mode] || mode || "平稳",
        dominant: plutchik.dominant_label || "",
        blend: plutchik.blend_label || "",
        moodScore,
        regulation: regulation.strategy_label || regulation.strategy || "",
        regulationIntensity: regulation.intensity || 0,
        dims,
        activeEmotions: activeItems.map((e) => `${e.label || e.key || "情绪"} ${Number(e.value || 0)}`).join("｜"),
        lastEvent,
        lastReason: rel.last_emotion_reason || rel.last_hurt_reason || "",
        pendingText: pending.text || "",
        pendingAge: pending.created_at_text || "",
        error,
        hasSample,
        visible,
        sortScore,
      };
    }).filter((item) => item.hasSample);
    const emotionalInfos = emotionInfos.filter((item) => item.visible);
    const emotionalCount = emotionalInfos.length;
    const pendingCount = emotionInfos.filter((item) => item.pendingText).length;
    const errorCount = emotionInfos.filter((item) => item.error).length;
    const calmCount = Math.max(0, emotionInfos.length - emotionalCount);
    const modeBuckets = { hurt: 0, refusing: 0, attached: 0, warming: 0, backoff: 0 };
    emotionalInfos.forEach((item) => {
      if (Object.prototype.hasOwnProperty.call(modeBuckets, item.mode)) modeBuckets[item.mode]++;
    });
    const topEmotional = (emotionalInfos.length ? emotionalInfos : emotionInfos)
      .sort((a, b) => b.sortScore - a.sortScore)
      .slice(0, 4);
    const userRows = topEmotional.map((u) => {
      const dimText = ["pleasantness", "tension", "arousal", "certainty"].map((k) => {
        const v = u.dims[k];
        if (v == null) return "";
        const labels = { pleasantness: "愉快", tension: "紧张", arousal: "激动", certainty: "确信" };
        return `<span>${labels[k]}：${v}</span>`;
      }).filter(Boolean).join("");
      return `
      <div class="exp-runtime-user-row">
        <div class="exp-runtime-user-head">
          <b>${escapeHtml(u.nick)}</b>
          <span class="exp-runtime-user-mode ${escapeHtml(u.mode)}">${escapeHtml(u.pendingText ? "等待复核" : (u.error ? "复核失败" : u.modeLabel))}</span>
        </div>
        <div class="exp-runtime-user-detail">
          ${dimText ? `<span class="exp-runtime-dims">${dimText}</span>` : ""}
          ${u.dominant ? `<span>主导：${escapeHtml(u.dominant)}</span>` : ""}
          ${u.blend ? `<span>复合：${escapeHtml(u.blend)}</span>` : ""}
          ${u.activeEmotions ? `<span>活跃：${escapeHtml(u.activeEmotions)}</span>` : ""}
          <span>余波值：${escapeHtml(String(u.moodScore))}</span>
          ${u.lastEvent && u.lastEvent !== "neutral" ? `<span>事件：${escapeHtml(u.lastEvent)}</span>` : ""}
          ${u.regulation ? `<span>调节：${escapeHtml(u.regulation)}（${u.regulationIntensity}）</span>` : ""}
          ${u.pendingText ? `<span>\u590d\u6838\u4e2d\uff1a${escapeHtml(u.pendingText)}${u.pendingAge ? `\uff5c${escapeHtml(u.pendingAge)}` : ""}</span>` : ""}
          ${u.error ? `<span>复核失败：${escapeHtml(u.error)}</span>` : ""}
          ${u.lastReason ? `<span>原因：${escapeHtml(String(u.lastReason).slice(0, 80))}</span>` : ""}
        </div>
      </div>
    `;}).join("");
    const runtimeHint = emotionInfos.length
      ? (emotionalInfos.length
        ? `${meta.runtimeHint || ""}${pendingCount ? ` 当前还有 ${pendingCount} 条情绪复核等待模型返回。` : ""}`
        : "当前已有情绪余波样本，但整体处于平稳或已回归状态；只有命中伤害、安抚、夸奖、道歉等事件，或模型复核返回有效变化后，数值才会明显波动。")
      : "暂无情绪余波样本。私聊发生伤害、安抚、夸奖、道歉等事件后会出现；如果开启模型复核，结果可能要等异步复核完成后才显示。";
    extraHtml = `
      <div class="exp-runtime-extra">
        <div class="exp-runtime-stats-row">
          <div class="exp-runtime-stat"><span>私聊用户</span><b>${escapeHtml(String(userCount))}</b></div>
          <div class="exp-runtime-stat"><span>已有样本</span><b>${escapeHtml(String(emotionInfos.length))}</b></div>
          <div class="exp-runtime-stat"><span>情绪波动</span><b>${escapeHtml(String(emotionalCount))}</b></div>
          <div class="exp-runtime-stat"><span>平稳样本</span><b>${escapeHtml(String(calmCount))}</b></div>
          <div class="exp-runtime-stat"><span>等待复核</span><b>${escapeHtml(String(pendingCount))}</b></div>
          <div class="exp-runtime-stat"><span>复核失败</span><b>${escapeHtml(String(errorCount))}</b></div>
        </div>
        ${modeBuckets.hurt || modeBuckets.refusing || modeBuckets.attached || modeBuckets.warming || modeBuckets.backoff ? `
          <div class="exp-runtime-stats-row">
            <div class="exp-runtime-stat"><span>收敛中</span><b>${escapeHtml(String(modeBuckets.hurt || 0))}</b></div>
            <div class="exp-runtime-stat"><span>高压回避</span><b>${escapeHtml(String(modeBuckets.refusing || 0))}</b></div>
            <div class="exp-runtime-stat"><span>缓和/贴近</span><b>${escapeHtml(String((modeBuckets.warming || 0) + (modeBuckets.attached || 0)))}</b></div>
            <div class="exp-runtime-stat"><span>后退</span><b>${escapeHtml(String(modeBuckets.backoff || 0))}</b></div>
          </div>
        ` : ""}
        ${userRows ? `<div class="exp-runtime-user-list"><div class="exp-runtime-user-list-title">${escapeHtml(emotionalInfos.length ? "情绪波动最大的用户" : "最近情绪样本")}</div>${userRows}</div>` : ""}
        <div class="exp-runtime-hint">${escapeHtml(runtimeHint)}</div>
      </div>
    `;
  } else if (key === "enable_maslow_motivation_experiment") {
    const strength = features.maslow_motivation_strength ?? settings.maslow_motivation_strength ?? 35;
    const scheduleInfluence = toBool(features.enable_maslow_schedule_influence) || toBool(settings.enable_maslow_schedule_influence);
    statusItems = [
      ["影响强度", `${strength} / 100`],
      ["日程影响", scheduleInfluence ? "已开启" : "未开启"],
      ["影响范围", scheduleInfluence ? "主动候选 + 日程倾向" : "仅主动候选"],
    ];
    const proactiveData = overview.proactive_candidates || {};
    const allCandidates = proactiveData.items || [];
    const pending = allCandidates.filter(proactiveCandidateIsPending);
    const needBuckets = { 状态: 0, 安全: 0, 归属: 0, 尊重: 0, 成长: 0, 意义: 0, 未分类: 0 };
    pending.forEach((c) => {
      const level = needLayerLabel(c.need_layer || c.need_level || c.maslow_level);
      const bucketKey = Object.prototype.hasOwnProperty.call(needBuckets, level) ? level : "未分类";
      needBuckets[bucketKey]++;
    });
    const maxBucket = Math.max(1, ...Object.values(needBuckets));
    const needBars = Object.entries(needBuckets).filter(([, v]) => v > 0).map(([k, v]) =>
      `<div class="exp-runtime-need-bar"><span>${escapeHtml(k)}</span><div class="exp-runtime-need-bar-track"><div class="exp-runtime-need-bar-fill" style="width:${Math.min(100, (v / maxBucket) * 100)}%"></div></div><b>${escapeHtml(String(v))}</b></div>`
    ).join("");
    const needCandidateRows = pending.filter((c) => c.need_layer || c.need_level).slice(0, 4).map((c) => `
      <div class="exp-runtime-user-row">
        <div class="exp-runtime-user-head">
          <b>${escapeHtml(c.topic || c.reason_label || c.reason || "未命名候选")}</b>
          <span class="exp-runtime-user-mode">${escapeHtml(needLayerLabel(c.need_layer || c.need_level))}</span>
        </div>
        <div class="exp-runtime-user-detail">
          ${c.need_drive ? `<span>驱动：${escapeHtml(c.need_drive)}</span>` : ""}
          ${c.need_note ? `<span>备注：${escapeHtml(c.need_note)}</span>` : ""}
          ${c.need_score_bias != null ? `<span>评分偏移：${escapeHtml(String(c.need_score_bias))}</span>` : ""}
        </div>
      </div>
    `).join("");
    extraHtml = `
      <div class="exp-runtime-extra">
        <div class="exp-runtime-stats-row">
          <div class="exp-runtime-stat"><span>待发送候选</span><b>${escapeHtml(String(pending.length))}</b></div>
          <div class="exp-runtime-stat"><span>已进入计划</span><b>${escapeHtml(String(proactiveData.counts?.accepted || 0))}</b></div>
        </div>
        ${needBars ? `<div class="exp-runtime-need-chart"><div class="exp-runtime-need-chart-title">候选需求层级分布</div>${needBars}</div>` : `<div class="exp-runtime-hint">暂无带需求层级的主动候选。开启后需要等待下一次主动候选生成/刷新，或到排障页运行一次主动消息测试，才会出现可观察记录。</div>`}
        ${needCandidateRows ? `<div class="exp-runtime-user-list"><div class="exp-runtime-user-list-title">候选需求分析</div>${needCandidateRows}</div>` : ""}
        <div class="exp-runtime-hint">${escapeHtml(meta.runtimeHint || "")}</div>
      </div>
    `;
  } else if (key === "enable_experimental_motivation_model") {
    const proactiveData = overview.proactive_candidates || {};
    const allCandidates = proactiveData.items || [];
    const pending = allCandidates.filter(proactiveCandidateIsPending);
    const taskData = overview.proactive_tasks || {};
    const userStates = Array.isArray(taskData.user_states) ? taskData.user_states : [];
    const motivationStates = userStates
      .map((item) => ({ item, motivation: item?.inner_readiness?.motivation || {} }))
      .filter((entry) => entry.motivation && Object.keys(entry.motivation).length);
    const proactiveTest = state.troubleshooting?.chain_tests?.proactive_message || {};
    const proactiveSteps = Array.isArray(proactiveTest.steps) ? proactiveTest.steps : [];
    const motivationStep = proactiveSteps.find((step) =>
      String(step.id || step.key || step.source || "").includes("experimental_motivation") ||
      String(step.name || step.title || "").includes("实验动机")
    );
    const diagnostics = state.diagnostics || [];
    const motivationDiag = motivationStep || diagnostics.find((d) =>
      String(d.id || d.source || "").includes("experimental_motivation") ||
      String(d.title || "").includes("实验动机")
    );
    const motivationState = motivationStates[0] || null;
    let driveScore = "-", incentiveScore = "-", arousalLevel = "-", arousalFit = "-", motivationLabel = "-", motivationScore = "-";
    const motivationDetail = String(motivationDiag?.detail || motivationDiag?.text || "");
    if (motivationDetail) {
      const detail = motivationDetail;
      const scoreMatch = detail.match(/([\d.]+)｜/);
      if (scoreMatch) motivationScore = scoreMatch[1];
      const driveMatch = detail.match(/驱力([\d.]+)/);
      if (driveMatch) driveScore = driveMatch[1];
      const incentiveMatch = detail.match(/诱因([\d.]+)/);
      if (incentiveMatch) incentiveScore = incentiveMatch[1];
      const arousalMatch = detail.match(/唤醒([\d.]+)\/适配([\d.]+)/);
      if (arousalMatch) { arousalLevel = arousalMatch[1]; arousalFit = arousalMatch[2]; }
      const labelMatch = detail.match(/｜([^｜]+)｜/);
      if (labelMatch) motivationLabel = labelMatch[1];
    }
    if (motivationState && motivationScore === "-") {
      const motivation = motivationState.motivation || {};
      const drive = motivation.drive || {};
      const incentive = motivation.incentive || {};
      const arousal = motivation.arousal || {};
      motivationScore = proactiveScore01(motivation.score) || "-";
      motivationLabel = motivation.label || "-";
      driveScore = proactiveScore01(drive.score) || "-";
      incentiveScore = proactiveScore01(incentive.score) || "-";
      arousalLevel = proactiveScore01(arousal.level) || "-";
      arousalFit = proactiveScore01(arousal.score) || "-";
    }
    statusItems = [
      ["综合动机分", motivationScore],
      ["判断结果", motivationLabel],
      ["驱力", driveScore],
      ["诱因", incentiveScore],
      ["唤醒水平", arousalLevel],
      ["唤醒适配", arousalFit],
      ["候选数", String(pending.length)],
      ["数据来源", motivationStep ? "主动消息链路测试" : (motivationState ? "主动运行态" : (motivationDiag ? "诊断项" : "暂无记录"))],
    ];
    const motivationStateRows = motivationStates.slice(0, 4).map(({ item, motivation }) => {
      const incentive = motivation.incentive || {};
      const arousal = motivation.arousal || {};
      return `
      <div class="exp-runtime-user-row">
        <div class="exp-runtime-user-head">
          <b>${escapeHtml(item.user_label || item.user_id || "未命名用户")}</b>
          <span class="exp-runtime-user-mode">${escapeHtml(motivation.label || "-")}</span>
        </div>
        <div class="exp-runtime-user-detail">
          <span>综合：${escapeHtml(proactiveScore01(motivation.score) || "-")}</span>
          ${motivation.detail ? `<span>${escapeHtml(motivation.detail)}</span>` : ""}
          ${incentive.label || incentive.detail ? `<span>诱因：${escapeHtml([incentive.label, incentive.detail].filter(Boolean).join(" · "))}</span>` : ""}
          ${arousal.label || arousal.detail ? `<span>唤醒：${escapeHtml([arousal.label, arousal.detail].filter(Boolean).join(" · "))}</span>` : ""}
        </div>
      </div>
    `;}).join("");
    const topCandidates = pending.slice(0, 4).map((c) => `
      <div class="exp-runtime-user-row">
        <div class="exp-runtime-user-head">
          <b>${escapeHtml(c.topic || c.reason_label || c.reason || "未命名候选")}</b>
          <span class="exp-runtime-user-mode">${escapeHtml(c.user_label || c.user_id || "-")}</span>
        </div>
        <div class="exp-runtime-user-detail">
          ${c.semantic_score != null ? `<span>语义贴合：${escapeHtml(proactivePercent100(c.semantic_score) || "-")}</span>` : ""}
          ${c.semantic_pressure != null ? `<span>压力：${escapeHtml(proactivePercent100(c.semantic_pressure) || "-")}</span>` : ""}
          ${c.need_layer ? `<span>需求层：${escapeHtml(needLayerLabel(c.need_layer))}</span>` : ""}
        </div>
      </div>
    `).join("");
    extraHtml = `
      <div class="exp-runtime-extra">
        <div class="exp-runtime-stats-row">
          <div class="exp-runtime-stat"><span>驱力</span><b>${escapeHtml(driveScore)}</b></div>
          <div class="exp-runtime-stat"><span>诱因</span><b>${escapeHtml(incentiveScore)}</b></div>
          <div class="exp-runtime-stat"><span>唤醒适配</span><b>${escapeHtml(arousalFit)}</b></div>
          <div class="exp-runtime-stat"><span>综合分</span><b>${escapeHtml(motivationScore)}</b></div>
        </div>
        <div class="exp-runtime-hint">${motivationDetail ? escapeHtml(motivationDetail.slice(0, 200)) : (motivationState ? "已从主动运行态读取动机调度结果；如果想看完整分步链路，可以到排障页点击“测试主动消息”。" : "暂无“实验动机调度”阶段记录。开启后需要主动链路跑到 Bot 开口欲阶段才会出现；可以等待下一次主动触发，或到排障页点击“测试主动消息”。")}</div>
        ${motivationStateRows ? `<div class="exp-runtime-user-list"><div class="exp-runtime-user-list-title">主动运行态动机</div>${motivationStateRows}</div>` : ""}
        ${topCandidates ? `<div class="exp-runtime-user-list"><div class="exp-runtime-user-list-title">近期候选</div>${topCandidates}</div>` : ""}
      </div>
    `;
  } else if (key === "enable_personality_iteration_experiment") {
    const diagnostics = state.diagnostics || [];
    const autoTuneEnabled = toBool(features.enable_personality_iteration_auto_tune) || toBool(settings.enable_personality_iteration_auto_tune);
    const personalityItems = diagnostics.filter((d) =>
      String(d.title || d.source || "").includes("人格") ||
      String(d.title || d.source || "").includes("贴合") ||
      String(d.title || d.source || "").includes("外向") ||
      String(d.title || d.source || "").includes("焦虑") ||
      String(d.title || d.source || "").includes("依恋") ||
      String(d.detail || "").includes("艾森克") ||
      String(d.detail || "").includes("大五") ||
      String(d.detail || "").includes("依恋") ||
      String(d.detail || "").includes("SDT") ||
      String(d.detail || "").includes("自主感")
    );
    statusItems = [
      ["检查维度", "艾森克PEN / 大五 / 依恋 / SDT"],
      ["显示位置", "排障/诊断页"],
      ["自主调节", autoTuneEnabled ? "已开启：临时覆盖少量主动策略参数" : "未开启：只给建议"],
      ["当前建议数", String(personalityItems.length)],
    ];
    const diagRows = personalityItems.slice(0, 4).map((d) => `
      <div class="exp-runtime-user-row">
        <div class="exp-runtime-user-head">
          <b>${escapeHtml(d.title || d.source || "-")}</b>
          <span class="exp-runtime-user-mode ${escapeHtml(d.level || "info")}">${escapeHtml(d.level || "info")}</span>
        </div>
        ${d.text || d.detail ? `<div class="exp-runtime-user-detail"><span>${escapeHtml((d.text || d.detail || "").slice(0, 120))}${(d.text || d.detail || "").length > 120 ? "…" : ""}</span></div>` : ""}
      </div>
    `).join("");
    extraHtml = `
      <div class="exp-runtime-extra">
        ${diagRows ? `<div class="exp-runtime-user-list"><div class="exp-runtime-user-list-title">角色贴合诊断建议</div>${diagRows}</div>` : `<div class="exp-runtime-hint">暂无诊断建议。开启功能并产生运行数据后，排障页会显示角色贴合建议。</div>`}
        <div class="exp-runtime-hint">${escapeHtml(meta.runtimeHint || "")}</div>
      </div>
    `;
  }
  const statusRows = statusItems.map(([name, value]) =>
    `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(value)}</dd></div>`
  ).join("");
  return `
    <article id="experimentalRuntime" class="exp-detail-card exp-runtime-card">
      <h3>运行状态</h3>
      ${enabled ? `<dl class="exp-runtime-dl">${statusRows}</dl>${extraHtml}` : `<div class="exp-runtime-disabled">功能未开启，暂无运行态数据。${escapeHtml(meta.runtimeHint || "")}</div>`}
    </article>
  `;
}

export function bindExperimentalOverviewActions() {
  const root = $("#experimentalRoot");
  if (!root) return;
  root.querySelectorAll("[data-exp-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.experimentalSubpage = button.dataset.expOpen || "";
      renderExperimentalPage();
    });
  });
  root.querySelectorAll("[data-exp-tool-open]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.experimentalSubpage = button.dataset.expToolOpen || "";
      renderExperimentalPage();
    });
  });
  root.querySelectorAll("[data-exp-toggle]").forEach((input) => {
    input.addEventListener("change", async () => {
      const key = input.dataset.expToggle || "";
      if (!key) return;
      state.featureDraft = state.featureDraft || {};
      state.featureDraft[key] = input.checked;
      const isSetting = Object.prototype.hasOwnProperty.call(state.overview?.settings || {}, key);
      const payload = isSetting
        ? { settings: { [key]: input.checked } }
        : { features: { [key]: input.checked } };
      const result = await runAction(
        () => postJson("/settings/update", payload),
        input.checked ? "已开启" : "已关闭",
        input.closest(".exp-card-toggle") || input.closest(".feature-detail-toggle"),
        { reload: false },
      );
      if (result) {
        reflectExperimentalToggleChange(key, input.checked);
        scheduleExperimentalRuntimeRefresh(false);
      }
    });
  });
}

export function bindExperimentalSubpageActions(key) {
  const root = $("#experimentalRoot");
  if (!root) return;
  root.querySelectorAll("[data-exp-back]").forEach((button) => {
    button.addEventListener("click", () => {
      state.experimentalSubpage = "";
      renderExperimentalPage();
      $("#experimentalRoot")?.scrollIntoView({ block: "start" });
    });
  });
  root.querySelectorAll("[data-exp-toggle]").forEach((input) => {
    input.addEventListener("change", async () => {
      const toggleKey = input.dataset.expToggle || "";
      if (!toggleKey) return;
      state.featureDraft = state.featureDraft || {};
      state.featureDraft[toggleKey] = input.checked;
      const isSetting = Object.prototype.hasOwnProperty.call(state.overview?.settings || {}, toggleKey);
      const payload = isSetting
        ? { settings: { [toggleKey]: input.checked } }
        : { features: { [toggleKey]: input.checked } };
      const result = await runAction(
        () => postJson("/settings/update", payload),
        input.checked ? "已开启" : "已关闭",
        input.closest(".feature-detail-toggle") || input.closest(".exp-card-toggle"),
        { reload: false },
      );
      if (result) {
        reflectExperimentalToggleChange(toggleKey, input.checked);
        scheduleExperimentalRuntimeRefresh(false);
      }
    });
  });
  root.querySelectorAll("[data-exp-param-form]").forEach((form) => {
    form.querySelectorAll("[data-feature-param]").forEach((input) => {
      if (input.type === "checkbox") {
        input.addEventListener("change", () => {
          const paramKey = input.dataset.featureParam || "";
          if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, paramKey)) {
            state.featureDraft[paramKey] = input.checked;
          }
          if (Object.prototype.hasOwnProperty.call(state.overview?.settings || {}, paramKey)) {
            state.overview.settings[paramKey] = input.checked;
          }
          const label = input.closest(".feature-param-check")?.querySelector("span");
          if (label) label.textContent = input.checked ? "开启" : "关闭";
          if (key === "enable_emotion_simulation" && paramKey === "enable_llm_emotion_judgement") {
            renderExperimentalPage();
          }
          if (key === "enable_maslow_motivation_experiment" && paramKey === "enable_maslow_motivation_experiment") {
            renderExperimentalPage();
          }
        });
      }
      if (input.tagName === "SELECT") {
        input.addEventListener("change", () => {
          const paramKey = input.dataset.featureParam || "";
          if (Object.prototype.hasOwnProperty.call(state.overview?.settings || {}, paramKey)) {
            state.overview.settings[paramKey] = input.value;
          }
          if (key === "enable_emotion_simulation" && paramKey === "emotion_judgement_mode") {
            renderExperimentalPage();
          }
        });
      }
    });
    form.querySelectorAll("[data-feature-provider-select]").forEach((select) => {
      syncFeatureProviderInput(select);
      select.addEventListener("change", () => syncFeatureProviderInput(select));
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await saveExperimentalSettings(key, form, "已保存参数");
    });
  });
  root.querySelectorAll("[data-persona-standard-field], [data-persona-standard-source-text], [data-persona-standard-supplement]").forEach((input) => {
    input.addEventListener("input", () => {
      collectPersonaStandardizationQuestionnaire();
      const key = input.dataset.personaStandardField || "";
      if (["speech", "output", "examples"].includes(key)) {
        invalidatePersonaStyleDraft(root);
      } else {
        invalidatePersonaStandardizationDraft(root);
      }
    });
  });
  root.querySelector("[data-persona-standard-template]")?.addEventListener("input", () => {
    invalidatePersonaStyleDraft(root);
    const draft = personaStandardizationDraftState();
    draft.base_confirmed = false;
  });
  root.querySelector("[data-persona-style-reference]")?.addEventListener("input", () => {
    collectPersonaStandardizationQuestionnaire();
    invalidatePersonaStyleDraft(root);
  });
  root.querySelectorAll("[data-persona-standard-source], [data-persona-standard-strength], [data-persona-standard-persona]").forEach((input) => {
    input.addEventListener("change", () => {
      collectPersonaStandardizationQuestionnaire();
      invalidatePersonaStandardizationDraft(root);
      renderExperimentalPage();
    });
  });
  root.querySelector("[data-persona-standard-generate]")?.addEventListener("click", async (event) => {
    await generatePersonaStandardizationDraft(event.currentTarget);
  });
  root.querySelector("[data-persona-style-generate]")?.addEventListener("click", async (event) => {
    await generatePersonaStyleScenarios(event.currentTarget);
  });
  root.querySelector("[data-persona-style-summary-generate]")?.addEventListener("click", async (event) => {
    await generatePersonaStyleSummary(event.currentTarget);
  });
  root.querySelectorAll("[data-persona-style-choice]").forEach((input) => {
    input.addEventListener("change", () => {
      const draft = personaStandardizationDraftState();
      const scenarioId = input.dataset.personaStyleChoice || "";
      draft.style_choices = draft.style_choices || {};
      draft.style_custom = draft.style_custom || {};
      draft.style_choices[scenarioId] = input.value || "";
      const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
      const scenario = scenarios.find((item) => item.id === scenarioId);
      const selected = (scenario?.options || []).find((option) => option.id === input.value);
      const selectedText = selected?.text || "";
      if (selectedText) {
        draft.style_custom[scenarioId] = selectedText;
        const customInput = Array.from(root.querySelectorAll("[data-persona-style-custom]"))
          .find((item) => item.dataset.personaStyleCustom === scenarioId);
        if (customInput) customInput.value = selectedText;
      }
      invalidatePersonaStyleSummary(root);
      maybePrefetchPersonaStyleScenarios();
      renderExperimentalPage();
    });
  });
  root.querySelectorAll("[data-persona-style-custom]").forEach((input) => {
    input.addEventListener("input", () => {
      const draft = personaStandardizationDraftState();
      const scenarioId = input.dataset.personaStyleCustom || "";
      draft.style_custom = draft.style_custom || {};
      draft.style_custom[scenarioId] = input.value || "";
      invalidatePersonaStyleSummary(root);
      const nextButton = Array.from(root.querySelectorAll("[data-persona-style-next]"))
        .find((item) => item.dataset.personaStyleNext === scenarioId);
      const scenarios = state.personaStandardizationStyleDraft?.draft?.scenarios || [];
      const scenario = scenarios.find((item) => personaStyleScenarioId(item) === scenarioId);
      if (nextButton && scenario) nextButton.disabled = !personaStyleScenarioAnswered(scenario, draft);
      if (String(input.value || "").trim()) maybePrefetchPersonaStyleScenarios();
    });
  });
  root.querySelectorAll("[data-persona-style-feedback]").forEach((input) => {
    input.addEventListener("input", () => {
      const draft = personaStandardizationDraftState();
      draft.style_feedback = draft.style_feedback || {};
      draft.style_feedback[input.dataset.personaStyleFeedback || ""] = input.value || "";
      invalidatePersonaStyleSummary(root);
    });
  });
  root.querySelectorAll("[data-persona-final-title], [data-persona-final-content]").forEach((input) => {
    input.addEventListener("input", () => {
      const editor = state.personaStandardizationFinalEditor;
      if (!editor) return;
      const id = input.dataset.personaFinalTitle || input.dataset.personaFinalContent || "";
      const section = (editor.sections || []).find((item) => item.id === id);
      if (!section) return;
      if (input.dataset.personaFinalTitle !== undefined) {
        section.title = input.value || "";
      } else {
        section.content = input.value || "";
      }
      if (state.personaStandardizationVoiceDraft) {
        state.personaStandardizationVoiceDraftStale = true;
        root.querySelector("[data-persona-voice-save]")?.setAttribute("disabled", "disabled");
        const voicePanel = root.querySelector(".persona-voice-apply");
        if (voicePanel && !voicePanel.querySelector("[data-persona-voice-stale-warning]")) {
          const warning = document.createElement("div");
          warning.className = "setup-guide-hint warn";
          warning.dataset.personaVoiceStaleWarning = "true";
          warning.textContent = "最终人格内容已修改，下方分通道草稿可能不再对应最新文本。请先重新生成分通道草稿，再保存到插件表达风格。";
          voicePanel.querySelector(".persona-voice-notes")?.before(warning);
        }
      }
    });
  });
  root.querySelectorAll("[data-persona-voice-channel]").forEach((input) => {
    input.addEventListener("input", () => {
      const channel = input.dataset.personaVoiceChannel || "";
      if (!channel) return;
      state.personaStandardizationVoiceDraft = state.personaStandardizationVoiceDraft || {};
      state.personaStandardizationVoiceDraft[channel] = input.value || "";
    });
  });
  root.querySelector("[data-persona-voice-regenerate]")?.addEventListener("click", () => {
    state.personaStandardizationVoiceDraft = buildPersonaVoiceChannelDrafts(root);
    state.personaStandardizationVoiceDraftStale = false;
    renderExperimentalPage();
    showToast("已重新生成分通道草稿，请审核后保存");
  });
  root.querySelector("[data-persona-voice-save]")?.addEventListener("click", async (event) => {
    await savePersonaVoiceChannelDrafts(event.currentTarget, root);
  });
  root.querySelectorAll("[data-persona-style-retry]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      await retryPersonaStyleScenario(event.currentTarget.dataset.personaStyleRetry || "", event.currentTarget);
    });
  });
  root.querySelectorAll("[data-persona-style-focus]").forEach((button) => {
    button.addEventListener("click", () => {
      const scenarioId = button.dataset.personaStyleFocus || "";
      if (!scenarioId) return;
      setPersonaStyleScenarioFocus(scenarioId);
      renderExperimentalPage();
    });
  });
  root.querySelectorAll("[data-persona-style-next]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      await advancePersonaStyleScenario(event.currentTarget.dataset.personaStyleNext || "", event.currentTarget);
    });
  });
  root.querySelector("[data-persona-style-load-more]")?.addEventListener("click", async (event) => {
    const result = await loadMorePersonaStyleScenarios({ silent: false, button: event.currentTarget });
    if (result) {
      const nextId = personaStyleNextUnansweredScenarioId();
      if (nextId) setPersonaStyleScenarioFocus(nextId);
      renderExperimentalPage();
    }
  });
  root.querySelector("[data-persona-standard-fill-sample]")?.addEventListener("click", () => {
    fillPersonaStandardizationSample();
  });
  root.querySelector("[data-persona-standard-confirm]")?.addEventListener("click", () => {
    confirmPersonaStandardizationBase();
  });
  root.querySelector("[data-persona-standard-copy]")?.addEventListener("click", async () => {
    const text = root.querySelector("[data-persona-standard-template]")?.value || state.personaStandardizationDraft?.draft?.template || "";
    await copyTextToClipboard(text, "已复制审核稿");
  });
  root.querySelector("[data-persona-standard-copy-final]")?.addEventListener("click", async () => {
    const text = collectPersonaFinalEditor(root) || personaStandardizationMergedTemplate();
    await copyTextToClipboard(text, "已复制最终稿");
  });
  root.querySelector("[data-persona-standard-clear]")?.addEventListener("click", () => {
    state.personaStandardizationDraft = null;
    state.personaStandardizationStyleDraft = null;
    state.personaStandardizationStyleSummaryDraft = null;
    state.personaStandardizationFinalEditor = null;
    state.personaStandardizationVoiceDraft = null;
    state.personaStandardizationVoiceDraftStale = false;
    state.personaStandardizationBaseStale = false;
    state.personaStandardizationStyleStale = false;
    state.personaStandardizationStyleScenarioFocusId = "";
    state.personaStandardizationStyleBatchLoading = false;
    state.personaStandardizationStyleBatchRequestedOffset = null;
    const draft = personaStandardizationDraftState();
    draft.base_confirmed = false;
    draft.style_choices = {};
    draft.style_custom = {};
    draft.style_feedback = {};
    renderExperimentalPage();
  });
}
