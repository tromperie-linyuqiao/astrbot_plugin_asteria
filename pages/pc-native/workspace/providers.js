/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {postJson} from './client.js';
import {foodMenuFeaturePanelHtml} from './learning.js';
import {bindFoodMenuFeatureActions} from './library.js';
import {environmentWeatherStatusHtml} from './life.js';
import {featureDescription,featureLabel,featurePublicKey,requireSecondClick,runAction,setActionBusy,showToast} from './persona.js';
import {collectPhotoApiEndpointEditor,collectSettingValue,currentProviderConfigMode,featureLockedByProactiveOnlyMode,featureTemporarilyUnlockedByProactiveOnly,isPercentInputSetting,isProviderConfigKey,normalizeModelFallbackOverrides,normalizeModelTimeoutOverrides,normalizePhotoApiEndpoint,photoApiEndpointDraft,photoApiEndpointEditorHtml,proactiveOnlyModeEnabled,proactiveOnlyRelatedUnlocks,providerAllowedInCurrentMode,providerNeedsLowLatency,setProviderConfigMode,syncProviderConfigModeControls,toBool,visibleConfigKey} from './schema.js';
import {bindSegmentedPreview,collectFeatureDetailPayload,featureDependencyLines,featureGroupForKey,featureRelatedSettings,featureSettingInput,renderFeatureSwitches,saveCurrentFeatureDetail,segmentedPreviewPanelHtml,syncFeatureProviderInput} from './settings.js';
import {$,configDescriptions,configLabels,featureDetailGuides,featureSettingSections,featureSwitchNotes,noFallbackProviderKeys,optionalNoFallbackProviderKeys,providerGroupByKey,providerGroups,providerGuides,providerLabels,providerPassiveImpactMeta,providerPreferenceMeta,state} from './state.js';
import {escapeHtml} from './workspace.js';
import asteriaProviders from '../js/panels/provider-tree.js';

export function featureDetailExplanation(key) {
  const guide = featureDetailGuides[key];
  if (guide?.summary) return guide.summary;
  if (key.startsWith("enable_group_")) return "群聊子能力。";
  if (key.startsWith("enable_private_reading_")) return "夹层阅读子能力。";
  if (key.startsWith("enable_bilibili_")) return "B 站子能力。";
  if (key.startsWith("enable_qzone_")) return "QQ 空间子能力。";
  return featureDescription(key);
}

export function featureDetailGuideRows(key) {
  const guide = featureDetailGuides[key] || {};
  const rows = [
    ["何时生效", guide.trigger || "该功能对应场景触发时生效。"],
    ["开启后", guide.enabled || "相关能力会参与判断、注入或后台整理。"],
    ["关闭后", guide.disabled || "相关能力停止新增处理，已有数据通常仍可在页面查看。"],
  ];
  if (featureSwitchNotes[key]) {
    rows.push(["管理入口", featureSwitchNotes[key]]);
  }
  return rows;
}

export function featureImpactLines(key) {
  const lines = [];
  const group = featureGroupForKey(key);
  lines.push(["模块", group]);
  if (["enable_humanized_states", "inject_passive_states", "enable_health_state", "enable_hunger_state", "enable_cycle_state", "enable_skill_growth_simulation"].includes(key)) {
    lines.push(["场景", "日程 / 状态 / 私聊 / 群聊"]);
  } else if (key === "enable_segmented_proactive_reply") {
    lines.push(["场景", "主动消息 / LLM 纯文本回复"]);
  } else if (key === "enable_message_debounce") {
    lines.push(["场景", "私聊 / 群聊 / 图片 / 合并转发"]);
  } else if (key === "enable_forward_message_adaptation") {
    lines.push(["场景", "私聊合并消息 / 群聊合并消息"]);
  } else if (key === "enable_proactive_quote_trigger_message") {
    lines.push(["场景", "群回复 / 群主动 / 私聊主动"]);
  } else if (key === "enable_tts_enhancement") {
    lines.push(["场景", "私聊 / 群聊 / 主动语音"]);
  } else if (["enable_screen_glance_action", "enable_poke_action", "enable_voice_action"].includes(key)) {
    lines.push(["场景", "私聊主动动作"]);
  } else if (key.startsWith("enable_group_") || key === "enable_atrelay_tools" || key === "enable_cross_user_memory_bridge" || key === "enable_worldbook_member_recognition") {
    lines.push(["场景", "群聊 / 转述 / 关系网"]);
  } else if (key === "enable_private_image_self_recognition") {
    lines.push(["场景", "私聊图片 / 引用图片 / 合并图片 / GIF"]);
  } else if (key === "enable_food_menu_recommendation") {
    lines.push(["场景", "私聊 / 吃饭选择"]);
  } else if (key.startsWith("enable_bilibili_") || key.startsWith("enable_news_") || key === "enable_external_event_self_link" || key.startsWith("enable_web_exploration") || key.startsWith("enable_qzone_") || key === "enable_photo_text_action" || key.startsWith("enable_private_reading_") || key === "enable_creative_writing" || key === "creative_hidden_mode") {
    lines.push(["场景", "长线主动"]);
  } else if (key.startsWith("enable_environment_") || key.includes("perception") || key === "enable_yesterday_screen_diary_context") {
    lines.push(["场景", key === "enable_yesterday_screen_diary_context" ? "日程 / 状态 / 屏幕日记" : "日程 / 状态 / 回复"]);
  } else {
    lines.push(["场景", "私聊陪伴"]);
  }
  return lines;
}

export function configLabel(name) {
  const label = configLabels[name] || providerLabels[name] || featureLabel(name) || name.replace(/^enable_/, "").replaceAll("_", " ");
  if (isPercentInputSetting(name) && !/[（(]%[）)]/.test(label)) {
    return `${label}（%）`;
  }
  return label;
}

export function configDescription(name) {
  const guide = providerGuides[name];
  if (guide) {
    return [guide.purpose, guide.fit, guide.fallback].filter(Boolean).join(" ");
  }
  return configDescriptions[name] || featureDescription(name) || "这个参数会影响该功能的触发频率、上下文范围或行为边界。";
}

export function featureDetailPage(key) {
  const enabled = toBool(state.featureDraft[key]);
  const locked = featureLockedByProactiveOnlyMode(key);
  const tempUnlocked = featureTemporarilyUnlockedByProactiveOnly(key);
  const displayEnabled = enabled || tempUnlocked;
  const relatedUnlocks = proactiveOnlyRelatedUnlocks(key);
  const related = featureRelatedSettings(key);
  const relatedMap = Object.fromEntries(related.map((item) => [item.key, item]));
  const dependencies = featureDependencyLines(key);
  const impacts = featureImpactLines(key);
  const guideRows = featureDetailGuideRows(key)
    .map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("");
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
  const sections = featureSettingSections[key] || [];
  const renderedSectionKeys = new Set();
  const groupedRows = sections
    .map((section) => {
      const items = (section.keys || []).map((name) => relatedMap[name]).filter(Boolean);
      items.forEach((item) => renderedSectionKeys.add(item.key));
      if (!items.length) return "";
      const sectionStatus = key === "enable_environment_perception" && section.title === "天气上下文"
        ? environmentWeatherStatusHtml()
        : "";
      return `
        <section class="feature-param-section">
          <header>
            <b>${escapeHtml(section.title || "参数")}</b>
            ${section.note ? `<span>${escapeHtml(section.note)}</span>` : ""}
          </header>
          ${sectionStatus}
          ${items.map(settingRow).join("")}
        </section>
      `;
    })
    .join("");
  const ungroupedRows = related.filter((item) => !renderedSectionKeys.has(item.key)).map(settingRow).join("");
  const extraParamPanel = [
    key === "enable_segmented_proactive_reply" ? segmentedPreviewPanelHtml() : "",
    key === "enable_photo_text_action" ? photoApiEndpointEditorHtml() : "",
  ].filter(Boolean).join("");
  const customFeaturePanel = key === "enable_food_menu_recommendation" ? foodMenuFeaturePanelHtml() : "";
  const settingsRows = related.length
    ? `${groupedRows}${ungroupedRows}`
    : `<div class="feature-param-empty">暂无关联参数</div>`;
  const showParamCard = key !== "enable_food_menu_recommendation" || related.length || extraParamPanel;
  const paramCardHtml = showParamCard ? `
        <article class="feature-detail-card feature-detail-card-params">
          <h3>关联参数</h3>
          <form class="feature-param-list ${key === "enable_tts_enhancement" ? "tts-config-layout" : ""}" data-feature-param-form="${escapeHtml(key)}">
            ${settingsRows}
            ${extraParamPanel}
            ${related.length ? `<button type="submit" class="feature-param-save">保存关联参数</button>` : ""}
          </form>
        </article>
      ` : "";
  const dependencyRows = dependencies.length
    ? dependencies.map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")
    : `<div><dt>-</dt><dd>无额外依赖</dd></div>`;
  const impactRows = impacts.map(([name, value]) => `<div><dt>${escapeHtml(name)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  return `
    <section class="feature-detail-page ${displayEnabled ? "on" : "off"} ${locked ? "locked" : ""}">
      <nav class="feature-detail-breadcrumb">
        <button type="button" data-feature-back>功能开关</button>
        <span>/ ${escapeHtml(featureGroupForKey(key))}</span>
      </nav>
      <div class="feature-state-strip ${displayEnabled ? "on" : "off"}">
        <b>${escapeHtml(locked ? (tempUnlocked ? "临时放行" : "已锁定") : enabled ? "开启" : "关闭")}</b>
        ${locked ? `<span>${escapeHtml(tempUnlocked ? "仅保留主动能力仍开启，但此功能已被临时放行；关闭后放行项会清空。" : "当前处于仅保留主动能力模式；保存的原始开关值不会被修改。")}</span>` : ""}
      </div>
      <header class="feature-detail-head">
        <div>
          <span class="module-badge">${escapeHtml(featureGroupForKey(key))}</span>
          <h2>${escapeHtml(featureLabel(key))}</h2>
          <p>${escapeHtml(featureDetailExplanation(key))}</p>
        </div>
        <label class="feature-detail-toggle">
          <input type="checkbox" data-feature-detail-toggle="${escapeHtml(key)}" ${displayEnabled ? "checked" : ""} ${locked ? "disabled" : ""}>
          <span class="feature-toggle-visual"></span>
          <b>${escapeHtml(locked ? (tempUnlocked ? "临时放行" : "已锁定") : enabled ? "开启" : "关闭")}</b>
        </label>
      </header>
      ${locked ? `
        <section class="feature-detail-card feature-temp-unlock-panel">
          <h3>主动专用临时放行</h3>
          <p>${escapeHtml(tempUnlocked ? "此功能已在仅保留主动能力时临时放行。关闭后，放行项会自动清空。" : "此功能当前被仅保留主动能力覆盖。你可以二次确认后临时放行，不会改写原配置。")}</p>
          ${relatedUnlocks.length ? `<p>建议同步：${escapeHtml(relatedUnlocks.map((item) => item.label || item.key).join("、"))}</p>` : ""}
          <div class="feature-temp-unlock-actions">
            <button type="button" data-proactive-temp-unlock="${escapeHtml(key)}" data-action="${tempUnlocked ? "clear" : "unlock"}">${escapeHtml(tempUnlocked ? "取消临时放行" : "临时放行")}</button>
            ${!tempUnlocked && relatedUnlocks.length ? `<button type="button" data-proactive-temp-unlock="${escapeHtml(key)}" data-action="unlock" data-sync-related="1">同步放行建议项</button>` : ""}
          </div>
        </section>
      ` : ""}
      ${customFeaturePanel}
      <div class="feature-detail-grid">
        <article class="feature-detail-card">
          <h3>基础信息</h3>
          <dl>
            <div><dt>${escapeHtml(featurePublicKey(key) === key ? "配置键" : "界面标识")}</dt><dd>${escapeHtml(featurePublicKey(key))}</dd></div>
            ${featurePublicKey(key) === key ? "" : `<div><dt>兼容配置键</dt><dd>${escapeHtml(key)}（仅为兼容旧配置保留）</dd></div>`}
            <div><dt>所属模块</dt><dd>${escapeHtml(featureGroupForKey(key))}</dd></div>
            <div><dt>当前状态</dt><dd>${escapeHtml(enabled ? "开启" : "关闭")}</dd></div>
          </dl>
        </article>
        <article class="feature-detail-card">
          <h3>范围</h3>
          <dl>${impactRows}</dl>
        </article>
        <article class="feature-detail-card feature-detail-card-guide">
          <h3>功能说明</h3>
          <dl>${guideRows}</dl>
        </article>
        ${paramCardHtml}
        <article class="feature-detail-card">
          <h3>依赖</h3>
          <dl>${dependencyRows}</dl>
        </article>
      </div>
    </section>
  `;
}

export function bindFeatureDetailActions() {
  document.querySelectorAll("[data-feature-back]").forEach((button) => {
    button.addEventListener("click", async () => {
      const saved = await saveCurrentFeatureDetail(button, "已保存并返回功能列表");
      if (!saved) return;
      state.selectedFeatureKey = "";
      renderFeatureSwitches();
    });
  });
  document.querySelectorAll("[data-feature-detail-toggle]").forEach((input) => {
    input.addEventListener("change", () => {
      state.featureDraft[input.dataset.featureDetailToggle] = input.checked;
      renderFeatureSwitches();
    });
  });
  document.querySelectorAll("[data-feature-param-form]").forEach((form) => {
    form.querySelectorAll("[data-feature-param]").forEach((input) => {
      if (input.type === "checkbox") {
        input.addEventListener("change", () => {
          const paramKey = input.dataset.featureParam || "";
          const label = input.closest(".feature-param-check")?.querySelector("span");
          if (label) label.textContent = input.checked ? "开启" : "关闭";
          if (paramKey && Object.prototype.hasOwnProperty.call(state.featureDraft || {}, paramKey)) {
            state.featureDraft[paramKey] = input.checked;
          }
          if (paramKey && Object.prototype.hasOwnProperty.call(state.overview?.settings || {}, paramKey)) {
            state.overview.settings[paramKey] = input.checked;
          }
          const preserveFeatureParamDraft = () => {
            form.querySelectorAll("[data-feature-param]").forEach((control) => {
              const draftKey = control.dataset.featureParam || "";
              if (!draftKey) return;
              const draftValue = collectSettingValue(draftKey, control);
              if (isProviderConfigKey(draftKey)) {
                state.overview.providers = state.overview.providers || {};
                state.overview.providers[draftKey] = String(draftValue || "").trim();
                return;
              }
              state.overview.settings = state.overview.settings || {};
              state.overview.settings[draftKey] = draftValue;
              if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, draftKey)) {
                state.featureDraft[draftKey] = toBool(draftValue);
              }
            });
          };
          const syncSettingBackedFeatureParam = (paramKey, { rerender = false } = {}) => {
            state.featureDraft[paramKey] = input.checked;
            state.overview.settings = state.overview.settings || {};
            state.overview.settings[paramKey] = input.checked;
            if (rerender) {
              preserveFeatureParamDraft();
              renderFeatureSwitches();
            }
          };
          if (state.selectedFeatureKey === "enable_humanized_states" && input.dataset.featureParam === "enable_rest_reply_simulation") {
            syncSettingBackedFeatureParam("enable_rest_reply_simulation", { rerender: input.checked });
          }
          if (
            state.selectedFeatureKey === "enable_humanized_states"
            && ["enable_daily_plan", "enable_detail_enhancement", "enable_daily_diary", "enable_daily_greetings", "enable_enhanced_dreams"].includes(input.dataset.featureParam)
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_message_debounce" && input.dataset.featureParam === "enable_smart_message_debounce") {
            syncSettingBackedFeatureParam("enable_smart_message_debounce", { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_livingmemory_integration" && input.dataset.featureParam === "enable_memory_companion_feature_context") {
            syncSettingBackedFeatureParam("enable_memory_companion_feature_context", { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_recall_enhancement" && input.dataset.featureParam === "enable_recall_message_cache") {
            syncSettingBackedFeatureParam("enable_recall_message_cache", { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_private_image_self_recognition" && input.dataset.featureParam === "enable_context_image_captioning") {
            syncSettingBackedFeatureParam("enable_context_image_captioning", { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_forward_message_adaptation" && input.dataset.featureParam === "forward_message_image_vision") {
            syncSettingBackedFeatureParam("forward_message_image_vision", { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_screen_glance_action" && input.dataset.featureParam === "enable_unanswered_screen_peek_followup") {
            syncSettingBackedFeatureParam("enable_unanswered_screen_peek_followup", { rerender: true });
          }
          if (
            state.selectedFeatureKey === "enable_tts_enhancement"
            && ["auto_voice_enabled", "enable_tts_local_playback", "enable_tts_live_subtitle_sync"].includes(input.dataset.featureParam)
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
          if (state.selectedFeatureKey === "enable_emotion_simulation" && input.dataset.featureParam === "enable_llm_emotion_judgement") {
            syncSettingBackedFeatureParam("enable_llm_emotion_judgement", { rerender: true });
          }
          if (
            state.selectedFeatureKey === "enable_environment_perception"
            && ["enable_weather_context", "enable_environment_change_proactive"].includes(input.dataset.featureParam)
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
          if (
            ["enable_group_slang_learning", "enable_group_member_profiles"].includes(state.selectedFeatureKey)
            && ["enable_group_slang_meanings", "enable_group_slang_web_search"].includes(input.dataset.featureParam)
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
          if (
            state.selectedFeatureKey === "enable_group_member_profiles"
            && ["enable_group_relationship_graph", "enable_group_slang_learning", "enable_group_topic_threads", "enable_group_episode_memory"].includes(input.dataset.featureParam)
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
          if (
            state.selectedFeatureKey === "enable_group_wakeup_enhancement"
            && ["enable_group_wakeup_question", "enable_group_wakeup_cold_group", "enable_group_interjection", "enable_group_interjection_feedback"].includes(input.dataset.featureParam)
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
          if (
            state.selectedFeatureKey === "enable_group_high_intensity_mode"
            && input.dataset.featureParam === "enable_group_high_intensity_mode"
          ) {
            syncSettingBackedFeatureParam(input.dataset.featureParam, { rerender: true });
          }
        });
      }
      if (state.selectedFeatureKey === "enable_emotion_simulation" && input.dataset.featureParam === "emotion_judgement_mode") {
        input.addEventListener("change", () => {
          state.overview.settings = state.overview.settings || {};
          state.overview.settings.emotion_judgement_mode = input.value || "suspicious";
          renderFeatureSwitches();
        });
      }
      if (state.selectedFeatureKey === "enable_passive_response_review" && input.dataset.featureParam === "passive_review_mode") {
        input.addEventListener("change", () => {
          state.overview.settings = state.overview.settings || {};
          state.overview.settings.passive_review_mode = input.value || "severe_only";
          renderFeatureSwitches();
        });
      }
      if (state.selectedFeatureKey === "enable_tts_enhancement" && input.dataset.featureParam === "tts_frequency_control_mode") {
        input.addEventListener("change", () => {
          state.overview.settings = state.overview.settings || {};
          state.overview.settings.tts_frequency_control_mode = input.value || "global";
          renderFeatureSwitches();
        });
      }
      if (state.selectedFeatureKey === "enable_tts_enhancement" && input.dataset.featureParam === "tts_generation_mode") {
        input.addEventListener("change", () => {
          state.overview.settings = state.overview.settings || {};
          state.overview.settings.tts_generation_mode = input.value || "fast_tag";
          // Preserve every unsaved field before rebuilding the conditional TTS sections.
          form.querySelectorAll("[data-feature-param]").forEach((control) => {
            const key = control.dataset.featureParam;
            if (!key || isProviderConfigKey(key)) return;
            state.overview.settings[key] = collectSettingValue(key, control);
          });
          renderFeatureSwitches();
        });
      }
      if (
        state.selectedFeatureKey === "enable_tts_enhancement"
        && ["tts_delivery_mode", "tts_voice_language"].includes(input.dataset.featureParam)
      ) {
        input.addEventListener("change", () => {
          state.overview.settings = state.overview.settings || {};
          form.querySelectorAll("[data-feature-param]").forEach((control) => {
            const key = control.dataset.featureParam;
            if (!key || isProviderConfigKey(key)) return;
            state.overview.settings[key] = collectSettingValue(key, control);
          });
          renderFeatureSwitches();
        });
      }
    });
    form.querySelectorAll("[data-feature-provider-select]").forEach((select) => {
      syncFeatureProviderInput(select);
      select.addEventListener("change", () => syncFeatureProviderInput(select));
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const featureKey = form.dataset.featureParamForm || state.selectedFeatureKey;
      const payload = collectFeatureDetailPayload(featureKey, form);
      const result = await runAction(
        () => postJson("/settings/update", payload),
        "已保存功能参数",
        form.querySelector(".feature-param-save"),
      );
      if (result && featureKey === "enable_photo_text_action") {
        state.imageApiEndpointDraft = null;
      }
    });
  });
  if (state.selectedFeatureKey === "enable_segmented_proactive_reply") {
    bindSegmentedPreview($("#featureFlags"));
  }
  if (state.selectedFeatureKey === "enable_photo_text_action") {
    bindPhotoApiEndpointEditor($("#featureFlags"));
  }
  if (state.selectedFeatureKey === "enable_food_menu_recommendation") {
    bindFoodMenuFeatureActions();
  }
  bindProactiveOnlyTempUnlockActions();
}

export function bindPhotoApiEndpointEditor(root = document) {
  const editor = root?.querySelector?.("[data-image-api-editor]");
  if (!editor) return;
  editor.querySelectorAll("[data-image-api-field]").forEach((input) => {
    input.addEventListener(input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input", () => {
      collectPhotoApiEndpointEditor(root);
    });
  });
  editor.querySelectorAll("[data-image-api-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.imageApiAction || "";
      const endpoints = collectPhotoApiEndpointEditor(root) || photoApiEndpointDraft();
      const index = Number(button.dataset.index || -1);
      if (action === "add") {
        endpoints.push(normalizePhotoApiEndpoint({ name: `备用在线 API ${endpoints.length + 1}`, enabled: true }, endpoints.length));
      } else if (action === "delete" && index >= 0 && endpoints.length > 1) {
        endpoints.splice(index, 1);
      } else if (action === "up" && index > 0) {
        [endpoints[index - 1], endpoints[index]] = [endpoints[index], endpoints[index - 1]];
      } else if (action === "down" && index >= 0 && index < endpoints.length - 1) {
        [endpoints[index + 1], endpoints[index]] = [endpoints[index], endpoints[index + 1]];
      }
      state.imageApiEndpointDraft = endpoints.map(normalizePhotoApiEndpoint);
      renderFeatureSwitches();
    });
  });
}

export function bindProactiveOnlyTempUnlockActions(root = document) {
  root.querySelectorAll("[data-proactive-temp-unlock]").forEach((button) => {
    button.addEventListener("click", async () => {
      const key = button.dataset.proactiveTempUnlock || "";
      const action = button.dataset.action || "unlock";
      const syncRelated = button.dataset.syncRelated === "1";
      const modeWasEnabled = proactiveOnlyModeEnabled();
      const confirmKey = `proactive-temp-${action}-${key}-${syncRelated ? "sync" : "single"}`;
      const confirmText = action === "clear"
        ? "再次点击取消临时放行"
        : syncRelated
          ? "再次点击确认同步放行"
          : "再次点击确认临时放行";
      if (!requireSecondClick(button, confirmKey, confirmText, confirmText)) return;
      setActionBusy(button, true);
      showToast("正在处理...");
      try {
        if (modeWasEnabled && !toBool(state.overview?.proactive_only?.enabled)) {
          const saved = await postJson("/settings/update", { features: { enable_proactive_only_mode: true } });
          state.overview = { ...(state.overview || {}), ...(saved || {}) };
          if (Object.prototype.hasOwnProperty.call(state.featureDraft || {}, "enable_proactive_only_mode")) {
            state.featureDraft.enable_proactive_only_mode = true;
          }
        }
        const result = await postJson("/proactive_only/unlock", { key, action, sync_related: syncRelated });
        state.overview = state.overview || {};
        const proactiveOnly = result?.proactive_only || result?.data?.proactive_only || {};
        state.overview.proactive_only = Object.keys(proactiveOnly).length ? proactiveOnly : (state.overview.proactive_only || {});
        if (modeWasEnabled && Object.prototype.hasOwnProperty.call(state.featureDraft || {}, "enable_proactive_only_mode")) {
          state.featureDraft.enable_proactive_only_mode = true;
        }
        renderFeatureSwitches();
        showToast(action === "clear" ? "已取消临时放行" : "已临时放行");
      } catch (error) {
        showToast(`操作失败：${error.message}`, "error");
      } finally {
        setActionBusy(button, false);
      }
    });
  });
}

export function renderProviders() {
  if (asteriaProviders?.renderProviders) {
    const saveButton = document.getElementById("saveProvidersBtn");
    const testButton = document.getElementById("testAllProvidersBtn");
    if (saveButton) saveButton.disabled = Boolean(state.providerSave?.status === "pending" || state.providerSave?.status === "unknown");
    if (testButton) testButton.disabled = false;
    asteriaProviders.renderProviders({
      window,
      document,
      state,
      escapeHtml,
      providerLabels,
      providerGuides,
      providerPreferenceMeta,
      providerPassiveImpactMeta,
      providerGroups,
      providerGroupByKey,
      noFallbackProviderKeys,
      optionalNoFallbackProviderKeys,
      visibleConfigKey,
      providerAllowedInCurrentMode,
      providerNeedsLowLatency,
      currentProviderConfigMode,
      normalizeModelFallbackOverrides,
      syncProviderConfigModeControls,
      setProviderConfigMode,
      postJson,
    });
    bindProviderToolbar();
    return;
  }
  const form = document.getElementById("providerForm");
  const saveButton = document.getElementById("saveProvidersBtn");
  const testButton = document.getElementById("testAllProvidersBtn");
  if (saveButton) saveButton.disabled = true;
  if (testButton) testButton.disabled = true;
  if (form && !form.innerHTML.trim()) {
    form.innerHTML = `<div class="empty small">模型配置面板脚本未加载。请刷新拓展页；若仍失败，检查 provider-tree.js 是否被浏览器拦截。</div>`;
  }
}

export function providerValuesForRender() {
  if (asteriaProviders?.currentProviderValues) {
    return asteriaProviders.currentProviderValues({ document, state });
  }
  return {
    ...(state.overview?.providers || {}),
    ...(state.providerDraft || {}),
  };
}

export function currentProviderValues() {
  return providerValuesForRender();
}

export function currentProviderTimeoutValues() {
  if (asteriaProviders?.currentProviderTimeoutValues) {
    return asteriaProviders.currentProviderTimeoutValues({ document, state });
  }
  return normalizeModelTimeoutOverrides(state.overview?.settings?.model_timeout_overrides);
}

export function currentProviderFallbackValues() {
  if (asteriaProviders?.currentProviderFallbackValues) {
    return asteriaProviders.currentProviderFallbackValues({ document, state });
  }
  return normalizeModelFallbackOverrides(state.overview?.settings?.model_fallback_overrides);
}

export function bindProviderToolbar() {
  if (asteriaProviders?.bindProviderToolbar) {
    asteriaProviders.bindProviderToolbar({ document, state, setProviderConfigMode, refreshProviders: renderProviders });
  }
}

export async function testProvider(key) {
  if (!asteriaProviders?.testProvider) {
    showToast("模型配置面板脚本未加载，请刷新拓展页", "error");
    return;
  }
  if (asteriaProviders?.testProvider) {
    await asteriaProviders.testProvider({
      document,
      state,
      postJson,
      noFallbackProviderKeys,
      optionalNoFallbackProviderKeys,
    }, key);
  }
}

export function miniStat(label, value) {
  return `<div class="mini-stat"><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span></div>`;
}

export function scoreGauge(label, value, min, max) {
  const num = Number(value || 0);
  const pct = Math.max(0, Math.min(100, Math.round(((num - min) / Math.max(1, max - min)) * 100)));
  return `
    <div class="gauge">
      <svg viewBox="0 0 120 64" role="img" aria-label="${escapeHtml(label)}">
        <path d="M16 58 A44 44 0 0 1 104 58" class="gauge-bg"></path>
        <path d="M16 58 A44 44 0 0 1 104 58" class="gauge-fg" pathLength="100" style="stroke-dasharray:${pct} 100"></path>
        <text x="60" y="48" text-anchor="middle">${escapeHtml(num)}</text>
      </svg>
      <span>${escapeHtml(label)}</span>
    </div>
  `;
}

export function relationshipGraphView(edges, groupMembers = {}) {
  const pairs = Object.entries(edges || {})
    .map(([key, value]) => {
      const parts = key.split(/[-|:>]+/).map((item) => item.trim()).filter(Boolean);
      const weight = Number(value?.count || value?.weight || value || 1);
      return parts.length >= 2 ? {
        a: parts[0],
        b: parts[1],
        weight,
        kind: value?.kind || value?.type || value?.relation || "",
        summary: value?.summary || value?.last_summary || value?.reason || "",
      } : null;
    })
    .filter(Boolean)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 24);
  if (!pairs.length) return `<div class="empty small">暂无关系边</div>`;

  const memberMap = relationshipMemberMap(groupMembers);
  const scores = new Map();
  pairs.forEach((edge) => {
    [edge.a, edge.b].forEach((id) => {
      const item = scores.get(id) || { id, degree: 0, weight: 0 };
      item.degree += 1;
      item.weight += edge.weight;
      scores.set(id, item);
    });
  });
  const topNodes = [...scores.values()]
    .sort((a, b) => b.weight - a.weight || b.degree - a.degree)
    .slice(0, 8);
  const maxWeight = Math.max(1, ...pairs.map((edge) => edge.weight));
  const strongest = pairs[0];
  const hiddenCount = Math.max(0, Object.keys(edges || {}).length - pairs.length);
  return `
    <div class="relation-map">
      <div class="relation-map-summary">
        <article><span>涉及成员</span><b>${escapeHtml(scores.size)}</b></article>
        <article><span>互动关系</span><b>${escapeHtml(Object.keys(edges || {}).length)}</b></article>
        <article><span>最强连接</span><b>${escapeHtml(relationNodeName(strongest.a, memberMap))} ↔ ${escapeHtml(relationNodeName(strongest.b, memberMap))}</b></article>
      </div>
      <div class="relation-node-grid">
        ${topNodes.map((node) => relationNodeCard(node, memberMap)).join("")}
      </div>
      <div class="relation-edge-list">
        ${pairs.map((edge) => relationEdgeRow(edge, memberMap, maxWeight)).join("")}
      </div>
      ${hiddenCount ? `<p class="muted relation-map-note">还有 ${escapeHtml(hiddenCount)} 条较弱关系未展开，可在群聊观测继续积累后查看。</p>` : ""}
    </div>
  `;
}

export function relationshipMemberMap(groupMembers = {}) {
  const map = new Map();
  const worldbookMembers = state.overview?.worldbook?.members || [];
  worldbookMembers.forEach((item) => {
    const id = String(item.user_id || "").trim();
    if (!id) return;
    map.set(id, {
      name: item.name || id,
      aliases: Array.isArray(item.aliases) ? item.aliases : [],
      observed: Array.isArray(item.observed_names) ? item.observed_names : [],
      source: "关系网",
    });
  });
  Object.entries(groupMembers || {}).forEach(([id, raw]) => {
    if (!id) return;
    const item = raw && typeof raw === "object" ? raw : {};
    const existing = map.get(String(id)) || {};
    map.set(String(id), {
      name: existing.name || item.name || item.nickname || item.card || id,
      aliases: existing.aliases || [],
      observed: existing.observed || [],
      source: existing.source || "群聊",
    });
  });
  return map;
}

export function relationNodeName(id, memberMap) {
  const item = memberMap.get(String(id));
  return item?.name || String(id);
}

export function relationNodeCard(node, memberMap) {
  const member = memberMap.get(String(node.id)) || {};
  const name = member.name || node.id;
  const subNames = [...(member.aliases || []), ...(member.observed || [])].filter(Boolean).slice(0, 3);
  return `
    <article class="relation-node-card">
      <div class="relation-avatar">${escapeHtml(shortName(name, 2))}</div>
      <div>
        <b>${escapeHtml(name)}</b>
        <code>${escapeHtml(node.id)}</code>
        ${subNames.length ? `<small>${subNames.map((item) => escapeHtml(item)).join(" / ")}</small>` : `<small>${escapeHtml(member.source || "群聊成员")}</small>`}
      </div>
      <span>${escapeHtml(node.degree)} 边</span>
    </article>
  `;
}

export function relationEdgeRow(edge, memberMap, maxWeight) {
  const pct = Math.max(4, Math.round((edge.weight / maxWeight) * 100));
  const leftName = relationNodeName(edge.a, memberMap);
  const rightName = relationNodeName(edge.b, memberMap);
  return `
    <article class="relation-edge-row">
      <div class="relation-edge-main">
        <b title="${escapeHtml(edge.a)}">${escapeHtml(leftName)}</b>
        <span>↔</span>
        <b title="${escapeHtml(edge.b)}">${escapeHtml(rightName)}</b>
      </div>
      <div class="relation-edge-meter"><i style="width:${pct}%"></i></div>
      <div class="relation-edge-meta">
        <code>${escapeHtml(edge.a)}</code>
        <code>${escapeHtml(edge.b)}</code>
        <span>${escapeHtml(edge.kind || "互动")} · ${escapeHtml(edge.weight)}</span>
      </div>
      ${edge.summary ? `<p>${escapeHtml(edge.summary)}</p>` : ""}
    </article>
  `;
}

export function groupMessageActivityView(messages) {
  const recent = (Array.isArray(messages) ? messages : [])
    .map(normalizeGroupMessage)
    .filter((item) => item.text || item.sender || item.timestamp)
    .slice(-24);
  if (!recent.length) return `<div class="empty small">暂无最近消息</div>`;
  const now = Math.floor(Date.now() / 1000);
  const buckets = Array.from({ length: 6 }, (_, index) => ({
    label: index === 5 ? "现在" : `-${(5 - index) * 2}h`,
    count: 0,
  }));
  recent.forEach((item) => {
    if (!item.timestamp) {
      buckets[5].count += 1;
      return;
    }
    const diffHours = Math.max(0, Math.floor((now - item.timestamp) / 3600));
    const index = Math.max(0, Math.min(5, 5 - Math.floor(diffHours / 2)));
    buckets[index].count += 1;
  });
  const max = Math.max(1, ...buckets.map((item) => item.count));
  const uniqueSpeakers = new Set(recent.map((item) => item.sender || item.senderId).filter(Boolean)).size;
  const latest = recent[recent.length - 1] || {};
  const displayRows = recent.slice(-8).reverse();
  return `
    <div class="group-message-activity">
      <div class="group-message-summary">
        <article><span>最近消息</span><b>${escapeHtml(recent.length)}</b></article>
        <article><span>说话人数</span><b>${escapeHtml(uniqueSpeakers || "-")}</b></article>
        <article><span>最后活跃</span><b>${escapeHtml(latest.displayTime || "刚刚")}</b></article>
      </div>
      <div class="group-activity-bars">
        ${buckets.map((item) => `
          <span title="${escapeHtml(`${item.label}：${item.count} 条`)}">
            <i style="height:${Math.max(8, Math.round((item.count / max) * 100))}%"></i>
            <small>${escapeHtml(item.label)}</small>
          </span>
        `).join("")}
      </div>
      <div class="group-message-list">
        ${displayRows.map((item) => `
          <article>
            <div>
              <b>${escapeHtml(item.sender || "群友")}</b>
              <time>${escapeHtml(item.displayTime || "")}</time>
            </div>
            <p>${escapeHtml(item.text || "[非文本消息]")}</p>
          </article>
        `).join("")}
      </div>
    </div>
  `;
}

export function normalizeGroupMessage(item) {
  const raw = item && typeof item === "object" ? item : {};
  const sender = raw.sender_name || raw.nickname || raw.card || raw.name || raw.user_name || raw.sender_id || raw.user_id || "";
  const senderId = raw.sender_id || raw.user_id || raw.qq || "";
  const text = raw.text || raw.message || raw.content || raw.raw_message || raw.summary || "";
  const timestamp = parseMessageTimestamp(raw.ts ?? raw.timestamp ?? raw.time ?? raw.datetime ?? raw.created_at);
  return {
    sender: String(sender || "").trim(),
    senderId: String(senderId || "").trim(),
    text: String(text || "").trim(),
    timestamp,
    displayTime: formatMessageTime(timestamp, raw.time || raw.created_at || raw.datetime || ""),
  };
}

export function parseMessageTimestamp(value) {
  if (value === null || value === undefined || value === "") return 0;
  if (typeof value === "number" && Number.isFinite(value)) return value > 1e12 ? Math.floor(value / 1000) : Math.floor(value);
  const text = String(value).trim();
  if (/^\d+$/.test(text)) {
    const num = Number(text);
    return num > 1e12 ? Math.floor(num / 1000) : Math.floor(num);
  }
  const parsed = Date.parse(text);
  if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
  const fallback = Date.parse(text.replace(/-/g, "/"));
  return Number.isFinite(fallback) ? Math.floor(fallback / 1000) : 0;
}

export function formatMessageTime(timestamp, fallback = "") {
  if (!timestamp) return String(fallback || "").trim();
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) return String(fallback || "").trim();
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function messageTimelineSvg(messages) {
  const recent = Array.isArray(messages) ? messages.slice(-30) : [];
  if (!recent.length) return `<div class="empty small">暂无最近消息</div>`;
  const buckets = Array.from({ length: 12 }, () => 0);
  const now = Math.floor(Date.now() / 1000);
  recent.forEach((item) => {
    const ts = Number(item.ts || item.time || 0);
    const diffHours = ts ? Math.max(0, Math.min(11, Math.floor((now - ts) / 3600))) : 0;
    buckets[11 - diffHours] += 1;
  });
  const max = Math.max(1, ...buckets);
  return `
    <svg class="timeline-svg" viewBox="0 0 360 120">
      ${buckets.map((value, index) => {
        const height = Math.max(4, Math.round((value / max) * 86));
        const x = 16 + index * 28;
        const y = 100 - height;
        return `<rect x="${x}" y="${y}" width="18" height="${height}" rx="4"></rect>`;
      }).join("")}
      <line x1="12" y1="102" x2="348" y2="102"></line>
      <text x="18" y="116">-12h</text>
      <text x="318" y="116">now</text>
    </svg>
  `;
}

export function shortName(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}
