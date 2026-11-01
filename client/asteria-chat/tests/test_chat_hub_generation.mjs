/* Final grouped run only: actual source methods; optional installed Chrome DOM. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import syncFs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

const web=fileURLToPath(new URL('../web/',import.meta.url));
const app=await fs.readFile(path.join(web,'app.js'),'utf8');
const compose=await fs.readFile(path.join(web,'chat-compose.js'),'utf8');
const experience=await fs.readFile(path.join(web,'chat-experience.js'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
function actual(source,name){
  const start=new RegExp('(?:async )?function '+name+'\\(').exec(source);assert(start,'missing actual '+name);
  const next=/\n\s*(?:async )?function [A-Za-z]/g;next.lastIndex=start.index+start[0].length;
  const end=next.exec(source);assert(end,'missing function boundary '+name);return source.slice(start.index,end.index);
}
const sse=(type,data,extra={})=>'data: '+JSON.stringify({type,data,...extra})+'\n\n';
const base={window:{ChatComposer:{}},mediaPart:value=>value};
const parseContext=vm.createContext(base);
vm.runInContext(actual(compose,'normalizeParts')+'\nwindow.ChatComposer.normalizeParts=normalizeParts;\n'+actual(app,'parseStream'),parseContext);
const parseStream=text=>parseContext.parseStream(text);
const purposes=[];
async function purpose(name,fn){await fn();purposes.push({name,status:'passed'});}

await purpose('actual_parser_truthful_phases_and_typed_projection',()=>{
  for(const [phase,source]of [['queued','sdk_run_accepted'],['generating','model_reasoning_received'],['streaming','model_output_received'],['completed','sdk_stream_finished'],['failed','sdk_error']])
    assert.equal(parseStream(sse('tls_generation_state',{phase,source})).phase,phase);
  assert.equal(parseStream(sse('is_running',true)).phase,'','remote run snapshot is not model ACK');
  assert.equal(parseStream(sse('tls_generation_state',{phase:'generating',source:'untrusted_text'})).phase,'');
  const reasoning=parseStream(sse('tls_generation_state',{phase:'generating',source:'model_reasoning_received'})+sse('plain','隐藏思考',{chain_type:'reasoning'}));
  assert.equal(reasoning.phase,'generating');assert.equal(reasoning.text,'');assert.equal(reasoning.parts.length,0);
  const typed=[{id:'saved-action',order:0,type:'action',label:'伙伴的动作',description:'轻轻靠近',source:'assistant_narrative'},
    {id:'saved-speech',order:1,type:'speech',text:'我在。',source:'assistant_speech'}];
  const result=parseStream(sse('plain','（轻轻靠近）\n\n我在。',{streaming:false})+sse('message_saved',{id:42})+sse('tls_parts',{role:'assistant',parts:typed})+sse('end',{}));
  assert.equal(result.messageId,42);assert.equal(result.parts[0].source,'assistant_narrative');assert.equal(result.parts[1].text,'我在。');assert.equal(result.phase,'completed');
  const failed=parseStream(sse('tls_generation_state',{phase:'queued',source:'sdk_run_accepted'})+sse('error','SDK明确失败')+sse('end',{}));
  assert.equal(failed.phase,'failed');assert.equal(failed.error,'SDK明确失败');
  const fallback='{"tls_reply":';assert.equal(parseStream(sse('plain',fallback,{streaming:false})).text,fallback);
});

class Element{
  constructor(){this.value='';this.textContent='';this.children=[];this.hidden=false;this.disabled=false;this.checked=false;this.dataset={};this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
  append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}querySelectorAll(){return [];}setAttribute(){}
}
function chromeEnvironment(){
  const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const state={server:'https://fixture.invalid/tls-chat-api',username:'owner',activeId:'owned',sessions:[],authenticated:true,bridgeAvailable:true,
    sending:false,loading:false,creating:false,attaching:false,appearanceBusy:false,remoteRunning:false,replyPhase:'idle',messages:[]};
  const context=vm.createContext({window:{},state,$,document:{querySelector:()=>$('local-dot')},URL,phonePerceptionPanel:null,
    renderRenameTitle(){},renderMessageSearchControls(){},configuredPersonaForCurrent:()=>null,readyAttachments:()=>[],invalidAttachments:()=>false,
    attachmentQueue:()=>[],primaryConnectionId:()=> 'owned',applyAppearance(){},renderInteractions(){},renderConversationExport(){},
    foregroundRecovery:{stateChanged(){}}});
  vm.runInContext(actual(app,'renderChrome'),context);
  return{state,$,context};
}
await purpose('actual_status_labels_do_not_infer_model_start_from_remote_running',()=>{
  const env=chromeEnvironment();env.state.remoteRunning=true;env.context.renderChrome();
  assert.match(env.$('reply-status-text').textContent,/TLS.*处理/);assert.doesNotMatch(env.$('reply-status-text').textContent,/正在输入|思考/);
  env.state.remoteRunning=false;env.state.sending=true;
  for(const phase of ['submitting','queued','generating','streaming','completed','failed','unknown']){
    env.state.replyPhase=phase;env.context.renderChrome();assert.equal(env.$('reply-status').dataset.phase,phase);assert.equal(env.$('reply-status').hidden,false);assert(env.$('reply-status-text').textContent);
  }
  env.state.sending=false;env.state.replyPhase='unknown';env.context.renderChrome();assert.match(env.$('reply-status-text').textContent,/不会自动重发/);
});

function sendingEnvironment(response){
  const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};$('draft').value='保留的正常聊天草稿';
  const state={server:'https://fixture.invalid/tls-chat-api',username:'owner',activeId:'owned',authenticated:true,sending:false,loading:false,attaching:false,
    creating:false,remoteRunning:false,requestSerial:0,messages:[],attachmentQueues:new Map(),pendingActions:[]};
  const calls=[],notices=[],writes=new Map(),composer={snapshot:text=>({parts:[{type:'text',text}],actions:[],stickers:[]}),
    normalizeParts:parseContext.window.ChatComposer.normalizeParts,clear(){},recover(){},hasContent:()=>false};
  const context=vm.createContext({state,$,window:{ChatComposer:composer,crypto:{randomUUID:()=> 'one-explicit-request'}},Date,Math,Set,Map,Error,
    primaryConnectionId:()=> 'owned',readyAttachments:()=>[],invalidAttachments:()=>false,attachmentQueue:()=>[],messageSearchScope:()=> 'owned',
    messageSendCurrent:scope=>state.authenticated&&scope.server===state.server&&scope.username===state.username&&scope.sessionId===state.activeId,
    storage:{set:(key,value)=>writes.set(key,value)},draftKey:id=>'draft:'+id,saveDraft(){},resizeDraft(){},renderPendingActions(){},
    hideNotice(){},renderChrome(){},renderMessages(){},renderSessions(){},jumpToLatest(){},openSettings(){},
    showNotice:(text,action,important)=>notices.push({text,important,hasManualAction:!!action}),errorText:error=>error.message,
    refreshCurrent(){},mediaPart:value=>value,parseStream,loadHistory:async()=>calls.push({method:'GET',kind:'history'}),loadSessions:async()=>calls.push({method:'GET',kind:'sessions'}),
    apiClient:{send:async(...args)=>{calls.push({method:'POST',args});return await response();}}});
  vm.runInContext(actual(app,'sendMessage'),context);return{context,state,$,calls,notices};
}
await purpose('actual_send_network_unknown_and_sdk_failure_never_automatically_resend',async()=>{
  for(const [expected,response]of [['unknown',async()=>{throw Error('连接中断，结果未知');}],['failed',async()=>sse('error','SDK已确定失败')+sse('end',{})],['failed',async()=>{throw Object.assign(Error('HTTP拒绝'),{status:403});}]]){
    const env=sendingEnvironment(response);await env.context.sendMessage({preventDefault(){}});
    assert.equal(env.state.replyPhase,expected);assert.equal(env.state.sending,false);assert.equal(env.calls.filter(call=>call.method==='POST').length,1);
    assert.match(env.calls.find(call=>call.method==='POST').args[4],/^tc-/);assert.equal(env.$('draft').value,'保留的正常聊天草稿');
    assert.equal(env.state.messages[0].delivery,'unknown');assert.match(env.notices.at(-1).text,/不会自动重发/);
    await new Promise(resolve=>setImmediate(resolve));assert.equal(env.calls.filter(call=>call.method==='POST').length,1);
  }
});

await purpose('actual_context_read_save_preserves_explicit_reply_format',async()=>{
  const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const state={activeId:'owned',sessions:[{session_id:'owned',tls_state:{revision:2}}]};
  let record={mode:'roleplay',scene:'原有场景',reply_format:'auto',revision:2};const calls=[];
  const context=vm.createContext({state,$,document:{createElement:()=>new Element()},contextSnapshot:null,
    panelTicket:()=>({owner:'fixed',epoch:1}),panelCurrent:()=>true,status(){},errorText:e=>e.message,renderChrome(){},route:name=>'/chat/'+name+'?session_id=owned',
    text:(tag,value)=>{const node=new Element();node.textContent=value;return node;},
    call:async(method,path,body)=>{calls.push({method,path,body:plain(body||{})});if(method==='POST'){assert.equal(body.expected_revision,record.revision);record={...record,...body,revision:record.revision+1};return plain(record);}return{mode:record.mode,scene:record.scene,tls_state:plain(record),memories:[],shared_memories:[]};}});
  vm.runInContext(actual(experience,'readContext')+'\n'+actual(experience,'saveContext'),context);
  await context.readContext();assert.equal($('experience-reply-format').value,'auto');
  $('experience-reply-format').value='structured';await context.saveContext({preventDefault(){}});
  assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.equal(calls.find(call=>call.method==='POST').body.reply_format,'structured');
  assert.equal($('experience-reply-format').value,'structured');assert.equal(state.sessions[0].tls_state.reply_format,'structured');
});

const browserResult={status:'not_run',reason:'Use --chrome in the single final grouped run; no silent browser install.'};
if(process.argv.includes('--chrome')){
  const require=createRequire(import.meta.url),{chromium}=require('playwright');
  const chrome=process.env.ASTERIA_CHROME_PATH||[process.env.ASTERIA_CHROME_PATH || undefined,'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(p=>syncFs.existsSync(p));
  assert(chrome,'Installed real Chrome required; do not download one');
  const browser=await chromium.launch({executablePath:chrome,headless:true}),errors=[],external=[];
  try{for(const width of [390,1280])await purpose('real_chrome_original_menu_nodes_handlers_context_and_late_entries_'+width,async()=>{
    const context=await browser.newContext({viewport:{width,height:900}});const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));page.on('console',event=>{if(event.type()==='error')errors.push(event.text());});
    await context.addInitScript(()=>{window.__hubCalls=[];window.hideMoreMenu=()=>{document.getElementById('more-menu').hidden=true;};document.addEventListener('DOMContentLoaded',()=>{
      const menu=document.getElementById('more-menu');window.__hubOriginal=new Map([...menu.querySelectorAll('button[id]')].map(node=>[node.id,node]));window.__contextOriginal=document.getElementById('conversation-persona');
      for(const node of window.__hubOriginal.values()){node.onclick=()=>window.__hubCalls.push('property:'+node.id);node.addEventListener('click',()=>window.__hubCalls.push('listener:'+node.id));}
      const role=document.createElement('button');role.id='fixture-role-entry';role.textContent='角色与剧情';menu.append(role);
    },{once:true});});
    await page.route('**/*',async route=>{const url=new URL(route.request().url());if(url.origin!=='http://hub-fixture.invalid'){external.push(url.origin);await route.abort();return;}
      const relative=url.pathname.slice(1)||'index.html',file=path.resolve(web,relative);assert(file.startsWith(path.resolve(web)+path.sep));let data=await fs.readFile(file);
      if(relative==='index.html')data=Buffer.from(data.toString('utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace('</body>','<script defer src="chat-hub.js"></script></body>'));
      await route.fulfill({status:200,contentType:({'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'})[path.extname(file).slice(1)]||'application/octet-stream',body:data});});
    await page.goto('http://hub-fixture.invalid/index.html');await page.waitForFunction(()=>document.getElementById('hub-connection')?.contains(document.getElementById('mobile-settings')));
    assert.equal(await page.evaluate(()=>[...window.__hubOriginal].every(([id,node])=>document.getElementById(id)===node)),true);
    assert.equal(await page.evaluate(()=>document.getElementById('conversation-persona')===window.__contextOriginal&&document.getElementById('hub-role-context').contains(window.__contextOriginal)),true);
    assert.equal(await page.locator('#conversation-persona').count(),1);assert.equal(await page.locator('#appearance-button').evaluate(node=>node.parentElement.id),'more-menu');
    assert.equal(await page.locator('#rename-button').evaluate(node=>node.parentElement.id),'more-menu');assert.equal(await page.locator('#fixture-role-entry').evaluate(node=>node.parentElement.id),'more-menu');
    await page.evaluate(()=>{document.getElementById('more-menu').hidden=false;});await page.locator('#settings-hub-open').click();await page.locator('#mobile-settings').click();
    assert.equal(await page.locator('#settings-hub-dialog').evaluate(node=>node.open),false);
    assert.deepEqual(await page.evaluate(()=>window.__hubCalls),['property:mobile-settings','listener:mobile-settings']);
    await page.evaluate(()=>{const late=document.createElement('button');late.id='late-phone-entry';late.textContent='新的手机入口';late.onclick=()=>window.__hubCalls.push('late');document.getElementById('more-menu').append(late);window.__late=late;});
    await page.waitForFunction(()=>document.getElementById('hub-connection').contains(window.__late));
    assert.equal(await page.evaluate(()=>document.getElementById('late-phone-entry')===window.__late),true);
    await page.evaluate(()=>{document.getElementById('more-menu').hidden=false;});await page.locator('#settings-hub-open').click();await page.locator('#late-phone-entry').click();
    assert.equal(await page.locator('#settings-hub-dialog').evaluate(node=>node.open),false);assert.equal(await page.evaluate(()=>window.__hubCalls.at(-1)),'late');
    await context.close();
  });assert.deepEqual(errors,[]);assert.deepEqual(external,[]);Object.assign(browserResult,{status:'passed',renderer:'real installed Chrome',native:'not loaded',api:'not loaded',viewports:[390,1280],page_and_console_errors:errors});}
  finally{await browser.close();}
}
console.log(JSON.stringify({passed:true,purposes,browser:browserResult,production_connected:false,android:false,model_calls:0,real_sends:0}));
