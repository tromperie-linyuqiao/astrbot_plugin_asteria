/** Asteria-owned workspace runtime. Source: tools/build_workspace_assets.cjs. */
const OWNERS=['astrbot_plugin_asteria','astrbot_plugin_virtual_body'];
const SERVICES={companion:'page/pc',memory:'page/native-memory'};
export class WorkspaceError extends Error {
  constructor(message,{status=null,submitted=false}={}){super(message);this.name='WorkspaceError';this.status=status;this.submitted=submitted;}
}
export function usableBridge(value){return Boolean(value&&typeof value.apiGet==='function'&&typeof value.apiPost==='function');}
function contextOwner(bridge){try{return bridge.getContext?.()?.pluginName||'';}catch{return '';}}
export function currentBridge(){
  const local=window.AstrBotPluginPage;
  if(usableBridge(local)){const owner=contextOwner(local);if(!owner||OWNERS.includes(owner))return local;}
  try{const parent=window.parent!==window?window.parent.AstrBotPluginPage:null;
    if(usableBridge(parent)&&OWNERS.includes(contextOwner(parent)))return parent;
  }catch{}
  return null;
}
export function unwrapWorkspaceResult(raw){
  let value=raw;
  if(typeof value==='string'){try{value=JSON.parse(value);}catch{throw new WorkspaceError('服务没有返回可读取的结果');}}
  // Peel only SDK envelopes first. A plugin's successful data may itself carry
  // ok:false/status:failed (a diagnostic or partial outcome); that is view data.
  for(let depth=0;depth<3;depth++){
    if(!value||typeof value!=='object'||Array.isArray(value))return value;
    const envelope=Object.keys(value).every(key=>['status','message','data','http_status','status_code'].includes(key));
    if(envelope&&['error','fail','failed'].includes(String(value.status||'').toLowerCase()))throw new WorkspaceError(value.message||'服务暂不可用',{status:value.http_status||value.status_code||null});
    if(envelope&&value.status==='ok'&&Object.hasOwn(value,'data')){value=value.data;continue;}
    break;
  }
  if(!value||typeof value!=='object'||Array.isArray(value))return value;
  if(value.success===false)throw new WorkspaceError(value.error||value.message||'服务拒绝了本次操作');
  if(value.success===true)return Object.hasOwn(value,'data')?value.data:value;
  if(value.ok===false||['error','fail','failed'].includes(String(value.status||'').toLowerCase()))throw new WorkspaceError(value.error||value.message||'服务拒绝了本次操作');
  return value;
}
export class AsteriaPageClient {
  constructor(service,{allowHttp=false}={}){if(!Object.hasOwn(SERVICES,service))throw Error('Unknown Asteria service');this.prefix=SERVICES[service];this.allowHttp=allowHttp;}
  async bridge(){const bridge=currentBridge();if(!bridge)throw new WorkspaceError('请从星栖 Asteria 后台重新打开这个页面。');
    if(typeof bridge.ready==='function')await bridge.ready();const owner=contextOwner(bridge);
    if(owner&&!OWNERS.includes(owner))throw new WorkspaceError('当前页面的服务身份已变化，请重新打开。');return bridge;}
  async request(route,{method='GET',body}={}){
    method=String(method).toUpperCase();if(!['GET','POST'].includes(method))throw new WorkspaceError('本页不支持这种操作方式');
    if(typeof route!=='string'||route.length>4096||route.startsWith('//'))throw new WorkspaceError('页面接口地址不正确');
    const url=new URL(route,'https://asteria-page.invalid/');
    if(url.origin!=='https://asteria-page.invalid'||url.hash)throw new WorkspaceError('页面接口地址不正确');
    const endpoint=this.prefix+'/'+url.pathname.replace(/^\/+/,''),params=Object.fromEntries(url.searchParams);
    if(typeof body==='string'){try{body=JSON.parse(body);}catch{throw new WorkspaceError('输入内容没有正确编码，请保留输入并重新检查。');}}
    const write=method==='POST';let submitted=false,raw;
    try{
      if(usableBridge(window.AstrBotPluginPage)||currentBridge()){
        const bridge=await this.bridge();
        if(write){submitted=true;raw=await bridge.apiPost(endpoint+(url.search||''),body??{});}
        else raw=await bridge.apiGet(endpoint,Object.keys(params).length?params:undefined);
        const owner=contextOwner(bridge);if(owner&&!OWNERS.includes(owner))throw new WorkspaceError('当前页面的服务身份已变化，结果未应用。',{submitted});
      }else if((typeof this.allowHttp==='function'?this.allowHttp():this.allowHttp)&&['http:','https:'].includes(location.protocol)){
        submitted=write;
        const response=await fetch('/api/v1/plugins/extensions/astrbot_plugin_asteria/'+endpoint+url.search,
          {method,cache:'no-store',credentials:'same-origin',headers:write?{'Content-Type':'application/json'}:undefined,
           body:write?JSON.stringify(body??{}):undefined});
        try{raw=await response.json();}catch{throw new WorkspaceError('服务没有返回可读取的结果',{status:response.status,submitted});}
        if(!response.ok)throw new WorkspaceError(raw?.message||raw?.error||('HTTP '+response.status),{status:response.status,submitted});
      }else throw new WorkspaceError('请从星栖 Asteria 后台重新打开这个页面。');
      if(raw===undefined)throw new WorkspaceError('服务返回结果不完整，请保留未保存的输入。',{submitted});
      return unwrapWorkspaceResult(raw);
    }catch(error){if(error instanceof WorkspaceError){if(submitted)error.submitted=true;throw error;}
      throw new WorkspaceError(error?.message||'服务暂时无法连接，请保留输入。',{status:error?.status??null,submitted});}
  }
  get(route){return this.request(route);}
  post(route,body){return this.request(route,{method:'POST',body});}
}
export async function openAsteriaConsole(area){
  const client=new AsteriaPageClient('companion'),bridge=await client.bridge();
  const result=unwrapWorkspaceResult(await bridge.apiGet('page/nav',{to:'console',format:'json',theme:['light','dark','black'].includes(document.documentElement.dataset.adminTheme)?document.documentElement.dataset.adminTheme:'dark'}));
  if(!result||typeof result.url!=='string')throw new WorkspaceError('工作台入口暂未确认，请重新打开。');
  const url=new URL(result.url,location.href),allowed=OWNERS.map(name=>'/api/plugin/page/content/'+name+'/console/');
  if(url.origin!==location.origin||!allowed.includes(url.pathname)||!url.searchParams.get('asset_token')||url.username||url.password)throw new WorkspaceError('工作台入口身份不匹配，请从后台重新进入。');
  url.hash=area;location.assign(url.href);
}
export function installWorkspaceShell(service){
  const root=document.getElementById('asteriaWorkspaceHeader');if(!root||root.dataset.mounted)return;
  root.dataset.mounted='true';root.className='asteria-workspace-header';document.documentElement.dataset.asteriaWorkspace=service;
  const brand=document.createElement('strong');brand.textContent='✧ 星栖 Asteria';
  const title=document.createElement('span');title.className='asteria-workspace-path';title.textContent=service==='companion'?'陪伴与角色':'记忆与资料';
  const label=document.createElement('label');label.textContent='定位本页';
  const jump=document.createElement('select');jump.setAttribute('aria-label','定位本页分区');label.append(jump);
  const back=document.createElement('button');back.type='button';back.textContent='返回工作台';
  const message=document.createElement('p');message.className='asteria-workspace-message';message.setAttribute('role','status');
  root.replaceChildren(brand,title,label,back,message);let headings=[];
  function options(){headings=[...document.querySelectorAll('h2,h3')].filter(node=>!node.closest('dialog')&&node.getClientRects().length&&node.textContent.trim());
    jump.replaceChildren(new Option('选择本页分区',''));headings.forEach((node,index)=>jump.add(new Option(node.textContent.trim().slice(0,70),String(index))));}
  jump.addEventListener('focus',options);jump.addEventListener('pointerdown',options);
  jump.addEventListener('change',()=>{if(jump.value==='')return;const target=headings[Number(jump.value)];if(!target)return;
    target.scrollIntoView({block:'start'});if(!target.hasAttribute('tabindex'))target.tabIndex=-1;target.focus({preventScroll:true});});
  back.addEventListener('click',async()=>{back.disabled=true;message.textContent='';try{await openAsteriaConsole(service==='companion'?'area-companion':'area-memory');}
    catch(error){message.textContent=error.message;}finally{back.disabled=false;}});options();
}
