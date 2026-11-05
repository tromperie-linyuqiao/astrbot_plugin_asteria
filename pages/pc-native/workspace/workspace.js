/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {fetchJson,getPageBridge,isUsableBridge,postJson} from './client.js';
import {invalidateImageCachePreviews,renderGroupBubbleChart,renderImageCache,renderRelationshipChart} from './image-cache.js';
import {renderGroups,renderLearning,renderLearningSummary,renderMemory,renderUsers} from './learning.js';
import {renderBookshelf} from './library.js';
import {renderConfig,renderModuleSettings,renderProactiveCandidates} from './life.js';
import {renderExperimentalPage,setActionBusy,showToast} from './persona.js';
import {renderProviders} from './providers.js';
import {renderDiagnostics,renderTroubleshooting} from './relationships.js';
import {featureDraftFromOverview,inferProviderConfigMode,normalizeModelFallbackOverrides,normalizeModelTimeoutOverrides} from './schema.js';
import {renderRoleplayPersonaDraftPanel} from './settings.js';
import {renderDashboard,renderDashboardPulse,renderSetupGuideOverlay,renderStats,setupGuideDraft} from './setup.js';
import {$,PAGE_THEMES,TRANSPARENT_IMAGE,asteriaWorkspaceState,state} from './state.js';
import {renderTokens} from './usage.js';
import asteriaOutfit from '../js/features/daily-outfit.js';
import asteriaAppearance from '../js/ui/appearance.js';
import asteriaQzone from '../js/panels/qzone-panel.js';

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function cleanInterjectionText(value) {
  const text = String(value ?? "").trim().replace(/^["'“”‘’` ]+|["'“”‘’` ]+$/g, "");
  if (!text || /^[.。…~～\s"'“”‘’`-]{0,12}$/.test(text)) return "";
  return text;
}

export function bookshelfImageTag(src, alt) {
  const imageSrc = String(src || "");
  if (!imageSrc) return "";
  const image = `<img src="${TRANSPARENT_IMAGE}" data-bookshelf-image-src="${escapeHtml(imageSrc)}" alt="${escapeHtml(alt || "书柜图片")}" loading="lazy" />`;
  if (!String(alt || "").endsWith("封面")) return image;
  return `
    <button type="button" class="bookshelf-cover-zoom" data-bookshelf-cover-preview disabled aria-label="放大预览${escapeHtml(alt || "作品封面")}">
      ${image}
      <span class="bookshelf-cover-zoom-hint" aria-hidden="true">点击放大</span>
    </button>
  `;
}

export function bookshelfImageDataPath(src) {
  const raw = String(src || "");
  if (!raw) return "";
  if (raw.startsWith("data:")) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.pathname.endsWith("/bookshelf/image")) {
      return `/bookshelf/image_data${url.search}`;
    }
    if (url.pathname.endsWith("/creative/project/cover")) {
      return `/creative/project/cover_data${url.search}`;
    }
    const marker = "/bookshelf/image?";
    const markerIndex = raw.indexOf(marker);
    if (markerIndex >= 0) {
      return `/bookshelf/image_data?${raw.slice(markerIndex + marker.length)}`;
    }
    const creativeMarker = "/creative/project/cover?";
    const creativeMarkerIndex = raw.indexOf(creativeMarker);
    if (creativeMarkerIndex >= 0) {
      return `/creative/project/cover_data?${raw.slice(creativeMarkerIndex + creativeMarker.length)}`;
    }
  } catch (error) {
    const marker = "/bookshelf/image?";
    const markerIndex = raw.indexOf(marker);
    if (markerIndex >= 0) return `/bookshelf/image_data?${raw.slice(markerIndex + marker.length)}`;
    const creativeMarker = "/creative/project/cover?";
    const creativeMarkerIndex = raw.indexOf(creativeMarker);
    if (creativeMarkerIndex >= 0) return `/creative/project/cover_data?${raw.slice(creativeMarkerIndex + creativeMarker.length)}`;
  }
  return raw;
}

export async function hydrateBookshelfImages(root = document) {
  const images = [...root.querySelectorAll("img[data-bookshelf-image-src]")];
  await Promise.all(images.map(async (img) => {
    if (img.dataset.loaded === "1" || img.dataset.loading === "1") return;
    const source = img.dataset.bookshelfImageSrc || "";
    if (!source) return;
    img.dataset.loading = "1";
    const endpoint = bookshelfImageDataPath(source);
    try {
      if (endpoint.startsWith("data:")) {
        img.src = endpoint;
      } else if (endpoint.startsWith("/bookshelf/image_data") || endpoint.startsWith("/creative/project/cover_data")) {
        const result = await fetchJson(endpoint);
        if (result?.data_url) img.src = result.data_url;
      } else {
        img.src = source;
      }
      img.dataset.loaded = "1";
      const previewButton = img.closest("[data-bookshelf-cover-preview]");
      if (previewButton instanceof HTMLButtonElement) {
        previewButton.disabled = false;
        previewButton.classList.add("is-ready");
        previewButton.classList.remove("is-error");
      }
    } catch (error) {
      img.dataset.loaded = "0";
      img.alt = `${img.alt || "书柜图片"}（加载失败）`;
      const previewButton = img.closest("[data-bookshelf-cover-preview]");
      if (previewButton instanceof HTMLButtonElement) {
        previewButton.disabled = true;
        previewButton.classList.add("is-error");
        previewButton.title = "封面加载失败，请刷新后重试";
      }
    } finally {
      img.dataset.loading = "0";
    }
  }));
}

export function openBookshelfCoverPreview(trigger) {
  const overlay = $("#bookshelfCoverPreview");
  const previewImage = $("#bookshelfCoverPreviewImage");
  const previewTitle = $("#bookshelfCoverPreviewTitle");
  const sourceImage = trigger?.querySelector("img[data-bookshelf-image-src]");
  if (!overlay || !previewImage || !sourceImage || sourceImage.dataset.loaded !== "1") return;
  asteriaWorkspaceState.bookshelfCoverPreviewReturnFocus = trigger instanceof HTMLElement ? trigger : null;
  previewImage.src = sourceImage.currentSrc || sourceImage.src;
  previewImage.alt = sourceImage.alt || "创作封面预览";
  if (previewTitle) previewTitle.textContent = sourceImage.alt || "创作封面";
  overlay.hidden = false;
  overlay.setAttribute("aria-hidden", "false");
  document.documentElement.dataset.bookshelfCoverPreview = "open";
  window.requestAnimationFrame(() => $("#bookshelfCoverPreviewClose")?.focus());
}

export function closeBookshelfCoverPreview() {
  const overlay = $("#bookshelfCoverPreview");
  const previewImage = $("#bookshelfCoverPreviewImage");
  if (!overlay || overlay.hidden) return;
  overlay.hidden = true;
  overlay.setAttribute("aria-hidden", "true");
  if (previewImage) {
    previewImage.removeAttribute("src");
    previewImage.alt = "";
  }
  delete document.documentElement.dataset.bookshelfCoverPreview;
  asteriaWorkspaceState.bookshelfCoverPreviewReturnFocus?.focus?.({ preventScroll: true });
  asteriaWorkspaceState.bookshelfCoverPreviewReturnFocus = null;
}

export function bindBookshelfCoverPreviewDismissal() {
  const overlay = $("#bookshelfCoverPreview");
  const dialog = overlay?.querySelector(".bookshelf-cover-preview__dialog");
  const closeButton = $("#bookshelfCoverPreviewClose");
  if (!overlay || overlay.dataset.dismissBound === "1") return;
  overlay.dataset.dismissBound = "1";
  closeButton?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    closeBookshelfCoverPreview();
  });
  overlay.addEventListener("click", (event) => {
    if (event.target !== overlay) return;
    event.preventDefault();
    closeBookshelfCoverPreview();
  });
  dialog?.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || overlay.hidden) return;
    event.preventDefault();
    event.stopPropagation();
    closeBookshelfCoverPreview();
  }, true);
}

export async function hydrateDailyOutfitLogo() {
  if (asteriaOutfit?.hydrateDailyOutfitLogo) {
    await asteriaOutfit.hydrateDailyOutfitLogo({ state, fetchJson, document });
  }
}

export function runWhenIdle(callback, timeout = 1200) {
  if (typeof window.requestIdleCallback === "function") {
    return window.requestIdleCallback(callback, { timeout });
  }
  return window.setTimeout(callback, Math.min(360, timeout));
}

export function cancelIdleTask(handle) {
  if (!handle) return;
  if (typeof window.cancelIdleCallback === "function") {
    window.cancelIdleCallback(handle);
  } else {
    window.clearTimeout(handle);
  }
}

export function scheduleDailyOutfitHydration(force = false) {
  const outfit = state.overview?.daily_outfit || {};
  const key = String(outfit.image_data_url || "");
  const image = document.getElementById("dailyOutfitLogo");
  if (!force && key && state.dailyOutfitHydrateKey === key && image?.dataset.source === key) return;
  if (state.dailyOutfitHydrateTimer) cancelIdleTask(state.dailyOutfitHydrateTimer);
  state.dailyOutfitHydrateTimer = runWhenIdle(() => {
    state.dailyOutfitHydrateTimer = null;
    state.dailyOutfitHydrateKey = key;
    hydrateDailyOutfitLogo().catch(() => {});
  }, 1600);
}

export async function openTLSNativeWorkspace(entry) {
  if (!["personal_goals", "memo_notes"].includes(entry)) return;
  try {
    const bridge = await getPageBridge();
    if (!isUsableBridge(bridge)) throw Error("请从 AstrBot 后台打开 TLS 页面。");
    if (typeof bridge.ready === "function") await bridge.ready();
    let result = await bridge.apiGet("page/nav", { to: "console", format: "json" });
    if (result && result.data && !result.url) result = result.data;
    if (!result || typeof result.url !== "string") throw Error("未能取得 TLS 管理入口。");
    const url = new URL(result.url, window.location.href);
    const paths = ["/api/plugin/page/content/astrbot_plugin_asteria/console/", "/tls/page/console/"];
    if (url.origin !== window.location.origin || !paths.includes(url.pathname) || url.username || url.password) {
      throw Error("管理入口地址不匹配，请从 AstrBot 后台重新打开。");
    }
    url.hash = entry;
    window.location.assign(url.href);
  } catch (error) { showToast(error.message || "TLS 管理入口暂不可打开，请稍后重试。", "error"); }
}

export function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function unwrapConfigPackagePayload(value) {
  let current = value;
  for (let index = 0; index < 8; index += 1) {
    if (!current || typeof current !== "object" || Array.isArray(current)) return current;
    if (current.kind === "private_companion_config_backup" || (current.overview && (current.users || current.groups))) return current;
    const next = current.package || current.data || current.payload || current.result;
    if (!next || typeof next !== "object" || Array.isArray(next) || next === current) return current;
    current = next;
  }
  return current;
}

export function formatBackupTime(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "未知时间";
  return new Date(timestamp * 1000).toLocaleString();
}

export function selectedConfigExportSections() {
  const sections = [...document.querySelectorAll("[data-export-section]")]
    .filter((input) => input.checked)
    .map((input) => input.dataset.exportSection)
    .filter(Boolean);
  return sections;
}

export function allowConfigChecksumMismatch() {
  return Boolean($("#configAllowChecksumMismatch")?.checked);
}

export function migrationDiffText(item) {
  const added = Number(item?.added || 0);
  const overwritten = Number(item?.overwritten || 0);
  const unchanged = Number(item?.unchanged || 0);
  return `新增 ${added} · 覆盖 ${overwritten} · 不变 ${unchanged}`;
}

export function migrationSectionLabel(value) {
  return {
    basic: "基础配置",
    relations: "关系/群资料",
    food_skills: "候选菜单/技能",
    providers: "模型配置",
    sensitive: "敏感配置",
  }[value] || value;
}

export function migrationLevelText(level) {
  return {
    ok: "正常",
    warn: "注意",
    error: "错误",
    unknown: "未知",
  }[level] || "提示";
}

export function renderConfigBackups() {
  const box = $("#configBackupList");
  if (!box) return;
  const items = Array.isArray(state.configBackups) ? state.configBackups : [];
  if (!items.length) {
    box.innerHTML = "暂无自动备份。";
    return;
  }
  box.innerHTML = items.map((item) => {
    const sections = Array.isArray(item.included_sections) && item.included_sections.length
      ? item.included_sections.map(migrationSectionLabel).join("、")
      : "旧备份";
    const checksum = item.error ? `读取失败：${item.error}` : (item.checksum_ok ? "校验通过" : "未取得有效校验");
    return `
      <div class="migration-backup-item">
        <div>
          <b>${escapeHtml(item.name || item.id)}</b>
          <span>${escapeHtml(formatBackupTime(item.exported_at || item.mtime))} · ${escapeHtml(item.version || "未知版本")} · ${escapeHtml(checksum)}</span>
          <small>${escapeHtml(sections)} · ${Number(item.size || 0).toLocaleString()} 字节</small>
        </div>
        <button type="button" data-config-restore="${escapeHtml(item.id)}" ${configMigrationLocked() ? "disabled" : ""}>恢复</button>
      </div>
    `;
  }).join("");
}

export function renderConfigImportChecks() {
  const box = $("#configImportChecks");
  if (!box) return;
  const checks = Array.isArray(state.configLastChecks) ? state.configLastChecks : [];
  if (!checks.length) {
    box.innerHTML = "导入后会在这里显示轻量检查结果。";
    return;
  }
  box.innerHTML = checks.map((item) => `
    <div class="migration-check-item ${escapeHtml(item.level || "ok")}">
      <b>${escapeHtml(item.title || migrationLevelText(item.level))}</b>
      <span>${escapeHtml(item.detail || "")}</span>
    </div>
  `).join("");
}

export function renderConfigMigrationPreview() {
  const box = $("#configMigrationPreview");
  if (!box) return;
  const modeSelect = $("#configImportMode");
  const conflictSelect = $("#configImportConflict");
  if (conflictSelect) {
    conflictSelect.disabled = (modeSelect?.value || "merge") === "replace";
  }
  const preview = state.configImportPreview;
  if (!state.configImportPackage) {
    box.innerHTML = "还没有选择备份或快照文件。";
    $("#previewConfigImportBtn").disabled = true;
    $("#applyConfigImportBtn").disabled = true;
    return;
  }
  $("#previewConfigImportBtn").disabled = state.configImportPreviewBusy;
  $("#applyConfigImportBtn").disabled = !preview || configMigrationLocked();
  const fileLine = `<p class="migration-note">当前文件：${escapeHtml(state.configImportFileName || "未命名文件")}</p>`;
  if (!preview) {
    box.innerHTML = `${fileLine}<p>${state.configImportPreviewBusy ? "正在预览当前文件…" : "已选择备份/快照文件，先点“预览导入”看看会改动哪些内容。"}</p>`;
    return;
  }
  const sections = Array.isArray(preview.sections) ? preview.sections : [];
  if (preview.legacy_snapshot && modeSelect && modeSelect.value === "replace") {
    modeSelect.value = "merge";
    if (conflictSelect) conflictSelect.disabled = false;
  }
  const sectionHtml = sections.length
    ? sections.map((item) => `
        <span>
          <b>${escapeHtml(item.label || item.key)}</b>
          ${Number(item.count || 0)} 条
          <small>${escapeHtml(migrationDiffText(item))}</small>
        </span>
      `).join("")
    : "<em>没有可迁移资料段</em>";
  const configDiff = preview.config_diff || {};
  const compatibility = preview.compatibility || {};
  const checksumLine = preview.checksum
    ? (preview.checksum_ok ? "文件校验：通过" : (preview.checksum_bypassed ? "文件校验：失败，已按风险选项继续" : "文件校验：失败"))
    : "文件校验：旧备份未提供";
  const checksumWarn = preview.checksum_bypassed
    ? `<p class="migration-warn">这份备份的校验值与当前内容不一致。仅当你确认文件只是被手动脱敏或删改敏感字段、且 JSON 内容完整时，才继续导入。</p>`
    : "";
  const compatibilityHtml = `
    <p class="migration-note">
      备份来自 ${escapeHtml(compatibility.backup_version || preview.version || "未知")}，当前版本 ${escapeHtml(compatibility.current_version || preview.current_version || "未知")}。
      ${escapeHtml(compatibility.message || "")}
    </p>
    <p class="${compatibility.level === "warn" || preview.checksum_bypassed ? "migration-warn" : "migration-note"}">${escapeHtml(checksumLine)}</p>
    ${checksumWarn}
  `;
  const included = Array.isArray(preview.included_sections) && preview.included_sections.length
    ? `<p class="migration-note">备份包含：${escapeHtml(preview.included_sections.map(migrationSectionLabel).join("、"))}</p>`
    : "";
  const legacy = preview.legacy_snapshot
    ? `<p class="migration-warn">这是旧版页面快照，只会按合并方式导入可识别的配置、名单、开关和模型指向；页面里的私聊/群聊摘要不会写回数据文件。</p>`
    : "";
  const ignored = Array.isArray(preview.ignored) && preview.ignored.length
    ? `<p class="migration-warn">已忽略 ${preview.ignored.length} 个未知字段：${escapeHtml(preview.ignored.slice(0, 8).join("、"))}</p>`
    : "";
  box.innerHTML = `
    ${fileLine}
    <div class="migration-preview-top">
      <b>备份版本 ${escapeHtml(preview.version || "未知")}</b>
      <span>${escapeHtml(formatBackupTime(preview.exported_at))}</span>
    </div>
    <div class="migration-counts">
      <span>配置 ${Number(preview.config_count || 0)} 项 <small>${escapeHtml(migrationDiffText(configDiff))}</small></span>
      <span>开关 ${Number(preview.features_count || 0)} 项</span>
      <span>模型 ${Number(preview.providers_count || 0)} 项</span>
    </div>
    <div class="migration-section-list">${sectionHtml}</div>
    ${compatibilityHtml}
    ${included}
    ${legacy}
    ${ignored}
    <p class="migration-note">导入前会自动保存当前可迁移配置；Token、缓存、最近消息、审计日志和临时队列不会导入。</p>
  `;
}

export async function handleConfigExport() {
  const sections = selectedConfigExportSections();
  if (!sections.length) {
    showToast("请至少选择一项导出内容", "error");
    return;
  }
  const params = new URLSearchParams();
  params.set("sections", sections.join(","));
  const button = $("#exportConfigBtn");
  if (button.disabled) return;
  setActionBusy(button, true);
  try {
    const data = await fetchJson(`/config/export?${params.toString()}`);
    const date = new Date().toISOString().slice(0, 10);
    downloadJson(`private-companion-config-${date}.json`, data);
    showToast(`已交给浏览器下载：${sections.map(migrationSectionLabel).join("、")}`);
  } catch (error) {
    showToast(`导出失败：${error.message}`, "error");
  } finally {
    setActionBusy(button, false);
  }
}

export async function readConfigImportFile(file) {
  const serial = ++state.configImportReadSerial;
  ++state.configImportPreviewSerial;
  state.configImportPreviewBusy = false;
  state.configImportFileName = file.name;
  state.configImportPackage = null;
  state.configImportPreview = null;
  renderConfigMigrationPreview();
  try {
    const text = await file.text();
    const data = JSON.parse(text.replace(/^\uFEFF/, ""));
    if (serial !== state.configImportReadSerial) return;
    state.configImportPackage = unwrapConfigPackagePayload(data);
    renderConfigMigrationPreview();
    showToast("备份/快照文件已读取，请先预览");
  } catch (error) {
    if (serial !== state.configImportReadSerial) return;
    showToast(`读取失败：${error instanceof SyntaxError ? "备份文件不是有效 JSON" : error.message}`, "error");
  }
}

export async function previewConfigImport() {
  if (state.configImportPreviewBusy) return;
  const source = state.configImportPackage;
  if (!source) {
    showToast("请先选择备份文件", "error");
    return;
  }
  const serial = ++state.configImportPreviewSerial;
  const allowMismatch = allowConfigChecksumMismatch();
  state.configImportPreviewBusy = true;
  state.configImportPreview = null;
  renderConfigMigrationPreview();
  const current = () => serial === state.configImportPreviewSerial && source === state.configImportPackage && allowMismatch === allowConfigChecksumMismatch();
  try {
    const result = await postJson("/config/import/preview", { package: source, allow_checksum_mismatch: allowMismatch });
    if (!current()) return;
    if (!result || !Array.isArray(result.sections) || !Number.isInteger(result.config_count)) throw new Error("预览返回不完整，请核对文件后重新预览");
    state.configImportPreview = result;
    showToast("预览完成，尚未写入");
  } catch (error) {
    if (current()) showToast(`预览失败：${error.message}`, "error");
  } finally {
    if (current()) {
      state.configImportPreviewBusy = false;
      renderConfigMigrationPreview();
    }
  }
}

export function configMigrationLocked() {
  return ["pending", "unknown"].includes(state.configMigrationResult?.status);
}

export function renderConfigMigrationResult() {
  const box = $("#configMigrationResult");
  if (!box) return;
  const item = state.configMigrationResult;
  box.hidden = !item;
  if (!item) return;
  const name = item.action === "restore" ? "恢复" : "导入";
  const titles = { pending: `${name}已提交，等待返回`, confirmed: `${name}接口已返回`, partial: `${name}部分完成：配置持久化失败`, unknown: `${name}结果未确认` };
  const result = item.response;
  box.innerHTML = `<article data-transfer-state="${escapeHtml(item.status)}">
    <h3>${escapeHtml(titles[item.status])}</h3>
    <p>本次来源：${escapeHtml(item.source)}</p>
    ${result ? `<dl><dt>导入前备份</dt><dd>${escapeHtml(result.backup_path)}</dd>
      <dt>配置保存</dt><dd>${result.config_saved ? "配置写入器返回成功" : "持久化失败；运行态或资料仍可能已经更新，不是整体未执行"}</dd>
      <dt>配置变更</dt><dd>${result.changed_config_count} 项</dd>
      <dt>方式 / 冲突</dt><dd>${result.mode === "replace" ? "覆盖所含资料段" : "合并"} / ${escapeHtml({use_backup:"使用备份",keep_current:"保留当前",fill_empty:"只补空字段"}[result.conflict])}</dd></dl>
      <p>接口返回的资料段：${result.applied_sections.length ? result.applied_sections.map(section => `${escapeHtml(section.label || section.key)} ${section.count} 条`).join("；") : "无资料段"}。</p>
      <p class="migration-note">上述数量是本次返回的资料段数量，不是全库总数。配置与资料分别保存，这份返回不证明全部资料已经落盘。其他分区保留当前输入，需主动刷新后核对当前值。</p>` : ""}
    ${item.status === "unknown" ? `<p class="migration-warn">${escapeHtml(item.error || "返回信息不完整或与本次操作不符")}。原请求可能已产生修改，本页已阻止再次导入和恢复。请先核对服务器配置、资料及备份；重新预览或看到相同值，不能证明上次操作已经完成。</p>` : ""}
    <p class="migration-note">本页结果不持久保存，刷新或离开后会消失；不会撤销已经开始的操作。</p>
  </article>`;
  renderConfigMigrationPreview();
  renderConfigBackups();
}

export async function executeConfigMigration(action, source, payload) {
  if (configMigrationLocked()) return;
  state.configMigrationResult = {status:"pending",action,source};
  renderConfigMigrationResult();
  try {
    const result = await postJson(action === "restore" ? "/config/restore" : "/config/import/apply", payload);
    const mode = action === "restore" ? "replace" : payload.mode;
    const conflict = action === "restore" ? "use_backup" : payload.conflict;
    const count = value => Number.isInteger(value) && value >= 0;
    if (!result || typeof result.config_saved !== "boolean" || typeof result.backup_path !== "string" || !result.backup_path.trim()
      || !count(result.changed_config_count) || result.mode !== mode || result.conflict !== conflict
      || !Array.isArray(result.applied_sections) || !result.applied_sections.every(section => typeof section?.key === "string" && section.key && count(section.count))
      || !Array.isArray(result.migration_backups) || !Array.isArray(result.post_import_checks)
      || (action === "restore" && result.restored_from !== payload.id)) throw new Error("返回信息不完整或与本次操作不符");
    state.configMigrationResult = {status:result.config_saved ? "confirmed" : "partial",action,source,response:result};
    state.configBackups = result.migration_backups;
    state.configLastChecks = result.post_import_checks;
    // Any completed write invalidates the earlier comparison, including another file's preview.
    state.configImportPreview = null;
    ++state.configImportPreviewSerial;
    state.configImportPreviewBusy = false;
    renderConfigImportChecks();
    showToast(result.config_saved ? `${action === "restore" ? "恢复" : "导入"}接口已返回，请查看本次结果` : "部分完成：配置持久化失败，请查看资料段与备份位置", result.config_saved ? "success" : "error");
  } catch (error) {
    state.configMigrationResult = {status:"unknown",action,source,error:error.message};
    showToast("结果未确认，请先核对；本页不会重复提交", "error");
  } finally {
    renderConfigMigrationResult();
  }
}

export async function applyConfigImport() {
  if (configMigrationLocked()) return;
  if (!state.configImportPackage || !state.configImportPreview) {
    showToast("请先预览备份内容", "error");
    return;
  }
  const mode = state.configImportPreview?.legacy_snapshot ? "merge" : ($("#configImportMode")?.value || "merge");
  const conflict = $("#configImportConflict")?.value || "use_backup";
  const conflictText = {
    use_backup: "使用备份内容",
    keep_current: "保留当前内容",
    fill_empty: "只补当前空字段",
  }[conflict] || "使用备份内容";
  const message = mode === "replace"
    ? "将覆盖可迁移资料段。已确认要继续吗？"
    : `将合并导入备份内容，字段冲突时：${conflictText}。已确认要继续吗？`;
  if (state.configImportPreview?.checksum_bypassed && !allowConfigChecksumMismatch()) {
    showToast("这份备份校验失败，确认导入前需要保持风险选项勾选", "error");
    return;
  }
  const finalMessage = state.configImportPreview?.checksum_bypassed
    ? `${message}\n\n注意：这份备份校验失败，只建议在确认它只是被手动脱敏/删改敏感字段时继续。`
    : message;
  if (!window.confirm(finalMessage)) return;
  await executeConfigMigration("import", state.configImportFileName || "所选文件", {
    package: state.configImportPackage,
    mode,
    conflict,
    allow_checksum_mismatch: allowConfigChecksumMismatch(),
  });
}

export async function restoreConfigBackup(id) {
  if (configMigrationLocked()) return;
  const backupId = String(id || "").trim();
  if (!backupId) return;
  if (!window.confirm(`将从自动备份恢复：${backupId}\n恢复前也会再次备份当前状态。继续吗？`)) return;
  await executeConfigMigration("restore", backupId, { id: backupId });
}

export function imageCacheActionResult(message, error = false) {
  const result = $("#imageCacheActionResult");
  if (result) { result.textContent = message; result.dataset.error = String(error); }
  showToast(message, error ? "error" : undefined);
}

export async function loadImageCache() {
  const params = new URLSearchParams();
  params.set("limit", "300");
  if (state.imageCacheFilter) params.set("q", state.imageCacheFilter);
  if (state.imageCacheScope && state.imageCacheScope !== "all") params.set("scope", state.imageCacheScope);
  const data = await fetchJson(`/image_cache/list?${params.toString()}`);
  const result = $("#imageCacheActionResult");
  if (result) { result.textContent = ""; result.dataset.error = "false"; }
  invalidateImageCachePreviews();
  state.imageCacheItems = Array.isArray(data.items) ? data.items : [];
  state.imageCacheTotal = Number(data.total || 0);
  state.imageCacheScopes = Array.isArray(data.scopes) ? data.scopes : [];
  state.imageCacheLoaded = true;
  if (state.selectedImageCacheKey && !state.imageCacheItems.some((item) => item.key === state.selectedImageCacheKey)) {
    state.selectedImageCacheKey = "";
  }
  if (!state.selectedImageCacheKey && state.imageCacheItems[0]) {
    state.selectedImageCacheKey = state.imageCacheItems[0].key;
  }
  renderImageCache();
  return data;
}

export async function loadTroubleshooting(options = {}) {
  const { silent = false, skipExperimentalRender = false } = options;
  const [data, overview] = await Promise.all([
    fetchJson("/troubleshooting"),
    fetchJson("/overview").catch(() => null),
  ]);
  state.troubleshooting = data || null;
  if (overview) {
    state.overview = overview;
    state.featureDraft = featureDraftFromOverview(overview);
  }
  if (!silent) renderTroubleshooting();
  if (state.activeTab === "experimental" && !skipExperimentalRender) renderExperimentalPage();
  return data;
}

export function applyOverviewData(overview) {
  state.overview = overview;
  hydrateTokenStatsFromOverview(overview);
  state.featureDraft = featureDraftFromOverview(overview);
  state.imageApiEndpointDraft = null;
  state.providerConfigMode = inferProviderConfigMode(overview);
  state.providerTimeoutDraft = normalizeModelTimeoutOverrides(overview?.settings?.model_timeout_overrides);
  state.providerFallbackDraft = normalizeModelFallbackOverrides(overview?.settings?.model_fallback_overrides);
  state.pageFontFamily = normalizePageFontFamily(overview?.settings?.page_font_family);
  state.pageTheme = normalizePageTheme(overview?.settings?.page_theme);
  applyPageFontFamily();
  applyPageTheme();
}

export function applyPageFontFamily() {
  return asteriaAppearance?.applyFontFamily(state.pageFontFamily) || normalizePageFontFamily(state.pageFontFamily);
}

export function normalizePageFontFamily(value) {
  if (asteriaAppearance?.normalizeFontFamily) {
    return asteriaAppearance.normalizeFontFamily(value);
  }
  const font = String(value || "original").trim().toLowerCase();
  return ["original", "yahei", "dengxian", "source_han", "simsun", "kaiti", "fangsong", "cheng"].includes(font)
    ? font
    : "original";
}

export async function savePageFontFamily(value) {
  const next = normalizePageFontFamily(value);
  const previous = state.pageFontFamily;
  state.pageFontFamily = next;
  applyPageFontFamily();
  try {
    const result = await postJson("/settings/update", { settings: { page_font_family: next } });
    showToast(result?.config_saved === false ? "页面字体已应用，但配置持久化失败；重启后可能恢复旧值" : "页面字体已保存", result?.config_saved === false ? "error" : "success");
  } catch (error) {
    state.pageFontFamily = previous;
    applyPageFontFamily();
    showToast(`字体保存失败：${error.message}`, "error");
  }
}

export function normalizePageTheme(raw) {
  const allowed = PAGE_THEMES.map((t) => t.value);
  const text = String(raw || "classic").trim().toLowerCase();
  return allowed.includes(text) ? text : "classic";
}

export function applyPageTheme({ explicit = false } = {}) {
  const theme = normalizePageTheme(state.pageTheme);
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("pc_theme", theme); } catch (e) {}
  if (explicit) {
    const url = new URL(location.href);
    url.searchParams.delete("theme");
    history.replaceState(history.state, "", url);
  }
  if (!new URLSearchParams(location.search).has("theme")) document.documentElement.dataset.adminTheme = "custom";
}

export function renderAppearanceSettings() {
  const current = normalizePageTheme(state.pageTheme);
  const grid = document.getElementById("appearanceThemeGrid");
  if (grid) {
    grid.innerHTML = PAGE_THEMES.map((t) => {
      const swatches = t.swatch.map((c) => `<span style="background:${c}"></span>`).join("");
      return `<div class="appearance-theme-option${t.value === current ? " is-active" : ""}" data-theme-value="${t.value}" role="radio" aria-checked="${t.value === current}" tabindex="0">
        <div class="appearance-theme-swatch">${swatches}</div>
        <div class="appearance-theme-label"><span>${escapeHtml(t.label)}</span></div>
      </div>`;
    }).join("");
  }
}

export function applyUserGroupLists(users, groups) {
  state.users = Array.isArray(users?.items) ? users.items : [];
  state.groups = Array.isArray(groups?.items) ? groups.items : [];
  state.userGroupListError = "";
  if (!state.selectedUserId && state.users[0]) state.selectedUserId = state.users[0].user_id;
  if (!state.selectedGroupId && state.groups[0]) state.selectedGroupId = state.groups[0].group_id;
}

export function renderAfterUserGroupListsLoaded() {
  renderDashboardPulse();
  renderRelationshipChart();
  renderGroupBubbleChart();
  if (state.activeTab === "private") {
    renderUsers();
  } else if (state.activeTab === "learning") {
    renderLearning();
  } else if (state.activeTab === "group") {
    renderGroups();
  } else if (state.activeTab === "memory") {
    renderMemory();
  } else if (state.activeTab === "proactive") {
    renderProactiveCandidates();
  } else if (state.activeTab === "experimental") {
    renderExperimentalPage();
  }
}

export async function loadUserGroupLists(requestSeq = asteriaWorkspaceState.loadAllRequestSeq, options = {}) {
  const { showErrors = false, silent = false, force = false } = options;
  if (!force && state.lazyLoaded.userGroupLists) {
    return { users: { items: state.users }, groups: { items: state.groups } };
  }
  if (!force && state.userGroupListPromise) return state.userGroupListPromise;
  state.userGroupListError = "";
  if (!silent && state.activeTab === "learning") renderLearningSummary();
  const promise = (async () => {
    try {
      const [users, groups] = await Promise.all([
        fetchJson("/users?limit=300"),
        fetchJson("/groups?limit=300"),
      ]);
      if (requestSeq !== asteriaWorkspaceState.loadAllRequestSeq) return null;
      applyUserGroupLists(users, groups);
      state.lazyLoaded.userGroupLists = true;
      if (!silent) {
        renderAfterUserGroupListsLoaded();
        const overview = state.overview || {};
        $("#subtitle").textContent = `${overview.plugin?.bot_name || "Private Companion"} · ${new Date().toLocaleString()}`;
      }
      return { users, groups };
    } catch (error) {
      if (requestSeq !== asteriaWorkspaceState.loadAllRequestSeq) return null;
      state.userGroupListError = error.message || "名单读取失败";
      console.warn("[PrivateCompanionPage] 用户/群聊列表加载失败", error);
      if (!silent) {
        const overview = state.overview || {};
        $("#subtitle").textContent = `${overview.plugin?.bot_name || "Private Companion"} · 总览已加载，名单加载失败`;
        if (state.activeTab === "learning") renderLearningSummary();
      }
      if (showErrors) showToast(`名单加载失败：${error.message}`, "error");
      return null;
    }
  })();
  state.userGroupListPromise = promise;
  try {
    return await promise;
  } finally {
    if (state.userGroupListPromise === promise) state.userGroupListPromise = null;
  }
}

export async function loadAll(options = {}) {
  const requestSeq = ++asteriaWorkspaceState.loadAllRequestSeq;
  const { waitForLists = false } = options;
  state.lazyLoaded.userGroupLists = false;
  state.userGroupListPromise = null;
  state.userGroupListError = "";
  state.expressionLibrary = null;
  state.expressionLibraryError = "";
  $("#subtitle").textContent = "读取运行态中...";
  try {
    const overview = await fetchJson("/overview");
    if (requestSeq !== asteriaWorkspaceState.loadAllRequestSeq) return;
    applyOverviewData(overview);
    state.overviewRefreshedAt = Date.now();
    renderAll();
    void ensureTabData(state.activeTab, true);
    $("#subtitle").textContent = `${overview.plugin?.bot_name || "Private Companion"} · 总览已加载`;
    const loadLists = () => {
      if (state.lazyLoaded.userGroupLists) return Promise.resolve(null);
      $("#subtitle").textContent = `${overview.plugin?.bot_name || "Private Companion"} · 正在后台补全名单...`;
      return loadUserGroupLists(requestSeq, { showErrors: true });
    };
    if (waitForLists) {
      await loadLists();
    } else {
      runWhenIdle(() => { loadLists(); }, 900);
    }
  } catch (error) {
    if (requestSeq !== asteriaWorkspaceState.loadAllRequestSeq) return;
    $("#subtitle").textContent = `加载失败：${error.message}`;
  }
}

export function hydrateTokenStatsFromOverview(overview) {
  const tokenStats = overview?.token_stats;
  if (!tokenStats || typeof tokenStats !== "object") return;
  state.tokenStats = tokenStats;
  state.tokenStatsPartial = true;
  state.lazyLoaded.tokenStats = false;
}

export function renderAll() {
  scheduleDailyOutfitHydration();
  renderStats();
  renderDashboard();
  renderActiveTab(state.activeTab);
  renderSetupGuideOverlay();
}

export function renderActiveTab(tabName = state.activeTab || "dashboard") {
  if (tabName === "private") {
    renderUsers();
  } else if (tabName === "learning") {
    renderLearning();
  } else if (tabName === "group") {
    renderGroups();
  } else if (tabName === "memory") {
    renderMemory();
  } else if (tabName === "proactive") {
    renderProactiveCandidates();
  } else if (tabName === "bookshelf") {
    renderBookshelf();
  } else if (tabName === "qzone") {
    if (asteriaQzone?.render) {
      asteriaQzone.render({ fetchJson, postJson, showToast, escapeHtml, document });
    } else {
      const meta = document.getElementById("qzoneFeedMeta");
      const feed = document.getElementById("qzoneFeed");
      if (meta) meta.textContent = "QQ 空间面板脚本未加载";
      if (feed && !feed.innerHTML.trim()) feed.innerHTML = `<div class="empty small">QQ 空间面板脚本未加载。请刷新拓展页；若仍失败，检查 qzone-panel.js 是否被浏览器拦截。</div>`;
    }
  } else if (tabName === "image-cache") {
    renderImageCache();
  } else if (tabName === "troubleshooting") {
    renderTroubleshooting();
  } else if (tabName === "tokens") {
    renderTokens();
  } else if (tabName === "roleplay") {
    renderModuleSettings();
    renderRoleplayPersonaDraftPanel();
  } else if (tabName === "config") {
    renderConfig();
    renderModuleSettings();
  } else if (tabName === "models") {
    renderProviders();
  } else if (tabName === "experimental") {
    renderExperimentalPage();
  }
}

export async function loadDiagnostics(force = false, options = {}) {
  const { skipExperimentalRender = false } = options;
  if (state.lazyLoaded.diagnostics && !force) return state.diagnostics;
  const diagnostics = await fetchJson("/diagnostics");
  state.diagnostics = diagnostics.items || [];
  state.lazyLoaded.diagnostics = true;
  if (state.activeTab === "troubleshooting") {
    renderDiagnostics();
  }
  if (state.activeTab === "experimental" && !skipExperimentalRender) {
    renderExperimentalPage();
  }
  renderDashboardPulse();
  return state.diagnostics;
}

export async function refreshExperimentalRuntimeData(force = false) {
  const requestSeq = asteriaWorkspaceState.loadAllRequestSeq;
  await Promise.all([
    loadDiagnostics(force, { skipExperimentalRender: true }).catch(() => null),
    loadTroubleshooting({ silent: true, skipExperimentalRender: true }).catch(() => null),
    loadUserGroupLists(requestSeq, { silent: true, force }).catch(() => null),
  ]);
  if (state.activeTab === "experimental") renderExperimentalPage();
}

export function scheduleExperimentalRuntimeRefresh(force = false) {
  state.experimentalRuntimeRefreshForce = Boolean(state.experimentalRuntimeRefreshForce || force);
  if (state.experimentalRuntimeRefreshTimer) {
    clearTimeout(state.experimentalRuntimeRefreshTimer);
  }
  state.experimentalRuntimeRefreshTimer = setTimeout(() => {
    const shouldForce = Boolean(state.experimentalRuntimeRefreshForce);
    state.experimentalRuntimeRefreshForce = false;
    state.experimentalRuntimeRefreshTimer = null;
    refreshExperimentalRuntimeData(shouldForce).catch(() => {});
  }, 120);
}

export async function loadTokenStats(force = false) {
  if (state.lazyLoaded.tokenStats && !force && !state.tokenStatsPartial) return state.tokenStats;
  const tokenStats = await fetchJson("/token/stats");
  applyTokenStatsSnapshot(tokenStats);
  return state.tokenStats;
}

export function applyTokenStatsSnapshot(tokenStats) {
  state.tokenStats = tokenStats || null;
  state.tokenStatsPartial = false;
  state.lazyLoaded.tokenStats = true;
  renderStats();
  if (state.activeTab === "tokens") renderTokens();
  if (state.activeTab === "dashboard") renderDashboardPulse();
  return state.tokenStats;
}

export async function loadAvailableProviders(force = false) {
  if (state.lazyLoaded.providers && !force) return state.availableProviders;
  const availableProviders = await fetchJson("/providers/available");
  state.availableProviders = availableProviders.items || [];
  state.lazyLoaded.providers = true;
  if (state.activeTab === "models") renderProviders();
  if (state.activeTab === "config" || state.activeTab === "roleplay") renderModuleSettings();
  return state.availableProviders;
}

export async function loadRoleplayPersonas(force = false) {
  if (state.lazyLoaded.roleplayPersonas && !force) return state.roleplayPersonas;
  const result = await fetchJson("/roleplay/personas").catch(() => ({ items: [] }));
  state.roleplayPersonas = Array.isArray(result.items) ? result.items : [];
  state.lazyLoaded.roleplayPersonas = true;
  const draft = setupGuideDraft();
  if (!draft.personaId) {
    draft.personaId = result.current || result.default || state.roleplayPersonas[0]?.id || "";
  }
  return state.roleplayPersonas;
}

export async function loadConfigBackups(force = false) {
  if (state.lazyLoaded.configBackups && !force) return state.configBackups;
  const configBackups = await fetchJson("/config/backups").catch(() => ({ items: [] }));
  state.configBackups = configBackups.items || [];
  state.lazyLoaded.configBackups = true;
  if (state.activeTab === "config") renderConfigBackups();
  return state.configBackups;
}

export async function ensureTabData(tabName, force = false) {
  if (tabName === "dashboard") {
    return;
  }
  if (["private", "group", "learning", "memory", "proactive", "experimental"].includes(tabName) && (!state.lazyLoaded.userGroupLists || force)) {
    await loadUserGroupLists(asteriaWorkspaceState.loadAllRequestSeq, { showErrors: true, force });
  }
  if (tabName === "tokens") {
    await loadTokenStats(force);
  } else if (tabName === "models") {
    await loadAvailableProviders(force);
  } else if (tabName === "roleplay") {
    loadAvailableProviders(force).catch(() => {});
  } else if (tabName === "config") {
    await loadConfigBackups(force);
  } else if (tabName === "image-cache") {
    renderImageCache();
    await loadImageCache();
  } else if (tabName === "troubleshooting") {
    renderTroubleshooting();
    loadDiagnostics(force).catch(() => {});
    await loadTroubleshooting();
  } else if (tabName === "experimental") {
    renderExperimentalPage();
    await refreshExperimentalRuntimeData(force);
  }
}
