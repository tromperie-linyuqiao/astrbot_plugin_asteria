/* Focused resource-reference UI checks in real Chrome. Only local synthetic
   projections; no resource fetch, file preview, model, production or chat send. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const web = fileURLToPath(new URL('../web/', import.meta.url));
const label = process.argv.find(value => value.startsWith('--label='))?.slice(8) || new Date().toISOString().replace(/[^0-9]/g, ''); assert.match(label, /^[a-z0-9_]+$/);
const out = fileURLToPath(new URL('../../../.runtime/personal_space_chat/resources_' + label + '/', import.meta.url)); await fs.mkdir(out, {recursive: true});
const names = ['chat-personal-space.js', 'chat-personal-space.css'];
const hashes = async () => Object.fromEntries(await Promise.all(names.map(async name => [name, crypto.createHash('sha256').update(await fs.readFile(path.join(web, name))).digest('hex')])));
const report = {schema: 'texas.personal.resources.chat.chrome.v1', at_utc: new Date().toISOString(), real_chrome: true, fixture_only: true, production_requests: 0, resource_fetches: 0, model_calls: 0, chat_sends: 0, checks: [], errors: [], blocked_external_requests: 0, sources_before: await hashes()};
const browser = await chromium.launch({headless: true, executablePath: process.env.ASTERIA_CHROME_PATH || undefined, args: ['--disable-background-networking']});
async function pageFor(width = 390, height = 844) {
  const page = await browser.newPage({viewport: {width, height}, reducedMotion: 'reduce'}); page.setDefaultTimeout(5000); page.on('pageerror', error => report.errors.push(error.message));
  await page.addInitScript(() => {
    window.state = {server: 'https://fixture.invalid', username: 'fixture-owner', activeId: 'owned', authenticated: true, sessionPersonaConfig: {configuredId: 'texas'}, messages: [{id: 'sentinel', text: '原有真实聊天'}]}; window.chatAuthEpoch = 1;
    const row = (id, name, resource, extra = {}) => ({id, kind: 'collection', fields: {name, description: '这是收藏条目的备注。', category: resource?.type === 'image' ? 'image' : 'music', resource_type: resource?.type || 'music', resource_id: 'C:\\Users\\secret-owner\\private-track.json', event_ids: ['event-one'], character_ids: ['person-one']}, revision: 1, version: 1, valid: true, archived: false, source: 'tls.life.fixture', created_at: 1793300000, updated_at: 1793300000, resource, ...extra});
    const scope = {server: 'source-private-server', owner: 'secret-owner', conversation: 'source-private-conversation'};
    const music = {state: 'available', status: 'available', type: 'music', available: true, id: 'private-resource-id', revision: 3, expected_revision: 3, name: '原音乐库名称', source_scope: scope, metadata: {title: '雨后的街道', artist: '虚构演奏者', album: '慢行', tags: ['雨天', '器乐'], url: 'https://private.example/stream', path: '/home/secret-owner/music.mp3', owner: 'secret-owner'}};
    const image = {state: 'available', status: 'available', type: 'image', available: true, id: 'private-image-id', revision: 4, expected_revision: 4, name: '旧街的光', source_scope: scope, preview_url: 'https://private.example/image', metadata: {title: '旧街的光', caption: '路灯刚刚亮起的街角。', tags: ['街道', '傍晚'], thumbnail_url: 'https://private.example/thumbnail', filename: 'C:\\Users\\secret-owner\\image.png'}};
    const changed = {...structuredClone(music), state: 'changed', status: 'changed', revision: 4, metadata: {title: '更新后的旋律', artist: '新的演奏者', album: '新版唱片'}};
    const f = window.__resources = {records: [row('music-one', '雨天的音乐收藏', music), row('image-one', '街角图片收藏', image), row('changed-one', '旧版本音乐收藏', changed, {valid: false}), row('legacy-one', '早先手填的收藏', undefined)], calls: [], notices: [], sourceLinks: [], saved: 0, sends: 0, deferred: [], defer: false}; f.messagesBefore = JSON.stringify(state.messages);
    window.showNotice = value => f.notices.push(value); window.saveDraft = () => f.saved++; window.errorText = error => error.message;
    window.ChatSettingsHub = {close() {}}; window.ChatExperience = {close() {}}; window.ChatLife = {closeActive() {}, openRecord(kind, id) { f.sourceLinks.push({kind, id}); }};
    window.apiClient = {json(method, route) {
      f.calls.push({method, route}); if (method !== 'GET' || !route.startsWith('/chat/life?')) throw Error('Fixture forbids writes and resource requests');
      const p = new URL(route, 'https://fixture.invalid').searchParams; if (p.get('view') !== 'personal') throw Error('Expected personal view');
      const session_id = p.get('session_id'), id = p.get('id'), kind = p.get('kind'), query = p.get('query') || '';
      const selected = f.records.find(value => value.id === id), records = f.records.filter(value => (kind === 'all' || kind === 'collection') && (!query || value.fields.name.includes(query)));
      const result = {session_id, scope: {persona: 'texas', conversation: session_id}, evidence_kind: 'roleplay_event', status: {state: 'ready'}, personal: structuredClone({overview: {spaces: [], recent_collections: records, active_interests: [], planned_explorations: []}, records, total: records.length, ...(selected ? {record: selected, events: [{id: 'event-one', fields: {title: '路过书摊'}}], people: [{id: 'person-one', fields: {name: '青禾'}}]} : {})})};
      if (f.defer) return new Promise(resolve => f.deferred.push(() => resolve(result))); return Promise.resolve(result);
    }, send() { f.sends++; throw Error('Fixture forbids send'); }};
  });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); if (url.origin !== 'http://resource-ui-fixture.invalid') { report.blocked_external_requests++; return route.abort(); }
    const name = url.pathname.slice(1);
    if (!name) return route.fulfill({contentType: 'text/html', body: '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="app.css"><link rel="stylesheet" href="chat-personal-space.css"><script defer src="chat-personal-space.js"></script></head><body><textarea id="draft" maxlength="16000">保留原来的草稿</textarea></body></html>'});
    if (!['app.css', ...names].includes(name)) { report.resource_fetches++; return route.abort(); }
    return route.fulfill({body: await fs.readFile(path.join(web, name)), contentType: name.endsWith('.css') ? 'text/css' : 'text/javascript'});
  });
  await page.goto('http://resource-ui-fixture.invalid/'); await page.evaluate(() => ChatPersonalSpace.open()); await page.getByText('全部资料 · 4 条记录', {exact: true}).waitFor(); return page;
}
async function choose(page, id) { await page.locator('[data-personal-record="collection:' + id + '"] .personal-record-title').click(); await page.locator('.personal-resource').waitFor(); }
async function noPrivateData(page) { const dom = await page.locator('#personal-dialog').evaluate(node => node.outerHTML); for (const text of ['secret-owner', 'private.example', 'private-resource-id', 'private-image-id', 'source-private', '/home/', 'Users\\', 'source_scope', 'preview_url']) assert.equal(dom.includes(text), false, 'private source field leaked: ' + text); assert.equal(await page.locator('.personal-resource img,.personal-resource audio,.personal-resource video,.personal-resource source,.personal-resource a,.personal-resource iframe').count(), 0); }
async function check(name, fn, width = 390, height = 844) {
  const result = {name, width, height}; report.checks.push(result); const page = await pageFor(width, height);
  try { result.details = await fn(page); await noPrivateData(page); assert.equal(await page.evaluate(() => __resources.calls.every(value => value.method === 'GET' && value.route.startsWith('/chat/life?'))), true); assert.equal(await page.evaluate(() => __resources.sends), 0); assert.equal(await page.evaluate(() => JSON.stringify(state.messages) === __resources.messagesBefore), true); result.passed = true; }
  catch (error) { result.passed = false; result.error = error.stack; await page.screenshot({path: path.join(out, name + '-failure.png')}); }
  finally { await page.close(); }
}
try {
  await check('current_music_metadata_search_and_local_draft', async page => {
    await page.locator('[data-personal-kind="collection"]').click(); await page.getByText('收藏 · 4 条记录', {exact: true}).waitFor(); assert.match(await page.locator('[data-personal-record="collection:changed-one"]').innerText(), /来源待复核/);
    await page.locator('#personal-search').fill('雨天'); await page.locator('#personal-search').press('Enter'); await page.getByText('“雨天” · 1 条记录', {exact: true}).waitFor(); await choose(page, 'music-one');
    assert.equal(await page.locator('.personal-resource').getAttribute('data-resource-state'), 'available'); const text = await page.locator('.personal-resource').innerText(); for (const expected of ['雨后的街道', '音乐人：虚构演奏者', '专辑：慢行', '雨天、器乐', '原资源当前资料']) assert(text.includes(expected)); assert.equal(await page.locator('#personal-follow-up').isEnabled(), true); await noPrivateData(page);
    await page.screenshot({path: path.join(out, 'music-current-390.png')}); const before = await page.evaluate(() => __resources.calls.length); await page.locator('#personal-follow-up').click(); assert.match(await page.locator('#draft').inputValue(), /^保留原来的草稿\n\n\[虚构生活资料 collection:music-one\]/); assert.equal(await page.evaluate(() => __resources.calls.length), before); assert.equal(await page.evaluate(() => __resources.saved), 1); return {actual_metadata_fields: 4, read_only_search: true, draft_only: true};
  });
  await check('current_image_text_metadata_no_preview_or_private_paths', async page => {
    await choose(page, 'image-one'); assert.match(await page.locator('.personal-resource').innerText(), /图片资料/); assert.match(await page.locator('.personal-resource').innerText(), /旧街的光/); assert.match(await page.locator('.personal-resource').innerText(), /路灯刚刚亮起的街角/); await noPrivateData(page); await page.screenshot({path: path.join(out, 'image-metadata-390.png')}); await page.getByRole('button', {name: '来源经历：路过书摊', exact: true}).click(); assert.deepEqual(await page.evaluate(() => __resources.sourceLinks), [{kind: 'event', id: 'event-one'}]); return {caption_and_tags: true, previews: 0, source_link_preserved: true};
  });
  await check('changed_record_is_readable_and_needs_review', async page => {
    await choose(page, 'changed-one'); const text = await page.locator('.personal-resource').innerText(); assert(text.includes('来源待复核')); assert(text.includes('更新后的旋律')); assert(text.includes('收藏引用的版本已变化')); assert(text.includes('TLSWebUI')); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true); assert.equal(await page.getByRole('button', {name: /核对|保存|收进|采集|收藏此/}).count(), 0); await page.screenshot({path: path.join(out, 'changed-needs-review-390.png')}); return {invalid_record_readable: true, current_metadata: true, chat_and_admin_actions: false};
  });
  await check('unavailable_states_never_reuse_cached_resource_metadata', async page => {
    await choose(page, 'music-one'); const labels = {missing: '原资源已不存在', denied: '原资源不可读取', archived: '原资源已归档', unverified: '资源引用待核对'};
    for (const [state, label] of Object.entries(labels)) {
      await page.evaluate(state => { const r = __resources.records[0].resource; r.state = r.status = state; r.name = 'STALE_PRIVATE_NAME'; r.metadata = {title: 'STALE_PRIVATE_TITLE', artist: 'STALE_PRIVATE_ARTIST', caption: 'STALE_PRIVATE_CAPTION', tags: ['STALE_PRIVATE_TAG']}; }, state);
      await page.locator('#personal-refresh').click(); await page.locator('.personal-resource .personal-resource-chip').filter({hasText: label}).waitFor(); const text = await page.locator('#personal-body').innerText(); assert.equal(text.includes('STALE_PRIVATE'), false); assert.equal(text.includes('雨后的街道'), false); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true); await noPrivateData(page);
    }
    await page.screenshot({path: path.join(out, 'unverified-reference-390.png')}); return {states: Object.keys(labels), stale_metadata_rendered: false};
  });
  await check('revision_mismatch_legacy_manual_ids_and_metadata_allowlist', async page => {
    await choose(page, 'music-one'); await page.evaluate(() => { const r = __resources.records[0].resource; r.expected_revision = 1; r.metadata.title = '元数据中的 <img src=x onerror=alert(1)>'; r.metadata.artist = 'https://private.example/artist'; r.metadata.album = 'C:\\Users\\secret-owner\\album'; r.metadata.tags = ['正常标签', '/home/secret-owner/tag', 'file:///private/data']; }); await page.locator('#personal-refresh').click(); await page.locator('.personal-resource[data-resource-state="changed"]').waitFor(); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true); assert.match(await page.locator('.personal-resource').innerText(), /元数据中的 <img/); assert.equal(await page.locator('#personal-body img,#personal-body script').count(), 0); await noPrivateData(page);
    await page.locator('#personal-back').click(); await choose(page, 'legacy-one'); assert.equal(await page.locator('.personal-resource').getAttribute('data-resource-state'), 'unverified'); assert.match(await page.locator('.personal-resource').innerText(), /未作为真实资源展示/); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true); return {revision_mismatch_warned: true, manual_id_unverified: true, plain_text_safe: true};
  });
  await check('resource_refresh_scope_and_compact_landscape', async page => {
    await choose(page, 'music-one'); const bounds = await page.locator('#personal-dialog').boundingBox(); assert(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= 845 && bounds.y + bounds.height <= 391); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); const area = await page.locator('#personal-body').boundingBox(); assert(area.height >= 45); await page.screenshot({path: path.join(out, 'music-current-landscape.png')});
    await page.evaluate(() => { __resources.defer = true; }); await page.locator('#personal-refresh').click(); await page.waitForFunction(() => __resources.deferred.length === 1); await page.evaluate(() => { state.activeId = 'other'; ChatPersonalSpace.scopeChanged(); __resources.deferred.shift()(); }); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.equal(await page.locator('#personal-body').textContent(), ''); assert.equal(await page.locator('#draft').inputValue(), '保留原来的草稿'); return {late_scope_ignored: true, mobile_height_usable: true};
  }, 844, 390);
} finally {
  await browser.close(); report.sources_after = await hashes(); report.sources_stable = JSON.stringify(report.sources_before) === JSON.stringify(report.sources_after); report.passed = report.errors.length === 0 && report.resource_fetches === 0 && report.blocked_external_requests === 0 && report.sources_stable && report.checks.every(value => value.passed); await fs.writeFile(path.join(out, 'result.safe.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({passed: report.passed, checks: report.checks, errors: report.errors, resource_fetches: report.resource_fetches, blocked_external_requests: report.blocked_external_requests, evidence: path.join(out, 'result.safe.json')})); process.exitCode = report.passed ? 0 : 1;
}
