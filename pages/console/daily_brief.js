(function(global){'use strict';
const FIELDS=['platform','bot_id','user_id','character_id','session_id'];
function full(s){return s&&FIELDS.every(k=>typeof s[k]==='string'&&s[k].trim());}
const same=(a,b)=>!!a&&!!b&&FIELDS.every(k=>a[k]===b[k]);
function mount(container,{api,getScope=()=>null}){
 let scope=null,version=0,last=null,busy=false,disposed=false;
 const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 container.replaceChildren();container.classList.add('daily-brief');
 const head=make('section',undefined,'panel brief-hero'),title=make('h2','角色的今日简报'),lead=make('p','把今天的安排和临近的重要日期放在一起。','hint');
 const actions=make('div',undefined,'actions'),zone=make('select'),label=make('label','简报时区 '),refresh=make('button','刷新简报'),download=make('button','导出本次简报');
 for(const z of ['UTC+08:00','UTC','UTC+09:00','UTC-05:00']){const o=make('option',z);o.value=z;zone.append(o);}label.append(zone);refresh.type=download.type='button';download.disabled=true;actions.append(label,refresh,download);head.append(title,lead,actions);
 const status=make('p','请选择上方完整会话。','hint');status.setAttribute('role','status');const body=make('div',undefined,'brief-grid');container.append(head,status,body);
 function section(title,note,rows,format){const card=make('section',undefined,'panel');card.append(make('h3',title),make('p',note,'hint'));if(!rows.length)card.append(make('p','本次读取没有符合条件的记录。','hint'));for(const r of rows){const item=make('article',undefined,'brief-item');for(const line of format(r))item.append(make('p',line));card.append(item);}body.append(card);}
 function render(value){body.replaceChildren();lead.textContent=value.day+' · '+value.timezone+' · 当前所选会话';
  section('临近的重要日期',value.dates.boundary+' · 展示 '+value.dates.upcoming.length+' / '+value.dates.total_relevant+' 条',value.dates.upcoming,r=>[r.title,r.date+' · '+(r.days_until===0?'今天':r.days_until+' 天后')+' · '+r.timezone,'来源：'+({'user_explicit':'人工登记','legacy_import':'历史导入'}[r.source]||r.source)]);
  const a=value.agenda;if(a.state==='available'||a.state==='partial'){
   section('今天的安排','计划不表示已发生或已经送达。',a.today,r=>[r.content,'计划时间（带时区）：'+r.due_at]);
   section('接下来的安排',a.state==='partial'?'仅扫描前100条日程，结果可能不完整。':'读取现有原生日程。',a.next,r=>[r.content,r.due_at]);
  }else{const c=make('section',undefined,'panel');c.append(make('h3','日程暂未读取'),make('p',a.state==='session_required'?'请在目标私聊发一条正常消息后，再刷新简报。':'日程服务暂不可用；重要日期仍可单独查看。','hint'));body.append(c);}
  const n=make('section',undefined,'panel brief-note');n.append(make('h3','这份简报从哪里来'),make('p','重要日期 '+value.dates.definitions+' 条；日程最多读取100条。数据按各服务当前状态读取，不是跨服务原子快照。','hint'),make('p','本页不调用模型、不主动发送消息，也不把计划、推断或虚构剧情写成真实经历。','hint'));body.append(n);
 }
 async function load(){if(disposed||busy)return;const chosen=scope||getScope();if(!full(chosen)){body.replaceChildren();last=null;download.disabled=true;status.textContent='请选择上方完整会话。';return;}const captured=++version,s={};for(const k of FIELDS)s[k]=chosen[k];const tz=zone.value;busy=true;refresh.disabled=true;download.disabled=true;status.textContent='正在读取实际日程和日期…';let timer;
  try{const value=await Promise.race([api('GET','page/daily-brief/read',{...s,timezone:tz}),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('timeout')),15000);})]);if(captured!==version||disposed||!same(s,scope||getScope()))return;if(!value||value.ok!==true||FIELDS.some(k=>value.scope?.[k]!==s[k])||value.timezone!==tz||!Array.isArray(value.dates?.upcoming)||!Array.isArray(value.agenda?.today)||!Array.isArray(value.agenda?.next))throw Error('invalid response');last=value;render(value);status.textContent='已读取 · '+new Date(value.sampled_at*1000).toLocaleTimeString()+(value.agenda.state==='available'?'':' · 日程部分资料尚未完整');download.disabled=false;
  }catch(e){if(captured!==version||disposed)return;last=null;body.replaceChildren();status.textContent=({401:'后台登录已过期，请重新登录后刷新简报。',403:'该范围的资料读取权限已变化，请核对所选会话。',503:'简报服务暂不可用，请稍后刷新。'})[Number(e?.status||e?.statusCode)]||'简报未完整读取，请刷新重试；未使用旧会话或默认资料。';}
  finally{clearTimeout(timer);if(captured===version&&!disposed){busy=false;refresh.disabled=false;}}
 }
 function setScope(s){const next=full(s)?Object.fromEntries(FIELDS.map(k=>[k,s[k]])):null;if(JSON.stringify(next)===JSON.stringify(scope))return;scope=next;version++;busy=false;last=null;body.replaceChildren();download.disabled=true;refresh.disabled=false;status.textContent=scope?'会话已切换，点击刷新读取当前资料。':'请选择上方完整会话。';}
 refresh.addEventListener('click',load);zone.addEventListener('change',()=>{version++;busy=false;last=null;download.disabled=true;refresh.disabled=false;body.replaceChildren();load();});
 download.addEventListener('click',()=>{if(!last||disposed||!same(last.scope,scope||getScope())||last.timezone!==zone.value)return;const blob=new Blob([JSON.stringify(last,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=make('a');a.href=url;a.download='texas-daily-brief-'+last.day+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);});
 return {setScope,activate:load,dispose(){disposed=true;version++;last=null;download.disabled=refresh.disabled=true;body.replaceChildren();}};
}
global.TLSDailyBrief=Object.freeze({mount});
})(globalThis);
