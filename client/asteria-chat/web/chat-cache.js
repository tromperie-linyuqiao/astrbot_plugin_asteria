'use strict';
/* Recoverable snapshots only. Drafts, credentials, preferences and send state
   have separate owners. No timers, network calls or send queue live here. */
window.ChatCache = (() => {
  const KEY = 'texas-chat.saved-history.v1';
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
    const revision = complete && result.is_running !== true && !(result.active_runs || []).length
      && /^[a-f0-9]{64}$/.test(result.history_revision || '') ? result.history_revision : null;
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

/* Image previews have one bounded disk owner. History keeps references only.
   No credentials, network, message sends or server writes are stored here. */
window.ChatMediaCache = (() => {
  const limits = Object.freeze({ bytes: 64 * 1024 * 1024, count: 256, ttlMs: 30 * 86400000 });
  let database, epoch = 0, error = '';
  const scope = (server, user) => JSON.stringify([server, user]);
  const valid = body => body && typeof body.data_url === 'string' && body.data_url.length <= 12 * 1024 * 1024
    && /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(body.data_url);
  function db() {
    if (!database) database = new Promise((resolve, reject) => {
      const request = indexedDB.open('texas-chat-media-v1', 2);
      request.onupgradeneeded = () => {
        for (const name of ['images','index','catalogs'])
          if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name, { keyPath: 'key' });
      };
      request.onsuccess = () => { request.result.onversionchange = () => { request.result.close(); database = null; }; resolve(request.result); };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('media_database_busy'));
    }).catch(failure => { database = null; throw failure; });
    return database;
  }
  async function run(mode, action) {
    const opened = await db();
    return new Promise((resolve, reject) => {
      const tx = opened.transaction(['images', 'index', 'catalogs'], mode); let value;
      tx.oncomplete = () => resolve(value); tx.onabort = tx.onerror = () => reject(tx.error || new Error('media_storage_failed'));
      try { action(tx.objectStore('images'), tx.objectStore('index'), result => { value = result; }, tx.objectStore('catalogs')); }
      catch (failure) { tx.abort(); reject(failure); }
    });
  }
  async function get(owner, resource, version = null) {
    const generation = epoch, key = JSON.stringify([owner, resource]);
    try {
      const value = await run('readwrite', (images, index, done) => {
        const request = images.get(key);
        request.onsuccess = () => {
          const row = request.result, now = Date.now();
          if (!row || generation !== epoch) return done(null);
          if (!valid(row.body) || now - row.touched > limits.ttlMs || now < row.touched
              || version != null && row.version !== version) {
            images.delete(key); index.delete(key); return done(null);
          }
          row.touched = now; images.put(row);
          index.put({ key, owner, touched: now, bytes: row.bytes }); done(row.body);
        };
      });
      return generation === epoch ? value || null : null;
    } catch (_) { error = '图片缓存暂不可读取，联网图片仍可使用。'; return null; }
  }
  async function put(owner, resource, version, body, generation = epoch) {
    if (!valid(body) || generation !== epoch) return false;
    const key = JSON.stringify([owner, resource]), bytes = body.data_url.length * 2;
    try {
      return await run('readwrite', (images, index, done) => {
        if (generation !== epoch) return done(false);
        const now = Date.now(), metadata = { key, owner, touched: now, bytes };
        images.put({ ...metadata, version, body: { data_url: body.data_url, mime_type: body.mime_type || body.data_url.split(';')[0].slice(5) } });
        index.put(metadata);
        const request = index.getAll();
        request.onsuccess = () => {
          const rows = request.result.sort((a,b) => a.touched - b.touched);
          let total = rows.reduce((sum,row) => sum + row.bytes, 0), count = rows.length;
          for (const row of rows) {
            if (row.key === key) continue;
            if (total <= limits.bytes && count <= limits.count && now-row.touched <= limits.ttlMs) continue;
            images.delete(row.key); index.delete(row.key); total -= row.bytes; count--;
          }
          error = ''; done(true);
        };
      });
    } catch (_) { error = '图片缓存未保存；已加载图片仍可查看。'; return false; }
  }
  const catalogLimits = Object.freeze({ count:8, bytes:2*1024*1024, rowBytes:512*1024, ttlMs:30*86400000 });
  function validCatalog(value) {
    return value && Array.isArray(value.items) && value.items.length <= 1000
      && value.items.every(row=>row && typeof row==='object' && !Array.isArray(row)
        && typeof (row.id||row.asset_id)==='string' && (row.id||row.asset_id).length<=128)
      && JSON.stringify(value).length*2<=catalogLimits.rowBytes;
  }
  async function catalogGet(owner, resource) {
    const generation=epoch,key=JSON.stringify([owner,resource]);
    try {
      const row=await run('readonly',(_,__,done,catalogs)=>{const request=catalogs.get(key);request.onsuccess=()=>done(request.result);});
      return generation===epoch && row && row.owner===owner && Date.now()>=row.savedAt
        && Date.now()-row.savedAt<catalogLimits.ttlMs && validCatalog(row.body) ? row.body : null;
    } catch (_) { return null; }
  }
  async function catalogPut(owner, resource, body, generation=epoch) {
    if(generation!==epoch||!validCatalog(body))return false;
    try {return await run('readwrite',(_,__,done,catalogs)=>{
      if(generation!==epoch)return done(false);
      const key=JSON.stringify([owner,resource]),savedAt=Date.now(),bytes=JSON.stringify(body).length*2;
      catalogs.put({key,owner,savedAt,bytes,body});
      const request=catalogs.getAll();request.onsuccess=()=>{
        const rows=request.result.sort((a,b)=>a.savedAt-b.savedAt);let total=rows.reduce((sum,row)=>sum+row.bytes,0),count=rows.length;
        for(const row of rows){if(row.key===key)continue;if(total<=catalogLimits.bytes&&count<=catalogLimits.count&&savedAt-row.savedAt<=catalogLimits.ttlMs)continue;catalogs.delete(row.key);total-=row.bytes;count--;}
        done(true);
      };
    });}catch(_){return false;}
  }
  async function clear(owner = null) {
    epoch++;
    try {
      return await run('readwrite', (images,index,done,catalogs) => {
        const result={ok:true,removed:0,catalogs_removed:0};done(result);
        const request = index.getAll(); request.onsuccess = () => {
          for (const row of request.result) if (owner == null || owner === row.owner) { images.delete(row.key); index.delete(row.key); result.removed++; }
          error = '';
        };
        const list=catalogs.getAll();list.onsuccess=()=>{for(const row of list.result)if(owner==null||owner===row.owner){catalogs.delete(row.key);result.catalogs_removed++;}};
      });
    } catch (_) { return { ok:false, removed:0 }; }
  }
  async function status(owner = null) {
    try {
      return await run('readonly', (_,index,done) => { const request=index.getAll();request.onsuccess=()=>{
        const rows=request.result.filter(row=>owner==null||row.owner===owner);
        done({ok:true,count:rows.length,bytes:rows.reduce((sum,row)=>sum+row.bytes,0),limits,error});
      }; });
    } catch (_) { return {ok:false,error:'图片缓存暂不可读取。',limits}; }
  }
  return Object.freeze({scope,get,put,clear,status,limits,catalogGet,catalogPut,catalogLimits,generation:()=>epoch});
})();
