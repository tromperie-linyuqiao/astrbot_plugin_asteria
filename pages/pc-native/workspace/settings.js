/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {postJson} from './client.js';
import {featureDescription,featureLabel,featurePublicKey,requireSecondClick,runAction,setActionBusy,showToast} from './persona.js';
import {bindFeatureDetailActions,bindProactiveOnlyTempUnlockActions,configDescription,featureDetailPage} from './providers.js';
import {collectPhotoApiEndpointEditor,collectSettingValue,displaySettingValue,featureLockedByProactiveOnlyMode,featureSearchText,featureTemporarilyUnlockedByProactiveOnly,formatProactiveDailyQuota,formatProactiveLimit,isPercentInputSetting,isPrivateReadingAvailable,isProviderConfigKey,proactiveOnlyModeEnabled,proactiveOnlyRelatedUnlocks,toBool,topLevelFeatureKey,visibleConfigKey,visibleFeatureSwitchKey,visibleTopLevelFeatureKeys} from './schema.js';
import {$,ROLEPLAY_MODE_STORAGE_KEY,asteriaWorkspaceState,embeddedFeatureParentByKey,featureGroups,featureSettingGroups,featureSettingTypes,newsSourcePresets,presetCatalog,roleplayExamples,roleplayLabelAliases,roleplayPersonaParts,roleplayTranslationParts,roleplayVisionParts,roleplayWorldParts,safeFeatureKeys,segmentedPreviewExamples,state} from './state.js';
import {escapeHtml} from './workspace.js';

export function moduleWorkbenchCard(item) {
  const meta = Array.isArray(item.meta) ? item.meta.filter(Boolean) : [];
  const actions = Array.isArray(item.actions) ? item.actions.filter(Boolean) : [];
  return `
    <article class="module-workbench-card ${escapeHtml(item.tone || "info")}">
      <header>
        <div>
          <span>${escapeHtml(item.kicker || "模块")}</span>
          <b>${escapeHtml(item.title || "未命名模块")}</b>
        </div>
        <em>${escapeHtml(item.status || "未知")}</em>
      </header>
      <p>${escapeHtml(item.body || "暂无模块概览。")}</p>
      ${meta.length ? `<div class="module-workbench-meta">${meta.map((value) => `<small>${escapeHtml(value)}</small>`).join("")}</div>` : ""}
      ${actions.length ? `<footer>${actions.map(([tab, label]) => `<button type="button" data-jump-tab="${escapeHtml(tab)}">${escapeHtml(label)}</button>`).join("")}</footer>` : ""}
    </article>
  `;
}

export function renderCurrentPersonaStatus(settings) {
  const input = document.getElementById("currentPersonaDisplay");
  if (!input) return;
  const personaId = String(settings.plugin_specific_persona_id || "").trim();
  input.value = personaId ? `插件指定人格 ID：${personaId}` : "继承 AstrBot 当前默认人格";
}

export function renderExternalAbilities() {
  const box = $("#externalAbilityList");
  if (!box) return;
  const items = state.overview?.external_abilities?.items || [];
  if (!items.length) {
    box.innerHTML = `<div class="empty small">暂无外部插件注册主动能力。第三方插件接入后会显示在这里，默认不会自动启用。</div>`;
    return;
  }
  box.innerHTML = items.map((item) => {
    const configText = JSON.stringify(item.config || {}, null, 2);
    const schemaRows = externalAbilitySchemaRows(item.config_schema || {});
    return `
      <article class="external-ability-card ${item.enabled ? "is-enabled" : ""} ${item.available ? "" : "is-unavailable"}">
        <header>
          <div>
            <span class="module-badge">${escapeHtml(item.module || "外部主动能力")}</span>
            <h3>${escapeHtml(item.label || item.name)}</h3>
            <p>${escapeHtml(item.description || item.use_for || "外部插件提供的主动行为。")}</p>
          </div>
          <span class="badge ${item.enabled && item.available ? "" : "off"}">${escapeHtml(item.available ? (item.enabled ? "启用" : "停用") : "未加载")}</span>
        </header>
        <div class="external-ability-meta">
          <div class="external-ability-meta-row"><span class="external-ability-meta-label">触发场景</span><span class="external-ability-meta-value">${escapeHtml(item.when || "由外部插件描述")}</span></div>
          <div class="external-ability-meta-row"><span class="external-ability-meta-label">适合用途</span><span class="external-ability-meta-value">${escapeHtml(item.use_for || "-")}</span></div>
          <div class="external-ability-meta-row"><span class="external-ability-meta-label">避开事项</span><span class="external-ability-meta-value">${escapeHtml(item.avoid || "-")}</span></div>
          <div class="external-ability-meta-row"><span class="external-ability-meta-label">最近执行</span><span class="external-ability-meta-value">${escapeHtml(item.last_executed || "从未")} ${item.last_summary ? `· ${escapeHtml(item.last_summary)}` : ""}</span></div>
        </div>
        <form class="external-ability-form" data-external-ability-form="${escapeHtml(item.name)}">
          <label class="toggle-row"><input name="enabled" type="checkbox" ${item.enabled ? "checked" : ""} ${item.available ? "" : "disabled"} /> <span>加入主动候选</span></label>
          <label>触发权重（%）<input name="share_probability" type="number" min="0" max="100" step="1" value="${escapeHtml(displaySettingValue('share_probability', Number(item.share_probability ?? 0)))}" /></label>
          <label>最小间隔小时 <input name="min_interval_hours" type="number" min="0" step="0.5" value="${escapeHtml(item.min_interval_hours ?? 0)}" /></label>
          <label class="wide-field">自定义配置 <textarea name="config" rows="5">${escapeHtml(configText)}</textarea></label>
          ${schemaRows ? `<div class="external-ability-schema wide-field">${schemaRows}</div>` : ""}
          <button type="submit">保存外部能力</button>
        </form>
      </article>
    `;
  }).join("");
}

export function externalAbilitySchemaRows(schema) {
  const entries = Object.entries(schema || {});
  if (!entries.length) return "";
  return entries.slice(0, 16).map(([key, raw]) => {
    const item = raw && typeof raw === "object" ? raw : {};
    const label = item.label || item.title || key;
    const desc = item.description || item.desc || item.help || "";
    return `<span><b>${escapeHtml(label)}</b>${desc ? `：${escapeHtml(desc)}` : ""}<small>${escapeHtml(key)}</small></span>`;
  }).join("");
}

export function markModuleFormDirty(form) {
  form?.closest(".module-card")?.classList.add("is-dirty");
}

export function markModuleFormClean(form) {
  const card = form?.closest(".module-card");
  if (!card) return;
  card.classList.remove("is-dirty");
}

export function renderPresetCards() {
  const box = $("#presetCards");
  if (!box) return;
  box.innerHTML = Object.entries(presetCatalog).map(([key, preset]) => {
    const changes = Array.isArray(preset.changes) ? preset.changes : [];
    return `
      <section class="preset-card preset-card-${escapeHtml(preset.tone || "balanced")}">
        <div class="preset-card-top">
          <span class="preset-pill">${escapeHtml(preset.cost || "预设")}</span>
          <b>${escapeHtml(preset.label)}</b>
          <p>${escapeHtml(preset.tagline || "")}</p>
        </div>
        <div class="preset-card-body">
          <span><strong>适合</strong>${escapeHtml(preset.bestFor || "")}</span>
          <span><strong>节奏</strong>${escapeHtml(preset.rhythm || "")}</span>
        </div>
        <div class="preset-change-list">
          ${changes.map((item) => `<em>${escapeHtml(item)}</em>`).join("")}
        </div>
        <button type="button" data-preset="${escapeHtml(key)}">应用这一套</button>
      </section>
    `;
  }).join("");
  document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", async () => {
      const label = presetCatalog[button.dataset.preset]?.label || button.dataset.preset;
      if (!requireSecondClick(button, `preset:${button.dataset.preset}`, `再次点击应用“${label}”`, "再次点击应用")) return;
      await runAction(() => postJson("/preset/apply", { name: button.dataset.preset }), "已应用配置预设", button);
    });
  });
}

export function fillForm(selector, values) {
  const form = $(selector);
  if (!form) return;
  form.querySelectorAll("[name]").forEach((input) => {
    const value = values[input.name];
    if (input.type === "checkbox") {
      input.checked = toBool(value);
    } else if (Array.isArray(value)) {
      input.value = value.join("\n");
    } else {
      input.value = displaySettingValue(input.name, value);
    }
  });
  if (selector === "#roleplayProfileForm") {
    hydrateRoleplayStandardFields();
    renderRoleplayKnowledgeSources();
  }
}

export function collectFormSettings(selector) {
  const form = $(selector);
  const result = {};
  if (!form) return result;
  if (selector === "#roleplayProfileForm") {
    if (roleplayMode() === "freeform") hydrateRoleplayStandardFields();
    syncRoleplayStandardFieldsToFreeform();
    syncRoleplayCoreFieldsFromPersona();
    syncRoleplayKnowledgeSelectionToInput();
  }
  form.querySelectorAll("[name]").forEach((input) => {
    if (input.disabled) return;
    result[input.name] = collectSettingValue(input.name, input);
  });
  return result;
}

export function roleplayKnowledgeSelectedSet() {
  const settings = state.overview?.settings || {};
  const hidden = document.querySelector('#roleplayProfileForm [name="roleplay_knowledge_source_ids"]');
  const raw = hidden ? hidden.value : (settings.roleplay_knowledge_source_ids || state.overview?.knowledge?.selected_ids || []);
  const items = Array.isArray(raw) ? raw : String(raw || "").split(/\r?\n|[,，;；]/);
  return new Set(items.map((item) => String(item || "").trim()).filter(Boolean));
}

export function syncRoleplayKnowledgeSelectionToInput() {
  const hidden = document.querySelector('#roleplayProfileForm [name="roleplay_knowledge_source_ids"]');
  if (!hidden) return;
  const selected = [...document.querySelectorAll("[data-roleplay-knowledge-id]:checked")]
    .map((input) => input.dataset.roleplayKnowledgeId || "")
    .filter(Boolean);
  hidden.value = selected.join("\n");
  const badge = document.getElementById("roleplayKnowledgeCount");
  if (badge) badge.textContent = String(selected.length);
}

export function renderRoleplayKnowledgeSources() {
  const box = document.getElementById("roleplayKnowledgeSources");
  if (!box) return;
  const knowledge = state.overview?.knowledge || {};
  const sources = Array.isArray(knowledge.sources) ? knowledge.sources : [];
  const selected = roleplayKnowledgeSelectedSet();
  const badge = document.getElementById("roleplayKnowledgeCount");
  if (badge) badge.textContent = String(selected.size);
  const returnedIds = new Set(sources.flatMap(source => [source.id, ...(source.documents || []).map(doc => doc.id)]));
  const unreturned = [...selected].filter(id => !returnedIds.has(id));
  box.innerHTML = sources.map((source) => {
    const sourceId = String(source.id || "");
    const docs = Array.isArray(source.documents) ? source.documents : [];
    const docRows = docs.map((doc) => {
      const docId = String(doc.id || "");
      const chunkCount = Number(doc.chunk_count || 0);
      return `
        <label class="roleplay-knowledge-doc">
          <input type="checkbox" data-roleplay-knowledge-id="${escapeHtml(docId)}" ${selected.has(docId) ? "checked" : ""} />
          <span>
            <b>${escapeHtml(doc.name || doc.doc_id || "未命名文档")}</b>
            <small>${escapeHtml(doc.file_type || "doc")} · ${chunkCount} 段</small>
          </span>
        </label>
      `;
    }).join("");
    return `
      <article class="roleplay-knowledge-source">
        <label class="roleplay-knowledge-base">
          <input type="checkbox" data-roleplay-knowledge-id="${escapeHtml(sourceId)}" ${selected.has(sourceId) ? "checked" : ""} />
          <span>
            <b>${escapeHtml(source.emoji ? `${source.emoji} ${source.name || source.kb_id}` : (source.name || source.kb_id || "未命名知识库"))}</b>
            <small>${Number(source.doc_count || docs.length)} 文档 · ${Number(source.chunk_count || 0)} 段</small>
          </span>
        </label>
        ${source.description ? `<p>${escapeHtml(source.description)}</p>` : ""}
        ${docRows ? `<div class="roleplay-knowledge-docs">${docRows}</div>` : ""}
      </article>
    `;
  }).join("");
  if (!sources.length) box.innerHTML = `<p class="section-desc">当前目录未返回可选择的知识库，不能据此认定资料已删除。</p>`;
  if (unreturned.length) box.insertAdjacentHTML("beforeend", `<section class="roleplay-knowledge-source"><b>当前目录未返回的引用</b><p>可能暂不可读或已移除。本页保留原标识，取消勾选并保存才会移除引用；不会删除知识库资料。</p>${unreturned.map(id => `<label class="roleplay-knowledge-doc"><input type="checkbox" data-roleplay-knowledge-id="${escapeHtml(id)}" checked /><span>${escapeHtml(id)}</span></label>`).join("")}</section>`);
  box.querySelectorAll("[data-roleplay-knowledge-id]").forEach((input) => {
    input.addEventListener("change", () => {
      syncRoleplayKnowledgeSelectionToInput();
      markModuleFormDirty(document.getElementById("roleplayProfileForm"));
    });
  });
  syncRoleplayKnowledgeSelectionToInput();
}

export function escapeRegExp(text) {
  return String(text || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function roleplayMode() {
  if (asteriaWorkspaceState.roleplayModeState === "standard" || asteriaWorkspaceState.roleplayModeState === "freeform") return asteriaWorkspaceState.roleplayModeState;
  const studioMode = document.querySelector(".roleplay-studio")?.dataset.roleplayMode;
  if (studioMode === "standard" || studioMode === "freeform") return studioMode;
  let stored = "";
  try {
    stored = window.localStorage?.getItem(ROLEPLAY_MODE_STORAGE_KEY) || "";
  } catch (error) {
    stored = "";
  }
  return stored === "freeform" ? "freeform" : "standard";
}

export function setRoleplayMode(mode) {
  const normalized = mode === "standard" ? "standard" : "freeform";
  asteriaWorkspaceState.roleplayModeState = normalized;
  try {
    window.localStorage?.setItem(ROLEPLAY_MODE_STORAGE_KEY, normalized);
  } catch (error) {
    // 嵌入式拓展页环境可能禁用 localStorage，模式仍可在当前页面内切换。
  }
  const studio = document.querySelector(".roleplay-studio");
  if (studio) studio.dataset.roleplayMode = normalized;
  document.querySelectorAll(".roleplay-mode-switch [data-roleplay-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.roleplayMode === normalized);
  });
}

export function bindRoleplayModeSwitch() {
  setRoleplayMode(roleplayMode());
  document.querySelectorAll(".roleplay-mode-switch [data-roleplay-mode]").forEach((button) => {
    button.addEventListener("click", () => switchRoleplayEditingMode(button.dataset.roleplayMode));
  });
  document.querySelectorAll("[data-roleplay-example]").forEach((button) => {
    button.addEventListener("click", () => applyRoleplayExample(button.dataset.roleplayExample));
  });
  const draftButton = document.getElementById("generateRoleplayDraftBtn");
  if (draftButton) draftButton.addEventListener("click", () => generateRoleplayDraftFromPersona(draftButton));
}

export function applyRoleplayExample(kind) {
  const example = roleplayExamples[kind];
  if (!example) return;
  switchRoleplayEditingMode("standard");
  if (kind === "persona") {
    Object.entries(example).forEach(([key, value]) => {
      const control = document.querySelector(`[data-roleplay-persona-part="${key}"]`);
      if (control) control.value = value;
    });
  } else if (kind === "world") {
    Object.entries(example).forEach(([key, value]) => {
      if (key === "translations") return;
      const control = document.querySelector(`[data-roleplay-world-part="${key}"]`);
      if (control) control.value = value;
    });
    Object.entries(example.translations || {}).forEach(([key, value]) => {
      const control = document.querySelector(`[data-roleplay-translation-part="${key}"]`);
      if (control) control.value = value;
    });
  } else if (kind === "user") {
    const nickname = document.querySelector('#roleplayProfileForm [name="default_nickname"]');
    if (nickname) nickname.value = example.nickname || "";
    ["user_gender", "user_age", "user_occupation", "role_relation", "interaction", "extra"].forEach((key) => {
      const control = document.querySelector(`[data-roleplay-user-part="${key}"]`);
      if (control) control.value = example[key] || "";
    });
  }
  const form = document.getElementById("roleplayProfileForm");
  if (form) markModuleFormDirty(form);
}

export async function generateRoleplayDraftFromPersona(button) {
  const scopes = selectedRoleplayDraftScopes();
  if (!scopes.length) return showToast("至少选择一类提取范围", "error");
  setActionBusy(button, true);
  showToast("正在读取主回复人格并提取世界知识草稿...");
  try {
    const result = await postJson("/roleplay/draft_from_persona", { scopes });
    state.roleplayPersonaDraft = result || null;
    renderRoleplayPersonaDraftPanel();
    showToast(result?.parse_note ? "草稿含处理说明，请核对后再填入" : "世界知识草稿已生成，请先预览再填入");
  } catch (error) {
    showToast(`生成失败：${error.message}`, "error");
  } finally {
    setActionBusy(button, false);
  }
}

export function selectedRoleplayDraftScopes() {
  const scopes = Array.from(document.querySelectorAll("[data-roleplay-draft-scope]:checked"))
    .map((input) => input.dataset.roleplayDraftScope || "")
    .filter(Boolean);
  return scopes;
}

export function renderRoleplayPersonaDraftPanel() {
  const panel = document.getElementById("roleplayPersonaDraftPanel");
  if (!panel) return;
  const result = state.roleplayPersonaDraft || {};
  const draft = result.draft || {};
  const scopes = Array.isArray(result.scopes) ? result.scopes : [];
  const rows = [
    ...roleplayDraftPartRows(draft.persona_parts, roleplayPersonaParts, "角色资料"),
    ...roleplayDraftPartRows(draft.world_parts, roleplayWorldParts, "世界观资料"),
    ...roleplayDraftPartRows(draft.user_parts, roleplayVisionParts, "用户与关系"),
    ...roleplayTranslationParts.map((label) => ["翻译", label, draft.translations?.[label] || ""]).filter(([, , value]) => String(value || "").trim()),
  ];
  const imageHint = String(draft.image_self_recognition_hint || "").trim();
  if (imageHint) rows.push(["识图", "图片自我识别线索", imageHint]);
  const notes = Array.isArray(draft.notes) ? draft.notes.filter(Boolean) : [];
  panel.hidden = false;
  panel.innerHTML = `
    <header>
      <div>
        <b>世界知识草稿</b>
        <span>${escapeHtml(roleplayDraftScopeLabel(scopes))} · ${escapeHtml(result.persona_id ? `指定人格：${result.persona_id}` : "继承 AstrBot 默认人格")} · ${escapeHtml(result.provider_id || "主模型")} · 来源 ${escapeHtml(result.source_chars || 0)} 字</span>
      </div>
      <div class="persona-draft-panel-actions">
        <button type="button" data-roleplay-draft-apply="empty">填入空白项</button>
        <button type="button" data-roleplay-draft-apply="overwrite" class="soft">覆盖当前草稿</button>
        <button type="button" data-roleplay-draft-close class="ghost">关闭</button>
      </div>
    </header>
    <p class="world-draft-origin">${escapeHtml(result.parse_note || "接口返回了可解析草稿；仍需核对内容和推断。")} </p>
    <p class="section-desc">请求来源：${escapeHtml(result.provider_id || "默认 Provider")} ${result.repair_provider_id ? ` · 修复请求：${escapeHtml(result.repair_provider_id)}` : ""}。这些标识是配置的请求来源，不是供应商执行回执；本页尚未保存。</p>
    <details><summary>查看来源摘要</summary><p>${escapeHtml(result.source_preview || "未返回来源摘要")}</p><p class="section-desc">来源 ${escapeHtml(result.source_chars || 0)} 字；摘要不等于完整人格。</p></details>
    ${rows.length ? `
      <div class="persona-draft-grid">
        ${rows.map(([group, label, value]) => `
          <section>
            <small>${escapeHtml(group)}</small>
            <b>${escapeHtml(label)}</b>
            <p>${escapeHtml(value)}</p>
          </section>
        `).join("")}
      </div>
    ` : `<div class="empty small">主模型没有抽取到足够明确的世界知识字段。可以换一个写得更具体的主回复人格后再试。</div>`}
    ${notes.length ? `<div class="persona-draft-notes">${notes.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
  `;
  panel.querySelector("[data-roleplay-draft-close]")?.addEventListener("click", () => {
    panel.hidden = true;
  });
  panel.querySelectorAll("[data-roleplay-draft-apply]").forEach((control) => {
    control.addEventListener("click", () => {
      const overwrite = control.dataset.roleplayDraftApply === "overwrite";
      if (overwrite && !requireSecondClick(control, "roleplay-draft-overwrite", "再次点击会覆盖当前世界知识工作台里对应范围的草稿", "再次点击覆盖")) {
        return;
      }
      applyRoleplayPersonaDraft(overwrite);
    });
  });
}

export function roleplayDraftPartRows(source, parts, group) {
  const data = source && typeof source === "object" ? source : {};
  return parts
    .map(([key, label]) => [group, label, data[key] || ""])
    .filter(([, , value]) => String(value || "").trim());
}

export function roleplayDraftScopeLabel(scopes) {
  const selected = new Set(scopes || []);
  const labels = [
    selected.has("persona") ? "角色资料" : "",
    selected.has("world") ? "世界观资料" : "",
    selected.has("user") ? "用户与关系" : "",
  ].filter(Boolean);
  return labels.length ? `范围：${labels.join("、")}` : "范围：角色资料";
}

export function applyRoleplayPersonaDraft(overwrite = false) {
  const draft = state.roleplayPersonaDraft?.draft || {};
  const scopes = new Set(Array.isArray(state.roleplayPersonaDraft?.scopes) ? state.roleplayPersonaDraft.scopes : ["persona"]);
  switchRoleplayEditingMode("standard");
  let changed = 0;
  if (scopes.has("persona")) {
    roleplayPersonaParts.forEach(([key]) => {
      changed += fillRoleplayDraftControl(`[data-roleplay-persona-part="${key}"]`, draft.persona_parts?.[key], overwrite);
    });
    changed += fillRoleplayDraftControl('#roleplayProfileForm [name="private_image_self_recognition_hint"]', draft.image_self_recognition_hint, overwrite);
  }
  if (scopes.has("world")) {
    roleplayWorldParts.forEach(([key]) => {
      changed += fillRoleplayDraftControl(`[data-roleplay-world-part="${key}"]`, draft.world_parts?.[key], overwrite);
    });
    roleplayTranslationParts.forEach((label) => {
      changed += fillRoleplayDraftControl(`[data-roleplay-translation-part="${label}"]`, draft.translations?.[label], overwrite);
    });
  }
  if (scopes.has("user")) {
    changed += fillRoleplayDraftControl('#roleplayProfileForm [name="default_nickname"]', draft.user_parts?.nickname, overwrite);
    roleplayVisionParts.forEach(([key]) => {
      if (key === "nickname") return;
      changed += fillRoleplayDraftControl(`[data-roleplay-user-part="${key}"]`, draft.user_parts?.[key], overwrite);
    });
  }
  syncRoleplayStandardFieldsToFreeform();
  const form = document.getElementById("roleplayProfileForm");
  if (changed && form) markModuleFormDirty(form);
  showToast(changed ? `已填入 ${changed} 项，请检查后保存世界知识` : "没有可填入的新字段");
}

export function fillRoleplayDraftControl(selector, value, overwrite = false) {
  const text = String(value || "").trim();
  if (!text) return 0;
  const control = document.querySelector(selector);
  if (!control) return 0;
  if (!overwrite && String(control.value || "").trim()) return 0;
  control.value = text;
  return 1;
}

export function extractLabeledValue(text, labels, label) {
  const lines = String(text || "").split(/\r?\n/);
  const labelSet = new Set(labels);
  const collected = [];
  let active = false;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    const matched = labels.find((item) => line.startsWith(`${item}：`) || line.startsWith(`${item}:`));
    if (matched) {
      if (active) break;
      active = matched === label;
      if (active) collected.push(line.replace(new RegExp(`^${escapeRegExp(label)}[：:]\\s*`), ""));
      continue;
    }
    if (active) {
      if (labelSet.has(line.replace(/[：:].*$/, ""))) break;
      collected.push(rawLine);
    }
  }
  return collected.join("\n").trim();
}

export function extractTranslationValue(text, label) {
  const pattern = new RegExp(`^\\s*${escapeRegExp(label)}\\s*(?:=|：|:)\\s*(.+?)\\s*$`);
  for (const line of String(text || "").split(/\r?\n/)) {
    const match = line.match(pattern);
    if (match) return match[1].trim();
  }
  return "";
}

export function hydrateRoleplayPartGroup(sourceName, attr, parts) {
  const text = document.querySelector(`#roleplayProfileForm [name="${sourceName}"]`)?.value || "";
  const labels = parts.map(([, label]) => label);
  parts.forEach(([key, label]) => {
    const control = document.querySelector(`[${attr}="${key}"]`);
    if (!control) return;
    let value = extractLabeledValue(text, labels, label);
    if (!value && roleplayLabelAliases[label]) {
      const aliasLabels = [...labels, ...roleplayLabelAliases[label]];
      for (const alias of roleplayLabelAliases[label]) {
        value = extractLabeledValue(text, aliasLabels, alias);
        if (value) break;
      }
    }
    control.value = value;
  });
}

export function syncRoleplayCoreFieldsFromPersona() {
  const personaText = document.querySelector('#roleplayProfileForm [name="schedule_persona_prompt"]')?.value || "";
  const labels = roleplayPersonaParts.map(([, label]) => label);
  const nameFromStandard = String(document.querySelector('[data-roleplay-persona-part="name"]')?.value || "").trim();
  const styleFromStandard = String(document.querySelector('[data-roleplay-persona-part="personality"]')?.value || "").trim();
  const name = nameFromStandard || extractLabeledValue(personaText, labels, "姓名");
  const style = styleFromStandard || extractLabeledValue(personaText, labels, "性格描述");
  const botNameInput = document.querySelector('#roleplayProfileForm [name="bot_name"]');
  const defaultStyleInput = document.querySelector('#roleplayProfileForm [name="default_style"]');
  if (botNameInput && name) botNameInput.value = name;
  if (defaultStyleInput && style) defaultStyleInput.value = style;
}

export function hydrateRoleplayUserFields() {
  const primaryText = document.querySelector('#roleplayProfileForm [name="roleplay_user_profile_prompt"]')?.value || "";
  const text = primaryText;
  const legacyPersonaText = document.querySelector('#roleplayProfileForm [name="schedule_persona_prompt"]')?.value || "";
  const labels = roleplayVisionParts.map(([, label]) => label);
  roleplayVisionParts.forEach(([key, label]) => {
    if (key === "nickname") {
      const nickname = extractLabeledValue(text, labels, label);
      const control = document.querySelector('#roleplayProfileForm [name="default_nickname"]');
      if (control && nickname && !String(control.value || "").trim()) control.value = nickname;
      return;
    }
    const control = document.querySelector(`[data-roleplay-user-part="${key}"], [data-roleplay-vision-part="${key}"]`);
    if (!control) return;
    let value = extractLabeledValue(text, labels, label);
    if (!value && label === "是角色的XX") {
      value = extractLabeledValue(legacyPersonaText, ["身份", "年龄感", "生活处境", "与用户关系", "说话风格", "能力边界", "禁区"], label);
      if (!value) value = extractLabeledValue(legacyPersonaText, ["身份", "年龄感", "生活处境", "与用户关系", "说话风格", "能力边界", "禁区"], "与用户关系");
    }
    control.value = value;
  });
}

export function hydrateRoleplayStandardFields() {
  hydrateRoleplayPartGroup("schedule_persona_prompt", "data-roleplay-persona-part", roleplayPersonaParts);
  hydrateRoleplayPartGroup("schedule_worldview_prompt", "data-roleplay-world-part", roleplayWorldParts);
  hydrateRoleplayUserFields();
  syncRoleplayCoreFieldsFromPersona();
  const translationText = document.querySelector('#roleplayProfileForm [name="worldview_adaptation_prompt"]')?.value || "";
  roleplayTranslationParts.forEach((label) => {
    const control = document.querySelector(`[data-roleplay-translation-part="${label}"]`);
    if (control) control.value = extractTranslationValue(translationText, label);
  });
  captureRoleplayStandardBaseline();
  setRoleplayMode(roleplayMode());
}

export function composeLabeledParts(attr, parts) {
  const lines = [];
  parts.forEach(([key, label]) => {
    const control = document.querySelector(`[${attr}="${key}"]`);
    const value = String(control?.value || "").trim();
    if (value) lines.push(`${label}：${value}`);
  });
  return lines.join("\n");
}

export function composeRoleplayUserParts() {
  const lines = [];
  roleplayVisionParts.forEach(([key, label]) => {
    if (key === "nickname") {
      const value = String(document.querySelector('#roleplayProfileForm [name="default_nickname"]')?.value || "").trim();
      if (value) lines.push(`${label}：${value}`);
      return;
    }
    const control = document.querySelector(`[data-roleplay-user-part="${key}"], [data-roleplay-vision-part="${key}"]`);
    const value = String(control?.value || "").trim();
    if (value) lines.push(`${label}：${value}`);
  });
  return lines.join("\n");
}

export function composeTranslationParts() {
  const lines = [];
  roleplayTranslationParts.forEach((label) => {
    const control = document.querySelector(`[data-roleplay-translation-part="${label}"]`);
    const value = String(control?.value || "").trim();
    if (value) lines.push(`${label} = ${value}`);
  });
  return lines.join("\n");
}

export function roleplayEditorGroups() {
  const group = (name, attr, parts) => ({name, fields:parts.map(([key,label]) => ({label, aliases:roleplayLabelAliases[label] || [], control:document.querySelector(`[${attr}="${key}"]`)}))});
  const user = group("roleplay_user_profile_prompt", "data-roleplay-user-part", roleplayVisionParts);
  user.fields[0].control = document.querySelector('#roleplayProfileForm [name="default_nickname"]');
  return [group("schedule_persona_prompt", "data-roleplay-persona-part", roleplayPersonaParts), group("schedule_worldview_prompt", "data-roleplay-world-part", roleplayWorldParts), user,
    {name:"worldview_adaptation_prompt", lineOnly:true, fields:roleplayTranslationParts.map(label => ({label, aliases:[], control:document.querySelector(`[data-roleplay-translation-part="${label}"]`)}))}];
}

export function captureRoleplayStandardBaseline() {
  asteriaWorkspaceState.roleplayStandardBaseline = Object.fromEntries(roleplayEditorGroups().map(group => [group.name,group.fields.map(field => String(field.control?.value || ""))]));
}

export function switchRoleplayEditingMode(mode) {
  if (mode === roleplayMode()) return;
  if (roleplayMode() === "standard") syncRoleplayStandardFieldsToFreeform();
  else hydrateRoleplayStandardFields();
  setRoleplayMode(mode);
}

export function syncRoleplayStandardFieldsToFreeform() {
  if (roleplayMode() !== "standard") return;
  roleplayEditorGroups().forEach(group => {
    const target = document.querySelector(`#roleplayProfileForm [name="${group.name}"]`);
    if (!target || !asteriaWorkspaceState.roleplayStandardBaseline[group.name]) return;
    const labels = group.fields.flatMap(field => [field.label,...field.aliases]);
    const matches = (line, names) => names.some(label => new RegExp(`^\\s*${escapeRegExp(label)}\\s*[${group.lineOnly ? "=：:" : "：:"}]`).test(line));
    group.fields.forEach((field,index) => {
      const current = String(field.control?.value || "");
      if (current === asteriaWorkspaceState.roleplayStandardBaseline[group.name][index]) return;
      const value = current.trim(), lines = target.value.split("\n");
      const start = lines.findIndex(line => matches(line,[field.label,...field.aliases]));
      const replacement = value ? `${field.label}${group.lineOnly ? " = " : "："}${value}` : "";
      if (start < 0) {
        if (replacement) target.value += `${target.value && !target.value.endsWith("\n") ? "\n" : ""}${replacement}`;
        return;
      }
      let end = start+1;
      if (!group.lineOnly) while (end < lines.length && !matches(lines[end],labels)) end++;
      lines.splice(start,end-start,...(replacement ? replacement.split("\n") : []));target.value=lines.join("\n");
    });
  });
  captureRoleplayStandardBaseline();
  syncRoleplayCoreFieldsFromPersona();
}

export function renderRoleplaySavedReading(settings = state.overview?.settings || {}, status = "最近读取的背景资料") {
  const box = document.getElementById("roleplaySavedReading");if (!box) return;
  const knowledge = state.overview?.knowledge || {}, names = new Map();
  (knowledge.sources || []).forEach(source => {names.set(source.id,source.name || source.id);(source.documents || []).forEach(doc => names.set(doc.id,doc.name || doc.id));});
  const ids = Array.isArray(settings.roleplay_knowledge_source_ids) ? settings.roleplay_knowledge_source_ids : String(settings.roleplay_knowledge_source_ids || "").split(/\n|[,，;；]/).filter(Boolean);
  box.innerHTML = `<article class="world-reading"><h3>${escapeHtml(status)}</h3><p class="section-desc">配置来源：当前 TLS 原生陪伴。背景资料与 AstrBot 主回复人格分开；被引用不代表每次注入或实际使用。下方编辑区是本页草稿。</p><div class="world-reading-grid">${[["角色资料","schedule_persona_prompt"],["世界背景","schedule_worldview_prompt"],["用户与关系","roleplay_user_profile_prompt"],["平台称呼转写","worldview_adaptation_prompt"],["图片识别线索","private_image_self_recognition_hint"]].map(([label,key]) => `<details><summary>${label} · ${String(settings[key] || "").length} 字</summary><p class="world-prose">${escapeHtml(settings[key] || "未填写")}</p></details>`).join("")}</div><p>适配模式：${escapeHtml(settings.worldview_adaptation_mode || "auto")} · 默认称呼：${escapeHtml(settings.default_nickname || "未填写")}</p><details><summary>引用来源 · ${ids.length} 项</summary>${ids.length ? ids.map(id => `<p>${escapeHtml(names.get(id) || "当前目录未返回")} <small>${escapeHtml(id)}</small></p>`).join("") : "未选择知识库引用"}</details></article>`;
}

export async function saveRoleplayWorkspace(form,button) {
  if (asteriaWorkspaceState.roleplaySavePending || asteriaWorkspaceState.roleplaySaveUnknown) return;
  const payload = collectFormSettings("#roleplayProfileForm"), resultBox = document.getElementById("roleplaySaveResult");
  const limits = {schedule_persona_prompt:2000,schedule_worldview_prompt:2000,roleplay_user_profile_prompt:2000,worldview_adaptation_prompt:1200,private_image_self_recognition_hint:1200};
  for (const [key,limit] of Object.entries(limits)) if (Array.from(String(payload[key] || "").trim()).length > limit) return showToast(`内容超过原 ${limit} 字容量，请在原文填写中整理后保存；本次未提交`,"error");
  const ids = String(payload.roleplay_knowledge_source_ids || "").split(/\n|[,，;；]/).map(v=>v.trim()).filter(Boolean);
  if (ids.length > 80) return showToast("引用超过原 80 项容量，本次未提交", "error");
  const fingerprint = () => JSON.stringify([...form.querySelectorAll("input,textarea,select")].map(el => [el.name,el.value,el.checked]));
  const submittedFingerprint = fingerprint();asteriaWorkspaceState.roleplaySavePending=true;setActionBusy(button,true);
  resultBox.innerHTML='<p data-world-result="pending">正在保存本次背景资料…</p>';
  try {
    const result = await postJson("/settings/update",{settings:payload}), changed=result?.changed;
    if (!changed || typeof result.config_saved !== "boolean" || !Object.keys(payload).every(key => key === "roleplay_knowledge_source_ids" ? Array.isArray(changed[key]) && changed[key].every(id=>typeof id === "string") : typeof changed[key] === "string")) throw new Error("返回的保存字段不完整");
    state.overview.settings = {...state.overview.settings,...changed};
    const message = result.config_saved ? "本次背景资料已保存" : "配置未持久保存；陪伴运行态可能已改变";
    renderRoleplaySavedReading(state.overview.settings,result.config_saved ? "本次保存返回的背景资料" : "本次返回的运行值 · 未持久保存");
    resultBox.innerHTML=`<p data-world-result="${result.config_saved ? "saved" : "partial"}">${message}。本页输入保留；等待期间继续编辑的内容尚未提交。其他分区需主动刷新核对。</p>`;
    if (result.config_saved && submittedFingerprint === fingerprint()) markModuleFormClean(form);
    showToast(message,result.config_saved ? undefined : "error");
  } catch(error) {
    asteriaWorkspaceState.roleplaySaveUnknown=true;
    resultBox.innerHTML=`<p data-world-result="unknown">本次结果未确认：${escapeHtml(error.message)}。输入保留，本页不再次提交。请核对服务器配置；当前值相同不证明本次完成或落盘。刷新会丢失本页草稿和标记，不会撤销已开始操作。</p>`;
    showToast("世界知识保存结果未确认，请先核对", "error");
  } finally {asteriaWorkspaceState.roleplaySavePending=false;setActionBusy(button,false);if (asteriaWorkspaceState.roleplaySaveUnknown) button.disabled=true;}
}

export function parseNewsSources(raw) {
  return splitNewsSourceLines(raw).map((line) => {
    const original = line;
    let text = line.trim();
    if (!text) return null;
    const enabled = !text.startsWith("#");
    if (!enabled) text = text.replace(/^#+\s*/, "");
    let name = "";
    let target = text;
    if (text.includes("|")) {
      [name, target] = text.split("|", 2);
    }
    target = String(target || "").trim();
    name = String(name || "").trim();
    if (!target) return null;
    const lowerTarget = target.toLowerCase();
    const type = lowerTarget.startsWith("bvid:") || target.includes("bilibili.com/video/")
      ? "bilibili_video"
      : (lowerTarget.startsWith("bilibili:") || target.includes("space.bilibili.com") ? "bilibili" : "rss");
    return { enabled, name, target, type, original };
  }).filter(Boolean);
}

export function splitNewsSourceLines(raw) {
  const text = String(raw || "").trim();
  if (!text) return [];
  const normalLines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (normalLines.length !== 1) return normalLines;
  const line = normalLines[0];
  const markers = Array.from(line.matchAll(/(?:^|\s+)(#?\s*[^|\n]+?)\|(?=(?:https?:\/\/|bilibili:|bvid:))/gi));
  if (markers.length <= 1) return normalLines;
  return markers.map((match, index) => {
    const start = match.index + match[0].length;
    const end = index + 1 < markers.length ? markers[index + 1].index : line.length;
    const name = String(match[1] || "").trim();
    const target = line.slice(start, end).trim();
    return `${name}|${target}`.trim();
  }).filter(Boolean);
}

export function newsSourceTypeLabel(type) {
  if (type === "bilibili") return "B站 UP";
  if (type === "bilibili_video") return "B站视频";
  return "新闻源";
}

export function newsSourcePlaceholder(type) {
  if (type === "bilibili") return "bilibili:UID 或空间链接";
  if (type === "bilibili_video") return "bvid:BV... 或视频链接";
  return "https://...rss.xml";
}

export function serializeNewsSources(items) {
  return items
    .filter((item) => item && String(item.target || "").trim())
    .map((item) => {
      const body = `${String(item.name || "").trim() || newsSourceTypeLabel(item.type)}|${String(item.target || "").trim()}`;
      return item.enabled === false ? `# ${body}` : body;
    })
    .join("\n");
}

export function newsSourceItemsFromDom() {
  return Array.from(document.querySelectorAll("[data-news-source-item]")).map((row) => ({
    enabled: Boolean(row.querySelector("[data-news-source-enabled]")?.checked),
    name: row.querySelector("[data-news-source-name]")?.value || "",
    type: row.querySelector("[data-news-source-type]")?.value || "rss",
    target: row.querySelector("[data-news-source-target]")?.value || "",
  }));
}

export function syncNewsSourcesRaw() {
  const raw = $("#newsSourcesRaw");
  const manager = $("#newsSourceManager");
  if (!raw || !manager) return;
  raw.value = serializeNewsSources(newsSourceItemsFromDom());
  markModuleFormDirty(raw.closest("form"));
}

export function renderNewsSourceManager(items = null) {
  const raw = $("#newsSourcesRaw");
  const manager = $("#newsSourceManager");
  if (!raw || !manager) return;
  const sources = items || parseNewsSources(raw.value);
  manager.innerHTML = `
    <div class="news-source-head">
      <div>
        <b>新闻源</b>
        <span>RSS/Atom、B 站 UP 主源或单条 B 站视频，最多读取前 12 个启用项。</span>
      </div>
      <div class="news-source-actions">
        <button type="button" data-news-source-add="rss">添加 RSS</button>
        <button type="button" data-news-source-add="bilibili">添加 B站 UP</button>
        <button type="button" data-news-source-add="bilibili_video">添加 B站视频</button>
        <button type="button" data-news-source-reset>恢复默认</button>
      </div>
    </div>
    <div class="news-source-list">
      ${sources.map((item, index) => `
        <article class="news-source-row" data-news-source-item="${index}">
          <label class="source-enable"><input type="checkbox" data-news-source-enabled ${item.enabled === false ? "" : "checked"} /> <span>${item.enabled === false ? "停用" : "启用"}</span></label>
          <input data-news-source-name type="text" value="${escapeHtml(item.name)}" placeholder="来源名称" />
          <select data-news-source-type>
            <option value="rss"${item.type === "rss" ? " selected" : ""}>RSS/Atom</option>
            <option value="bilibili"${item.type === "bilibili" ? " selected" : ""}>B站 UP</option>
            <option value="bilibili_video"${item.type === "bilibili_video" ? " selected" : ""}>B站视频</option>
          </select>
          <input data-news-source-target type="text" value="${escapeHtml(item.target)}" placeholder="${newsSourcePlaceholder(item.type)}" />
          <button type="button" data-news-source-remove="${index}">移除</button>
        </article>
      `).join("") || `<div class="empty small">还没有新闻源，可以添加 RSS、B 站 UP 主源或单条 B 站视频。</div>`}
    </div>
  `;
}

export function resetNewsSourcesToDefault() {
  const items = newsSourcePresets.map(([name, target]) => ({
    enabled: true,
    name,
    target,
    type: target.startsWith("bilibili:") ? "bilibili" : "rss",
  }));
  const raw = $("#newsSourcesRaw");
  if (raw) raw.value = serializeNewsSources(items);
  renderNewsSourceManager(items);
  syncNewsSourcesRaw();
}

export function decodeSegmentedWordToken(value) {
  const raw = String(value ?? "");
  const trimmed = raw.trim();
  const lower = trimmed.toLowerCase();
  if (["<space>", "{space}", "[space]", "\\s", "\\u0020", "空格"].includes(lower)) return " ";
  if (["<newline>", "{newline}", "[newline]", "\\n", "换行"].includes(lower)) return "\n";
  if (["<tab>", "{tab}", "[tab]", "\\t", "tab"].includes(lower)) return "\t";
  if (["<comma>", "{comma}", "[comma]", "comma", "英文逗号"].includes(lower)) return ",";
  if (["<zh_comma>", "{zh_comma}", "[zh_comma]", "zh_comma", "中文逗号", "逗号"].includes(lower)) return "，";
  return raw;
}

export function parseSegmentedWordList(value) {
  if (Array.isArray(value)) {
    return value.map(decodeSegmentedWordToken).filter((item) => item !== "");
  }
  const raw = String(value ?? "");
  const parts = raw.includes("\n") || raw.includes("\r")
    ? raw.split(/\r?\n/)
    : raw.split(/[,、]+/);
  return parts
    .map(decodeSegmentedWordToken)
    .filter((item) => item !== "");
}

export function decodeSegmentedReplacementToken(value, replacement = false) {
  const raw = String(value ?? "");
  const trimmed = raw.trim();
  const lower = trimmed.toLowerCase();
  const aliases = new Map([
    ["<space>", " "], ["{space}", " "], ["[space]", " "], ["空格", " "],
    ["<newline>", "\n"], ["{newline}", "\n"], ["[newline]", "\n"], ["换行", "\n"],
    ["<tab>", "\t"], ["{tab}", "\t"], ["[tab]", "\t"], ["tab", "\t"],
    ["<empty>", ""], ["{empty}", ""], ["[empty]", ""], ["空内容", ""], ["删除", ""],
  ]);
  if (aliases.has(lower) && (replacement || !["<empty>", "{empty}", "[empty]", "空内容", "删除"].includes(lower))) {
    return aliases.get(lower);
  }
  return trimmed.replace(/\\n/g, "\n").replace(/\\t/g, "\t");
}

export function parseSegmentedReplacementRules(value) {
  const rawRules = Array.isArray(value)
    ? value
    : String(value ?? "").split(/\r?\n/).filter((line) => line.trim());
  const pairs = [];
  rawRules.slice(0, 80).forEach((rawRule) => {
    let oldValue = "";
    let newValue = "";
    if (rawRule && typeof rawRule === "object") {
      oldValue = rawRule.from ?? rawRule.old ?? rawRule.source ?? "";
      newValue = rawRule.to ?? rawRule.new ?? rawRule.replacement ?? "";
    } else {
      const rule = String(rawRule ?? "");
      const separator = ["=>", "＝>", "→", "->"].find((item) => rule.includes(item));
      if (!separator) return;
      const separatorIndex = rule.indexOf(separator);
      oldValue = rule.slice(0, separatorIndex);
      newValue = rule.slice(separatorIndex + separator.length);
    }
    const oldText = decodeSegmentedReplacementToken(oldValue, false);
    const newText = decodeSegmentedReplacementToken(newValue, true);
    if (!oldText || oldText.length > 200 || newText.length > 500) return;
    pairs.push([oldText, newText]);
  });
  return pairs;
}

export function applySegmentedPreviewReplacements(value, rules) {
  const pairs = parseSegmentedReplacementRules(rules);
  const original = String(value || "");
  if (!pairs.length || !original) return [original, 0];
  const protectedPattern = /<(?:image|img|video|record|audio|file)\b[^>]*(?:>.*?<\/(?:image|img|video|record|audio|file)>|\/?>)|<tts\b[^>]*>.*?<\/tts>|<[^>\n]{1,240}\bpath="[^"]{1,500}"[^>\n]*>|<[^>\n]{1,240}\b(?:url|src)="[^"]{1,500}"[^>\n]*>|\b(?:https?:\/\/|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+/gis;
  let cursor = 0;
  let output = "";
  let replacementCount = 0;
  const replacePlain = (source) => {
    let next = String(source || "");
    pairs.forEach(([oldText, newText]) => {
      const count = Math.max(0, next.split(oldText).length - 1);
      if (!count) return;
      next = next.split(oldText).join(newText);
      replacementCount += count;
    });
    return next;
  };
  let match = null;
  while ((match = protectedPattern.exec(original)) !== null) {
    output += replacePlain(original.slice(cursor, match.index));
    output += match[0];
    cursor = match.index + match[0].length;
  }
  output += replacePlain(original.slice(cursor));
  return [output, replacementCount];
}

export function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function segmentedProtectedCleanupChunks(value) {
  const protectedPattern = /<(?:image|img|video|record|audio|file)\b[^>]*(?:>.*?<\/(?:image|img|video|record|audio|file)>|\/?>)|<tts\b[^>]*>.*?<\/tts>|<[^>\n]{1,240}\bpath="[^"]{1,500}"[^>\n]*>|<[^>\n]{1,240}\b(?:url|src)="[^"]{1,500}"[^>\n]*>|\b(?:https?:\/\/|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+/gis;
  const bracketPairs = { "(": ")", "（": "）", "[": "]", "【": "】", "{": "}", "「": "」", "『": "』", "《": "》" };
  const bracketOpeners = new Set(Object.keys(bracketPairs));
  const quotePairs = { "\"": "\"", "“": "”", "'": "'", "‘": "’" };
  const chunks = [];
  let current = "";
  let protectedChunk = false;
  const bracketStack = [];
  let quoteClose = "";
  const text = String(value || "");
  let lastIndex = 0;
  const flush = () => {
    if (current) chunks.push([current, protectedChunk]);
    current = "";
  };
  const feedPlain = (part) => [...String(part || "")].forEach((char) => {
    if (!protectedChunk && bracketOpeners.has(char)) {
      flush();
      protectedChunk = true;
      bracketStack.push(bracketPairs[char]);
      current += char;
      return;
    }
    if (!protectedChunk && quotePairs[char]) {
      flush();
      protectedChunk = true;
      quoteClose = quotePairs[char];
      current += char;
      return;
    }
    current += char;
    if (!protectedChunk) return;
    if (quoteClose) {
      if (char === quoteClose) {
        quoteClose = "";
        if (!bracketStack.length) {
          flush();
          protectedChunk = false;
        }
      }
      return;
    }
    if (bracketOpeners.has(char)) {
      bracketStack.push(bracketPairs[char]);
    } else if (bracketStack.length && char === bracketStack[bracketStack.length - 1]) {
      bracketStack.pop();
      if (!bracketStack.length) {
        flush();
        protectedChunk = false;
      }
    }
  });
  let match = null;
  while ((match = protectedPattern.exec(text)) !== null) {
    feedPlain(text.slice(lastIndex, match.index));
    flush();
    chunks.push([match[0], true]);
    lastIndex = match.index + match[0].length;
  }
  feedPlain(text.slice(lastIndex));
  flush();
  return chunks;
}

export function protectSegmentedUrls(value) {
  const replacements = {};
  const parts = segmentedProtectedCleanupChunks(value).map(([chunk, protectedChunk]) => {
    if (!protectedChunk) return chunk;
    const token = `PCSEGTOKEN${Object.keys(replacements).length}X`;
    replacements[token] = chunk;
    return token;
  });
  return [parts.join(""), replacements];
}

export function restoreSegmentedUrls(value, replacements) {
  let restored = String(value || "");
  Object.entries(replacements || {}).forEach(([token, original]) => {
    restored = restored.split(token).join(original);
  });
  return restored;
}

export function segmentedProtectedSplitWordCount(value, splitWords) {
  const words = Array.isArray(splitWords) ? splitWords.filter((item) => item !== "") : [];
  if (!words.length) return 0;
  let count = 0;
  segmentedProtectedCleanupChunks(value).forEach(([chunk, protectedChunk]) => {
    if (!protectedChunk) return;
    words.forEach((word) => {
      if (!word) return;
      count += Math.max(0, String(chunk).split(word).length - 1);
    });
  });
  return count;
}

export function splitSegmentedWordsOutsideProtected(value, splitWords) {
  const words = [...new Set((splitWords || []).filter((item) => item !== ""))]
    .sort((left, right) => right.length - left.length);
  if (!words.length) return [String(value || "")];
  const urlPattern = /^(?:https?:\/\/|www\.)/i;
  const protectedStartsWithSplitWord = (chunk) => {
    const stripped = String(chunk || "").trimStart();
    return words.some((word) => stripped.startsWith(word));
  };
  const segments = [];
  let current = "";
  const pushCurrent = () => {
    if (current) segments.push(current);
    current = "";
  };
  const feedPlain = (chunk) => {
    const text = String(chunk || "");
    let index = 0;
    while (index < text.length) {
      const matched = words.find((word) => text.startsWith(word, index));
      if (matched) {
        let delimiter = matched;
        if (matched === ".") {
          let end = index + matched.length;
          while (end < text.length && text[end] === ".") {
            delimiter += text[end];
            end += 1;
          }
          current += delimiter;
          pushCurrent();
          index = end;
          continue;
        }
        if (["…", "~", "～"].includes(matched)) {
          let end = index + matched.length;
          while (end < text.length && text.startsWith(matched, end)) {
            delimiter += matched;
            end += matched.length;
          }
          current += delimiter;
          pushCurrent();
          index = end;
          continue;
        }
        current += delimiter;
        pushCurrent();
        index += matched.length;
      } else {
        current += text[index];
        index += 1;
      }
    }
  };
  segmentedProtectedCleanupChunks(value).forEach(([chunk, protectedChunk]) => {
    if (protectedChunk) {
      if (current && protectedStartsWithSplitWord(chunk)) pushCurrent();
      current += chunk;
      if (urlPattern.test(String(chunk || "").trim())) pushCurrent();
    } else {
      feedPlain(chunk);
    }
  });
  pushCurrent();
  return segments;
}

export function segmentedVisibleLen(value) {
  return String(value || "").replace(/\s+/g, "").length;
}

export function segmentedIsSoftShort(value, minChars) {
  const cleaned = String(value || "").replace(/\s+/g, " ").trim();
  if (!cleaned) return false;
  const body = cleaned.replace(/[。！？!?…~～,.，、\s]+$/g, "");
  if (segmentedVisibleLen(cleaned) <= Math.max(1, minChars)) return true;
  if (/(?:\.{2,}|…{1,}|~{2,}|～{2,})$/.test(cleaned)) return false;
  return new Set(["哈哈", "哈", "嗯", "唔", "诶", "欸", "啊", "呀", "我也觉得", "确实", "真的", "对吧", "不是", "那个", "还有"]).has(body);
}

export function segmentedJoinPair(left, right) {
  const lhs = String(left || "").trim();
  const rhs = String(right || "").trim();
  if (!lhs) return rhs;
  if (!rhs) return lhs;
  if (/[！？!?]$/.test(lhs)) return `${lhs} ${rhs}`.trim();
  let softened = lhs.replace(/[。…~～]+$/g, "，").replace(/[!?！？]+$/g, "，");
  if (!/[，,、\s]$/.test(softened)) softened += "，";
  return `${softened}${rhs.replace(/^\s+/, "")}`;
}

export function segmentedControlValue(root, key) {
  const control = root?.querySelector?.(`[name="${key}"], [data-feature-param="${key}"], [data-feature-detail-toggle="${key}"]`);
  if (!control) {
    if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, key)) return toBool(state.featureDraft[key]);
    return state.overview?.settings?.[key];
  }
  if (control.type === "checkbox") return Boolean(control.checked);
  if (control.type === "number") return Number(control.value || 0);
  return control.value;
}

export function segmentedPreviewValues(root = document) {
  const settings = state.overview?.settings || {};
  const keys = [
    "enable_segmented_proactive_reply",
    "segmented_proactive_scope",
    "segmented_proactive_chat_scope",
    "segmented_proactive_threshold",
    "segmented_proactive_min_segment_chars",
    "segmented_proactive_max_segments",
    "segmented_proactive_send_as_forward",
    "segmented_proactive_split_mode",
    "segmented_proactive_regex",
    "segmented_proactive_split_words",
    "enable_segmented_proactive_content_cleanup",
    "segmented_proactive_content_cleanup_scope",
    "segmented_proactive_content_cleanup_rule",
    "segmented_proactive_content_cleanup_words",
    "enable_segmented_proactive_content_replacement",
    "segmented_proactive_content_replacements",
    "segmented_proactive_interval_method",
    "segmented_proactive_interval_min",
    "segmented_proactive_interval_max",
    "segmented_proactive_log_base",
  ];
  const values = {};
  keys.forEach((key) => {
    const value = segmentedControlValue(root, key);
    values[key] = value == null ? settings[key] : value;
  });
  values.enable_segmented_proactive_reply = toBool(values.enable_segmented_proactive_reply);
  values.segmented_proactive_send_as_forward = toBool(values.segmented_proactive_send_as_forward);
  values.enable_segmented_proactive_content_cleanup = toBool(values.enable_segmented_proactive_content_cleanup);
  values.enable_segmented_proactive_content_replacement = toBool(values.enable_segmented_proactive_content_replacement);
  values.segmented_proactive_content_cleanup_scope = String(values.segmented_proactive_content_cleanup_scope || "all");
  values.segmented_proactive_split_words = String(values.segmented_proactive_split_words ?? "");
  values.segmented_proactive_content_cleanup_words = String(values.segmented_proactive_content_cleanup_words ?? "");
  values.segmented_proactive_content_replacements = Array.isArray(values.segmented_proactive_content_replacements)
    ? values.segmented_proactive_content_replacements
    : String(values.segmented_proactive_content_replacements ?? "");
  return values;
}

export function simulateSegmentedProactive(text, values) {
  let normalized = String(text || "").trim();
  if (!normalized) return { segments: [], status: "请输入一段主动消息示例。" };
  if (!values.enable_segmented_proactive_reply) {
    return { segments: [normalized], status: "主动分段未开启，真实发送会保持一整条。" };
  }
  let replacementCount = 0;
  if (values.enable_segmented_proactive_content_replacement) {
    const [replaced, count] = applySegmentedPreviewReplacements(
      normalized,
      values.segmented_proactive_content_replacements,
    );
    if (count > 0 && replaced.trim()) {
      normalized = replaced.trim();
      replacementCount = count;
    }
  }
  const threshold = Math.max(20, Number(values.segmented_proactive_threshold || 500));
  if (normalized.length > threshold) {
    const replacementText = replacementCount ? `已完成 ${replacementCount} 处内容替换；` : "";
    return { segments: [normalized], status: `${replacementText}文本长度 ${normalized.length} 超过阈值 ${threshold}，真实发送不会分段。` };
  }
  const splitMode = String(values.segmented_proactive_split_mode || "regex");
  const scope = String(values.segmented_proactive_scope || "proactive_only");
  const chatScope = String(values.segmented_proactive_chat_scope || "all");
  const cleanupEnabled = Boolean(values.enable_segmented_proactive_content_cleanup);
  const cleanupScope = String(values.segmented_proactive_content_cleanup_scope || "all");
  const minChars = Math.max(1, Number(values.segmented_proactive_min_segment_chars || 8));
  const maxSegments = Math.max(1, Number(values.segmented_proactive_max_segments || 3));
  const cleanupWords = parseSegmentedWordList(values.segmented_proactive_content_cleanup_words);
  const [protectedNormalized, protectedUrls] = protectSegmentedUrls(normalized);
  let protectedSplitHits = 0;
  let cleanupRegex = null;
  if (cleanupEnabled && splitMode !== "words" && values.segmented_proactive_content_cleanup_rule) {
    cleanupRegex = new RegExp(String(values.segmented_proactive_content_cleanup_rule), "g");
  }
  const cleanSegment = (segment) => {
    const original = String(segment || "");
    let cleaned = "";
    const stripTrailingWords = (value, words) => {
      let next = String(value || "").trimEnd();
      const sortedWords = Array.from(new Set(words.filter((word) => word !== ""))).sort((a, b) => b.length - a.length);
      let changed = true;
      while (changed && next) {
        changed = false;
        for (const word of sortedWords) {
          if (next.endsWith(word)) {
            next = next.slice(0, -word.length).trimEnd();
            changed = true;
            break;
          }
        }
      }
      return next;
    };
    const stripTrailingRegex = (value, pattern) => {
      let next = String(value || "").trimEnd();
      if (!pattern) return next;
      let changed = true;
      while (changed && next) {
        changed = false;
        const matches = Array.from(next.matchAll(pattern));
        const trailing = matches.reverse().find((match) => match.index != null && match.index + match[0].length === next.length && match[0].length > 0);
        if (trailing) {
          next = next.slice(0, trailing.index).trimEnd();
          changed = true;
        }
      }
      return next;
    };
    segmentedProtectedCleanupChunks(original).forEach(([chunk, protectedChunk]) => {
      if (protectedChunk || !cleanupEnabled) {
        cleaned += chunk;
        return;
      }
      let next = chunk;
      if (splitMode === "words") {
        if (cleanupScope === "trailing") {
          next = stripTrailingWords(next, cleanupWords);
        } else {
          cleanupWords.forEach((word) => {
            if (word !== "") next = next.split(word).join("");
          });
        }
      } else if (cleanupRegex) {
        next = cleanupScope === "trailing" ? stripTrailingRegex(next, cleanupRegex) : next.replace(cleanupRegex, "");
      }
      cleaned += next;
    });
    return restoreSegmentedUrls(cleaned.trim(), protectedUrls);
  };
  let rawSegments = [];
  try {
    if (splitMode === "words") {
      const splitWords = parseSegmentedWordList(values.segmented_proactive_split_words);
      if (!splitWords.includes("\n")) splitWords.push("\n");
      if (!splitWords.length) return { segments: [normalized], status: "分段模式为 words，但分段词为空。" };
      protectedSplitHits = segmentedProtectedSplitWordCount(normalized, splitWords);
      rawSegments = splitSegmentedWordsOutsideProtected(normalized, splitWords);
    } else {
      const pattern = new RegExp(String(values.segmented_proactive_regex || ".*?[。？！~…\\n]+|.+$"), "gms");
      rawSegments = protectedNormalized.match(pattern) || [];
    }
  } catch (error) {
    return { segments: [normalized], error: `分段规则无法解析：${error.message}` };
  }
  let segments = rawSegments.map(cleanSegment).filter(Boolean);
  if (segments.length > 1) {
    const merged = [];
    let index = 0;
    while (index < segments.length) {
      let current = segments[index];
      while (
        index + 1 < segments.length &&
        (segmentedVisibleLen(current) < minChars || segmentedIsSoftShort(current, minChars) || merged.length >= Math.max(0, maxSegments - 1))
      ) {
        current = segmentedJoinPair(current, segments[index + 1]);
        index += 1;
      }
      if (merged.length && (segmentedVisibleLen(current) < minChars || segmentedIsSoftShort(current, minChars))) {
        merged[merged.length - 1] = segmentedJoinPair(merged[merged.length - 1], current);
      } else {
        merged.push(current);
      }
      index += 1;
    }
    if (merged.length > maxSegments) {
      const kept = merged.slice(0, maxSegments - 1);
      let tail = merged[maxSegments - 1];
      merged.slice(maxSegments).forEach((item) => {
        tail = segmentedJoinPair(tail, item);
      });
      segments = kept.concat(tail);
    } else {
      segments = merged;
    }
  }
  if (!segments.length || (segments.length <= 1 && !cleanupEnabled)) {
    return { segments: [normalized], status: "当前规则没有产生有效分段，真实发送会保持一整条。" };
  }
  const scopeText = scope === "all_llm" ? "插件主动与普通 LLM 纯文本回复都会使用此规则" : "仅插件主动消息使用此规则";
  const chatScopeText = chatScope === "private" ? "；仅私聊生效" : chatScope === "group" ? "；仅群聊生效" : "";
  const sendText = values.segmented_proactive_send_as_forward && segments.length > 1 ? "；真实发送会优先打包成合并消息" : "";
  const protectedText = protectedSplitHits ? `；${protectedSplitHits} 个分隔符位于括号/引号/网址内，已按保护规则跳过` : "";
  const replacementText = replacementCount ? `；已完成 ${replacementCount} 处内容替换` : "";
  return { segments, status: `预计发送 ${segments.length} 段；${scopeText}${chatScopeText}${sendText}${protectedText}${replacementText}。` };
}

export function segmentedPreviewPanelHtml() {
  return `
    <section class="segmented-preview-panel wide-field" data-segmented-preview-panel>
      <header>
        <div>
          <h4>分段效果预览</h4>
        </div>
        <div class="segmented-preview-actions">
          <button type="button" data-segmented-example="simple">简单示例</button>
          <button type="button" data-segmented-example="complex">复杂示例</button>
        </div>
      </header>
      <textarea data-segmented-preview-input rows="4"></textarea>
      <div data-segmented-preview-output class="segmented-preview-output"></div>
    </section>
  `;
}

export function renderSegmentedPreview(panel = null) {
  const targetPanels = panel ? [panel] : Array.from(document.querySelectorAll("[data-segmented-preview-panel], .segmented-preview-panel"));
  targetPanels.forEach((previewPanel) => {
    const input = previewPanel.querySelector("[data-segmented-preview-input], #segmentedPreviewInput");
    const output = previewPanel.querySelector("[data-segmented-preview-output], #segmentedPreviewOutput");
    if (!input || !output) return;
    const root = previewPanel.closest("[data-feature-param-form]") || document;
    if (!input.value) input.value = segmentedPreviewExamples.simple;
    let result;
    try {
      result = simulateSegmentedProactive(input.value, segmentedPreviewValues(root));
    } catch (error) {
      result = { segments: [], error: error.message };
    }
    if (result.error) {
      output.innerHTML = `<div class="segmented-preview-error">${escapeHtml(result.error)}</div>`;
      return;
    }
    const segments = result.segments || [];
    output.innerHTML = `
      <div class="segmented-preview-summary">
        <span>${escapeHtml(result.status || "")}</span>
        <span>原文 ${escapeHtml(String(input.value || "").length)} 字</span>
        <span>保护：网址内部不拆，链接结束可断；括号 / 双引号内部不拆</span>
        <span>空格可写作 &lt;space&gt; 或 空格</span>
      </div>
      <div class="segmented-preview-list">
        ${segments.map((segment, index) => `
          <section class="segmented-preview-segment">
            <b>${escapeHtml(index + 1)}</b>
            <p>${escapeHtml(segment)}</p>
          </section>
        `).join("")}
      </div>
    `;
  });
}

export function segmentedConfigControlShell(control) {
  return control?.closest?.(".feature-param-row, label, .toggle-row") || null;
}

export function updateSegmentedConfigVisibility(root = document) {
  const values = segmentedPreviewValues(root);
  const mode = String(values.segmented_proactive_split_mode || "regex");
  const cleanupEnabled = Boolean(values.enable_segmented_proactive_content_cleanup);
  const intervalMethod = String(values.segmented_proactive_interval_method || "log");
  const visibility = {
    segmented_proactive_regex: mode === "regex",
    segmented_proactive_split_words: mode === "words",
    segmented_proactive_content_cleanup_scope: cleanupEnabled,
    segmented_proactive_content_cleanup_rule: cleanupEnabled && mode === "regex",
    segmented_proactive_content_cleanup_words: cleanupEnabled && mode === "words",
    segmented_proactive_content_replacements: Boolean(values.enable_segmented_proactive_content_replacement),
    segmented_proactive_interval_min: intervalMethod === "random",
    segmented_proactive_interval_max: intervalMethod === "random",
    segmented_proactive_log_base: intervalMethod === "log",
  };
  Object.entries(visibility).forEach(([key, visible]) => {
    root.querySelectorAll(`[name="${key}"], [data-feature-param="${key}"]`).forEach((control) => {
      const shell = segmentedConfigControlShell(control);
      if (shell) shell.classList.toggle("segmented-config-hidden", !visible);
    });
  });
}

export function bindSegmentedPreview(root = document) {
  const scope = root || document;
  scope.querySelectorAll("[data-segmented-preview-panel], .segmented-preview-panel").forEach((panel) => {
    const input = panel.querySelector("[data-segmented-preview-input], #segmentedPreviewInput");
    if (input && !input.dataset.segmentedPreviewBound) {
      input.dataset.segmentedPreviewBound = "1";
      input.addEventListener("input", () => renderSegmentedPreview(panel));
    }
    panel.querySelectorAll("[data-segmented-example]").forEach((button) => {
      if (button.dataset.segmentedPreviewBound) return;
      button.dataset.segmentedPreviewBound = "1";
      button.addEventListener("click", () => {
        if (!input) return;
        input.value = segmentedPreviewExamples[button.dataset.segmentedExample] || segmentedPreviewExamples.simple;
        renderSegmentedPreview(panel);
      });
    });
  });
  const controls = scope.querySelectorAll('[name^="segmented_proactive_"], [name="enable_segmented_proactive_reply"], [name="enable_segmented_proactive_content_cleanup"], [name="enable_segmented_proactive_content_replacement"], [data-feature-param^="segmented_proactive_"], [data-feature-param="enable_segmented_proactive_content_cleanup"], [data-feature-param="enable_segmented_proactive_content_replacement"], [data-feature-detail-toggle="enable_segmented_proactive_reply"]');
  controls.forEach((control) => {
    if (control.dataset.segmentedConfigBound) return;
    control.dataset.segmentedConfigBound = "1";
    const handler = () => {
      const owner = control.closest("[data-feature-param-form]") || scope;
      updateSegmentedConfigVisibility(owner);
      renderSegmentedPreview();
    };
    control.addEventListener("input", handler);
    control.addEventListener("change", handler);
  });
  scope.querySelectorAll("[data-feature-param-form]").forEach((form) => updateSegmentedConfigVisibility(form));
  renderSegmentedPreview();
}

export function normalizeGroupIdList(value) {
  const source = Array.isArray(value) ? value.join("\n") : String(value || "");
  const seen = new Set();
  return source
    .split(/[\s,，;；、]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      if (seen.has(item)) return false;
      seen.add(item);
      return true;
    });
}

export function accessDraftFromForm(group = {}) {
  const whitelistInput = $("#groupWhitelist");
  const blacklistInput = $("#groupBlacklist");
  return {
    mode: $("#groupAccessMode")?.value || group.access_mode || "whitelist",
    whitelist: new Set(normalizeGroupIdList(whitelistInput ? whitelistInput.value : group.whitelist || [])),
    blacklist: new Set(normalizeGroupIdList(blacklistInput ? blacklistInput.value : group.blacklist || [])),
  };
}

export function writeAccessDraft(draft) {
  $("#groupAccessMode").value = draft.mode || "whitelist";
  $("#groupWhitelist").value = [...draft.whitelist].join("\n");
  $("#groupBlacklist").value = [...draft.blacklist].join("\n");
}

export function groupAllowedByDraft(groupId, draft) {
  const id = String(groupId || "");
  return draft.mode === "blacklist" ? !draft.blacklist.has(id) : draft.whitelist.has(id);
}

export function groupListMark(groupId, draft) {
  const id = String(groupId || "");
  if (draft.whitelist.has(id) && draft.blacklist.has(id)) return "白名单 + 黑名单";
  if (draft.whitelist.has(id)) return "白名单";
  if (draft.blacklist.has(id)) return "黑名单";
  return "未列入";
}

export function renderAccessManager(group) {
  const draft = accessDraftFromForm(group);
  const mode = draft.mode === "blacklist" ? "blacklist" : "whitelist";
  $("#groupAccessMode").value = mode;
  document.querySelectorAll("[name='groupAccessModeChoice']").forEach((input) => {
    input.checked = input.value === mode;
  });

  const knownGroups = state.groups || [];
  const allowedCount = knownGroups.filter((item) => groupAllowedByDraft(item.group_id, draft)).length;
  const blockedCount = Math.max(0, knownGroups.length - allowedCount);
  const warning = mode === "whitelist" && draft.whitelist.size === 0
    ? "白名单为空"
    : mode === "blacklist" && draft.blacklist.size === 0
      ? "未拦截群"
      : "已配置";
  $("#accessSummary").innerHTML = `
    <section class="access-summary-card ${mode}">
      <span>当前模式</span>
      <b>${escapeHtml(mode === "blacklist" ? "黑名单" : "白名单")}</b>
      <small>${escapeHtml(warning)}</small>
    </section>
    <section class="access-summary-card ok">
      <span>允许群</span>
      <b>${escapeHtml(allowedCount)}</b>
      <small>已记录群</small>
    </section>
    <section class="access-summary-card blocked">
      <span>拦截群</span>
      <b>${escapeHtml(blockedCount)}</b>
      <small>已记录群</small>
    </section>
    <section class="access-summary-card">
      <span>名单规模</span>
      <b>${escapeHtml(draft.whitelist.size)} / ${escapeHtml(draft.blacklist.size)}</b>
      <small>白名单 / 黑名单</small>
    </section>
  `;

  $("#accessQuickGroups").innerHTML = knownGroups.length
    ? knownGroups.map((item) => {
      const groupId = String(item.group_id || "");
      const inWhite = draft.whitelist.has(groupId);
      const inBlack = draft.blacklist.has(groupId);
      const allowed = groupAllowedByDraft(groupId, draft);
      return `
        <section class="access-group-card ${allowed ? "ok" : "blocked"}">
          <div>
            <b>${escapeHtml(groupId)}</b>
            <span>${escapeHtml(allowed ? "允许" : "拦截")} · ${escapeHtml(groupListMark(groupId, draft))}</span>
            <small>消息 ${escapeHtml(item.message_count || 0)} · 最近 ${escapeHtml(item.last_seen || "未知")}</small>
          </div>
          <div class="access-group-actions">
            <button type="button" data-access-action="white" data-access-group="${escapeHtml(groupId)}">${escapeHtml(inWhite ? "移出白名单" : "加入白名单")}</button>
            <button type="button" data-access-action="black" data-access-group="${escapeHtml(groupId)}">${escapeHtml(inBlack ? "移出黑名单" : "加入黑名单")}</button>
          </div>
        </section>
      `;
    }).join("")
    : `<div class="empty small">暂无群聊记录</div>`;

  renderListCoverage(group, draft);
}

export function renderListCoverage(group, draft = null) {
  const access = draft || {
    mode: group.access_mode || "whitelist",
    whitelist: new Set(normalizeGroupIdList(group.whitelist || [])),
    blacklist: new Set(normalizeGroupIdList(group.blacklist || [])),
  };
  const rows = state.groups.map((item) => {
    const groupId = String(item.group_id || "");
    const allowed = groupAllowedByDraft(groupId, access);
    return `
      <div class="coverage-item ${allowed ? "ok" : "blocked"}">
        <b>${escapeHtml(groupId)}</b>
        <span>${escapeHtml(allowed ? "允许" : "拦截")} · ${escapeHtml(groupListMark(groupId, access))}</span>
      </div>
    `;
  });
  $("#listCoverage").innerHTML = rows.length ? rows.join("") : `<div class="empty small">暂无群聊记录</div>`;
}

export function renderFeatureSwitches() {
  const expandedGroups = new Set([...document.querySelectorAll('#featureFlags details[data-feature-group][open]')].map((item) => item.dataset.featureGroup));
  const filter = ($("#featureFilter")?.value || "").trim().toLowerCase();
  renderProactiveOnlyModeCard();
  renderPassiveInjectionPositionForm();
  const knownKeys = new Set(featureGroups.flatMap((group) => group.keys));
  const extraKeys = Object.keys(state.featureDraft || {}).filter((key) => !knownKeys.has(key) && visibleFeatureSwitchKey(key));
  const groups = extraKeys.length
    ? [...featureGroups, { title: "其他", note: "来自配置但暂未归入固定分组的开关。", keys: extraKeys }]
    : featureGroups;
  const overviewSettings = state.overview?.settings || {};
  const intensity = state.overview?.proactive_intensity || {};
  const intensitySearchText = "主动强度预设 主动触达 proactive_intensity_preset 私聊主动 群聊唤醒 群主动插话";
  const intensityVisible = !filter || intensitySearchText.toLowerCase().includes(filter);
  const visibleDraftKeys = visibleTopLevelFeatureKeys(state.featureDraft || {});
  const total = visibleDraftKeys.length;
  const enabled = visibleDraftKeys.filter((key) => toBool(state.featureDraft[key])).length;
  const proactiveLocked = visibleDraftKeys.filter((key) => featureLockedByProactiveOnlyMode(key)).length;
  const riskyEnabled = ["enable_group_interjection", "enable_bilibili_boredom_watch", isPrivateReadingAvailable() ? "enable_private_reading_boredom_read" : "", isPrivateReadingAvailable() ? "enable_private_reading_ask_recommendation" : "", "enable_unanswered_screen_peek_followup"]
    .filter((key) => toBool(state.featureDraft[key])).length;
  const activeSafeFeatureKeys = safeFeatureKeys.filter((key) => !featureLockedByProactiveOnlyMode(key));
  $("#featureSwitchSummary").innerHTML = `
    <section class="feature-summary-card ok">
      <span>已开启</span>
      <b>${escapeHtml(enabled)} / ${escapeHtml(total)}</b>
      <small>当前主开关</small>
    </section>
    <section class="feature-summary-card">
      <span>基础安全项</span>
      <b>${escapeHtml(activeSafeFeatureKeys.filter((key) => toBool(state.featureDraft[key])).length)} / ${escapeHtml(activeSafeFeatureKeys.length)}</b>
      <small>${escapeHtml(proactiveOnlyModeEnabled() ? "已排除模式锁定项" : "隐私、记忆、回复稳定性")}</small>
    </section>
    <section class="feature-summary-card ${riskyEnabled ? "warn" : ""}">
      <span>${escapeHtml(proactiveOnlyModeEnabled() ? "模式锁定" : "高主动子项")}</span>
      <b>${escapeHtml(proactiveOnlyModeEnabled() ? proactiveLocked : riskyEnabled)}</b>
      <small>${escapeHtml(proactiveOnlyModeEnabled() ? "被动能力已关闭" : "含详情页子开关")}</small>
    </section>
  `;

  if (embeddedFeatureParentByKey[state.selectedFeatureKey]) {
    state.selectedFeatureKey = embeddedFeatureParentByKey[state.selectedFeatureKey];
  }
  if (state.selectedFeatureKey && state.selectedFeatureKey !== "enable_proactive_only_mode" && !visibleFeatureSwitchKey(state.selectedFeatureKey)) {
    state.selectedFeatureKey = "";
  }
  syncFeatureFooterAction();
  if (state.selectedFeatureKey && Object.prototype.hasOwnProperty.call(state.featureDraft, state.selectedFeatureKey)) {
    $("#featureFlags").innerHTML = featureDetailPage(state.selectedFeatureKey);
    bindFeatureDetailActions();
    return;
  }

  const board = groups.map((group) => {
    const visibleKeys = group.keys.filter((key) => {
      if (!visibleFeatureSwitchKey(key)) return false;
      if (!filter) return true;
      return featureSearchText(key).includes(filter);
    });
    const hasIntensityCard = group.title === "通用能力" && intensityVisible;
    if (!visibleKeys.length && !hasIntensityCard) return "";
    const groupEnabled = visibleKeys.filter((key) => toBool(state.featureDraft[key])).length;
    const groupMeta = visibleKeys.length ? `${groupEnabled} / ${visibleKeys.length}` : "设置项";
    const prefix = hasIntensityCard
      ? proactiveIntensityCommonSettingCard(overviewSettings, intensity)
      : "";
    return `
      <details class="feature-switch-group aw-feature-group" data-feature-group="${escapeHtml(group.title)}"${filter || expandedGroups.has(group.title) ? " open" : ""}>
        <summary>
          <div>
            <b>${escapeHtml(group.title)}</b>
          </div>
          <small>${escapeHtml(groupMeta)}</small>
        </summary>
        <div class="feature-switch-list">
          ${prefix}
          ${visibleKeys.map((key) => featureSwitchItem(key)).join("")}
        </div>
      </details>
    `;
  }).filter(Boolean).join("");
  $("#featureFlags").innerHTML = board || `<div class="empty small">没有匹配的功能开关</div>`;
  document.querySelectorAll("[data-feature-key]").forEach((input) => {
    input.addEventListener("change", () => {
      state.featureDraft[input.dataset.featureKey] = input.checked;
      renderFeatureSwitches();
    });
  });
  document.querySelectorAll("[data-feature-open]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedFeatureKey = button.dataset.featureOpen || "";
      renderFeatureSwitches();
    });
  });
  bindProactiveOnlyTempUnlockActions($("#featureFlags"));
  bindProactiveIntensityCommonSetting();
}

export function proactiveIntensityCommonSettingCard(settings = {}, intensity = {}) {
  const current = String(settings.proactive_intensity_preset || intensity.preset || "off");
  const enabled = Boolean(intensity?.enabled);
  const effective = intensity?.effective || {};
  const interestProbability = Math.round(Number(effective.group_wakeup_interest_probability || 0) * 100);
  const maxDailyText = effective.max_daily_messages_text || formatProactiveLimit(effective.max_daily_messages, effective.max_daily_messages_unlimited);
  const interjectLimitText = effective.group_interject_max_daily_text || formatProactiveLimit(effective.group_interject_max_daily, effective.group_interject_max_daily_unlimited);
  const detail = enabled
    ? `当前有效：私聊 ${formatProactiveDailyQuota(effective.max_daily_messages, effective.max_daily_messages_unlimited, maxDailyText)}，空闲 ${effective.idle_minutes ?? "-"} 分钟，群唤醒冷却 ${effective.group_wakeup_cooldown_seconds ?? "-"} 秒，兴趣唤醒 ${interestProbability}%，群插话间隔 ${effective.group_interject_min_interval_minutes ?? "-"} 分钟，群插话上限 ${interjectLimitText}${effective.ignore_token_soft_limit ? "；最高档忽略 Token 软限额降载" : ""}。`
    : "关闭时完全沿用手动参数，不改变私聊、群聊唤醒或群主动插话频率。";
  return `
    <section class="feature-switch-item feature-setting-inline ${enabled ? "on" : "off"}">
      <div class="feature-switch-body">
        <button type="button" class="feature-switch-text" data-jump-tab="troubleshooting">
          <b>主动强度预设</b>
          <small>proactive_intensity_preset</small>
        </button>
        <div class="feature-switch-meta">
          <span class="feature-state-text">${escapeHtml(enabled ? (intensity.label || current) : "关闭：手动参数")}</span>
          <span class="feature-lock-note">影响私聊主动、群聊唤醒和群主动插话；排障页会显示当前覆盖项。</span>
        </div>
        <div class="feature-lock-related">${escapeHtml(detail)}</div>
      </div>
      <form class="feature-inline-setting-form" data-proactive-intensity-form>
        <select name="proactive_intensity_preset">
          ${[
            ["off", "关闭：手动参数"],
            ["balanced", "标准偏主动"],
            ["high_private", "私聊高频"],
            ["high_group", "群聊活跃"],
            ["live", "在线陪伴：不省成本"],
          ].map(([value, label]) => `<option value="${escapeHtml(value)}"${current === value ? " selected" : ""}>${escapeHtml(label)}</option>`).join("")}
        </select>
        <button type="submit">保存</button>
      </form>
    </section>
  `;
}

export function bindProactiveIntensityCommonSetting() {
  document.querySelectorAll("[data-proactive-intensity-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const value = form.querySelector('[name="proactive_intensity_preset"]')?.value || "off";
      await runAction(
        () => postJson("/settings/update", { settings: { proactive_intensity_preset: value } }),
        "已保存主动强度预设",
        form.querySelector("button[type='submit']"),
      );
    });
  });
}

export function syncFeatureFooterAction() {
  const button = $("#saveFeaturesBtn");
  if (!button) return;
  const inDetail = Boolean(state.selectedFeatureKey && Object.prototype.hasOwnProperty.call(state.featureDraft || {}, state.selectedFeatureKey));
  button.textContent = inDetail ? "返回功能列表" : "保存功能开关";
  button.dataset.action = inDetail ? "back" : "save";
}

export function renderProactiveOnlyModeCard() {
  const root = $("#proactiveOnlyModeCard");
  if (!root) return;
  const key = "enable_proactive_only_mode";
  const checked = toBool(state.featureDraft[key]);
  const proactiveChat = state.overview?.proactive_chat || {};
  const proactiveChatState = proactiveChat.enabled
    ? (proactiveChat.runtime_mode_label || (proactiveChat.installed ? "发送前兼容" : "等待运行实例"))
    : "联动已关闭";
  const proactiveChatTone = proactiveChat.deep_active ? "on" : proactiveChat.installed ? "paused" : "off";
  const proactiveRuntimeVersion = String(proactiveChat.runtime_version || "未知").replace(/^v/i, "");
  const proactiveRuntimeMeta = proactiveChat.deep_active
    ? `v${proactiveRuntimeVersion} · 已接管 ${Number(proactiveChat.runtime_method_count || 0)} 个关键方法`
    : (proactiveChat.runtime_last_error || proactiveChat.runtime_last_event || "");
  const settings = state.overview?.settings || {};
  const injectionPosition = String(settings.passive_injection_position || "prompt");
  root.innerHTML = `
    <div class="proactive-mode-stack">
      <div class="proactive-mode-settings-row">
        <section class="proactive-mode-card ${checked ? "on" : "off"}">
          <label class="feature-toggle-hit proactive-mode-toggle" aria-label="${escapeHtml(featureLabel(key))}">
            <input type="checkbox" data-proactive-only-mode-toggle ${checked ? "checked" : ""}>
            <span class="feature-toggle-visual"></span>
          </label>
          <div class="proactive-mode-main">
            <div class="proactive-mode-heading-row">
              <div class="proactive-mode-kicker">兼容与隔离</div>
              <span class="proactive-chat-status ${escapeHtml(proactiveChatTone)}">Proactive Chat · ${escapeHtml(proactiveChatState)}</span>
            </div>
            <h3>${escapeHtml(featureLabel(key))}</h3>
            <p>只让本插件负责主动私聊调度、生成和发送；普通私聊/群聊放行给 AstrBot 默认主链或其他插件。</p>
            ${proactiveRuntimeMeta ? `<small class="proactive-mode-runtime">${escapeHtml(proactiveRuntimeMeta)}</small>` : ""}
            <small class="proactive-mode-code">${escapeHtml(key)}</small>
          </div>
          <button type="button" class="proactive-mode-detail proactive-mode-button soft" data-feature-open="${escapeHtml(key)}">查看说明</button>
        </section>
      </div>
    </div>
  `;
  root.querySelector("[data-proactive-only-mode-toggle]")?.addEventListener("change", (event) => {
    state.featureDraft[key] = Boolean(event.target.checked);
    renderFeatureSwitches();
  });
  root.querySelector("[data-feature-open]")?.addEventListener("click", () => {
    state.selectedFeatureKey = key;
    renderFeatureSwitches();
  });

}

export function renderPassiveInjectionPositionForm() {
  const form = $("#passiveInjectionPositionForm");
  if (!form) return;
  const settings = state.overview?.settings || {};
  const select = form.querySelector('[name="passive_injection_position"]');
  if (select) select.value = String(settings.passive_injection_position || "prompt");
  if (form.dataset.bound) return;
  form.dataset.bound = "1";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = form.querySelector('[name="passive_injection_position"]')?.value || "prompt";
    await runAction(
      () => postJson("/settings/update", { settings: { passive_injection_position: value } }),
      "已保存动态提示词注入位置",
      form.querySelector("button[type='submit']"),
    );
  });
}

export function featureSwitchItem(key) {
  const checked = toBool(state.featureDraft[key]);
  const locked = featureLockedByProactiveOnlyMode(key);
  const tempUnlocked = featureTemporarilyUnlockedByProactiveOnly(key);
  const displayOn = checked || tempUnlocked;
  const related = proactiveOnlyRelatedUnlocks(key);
  const stateText = locked ? (tempUnlocked ? "临时放行" : "已锁定") : checked ? "开启" : "关闭";
  const lockNote = tempUnlocked ? "已临时放行，关闭仅保留主动能力后清空" : "仅保留主动能力中，原配置保留";
  const relatedText = related.length ? `建议同步：${related.map((item) => item.label || item.key).join("、")}` : "";
  return `
    <section class="feature-switch-item ${displayOn ? "on" : "off"} ${locked ? "locked" : ""}" title="${escapeHtml(locked ? "仅保留主动能力开启时，本功能在本插件普通被动链路中被跳过，原配置会保留。" : featureDescription(key))}">
      <label class="feature-toggle-hit" aria-label="${escapeHtml(featureLabel(key))}">
        <input type="checkbox" data-feature-key="${escapeHtml(key)}" ${displayOn ? "checked" : ""} ${locked ? "disabled" : ""}>
        <span class="feature-toggle-visual"></span>
      </label>
      <div class="feature-switch-body">
        <button type="button" class="feature-switch-text" data-feature-open="${escapeHtml(key)}">
          <b>${escapeHtml(featureLabel(key))}</b>
          <small>${escapeHtml(featurePublicKey(key))}</small>
        </button>
        <div class="feature-switch-meta">
          <span class="feature-state-text">${escapeHtml(stateText)}</span>
          ${locked ? `<span class="feature-lock-note">${escapeHtml(lockNote)}</span>` : ""}
        </div>
        ${locked && relatedText ? `<div class="feature-lock-related">${escapeHtml(relatedText)}</div>` : ""}
      </div>
      ${locked ? `<button type="button" class="feature-temp-unlock-btn" data-proactive-temp-unlock="${escapeHtml(key)}" data-action="${tempUnlocked ? "clear" : "unlock"}">${escapeHtml(tempUnlocked ? "取消放行" : "临时放行")}</button>` : ""}
    </section>
  `;
}

export function featureGroupForKey(key) {
  if (key === "enable_proactive_only_mode") return "兼容与隔离";
  const parentKey = topLevelFeatureKey(key);
  const group = featureGroups.find((item) => item.keys.includes(parentKey));
  return group ? group.title : "其他";
}

export function featureRelatedSettings(key) {
  const settings = state.overview?.settings || {};
  const providers = state.overview?.providers || {};
  const keys = featureSettingGroups[key] || [];
  const fallbackValue = (name) => {
    const defaults = {
      inbound_message_debounce_seconds: 3,
      text_message_debounce_seconds: 8,
      image_message_debounce_seconds: 8,
      forward_message_debounce_seconds: 0,
      text_message_debounce_max_wait_seconds: 12,
      message_debounce_max_merge_messages: 8,
      enable_smart_message_debounce: false,
      SMART_MESSAGE_DEBOUNCE_PROVIDER_ID: "",
      enable_smart_silence: true,
      smart_silence_judge_mode: "boundary_only",
      SMART_SILENCE_PROVIDER_ID: "",
      smart_silence_min_confidence: 0.66,
      smart_silence_model_timeout_seconds: 1.2,
      smart_message_debounce_model_timeout_seconds: 0.8,
      smart_message_debounce_wait_seconds: 3,
      smart_message_debounce_learning_window_seconds: 8,
      smart_message_debounce_examples_limit: 8,
      tts_generation_mode: "fast_tag",
      tts_voice_language: "ja",
      tts_fishaudio_model: "auto",
      tts_delivery_mode: "voice_and_text",
      tts_foreign_text_mode: "translation",
      tts_conversion_scope: "partial",
      tts_conversion_provider_id: "",
      tts_extra_prompt: "",
      tts_frequency_control_mode: "global",
      tts_constraint_mode: "weak",
      tts_session_min_interval_seconds: 120,
      tts_private_min_interval_seconds: -1,
      tts_group_min_interval_seconds: -1,
      tts_trigger_probability: 25,
      tts_private_trigger_probability: -1,
      tts_group_trigger_probability: -1,
      enable_tts_local_playback: false,
      enable_tts_local_playback_live_only: false,
      tts_local_playback_volume: 35,
      tts_local_playback_min_interval_seconds: 0,
      enable_tts_live_subtitle_sync: false,
      tts_live_subtitle_url: "",
      auto_voice_enabled: true,
      tts_conversion_scope: "full",
      auto_voice_max_chars: 80,
      auto_voice_probability: 20,
      auto_voice_cooldown_seconds: 180,
      main_user_voice_probability: 0,
      main_user_mention_voice_keywords: "",
      main_user_mention_voice_probability: 0,
      main_user_mention_voice_prompt: "",
    };
    return Object.prototype.hasOwnProperty.call(defaults, name) ? defaults[name] : undefined;
  };
  return keys
    .filter((item) => visibleConfigKey(item))
    .filter((item) => featureSettingVisibleForCurrentMode(key, item, settings))
    .filter((item) => (
      Object.prototype.hasOwnProperty.call(settings, item)
      || Object.prototype.hasOwnProperty.call(providers, item)
      || Object.prototype.hasOwnProperty.call(state.featureDraft || {}, item)
      || fallbackValue(item) !== undefined
    ))
    .map((item) => ({
      key: item,
      value: Object.prototype.hasOwnProperty.call(state.featureDraft || {}, item)
        ? state.featureDraft[item]
        : Object.prototype.hasOwnProperty.call(settings, item)
          ? settings[item]
          : Object.prototype.hasOwnProperty.call(providers, item)
            ? providers[item]
            : fallbackValue(item),
      feature: Object.prototype.hasOwnProperty.call(state.featureDraft || {}, item),
      description: configDescription(item),
    }));
}

export function featureSettingVisibleForCurrentMode(featureKey, settingKey, settings = state.overview?.settings || {}) {
  const boolSetting = (name) => {
    if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, name)) return Boolean(state.featureDraft[name]);
    return toBool(settings[name]);
  };
  const valueSetting = (name, fallback = "") => {
    if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, name)) return state.featureDraft[name];
    return Object.prototype.hasOwnProperty.call(settings, name) ? settings[name] : fallback;
  };
  if (featureKey === "enable_livingmemory_integration") {
    const livingmemory = state.overview?.livingmemory || {};
    const memoryCompanionActive = Boolean(livingmemory.memory_companion_active);
    const livingmemoryAvailable = Boolean(livingmemory.available);
    const companionOnlyKeys = new Set([
      "memory_companion_context_timeout_seconds",
      "enable_memory_companion_emotional_drift",
      "enable_memory_companion_cross_window_emotion",
      "enable_memory_companion_dream_fragment",
      "enable_memory_companion_open_loop_search",
      "enable_memory_companion_feature_context",
      "enable_memory_companion_private_recall",
      "memory_companion_context_top_k",
      "memory_companion_context_max_chars",
    ]);
    if (settingKey === "livingmemory_tool_name" && !livingmemoryAvailable) return false;
    if (companionOnlyKeys.has(settingKey) && !memoryCompanionActive) return false;
    if (settingKey === "enable_memory_companion_cross_window_emotion" && !boolSetting("enable_memory_companion_emotional_drift")) return false;
    if (["enable_memory_companion_private_recall", "memory_companion_context_top_k", "memory_companion_context_max_chars"].includes(settingKey) && !boolSetting("enable_memory_companion_feature_context")) return false;
  }
  if (featureKey === "enable_proactive_only_mode") {
    if (settingKey === "proactive_prompt_template") return boolSetting("enable_llm_proactive_message");
    if (["proactive_chat_bridge_review_mode", "proactive_chat_bridge_collision_window_seconds"].includes(settingKey)) return boolSetting("enable_proactive_chat_integration");
    if (["PROACTIVE_PERSONA_JUDGE_PROVIDER_ID", "proactive_persona_judge_send_threshold", "proactive_persona_judge_cache_minutes", "proactive_persona_judge_max_daily"].includes(settingKey)) {
      return boolSetting("enable_llm_proactive_persona_judge");
    }
    return true;
  }
  if (featureKey === "enable_humanized_states") {
    const dailyPlanChildren = new Set([
      "daily_plan_time",
      "daily_plan_item_count",
      "include_schedule_in_messages",
      "enable_detail_enhancement",
      "detail_enhancement_lead_minutes",
      "daily_plan_prompt",
    ]);
    const diaryChildren = new Set(["daily_diary_time", "daily_diary_form", "daily_diary_length", "daily_diary_creativity", "daily_diary_custom_direction", "daily_diary_generate_share_seed", "max_diary_entries"]);
    if (dailyPlanChildren.has(settingKey) && !boolSetting("enable_daily_plan")) return false;
    if (settingKey === "detail_enhancement_lead_minutes" && !boolSetting("enable_detail_enhancement")) return false;
    if (diaryChildren.has(settingKey) && !boolSetting("enable_daily_diary")) return false;
    if (settingKey === "greeting_idle_minutes" && !boolSetting("enable_daily_greetings")) return false;
    const dreamChildren = new Set(["dream_afterglow_mode", "enable_mixed_dream_themes", "enable_intimate_dream_theme", "dream_theme_candidates"]);
    if (dreamChildren.has(settingKey) && !boolSetting("enable_enhanced_dreams")) return false;
    const restChildren = new Set(["rest_reply_mode", "rest_reply_probability", "rest_reply_llm_threshold", "rest_reply_active_windows", "rest_reply_awake_grace_minutes", "enable_rest_backlog_reply", "rest_backlog_max_messages", "REST_WAKEUP_PROVIDER_ID"]);
    if (settingKey === "enable_qq_custom_presence_sync") {
      return boolSetting("enable_qq_presence_sync");
    }
    if (restChildren.has(settingKey)) {
      const restEnabled = boolSetting("enable_rest_reply_simulation");
      if (!restEnabled) return false;
      if (settingKey === "rest_reply_probability") return String(valueSetting("rest_reply_mode", "probability")) === "probability";
      if (["rest_reply_llm_threshold", "REST_WAKEUP_PROVIDER_ID"].includes(settingKey)) return String(valueSetting("rest_reply_mode", "probability")) === "llm";
      if (settingKey === "rest_backlog_max_messages") return boolSetting("enable_rest_backlog_reply");
      return true;
    }
    return true;
  }
  if (featureKey === "enable_environment_perception") {
    const weatherChildren = new Set([
      "weather_api_key",
      "weather_city",
      "weather_lat",
      "weather_lon",
      "weather_refresh_minutes",
      "enable_environment_change_proactive",
      "environment_change_check_minutes",
      "environment_change_cooldown_minutes",
    ]);
    if (weatherChildren.has(settingKey) && !boolSetting("enable_weather_context")) return false;
    if (["environment_change_check_minutes", "environment_change_cooldown_minutes"].includes(settingKey)) {
      return boolSetting("enable_environment_change_proactive");
    }
    return true;
  }
  if (featureKey === "enable_worldbook_member_recognition") {
    if (["worldbook_self_registration_block_words", "worldbook_self_registration_block_reply"].includes(settingKey)) {
      return boolSetting("worldbook_self_registration");
    }
    return true;
  }
  if (featureKey === "enable_message_debounce") {
    if (settingKey === "text_message_debounce_seconds" && boolSetting("enable_smart_message_debounce")) return false;
    return true;
  }
  if (featureKey === "enable_recall_enhancement") {
    if (settingKey === "recall_message_cache_text_chars" && !boolSetting("enable_recall_message_cache")) return false;
    return true;
  }
  if (featureKey === "enable_private_image_self_recognition") {
    if (["context_image_caption_max_items", "context_image_caption_timeout_seconds"].includes(settingKey)) {
      return boolSetting("enable_context_image_captioning");
    }
    return true;
  }
  if (featureKey === "enable_forward_message_adaptation") {
    if (["forward_message_image_limit", "forward_message_image_vision_timeout_seconds"].includes(settingKey)) {
      return boolSetting("forward_message_image_vision");
    }
    return true;
  }
  if (featureKey === "enable_group_member_profiles") {
    if (settingKey === "max_group_relationship_edges") return boolSetting("enable_group_relationship_graph");
    if (settingKey === "group_slang_summary_minutes") return boolSetting("enable_group_slang_learning");
    if (settingKey === "max_group_topic_threads") return boolSetting("enable_group_topic_threads");
    if (["group_episode_refresh_minutes", "max_group_episodes"].includes(settingKey)) return boolSetting("enable_group_episode_memory");
    return true;
  }
  if (featureKey === "enable_screen_glance_action") {
    if (["unanswered_screen_peek_after_minutes", "unanswered_screen_peek_cooldown_minutes"].includes(settingKey)) {
      return boolSetting("enable_unanswered_screen_peek_followup");
    }
    return true;
  }
  if (featureKey === "enable_group_slang_learning") {
    if (settingKey === "enable_group_slang_web_search") return boolSetting("enable_group_slang_meanings");
    if (["group_slang_web_search_terms", "group_slang_web_search_results"].includes(settingKey)) {
      return boolSetting("enable_group_slang_meanings") && boolSetting("enable_group_slang_web_search");
    }
    return true;
  }
  if (featureKey === "enable_group_wakeup_enhancement") {
    if (settingKey === "group_wakeup_question_threshold") {
      return boolSetting("enable_group_wakeup_question");
    }
    if (["group_wakeup_cold_group_threshold", "group_wakeup_cold_group_idle_minutes"].includes(settingKey)) {
      return boolSetting("enable_group_wakeup_cold_group");
    }
    if ([
      "group_high_intensity_wakeup_window_seconds",
      "group_high_intensity_wakeup_threshold",
      "group_high_intensity_cooldown_seconds",
      "group_high_intensity_merge_seconds",
      "group_high_intensity_max_merge_messages",
      "group_high_intensity_merge_scope",
    ].includes(settingKey)) {
      return boolSetting("enable_group_high_intensity_mode");
    }
    return true;
  }
  if (featureKey === "enable_passive_response_review") {
    if (settingKey === "response_review_max_chars") {
      return String(valueSetting("passive_review_mode", "severe_only")) === "full";
    }
    return true;
  }
  if (featureKey === "enable_maslow_motivation_experiment") {
    if (["enable_maslow_schedule_influence", "maslow_motivation_strength"].includes(settingKey)) {
      return boolSetting("enable_maslow_motivation_experiment");
    }
    return true;
  }
  if (featureKey === "enable_personality_iteration_experiment") {
    if (settingKey === "enable_personality_iteration_auto_tune") {
      return boolSetting("enable_personality_iteration_experiment");
    }
    return true;
  }
  if (featureKey === "enable_photo_text_action") {
    if (settingKey === "photo_persona_reference_image_path") return boolSetting("enable_photo_reference_image");
    if (["daily_outfit_photo_prompt", "daily_outfit_rotation_days"].includes(settingKey)) return boolSetting("enable_daily_outfit_photo");
    if (settingKey === "enable_natural_language_photo_generation") {
      return String(valueSetting("natural_language_photo_generation_mode", "tool_first")) === "rule_fast";
    }
    if (["natural_language_photo_generation_max_daily", "natural_language_photo_extra_prompt"].includes(settingKey)) {
      return String(valueSetting("natural_language_photo_generation_mode", "tool_first")) === "rule_fast" && boolSetting("enable_natural_language_photo_generation");
    }
    return true;
  }
  if (featureKey === "enable_emotion_simulation") {
    if (settingKey === "emotion_judgement_mode") return boolSetting("enable_llm_emotion_judgement");
    if (settingKey === "EMOTION_JUDGEMENT_PROVIDER_ID") return boolSetting("enable_llm_emotion_judgement") && String(valueSetting("emotion_judgement_mode", "suspicious")) !== "off";
    return true;
  }
  if (featureKey !== "enable_tts_enhancement") return true;
  const mode = String(settings.tts_frequency_control_mode || "global");
  const rawGenerationMode = String(settings.tts_generation_mode || "fast_tag").toLowerCase();
  const generationMode = {
    hybrid: "fast_tag",
    direct: "fast_tag",
    tag: "fast_tag",
    fast: "fast_tag",
    convert: "postprocess",
    post: "postprocess",
    llm: "postprocess",
  }[rawGenerationMode] || rawGenerationMode;
  const deliveryMode = String(valueSetting("tts_delivery_mode", "voice_and_text") || "voice_and_text");
  const voiceLanguage = String(valueSetting("tts_voice_language", "ja") || "ja");
  const globalOnly = new Set([
    "tts_constraint_mode",
    "tts_session_min_interval_seconds",
    "tts_private_min_interval_seconds",
    "tts_group_min_interval_seconds",
    "tts_trigger_probability",
    "tts_private_trigger_probability",
    "tts_group_trigger_probability",
  ]);
  const legacyOnly = new Set([
    "auto_voice_probability",
    "auto_voice_cooldown_seconds",
    "main_user_voice_probability",
    "main_user_mention_voice_keywords",
    "main_user_mention_voice_probability",
    "main_user_mention_voice_prompt",
  ]);
  const fastTagOnly = new Set([
    "tts_constraint_mode",
    "auto_voice_enabled",
    "auto_voice_max_chars",
    "auto_voice_probability",
    "auto_voice_cooldown_seconds",
    "main_user_voice_probability",
    "main_user_mention_voice_keywords",
    "main_user_mention_voice_probability",
    "main_user_mention_voice_prompt",
  ]);
  const autoVoiceChildren = new Set([
    "auto_voice_max_chars",
  ]);
  const legacyAutoVoiceChildren = new Set([
    "auto_voice_probability",
    "auto_voice_cooldown_seconds",
    "main_user_voice_probability",
    "main_user_mention_voice_keywords",
    "main_user_mention_voice_probability",
    "main_user_mention_voice_prompt",
  ]);
  const localPlaybackChildren = new Set([
    "enable_tts_local_playback_live_only",
    "tts_local_playback_volume",
    "tts_local_playback_min_interval_seconds",
  ]);
  const liveSubtitleChildren = new Set([
    "tts_live_subtitle_url",
  ]);
  if (generationMode === "postprocess" && fastTagOnly.has(settingKey)) return false;
  if (settingKey === "tts_foreign_text_mode" && (deliveryMode === "voice_only" || voiceLanguage === "zh")) return false;
  if (autoVoiceChildren.has(settingKey) && !boolSetting("auto_voice_enabled")) return false;
  if (legacyAutoVoiceChildren.has(settingKey) && !boolSetting("auto_voice_enabled")) return false;
  if (localPlaybackChildren.has(settingKey) && !boolSetting("enable_tts_local_playback")) return false;
  if (liveSubtitleChildren.has(settingKey) && !boolSetting("enable_tts_live_subtitle_sync")) return false;
  if (mode === "legacy") return !globalOnly.has(settingKey);
  return !legacyOnly.has(settingKey);
}

export function featureSettingInputType(key, value) {
  if (featureSettingTypes[key]) return featureSettingTypes[key];
  if (typeof value === "boolean") return { type: "checkbox" };
  if (typeof value === "number") return { type: "number" };
  if (Array.isArray(value)) return { type: "textarea" };
  return { type: "text" };
}

export function featureSettingInput(key, value) {
  const spec = featureSettingInputType(key, value);
  const safeKey = escapeHtml(key);
  const disabled = featureLockedByProactiveOnlyMode(key);
  const disabledAttr = disabled ? " disabled" : "";
  if (spec.type === "checkbox") {
    const checked = toBool(value);
    return `
      <label class="feature-param-check">
        <input type="checkbox" data-feature-param="${safeKey}" ${checked ? "checked" : ""}${disabledAttr}>
        <span>${escapeHtml(disabled ? "已锁定" : checked ? "开启" : "关闭")}</span>
      </label>
    `;
  }
  if (spec.type === "select") {
    return `
      <select data-feature-param="${safeKey}"${disabledAttr}>
        ${(spec.options || []).map(([optionValue, label]) => `
          <option value="${escapeHtml(optionValue)}"${String(value ?? "") === String(optionValue) ? " selected" : ""}>${escapeHtml(label)}</option>
        `).join("")}
      </select>
    `;
  }
  if (spec.type === "provider") {
    return featureProviderSelect(key, value);
  }
  if (spec.type === "textarea") {
    return `<textarea data-feature-param="${safeKey}" rows="3"${disabledAttr}>${escapeHtml(Array.isArray(value) ? value.join("\n") : value ?? "")}</textarea>`;
  }
  const password = spec.type === "password";
  const numeric = spec.type === "number" || typeof value === "number";
  const percentInput = isPercentInputSetting(key);
  const step = percentInput ? (spec.step ?? "1") : (spec.step ?? (key === "skill_growth_rate" ? "0.01" : "any"));
  const min = percentInput ? (spec.min ?? "0") : (spec.min ?? "");
  const max = percentInput ? (spec.max ?? "100") : (spec.max ?? "");
  const displayValue = displaySettingValue(key, value);
  return `
    <input
      type="${password ? "password" : numeric ? "number" : "text"}"
      data-feature-param="${safeKey}"
      value="${escapeHtml(displayValue)}"
      ${numeric ? `step="${step}"` : ""}
      ${min ? `min="${min}"` : ""}
      ${max ? `max="${max}"` : ""}
      ${disabledAttr}
    />
  `;
}

export function featureProviderSelect(key, value) {
  const current = String(value || "").trim();
  const known = state.availableProviders.some((item) => item.id === current);
  const customValue = current && !known ? current : "";
  const options = [
    `<option value="">留空自动回退</option>`,
    ...state.availableProviders.map((item) => {
      const label = `${item.name || item.id}${item.model ? ` · ${item.model}` : ""}${item.is_default ? " · 默认" : ""}`;
      return `<option value="${escapeHtml(item.id)}" ${item.id === current ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }),
    `<option value="__custom__" ${customValue ? "selected" : ""}>手动输入 Provider ID</option>`,
  ].join("");
  return `
    <div class="feature-provider-select">
      <select data-feature-provider-select="${escapeHtml(key)}">${options}</select>
      <input data-feature-param="${escapeHtml(key)}" value="${escapeHtml(current)}" placeholder="自定义 Provider ID" ${customValue ? "" : "hidden"} />
    </div>
  `;
}

export function syncFeatureProviderInput(select) {
  const key = select.dataset.featureProviderSelect;
  const input = document.querySelector(`[data-feature-param="${key}"]`);
  if (!input) return;
  if (select.value === "__custom__") {
    input.hidden = false;
    input.focus();
  } else {
    input.hidden = true;
    input.value = select.value;
  }
}

export function collectFeatureDetailPayload(featureKey, root = document) {
  if (featureKey === "enable_photo_text_action") {
    collectPhotoApiEndpointEditor(root);
  }
  const overviewSettings = state.overview?.settings || {};
  const features = {};
  const settings = {};
  const providers = {};
  if (Object.prototype.hasOwnProperty.call(overviewSettings, featureKey)) {
    settings[featureKey] = toBool(state.featureDraft[featureKey]);
  } else {
    features[featureKey] = toBool(state.featureDraft[featureKey]);
  }
  root.querySelectorAll("[data-feature-param]").forEach((input) => {
    const key = input.dataset.featureParam;
    if (!key) return;
    const value = collectSettingValue(key, input);
    if (isProviderConfigKey(key)) {
      providers[key] = String(value || "").trim();
      state.providerDraft = { ...(state.providerDraft || {}), [key]: providers[key] };
    } else if (Object.prototype.hasOwnProperty.call(overviewSettings, key)) {
      settings[key] = value;
      if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, key)) {
        state.featureDraft[key] = toBool(value);
      }
    } else if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, key)) {
      features[key] = toBool(value);
      state.featureDraft[key] = toBool(value);
    } else {
      settings[key] = value;
    }
  });
  return { features, settings, providers };
}

export async function saveCurrentFeatureDetail(control = null, successMessage = "已保存功能参数") {
  const featureKey = state.selectedFeatureKey || "";
  if (!featureKey) return true;
  const form = Array.from(document.querySelectorAll("[data-feature-param-form]"))
    .find((item) => item.dataset.featureParamForm === featureKey);
  if (!form) return true;
  const payload = collectFeatureDetailPayload(featureKey, form);
  const result = await runAction(
    () => postJson("/settings/update", payload),
    successMessage,
    control || form.querySelector(".feature-param-save"),
  );
  return Boolean(result);
}

export function featureDependencyLines(key) {
  const dependencies = [];
  if (featureLockedByProactiveOnlyMode(key)) dependencies.push(["仅保留主动能力", "普通被动链路中此功能被本插件跳过，原配置保留；关闭仅保留主动能力后生效。"]);
  if (key === "enable_proactive_only_mode") {
    dependencies.push(["注意", "只跳过本插件的普通被动增强，不会阻止默认回复或其他插件"]);
    const proactiveChat = state.overview?.proactive_chat || {};
    if (proactiveChat.deep_active) dependencies.push(["Proactive Chat", `深度联动；生成前上下文与调度互斥、生成后复核、平台发送结算均已接管（${proactiveChat.runtime_method_count || 0} 个方法），最近同步 ${proactiveChat.last_sent || "暂无记录"}`]);
    else if (proactiveChat.active) dependencies.push(["Proactive Chat", `当前为${proactiveChat.runtime_mode_label || "发送前兼容"}；${proactiveChat.runtime_last_error || proactiveChat.runtime_last_event || "等待兼容运行实例"}`]);
    else if (proactiveChat.installed) dependencies.push(["Proactive Chat", "已检测到插件；开启联动后会优先建立深度运行时桥接"]);
    else dependencies.push(["Proactive Chat", "未检测到；安装后无需修改对方插件，本页联动开关会自动生效"]);
  }
  if (key !== "enable_group_companion" && key.startsWith("enable_group_")) dependencies.push(["依赖", "群聊总开关"]);
  if (key === "enable_group_conversation_followup") dependencies.push(["依赖", "群聊场景感知"]);
  if (["enable_companion_memory", "enable_expression_learning", "enable_intent_emotion_analysis", "enable_passive_response_review", "enable_proactive_message_review", "enable_smart_silence", "enable_passive_topic_suppression", "enable_relationship_state_machine", "enable_emotion_simulation", "enable_dialogue_episode_memory", "enable_open_loop_tracking", "enable_food_menu_recommendation"].includes(key)) {
    dependencies.push(["依赖", "私聊互动策略"]);
  }
  if (["enable_bilibili_boredom_watch"].includes(key)) dependencies.push(["依赖", "B 站能力可用"]);
  if (["enable_web_exploration", "enable_web_exploration_boredom_search"].includes(key)) dependencies.push(["依赖", "AstrBot 网页搜索"]);
  if (["enable_qzone_life_publish", "enable_qzone_comment_inbox"].includes(key)) dependencies.push(["依赖", "QQ 空间动态层"]);
  if (key === "enable_qzone_generated_image_publish") dependencies.push(["依赖", "QQ 空间动态层 + 主动拍照/生图"]);
  if (key === "enable_qzone_emotional_vent_publish") dependencies.push(["依赖", "情绪模拟 + QQ 空间动态层"]);
  if (key === "enable_photo_text_action") dependencies.push(["依赖", "ComfyUI、SDGen 或在线图片 API"]);
  if (key === "enable_tts_enhancement") dependencies.push(["依赖", "当前会话 TTS provider"]);
  if (key === "enable_screen_glance_action") dependencies.push(["依赖", "screen_companion 屏幕观察能力"]);
  if (key === "enable_poke_action") dependencies.push(["依赖", "当前平台支持戳一戳"]);
  if (key === "enable_voice_action") dependencies.push(["依赖", "当前会话 TTS provider"]);
  if (key === "enable_yesterday_screen_diary_context") dependencies.push(["依赖", "screen_companion 昨日观察日记"]);
  if (key === "enable_livingmemory_integration") {
    const livingmemory = state.overview?.livingmemory || {};
    if (livingmemory.conflict_warning) dependencies.push(["警告", livingmemory.conflict_warning]);
    else if (livingmemory.selected_plugin_name) dependencies.push(["当前使用", livingmemory.selected_plugin_name]);
    else if (livingmemory.compatible_available || livingmemory.available || livingmemory.memory_companion_active) dependencies.push(["当前使用", "已检测到可协同记忆插件"]);
    else dependencies.push(["依赖", "需要安装并启用“我会牢牢记住你”/MemoryCompanion 或 LivingMemory"]);
  }
  if (key.startsWith("enable_private_reading_")) dependencies.push(["依赖", "素材能力可用"]);
  if (key === "enable_private_image_self_recognition") dependencies.push(["依赖", "AstrBot 默认图片转述模型 / 插件识图模型"]);
  if (["enable_group_interjection", "enable_bilibili_boredom_watch", "enable_news_boredom_read", "enable_web_exploration_boredom_search", "enable_private_reading_boredom_read", "enable_private_reading_ask_recommendation", "enable_unanswered_screen_peek_followup"].includes(key)) {
    dependencies.push(["注意", "高主动项"]);
  }
  return dependencies;
}
