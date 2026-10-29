import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../web/chat-notification-preferences.js',import.meta.url),'utf8');
function setup(available=true){
  const ids=new Map(),ready=[];let saves=[],refreshes=0,reject=false;
  class Node{
    constructor(tag){this.tag=tag;this.children=[];this.events={};this.textContent='';this.type='';this.value='';this.disabled=false;}
    set id(value){this._id=value;ids.set(value,this);} get id(){return this._id;}
    append(...items){this.children.push(...items);} replaceChildren(){this.children=[];}
    setAttribute(){} addEventListener(name,fn){this.events[name]=fn;}
    click(){this.events.click?.();}
  }
  const root=new Node('div');root.id='notification-preferences';const dialog=new Node('dialog');dialog.id='settings-dialog';
  const defaults={ok:true,enabled:true,reply:true,proactive:true,reminder:true,preview:true,quiet_enabled:false,quiet_start:'22:00',quiet_end:'08:00',click_target:'message'};
  const window={ChatNotificationStatus:{refresh(){refreshes++;}},AsteriaChat:available?{
    getNotificationPreferences(){return JSON.stringify(defaults);},
    setNotificationPreferences(value){saves.push(JSON.parse(value));return JSON.stringify(reject?{ok:false}:{...JSON.parse(value),ok:true});}
  }:undefined};
  const context={window,document:{getElementById:id=>ids.get(id),createElement:tag=>new Node(tag),addEventListener:(event,fn)=>ready.push(fn)},MutationObserver:class{observe(){}}};
  vm.runInNewContext(source,context);ready.forEach(fn=>fn());
  return{ids,root,saves,get refreshes(){return refreshes;},set reject(value){reject=value;},button:()=>root.children.find(node=>node.tag==='button'),status:()=>root.children.at(-1)};
}
{
  const ui=setup();assert.equal(ui.saves.length,0,'viewing preferences must be read-only');
  assert.equal(ui.ids.get('notification-pref-quiet_start').disabled,true);
  ui.ids.get('notification-pref-quiet_enabled').checked=true;ui.ids.get('notification-pref-quiet_enabled').events.change();
  assert.equal(ui.ids.get('notification-pref-quiet_start').disabled,false);
  ui.ids.get('notification-pref-reply').checked=false;ui.ids.get('notification-pref-preview').checked=false;
  ui.ids.get('notification-pref-click_target').value='conversation';ui.button().click();
  assert.equal(ui.saves.length,1);assert.equal(ui.saves[0].reply,false);assert.equal(ui.saves[0].proactive,true);assert.equal(ui.saves[0].reminder,true);
  assert.equal(ui.saves[0].preview,false);assert.equal(ui.saves[0].quiet_start,'22:00');assert.equal(ui.saves[0].quiet_end,'08:00');assert.equal(ui.saves[0].click_target,'conversation');
  assert.equal(ui.refreshes,1);assert.match(ui.status().textContent,/已保存/);
  ui.ids.get('notification-pref-quiet_start').value='24:00';ui.button().click();assert.equal(ui.saves.length,1);assert.match(ui.status().textContent,/有效/);
  ui.ids.get('notification-pref-quiet_start').value='22:00';ui.reject=true;ui.button().click();assert.match(ui.status().textContent,/未保存/);
  ui.ids.get('notification-pref-enabled').checked=false;ui.ids.get('notification-pref-enabled').events.change();assert.equal(ui.ids.get('notification-pref-reply').disabled,true);
}
{
  const unavailable=setup(false);assert.equal(unavailable.button(),undefined);assert.equal(unavailable.saves.length,0);
  assert.match(unavailable.root.children.at(-1).textContent,/无法读取/);
}
console.log('notification preferences read-only load, persisted choices, quiet window validation and error handling passed');
