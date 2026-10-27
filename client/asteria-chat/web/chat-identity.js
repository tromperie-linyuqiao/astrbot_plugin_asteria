'use strict';

/* Explicit pairing through the existing authenticated chat bridge. */
window.ChatIdentity = (() => {
  let owner = '', busy = false;
  const scope = () => JSON.stringify([state.server, state.username, state.activeId]);
  const active = selected => selected === owner && owner === scope() && document.getElementById('identity-dialog').open;
  const node = id => document.getElementById(id);
  const say = value => { node('identity-message').textContent = value; };
  async function read() {
    if (busy) return;
    const selected = owner;
    busy = true;
    try {
      const result = await apiClient.json('GET', '/chat/identity?session_id=' + encodeURIComponent(state.activeId));
      if (!active(selected)) return;
      node('identity-state').textContent = result.linked ? '已绑定 QQ ' + result.qq_account_masked : '尚未绑定QQ';
      node('identity-revoke').hidden = !result.linked && !result.pending;
      node('identity-generate').hidden = result.linked;
      node('identity-consent-label').hidden = result.linked;
      node('identity-notify-label').hidden = result.linked;
      if (result.linked) {
        node('identity-command').hidden = true;
        say(result.qq_persona_observed ? '绑定已生效。两端会按原有记忆规则读取获授权的长期资料。'
          : 'QQ私聊已确认。再与QQ里的伙伴正常聊一句，便可登记当前角色并读取其记忆。');
      } else say(result.pending ? '有一条待QQ确认的绑定码；生成新码会使旧码失效。' : '只会在你用QQ私聊确认后启用共享。');
    } catch (error) { if (active(selected)) say(errorText(error)); }
    finally { busy = false; if (owner && selected !== owner && active(owner)) read(); }
  }
  async function issue() {
    if (busy || !active(owner)) return;
    const selected = owner;
    if (!node('identity-consent').checked) { say('请先勾选共享双方长期记忆。'); return; }
    busy = true; node('identity-generate').disabled = true;
    try {
      const data = await apiClient.json('POST', '/chat/identity/challenge', {session_id:state.activeId, consent:true,
        notifications:node('identity-notify').checked});
      if (!active(selected)) return;
      const code = node('identity-command'); code.value = data.command; code.hidden = false;
      node('identity-revoke').hidden = false;
      say('长按复制上方整条命令，发给QQ里的伙伴。绑定码10分钟有效；发完点“刷新绑定状态”。');
    } catch (error) { if (active(selected)) say(errorText(error) + ' 请先刷新状态，不会自动重复提交。'); }
    finally { busy = false; node('identity-generate').disabled = false; if (owner && selected !== owner && active(owner)) read(); }
  }
  async function revoke() {
    if (busy || !active(owner)) return;
    const selected = owner;
    busy = true; node('identity-revoke').disabled = true;
    try {
      await apiClient.json('POST', '/chat/identity/revoke', {session_id:state.activeId});
      if (!active(selected)) return;
      node('identity-command').value = ''; node('identity-command').hidden = true;
      say('已解除共享并作废待确认的码。原聊天与记忆保留。');
    } catch (error) { if (active(selected)) say(errorText(error) + ' 请刷新状态确认结果。'); }
    finally { busy = false; node('identity-revoke').disabled = false; }
    if (owner && active(owner)) await read();
  }
  function open() {
    if (!state.authenticated || !state.activeId) { showNotice('先登录并连接伙伴。'); return; }
    hideMoreMenu(); owner = scope();
    node('identity-command').value = ''; node('identity-command').hidden = true;
    node('identity-consent').checked = false;
    node('identity-notify').checked = true;
    node('identity-state').textContent = '正在读取…'; say('');
    node('identity-revoke').hidden = true; node('identity-generate').hidden = false;
    node('identity-consent-label').hidden = node('identity-notify-label').hidden = false;
    node('identity-dialog').showModal(); read();
  }
  document.addEventListener('DOMContentLoaded', () => {
    const dialog = document.createElement('dialog'); dialog.id = 'identity-dialog'; dialog.className = 'settings-dialog';
    dialog.innerHTML = '<div class="settings-form"><div class="dialog-heading"><h2>QQ与记忆共享</h2><button id="identity-close" type="button" class="icon-button" aria-label="关闭">×</button></div><strong id="identity-state">正在读取…</strong><p class="appearance-help">在QQ私聊确认后，双方可以使用彼此的长期记忆。资料保留原来源，不合并或删除历史；不会因此增加QQ发信权限。</p><label id="identity-consent-label" class="experience-field"><span><input id="identity-consent" type="checkbox"> 我同意与确认绑定的QQ私聊双向共享长期记忆</span></label><input id="identity-command" class="identity-command" readonly hidden aria-label="发送到QQ的绑定命令"><p id="identity-message" class="appearance-help" role="status"></p><div class="appearance-actions"><button id="identity-generate" class="primary-button" type="button">生成绑定码</button><button id="identity-refresh" class="secondary-button" type="button">刷新绑定状态</button><button id="identity-revoke" class="text-button" type="button" hidden>解除共享 / 作废绑定码</button></div></div>';
    document.body.append(dialog);
    const notify = document.createElement('label'); notify.id = 'identity-notify-label'; notify.className = 'experience-field';
    const check = document.createElement('input'); check.type = 'checkbox'; check.id = 'identity-notify'; check.checked = true;
    notify.append(check, document.createTextNode(' 同时在APP接收QQ已确认发送的主动消息文本副本（不重复发QQ）'));
    node('identity-consent-label').after(notify);
    node('identity-close').onclick = () => dialog.close();
    node('identity-generate').onclick = issue; node('identity-refresh').onclick = read; node('identity-revoke').onclick = revoke;
    node('identity-command').addEventListener('focus', () => node('identity-command').select());
    dialog.addEventListener('close', () => { if (!dialog.open) { owner = ''; node('identity-command').value = ''; } });
    const button = document.createElement('button'); button.type = 'button'; button.className = 'menu-item';
    button.textContent = 'QQ与记忆共享'; button.onclick = open; node('more-menu').append(button);
  }, {once:true});
  function scopeChanged() {
    if (owner && owner !== scope()) {
      owner = ''; node('identity-command').value = ''; node('identity-dialog').close();
    }
  }
  return {open, scopeChanged};
})();
