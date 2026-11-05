/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {fetchJson,postJson} from './client.js';
import {foodField,foodTimeValues,formatNumber,formatPercent,syncFoodMenuSelectionUi} from './learning.js';
import {creativeReadingMode,formatCreativeContentByMode,renderBookDetailPanel,scheduleLifecycleLabel} from './life.js';
import {requireSecondClick,runAction,showToast} from './persona.js';
import {toBool} from './schema.js';
import {$,asteriaWorkspaceState,bookshelfPageOrder,creativeOperations,skillOperations,state} from './state.js';
import {bookshelfImageTag,escapeHtml,hydrateBookshelfImages,openTLSNativeWorkspace} from './workspace.js';

export function bindFoodMenuActions() {
  document.querySelectorAll("[data-food-save]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.foodSave || "";
      await runAction(() => postJson("/food_menu/update", {
        id,
        name: foodField(id, "name")?.value || "",
        type: foodField(id, "type")?.value || "",
        category: foodField(id, "category")?.value || "",
        tags: foodField(id, "tags")?.value || "",
        times: foodTimeValues(id),
        aliases: foodField(id, "aliases")?.value || "",
        avoid: foodField(id, "avoid")?.value || "",
        note: foodField(id, "note")?.value || "",
        favorite: Boolean(foodField(id, "favorite")?.checked),
        hidden: Boolean(foodField(id, "hidden")?.checked),
      }), "已保存候选", button);
    });
  });
  document.querySelectorAll("[data-food-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.dataset.foodDelete || "";
      if (!requireSecondClick(button, `food:${id}`, "再次点击删除候选", "再次点击删除")) return;
      await runAction(() => postJson("/food_menu/update", { id, delete: true }), "已删除候选", button);
    });
  });
}

export function bindFoodMenuFeatureActions() {
  document.querySelectorAll("[data-food-select]").forEach((input) => {
    input.addEventListener("change", () => {
      const itemId = String(input.dataset.foodSelect || "");
      if (!itemId) return;
      if (input.checked) state.selectedFoodMenuIds.add(itemId);
      else state.selectedFoodMenuIds.delete(itemId);
      syncFoodMenuSelectionUi({ resetConfirmation: true });
    });
  });
  const selectAll = document.querySelector("[data-food-select-all]");
  if (selectAll instanceof HTMLInputElement) {
    selectAll.addEventListener("change", () => {
      document.querySelectorAll("[data-food-select]").forEach((input) => {
        const itemId = String(input.dataset.foodSelect || "");
        if (!itemId) return;
        if (selectAll.checked) state.selectedFoodMenuIds.add(itemId);
        else state.selectedFoodMenuIds.delete(itemId);
      });
      syncFoodMenuSelectionUi({ resetConfirmation: true });
    });
  }
  const bulkDeleteButton = document.querySelector("[data-food-bulk-delete]");
  if (bulkDeleteButton instanceof HTMLButtonElement) {
    bulkDeleteButton.addEventListener("click", async () => {
      syncFoodMenuSelectionUi();
      const ids = [...state.selectedFoodMenuIds];
      if (!ids.length) {
        showToast("请先选择要删除的候选");
        return;
      }
      const confirmKey = `food-bulk:${ids.slice().sort().join(",")}`;
      if (!requireSecondClick(bulkDeleteButton, confirmKey, `再次点击删除已选的 ${ids.length} 个候选`, "再次点击删除")) return;
      window.clearTimeout(bulkDeleteButton._confirmTimer);
      bulkDeleteButton.textContent = bulkDeleteButton.dataset.originalText || "删除所选";
      delete bulkDeleteButton.dataset.originalText;
      await runAction(
        async () => {
          const response = await postJson("/food_menu/bulk_delete", { ids });
          ids.forEach((itemId) => state.selectedFoodMenuIds.delete(itemId));
          return response;
        },
        "",
        bulkDeleteButton,
      );
    });
  }
  const formEl = $("#foodMenuFeatureAddForm");
  if (formEl) {
    formEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(formEl);
      const name = String(form.get("name") || "").trim();
      if (!name) return;
      const times = Array.from(formEl.querySelectorAll('input[name="times"]:checked')).map((input) => input.value);
      const saved = await runAction(() => postJson("/food_menu/update", {
        name,
        type: form.get("type") || "",
        category: form.get("category") || "",
        tags: form.get("tags") || "",
        times,
        note: form.get("note") || "",
        favorite: Boolean(form.get("favorite")),
        hidden: false,
      }), "已加入候选", event.submitter);
      if (saved) formEl.reset();
    });
  }
  const bulkForm = $("#foodMenuBulkForm");
  if (bulkForm) {
    bulkForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(bulkForm);
      const text = String(form.get("text") || "").trim();
      if (!text) return;
      const saved = await runAction(() => postJson("/food_menu/bulk_update", {
        text,
        favorite: Boolean(form.get("favorite")),
      }), "已批量加入候选", event.submitter);
      if (saved) bulkForm.reset();
    });
  }
  document.querySelectorAll("[data-food-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      const textarea = $("#foodMenuBulkForm")?.querySelector('textarea[name="text"]');
      if (!textarea) return;
      const preset = [
        "兰州拉面",
        "黄焖鸡",
        "楼下麻辣烫",
        "沙县小吃",
        "煎饼果子｜早餐｜快、便宜｜早餐",
        "粥｜清淡｜热乎、清淡｜早餐",
        "奶茶｜甜口｜甜｜加餐",
        "泡面｜应急｜快、热乎｜夜宵",
      ].join("\n");
      textarea.value = textarea.value.trim() ? `${textarea.value.trim()}\n${preset}` : preset;
      textarea.focus();
    });
  });
  document.querySelectorAll("[data-food-feature-save-toggle]").forEach((button) => {
    button.addEventListener("click", async () => {
      await runAction(
        () => postJson("/settings/update", {
          features: { enable_food_menu_recommendation: toBool(state.featureDraft?.enable_food_menu_recommendation) },
        }),
        "已保存吃什么候选开关",
        button,
      );
    });
  });
  bindFoodMenuActions();
  syncFoodMenuSelectionUi();
}

export function skillWindowText(growth) {
  return `最近返回 ${(growth.items || []).length} 项 / 记录总数 ${growth.skill_count ?? 0} 项；最多返回 120 项，每项最近 4 条成长记录。${growth.enabled ? "成长已开启" : "成长未开启，原记录保留"}。${growth.schedule_influence && growth.enabled ? "日程参考开启" : "日程参考未开启"}；被动提示${growth.passive_injection && growth.enabled ? "开启" : "未开启"}。`;
}

export function filterSkillRecords() {
  const query = String($("#skillSearch")?.value || "").trim().toLocaleLowerCase();
  const status = $("#skillFilter")?.value || "all";
  let visible = 0;
  $("#skillGrowthPanel")?.querySelectorAll("[data-skill-record]").forEach((card) => {
    const match = (!query || String(card.dataset.skillSearch || "").includes(query))
      && (status === "all" || (status === "hidden" && card.dataset.skillHidden === "true")
        || (status === "frozen" && card.dataset.skillFrozen === "true")
        || (status === "normal" && card.dataset.skillHidden !== "true" && card.dataset.skillFrozen !== "true"));
    card.hidden = !match;
    if (match) visible++;
  });
  $("#skillGrowthPanel")?.querySelectorAll(".skill-category-group").forEach((group) => {
    group.hidden = !Array.from(group.querySelectorAll("[data-skill-record]")).some((card) => !card.hidden);
  });
  if ($("#skillFilterCount")) $("#skillFilterCount").textContent = `本页匹配 ${visible} 项；只查找已返回的名称、分类、关键词和别名。筛选保留本页输入。`;
}

export function renderSkillGrowth() {
  const growth = state.overview?.skill_growth || {};
  const items = Array.isArray(growth.items) ? growth.items : [];
  const panel = $("#skillGrowthPanel");
  if (!panel) return;
  if ($("#skillGrowthSummary")) $("#skillGrowthSummary").textContent = `${growth.skill_count ?? items.length} 项 · ${growth.enabled ? "成长开启" : "成长未开启"}`;
  panel.innerHTML = `
    <p id="skillWindowInfo" class="skill-window-info">${escapeHtml(skillWindowText(growth))}</p>
    <div class="skill-growth-head"><span>成长倍率 ${escapeHtml(growth.rate || 1)}</span><span>隐藏 ${escapeHtml(growth.hidden_count || 0)} 项</span><span>冻结 ${escapeHtml(growth.frozen_count || 0)} 项</span></div>
    <div class="skill-filters"><label>查找记录 <input id="skillSearch" type="search" placeholder="名称、分类、关键词或别名" /></label><label>状态 <select id="skillFilter"><option value="all">全部状态</option><option value="normal">未隐藏、未冻结</option><option value="hidden">已隐藏</option><option value="frozen">已冻结</option></select></label></div>
    <p id="skillFilterCount" class="skill-window-info"></p>
    <div class="skill-category-list">${items.length ? renderSkillCategoryGroups(items) : '<div class="empty small">暂无返回的技能记录</div>'}</div>`;
  $("#skillSearch")?.addEventListener("input", filterSkillRecords);
  $("#skillFilter")?.addEventListener("change", filterSkillRecords);
  bindSkillGrowthActions();filterSkillRecords();
  skillOperations.forEach((_value, key) => renderSkillOperation(key));
}

export function skillResultMarkup(op) {
  if (!op) return "";
  const details = op.record ? `<details><summary>本次返回的记录</summary><dl>${[
    ["标识", op.record.id], ["名称 / 分类", `${op.record.name} / ${op.record.category}`],
    ["等级 / 经验", `${op.record.level_title} / ${op.record.exp}`],
    ["关键词", (op.record.keywords || []).join("、")], ["别名", (op.record.aliases || []).join("、")],
    ["隐藏 / 冻结", `${op.record.hidden ? "隐藏" : "未隐藏"} / ${op.record.frozen ? "冻结" : "未冻结"}`]
  ].map(([k,v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v || "未记录")}</dd>`).join("")}</dl></details>` : "";
  return `<p>${escapeHtml(op.message)}</p>${details}`;
}

export function renderSkillOperation(key) {
  const op = skillOperations.get(key);
  const container = key === "$add" ? $("#skillAddForm") : skillField(key, "save")?.closest(".skill-editor");
  if (!container || !op) return;
  const box = container.querySelector(".skill-operation-result");
  if (box) { box.innerHTML = skillResultMarkup(op); box.dataset.status = op.status; }
  container.querySelectorAll(key === "$add" ? '[type="submit"]' : '[data-skill-save], [data-skill-delete]').forEach((button) => {
    button.disabled = ["pending", "unknown", "removed"].includes(op.status);
  });
}

export function refreshSkillGroupLabels() {
  const growth = state.overview?.skill_growth || {};
  $("#skillGrowthPanel")?.querySelectorAll(".skill-category-group").forEach((group) => {
    const cards = Array.from(group.querySelectorAll("[data-skill-record]"));
    if (!cards.length) {group.remove();return;}
    const current = cards.filter((card) => card.dataset.skillRemoved !== "true").map((card) => (growth.items || []).find((x) => x.id === card.dataset.skillRecord)).filter(Boolean);
    const label = group.querySelector(":scope>summary small");
    if (label) label.textContent = `${current.length} 项当前返回记录${cards.some((x) => x.dataset.skillRemoved === "true") ? " · 含本页移除结果" : ""}`;
  });
  const head = $("#skillGrowthPanel .skill-growth-head");
  if (head) head.innerHTML = `<span>成长倍率 ${escapeHtml(growth.rate || 1)}</span><span>隐藏 ${escapeHtml(growth.hidden_count || 0)} 项</span><span>冻结 ${escapeHtml(growth.frozen_count || 0)} 项</span>`;
}

export function acceptSkillSnapshot(growth, record, deletedId = "") {
  state.overview.skill_growth = growth;
  if ($("#skillWindowInfo")) $("#skillWindowInfo").textContent = skillWindowText(growth);
  if ($("#skillGrowthSummary")) $("#skillGrowthSummary").textContent = `${growth.skill_count} 项 · ${growth.enabled ? "成长开启" : "成长未开启"}`;
  const count = $("#learningTabSkills b");if (count) count.textContent = String(growth.skill_count);
  if (record) {
    let card = skillField(record.id, "save")?.closest(".skill-card");
    const template = document.createElement("template");template.innerHTML = renderSkillCard(record);
    const fresh = template.content.firstElementChild;
    if (card) {
      [".skill-card-toggle header", ".skill-level-line", ".skill-meter", ".skill-reading"].forEach((selector) => {
        const a = card.querySelector(selector), b = fresh.querySelector(selector);if (a && b) a.replaceWith(b);
      });
      for (const name of ["skillSearch", "skillHidden", "skillFrozen"]) card.dataset[name] = fresh.dataset[name];
      card.classList.toggle("is-hidden-skill", Boolean(record.hidden));card.classList.toggle("is-frozen-skill", Boolean(record.frozen));
      const category = record.category || "能力";
      if (card.closest("[data-skill-category-name]")?.dataset.skillCategoryName !== category) {
        const list = $("#skillGrowthPanel .skill-category-list");
        let group = Array.from(list.querySelectorAll("[data-skill-category-name]")).find((x) => x.dataset.skillCategoryName === category);
        if (!group) {
          const shell = document.createElement("template");shell.innerHTML = renderSkillCategoryGroups([record]);group = shell.content.firstElementChild;
          group.querySelector(".skill-growth-grid").replaceChildren();list.append(group);
        }
        group.open = true;group.querySelector(".skill-growth-grid").append(card);
      }
    } else {
      const list = $("#skillGrowthPanel .skill-category-list");
      const group = Array.from(list?.querySelectorAll("[data-skill-category-name]") || []).find((x) => x.dataset.skillCategoryName === (record.category || "能力"));
      if (group) group.querySelector(".skill-growth-grid").append(fresh);
      else { list?.querySelector(".empty")?.remove();list?.insertAdjacentHTML("beforeend", renderSkillCategoryGroups([record])); }
      bindSkillGrowthActions();
    }
  }
  if (deletedId) {
    const card = skillField(deletedId, "save")?.closest(".skill-card");
    if (card) {card.dataset.skillRemoved = "true";const label = card.querySelector(".skill-level-line");if (label) label.textContent = "本次返回：此记录已移除；下方保留本页输入与结果。";}
  }
  refreshSkillGroupLabels();filterSkillRecords();
}

export async function saveSkillRecord(payload, container, button, adding = false) {
  const key = adding ? "$add" : payload.id;
  if (["pending", "unknown", "removed"].includes(skillOperations.get(key)?.status)) return;
  const initialForm = adding ? JSON.stringify(Array.from(new FormData(container).entries())) : "";
  const op = {status:"pending", message:"正在提交这条记录…"};skillOperations.set(key, op);renderSkillOperation(key);
  showToast(op.message);
  try {
    const result = await postJson("/skill/update", payload);
    const growth = result?.skill_growth;
    if (!growth || !Array.isArray(growth.items) || typeof growth.enabled !== "boolean" || !Number.isFinite(growth.skill_count)
      || (payload.delete && typeof result.changed !== "boolean")) throw new Error("返回记录或删除结果不完整");
    const normalizedName = String(payload.name || "").trim().replace(/\s+/g, " ").slice(0, 32);
    const record = payload.delete ? null : growth.items.find((item) => payload.id ? item.id === payload.id : item.name === normalizedName);
    if (!payload.delete && (!record || typeof record.id !== "string" || !Number.isFinite(record.exp) || !Number.isFinite(record.level)
      || typeof record.hidden !== "boolean" || typeof record.frozen !== "boolean" || !Array.isArray(record.keywords) || !Array.isArray(record.aliases))) throw new Error("当前返回窗口未提供可核对的目标记录");
    op.status = payload.delete ? "removed" : "accepted";op.record = record;
    op.message = payload.delete ? (result.changed ? "服务已接受删除；仅移除此技能记录。" : "目标记录已不存在，本次没有删除记录。") : "服务已接受更新；下面是本次返回值。当前输入保留，未再次提交。";
    op.message += " 后台沿原机制延后保存，此回执不证明已落盘。";
    acceptSkillSnapshot(growth, record, payload.delete ? payload.id : "");
    if (adding && container.isConnected && JSON.stringify(Array.from(new FormData(container).entries())) === initialForm) container.reset();
    showToast(payload.delete && !result.changed ? "目标已不存在，本次没有删除记录" : payload.delete ? "服务已接受删除" : "服务已接受更新");
  } catch (error) {
    op.status = "unknown";op.message = `结果未确认：${error.message}。本页输入保留，未自动重试；请先核对记录再操作。刷新后相同内容也不能证明此次操作已落盘。`;
    showToast("技能操作结果未确认，输入已保留", "error");
  } finally { renderSkillOperation(key); }
}

export function renderPersonalGoals() {
  const goals = state.overview?.personal_goals || {};
  const panel = $("#personalGoalPanel");
  if (!panel) return;
  const items = Array.isArray(goals.items) ? goals.items : [];
  if (!items.length) {
    panel.innerHTML = `<div class="empty small">没有旧个人目标历史。新目标和日常推进请到 TLS 个人目标维护。</div>`;
    return;
  }
  panel.innerHTML = `<div class="skill-growth-head"><span>历史进行中 ${escapeHtml(goals.active_count || 0)}</span><span>历史已完成 ${escapeHtml(goals.completed_count || 0)}</span><span>旧记录只读 · 不再由此处推进</span></div><div class="skill-growth-grid">${items.map((item) => `
    <article class="skill-card is-collapsed">
      <button type="button" class="skill-card-toggle" data-goal-toggle aria-expanded="false"><header><div><span>${escapeHtml(item.category || "生活")}</span><h3>${escapeHtml(item.title || "未命名目标")}</h3></div><b>${escapeHtml(item.status_label || "进行中")}</b></header></button>
      <div class="skill-level-line"><span>${escapeHtml(item.next_step ? `下一步：${item.next_step}` : "尚未填写下一步")}</span><small>${escapeHtml(item.progress || 0)}%</small></div>
      <div class="skill-meter"><i style="width:${escapeHtml(item.progress || 0)}%"></i></div>
      <div class="skill-card-body">
        ${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}
        <div class="skill-meta"><span>最近推进 ${escapeHtml(item.last_progress || "暂无")}</span><span>每次 +${escapeHtml(item.auto_step || 10)}%</span></div>
        ${Array.isArray(item.recent_logs) && item.recent_logs.length ? `<div class="skill-log">${item.recent_logs.slice().reverse().map((log) => `<p><b>${escapeHtml(log.kind === "manual_progress" ? "手动" : `到 ${log.progress || 0}%`)}</b><span>${escapeHtml(log.evidence || "进度记录")}</span><small>${escapeHtml(log.time || "")}</small></p>`).join("")}</div>` : ""}
        <details class="skill-editor"><summary>历史定义</summary><p>匹配词：${escapeHtml((item.keywords || []).join("、") || "未记录")}</p><p>旧资料保留，不直接写入新的完整会话范围。</p><button type="button" data-tls-native-entry="personal_goals">打开 TLS 个人目标管理</button></details>
      </div>
    </article>`).join("")}</div>`;
  bindPersonalGoalActions();
}

export function goalField(id, field) {
  return document.querySelector(`[data-goal-${field}="${CSS.escape(id)}"]`);
}

export function bindPersonalGoalActions() {
  document.querySelectorAll("[data-goal-toggle]").forEach((button) => button.addEventListener("click", () => {
    const card = button.closest(".skill-card");
    if (!card) return;
    const collapsed = card.classList.toggle("is-collapsed");
    button.setAttribute("aria-expanded", String(!collapsed));
  }));
}

export function renderSkillCategoryGroups(items) {
  const groups = new Map();
  items.forEach((item) => {
    const category = String(item.category || "能力").trim() || "能力";
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(item);
  });
  return Array.from(groups.entries()).map(([category, groupItems]) => {
    const maxItem = groupItems.reduce((best, item) => Number(item.level || 1) > Number(best.level || 1) ? item : best, groupItems[0]);
    const totalTraining = groupItems.reduce((sum, item) => sum + Number(item.training_count || 0), 0);
    const hiddenCount = groupItems.filter((item) => item.hidden).length;
    const frozenCount = groupItems.filter((item) => item.frozen).length;
    return `
      <details class="skill-category-group ${escapeHtml(categorySlug(category))}" data-skill-category-name="${escapeHtml(category)}">
        <summary>
          <span>${escapeHtml(category)}</span>
          <small>${escapeHtml(groupItems.length)} 项｜最好 ${escapeHtml(maxItem?.level_title || "能力状态")}｜训练 ${escapeHtml(totalTraining)} 次${hiddenCount ? `｜隐藏 ${escapeHtml(hiddenCount)}` : ""}${frozenCount ? `｜冻结 ${escapeHtml(frozenCount)}` : ""}</small>
        </summary>
        <div class="skill-growth-grid">
          ${groupItems.map(renderSkillCard).join("")}
        </div>
      </details>
    `;
  }).join("");
}

export function renderSkillCard(item) {
  const logs = Array.isArray(item.recent_logs) ? item.recent_logs : [];
  const badges = [
    item.hidden ? "已隐藏" : "",
    item.frozen ? "已冻结" : "",
  ].filter(Boolean);
  return `
    <article class="skill-card is-collapsed ${item.hidden ? "is-hidden-skill" : ""} ${item.frozen ? "is-frozen-skill" : ""}" data-skill-record="${escapeHtml(item.id || "")}" data-skill-search="${escapeHtml([item.name, item.category, ...(item.keywords || []), ...(item.aliases || [])].join(" ").toLocaleLowerCase())}" data-skill-hidden="${Boolean(item.hidden)}" data-skill-frozen="${Boolean(item.frozen)}">
      <button type="button" class="skill-card-toggle" data-skill-toggle aria-expanded="false">
        <header>
          <div>
            <span>${escapeHtml(item.category || "能力")}</span>
            <h3>${escapeHtml(item.name || "未命名技能")}</h3>
          </div>
          <b>${escapeHtml(item.level_title || "能力状态")}</b>
        </header>
      </button>
      <div class="skill-level-line">
        <span>${badges.length ? badges.map((badge) => `<em>${escapeHtml(badge)}</em>`).join("") : "能力状态"}</span>
        <small>${escapeHtml(item.next_exp ? `${item.exp}/${item.next_exp}` : `${item.exp}`)}</small>
      </div>
      <div class="skill-meter"><i style="width:${escapeHtml(item.progress || 0)}%"></i></div>
      <div class="skill-card-body">
        <div class="skill-reading"><p>${escapeHtml(item.description || "")}</p>
        <div class="skill-meta">
          <span>训练 ${escapeHtml(item.training_count || 0)} 次</span>
          <span>最近 ${escapeHtml(item.last_trained || "未训练")}</span>
        </div>
        ${logs.length ? `
          <div class="skill-log">
            ${logs.slice().reverse().map((log) => `
              <p><b>${escapeHtml(log.level_up ? "升级" : `+${log.exp || 0}`)}</b><span>${escapeHtml(log.activity || "日程练习")}</span><small>${escapeHtml(log.time || "")}</small></p>
            `).join("")}
          </div>
        ` : ""}
        </div><details class="skill-editor">
          <summary>编辑这条记录</summary><p class="skill-editor-note">等级由经验确定；选等级只补足经验下限。已有记录填 0 会保留原经验。冻结后仍可作为角色提示与日程参考，隐藏则退出这些参考及自动成长。</p>
          <div class="skill-editor-grid">
            <label>名称 <input data-skill-name="${escapeHtml(item.id || "")}" value="${escapeHtml(item.name || "")}" maxlength="32" /></label>
            <label>分类 <input data-skill-category="${escapeHtml(item.id || "")}" value="${escapeHtml(item.category || "")}" maxlength="20" /></label>
            <label>等级
              <select data-skill-level="${escapeHtml(item.id || "")}">
                ${[1, 2, 3, 4, 5, 6].map((level) => `<option value="${level}" ${Number(item.level || 1) === level ? "selected" : ""}>${escapeHtml(skillLevelLabel(level))}</option>`).join("")}
              </select>
            </label>
            <label>经验 <input data-skill-exp="${escapeHtml(item.id || "")}" type="number" min="0" step="0.01" value="${escapeHtml(item.exp || 0)}" /></label>
            <label class="wide-field">关键词 <input data-skill-keywords="${escapeHtml(item.id || "")}" value="${escapeHtml((item.keywords || []).join(", "))}" maxlength="180" /></label>
            <label class="wide-field">合并别名 <input data-skill-aliases="${escapeHtml(item.id || "")}" value="${escapeHtml((item.aliases || []).join(", "))}" maxlength="180" placeholder="同义叫法会合并到这项技能" /></label>
            <label class="check-field"><input data-skill-hidden="${escapeHtml(item.id || "")}" type="checkbox" ${item.hidden ? "checked" : ""} /> 隐藏：不参与日程、注入和自动成长</label>
            <label class="check-field"><input data-skill-frozen="${escapeHtml(item.id || "")}" type="checkbox" ${item.frozen ? "checked" : ""} /> 冻结成长：保留能力状态，但不再自动加经验</label>
          </div>
          <div class="skill-operation-result" role="status" aria-live="polite"></div>
          <div class="skill-editor-actions">
            <button type="button" data-skill-save="${escapeHtml(item.id || "")}">保存技能</button>
            <button type="button" class="danger-outline" data-skill-delete="${escapeHtml(item.id || "")}">删除</button>
          </div>
        </details>
      </div>
    </article>
  `;
}

export function skillExpFloor(level) {
  return { 1: 0, 2: 100, 3: 260, 4: 520, 5: 900, 6: 1400 }[Number(level || 1)] || 0;
}

export function skillLevelLabel(level) {
  return {
    1: "一窍不通",
    2: "会一点点",
    3: "勉强能做",
    4: "基本熟练",
    5: "很熟练",
    6: "很有心得",
  }[Number(level || 1)] || "能力状态";
}

export function skillField(id, field) {
  return document.querySelector(`[data-skill-${field}="${CSS.escape(id)}"]`);
}

export function bindSkillGrowthActions() {
  document.querySelectorAll("[data-skill-toggle]:not([data-skill-bound])").forEach((button) => {
    button.dataset.skillBound = "true";
    button.addEventListener("click", () => {
      const card = button.closest(".skill-card");
      if (!card) return;
      const collapsed = card.classList.toggle("is-collapsed");
      button.setAttribute("aria-expanded", String(!collapsed));
    });
  });
  document.querySelectorAll("[data-skill-level]:not([data-skill-bound])").forEach((select) => {
    select.dataset.skillBound = "true";
    select.addEventListener("change", () => {
      const id = select.dataset.skillLevel || "";
      const expInput = skillField(id, "exp");
      if (expInput && Number(expInput.value || 0) < skillExpFloor(select.value)) {
        expInput.value = String(skillExpFloor(select.value));
      }
    });
  });
  document.querySelectorAll("[data-skill-save]:not([data-skill-bound])").forEach((button) => {
    button.dataset.skillBound = "true";
    button.addEventListener("click", async () => {
      const id = button.dataset.skillSave || "";
      await saveSkillRecord({
        id,
        name: skillField(id, "name")?.value || "",
        category: skillField(id, "category")?.value || "",
        level: Number(skillField(id, "level")?.value || 1),
        exp: Number(skillField(id, "exp")?.value || 0),
        keywords: skillField(id, "keywords")?.value || "",
        aliases: skillField(id, "aliases")?.value || "",
        hidden: Boolean(skillField(id, "hidden")?.checked),
        frozen: Boolean(skillField(id, "frozen")?.checked),
      }, button.closest(".skill-editor"), button);
    });
  });
  document.querySelectorAll("[data-skill-delete]:not([data-skill-bound])").forEach((button) => {
    button.dataset.skillBound = "true";
    button.addEventListener("click", async () => {
      const id = button.dataset.skillDelete || "";
      if (!requireSecondClick(button, `skill:${id}`, "再次点击删除技能", "再次点击删除")) return;
      await saveSkillRecord({ id, delete: true }, button.closest(".skill-editor"), button);
    });
  });
}

export function renderLifeHero(daily, life) {
  const energy = Number(daily.energy || 0);
  const pct = Math.max(0, Math.min(100, energy));
  const energyText = roleplayEnergyLabel(daily.energy);
  $("#lifeEnergy").textContent = energyText || "--";
  $("#lifeEnergy").title = daily.energy === undefined || daily.energy === "" ? "" : `心理能量 ${formatNumber(energy)}/100`;
  $("#lifeEnergyBar").style.width = `${pct}%`;
  $("#lifeEnergyBar").title = $("#lifeEnergy").title;
  $("#lifeSnapshotMeta").textContent = daily.date ? `状态记录日期：${daily.date}` : "状态记录日期：未记录";
  $("#lifeMood").textContent = normalizeRoleplayStateText(daily.mood_bias) || "未记录情绪";
  $("#lifeNote").textContent = daily.note || daily.sleep || "暂无额外备注";
  $("#lifeLocation").textContent = daily.location ? normalizeLocationText(daily.location) : "未记录位置";
  $("#lifeWeather").textContent = daily.weather || "未记录天气";
  const current = life.current_plan || {};
  $("#lifeCurrentActivity").textContent = current.activity || "暂无当前日程";
  $("#lifeCurrentSeed").textContent = [current.end ? `${current.time}-${current.end}` : current.time, scheduleLifecycleLabel(current.lifecycle), current.mood, current.message_seed].filter(Boolean).join(" · ") || "暂无细节";
}

export function roleplayEnergyLabel(value) {
  if (value === undefined || value === null || value === "") return "";
  const energy = Number(value);
  if (!Number.isFinite(energy)) return normalizeRoleplayStateText(value);
  if (energy < 35) return "完全没精神";
  if (energy < 55) return "提不起劲";
  if (energy > 84) return "很精神";
  if (energy > 70) return "精神还不错";
  return "状态一般";
}

export function normalizeLocationText(value) {
  const text = String(value || "").trim();
  if (!text || text === "地点感平稳" || text === "地点无明显变化") return "随当前日程变化";
  return text;
}

export function normalizeRoleplayStateText(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const replacements = {
    "黏人": "粘人",
    "睡眠平稳": "睡得很踏实",
    "饥饿感平稳": "无饥饿感",
    "无明显周期影响": "不处于生理期",
  };
  return replacements[text] || text;
}

export function normalizeDailyStateForDisplay(daily) {
  if (!daily || typeof daily !== "object") return {};
  const result = { ...daily };
  ["mood_bias", "sleep", "hunger", "body_cycle"].forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(result, key)) {
      result[key] = normalizeRoleplayStateText(result[key]);
    }
  });
  return result;
}

export function renderDreamCard(dream) {
  const hasRecord = [dream.date, dream.generated_at, dream.label, dream.content, dream.dream_type, dream.afterglow]
    .some((value) => String(value || "").trim());
  const meta = [
    dream.dream_type || (hasRecord ? "类型未记录" : ""),
    dream.mood ? `情绪 ${dream.mood}` : "",
    dream.duration_hours ? `${dream.duration_hours} 小时` : "",
    dream.generated_at || dream.date || "",
  ].filter(Boolean).join(" · ");
  $("#dreamMeta").textContent = hasRecord ? meta : "暂无梦境记录";
  const delta = Number(dream.energy_delta || 0);
  const deltaText = delta > 0 ? `精力 +${delta}` : delta < 0 ? `精力 ${delta}` : "精力变化 0";
  $("#dreamAfterglow").textContent = hasRecord ? (dream.afterglow || dream.label || deltaText) : "未记录余韵";
  $("#dreamContent").textContent = dream.content || dream.label || "暂无梦境内容";
  const factors = Array.isArray(dream.factors) ? dream.factors : [];
  $("#dreamFactors").innerHTML = factors.length
    ? factors.map((item) => `<span class="fragment-chip">${escapeHtml(item)}</span>`).join("")
    : `<span class="muted">暂无梦境因子</span>`;
}

export function renderStatePillBoard(daily) {
  const items = [
    ["睡眠", daily.sleep],
    ["睡眠阶段", daily.sleep_phase || daily.sleep_runtime?.label],
    ["梦境", daily.dream],
    ["健康", daily.health],
    ["饥饿", daily.hunger],
    ["生理期状态", daily.body_cycle],
  ].map(([label, value]) => [label, normalizeRoleplayStateText(value)])
    .filter(([, value]) => value !== undefined && value !== "");
  $("#statePillBoard").innerHTML = items.length
    ? items.map(([label, value]) => `
      <span>
        <b>${escapeHtml(label)}</b>
        ${escapeHtml(value || "-")}
      </span>
    `).join("")
    : `<div class="empty small">暂无今日状态</div>`;
}

export function renderDiaryCards(diaries) {
  $("#diaryCards").innerHTML = diaries.length
    ? diaries.slice().reverse().map((item) => {
      const tags = Array.isArray(item.tags) && item.tags.length
        ? item.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")
        : `<span>未标记</span>`;
      return `
        <details class="diary-card">
          <summary><b>${escapeHtml(item.date || "未记录日期")}</b><span>${escapeHtml(item.summary || "展开阅读留存文字")}</span></summary>
          <small>记录时间：${escapeHtml(item.generated_at || "未记录")}</small>
          <p>${escapeHtml(item.body || item.summary || "暂无日记正文")}</p>
          <div class="diary-tags">${tags}</div>
          ${item.share_seed ? `<details class="life-share-seed"><summary>留存分享线索 · 未代表已发送</summary><blockquote>${escapeHtml(item.share_seed)}</blockquote></details>` : ""}
        </details>
      `;
    }).join("")
    : `<div class="empty small">暂无日记</div>`;
}

export function renderDreamFragments(fragments) {
  if (!fragments.length) {
    $("#dreamFragments").innerHTML = `<div class="empty small">暂无梦境碎片</div>`;
    return;
  }
  $("#dreamFragments").innerHTML = fragments.map((item) => {
    const weight = Number(item.weight);
    return `<details class="life-fragment"><summary>${escapeHtml(item.text || "未记录文字")}</summary>
      <dl><dt>原来源</dt><dd>${escapeHtml(item.source || "未记录来源")}</dd>
      <dt>记录时间</dt><dd>${escapeHtml(item.created_at || "未记录时间")}</dd>
      <dt>原权重</dt><dd>${Number.isFinite(weight) ? escapeHtml(weight.toFixed(1)) : "未记录"}</dd></dl></details>`;
  }).join("");
}

export function renderCreativeStatusBar(selector, chips) {
  const el = $(selector);
  if (!el) return;
  if (!Array.isArray(chips) || !chips.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = chips.map((chip) => {
    const tone = chip.tone || "info";
    const isOff = tone === "off";
    return `<span class="creative-chip ${escapeHtml(tone)}"${isOff ? ' data-off="1"' : ""}>
      <small>${escapeHtml(chip.label || "")}</small>
      <b>${escapeHtml(chip.value || "")}</b>
    </span>`;
  }).join("");
}

export function renderBookshelf() {
  const creative = state.overview?.creative || {};
  const bookshelf = state.bookshelfUnlocked || state.overview?.bookshelf || {};
  const privateReading = state.overview?.private_reading || {};
  const settings = state.overview?.settings || {};
  $("#bookshelfPublicCount").textContent = bookshelf.public_count ?? creative.project_count ?? 0;
  $("#bookshelfSecretCount").textContent = bookshelf.secret_count ?? 0;
  $("#bookshelfDiaryCount").textContent = bookshelf.diary_count ?? 0;
  $("#bookshelfJmCount").textContent = bookshelf.jm_album_count ?? 0;
  const memoNotes = bookshelf.memo_notes || {};
  $("#bookshelfMemoCount").textContent = memoNotes.active ?? 0;
  $("#bookshelfMemoSummary").textContent = "旧便签历史只读 · 提醒统一在 TLS 维护";
  $("#bookshelfLockState").textContent = bookshelf.unlocked ? "已解锁" : "未解锁";
  const passwordHint = String(bookshelf.password_hint || "").trim();
  const passwordHintEl = $("#bookshelfPasswordHint");
  if (passwordHintEl) {
    passwordHintEl.textContent = passwordHint ? `提示：${passwordHint}` : "";
    passwordHintEl.hidden = !passwordHint;
  }
  $("#bookshelfIntro").textContent = creative.enabled
    ? "Bot 自主推进的公开创作作品"
    : "创作功能未开启";
  const creativeChips = [];
  creativeChips.push({
    label: "创作",
    value: creative.enabled ? "开启" : "关闭",
    tone: creative.enabled ? "ok" : "off",
  });
  if (creative.enabled) {
    creativeChips.push({
      label: "提起方式",
      value: creative.hidden_mode ? "节点自然提起" : "普通模式",
      tone: "info",
    });
    creativeChips.push({
      label: "灵感触发",
      value: formatPercent(settings.creative_inspiration_probability),
      tone: "metric",
    });
    creativeChips.push({
      label: "节点提起",
      value: formatPercent(settings.creative_share_probability),
      tone: "metric",
    });
    creativeChips.push({
      label: "单次创作",
      value: `${settings.creative_chars_per_session || settings.creative_base_chars_per_hour || 0} 字`,
      tone: "metric",
    });
    creativeChips.push({
      label: "作品封面",
      value: creative.cover_generation_enabled ? "自动生成" : "关闭",
      tone: creative.cover_generation_enabled ? "ok" : "off",
    });
  }
  if (privateReading.available) {
    creativeChips.push({
      label: "夹层阅读",
      value: privateReading.boredom_read_enabled ? "可触发" : "关闭",
      tone: privateReading.boredom_read_enabled ? "ok" : "off",
    });
    creativeChips.push({
      label: "征求推荐",
      value: privateReading.ask_recommendation_enabled ? "可触发" : "关闭",
      tone: privateReading.ask_recommendation_enabled ? "ok" : "off",
    });
  }
  renderCreativeStatusBar("#creativeSettings", creativeChips);
  renderMemoNotes(memoNotes);
  const publicBooks = bookshelf.public_books || [];
  $("#bookshelfPublicBooks").innerHTML = publicBooks.length
    ? renderBookCategoryShelves(publicBooks, { emptyText: "上层书架为空", reverseBooks: true })
    : `<div class="empty">上层书架为空</div>`;
  const secretBooks = bookshelf.secret_books || [];
  $("#bookshelfSecretBooks").innerHTML = bookshelf.unlocked
    ? renderUnlockedDrawer(secretBooks)
    : renderLockedDrawer(bookshelf.secret_count || 0);
  renderBookshelfPage();
  void hydrateBookshelfImages(document);
}

export function memoRepeatLabel(value) {
  return {
    daily: "每天",
    weekly: "每周",
    monthly: "每月",
    yearly: "每年",
  }[String(value || "none")] || "";
}

export function memoDueLabel(note) {
  if (note.status === "completed") return "已完成";
  return {
    overdue: "已逾期",
    due: "即将到期",
    today: "24 小时内",
    upcoming: note.due_text || "已安排",
    none: "无到期时间",
  }[note.due_state] || note.due_text || "无到期时间";
}

export function renderMemoNotes(memoNotes = {}) {
  const items = Array.isArray(memoNotes.items) ? memoNotes.items : [];
  const filter = state.memoFilter || "active";
  const visible = items.filter((item) => {
    if (filter === "completed") return item.status === "completed";
    if (filter === "active") return item.status !== "completed";
    return true;
  });
  $("#memoActiveCount").textContent = memoNotes.active ?? items.filter((item) => item.status !== "completed").length;
  $("#memoAllCount").textContent = memoNotes.total ?? items.length;
  $("#memoCompletedCount").textContent = memoNotes.completed ?? items.filter((item) => item.status === "completed").length;
  $("#memoDueHint").textContent = "历史日期仅供查阅，不代表当前提醒队列。";
  $("#memoWorkspaceMeta").textContent = memoNotes.active
    ? `${memoNotes.active} 张进行中${memoNotes.completed ? ` · ${memoNotes.completed} 张已完成` : ""}`
    : memoNotes.completed ? `${memoNotes.completed} 张已完成` : "暂无进行中便签";
  document.querySelectorAll("[data-memo-filter]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.memoFilter === filter);
  });
  const root = $("#memoNoteGrid");
  if (!root) return;
  root.innerHTML = visible.length
    ? visible.map((note) => {
      const repeat = memoRepeatLabel(note.repeat);
      const title = note.title || String(note.content || "未命名便签").slice(0, 24);
      const dueClass = note.due_state === "overdue" ? "is-overdue" : "";
      return `
        <article class="memo-note ${escapeHtml(note.color || "yellow")} ${note.pinned ? "is-pinned" : ""} ${note.status === "completed" ? "is-completed" : ""} ${dueClass}">
          <header>
            <h3>${escapeHtml(title)}</h3>
            <span>${escapeHtml(memoDueLabel(note))}</span>
          </header>
          <div class="memo-note-meta">
            ${note.due_text ? `<span>${escapeHtml(note.due_text)}</span>` : ""}
            ${repeat ? `<span>· ${escapeHtml(repeat)}</span>` : ""}
            ${note.remind_enabled ? `<span>· 旧提醒意向（不再执行）</span>` : ""}
          </div>
          <p class="memo-note-content">${escapeHtml(note.content || "没有补充内容")}</p>
          <footer class="memo-note-actions">
            <button type="button" data-tls-native-entry="memo_notes">打开 TLS 备忘便签管理</button>
          </footer>
        </article>
      `;
    }).join("")
    : `<div class="memo-empty">${filter === "completed" ? "还没有已完成便签" : filter === "all" ? "书柜里还没有便签" : "当前没有待处理便签"}</div>`;
}

export function currentMemoNotes() {
  const shelf = state.bookshelfUnlocked || state.overview?.bookshelf || {};
  return Array.isArray(shelf.memo_notes?.items) ? shelf.memo_notes.items : [];
}

export function applyMemoPayload(payload) {
  if (!payload || typeof payload !== "object") return;
  if (state.overview?.bookshelf) state.overview.bookshelf.memo_notes = payload;
  if (state.bookshelfUnlocked) state.bookshelfUnlocked.memo_notes = payload;
}

export function openMemoEditor(note = null) {
  return openTLSNativeWorkspace("memo_notes");
}

export function closeMemoEditor() {
  state.memoEditorId = "";
  const form = $("#memoEditorForm");
  if (form) {
    form.reset();
    form.hidden = true;
  }
}

export async function updateMemoAction(action, note, button) {
  return openTLSNativeWorkspace("memo_notes");
}

export function renderLockedDrawer(count) {
  return `
    <div class="drawer-locked">
      <div class="drawer-face">
        <span></span>
        <i></i>
      </div>
      <div>
        <b>${escapeHtml(count || 0)} 本锁在夹层里</b>
        <p>需要密码</p>
      </div>
    </div>
  `;
}

export function renderUnlockedDrawer(items) {
  if (!items.length) {
    return `<div class="empty small">抽屉已经打开，但里面暂时还没有日记本或私密阅读记录。</div>`;
  }
  return renderBookCategoryShelves(items, {
    reverseBooks: true,
    notes: {
      "日记": "按日期收进同一本里",
      "私密阅读": "只保留标题和阅读印象",
    },
  });
}

export function renderBookCategoryShelves(items, options = {}) {
  const books = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!books.length) return `<div class="empty small">${escapeHtml(options.emptyText || "暂无书籍")}</div>`;
  const groups = [];
  books.forEach((book) => {
    const title = bookshelfCategoryTitle(book);
    let group = groups.find((item) => item.title === title);
    if (!group) {
      group = { title, books: [] };
      groups.push(group);
    }
    group.books.push(book);
  });
  return groups.map((group) => {
    const rowClass = options.rowClass || (group.books.some((book) => book.kind === "diary" || book.kind === "jm_album") ? "drawer-book-row" : "book-row");
    const booksForRender = options.reverseBooks ? group.books.slice().reverse() : group.books;
    const note = options.notes?.[group.title] || bookshelfCategoryNote(group.title, group.books);
    return `
      <section class="drawer-book-group book-category-group ${escapeHtml(categorySlug(group.title))}">
        <header>
          <span>${escapeHtml(group.title)} <b>${escapeHtml(group.books.length)}</b></span>
          ${note ? `<small>${escapeHtml(note)}</small>` : ""}
        </header>
        <div class="${escapeHtml(rowClass)}">${booksForRender.map(renderBookshelfBook).join("")}</div>
      </section>
    `;
  }).join("");
}

export function bookshelfCategoryTitle(book) {
  const raw = String(book?.category || "").trim();
  if (raw) return raw;
  if (book?.kind === "creative") return book.work_type || "创作";
  if (book?.kind === "diary") return "日记";
  if (book?.kind === "browsing") return "浏览记录";
  if (book?.kind === "jm_album") return "私密阅读";
  return "其他";
}

export function bookshelfCategoryNote(title, books) {
  const kind = books[0]?.kind || "";
  if (kind === "browsing") return "新闻阅读和主动搜索会在这里留痕";
  if (kind === "creative") return "";
  if (kind === "diary") return "按日期翻阅";
  if (kind === "jm_album") return "夹层内的私密阅读记录";
  return `${books.length} 本`;
}

export function categorySlug(value) {
  const text = String(value || "category").toLowerCase();
  return text.replace(/[^a-z0-9\u4e00-\u9fff_-]+/g, "-").slice(0, 32) || "category";
}

export function renderBookshelfBook(item) {
  const kind = item.kind || "creative";
  const kindLabel = {
    creative: "创作",
    diary: "日记本",
    browsing: "浏览记录",
    jm_album: "私密阅读",
  }[kind] || kind;
  const bookId = bookshelfBookId(item);
  const title = item.title || "未命名";
  const rawMeta = item.progress || item.created || item.status || item.tone || "";
  const meta = item.progress
    ? String(rawMeta).replace(/\s*\/\s*/g, "/").replace(/\s+字/g, "字")
    : String(rawMeta);
  const metaClass = meta.length > 10 ? "is-long" : "";
  const titleClass = Array.from(String(title)).length > 9 ? "is-long" : "";
  const ariaLabel = [kindLabel, title, meta].filter(Boolean).join("，");
  return `
    <button type="button" class="shelf-book ${escapeHtml(kind)}" data-book-id="${escapeHtml(bookId)}" title="${escapeHtml(title)}" aria-label="${escapeHtml(ariaLabel)}">
      <div class="book-spine">
        <i class="book-shine"></i>
        <b class="${titleClass}">${escapeHtml(title)}</b>
        ${meta ? `<small class="${metaClass}">${escapeHtml(meta)}</small>` : `<small>书柜藏本</small>`}
        <em></em>
      </div>
    </button>
  `;
}

export function bookshelfBookId(item) {
  return `${item.kind || "book"}:${item.id || item.title || ""}`;
}

export async function saveSelectedBookshelfReadingState() {
  const book = state.selectedBook;
  if (!book || book.kind !== "jm_album" || !book.album_id) return;
  const pages = Array.isArray(book.pages) ? book.pages : [];
  const currentPage = Math.min(Math.max(1, Number(state.selectedBookSpreadIndex || 0) + 1), Math.max(1, pages.length));
  const bookmarkInput = document.querySelector("[data-book-bookmark]");
  const bookmark = bookmarkInput instanceof HTMLInputElement ? bookmarkInput.value.trim() : String(book.reading_bookmark || "").trim();
  try {
    const result = await postJson("/bookshelf/reading_state", {
      album_id: book.album_id,
      page: currentPage,
      total_pages: pages.length,
      bookmark,
      access_token: state.bookshelfAccessToken || state.bookshelfUnlocked?.access_token || "",
    });
    state.bookshelfUnlocked = result.bookshelf || state.bookshelfUnlocked;
    state.bookshelfAccessToken = result.bookshelf?.access_token || state.bookshelfAccessToken || "";
    const updated = allBookshelfBooks().find((item) => item.kind === "jm_album" && String(item.album_id || "") === String(book.album_id));
    if (updated) state.selectedBook = updated;
  } catch (error) {
    console.debug("保存阅读进度失败", error);
  }
}

export async function ensureCreativeProjectDetail(book, force = false) {
  if (!book || book.kind !== "creative" || !book.id) return book;
  if (book.project_detail_loaded && !force) return book;
  if (book.project_loading && !force) return book;
  book.project_loading = true;
  book.project_error = "";
  try {
    const detail = await fetchJson(`/creative/project?id=${encodeURIComponent(book.id)}`);
    Object.assign(book, detail || {}, { project_detail_loaded: true, project_loading: false, kind: "creative" });
    if (state.selectedBook && state.selectedBook.id === book.id && state.selectedBook.kind === "creative") {
      state.selectedBook = book;
      renderBookDetailPanel();
    }
    return book;
  } catch (error) {
    book.project_loading = false;
    book.project_error = error.message || String(error || "读取失败");
    if (state.selectedBook && state.selectedBook.id === book.id && state.selectedBook.kind === "creative") {
      state.selectedBook = book;
      renderBookDetailPanel();
    }
    return book;
  }
}

export function renderBookCoverInner(book, kindLabel, title, progress = "") {
  const coverSrc = String(book.cover_src || "");
  const image = coverSrc ? bookshelfImageTag(coverSrc, `${title || "作品"}封面`) : "";
  return `
    ${image}
    <span>${escapeHtml(kindLabel)}</span>
    <b>${escapeHtml(title || "未命名")}</b>
    ${progress ? `<small>${escapeHtml(progress)}</small>` : ""}
  `;
}

export function creativeOperationKey(id, kind) { return `${id}:${kind}`; }

export function creativeResultMarkup(id, kind) {
  const key = creativeOperationKey(id, kind), item = creativeOperations.get(key);
  if (!item) return "";
  return `<p role="status">${escapeHtml(item.message)}</p>
    ${item.readback !== undefined ? `<details><summary>当前读取的内容（不改本页输入）</summary><pre>${escapeHtml(JSON.stringify(item.readback, null, 2))}</pre></details>` : ""}
    ${!item.busy ? `<button type="button" data-creative-readback="${escapeHtml(key)}">仅重新读取当前记录</button>` : ""}`;
}

export function creativeOperationAttrs(id, kind) {
  const item = creativeOperations.get(creativeOperationKey(id, kind));
  return item && (item.busy || item.unknown) ? " disabled" : "";
}

export function creativeOperationView(key) {
  const item = creativeOperations.get(key); if (!item) return;
  document.querySelectorAll('[data-creative-operation]').forEach(el => {
    if (el.dataset.creativeOperation !== key) return;
    const result = el.querySelector('.creative-save-result');
    if (result) result.innerHTML = creativeResultMarkup(item.id, item.kind);
    const submit = el.querySelector('button[type="submit"], [data-creative-reanalyze], [data-creative-rebuild-memory]');
    if (submit) submit.disabled = Boolean(item.busy || item.unknown);
  });
}

export async function readCreativeOperation(key) {
  const item = creativeOperations.get(key); if (!item || item.busy) return;
  try {
    const detail = await fetchJson(`/creative/project?id=${encodeURIComponent(item.id)}`);
    if (!detail || detail.id !== item.id || !Array.isArray(detail.chunks)) throw new Error("作品回读不完整或对象不一致");
    if (item.kind.startsWith('chunk:')) item.readback = detail.chunks.find(c => Number(c.index) === Number(item.kind.slice(6))) || {missing:true};
    else if (item.kind === 'outline') item.readback = detail.outline;
    else if (item.kind === 'characters') item.readback = detail.characters;
    else if (item.kind === 'rebuild') item.readback = detail.creative_memory_pool;
    else if (item.kind === 'reanalyze') item.readback = detail.quality_reviews;
    else item.readback = Object.fromEntries(['title','work_type','tone','point_of_view','target_chars','premise','next_hint'].map(k => [k, detail[k]]));
    const books = allBookshelfBooks();
    books.filter(b => b.kind === 'creative' && b.id === item.id).forEach(b => Object.assign(b, detail, {project_loaded:true,project_error:""}));
    if (state.selectedBook?.kind === 'creative' && state.selectedBook.id === item.id) Object.assign(state.selectedBook, detail, {project_loaded:true,project_error:""});
    item.message = item.unknown ? "本次结果未确认；已读取当前记录，同值不能证明先前操作完成。没有重复提交。" : `${item.confirmed}；当前记录已读取，本页输入保留。`;
  } catch (error) {
    item.message = `${item.unknown ? "本次结果未确认" : item.confirmed}；后续读取失败：${error.message}。本页输入保留。`;
  }
  creativeOperationView(key);
}

export async function saveCreativeOperation(kind, path, payload, label) {
  const id = String(payload.id || ""), key = creativeOperationKey(id, kind), old = creativeOperations.get(key);
  if (old?.busy || old?.unknown) { creativeOperationView(key); return; }
  const item = {id,kind,busy:true,unknown:false,message:"正在提交；后续输入将保留，请勿重复操作。"};
  creativeOperations.set(key,item);creativeOperationView(key);
  try {
    const result = await postJson(path, payload);
    if (!result || result.project_id !== id || (kind === 'basic' && typeof result.changed !== 'boolean')
        || (kind.startsWith('chunk:') && result.chunk_index !== payload.chunk_index)
        || (kind === 'rebuild' && (result.success !== true || !Number.isInteger(result.memory_count) || result.memory_count < 0))
        || (kind === 'reanalyze' && (!result.review || typeof result.review !== 'object'))) throw new Error("操作回执不完整或对象不一致");
    item.confirmed = kind === 'rebuild' ? `已重建本作品内部资料，返回 ${result.memory_count} 条` : kind === 'reanalyze' ? "已返回本次分析；结果仍需阅读" : `已保存${label}${kind === 'basic' && !result.changed ? '（未改变字段）' : ''}`;
    item.busy=false;item.message=item.confirmed;creativeOperationView(key);
    await readCreativeOperation(key);
  } catch(error) {
    item.busy=false;item.unknown=true;item.message=`本次结果未确认：${error.message}。保留本页输入，请先读取当前记录；本页不重复提交。`;
    creativeOperationView(key);
  }
}

export function creativeFold(name, title, content, open=false) {
  return `<details class="creative-workspace-section" data-creative-section="${name}"${open ? ' open' : ''}><summary>${title}</summary><div class="creative-section-body">${content}</div></details>`;
}

export function creativeQualityScore(review, name) {
  const value = review?.[`${name}_score`] ?? review?.scores?.[name];
  return typeof value === 'number' && Number.isFinite(value) ? `${value}/10` : '未记录';
}

export function renderCreativeStoryBible(book) {
  const sb = book.story_bible && typeof book.story_bible === "object" ? book.story_bible : {};
  const list = (items) => Array.isArray(items) && items.length
    ? `<ul>${items.map((item) => `<li>${escapeHtml(String(item || ""))}</li>`).join("")}</ul>`
    : `<div class="empty small">暂无</div>`;
  return `
    <section class="creative-manager-card">
      <h3>故事档案</h3>
      <div class="creative-meta-grid">
        <div><b>主线</b><span>${escapeHtml(sb.mainline_direction || "") || "未建立"}</span></div>
        <div><b>下一步</b><span>${escapeHtml(sb.next_direction || book.next_hint || "") || "未指定"}</span></div>
      </div>
      <div class="creative-columns">
        <div><b>主题</b>${list(sb.active_themes)}</div>
        <div><b>未解决线索</b>${list(sb.unresolved_threads)}</div>
        <div><b>已解决线索</b>${list(sb.resolved_threads)}</div>
        <div><b>重要事实</b>${list(sb.important_facts)}</div>
      </div>
    </section>
  `;
}

export function renderCreativeOutlineEditor(book) {
  const rows = Array.isArray(book.outline) ? book.outline : [];
  return `
    <section class="creative-manager-card">
      <div class="creative-card-head">
        <h3>大纲</h3>
        <span>${rows.length} 条</span>
      </div>
      <form data-creative-outline-form data-project-id="${escapeHtml(book.id || "")}" data-creative-operation="${escapeHtml(creativeOperationKey(book.id, "outline"))}">
        <textarea name="outline" rows="10" placeholder="一行一条大纲；原规则最多 30 条、每条 100 字">${escapeHtml(rows.join("\n"))}</textarea>
        <div class="creative-form-actions">
          <button type="submit"${creativeOperationAttrs(book.id, "outline")}>保存大纲</button>
        </div>
      <div class="creative-save-result">${creativeResultMarkup(book.id, "outline")}</div></form>
    </section>
  `;
}

export function renderCreativeCharactersEditor(book) {
  const chars = Array.isArray(book.characters) ? book.characters : [];
  return `
    <section class="creative-manager-card">
      <div class="creative-card-head">
        <h3>角色</h3>
        <span>${chars.length} 个</span>
      </div>
      <form data-creative-characters-form data-project-id="${escapeHtml(book.id || "")}" data-creative-operation="${escapeHtml(creativeOperationKey(book.id, "characters"))}">
        <textarea name="characters" rows="12" placeholder='[{"name":"角色名","role":"身份","description":"描述"}]'>${escapeHtml(JSON.stringify(chars, null, 2))}</textarea>
        <div class="creative-form-actions">
          <button type="submit"${creativeOperationAttrs(book.id, "characters")}>保存角色</button>
        </div>
      <div class="creative-save-result">${creativeResultMarkup(book.id, "characters")}</div></form>
    </section>
  `;
}

export function renderCreativeQualityPanel(book) {
  const reviews = Array.isArray(book.quality_reviews) ? book.quality_reviews : [];
  const latest = reviews[reviews.length - 1] || {};
  const score = (name) => creativeQualityScore(latest, name);
  const issues = Array.isArray(latest.issues) ? latest.issues : [];
  return `
    <section class="creative-manager-card">
      <div class="creative-card-head">
        <h3>质量分析</h3>

      </div>
      <div class="creative-meta-grid quality">
        <div><b>人格一致</b><span>${escapeHtml(score("persona"))}</span></div>
        <div><b>推进度</b><span>${escapeHtml(score("progress"))}</span></div>
        <div><b>重复度</b><span>${escapeHtml(score("repetition"))}</span></div>
      </div>
      ${issues.length ? `<ul class="creative-issues">${issues.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<div class="empty small">暂无分析结果</div>`}
    </section>
  `;
}

export function renderCreativeChunkEditors(book) {
  const chunks = Array.isArray(book.chunks) ? book.chunks : [];
  return `<p>保留正文换行；每段保存最多 5000 字，超限会拒绝，不自动截断。已有长段仍可完整阅读。</p>
    ${chunks.length ? chunks.map(chunk => `<details class="creative-workspace-chunk" data-creative-chunk="${escapeHtml(chunk.index)}">
      <summary>片段 ${Number(chunk.index)+1} · ${Array.from(String(chunk.text || '')).length} 字${chunk.manually_edited ? ' · 已手改' : ''}</summary>
      <form class="creative-chunk-editor" data-creative-chunk-form data-project-id="${escapeHtml(book.id)}" data-chunk-index="${escapeHtml(chunk.index)}" data-creative-operation="${escapeHtml(creativeOperationKey(book.id, 'chunk:'+chunk.index))}">
        <textarea name="text" rows="10">${escapeHtml(chunk.text || '')}</textarea>
        <button type="submit"${creativeOperationAttrs(book.id, 'chunk:'+chunk.index)}>保存本段</button>
        <div class="creative-save-result">${creativeResultMarkup(book.id, 'chunk:'+chunk.index)}</div>
      </form></details>`).join('') : '<div class="empty small">暂无正文片段</div>'}`;
}

export function renderCreativeManager(book, kindLabel, displayTitle, displayIntro) {
  if (book.project_loading) {
    return `<article class="book-preview subpage creative"><div class="empty">正在加载作品详情...</div></article>`;
  }
  if (book.project_error) {
    return `<article class="book-preview subpage creative"><div class="empty">作品详情加载失败：${escapeHtml(book.project_error)}</div></article>`;
  }
  return `
    <article class="book-preview subpage creative creative-manager-page">
      <div class="book-preview-cover ${book.cover_src ? "has-cover-image" : ""}">
        ${renderBookCoverInner(book, kindLabel, book.title || "未命名")}
      </div>
      <div class="book-preview-info creative-manager-info">
        <nav class="book-breadcrumb">
          <button type="button" data-book-close>书柜</button>
          <span>/ ${escapeHtml(kindLabel)}</span>
        </nav>
        <div class="reader-toolbar">
          <span>${escapeHtml(kindLabel)}</span>
          <button type="button" data-book-close>收回书柜</button>
        </div>
        <h2>${escapeHtml(book.title || displayTitle || "未命名")}</h2><p class="creative-workspace-note">各分区单独保存。收起保留本页输入；保存回读不覆盖继续输入的内容。切换作品、返回预览、刷新或离页不保留未保存输入。原创作来源与访问范围保持。</p><div class="creative-form-actions"><button type="button" data-book-read>阅读全文</button></div>
        <p>${escapeHtml(book.premise || displayIntro || "这本作品还没有简介。")}</p>
        ${creativeFold("basic", "资料与写作偏好", `<form class="inline-form creative-project-basic-form" data-creative-project-form data-project-id="${escapeHtml(book.id || "")}" data-creative-operation="${escapeHtml(creativeOperationKey(book.id, "basic"))}">
          <label>标题 <input name="title" value="${escapeHtml(book.title || "")}" /></label>
          <label>类型 <input name="work_type" value="${escapeHtml(book.work_type || "")}" /></label>
          <label>气质 <input name="tone" value="${escapeHtml(book.tone || "")}" /></label>
          <label>视角 <input name="point_of_view" value="${escapeHtml(book.point_of_view || "")}" /></label>
          <label>目标字数 <input name="target_chars" type="number" min="300" max="5200" value="${escapeHtml(book.target_chars || 2000)}" /></label>
          <label class="wide">核心设定 <textarea name="premise" rows="3">${escapeHtml(book.premise || "")}</textarea></label>
          <label class="wide">下一步提示 <textarea name="next_hint" rows="2">${escapeHtml(book.next_hint || "")}</textarea></label>
          <div class="creative-form-actions wide">
            <button type="submit"${creativeOperationAttrs(book.id, "basic")}>保存作品信息</button>
            <button type="button" class="read-button" data-book-read>进入阅读页</button>
          </div>
        <div class="creative-save-result">${creativeResultMarkup(book.id, "basic")}</div></form>`, true)}
        <div class="creative-form-actions">
          <button type="button" class="danger-outline" data-creative-exit-edit>返回预览</button>

        </div>
        ${creativeFold("story", "故事档案与来源", renderCreativeStoryBible(book) + `<dl class="creative-source"><div><dt>来源</dt><dd>${escapeHtml(book.source || "未记录")}</dd></div><div><dt>来源说明</dt><dd>${escapeHtml(book.source_text || "未记录")}</dd></div><div><dt>最近人工修订</dt><dd>${escapeHtml(book.last_manual_edit_summary || "未记录")}</dd></div></dl><details><summary>已有修订与内部资料（接口窗口）</summary><pre>${escapeHtml(JSON.stringify({revision_notes:book.revision_notes,manual_edits:book.manual_edits,creative_memory_pool:book.creative_memory_pool}, null, 2))}</pre></details>`)}
        ${creativeFold("outline", "大纲编辑", renderCreativeOutlineEditor(book))}
        ${creativeFold("characters", "人物编辑", renderCreativeCharactersEditor(book))}
        ${creativeFold("quality", "留存质量分析", renderCreativeQualityPanel(book))}
        ${creativeFold("chunks", `正文片段 · ${(book.chunks || []).length}`, renderCreativeChunkEditors(book))}
        ${creativeFold("maintenance", "分析、重建与删除", `<p>重新分析会调用模型，检查最新非空片段并保存分析记录；不会自动改正文。单次分析不代表全书质量。</p>
          <div data-creative-operation="${escapeHtml(creativeOperationKey(book.id, 'reanalyze'))}"><button type="button" data-creative-reanalyze="${escapeHtml(book.id)}"${creativeOperationAttrs(book.id, 'reanalyze')}>重新分析</button><div class="creative-save-result">${creativeResultMarkup(book.id, 'reanalyze')}</div></div>
          <p>重建会替换本作品内部的创作资料池，依据近期片段、大纲、人物及人工修订重建；不调用模型，不清理聊天记忆。原窗口最多取 12 段正文、12 条大纲、10 个人物及最近 10 条修订。</p>
          <div data-creative-operation="${escapeHtml(creativeOperationKey(book.id, 'rebuild'))}"><button type="button" data-creative-rebuild-memory="${escapeHtml(book.id)}"${creativeOperationAttrs(book.id, 'rebuild')}>重建作品内部资料</button><div class="creative-save-result">${creativeResultMarkup(book.id, 'rebuild')}</div></div>
          <p>删除会移除作品记录及其中的正文、设定、分析和内部资料；本入口不删除独立封面文件。保留原二次点击确认，不能撤销已开始的操作。</p>
          <button type="button" class="danger-outline" data-book-delete data-book-kind="creative" data-book-id="${escapeHtml(book.id)}" data-book-title="${escapeHtml(book.title)}">删除作品</button>`)}
      </div>
    </article>
  `;
}

export function renderCreativeBookPreview(book, kindLabel, displayTitle, displayIntro, displayContent) {
  if (book.project_loading) {
    return `<article class="book-preview subpage creative"><div class="empty">正在加载作品详情...</div></article>`;
  }
  if (book.project_error) {
    return `<article class="book-preview subpage creative"><div class="empty">作品详情加载失败：${escapeHtml(book.project_error)}</div></article>`;
  }
  const sb = book.story_bible && typeof book.story_bible === "object" ? book.story_bible : {};
  const outline = Array.isArray(book.outline) ? book.outline : [];
  const characters = Array.isArray(book.characters) ? book.characters : [];
  const reviews = Array.isArray(book.quality_reviews) ? book.quality_reviews : [];
  const latestReview = reviews[reviews.length - 1] || {};
  const latestSnippet = Array.isArray(book.chunks) && book.chunks.length ? book.chunks[book.chunks.length - 1].text || "" : displayContent || "";
  const score = (name) => creativeQualityScore(latestReview, name);
  return `
    <article class="book-preview subpage creative creative-preview-card">
      <div class="book-preview-cover ${book.cover_src ? "has-cover-image" : ""}">
        ${renderBookCoverInner(book, kindLabel, book.title || displayTitle || "未命名")}
      </div>
      <div class="book-preview-info creative-manager-info">
        <nav class="book-breadcrumb">
          <button type="button" data-book-close>书柜</button>
          <span>/ ${escapeHtml(kindLabel)}</span>
        </nav>
        <div class="reader-toolbar">
          <span>${escapeHtml(kindLabel)}</span>
          <button type="button" data-book-close>收回书柜</button>
        </div>
        <h2>${escapeHtml(book.title || displayTitle || "未命名")}</h2>
        <p>${escapeHtml(book.premise || displayIntro || "这本作品还没有简介。")}</p>
        <dl>
          ${book.status ? `<div><dt>状态</dt><dd>${escapeHtml(book.status)}</dd></div>` : ""}
          ${book.tone ? `<div><dt>气质</dt><dd>${escapeHtml(book.tone)}</dd></div>` : ""}
          ${book.point_of_view ? `<div><dt>视角</dt><dd>${escapeHtml(book.point_of_view)}</dd></div>` : ""}
          ${book.progress ? `<div><dt>进度</dt><dd>${escapeHtml(book.progress)}</dd></div>` : ""}
          ${book.created ? `<div><dt>入柜</dt><dd>${escapeHtml(book.created)}</dd></div>` : ""}
        </dl>
        <section class="creative-manager-card">
          <h3>故事档案</h3>
          <div class="creative-meta-grid">
            <div><b>主线</b><span>${escapeHtml(sb.mainline_direction || "") || "未建立"}</span></div>
            <div><b>下一步</b><span>${escapeHtml(sb.next_direction || book.next_hint || "") || "未指定"}</span></div>
          </div>
        </section>
        <section class="creative-manager-card">
          <h3>大纲预览</h3>
          ${outline.length ? `<ul class="creative-issues">${outline.slice(0, 8).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<div class="empty small">暂无大纲</div>`}
        </section>
        <section class="creative-manager-card">
          <h3>角色预览</h3>
          ${characters.length ? `<ul class="creative-issues">${characters.slice(0, 6).map((item) => `<li><b>${escapeHtml(item.name || "未命名角色")}</b>${item.role ? ` · ${escapeHtml(item.role)}` : ""}</li>`).join("")}</ul>` : `<div class="empty small">暂无角色</div>`}
        </section>
        <section class="creative-manager-card">
          <h3>最近质量分析</h3>
          <div class="creative-meta-grid quality">
            <div><b>人格一致</b><span>${escapeHtml(score("persona"))}</span></div>
            <div><b>推进度</b><span>${escapeHtml(score("progress"))}</span></div>
            <div><b>重复度</b><span>${escapeHtml(score("repetition"))}</span></div>
          </div>
        </section>
        <section class="creative-manager-card">
          <h3>最新片段</h3>
          <div class="reader-content creative-content ${escapeHtml(creativeReadingMode(book))}">${formatCreativeContentByMode(latestSnippet || "这本书还没有正文。", creativeReadingMode(book))}</div>
        </section>
        <div class="creative-form-actions">
          <button type="button" data-creative-enter-edit>编辑作品</button>
          <button type="button" class="read-button" data-book-read>进入阅读页</button>
          <button type="button" class="danger-outline" data-book-delete data-book-kind="creative" data-book-id="${escapeHtml(book.id || "")}" data-book-title="${escapeHtml(book.title || displayTitle || "")}">删除作品</button>
        </div>
      </div>
    </article>
  `;
}

export function bookTagInputValue(tags) {
  return Array.isArray(tags) ? tags.filter(Boolean).join("、") : "";
}

export function parseBookTagInput(value) {
  const seen = new Set();
  return String(value || "")
    .split(/[,，、\s\n\r]+/)
    .map((item) => item.trim())
    .filter((item) => {
      if (!item) return false;
      const key = item.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 8);
}

export function mergeBookTagCandidates(...groups) {
  const seen = new Set();
  const result = [];
  groups.flat().forEach((tag) => {
    const text = String(tag || "").trim();
    if (!text) return;
    const key = text.toLocaleLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });
  return result.slice(0, 16);
}

export function renderBookPreferenceEditor(book) {
  if (book.kind !== "jm_album") return "";
  const likedValue = bookTagInputValue(book.user_liked_tags);
  const dislikedValue = bookTagInputValue(book.user_disliked_tags);
  const sourceTags = Array.isArray(book.tags) ? book.tags.filter(Boolean) : [];
  const preferenceTags = Array.isArray(book.preference_tags) ? book.preference_tags.filter(Boolean) : [];
  const preferenceChips = preferenceTags.length
    ? `<div class="book-preference-auto-tags"><span>Bot 标注</span>${preferenceTags.map((tag) => `<b>${escapeHtml(tag)}</b>`).join("")}</div>`
    : "";
  const candidates = mergeBookTagCandidates(sourceTags, preferenceTags);
  const candidatePicker = candidates.length
    ? `
      <div class="book-preference-candidates">
        <span>现有标签</span>
        ${candidates.map((tag) => `
          <div class="book-preference-candidate">
            <b>${escapeHtml(tag)}</b>
            <button type="button" data-book-tag-pick data-tag-target="liked" data-tag-value="${escapeHtml(tag)}">喜好</button>
            <button type="button" data-book-tag-pick data-tag-target="disliked" data-tag-value="${escapeHtml(tag)}">厌恶</button>
          </div>
        `).join("")}
      </div>
    `
    : "";
  return `
    <form class="book-preference-editor" data-book-preference-form>
      <header>
        <span>偏好标签</span>
        <button type="submit">保存标签</button>
      </header>
      <div class="book-preference-fields">
        <label>
          <span>喜好</span>
          <input type="text" name="liked_tags" value="${escapeHtml(likedValue)}" placeholder="画风、节奏、设定">
        </label>
        <label>
          <span>厌恶</span>
          <input type="text" name="disliked_tags" value="${escapeHtml(dislikedValue)}" placeholder="拖沓、雷点、题材">
        </label>
      </div>
      ${candidatePicker}
      ${preferenceChips}
    </form>
  `;
}

export function allBookshelfBooks() {
  const bookshelf = state.bookshelfUnlocked || state.overview?.bookshelf || {};
  return [
    ...(bookshelf.public_books || []),
    ...(bookshelf.secret_books || []),
  ];
}

export function renderBookshelfPage() {
  const home = $("#bookcaseHome");
  if (home) home.hidden = state.bookshelfPage !== "shelf";
  renderBookDetailPanel();
}

export function clearBookshelfFallbackMotion() {
  if (asteriaWorkspaceState.bookshelfFallbackTimer !== null) {
    window.clearTimeout(asteriaWorkspaceState.bookshelfFallbackTimer);
    asteriaWorkspaceState.bookshelfFallbackTimer = null;
  }
  document.querySelectorAll("#panel-bookshelf .bookshelf-view.is-entering")
    .forEach((view) => view.classList.remove("is-entering"));
}

export function cancelBookshelfTransition() {
  const transition = asteriaWorkspaceState.activeBookshelfTransition;
  asteriaWorkspaceState.activeBookshelfTransition = null;
  transition?.skipTransition?.();
  clearBookshelfFallbackMotion();
  delete document.documentElement.dataset.bookshelfTransition;
  delete document.documentElement.dataset.bookshelfDirection;
  const panel = $("#panel-bookshelf");
  if (panel) delete panel.dataset.bookshelfDirection;
}

export function bookshelfFocusTarget(page) {
  if (page === "shelf") {
    return [...document.querySelectorAll("#bookcaseHome [data-book-id]")]
      .find((item) => item.dataset.bookId === asteriaWorkspaceState.bookshelfReturnFocusBookId) || $("#bookcaseHome");
  }
  const panel = $("#bookDetailPanel");
  return page === "reader"
    ? panel?.querySelector("[data-book-back]")
    : panel?.querySelector("[data-book-close]");
}

export function settleBookshelfTransition(page) {
  window.requestAnimationFrame(() => {
    const target = bookshelfFocusTarget(page);
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const outsideViewport = rect.bottom < 8 || rect.top > window.innerHeight - 8;
    if (outsideViewport) {
      target.scrollIntoView({ behavior: "auto", block: page === "shelf" ? "center" : "start" });
    }
    if (target.matches("button, [href], input, select, textarea, [tabindex]")) {
      target.focus({ preventScroll: true });
    }
  });
}

export function transitionBookshelfPage(nextPage, options = {}) {
  if (!Object.prototype.hasOwnProperty.call(bookshelfPageOrder, nextPage)) return false;
  const previousPage = state.bookshelfPage;
  if (nextPage === previousPage) return false;

  const direction = bookshelfPageOrder[nextPage] > bookshelfPageOrder[previousPage] ? "forward" : "backward";
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  const root = document.documentElement;
  const bookshelfPanel = $("#panel-bookshelf");

  if (asteriaWorkspaceState.activeTabTransition) {
    const tabTransition = asteriaWorkspaceState.activeTabTransition;
    asteriaWorkspaceState.activeTabTransition = null;
    tabTransition.skipTransition?.();
    delete root.dataset.tabDirection;
  }
  const previousTransition = asteriaWorkspaceState.activeBookshelfTransition;
  asteriaWorkspaceState.activeBookshelfTransition = null;
  previousTransition?.skipTransition?.();
  clearBookshelfFallbackMotion();
  root.dataset.bookshelfDirection = direction;
  if (bookshelfPanel) bookshelfPanel.dataset.bookshelfDirection = direction;

  let committed = false;
  const commit = (fallbackMotion = false) => {
    if (committed) return;
    committed = true;
    if (typeof options.mutate === "function") options.mutate();
    state.bookshelfPage = nextPage;
    renderBookshelfPage();
    if (typeof options.afterCommit === "function") options.afterCommit();
    if (!fallbackMotion) return;
    const activeView = nextPage === "shelf" ? $("#bookcaseHome") : $("#bookDetailPanel");
    if (!activeView) return;
    void activeView.offsetWidth;
    activeView.classList.add("is-entering");
  };

  const cleanup = () => {
    delete root.dataset.bookshelfTransition;
    delete root.dataset.bookshelfDirection;
    if (bookshelfPanel) delete bookshelfPanel.dataset.bookshelfDirection;
    clearBookshelfFallbackMotion();
    settleBookshelfTransition(nextPage);
  };

  if (!reduceMotion && typeof document.startViewTransition === "function") {
    root.dataset.bookshelfTransition = "active";
    try {
      const transition = document.startViewTransition(() => commit(false));
      asteriaWorkspaceState.activeBookshelfTransition = transition;
      const finishTransition = () => {
        if (asteriaWorkspaceState.activeBookshelfTransition !== transition) return;
        asteriaWorkspaceState.activeBookshelfTransition = null;
        if (!committed) {
          commit(true);
          asteriaWorkspaceState.bookshelfFallbackTimer = window.setTimeout(cleanup, 230);
          return;
        }
        cleanup();
      };
      transition.finished.then(finishTransition, finishTransition);
      return true;
    } catch (_error) {
      delete root.dataset.bookshelfTransition;
      asteriaWorkspaceState.activeBookshelfTransition = null;
    }
  }

  commit(!reduceMotion);
  if (reduceMotion) {
    cleanup();
  } else {
    asteriaWorkspaceState.bookshelfFallbackTimer = window.setTimeout(cleanup, 230);
  }
  return true;
}
