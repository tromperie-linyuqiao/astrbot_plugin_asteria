/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {postJson} from './client.js';
import {switchLearningSection} from './learning.js';
import {allBookshelfBooks,cancelBookshelfTransition,parseBookTagInput,renderBookshelf} from './library.js';
import {renderBookDetailPanel} from './life.js';
import {requireSecondClick,runAction,showToast} from './persona.js';
import {currentProviderFallbackValues,currentProviderTimeoutValues,currentProviderValues} from './providers.js';
import {currentProviderConfigMode,visibleConfigKey} from './schema.js';
import {collectFeatureDetailPayload} from './settings.js';
import {$,asteriaWorkspaceState,providerLabels,state} from './state.js';
import {applyPageTheme,ensureTabData,hydrateBookshelfImages,renderActiveTab,renderAppearanceSettings,scheduleExperimentalRuntimeRefresh} from './workspace.js';
import asteriaProviders from '../js/panels/provider-tree.js';

export async function saveExperimentalSettings(key, form, successMessage) {
  const payload = collectFeatureDetailPayload(key, form);
  const result = await runAction(
    () => postJson("/settings/update", payload),
    successMessage || "已保存参数",
    form.querySelector(".feature-param-save"),
    { reload: false },
  );
  if (result && state.activeTab === "experimental") {
    scheduleExperimentalRuntimeRefresh(true);
  }
}

export function revealActiveTab(tabButton, reduceMotion = false) {
  const nav = tabButton?.closest(".annotations");
  if (!nav) return;
  const left = tabButton.offsetLeft;
  const right = left + tabButton.offsetWidth;
  const visibleLeft = nav.scrollLeft;
  const visibleRight = visibleLeft + nav.clientWidth;
  if (left >= visibleLeft && right <= visibleRight) return;
  const target = Math.max(0, left - (nav.clientWidth - tabButton.offsetWidth) / 2);
  if (typeof nav.scrollTo === "function") {
    nav.scrollTo({ left: target, behavior: reduceMotion ? "auto" : "smooth" });
  } else {
    nav.scrollLeft = target;
  }
}

export function switchTab(tabName) {
  const opensSocialLearning = tabName === "worldbook";
  tabName = tabName === "modules" ? "config" : (opensSocialLearning ? "learning" : (tabName || "dashboard"));
  if (opensSocialLearning) state.learningSection = "social";
  if (tabName === state.activeTab) {
    if (opensSocialLearning) switchLearningSection("social", { focus: true });
    return;
  }
  cancelBookshelfTransition();
  const tabs = [...document.querySelectorAll(".annotations .tab[data-tab]")];
  const previousIndex = tabs.findIndex((item) => item.dataset.tab === state.activeTab);
  const nextIndex = tabs.findIndex((item) => item.dataset.tab === tabName);
  const direction = nextIndex >= 0 && previousIndex >= 0 && nextIndex < previousIndex ? "previous" : "next";
  const reduceMotion = Boolean(document.documentElement.dataset.nativeWorkspace) || window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  document.documentElement.dataset.tabDirection = direction;

  const commit = (fallbackMotion = false) => {
    state.activeTab = tabName;
    syncNativeCompanionNavigation(tabName);
    tabs.forEach((item) => item.classList.toggle("is-active", item.dataset.tab === tabName));
    revealActiveTab(tabs.find((item) => item.dataset.tab === tabName), reduceMotion);
    document.querySelectorAll(".panel").forEach((item) => {
      item.classList.remove("is-entering", "is-leaving");
      item.classList.toggle("is-active", item.id === `panel-${tabName}`);
    });
    const activePanel = document.getElementById(`panel-${tabName}`);
    if (fallbackMotion && activePanel) {
      void activePanel.offsetWidth;
      activePanel.classList.add("is-entering");
      activePanel.addEventListener("animationend", () => activePanel.classList.remove("is-entering"), { once: true });
    }
    renderActiveTab(state.activeTab);
  };

  if (!reduceMotion && typeof document.startViewTransition === "function") {
    asteriaWorkspaceState.activeTabTransition?.skipTransition?.();
    try {
      const transition = document.startViewTransition(() => commit(false));
      asteriaWorkspaceState.activeTabTransition = transition;
      transition.finished.finally(() => {
        if (asteriaWorkspaceState.activeTabTransition === transition) {
          asteriaWorkspaceState.activeTabTransition = null;
          delete document.documentElement.dataset.tabDirection;
        }
      });
    } catch (_error) {
      commit(true);
      asteriaWorkspaceState.activeTabTransition = null;
    }
  } else {
    commit(!reduceMotion);
  }
  ensureTabData(tabName).catch((error) => showToast(`页面数据加载失败：${error.message}`, "error"));
}

export async function deleteSelectedBookshelfItem(button = null) {
  const book = state.selectedBook || {};
  const dataset = button?.dataset || {};
  const kind = dataset.bookKind || book.kind || "";
  const itemId = dataset.bookId || book.id || "";
  const albumId = dataset.bookAlbumId || book.album_id || "";
  const title = dataset.bookTitle || book.title || "";
  const diaryDate = kind === "diary" ? (dataset.bookDate || state.selectedDiaryDate || "") : "";
  if (!kind) {
    alert("没有找到当前书籍，请刷新拓展页后再试。");
    return;
  }
  const label = kind === "diary" && diaryDate ? `${diaryDate} 的日记` : (title || "这本书");
  if (kind !== "jm_album" && !requireSecondClick(button, `book:${kind}:${itemId}:${diaryDate}`, `再次点击删除「${label}」`, "再次点击删除")) return;
  if (button) {
    button.disabled = true;
    button.textContent = "移除中...";
  }
  showToast("正在从书柜移除...");
  try {
    if (kind === "creative") {
      const result = await postJson("/creative/project/delete", { id: itemId });
      if (!result.removed) {
        showToast("没有找到要删除的创作项目，请刷新拓展页后再试。", "error");
        if (button) {
          button.disabled = false;
          button.textContent = "删除作品";
        }
        return;
      }
      const removeCreative = (shelf) => {
        if (!shelf || !Array.isArray(shelf.public_books)) return;
        shelf.public_books = shelf.public_books.filter((item) => !(item.kind === "creative" && String(item.id || "") === String(itemId)));
        shelf.public_count = shelf.public_books.length;
      };
      removeCreative(state.overview?.bookshelf);
      removeCreative(state.bookshelfUnlocked);
      if (state.overview?.creative) {
        const items = Array.isArray(state.overview.creative.items) ? state.overview.creative.items : [];
        state.overview.creative.items = items.filter((item) => String(item.id || "") !== String(itemId));
        state.overview.creative.project_count = state.overview.creative.items.length;
        state.overview.creative.active_projects = state.overview.creative.items.filter((item) => item.status === "drafting").length;
      }
      state.selectedBook = null;
      state.bookshelfPage = "shelf";
      state.creativeEditing = false;
      state.selectedBookSpreadIndex = 0;
      renderBookshelf();
      showToast("创作项目已删除。");
      return;
    }
    const result = await postJson("/bookshelf/delete", {
      kind,
      id: itemId,
      album_id: albumId,
      title,
      date: diaryDate,
      access_token: state.bookshelfAccessToken || state.bookshelfUnlocked?.access_token || "",
    });
    if (!result.changed) {
      showToast("没有找到要移除的书柜条目，请刷新拓展页后再试。", "error");
      if (button) {
        button.disabled = false;
        button.textContent = kind === "diary" ? "删除当前日记" : "从书柜移除";
      }
      return;
    }
    state.bookshelfUnlocked = result.bookshelf || null;
    state.bookshelfAccessToken = result.bookshelf?.access_token || state.bookshelfAccessToken || "";
    state.selectedBook = null;
    state.bookshelfPage = "shelf";
    state.selectedBookSpreadIndex = 0;
    renderBookshelf();
    showToast(kind === "diary" ? "日记已删除。" : "已从书柜移除。");
  } catch (error) {
    showToast(`移除失败：${error.message}`, "error");
    if (button) {
      button.disabled = false;
      button.textContent = kind === "diary" ? "删除当前日记" : "从书柜移除";
    }
  }
}

export async function rateSelectedBookshelfItem(button = null) {
  const book = state.selectedBook || {};
  const albumId = book.album_id || button?.closest("[data-book-rating-album]")?.dataset?.bookRatingAlbum || "";
  const rating = Number(button?.dataset?.bookRating || 0);
  if (!albumId || !rating) {
    showToast("没有找到要评分的阅读记录。", "error");
    return;
  }
  const reason = "";
  await runAction(async () => {
    const result = await postJson("/bookshelf/rate", {
      album_id: albumId,
      rating,
      reason,
      access_token: state.bookshelfAccessToken || state.bookshelfUnlocked?.access_token || "",
    });
    state.bookshelfUnlocked = result.bookshelf || null;
    state.bookshelfAccessToken = result.bookshelf?.access_token || state.bookshelfAccessToken || "";
    const updated = allBookshelfBooks().find((item) => item.kind === "jm_album" && String(item.album_id || "") === String(albumId));
    if (updated) state.selectedBook = updated;
    renderBookshelf();
    state.bookshelfPage = "reader";
    renderBookDetailPanel();
  }, `已评分 ${rating}/10`, button);
}

export async function updateSelectedBookshelfTags(form) {
  const book = state.selectedBook || {};
  const albumId = book.album_id || "";
  if (!albumId) {
    showToast("没有找到要编辑标签的阅读记录。", "error");
    return;
  }
  const button = form.querySelector("button[type='submit']");
  const likedTags = parseBookTagInput(form.elements.liked_tags?.value || "");
  const dislikedTags = parseBookTagInput(form.elements.disliked_tags?.value || "")
    .filter((tag) => !likedTags.some((liked) => liked.toLocaleLowerCase() === tag.toLocaleLowerCase()));
  await runAction(async () => {
    const result = await postJson("/bookshelf/tags", {
      album_id: albumId,
      liked_tags: likedTags,
      disliked_tags: dislikedTags,
      access_token: state.bookshelfAccessToken || state.bookshelfUnlocked?.access_token || "",
    });
    state.bookshelfUnlocked = result.bookshelf || null;
    state.bookshelfAccessToken = result.bookshelf?.access_token || state.bookshelfAccessToken || "";
    const updated = allBookshelfBooks().find((item) => item.kind === "jm_album" && String(item.album_id || "") === String(albumId));
    if (updated) state.selectedBook = updated;
    state.bookshelfPage = "detail";
    renderBookshelf();
    renderBookDetailPanel();
  }, "已保存标签", button);
}

export function applyBookPreferenceTagPick(button) {
  const form = button.closest("[data-book-preference-form]");
  const tag = String(button.dataset.tagValue || "").trim();
  const target = button.dataset.tagTarget === "disliked" ? "disliked_tags" : "liked_tags";
  const other = target === "liked_tags" ? "disliked_tags" : "liked_tags";
  if (!form || !tag) return;
  const targetInput = form.elements[target];
  const otherInput = form.elements[other];
  if (!(targetInput instanceof HTMLInputElement) || !(otherInput instanceof HTMLInputElement)) return;
  const targetTags = parseBookTagInput(targetInput.value);
  const otherTags = parseBookTagInput(otherInput.value).filter((item) => item.toLocaleLowerCase() !== tag.toLocaleLowerCase());
  if (!targetTags.some((item) => item.toLocaleLowerCase() === tag.toLocaleLowerCase())) {
    targetTags.push(tag);
  }
  targetInput.value = targetTags.slice(0, 8).join("、");
  otherInput.value = otherTags.join("、");
}

export async function rereadSelectedBookshelfItem(button = null) {
  const book = state.selectedBook || {};
  const albumId = book.album_id || "";
  if (!albumId) {
    showToast("没有找到要重读的阅读记录。", "error");
    return;
  }
  const currentPage = state.bookshelfPage;
  await runAction(async () => {
    const result = await postJson("/bookshelf/comments/update", {
      album_id: albumId,
      access_token: state.bookshelfAccessToken || state.bookshelfUnlocked?.access_token || "",
    });
    state.bookshelfUnlocked = result.bookshelf || null;
    state.bookshelfAccessToken = result.bookshelf?.access_token || state.bookshelfAccessToken || "";
    const updated = allBookshelfBooks().find((item) => item.kind === "jm_album" && String(item.album_id || "") === String(albumId));
    if (updated) state.selectedBook = updated;
    state.bookshelfPage = currentPage === "reader" ? "reader" : "detail";
    renderBookshelf();
    renderBookDetailPanel();
    void hydrateBookshelfImages($("#bookDetailPanel") || document);
  }, "", button);
}

export async function savePageTheme(theme) {
  const previous = state.pageTheme;
  state.pageTheme = theme;
  applyPageTheme();
  renderAppearanceSettings();
  try {
    const result = await postJson("/settings/update", { settings: { page_theme: theme } });
    if (result?.config_saved !== false) applyPageTheme({ explicit: true });
    showToast(result?.config_saved === false ? "主题已应用，但配置持久化失败；重启后可能恢复旧值" : "主题已保存", result?.config_saved === false ? "error" : "success");
  } catch (error) {
    state.pageTheme = previous;
    applyPageTheme();
    renderAppearanceSettings();
    showToast(`主题保存失败：${error.message}`, "error");
  }
}

export function completeTokenStatsSnapshot(value) {
  const object = (v) => v && typeof v === "object" && !Array.isArray(v);
  const bucket = (v) => object(v) && ["total_tokens", "calls"].every((key) => typeof v[key] === "number" && Number.isFinite(v[key]));
  const source = (v) => object(v) && bucket(v.totals) && ["by_day", "by_hour", "by_provider", "by_task", "recent"].every((key) => Array.isArray(v[key]));
  return source(value) && source(value.external) && source(value.memory_plugin)
    && object(value.budget) && typeof value.budget.used === "number" && Number.isFinite(value.budget.used)
    && object(value.balance) && typeof value.memory_plugin.available === "boolean";
}

export function renderTokenResetNotice() {
  const result = state.tokenResetState;
  const notice = $("#tokenResetNotice"), check = $("#tokenResetCheckBtn"), button = $("#resetTokenStatsBtn");
  notice.hidden = !result;
  notice.textContent = result?.text || "";
  check.hidden = result?.status !== "unknown";
  button.disabled = result?.status === "pending" || result?.status === "unknown";
}

export function providerFormSnapshot() {
  return {
    providers: currentProviderValues(), timeouts: currentProviderTimeoutValues(), fallbacks: currentProviderFallbackValues(),
    peak: asteriaProviders.currentDeepseekPeakValues({ document, state }), mode: currentProviderConfigMode(),
  };
}

export function providerReceiptMap(raw, numbers = false) {
  if (typeof raw === "string") { try { raw = JSON.parse(raw); } catch (_error) { return null; } }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  if (!Object.values(raw).every(v => numbers ? Number.isInteger(v) && v >= 5 && v <= 600 : typeof v === "string")) return null;
  return raw;
}

export function providerSame(a, b) {
  if (a && b && typeof a === "object" && typeof b === "object") {
    const keys = Object.keys(a);return keys.length === Object.keys(b).length && keys.every(k => providerSame(a[k], b[k]));
  }
  return a === b;
}

export function providerReceiptComplete(result, payload) {
  if (!result || typeof result.config_saved !== "boolean" || !result.providers || !result.settings || !result.changed) return false;
  if (!Object.keys(payload.providers).every(k => typeof result.providers[k] === "string" && result.changed[k] === result.providers[k])) return false;
  if (result.settings.provider_config_mode !== payload.settings.provider_config_mode) return false;
  return Object.keys(payload.settings).every(k => {
    const value = result.settings[k], changed = result.changed[k];
    if (k === "model_timeout_overrides" || k === "model_fallback_overrides") {
      const a = providerReceiptMap(value, k === "model_timeout_overrides"), b = providerReceiptMap(changed, k === "model_timeout_overrides");
      return a !== null && b !== null && providerSame(a, b);
    }
    return typeof value === typeof payload.settings[k] && providerSame(value, changed);
  });
}

export function providerReadComplete(result) {
  return result?.providers && Object.keys(providerLabels).filter(visibleConfigKey).every(k => typeof result.providers[k] === "string")
    && ["quick", "precision"].includes(result.settings?.provider_config_mode)
    && providerReceiptMap(result.settings.model_timeout_overrides, true) !== null
    && providerReceiptMap(result.settings.model_fallback_overrides) !== null;
}

export function providerLaterValues(current, submitted) {
  const result = {};
  new Set([...Object.keys(current), ...Object.keys(submitted)]).forEach(k => {
    if (!providerSame(current[k] ?? "", submitted[k] ?? "")) result[k] = current[k] ?? "";
  });
  return result;
}

export function applyProviderRead(result) {
  state.overview = { ...state.overview, providers: { ...result.providers },
    settings: { ...state.overview?.settings, ...result.settings }, deepseek_peak_routing: result.deepseek_peak_routing };
}

export function renderProviderSaveNotice() {
  const record = state.providerSave, busy = record?.status === "pending", unknown = record?.status === "unknown";
  const notice = $("#providerSaveNotice");
  if (notice) { notice.hidden = !record?.message;notice.textContent = record?.message || ""; }
  const savedMode = state.overview?.settings?.provider_config_mode;
  const mode = $("#providerSavedMode");if (mode) mode.textContent = savedMode === "quick" ? "快速配置" : savedMode === "precision" ? "精准配置" : "尚未读取";
  const save = $("#saveProvidersBtn");if (save) save.disabled = busy || unknown;
  const read = $("#providerReadBtn");if (read) read.disabled = busy || Boolean(state.providerReadBusy);
}

export function syncNativeCompanionNavigation(tab) {
  const root = document.getElementById("nativeCompanionNavigation");
  if (!root) return;
  root.querySelectorAll("[data-tab]").forEach((button) => {
    const active = button.dataset.tab === tab;
    button.setAttribute("aria-current", active ? "page" : "false");
    if (active) document.getElementById("nativeCompanionNavigationTitle").textContent = button.textContent.trim();
  });
  const hash = tab === "dashboard" ? "" : `#tab=${encodeURIComponent(tab)}`;
  if (location.hash !== hash) history.replaceState(history.state, "", `${location.pathname}${location.search}${hash}`);
  if (matchMedia("(max-width:760px)").matches) root.open = false;
}

export function initNativeCompanionNavigation() {
  const root = document.getElementById("nativeCompanionNavigation");
  if (!root) return;
  const narrow = matchMedia("(max-width:760px)");
  root.open = !narrow.matches;
  narrow.addEventListener("change", () => { root.open = !narrow.matches; });
  document.getElementById("nativeCompanionSearch").addEventListener("input", (event) => {
    const query = event.target.value.trim().toLocaleLowerCase();
    let visible = 0;
    root.querySelectorAll("[data-tab]").forEach((button) => {
      button.hidden = !button.textContent.toLocaleLowerCase().includes(query);
      if (!button.hidden) visible++;
    });
    root.querySelectorAll(".aw-nav-group").forEach((group) => { group.hidden = !group.querySelector("button:not([hidden])"); });
    root.querySelector(".aw-nav-empty").hidden = visible > 0;
  });
  // Technical projections remain accessible, but do not occupy the daily view by default.
  for (const id of ["dailyState", "livingMemoryBox", "memoryComposition", "interactionImpact"]) {
    const target = document.getElementById(id);
    const card = target?.closest("article");
    if (!card || card.closest(".aw-native-fold")) continue;
    const fold = document.createElement("details"); fold.className = "aw-native-fold";
    const title = document.createElement("summary");
    title.textContent = card.querySelector("h2,h3,h4")?.textContent || "详细状态";
    fold.append(title); card.before(fold); fold.append(card);
  }
  const requested = new URLSearchParams(location.hash.slice(1)).get("tab");
  const exists = [...root.querySelectorAll("[data-tab]")].some((button) => button.dataset.tab === requested);
  if (exists && requested !== "dashboard") switchTab(requested);
  else syncNativeCompanionNavigation("dashboard");
}
