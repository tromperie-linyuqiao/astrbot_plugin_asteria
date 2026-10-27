'use strict';

/* All HTTP and credential handling belong to the local Android bridge.
   Changing a server route only requires updating this small mapping. */
const API = Object.freeze({
  login: '/auth/login', sessions: '/chat/sessions', personas: '/chat/personas', connect: '/chat/connect',
  history: id => '/chat/history?session_id=' + encodeURIComponent(id), send: '/chat/send', rename: '/chat/rename',
  removeSession: '/chat/remove'
});
/* Local sticker pack shipped with the app; each item is uploaded through the
   existing attachment endpoint and then sent as one image message. */
const STICKERS = Object.freeze([]); // The single shared library now lives on TLS.
const THEME_KEY = 'theme';
const THEME_ORDER = ['system', 'dark', 'light'];
const THEME_LABEL = { system: '跟随系统', dark: '深色', light: '浅色' };
const DEFAULT_APPEARANCE = Object.freeze({ version: 1, displayName: '', avatar: null, background: 'default', backgroundImage: null });
const MAX_EXPORT_BYTES = 2 * 1024 * 1024;
const DEFAULT_INTERACTIONS = Object.freeze({ version: 1, slots: Object.freeze([
  Object.freeze({ label: '摸摸头', action: '我想轻轻摸摸你的头，可以吗？', enabled: true }),
  Object.freeze({ label: '轻戳肚子', action: '我想轻轻戳一下你的肚子，看看你的反应，可以吗？', enabled: true }),
  Object.freeze({ label: '牵手', action: '我想牵着你的手，陪你待一会儿。', enabled: true }),
  Object.freeze({ label: '靠一会儿', action: '我想轻轻靠着你休息一会儿，可以陪我吗？', enabled: true })
]) });
const $ = id => document.getElementById(id);
let phonePerceptionPanel = null;
let perceptionNativeScope = null;
const state = { authenticated: false, bridgeAvailable: false, server: '', username: '',
  sessions: [], personas: [], newPersona: '', sessionPersonas: new Map(), sessionPersonaConfig: null, activeId: null, messages: [], sending: false, loading: false, creating: false,
  attaching: false, attachmentQueues: new Map(), mediaCache: new Map(), previewElements: [],
  appearanceCache: null, appearanceEditing: null, appearanceSerial: 0, appearanceBusy: false, appearancePendingEpoch: null,
  interactionCache: null, interactionEditing: null, interactionCooldowns: new Map(),
  renameEditing: null, renaming: false, renameUnknown: new Map(),
  exportEditing: null, exportBusy: false, exportSerial: 0, exportPendingEpoch: null,
  messageSearch: { scope: '', open: false, query: '', hits: [], index: -1, limited: false },
  pendingActions: [], stickerBusy: false, stickerSending: '', deleteEditing: null,
  readingScope: '', messageRenderSerial: 0,
  primaryId: null, primaryAccount: '', remoteRunning: false, replyPhase: 'idle', requestSerial: 0, historySerial: 0, requests: new Map() };
const storage = {
  get(key) { try { return localStorage.getItem(key) || ''; } catch (_) { return ''; } },
  set(key, value) { try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch (_) {} }
};
const pref = name => 'asteria-chat.' + name;
const draftKey = id => pref('draft.' + encodeURIComponent(state.server + '|' + state.username) + '.' + (id || 'new'));
const parse = value => typeof value === 'string' ? JSON.parse(value) : value;

function native() {
  const value = window.AsteriaChat;
  if (!value || typeof value.request !== 'function') throw new Error('请在 Asteria Chat 应用中打开此页面。');
  return value;
}
function nativeConfig() {
  try { return parse(native().getConfig()) || {}; } catch (_) { return {}; }
}
function errorText(error) {
  const message = error && typeof error.message === 'string' ? error.message : '连接暂时不可用，请稍后重试。';
  return message.replace(/[\u0000-\u001f<>]/g, '').slice(0, 220);
}
function responseError(status, body) {
  let text = status === 0 ? '网络连接未完成，请检查网络或服务器地址。' : '服务器暂时未能处理请求。';
  if (status === 401) text = '登录已失效，请重新登录。';
  else if (status === 403) text = '当前账户无权访问这段会话。';
  else if (status === 404) text = '找不到会话或聊天接口，请同步列表。';
  else if (body && typeof body === 'object') {
    const detail = typeof body.message === 'string' ? body.message : typeof body.error === 'string' ? body.error : '';
    if (detail) text = detail;
  }
  const error = new Error(text);
  error.status = status;
  error.code = body && typeof body.error === 'string' ? body.error : '';
  error.partialFilePossible = !!(body && typeof body === 'object' && body.partial_file_possible === true);
  return error;
}
function bridgeRequest(method, path, body, options = {}) {
  return new Promise((resolve, reject) => {
    let completed = false;
    const completeNative = method === 'GET' && typeof options.onNativeComplete === 'function' ? () => {
      if (!completed) { completed = true; options.onNativeComplete(); }
    } : null;
    let bridge;
    try { bridge = native(); } catch (error) { if (completeNative) completeNative(); reject(error); return; }
    const requestId = 'tc-' + Date.now().toString(36) + '-' + (++state.requestSerial);
    const timeout = setTimeout(() => {
      if (completeNative) {
        const pending = state.requests.get(requestId); if (pending) pending.expired = true;
      } else state.requests.delete(requestId);
      const error = new Error('等待服务器超时。发送结果需要先同步记录确认，请勿连续重复发送。');
      error.status = 0;
      if (completeNative) error.nativeCompletionUnknown = true;
      reject(error);
    }, method === 'POST' && [API.send,'/chat/regenerate'].includes(path) ? 180000 : 45000);
    state.requests.set(requestId, { resolve, reject, timeout, completeNative });
    try { if(options.streaming && typeof bridge.requestStream==='function')bridge.requestStream(requestId,path,JSON.stringify(body));else bridge.request(JSON.stringify({ requestId, method, path, body: body === undefined ? null : body })); }
    catch (error) { clearTimeout(timeout); state.requests.delete(requestId); if (completeNative) completeNative(); reject(error); }
  });
}
function nativeAsync(method, args, timeoutMs = 45000) {
  return new Promise((resolve, reject) => {
    let bridge;
    try { bridge = native(); if (typeof bridge[method] !== 'function') throw new Error('此功能需要新版 Asteria Chat 应用。'); }
    catch (error) { reject(error); return; }
    const requestId = 'tc-media-' + Date.now().toString(36) + '-' + (++state.requestSerial);
    const timeout = setTimeout(() => {
      state.requests.delete(requestId);
      const error = new Error('文件操作等待超时，结果尚未确认；应用不会自动重新上传或发送。');
      error.nativeTimeout = true;
      reject(error);
    }, timeoutMs);
    state.requests.set(requestId, { resolve, reject, timeout });
    try { bridge[method](requestId, ...args); }
    catch (error) { clearTimeout(timeout); state.requests.delete(requestId); reject(error); }
  });
}
function responseData(body) {
  return body && typeof body === 'object' && Object.prototype.hasOwnProperty.call(body, 'data') ? body.data : body;
}
function appearanceScope() {
  const session = state.sessions.find(item => item.session_id === state.activeId);
  if (!state.authenticated || !state.server || !state.username || !state.activeId || !session) return null;
  return { key: pref('appearance.' + encodeURIComponent(JSON.stringify([state.server, state.username, state.activeId]))),
    title: typeof session.display_name === 'string' && session.display_name ? session.display_name : '当前对话' };
}
/* Read one conversation's local appearance without touching the active cache. */
const sessionAppearanceCache = new Map();
function sessionAppearance(sessionId) {
  const cacheKey = String(state.server) + '|' + String(state.username) + '|' + String(sessionId);
  if (sessionAppearanceCache.has(cacheKey)) return sessionAppearanceCache.get(cacheKey);
  let value = { avatar: null, displayName: '' };
  try {
    const raw = localStorage.getItem(pref('appearance.' + encodeURIComponent(JSON.stringify([state.server, state.username, sessionId]))));
    if (raw) {
      const parsed = JSON.parse(raw);
      value = { avatar: typeof parsed.avatar === 'string' ? parsed.avatar : null,
        displayName: typeof parsed.displayName === 'string' ? parsed.displayName : '' };
    }
  } catch (_) { /* a broken local record only costs the avatar. */ }
  if (sessionAppearanceCache.size > 64) sessionAppearanceCache.clear();
  sessionAppearanceCache.set(cacheKey, value);
  return value;
}
function appearanceImage(value) {
  if (value === null) return null;
  const prefix = 'data:image/jpeg;base64,';
  if (typeof value !== 'string' || !value.startsWith(prefix) || value.length > 700000) throw new Error('外观图片必须是应用处理的 JPEG 图片。');
  const encoded = value.slice(prefix.length);
  if (!encoded.startsWith('/9j/') || encoded.length % 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) throw new Error('外观图片格式无效。');
  const bytes = encoded.length / 4 * 3 - (encoded.endsWith('==') ? 2 : encoded.endsWith('=') ? 1 : 0);
  if (bytes > 512 * 1024) throw new Error('处理后的图片仍超过 512 KB，请重新选择。');
  return value;
}
function validateAppearance(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1
      || Object.keys(value).sort().join('|') !== 'avatar|background|backgroundImage|displayName|version'
      || typeof value.displayName !== 'string' || value.displayName.length > 40 || /[\u0000-\u001f\u007f]/.test(value.displayName)
      || !['default', 'mint', 'sand', 'night', 'image'].includes(value.background)) throw new Error('外观设置格式无效，请恢复默认后重新保存。');
  const result = { ...DEFAULT_APPEARANCE, displayName: value.displayName.trim(), avatar: appearanceImage(value.avatar),
    background: value.background, backgroundImage: appearanceImage(value.backgroundImage) };
  if (result.background === 'image' && !result.backgroundImage) throw new Error('请先选择背景图片。');
  if (result.background !== 'image') result.backgroundImage = null;
  return result;
}
function readAppearance(scope) {
  const raw = localStorage.getItem(scope.key);
  if (raw === null || raw === '') return { ...DEFAULT_APPEARANCE };
  if (raw.length > 1500000) throw new Error('本机外观记录过大，暂不读取。');
  return validateAppearance(JSON.parse(raw));
}
function currentAppearance() {
  const scope = appearanceScope();
  if (!scope) { state.appearanceCache = null; return DEFAULT_APPEARANCE; }
  if (!state.appearanceCache || state.appearanceCache.key !== scope.key) {
    try { state.appearanceCache = { key: scope.key, value: readAppearance(scope), error: '' }; }
    catch (_) { state.appearanceCache = { key: scope.key, value: { ...DEFAULT_APPEARANCE }, error: '无法读取本机外观，暂时使用默认设置。' }; }
  }
  return state.appearanceCache.value;
}
function appearanceBaseName() {
  return '助手';
}
/* One wallpaper layer behind every region: the sidebar, header, transcript and
   composer are translucent, so a chosen palette or picture covers the whole app
   instead of only the middle column. */
function paintAppearance(element, appearance) {
  const surface = element || $('app');
  for (const name of ['default', 'mint', 'sand', 'night', 'image']) surface.classList.toggle('appearance-' + name, appearance.background === name);
  const picture = appearance.background === 'image' && appearance.backgroundImage;
  // A preview owns its wallpaper locally; only a saved appearance paints the app.
  const shell = surface === $('app') ? document.documentElement : surface;
  if (shell && shell.style && typeof shell.style.setProperty === 'function') {
    shell.style.setProperty('--chat-wallpaper', picture ? 'url("' + appearance.backgroundImage + '")' : 'none');
  }
  return surface;
}
/* Light/dark preference is a device setting shared by all conversations. */
function themePreference() {
  const value = storage.get(pref(THEME_KEY));
  return ['light', 'dark', 'system'].includes(value) ? value : 'system';
}
function systemTheme() {
  try { return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; }
  catch (_) { return 'light'; }
}
function effectiveTheme() {
  const mode = themePreference();
  return mode === 'system' ? systemTheme() : mode;
}
/* The header menu exposes the same device-wide preference as the settings
   selector, so a dark-mode switch is one tap away from any conversation. */
function setThemePreference(mode) {
  const value = THEME_ORDER.includes(mode) ? mode : 'system';
  storage.set(pref(THEME_KEY), value === 'system' ? '' : value);
  applyTheme();
  return value;
}
function renderThemeMenu() {
  const item = $('menu-theme'); if (!item) return;
  const mode = themePreference();
  item.textContent = '深色模式：' + THEME_LABEL[mode];
  item.dataset.mode = mode;
  item.setAttribute('aria-label', '深色模式，当前' + THEME_LABEL[mode] + '，点击切换');
}
function applyTheme() {
  const theme = effectiveTheme();
  const shell = document.documentElement;
  if (shell && shell.dataset) shell.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === 'dark' ? '#161a18' : '#f7f8f5';
  // Status/navigation bars live outside the WebView, so the page reports the
  // effective theme instead of guessing it natively.
  if (window.AsteriaChat && typeof window.AsteriaChat.setChromeTheme === 'function') {
    try { window.AsteriaChat.setChromeTheme(theme); } catch (_) {}
  }
  const select = $('theme');
  if (select && select.value !== themePreference()) select.value = themePreference();
  renderThemeMenu();
}
function applyAppearance() {
  const appearance = currentAppearance();
  if ($('header-avatar')._appearance !== appearance) {
    $('header-avatar').src = appearance.avatar || 'logo.svg';
    $('header-avatar')._appearance = appearance;
  }
  if (appearance.displayName) $('conversation-title').textContent = appearance.displayName;
  paintAppearance($('app'), appearance);
}
function appearanceError(message) { $('appearance-error').textContent = message; $('appearance-error').hidden = !message; }
function previewAppearance() {
  const editing = state.appearanceEditing; if (!editing) return;
  const draft = editing.draft;
  $('appearance-avatar-preview').src = draft.avatar || 'logo.svg';
  $('appearance-name-preview').textContent = draft.displayName.trim() || appearanceBaseName();
  paintAppearance($('appearance-preview'), draft);
  $('appearance-image-status').textContent = draft.background === 'image' ? '已选本机图片 · 保存后生效' : '图片在本机处理，不上传服务器。';
  for (const button of document.querySelectorAll('[data-appearance-palette]')) button.setAttribute('aria-pressed', String(button.dataset.appearancePalette === draft.background));
  $('appearance-save').disabled = state.appearanceBusy;
  $('choose-avatar').disabled = state.appearanceBusy || state.attaching || state.exportBusy;
  $('choose-background').disabled = state.appearanceBusy || state.attaching || state.exportBusy;
}
function openAppearance() {
  const scope = appearanceScope();
  if (!scope) { showNotice('请先登录并打开一个对话，再设置此对话的本机外观。'); return; }
  cancelInteractions();
  if ($('settings-dialog').open) $('settings-dialog').close();
  let value, error = '';
  try { value = readAppearance(scope); }
  catch (_) { value = { ...DEFAULT_APPEARANCE }; error = '无法读取原外观，暂显示默认值。保存前请检查本机存储。'; }
  state.appearanceEditing = { scope, draft: { ...value }, epoch: ++state.appearanceSerial };
  $('appearance-scope').textContent = scope.title + ' · 仅此对话 · 仅此设备';
  $('appearance-name').value = value.displayName;
  $('appearance-name').placeholder = '默认：' + appearanceBaseName();
  appearanceError(error); previewAppearance();
  if (!$('appearance-dialog').open) $('appearance-dialog').showModal();
}
function cancelAppearance() {
  state.appearanceEditing = null; state.appearanceSerial++;
  if ($('appearance-dialog').open) $('appearance-dialog').close();
  applyAppearance();
}
function resetAppearance() {
  if (!state.appearanceEditing) return;
  state.appearanceEditing.draft = { ...DEFAULT_APPEARANCE };
  $('appearance-name').value = ''; appearanceError(''); previewAppearance();
}
async function chooseAppearanceImage(kind) {
  const editing = state.appearanceEditing;
  if (!editing || !['avatar', 'background'].includes(kind)) return;
  if (state.appearanceBusy || state.attaching || state.exportBusy) { appearanceError('请先完成当前图片、附件或文件保存。'); return; }
  const scope = appearanceScope();
  if (!scope || scope.key !== editing.scope.key) { appearanceError('当前对话已经变化，请重新打开外观面板。'); return; }
  state.appearanceBusy = true; state.appearancePendingEpoch = editing.epoch;
  appearanceError(''); previewAppearance(); renderChrome();
  try {
    const data = responseData(await nativeAsync('chooseAppearanceImage', [kind], 300000));
    if (state.appearanceEditing !== editing || !appearanceScope() || appearanceScope().key !== editing.scope.key) return;
    if (data && data.cancelled === true) return;
    if (!data || data.kind !== kind || !Number.isInteger(data.width) || !Number.isInteger(data.height)
        || data.width < 1 || data.height < 1 || data.width > 1280 || data.height > 1280) throw new Error('应用未返回有效的处理后图片。');
    const url = appearanceImage(data.data_url);
    if (!url) throw new Error('未收到外观图片。');
    if (kind === 'avatar') editing.draft.avatar = url;
    else { editing.draft.backgroundImage = url; editing.draft.background = 'image'; }
    previewAppearance();
  } catch (error) { if (state.appearanceEditing === editing) appearanceError(errorText(error)); }
  finally {
    if (state.appearancePendingEpoch === editing.epoch) { state.appearanceBusy = false; state.appearancePendingEpoch = null; }
    previewAppearance(); renderChrome();
  }
}
function persistAppearance(scope, value) {
  const previous = localStorage.getItem(scope.key);
  const defaults = !value.displayName && !value.avatar && value.background === 'default';
  const expected = defaults ? null : JSON.stringify(value);
  let wrote = false;
  try {
    if (expected === null) localStorage.removeItem(scope.key); else localStorage.setItem(scope.key, expected);
    wrote = true;
    if (localStorage.getItem(scope.key) !== expected) throw new Error('保存回读不一致');
    sessionAppearanceCache.clear();
    return expected === null ? { ...DEFAULT_APPEARANCE } : readAppearance(scope);
  } catch (_) {
    let restoreFailed = false;
    if (wrote) {
      try { if (previous === null) localStorage.removeItem(scope.key); else localStorage.setItem(scope.key, previous); }
      catch (_) { restoreFailed = true; }
    }
    throw new Error(restoreFailed ? '外观保存结果未能确认，原设置也无法恢复。请检查本机存储后重试。' : '无法保存本机外观，本次修改未应用。可能是存储空间不足或本机存储不可用。');
  }
}
function saveAppearance(event) {
  event.preventDefault();
  const editing = state.appearanceEditing; if (!editing) return false;
  if (state.appearanceBusy) { appearanceError('图片仍在处理，请完成后再保存。'); return false; }
  try {
    const scope = appearanceScope();
    if (!scope || scope.key !== editing.scope.key) throw new Error('当前对话已经变化，本次修改未保存。');
    const value = validateAppearance({ ...editing.draft, displayName: $('appearance-name').value });
    const saved = persistAppearance(scope, value);
    state.appearanceCache = { key: scope.key, value: saved, error: '' };
    cancelAppearance(); renderSessions(); renderMessages(); renderChrome();
    showNotice('当前对话外观已保存，仅在这台设备生效。'); return true;
  } catch (error) { appearanceError(errorText(error)); return false; }
}
function defaultInteractions() { return { version: 1, slots: DEFAULT_INTERACTIONS.slots.map(slot => ({ ...slot })) }; }
function interactionScope() {
  const scope = appearanceScope();
  return scope ? { key: pref('interactions.' + encodeURIComponent(JSON.stringify([state.server, state.username, state.activeId]))), title: scope.title } : null;
}
function validateInteractions(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1
      || Object.keys(value).sort().join('|') !== 'slots|version' || !Array.isArray(value.slots) || value.slots.length !== 4) throw new Error('互动设置格式无效，请恢复默认后重新保存。');
  return { version: 1, slots: value.slots.map(slot => {
    if (!slot || typeof slot !== 'object' || Array.isArray(slot) || Object.keys(slot).sort().join('|') !== 'action|enabled|label'
        || typeof slot.label !== 'string' || !slot.label.trim() || slot.label.length > 12 || /[\u0000-\u001f\u007f]/.test(slot.label)
        || typeof slot.action !== 'string' || !slot.action.trim() || slot.action.length > 300 || /[\u0000-\u0009\u000b-\u001f\u007f]/.test(slot.action)
        || typeof slot.enabled !== 'boolean') throw new Error('每项名称需为 1–12 字，互动文案需为 1–300 字，并选择是否启用。');
    return { label: slot.label.trim(), action: slot.action.trim(), enabled: slot.enabled };
  }) };
}
function readInteractions(scope) {
  const raw = localStorage.getItem(scope.key);
  if (raw === null || raw === '') return defaultInteractions();
  if (raw.length > 16000) throw new Error('本机互动记录过大，暂不读取。');
  return validateInteractions(JSON.parse(raw));
}
function currentInteractions() {
  const scope = interactionScope();
  if (!scope) { state.interactionCache = null; return DEFAULT_INTERACTIONS; }
  if (!state.interactionCache || state.interactionCache.key !== scope.key) {
    try { state.interactionCache = { key: scope.key, value: readInteractions(scope), error: '' }; }
    catch (_) { state.interactionCache = { key: scope.key, value: defaultInteractions(), error: '本机互动设置无法读取，请编辑或恢复默认后保存。' }; }
  }
  return state.interactionCache.value;
}
function interactionBusy() { return state.sending || state.attaching || state.appearanceBusy || state.remoteRunning || state.creating || state.stickerBusy; }
/* A chosen interaction becomes a compact action token, never chat prose. */
function actionToken(label) { return '（' + String(label).replace(/[（）\n\r]/g, '').slice(0, 40) + '）'; }
function buildOutgoingText(text, labels) {
  const actions = labels && labels.length ? labels.map(actionToken).join('') : '';
  // The action block is structural: it must never be cut in half, so a long
  // draft is shortened first and the actions always survive intact.
  const room = Math.max(0, 16000 - (actions ? actions.length + 1 : 0));
  const prose = text ? String(text).slice(0, room) : '';
  const blocks = [];
  if (prose) blocks.push(prose);
  if (actions) blocks.push(actions);
  return blocks.join('\n');
}
function renderPendingActions() {
  if (window.ChatComposer) { window.ChatComposer.renderPreview(); return; }
  const list = $('pending-actions'); if (!list) return;
  list.replaceChildren();
  list.hidden = !state.pendingActions.length;
  state.pendingActions.forEach((item, index) => {
    const chip = document.createElement('span'); chip.className = 'pending-action';
    const label = document.createElement('button'); label.type = 'button'; label.className = 'pending-action-label'; label.textContent = actionToken(item.label);
    label.title = '取消这条互动'; label.addEventListener('click', () => { state.pendingActions.splice(index, 1); renderPendingActions(); renderChrome(); });
    chip.append(label); list.append(chip);
  });
}
function renderInteractions() {
  if (window.ChatComposer) { window.ChatComposer.renderPreview(); window.ChatComposer.sync(); return; }
  const scope = interactionScope(); const config = currentInteractions();
  const error = state.interactionCache && state.interactionCache.error;
  for (let index = 0; index < 4; index++) {
    const button = $('quick-slot-' + index); const slot = config.slots[index];
    button.textContent = slot.label;
    button.disabled = !scope || interactionBusy() || !slot.enabled || !!error;
    button.title = slot.enabled ? '作为动作发送，不进入聊天正文' : '此快捷文案已停用';
  }
  $('interaction-edit').disabled = !scope || state.appearanceBusy;
  $('interaction-hint').textContent = !scope ? '请先登录并打开对话，再使用本机互动快捷文案。'
    : error || (interactionBusy() ? '当前正在处理消息或文件，完成后再加入互动。'
      : '点一下把动作放进待发送栏，确认后再发送；动作不会显示在聊天正文里。');
  renderPendingActions();
}
function insertInteraction(index) {
  const scope = interactionScope();
  if (!scope) { showNotice('请先登录并打开一个对话，互动快捷键不会自动创建会话。'); return false; }
  if (!Number.isInteger(index) || index < 0 || index > 3 || interactionBusy()) return false;
  const config = currentInteractions();
  if (state.interactionCache && state.interactionCache.error) { showNotice(state.interactionCache.error); return false; }
  const slot = config.slots[index]; if (!slot.enabled) return false;
  const now = Date.now(); const cooldownKey = scope.key + ':' + index;
  for (const [key, at] of state.interactionCooldowns) if (now - at >= 1500 || now < at) state.interactionCooldowns.delete(key);
  if (state.interactionCooldowns.has(cooldownKey)) { showNotice('这项文案刚刚已加入输入框，请先确认内容。'); return false; }
  if (state.pendingActions.length >= 4) { showNotice('一次最多带上 4 个互动动作，请先发送或取消。'); return false; }
  state.pendingActions.push({ label: slot.label, action: slot.action });
  state.interactionCooldowns.set(cooldownKey, now);
  renderPendingActions(); renderChrome();
  showNotice(actionToken(slot.label) + ' 已放进待发送栏；它作为动作提交，不会出现在聊天正文。'); return true;
}
function interactionError(message) { $('interaction-error').textContent = message; $('interaction-error').hidden = !message; }
function fillInteractionEditor(config) {
  for (let index = 0; index < 4; index++) {
    $('quick-label-' + index).value = config.slots[index].label;
    $('quick-action-' + index).value = config.slots[index].action;
    $('quick-enabled-' + index).checked = config.slots[index].enabled;
  }
}
function openInteractions() {
  if (window.ChatComposer) { window.ChatComposer.showActions(); return; }
  const scope = interactionScope();
  if (!scope) { showNotice('请先登录并打开一个对话，再编辑本机互动文案。'); return; }
  cancelAppearance();
  if ($('settings-dialog').open) $('settings-dialog').close();
  let value, error = '';
  try { value = readInteractions(scope); }
  catch (_) { value = defaultInteractions(); error = '无法读取原互动设置，暂显示默认值。保存前请检查本机存储。'; }
  state.interactionEditing = { scope };
  $('interaction-scope').textContent = scope.title + ' · 仅此对话 · 仅此设备';
  fillInteractionEditor(value); interactionError(error);
  if (!$('interaction-dialog').open) $('interaction-dialog').showModal();
}
function cancelInteractions() {
  state.interactionEditing = null;
  if ($('interaction-dialog').open) $('interaction-dialog').close();
}
function resetInteractions() { if (state.interactionEditing) { fillInteractionEditor(defaultInteractions()); interactionError(''); } }
function persistInteractions(scope, value) {
  const previous = localStorage.getItem(scope.key);
  const expected = JSON.stringify(value) === JSON.stringify(defaultInteractions()) ? null : JSON.stringify(value);
  let wrote = false;
  try {
    if (expected === null) localStorage.removeItem(scope.key); else localStorage.setItem(scope.key, expected);
    wrote = true;
    if (localStorage.getItem(scope.key) !== expected) throw new Error('保存回读不一致');
    return expected === null ? defaultInteractions() : readInteractions(scope);
  } catch (_) {
    let restoreFailed = false;
    if (wrote) {
      try { if (previous === null) localStorage.removeItem(scope.key); else localStorage.setItem(scope.key, previous); }
      catch (_) { restoreFailed = true; }
    }
    throw new Error(restoreFailed ? '互动设置保存结果未能确认，原设置也无法恢复。请检查本机存储。' : '无法保存本机互动设置，本次修改未应用。可能是空间不足或本机存储不可用。');
  }
}
function saveInteractions(event) {
  event.preventDefault(); const editing = state.interactionEditing; if (!editing) return false;
  try {
    const scope = interactionScope();
    if (!scope || scope.key !== editing.scope.key) throw new Error('当前对话已经变化，本次修改未保存。');
    const value = validateInteractions({ version: 1, slots: Array.from({ length: 4 }, (_, index) => ({
      label: $('quick-label-' + index).value, action: $('quick-action-' + index).value, enabled: $('quick-enabled-' + index).checked
    })) });
    const saved = persistInteractions(scope, value);
    state.interactionCache = { key: scope.key, value: saved, error: '' };
    cancelInteractions(); renderInteractions(); showNotice('当前对话的本机互动文案已保存。'); return true;
  } catch (error) { interactionError(errorText(error)); return false; }
}
function receive(id, payload) {
  const pending = state.requests.get(String(id));
  if (!pending) return; // A late response never triggers another send.
  state.requests.delete(String(id));
  clearTimeout(pending.timeout);
  if (pending.completeNative) pending.completeNative();
  if (pending.expired) { foregroundRecovery.stateChanged(); return; }
  try {
    const result = parse(payload);
    if (!result || typeof result.status !== 'number') throw new Error('应用返回了无法识别的连接结果。');
    let body = result.body;
    if (typeof body === 'string' && /^\s*[\[{]/.test(body)) {
      try { body = JSON.parse(body); } catch (_) {}
    }
    if (result.status === 401) {
      state.authenticated = false;
      try { native().clearAuth(); } catch (_) {}
      renderChrome();
    }
    if (result.status < 200 || result.status >= 300 || (body && typeof body === 'object' && body.status === 'error')) {
      throw responseError(result.status, body);
    }
    pending.resolve(body);
  } catch (error) { pending.reject(error); }
  foregroundRecovery.stateChanged();
}
const apiClient = {
  async json(method, path, body, options) {
    const response = await bridgeRequest(method, path, body, options);
    if (!response || typeof response !== 'object') throw new Error('服务器返回的数据格式暂不兼容。');
    return Object.prototype.hasOwnProperty.call(response, 'data') ? response.data : response;
  },
  sessions: options => apiClient.json('GET', API.sessions, undefined, options),
  personas: () => apiClient.json('GET', API.personas),
  connectBot: body => apiClient.json('POST', API.connect, body),
  history: (id, options) => apiClient.json('GET', API.history(id), undefined, options),
  send: (id, message, files = [], parts = null, clientMessageId = null) => bridgeRequest('POST', API.send, {
    session_id: id, message, enable_streaming: true,
    ...(parts ? { parts, client_message_id: clientMessageId } : {}),
    ...(files.length ? { files: files.filter(file=>!(parts||[]).some(part=>part.attachment_id===file.attachment_id)).map(file => ({ attachment_id: file.attachment_id })) } : {})
  }, {streaming:true})
};

function recoveryScope() {
  if (!state.authenticated || !state.server || !state.username) return null;
  if (state.activeId && !state.sessions.some(item => item.session_id === state.activeId)) return null;
  return { key: JSON.stringify([state.server, state.username, state.activeId || null]), sessionId: state.activeId || null };
}
function recoveryForeground() {
  const configured = nativeConfig().foreground;
  return document.hidden !== true && (typeof configured === 'boolean' ? configured : true);
}
function recoveryOnline() { return typeof navigator === 'undefined' || navigator.onLine !== false; }
function createForegroundRecovery({ intervalMs = 3000, idleMs = 30000, maxReads = 30, maxErrors = 3 } = {}) {
  if (!Number.isInteger(intervalMs) || intervalMs < 10 || intervalMs > 60000
      || !Number.isInteger(idleMs) || idleMs < intervalMs || idleMs > 300000
      || !Number.isInteger(maxReads) || maxReads < 1 || maxReads > 30
      || !Number.isInteger(maxErrors) || maxErrors < 1 || maxErrors > 3) throw new Error('前台回读参数无效。');
  let timer = null, inFlight = false, nativeTicket = null, loadingTicket = null;
  let epoch = 0, scope = null, active = false, waiting = false, reads = 0, errors = 0, deadline = 0, generating = false;
  let nextDelay = intervalMs, reason = 'idle', blockedKey = null, observedRunningKey = null, timeoutLocked = false;
  const sameScope = captured => { const current = recoveryScope(); return !!current && current.key === captured.key; };
  const busy = () => state.sending || state.loading || state.creating || state.attaching || state.appearanceBusy || state.exportBusy || !!state.exportEditing || state.requests.size > 0;
  const clearTimer = () => { if (timer !== null) { clearTimeout(timer); timer = null; } };
  function paint() {
    const element = $('auto-sync-status'); if (!element) return;
    element.classList.toggle('needs-attention', timeoutLocked || !recoveryOnline() || ['errors', 'authorization', 'budget'].includes(reason));
    element.textContent = timeoutLocked ? '上次自动同步超时，已暂停。稍后请点同步核对，应用不会重发消息。'
      : !recoveryForeground() ? '已暂停自动同步；仅在前台同步。'
      : !recoveryOnline() ? '设备提示离线，自动同步已暂停。'
      : !state.authenticated ? '登录后前台自动同步；后台提醒需在设置中明确开启。'
      : reason === 'errors' || reason === 'authorization' ? '自动同步已暂停，请点同步核对；应用不会重发消息。'
      : reason === 'budget' ? '本轮自动同步已到上限，请点同步核对回复。'
      : inFlight ? '正在同步记录，不会自动发送或重发消息。'
      : active && waiting ? '当前操作完成后自动同步。'
      : active ? (generating ? '正在同步生成中的回复。' : '前台每30秒同步新消息；不会自动发送。')
      : '前台同步待启动；后台提醒需在设置中明确开启。';
  }
  function finish(why, lock = false) {
    if (lock && scope) blockedKey = scope.key;
    epoch++; active = false; waiting = false; clearTimer(); reason = why; scope = null; paint();
  }
  function cancel(why = 'cancelled', releaseLoading = false) {
    epoch++; active = false; waiting = false; clearTimer(); reason = why; scope = null;
    blockedKey = null; observedRunningKey = null;
    if (releaseLoading && loadingTicket) { loadingTicket = null; state.loading = false; }
    paint();
  }
  function eligible() { return recoveryForeground() && recoveryOnline() && !!recoveryScope(); }
  function schedule() {
    if (!active || timer !== null || inFlight || nativeTicket) { paint(); return; }
    if (!eligible() || !scope || !sameScope(scope)) { cancel('scope_or_visibility'); return; }
    if (generating && (reads >= maxReads || Date.now() >= deadline)) { finish('budget', true); return; }
    if (busy()) { waiting = true; paint(); return; }
    waiting = false;
    timer = setTimeout(() => { timer = null; void run(); }, nextDelay);
    paint();
  }
  function start(captured, delay) {
    if (timeoutLocked || blockedKey === captured.key) { paint(); return; }
    epoch++; scope = captured; active = true; waiting = false; reads = 0; errors = 0;
    generating = state.remoteRunning === true;
    deadline = Date.now() + intervalMs * maxReads; nextDelay = delay; reason = generating ? 'active' : 'idle';
    if (generating) observedRunningKey = captured.key;
    schedule();
  }
  async function run() {
    if (!active || inFlight || nativeTicket || !scope) return;
    if (!eligible() || !sameScope(scope)) { cancel('scope_or_visibility'); return; }
    if (generating && (reads >= maxReads || Date.now() >= deadline)) { finish('budget', true); return; }
    if (busy()) { waiting = true; paint(); return; }
    const ticket = { epoch, scope }; inFlight = true; nativeTicket = ticket; loadingTicket = ticket;
    reads++; waiting = false; nextDelay = intervalMs; state.loading = true; renderChrome();
    const accept = () => active && epoch === ticket.epoch && eligible() && sameScope(ticket.scope)
      && !state.sending && !state.creating && !state.attaching && !state.appearanceBusy;
    const onNativeComplete = () => {
      if (nativeTicket === ticket) nativeTicket = null;
      stateChanged();
    };
    try {
      const applied = ticket.scope.sessionId
        ? await loadHistory(ticket.scope.sessionId, { accept, reconcileAttachments: false, preserveUnconfirmed: true, preserveReading: true, onNativeComplete })
        : await loadSessions({ select: false, accept, onNativeComplete });
      if (!accept() || applied === false) return;
      errors = 0;
      if (!ticket.scope.sessionId) { finish('complete'); }
      else if (state.remoteRunning) {
        if (!generating) { generating = true; deadline = Date.now() + intervalMs * maxReads; reads = 1; }
        observedRunningKey = ticket.scope.key; nextDelay = intervalMs; reason = 'active';
      } else {
        // Proactive history inserts have no is_running phase. Keep the same
        // single read coordinator alive at the idle interval after completion.
        generating = false; observedRunningKey = null; reads = 0;
        nextDelay = idleMs; reason = 'idle';
      }
    } catch (error) {
      if (error && error.nativeCompletionUnknown === true) {
        timeoutLocked = true; finish('timeout', true);
      } else if (epoch !== ticket.epoch || !sameScope(ticket.scope)) return;
      else if (error && [401, 403].includes(error.status)) finish('authorization', true);
      else { errors++; if (errors >= maxErrors) finish('errors', true); }
    } finally {
      if (loadingTicket === ticket) { loadingTicket = null; state.loading = false; }
      inFlight = false;
      renderChrome();
    }
  }
  function stateChanged() {
    const current = recoveryScope();
    if (!recoveryForeground() || !recoveryOnline() || !current) {
      if (active || timer !== null) cancel('scope_or_visibility');
      paint(); return;
    }
    if (active && scope && scope.key !== current.key) cancel('scope_changed');
    if (!state.remoteRunning) observedRunningKey = null;
    if (!active && current.sessionId && !timeoutLocked && blockedKey !== current.key) {
      start(current, state.remoteRunning ? intervalMs : idleMs); return;
    }
    if (active && state.remoteRunning && !generating && !inFlight) {
      generating = true; reads = 0; deadline = Date.now() + intervalMs * maxReads;
      nextDelay = intervalMs; reason = 'active'; clearTimer();
    }
    if (active) {
      if (!inFlight && busy()) { clearTimer(); waiting = true; }
      else schedule();
    }
    paint();
  }
  function signal() {
    const current = recoveryScope();
    if (!recoveryForeground() || !recoveryOnline() || !current) { cancel('scope_or_visibility'); return; }
    if (timeoutLocked || blockedKey === current.key) { paint(); return; }
    if (active && scope && scope.key === current.key) { schedule(); return; }
    if (active) cancel('scope_changed');
    start(current, 0);
  }
  function manualIntent() {
    if (nativeTicket) { paint(); return false; }
    timeoutLocked = false; cancel('manual'); return true;
  }
  return { signal, stateChanged, cancel, manualIntent,
    snapshot: () => ({ active, inFlight, nativePending: !!nativeTicket, timer: timer !== null,
      waiting, reads, errors, reason, generating, timeoutLocked, maxReads, maxErrors, intervalMs, idleMs }) };
}
let foregroundRecovery = createForegroundRecovery();

function attachmentQueue(id = state.activeId) { return state.attachmentQueues.get(id) || []; }
function readyAttachments() { return attachmentQueue().filter(item => item.status === 'ready'); }
function invalidAttachments() { return attachmentQueue().some(item => item.status !== 'ready'); }
function fileSize(value) {
  if (!Number.isFinite(value) || value < 0) return '';
  return value < 1024 ? value + ' B' : value < 1024 * 1024 ? (value / 1024).toFixed(1) + ' KB' : (value / (1024 * 1024)).toFixed(1) + ' MB';
}
function renderAttachments() {
  const list = $('attachment-queue'); list.replaceChildren();
  const queue = attachmentQueue(); list.hidden = !queue.length;
  for (const item of queue) {
    const chip = document.createElement('div'); chip.className = 'attachment-chip' + (['unknown', 'send-unknown'].includes(item.status) ? ' problem' : '');
    const icon = document.createElement('span'); icon.className = 'attachment-chip-icon'; icon.textContent = item.type === 'image' ? '▧' : '▤';
    const info = document.createElement('div'); info.className = 'attachment-chip-info';
    const name = document.createElement('span'); name.className = 'attachment-chip-name'; name.textContent = item.display_name || '图片或文件';
    const status = document.createElement('span'); status.className = 'attachment-chip-status';
    status.textContent = item.status === 'choosing' ? '选择文件 / 上传中…' : item.status === 'sending' ? '发送中，尚未确认保存' : item.status === 'send-unknown' ? '发送结果待核对' : item.status === 'unknown' ? '上传结果待确认，请移除后检查' : '已上传 · 待发送' + (item.size ? ' · ' + fileSize(item.size) : '');
    info.append(name, status); chip.append(icon, info);
    if (item.status === 'send-unknown') {
      const prepare = document.createElement('button'); prepare.className = 'attachment-prepare'; prepare.textContent = '核对后重试';
      prepare.addEventListener('click', async () => {
        if (!await refreshCurrent() || state.remoteRunning || !attachmentQueue().includes(item)) return;
        item.status = 'ready'; renderAttachments(); renderChrome();
        showNotice('已同步记录。请确认附件没有保存，再点发送；应用不会自动重发。');
      }); chip.append(prepare);
    }
    const remove = document.createElement('button'); remove.textContent = '×'; remove.setAttribute('aria-label', '移除待发送附件');
    remove.disabled = item.status === 'choosing' || item.status === 'sending';
    remove.addEventListener('click', () => {
      state.attachmentQueues.set(item.session_id, attachmentQueue(item.session_id).filter(value => value !== item));
      renderAttachments(); renderChrome();
    }); chip.append(remove); list.append(chip);
  }
}
async function chooseAttachment() {
  if (!state.authenticated) { openSettings(); return; }
  if (state.sending || state.loading || state.attaching || state.appearanceBusy || state.exportBusy || state.remoteRunning) return;
  if(primaryConnectionId()&&state.activeId!==primaryConnectionId()){showNotice('这里是历史记录，请回到伙伴再发送。');return;}
  if (attachmentQueue().length >= 4) { showNotice('每条消息最多附带 4 个文件。'); return; }
  state.attaching = true; renderChrome();
  let item;
  try {
    const sessionId = state.activeId || await connectLongTerm();
    const queue = attachmentQueue(sessionId);
    item = { localId: 'file-' + Date.now(), session_id: sessionId, status: 'choosing' };
    state.attachmentQueues.set(sessionId, [...queue, item]); renderAttachments();
    const body = await nativeAsync('chooseAttachment', [sessionId], 300000);
    if (body && body.cancelled === true) {
      state.attachmentQueues.set(sessionId, attachmentQueue(sessionId).filter(value => value !== item)); return;
    }
    const data = responseData(body);
    if (!data || typeof data.attachment_id !== 'string' || !data.attachment_id
        || typeof data.filename !== 'string' || data.session_id !== sessionId
        || !['image', 'file', 'record', 'video'].includes(data.type)) throw new Error('服务器未确认有效的附件上传结果。');
    Object.assign(item, { attachment_id: data.attachment_id, filename: data.filename,
      display_name: typeof data.display_name === 'string' ? data.display_name : data.filename,
      type: data.type, mime_type: data.mime_type, size: data.size, status: 'ready' });
    hideNotice();
  } catch (error) {
    if (item && ['picker_unavailable','attachment_not_ready','file_too_large'].includes(error.code)) {
      state.attachmentQueues.set(item.session_id, attachmentQueue(item.session_id).filter(value => value !== item));
    } else if (item) item.status = 'unknown';
    showNotice(errorText(error), null, true);
  } finally { state.attaching = false; renderAttachments(); renderChrome(); }
}

function showNotice(text, action, error = false) {
  $('notice-text').textContent = text;
  $('notice').classList.toggle('error', error);
  $('notice').dataset.kind = error ? 'error' : action ? 'action' : 'status';
  $('notice').setAttribute('role', error ? 'alert' : 'status');
  $('notice').hidden = false;
  $('notice-action').hidden = !action;
  $('notice-action').textContent = action ? action.label : '';
  $('notice-action').onclick = action ? action.run : null;
}
function hideNotice() { $('notice').hidden = true; $('notice-action').onclick = null; $('notice-action').hidden = true; }
/* Reply notifications while the page is hidden. The server still owns delivery:
   this only announces a record the client really read, and it is bounded to one
   poll per 30s with the same document id remembered across restarts. */
function notifyEnabled() { return storage.get(pref('notify')) === '1'; }
let notifyWatch = null;
/* One remembered record per conversation: switching conversations must not
   resurrect an old message as a new notification. */
function notifiedKey() { return pref('notified.' + encodeURIComponent(state.activeId || '')); }
function conversationTitle() {
  const active = state.sessions.find(item => item.session_id === state.activeId);
  const appearance = currentAppearance();
  return appearance.displayName || (active && active.display_name) || appearanceBaseName();
}
function notifyTarget() {
  return !!(state.authenticated && state.activeId && window.AsteriaChat
    && typeof window.AsteriaChat.notifyMessage === 'function');
}
async function notifyTick() {
  if (window.AsteriaChat && typeof window.AsteriaChat.setReplyWatch === 'function') return;
  if (!notifyEnabled() || !notifyTarget() || document.hidden !== true || state.sending) return;
  try {
    const result = await apiClient.history(state.activeId);
    const rows = normalizeHistory(result && Array.isArray(result.history) ? result.history : []);
    const last = rows.filter(row => row.role === 'assistant').pop();
    if (!last || last.id === storage.get(notifiedKey())) return;
    const answer = parse(window.AsteriaChat.notifyMessage(state.activeId, conversationTitle(),
      String(last.text || '').slice(0, 120)));
    if (answer && answer.ok === true) {
      // Remembered only after the notification really exists: a refused or
      // deferred notification must not silence this reply for ever.
      storage.set(notifiedKey(), last.id);
    } else if (answer && answer.error === 'notification_permission') {
      showNotice('通知权限还没开启，这条回复会在开启后补提醒。');
    }
  } catch (_) { /* a hidden poll never raises a notice or resends anything. */ }
}
function startNotifyWatch() {
  if (window.AsteriaChat && typeof window.AsteriaChat.setReplyWatch === 'function') return;
  if (notifyWatch !== null || typeof setInterval !== 'function') return;
  notifyWatch = setInterval(notifyTick, 30000);
}
/* Android reports the keyboard through the visual viewport; dvh alone keeps the
   composer under the keyboard, so the app shell follows the visible height. */
function syncViewport() {
  const shell = document.documentElement;
  if (!shell || !shell.style || typeof shell.style.setProperty !== 'function') return;
  const viewport = window.visualViewport;
  const nativeView = window.ChatComposer && window.ChatComposer.viewport();
  const height = nativeView && nativeView.height > 0 ? nativeView.height : viewport ? viewport.height : window.innerHeight;
  const inset = viewport && typeof window.innerHeight === 'number'
    ? Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop)) : 0;
  const apply = () => {
    document.documentElement.style.setProperty('--app-height', Math.round(height) + 'px');
    document.documentElement.style.setProperty('--keyboard-inset', (nativeView ? 0 : inset) + 'px');
    syncComposerMetrics();
  };
  if (window.ChatComposer) window.ChatComposer.withReading(apply); else apply();
}
function keepComposerVisible() {
  // Host layout owns IME visibility. Never scroll the transcript on input focus.
  syncViewport();
}
function syncComposerMetrics() {
  const area = document.querySelector('.composer-area'), app = $('app');
  if (area && app && app.style && typeof app.style.setProperty === 'function'
      && typeof area.getBoundingClientRect === 'function') {
    const height=Math.ceil(area.getBoundingClientRect().height)+'px';
    if(app.style.getPropertyValue('--composer-height')!==height)app.style.setProperty('--composer-height',height);
  }
  if (window.ChatComposer) window.ChatComposer.panelHeight();
}
function resizeDraft() {
  const view = window.ChatComposer && window.ChatComposer.viewport();
  const height = view && view.height || window.visualViewport && window.visualViewport.height || innerHeight;
  const limit = Math.max(42, Math.min(132, Math.floor(height * .22)));
  const measurement=JSON.stringify([$('draft').value,$('draft').clientWidth,limit]);
  if(state.draftMeasurement===measurement)return;
  state.draftMeasurement=measurement;
  $('draft').style.height = 'auto'; $('draft').style.height = Math.min($('draft').scrollHeight, limit) + 'px';
  $('draft').style.maxHeight = limit + 'px'; syncComposerMetrics();
}
function saveDraft() { storage.set(draftKey(state.activeId), $('draft').value); if (window.ChatComposer) window.ChatComposer.persist(); }
function restoreDraft() { $('draft').value = storage.get(draftKey(state.activeId)); if (window.ChatComposer) window.ChatComposer.restore(); resizeDraft(); renderChrome(); }
function sidebar(open) {
  $('sidebar').classList.toggle('open', open);
  $('sidebar-backdrop').hidden = !open;
  $('open-sidebar').setAttribute('aria-expanded', String(open));
}

function renameScope() {
  const scope = appearanceScope();
  return scope ? { key: scope.key, sessionId: state.activeId } : null;
}
function currentRenameEditor(editor) {
  const scope = renameScope();
  return state.renameEditing === editor && !!scope && scope.key === editor.scope.key;
}
function cancelRenameTitle() {
  const open = !!state.renameEditing || $('rename-dialog').open;
  state.renameEditing = null;
  if ($('rename-dialog').open) $('rename-dialog').close();
  return open;
}
function renderRenameTitle() {
  const scope = renameScope();
  if (state.renameEditing && (!scope || scope.key !== state.renameEditing.scope.key)) cancelRenameTitle();
  $('rename-button').disabled = !scope || state.renaming || state.sending || state.loading || state.creating || state.attaching || state.appearanceBusy;
  const editor = state.renameEditing;
  if (!editor) return;
  $('rename-input').disabled = state.renaming || editor.phase !== 'editing';
  $('rename-save').disabled = state.renaming || editor.phase !== 'editing';
  $('rename-save').textContent = editor.phase === 'pending' ? '正在保存…' : '保存';
  $('rename-check').hidden = !['unknown', 'verify', 'error'].includes(editor.phase);
  $('rename-check').disabled = state.renaming;
  $('rename-error').textContent = editor.message || '';
  $('rename-error').hidden = !editor.message;
  $('rename-error').classList.toggle('rename-confirmed', editor.phase === 'verified');
}
function renameServerTitle(value) {
  return value === null || value === '' ? '未命名会话' : value;
}
function exportScope() { return appearanceScope(); }
function exportUtf8Bytes(text) {
  let bytes = 0;
  for (let index = 0; index < text.length; index++) {
    const unit = text.charCodeAt(index);
    if (unit < 0x80) bytes++;
    else if (unit < 0x800) bytes += 2;
    else if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = text.charCodeAt(++index);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error('记录含无效文字编码，无法导出；原内容未改动。');
      bytes += 4;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) throw new Error('记录含无效文字编码，无法导出；原内容未改动。');
    else bytes += 3;
  }
  return bytes;
}
function exportMarkdownText(value) {
  if (exportUtf8Bytes(value) > MAX_EXPORT_BYTES) throw new Error('当前记录超过2 MiB导出上限，请缩小已加载范围；不会截断保存。');
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/[\\`*_{}\[\]()#+\-.!|]/g, '\\$&');
}
function safeExportMediaName(value, part) {
  if (typeof value !== 'string' || !value.trim() || value.length > 256
      || /[\\/\u0000-\u001f\u007f]/.test(value) || value.includes('://')
      || value === part.attachment_id || value === part.stored_filename
      || (value.includes('.') && value.slice(0, value.lastIndexOf('.')) === part.attachment_id)
      || /^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\.[^.]*)?$/i.test(value)) return '';
  return value;
}
function exportMessageParts(message) {
  if (!message || message.delivery !== 'confirmed' || !['user', 'assistant'].includes(message.role) || !Array.isArray(message.parts)) return [];
  const parts = [];
  for (const part of message.parts) {
    if (!part || typeof part !== 'object') continue;
    if (part.type === 'plain' && typeof part.text === 'string' && part.text.length) parts.push({ type: 'plain', text: part.text });
    else if (part.type === 'action') parts.push({ type: 'plain', text: '[用户动作] ' + (part.label || '互动') + (part.description ? '：' + part.description : '') });
    else if (part.type === 'sticker') parts.push({ type: 'image', name: part.name || '表情' });
    else if (['image', 'file', 'record', 'video'].includes(part.type)) parts.push({ type: part.type,
      name: safeExportMediaName(part.export_name, part) });
  }
  return parts;
}
function buildConversationMarkdown(messages, title, at = new Date()) {
  const chunks = []; let bytes = 0, count = 0;
  const append = value => { const size = exportUtf8Bytes(value); if (bytes + size > MAX_EXPORT_BYTES) throw new Error('当前记录超过2 MiB导出上限，请缩小已加载范围；不会截断保存。'); bytes += size; chunks.push(value); };
  const date = at instanceof Date ? at : new Date(at);
  if (!Number.isFinite(date.getTime())) throw new Error('导出时间无效，请稍后重试。');
  append('# Asteria Chat 对话导出\n\n当前显示会话标题：' + exportMarkdownText(title) + '\n\n');
  append('导出时间（UTC）：' + date.toISOString() + '\n\n');
  append('范围：当前已加载且已确认保存的消息快照，并非全部历史。草稿、未确认片段不包含在内；媒体仅有名称文字，不包含原文件。\n\n');
  const mediaNames = { image: '图片', file: '文件', record: '音频', video: '视频' };
  for (const message of messages) {
    const parts = exportMessageParts(message); if (!parts.length) continue;
    let when = '时间未提供';
    if (typeof message.created_at === 'string' || typeof message.created_at === 'number') {
      const value = message.created_at;
      const stamp = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
      if (Number.isFinite(stamp.getTime())) when = stamp.toISOString();
    }
    append('## ' + (message.role === 'user' ? '你' : '助手') + ' · ' + when + '\n\n');
    for (const part of parts) append(part.type === 'plain' ? exportMarkdownText(part.text) + '\n\n'
      : mediaNames[part.type] + (part.name ? '：' + exportMarkdownText(part.name) : '') + '（原文件未导出）\n\n');
    count++;
  }
  if (!count) throw new Error('当前没有可导出的已确认消息。');
  const localDate = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  return { markdown: chunks.join(''), bytes, count, title, filename: 'asteria-chat-' + localDate + '.md' };
}
function exportBlocked() {
  return state.sending || state.loading || state.creating || state.attaching || state.appearanceBusy
    || state.renaming || state.remoteRunning || state.exportBusy || state.requests.size > 0;
}
function currentExportEditor(editor) {
  const scope = exportScope(); return state.exportEditing === editor && !!scope && scope.key === editor.scope.key;
}
function cancelConversationExport(force = false) {
  if (!state.exportEditing && !$('export-dialog').open) return false;
  if (state.exportBusy && !force) {
    $('export-status').textContent = '请在系统保存界面取消，当前操作尚未结束。'; $('export-status').hidden = false; return true;
  }
  state.exportEditing = null;
  if ($('export-dialog').open) $('export-dialog').close();
  return true;
}
function renderConversationExport() {
  const scope = exportScope();
  if (state.exportEditing && !currentExportEditor(state.exportEditing)) cancelConversationExport(true);
  const available = !!(window.AsteriaChat && typeof window.AsteriaChat.exportConversation === 'function');
  const count = scope ? state.messages.filter(message => exportMessageParts(message).length).length : 0;
  $('export-open').disabled = !scope || exportBlocked() || !available || !count;
  $('export-available').textContent = !scope ? '请先登录并打开对话' : !available ? '请更新应用后使用' : exportBlocked() ? '当前操作完成后可导出'
    : count ? '当前有' + count + '条已确认消息 →' : '暂无已确认消息';
  const editor = state.exportEditing; if (!editor) return;
  $('export-confirm').disabled = state.exportBusy || editor.phase !== 'preview';
  $('export-confirm').textContent = state.exportBusy ? '等待系统保存…' : '选择位置并保存';
  $('export-close').disabled = state.exportBusy; $('export-cancel').disabled = state.exportBusy;
  $('export-status').textContent = editor.message || '';
  $('export-status').hidden = !editor.message;
}
function openConversationExport() {
  if (!exportScope() || exportBlocked()) return;
  if (!window.AsteriaChat || typeof window.AsteriaChat.exportConversation !== 'function') return;
  try {
    const scope = exportScope();
    const snapshot = buildConversationMarkdown(state.messages, $('conversation-title').textContent || '未命名会话');
    cancelAppearance(); cancelInteractions(); cancelRenameTitle();
    if ($('settings-dialog').open) $('settings-dialog').close();
    state.exportEditing = { scope, snapshot, epoch: ++state.exportSerial, phase: 'preview', message: '' };
    $('export-summary').textContent = snapshot.count + '条已确认消息 · UTF-8 ' + fileSize(snapshot.bytes);
    $('export-conversation-title').textContent = snapshot.title;
    $('export-filename').textContent = snapshot.filename;
    $('export-dialog').showModal(); renderChrome();
  } catch (error) {
    $('export-available').textContent = errorText(error);
  }
}
async function saveConversationExport(event) {
  event.preventDefault(); const editor = state.exportEditing;
  if (!editor || !currentExportEditor(editor) || exportBlocked() || editor.phase !== 'preview') return;
  state.exportBusy = true; state.exportPendingEpoch = editor.epoch; editor.phase = 'saving'; editor.message = '';
  renderChrome();
  try {
    const data = responseData(await nativeAsync('exportConversation', [editor.snapshot.filename, editor.snapshot.markdown], 300000));
    if (!currentExportEditor(editor)) return;
    if (data && data.cancelled === true && data.exported !== true) { editor.phase = 'preview'; editor.message = '已取消保存。'; }
    else if (data && data.exported === true && data.filename === editor.snapshot.filename && data.bytes === editor.snapshot.bytes) {
      editor.phase = 'saved'; editor.message = '已保存到你选择的位置。';
    } else throw new Error('系统未返回可确认的保存结果，请检查所选位置。');
  } catch (error) {
    if (currentExportEditor(editor)) {
      editor.phase = error && error.nativeTimeout ? 'unknown' : 'error';
      editor.message = error && error.nativeTimeout ? '保存结果尚未确认，请检查所选位置；应用不会自动重试。'
        : error && error.partialFilePossible ? '保存失败，目标位置可能有不完整文件。请先检查；应用不会自动重试。'
        : '未能确认保存：' + errorText(error) + ' 应用不会自动重试。';
    }
  } finally {
    if (state.exportPendingEpoch === editor.epoch) { state.exportBusy = false; state.exportPendingEpoch = null; }
    renderChrome();
  }
}
async function readRenameTitle(editor, mode) {
  const rows = await apiClient.sessions();
  if (!currentRenameEditor(editor)) return false;
  if (!Array.isArray(rows)) throw new Error('会话列表格式暂不兼容，尚未确认标题。');
  const row = rows.find(item => item && item.session_id === editor.scope.sessionId);
  if (!row || !Object.prototype.hasOwnProperty.call(row, 'display_name') || (row.display_name !== null && typeof row.display_name !== 'string')) {
    throw new Error('无法确认这段会话的服务器标题，请稍后核对。');
  }
  state.sessions = rows.filter(item => item && typeof item.session_id === 'string');
  editor.expected = row.display_name;
  $('rename-server-title').textContent = renameServerTitle(row.display_name);
  if (mode === 'unknown') {
    editor.phase = 'unknown';
    editor.message = row.display_name === editor.requested
      ? '已读到目标标题，但上次保存回执未确认；本次不会重复提交。可关闭后继续使用。'
      : '上次保存结果仍不确定，当前仅核对服务器标题，不会重复提交。请稍后再次核对。';
  } else if (mode === 'verify') {
    editor.phase = row.display_name === editor.requested ? 'verified' : 'verify';
    editor.message = editor.phase === 'verified' ? '已保存，并从服务器重新读到此标题。'
      : '保存请求已返回，但服务器当前标题尚未一致；请再次核对，应用不会重复提交。';
  } else {
    editor.phase = 'editing';
    if (mode === 'open') { $('rename-input').value = row.display_name === null ? '' : row.display_name; editor.message = ''; }
  }
  renderSessions();
  return true;
}
async function openRenameTitle() {
  const scope = renameScope();
  if (!scope || state.renaming || state.sending || state.loading || state.creating || state.attaching || state.appearanceBusy) return;
  const uncertain = state.renameUnknown.get(scope.key);
  const editor = { scope, expected: null, requested: uncertain ? uncertain.requested : '', phase: 'loading', message: '正在读取服务器当前标题…' };
  state.renameEditing = editor;
  $('rename-input').value = editor.requested; $('rename-server-title').textContent = '正在读取…';
  if (!$('rename-dialog').open) $('rename-dialog').showModal();
  state.renaming = true; renderChrome();
  try { await readRenameTitle(editor, uncertain ? 'unknown' : 'open'); }
  catch (error) { if (currentRenameEditor(editor)) { editor.phase = uncertain ? 'unknown' : 'error'; editor.message = errorText(error) + ' 尚未确认服务器标题。'; } }
  finally { state.renaming = false; renderChrome(); }
}
async function reconcileRenameTitle() {
  const editor = state.renameEditing;
  if (!editor || !currentRenameEditor(editor) || state.renaming) return;
  const mode = state.renameUnknown.has(editor.scope.key) ? 'unknown' : editor.phase === 'verify' ? 'verify' : 'open';
  state.renaming = true; renderChrome();
  try { await readRenameTitle(editor, mode); }
  catch (error) { if (currentRenameEditor(editor)) editor.message = errorText(error) + ' 尚未确认服务器标题。'; }
  finally { state.renaming = false; renderChrome(); }
}
async function saveRenameTitle(event) {
  event.preventDefault();
  const editor = state.renameEditing;
  if (!editor || !currentRenameEditor(editor) || state.renaming || editor.phase !== 'editing' || state.renameUnknown.has(editor.scope.key)) return;
  const raw = $('rename-input').value, title = raw.trim();
  if (/[\u0000-\u001f\u007f-\u009f]/.test(raw) || !title || Array.from(title).length > 120) {
    editor.message = '请输入不含控制字符的标题，去除首尾空格后为 1–120 字。'; renderRenameTitle(); return;
  }
  editor.requested = title; editor.phase = 'pending'; editor.message = '正在保存；完成后会重新读取服务器标题。';
  const pending = { requested: title };
  state.renameUnknown.set(editor.scope.key, pending);
  state.renaming = true; renderChrome();
  let mode = 'verify';
  try {
    await apiClient.json('POST', API.rename, { session_id: editor.scope.sessionId, display_name: title, expected_display_name: editor.expected });
    if (state.renameUnknown.get(editor.scope.key) === pending) state.renameUnknown.delete(editor.scope.key);
  } catch (error) {
    const rejected = [400, 403, 404, 409].includes(error.status);
    if (rejected && state.renameUnknown.get(editor.scope.key) === pending) state.renameUnknown.delete(editor.scope.key);
    mode = rejected ? 'rejected' : 'unknown';
    if (currentRenameEditor(editor)) editor.message = rejected ? errorText(error) + ' 已重新读取当前标题后，可修改再明确保存。'
      : '保存结果不确定。仅核对服务器标题，不会自动重新保存。';
  }
  if (currentRenameEditor(editor)) {
    editor.phase = mode === 'unknown' ? 'unknown' : mode === 'verify' ? 'verify' : 'error';
    try { await readRenameTitle(editor, mode); }
    catch (error) { if (currentRenameEditor(editor)) { editor.phase = mode === 'unknown' ? 'unknown' : mode === 'verify' ? 'verify' : 'error'; editor.message += ' ' + errorText(error) + ' 尚未确认服务器标题。'; } }
  }
  state.renaming = false; renderChrome();
}

/* One shared close for the header menu: selecting a conversation, pressing
   Escape or picking an action all end in the same visible state. */
function hideMoreMenu() {
  const menu = $('more-menu'); if (!menu) return;
  menu.hidden = true;
  const button = $('more-button');
  if (button) button.setAttribute('aria-expanded', 'false');
}
function renderChrome() {
  if (phonePerceptionPanel) {
    phonePerceptionPanel.scopeChanged();
    const current = state.authenticated && state.server && state.username && state.activeId
      ? JSON.stringify([state.server,state.username,state.activeId]) : null;
    if (perceptionNativeScope && current !== perceptionNativeScope && (current || !state.authenticated)) {
      nativeAsync('stopPhonePerception', []).catch(() => {});
    }
    // Empty selection during initial loading is not a request to stop an
    // explicitly enabled collector from the same saved account/session.
    if (current || !state.authenticated) perceptionNativeScope = current;
  }
  if (window.ChatIdentity) window.ChatIdentity.scopeChanged();
  if (window.ChatWorkspace) window.ChatWorkspace.scopeChanged();
  if (window.ChatNight && typeof window.ChatNight.scopeChanged === 'function') window.ChatNight.scopeChanged();
  if (window.ChatExperience && typeof window.ChatExperience.scopeChanged === 'function') window.ChatExperience.scopeChanged();
  renderRenameTitle();
  renderMessageSearchControls();
  const active = state.sessions.find(item => item.session_id === state.activeId);
  const persona = configuredPersonaForCurrent();
  $('conversation-title').textContent = active && active.display_name ? active.display_name
    : persona && persona.status === 'configured' ? persona.displayName : state.activeId ? '聊天记录' : 'Asteria Chat';
  $('conversation-persona').textContent = !state.activeId ? '会话角色：打开对话后查看配置'
    : !persona ? (state.loading ? '会话角色：正在读取配置…' : '会话角色：尚未读取配置')
    : persona.status === 'configured' ? '会话角色：' + persona.displayName + '（配置）'
    : persona.status === 'unconfigured' ? '会话角色：未配置'
    : persona.status === 'missing' ? '会话角色：配置角色已不存在' : '会话角色：配置暂无法确认';
  $('account-label').textContent = state.authenticated ? state.username || '已登录账户' : '尚未登录';
  let serverName = '连接你的服务器';
  try { if (state.server) serverName = new URL(state.server).host; } catch (_) {}
  $('server-label').textContent = serverName;
  document.querySelector('.local-dot').classList.toggle('connected', state.authenticated);
  $('connection-status').textContent = !state.bridgeAvailable ? '需要在 Android 应用中连接' : !state.authenticated ? '登录后同步会话' : state.loading ? '正在读取服务器记录…' : state.sending ? '本轮消息正在处理中' : state.remoteRunning ? '服务器仍在生成 · 可点同步查看' : '私人对话';
  $('send-button').disabled = !state.bridgeAvailable || !state.authenticated || state.sending || state.loading || state.creating || state.attaching || state.remoteRunning || invalidAttachments() || (!$('draft').value.trim() && !readyAttachments().length && !(window.ChatComposer && window.ChatComposer.hasContent()));
  $('attach-button').disabled = !state.bridgeAvailable || !state.authenticated || state.sending || state.loading || state.creating || state.attaching || state.appearanceBusy || state.remoteRunning;
  $('bot-home').disabled = state.sending || state.loading || state.creating || state.attaching;
  $('refresh-chat').disabled = !state.authenticated || state.loading || state.sending;
  $('refresh-sessions').disabled = !state.authenticated || state.loading || state.sending;
  const sessionBusy = state.sending || state.attaching || state.loading || state.creating;
  for (const button of $('conversation-list').querySelectorAll('.session-button')) button.disabled = sessionBusy;
  const phase=state.replyPhase;
  $('reply-status').hidden = !state.sending && !state.remoteRunning && !['failed','unknown'].includes(phase);
  $('reply-status').dataset.phase=phase;
  const phases={submitting:'正在提交这条消息…',queued:'消息已接收，等待开始回复…',generating:'伙伴正在组织回复…',streaming:'伙伴正在输入…',completed:'回复已生成，正在同步保存记录…',failed:'本轮回复未完成，可同步查看实际记录。',unknown:'连接中断，回复结果待同步；不会自动重发。'};
  $('reply-status-text').textContent=state.sending?(phases[phase]||'TLS正在处理这轮消息…'):state.remoteRunning?'TLS仍在处理这轮消息，可同步查看。':(phases[phase]||'');
  $('empty-login').hidden = state.authenticated;
  $('empty-description').textContent = state.authenticated ? '登录后持续连接伙伴，之前的聊天与日常都会留在这里。' : '连接你的服务器，继续与伙伴的对话。';
  $('draft-status').textContent = attachmentQueue().length ? '文字草稿保存在本机 · 附件在当前页面待发送' : $('draft').value ? '草稿已保存在这台设备' : '草稿仅保存在这台设备';
  $('menu-delete').disabled = !state.activeId || state.activeId === primaryConnectionId() || state.sending || state.loading;
  $('menu-delete').hidden = !!state.activeId && state.activeId === primaryConnectionId();
  $('menu-export').disabled = !state.activeId;
  $('menu-interactions').disabled = !state.activeId;
  $('appearance-button').disabled = !state.activeId;
  $('refresh-chat').disabled = !state.authenticated || state.loading || state.sending;
  $('logout-button').hidden = !state.authenticated;
  $('persona-settings').hidden = !state.authenticated;
  applyAppearance();
  renderInteractions();
  renderConversationExport();
  foregroundRecovery.stateChanged();
}
function dateLabel(value, full = false) {
  if (!value) return '';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', full ? { month: 'short', day: 'numeric' } : { hour: '2-digit', minute: '2-digit' }).format(date);
}
function openDeleteConversation(id) {
  const item = state.sessions.find(row => row.session_id === id);
  if (!item) return;
  state.deleteEditing = { sessionId: id, title: item.display_name || '未命名会话' };
  $('delete-title').textContent = state.deleteEditing.title;
  $('delete-error').hidden = true;
  $('delete-error').textContent = '';
  if (!$('delete-dialog').open) $('delete-dialog').showModal();
}
function cancelDeleteConversation() {
  state.deleteEditing = null;
  if ($('delete-dialog').open) $('delete-dialog').close();
}
async function confirmDeleteConversation(event) {
  event.preventDefault();
  const editing = state.deleteEditing;
  if (!editing || state.sending || state.loading) return;
  const button = $('delete-confirm'); button.disabled = true; button.textContent = '正在删除…';
  const fail = text => { $('delete-error').textContent = text; $('delete-error').hidden = false; };
  try {
    await apiClient.json('POST', API.removeSession, { session_id: editing.sessionId });
    state.sessions = state.sessions.filter(row => row.session_id !== editing.sessionId);
    if (state.activeId === editing.sessionId) {
      state.activeId = null; state.messages = []; state.readingScope = '';
      storage.set(pref('last-session.' + encodeURIComponent(state.server + '|' + state.username)), '');
    }
    cancelDeleteConversation(); renderSessions(); renderMessages();
    showNotice('会话已从服务器删除。');
    await loadSessions({ select: !state.activeId });
    if (!state.activeId) renderMessages();
  } catch (error) {
    const status = Number(error && error.status);
    if (status === 404) {
      // Either already gone, or this server build has no delete route yet.
      try { await loadSessions({ select: false }); } catch (_) {}
      const still = state.sessions.some(row => row.session_id === editing.sessionId);
      if (!still) { cancelDeleteConversation(); renderSessions(); showNotice('会话已不存在，列表已更新。'); return; }
      fail('当前服务器尚未提供删除接口。删除需要服务端支持，客户端已就绪；请联系维护者更新服务端后再试。');
    } else fail(errorText(error) + ' 会话未被删除。');
  } finally {
    button.disabled = false; button.textContent = '删除';
  }
}
function renderSessions() {
  const list = $('conversation-list');
  list.replaceChildren();
  if (!state.sessions.length) {
    const empty = document.createElement('p'); empty.className = 'list-empty';
    empty.textContent = state.authenticated ? '尚未连接伙伴，登录后会恢复长期聊天。' : '登录后同步你的会话。';
    list.append(empty);
  }
  for (const item of state.sessions.filter(item=>state.sessionView==='archived' ? item.tls_state&&item.tls_state.archived===true : !(item.tls_state&&item.tls_state.archived===true))) {
    const row = document.createElement('div'); row.className = 'session-row' + (item.session_id === state.activeId ? ' active' : '');
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'session-button' + (item.session_id === state.activeId ? ' active' : '');
    button.disabled = state.sending || state.attaching || state.loading || state.creating;
    button.setAttribute('aria-current', item.session_id === state.activeId ? 'true' : 'false');
    const avatar = document.createElement('span'); avatar.className = 'session-avatar'; avatar.setAttribute('aria-hidden', 'true');
    const stored = sessionAppearance(item.session_id);
    if (stored.avatar) { const image = document.createElement('img'); image.src = stored.avatar; image.alt = ''; avatar.append(image); }
    else avatar.textContent = (stored.displayName || item.display_name || '会').slice(0, 1);
    const main = document.createElement('span'); main.className = 'session-main';
    const name = document.createElement('span'); name.className = 'session-name';
    name.textContent = stored.displayName || item.display_name || '未命名会话';
    const preview = document.createElement('span'); preview.className = 'session-preview';
    preview.textContent = item.session_id === state.activeId ? '正在回看' : '以前的记录，点击回看';
    main.append(name, preview);
    const meta = document.createElement('span'); meta.className = 'session-meta';
    const date = document.createElement('span'); date.className = 'session-date';
    date.textContent = fullDateLabel(item.updated_at || item.created_at) || '';
    meta.append(date);
    button.append(avatar, main, meta);
    button.addEventListener('click', () => { hideMoreMenu(); selectSession(item.session_id); });
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'session-delete';
    remove.textContent = '×'; remove.title = '删除这个会话';
    remove.setAttribute('aria-label', '删除会话 ' + (item.display_name || '未命名会话'));
    remove.disabled = state.sending || state.attaching || state.stickerBusy;
    remove.addEventListener('click', event => { event.stopPropagation(); openDeleteConversation(item.session_id); });
    const archive=document.createElement('button');archive.className='session-archive';archive.textContent=item.tls_state&&item.tls_state.archived?'恢复':'归档';archive.type='button';archive.onclick=()=>window.ChatExperience&&window.ChatExperience.archive(item);    if(item.session_id===primaryConnectionId()){row.classList.add('primary-connection');archive.hidden=true;remove.hidden=true;preview.textContent='与伙伴的长期聊天';}row.append(button,archive, remove); list.append(row);
  }
  renderChrome();
}
function messageSearchScope() { const scope = appearanceScope(); return scope ? scope.key : ''; }
function syncMessageSearchScope() {
  const scope = messageSearchScope();
  if (state.messageSearch.scope !== scope) {
    state.messageSearch = { scope, open: false, query: '', hits: [], index: -1, limited: false };
    $('search-input').value = '';
  }
  return scope;
}
function renderMessageSearchControls() {
  const scope = syncMessageSearchScope(), search = state.messageSearch;
  $('search-button').disabled = !scope || !state.messages.length;
  $('search-panel').hidden = !search.open;
  $('search-prev').disabled = $('search-next').disabled = !search.hits.length;
  const result = !search.query ? '输入关键词，按文字片段查找' : !search.hits.length ? '无匹配文字'
    : (search.index + 1) + ' / ' + search.hits.length + ' 处' + (search.limited ? ' · 仅显示前200处' : '');
  $('search-count').textContent = '仅当前已加载 ' + state.messages.length + ' 条 · ' + result;
}
/* Split a plain part into compact action lines and ordinary prose. Legacy
   【角色互动】 messages stay readable even though new taps never write them. */
function splitActionLines(text) {
  const rows = [];
  for (const line of String(text).split('\n')) {
    const legacy = /^【角色互动】\s*(.+)$/.exec(line);
    const token = /^（([^（）\n]{1,40})）$/.exec(line);
    if (legacy) rows.push({ kind: 'action', label: legacy[1].trim().slice(0, 40) });
    else if (token) rows.push({ kind: 'action', label: token[1] });
    else rows.push({ kind: 'text', text: line });
  }
  return rows;
}
function actionOnly(parts) {
  return parts.length > 0 && parts.every(part => part.type === 'action');
}
/* QQ-style rhythm: a centred time line whenever the conversation pauses, and a
   compact avatar next to a bubble with no per-message speaker label. */
function fullDateLabel(value) {
  if (!value) return '';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  if (!Number.isFinite(date.getTime())) return '';
  const now = new Date();
  const clock = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(date);
  const sameDay = date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay) return clock;
  if (date.getFullYear() === yesterday.getFullYear() && date.getMonth() === yesterday.getMonth()
    && date.getDate() === yesterday.getDate()) return '昨天 ' + clock;
  const day = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' }).format(date);
  return date.getFullYear() === now.getFullYear() ? day + ' ' + clock : day;
}
function messageStamp(message) {
  const date = new Date(typeof message.created_at === 'number' && message.created_at < 1e12
    ? message.created_at * 1000 : message.created_at);
  return Number.isFinite(date.getTime()) ? date.getTime() : 0;
}
function wantsTimeSeparator(previous, message) {
  if (!previous) return true;
  const gap = messageStamp(message) - messageStamp(previous);
  return !(gap >= 0 && gap < 5 * 60 * 1000);
}
function timeSeparator(message) {
  const line = document.createElement('div'); line.className = 'message-time';
  line.textContent = fullDateLabel(message.created_at) || '较早的记录';
  return line;
}
function messageParts(message) {
  return Array.isArray(message.parts) && message.parts.length ? message.parts : [{ type: 'plain', text: message.text || '这条消息暂不支持显示。' }];
}
function updateMessageSearchHits() {
  const search = state.messageSearch, previous = search.hits[search.index];
  const previousKey = previous && previous.key + ':' + previous.part + ':' + previous.start;
  search.hits = []; search.limited = false;
  if (search.open && search.query) {
    outer: for (const message of state.messages) {
      const parts = messageParts(message);
      for (let part = 0; part < parts.length; part++) {
        if (parts[part].type !== 'plain' || typeof parts[part].text !== 'string') continue;
        const text = parts[part].text;
        for (let start = text.indexOf(search.query); start >= 0; start = text.indexOf(search.query, start + search.query.length)) {
          if (search.hits.length >= 200) { search.limited = true; break outer; }
          search.hits.push({ key: String(message.id), part, start, ordinal: search.hits.length });
        }
      }
    }
  }
  const retained = previousKey ? search.hits.findIndex(hit => hit.key + ':' + hit.part + ':' + hit.start === previousKey) : -1;
  search.index = retained >= 0 ? retained : search.hits.length ? 0 : -1;
}
function appendSearchText(element, text, key, part) {
  const search = state.messageSearch, hits = search.hits.filter(hit => hit.key === String(key) && hit.part === part);
  if (!hits.length) { element.textContent = text; return; }
  let offset = 0;
  for (const hit of hits) {
    if (hit.start > offset) element.append(document.createTextNode(text.slice(offset, hit.start)));
    const mark = document.createElement('mark'); mark.textContent = text.slice(hit.start, hit.start + search.query.length);
    mark.dataset.searchHit = String(hit.ordinal); mark.className = hit.ordinal === search.index ? 'search-current' : '';
    element.append(mark); offset = hit.start + search.query.length;
  }
  if (offset < text.length) element.append(document.createTextNode(text.slice(offset)));
}
function captureMessagePosition(container) {
  if (!container || typeof container.getBoundingClientRect !== 'function') return null;
  const top = container.getBoundingClientRect().top;
  const row = [...container.querySelectorAll('.message-row')].find(node => node.getBoundingClientRect().bottom > top);
  return { follow: container.scrollHeight - container.clientHeight - container.scrollTop <= 64,
    top: container.scrollTop, key: row && row.dataset.messageKey,
    offset: row ? row.getBoundingClientRect().top - top : 0 };
}
/* QQ keeps a quiet shortcut back to the newest message once you scroll up. */
function updateJumpLatest() {
  const box = $('messages'), button = $('jump-latest');
  if (!box || !button) return;
  const height = Number(box.scrollHeight), top = Number(box.scrollTop), view = Number(box.clientHeight);
  // Only touch the DOM when the answer changes: a redundant hidden toggle
  // forces a layout pass (and in the synthetic browser, a scroll clamp).
  const hide = !(state.messages.length > 0 && Number.isFinite(height)
    && Number.isFinite(top) && Number.isFinite(view) && height - top - view > 240);
  if (button.hidden !== hide) button.hidden = hide;
}
function jumpToLatest() {
  const box = $('messages');
  if (!box) return;
  state.readingScope = '';
  state.liveFollowScope = messageSearchScope();
  setMessageScroll(box, box.scrollHeight);
  updateJumpLatest();
}
function setMessageScroll(container, top) {
  if (!container || !container.style || typeof container.scrollTo !== 'function') { if (container) container.scrollTop = top; return; }
  const prior = container.style.scrollBehavior; container.style.scrollBehavior = 'auto';
  container.scrollTop = Math.max(0, top); container.style.scrollBehavior = prior;
}
function jumpMessageSearch() {
  const search = state.messageSearch, container = $('messages');
  for (const mark of container.querySelectorAll('mark[data-search-hit]')) mark.classList.toggle('search-current', Number(mark.dataset.searchHit) === search.index);
  const mark = [...container.querySelectorAll('mark[data-search-hit]')].find(node => Number(node.dataset.searchHit) === search.index);
  if (mark) setMessageScroll(container, container.scrollTop + mark.getBoundingClientRect().top
    - container.getBoundingClientRect().top - container.clientHeight / 2 + mark.getBoundingClientRect().height / 2);
  renderMessageSearchControls();
}
function openMessageSearch() {
  if (!syncMessageSearchScope() || !state.messages.length) return;
  state.messageSearch.open = true; renderMessageSearchControls(); $('search-input').focus();
}
function closeMessageSearch() {
  if (!state.messageSearch.open) return false;
  state.messageSearch.open = false; state.messageSearch.query = ''; state.messageSearch.hits = []; state.messageSearch.index = -1;
  $('search-input').value = ''; renderMessages(); return true;
}
function changeMessageSearch() {
  if (!state.messageSearch.open || !syncMessageSearchScope()) return;
  state.messageSearch.query = $('search-input').value.slice(0, 200); $('search-input').value = state.messageSearch.query;
  state.messageSearch.hits = []; state.messageSearch.index = -1; renderMessages({ jumpToSearch: true });
}
function moveMessageSearch(delta) {
  if (!state.messageSearch.open || !state.messageSearch.hits.length) return;
  state.messageSearch.index = (state.messageSearch.index + delta + state.messageSearch.hits.length) % state.messageSearch.hits.length;
  jumpMessageSearch();
}
function renderMessages({ jumpToSearch = false, forceLatest = false } = {}) {
  const container = $('messages');
  const scope = syncMessageSearchScope(), ticket = ++state.messageRenderSerial;
  const position = state.readingScope === scope ? captureMessagePosition(container) : null;
  if(forceLatest)state.liveFollowScope=scope;
  state.readingScope = scope; updateMessageSearchHits();
  const appearance = currentAppearance();
  state.previewElements = [];
  for (const node of [...container.querySelectorAll('.message-row, .message-time')]) node.remove();
  const spacer = $('messages-spacer');
  if (spacer) spacer.hidden = state.messages.length === 0;
  $('empty-state').hidden = !!state.messages.length;
  let previous = null;
  for (const message of state.messages) {
    if (wantsTimeSeparator(previous, message)) container.append(timeSeparator(message));
    const continued = !!previous && previous.role === message.role
      && (previous.notice?.kind || 'chat') === (message.notice?.kind || 'chat')
      && (previous.notice?.source || '') === (message.notice?.source || '')
      && messageStamp(message) - messageStamp(previous) < 5 * 60 * 1000
      && messageStamp(message) >= messageStamp(previous);
    previous = message;
    const row = document.createElement('article');
    row.className = 'message-row ' + message.role + (continued ? ' continued' : '')
      + (message.delivery === 'unknown' ? ' failed' : '');
    if (message.notice && message.delivery === 'confirmed') row.classList.add('event-' + message.notice.kind);
    row.dataset.messageKey = String(message.id);
    const avatar = document.createElement('div'); avatar.className = 'message-avatar'; avatar.setAttribute('aria-hidden', 'true');
    if (message.role === 'assistant') { const logo = document.createElement('img'); logo.src = appearance.avatar || 'logo.svg'; logo.alt = ''; avatar.append(logo); }
    else avatar.textContent = '你';
    const body = document.createElement('div'); body.className = 'message-body';
    if (message.notice && message.delivery === 'confirmed') {
      const source = document.createElement('div'); source.className = 'message-event-label';
      const title = { proactive: '主动消息', reminder: '日程提醒', event: 'TLS 消息' }[message.notice.kind];
      source.append(document.createTextNode(title + (message.notice.source === 'qq_confirmed_proactive' ? ' · QQ同步' : '')));
      const saved = document.createElement('span'); saved.className = 'message-event-state';
      saved.textContent = '已保存至会话'; source.append(saved); body.append(source);
    }
    const parts = messageParts(message);
    let bubble=null;
    for (const [partIndex, part] of parts.entries()) {
      if(['action','sticker'].includes(part.type)&&window.ChatComposer){
        bubble=null;const expression=document.createElement('div');expression.className='message-expression '+(part.type==='sticker'?'expression-sticker':'expression-action '+(part.source==='assistant_narrative'?'expression-narrative-action':'expression-user-action'));expression.append(window.ChatComposer.renderPart(part));body.append(expression);continue;
      }
      if(!bubble){bubble=document.createElement('div');bubble.className='message-bubble';body.append(bubble);}
      if (part.type==='reference' && window.ChatComposer) { bubble.classList.add('has-reference');bubble.append(window.ChatComposer.renderPart(part)); continue; }
      if (part.type !== 'plain') { bubble.classList.add('has-media');bubble.append(renderMediaPart(part, message, state.activeId)); continue; }
      bubble.classList.add('has-text');
      const text = document.createElement('span'); text.className = 'message-text';
      appendSearchText(text, part.text, message.id, partIndex);
      bubble.append(text);
    }
    if (message.delivery && message.delivery !== 'confirmed') {
      const delivery = document.createElement('div'); delivery.className = 'message-delivery';
      const detail = document.createElement('span');
      detail.textContent = message.delivery === 'pending' ? '正在提交，尚未确认保存' : message.delivery === 'unknown' ? '发送状态待确认，请先同步记录' : '正在生成，尚未确认完整保存';
      delivery.append(detail);
      if (message.delivery === 'unknown') {
        const check = document.createElement('button'); check.textContent = '同步记录'; check.addEventListener('click', () => refreshCurrent());
        const retry = document.createElement('button'); retry.textContent = '重试准备';
        retry.addEventListener('click', async () => {
          if (state.sending) return;
          const ok = await refreshCurrent();
          if (!ok || state.remoteRunning) return;
          $('draft').value = message.text; saveDraft(); resizeDraft(); $('draft').focus();
          showNotice('已重新读取记录。请先确认上条是否已经保存，再决定是否再次发送；应用不会自动重发。');
        });
        delivery.append(check, retry);
      }
      body.append(delivery);
    }
    row.append(avatar, body); container.append(row);
  }
  renderAttachments(); renderChrome(); updateJumpLatest();
  requestAnimationFrame(() => {
    if (ticket !== state.messageRenderSerial || scope !== messageSearchScope()) return;
    if (jumpToSearch && state.messageSearch.hits.length) { jumpMessageSearch(); return; }
    if (position && !forceLatest && state.liveFollowScope!==scope && (!position.follow || (state.messageSearch.open && state.messageSearch.query))) {
      const row = [...container.querySelectorAll('.message-row')].find(node => node.dataset.messageKey === position.key);
      if (row) setMessageScroll(container, container.scrollTop + row.getBoundingClientRect().top - container.getBoundingClientRect().top - position.offset);
      else { setMessageScroll(container, position.top); if (position.key && $('notice').hidden) showNotice('原阅读位置已不在本次加载的记录中，已保留附近位置。'); }
    } else setMessageScroll(container, container.scrollHeight);
  });
}
function renderStickers() {
  const panel = $('sticker-grid'); if (!panel) return;
  panel.replaceChildren();
  for (const name of STICKERS) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'sticker-item';
    button.dataset.sticker = name; button.title = '发送这个表情';
    const image = document.createElement('img'); image.src = 'stickers/' + name; image.alt = ''; image.loading = 'lazy';
    button.append(image);
    button.addEventListener('click', () => sendSticker(name));
    if (state.stickerSending === name) { button.classList.add('sending'); button.disabled = true; }
    panel.append(button);
  }
}
function stickerPanel(open) {
  const panel = $('sticker-panel'); if (!panel) return;
  const log = $('messages');
  const follow = log && log.scrollHeight - log.clientHeight - log.scrollTop <= 64;
  panel.hidden = !open;
  if (document.body && document.body.classList) document.body.classList.toggle('sticker-open', !!open);
  $('sticker-button').setAttribute('aria-expanded', String(!!open));
  syncComposerMetrics();
  if (follow) log.scrollTop = log.scrollHeight;
  updateJumpLatest();
}
async function sendSticker(name) {
  if (!STICKERS.includes(name) || state.stickerBusy || state.sending || state.loading || state.creating
      || state.attaching || state.appearanceBusy || state.exportBusy || state.remoteRunning || invalidAttachments()) return;
  if (!state.authenticated) { openSettings(); return; }
  if (attachmentQueue().length >= 4) { showNotice('请先处理当前待发送附件，再发送表情。'); return; }
  const scope = { server: state.server, username: state.username, sessionId: state.activeId };
  const current = () => messageSendCurrent(scope);
  // The original send lock covers creation, upload and send; a sticker is an
  // attachment-only message, not another concurrent sending pipeline.
  state.sending = true; state.stickerBusy = true; state.stickerSending = name;
  renderStickers(); renderChrome();
  let item;
  try {
    if (!scope.sessionId) scope.sessionId = await connectLongTerm({ accept: current });
    if (!scope.sessionId || !current()) return;
    item = { localId: 'file-' + Date.now() + '-' + (++state.requestSerial), session_id: scope.sessionId,
      filename: name, display_name: name, type: 'image', status: 'choosing' };
    state.attachmentQueues.set(scope.sessionId, [...attachmentQueue(scope.sessionId), item]); renderAttachments();
    const data = responseData(await nativeAsync('chooseSticker', [name, scope.sessionId], 120000));
    if (!current()) return;
    if (!data || typeof data.attachment_id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(data.attachment_id)) {
      throw new Error('表情上传没有返回有效附件。');
    }
    if (data.session_id !== scope.sessionId || data.type !== 'image' || !attachmentFilename(data))
      throw new Error('服务器未确认当前会话的表情附件。');
    Object.assign(item, { attachment_id: data.attachment_id, filename: data.filename,
      display_name: name, mime_type: data.mime_type || 'image/png', size: data.size, status: 'ready' });
    await sendMessage({ preventDefault() {} }, { kind: 'sticker', scope, files: [item] });
  } catch (error) {
    if (!current()) return;
    if (item && attachmentQueue(scope.sessionId).includes(item)) item.status = 'unknown';
    showNotice(errorText(error) + ' 表情上传结果尚未确认，未自动重新上传或发送。', { label: '同步记录', run: refreshCurrent }, true);
  } finally {
    // The sheet stays open so several stickers can be sent in a row.
    state.sending = false; state.stickerBusy = false; state.stickerSending = '';
    renderAttachments(); renderStickers(); renderChrome();
  }
}
function messageSendCurrent(scope) {
  return !!scope && state.authenticated && state.server === scope.server
    && state.username === scope.username && state.activeId === scope.sessionId;
}
function attachmentFilename(part) {
  const name = typeof part.stored_filename === 'string' && part.stored_filename ? part.stored_filename : part.filename;
  return typeof name === 'string' && name && name.length <= 255 && !/[\\/\u0000-\u001f]/.test(name) && !['.', '..'].includes(name) ? name : '';
}
function mediaPart(part) {
  const exportCandidate = typeof part.display_name === 'string' ? part.display_name
    : typeof part.stored_filename === 'string' && part.stored_filename && part.filename !== part.stored_filename ? part.filename : '';
  return { type: part.type, attachment_id: typeof part.attachment_id === 'string' ? part.attachment_id : '',
    filename: typeof part.filename === 'string' ? part.filename : '', stored_filename: typeof part.stored_filename === 'string' ? part.stored_filename : '',
    display_name: typeof part.display_name === 'string' ? part.display_name : typeof part.filename === 'string' ? part.filename : '',
    mime_type: typeof part.mime_type === 'string' ? part.mime_type : '', source: part.source || 'history',
    export_name: safeExportMediaName(exportCandidate, part) };
}
function contentParts(content) {
  if (!content || typeof content !== 'object' || !Array.isArray(content.message)) return [];
  const result = [];
  for (const part of content.message) {
    if (!part || typeof part !== 'object') continue;
    if (part.type === 'plain' && typeof part.text === 'string') result.push({ type: 'plain', text: part.text });
    else if (['image', 'file', 'record', 'video'].includes(part.type)) result.push(mediaPart(part));
  }
  return result;
}
function rememberImage(key, body) {
  state.mediaCache.delete(key); state.mediaCache.set(key, body);
  while (state.mediaCache.size > 3) state.mediaCache.delete(state.mediaCache.keys().next().value);
}
function showPreview(img, button, body) {
  const url = body && body.data_url, mime = body && body.mime_type;
  if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(mime)
      || typeof url !== 'string' || url.length > 12 * 1024 * 1024
      || !url.startsWith('data:' + mime + ';base64,') || !/^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(url)) throw new Error('图片预览格式暂不支持，可尝试用系统打开。');
  // Decode while hidden, then change layout using the existing reading anchor.
  // A late image keeps latest-follow, while a reader stays at their current line.
  img.onload = () => {
    img.onload = null;
    if (!img.isConnected) return;
    const reveal = () => {
      while (state.previewElements.length >= 3) {
        const previous = state.previewElements.shift(); previous.img.removeAttribute('src'); previous.img.hidden = true;
        previous.button.hidden = false; previous.button.disabled = false; previous.button.textContent = '查看图片';
      }
      img.hidden = false; button.hidden = true;
      state.previewElements.push({ img, button });
    };
    if (window.ChatComposer) window.ChatComposer.withReading(reveal); else reveal();
  };
  img.loading = 'eager'; // A hidden lazy image would never reach its load callback.
  img.src = url;
}
function renderMediaPart(part, message, sessionId) {
  const card = document.createElement('div'); card.className = 'message-media';
  const filename = attachmentFilename(part), name = part.display_name || part.filename || (part.type === 'image' ? '图片' : '文件');
  const available = message.delivery === 'confirmed' && part.source !== 'stream' && !!filename;
  const error = document.createElement('p'); error.className = 'media-error'; error.hidden = true;
  const account = state.server + '|' + state.username;
  async function open() {
    if (!available) return;
    try { await nativeAsync('openAttachment', [sessionId, filename]); }
    catch (failure) { error.textContent = errorText(failure); error.hidden = false; }
  }
  if (part.type === 'image') {
    const image = document.createElement('img'); image.className = 'message-image'; image.alt = name; image.hidden = true; image.loading = 'lazy'; image.addEventListener('click', open);
    const button = document.createElement('button'); button.type = 'button'; button.className = 'image-button';
    button.textContent = available ? '▧  查看图片' : filename ? '同步保存记录后查看图片' : '图片缺少可下载引用'; button.disabled = !available;
    const key = account + '|' + sessionId + '|' + filename;
    image.addEventListener('error', () => { image.hidden = true; button.hidden = false; button.disabled = false; button.textContent = '图片未能显示，点击重试'; });
    button.addEventListener('click', async () => {
      button.disabled = true; button.textContent = '正在读取图片…'; error.hidden = true;
      try {
        const body = state.mediaCache.get(key) || responseData(await nativeAsync('loadAttachment', [sessionId, filename]));
        if (!state.authenticated || account !== state.server + '|' + state.username) throw new Error('账户已切换，请重新打开记录。');
        showPreview(image, button, body); rememberImage(key, body);
      } catch (failure) { button.disabled = false; button.textContent = '重新读取图片'; error.textContent = errorText(failure); error.hidden = false; }
    });
    card.append(image, button);
    const caption = document.createElement('div'); caption.className = 'media-caption'; caption.textContent = '点击图片可用系统打开原文件'; card.append(caption);
    if (available && state.mediaCache.has(key)) {
      try { showPreview(image, button, state.mediaCache.get(key)); } catch (_) { state.mediaCache.delete(key); }
    }
  } else {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'file-button'; button.disabled = !available;
    const icon = document.createElement('span'); icon.className = 'file-icon'; icon.textContent = part.type === 'record' ? '♫' : part.type === 'video' ? '▷' : '▤';
    const info = document.createElement('div'); info.className = 'file-info';
    const label = document.createElement('span'); label.className = 'file-name'; label.textContent = name;
    const hint = document.createElement('span'); hint.className = 'file-hint'; hint.textContent = available ? '用系统应用打开' : filename ? '同步保存记录后打开' : '缺少可下载引用';
    info.append(label, hint); button.append(icon, info); button.addEventListener('click', open); card.append(button);
  }
  card.append(error); return card;
}
function contentText(content) {
  return contentParts(content).filter(part => part.type === 'plain').map(part => part.text).join('\n');
}
function savedMessageNotice(content) {
  if (!content || content.type !== 'bot') return null;
  const refs = content.refs;
  if (!refs || !['qq_confirmed_proactive', 'tls_chat_direct'].includes(refs.source)) return null;
  const metadata = refs.tls_notice;
  const kind = metadata && metadata.schema === 1 && ['proactive', 'reminder'].includes(metadata.kind) ? metadata.kind : 'event';
  return { kind, source: refs.source };
}
function normalizeHistory(rows) {
  const seen = new Set(); const result = [];
  for (const [index, row] of rows.entries()) {
    if (!row || typeof row !== 'object' || !row.content || !['user', 'bot'].includes(row.content.type)) continue;
    const key = row.id != null ? String(row.id) + '|' + String(row.llm_checkpoint_id || '') : 'row-' + index;
    if (seen.has(key)) continue; seen.add(key);
    const typed = row.tls_parts || row.content.tls_parts;
    const parts = window.ChatComposer && Array.isArray(typed) ? window.ChatComposer.normalizeParts(typed) : contentParts(row.content);
    const notice = savedMessageNotice(row.content);
    if (row.content.type === 'bot' && !parts.length && !notice) continue;
    result.push({ id: key, serverId: row.id, checkpoint: row.llm_checkpoint_id,
      clientMessageId: row.client_message_id || row.content.client_message_id || null,
      role: row.content.type === 'user' ? 'user' : 'assistant', text: parts.filter(part => part.type === 'plain').map(part => part.text).join('\n'), parts,
      origin: row.content.refs && ['qq_confirmed_proactive','tls_chat_direct'].includes(row.content.refs.source) ? row.content.refs.source : null,
      notice,
      created_at: row.created_at, delivery: 'confirmed' });
  }
  return result;
}
async function loadSessions({ select = true, accept = () => true, onNativeComplete } = {}) {
  const rows = await apiClient.sessions({ onNativeComplete });
  if (!accept()) return false;
  if (!Array.isArray(rows)) throw new Error('会话列表格式暂不兼容，请检查服务器版本。');
  state.sessions = rows.filter(row => row && typeof row.session_id === 'string' && row.session_id);
  renderSessions();
  if (select && !state.activeId) {
    await connectLongTerm({accept});
    if(accept()&&state.primaryId)await selectSession(state.primaryId);
  }
  return true;
}
async function loadPersonas() {
  const rows = await apiClient.personas();
  if (!Array.isArray(rows)) throw new Error('角色列表格式暂不兼容。');
  state.personas = rows.filter(item => item && typeof item.persona_id === 'string' && item.persona_id && typeof item.display_name === 'string');
  const saved = storage.get(pref('persona.' + encodeURIComponent(state.server + '|' + state.username)));
  const solePersona = state.personas.length === 1 ? state.personas[0].persona_id : '';
  state.newPersona = state.personas.some(item => item.persona_id === saved) ? saved : solePersona;
  const select = $('persona'); select.replaceChildren();
  const empty = document.createElement('option'); empty.value = ''; empty.textContent = state.personas.length ? '请选择服务器中的角色' : '服务器尚无可用角色'; select.append(empty);
  for (const persona of state.personas) { const option = document.createElement('option'); option.value = persona.persona_id; option.textContent = persona.display_name; select.append(option); }
  select.value = state.newPersona;
}
function normalizeConfiguredPersona(value) {
  const unknown = { status: 'unavailable', configuredId: null, displayName: null };
  if (!value || typeof value !== 'object' || Array.isArray(value)) return unknown;
  if (value.status === 'configured') {
    if (typeof value.configured_id !== 'string' || !value.configured_id.trim()
        || typeof value.display_name !== 'string' || !value.display_name.trim()
        || value.configured_id !== value.display_name) return unknown;
    return { status: 'configured', configuredId: value.configured_id, displayName: value.display_name };
  }
  if (['unconfigured', 'missing', 'unavailable'].includes(value.status)
      && value.configured_id === null && value.display_name === null) return { status: value.status, configuredId: null, displayName: null };
  return unknown;
}
function configuredPersonaForCurrent() {
  return state.sessionPersonaConfig && state.sessionPersonaConfig.sessionId === state.activeId ? state.sessionPersonaConfig : null;
}
async function loadHistory(id, { accept = () => true, reconcileAttachments = true, preserveUnconfirmed = false, preserveReading = false, onNativeComplete } = {}) {
  if (!state.sessions.some(item => item.session_id === id)) throw new Error('请从当前账户的会话列表打开对话。');
  const serial = ++state.historySerial;
  if (state.activeId === id) state.sessionPersonaConfig = { sessionId: id, ...normalizeConfiguredPersona(null) };
  const result = await apiClient.history(id, { onNativeComplete });
  if (serial !== state.historySerial || state.activeId !== id || !accept()) return false;
  if (!result || !Array.isArray(result.history)) throw new Error('聊天记录格式暂不兼容，请检查服务器版本。');
  state.sessionPersonaConfig = { sessionId: id, ...normalizeConfiguredPersona(result.persona) };
  const sessionItem=state.sessions.find(value=>value.session_id===id);if(sessionItem&&result.tls_state)sessionItem.tls_state=result.tls_state;
  const previousReplies=new Set(state.messages.filter(value=>value.role==='assistant'&&value.serverId!=null).map(value=>String(value.serverId)));
  const hadHistory=state.messages.length>0;
  const actualMessages = normalizeHistory(result.history);
  if (preserveUnconfirmed) {
    // An automatic read is not an ACK for a local unknown send. Only a stable
    // server/client ID or checkpoint can replace that local card; never text.
    const unresolved = state.messages.filter(row => ['pending','unknown','unconfirmed'].includes(row.delivery)
      && !actualMessages.some(saved => saved.role === row.role && (
        row.serverId != null && String(row.serverId) === String(saved.serverId)
        || row.clientMessageId && row.clientMessageId === saved.clientMessageId
        || row.checkpoint && row.checkpoint === saved.checkpoint)));
    actualMessages.push(...unresolved);
  }
  state.messages = actualMessages;
  const receivedReply=hadHistory&&state.messages.some(value=>value.role==='assistant'&&value.serverId!=null&&!previousReplies.has(String(value.serverId)));
  const referenced = new Set(result.history.filter(row => row && row.content && row.content.type === 'user')
    .flatMap(row => contentParts(row.content)).map(part => part.attachment_id).filter(Boolean));
  if (reconcileAttachments) state.attachmentQueues.set(id, attachmentQueue(id).filter(item => !referenced.has(item.attachment_id)));
  state.remoteRunning = result.is_running === true;
  if(!state.sending)state.replyPhase=state.remoteRunning?'processing':'idle';
  if (state.remoteRunning && Array.isArray(result.active_runs)) {
    for (const run of result.active_runs) {
      const text = contentText(run.content);
      const parts = contentParts(run.content);
      if ((text || parts.length) && !state.messages.some(item => item.role === 'assistant' && item.checkpoint === run.llm_checkpoint_id)) {
        state.messages.push({ id: 'run-' + run.run_id, role: 'assistant', text, parts, delivery: 'unconfirmed' });
      }
    }
  }
  if (preserveReading && captureMessagePosition($('messages'))?.follow === false) state.liveFollowScope = '';
  renderMessages({forceLatest:!preserveReading&&receivedReply&&!state.messageSearch.open});
  if (recoveryForeground() && window.ChatComposer && typeof window.ChatComposer.historyReceived === 'function') window.ChatComposer.historyReceived(id);
  return true;
}
async function selectSession(id) {
  if (state.sending || state.attaching) { showNotice('本轮消息或文件仍在处理，完成后再切换会话。'); return; }
  foregroundRecovery.cancel('scope_changed', true);
  cancelAppearance(); cancelInteractions(); saveDraft(); state.activeId = id; state.sessionPersonaConfig = null; state.messages = []; state.remoteRunning = false; state.replyPhase='idle';
  storage.set(pref('last-session.' + encodeURIComponent(state.server + '|' + state.username)), id);
  restoreDraft(); sidebar(false); renderSessions(); renderMessages();
  state.loading = true; renderChrome();
  try { await loadHistory(id); hideNotice(); }
  catch (error) { showNotice(errorText(error), { label: '重试同步', run: refreshCurrent }, true); }
  finally { state.loading = false; renderChrome(); }
}
async function refreshCurrent() {
  if (!state.authenticated) { openSettings(); return false; }
  if (state.sending) { showNotice('本轮回复仍在接收，完成后再同步记录。'); return false; }
  if (state.loading || !foregroundRecovery.manualIntent()) { showNotice('上一次读取尚未结束，请稍候再同步；应用不会叠加自动请求。'); return false; }
  state.loading = true; renderChrome();
  try { if (state.activeId) await loadHistory(state.activeId); else await loadSessions(); hideNotice(); return true; }
  catch (error) { showNotice(errorText(error), { label: '重试同步', run: refreshCurrent }, true); return false; }
  finally { state.loading = false; renderChrome(); }
}
function primaryConnectionId() {return state.primaryAccount===state.server+'|'+state.username?state.primaryId:null;}
async function connectLongTerm({ accept = () => true } = {}) {
  const owner=state.server+'|'+state.username;
  const preferred=primaryConnectionId()||storage.get(pref('last-session.'+encodeURIComponent(owner)));
  const persona=state.personas.find(item=>item.persona_id===state.newPersona);
  const session=await apiClient.connectBot({...(persona?{persona_id:persona.persona_id}:{}),...(preferred?{preferred_session_id:preferred}:{})});
  if(!accept()||owner!==state.server+'|'+state.username)return null;
  if(!session||typeof session.session_id!=='string'||session.primary!==true)throw new Error('服务器尚未确认长期聊天连接，请同步记录，不会自动新建其他对话。');
  state.primaryId=session.session_id;state.primaryAccount=owner;
  const existing=state.sessions.find(item=>item.session_id===session.session_id);
  if(existing)Object.assign(existing,session);else state.sessions.unshift(session);
  if(state.activeId!==session.session_id){
    saveDraft();
    state.activeId=session.session_id;state.sessionPersonaConfig=null;state.messages=[];state.remoteRunning=false;
    restoreDraft();
  }
  if(session.persona_id)state.sessionPersonas.set(session.session_id,session.persona_id);
  storage.set(pref('last-session.'+encodeURIComponent(owner)),session.session_id);
  renderSessions();renderMessages();sidebar(false);
  return session.session_id;
}
async function returnToBot() {
  if(!state.authenticated){openSettings();return;}
  if(state.sending||state.loading||state.creating||state.attaching)return;
  foregroundRecovery.cancel('long_term_connection',true);saveDraft();state.creating=true;renderChrome();
  try{const id=primaryConnectionId()||await connectLongTerm();if(id)await selectSession(id);restoreDraft();hideNotice();}
  catch(error){showNotice(errorText(error)+' 请先同步连接状态，不会重复建立新聊天。',null,true);}
  finally{state.creating=false;renderChrome();}
}
function parseStream(body) {
  if (typeof body !== 'string') throw new Error('服务器未返回可识别的消息流，请先同步记录。');
  const result = { text: '', parts: [], userParts: null, assistantParts: null, userId: null, messageId: null, ended: false, error: '', phase: '' };
  let count = 0; let assistantPartsMessageId = null;
  for (const frame of body.replace(/\r\n/g, '\n').split('\n\n')) {
    const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
    if (!data) continue;
    if (data === '[DONE]') { result.ended = true; continue; }
    let event; try { event = JSON.parse(data); } catch (_) { continue; }
    count++;
    if(event.type==='tls_generation_state'&&event.data&&['sdk_run_accepted','model_reasoning_received','model_output_received','sdk_error','sdk_stream_finished'].includes(event.data.source)&&['queued','generating','streaming','completed','failed'].includes(event.data.phase))result.phase=event.data.phase;
    if (event.type === 'tls_parts' && event.data && Array.isArray(event.data.parts) && window.ChatComposer) {
      const typed = window.ChatComposer.normalizeParts(event.data.parts);
      if (event.data.role === 'user') result.userParts = typed;
      else if (typed.length) {
        result.assistantParts = typed;
        assistantPartsMessageId = event.data.message_id != null ? event.data.message_id : result.messageId;
      }
    }
    if (event.type === 'plain' && typeof event.data === 'string' && !['reasoning', 'tool_call', 'tool_call_result'].includes(event.chain_type)) {
      const last = result.parts[result.parts.length - 1];
      if (event.streaming !== false && last && last.type === 'plain') last.text += event.data;
      else if (event.streaming === false && !result.parts.some(part => part.type !== 'plain')) result.parts = [{ type: 'plain', text: event.data }];
      else result.parts.push({ type: 'plain', text: event.data });
    }
    if (event.type === 'complete' && typeof event.data === 'string') {
      if (!result.parts.some(part => part.type !== 'plain')) result.parts = event.data ? [{ type: 'plain', text: event.data }] : [];
      else if (event.data && !result.parts.some(part => part.type === 'plain')) result.parts.push({ type: 'plain', text: event.data });
    }
    if (['image', 'file', 'record', 'video'].includes(event.type) && typeof event.data === 'string') {
      const prefix = { image: '[IMAGE]', file: '[FILE]', record: '[RECORD]', video: '[VIDEO]' }[event.type];
      const token = event.data.startsWith(prefix) ? event.data.slice(prefix.length) : event.data;
      const separator = ['file', 'video'].includes(event.type) ? token.indexOf('|') : -1;
      const stored = separator >= 0 ? token.slice(0, separator) : token;
      const display = separator >= 0 ? token.slice(separator + 1) : token;
      result.parts.push(mediaPart({ type: event.type, filename: display, stored_filename: stored, source: 'stream' }));
    }
    if (event.type === 'attachment_saved' && event.data && typeof event.data.id === 'string') {
      const part = [...result.parts].reverse().find(value => value.type === event.data.type && !value.attachment_id);
      if (part) part.attachment_id = event.data.id;
    }
    if (event.type === 'user_message_saved' && event.data) result.userId = event.data.id;
    if (event.type === 'message_saved' && event.data) result.messageId = event.data.id;
    if (event.type === 'end') {result.ended = true;if(!result.error)result.phase='completed';}
    if (event.type === 'error') {result.error = typeof event.data === 'string' ? event.data : event.data && event.data.message || '服务器生成过程中出现错误。';result.phase='failed';}
  }
  if (!count) throw new Error('未收到有效回复。请先同步记录确认发送状态。');
  if (result.assistantParts) {
    result.parts = result.assistantParts;
    if (assistantPartsMessageId != null) result.messageId = assistantPartsMessageId;
  }
  result.text = result.parts.filter(part => part.type === 'plain').map(part => part.text).join('');
  return result;
}
async function sendMessage(event, prepared = null) {
  event.preventDefault();
  if(primaryConnectionId()&&state.activeId&&state.activeId!==primaryConnectionId()){showNotice('这里是以前的记录，请回到伙伴继续长期聊天。');return;}
  const legacySticker = prepared && prepared.kind === 'sticker';
  const direct = prepared && prepared.kind === 'composition';
  if (prepared && !legacySticker && !direct) return;
  const consume = !prepared || prepared.consume !== false && !legacySticker;
  const draftText = $('draft').value;
  const text = prepared ? prepared.text || '' : draftText.trim();
  const files = prepared ? prepared.files || [] : [...readyAttachments()];
  let composition;
  try { composition = prepared ? { parts: prepared.parts || null, actions: [], stickers: [] }
      : window.ChatComposer ? window.ChatComposer.snapshot(text) : { parts: null, actions: [], stickers: [] }; }
  catch (failure) { showNotice(errorText(failure), null, true); return; }
  if ((!text && !files.length && !(composition.parts && composition.parts.length)) || (!legacySticker && state.sending)
      || state.loading || state.attaching || state.remoteRunning || (!prepared && invalidAttachments())) return;
  if (!state.authenticated) { openSettings(); return; }
  const scope = prepared ? prepared.scope : { server: state.server, username: state.username, sessionId: state.activeId };
  const current = () => messageSendCurrent(scope);
  if (legacySticker && (!state.sending || !state.stickerBusy || !current())) return;
  if (direct && !current()) return;
  state.sending = true; state.replyPhase='submitting'; renderChrome();
  const clientMessageId = 'tc-' + (window.crypto && typeof window.crypto.randomUUID === 'function'
    ? window.crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));
  let sentSession = scope.sessionId; let userMessage;
  try {
    if (!sentSession) { sentSession = await connectLongTerm({ accept: current }); scope.sessionId = sentSession; }
    if (!sentSession || !current()) return;
    if (consume) storage.set(draftKey(sentSession), draftText);
    state.liveFollowScope=messageSearchScope();
    for (const file of files) file.status = 'sending';
    userMessage = { id: 'local-' + Date.now() + '-' + (++state.requestSerial), role: 'user', text,
      clientMessageId,
      parts: [...(composition.parts && window.ChatComposer ? window.ChatComposer.normalizeParts(composition.parts) : text ? [{ type: 'plain', text }] : []), ...files.filter(file=>!(composition.parts||[]).some(part=>part.attachment_id===file.attachment_id)).map(file => mediaPart({ ...file, source: 'upload' }))],
      created_at: new Date().toISOString(), delivery: 'pending' };
    state.messages.push(userMessage);
    if (consume) {
      $('draft').value = ''; resizeDraft();
      if (window.ChatComposer) window.ChatComposer.clear(); else state.pendingActions = [];
      renderPendingActions(); hideNotice();
    }
    renderMessages({forceLatest:true});
    jumpToLatest();
    const stream = parseStream(await apiClient.send(sentSession, text, files, composition.parts, clientMessageId));
    if (!current()) return;
    state.replyPhase=stream.error?'failed':'completed';
    userMessage.delivery = stream.userId != null ? 'confirmed' : 'unknown';
    if (stream.userParts) userMessage.parts = stream.userParts;
    if (stream.userId != null) {
      const sentIds = new Set(files.map(file => file.attachment_id));
      state.attachmentQueues.set(sentSession, attachmentQueue(sentSession).filter(file => !sentIds.has(file.attachment_id)));
    } else for (const file of files) file.status = 'send-unknown';
    if (stream.parts.length) state.messages.push({ id: stream.messageId || 'reply-' + Date.now(), role: 'assistant', text: stream.text, parts: stream.parts, delivery: stream.messageId != null ? 'confirmed' : 'unconfirmed' });
    renderMessages();
    if (stream.error) {const failure=new Error(stream.error);failure.generationFailed=true;throw failure;}
    if (!stream.ended || stream.messageId == null) showNotice('回复已返回，正在核对服务器保存记录。');
    await loadHistory(sentSession, { accept: current });
    if (!current()) return;
    if (consume && !$('draft').value) storage.set(draftKey(sentSession), '');
    await loadSessions({ select: false, accept: current });
  } catch (error) {
    if (!current()) return;
    state.replyPhase=error&&(error.generationFailed||Number.isInteger(error.status)&&error.status>=400)?'failed':'unknown';
    for (const file of files) if (attachmentQueue(sentSession).includes(file)) file.status = 'send-unknown';
    if (userMessage && userMessage.delivery !== 'confirmed') userMessage.delivery = 'unknown';
    if (consume && (!userMessage || userMessage.delivery !== 'confirmed') && !$('draft').value) {
      $('draft').value = draftText; saveDraft(); resizeDraft();
      if (window.ChatComposer) window.ChatComposer.recover(composition);
      renderPendingActions();
    }
    renderMessages();
    showNotice(errorText(error) + (userMessage && userMessage.delivery === 'confirmed' ? ' 消息已保存，可同步记录查看回复。' : ' 先同步记录核对结果，应用不会自动重发。'), { label: '同步记录', run: refreshCurrent }, true);
  } finally { if (!legacySticker) state.sending = false; renderMessages(); renderSessions(); renderChrome(); }
}
async function refreshSessions() {
  if (!state.authenticated) { openSettings(); return; }
  if (state.loading || !foregroundRecovery.manualIntent()) { showNotice('上一次读取尚未结束，请稍候再同步。'); return; }
  state.loading = true; renderChrome();
  try { await loadSessions(); hideNotice(); }
  catch (error) { showNotice(errorText(error), { label: '重试同步', run: refreshSessions }, true); }
  finally { state.loading = false; renderChrome(); }
}
function openSettings() {
  sidebar(false); $('server').value = state.server; $('username').value = state.username;
  $('password').value = ''; $('login-error').hidden = true;
  if (!$('settings-dialog').open) $('settings-dialog').showModal();
}
async function login(event) {
  event.preventDefault();
  if (state.sending || state.attaching) { $('login-error').textContent = '请等待本轮消息或文件处理结束后再切换账户。'; $('login-error').hidden = false; return; }
  const server = $('server').value.trim().replace(/\/+$/, '');
  const username = $('username').value.trim(); const password = $('password').value;
  $('login-button').disabled = true; $('login-button').textContent = '正在登录…'; $('login-error').hidden = true;
  try {
    foregroundRecovery.cancel('login', true);
    cancelAppearance(); cancelInteractions();
    const configured = parse(native().setServer(server));
    if (!configured || configured.ok !== true) throw new Error(configured && configured.error || '服务器地址不可用。');
    state.server = configured.server || server; state.username = username;
    state.authenticated = false; state.sessions = []; state.messages = []; state.activeId = null; state.sessionPersonaConfig = null;
    state.personas = []; state.newPersona = ''; state.sessionPersonas.clear();
    state.attachmentQueues.clear(); state.mediaCache.clear(); state.previewElements = [];
    state.appearanceCache = null;
    state.interactionCache = null;
    const body = { username, password };
    await apiClient.json('POST', API.login, body);
    const config = nativeConfig();
    if (config.authenticated !== true) throw new Error('登录响应未建立有效凭证，请核对服务器接口。');
    state.authenticated = true;
    $('password').value = '';
    storage.set(pref('username'), username);
    $('settings-dialog').close(); restoreDraft(); renderMessages(); renderSessions();
    await loadPersonas(); await refreshSessions();
  } catch (error) {
    if ($('settings-dialog').open) { $('login-error').textContent = errorText(error); $('login-error').hidden = false; }
    else showNotice(errorText(error), { label: '连接设置', run: openSettings }, true);
    renderChrome();
  }
  finally { $('login-button').disabled = false; $('login-button').textContent = '登录并同步'; }
}
function logout() {
  if (state.sending || state.attaching) { showNotice('请等待本轮消息或文件处理结束。'); return; }
  foregroundRecovery.cancel('logout', true);
  cancelAppearance(); cancelInteractions(); saveDraft();
  try { native().clearAuth(); } catch (_) {}
  state.authenticated = false; state.sessions = []; state.messages = []; state.activeId = null; state.sessionPersonaConfig = null; state.remoteRunning = false; state.replyPhase='idle';
  state.personas = []; state.newPersona = ''; state.sessionPersonas.clear();
  state.attachmentQueues.clear(); state.mediaCache.clear(); state.previewElements = [];
  state.appearanceCache = null;
  state.interactionCache = null;
  $('draft').value = ''; resizeDraft(); $('settings-dialog').close(); renderSessions(); renderMessages(); hideNotice();
}
function init() {
  if (typeof ResizeObserver === 'function') {
    const composerObserver = new ResizeObserver(syncComposerMetrics);
    composerObserver.observe(document.querySelector('.composer-area'));
  }
  syncComposerMetrics();
  state.username = storage.get(pref('username'));
  const config = nativeConfig();
  state.server = typeof config.server === 'string' ? config.server : '';
  state.authenticated = config.authenticated === true;
  state.bridgeAvailable = !!(window.AsteriaChat && typeof window.AsteriaChat.request === 'function');
  if (window.AsteriaChatPerception) phonePerceptionPanel = window.AsteriaChatPerception.install({
    state, api: apiClient, bridgeRequest: (method, args = []) => nativeAsync(method, args), showNotice
  });
  $('app-version').textContent = typeof config.version === 'string' ? config.version : '';
  $('composer').addEventListener('submit', sendMessage);
  $('search-button').addEventListener('click', openMessageSearch);
  $('rename-button').addEventListener('click', openRenameTitle);
  $('rename-form').addEventListener('submit', saveRenameTitle);
  $('rename-cancel').addEventListener('click', cancelRenameTitle);
  $('rename-close').addEventListener('click', cancelRenameTitle);
  $('rename-check').addEventListener('click', reconcileRenameTitle);
  $('rename-dialog').addEventListener('cancel', event => { event.preventDefault(); cancelRenameTitle(); });
  $('search-input').addEventListener('input', changeMessageSearch);
  $('search-prev').addEventListener('click', () => moveMessageSearch(-1));
  $('search-next').addEventListener('click', () => moveMessageSearch(1));
  $('search-close').addEventListener('click', closeMessageSearch);
  $('search-input').addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeMessageSearch(); }
    else if (event.key === 'Enter') { event.preventDefault(); moveMessageSearch(event.shiftKey ? -1 : 1); }
  });
  $('more-menu').hidden = true;
  $('more-button').setAttribute('aria-haspopup', 'true');
  const closeMenu = hideMoreMenu;
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hideMoreMenu(); });
  $('more-button').addEventListener('click', () => {
    const open = $('more-menu').hidden;
    $('more-menu').hidden = !open;
    $('more-button').setAttribute('aria-expanded', String(open));
  });
  for (const id of ['rename-button', 'refresh-chat', 'appearance-button', 'menu-interactions', 'menu-export', 'mobile-settings', 'menu-delete']) {
    $(id).addEventListener('click', closeMenu);
  }
  $('menu-delete').addEventListener('click', () => { if (state.activeId) openDeleteConversation(state.activeId); });
  $('menu-interactions').addEventListener('click', openInteractions);
  $('menu-export').addEventListener('click', openConversationExport);
  document.addEventListener('click', event => {
    const menu = $('more-menu');
    if (menu.hidden) return;
    if (event.target && ($('more-button').contains(event.target) || menu.contains(event.target))) return;
    closeMenu();
  });
  $('attach-button').addEventListener('click', () => window.ChatComposer ? window.ChatComposer.setPanel('attachments') : chooseAttachment());
  $('jump-latest').addEventListener('click', jumpToLatest);
  $('sticker-button').addEventListener('click', () => window.ChatComposer ? window.ChatComposer.setPanel('expressions') : stickerPanel($('sticker-panel').hidden));
  $('sticker-close').addEventListener('click', () => stickerPanel(false));
  if (!window.ChatComposer) renderStickers();
  $('theme').addEventListener('change', () => {
    setThemePreference($('theme').value);
    renderMessages();
  });
  $('menu-theme').addEventListener('click', () => {
    const next = THEME_ORDER[(THEME_ORDER.indexOf(themePreference()) + 1) % THEME_ORDER.length];
    setThemePreference(next);
    renderThemeMenu();
    showNotice('深色模式：' + THEME_LABEL[next]);
  });
  $('delete-form').addEventListener('submit', confirmDeleteConversation);
  $('delete-cancel').addEventListener('click', cancelDeleteConversation);
  $('delete-close').addEventListener('click', cancelDeleteConversation);
  $('delete-dialog').addEventListener('cancel', event => { event.preventDefault(); cancelDeleteConversation(); });
  $('draft').addEventListener('focus', keepComposerVisible);
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', syncViewport);
    window.visualViewport.addEventListener('scroll', syncViewport);
  }
  window.addEventListener('resize', syncViewport);
  if (window.matchMedia) {
    try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { applyTheme(); }); }
    catch (_) {}
  }
  syncViewport(); applyTheme();
  $('notify-toggle').checked = false;
  $('notify-toggle').addEventListener('change', () => {
    if (window.ChatComposer) { window.ChatComposer.toggleWatch($('notify-toggle').checked); return; }
    storage.set(pref('notify'), $('notify-toggle').checked ? '1' : '');
    if ($('notify-toggle').checked) {
      startNotifyWatch();
      const bridge = window.AsteriaChat;
      let granted = true;
      try {
        if (bridge && typeof bridge.requestNotificationPermission === 'function') {
          const answer = parse(bridge.requestNotificationPermission());
          granted = !(answer && answer.granted === false);
        }
      } catch (_) { granted = false; }
      showNotice(granted ? '已开启新回复提醒；应用在后台运行时读取到新回复会发系统通知。'
        : '请在系统弹窗中允许通知；允许后新回复才会提醒。');
    } else showNotice('已关闭新回复提醒。');
  });
  startNotifyWatch();
  $('draft').addEventListener('input', () => { resizeDraft(); saveDraft(); renderChrome(); });
  $('draft').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && (event.ctrlKey || event.metaKey || window.matchMedia('(pointer: fine) and (min-width: 800px)').matches)) { event.preventDefault(); $('composer').requestSubmit(); }
  });
  $('settings-form').addEventListener('submit', login);
  $('export-open').addEventListener('click', openConversationExport);
  $('export-form').addEventListener('submit', saveConversationExport);
  $('export-close').addEventListener('click', () => { if (cancelConversationExport()) renderChrome(); });
  $('export-cancel').addEventListener('click', () => { if (cancelConversationExport()) renderChrome(); });
  $('export-dialog').addEventListener('cancel', event => { event.preventDefault(); if (cancelConversationExport()) renderChrome(); });
  for (let index = 0; index < 4; index++) $('quick-slot-' + index).addEventListener('click', () => insertInteraction(index));
  $('interaction-edit').addEventListener('click', openInteractions);
  $('interaction-form').addEventListener('submit', saveInteractions);
  $('interaction-close').addEventListener('click', cancelInteractions);
  $('interaction-cancel').addEventListener('click', cancelInteractions);
  $('interaction-reset').addEventListener('click', resetInteractions);
  $('interaction-dialog').addEventListener('cancel', event => { event.preventDefault(); cancelInteractions(); });
  $('appearance-button').addEventListener('click', openAppearance);
  $('appearance-settings-button').addEventListener('click', openAppearance);
  $('appearance-form').addEventListener('submit', saveAppearance);
  $('appearance-close').addEventListener('click', cancelAppearance);
  $('appearance-cancel').addEventListener('click', cancelAppearance);
  $('appearance-dialog').addEventListener('cancel', event => { event.preventDefault(); cancelAppearance(); });
  $('appearance-reset').addEventListener('click', resetAppearance);
  $('appearance-name').addEventListener('input', () => {
    if (state.appearanceEditing) { state.appearanceEditing.draft.displayName = $('appearance-name').value; previewAppearance(); }
  });
  $('choose-avatar').addEventListener('click', () => chooseAppearanceImage('avatar'));
  $('choose-background').addEventListener('click', () => chooseAppearanceImage('background'));
  $('clear-avatar').addEventListener('click', () => {
    if (state.appearanceEditing) { state.appearanceEditing.draft.avatar = null; previewAppearance(); }
  });
  for (const button of document.querySelectorAll('[data-appearance-palette]')) button.addEventListener('click', () => {
    if (state.appearanceEditing) { state.appearanceEditing.draft.background = button.dataset.appearancePalette; previewAppearance(); }
  });
  $('persona').addEventListener('change', () => {
    const id = $('persona').value;
    state.newPersona = state.personas.some(item => item.persona_id === id) ? id : '';
    storage.set(pref('persona.' + encodeURIComponent(state.server + '|' + state.username)), state.newPersona);
  });
  $('refresh-personas').addEventListener('click', () => loadPersonas().catch(error => {
    $('login-error').textContent = errorText(error); $('login-error').hidden = false;
  }));
  $('close-settings').addEventListener('click', () => $('settings-dialog').close());
  $('settings-button').addEventListener('click', openSettings); $('mobile-settings').addEventListener('click', openSettings); $('empty-login').addEventListener('click', openSettings);
  $('logout-button').addEventListener('click', logout); $('bot-home').addEventListener('click', returnToBot);
  $('refresh-sessions').addEventListener('click', refreshSessions); $('refresh-chat').addEventListener('click', refreshCurrent);
  $('notice-close').addEventListener('click', hideNotice);
  $('open-sidebar').addEventListener('click', () => sidebar(true)); $('close-sidebar').addEventListener('click', () => sidebar(false)); $('sidebar-backdrop').addEventListener('click', () => sidebar(false));
  for (const button of document.querySelectorAll('[data-draft]')) button.addEventListener('click', () => { $('draft').value = button.dataset.draft; saveDraft(); resizeDraft(); renderChrome(); $('draft').focus(); });
  window.addEventListener('offline', () => { foregroundRecovery.signal(); });
  window.addEventListener('online', () => { foregroundRecovery.signal(); });
  document.addEventListener('visibilitychange', () => {
    foregroundRecovery.signal(); if (document.hidden) notifyTick();
    else if (phonePerceptionPanel) phonePerceptionPanel.foregroundChanged();
  });
  window.addEventListener('pagehide', () => { foregroundRecovery.cancel('pagehide'); saveDraft(); });
  window.addEventListener('storage', event => {
    const scope = appearanceScope();
    if (scope && event.key === scope.key) { state.appearanceCache = null; renderMessages(); renderChrome(); }
    const interactions = interactionScope();
    if (interactions && event.key === interactions.key) { state.interactionCache = null; renderInteractions(); }
    if (event.key === pref(THEME_KEY)) applyTheme();
  });
  if (window.ChatComposer) window.ChatComposer.init();
  restoreDraft(); renderPendingActions(); renderSessions(); renderMessages();
  if (state.authenticated) loadPersonas().then(refreshSessions).catch(error => showNotice(errorText(error), { label: '连接设置', run: openSettings }, true));
  else if (!state.bridgeAvailable) showNotice('当前是本地界面预览；请安装 Android 应用后连接服务器。');
}
window.AsteriaChatUI = Object.freeze({ receive:(id,payload)=>receive(id,payload), receiveStream:value=>window.ChatExperience&&window.ChatExperience.receiveStream(value),
  viewportChanged: value => { if (window.ChatComposer) window.ChatComposer.viewportChanged(value); },
  replyWatchChanged: value => { if (window.ChatComposer) window.ChatComposer.watchChanged(value); },
  notificationPermissionChanged: granted => { if (window.ChatComposer) window.ChatComposer.permissionChanged(granted); if (window.ChatNotificationStatus) window.ChatNotificationStatus.refresh(); },
  openConversation: id => { if (window.ChatComposer) window.ChatComposer.openConversation(id); },
  foregroundChanged: () => { foregroundRecovery.signal(); syncViewport(); if (phonePerceptionPanel) phonePerceptionPanel.foregroundChanged(); if (window.ChatNotificationStatus) window.ChatNotificationStatus.refresh(); },
  back: () => window.ChatComposer && window.ChatComposer.closeActive() || closeMessageSearch() || cancelRenameTitle() || cancelConversationExport() });
document.addEventListener('DOMContentLoaded', init, { once: true });
