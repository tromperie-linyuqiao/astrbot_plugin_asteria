/* Explicit logical maintenance. No background restore, retry or deletion. */
(function (global) {
  'use strict';
  const root=document.getElementById('material-maintenance-mount'); if(!root)return;
  const FIELDS=['platform','bot_id','user_id','character_id','session_id'];
  const labels={memories:'普通记忆资料',agreements:'长期约定',goal_definitions:'目标定义（仅导出）'};
  let scope=null,serial=0,busy=false,bundle=null,restorePlan=null,repairPlan=null,pending=null;
  let recordPage=null,recordOffset=0,bulkPlan=null;const selectedRecords=new Map();
  const key=s=>JSON.stringify(FIELDS.map(k=>s&&s[k]));
  const current=()=>typeof state==='object'&&state.scope?Object.fromEntries(FIELDS.map(k=>[k,state.scope[k]])):null;
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  root.innerHTML=`<section class="panel material-maintenance"><div class="panel-head"><div><h2>备份与维护</h2><p class="hint">资料定义的逻辑备份；不操作执行账本、任务、租约或原始文件。</p></div><button data-mm="refresh" type="button">刷新容量</button></div><p data-mm="scope" class="drawer-scope"></p><div data-mm="capacity" class="mm-capacity"></div><p data-mm="notice" class="hint" role="status" aria-live="polite"></p><div data-mm="pending" class="mm-pending" hidden><p>上次请求结果需要核对。不会自动再次提交。</p><code data-mm="request"></code><button data-mm="receipt" type="button">查询原请求回执</button><pre data-mm="receipt-result"></pre></div></section>
  <section class="panel material-maintenance"><div class="panel-head"><h2>批量整理普通记忆</h2><button data-mm="records-refresh" type="button">读取当前资料列表</button></div><p class="hint">每页最多20项。勾选后先查看每条修订与冲突，再一次确认软归档或恢复。原文、来源和历史保留；特殊核心约定、画像及执行记录不在这里批量处理。</p><div class="mm-controls"><label class="mm-check"><input data-mm="include-archived" type="checkbox">包含已归档资料</label><label class="mm-check"><input data-mm="select-all" type="checkbox">选中本页可操作项</label><span data-mm="selected-count" class="hint">尚未选择</span></div><div data-mm="records" class="mm-record-list"></div><div class="actions"><button data-mm="records-prev" type="button">上一页</button><span data-mm="records-range" class="hint"></span><button data-mm="records-next" type="button">下一页</button></div><div class="mm-controls"><label>批量操作<select data-mm="bulk-operation"><option value="archive">软归档所选普通记忆</option><option value="restore">恢复所选已归档普通记忆</option></select></label><button data-mm="bulk-preview" type="button">预览所选资料与冲突</button></div><div data-mm="bulk-result"></div><label class="mm-confirm"><input data-mm="bulk-check" type="checkbox">我已核对本批每条内容和修订，只执行预览中的软归档/恢复；不永久删除、不处理核心资料或业务账本。</label><button data-mm="bulk-confirm" type="button" class="primary" disabled>确认整批操作</button></section>
  <section class="panel material-maintenance"><h2>保存一份资料备份</h2><p class="hint">每份最多读取各类20项。导出文件包含私人正文，请自行保管；不是数据库或整机快照。归档、特殊资料和不支持的记录会明确列出，不假称完整。</p><div class="mm-choices"><label><input data-mm-kind="memories" type="checkbox" checked>记忆资料</label><label><input data-mm-kind="agreements" type="checkbox" checked>长期约定</label><label><input data-mm-kind="goal_definitions" type="checkbox" checked>目标定义</label></div><div class="mm-controls"><label>每类条数<input data-mm="limit" type="number" min="1" max="20" value="20"></label><label>起始位置<input data-mm="offset" type="number" min="0" max="1000000" value="0"></label><button data-mm="export" type="button">读取并保存 JSON</button></div><div data-mm="export-result"></div></section>
  <section class="panel material-maintenance"><h2>从逻辑备份追加恢复</h2><p class="hint">先选择文件，再预览。只接受完全相同的用户、角色和会话范围；不会覆盖冲突、自动恢复归档，或将备份当作新的传感器证据。目标进度与执行事件不回放。</p><label class="mm-file">选择备份文件<input data-mm="file" type="file" accept="application/json,.json"></label><p data-mm="file-info" class="hint"></p><div class="mm-controls"><label>本次恢复类型<select data-mm="restore-kind"><option value="memories">记忆资料</option><option value="agreements">长期约定</option></select></label><button data-mm="restore-preview" type="button">预览冲突和新增项</button></div><div data-mm="restore-result"></div><label class="mm-confirm"><input data-mm="restore-check" type="checkbox">本人确认：追加到当前完全相同范围，不覆盖已有资料；备份内容作为本人确认资料，不冒充新观察。</label><button data-mm="restore-confirm" type="button" class="primary" disabled>确认追加恢复</button></section>
  <section class="panel material-maintenance"><h2>可确证的引用修复</h2><p class="hint">仅重建从当前原文可确定的词法检索索引，或移除引用不存在记录的派生索引项。不会删正文、记忆历史、事件或执行账本；缺失旧档案和素材原件只报问题，不猜测替换。</p><div class="mm-controls"><label>扫描记录数<input data-mm="repair-limit" type="number" min="1" max="200" value="100"></label><button data-mm="repair-preview" type="button">预览派生索引差异</button></div><div data-mm="repair-result"></div><label class="mm-confirm"><input data-mm="repair-check" type="checkbox">我确认只修复以上派生检索索引，保留全部原资料和业务账本。</label><button data-mm="repair-confirm" type="button" disabled>确认修复派生索引</button></section>`;
  const $=name=>root.querySelector('[data-mm="'+name+'"]');
  function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('mm-error',error);}
  function pendingKey(){return 'tls.maintenance.pending.'+encodeURIComponent(key(scope));}
  function remember(value){pending=value;try{if(value)sessionStorage.setItem(pendingKey(),JSON.stringify(value));else sessionStorage.removeItem(pendingKey());}catch(_){}drawPending();}
  function drawPending(){ $('pending').hidden=!pending;$('request').textContent=pending?pending.request_id:'';controls(); }
  function controls(){
    for(const name of ['export','restore-preview','repair-preview'])$(name).disabled=busy||!scope||!!pending;
    $('restore-confirm').disabled=busy||!scope||!!pending||!restorePlan||restorePlan.can_restore!==true||!$('restore-check').checked;
    $('repair-confirm').disabled=busy||!scope||!!pending||!repairPlan||!repairPlan.repairable||!$('repair-check').checked;
    $('refresh').disabled=busy||!scope;$('receipt').disabled=busy||!pending;
    $('records-refresh').disabled=busy||!scope;
    $('records-prev').disabled=busy||!scope||recordOffset===0;
    $('records-next').disabled=busy||!scope||!recordPage||!recordPage.has_more;
    $('include-archived').disabled=busy||!scope;
    $('select-all').disabled=busy||!scope||!!pending||!recordPage;
    $('bulk-operation').disabled=busy||!!pending;
    $('bulk-preview').disabled=busy||!scope||!!pending||!selectedRecords.size;
    $('bulk-confirm').disabled=busy||!scope||!!pending||!bulkPlan||bulkPlan.can_apply!==true||!$('bulk-check').checked;
    for(const check of $('records').querySelectorAll('input[type="checkbox"]'))check.disabled=busy||!!pending||check.dataset.eligible!=='true';
  }
  async function call(method,path,data){
    if(!scope||typeof api!=='function')throw Error('请先选择完整真实会话。');
    const expected=key(scope);
    const value=await api(method,'page/material-maintenance/'+path,data);
    const body=value&&value.ok===true?value:value&&value.data;
    if(!body||body.ok!==true||key(body.scope)!==expected||!body.maintenance)throw Error('维护响应范围或格式不匹配。');
    return body.maintenance;
  }
  async function run(task){
    if(busy)return;busy=true;controls();const version=serial,original=key(scope);
    try{await task(()=>version===serial&&original===key(current()));}
    catch(error){if(version===serial)notice(typeof errorMessage==='function'?errorMessage(error):String(error.message||error),true);}
    finally{if(version===serial){busy=false;controls();}}
  }
  function jsonDetail(target,value,label='查看完整预览'){
    const d=el('details'),s=el('summary',label),p=el('pre',JSON.stringify(value,null,2));d.append(s,p);target.append(d);
  }
  function drawCap(value){
    const target=$('capacity');target.replaceChildren();
    for(const [id,label]of [['memories','原生记忆'],['agreements','长期约定'],['goal_definitions','目标定义'],['journal','共享日志记录']]){
      const v=value.capacity[id],card=el('div',undefined,'mm-capacity-card');card.append(el('span',label),el('strong',v.used===null?'未知':String(v.used)),el('small',v.limit===null?'未配置条数上限':'上限 '+v.limit));if(id==='journal')card.append(el('small','全Host共享，不代表此用户'));target.append(card);
    }
    $('scope').textContent='当前用户 '+scope.user_id+' · 角色 '+scope.character_id+' · 当前会话';
    notice('容量来自当前授权资料服务；数据库字节不等于磁盘可用空间。');
  }
  function clearBulkPreview(){bulkPlan=null;$('bulk-check').checked=false;$('bulk-result').replaceChildren();controls();}
  function selectionChanged(){
    clearBulkPreview();$('selected-count').textContent=selectedRecords.size?'已选 '+selectedRecords.size+' 项（最多20项）':'尚未选择';
    const choices=(recordPage&&recordPage.records||[]).filter(row=>row.bulk_eligible);
    $('select-all').checked=choices.length>0&&choices.every(row=>selectedRecords.has(row.id));
  }
  function drawRecords(value){
    recordPage=value;selectedRecords.clear();const target=$('records');target.replaceChildren();
    for(const row of value.records){
      const card=el('article',undefined,'mm-record-card'),heading=el('label',undefined,'mm-record-head'),check=el('input');check.type='checkbox';check.dataset.eligible=String(row.bulk_eligible);check.disabled=!row.bulk_eligible;
      check.addEventListener('change',()=>{if(check.checked)selectedRecords.set(row.id,{id:row.id,expected_revision:row.revision});else selectedRecords.delete(row.id);selectionChanged();});
      heading.append(check,el('strong',(row.archived?'已归档 · ':'')+(row.memory_type||'资料')),el('small','修订 '+row.revision));
      card.append(heading,el('p',row.content===null?'内容因身份不一致而保留，需单项核对。':row.content,'mm-record-content'),el('small','来源：'+row.source_id+' · '+row.id));
      if(row.held_reason)card.append(el('p',row.held_reason,'mm-error'));target.append(card);
    }
    if(!value.records.length)target.append(el('p','当前条件下没有资料。','hint'));
    $('records-range').textContent=value.total?'当前 '+(value.offset+1)+'–'+(value.offset+value.records.length)+' / '+value.total+' 项':'0 项';selectionChanged();
  }
  async function loadRecords(valid){const value=await call('GET','records',{...scope,include_archived:$('include-archived').checked,limit:20,offset:recordOffset});if(valid())drawRecords(value);}
  $('records-refresh').addEventListener('click',()=>run(loadRecords));
  $('include-archived').addEventListener('change',()=>{recordOffset=0;run(loadRecords);});
  $('records-prev').addEventListener('click',()=>{recordOffset=Math.max(0,recordOffset-20);run(loadRecords);});
  $('records-next').addEventListener('click',()=>{if(recordPage&&recordPage.has_more){recordOffset=recordPage.next_offset;run(loadRecords);}});
  $('select-all').addEventListener('change',()=>{const checked=$('select-all').checked;selectedRecords.clear();for(const row of recordPage&&recordPage.records||[])if(checked&&row.bulk_eligible)selectedRecords.set(row.id,{id:row.id,expected_revision:row.revision});for(const n of $('records').querySelectorAll('input[type="checkbox"]'))if(n.dataset.eligible==='true')n.checked=checked;selectionChanged();});
  $('bulk-operation').addEventListener('change',clearBulkPreview);
  $('bulk-preview').addEventListener('click',()=>run(async valid=>{
    const value=await call('POST','bulk/preview',{scope,operation:$('bulk-operation').value,items:[...selectedRecords.values()]});if(!valid())return;
    bulkPlan=value;$('bulk-check').checked=false;const target=$('bulk-result');target.replaceChildren(el('p',value.can_apply?'整批可操作；请逐项核对内容和修订。':'本批存在冲突或不支持项，整批不会执行。',value.can_apply?'hint':'mm-error'));
    const states={ready:'将执行',unchanged:'不变',missing:'不存在',unsupported:'不可操作',conflict:'修订冲突'};
    for(const row of value.records){const item=el('div',undefined,'mm-bulk-preview');item.append(el('strong',(states[row.status]||row.status)+' · 预期修订 '+row.expected_revision+' / 当前 '+(row.current_revision??'无')),el('p',row.content||row.id),el('small',row.reason));target.append(item);}notice('批量预览完成，尚未修改资料。');
  }));
  $('bulk-check').addEventListener('change',controls);
  function download(value){
    const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=el('a');
    a.href=url;a.download='TLS-资料逻辑备份-'+new Date().toISOString().slice(0,10)+'-offset'+value.offset+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
  $('export').addEventListener('click',()=>run(async valid=>{
    const kinds=[...root.querySelectorAll('[data-mm-kind]:checked')].map(n=>n.dataset.mmKind),limit=+$('limit').value,offset=+$('offset').value;
    const value=await call('POST','export',{scope,kinds,limit,offset});if(!valid())return;
    $('export-result').replaceChildren();
    for(const[kind,section]of Object.entries(value.sections)){
      const records=section.records||[];$('export-result').append(el('p',labels[kind]+'：本份 '+records.length+' 项'+(section.has_more?'；还有下一份，起始位置 '+section.next_offset:'；本范围已到末尾'),'hint'));
    }
    jsonDetail($('export-result'),{sha256:value.sha256,logical_only:true,includes_execution_state:false},'备份校验与范围');download(value);notice('已交给浏览器保存；是否落盘以浏览器下载结果为准。');
  }));
  $('file').addEventListener('change',async()=>{
    restorePlan=null;bundle=null;$('restore-check').checked=false;$('restore-result').replaceChildren();const file=$('file').files[0],owner=key(scope),version=serial;
    if(!file){$('file-info').textContent='';controls();return;}
    if(file.size>768*1024){$('file-info').textContent='';notice('备份文件超过768 KiB；请使用有界导出文件。',true);controls();return;}
    try{const value=JSON.parse(await file.text());if(version!==serial||owner!==key(current()))return;bundle=value;$('file-info').textContent=file.name+' · '+file.size+' 字节 · 只在点击预览后提交到当前服务';notice('文件已读取到当前页面，尚未恢复任何内容。');}catch(_){notice('文件不是有效JSON备份。',true);}controls();
  });
  $('restore-kind').addEventListener('change',()=>{restorePlan=null;$('restore-check').checked=false;controls();});
  $('restore-preview').addEventListener('click',()=>run(async valid=>{
    if(!bundle)throw Error('先选择逻辑备份文件。');const kind=$('restore-kind').value,value=await call('POST','restore/preview',{scope,bundle,kind});if(!valid())return;
    restorePlan=value;$('restore-check').checked=false;$('restore-result').replaceChildren(el('p',value.can_restore?'预览允许追加；请逐项查看后明确确认。':'存在冲突、归档或不支持记录；未写入，请在专用资料页核对。',value.can_restore?'hint':'mm-error'));jsonDetail($('restore-result'),value.manager_preview,'查看每项内容、重复与冲突');notice('恢复预览完成，尚未写入。');
  }));
  function requestId(){const compat=global.TLSBrowserCompat;if(compat&&typeof compat.uuid==='function')return 'maintenance-ui:'+compat.uuid();if(global.crypto&&crypto.randomUUID)return 'maintenance-ui:'+crypto.randomUUID();throw Error('当前浏览器无法创建稳定请求ID，请刷新。');}
  function confirmOperation(operation,body,resultTarget){return run(async valid=>{
    const id=requestId();remember({request_id:id,operation,scope});
    try{const value=await call('POST',operation,{scope,...body,request_id:id,confirmed:true});if(!valid())return;
      remember(null);resultTarget.replaceChildren(el('p','操作已完成；保留原记录与执行账本。','hint'));jsonDetail(resultTarget,value,'查看操作回执');restorePlan=repairPlan=null;$('restore-check').checked=$('repair-check').checked=false;
      if(operation==='bulk/confirm'){bulkPlan=null;$('bulk-check').checked=false;selectedRecords.clear();let refreshFailed=false;try{await loadRecords(valid);}catch(_){refreshFailed=true;}if(!valid())return;resultTarget.replaceChildren(el('p','整批完成：修改 '+value.changed+' 项。原来源、历史及执行账本保留。','hint'));jsonDetail(resultTarget,value,'查看同事务批量回执');if(refreshFailed){notice('整批操作已完成，列表暂未刷新；已保留确认回执，可手动重新读取列表。',true);return;}}
      notice('维护操作完成，请按正常业务读取结果继续使用。');
    }catch(error){if(valid()){notice('确认结果未完整取得。保留原请求ID，只查询回执，不自动重发。',true);}throw error;}
  });}
  $('restore-confirm').addEventListener('click',()=>{if(restorePlan&&$('restore-check').checked)confirmOperation('restore/confirm',{bundle,kind:restorePlan.kind,preview_sha256:restorePlan.preview_sha256},$('restore-result'));});
  $('bulk-confirm').addEventListener('click',()=>{if(bulkPlan&&$('bulk-check').checked)confirmOperation('bulk/confirm',{operation:bulkPlan.operation,items:bulkPlan.items,preview_sha256:bulkPlan.preview_sha256},$('bulk-result'));});
  $('repair-preview').addEventListener('click',()=>run(async valid=>{
    const value=await call('POST','repair/preview',{scope,limit:+$('repair-limit').value});if(!valid())return;repairPlan=value;$('repair-check').checked=false;$('repair-result').replaceChildren(el('p','本次扫描 '+value.scanned+' 项'+(value.truncated?'（有后续，非全量）':'')+'；可修复 '+value.repairable+' 项派生索引差异。','hint'));jsonDetail($('repair-result'),value,'查看确证差异');notice('派生索引预览完成，尚未修改。');
  }));
  $('repair-confirm').addEventListener('click',()=>{if(repairPlan&&$('repair-check').checked)confirmOperation('repair/confirm',{limit:repairPlan.limit,preview_sha256:repairPlan.preview_sha256},$('repair-result'));});
  for(const name of ['restore-check','repair-check'])$(name).addEventListener('change',controls);
  $('receipt').addEventListener('click',()=>run(async valid=>{const value=await call('GET','receipt',{...scope,request_id:pending.request_id});if(!valid())return;$('receipt-result').textContent=JSON.stringify(value,null,2);if(value.receipt&&value.receipt.state==='completed'){restorePlan=repairPlan=bulkPlan=null;for(const name of ['restore-check','repair-check','bulk-check'])$(name).checked=false;remember(null);notice('原请求回执已确认完成；没有重发。旧预览已失效，请重新读取资料后再操作。');}else notice(value.found?'原请求仍未完整确认；请保留回执并核对资料，不重发。':'服务端未找到该请求回执；先核对是否已写入，不自动重发。',true);}));
  async function activate(){const next=current();if(key(next)!==key(scope)){scope=next;serial++;busy=false;bundle=restorePlan=repairPlan=bulkPlan=null;recordPage=null;recordOffset=0;selectedRecords.clear();pending=null;$('file').value='';$('file-info').textContent='';for(const name of ['capacity','export-result','restore-result','repair-result','records','bulk-result'])$(name).replaceChildren();for(const name of ['restore-check','repair-check','bulk-check','select-all'])$(name).checked=false;$('scope').textContent='';$('request').textContent='';$('receipt-result').textContent='';$('records-range').textContent='';$('selected-count').textContent='尚未选择';try{pending=JSON.parse(sessionStorage.getItem(pendingKey())||'null');}catch(_){}drawPending();}if(!scope){notice('请先选择完整会话资料范围。');controls();return;}await run(async valid=>{const value=await call('GET','status',scope);if(valid()){drawCap(value);await loadRecords(valid);}});}
  $('refresh').addEventListener('click',activate);
  global.TLSMaterialMaintenancePanel={activate,scopeChanged:activate};controls();
})(window);
