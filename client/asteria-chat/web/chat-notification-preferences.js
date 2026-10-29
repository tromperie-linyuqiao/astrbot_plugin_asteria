'use strict';
/* Native preferences are authoritative; merely viewing settings never enables a service. */
window.ChatNotificationPreferences=(()=>{
  const get=()=>document.getElementById('notification-preferences');
  const node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  function call(method,value){const bridge=window.AsteriaChat;if(typeof bridge?.[method]!=='function')return null;const result=value===undefined?bridge[method]():bridge[method](JSON.stringify(value));return typeof result==='string'?JSON.parse(result):result;}
  function render(){
    const root=get();if(!root)return;root.replaceChildren();
    root.append(node('h3','通知偏好'));
    let saved;
    try{saved=call('getNotificationPreferences');if(saved?.ok!==true)throw Error('当前版本无法读取通知偏好。');}
    catch(error){root.append(node('p',error.message||'当前版本无法读取通知偏好。'));return;}
    const fields={};
    const add=(key,label,type='checkbox')=>{
      const row=node('label'),input=node('input');input.type=type;input.id='notification-pref-'+key;
      if(type==='checkbox')input.checked=saved[key]===true;else input.value=saved[key];
      row.append(input,node('span',label));root.append(row);fields[key]=input;return input;
    };
    for(const [key,label]of [['enabled','接收消息通知'],['reply','聊天回复'],['proactive','主动消息'],['reminder','日程提醒'],['preview','通知中显示消息预览'],['quiet_enabled','启用免打扰时段']])add(key,label);
    add('quiet_start','免打扰开始','time');add('quiet_end','免打扰结束','time');
    const targetRow=node('label'),target=node('select');target.id='notification-pref-click_target';
    for(const [value,label]of [['message','打开并定位这条消息'],['conversation','打开对应会话']]){const option=node('option',label);option.value=value;target.append(option);}
    target.value=saved.click_target;targetRow.append(node('span','点击通知后'),target);root.append(targetRow);fields.click_target=target;
    root.append(node('p','免打扰按手机本地时间生效，跨午夜可用；开始与结束相同表示全天。被关闭或免打扰拦下的通知不会在之后补弹。'));
    root.append(node('p','保存偏好不会申请系统权限或启动后台检查。关闭消息通知会停止现有回复检查；再次开启后，需要手动开启检查。'));
    const status=node('p');status.setAttribute('role','status');const save=node('button','保存通知偏好');save.type='button';root.append(save,status);
    const sync=()=>{for(const [key,field]of Object.entries(fields)){if(key==='enabled')continue;field.disabled=!fields.enabled.checked||(['quiet_start','quiet_end'].includes(key)&&!fields.quiet_enabled.checked);}};
    fields.enabled.addEventListener('change',sync);fields.quiet_enabled.addEventListener('change',sync);sync();
    save.addEventListener('click',()=>{
      const value=Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,input.type==='checkbox'?input.checked:input.value]));
      if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.quiet_start)||!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.quiet_end)){status.textContent='请填写有效的开始和结束时间。';return;}
      try{const result=call('setNotificationPreferences',value);if(result?.ok!==true)throw Error('通知偏好未保存，请稍后再试。');status.textContent='通知偏好已保存。';window.ChatNotificationStatus?.refresh();}
      catch(error){status.textContent=error.message||'通知偏好未保存，请稍后再试。';}
    });
  }
  document.addEventListener('DOMContentLoaded',()=>{render();const dialog=document.getElementById('settings-dialog');if(dialog)new MutationObserver(()=>{if(dialog.open)render();}).observe(dialog,{attributes:true,attributeFilter:['open']});},{once:true});
  return{refresh:render};
})();
