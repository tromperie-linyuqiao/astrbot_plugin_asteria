'use strict';
window.AsteriaChatPerceptionStatus = (() => {
  const titles = { battery: '电量与充电', screen: '屏幕', network: '网络', audio: '音频', device: '设备', activity: '活动', app: '当前应用', music: '音乐', location: '位置' };
  const statuses = { fresh: '新鲜记录', stale: '已过期', unknown: '尚未确认', disabled: '未启用', unauthorized: '未授权', unavailable: '不可用' };
  const fields = { level: '电量', charging: '正在充电', charging_type: '充电类型', temperature_c: '温度', on: '屏幕亮起', locked: '锁定', type: '网络类型', roaming: '漫游', metered: '计费网络', media_active: '媒体活动', headphones: '耳机已连接', ringer_mode: '铃声模式', name: '设备名称', platform: '平台', os_version: '系统版本', power_save: '省电模式', battery_temp_c: '电池温度', steps_today: '今日步数', device_idle: '设备空闲', last_unlock_epoch: '上次解锁', foreground_package: '应用包名', foreground_label: '应用名称', foreground_since_epoch: '进入应用时间', foreground_minutes: '前台分钟', state: '播放状态', playing: '正在播放', title: '曲目', artist: '歌手', album: '专辑', source: '事实来源', package: '播放器', track_id: '曲目标识', progress_ms: '进度', duration_ms: '时长', playback_speed: '播放速度' };
  const node = (tag, text, cls) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; if (cls) value.className = cls; return value; };
  const time = value => { if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '未提供'; const date = new Date(value * 1000); return Number.isFinite(date.getTime()) ? date.toLocaleString() : '未提供'; };
  function fact(key, value) {
    if (value === null || value === undefined) return '未提供';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (key.endsWith('_epoch')) return time(value);
    if (key.endsWith('_ms') && typeof value === 'number') return (value / 1000).toFixed(1) + ' 秒';
    if (key === 'level' && typeof value === 'number') return value + '%';
    return String(value);
  }
  function transport(value) {
    const item = value || {}, section = node('section', undefined, 'perception-unified-transport');
    const labels = { unconfigured: '尚未配置', unknown: '尚无真实访问结果', reachable: '最近访问成功', unauthorized: '最近访问被拒绝', unavailable: '最近访问失败' };
    section.append(node('p', '感知桥配置：' + (item.configured === true ? '已配置' : item.configured === false ? '未配置' : '待核对')),
      node('p', '访问状态：' + (labels[item.state] || '待核对')),
      node('p', '上次尝试：' + time(item.last_attempt_at) + '\n上次成功访问：' + time(item.last_success_at), 'perception-unified-time'));
    if (item.error?.message) section.append(node('p', item.error.message, 'perception-unified-reason'));
    return section;
  }
  function report(value) {
    const section = node('section', undefined, 'perception-unified-report');
    const verified = value?.accepted === true && value?.state === 'accepted' && value?.provenance === 'existing_journal_report_receipt';
    const state = verified ? '感知桥已确认接收本次上报' : value?.state === 'rejected' ? '感知桥未接受本次上报' : value?.state === 'unverified' || value?.state === 'accepted' ? '旧上报记录尚未核对' : '尚无与当前设备及当前配置相符的接收证明';
    section.append(node('h4', '上报接收'), node('p', state), node('p', '开始：' + time(value?.started_at) + '\n完成：' + time(value?.completed_at), 'perception-unified-time'));
    if (Number.isInteger(value?.http_status)) section.append(node('p', '桥端返回 HTTP ' + value.http_status));
    return section;
  }
  function sources(value) {
    const grid = node('div', undefined, 'perception-unified-grid');
    for (const [key, title] of Object.entries(titles)) {
      const row = value?.[key] || { status: 'unknown' }, card = node('article', undefined, 'perception-unified-source'), head = node('div', undefined, 'perception-unified-heading');
      head.append(node('h4', title), node('span', statuses[row.status] || '待核对', 'perception-unified-badge')); card.append(head);
      const hidden = row.unauthorized === true || ['unauthorized', 'disabled'].includes(row.status);
      if (!hidden && row.value && typeof row.value === 'object') {
        if (row.status !== 'fresh') card.append(node('p', '以下仅是上次记录，当前状态尚未确认。', 'perception-unified-archive'));
        for (const [name, item] of Object.entries(row.value)) {
          if (['schema_version', 'observed_at'].includes(name)) continue;
          card.append(node('p', (fields[name] || name) + '：' + fact(name, item)));
        }
      } else card.append(node('p', hidden ? '没有可显示的已授权记录。' : '尚无此来源的可用事实。'));
      card.append(node('p', 'TLS 收到快照：' + time(row.last_received_at) + '\n来源观察：' + time(row.observed_at) + '\n原有效期至：' + time(row.expires_at), 'perception-unified-time'));
      if (row.error?.message) card.append(node('p', row.error.message + (Number.isInteger(row.error.http_status) ? '（HTTP ' + row.error.http_status + '）' : ''), 'perception-unified-reason'));
      grid.append(card);
    }
    return grid;
  }
  function render(container, value) {
    if (!container) return;
    container.replaceChildren(); container.classList.add('perception-unified');
    container.append(node('h3', '服务器实际感知状态'));
    if (!value || value.schema !== 1 || !value.sources) { container.append(node('p', '统一来源状态尚未读取，请用现有“刷新状态”查看。')); return; }
    container.append(node('p', '沿用原 PPB 已授权来源；这里仅展示已有状态，不启动采集或上报。', 'appearance-help'));
    const aggregate = !value.device_id && Array.isArray(value.summaries) && value.summaries.length;
    if (aggregate) container.append(node('p', '尚未选定具体设备，以下逐台展示原已授权设备的已有记录。'));
    const records = aggregate ? value.summaries : [value];
    for (const record of records) {
      const group = node('section', undefined, 'perception-unified-device');
      if (record.device_id) group.append(node('h4', '设备：' + record.device_id));
      group.append(transport(record.transport), report(record.report), sources(record.sources)); container.append(group);
    }
    container.append(node('p', '状态生成：' + time(value.generated_at), 'perception-unified-time'));
  }
  return Object.freeze({ render });
})();
