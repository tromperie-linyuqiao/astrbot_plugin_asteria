/* Real Chrome, actual personal-space module and shared CSS, explicit synthetic
   read-only TLS projection. No Bot, model, production service or chat send. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const web = fileURLToPath(new URL('../web/', import.meta.url));
const base = fileURLToPath(new URL('../../../.runtime/personal_space_chat/', import.meta.url));
const label = process.argv.find(value => value.startsWith('--label='))?.slice(8) || new Date().toISOString().replace(/[^0-9]/g, '');
assert.match(label, /^[a-z0-9_]+$/);
const out = path.join(base, label); await fs.mkdir(out, {recursive: true});
const sourceFiles = ['chat-personal-space.js', 'chat-personal-space.css'];
const hashes = async () => Object.fromEntries(await Promise.all(sourceFiles.map(async name => [name, crypto.createHash('sha256').update(await fs.readFile(path.join(web, name))).digest('hex')])));
const report = {schema: 'texas.personal.chat.chrome.v1', at_utc: new Date().toISOString(), real_chrome: true, fixture_only: true, production_requests: 0, model_calls: 0, chat_sends: 0, checks: [], errors: [], sources_before: await hashes()};
const browser = await chromium.launch({headless: true, executablePath: process.env.ASTERIA_CHROME_PATH || undefined, args: ['--disable-background-networking']});
async function pageFor(width = 390, height = 844) {
  const page = await browser.newPage({viewport: {width, height}, reducedMotion: 'reduce'});
  page.on('pageerror', error => report.errors.push(error.message));
  await page.addInitScript(() => {
    window.state = {server: 'https://fixture.invalid', username: 'fixture-owner', authenticated: true, activeId: 'owned', sessionPersonaConfig: {configuredId: 'texas'}, messages: [{id: 'real-chat-sentinel', text: '真实聊天记录保持原样'}]};
    window.chatAuthEpoch = 1;
    const row = (kind, id, name, extra = {}) => ({kind, id, fields: {name, description: '一段普通的虚构生活资料。', event_ids: ['event-one'], character_ids: ['person-one'], ...extra}, source: 'tls.life.fixture', revision: 2, version: 2, created_at: 1793300000, updated_at: 1793386400, valid: true, archived: false, evidence_kind: 'roleplay_event'});
    const records = [
      row('space', 'space-one', '窗边的角落', {environment: '午后有阳光', area: '靠窗'}),
      row('item', 'item-one', '蓝色马克杯', {space_id: 'space-one', origin: 'user_gift', giver: '你', gifted_at: 1793300000, message_ref: 'operator-note'}),
      row('interest', 'interest-one', '手写字', {status: 'active', questions: ['什么样的字更舒展？'], explored: ['试着慢慢落笔'], worth_continuing: true, last_attended_at: 1793300000}),
      row('exploration', 'exploration-one', '观星 <img src=x onerror=alert(1)>', {interest_id: 'interest-one', status: 'planned', goal: '先认识几颗星', findings: ['尚未确认结果'], source_kind: 'terra_canon', sources: [{title: '安全资料', url: 'https://example.org/reference'}, {title: '危险参考', url: 'javascript:alert(1)'}], description: '<script>window.injected=true</script>'}),
      row('collection', 'collection-one', '雨天听的歌', {category: 'music', resource_id: 'track-fixture', resource_type: 'link', interest_id: 'interest-one'}),
      ...Array.from({length: 25}, (_, index) => row('collection', 'remote-' + index, '远处收藏 ' + index, {category: 'book'}))
    ];
    const f = window.__personal = {records, calls: [], flags: {}, deferred: [], notices: [], sources: [], saved: 0, closeLife: 0, sends: 0};
    f.scope = {persona: 'texas', scenario: 'fixture-scene', conversation: 'owned'};
    f.snapshot = JSON.stringify(state.messages);
    window.showNotice = text => f.notices.push(text); window.saveDraft = () => f.saved++; window.errorText = error => error.message;
    window.ChatSettingsHub = {close() {}}; window.ChatExperience = {close() {}};
    window.ChatLife = {closeActive() { f.closeLife++; }, openRecord(kind, id) { f.sources.push({kind, id}); }};
    window.apiClient = {json(method, route, body) {
      f.calls.push({method, route, body}); if (method !== 'GET' || !route.startsWith('/chat/life?')) throw Error('Fixture forbids writes and unrelated requests');
      const url = new URL(route, 'https://fixture.invalid'), p = url.searchParams;
      if (p.get('view') !== 'personal') throw Error('Personal projection must be explicit');
      const session_id = p.get('session_id'), id = p.get('id'), kind = p.get('kind'), query = p.get('query') || '', limit = Number(p.get('limit')), offset = Number(p.get('offset'));
      const responseScope = structuredClone(f.scope);
      const produce = () => {
        if (f.flags.http) throw Object.assign(Error('Fixture server unavailable'), {status: f.flags.http});
        if (f.flags.old) return {session_id, events: [], ongoing: [], people: []};
        const match = f.records.filter(value => (kind === 'all' || value.kind === kind) && (!query || Object.values(value.fields).filter(value => typeof value === 'string').join('\n').includes(query)));
        const overview = {spaces: f.records.filter(value => value.kind === 'space'), recent_collections: f.records.filter(value => value.kind === 'collection').slice(0, 8), active_interests: f.records.filter(value => value.kind === 'interest'), planned_explorations: f.records.filter(value => value.kind === 'exploration')};
        const selected = id ? f.records.find(value => value.id === id && value.kind === kind) : null;
        if (id && !selected) throw Object.assign(Error('Fixture record missing'), {status: 404});
        return {session_id: f.flags.wrongSession ? 'another' : session_id, scope: responseScope, evidence_kind: f.flags.wrongEvidence ? 'chat_message' : 'roleplay_event', status: {state: 'ready'}, personal: structuredClone({overview, records: match.slice(offset, offset + limit), total: match.length, ...(selected ? {record: selected, events: [{id: 'event-one', fields: {title: '午后书店'}}], people: [{id: 'person-one', fields: {name: '青禾'}}]} : {})})};
      };
      if (f.flags.defer) return new Promise((resolve, reject) => f.deferred.push(() => { try { resolve(produce()); } catch (error) { reject(error); } }));
      return Promise.resolve().then(produce);
    }, send() { f.sends++; throw Error('No chat send allowed'); }};
  });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); if (url.origin !== 'http://personal-fixture.invalid') return route.abort();
    const file = url.pathname.slice(1);
    if (!file) return route.fulfill({contentType: 'text/html', body: '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="app.css"><link rel="stylesheet" href="chat-personal-space.css"><script defer src="chat-personal-space.js"></script></head><body><main><textarea id="draft" maxlength="16000">原有\n多行草稿</textarea></main></body></html>'});
    if (!['app.css', ...sourceFiles].includes(file)) return route.abort();
    return route.fulfill({body: await fs.readFile(path.join(web, file)), contentType: file.endsWith('.css') ? 'text/css' : 'text/javascript'});
  });
  await page.goto('http://personal-fixture.invalid/');
  return page;
}
async function open(page) { await page.evaluate(() => ChatPersonalSpace.open()); await page.waitForFunction(() => document.querySelector('#personal-body')?.textContent.includes('全部资料')); }
async function choose(page, kind, title) { await page.locator('[data-personal-kind="' + kind + '"]').click(); await page.getByRole('button', {name: title, exact: true}).click(); await page.locator('#personal-follow-up').waitFor(); }
async function check(name, fn, width = 390, height = 844) {
  const result = {name, width, height}; report.checks.push(result); const page = await pageFor(width, height);
  try { result.details = await fn(page); assert.equal(await page.evaluate(() => __personal.sends), 0); assert.equal(await page.evaluate(() => __personal.calls.every(value => value.method === 'GET')), true); assert.equal(await page.evaluate(() => JSON.stringify(state.messages) === __personal.snapshot), true); result.passed = true; }
  catch (error) { result.passed = false; result.error = error.stack; await page.screenshot({path: path.join(out, name + '-' + width + '-failure.png')}); }
  finally { await page.close(); }
}
try {
  for (const width of [390, 1280]) await check('overview_five_kinds_detail_source_and_plain_text', async page => {
    await open(page); assert.equal(await page.locator('.personal-overview>.personal-card').count(), 4); assert.equal(await page.locator('.personal-tab').count(), 6);
    await choose(page, 'item', '蓝色马克杯'); assert.match(await page.locator('#personal-body').innerText(), /用户赠予（管理端记录，未核验）/); assert.match(await page.locator('#personal-body').innerText(), /尚未核验真实聊天依据/);
    await page.getByRole('button', {name: '所在空间：space-one', exact: true}).click(); await page.getByRole('heading', {name: '窗边的角落', exact: true}).waitFor(); assert.match(await page.locator('#personal-body').innerText(), /午后有阳光/);
    await page.locator('#personal-back').click(); await page.getByRole('heading', {name: '蓝色马克杯', exact: true}).waitFor(); await page.locator('#personal-back').click();
    await choose(page, 'exploration', '观星 <img src=x onerror=alert(1)>'); assert.equal(await page.locator('#personal-body img,#personal-body script').count(), 0); assert.match(await page.locator('#personal-body').innerText(), /泰拉资料（未核验）/); assert.equal(await page.locator('#personal-body a').count(), 1); assert.equal(await page.locator('#personal-body a').getAttribute('rel'), 'noopener noreferrer'); assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.screenshot({path: path.join(out, 'personal-detail-' + width + '.png')}); await page.getByRole('button', {name: '来源经历：午后书店', exact: true}).click(); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.deepEqual(await page.evaluate(() => __personal.sources), [{kind: 'event', id: 'event-one'}]);
    await open(page); await choose(page, 'interest', '手写字'); assert.match(await page.locator('#personal-body').innerText(), /待探索的问题/); await page.getByRole('button', {name: '关联人物：青禾', exact: true}).click(); assert.deepEqual(await page.evaluate(() => __personal.sources.at(-1)), {kind: 'character', id: 'person-one'});
    await open(page); await choose(page, 'collection', '雨天听的歌'); assert.match(await page.locator('#personal-body').innerText(), /收藏类别：音乐/); return {overview_sections: 4, record_kinds: 5, source_destinations: 2, unsafe_links: 0, edits: 0};
  }, width);
  await check('explicit_follow_up_only_appends_editable_draft', async page => {
    await open(page); await choose(page, 'interest', '手写字'); const before = await page.evaluate(() => __personal.calls.length); await page.locator('#personal-follow-up').click();
    assert.equal(await page.locator('#draft').inputValue(), '原有\n多行草稿\n\n[虚构生活资料 interest:interest-one] 关于「手写字」，最近有什么新想法，或者还想探索什么？'); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.equal(await page.evaluate(() => __personal.saved), 1); assert.equal(await page.evaluate(() => __personal.calls.length), before); assert.equal(await page.locator('#draft').isEditable(), true); return {draft_saved_once: true, follow_up_requests: 0, automatic_sends: 0};
  });
  await check('server_search_paging_and_reading_position', async page => {
    await open(page); await page.locator('#personal-search').fill('远处'); await page.locator('#personal-search').press('Enter'); await page.getByText('“远处” · 25 条记录', {exact: true}).waitFor(); assert.equal(await page.locator('[data-personal-record]').count(), 20);
    await page.getByRole('button', {name: '下一页', exact: true}).click(); await page.getByRole('button', {name: '远处收藏 24', exact: true}).waitFor(); assert.equal(await page.locator('[data-personal-record]').count(), 5); assert.equal(await page.locator('#personal-body').evaluate(node => node.scrollTop), 0);
    await page.getByRole('button', {name: '远处收藏 24', exact: true}).scrollIntoViewIfNeeded(); const before = await page.locator('#personal-body').evaluate(node => node.scrollTop); await page.getByRole('button', {name: '远处收藏 24', exact: true}).click(); await page.locator('#personal-follow-up').waitFor(); await page.locator('#personal-back').click(); const after = await page.locator('#personal-body').evaluate(node => node.scrollTop); assert(Math.abs(after - before) <= 1, 'list reading position ' + before + ' -> ' + after);
    await page.getByRole('button', {name: '上一页', exact: true}).click(); await page.getByRole('button', {name: '远处收藏 0', exact: true}).waitFor(); await page.locator('#personal-search-clear').click(); await page.getByText('全部资料 · 30 条记录', {exact: true}).waitFor();
    const offsets = await page.evaluate(() => __personal.calls.filter(value => new URL(value.route, 'https://fixture.invalid').searchParams.get('query') === '远处').map(value => new URL(value.route, 'https://fixture.invalid').searchParams.get('offset'))); assert.deepEqual(offsets, ['0', '20', '0']); return {server_search: true, offsets, return_scroll_restored: true};
  });
  await check('draft_guard_archived_invalid_long_and_readonly', async page => {
    await page.evaluate(() => { __personal.records[2].valid = false; }); await open(page); await choose(page, 'interest', '手写字'); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true);
    await page.evaluate(() => { __personal.records[2].valid = true; __personal.records[2].archived = true; }); await page.locator('#personal-refresh').click(); await page.getByText('已归档 · 仅供查阅', {exact: true}).first().waitFor(); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true);
    await page.evaluate(() => { __personal.records[2].archived = false; }); await page.locator('#personal-refresh').click(); await page.locator('#personal-follow-up').waitFor({state: 'visible'}); await page.waitForFunction(() => !document.querySelector('#personal-follow-up').disabled);
    await page.evaluate(() => { document.getElementById('draft').value = '原'.repeat(15999); }); await page.locator('#personal-follow-up').click(); assert.equal((await page.locator('#draft').inputValue()).length, 15999); assert.match(await page.locator('#personal-note').innerText(), /草稿过长/);
    await page.evaluate(() => { document.getElementById('draft').value = '只读草稿'; document.getElementById('draft').readOnly = true; }); await page.locator('#personal-follow-up').click(); assert.equal(await page.locator('#draft').inputValue(), '只读草稿'); assert.match(await page.locator('#personal-note').innerText(), /输入框只读/); assert.equal(await page.evaluate(() => __personal.saved), 0); return {guards: 4, draft_unchanged: true};
  });
  await check('unsupported_independent_server_and_retry', async page => {
    for (const flag of ['http', 'old']) { await page.evaluate(flag => { ChatPersonalSpace.closeActive(); __personal.flags = flag === 'http' ? {http: 404} : {old: true}; ChatPersonalSpace.open(); }, flag); await page.getByText(/独立服务端需更新/).first().waitFor(); assert.equal(await page.locator('#personal-follow-up').count(), 0); }
    await page.evaluate(() => { __personal.flags = {}; }); await page.locator('#personal-refresh').click(); await page.getByText('全部资料 · 30 条记录', {exact: true}).waitFor(); return {unsupported_old_projection: true, explicit_retry: true};
  });
  await check('late_scope_auth_close_and_server_scope_responses', async page => {
    await page.evaluate(() => { __personal.flags.defer = true; ChatPersonalSpace.open(); }); await page.waitForFunction(() => __personal.deferred.length === 1);
    await page.evaluate(() => { state.activeId = 'another'; ChatPersonalSpace.scopeChanged(); __personal.flags.defer = false; ChatPersonalSpace.open(); }); await page.getByText('全部资料 · 30 条记录', {exact: true}).waitFor(); await page.evaluate(() => __personal.deferred.shift()()); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), true);
    await page.evaluate(() => { __personal.flags.defer = true; }); await page.locator('[data-personal-kind="interest"]').click(); await page.waitForFunction(() => __personal.deferred.length === 1); await page.evaluate(() => { chatAuthEpoch++; ChatPersonalSpace.scopeChanged(); __personal.deferred.shift()(); }); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false);
    await page.evaluate(() => { __personal.flags.defer = false; ChatPersonalSpace.open(); }); await page.getByText('全部资料 · 30 条记录', {exact: true}).waitFor(); await page.evaluate(() => { __personal.scope.scenario = 'changed-scene'; }); await page.locator('#personal-refresh').click(); await page.waitForFunction(() => !document.querySelector('#personal-dialog').open); assert.match(await page.evaluate(() => __personal.notices.at(-1)), /资料范围已变化/); assert.equal(await page.locator('#draft').inputValue(), '原有\n多行草稿'); return {late_scope_ignored: true, late_auth_ignored: true, server_scope_invalidated: true};
  });
  await check('wrong_session_evidence_failure_and_failed_refresh', async page => {
    await page.evaluate(() => { __personal.flags.wrongSession = true; ChatPersonalSpace.open(); }); await page.getByText(/会话不匹配/).first().waitFor(); assert.equal(await page.locator('[data-personal-record]').count(), 0);
    await page.evaluate(() => { __personal.flags = {wrongEvidence: true}; }); await page.locator('#personal-refresh').click(); await page.getByText(/未标明虚构生活资料来源/).first().waitFor();
    await page.evaluate(() => { __personal.flags = {}; }); await page.locator('#personal-refresh').click(); await page.getByText('全部资料 · 30 条记录', {exact: true}).waitFor(); await choose(page, 'interest', '手写字'); await page.evaluate(() => { __personal.flags.http = 503; }); await page.locator('#personal-refresh').click(); await page.getByText(/当前保留的是上次读取的资料/).waitFor(); assert.equal(await page.locator('#personal-follow-up').isDisabled(), true); return {wrong_session_blocked: true, nonfiction_evidence_blocked: true, failed_refresh_cannot_compose: true};
  });
  for (const [width, height] of [[390, 844], [844, 390], [1280, 480]]) await check('viewport_containment_scroll_and_escape', async page => {
    await open(page); const bounds = await page.locator('#personal-dialog').boundingBox(); assert(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= height + 1); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); await page.screenshot({path: path.join(out, 'personal-overview-top-' + width + 'x' + height + '.png')});
    const bodyBounds = await page.locator('#personal-body').boundingBox(); assert(bodyBounds.height >= 45, 'reading area remains usable'); await page.getByRole('button', {name: '下一页', exact: true}).scrollIntoViewIfNeeded(); assert((await page.locator('#personal-body').evaluate(node => node.scrollTop)) > 0); await page.screenshot({path: path.join(out, 'personal-overview-' + width + 'x' + height + '.png')}); await page.keyboard.press('Escape'); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.equal(await page.locator('#personal-body').textContent(), ''); return {contained: true, scrollable: true, escape_clears_data: true};
  }, width, height);
} finally {
  await browser.close(); report.sources_after = await hashes(); report.sources_stable = JSON.stringify(report.sources_before) === JSON.stringify(report.sources_after); report.passed = report.errors.length === 0 && report.sources_stable && report.checks.every(value => value.passed);
  await fs.writeFile(path.join(out, 'result.safe.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({passed: report.passed, checks: report.checks, errors: report.errors, evidence: path.join(out, 'result.safe.json')})); process.exitCode = report.passed ? 0 : 1;
}
