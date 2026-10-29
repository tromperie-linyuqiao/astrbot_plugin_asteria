/* NB03: execute actual normalizer/render callbacks, no live API/model/device. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source=await fs.readFile(new URL('../web/chat-compose.js',import.meta.url),'utf8');
class Element{
  constructor(){this.children=[];this.textContent='';this.className='';}
  append(...nodes){this.children.push(...nodes);}
}
const context=vm.createContext({window:{},document:{createElement:()=>new Element()},mediaPart:part=>({type:part.type,attachment_id:part.attachment_id}),Map,Set,Array,Object,JSON,Number,String,Date,Math,Promise});
vm.runInContext(source,context,{filename:'chat-compose.js'});
const ui=context.window.ChatComposer,clone=value=>JSON.parse(JSON.stringify(value));
const sourceResult={source:'tls.chat.native_touch',state:'native_touch_applied',applied:1,
  parts:['head'],character:'texas',applied_at:1730000000,body_updated_at:'2024-10-27T00:00:00Z'};
const parts=ui.normalizeParts([
  {type:'action',action_id:'headpat',label:'摸头',description:'轻轻摸摸头',source:'user_action',fragment_id:'action-1',order:0,native_result:sourceResult},
  {type:'speech',text:'今天怎么样？',fragment_id:'text-1',order:1},
  {type:'sticker',asset_id:'asset-1',label:'平静',fragment_id:'sticker-1',order:2},
]);
assert.deepEqual(clone(parts).map(part=>[part.type,part.fragment_id,part.order]),[
  ['action','action-1',0],['plain','text-1',1],['sticker','sticker-1',2],
]);
assert.deepEqual(clone(parts[0].native_result),sourceResult);
const view=ui.renderPart(parts[0]);
assert.equal(view.children[0].textContent,'身体事件已处理');
assert.match(view.children[0].title,/冷却和阶段规则/);
const narrative=ui.normalizeParts([{type:'action',description:'轻轻靠着你',source:'assistant_narrative',native_result:sourceResult}])[0];
assert.equal(narrative.native_result,undefined);
assert.equal(ui.renderPart(narrative).children.length,0);
const unchecked=ui.normalizeParts([{type:'action',source:'user_action',native_result:{state:'native_touch_applied',applied:1}}])[0];
assert.equal(unchecked.native_result,undefined);
const roleplay=ui.normalizeParts([{type:'action',source:'user_action',native_result:{...sourceResult,state:'roleplay_input',applied:0}}])[0];
assert.equal(ui.renderPart(roleplay).children[0].textContent,'已交给角色回应');
const media=ui.normalizeParts([{type:'attachment',attachment_id:'a',fragment_id:'media-a',order:3},
 {type:'image',attachment_id:'b',fragment_id:'media-b',order:4}]);
assert.deepEqual(clone(media).map(p=>[p.type,p.fragment_id,p.order]),[['file','media-a',3],['image','media-b',4]]);
console.log(JSON.stringify({passed:true,purposes:5,production:false,android:false,models:0,sends:0}));
