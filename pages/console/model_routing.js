/* Existing provider IDs only. No key fields, test calls or background polling. */
(function(global){
'use strict';
function mount(root,{api}){
 if(root.__modelRouting)return root.__modelRouting;
 root.innerHTML='<section class="panel model-routing"><div class="panel-head"><div><h2>任务模型分工</h2><p class="hint">普通聊天默认沿用你当前选择。复杂角色互动、摘要和档案处理可使用不同的已有模型；此处不新增模型、不填写密钥。</p></div><button data-model-refresh type="button">读取当前设置</button></div><p data-model-status role="status" aria-live="polite"></p><form data-model-form><div data-model-list></div><div class="actions"><button data-model-save type="submit" class="primary">保存并回读</button><button data-model-cancel type="button">放弃本次修改</button></div></form><p class="hint">首选失败后，原工作流可尝试备选，再保留既有继承链。普通聊天流开始后不会为切换模型而自动重发用户消息。规则分类和记忆筛选本身不额外调用模型。</p></section><section class="panel model-routing"><h2>实际调用与用量</h2><p class="hint">只显示已接通路由的真实调用。Token为提供商实际报告的累计值；缺少报告会标记未知。没有价格资料时，费用保持未知。</p><div data-model-usage></div><details><summary>最近实际调用</summary><div data-model-recent></div></details></section>';
 const $=s=>root.querySelector(s),list=$('[data-model-list]'),status=$('[data-model-status]');
 let data=null,busy=false,pending=null,pendingFailure='',readChecked=false,serial=0,destroyed=false;
 const fields=new Map(),node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;};
 const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const message=(text,error=false)=>{status.textContent=text;status.dataset.error=String(error);};
 const reason=error=>error?.publicMessage||error?.message||'操作结果未确认';
 function controls(){for(const select of fields.values())for(const input of select)input.disabled=busy||!!pending;
  $('[data-model-save]').disabled=busy||!!pending||!data;$('[data-model-cancel]').disabled=busy||!data||!!pending&&!readChecked;$('[data-model-cancel]').textContent=pending?'已核对，结束本次等待':'放弃本次修改';$('[data-model-refresh]').disabled=busy;}
 function selection(){return Object.fromEntries((data?.tasks||[]).map(task=>[task.id,{preferred_provider_id:fields.get(task.id)[0].value,fallback_provider_id:fields.get(task.id)[1].value}]));}
 function render(){
  list.replaceChildren();fields.clear();
  for(const task of data.tasks){const card=node('fieldset'),legend=node('legend',task.label),values=[];card.append(legend);
   for(const [key,label]of [['preferred_provider_id','首选模型'],['fallback_provider_id','备选模型']]){const row=node('label',label),select=node('select');select.setAttribute('aria-label',task.label+' '+label);
    const inherited=node('option','沿用既有模型');inherited.value='';select.append(inherited);
    for(const provider of data.providers){const option=node('option',provider.id+(provider.model?' · '+provider.model:''));option.value=provider.id;select.append(option);}
    const current=data.routes[task.id][key];if(current&&!data.providers.some(p=>p.id===current)){const missing=node('option',current+'（当前不可用，请重新选择）');missing.value=current;missing.disabled=true;select.append(missing);}select.value=current;row.append(select);card.append(row);values.push(select);}
   fields.set(task.id,values);list.append(card);}
  const usage=$('[data-model-usage]');usage.replaceChildren();const table=node('table'),head=node('tr');for(const label of ['任务','真实调用','失败','已报告Token','用量未知','费用'])head.append(node('th',label));table.append(head);
  for(const task of data.tasks){const value=data.usage.tasks[task.id],row=node('tr');for(const text of [task.label,value?.calls||0,value?.failures||0,value?.total_tokens||0,value?.usage_unknown_calls||0,'未知'])row.append(node('td',text));table.append(row);}usage.append(table);
  const recent=$('[data-model-recent]');recent.replaceChildren();for(const item of [...data.usage.recent].reverse()){const row=node('p',new Date(item.at*1000).toLocaleString()+' · '+item.task+' · '+item.provider_id+' · '+(item.success?'已返回':'失败')+' · Token '+(item.usage?.total_tokens??'未知'));recent.append(row);}if(!recent.children.length)recent.append(node('p','尚无此路由记录的实际调用。'));
  controls();
 }
 async function request(method,path,body){const result=await api(method,'page/model-routing/'+path,body);if(!result||result.ok!==true||result.backend!=='task_model_router'||!result.routing)throw Error('后台模型路由响应不完整');return result.routing;}
 async function read(){if(busy||destroyed)return;busy=true;controls();const token=++serial;try{const next=await request('GET','state',{});if(token!==serial||destroyed)return;
   data=next;if(pending){const matched=Object.entries(pending).every(([task,value])=>equal(data.routes[task],value));readChecked=true;if(matched){pending=null;pendingFailure='';readChecked=false;message('已回读，原保存结果已确认。');}else message((pendingFailure?pendingFailure+' ':'')+'已读取当前版本；原保存尚无一致回执，请核对后结束等待，不会自动重发。',true);}else message('已读取现有提供商与任务设置；读取不会调用模型。');render();
  }catch(error){message(reason(error)+(pendingFailure?' 上次保存原因：'+pendingFailure:''),true);}finally{busy=false;controls();}}
 $('[data-model-form]').addEventListener('submit',async event=>{event.preventDefault();if(busy||pending||!data)return;const changes=selection();busy=true;pending=changes;pendingFailure='';readChecked=false;controls();try{const next=await request('POST','settings',{expected_revision:data.revision,changes});if(destroyed)return;data=next;pending=null;pendingFailure='';render();message('任务模型设置已保存并回读；没有发起测试模型调用。');}
  catch(error){pendingFailure=reason(error);message(pendingFailure+' 请读取当前设置核对，不会自动重发。',true);}finally{busy=false;controls();}});
 $('[data-model-refresh]').addEventListener('click',read);$('[data-model-cancel]').addEventListener('click',()=>{if(!data||busy)return;if(pending){if(!readChecked)return;pending=null;pendingFailure='';readChecked=false;render();message('已结束等待，原请求仍可能稍后生效；重新修改前请核对当前值。没有重发。');}else{render();message('已放弃本次未保存修改。');}});
 const controller={activate:read,setScope:()=>{},destroy(){destroyed=true;serial++;}};root.__modelRouting=controller;controls();return controller;
}
global.TLSModelRouting={mount};
})(window);
