/* Complete current page, actual renderer, explicit local Native/API fixtures. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import syncFs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('playwright');
const WEB=fileURLToPath(new URL('../web/',import.meta.url));
const OUTPUT=fileURLToPath(new URL('../../../.runtime/message-polish/',import.meta.url));
const baseline=process.argv.includes('--baseline'),toolsOnly=process.argv.includes('--tools-only'),label=process.argv.find(value=>value.startsWith('--label='))?.slice(8)||(baseline?'before_r1':'after_r1');
assert.match(label,/^[a-z0-9_]+$/);await fs.mkdir(OUTPUT,{recursive:true});const out=path.join(OUTPUT,label);await fs.mkdir(out,{recursive:false});
const ORIGIN='http://message-polish-fixture.invalid',PRIMARY='fixture-long-term';
const chrome=process.env.ASTERIA_CHROME_PATH||['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(syncFs.existsSync);
assert(chrome,'Existing Chrome required; no browser download');
const products=['app.js','app.css','chat-compose.js','chat-compose.css','chat-experience.js','chat-experience.css','chat-night.js','chat-night.css','index.html'];
const hashes=async()=>Object.fromEntries(await Promise.all(products.map(async name=>[name,crypto.createHash('sha256').update(await fs.readFile(path.join(WEB,name))).digest('hex')])));
const report={schema:'texas.chat.message-polish.chrome.v1',at_utc:new Date().toISOString(),mode:baseline?'before_visual_reference':toolsOnly?'affected_avatar_tools_only':'focused_after_checks',
 renderer:'actual installed Chrome',native:'local Java bridge fixture',api:'local in-memory fixture',production_connected:false,android:false,
 real_model_calls:0,real_sends:0,purposes:[],screenshots:[],page_errors:[],console_errors:[],external_requests:[],sources_before:await hashes()};

function installFixture(){
 const PRIMARY='fixture-long-term',server='https://fixture.invalid/tls-chat-api';
 const canvas=document.createElement('canvas');canvas.width=canvas.height=160;const c=canvas.getContext('2d');
 function portrait(color,initial){c.clearRect(0,0,160,160);c.fillStyle=color;c.fillRect(0,0,160,160);c.fillStyle='#faf9f2';c.font='600 74px sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillText(initial,80,85);return canvas.toDataURL('image/jpeg');}
 const roleImage=portrait('#667887','T'),userImage=portrait('#b48c70','Q');
 c.clearRect(0,0,160,160);c.fillStyle='#d8ded1';c.beginPath();c.moveTo(28,56);c.lineTo(27,11);c.lineTo(60,37);c.arc(80,83,55,3.9,5.5);c.lineTo(137,11);c.lineTo(132,61);c.arc(80,83,55,-.4,3.7);c.fill();
 c.fillStyle='#53634c';c.beginPath();c.ellipse(61,78,4,6,0,0,7);c.ellipse(100,78,4,6,0,0,7);c.fill();c.strokeStyle='#53634c';c.lineWidth=3;c.beginPath();c.moveTo(71,100);c.quadraticCurveTo(80,106,89,100);c.stroke();
 c.fillStyle='#65735d';c.font='500 25px sans-serif';c.textAlign='center';c.fillText('嗯。',80,151);const preview=canvas.toDataURL('image/png');
 const typed=(id,who,parts,time)=>({id,created_at:'2026-10-27T'+time+':00Z',tls_parts:parts,content:{type:who,message:parts.filter(p=>['plain','speech'].includes(p.type)).map(p=>({type:'plain',text:p.text}))}});
 const history=[
  typed(1,'user',[{type:'action',label:'靠一会儿',description:'轻轻靠着伙伴休息片刻。',source:'user_action'},{type:'speech',text:'今天有点累，想在你旁边安静待一会儿。'}],'10:00'),
  typed(2,'bot',[{type:'action',label:'她把手边的书合上，往你这边留出一点位置。',description:'',source:'assistant_narrative'},
    {type:'speech',text:'过来吧。不用急着说什么。'},{type:'speech',text:'今天剩下的事，等你歇一会儿再慢慢讲。我在听。'},
    {type:'sticker',asset_id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',name:'本地示意表情'}],'10:01'),
  typed(3,'user',[{type:'reference',role:'assistant',message_id:2,text:'不用急着说什么。'},{type:'speech',text:'（这句话保留普通文字。）那就先陪我听会儿歌。'}],'10:02'),
  {id:4,created_at:'2026-10-27T10:09:00Z',content:{type:'bot',message:[{type:'plain',text:'晚饭前记得留一点时间休息。'}],refs:{source:'tls_chat_direct',tls_notice:{schema:1,kind:'reminder'}}}},
  {id:5,created_at:'2026-10-27T10:10:00Z',content:{type:'user',message:[{type:'file',filename:'fixture-note.txt',display_name:'今天的小计划.txt'},{type:'image',filename:'fixture-view.png',display_name:'窗边的光.png'}]}},
  typed(6,'bot',[{type:'speech',text:'好的。你不用把每一分钟都安排满。\n\n先把水喝了，找个舒服的位置。想说话的时候就说，不想说也可以。'}],'10:11')
 ];
 const settings={frequency:'expressive',per_unit:true,cooldown_seconds:60,fragment_display:'semantic',mode_policies:{chat:'semantic',roleplay:'paragraph',technical:'text_only'}};
 const persona={status:'configured',configured_id:'texas-fixture',display_name:'伙伴'};
 const session={session_id:PRIMARY,display_name:'伙伴',platform_id:'webchat',creator:'fixture-user',primary:true,created_at:'2026-10-27T10:00:00Z',updated_at:'2026-10-27T10:11:00Z',persona_id:'texas-fixture',tls_state:{archived:false,mode:'chat',scene:'',reply_format:'auto',revision:0}};
 const f=window.__messageFixture={calls:[],nativeCalls:[],unexpected:[],history,preview,roleImage,userImage};
 const reply=(id,data,status=200)=>setTimeout(()=>window.AsteriaChatUI.receive(id,JSON.stringify({status,body:status===200?{status:'ok',data}:{status:'error',message:String(data)}})),3);
 function request(raw){const q=JSON.parse(raw),url=new URL(q.path,server),p=url.pathname;f.calls.push({method:q.method,path:p,body:q.body});
  if(q.method==='POST'&&p==='/chat/connect')return reply(q.requestId,session);
  if(q.method!=='GET'){f.unexpected.push({method:q.method,path:p});return reply(q.requestId,'Fixture forbids writes',403);}
  const values={
   '/chat/personas':[{persona_id:'texas-fixture',display_name:'伙伴'}],'/chat/sessions':[session],
   '/chat/history':{history:f.history,is_running:false,active_runs:[],persona,tls_state:session.tls_state},
   '/chat/actions':{items:[],revision:0,native_touch:{available:false,verbs:[],parts:[]}},
   '/chat/expressions':{items:[],total:0},'/chat/expression-preview':{data_url:preview,mime_type:'image/png',name:'本地示意表情'},
   '/chat/expression-settings':{defaults:settings,role:{},session:{},effective:settings,sources:Object.fromEntries(Object.keys(settings).map(k=>[k,'default'])),role_revision:0,session_revision:0},
   '/chat/user-avatar':{revision:1,data_url:userImage,source_data_url:userImage,crop:{x:.5,y:.5,zoom:1}},
   '/chat/context':{session_id:PRIMARY,persona,mode:'chat',scene:'',tls_state:session.tls_state,memories:[],shared_memories:[],narrative:null,memory_state:'available'},
   '/chat/bookmarks':{items:[],limited:false},'/chat/identity':{linked:false},
   '/chat/important-dates':{records:[],sources:[],writable:true,capabilities:{}},
   '/chat/workspace':{identity:{linked:false},supported_settings:[],destinations:{qq:'保留QQ'},settings:{revision:0,values:{}}}
  };if(Object.hasOwn(values,p))return reply(q.requestId,values[p]);f.unexpected.push({method:q.method,path:p});reply(q.requestId,'Unknown fixture route',404);
 }
 localStorage.setItem('asteria-chat.username','fixture-user');
 window.AsteriaChat={request,getConfig:()=>JSON.stringify({server,authenticated:true,foreground:true,version:'local-message-fixture'}),
  getViewportMetrics:()=>JSON.stringify({source:'android',width:innerWidth,height:innerHeight,imeVisible:false,sequence:1}),
  getReplyWatchStatus:()=>JSON.stringify({running:false,state:'stopped'}),setChromeTheme:()=>{},
  ackReplyWatch:()=>JSON.stringify({ok:true,service_started:false}),
  openAttachment(id,sessionId,filename){f.nativeCalls.push({method:'openAttachment',sessionId,filename});reply(id,{opened:true});},
  loadAttachment(id,sessionId,filename){f.nativeCalls.push({method:'loadAttachment',sessionId,filename});reply(id,{data_url:preview,mime_type:'image/png'});},
  stopPhonePerception(id){f.nativeCalls.push({method:'stopPhonePerception'});reply(id,{enabled:false,running:false});},clearAuth(){}};
}

await fs.mkdir(OUTPUT,{recursive:true});
const browser=await chromium.launch({executablePath:chrome,headless:true});
try{
 for(const width of [390,1280]){
  const context=await browser.newContext({viewport:{width,height:900},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  await context.addInitScript(installFixture);const page=await context.newPage();
  page.on('pageerror',e=>report.page_errors.push({width,message:e.message}));
  page.on('console',m=>{if(m.type()==='error')report.console_errors.push({width,message:m.text()});});
  await page.route('**/*',async route=>{const url=new URL(route.request().url());if(url.origin!==ORIGIN){report.external_requests.push(url.origin+url.pathname);return route.abort();}
   const name=decodeURIComponent(url.pathname).slice(1)||'index.html';if(name.includes('..'))return route.abort();
   try{return route.fulfill({contentType:({'html':'text/html; charset=utf-8','js':'application/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'})[path.extname(name).slice(1)]||'application/octet-stream',body:await fs.readFile(path.join(WEB,name))});}
   catch{return route.fulfill({status:404,body:'Fixture file missing'});}});
  await page.goto(ORIGIN+'/index.html',{waitUntil:'load'});
  await page.waitForFunction(()=>state.authenticated&&state.activeId==='fixture-long-term'&&!state.loading&&state.messages.length===6);
  await page.evaluate(()=>{state.appearanceCache={key:appearanceScope().key,value:{...DEFAULT_APPEARANCE,avatar:__messageFixture.roleImage},error:''};renderMessages();});
  await page.waitForFunction(()=>document.querySelector('.typed-sticker img')?.complete&&document.querySelector('.typed-sticker img')?.naturalWidth>0&&document.querySelector('.message-row.user .message-avatar img')?.complete);
  const purpose=async(name,fn)=>{try{const details=await fn();report.purposes.push({width,name,passed:true,details});}catch(e){report.purposes.push({width,name,passed:false,error:String(e.stack||e).slice(0,2200)});}};
  if(toolsOnly){
   const theme=width===390?'light':'black';await page.evaluate(mode=>{storage.set(pref('theme'),mode);applyTheme();renderMessages();},theme);
   await purpose('larger_avatars_nonoccupying_tools_keyboard_focus_and_real_menus',async()=>{
    const observations=[];
    for(const role of ['assistant','user']){
     const row=page.locator('.message-row.'+role).first(),toggle=row.locator('.message-tools-toggle');await row.scrollIntoViewIfNeeded();await toggle.focus();
     await page.waitForFunction(el=>Number(getComputedStyle(el.closest('.message-tools')).opacity)===1,await toggle.elementHandle(),{timeout:2000});
     const shape=await row.evaluate(n=>{const r=e=>{const v=e.getBoundingClientRect();return {x:v.x,y:v.y,width:v.width,height:v.height,right:v.right,bottom:v.bottom};};
      return {avatar:r(n.querySelector('.message-avatar')),body:r(n.querySelector('.message-body')),button:r(n.querySelector('.message-tools-toggle')),position:getComputedStyle(n.querySelector('.message-tools')).position,focusOpacity:Number(getComputedStyle(n.querySelector('.message-tools')).opacity),viewport:innerWidth};});
     assert(shape.avatar.width>=46);assert.equal(shape.position,'absolute');assert.equal(shape.focusOpacity,1);
     assert(shape.button.width>=44&&shape.button.height>=36);assert(Math.abs(shape.button.x-shape.avatar.x)<1);
     assert(shape.button.y>=shape.avatar.bottom+2,'Tools do not cover the avatar');assert(shape.button.x>=0&&shape.button.right<=width);
     assert(role==='assistant'?shape.button.right<=shape.body.x-1:shape.button.x>=shape.body.right+1,'Tools do not cover the message');
     await toggle.click();const menu=row.locator('.message-action-menu');assert(await menu.isVisible());
     const bounds=await menu.boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=width+1);assert(bounds.y>=0&&bounds.y+bounds.height<=900);
     assert(await menu.getByRole('button',{name:'引用这条消息',exact:true}).count()===1);
     await toggle.click();assert.equal(await menu.isVisible(),false);observations.push({role,...shape,menu:bounds});
    }
    assert.equal(await page.evaluate(()=>__messageFixture.calls.filter(row=>row.method==='POST'&&row.path!=='/chat/connect').length),0);return observations;
   });
   await page.locator('[data-message-key="2|"]').scrollIntoViewIfNeeded();await page.locator('#draft').focus();
   const file=path.join(out,`${width}-${theme}.png`);await page.screenshot({path:file,fullPage:true});report.screenshots.push({width,theme,path:file});
   report.purposes.push({width,name:'fixture_boundary',passed:(await page.evaluate(()=>__messageFixture.unexpected.length))===0});
   await context.close();continue;
  }
  for(const theme of ['light','dark','black']){
   await page.evaluate(mode=>{storage.set(pref('theme'),mode);applyTheme();renderMessages();},theme);
   await page.locator('#messages').evaluate(n=>n.scrollTop=60);
   await page.waitForTimeout(25);
   const file=path.join(out,`${width}-${theme}.png`);await page.screenshot({path:file,fullPage:true});report.screenshots.push({width,theme,path:file});
   if(!baseline)await purpose('message_surfaces_'+theme,async()=>{
    const values=await page.evaluate(()=>{
     const row=[...document.querySelectorAll('.message-row')].find(n=>n.dataset.messageKey==='2|'),body=row.querySelector('.message-body'),bubble=row.querySelector('.message-bubble'),text=bubble.querySelector('.message-text'),sticker=row.querySelector('.expression-sticker'),image=sticker.querySelector('img'),action=row.querySelector('.expression-action');
     const rect=n=>({x:n.getBoundingClientRect().x,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right});
     return {viewport:innerWidth,page:document.documentElement.scrollWidth,theme:document.documentElement.dataset.theme,
      root:getComputedStyle(document.documentElement).backgroundColor,body:rect(body),avatar:row.querySelector('.message-avatar').getBoundingClientRect().width,
      paragraphDisplays:[...bubble.querySelectorAll('.message-text')].map(n=>getComputedStyle(n).display),font:getComputedStyle(text).fontSize,
      stickerOutsideBubble:!sticker.closest('.message-bubble'),stickerBackground:getComputedStyle(sticker).backgroundColor,sticker:rect(image),
      narrative:action.classList.contains('expression-narrative-action'),hasPlainParentheses:document.querySelector('[data-message-key="3|"]').textContent.includes('（这句话保留普通文字。）'),
      roleImage:row.querySelector('.message-avatar img').src,userImage:document.querySelector('.message-row.user .message-avatar img').src};});
    assert(values.page<=width+1);assert(values.body.right<=width+1);assert(values.body.width<=576.5);assert(values.avatar>=40);
    assert(values.paragraphDisplays.every(value=>value==='block'),'Existing speech units need visual paragraph separation');
    assert(values.stickerOutsideBubble);assert.equal(values.stickerBackground,'rgba(0, 0, 0, 0)');assert(values.sticker.width>=128&&values.sticker.width<=160);assert(values.narrative);assert(values.hasPlainParentheses);assert.notEqual(values.roleImage,values.userImage);
    if(theme==='black')assert.equal(values.root,'rgb(0, 0, 0)');return values;
   });
  }
  if(!baseline){
   await purpose('draft_history_identity_and_reading_anchor_unchanged',async()=>{
    await page.locator('#draft').fill('只保留在本地的聊天草稿，不发送。');
    const before=await page.evaluate(()=>{state.liveFollowScope='';const box=document.querySelector('#messages');box.scrollTop=170;return {position:captureMessagePosition(box),history:JSON.stringify(state.messages.map(({id,serverId,checkpoint,origin,notice,parts})=>({id,serverId,checkpoint,origin,notice,parts}))),refs:JSON.stringify(__messageFixture.history.map(row=>row.content.refs))};});
    await page.evaluate(()=>renderMessages());await page.waitForTimeout(30);
    const after=await page.evaluate(()=>({position:captureMessagePosition(document.querySelector('#messages')),history:JSON.stringify(state.messages.map(({id,serverId,checkpoint,origin,notice,parts})=>({id,serverId,checkpoint,origin,notice,parts}))),refs:JSON.stringify(__messageFixture.history.map(row=>row.content.refs))}));
    assert.equal(after.history,before.history);assert.equal(after.refs,before.refs);assert.equal(after.position.key,before.position.key);assert(Math.abs(after.position.offset-before.position.offset)<=2);
    assert.equal(await page.locator('#draft').inputValue(),'只保留在本地的聊天草稿，不发送。');return {anchor_delta:after.position.offset-before.position.offset,history_unchanged:true};
   });
   await purpose('attachment_original_click_handlers_and_unknown_manual_protection',async()=>{
    await page.locator('.file-button').click();await page.waitForFunction(()=>__messageFixture.nativeCalls.some(row=>row.method==='openAttachment'));
    await page.locator('.image-button').click();await page.waitForFunction(()=>document.querySelector('.message-image')?.hidden===false);
    await page.locator('.message-image').click();await page.waitForFunction(()=>__messageFixture.nativeCalls.filter(row=>row.method==='openAttachment').length===2);
    await page.evaluate(()=>{state.messages.push({id:'fixture-unknown',role:'user',text:'这条只用于本地未知状态样式。',parts:[{type:'plain',text:'这条只用于本地未知状态样式。'}],created_at:'2026-10-27T10:12:00Z',delivery:'unknown'});renderMessages();});
    assert.equal(await page.locator('[data-message-key="fixture-unknown"] .message-delivery').getByRole('button',{name:'同步记录',exact:true}).count(),1);
    assert.match(await page.locator('[data-message-key="fixture-unknown"] .message-delivery').textContent(),/待确认/);
    assert.equal(await page.evaluate(()=>__messageFixture.calls.filter(row=>row.method==='POST'&&row.path!=='/chat/connect').length),0);
    assert.equal(await page.locator('#draft').inputValue(),'只保留在本地的聊天草稿，不发送。');
    return {native_attachment:'local callback fixture only',automatically_replayed_posts:0};
   });
  }
  report.purposes.push({width,name:'fixture_boundary',passed:(await page.evaluate(()=>__messageFixture.unexpected.length))===0});
  await context.close();
 }
}finally{await browser.close();report.sources_after=await hashes();report.sources_stable=JSON.stringify(report.sources_before)===JSON.stringify(report.sources_after);
 report.passed=report.purposes.every(row=>row.passed)&&!report.page_errors.length&&!report.console_errors.length&&!report.external_requests.length&&report.sources_stable;
 await fs.writeFile(path.join(out,'result.safe.json'),JSON.stringify(report,null,2),{flag:'wx'});console.log(JSON.stringify({passed:report.passed,mode:report.mode,purposes:report.purposes,page_errors:report.page_errors,console_errors:report.console_errors,external_requests:report.external_requests,result:path.join(out,'result.safe.json'),screenshots:report.screenshots}));}
process.exitCode=report.passed?0:1;
