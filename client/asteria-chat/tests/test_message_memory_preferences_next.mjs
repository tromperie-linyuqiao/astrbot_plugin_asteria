/* Actual new-module callbacks against owned API/DOM fixtures; no server or model. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const memorySource=await fs.readFile(new URL('../web/chat-message-memory.js',import.meta.url),'utf8');
const preferenceSource=await fs.readFile(new URL('../web/chat-session-preferences.js',import.meta.url),'utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function flush(){for(let i=0;i<8;i++)await tick();}
const error=(message,status)=>Object.assign(Error(message),status?{status}:{});
class Element{
  constructor(tag,document){this.tagName=tag.toUpperCase();this.document=document;this.children=[];this.events={};this.attributes={};this._text='';this._value='';this.hidden=false;this.disabled=false;this.checked=false;this.open=false;}
  set id(value){this._id=value;this.document.nodes.set(value,this);}get id(){return this._id||'';}
  set textContent(value){this._text=String(value??'');this.children=[];}get textContent(){return this._text+this.children.map(item=>item.textContent).join(' ');}
  set value(value){const selected=String(value??'');this._value=this.tagName==='SELECT'&&this.children.length&&!this.children.some(option=>option.value===selected)?'':selected;}get value(){return this._value;}
  append(...items){for(const item of items){item.parent=this;this.children.push(item);if(this.tagName==='SELECT'&&!this._value)this._value=item.value;}}
  replaceChildren(...items){this.children=[];this._text='';this.append(...items);}
  addEventListener(name,callback){(this.events[name]??=[]).push(callback);}
  setAttribute(name,value){this.attributes[name]=String(value);}
  showModal(){this.open=true;}
  close(){this.open=false;for(const callback of this.events.close||[])callback();}
  async fire(name,event={}){for(const callback of this.events[name]||[])await callback(event);}
  async click(){if(!this.disabled&&!this.hidden)await this.fire('click');}
  all(tag){return this.children.flatMap(item=>[...(item.tagName===tag.toUpperCase()?[item]:[]),...item.all(tag)]);}
}
function fixture(){
  const document={nodes:new Map(),createElement(tag){return new Element(tag,this);},getElementById(id){return this.nodes.get(id)||null;}};
  document.body=document.createElement('body');
  const state={server:'https://fixture.invalid',username:'owner',activeId:'owned',authenticated:true,
    sessions:[{session_id:'owned',tls_state:{mode:'roleplay',scene:'原有剧情不被覆盖'}}],draft:'尚未发送的聊天草稿',pendingActions:[{id:'untouched'}]};
  const calls=[],notices=[],memories=new Map(),preferences=new Map(),expressionStates=new Map(),deferred=[];
  const behavior={writeFailure:null,correctFailure:false,preferenceFailure:false,oldServer:false,defer:null,normalizeLength:null};
  const defaultExpression={frequency:'balanced',per_unit:true,cooldown_seconds:60,fragment_display:'semantic',mode_policies:{chat:'semantic',roleplay:'paragraph',technical:'text_only'}};
  const memoryFor=(sid,id)=>{const key=sid+':'+id;if(!memories.has(key))memories.set(key,{session_id:sid,message:{message_id:id,role:id==='43'?'assistant':'user',mode:id==='43'?'roleplay':'chat',source_message_ids:[id]},
    records:[],candidates:[],important_saved:false,important_state:'not_saved',pending_candidate:null,candidate_status:'not_proposed',state:'no_exact_association',bookmark_is_memory:false,operations:new Map()});return memories.get(key);};
  const preferenceFor=sid=>{if(!preferences.has(sid))preferences.set(sid,{session_id:sid,revision:4,archived:false,mode:'roleplay',scene:'原有剧情不被覆盖',reply_format:'auto',reply_style:'inherit',reply_length:'inherit',rp_intensity:'inherit'});return preferences.get(sid);};
  const expressionFor=sid=>{if(!expressionStates.has(sid))expressionStates.set(sid,{effective:copy(defaultExpression),defaults:copy(defaultExpression),role:{},session:{},sources:Object.fromEntries(Object.keys(defaultExpression).map(key=>[key,'default'])),session_revision:0,role_revision:0});return expressionStates.get(sid);};
  const response=value=>copy(value);
  const api={async json(method,path,payload){
    const body=payload&&copy(payload);calls.push({method,path,body});
    const url=new URL('https://fixture.invalid'+path),sid=method==='GET'?url.searchParams.get('session_id'):body.session_id;
    if(behavior.defer===url.pathname&&method==='GET')return new Promise((resolve,reject)=>deferred.push({path,sid,resolve,reject}));
    if(method==='GET'){
      if(behavior.oldServer)throw error('旧服务未提供这个接口',404);
      if(url.pathname==='/chat/message-memory')return response(memoryFor(sid,url.searchParams.get('message_id')));
      if(url.pathname==='/chat/session-state')return response(preferenceFor(sid));
      if(url.pathname==='/chat/expression-settings')return response(expressionFor(sid));
      if(url.pathname==='/chat/memory-detail'){
        const row=[...memories.values()].flatMap(item=>item.records).find(item=>item.id===url.searchParams.get('id'));
        assert(row);return response({record:row,editable:true,history_total:1,history:[{revision:row.revision,operation:'create',record:row}]});
      }
      throw Error('Unexpected GET '+path);
    }
    if(url.pathname==='/chat/message-memory'){
      assert.deepEqual(Object.keys(body).sort(),['action','expected_revision','message_id','request_id','session_id',...(body.action==='confirm'?['confirm']:[])].sort());
      assert.match(body.request_id,/^[A-Za-z0-9_.:-]{8,128}$/);
      const data=memoryFor(sid,String(body.message_id));
      if(behavior.writeFailure==='before')throw error('结果待回读');
      assert.equal(body.expected_revision,data.pending_candidate?.revision||0);
      const candidate=data.pending_candidate;
      if(body.action==='propose'){
        assert.equal(data.important_saved,false);data.pending_candidate={message_id:String(body.message_id),original_text:'服务端核对的原始消息 '+body.message_id,
          source:copy(data.message),evidence_kind:data.message.role==='assistant'?'roleplay_event':'user_reported',status:'pending',revision:(candidate?.revision||0)+1,
          recall_eligible:false,last_operation:{action:body.action,request_id:body.request_id}};
      }else if(body.action==='confirm'){
        assert.equal(body.confirm,true);assert.equal(candidate?.status,'pending');candidate.status='confirmed';candidate.revision++;
        const record={id:'memory.'+body.message_id,content:candidate.original_text,revision:1,source_id:'tls.chat.message.important',evidence_kind:candidate.evidence_kind,memory_type:'explicit_memory',review_status:'manual',lifecycle:'stable_memory',editable:true};
        data.records.push(record);data.saved_record=record;data.important_saved=true;data.important_state='stable_memory';candidate.memory_id=record.id;candidate.last_operation={action:body.action,request_id:body.request_id};
      }else{assert.equal(body.action,'reject');assert.equal(candidate?.status,'pending');candidate.status='rejected';candidate.revision++;candidate.last_operation={action:body.action,request_id:body.request_id};}
      data.candidate_status=data.pending_candidate.status;
      if(behavior.writeFailure==='after')throw error('服务器结果尚未确认');
      return response(data);
    }
    if(url.pathname==='/chat/memory-correct'){
      if(behavior.correctFailure)throw error('资料版本冲突',409);
      const row=[...memories.values()].flatMap(item=>item.records).find(item=>item.id===body.id);assert(row);assert.equal(body.expected_revision,row.revision);row.content=body.content;row.revision++;return response({record:row});
    }
    if(url.pathname==='/chat/session-state'){
      if(behavior.preferenceFailure)throw error('旧服务不支持新的会话偏好',400);
      const old=preferenceFor(sid);assert.equal(body.expected_revision,old.revision);
      assert.equal('mode' in body,false);assert.equal('scene' in body,false);assert.equal('persona_id' in body,false);
      const enums={reply_style:['inherit','natural','warm','direct'],reply_length:['inherit','short','balanced','detailed'],rp_intensity:['inherit','light','balanced','immersive'],reply_format:['auto','text','structured']};
      if(body.reset_preferences){Object.assign(old,{reply_style:'inherit',reply_length:'inherit',rp_intensity:'inherit'});}
      for(const [key,values]of Object.entries(enums))if(key in body){assert(values.includes(body[key]));old[key]=body[key];}
      if(behavior.normalizeLength)old.reply_length=behavior.normalizeLength;old.revision++;return response(old);
    }
    assert.equal(url.pathname,'/chat/expression-settings');assert.equal(body.level,'session');
    const old=expressionFor(sid);assert.equal(body.expected_revision,old.session_revision);old.session_revision++;
    if(body.reset){old.session={};old.effective=copy(defaultExpression);old.sources=Object.fromEntries(Object.keys(defaultExpression).map(key=>[key,'default']));}
    else{old.session=body.changes;old.effective=copy(body.changes);old.sources=Object.fromEntries(Object.keys(defaultExpression).map(key=>[key,'session']));}
    return response(old);
  }};
  const window={crypto:webcrypto};
  const context=vm.createContext({window,document,state,apiClient:api,showNotice:value=>notices.push(value),errorText:value=>value.message,
    console,URL,URLSearchParams,Map,Set,JSON,Object,Array,Number,String,Date,Math,Promise,Error,encodeURIComponent});
  vm.runInContext(memorySource,context,{filename:'chat-message-memory.js'});vm.runInContext(preferenceSource,context,{filename:'chat-session-preferences.js'});
  const get=id=>{const value=document.getElementById(id);assert(value,'Missing actual UI node '+id);return value;};
  const button=(label,dialog)=>{const value=get(dialog).all('button').find(item=>item.textContent===label);assert(value,'Missing button '+label);return value;};
  const click=async(label,dialog='message-memory-dialog')=>{await button(label,dialog).click();await flush();};
  return{window,document,state,calls,behavior,deferred,memoryFor,preferenceFor,expressionFor,get,button,click,notices,
    posts:()=>calls.filter(item=>item.method==='POST')};
}

let purposes=0;
{
  const e=fixture();assert.equal(e.calls.length,0,'loading starts no network activity');
  e.window.openMessageMemory({id:'local-pending'});await flush();assert.equal(e.calls.length,0);assert.match(e.notices[0],/保存后/);
  e.window.openMessageMemory({serverId:42});await flush();
  assert.equal(e.posts().length,0);assert.equal(e.get('message-memory-save').hidden,true);
  await e.click('加入记忆候选');const data=e.memoryFor('owned','42');
  assert.equal(data.pending_candidate.status,'pending');assert.equal(data.pending_candidate.recall_eligible,false);assert.equal(data.records.length,0);assert.equal(data.important_saved,false);
  assert.match(e.get('message-memory-records').textContent,/服务端核对的原始消息 42.*待你确认/);
  assert.equal(e.get('message-memory-save').hidden,false);assert.equal(e.get('message-memory-save').disabled,true);
  const count=e.posts().length;await e.get('message-memory-save').fire('click');await flush();assert.equal(e.posts().length,count,'unchecked confirmation is denied by the real callback');
  e.get('message-memory-confirm').checked=true;await e.get('message-memory-confirm').fire('change');await e.click('确认保存长期记忆');
  assert.equal(data.pending_candidate.status,'confirmed');assert.equal(data.records.length,1);assert.equal(e.posts().at(-1).body.confirm,true);
  assert.match(e.get('message-memory-dialog').textContent,/长期记忆已明确保存/);assert.equal(e.state.draft,'尚未发送的聊天草稿');assert.deepEqual(e.state.pendingActions,[{id:'untouched'}]);purposes++;

  await e.click('查看原文与纠错');let textarea=e.get('message-memory-records').all('textarea')[0];textarea.value='仍未发送的纠错草稿';await textarea.fire('input');
  let check=e.get('message-memory-records').all('input')[0];check.checked=true;await check.fire('change');e.behavior.correctFailure=true;await e.click('保存纠错');
  assert.equal(textarea.value,'仍未发送的纠错草稿');assert.match(e.get('message-memory-dialog').textContent,/草稿|编辑内容保留/);
  await e.click('返回关联记忆');await e.click('查看原文与纠错');textarea=e.get('message-memory-records').all('textarea')[0];assert.equal(textarea.value,'仍未发送的纠错草稿');
  e.window.ChatMessageMemory.closeActive();e.window.openMessageMemory({serverId:42});await flush();await e.click('查看原文与纠错');assert.equal(e.get('message-memory-records').all('textarea')[0].value,'仍未发送的纠错草稿');
  e.state.username='other-owner';e.window.ChatMessageMemory.scopeChanged();assert.equal(e.get('message-memory-dialog').open,false);
  e.window.openMessageMemory({serverId:42});await flush();await e.click('查看原文与纠错');assert.notEqual(e.get('message-memory-records').all('textarea')[0].value,'仍未发送的纠错草稿','drafts never cross account scope');purposes++;
}
{
  const e=fixture();e.window.openMessageMemory({serverId:43});await flush();await e.click('加入记忆候选');
  const data=e.memoryFor('owned','43');assert.equal(data.pending_candidate.evidence_kind,'roleplay_event');
  await e.click('不保存这个候选');assert.equal(data.pending_candidate.status,'rejected');assert.equal(data.records.length,0);assert.equal(data.important_saved,false);
  assert.equal(e.get('message-memory-save').hidden,true);assert.match(e.get('message-memory-dialog').textContent,/已放弃/);assert.equal(e.posts().length,2);purposes++;
}
{
  const e=fixture();e.window.openMessageMemory({serverId:42});await flush();e.behavior.writeFailure='after';await e.click('加入记忆候选');
  const before=e.posts().length;assert.equal(before,1);assert.equal(e.get('message-memory-propose').disabled,true);await flush();assert.equal(e.posts().length,before);
  await e.click('重新读取');assert.equal(e.posts().length,before,'unknown proposal resolves through GET only');assert.equal(e.get('message-memory-save').hidden,false);
  e.get('message-memory-confirm').checked=true;await e.get('message-memory-confirm').fire('change');await e.click('确认保存长期记忆');const confirms=e.posts().length;
  await e.click('重新读取');assert.equal(e.posts().length,confirms);assert.equal(e.memoryFor('owned','42').records.length,1);assert.match(e.get('message-memory-dialog').textContent,/已存在重要记忆/);purposes++;
}
{
  const e=fixture();e.window.openMessageMemory({serverId:42});await flush();e.behavior.writeFailure='before';await e.click('加入记忆候选');
  const count=e.posts().length;await e.click('重新读取');assert.equal(e.posts().length,count);assert.equal(e.get('message-memory-propose').disabled,true);
  e.window.ChatMessageMemory.closeActive();e.window.openMessageMemory({serverId:42});await flush();assert.equal(e.posts().length,count);assert.equal(e.get('message-memory-propose').disabled,true,'unresolved write is never repeated after reopening');purposes++;
}
{
  const e=fixture();e.behavior.defer='/chat/message-memory';e.window.openMessageMemory({serverId:42});await flush();assert.equal(e.deferred.length,1);
  e.window.ChatMessageMemory.closeActive();e.deferred.shift().resolve(copy(e.memoryFor('owned','42')));await flush();assert.equal(e.get('message-memory-records').textContent,'');
  e.window.openMessageMemory({serverId:42});await flush();e.state.activeId='other';e.window.ChatMessageMemory.scopeChanged();assert.equal(e.get('message-memory-dialog').open,false);
  e.deferred.shift().resolve(copy(e.memoryFor('owned','42')));await flush();assert.equal(e.get('message-memory-records').textContent,'');
  e.window.openMessageMemory({serverId:43});await flush();e.state.authenticated=false;e.window.ChatMessageMemory.scopeChanged();e.deferred.shift().resolve(copy(e.memoryFor('other','43')));await flush();assert.equal(e.get('message-memory-dialog').open,false);assert.equal(e.posts().length,0);purposes++;
}
{
  const e=fixture();e.window.openSessionPreferences();await flush();const dialog='session-preferences-dialog';assert.equal(e.posts().length,0);
  for(const [key,value]of Object.entries({reply_style:'direct',reply_length:'detailed',rp_intensity:'light',reply_format:'structured'}))e.get('session-preference-'+key).value=value;
  e.behavior.normalizeLength='balanced';await e.click('保存会话偏好',dialog);
  const post=e.posts()[0];assert.equal(post.body.expected_revision,4);assert.equal(post.body.reply_length,'detailed');assert.equal(e.get('session-preference-reply_length').value,'balanced','UI uses actual server readback');
  assert.equal(e.state.sessions[0].tls_state.reply_length,'balanced');assert.equal(e.preferenceFor('owned').mode,'roleplay');assert.equal(e.preferenceFor('owned').scene,'原有剧情不被覆盖');
  e.behavior.normalizeLength=null;await e.click('恢复回复偏好继承',dialog);assert.equal(e.posts().at(-1).body.reset_preferences,true);assert.equal(e.posts().at(-1).body.expected_revision,5);
  for(const key of ['reply_style','reply_length','rp_intensity'])assert.equal(e.get('session-preference-'+key).value,'inherit');assert.equal(e.get('session-preference-reply_format').value,'auto');
  assert.equal(e.preferenceFor('owned').mode,'roleplay');assert.equal(e.preferenceFor('owned').scene,'原有剧情不被覆盖');
  e.get('session-preference-frequency').value='low';e.get('session-preference-cooldown_seconds').value='20';await e.click('保存本会话表情策略',dialog);
  assert.equal(e.posts().at(-1).body.level,'session');assert.equal(e.expressionFor('owned').effective.frequency,'low');await e.click('恢复表情策略继承',dialog);assert.equal(e.posts().at(-1).body.reset,true);assert.equal(e.get('session-preference-frequency').value,'balanced');purposes++;
}
{
  const e=fixture();e.window.openSessionPreferences();await flush();const dialog='session-preferences-dialog';e.get('session-preference-reply_style').value='warm';e.get('session-preference-reply_length').value='detailed';
  e.behavior.preferenceFailure=true;await e.click('保存会话偏好',dialog);const count=e.posts().length;
  assert.match(e.get(dialog).textContent,/旧服务不支持新的会话偏好.*表单保留/);assert.equal(e.get('session-preference-reply_style').value,'warm');assert.equal(e.get('session-preference-reply_length').value,'detailed');
  assert.equal(e.button('保存会话偏好',dialog).disabled,true);await flush();assert.equal(e.posts().length,count,'failure never auto-posts');
  await e.click('重新读取',dialog);assert.equal(e.posts().length,count);e.behavior.oldServer=true;await e.click('重新读取',dialog);assert.match(e.get(dialog).textContent,/会话偏好暂不可用/);assert.equal(e.button('保存会话偏好',dialog).disabled,true);purposes++;
}
{
  const e=fixture();e.behavior.defer='/chat/session-state';e.window.openSessionPreferences();await flush();assert.equal(e.deferred.length,1);
  e.window.ChatSessionPreferences.closeActive();e.deferred.shift().resolve({...copy(e.preferenceFor('owned')),reply_style:'direct'});await flush();assert.equal(e.get('session-preferences-dialog').open,false);
  e.window.openSessionPreferences();await flush();e.state.activeId='other';e.window.ChatSessionPreferences.scopeChanged();e.deferred.shift().resolve({...copy(e.preferenceFor('owned')),reply_style:'warm'});await flush();assert.equal(e.get('session-preferences-dialog').open,false);
  e.window.openSessionPreferences();await flush();e.state.authenticated=false;e.window.ChatSessionPreferences.scopeChanged();e.deferred.shift().resolve(copy(e.preferenceFor('other')));await flush();assert.equal(e.get('session-preferences-dialog').open,false);assert.equal(e.posts().length,0);purposes++;
}
console.log(JSON.stringify({passed:true,purposes,actual_module_callbacks:true,models:0,sends:0,production:false}));
