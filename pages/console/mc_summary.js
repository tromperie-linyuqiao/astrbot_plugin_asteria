/* Asteria memory summary state; the former algorithm handoff controls are retired. */
(function(global){
 'use strict';const root=document.getElementById('mc-summary-mount');if(!root)return;
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let current=null,fresh=false,busy=false;
 root.innerHTML='<section class="panel mc-summary-panel"><div class="panel-head"><h2>记忆摘要服务</h2><button type="button" data-summary-status>刷新状态</button></div><p>摘要、时间线与记忆资料由 Asteria 自身的记忆服务处理。此页查看运行信息，不再切换或恢复其他插件的算法。</p><div data-summary-stats class="mc-summary-stats"></div><p data-summary-notice class="hint" role="status">等待读取。</p><div class="actions"><button type="button" data-summary-inspect>查看来源与当前调用</button><button type="button" data-summary-full>查看系统服务</button></div><details><summary>参数与运行详情</summary><p>状态表示当前服务与来源检查，不证明某次模型调用或摘要写入已经完成。</p><div data-summary-details></div></details></section>';
 const $=name=>root.querySelector('[data-summary-'+name+']');
 function notice(text,error){$('notice').textContent=text;$('notice').classList.toggle('mc-summary-error',!!error);}
 function draw(){
  $('stats').replaceChildren();$('details').replaceChildren();
  if(current){
   const active=current.algorithm_active===true&&current.active===true;
   for(const [label,value] of [['摘要服务',!fresh?'上次状态，当前未确认':active?'Asteria 服务运行中':'未运行或待核对'],['来源检查',current.source_current===true?'当前来源一致':'待核对'],['异常引用',current.recovery_required?'需要核对保留引用':'没有报告异常引用']]){
    const item=node('div');item.append(node('small',label),node('strong',value));$('stats').append(item);
   }
   if(current.parameters)for(const [key,value] of Object.entries(current.parameters))$('details').append(node('p',key+'：'+value,'hint'));
   if(current.inflight)$('details').append(node('p','已审摘要调用：'+current.inflight.audited_summary_calls+'；未能判定的等待链：'+current.inflight.unknown_task_chains,'hint'));
   if(current.preflight_error)$('details').append(node('p',String(current.preflight_error),'mc-summary-error'));
  }
  $('status').disabled=busy;$('inspect').disabled=busy;
 }
 async function load(inspect){
  if(busy)return;busy=true;draw();notice('正在读取摘要服务状态…');
  try{
   const value=await api('GET','page/server-integration/mc/summary/'+(inspect?'inspect':'status'));
   const result=value&&value.ok===true?value:value&&value.data;
   const summary=result&&(result.summary||result.mc&&result.mc.summary);
   if(!result||result.ok!==true||!summary||typeof summary!=='object')throw Error('摘要状态不完整。');
   current=summary;fresh=true;notice(current.recovery_required?'检测到保留引用，请核对运行详情。':'已读取当前状态。',!!current.recovery_required);
  }catch(error){fresh=false;notice((error.message||'读取失败。')+' 上次记录不作为当前运行证明。',true);}
  finally{busy=false;draw();}
 }
 $('status').addEventListener('click',()=>load(false));$('inspect').addEventListener('click',()=>load(true));
 $('full').addEventListener('click',()=>global.TLSAdminWorkspace?.navigate('native_ownership'));
 global.TLSMCSummaryPanel={activate:()=>load(false)};draw();
})(window);
