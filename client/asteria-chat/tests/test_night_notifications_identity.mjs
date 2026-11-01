/* Actual JS notification lifetime and receipt hooks. No browser/device/server. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const night = await fs.readFile(new URL('../web/chat-night.js', import.meta.url), 'utf8');
const receipts = await fs.readFile(new URL('../web/chat-receipts.js', import.meta.url), 'utf8');
let purposes = 0;
{
  const elements = new Map(), timers = new Map(), listeners = new Map(); let sequence = 0;
  const get = id => { if (!elements.has(id)) elements.set(id, {hidden:true,textContent:'',onclick:null}); return elements.get(id); };
  const state = {authenticated:true,server:'https://fixture.invalid',username:'owner',activeId:'one'};
  const context = vm.createContext({window:{addEventListener:(name,fn)=>listeners.set(name,fn)},
    document:{getElementById:get,addEventListener(){}}, state, Map,Set,WeakMap,WeakSet,JSON,Math,String,
    showNotice(message,action,error){get('notice').hidden=false;get('notice-text').textContent=message;
      get('notice-action').hidden=!action;get('notice-action').textContent=action?.label||'';get('notice-action').onclick=action?.run||null;},
    hideNotice(){get('notice').hidden=true;get('notice-action').onclick=null;get('notice-action').hidden=true;},
    setTimeout(fn,ms){const id=++sequence;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),hideMoreMenu(){}
  });
  const marker='return {openBody,openUserAvatar,readUserAvatar,requestClose,paintAvatar,scopeChanged};';
  assert(night.includes(marker));
  vm.runInContext(night.replace(marker,marker.replace('scopeChanged}', 'scopeChanged,installNotices}')),context);
  context.window.ChatNight.installNotices();
  context.showNotice('已保存');const first=[...timers.entries()][0];
  for(let i=0;i<10;i++)context.showNotice('已保存');
  assert.equal(timers.size,1);assert.equal([...timers.keys()][0],first[0]);
  const stale=first[1].fn;
  context.showNotice('需要你核对',null,true);assert.equal(timers.size,0);stale();
  assert.equal(get('notice').hidden,false);assert.equal(get('notice-text').textContent,'需要你核对');purposes++;
  const action={label:'核对',run(){}};context.showNotice('结果未知',action);assert.equal(timers.size,0);
  state.activeId='two';context.window.ChatNight.scopeChanged();
  assert.equal(get('notice').hidden,true);assert.equal(get('notice-text').textContent,'');
  assert.equal(get('notice-action').onclick,null);assert.equal(get('notice-action').textContent,'');purposes++;
  context.showNotice('同步完成');listeners.get('pagehide')();assert.equal(get('notice').hidden,true);assert.equal(timers.size,0);
  listeners.get('pageshow')();context.showNotice('再打开一次');assert.equal(timers.size,1);
  [...timers.values()][0].fn();assert.equal(get('notice').hidden,true);assert.equal(timers.size,0);purposes++;
}
{
  const storage = new Map(), cleared = [], posts = [];
  let foreground = true;
  const state = {authenticated:true,server:'https://fixture.invalid',username:'owner',activeId:'one',cacheDisplay:null};
  const context = vm.createContext({state,window:{AsteriaChat:{clearMessageNotification:(sid,id)=>cleared.push({sid,id})}},
    document:{getElementById:()=>null},localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    recoveryForeground:()=>foreground,Set,JSON,Object,Array,String,Promise,
    apiClient:{json:async(method,path,body)=>{posts.push({method,path,body});return {schema:1,messages:[]};}}
  });
  vm.runInContext(receipts,context);const receipt=context.window.ChatReceipts;
  const snapshot=supported=>({history:[{id:10,content:{type:'bot'}},{id:11,content:{type:'bot'}}],
    receipt_transport:{schema:1,supported}});
  const settle=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
  receipt.historyReceived('one',snapshot(true));await settle();
  assert.equal(cleared.length,0);assert(posts.every(row=>row.body.phase==='client_received'));purposes++;
  receipt.notificationOpened('one','10');assert.equal(cleared.length,0);
  receipt.historyReceived('one',snapshot(true));await settle();
  assert.deepEqual(cleared,[{sid:'one',id:'10'}]);
  assert(posts.some(row=>row.body.phase==='user_opened'&&row.body.message_ids.length===1&&row.body.message_ids[0]==='10'));
  assert(!posts.some(row=>row.body.phase==='user_opened'&&row.body.message_ids.includes('11')));purposes++;
  receipt.notificationOpened('one','11');state.cacheDisplay={cached:true};receipt.historyReceived('one',snapshot(true));await settle();
  assert.equal(cleared.length,1);state.cacheDisplay=null;foreground=false;
  receipt.historyReceived('one',snapshot(true));await settle();assert.equal(cleared.length,1);
  foreground=true;receipt.historyReceived('one',snapshot(true));await settle();assert.deepEqual(cleared.at(-1),{sid:'one',id:'11'});purposes++;
  const before=cleared.length;assert.equal(receipt.messageOpened('one','missing'),false);
  state.activeId='other';assert.equal(receipt.messageOpened('one','10'),false);assert.equal(cleared.length,before);
  state.activeId='one';posts.length=0;receipt.historyReceived('one',snapshot(false));
  assert.equal(receipt.messageOpened('one','10'),true);await settle();
  assert.deepEqual(cleared.at(-1),{sid:'one',id:'10'});assert.equal(posts.length,0);purposes++;
}
console.log(JSON.stringify({purposes,passed:true,network:0,android_device:false}));
