/* One real-index integration fixture. All shipped scripts, hub navigation,
   Android-back callback and scope hooks run unchanged. Services are local data. */
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
const out = fileURLToPath(new URL('../../../.runtime/personal_space_chat/assembled_' + label + '/', import.meta.url)); await fs.mkdir(out, {recursive: true});
const names = ['index.html', 'app.js', 'chat-hub.js', 'chat-life.js', 'chat-personal-space.js', 'chat-personal-space.css'];
const hashes = async () => Object.fromEntries(await Promise.all(names.map(async name => [name, crypto.createHash('sha256').update(await fs.readFile(path.join(web, name))).digest('hex')])));
const report = {schema: 'texas.personal.chat.assembled.chrome.v1', at_utc: new Date().toISOString(), real_chrome: true, fixture_only: true, actual_index: true, module_stubs: false, production_requests: 0, model_calls: 0, chat_sends: 0, checks: [], errors: [], blocked_external_requests: 0, sources_before: await hashes()};
const browser = await chromium.launch({headless: true, executablePath: process.env.ASTERIA_CHROME_PATH || undefined, args: ['--disable-background-networking']});
const page = await browser.newPage({viewport: {width: 390, height: 844}, reducedMotion: 'reduce'}); page.setDefaultTimeout(5000); page.on('pageerror', error => report.errors.push(error.message));
try {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); if (url.origin !== 'http://personal-assembled.invalid') { report.blocked_external_requests++; return route.abort(); }
    const name = decodeURIComponent(url.pathname).replace(/^\//, '') || 'index.html'; if (name.includes('..')) return route.abort();
    try { return route.fulfill({body: await fs.readFile(path.join(web, name)), contentType: name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : name.endsWith('.html') ? 'text/html' : name.endsWith('.svg') ? 'image/svg+xml' : 'image/png'}); } catch { return route.abort(); }
  });
  await page.addInitScript(() => { window.AsteriaChat = {getConfig: () => JSON.stringify({server: 'https://fixture.invalid', authenticated: false, foreground: true, version: 'personal-assembled-fixture'}), setChromeTheme() {}, clearAuth() {}, request() { throw Error('Fixture forbids native service requests'); }}; });
  await page.goto('http://personal-assembled.invalid/');
  await page.evaluate(() => {
    const record = (id, fields, extra = {}) => ({id, fields, revision: 1, version: 1, valid: true, archived: false, source: 'tls.life.fixture', evidence_kind: 'roleplay_event', created_at: 1793300000, updated_at: 1793300000, ...extra});
    const event = record('event-one', {title: '午后旧书摊', content: '在书摊见到青禾，挑选一本手记。', status: 'completed', occurred_at: 1793300000, character_ids: ['person-one'], previous_event_ids: []});
    const person = record('person-one', {name: '青禾', kind: 'recurring', description: '街角的旧书摊主。', relationship: '偶尔相遇。', event_ids: ['event-one']});
    const interest = record('interest-one', {name: '手写字', description: '想慢慢练习落笔。', status: 'active', questions: ['怎样写得更舒展？'], event_ids: ['event-one'], character_ids: ['person-one']}, {kind: 'interest'});
    const f = window.__assembled = {calls: [], sends: 0, deferred: [], defer: false, event, person, interest};
    apiClient.json = async (method, route, body) => {
      f.calls.push({method, route, body: structuredClone(body)}); if (method !== 'GET') throw Error('Fixture forbids mutation');
      if (!route.startsWith('/chat/life?')) { if (route.startsWith('/chat/user-avatar')) return {revision: 0, data_url: null}; if (route.startsWith('/chat/actions')) return {items: [], revision: 0, native_touch: {available: false, verbs: [], parts: []}}; if (route.startsWith('/chat/expressions')) return {items: [], total: 0}; return {items: [], linked: false}; }
      const p = new URL(route, 'https://fixture.invalid').searchParams, session_id = p.get('session_id');
      const produce = () => {
        if (p.get('view') === 'personal') return {session_id, evidence_kind: 'roleplay_event', scope: {persona: 'fixture-persona', scenario: 'fixture', conversation: session_id}, status: {state: 'ready'}, personal: {overview: {spaces: [], recent_collections: [], active_interests: [interest], planned_explorations: []}, records: [structuredClone(interest)], total: 1, ...(p.has('id') ? {record: structuredClone(interest), events: [structuredClone(event)], people: [structuredClone(person)]} : {})}};
        if (p.has('event_id')) return {session_id, event: structuredClone(event), history: [], related: {people: [structuredClone(person)], previous: [], following: []}, threads: [], shares: []};
        if (p.has('person_id')) return {session_id, person: structuredClone(person), events: [structuredClone(event)]};
        return {session_id, events: [structuredClone(event)], people: [structuredClone(person)], ongoing: [], policy: {enabled: false}, status: {state: 'disabled', share_enabled: false}};
      };
      if (f.defer && p.get('view') === 'personal') return new Promise(resolve => f.deferred.push(() => resolve(produce())));
      return produce();
    };
    apiClient.send = () => { f.sends++; throw Error('Fixture forbids chat send'); };
    state.server = 'https://fixture.invalid'; state.username = 'fixture-owner'; state.authenticated = true; state.bridgeAvailable = true; state.activeId = 'owned'; state.sessions = [{session_id: 'owned', primary: true, tls_state: {mode: 'chat'}}, {session_id: 'other'}]; state.primaryId = 'owned'; state.primaryAccount = state.server + '|' + state.username; state.sessionPersonaConfig = {sessionId: 'owned', configuredId: 'fixture-persona', status: 'configured'};
    state.messages = [{id: 'saved-chat', serverId: 9, role: 'assistant', text: '原有聊天内容', parts: [{type: 'plain', text: '原有聊天内容'}], delivery: 'confirmed'}]; f.messagesBefore = JSON.stringify(state.messages);
    foregroundRecovery.cancel('personal assembled fixture', true); foregroundRecovery.stateChanged = () => {}; renderMessages(); $('draft').value = '保持原有聊天草稿'; renderChrome();
  });
  await page.waitForFunction(() => document.getElementById('menu-personal-space')?.parentElement.id === 'hub-role');
  assert.equal(await page.locator('script[src="chat-personal-space.js"]').count(), 1); assert.equal(await page.locator('link[href="chat-personal-space.css"]').count(), 1); assert.equal(await page.locator('#menu-personal-space').count(), 1);
  await page.evaluate(() => ChatSettingsHub.openSection('role')); await page.locator('#menu-personal-space').click(); await page.getByText('全部资料 · 1 条记录', {exact: true}).waitFor(); assert.equal(await page.locator('#settings-hub-dialog').evaluate(node => node.open), false);
  report.checks.push('Actual index loads module once; actual role/settings doorway opens personal modal and closes settings.');
  await page.locator('[data-personal-record="interest:interest-one"] .personal-record-title').click(); await page.locator('#personal-follow-up').waitFor(); await page.getByRole('button', {name: '来源经历：午后旧书摊', exact: true}).click(); await page.getByRole('button', {name: '追问这段经历', exact: true}).waitFor();
  assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.equal(await page.locator('#life-dialog').evaluate(node => node.open), true); assert.match(await page.locator('#life-body').innerText(), /在书摊见到青禾/);
  report.checks.push('Actual ChatLife.openRecord(event,id) reads the event source and closes personal modal.');
  await page.locator('#life-dialog .life-intro').getByRole('button', {name: '私人空间与兴趣', exact: true}).click(); await page.getByText('全部资料 · 1 条记录', {exact: true}).waitFor(); assert.equal(await page.locator('#life-dialog').evaluate(node => node.open), false);
  await page.locator('[data-personal-record="interest:interest-one"] .personal-record-title').click(); await page.locator('#personal-follow-up').waitFor(); await page.getByRole('button', {name: '关联人物：青禾', exact: true}).click(); await page.getByRole('button', {name: '聊聊这个人', exact: true}).waitFor(); assert.match(await page.locator('#life-body').innerText(), /街角的旧书摊主/);
  report.checks.push('Life doorway opens personal modal; actual character source navigation reads the correct person.');
  assert.equal(await page.evaluate(() => AsteriaChatUI.back()), true); assert.equal(await page.locator('#life-dialog').evaluate(node => node.open), false);
  await page.evaluate(() => ChatSettingsHub.openSection('role')); await page.locator('#menu-personal-space').click(); await page.getByText('全部资料 · 1 条记录', {exact: true}).waitFor(); await page.screenshot({path: path.join(out, 'actual-index-settings-personal-390.png')});
  assert.equal(await page.evaluate(() => AsteriaChatUI.back()), true); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.equal(await page.locator('#personal-body').textContent(), '');
  report.checks.push('Actual AsteriaChatUI.back closes either current modal and clears personal view data.');
  await page.evaluate(() => { __assembled.defer = true; ChatPersonalSpace.open(); }); await page.waitForFunction(() => __assembled.deferred.length === 1);
  await page.evaluate(() => { state.activeId = 'other'; renderChrome(); __assembled.deferred.shift()(); }); assert.equal(await page.locator('#personal-dialog').evaluate(node => node.open), false); assert.equal(await page.locator('#personal-body').textContent(), '');
  report.checks.push('Actual renderChrome scope hook closes personal view and discards the late prior-session response.');
  assert.equal(await page.locator('#draft').inputValue(), '保持原有聊天草稿'); assert.equal(await page.evaluate(() => JSON.stringify(state.messages) === __assembled.messagesBefore), true); assert.equal(await page.evaluate(() => __assembled.sends), 0); assert.equal(await page.evaluate(() => __assembled.calls.every(value => value.method === 'GET')), true);
  const calls = await page.evaluate(() => __assembled.calls.filter(value => value.route.startsWith('/chat/life?'))); assert(calls.some(value => value.route.includes('event_id=event-one'))); assert(calls.some(value => value.route.includes('person_id=person-one'))); report.life_calls = calls; report.passed = report.errors.length === 0;
} catch (error) { report.passed = false; report.failure = error.stack; await page.screenshot({path: path.join(out, 'assembled-failure.png')}); }
finally { await browser.close(); report.sources_after = await hashes(); report.sources_stable = JSON.stringify(report.sources_before) === JSON.stringify(report.sources_after); report.passed &&= report.sources_stable; await fs.writeFile(path.join(out, 'result.safe.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify({passed: report.passed, checks: report.checks, errors: report.errors, failure: report.failure, evidence: path.join(out, 'result.safe.json')})); process.exitCode = report.passed ? 0 : 1; }
