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
const out = fileURLToPath(new URL('../../../.runtime/voice_cloud_r108/browser_' + label + '/', import.meta.url)); await fs.mkdir(out, {recursive: true});
const names = ['index.html', 'app.js', 'chat-hub.js', 'chat-life.js', 'chat-personal-space.js', 'chat-personal-space.css','chat-voice.js','chat-voice.css'];
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
  await page.addInitScript(() => {window.AsteriaChat={getConfig:()=>JSON.stringify({server:'https://fixture.invalid',authenticated:false,foreground:true,version:'voice-fixture'}),setChromeTheme(){},clearAuth(){},request(){throw Error('No native transport in browser fixture');}};});
  await page.goto('http://personal-assembled.invalid/');await page.locator('#menu-voice').waitFor({state:'attached'});
  await page.evaluate(()=>{
    window.f={calls:[],native:[],revision:0,saved:null,asr:null};
    state.server='https://fixture.invalid';state.username='voice-owner';state.authenticated=true;state.bridgeAvailable=true;state.activeId='owned';state.sessions=[{session_id:'owned',primary:true,tls_state:{mode:'chat'}}];state.primaryId='owned';
    foregroundRecovery.cancel('voice fixture',true);foregroundRecovery.stateChanged=()=>{};
    f.defaults={name:'独立音色',language:'zh-CN',timbre:'自然清晰',pronunciation:'普通话',emotion:'平静',pauses:'按原文标点',rate:0.95,pitch:1,binding:{service:'android_system',voice_id:''},rights:'system_voice',test_sample:'这是一句独立试听。'};
    apiClient.json=async(method,url,body)=>{f.calls.push({method,url,body});if(url.startsWith('/chat/voice')){if(method==='POST'){f.saved=structuredClone(body.profile);f.revision++;}return{session_id:'owned',profile:structuredClone(f.saved||f.defaults),revision:f.revision};}if(url.startsWith('/chat/life')){const p=new URLSearchParams(url.split('?')[1]);const row={id:'interest1',kind:'interest',fields:{name:'音乐的故事',origin_note:'一次记录中的讨论',next_direction:'继续了解乐器',attention:'growing',status:'active',questions:[],explored:[],event_ids:[],character_ids:[]},valid:true,revision:1,archived:false,created_at:1800000000,updated_at:1800000000};return{session_id:'owned',evidence_kind:'roleplay_event',scope:{private:true},status:{state:'paused_budget'},personal:p.get('id')?{record:row,links:[{...row,id:'collection1',kind:'collection',fields:{name:'相关笔记',category:'note'}}]}:{records:[row],total:1}};}throw Error('unexpected '+url);};
    nativeAsync=async(method,args)=>{f.native.push({method,args:structuredClone(args)});if(method==='recognizeSpeech')return new Promise(resolve=>{f.asr=resolve;});const request=JSON.parse(args[1]);if(request.action==='voices')return{ok:true,voices:[{id:'fixture-cn',language:'zh-CN',network:false}]};return{ok:true,phase:request.action==='speak'?'synthesizing':request.action==='pause'?'paused':request.action==='resume'?'playing':'stopped',message_id:request.message_id||'saved1'};};
    state.messages=[{id:'saved1',serverId:1,role:'assistant',text:'不能替换原文',parts:[{type:'action',text:'动作不朗读',description:'轻轻点头'},{type:'plain',text:'今天辛苦了。'},{type:'sticker',asset_id:'one'}],delivery:'confirmed'}];renderMessages();renderChrome();$('draft').value='原有草稿';
  });
  await page.evaluate(()=>{f.defaults.language='ja-JP';});await page.locator('#voice-button').click();await page.waitForFunction(()=>!!f.asr);assert.equal(await page.evaluate(()=>f.native.find(x=>x.method==='recognizeSpeech').args[1]),'ja-JP');await page.evaluate(()=>{f.asr({cancelled:true});f.native=[];f.asr=null;f.defaults.language='zh-CN';});
  await page.evaluate(()=>ChatSettingsHub.openSection('interaction'));await page.locator('#menu-voice').click();await page.getByText(/已读取 TLS 声音档案/).waitFor();
  await page.locator('#voice-rate').fill('1.1');await page.locator('#voice-voice_id').selectOption('fixture-cn');await page.locator('#voice-save').click();await page.getByText('声音档案已保存，之后的朗读使用新配置。').waitFor();
  assert.equal(await page.evaluate(()=>f.saved.rate),1.1);assert.equal(await page.evaluate(()=>f.saved.binding.voice_id),'fixture-cn');
  await page.getByRole('button',{name:'试听',exact:true}).click();await page.waitForFunction(()=>f.native.some(x=>x.method==='voiceCommand'&&JSON.parse(x.args[1]).action==='speak'));
  assert.equal(await page.evaluate(()=>f.calls.filter(x=>x.method==='POST').length),1);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.screenshot({path:path.join(out,'voice-profile-390.png')});assert.equal(await page.evaluate(()=>AsteriaChatUI.back()),true);
  await page.evaluate(()=>ChatVoice.speak(state.messages[0]));await page.waitForFunction(()=>f.native.filter(x=>x.method==='voiceCommand'&&JSON.parse(x.args[1]).action==='speak').length===2);
  const speech=await page.evaluate(()=>JSON.parse(f.native.filter(x=>x.method==='voiceCommand'&&JSON.parse(x.args[1]).action==='speak').at(-1).args[1]));assert.equal(speech.text,'今天辛苦了。');assert.equal(speech.message_id,'1');
  await page.evaluate(()=>ChatVoice.receive({phase:'playing',duration_ms:8000,position_ms:1200}));await page.locator('#voice-playback').getByRole('button',{name:'暂停',exact:true}).click();await page.locator('#voice-playback').getByRole('button',{name:'继续',exact:true}).waitFor();
  await page.locator('#voice-button').click();await page.waitForFunction(()=>!!f.asr);await page.evaluate(()=>f.asr({text:'语音补充',session_id:'owned'}));await page.waitForFunction(()=>$('draft').value.includes('语音补充'));assert.deepEqual((await page.locator('#draft').inputValue()).split(String.fromCharCode(10)),['原有草稿','语音补充']);
  await page.locator('#voice-button').click();await page.waitForFunction(()=>f.native.filter(x=>x.method==='recognizeSpeech').length===2);await page.evaluate(()=>{state.activeId='other';renderChrome();f.asr({text:'旧会话结果',session_id:'owned'});});await page.waitForTimeout(50);assert(!(await page.locator('#draft').inputValue()).includes('旧会话结果'));assert.equal(await page.locator('#voice-playback').isVisible(),false);
  await page.evaluate(()=>{
    state.activeId='owned';renderChrome();const original=apiClient.json, native=nativeAsync;
    f.cloud={available:true,label:'渊站 · 语音',model:'s2.1-pro',models:['s2.1-pro'],max_characters:1500};
    apiClient.json=async(method,url,body)=>{if(url==='/chat/voice/synthesize'){f.calls.push({method,url,body});return{session_id:'owned',audio_id:'a'.repeat(64),cached:false};}const result=await original(method,url,body);if(url.startsWith('/chat/voice'))result.cloud=f.cloud;return result;};
    nativeAsync=async(method,args)=>{if(method==='playCloudVoice'){f.native.push({method,args});ChatVoice.receive({phase:'playing',message_id:args[2],duration_ms:3000,position_ms:0});return{ok:true};}return native(method,args);};
    ChatVoice.open();
  });
  await page.getByText(/已读取 TLS 声音档案/).waitFor();await page.locator('#voice-engine').selectOption('fish_tts');assert.equal(await page.locator('#voice-pitch').isDisabled(),true);
  await page.locator('#voice-save').click();await page.getByText('声音档案已保存，之后的朗读使用新配置。').waitFor();assert.equal(await page.evaluate(()=>f.saved.binding.service),'fish_tts');assert.equal(await page.evaluate(()=>f.saved.binding.model),'s2.1-pro');
  await page.getByRole('button',{name:'试听',exact:true}).click();await page.waitForFunction(()=>f.native.some(x=>x.method==='playCloudVoice'));assert.equal(await page.evaluate(()=>f.calls.filter(x=>x.url==='/chat/voice/synthesize').length),1);
  await page.screenshot({path:path.join(out,'cloud-voice-390.png')});await page.evaluate(()=>AsteriaChatUI.back());await page.evaluate(()=>ChatVoice.speak(state.messages[0]));await page.waitForFunction(()=>f.native.filter(x=>x.method==='playCloudVoice').length===2);
  assert.deepEqual(await page.evaluate(()=>f.calls.filter(x=>x.url==='/chat/voice/synthesize').at(-1).body),{session_id:'owned',message_id:'1'});
  await page.evaluate(()=>{state.activeId='owned';renderChrome();ChatPersonalSpace.open();});await page.locator('[data-personal-kind="interest"]').click();await page.locator('[data-archive-filter="status"]').selectOption('active');await page.waitForFunction(()=>f.calls.some(x=>x.url.includes('status=active')));await page.locator('.personal-record-title').first().click();await page.getByText('继续了解乐器',{exact:true}).waitFor();await page.getByRole('button',{name:'收藏 · 相关笔记'}).waitFor();
  await page.screenshot({path:path.join(out,'archive-interest-390.png')});
  report.checks=['cloud profile/model persist; sample synthesis to native playback','saved cloud speech requests only stable message id','actual index and settings entry','voice profile save with revision','speech excludes actions and media; uses stable server message ID','ASR first loads server language; appends editable draft; stale result discarded','pause status and account cancellation','archive filter request and linked detail'];report.passed=report.errors.length===0;
}catch(error){report.passed=false;report.failure=error.stack;await page.screenshot({path:path.join(out,'failure.png')});}
finally{await browser.close();report.errors=[...new Set(report.errors)];await fs.writeFile(path.join(out,'result.safe.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,checks:report.checks,errors:report.errors,failure:report.failure,evidence:out}));process.exitCode=report.passed?0:1;}
