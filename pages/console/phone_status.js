(function(global){'use strict';
const FIELDS=['platform','bot_id','user_id','character_id','session_id'];
const TITLES={battery:'电量与充电',screen:'屏幕',network:'网络',audio:'音频',device:'设备',activity:'活动',app:'前台应用',music:'音乐',location:'位置'};
const STATES={fresh:'新鲜记录',stale:'已过期',unknown:'尚未收到',disabled:'未启用',unauthorized:'未授权',unavailable:'不可用'};
const NAMES={level:'电量（%）',charging:'正在充电',charging_type:'充电类型',temperature_c:'温度（℃）',on:'屏幕亮起',locked:'锁定',type:'网络类型',roaming:'漫游',metered:'计费网络',headphones:'耳机已连接',ringer_mode:'铃声模式',media_active:'媒体活动',name:'设备名称',platform:'平台',os_version:'系统版本',power_save:'省电模式',steps_today:'今日步数',device_idle:'设备空闲',last_unlock_epoch:'上次解锁',foreground_package:'应用包名',foreground_label:'应用名称',foreground_since_epoch:'进入应用时间',foreground_minutes:'前台分钟',state:'播放状态',playing:'正在播放',title:'曲目',artist:'歌手',album:'专辑',source:'事实来源',package:'播放器',track_id:'曲目标识',duration_ms:'时长',progress_ms:'进度',playback_speed:'播放速度'};
function unpack(value){for(let i=0;i<4;i++){if(!value||typeof value!=='object')throw Error('状态响应不可识别');if(value.ok===false||value.status==='error')throw Error(value.message||value.error||'状态读取失败');if(value.unified_status)return value.unified_status;if(value.schema===1&&value.sources)return value;if(value.data&&typeof value.data==='object'){value=value.data;continue;}break;}throw Error('后台未提供统一感知状态');}
function timestamp(value){if(typeof value!=='number'||!Number.isFinite(value)||value<=0)return '未提供';const date=new Date(value*1000);return Number.isFinite(date.getTime())?date.toLocaleString():'未提供';}
function mount(container,{api,getScope=()=>null}){
 let scope=null,epoch=0,busy=false,disposed=false,selected='';
 const make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const full=s=>s&&FIELDS.every(key=>typeof s[key]==='string'&&s[key].trim());
 const same=(a,b)=>!!a&&!!b&&FIELDS.every(key=>a[key]===b[key]);
 container.replaceChildren();container.classList.add('phone-unified-status');
 const panel=make('section',undefined,'panel'),head=make('div',undefined,'panel-head'),actions=make('div',undefined,'actions');
 const cached=make('button','刷新已有状态'),read=make('button','读取现有 PPB 状态一次'),select=make('select'),label=make('label','已分配设备 ');
 cached.type=read.type='button';label.append(select);actions.append(label,cached,read);head.append(make('h2','手机来源的真实状态'),actions);
 const hint=make('p','只读同一原生客户端与有效缓存，不新增采集；点击按钮不代表手机新上报。配置、最近访问、上报接收与每项新鲜度分别展示，没有数据不代表手机离线。','hint');
 const notice=make('p','先选择上方完整会话。','hint'),connection=make('p','','hint'),receipt=make('p','','hint'),body=make('div',undefined,'phone-status-grid');notice.setAttribute('role','status');
 panel.append(head,hint,notice,connection,receipt,body);container.append(panel);
 function controls(){cached.disabled=read.disabled=select.disabled=busy||!full(scope)||disposed;}
 function draw(value){
  if(value.schema!==1||!value.sources||!value.transport||!value.access)throw Error('后台感知状态不完整');
  const previous=selected;select.replaceChildren();const initial=make('option','请选择已分配的设备');initial.value='';select.append(initial);
  for(const device of value.devices||[]){if(!device||typeof device.id!=='string')continue;const option=make('option',device.label||device.id);option.value=device.id;select.append(option);}
  selected=(value.devices||[]).some(item=>item.id===previous)?previous:value.device_id||'';select.value=selected;
  const transport=value.transport,labels={unconfigured:'尚未配置',unknown:'尚无访问结果',reachable:'最近访问成功',unauthorized:'最近访问被拒绝',unavailable:'最近访问失败'};
  connection.textContent='连接配置：'+(transport.configured===true?'已配置':transport.configured===false?'未配置':'待核对')+'；访问：'+(labels[transport.state]||'待核对')+'；上次成功访问：'+timestamp(transport.last_success_at)+(transport.error?.message?'；原因：'+transport.error.message:'');
  receipt.textContent=value.report?('原上报记录：'+(value.report.accepted===true?'感知桥已确认接收':value.report.state==='rejected'?'感知桥拒绝':'结果尚未确认')+'；完成时间：'+timestamp(value.report.completed_at)):'暂无与当前设备及当前配置相符的上报接收证明。';
  body.replaceChildren();const records=!value.device_id&&Array.isArray(value.summaries)&&value.summaries.length?value.summaries:[value];for(const record of records){const group=make('section',undefined,'phone-status-device');
  if(record.device_id)group.append(make('h3','设备：'+record.device_id));
  if(records.length>1)group.append(make('p','访问：'+(labels[record.transport?.state]||'待核对')+'；上次成功：'+timestamp(record.transport?.last_success_at),'hint'));
  for(const [key,title]of Object.entries(TITLES)){
   const row=record.sources[key]||{status:'unknown'},card=make('article',undefined,'module phone-source'),heading=make('div',undefined,'panel-head');
   heading.append(make('h3',title),make('span',STATES[row.status]||'待核对','tag '+(row.status==='fresh'?'on':'off')));card.append(heading);
   if(row.value&&typeof row.value==='object'&&!row.unauthorized){if(row.status!=='fresh')card.append(make('p','以下仅是上次记录，不代表当前仍如此。','archive-holds'));for(const [field,item]of Object.entries(row.value)){if(field==='schema_version'||field==='observed_at'||item===null)continue;const text=typeof item==='boolean'?(item?'是':'否'):field.endsWith('_epoch')?timestamp(item):field.endsWith('_ms')&&typeof item==='number'?(item/1000).toFixed(1)+' 秒':String(item);card.append(make('p',(NAMES[field]||field)+'：'+text,'hint'));}}
   else card.append(make('p','没有可显示的已授权记录。','hint'));
   card.append(make('p','TLS 收到快照：'+timestamp(row.last_received_at)+'\n来源观察时间：'+timestamp(row.observed_at)+'\n原有效期至：'+timestamp(row.expires_at),'scope-details'));
   if(row.error?.message)card.append(make('p','原因：'+row.error.message+(Number.isInteger(row.error.http_status)?'（HTTP '+row.error.http_status+'）':''),'hint'));
   group.append(card);
  }body.append(group);}
  notice.textContent=(value.access.authorized?(value.device_id?'已读取当前授权设备。':'请选择已分配的具体设备。'):'当前读取未获授权或来源不可用。')+' 状态生成：'+timestamp(value.generated_at);
 }
 function setScope(value){const next=full(value)?Object.fromEntries(FIELDS.map(key=>[key,value[key]])):null;if(same(next,scope))return;scope=next;epoch++;busy=false;selected='';body.replaceChildren();connection.textContent=receipt.textContent='';notice.textContent=scope?'等待读取此会话的已有状态。':'先选择上方完整会话。';controls();}
 async function load(refresh=false){setScope(getScope());if(!full(scope)||busy||disposed)return;const current=++epoch,query={...scope,...(selected?{device_id:selected}:{})};busy=true;controls();notice.textContent=refresh?'正在通过原客户端查询一次…':'正在读取原客户端已有状态…';try{const value=unpack(await api('GET','page/phone/status'+(refresh?'/read':''),query));if(disposed||current!==epoch||!same(scope,query))return;draw(value);}catch(error){if(!disposed&&current===epoch){notice.textContent=String(error?.publicMessage||error?.message||'状态暂不可用');body.replaceChildren();}}finally{if(current===epoch){busy=false;controls();}}}
 cached.addEventListener('click',()=>load(false));read.addEventListener('click',()=>load(true));select.addEventListener('change',()=>{selected=select.value;load(false);});controls();
 return {setScope,activate:()=>load(false),refresh:()=>load(false),readOnce:()=>load(true),dispose(){disposed=true;epoch++;body.replaceChildren();controls();}};
}
global.TLSPhoneStatus=Object.freeze({mount});
})(globalThis);
