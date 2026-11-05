/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {installWorkspaceShell} from './page-runtime.js';
import {fetchJson,postJson} from './client.js';
import {renderImageCache} from './image-cache.js';
import {checkWorldbookObservation,handleWorldbookGroupAction,handleWorldbookMemberAction,renderGroups,renderUsers,renderWorldbook} from './learning.js';
import {closeMemoEditor,currentMemoNotes,openMemoEditor,readCreativeOperation,renderBookshelf,renderMemoNotes,saveCreativeOperation,saveSelectedBookshelfReadingState,saveSkillRecord,skillExpFloor,transitionBookshelfPage,updateMemoAction} from './library.js';
import {renderBookDetailPanel,renderProactiveRecords,renderStorageConfig,selectBookshelfBook,setBookshelfUnlockMessage} from './life.js';
import {applyBookPreferenceTagPick,applyProviderRead,completeTokenStatsSnapshot,deleteSelectedBookshelfItem,initNativeCompanionNavigation,providerFormSnapshot,providerLaterValues,providerReadComplete,providerReceiptComplete,providerReceiptMap,providerSame,rateSelectedBookshelfItem,renderProviderSaveNotice,renderTokenResetNotice,rereadSelectedBookshelfItem,savePageTheme,switchTab,updateSelectedBookshelfTags} from './navigation.js';
import {copyTextToClipboard,requireSecondClick,runAction,setActionBusy,showToast} from './persona.js';
import {bindProviderToolbar,renderProviders,testProvider} from './providers.js';
import {renderTroubleshooting,syncTroubleshootingTestButtons,troubleshootingTestPresentation,troubleshootingTestResult,updateTroubleshootingWarningSuppression} from './relationships.js';
import {featureDraftFromOverview,featureLockedByProactiveOnlyMode,providerAllowedInCurrentMode,toBool,visibleConfigKey} from './schema.js';
import {accessDraftFromForm,bindRoleplayModeSwitch,bindSegmentedPreview,collectFormSettings,markModuleFormClean,markModuleFormDirty,newsSourceItemsFromDom,newsSourcePlaceholder,newsSourceTypeLabel,renderAccessManager,renderFeatureSwitches,renderNewsSourceManager,resetNewsSourcesToDefault,saveCurrentFeatureDetail,saveRoleplayWorkspace,syncNewsSourcesRaw,writeAccessDraft} from './settings.js';
import {applySetupGuide,clearSetupGuideProactivePoll,generateSetupGuideRoleplayDraft,invalidateSetupGuideProviderTest,renderSetupGuideOverlay,rerenderSetupGuideOverlayPreserveScroll,runSetupGuideDailyGeneration,runSetupGuideProactiveTest,saveSetupGuideAdvancedBlock,setupGuideAdvancedStepIndex,setupGuideApplyIntensityPreset,setupGuideDraft,setupGuideStepBlockMessage,setupGuideStepIndex,testAllSetupGuideProviders,testSetupGuideProvider,updateSetupGuideSelectedStates,updateSetupGuideStatusViews} from './setup.js';
import {$,providerLabels,safeFeatureKeys,setupGuideAdvancedItems,setupGuideAdvancedToggleFields,setupGuideDynamicFields,setupGuideQuickProviderKeys,setupGuideSteps,state} from './state.js';
import {normalizedTokenSource,renderTokens} from './usage.js';
import {applyConfigImport,applyTokenStatsSnapshot,bindBookshelfCoverPreviewDismissal,closeBookshelfCoverPreview,downloadJson,handleConfigExport,imageCacheActionResult,loadAll,loadAvailableProviders,loadDiagnostics,loadImageCache,loadRoleplayPersonas,loadTroubleshooting,openBookshelfCoverPreview,openTLSNativeWorkspace,previewConfigImport,readConfigImportFile,renderConfigMigrationPreview,restoreConfigBackup,savePageFontFamily} from './workspace.js';
import asteriaProviders from '../js/panels/provider-tree.js';

let started=false;
export function startWorkspace(){
  if(started)return;
  started=true;
  installWorkspaceShell('companion');
bindBookshelfCoverPreviewDismissal();
document.querySelectorAll(".annotations .tab[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    switchTab(button.dataset.tab);
  });
});
document.addEventListener("click", async (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  if (target.closest("[data-setup-guide-open]")) {
    state.setupGuideOpen = true;
    state.setupGuideMode = "home";
    state.setupGuideAdvancedBlock = "";
    state.setupGuideAdvancedStep = 0;
    renderSetupGuideOverlay();
    Promise.all([loadAvailableProviders(false), loadRoleplayPersonas(false)])
      .then(() => {
        const active = document.activeElement;
        const editingGuideField = active instanceof Element && Boolean(active.closest(".setup-guide-modal [data-setup-guide-field]"));
        if (state.setupGuideOpen && !editingGuideField) renderSetupGuideOverlay();
      })
      .catch(() => {});
    return;
  }
  if (target.closest("[data-setup-guide-close]")) {
    state.setupGuideOpen = false;
    clearSetupGuideProactivePoll();
    renderSetupGuideOverlay();
    return;
  }
  const modeButton = target.closest("[data-setup-guide-mode]");
  if (modeButton) {
    const requestedMode = modeButton.dataset.setupGuideMode || "home";
    state.setupGuideMode = requestedMode === "advanced" ? "advanced" : requestedMode === "first" ? "first" : "home";
    if (state.setupGuideMode !== "advanced") {
      state.setupGuideAdvancedBlock = "";
      state.setupGuideAdvancedStep = 0;
    }
    renderSetupGuideOverlay();
    return;
  }
  const advancedBlockButton = target.closest("[data-setup-guide-advanced-block]");
  if (advancedBlockButton) {
    state.setupGuideMode = "advanced";
    state.setupGuideAdvancedBlock = advancedBlockButton.dataset.setupGuideAdvancedBlock || "";
    state.setupGuideAdvancedStep = 0;
    renderSetupGuideOverlay();
    return;
  }
  if (target.closest("[data-setup-guide-advanced-home]")) {
    state.setupGuideMode = "advanced";
    state.setupGuideAdvancedBlock = "";
    state.setupGuideAdvancedStep = 0;
    renderSetupGuideOverlay();
    return;
  }
  if (target.closest("[data-setup-guide-prev]")) {
    if (state.setupGuideMode === "advanced") {
      if (state.setupGuideAdvancedBlock && setupGuideAdvancedStepIndex() > 0) {
        state.setupGuideAdvancedStep = setupGuideAdvancedStepIndex() - 1;
      } else if (state.setupGuideAdvancedBlock) {
        state.setupGuideAdvancedBlock = "";
        state.setupGuideAdvancedStep = 0;
      } else {
        state.setupGuideMode = "home";
      }
      renderSetupGuideOverlay();
      return;
    }
    state.setupGuideStep = Math.max(0, setupGuideStepIndex() - 1);
    state.setupGuideOpen = true;
    renderSetupGuideOverlay();
    return;
  }
  const providerTestAll = target.closest("[data-setup-guide-provider-test-all]");
  if (providerTestAll instanceof HTMLButtonElement) {
    await testAllSetupGuideProviders(providerTestAll);
    return;
  }
  const providerTest = target.closest("[data-setup-guide-provider-test]");
  if (providerTest instanceof HTMLButtonElement) {
    await testSetupGuideProvider(providerTest.dataset.setupGuideProviderTest || "", providerTest);
    return;
  }
  const roleplayDraftButton = target.closest("[data-setup-guide-roleplay-draft]");
  if (roleplayDraftButton instanceof HTMLButtonElement) {
    await generateSetupGuideRoleplayDraft(roleplayDraftButton);
    return;
  }
  const dailyRunButton = target.closest("[data-setup-guide-daily-run]");
  if (dailyRunButton instanceof HTMLButtonElement) {
    await runSetupGuideDailyGeneration(dailyRunButton);
    return;
  }
  const proactiveTestButton = target.closest("[data-setup-guide-proactive-test]");
  if (proactiveTestButton instanceof HTMLButtonElement) {
    await runSetupGuideProactiveTest(proactiveTestButton);
    return;
  }
  const swapImageApiButton = target.closest("[data-swap-image-api]");
  if (swapImageApiButton instanceof HTMLButtonElement) {
    if (!requireSecondClick(swapImageApiButton, "swap-image-api", "再次点击交换在线生图 API 优先级", "再次点击交换")) return;
    const result = await runAction(
      () => postJson("/settings/swap_image_api", {}),
      "已交换在线生图 API 优先级",
      swapImageApiButton,
    );
    if (result?.plugin) {
      state.setupGuideDraft = null;
      state.featureDraft = featureDraftFromOverview(result);
      renderSetupGuideOverlay();
    }
    return;
  }
  if (target.closest("[data-setup-guide-world-confirm]")) {
    const draft = setupGuideDraft();
    draft.worldKnowledgeConfirmed = true;
    renderSetupGuideOverlay();
    showToast("已确认世界知识草稿");
    return;
  }
  if (target.closest("[data-setup-guide-worldbook-confirm]")) {
    const draft = setupGuideDraft();
    draft.worldbookDraftConfirmed = true;
    rerenderSetupGuideOverlayPreserveScroll();
    showToast("已确认关系网词条草稿");
    return;
  }
  if (target.closest("[data-setup-guide-finish-explore]")) {
    const button = target.closest("[data-setup-guide-finish-explore]");
    await applySetupGuide({ close: true, advanced: false, control: button instanceof HTMLButtonElement ? button : null });
    return;
  }
  if (target.closest("[data-setup-guide-advanced]")) {
    const button = target.closest("[data-setup-guide-advanced]");
    const saved = await applySetupGuide({ close: false, advanced: true, control: button instanceof HTMLButtonElement ? button : null, successMessage: "首次配置已保存，继续进阶配置" });
    if (saved) {
      state.setupGuideMode = "advanced";
      state.setupGuideAdvancedBlock = "";
      state.setupGuideAdvancedStep = 0;
      state.setupGuideOpen = true;
      renderSetupGuideOverlay();
    }
    return;
  }
  if (target.closest("[data-setup-guide-next]")) {
    if (state.setupGuideMode === "advanced") {
      const button = target.closest("[data-setup-guide-next]");
      const blockId = state.setupGuideAdvancedBlock || "";
      const items = setupGuideAdvancedItems[blockId] || [];
      const stepIndex = setupGuideAdvancedStepIndex(blockId);
      if (items.length && stepIndex < items.length - 1) {
        state.setupGuideAdvancedStep = stepIndex + 1;
        renderSetupGuideOverlay();
        return;
      }
      const saved = await saveSetupGuideAdvancedBlock(button instanceof HTMLButtonElement ? button : null);
      if (saved) {
        state.setupGuideAdvancedBlock = "";
        state.setupGuideAdvancedStep = 0;
        renderSetupGuideOverlay();
      }
      return;
    }
    const index = setupGuideStepIndex();
    const blockMessage = setupGuideStepBlockMessage(index + 1);
    if (blockMessage) {
      showToast(blockMessage, "error");
      return;
    }
    if (index >= setupGuideSteps.length - 1) {
      const button = target.closest("[data-setup-guide-next]");
      await applySetupGuide({ close: true, advanced: false, control: button instanceof HTMLButtonElement ? button : null });
      return;
    } else {
      state.setupGuideStep = index + 1;
      state.setupGuideOpen = true;
    }
    renderSetupGuideOverlay();
    return;
  }
  const advancedStepTarget = target.closest("[data-setup-guide-advanced-step]");
  if (advancedStepTarget) {
    const blockId = state.setupGuideAdvancedBlock || "";
    const items = setupGuideAdvancedItems[blockId] || [];
    const index = Number(advancedStepTarget.dataset.setupGuideAdvancedStep || 0);
    if (items.length) {
      state.setupGuideAdvancedStep = Math.max(0, Math.min(items.length - 1, Number.isFinite(index) ? index : 0));
      renderSetupGuideOverlay();
    }
    return;
  }
  const stepTarget = target.closest("[data-setup-guide-step]");
  if (stepTarget) {
    const index = Number(stepTarget.dataset.setupGuideStep || 0);
    const nextIndex = Math.max(0, Math.min(setupGuideSteps.length - 1, Number.isFinite(index) ? index : 0));
    const blockMessage = setupGuideStepBlockMessage(nextIndex);
    if (blockMessage) {
      showToast(blockMessage, "error");
      return;
    }
    state.setupGuideStep = nextIndex;
    renderSetupGuideOverlay();
  }
});
document.addEventListener("input", (event) => {
  const input = event.target instanceof Element ? event.target.closest("[data-setup-guide-field]") : null;
  if (!input) return;
  const key = input.dataset.setupGuideField || "";
  if (!key) return;
  const draft = setupGuideDraft();
  const previousValue = draft[key];
  if (input instanceof HTMLInputElement && input.type === "checkbox") {
    draft[key] = input.checked;
  } else {
    draft[key] = input.value;
  }
  if (setupGuideQuickProviderKeys.includes(key) && String(previousValue || "") !== String(draft[key] || "")) {
    invalidateSetupGuideProviderTest(key);
  }
  if (key === "personaId" && String(previousValue || "") !== String(draft[key] || "")) {
    state.setupGuideRoleplayDraft = null;
    draft.worldKnowledgeConfirmed = false;
  }
  if (key.startsWith("worldKnowledge") && key !== "worldKnowledgeConfirmed") {
    draft.worldKnowledgeConfirmed = false;
  }
  if (key.startsWith("worldbook") && key !== "worldbookDraftConfirmed") {
    draft.worldbookDraftConfirmed = false;
  }
  if (key === "privateIntensity" && String(previousValue || "") !== String(draft[key] || "")) {
    setupGuideApplyIntensityPreset(String(draft[key] || "off"));
    rerenderSetupGuideOverlayPreserveScroll();
    return;
  }
  if (state.setupGuideMode === "advanced" && setupGuideAdvancedToggleFields.has(key) && String(previousValue || "") !== String(draft[key] || "")) {
    rerenderSetupGuideOverlayPreserveScroll();
    return;
  }
  if (setupGuideDynamicFields.has(key) && String(previousValue || "") !== String(draft[key] || "")) {
    rerenderSetupGuideOverlayPreserveScroll();
    return;
  }
  updateSetupGuideStatusViews();
});
document.addEventListener("change", (event) => {
  const advancedToggle = event.target instanceof Element ? event.target.closest("[data-setup-guide-advanced-toggle]") : null;
  if (advancedToggle) {
    const key = advancedToggle.dataset.setupGuideAdvancedToggle || "";
    if (!key) return;
    const draft = setupGuideDraft();
    const nextValue = String(advancedToggle.value || "").toLowerCase() === "true";
    if (Boolean(draft[key]) !== nextValue) {
      draft[key] = nextValue;
      rerenderSetupGuideOverlayPreserveScroll();
    } else {
      updateSetupGuideSelectedStates(advancedToggle.closest(".setup-guide-form") || document);
    }
    return;
  }
  const input = event.target instanceof Element ? event.target.closest("[data-setup-guide-field]") : null;
  if (!input) return;
  const key = input.dataset.setupGuideField || "";
  if (!key) return;
  const draft = setupGuideDraft();
  const previousValue = draft[key];
  if (input instanceof HTMLInputElement && input.type === "checkbox") {
    draft[key] = input.checked;
  } else {
    draft[key] = input.value;
  }
  if (setupGuideQuickProviderKeys.includes(key) && String(previousValue || "") !== String(draft[key] || "")) {
    invalidateSetupGuideProviderTest(key);
  }
  if (key === "personaId" && String(previousValue || "") !== String(draft[key] || "")) {
    state.setupGuideRoleplayDraft = null;
    draft.worldKnowledgeConfirmed = false;
  }
  if (key.startsWith("worldKnowledge") && key !== "worldKnowledgeConfirmed") {
    draft.worldKnowledgeConfirmed = false;
  }
  if (key.startsWith("worldbook") && key !== "worldbookDraftConfirmed") {
    draft.worldbookDraftConfirmed = false;
  }
  if (key === "privateIntensity" && String(previousValue || "") !== String(draft[key] || "")) {
    setupGuideApplyIntensityPreset(String(draft[key] || "off"));
    rerenderSetupGuideOverlayPreserveScroll();
    return;
  }
  if (state.setupGuideMode === "advanced" && setupGuideAdvancedToggleFields.has(key) && String(previousValue || "") !== String(draft[key] || "")) {
    rerenderSetupGuideOverlayPreserveScroll();
    return;
  }
  if (setupGuideDynamicFields.has(key) && String(previousValue || "") !== String(draft[key] || "")) {
    rerenderSetupGuideOverlayPreserveScroll();
    return;
  }
  updateSetupGuideSelectedStates(input.closest(".setup-guide-form") || document);
  updateSetupGuideStatusViews();
});
document.addEventListener("click", async (event) => {
  const target = event.target instanceof Element ? event.target.closest("[data-jump-tab]") : null;
  if (!target) return;
  state.setupGuideOpen = false;
  clearSetupGuideProactivePoll();
  renderSetupGuideOverlay();
  switchTab(target.dataset.jumpTab);
});
document.addEventListener("click", async (event) => {
  const element = event.target instanceof Element ? event.target : null;
  const nativeEntry = element?.closest("[data-tls-native-entry]");
  if (nativeEntry) {
    event.preventDefault();
    await openTLSNativeWorkspace(nativeEntry.dataset.tlsNativeEntry);
    return;
  }
  const coverPreviewTrigger = element?.closest("[data-bookshelf-cover-preview]");
  if (coverPreviewTrigger) {
    openBookshelfCoverPreview(coverPreviewTrigger);
    return;
  }
  if (element?.closest("[data-bookshelf-cover-preview-close]") || element?.id === "bookshelfCoverPreview") {
    closeBookshelfCoverPreview();
    return;
  }
  const memoActionButton = element?.closest("[data-memo-action]");
  if (memoActionButton) {
    const noteId = memoActionButton.dataset.memoId || "";
    const note = currentMemoNotes().find((item) => String(item.id || "") === noteId);
    if (note) await updateMemoAction(memoActionButton.dataset.memoAction || "", note, memoActionButton);
    return;
  }
  const warningSuppression = element?.closest("[data-troubleshooting-warning-action]");
  if (warningSuppression) {
    await updateTroubleshootingWarningSuppression(warningSuppression);
    return;
  }
  const troubleshootingFilter = element?.closest("[data-troubleshooting-filter]");
  if (troubleshootingFilter) {
    state.troubleshootingFilter = troubleshootingFilter.dataset.troubleshootingFilter || "all";
    renderTroubleshooting();
    return;
  }
  const troubleshootingCategory = element?.closest("[data-troubleshooting-category]");
  if (troubleshootingCategory) {
    state.troubleshootingCategory = troubleshootingCategory.dataset.troubleshootingCategory || "all";
    state.troubleshootingFilter = "all";
    renderTroubleshooting();
    return;
  }
  const troubleshootingRefresh = element?.closest("[data-troubleshooting-refresh]");
  if (troubleshootingRefresh) {
    setActionBusy(troubleshootingRefresh, true);
    try {
      await Promise.all([loadTroubleshooting(), loadDiagnostics(true)]);
      showToast("排障信息已刷新");
    } catch (error) {
      showToast(`刷新失败：${error.message}`, "error");
    } finally {
      setActionBusy(troubleshootingRefresh, false);
    }
    return;
  }
  const scrollTarget = element?.closest("[data-scroll-target]");
  if (scrollTarget) {
    const targetId = scrollTarget.dataset.scrollTarget || "";
    const targetEl = targetId ? document.getElementById(targetId) : null;
    if (targetEl) {
      const disclosure = targetEl.closest("details");
      if (disclosure) disclosure.open = true;
      requestAnimationFrame(() => targetEl.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
    return;
  }
  const troubleshootingTest = element?.closest("[data-troubleshooting-test]");
  if (troubleshootingTest) {
    const testType = troubleshootingTest.dataset.troubleshootingTest || "";
    const workflowKind = troubleshootingTest.dataset.troubleshootingWorkflowKind || "";
    if (!testType || ["running", "unknown"].includes(state.troubleshootingTestAttempts[testType]?.status) || troubleshootingTestResult(testType).pending) return;
    state.troubleshootingTestAttempts[testType] = {status: "running"};
    syncTroubleshootingTestButtons();
    try {
      const result = await postJson("/troubleshooting/test", { type: testType, workflow_kind: workflowKind });
      if (!result || result.type !== testType || typeof result.ok !== "boolean"
        || !Number.isFinite(result.ran_at) || result.ran_at <= 0
        || (result.pending !== undefined && typeof result.pending !== "boolean")) {
        throw new Error("返回的操作类别或结果字段不完整");
      }
      state.troubleshooting = state.troubleshooting || {};
      state.troubleshooting.chain_tests = {...(state.troubleshooting.chain_tests || {}), [testType]: result};
      state.troubleshootingTestAttempts[testType] = {status: "returned", result};
      const presentation = troubleshootingTestPresentation(result);
      renderTroubleshooting();
      showToast(presentation.label, ["warn", "error"].includes(presentation.status) ? "error" : "success");
    } catch (error) {
      state.troubleshootingTestAttempts[testType] = {status: "unknown", error: String(error.message || error)};
      renderTroubleshooting();
      showToast("本次结果未确认，请核对留存记录与实际结果；不会自动重发测试", "error");
    }
    return;
  }
  const copyButton = element?.closest("[data-copy-text]");
  if (copyButton) {
    void copyTextToClipboard(copyButton.dataset.copyText || "", "已复制摘要");
    return;
  }
  const row = element?.closest("[data-image-cache-key]");
  if (row) {
    state.selectedImageCacheKey = row.dataset.imageCacheKey || "";
    renderImageCache();
    return;
  }
  const deleteButton = element?.closest("[data-image-cache-delete]");
  if (deleteButton) {
    const key = deleteButton.dataset.imageCacheDelete || "";
    if (!key) return;
    if (!requireSecondClick(deleteButton, `image-cache:${key}`, "再次点击会删除这条图片缓存")) return;
    setActionBusy(deleteButton, true);
    try {
      const deleted = await postJson("/image_cache/delete", { key });
      if (deleted?.key !== key || !Number.isInteger(deleted.remaining) || deleted.remaining < 0) {
        imageCacheActionResult("删除结果未确认，请先刷新列表核对，不要重复提交", true);
        return;
      }
      const present = state.imageCacheItems.some(item => item.key === key);
      state.imageCacheItems = state.imageCacheItems.filter(item => item.key !== key);
      if (present) state.imageCacheTotal = Math.max(0, state.imageCacheTotal - 1);
      if (state.selectedImageCacheKey === key) state.selectedImageCacheKey = "";
      renderImageCache();
      try {
        await loadImageCache();
        imageCacheActionResult("图片缓存已删除");
      } catch (error) {
        imageCacheActionResult(`图片缓存已删除；最新列表读取失败，当前列表仅按已确认结果更新：${error.message}`, true);
      }
    } catch (error) {
      imageCacheActionResult(`删除失败：${error.message}`, true);
    } finally {
      setActionBusy(deleteButton, false);
    }
  }
});
document.addEventListener("click", async (event) => {
  const element = event.target instanceof Element ? event.target : null;
  const proactiveDeleteButton = element?.closest("[data-proactive-candidate-delete]");
  if (proactiveDeleteButton) {
    const candidateId = proactiveDeleteButton.dataset.proactiveCandidateDelete || "";
    const userId = proactiveDeleteButton.dataset.proactiveUserId || "";
    if (!candidateId) return;
    if (!requireSecondClick(proactiveDeleteButton, `proactive-delete:${candidateId}`, "再次点击删除候选；若关联当前计划也会重新安排检查，已开始或发出的消息不能撤回", "确认删除候选")) return;
    await runAction(async () => {
      const result = await postJson("/proactive/candidate/delete", { candidate_id: candidateId, user_id: userId });
      if (state.overview) {
        state.overview.proactive_candidates = result.proactive_candidates || state.overview.proactive_candidates;
        state.overview.proactive_tasks = result.proactive_tasks || state.overview.proactive_tasks;
      }
      return {...(state.overview || {}), message: result.message || (result.cleared_current_plan ? "已删除候选，并重新安排关联检查" : "已删除候选")};
    }, "", proactiveDeleteButton);
    return;
  }
  const proactivePruneButton = element?.closest("[data-proactive-candidate-prune]");
  if (proactivePruneButton) {
    const userId = proactivePruneButton.dataset.proactiveCandidatePrune || "";
    const keep = Number(proactivePruneButton.dataset.proactivePruneKeep || 160) || 160;
    if (!userId) return;
    if (!requireSecondClick(proactivePruneButton, `proactive-prune:${userId}:${keep}`, `再次点击将该用户未发送候选压到 ${keep} 条`, "确认整理该用户候选")) return;
    await runAction(async () => {
      const result = await postJson("/proactive/candidate/prune", { user_id: userId, keep });
      if (state.overview) {
        state.overview.proactive_candidates = result.proactive_candidates || state.overview.proactive_candidates;
        state.overview.proactive_tasks = result.proactive_tasks || state.overview.proactive_tasks;
      }
      return {...(state.overview || {}), message: result.message || `已整理 ${Number(result.removed || 0)} 条未发送候选`};
    }, "", proactivePruneButton);
    return;
  }
  const creativeReanalyze = element?.closest("[data-creative-reanalyze]");
  if (creativeReanalyze) {
    const projectId = creativeReanalyze.dataset.creativeReanalyze || "";
    await saveCreativeOperation("reanalyze", "/creative/project/reanalyze", {id:projectId}, "分析");
    return;
  }
  const creativeRebuildMemory = element?.closest("[data-creative-rebuild-memory]");
  if (creativeRebuildMemory) {
    const projectId = creativeRebuildMemory.dataset.creativeRebuildMemory || "";
    await saveCreativeOperation("rebuild", "/creative/project/rebuild_memory", {id:projectId}, "作品内部资料");
    return;
  }
  const deleteButton = element?.closest("[data-book-delete]");
  if (deleteButton) {
    void deleteSelectedBookshelfItem(deleteButton);
    return;
  }
  const bookButton = element?.closest("[data-book-id]");
  if (bookButton) {
    selectBookshelfBook(bookButton.dataset.bookId);
    return;
  }
  if (element?.closest("[data-creative-enter-edit]")) {
    state.creativeEditing = true;
    renderBookDetailPanel();
    return;
  }
  if (element?.closest("[data-creative-exit-edit]")) {
    state.creativeEditing = false;
    renderBookDetailPanel();
    return;
  }
  if (element?.closest("[data-book-read]")) {
    transitionBookshelfPage("reader", {
      mutate: () => {
        const savedPage = Math.max(1, Number(state.selectedBook?.reading_progress_page || 1));
        state.selectedBookSpreadIndex = state.selectedBook?.kind === "jm_album" && savedPage > 1 ? Math.max(0, (savedPage - 1) - ((savedPage - 1) % 2)) : 0;
      },
      afterCommit: () => {
        if (state.selectedBook?.kind === "jm_album") void saveSelectedBookshelfReadingState();
      },
    });
    return;
  }
  if (element?.closest("[data-book-prev]")) {
    state.selectedBookSpreadIndex = Math.max(0, Number(state.selectedBookSpreadIndex || 0) - 2);
    renderBookDetailPanel();
    void saveSelectedBookshelfReadingState();
    return;
  }
  if (element?.closest("[data-book-next]")) {
    const pages = Array.isArray(state.selectedBook?.pages) ? state.selectedBook.pages : [];
    state.selectedBookSpreadIndex = Math.min(Math.max(0, pages.length - 1), Number(state.selectedBookSpreadIndex || 0) + 2);
    renderBookDetailPanel();
    void saveSelectedBookshelfReadingState();
    return;
  }
  if (element?.closest("[data-book-save-progress]")) {
    void saveSelectedBookshelfReadingState();
    return;
  }
  const ratingButton = element?.closest("[data-book-rating]");
  if (ratingButton) {
    void rateSelectedBookshelfItem(ratingButton);
    return;
  }
  const commentsUpdateButton = element?.closest("[data-book-reread], [data-book-comments-update]");
  if (commentsUpdateButton) {
    void rereadSelectedBookshelfItem(commentsUpdateButton);
    return;
  }
  const tagPickButton = element?.closest("[data-book-tag-pick]");
  if (tagPickButton) {
    applyBookPreferenceTagPick(tagPickButton);
    return;
  }
  const diaryJump = element?.closest("[data-diary-jump]");
  if (diaryJump) {
    state.selectedDiaryDate = diaryJump.dataset.diaryJump || "";
    renderBookDetailPanel();
    return;
  }
  const browsingJump = element?.closest("[data-browsing-index]");
  if (browsingJump) {
    state.selectedBrowsingIndex = Number(browsingJump.dataset.browsingIndex || 0);
    renderBookDetailPanel();
    return;
  }
  const copySource = element?.closest("[data-copy-source-url]");
  if (copySource) {
    void copyTextToClipboard(copySource.dataset.copySourceUrl || "", "已复制来源链接");
    return;
  }
  if (element?.closest("[data-book-back]")) {
    transitionBookshelfPage("detail", {
      mutate: () => { state.creativeEditing = false; },
    });
    return;
  }
  if (element?.closest("[data-book-close]")) {
    transitionBookshelfPage("shelf", {
      mutate: () => {
        state.selectedBook = null;
        state.creativeEditing = false;
      },
    });
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#bookshelfCoverPreview")?.hidden) {
    event.preventDefault();
    closeBookshelfCoverPreview();
  }
});
document.addEventListener("submit", (event) => {
  const form = event.target instanceof HTMLFormElement ? event.target : null;
  if (!form || !form.matches("[data-book-preference-form]")) return;
  event.preventDefault();
  void updateSelectedBookshelfTags(form);
});
document.addEventListener("submit", async (event) => {
  const form = event.target instanceof HTMLFormElement ? event.target : null;
  if (form?.matches("[data-creative-project-form]")) {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    const formData = new FormData(form);
    const projectId = form.dataset.projectId || "";
    await saveCreativeOperation('basic', "/creative/project/update", {
        id: projectId,
        title: formData.get("title"),
        work_type: formData.get("work_type"),
        tone: formData.get("tone"),
        point_of_view: formData.get("point_of_view"),
        target_chars: Number(formData.get("target_chars") || 0),
        premise: formData.get("premise"),
        next_hint: formData.get("next_hint"),
      }, '作品信息');
    return;
  }
  if (form?.matches("[data-creative-outline-form]")) {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    const projectId = form.dataset.projectId || "";
    const formData = new FormData(form);
    await saveCreativeOperation('outline', "/creative/project/outline/update", {
        id: projectId,
        outline: formData.get("outline"),
      }, '大纲');
    return;
  }
  if (form?.matches("[data-creative-characters-form]")) {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    const projectId = form.dataset.projectId || "";
    const formData = new FormData(form);
    let characters = [];
    try {
      const raw = String(formData.get("characters") || "").trim();
      characters = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(characters)) throw new Error("角色必须是 JSON 数组");
    } catch (error) {
      showToast(`角色格式错误：${error.message}`, "error");
      return;
    }
    await saveCreativeOperation('characters', "/creative/project/characters/update", {
        id: projectId,
        characters,
      }, '角色');
    return;
  }
  if (form?.matches("[data-creative-chunk-form]")) {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    const projectId = form.dataset.projectId || "";
    const chunkIndex = Number(form.dataset.chunkIndex || -1);
    const formData = new FormData(form);
    const body = String(formData.get("text") || "").trim();
    if (!body || Array.from(body).length > 5000) { showToast("正文须为 1–5000 字，未提交；原内容保留。", "error"); return; }
    await saveCreativeOperation('chunk:'+chunkIndex, "/creative/project/chunk/update", {
        id: projectId,
        chunk_index: chunkIndex,
        text: formData.get("text"),
      }, '正文片段');
    return;
  }
  if (!form || !form.matches("[data-image-cache-editor]")) return;
  event.preventDefault();
  const key = form.dataset.imageCacheEditor || "";
  const submit = form.querySelector('button[type="submit"]');
  const formData = new FormData(form);
  setActionBusy(submit, true);
  try {
    const updated = await postJson("/image_cache/update", {
      key,
      text: formData.get("text"),
      scope: formData.get("scope"),
      provider_id: formData.get("provider_id"),
    });
    if (updated?.key !== key || typeof updated.text !== "string") {
      imageCacheActionResult("保存结果未确认，请先刷新列表核对，不要重复提交", true);
      return;
    }
    state.imageCacheItems = state.imageCacheItems.map(item => item.key === key ? {...item, ...updated} : item);
    renderImageCache();
    try {
      await loadImageCache();
      imageCacheActionResult("图片缓存已保存");
    } catch (error) {
      imageCacheActionResult(`图片缓存已保存；最新列表读取失败，当前显示本次确认结果：${error.message}`, true);
    }
  } catch (error) {
    imageCacheActionResult(`保存失败：${error.message}`, true);
  } finally {
    setActionBusy(submit, false);
  }
});
document.addEventListener("change", (event) => {
  const target = event.target instanceof HTMLSelectElement ? event.target : null;
  if (!target || !target.matches("[data-diary-date]")) return;
  state.selectedDiaryDate = target.value;
  renderBookDetailPanel();
});
$("#refreshBtn").addEventListener("click", loadAll);
document.querySelectorAll("[data-page-font-select]").forEach((select) => {
  select.addEventListener("change", (event) => {
    const target = event.currentTarget;
    if (!(target instanceof HTMLSelectElement)) return;
    savePageFontFamily(target.value);
  });
});
document.getElementById("appearanceThemeGrid")?.addEventListener("click", (event) => {
  const option = event.target.closest("[data-theme-value]");
  if (!option) return;
  savePageTheme(option.dataset.themeValue);
});
document.getElementById("appearanceThemeGrid")?.addEventListener("keydown", (event) => {
  const option = event.target.closest("[data-theme-value]");
  if (!option) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    savePageTheme(option.dataset.themeValue);
  }
});
$("#refreshImageCacheBtn")?.addEventListener("click", () => {
  loadImageCache().catch((error) => showToast(`刷新失败：${error.message}`, "error"));
});
$("#refreshTroubleshootingBtn")?.addEventListener("click", () => {
  Promise.all([loadTroubleshooting(), loadDiagnostics(true)])
    .then(() => showToast("排障信息已刷新"))
    .catch((error) => showToast(`刷新失败：${error.message}`, "error"));
});
$("#imageCacheFilter")?.addEventListener("input", (event) => {
  state.imageCacheFilter = event.target.value || "";
  window.clearTimeout(state._imageCacheFilterTimer);
  state._imageCacheFilterTimer = window.setTimeout(() => {
    loadImageCache().catch((error) => showToast(`筛选失败：${error.message}`, "error"));
  }, 220);
});
$("#imageCacheScope")?.addEventListener("change", (event) => {
  state.imageCacheScope = event.target.value || "all";
  loadImageCache().catch((error) => showToast(`筛选失败：${error.message}`, "error"));
});
$("#bookshelfUnlockForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = $("#bookshelfPassword").value.trim();
  if (!password) {
    setBookshelfUnlockMessage("请输入密码", "error");
    return;
  }
  const button = event.currentTarget.querySelector("button[type='submit']");
  if (button) {
    button.disabled = true;
    button.textContent = "验证中...";
  }
  setBookshelfUnlockMessage("正在验证...", "");
  try {
    const result = await postJson("/bookshelf/unlock", { password });
    state.bookshelfUnlocked = result.bookshelf || null;
    state.bookshelfAccessToken = result.bookshelf?.access_token || "";
    state.selectedBook = null;
    state.bookshelfPage = "shelf";
    renderBookshelf();
    $("#bookshelfPassword").value = "";
    setBookshelfUnlockMessage("密码正确，已打开", "ok");
  } catch (error) {
    setBookshelfUnlockMessage(error.message || "密码不对", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "打开抽屉";
    }
  }
});
$("#memoCreateBtn")?.addEventListener("click", () => openMemoEditor());
$("#memoCancelBtn")?.addEventListener("click", closeMemoEditor);
document.querySelectorAll("[data-memo-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.memoFilter = button.dataset.memoFilter || "active";
    renderMemoNotes((state.bookshelfUnlocked || state.overview?.bookshelf || {}).memo_notes || {});
  });
});
$("#memoDueAt")?.addEventListener("change", (event) => {
  const hasDue = Boolean(event.target.value);
  $("#memoRemind").disabled = !hasDue;
  if (!hasDue) {
    $("#memoRemind").checked = false;
    $("#memoEditorHint").textContent = "普通便签";
  } else {
    $("#memoRemind").disabled = false;
    $("#memoEditorHint").textContent = "已设置到期提醒";
  }
});
$("#memoEditorForm")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await openTLSNativeWorkspace("memo_notes");
});
$("#userFilter").addEventListener("input", () => renderUsers(false));
$("#userStatusFilter").addEventListener("change", () => renderUsers(false));
$("#groupFilter").addEventListener("input", () => renderGroups(false));
$("#groupStatusFilter").addEventListener("change", () => renderGroups(false));
$("#worldbookMemberFilter").addEventListener("input", renderWorldbook);
$("#worldbookObservationFilter").addEventListener("change", renderWorldbook);
$("#worldbookObservationCheckBtn").addEventListener("click", checkWorldbookObservation);
$("#featureFilter").addEventListener("input", renderFeatureSwitches);
$("#worldbookMembers").addEventListener("click", async (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-worldbook-living-memory], [data-worldbook-living-memory-close], [data-worldbook-edit], [data-worldbook-member], [data-worldbook-save], [data-worldbook-memory-toggle], [data-worldbook-memory-delete], [data-worldbook-observation-accept], [data-worldbook-observation-reject], [data-worldbook-delete]") : null;
  if (!button) return;
  event.preventDefault();
  await handleWorldbookMemberAction(button);
});
$("#worldbookGroups").addEventListener("click", async (event) => {
  const button = event.target instanceof Element ? event.target.closest("[data-worldbook-group-save], [data-worldbook-group-delete]") : null;
  if (!button) return;
  event.preventDefault();
  await handleWorldbookGroupAction(button);
});
$("#worldbookImportBtn").addEventListener("click", async () => {
  await runAction(() => postJson("/worldbook/import", {}), "已刷新关系网", $("#worldbookImportBtn"));
});
$("#worldbookClearPendingBtn").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (!requireSecondClick(button, "worldbook-clear-pending", "再次点击清理所有待确认观察", "再次点击清理")) return;
  await runAction(() => postJson("/worldbook/observations/clear", {}), "", button);
  button.disabled = !((state.overview?.worldbook?.pending_observation_total || 0) > 0);
});
$("#worldbookAddMemberForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const userId = String(form.get("user_id") || "").trim();
  if (!userId) return;
  const validId = /^\d{5,}$/.test(userId) || /^bili:\d{2,}$/i.test(userId) || /^bili_live_[A-Za-z0-9_-]{6,64}$/.test(userId);
  if (!validId) {
    alert("关系节点必须使用有效 QQ 号或 B 站外部身份键");
    return;
  }
  const saved = await runAction(() => postJson("/worldbook/member/update", {
    user_id: userId,
    name: form.get("name") || userId,
    priority: Number(form.get("priority") || 120),
    enabled: true,
  }), "已添加关系节点", event.submitter);
  if (saved) event.currentTarget.reset();
});
$("#worldbookAddGroupForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const groupId = String(form.get("group_id") || "").trim();
  if (!groupId) return;
  const saved = await runAction(() => postJson("/worldbook/group/update", {
    group_id: groupId,
    name: form.get("name") || groupId,
    enabled: true,
  }), "已添加群资料", event.submitter);
  if (saved) event.currentTarget.reset();
});
$("#skillAddForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const element = event.currentTarget;
  const form = new FormData(element);
  const name = String(form.get("name") || "").trim();
  if (!name) return;
  const level = Number(form.get("level") || 1);
  await saveSkillRecord({
    name,
    category: form.get("category") || "能力",
    level,
    exp: skillExpFloor(level),
    keywords: form.get("keywords") || name,
    aliases: form.get("aliases") || "",
    hidden: false,
    frozen: false,
  }, element, event.submitter, true);
});
$("#personalGoalAddForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await openTLSNativeWorkspace("personal_goals");
});
$("#resetTokenStatsBtn").addEventListener("click", async () => {
  const button = $("#resetTokenStatsBtn");
  if (["pending", "unknown"].includes(state.tokenResetState?.status)) return;
  if (!requireSecondClick(button, "token-reset", "再次点击将清空陪伴与主链的全部留存统计，并重置陪伴当日计入限额的用量；与当前筛选无关。", "再次点击确认清空")) return;
  state.tokenResetState = { status: "pending", text: "正在提交统计清空；尚未确认结果。" };
  setActionBusy(button, true);renderTokenResetNotice();showToast("正在处理...");
  try {
    const result = await postJson("/token/reset", {});
    if (!completeTokenStatsSnapshot(result)) throw new Error("接口返回的统计结果不完整");
    state.tokenResetState = { status: "confirmed", text: "接口已确认清空陪伴与主链统计，已显示本次返回值。记忆侧统计、余额及限额配置保留；后续调用仍会继续累计。" };
    applyTokenStatsSnapshot(result);
    showToast("已确认清空陪伴与主链统计");
  } catch (error) {
    state.tokenResetState = { status: "unknown", text: `清空结果未确认：${error.message}。保留原显示供对照，本页不重复提交；可仅核对当前统计。` };
    showToast("清空结果未确认，请仅核对当前统计", "error");
  } finally {
    setActionBusy(button, false);button.textContent = "清空陪伴与主链统计";renderTokenResetNotice();
  }
});
$("#tokenResetCheckBtn").addEventListener("click", async () => {
  if (state.tokenResetState?.status !== "unknown") return;
  const button = $("#tokenResetCheckBtn");setActionBusy(button, true);
  try {
    const current = await fetchJson("/token/stats");
    if (!completeTokenStatsSnapshot(current)) throw new Error("当前统计返回不完整");
    state.tokenResetState.text = "已读取当前统计；这不能证明先前未确认的清空请求是否完成或落盘。本页仍不重复提交，当前值可能包含后续新增调用。";
    applyTokenStatsSnapshot(current);
  } catch (error) {
    state.tokenResetState.text = `清空结果仍未确认，当前统计读取失败：${error.message}。原显示保留，本页不重复提交。`;
  } finally { setActionBusy(button, false);renderTokenResetNotice(); }
});
document.querySelectorAll("[data-token-view]").forEach((button) => {
  button.addEventListener("click", () => {
    state.tokenView = button.dataset.tokenView || "today";
    renderTokens();
  });
});
document.querySelectorAll("[data-token-source]").forEach((button) => {
  button.addEventListener("click", () => {
    state.tokenSource = normalizedTokenSource(button.dataset.tokenSource);
    renderTokens();
  });
});
$("#tokenDateSelect").addEventListener("change", (event) => {
  state.tokenDate = event.target.value;
  state.tokenView = "date";
  renderTokens();
});
document.addEventListener("submit", async (event) => {
  const form = event.target instanceof HTMLFormElement ? event.target.closest("[data-external-ability-form]") : null;
  if (!form) return;
  event.preventDefault();
  const button = event.submitter || form.querySelector("button[type='submit']");
  const name = form.dataset.externalAbilityForm || "";
  let config = {};
  const rawConfig = form.querySelector('[name="config"]')?.value || "{}";
  try {
    config = JSON.parse(rawConfig || "{}");
  } catch (error) {
    showToast("自定义配置必须是 JSON 对象", "error");
    return;
  }
  if (!config || typeof config !== "object" || Array.isArray(config)) {
    showToast("自定义配置必须是 JSON 对象", "error");
    return;
  }
  await runAction(() => postJson("/external_ability/update", {
    name,
    enabled: Boolean(form.querySelector('[name="enabled"]')?.checked),
    share_probability: Math.max(0, Math.min(1, Number(form.querySelector('[name="share_probability"]')?.value || 0) / 100)),
    min_interval_hours: Number(form.querySelector('[name="min_interval_hours"]')?.value || 0),
    config,
  }), "已保存外部主动能力", button);
});
document.addEventListener("click", async (event) => {
  const addType = event.target?.dataset?.newsSourceAdd;
  if (addType) {
    const items = newsSourceItemsFromDom();
    items.push({
      enabled: true,
      name: newsSourceTypeLabel(addType),
      type: addType,
      target: addType === "bilibili" ? "bilibili:" : (addType === "bilibili_video" ? "bvid:" : "https://"),
    });
    renderNewsSourceManager(items);
    syncNewsSourcesRaw();
    return;
  }
  if (event.target?.dataset?.newsSourceReset !== undefined) {
    resetNewsSourcesToDefault();
    return;
  }
  const removeIndex = event.target?.dataset?.newsSourceRemove;
  if (removeIndex !== undefined) {
    const index = Number(removeIndex);
    const items = newsSourceItemsFromDom().filter((_, itemIndex) => itemIndex !== index);
    renderNewsSourceManager(items);
    syncNewsSourcesRaw();
    return;
  }
  const saveNewsSources = event.target?.closest?.("[data-save-news-sources]");
  if (saveNewsSources) {
    syncNewsSourcesRaw();
    const raw = $("#newsSourcesRaw");
    await runAction(() => postJson("/settings/update", {
      settings: { news_sources: raw?.value || "" },
    }), "已保存新闻源", saveNewsSources);
  }
});
document.addEventListener("input", (event) => {
  if (event.target?.closest?.("#newsSourceManager")) syncNewsSourcesRaw();
});
document.addEventListener("change", (event) => {
  if (!event.target?.closest?.("#newsSourceManager")) return;
  if (event.target.matches("[data-news-source-type]")) {
    const row = event.target.closest("[data-news-source-item]");
    const input = row?.querySelector("[data-news-source-target]");
    if (input && !String(input.value || "").trim()) {
      input.value = event.target.value === "bilibili" ? "bilibili:" : (event.target.value === "bilibili_video" ? "bvid:" : "https://");
    }
    if (input) input.placeholder = newsSourcePlaceholder(event.target.value);
  }
  syncNewsSourcesRaw();
});
bindRoleplayModeSwitch();
bindProviderToolbar();
["roleplayProfileForm", "privateAliasForm", "quickModuleForm", "runtimeSettingsForm"].forEach((formId) => {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener("input", () => markModuleFormDirty(form));
  form.addEventListener("change", () => markModuleFormDirty(form));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (formId === "roleplayProfileForm") return saveRoleplayWorkspace(form,event.submitter);
    const saved = await runAction(() => postJson("/settings/update", {
      settings: collectFormSettings(`#${formId}`),
    }), formId === "runtimeSettingsForm" ? "已保存运行设置" : "已保存模块调参", event.submitter);
    if (!saved) return;
    markModuleFormClean(form);
    if (formId === "privateAliasForm") {
      await loadAll();
    }
  });
});
bindSegmentedPreview();
$("#addUserForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const element = event.currentTarget, form = new FormData(element);
  const userId = String(form.get("user_id") || "").trim();
  if (!userId) return;
  const saved = await runAction(async () => {
    const result = await postJson("/user/update", {user_id: userId, enabled: true, nickname: form.get("nickname") || ""});
    state.selectedUserId = result.user_id || userId;
    state.userDetailSection = "profile";
    return result;
  }, "已添加私聊对象", event.submitter);
  if (saved) element.reset();
});
$("#addGroupForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const element = event.currentTarget, form = new FormData(element);
  const groupId = String(form.get("group_id") || "").trim();
  const listMode = String(form.get("list_mode") || "none");
  if (!groupId) return;
  let created = false;
  const saved = await runAction(async () => {
    let result = await postJson("/group/update", { group_id: groupId, enabled: true });
    created = true;
    state.selectedGroupId = groupId;
    state.groupDetailSection = "status";
    if (listMode !== "none") {
      const group = state.overview?.group || {};
      const whitelist = new Set(group.whitelist || []);
      const blacklist = new Set(group.blacklist || []);
      if (listMode === "whitelist") whitelist.add(groupId);
      if (listMode === "blacklist") blacklist.add(groupId);
      try {
        result = await postJson("/settings/update", {
          group_whitelist_ids: [...whitelist], group_blacklist_ids: [...blacklist],
        });
      } catch (error) {
        throw new Error(`群观测已创建；名单保存未确认：${error.message}。请先在群聊名单核对，勿反复新增。`);
      }
    }
    return result;
  }, "已添加群聊观测", event.submitter);
  if (saved) element.reset();
  else if (created) await loadAll();
});
$("#exportSnapshotBtn").addEventListener("click", async () => {
  await runAction(async () => {
    const params = new URLSearchParams();
    params.set("sections", "basic,relations,food_skills,providers");
    const snapshot = await fetchJson(`/config/export?${params.toString()}`);
    const date = new Date().toISOString().slice(0, 10);
    downloadJson(`private-companion-snapshot-${date}.json`, snapshot);
  }, "快照已导出，可在配置迁移中导入", $("#exportSnapshotBtn"));
});
$("#exportConfigBtn").addEventListener("click", async () => {
  await handleConfigExport();
});
$("#importConfigFile").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    await readConfigImportFile(file);
  } catch (error) {
    state.configImportPackage = null;
    state.configImportPreview = null;
    renderConfigMigrationPreview();
    showToast(`读取失败：${error.message}`, "error");
  }
});
$("#previewConfigImportBtn").addEventListener("click", async () => {
  await previewConfigImport();
});
$("#applyConfigImportBtn").addEventListener("click", async () => {
  await applyConfigImport();
});
$("#configImportMode").addEventListener("change", () => {
  renderConfigMigrationPreview();
});
$("#configAllowChecksumMismatch").addEventListener("change", () => {
  ++state.configImportPreviewSerial;
  state.configImportPreviewBusy = false;
  state.configImportPreview = null;
  renderConfigMigrationPreview();
});
$("#storageBackendSelect").addEventListener("change", () => {
  renderStorageConfig({ preserveDraft: true });
});
$("#storageConfigForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const backend = String($("#storageBackendSelect")?.value || "json").trim().toLowerCase() || "json";
  const sqlitePath = String($("#storageSqlitePathInput")?.value || "").trim();
  const safetyEnabled = Boolean($("#storageSafetyCleanupToggle")?.checked);
  await runAction(
    () => postJson("/settings/update", {
      settings: {
        storage_backend: backend,
        storage_sqlite_path: sqlitePath,
        enable_store_control_tag_sanitization: safetyEnabled,
      },
    }),
    "已保存存储方式",
    event.submitter || $("#saveStorageConfigBtn")
  );
});
$("#configBackupList").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-config-restore]");
  if (!button) return;
  await restoreConfigBackup(button.dataset.configRestore);
});
$("#accessForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const draft = accessDraftFromForm(state.overview?.group || {});
  writeAccessDraft(draft);
  await runAction(() => postJson("/settings/update", {
    group_access_mode: draft.mode,
    group_whitelist_ids: [...draft.whitelist],
    group_blacklist_ids: [...draft.blacklist],
  }), "已保存群聊名单", event.submitter);
});
$("#groupAccessMode").addEventListener("change", () => {
  renderAccessManager(state.overview?.group || {});
});
document.querySelectorAll("[name='groupAccessModeChoice']").forEach((input) => {
  input.addEventListener("change", () => {
    $("#groupAccessMode").value = input.value;
    renderAccessManager(state.overview?.group || {});
  });
});
$("#accessQuickGroups").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-access-action]");
  if (!button) return;
  const groupId = String(button.dataset.accessGroup || "").trim();
  if (!groupId) return;
  const draft = accessDraftFromForm(state.overview?.group || {});
  const targetSet = button.dataset.accessAction === "black" ? draft.blacklist : draft.whitelist;
  if (targetSet.has(groupId)) {
    targetSet.delete(groupId);
  } else {
    targetSet.add(groupId);
    if (button.dataset.accessAction === "black") {
      draft.whitelist.delete(groupId);
    } else {
      draft.blacklist.delete(groupId);
    }
  }
  writeAccessDraft(draft);
  renderAccessManager(state.overview?.group || {});
  await runAction(() => postJson("/settings/update", {
    group_access_mode: draft.mode,
    group_whitelist_ids: [...draft.whitelist],
    group_blacklist_ids: [...draft.blacklist],
  }), "已更新群聊名单", button);
});
$("#saveFeaturesBtn").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (button?.dataset?.action === "back" || (state.selectedFeatureKey && Object.prototype.hasOwnProperty.call(state.featureDraft || {}, state.selectedFeatureKey))) {
    const saved = await saveCurrentFeatureDetail(button, "已保存并返回功能列表");
    if (!saved) return;
    state.selectedFeatureKey = "";
    renderFeatureSwitches();
    return;
  }
  const overviewSettings = state.overview?.settings || {};
  const features = {};
  const settings = {};
  Object.entries(state.featureDraft).forEach(([key, value]) => {
    if (!visibleConfigKey(key)) return;
    if (Object.prototype.hasOwnProperty.call(overviewSettings, key)) {
      settings[key] = toBool(value);
    } else {
      features[key] = toBool(value);
    }
  });
  const proactiveIntensitySelect = document.querySelector('[data-proactive-intensity-form] [name="proactive_intensity_preset"]');
  if (proactiveIntensitySelect) {
    settings.proactive_intensity_preset = proactiveIntensitySelect.value || "off";
  }
  await runAction(() => postJson("/settings/update", { features, settings }), "已保存功能开关", button);
});
$("#enableSafeFeaturesBtn").addEventListener("click", () => {
  safeFeatureKeys.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(state.featureDraft, key) && !featureLockedByProactiveOnlyMode(key)) {
      state.featureDraft[key] = true;
    }
  });
  renderFeatureSwitches();
});
$("#saveProvidersBtn").addEventListener("click", async () => {
  if (!asteriaProviders?.currentProviderValues) { showToast("模型配置面板脚本未加载，请刷新拓展页", "error");return; }
  if (["pending", "unknown"].includes(state.providerSave?.status) || state.providerReadBusy) return;
  const submitted = providerFormSnapshot(), providers = {};
  Object.keys(providerLabels).forEach(k => { if (visibleConfigKey(k)) providers[k] = submitted.providers[k] || ""; });
  providers.DEEPSEEK_PEAK_REPLACEMENT_PROVIDER_ID = submitted.peak.provider;
  const payload = { providers, overwrite_provider_modes: true, settings: {
    provider_config_mode: submitted.mode, model_timeout_overrides: submitted.timeouts, model_fallback_overrides: submitted.fallbacks,
    enable_deepseek_peak_replacement: submitted.peak.enabled, deepseek_peak_windows: submitted.peak.windows,
    deepseek_peak_timezone: submitted.peak.timezone, deepseek_peak_match_keywords: submitted.peak.keywords,
  } };
  const button = $("#saveProvidersBtn");
  state.providerSave = { status: "pending", message: "正在保存两套分流配置。等待期间的后续输入会保留，不会自动补交。" };
  setActionBusy(button, true);renderProviderSaveNotice();
  try {
    const result = await postJson("/settings/update", payload);
    if (!providerReceiptComplete(result, payload)) throw new Error("返回缺少完整模型或配置确认字段");
    const current = providerFormSnapshot();
    applyProviderRead(result);
    if (result.config_saved === false) {
      state.providerDraft = { ...current.providers };
      state.providerTimeoutDraft = providerLaterValues(current.timeouts, providerReceiptMap(result.settings.model_timeout_overrides, true));
      state.providerFallbackDraft = providerLaterValues(current.fallbacks, providerReceiptMap(result.settings.model_fallback_overrides));
      state.providerSave = { status: "failed", message: "服务端明确未能保存到配置文件；运行态可能已经改变。输入已保留，请先核对再决定是否重新保存。读取运行态不证明已写入文件。" };
    } else {
      // Only retire the submitted values. Later edits stay as drafts over the confirmed server expansion.
      state.providerDraft = providerLaterValues(current.providers, submitted.providers);
      state.providerTimeoutDraft = providerLaterValues(current.timeouts, submitted.timeouts);
      state.providerFallbackDraft = providerLaterValues(current.fallbacks, submitted.fallbacks);
      const confirmedPeak = { enabled: result.settings.enable_deepseek_peak_replacement, provider: result.providers.DEEPSEEK_PEAK_REPLACEMENT_PROVIDER_ID,
        windows: result.settings.deepseek_peak_windows, timezone: result.settings.deepseek_peak_timezone, keywords: result.settings.deepseek_peak_match_keywords };
      for (const [key, selector] of Object.entries({enabled:"[data-deepseek-peak-enabled]",provider:"[data-deepseek-peak-provider-input]",windows:"[data-deepseek-peak-windows]",timezone:"[data-deepseek-peak-timezone]",keywords:"[data-deepseek-peak-keywords]"})) {
        const input = document.querySelector(selector);
        if (input && providerSame(current.peak[key], submitted.peak[key])) { if (key === "enabled") input.checked = confirmedPeak[key];else input.value = confirmedPeak[key]; }
      }
      state.providerSave = { status: "confirmed", message: "已确认保存，已采用服务端返回的两套分流配置；保存等待期间的后续输入已保留为草稿，未自动提交。配置读取或测试结果不等于每次实际调用模型。" };
    }
    state.providerConfigMode = current.mode;
    renderProviders();showToast(result.config_saved ? "模型配置已确认保存" : "配置文件保存失败，输入已保留", result.config_saved ? "success" : "error");
  } catch (error) {
    state.providerSave = { status: "unknown", message: `保存结果未确认：${error.message}。本页先仅读取核对，不重复提交；不能据此撤销或判断已开始的保存是否完成。` };
    showToast("保存结果未确认，请先核对", "error");
  } finally { setActionBusy(button, false);renderProviderSaveNotice(); }
});
$("#providerReadBtn").addEventListener("click", async () => {
  if (state.providerReadBusy || state.providerSave?.status === "pending") return;
  state.providerReadBusy = true;renderProviderSaveNotice();
  try {
    const result = await fetchJson("/overview");
    if (!providerReadComplete(result)) throw new Error("配置读取不完整");
    const current = providerFormSnapshot();applyProviderRead(result);
    state.providerDraft = { ...current.providers };
    state.providerTimeoutDraft = providerLaterValues(current.timeouts, providerReceiptMap(result.settings.model_timeout_overrides, true));
    state.providerFallbackDraft = providerLaterValues(current.fallbacks, providerReceiptMap(result.settings.model_fallback_overrides));
    state.providerConfigMode = current.mode;
    const status = state.providerSave?.status || "read";
    state.providerSave = { status, message: status === "unknown"
      ? "已读取当前服务端配置，草稿保留；相同内容不能证明先前未确认的写入已经完成或落盘，本页不自动重复提交。"
      : "已读取当前服务端配置，草稿保留。读取反映运行态，不证明未确认的保存已完成或写入文件。" };
    renderProviders();
  } catch (error) {
    state.providerSave = { status: state.providerSave?.status || "read", message: `${state.providerSave?.message || ""} 读取失败：${error.message}；保留原输入和最近读取。` };
  } finally { state.providerReadBusy = false;renderProviderSaveNotice(); }
});
$("#testAllProvidersBtn").addEventListener("click", async () => {
  if (!asteriaProviders?.testProvider) {
    showToast("模型配置面板脚本未加载，请刷新拓展页", "error");
    return;
  }
  for (const key of Object.keys(providerLabels).filter((item) => visibleConfigKey(item) && providerAllowedInCurrentMode(item))) {
    await testProvider(key);
  }
});
initNativeCompanionNavigation();
loadAll();
document.querySelectorAll('[data-proactive-view]').forEach(button => button.addEventListener('click', () => {
  state.proactiveRecordView = button.dataset.proactiveView;
  state.proactiveRecordStatus = "all"; state.proactiveRecordSource = "all"; state.proactiveRecordPage = 0;
  renderProactiveRecords();
}));
$("#proactiveRecordQuery").addEventListener('input', event => {
  state.proactiveRecordQuery = event.target.value; state.proactiveRecordPage = 0; renderProactiveRecords();
});
for (const [id, key] of [["proactiveRecordUser", "proactiveCandidateFilter"], ["proactiveRecordStatus", "proactiveRecordStatus"], ["proactiveRecordSource", "proactiveRecordSource"]]) {
  $("#" + id).addEventListener('change', event => {state[key] = event.target.value; state.proactiveRecordPage = 0; renderProactiveRecords();});
}
$("#proactiveRecordReset").addEventListener('click', () => {
  state.proactiveRecordQuery = ""; state.proactiveCandidateFilter = "all"; state.proactiveRecordStatus = "all";
  state.proactiveRecordSource = "all"; state.proactiveRecordPage = 0; $("#proactiveRecordQuery").value = ""; renderProactiveRecords();
});
$("#proactiveRecordPrevious").addEventListener('click', () => {state.proactiveRecordPage--; renderProactiveRecords();});
$("#proactiveRecordNext").addEventListener('click', () => {state.proactiveRecordPage++; renderProactiveRecords();});
document.addEventListener("click", event => {
  const button = event.target.closest?.('[data-creative-readback]');
  if (button) void readCreativeOperation(button.dataset.creativeReadback);
});
}
