import fs from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../..');
const js=await fs.readFile(path.join(root,'client/asteria-chat/web/app.js'),'utf8');
const html=await fs.readFile(path.join(root,'client/asteria-chat/web/index.html'),'utf8');
class Element {
 constructor(id=''){this.id=id;this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.open=false;this.children=[];this.style={};this.dataset={};this.scrollHeight=40;this.handlers={};this.className='';this.classList={add:(...names)=>{this.className=[...new Set([...this.className.split(' ').filter(Boolean),...names])].join(' ');},remove:(...names)=>{this.className=this.className.split(' ').filter(v=>!names.includes(v)).join(' ');},toggle:(name,value)=>{const list=this.className.split(' ').filter(Boolean).filter(v=>v!==name);if(value)list.push(name);this.className=list.join(' ');}};}
 set innerHTML(value){throw Error('unsafe HTML insertion');}
 append(...items){for(const item of items){item.parent=this;this.children.push(item);}}
 replaceChildren(...items){this.children=[];this.append(...items);}
 addEventListener(name,handler){(this.handlers[name]??=[]).push(handler);}
 setAttribute(name,value){this[name]=value;}
 querySelectorAll(selector){return this.children.filter(c=>selector==='.message-row'&&c.className.split(' ').includes('message-row'));}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(v=>v!==this);}
 showModal(){this.open=true;} close(){this.open=false;} focus(){}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function setup({authenticated=true,personas=[{persona_id:'sdk-real-texas',display_name:'伙伴'}],networkError=false}={}){
 const elements=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element(m[1])]));
 const callbacks={},prefs=new Map(),requests=[],config={server:'https://local-fixture.invalid/tls-chat-api',authenticated,version:'fixture'};
 const session={session_id:'owned-1',display_name:'真实测试会话',created_at:'2026-10-25T00:00:00Z'};
 const serverHistory=[{id:1,llm_checkpoint_id:'cp1',content:{type:'user',message:[{type:'plain',text:'old question'}]}},{id:2,llm_checkpoint_id:'cp1',content:{type:'bot',message:[{type:'plain',text:'<img src=x onerror=alert(1)>'}]}}];
 let context;
 const bridge={getConfig:()=>JSON.stringify(config),setServer:url=>{config.server=url;return JSON.stringify({ok:true,server:url});},clearAuth:()=>{config.authenticated=false;return '{"ok":true}';},request:raw=>{
  const req=JSON.parse(raw);requests.push(req);
  let status=200,body;
  if(req.path==='/auth/login'){config.authenticated=true;body={status:'ok',authenticated:true,data:{}};}
  else if(req.path==='/chat/personas')body={status:'ok',data:personas};
  else if(req.path==='/chat/sessions')body={status:'ok',data:[session]};
  else if(req.path.startsWith('/chat/history?'))body={status:'ok',data:{history:serverHistory,is_running:false,active_runs:[]}};
  else if(req.path==='/chat/connect')body={status:'ok',data:{...session,session_id:bridge.connectTarget||session.session_id,primary:true,platform_id:'webchat',persona_id:req.body.persona_id}};
  else if(req.path==='/chat/send'){
   if(networkError){status=0;body={error:'offline',request_not_retried:true};}
   else {body='data: '+JSON.stringify({type:'user_message_saved',data:{id:3}})+'\n\ndata: '+JSON.stringify({type:'plain',data:'Hi',streaming:true})+'\n\ndata: '+JSON.stringify({type:'complete',data:'Hi'})+'\n\ndata: '+JSON.stringify({type:'message_saved',data:{id:4}})+'\n\ndata: '+JSON.stringify({type:'end'})+'\n\n';}
  }else throw Error('unexpected API path '+req.path);
  queueMicrotask(()=>context.window.AsteriaChatUI.receive(req.requestId,{status,body}));
 }};
 const doc={getElementById:id=>{assert(elements[id],'missing DOM '+id);return elements[id];},createElement:()=>new Element(),querySelector:()=>elements['local-dot']??=(new Element()),querySelectorAll:()=>[],addEventListener:(name,fn)=>callbacks[name]=fn};
 const window={AsteriaChat:bridge,innerHeight:900,innerWidth:1280,addEventListener:()=>{}};
 context=vm.createContext({window,document:doc,localStorage:{getItem:k=>prefs.get(k)||null,setItem:(k,v)=>prefs.set(k,v),removeItem:k=>prefs.delete(k)},URL,Intl,Date,JSON,Promise,Map,Set,innerHeight:900,innerWidth:1280,console,setTimeout,clearTimeout,queueMicrotask,requestAnimationFrame:fn=>fn(),fetch:()=>{throw Error('forbidden fetch');}});
 vm.runInContext(js+'\n;globalThis.testAPI={state,parseStream,normalizeHistory,contentParts,renderMessages,renderAttachments,chooseAttachment,attachmentQueue,connectLongTerm,sendMessage,login,refreshCurrent,loadPersonas,loadHistory,selectSession,normalizeConfiguredPersona,configuredPersonaForCurrent,renderChrome,appearanceBaseName,openAppearance,saveAppearance,logout};',context,{filename:'app.js'});
 callbacks.DOMContentLoaded();
 for(let i=0;i<6;i++)await tick();
 return{api:context.testAPI,elements,prefs,requests,config,context,serverHistory,bridge};
}

Element.prototype.removeAttribute=function(name){delete this[name];};
const json=value=>JSON.parse(JSON.stringify(value));
const walk=element=>[element,...element.children.flatMap(walk)];
const buttons=(element,name)=>walk(element).filter(item=>item.className.split(' ').includes(name));
async function click(element){for(const handler of element.handlers.click||[])await handler();}
function reply(instance,id,status,body){queueMicrotask(()=>instance.context.window.AsteriaChatUI.receive(id,{status,body}));}
function installMedia(instance){
 const calls=[],uploads=new Map();let sequence=0;
 instance.bridge.chooseAttachment=(id,session)=>{
  calls.push({method:'choose',session});const index=++sequence;
  const value={attachment_id:'upload-'+index,filename:'stored-'+index+'.png',display_name:'图片'+index+'.png',type:'image',mime_type:'image/png',size:68,session_id:session};uploads.set(value.attachment_id,value);
  reply(instance,id,200,{status:'ok',data:value});
 };
 const tiny='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9V0AAAAASUVORK5CYII=';
 instance.bridge.loadAttachment=(id,session,filename)=>{calls.push({method:'load',session,filename});reply(instance,id,200,{data_url:'data:image/png;base64,'+tiny,mime_type:'image/png'});};
 instance.bridge.openAttachment=(id,session,filename)=>{calls.push({method:'open',session,filename});reply(instance,id,200,{opened:true});};
 const old=instance.bridge.request;
 instance.bridge.request=raw=>{
  const request=JSON.parse(raw);
  if(request.path==='/chat/send'&&request.body.files?.length){
   instance.requests.push(request);
   assert(request.body.files.length<=4);for(const file of request.body.files)assert.deepEqual(Object.keys(file),['attachment_id']);
   const parts=[...(request.body.message?[{type:'plain',text:request.body.message}]:[]),...request.body.files.map(file=>{const item=uploads.get(file.attachment_id);return{type:item.type,attachment_id:item.attachment_id,filename:item.filename};})];
   instance.serverHistory.push({id:31,llm_checkpoint_id:'cp-upload',content:{type:'user',message:parts}});
   instance.serverHistory.push({id:32,llm_checkpoint_id:'cp-upload',content:{type:'bot',message:[{type:'plain',text:'测试接收确认'}]}});
   const events=[{type:'user_message_saved',data:{id:31}},{type:'plain',data:'测试接收确认',streaming:true},{type:'complete',data:'测试接收确认'},{type:'message_saved',data:{id:32}},{type:'end'}];
   reply(instance,request.requestId,200,events.map(value=>'data: '+JSON.stringify(value)+'\n\n').join(''));return;
  }
  old(raw);
 };
 return{calls,uploads};
}

let assertions=0;const eq=(a,b)=>{assert.deepEqual(json(a),json(b));assertions++;};const check=v=>{assert(v);assertions++;};const submit={preventDefault(){}};
const ready=async()=>{const app=await setup();app.api.state.username='fixture-user';app.api.renderChrome();return app;};
function installHistory(app,body,status=200){const old=app.bridge.request;app.bridge.request=raw=>{const request=JSON.parse(raw);if(request.path.startsWith('/chat/history?')){app.requests.push(request);reply(app,request.requestId,status,body);return;}old(raw);};}
const app=await ready();const history=app.serverHistory;
const configured={configured_id:'真实SDK角色',display_name:'真实SDK角色',status:'configured'};
installHistory(app,{status:'ok',data:{history,persona:configured,is_running:false,active_runs:[]}});await app.api.loadHistory('owned-1');app.api.renderChrome();
eq(app.elements['conversation-persona'].textContent,'会话角色：真实SDK角色（配置）');eq(app.elements['conversation-title'].textContent,'真实测试会话');eq(app.api.configuredPersonaForCurrent().status,'configured');eq(app.api.state.messages.length,2);
const bot=walk(app.elements.messages).find(element=>element.className==='message-row assistant');check(bot);check(walk(bot).some(element=>element.textContent==='<img src=x onerror=alert(1)>'));check(!walk(bot).some(element=>element.textContent==='真实SDK角色'));
app.api.state.sessions[0].display_name='';app.api.renderChrome();eq(app.elements['conversation-title'].textContent,'真实SDK角色');
app.api.openAppearance();app.elements['appearance-name'].value='本机昵称';check(app.api.saveAppearance(submit));eq(app.elements['conversation-title'].textContent,'本机昵称');check(!walk(app.elements.messages).some(element=>element.textContent==='真实SDK角色'));eq(app.elements['conversation-persona'].textContent,'会话角色：真实SDK角色（配置）');
for(const[status,label]of [['unconfigured','会话角色：未配置'],['missing','会话角色：配置角色已不存在'],['unavailable','会话角色：配置暂无法确认']]){installHistory(app,{status:'ok',data:{history,persona:{configured_id:null,display_name:null,status}}});await app.api.loadHistory('owned-1');app.api.renderChrome();eq(app.elements['conversation-persona'].textContent,label);eq(app.api.state.messages.length,2);eq(app.elements['conversation-title'].textContent,'本机昵称');}
for(const persona of [undefined,null,{}, {status:'configured',configured_id:'真实',display_name:'别名'}, {status:'configured',configured_id:'',display_name:''},{status:'configured',configured_id:5,display_name:5},{status:'missing',configured_id:'泄露的坏配置',display_name:null},{status:'surprise',configured_id:null,display_name:null}]){installHistory(app,{status:'ok',data:{history,...(persona===undefined?{}:{persona})}});await app.api.loadHistory('owned-1');app.api.renderChrome();eq(app.elements['conversation-persona'].textContent,'会话角色：配置暂无法确认');eq(app.api.state.messages.length,2);}
installHistory(app,{status:'error',message:'fixture unavailable'},503);await assert.rejects(()=>app.api.loadHistory('owned-1'));app.api.renderChrome();eq(app.elements['conversation-persona'].textContent,'会话角色：配置暂无法确认');eq(app.api.state.messages.length,2);
const late=await ready();late.api.state.sessions.push({session_id:'owned-2',display_name:'第二真实标题'});const pending=[];late.bridge.request=raw=>{const request=JSON.parse(raw);late.requests.push(request);pending.push(request);};
const older=late.api.loadHistory('owned-1');await tick();const newer=late.api.selectSession('owned-2');await tick();check(!late.elements['conversation-persona'].textContent.includes('真实SDK角色'));
const latest=pending.find(request=>request.path.includes('owned-2'));reply(late,latest.requestId,200,{status:'ok',data:{history:[],persona:{status:'configured',configured_id:'第二角色',display_name:'第二角色'}}});await newer;const old=pending.find(request=>request.path.includes('owned-1'));reply(late,old.requestId,200,{status:'ok',data:{history,persona:configured}});await older;late.api.renderChrome();eq(late.api.state.activeId,'owned-2');eq(late.elements['conversation-persona'].textContent,'会话角色：第二角色（配置）');eq(late.elements['conversation-title'].textContent,'第二真实标题');eq(late.api.state.messages.length,0);
const created=await ready();created.api.state.sessionPersonaConfig={sessionId:'owned-1',status:'configured',configuredId:'旧角色',displayName:'旧角色'};created.bridge.connectTarget='created-1';await created.api.connectLongTerm();created.api.renderChrome();eq(created.api.state.sessionPersonaConfig,null);check(!created.elements['conversation-persona'].textContent.includes('旧角色'));eq(created.api.appearanceBaseName(),'助手');
created.api.state.sessionPersonaConfig={sessionId:'created-1',status:'configured',configuredId:'新角色',displayName:'新角色'};created.api.logout();eq(created.api.state.sessionPersonaConfig,null);eq(created.elements['conversation-persona'].textContent,'会话角色：打开对话后查看配置');
check(html.includes('不代表本轮模型最终选择'));check(html.includes('不代表历史每条消息的生成角色'));
for(const instance of [app,late,created])eq(instance.requests.filter(request=>request.path==='/chat/send').length,0);
const files=[];for(const name of ['index.html','app.css','app.js','logo.svg']){const raw=await fs.readFile(path.join(root,'client/asteria-chat/web',name));files.push({path:'client/asteria-chat/web/'+name,sha256:createHash('sha256').update(raw).digest('hex'),bytes:raw.length});}
const result={schema:1,observed_at_utc:new Date().toISOString(),passed:true,assertions,files,boundary:'Node VM with server/native/DOM fixtures only. Configured Persona is display metadata; not actual per-turn model choice, message provenance, scope or memory authorization.',coverage:['Four backend configuration states displayed honestly','Old/missing/malformed DTO does not block message history','Real session title and local display name preserve priority','Historical assistant bubbles do not use configured Persona as message author','Actual late old-history reply cannot contaminate another conversation','Reconnect/logout clears current role metadata; no persisted Persona inference','No sends triggered by metadata rendering'],production_requests:0,model_calls:0};
if(process.argv[2])await fs.writeFile(path.resolve(root,process.argv[2]),JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(result));

for(const instance of [app,late,created])instance.api.logout();
