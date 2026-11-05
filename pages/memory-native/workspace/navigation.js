/** 星栖 Asteria workspace. Credited feature/view routines retained; transport, module state and startup owned by Asteria.
 * See docs/system/FRONTEND_PROVENANCE.md and upstream source notices. */

import {bindActions} from './maintenance.js';
import {loadBuckets,openView,playInitialOverviewEntrance,returnHome} from './memory.js';
import {loadStats,normalizeBuckets,renderBuckets,renderStandardRecentBuckets,selectSecondaryNav,syncOverviewLayoutControls} from './overview.js';
import {syncNativeMemoryNavigation} from './personal.js';
import {loadCompanionAvailability} from './portraits.js';
import {VIEWS,state} from './state.js';
import {loadConfiguredTheme,loadUiCapabilities,setMessage} from './workspace.js';

export function initNativeMemoryNavigation() {
  const root = document.getElementById("nativeMemoryNavigation");
  if (!root) return;
  const narrow = matchMedia("(max-width:760px)");
  root.open = !narrow.matches;
  narrow.addEventListener("change", () => { root.open = !narrow.matches; });
  root.querySelectorAll("[data-native-view]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.nativeView === "overview") void returnHome();
    else void openView(button.dataset.nativeView);
  }));
  document.getElementById("nativeMemorySearch").addEventListener("input", (event) => {
    const query = event.target.value.trim().toLocaleLowerCase();
    let visible = 0;
    root.querySelectorAll("[data-native-view]").forEach((button) => {
      button.hidden = !button.textContent.toLocaleLowerCase().includes(query);
      if (!button.hidden) visible++;
    });
    root.querySelectorAll(".aw-nav-group").forEach((group) => { group.hidden = !group.querySelector("button:not([hidden])"); });
    root.querySelector(".aw-nav-empty").hidden = visible > 0;
  });
  // Do not overwrite a saved link while startup is reading its existing data.
  if (!location.hash) syncNativeMemoryNavigation("overview");
}

export async function init() {
  syncOverviewLayoutControls();
  initNativeMemoryNavigation();
  bindActions();
  playInitialOverviewEntrance();
  await loadUiCapabilities();
  await loadConfiguredTheme();
  try {
    await loadCompanionAvailability();
    await loadStats();
    await loadBuckets();
    renderBuckets();
  } catch (error) {
    setMessage(`页面 API 暂不可用：${error.message}`);
    state.buckets = normalizeBuckets([]);
    renderBuckets();
    renderStandardRecentBuckets();
  }
  const route = new URLSearchParams(location.hash.slice(1));
  const requested = route.get("view");
  if (requested && VIEWS[requested] && requested !== "maintain") {
    await openView(requested);
    if (route.get("section")) await selectSecondaryNav(route.get("section"));
  }
}
