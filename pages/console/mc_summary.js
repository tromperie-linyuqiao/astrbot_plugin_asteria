/* Normal AstrBot administrator control of the one existing summary owner. */
(function (global) {
  'use strict';
  const root = document.getElementById('mc-summary-mount');
  if (!root) return;
  const node = (tag, text, cls) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; if (cls) value.className = cls; return value; };
  let current = null, fresh = false, busy = false, pending = null, pendingEnded = false, inspected = false;
  root.innerHTML = `<section class="panel mc-summary-panel"><div class="panel-head"><h2>记忆摘要算法</h2><button type="button" data-summary-status>刷新状态</button></div><p data-summary-boundary>先读取实际摘要执行者；算法切片与完整原生记忆服务分别显示，不按配置开关推断接管。</p><div data-summary-stats class="mc-summary-stats"></div><p data-summary-notice class="hint" role="status" aria-live="polite">正在等待读取真实状态。</p><div class="actions"><button type="button" data-summary-inspect>检查当前来源与在途调用</button><button type="button" class="primary" data-summary-activate disabled>交给TLS原生算法</button><button type="button" data-summary-restore disabled>恢复原MC算法</button><button type="button" data-summary-full hidden>打开完整记忆服务归属</button></div><details><summary>职责边界与恢复方式</summary><p>新算法保持原参数和提示合同，不创建第二个摘要worker、模型路由、数据库或发送器。交接会等待当前已开始的摘要调用；超过期限、来源变化或有未知所有者时会拒绝。</p><p>关闭配置开关不等于恢复原实例。请用此页的“恢复原MC算法”。状态未知时先回读或检查，不要重复提交；页面只展示真实返回，不代替生产运行验收。</p><div data-summary-details></div></details></section>`;
  const $ = name => root.querySelector('[data-summary-' + name + ']');
  function notice(text, error) { $('notice').textContent = text; $('notice').classList.toggle('mc-summary-error', !!error); }
  function draw() {
    const stats = $('stats'); stats.replaceChildren();
    if (current) {
      const owner = !fresh ? '当前状态未确认，请重新读取' : current.algorithm_active === true && current.active === true ? 'TLS原生算法运行' : current.algorithm_active === true ? 'TLS持有算法；当前未活动' : current.owner === 'original_algorithm' ? '原MC算法实例' : '尚未证明交接';
      for (const [label, value] of [['当前算法', owner], ['物理来源', current.source_current === true ? '当前来源一致' : '需要检查'], ['恢复状态', current.recovery_required ? '需要恢复处理' : '没有已报告的恢复阻断']]) {
        const item = node('div'); item.append(node('small', label), node('strong', value)); stats.append(item);
      }
      const full = current.algorithm_only === false && current.stop_requires_full_service_stop === true;
      $('boundary').textContent = full ? '摘要随完整TLS原生记忆服务运行；时间线、摘要worker、模型选择、原历史库和审计入口属于同一原生服务。这里不能单独恢复旧算法，应在原生接管中心管理整服务归属。' : '当前为摘要算法切片；时间线、摘要worker、模型选择和原数据库职责保持其现有执行者。';
      $('full').hidden = !full;
      const details = $('details'); details.replaceChildren();
      if (current.parameters) for (const [key, value] of Object.entries(current.parameters)) details.append(node('p', key + '：' + value, 'hint'));
      if (current.inflight) details.append(node('p', '已审摘要调用：' + current.inflight.audited_summary_calls + '；无法判定的等待链：' + current.inflight.unknown_task_chains, 'hint'));
      if (current.preflight_error) details.append(node('p', '本次检查：' + current.preflight_error, 'mc-summary-error'));
      if (current.configuration_mismatch) details.append(node('p', '配置已关但算法实例仍由TLS持有。请显式恢复，不要仅修改开关。', 'mc-summary-error'));
    }
    $('activate').disabled = busy || !fresh || !!pending || !inspected || !current || current.ready_for_activation !== true;
    $('restore').disabled = busy || !fresh || !!pending || !current || current.stop_requires_full_service_stop === true || !(current.algorithm_active || current.controller_retained || current.retained_recovery_available);
    $('inspect').disabled = busy; $('status').disabled = busy;
  }
  function unpack(value) {
    const response = value && value.ok === true ? value : value && value.data;
    if (!response || response.ok !== true) throw Error('摘要接口没有返回可确认的状态。');
    const summary = response.summary || response.mc && response.mc.summary;
    if (!summary || typeof summary !== 'object') throw Error('摘要状态格式不完整。');
    return summary;
  }
  async function call(method, suffix) {
    if (typeof api !== 'function') throw Error('后台连接尚未准备好。');
    return unpack(await api(method, 'page/server-integration/mc/summary/' + suffix, method === 'POST' ? {} : undefined));
  }
  async function load(inspect) {
    if (busy) return;
    busy = true; draw(); notice(inspect ? '正在检查真实来源、算法参数和当前调用…' : '正在读取当前摘要执行权…');
    try {
      current = await call('GET', inspect ? 'inspect' : 'status'); fresh = true; inspected = !!inspect;
      if (pending && current.source_current === true && (pending === 'activate' ? current.algorithm_active === true : current.owner === 'original_algorithm' && current.algorithm_active === false)) pending = null;
      if (pending && pendingEnded && inspect && current.source_current === true && current.owner === 'original_algorithm' && current.algorithm_active === false) pending = null;
      notice(pending ? '上次操作结果仍待确认；已禁止重复提交，请检查来源并核对。' : inspect && current.ready_for_activation ? '当前检查允许尝试交接；提交时仍会复核并排空。' : current.recovery_required ? '当前存在保留的恢复引用或未知所有者，请先处理恢复。' : '已读取真实摘要状态。', !!pending || !!current.recovery_required);
    } catch (error) { fresh = false; inspected = false; notice((error.message || '摘要状态暂不可用。') + ' 旧状态不作为当前交接依据。', true); }
    finally { busy = false; draw(); }
  }
  async function operate(action) {
    if (busy || pending || !fresh) return;
    if (action === 'restore' && current?.stop_requires_full_service_stop === true) return;
    if (action === 'activate' && (!inspected || !current || current.ready_for_activation !== true)) return;
    if (!global.confirm(action === 'activate' ? '仅将当前摘要算法实例交给TLS；其他MC职责继续保留。现在交接？' : '等待已开始的摘要调用后，精确恢复原MC算法实例。现在恢复？')) return;
    busy = true; pending = action; pendingEnded = false; draw(); notice('正在进行算法实例交接，请勿重复提交。');
    try {
      current = await call('POST', action);
      const confirmed = action === 'activate' ? current.algorithm_active === true && current.configured === true : current.algorithm_active === false && current.recovery_required !== true && current.configured === false;
      if (!confirmed) throw Error('操作已返回，但所有权状态尚未确认，请先回读。');
      pending = null; inspected = false; notice(action === 'activate' ? '当前算法实例已交给TLS；实际摘要结果仍待运行验收。' : '当前算法已恢复到原MC路径，新记忆资料没有删除。');
    } catch (error) {
      pendingEnded = [400,401,403,409].includes(Number(error.status || error.statusCode));
      notice((error.message || '交接暂未完成。') + ' 先回读或检查，结果未知时不要重复提交。', true);
    }
    finally { busy = false; draw(); }
  }
  $('status').addEventListener('click', () => load(false));
  $('inspect').addEventListener('click', () => load(true));
  $('activate').addEventListener('click', () => operate('activate'));
  $('restore').addEventListener('click', () => operate('restore'));
  $('full').addEventListener('click', () => document.querySelector('[data-view="native_ownership"]')?.click());
  global.TLSMCSummaryPanel = { activate: () => load(false) };
  draw();
})(window);
