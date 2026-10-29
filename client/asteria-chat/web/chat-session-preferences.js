'use strict';

/* Session scope only: the server saves these values and injects finite hints. */
window.ChatSessionPreferences=(()=>{
  let dialog,form,status,save,reset,expressionSave,expressionReset,owner='',session='',epoch=0,busy=false,saved=null,expressions=null;
  const fields={};
  const scope=()=>JSON.stringify([state.server,state.username,state.activeId]);
  const node=(tag,text)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;};
  const button=(text,fn)=>{const item=node('button',text);item.type='button';item.className='text-button';item.addEventListener('click',fn);return item;};
  const ticket=()=>({owner,session,epoch});
  const current=t=>dialog?.open&&state.authenticated&&t.owner===owner&&owner===scope()&&t.epoch===epoch;
  function say(value){status.textContent=value;}
  function controls(){for(const item of [save,reset])item.disabled=busy||!saved;for(const item of [expressionSave,expressionReset])item.disabled=busy||!expressions;}
  function select(key,label,options){const row=node('label'),input=node('select');input.id='session-preference-'+key;
    for(const [value,text]of options){const option=node('option',text);option.value=value;input.append(option);}row.append(node('span',label),input);form.append(row);fields[key]=input;return input;}
  function close(){epoch++;owner='';saved=null;expressions=null;busy=false;if(dialog?.open)dialog.close();}
  function setup(){
    if(dialog)return;dialog=node('dialog');dialog.id='session-preferences-dialog';dialog.className='settings-dialog session-preferences-dialog';dialog.setAttribute('aria-labelledby','session-preferences-title');
    const header=node('div');header.className='dialog-heading';const title=node('h2','本会话偏好');title.id='session-preferences-title';header.append(title,button('关闭',close));form=node('div');form.className='settings-form';
    form.append(header,node('p','只作用于当前会话的后续回复。恢复继承后，沿用角色和系统的原有表达。'));dialog.append(form);
    select('reply_style','回复语气',[['inherit','继承原有语气'],['natural','自然'],['warm','温和体贴'],['direct','直接清楚']]);
    select('reply_length','回复长度',[['inherit','继承原有长度'],['short','简短'],['balanced','适中'],['detailed','详细']]);
    select('rp_intensity','虚构互动强度',[['inherit','继承原有强度'],['light','轻量'],['balanced','适中'],['immersive','沉浸']]);
    select('reply_format','回复格式',[['auto','自动（剧情沿用动作与话语）'],['text','普通文字'],['structured','动作与话语']]);
    form.append(node('p','互动强度仅在会话的角色扮演模式下使用。可在会话详情中切换模式。'));
    save=button('保存会话偏好',()=>write(false));save.className='primary-button';reset=button('恢复回复偏好继承',()=>write(true));form.append(save,reset,node('h3','本会话表情策略'));
    select('frequency','表情频率',[['off','关闭'],['low','较少'],['balanced','适中'],['expressive','丰富']]);
    const per=node('label'),check=node('input');check.type='checkbox';check.id='session-preference-per_unit';per.append(check,node('span','按语义片段选择表情'));form.append(per);fields.per_unit=check;
    const cooldown=node('label'),seconds=node('input');seconds.type='number';seconds.min='0';seconds.max='86400';seconds.step='1';seconds.id='session-preference-cooldown_seconds';cooldown.append(node('span','同一表情冷却（秒）'),seconds);form.append(cooldown);fields.cooldown_seconds=seconds;
    select('fragment_display','片段展示',[['semantic','语义片段'],['compact','紧凑']]);
    for(const [mode,label]of [['chat','日常模式配图'],['roleplay','剧情模式配图'],['technical','讨论模式配图']])select('policy_'+mode,label,[['semantic','按语义'],['paragraph','按段落'],['single','单张'],['text_only','仅文字']]);
    expressionSave=button('保存本会话表情策略',()=>writeExpressions(false));expressionReset=button('恢复表情策略继承',()=>writeExpressions(true));
    form.append(expressionSave,expressionReset);status=node('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');form.append(status,button('重新读取',read));
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});document.body.append(dialog);
  }
  function render(){
    if(saved)for(const key of ['reply_style','reply_length','rp_intensity','reply_format'])fields[key].value=saved[key]||'inherit';
    if(expressions){const value=expressions.effective;for(const key of ['frequency','fragment_display','cooldown_seconds'])fields[key].value=value[key];fields.per_unit.checked=value.per_unit;
      for(const mode of ['chat','roleplay','technical'])fields['policy_'+mode].value=value.mode_policies[mode];}
    controls();
  }
  async function read(){
    const t=ticket();if(!current(t)||busy)return;busy=true;controls();say('正在读取当前会话的实际偏好…');
    try{
      const results=await Promise.allSettled([apiClient.json('GET','/chat/session-state?session_id='+encodeURIComponent(t.session)),apiClient.json('GET','/chat/expression-settings?session_id='+encodeURIComponent(t.session))]);
      if(!current(t))return;saved=results[0].status==='fulfilled'?results[0].value:null;expressions=results[1].status==='fulfilled'?results[1].value:null;render();
      const sources=expressions?Object.entries(expressions.sources).map(([key,value])=>({frequency:'频率',per_unit:'语义配图',cooldown_seconds:'冷却',fragment_display:'展示',mode_policies:'模式策略'}[key]||key)+'：'+({session:'本会话',role:'角色默认',default:'系统默认'}[value]||value)).join(' · '):'表情策略暂不可用';
      say((saved?'已读取会话偏好。':'会话偏好暂不可用。')+' '+sources);
    }catch(error){if(current(t))say(errorText(error));}
    finally{if(current(t)){busy=false;controls();}}
  }
  async function write(inherit){
    const t=ticket();if(!current(t)||busy||!saved)return;busy=true;controls();say('正在保存本会话的回复偏好…');
    try{const value=await apiClient.json('POST','/chat/session-state',{session_id:t.session,expected_revision:saved.revision,
      ...(inherit?{reset_preferences:true,reply_format:'auto'}:Object.fromEntries(['reply_style','reply_length','rp_intensity','reply_format'].map(key=>[key,fields[key].value])))});
      if(!current(t))return;saved=value;const row=state.sessions.find(item=>item.session_id===t.session);if(row)row.tls_state=value;render();say(inherit?'已恢复继承；后续回复沿用原有偏好。':'已保存到当前会话，后续回复会读取这些表达偏好。');
    }catch(error){if(current(t)){saved=null;say(errorText(error)+' 请重新读取核对，表单保留。');}}
    finally{if(current(t)){busy=false;controls();}}
  }
  async function writeExpressions(inherit){
    const t=ticket();if(!current(t)||busy||!expressions)return;const seconds=Number(fields.cooldown_seconds.value);
    if(!inherit&&(!Number.isInteger(seconds)||seconds<0||seconds>86400)){say('冷却时间须为0到86400的整数秒。');return;}
    busy=true;controls();say('正在保存本会话表情策略…');
    try{const value=await apiClient.json('POST','/chat/expression-settings',{session_id:t.session,level:'session',expected_revision:expressions.session_revision,
      ...(inherit?{reset:true}:{changes:{frequency:fields.frequency.value,per_unit:fields.per_unit.checked,cooldown_seconds:seconds,fragment_display:fields.fragment_display.value,
        mode_policies:Object.fromEntries(['chat','roleplay','technical'].map(mode=>[mode,fields['policy_'+mode].value]))}})});
      if(!current(t))return;expressions=value;render();say(inherit?'已恢复本会话表情策略继承。':'已保存本会话表情策略，后续回复会使用。');
    }catch(error){if(current(t)){expressions=null;say(errorText(error)+' 请重新读取核对，表单保留。');}}
    finally{if(current(t)){busy=false;controls();}}
  }
  function open(){if(!state.authenticated||!state.activeId){showNotice('请先打开自己的聊天会话。');return;}setup();close();owner=scope();session=state.activeId;epoch++;dialog.showModal();controls();void read();}
  return{open,openSessionPreferences:open,closeActive:()=>{if(!dialog?.open)return false;close();return true;},scopeChanged:()=>{if(owner&&(!state.authenticated||owner!==scope()))close();}};
})();
window.openSessionPreferences=()=>window.ChatSessionPreferences.open();
