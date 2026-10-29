import assert from 'node:assert/strict';
import fs from 'node:fs';import vm from 'node:vm';
const nodes=new Map(),calls=[];
const state={authenticated:true,server:'https://fixture.invalid',username:'owner',activeId:'session',
 messages:[{role:'assistant',delivery:'confirmed',serverId:'100'}]};
const context={window:{},state,document:{getElementById:id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',checked:false});return nodes.get(id);}},
 recoveryForeground:()=>true,primaryConnectionId:()=> 'session',pref:v=>v,storage:{set(){}},
 parse:JSON.parse,native:()=>({ackReplyWatch:(sid,id)=>{calls.push([sid,id]);return JSON.stringify({ok:true});}})};
vm.createContext(context);vm.runInContext(fs.readFileSync(new URL('../web/chat-compose.js',import.meta.url),'utf8'),context);
const ui=context.window.ChatComposer;
ui.watchChanged({running:true,session_id:'session',state:'running'});
ui.historyReceived('session');ui.historyReceived('session');assert.equal(calls.length,1);
ui.watchChanged({running:true,session_id:'session',state:'running',message_sync:'cursor_unavailable'});
ui.historyReceived('session');assert.equal(calls.length,2,'real foreground reread can re-ack unchanged assistant after a missing user-row cursor');
state.activeId='foreign';ui.historyReceived('session');assert.equal(calls.length,2);
console.log('NB03 real history callback re-ack gap without another chat send or scope adoption');
