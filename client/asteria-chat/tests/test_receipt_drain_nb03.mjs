import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const shared=new Map(),calls=[];
const key='asteria-chat.receipts.'+JSON.stringify(['https://fixture.invalid','owner','session']);
shared.set(key,JSON.stringify(Object.fromEntries(Array.from({length:64},(_,i)=>[String(i+1),{client_received:true}]))));
const state={authenticated:true,server:'https://fixture.invalid',username:'owner',activeId:'session'};
const observed=new Set();
const context={window:{},state,document:{getElementById:()=>null},recoveryForeground:()=>true,
 localStorage:{getItem:k=>shared.get(k)||null,setItem:(k,v)=>shared.set(k,v)},
 apiClient:{async json(method,path,body){calls.push({method,path,body});body.message_ids.forEach(id=>observed.add(id));
 return{schema:1,messages:[...observed].map(message_id=>({message_id,client_received_at:100}))};}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(new URL('../web/chat-receipts.js',import.meta.url),'utf8'),context);
context.window.ChatReceipts.historyReceived('session',{receipt_transport:{schema:1,supported:true},
 history:Array.from({length:64},(_,i)=>({id:i+1,content:{type:'bot'}}))});
await new Promise(resolve=>setImmediate(resolve));
assert.equal(calls.length,2);assert.equal(observed.size,64);
assert(calls.every(c=>c.path==='/chat/receipts'&&c.body.message_ids.length<=32));
assert.deepEqual(JSON.parse(shared.get(key)),{});
console.log('NB03 bounded64 receipt outbox drains both32 batches without chat send');
