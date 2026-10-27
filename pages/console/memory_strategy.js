/* Existing console auth and SDK config; no independent background polling. */
(function(global){
  'use strict';
  const root=document.getElementById('memory-strategy-mount');if(!root)return;
  const fields=[['living_memory_strategy_enabled','按信息价值分流记忆','checkbox'],
    ['living_memory_working_ttl_minutes','临时工作记忆有效期（分钟）','number'],
    ['living_memory_summary_filter_low_value','摘要过滤寒暄与低信息内容','checkbox'],
    ['living_memory_summary_dedupe','同一摘要窗口筛除完全重复发言','checkbox']];
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const panel=el('section');panel.className='panel memory-strategy-panel';panel.append(el('h2','记忆分流与摘要'));
  const help=el('p','原文仍留在既有时间线；临时状态有有效期，明确事实和偏好继续走证据与冲突审核，RP不当作现实资料。');help.className='hint';panel.append(help);
  const controls={};for(const [key,label,type]of fields){const row=el('label'),input=el('input');row.className='memory-strategy-field';input.type=type;
    if(type==='number'){input.min='5';input.max='1440';input.step='1';}controls[key]=input;row.append(el('span',label),input);panel.append(row);}
  const actions=el('div');actions.className='actions';const refresh=el('button','读取当前值'),save=el('button','保存设置'),defaults=el('button','填入默认值'),finish=el('button','已核对，结束本次等待');
  for(const b of [refresh,save,defaults,finish]){b.type='button';actions.append(b);}panel.append(actions);
  const status=el('p','尚未读取。');status.className='hint';status.setAttribute('role','status');panel.append(status);root.append(panel);
  let snapshot=null,busy=false,pending=null,pendingFailure='',readChecked=false;
  const reason=error=>error?.publicMessage||error?.message||'操作结果未确认。';
  const values=()=>Object.fromEntries(fields.map(([key,,type])=>[key,type==='checkbox'?controls[key].checked:Number(controls[key].value)]));
  const paint=value=>{for(const[key,,type]of fields){if(type==='checkbox')controls[key].checked=value[key];else controls[key].value=String(value[key]);}};
  const lock=()=>{for(const n of Object.values(controls))n.disabled=busy||!!pending;refresh.disabled=busy;save.disabled=busy||!!pending||!snapshot?.writable;defaults.disabled=busy||!!pending||!snapshot;finish.hidden=!pending;finish.disabled=busy||!readChecked;};
  const same=(a,b)=>fields.every(([key])=>a?.[key]===b?.[key]);
  const unwrap=value=>{const row=value?.ok===true?value:value?.data;if(row?.ok!==true||!row.values||typeof row.revision!=='string')throw Error('记忆策略响应不完整。');return row;};
  async function load(){if(busy)return;busy=true;lock();status.textContent='正在读取…';try{const row=unwrap(await api('GET','page/memory-strategy/config'));
    snapshot=row;if(pending)readChecked=true;if(pending&&same(row.values,pending)){pending=null;pendingFailure='';status.textContent='已回读确认保存。';}else status.textContent=pending?(pendingFailure?pendingFailure+' ':'')+'已回读，上次结果仍待核对，不会自动重发。':row.boundary;
    if(!pending)paint(row.values);
  }catch(e){status.textContent=reason(e)+(pendingFailure?' 上次保存原因：'+pendingFailure:'');}finally{busy=false;lock();}}
  save.onclick=async()=>{if(busy||pending||!snapshot?.writable)return;const next=values(),changes=Object.fromEntries(fields.filter(([key])=>next[key]!==snapshot.values[key]).map(([key])=>[key,next[key]]));
    if(!Object.keys(changes).length){status.textContent='没有需要保存的修改。';return;}
    if(!Number.isInteger(next.living_memory_working_ttl_minutes)||next.living_memory_working_ttl_minutes<5||next.living_memory_working_ttl_minutes>1440){status.textContent='有效期请输入5–1440的整数分钟。';return;}
    pending=next;pendingFailure='';readChecked=false;busy=true;lock();status.textContent='正在保存…';try{await api('POST','page/memory-strategy/config/save',{expected_revision:snapshot.revision,changes});}
    catch(e){pendingFailure=reason(e);status.textContent=pendingFailure+' 请先回读核对，不会自动重发。';}
    finally{busy=false;lock();}await load();};
  refresh.onclick=load;defaults.onclick=()=>{if(snapshot&&!busy&&!pending){paint(snapshot.defaults);status.textContent='默认值已填入，尚未保存。';}};
  finish.onclick=()=>{if(!busy&&pending&&readChecked){pending=null;pendingFailure='';paint(snapshot.values);status.textContent='已结束等待，原请求仍可能稍后生效；重新修改前请核对当前值。没有重发。';lock();}};
  global.TLSMemoryStrategyPanel={activate:load};lock();
})(window);
