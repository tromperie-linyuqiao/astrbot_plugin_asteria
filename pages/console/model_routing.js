/* Existing provider IDs only. No key fields, test calls or background polling. */
(function(global){
'use strict';
function mount(root,{api}){
 if(root.__modelRouting)return root.__modelRouting;
 root.innerHTML='<section class="panel model-routing"><div class="panel-head"><div><h2>任务分工</h2><p class="hint">展开任务，设置首选和备选模型。普通聊天仍用当前已选模型。</p></div><button data-model-refresh type="button">读取当前设置</button></div><p data-model-status role="status" aria-live="polite"></p><form data-model-form><div data-model-list></div><div class="actions"><button data-model-save type="submit" class="primary">保存并回读</button><button data-model-cancel type="button">放弃本次修改</button></div></form><details class="model-routing-note"><summary>回退与适用范围</summary><p class="hint">首选失败后，原工作流可尝试备选。普通聊天流开始后不会为切换模型自动重发；规则分类和记忆筛选本身不额外调用模型。</p></details></section><section class="panel model-routing"><h2>实际调用与用量</h2><p class="hint">统计已接入任务的调用记录。用量来自提供商的报告。</p><div data-model-usage role="region" aria-label="任务调用与用量表" tabindex="0"></div><details><summary>最近实际调用</summary><div data-model-recent></div></details></section>';
 const $=s=>root.querySelector(s),list=$('[data-model-list]'),status=$('[data-model-status]');
 let data=null,base=null,busy=false,pending=null,pendingFailure='',readChecked=false,needsRead=false,serial=0,destroyed=false;
 let conflicts=[];
 const fields=new Map(),node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);return n;};
 const review=node('section');review.className='model-routing-note';review.hidden=true;list.after(review);
 const message=(text,error=false)=>{status.textContent=text;status.dataset.error=String(error);};
 const reason=error=>error?.publicMessage||error?.message||'操作结果未确认';
 function controls(){for(const select of fields.values())for(const input of select)input.disabled=busy||!!pending;
  $('[data-model-save]').disabled=busy||!!pending||!data||needsRead||conflicts.length>0;
  $('[data-model-cancel]').disabled=busy||!data||!!pending&&!readChecked;
  $('[data-model-cancel]').textContent=pending?'已核对，结束本次等待':'放弃本次修改';$('[data-model-refresh]').disabled=busy;
  for(const button of review.querySelectorAll('button'))button.disabled=busy;}
 function selection(){return Object.fromEntries((data?.tasks||[]).map(task=>[task.id,{preferred_provider_id:fields.get(task.id)[0].value,fallback_provider_id:fields.get(task.id)[1].value}]));}
 function renderReview(){
  review.replaceChildren();review.hidden=pending!==null||!conflicts.length;if(review.hidden)return;
  review.append(node('h3','核对同时改动的任务'));
  for(const id of conflicts){const route=data.routes[id],task=data.tasks.find(item=>item.id===id);
   review.append(node('p',task.label+' · 服务器首选：'+(route.preferred_provider_id||'继承')+' · 备选：'+(route.fallback_provider_id||'继承')));}
  function choose(useServer){
   if(busy||pending||!conflicts.length)return;
   const choices=selection();if(useServer)for(const id of conflicts)choices[id]=data.routes[id];
   conflicts=[];base={...data.routes};render(choices);
   message('已核对冲突任务，请检查后再保存。');
  }
  for(const [label,useServer] of [['采用服务器的冲突设置',true],['保留我的冲突设置',false]]){
   const button=node('button',label);button.type='button';button.addEventListener('click',()=>choose(useServer));review.append(button);}
 }
 function render(routes=data.routes){
  const hadTasks=list.childElementCount>0;
  const expanded=new Set([...list.querySelectorAll('details[open]')].map(item=>item.dataset.task));
  list.replaceChildren();fields.clear();
  for(const [index,task] of data.tasks.entries()){
   const taskDetails=node('details');
   taskDetails.className='model-task';
   taskDetails.dataset.task=task.id;
   taskDetails.open=hadTasks?expanded.has(task.id):index===0;
   const card=node('fieldset'),legend=node('legend',task.label),values=[];
   legend.className='sr-only';card.append(legend);
   taskDetails.append(node('summary',task.label),card);
   for(const [key,label]of [['preferred_provider_id','首选模型'],['fallback_provider_id','备选模型']]){const row=node('label',label),select=node('select');select.setAttribute('aria-label',task.label+' '+label);
    const inherited=node('option','沿用既有模型');inherited.value='';select.append(inherited);
    for(const provider of data.providers){const option=node('option',provider.id+(provider.model?' · '+provider.model:''));option.value=provider.id;select.append(option);}
    const current=routes[task.id][key];if(current&&!data.providers.some(p=>p.id===current)){const missing=node('option',current+'（当前不可用，请重新选择）');missing.value=current;missing.disabled=true;select.append(missing);}select.value=current;row.append(select);card.append(row);values.push(select);}
   fields.set(task.id,values);list.append(taskDetails);}
  const usage=$('[data-model-usage]');
  usage.replaceChildren();
  const table=node('table'),headers=node('thead'),head=node('tr'),rows=node('tbody');
  for(const label of ['任务','调用记录','失败','已报告 Token','用量未知','费用']){
   const cell=node('th',label);
   cell.scope='col';head.append(cell);
  }
  headers.append(head);table.append(headers,rows);
  for(const task of data.tasks){
   const value=data.usage.tasks[task.id],row=node('tr'),title=node('th',task.label);
   title.scope='row';row.append(title);
   for(const text of [value?.calls??'—',value?.failures??'—',value?.total_tokens??'—',value?.usage_unknown_calls??'—','未知'])row.append(node('td',text));
   rows.append(row);
  }
  usage.append(table);
  const recent=$('[data-model-recent]');recent.replaceChildren();for(const item of [...data.usage.recent].reverse()){const taskLabel=data.tasks.find(task=>task.id===item.task)?.label||'未分类任务',elapsed=Number.isSafeInteger(item.elapsed_ms)&&item.elapsed_ms>=0?item.elapsed_ms+' 毫秒':'未知',failure=item.success?'':' · 失败类型：'+(item.error_type||'未知');const row=node('p',new Date(item.at*1000).toLocaleString()+' · '+taskLabel+' · '+item.provider_id+' · '+(item.success?'已返回':'失败')+' · 耗时 '+elapsed+failure+' · Token '+(item.usage?.total_tokens??'未知'));recent.append(row);}if(!recent.children.length)recent.append(node('p','尚无此路由记录的实际调用。'));
  renderReview();controls();
 }
 async function request(method,path,body){const result=await api(method,'page/model-routing/'+path,body);if(!result||result.ok!==true||result.backend!=='task_model_router'||!result.routing)throw Error('后台模型路由响应不完整');return result.routing;}
 function applyLatest(next,editing){
  const edits=global.TLSRecordEdits,previous=base||next.routes;
  const local=edits.changes(editing,previous);
  data=next;base={...next.routes};
  conflicts=edits.conflicts(local,previous,next.routes);
  for(const id of conflicts)base[id]=previous[id];
  render({...next.routes,...local});
  return Object.keys(local).length>0;
 }
 function clearPending(){pending=null;pendingFailure='';readChecked=false;}
 async function read(){
  if(busy||destroyed)return;
  const editing=selection(),token=++serial;busy=true;controls();
  try{
   const next=await request('GET','state',{});
   if(token!==serial||destroyed)return;
   needsRead=false;
   if(pending){
    data=next;readChecked=true;
    const remaining=global.TLSRecordEdits.changes(pending,next.routes);
    if(Object.keys(remaining).length)message((pendingFailure?pendingFailure+' ':'')+'已读取当前版本；原保存尚无一致回执，请核对后结束等待，不会自动重发。',true);
    else{clearPending();base={...next.routes};message('已回读，原保存结果已确认。');}
    render();return;
   }
   const edited=applyLatest(next,editing);
   message(conflicts.length?'已读取最新版本，请核对同时改动的任务。'
    :edited?'已读取当前版本，未保存的任务设置已保留。':'已读取现有提供商与任务设置；读取不会调用模型。');
  }catch(error){if(!destroyed)message(reason(error)+(pendingFailure?' 上次保存原因：'+pendingFailure:''),true);}
  finally{busy=false;if(!destroyed)controls();}
 }
 $('[data-model-form]').addEventListener('submit',async event=>{
  event.preventDefault();if(busy||pending||!data||needsRead||conflicts.length)return;
  const changes=global.TLSRecordEdits.changes(selection(),data.routes);
  if(!Object.keys(changes).length){message('任务设置没有变化。');return;}
  const revision=data.revision;
  busy=true;pending=changes;controls();
  try{
   const next=await request('POST','settings',{expected_revision:revision,changes});
   if(destroyed)return;
   if(!(next.revision>revision)||Object.keys(global.TLSRecordEdits.changes(changes,next.routes)).length)
    throw Error('回执尚未确认本次修改。');
   clearPending();data=next;base={...next.routes};render();
   message('任务模型设置已保存并回读；没有发起测试模型调用。');
  }catch(error){
   if(destroyed)return;
   if(Number(error?.status)===409&&!error.outcomeUnknown){
    clearPending();needsRead=true;message(reason(error)+' 未保存的选择仍保留，请读取最新版本。',true);
   }else{
    pendingFailure=reason(error);message(pendingFailure+' 请读取当前设置核对，不会自动重发。',true);
   }
  }finally{busy=false;if(!destroyed)controls();}
 });
 $('[data-model-refresh]').addEventListener('click',read);
 $('[data-model-cancel]').addEventListener('click',()=>{
  if(!data||busy)return;
  if(pending){
   if(!readChecked)return;
   const editing=pending;clearPending();applyLatest(data,editing);
   message('已结束等待，原请求仍可能稍后生效。未确认的选择已保留，请先核对。');
  }else{
   conflicts=[];base={...data.routes};render();
   message('已放弃本次未保存修改。');
  }
 });
 const controller={activate:read,setScope:()=>{},destroy(){destroyed=true;serial++;}};root.__modelRouting=controller;controls();return controller;
}
global.TLSModelRouting={mount};
})(window);
