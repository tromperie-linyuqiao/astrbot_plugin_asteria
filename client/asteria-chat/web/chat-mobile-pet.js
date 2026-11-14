'use strict';
window.ChatMobilePet = (() => {
  let dialog, mode, target, game, status, explanation, permission, start, stop, busy = false;
  let lastScope = '', startRefresh;
  const labels = ['陪伴模式', '游戏模式', '跟随指定应用'];
  const access = [
    ['overlay', '允许显示在其他应用上层', '你可以在系统设置里撤回浮窗权限。'],
    ['notifications', '开启桌宠控制通知', '通知栏会保留一个“关闭桌宠”按钮。'],
    ['usage', '允许读取应用使用情况', 'Asteria Chat 只在本机匹配你指定的应用，独立于感知桥上传。']
  ];
  const bridge = () => window.TexasChat;
  function button(label, action, cls = 'secondary-button') {
    const value = document.createElement('button');
    value.type = 'button'; value.className = cls; value.textContent = label; value.onclick = action;
    return value;
  }
  function init() {
    dialog = document.createElement('dialog');
    dialog.className = 'settings-dialog';
    dialog.setAttribute('aria-labelledby', 'mobile-pet-title');
    dialog.innerHTML = '<div class="settings-form"><div class="dialog-heading"><div><h2 id="mobile-pet-title">手机桌宠</h2><p id="mobile-pet-bound" class="settings-intro"></p></div><button type="button" class="icon-button" aria-label="关闭" data-pet-close>×</button></div><p id="mobile-pet-status" role="status" class="appearance-help"></p><label>显示方式<select id="mobile-pet-mode"><option value="0">陪伴模式</option><option value="1">游戏模式</option><option value="2">跟随指定应用</option></select></label><label id="mobile-pet-target">应用包名<input id="mobile-pet-package" type="text" maxlength="120" placeholder="com.mojang.minecraftpe" autocomplete="off" spellcheck="false" aria-describedby="mobile-pet-help"></label><p id="mobile-pet-help" class="appearance-help"></p><section id="mobile-pet-permission"></section><div id="mobile-pet-actions"></div></div>';
    document.body.append(dialog);
    dialog.querySelector('[data-pet-close]').onclick = close;
    mode = dialog.querySelector('#mobile-pet-mode');
    target = dialog.querySelector('#mobile-pet-target');
    game = dialog.querySelector('#mobile-pet-package');
    status = dialog.querySelector('#mobile-pet-status');
    explanation = dialog.querySelector('#mobile-pet-help');
    permission = dialog.querySelector('#mobile-pet-permission');
    mode.onchange = () => refresh();
    start = button('开启桌宠', () => control('start'), 'primary-button');
    stop = button('关闭桌宠', () => control('stop'));
    dialog.querySelector('#mobile-pet-actions').append(start, ' ', stop);
  }
  function read() {
    try { return JSON.parse(bridge().mobilePetStatus(String(state.activeId || ''))); }
    catch (_) { return null; }
  }
  function open() {
    if (!dialog) init();
    const saved = read();
    mode.value = String(saved?.mode ?? 0);
    game.value = saved?.game_package || '';
    if (!dialog.open) dialog.showModal();
    refresh();
  }
  function close() {
    if (!dialog?.open) return false;
    clearTimeout(startRefresh);
    dialog.close();
    return true;
  }
  function refresh() {
    if (!dialog?.open) return;
    const saved = read(), bound = Boolean(state.authenticated && state.activeId);
    const following = mode.value === '2';
    dialog.querySelector('#mobile-pet-bound').textContent = bound
      ? '绑定会话 · ' + currentRoleName()
      : '先进入要绑定的角色会话。';
    target.hidden = !following;
    explanation.textContent = following
      ? '只在指定应用可识别时切为游戏模式。我的世界国际版可填写 com.mojang.minecraftpe。'
      : mode.value === '1' ? '更小、固定位置。新回复只显示一个圆点。'
        : '可拖动。新回复显示简短提示，点开可以回到原会话。';
    permission.replaceChildren();
    const missing = saved ? access.filter(([id]) => !saved[id] && (id !== 'usage' || following)) : [];
    for (const [id, label, help] of missing) {
      const row = document.createElement('p');
      row.className = 'appearance-help';
      row.textContent = help;
      permission.append(button(label, () => bridge()?.mobilePetPermission(id)), row);
    }
    status.textContent = !saved ? '请在 Android 版 Asteria Chat 中使用手机桌宠。'
      : saved.running ? '已开启 · ' + labels[saved.mode] + '。切到其他应用后显示。'
        : saved.pending ? '正在开启桌宠。' : '桌宠已关闭。';
    start.textContent = saved?.running ? '应用显示方式' : '开启桌宠';
    start.disabled = busy || !saved || saved.pending || !bound || missing.length > 0;
    stop.hidden = !saved?.running && !saved?.pending;
    stop.disabled = busy;
  }
  async function control(action) {
    if (busy) return;
    const selected = Number(mode.value), packageName = game.value.trim();
    if (action === 'start' && selected === 2 && !/^[a-z0-9_]+(?:\.[a-z0-9_]+)+$/i.test(packageName)) {
      status.textContent = '请输入应用包名，例如 com.mojang.minecraftpe。';
      return;
    }
    busy = true; refresh();
    let notice = '';
    try {
      await nativeAsync('mobilePetControl', [String(state.activeId || ''), action, selected, packageName], 10000);
      if (action === 'start') {
        clearTimeout(startRefresh);
        startRefresh = setTimeout(refresh, 900);
      }
    } catch (error) {
      notice = error.message || '操作未完成，请检查当前会话和权限。';
    } finally {
      busy = false; refresh();
      if (notice && dialog.open) status.textContent = notice;
    }
  }
  function scopeChanged() {
    const next = state.authenticated && state.activeId
      ? JSON.stringify([state.server, state.username, state.activeId]) : '';
    if (next === lastScope) return;
    lastScope = next;
    if (next) bridge()?.mobilePetConversationChanged?.(state.activeId);
    refresh();
  }
  return { open, close, refresh, scopeChanged };
})();
