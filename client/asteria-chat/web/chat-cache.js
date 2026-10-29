'use strict';
/* Recoverable snapshots only. Drafts, credentials, preferences and send state
   have separate owners. No timers, network calls or send queue live here. */
window.ChatCache = (() => {
  const KEY = 'asteria-chat.saved-history.v1';
  const limits = Object.freeze({ ttlMs: 30 * 86400000, accounts: 4, sessions: 20, messages: 250, chars: 1500000 });
  let error = '';
  const clone = value => JSON.parse(JSON.stringify(value));
  const scope = (server, username) => JSON.stringify([server, username]);
  const validId = id => typeof id === 'string' && id.length > 0 && id.length <= 256 && !/[\u0000-\u001f]/.test(id);
  function clean(db) {
    const cutoff = Date.now() - limits.ttlMs;
    if (!db || db.version !== 1 || !Array.isArray(db.accounts)) return { version: 1, accounts: [] };
    db.accounts = db.accounts.filter(account => account && typeof account.key === 'string' && account.updatedAt >= cutoff
      && Array.isArray(account.sessions) && Array.isArray(account.records));
    for (const account of db.accounts) {
      account.sessions = account.sessions.filter(row => row && validId(row.session_id)).slice(0, limits.sessions);
      const ids = new Set(account.sessions.map(row => row.session_id));
      account.records = account.records.filter(row => row && ids.has(row.id) && row.updatedAt >= cutoff
        && row.snapshot && Array.isArray(row.snapshot.history)).slice(-limits.sessions);
      if (!ids.has(account.lastId)) account.lastId = null;
    }
    db.accounts.sort((a, b) => b.updatedAt - a.updatedAt);
    db.accounts = db.accounts.slice(0, limits.accounts);
    return db;
  }
  function read() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw && raw.length > limits.chars) { localStorage.removeItem(KEY); return clean(null); }
      return clean(raw ? JSON.parse(raw) : null);
    } catch (_) { error = '本机缓存暂不可读取，联网记录仍可使用。'; return clean(null); }
  }
  function trim(db) {
    let raw = JSON.stringify(db);
    while (raw.length > limits.chars) {
      const oldest = db.accounts.flatMap(account => account.records.map(record => ({ account, record })))
        .sort((a, b) => a.record.updatedAt - b.record.updatedAt)[0];
      if (oldest) oldest.account.records = oldest.account.records.filter(row => row !== oldest.record);
      else if (db.accounts.length) db.accounts.pop();
      else break;
      raw = JSON.stringify(db);
    }
    return raw;
  }
  function write(db) {
    const raw = trim(clean(db));
    try {
      localStorage.setItem(KEY, raw);
      if (localStorage.getItem(KEY) !== raw) throw new Error('cache_readback');
      error = ''; return true;
    } catch (_) {
      // Only this recoverable cache is expendable when storage is full.
      try { localStorage.removeItem(KEY); } catch (_) {}
      error = '本机空间不足，记录缓存未保存；草稿和外观未清除。'; return false;
    }
  }
  function accountIn(db, server, username, create = false) {
    if (!server || !username) return null;
    const key = scope(server, username);
    let account = db.accounts.find(row => row.key === key);
    if (!account && create) { account = { key, updatedAt: Date.now(), lastId: null, sessions: [], records: [] }; db.accounts.unshift(account); }
    return account || null;
  }
  function sessionMetadata(row) {
    return { session_id: row.session_id,
      display_name: typeof row.display_name === 'string' ? row.display_name.slice(0, 256) : '',
      created_at: row.created_at, updated_at: row.updated_at,
      persona_id: typeof row.persona_id === 'string' ? row.persona_id.slice(0, 256) : undefined,
      primary: row.primary === true, tls_state: row.tls_state ? clone(row.tls_state) : undefined };
  }
  function sessions(server, username, rows, lastId) {
    const db = read(), account = accountIn(db, server, username, true); if (!account) return false;
    const seen = new Set();
    const all = rows.filter(row => row && validId(row.session_id) && !seen.has(row.session_id) && seen.add(row.session_id));
    // Keep the active conversation even when the remote list is much larger.
    account.sessions = [...all.filter(row => row.session_id === lastId), ...all.filter(row => row.session_id !== lastId)]
      .slice(0, limits.sessions).map(sessionMetadata);
    const ids = new Set(account.sessions.map(row => row.session_id));
    account.records = account.records.filter(row => ids.has(row.id));
    account.lastId = ids.has(lastId) ? lastId : null;
    account.updatedAt = Date.now(); return write(db);
  }
  function save(server, username, id, result) {
    if (!validId(id) || !result || !Array.isArray(result.history)) return false;
    const db = read(), account = accountIn(db, server, username);
    if (!account || !account.sessions.some(row => row.session_id === id)) return false;
    // History is a full authoritative snapshot: never merge deleted rows back.
    // Only saved rows with stable server IDs survive; partial runs never do.
    const seen = new Set();
    const saved = result.history.filter(row => row && row.id != null && row.content
      && ['user', 'bot'].includes(row.content.type)).filter(row => {
        const key = String(row.id); if (seen.has(key)) return false; seen.add(key); return true;
      });
    const complete = saved.length === result.history.length && saved.length <= limits.messages && result.is_running !== true;
    const snapshot = clone({ history: saved.slice(-limits.messages), persona: result.persona,
      tls_state: result.tls_state, receipt_transport: result.receipt_transport, is_running: false, active_runs: [] });
    const revision = complete && /^[a-f0-9]{64}$/.test(result.history_revision || '') ? result.history_revision : null;
    account.records = account.records.filter(row => row.id !== id);
    account.records.push({ id, updatedAt: Date.now(), complete, revision, snapshot });
    account.lastId = id; account.updatedAt = Date.now();
    return write(db);
  }
  function restore(server, username) {
    const db = read(); write(db); // Expired data is physically reclaimed on access.
    const account = accountIn(db, server, username);
    return account ? clone(account) : null;
  }
  function history(server, username, id) {
    const record = accountIn(read(), server, username)?.records.find(row => row.id === id);
    return record ? clone(record) : null;
  }
  function remove(server, username, id) {
    const db = read(), account = accountIn(db, server, username); if (!account) return true;
    account.sessions = account.sessions.filter(row => row.session_id !== id);
    account.records = account.records.filter(row => row.id !== id);
    if (account.lastId === id) account.lastId = null;
    return write(db);
  }
  function clear(server, username) {
    const db = read(); db.accounts = db.accounts.filter(row => row.key !== scope(server, username));
    return write(db);
  }
  function stats(server, username) {
    const account = accountIn(read(), server, username);
    return { sessions: account?.records.length || 0,
      messages: account?.records.reduce((sum, row) => sum + row.snapshot.history.length, 0) || 0,
      updatedAt: account?.records.reduce((latest, row) => Math.max(latest, row.updatedAt), 0) || 0,
      bytes: account ? JSON.stringify(account).length * 2 : 0, error, limits };
  }
  return Object.freeze({ sessions, save, restore, history, remove, clear, stats, limits });
})();
