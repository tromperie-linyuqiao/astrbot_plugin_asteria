'use strict';
/* Voice is a rendering/input adapter. It never creates a second chat request. */
window.ChatVoice = (() => {
  const defaults = {name:'Texas Voice · 独立音色',language:'zh-CN',timbre:'自然、清晰、克制的中文表达；不模仿原作配音演员',pronunciation:'普通话，专有名词保持原文',emotion:'平静为主，温和表达；不夸张',pauses:'遵循原文标点，不改变动作与事实',rate:0.95,pitch:1,binding:{service:'android_system',voice_id:''},rights:'system_voice',test_sample:'今天过得怎么样？我在这里，慢慢说就好。'};
  let dialog, form, note, bar, barText, pause, progress, owner='', currentScope='', activeRequestId='', profileOwner='', profile=structuredClone(defaults), revision=0, saveable=false, busy=false, recognizing=false, recognitionOwner='', playback='idle', voices=[], serial=0, speechSerial=0, cloud={available:false,models:[]}, recent=[], recentBox, previewButton, retryButton, speechBusy=false, deviceLoading=null;
  const scope=()=>JSON.stringify([state.server,state.username,state.activeId,chatAuthEpoch]);
  const node=(tag,text,cls='')=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;n.className=cls;return n;};
  const button=(label,fn,cls='text-button')=>{const b=node('button',label,cls);b.type='button';b.onclick=fn;return b;};
  function say(text){if(note)note.textContent=text;}
  function speechStatus(text){bar.hidden=false;barText.textContent=text;say(text);}
  function busySpeech(value){speechBusy=value;if(previewButton)previewButton.disabled=value||busy;if(retryButton)retryButton.disabled=value||busy;}
  function available(){return state.authenticated&&!!state.activeId;}
  async function command(action,extra={}){
    const target=scope(),ticket=speechSerial;
    const data=responseData(await nativeAsync('voiceCommand',[state.activeId,JSON.stringify({action,...extra})],75000,action==='speak'?id=>{activeRequestId=id;}:undefined));
    if(target!==scope()||ticket!==speechSerial){const error=Error('原语音操作已结束。');error.voiceCancelled=true;throw error;}
    if(data?.ok!==true)throw Error(data?.message||'语音操作暂不可用');return data;
  }
  function stop(){speechSerial++;activeRequestId='';busySpeech(false);if(available())void command('stop').catch(()=>{});owner='';if(bar)bar.hidden=true;playback='stopped';}
  function scopeChanged(){const next=scope();if(currentScope===next)return;currentScope=next;stop();serial++;profileOwner='';profile=structuredClone(defaults);cloud={available:false,models:[]};recent=[];voices=[];deviceLoading=null;saveable=false;busy=false;recognizing=false;recognitionOwner='';closeActive();}
  function receive(value){
    if(!owner||owner!==scope()||!bar||!activeRequestId||value?.request_id!==activeRequestId)return;
    playback=value.phase;bar.hidden=['idle','stopped'].includes(playback);
    barText.textContent=({synthesizing:'正在生成语音',preparing:'正在准备播放',playing:'正在朗读',paused:'朗读已暂停',completed:'朗读完成',error:'语音暂不可用'})[playback]||'语音';
    if(value.message)barText.textContent+=' · '+value.message;
    if(dialog?.open)say(barText.textContent);
    pause.hidden=!['playing','paused'].includes(playback);pause.textContent=playback==='paused'?'继续':'暂停';
    progress.hidden=!value.duration_ms;progress.max=value.duration_ms||1;progress.value=value.position_ms||0;
  }
  function setup(){if(dialog)return;
    dialog=node('dialog',undefined,'settings-dialog voice-dialog');dialog.id='voice-dialog';dialog.setAttribute('aria-labelledby','voice-title');
    form=node('form',undefined,'settings-form');const head=node('div',undefined,'dialog-heading'),title=node('h2','Texas Voice');title.id='voice-title';head.append(title,button('×',closeActive,'icon-button'));form.append(head,node('p','可选设备音色或服务器已配置的云端音色。云端朗读会把所选话语发送给语音服务，音频按会话缓存。电话模式在本机连续转写；单次语音输入可使用系统识别。','appearance-help'));
    const field=(key,label,kind='input')=>{const wrap=node('label',label),input=node(kind);input.name=key;input.id='voice-'+key;wrap.htmlFor=input.id;wrap.append(input);form.append(wrap);return input;};
    field('name','声音档案名称').maxLength=120;
    const language=field('language','语言','select');for(const [id,label] of [['zh-CN','普通话'],['zh-TW','中文（台湾）'],['en-US','英语'],['ja-JP','日语']]){const option=node('option',label);option.value=id;language.append(option);}
    const engine=field('engine','朗读服务','select');for(const [id,label] of [['android_system','设备系统音色'],['fish_tts','Fish Audio · Drama 3 等'],['cosyvoice','CosyVoice v3 Flash']]){const option=node('option',label);option.value=id;engine.append(option);}engine.onchange=()=>{const next=engine.value,changed=profile.binding.service!==next;profile=readForm();if(changed&&isCloudService(next)){const cfg=serviceConfig(next);profile.binding={service:next,voice_id:cfg.default_voice_id||'',model:cfg.model||''};}paint();if(next==='android_system'){if(changed)profile.binding={service:'android_system',voice_id:''};paint();void loadDeviceVoices();}};
    field('voice_id','本机实际音色','select');field('model','云端语音模型','select');const providerStatus=node('p','', 'appearance-help');providerStatus.id='voice-provider-status';form.append(providerStatus);
    field('reference_id','云端音色 ID（留空使用服务默认音色）').maxLength=200;
    for(const [key,label,min,max,step] of [['rate','语速',0.7,1.3,0.05],['pitch','音高',0.8,1.2,0.05]]){const input=field(key,label);input.type='number';input.min=min;input.max=max;input.step=step;}
    const direction=node('details'),summary=node('summary','声音方向与授权边界');direction.append(summary,node('p','以下描述作为可迁移的音色档案保存。设备引擎应用音色、语言、语速和音高；云端应用音色 ID 与语速。描述不会被拼成需要朗读的文字，当前不自动添加情绪标签。','appearance-help'));
    for(const [key,label] of [['timbre','基础音色'],['pronunciation','发音特点'],['emotion','情感范围'],['pauses','停顿习惯']]){const wrap=node('label',label),input=node('textarea');input.name=key;input.maxLength=600;input.rows=2;wrap.append(input);direction.append(wrap);}form.append(direction);
    const sample=field('test_sample','试听文本（不发送聊天）','textarea');sample.maxLength=300;sample.rows=3;
    const actions=node('div',undefined,'voice-actions');const saveButton=node('button','保存到当前会话','primary-button');saveButton.type='submit';saveButton.id='voice-save';
    previewButton=button('试听',()=>speakText(readForm().test_sample,'preview',readForm()));previewButton.id='voice-preview';
    retryButton=button('明确重试失败的试听',()=>speakText(readForm().test_sample,'preview',readForm(),true));retryButton.hidden=true;
    actions.append(previewButton,saveButton,button('重新读取',load),button('恢复默认草案',()=>{profile=structuredClone(defaults);paint();say('已恢复默认草案，保存后生效。');}),button('清理本机语音缓存',async()=>{try{await command('clear');stop();say('已清理本机合成语音，服务器聊天与资料不变。');}catch(e){if(!e.voiceCancelled)say(errorText(e));}}));form.append(actions);
    note=node('p','', 'voice-note');note.setAttribute('role','status');form.append(note);
    const controls=node('div',undefined,'voice-actions');controls.append(button('暂停／继续',async()=>{try{receive(await command(playback==='paused'?'resume':'pause'));}catch(e){if(!e.voiceCancelled)say(errorText(e));}}),button('停止朗读',()=>{stop();say('已停止播放。正在合成的服务器任务不会重新提交。');}),retryButton);form.append(controls);
    recentBox=node('section',undefined,'voice-recent');recentBox.setAttribute('aria-label','最近云端语音');form.append(recentBox);form.onsubmit=save;dialog.append(form);document.body.append(dialog);
    dialog.addEventListener('cancel',e=>{e.preventDefault();closeActive();});dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeActive();}});
    bar=node('section',undefined,'voice-playback');bar.id='voice-playback';bar.setAttribute('aria-label','当前消息朗读');bar.hidden=true;barText=node('span','');barText.setAttribute('role','status');pause=button('暂停',async()=>{try{receive(await command(playback==='paused'?'resume':'pause'));}catch(e){if(!e.voiceCancelled)say(errorText(e));}});progress=node('progress');progress.setAttribute('aria-label','朗读进度');bar.append(barText,progress,pause,button('停止',stop));document.querySelector('.chat-header').after(bar);
  }
  const isCloudService=service=>['fish_tts','cosyvoice'].includes(service);
  function serviceConfig(service){return cloud.services?.find(row=>row.service===service)||(service==='fish_tts'?cloud:{available:false,model:'cosyvoice-v3-flash',models:['cosyvoice-v3-flash'],reason:'这台服务器尚未配置 CosyVoice v3 Flash。'});}
  function paint(){for(const [key,value] of Object.entries(profile))if(form.elements.namedItem(key))form.elements.namedItem(key).value=value;
    form.elements.namedItem('engine').value=profile.binding.service;
    const isCloud=isCloudService(profile.binding.service),cfg=serviceConfig(profile.binding.service);const hint=document.getElementById('voice-provider-status');if(hint)hint.textContent=!isCloud?'设备音色由当前手机提供。':cfg.available?'服务端已配置；真实可用性以合成结果为准。':(cfg.reason||'请在 AstrBot 的声音与语音配置中填入该服务的独立 Key。');
    for(const key of ['model','reference_id'])form.elements.namedItem(key).closest('label').hidden=!isCloud;
    form.elements.namedItem('voice_id').closest('label').hidden=isCloud;
    form.elements.namedItem('pitch').disabled=isCloud;
    if(isCloud)form.elements.namedItem('pitch').value=1;
    const models=form.elements.namedItem('model');models.replaceChildren();
    for(const id of cfg.models||[]){const opt=node('option',id==='drama-3'?'Fish Audio Drama 3':id);opt.value=id;models.append(opt);}
    if(profile.binding.model&&!cfg.models?.includes(profile.binding.model)){const opt=node('option',profile.binding.model+'（本服务器未启用）');opt.value=profile.binding.model;models.append(opt);}
    models.value=profile.binding.model||cfg.model||'';
    form.elements.namedItem('reference_id').value=isCloud?profile.binding.voice_id:'';
    const select=form.elements.namedItem('voice_id');select.replaceChildren();const fallback=node('option','跟随设备的所选语言音色');fallback.value='';select.append(fallback);
    for(const voice of voices){const option=node('option',voice.language+' · '+voice.id+(voice.network?' · 需联网':' · 离线音色'));option.value=voice.id;select.append(option);}
    if(profile.binding.voice_id&&!voices.some(x=>x.id===profile.binding.voice_id)){const missing=node('option',profile.binding.voice_id+'（本机不可用）');missing.value=profile.binding.voice_id;select.append(missing);}select.value=profile.binding.voice_id;
    form.querySelector('#voice-save').disabled=!saveable||busy;busySpeech(speechBusy);paintRecent();
  }
  function readForm(){const value=structuredClone(profile);for(const key of Object.keys(defaults)){const input=form.elements.namedItem(key);if(input)value[key]=['rate','pitch'].includes(key)?Number(input.value):input.value.trim();}const service=form.elements.namedItem('engine').value;const cfg=serviceConfig(service),model=form.elements.namedItem('model').value;value.binding=isCloudService(service)?{service,voice_id:form.elements.namedItem('reference_id').value.trim(),model:model||cfg.model||''}:{service:'android_system',voice_id:form.elements.namedItem('voice_id').value};value.rights=isCloudService(service)?'provider_voice':'system_voice';if(isCloudService(service))value.pitch=1;return value;}
  async function fetchProfile(target,accept=()=>true){const data=await apiClient.json('GET','/chat/voice?session_id='+encodeURIComponent(state.activeId));if(target!==scope()||!accept())return false;if(data.session_id!==state.activeId||!data.profile||!Number.isInteger(data.revision))throw Error('声音档案返回不完整');profile=data.profile;cloud=data.cloud||{available:false,models:[]};recent=Array.isArray(data.recent_audio)?data.recent_audio:[];revision=data.revision;profileOwner=target;saveable=true;return true;}
  function paintRecent(){
    if(!recentBox)return;recentBox.replaceChildren(node('h3','最近云端语音'));
    if(!recent.length)recentBox.append(node('p','暂无合成记录。试听只合成这段文字，不会发送聊天。','appearance-help'));
    for(const item of recent){const row=node('div',undefined,'voice-receipt');
      const labels={ready:item.cached?'可播放':'缓存已过期',failed:'合成失败',generating:'服务器正在合成',unknown:'结果待确认'};
      row.append(node('strong',(item.preview?'试听':'消息朗读')+' · '+(labels[item.state]||'待确认')),
        node('small',(item.model||'')+' · '+new Date(item.updated_at*1000).toLocaleString()));
      if(item.error)row.append(node('p',item.error));
      if(item.state==='ready'&&item.cached)row.append(button('播放已生成语音',()=>playCached(item)));
      recentBox.append(row);
    }
    retryButton.hidden=!recent.some(x=>x.preview&&x.retryable);
  }
  async function playCached(item){
    if(speechBusy||!available())return;const target=scope(),ticket=++speechSerial;owner=target;activeRequestId='';busySpeech(true);
    try{speechStatus('正在读取已生成音频，不会再次合成…');const result=responseData(await nativeAsync('playCloudVoice',[state.activeId,item.audio_id,String(item.message_id||'preview')],120000,id=>{activeRequestId=id;}));if(target===scope()&&ticket===speechSerial&&result?.ok!==true)throw Error(result?.message||'手机播放未完成');}
    catch(e){if(target===scope()&&ticket===speechSerial)speechStatus(errorText(e));}
    finally{if(target===scope()&&ticket===speechSerial)busySpeech(false);}
  }
  async function loadDeviceVoices(){
    if(deviceLoading)return;const target=scope(),ticket={};deviceLoading=ticket;
    try{const data=responseData(await nativeAsync('voiceCommand',[state.activeId,JSON.stringify({action:'voices'})],8000));
      if(target!==scope()||deviceLoading!==ticket)return;if(data?.ok!==true)throw Error(data?.message||'设备音色不可用');voices=data.voices||[];
      if(profile.binding.service==='android_system'){const draft=readForm();profile=draft;paint();say('本机有 '+voices.length+' 个音色。');}}
    catch(e){if(target===scope()&&deviceLoading===ticket&&profile.binding.service==='android_system')say(errorText(e)+' 云端音色不依赖本机语音引擎。');}
    finally{if(deviceLoading===ticket)deviceLoading=null;}
  }
  async function load(){
    setup();scopeChanged();if(!available()||busy)return;const target=scope(),ticket=++serial;busy=true;saveable=false;paint();say('正在读取声音档案…');
    try{await fetchProfile(target,()=>ticket===serial);if(ticket!==serial||target!==scope())return;
      say('已读取 TLS 声音档案，修订 '+revision+'。'+(cloud.available?' 云端已配置 '+cloud.label+'；是否可用以合成结果为准。':' 云端语音未配置。'));
    }catch(e){if(ticket!==serial||target!==scope())return;saveable=false;say('无法读取声音档案：'+errorText(e));}
    finally{if(ticket===serial&&target===scope()){busy=false;paint();if(profile.binding.service==='android_system')void loadDeviceVoices();}}
  }
  async function save(event){event.preventDefault();if(busy||!saveable||profileOwner!==scope())return;const target=scope(),draft=readForm();busy=true;paint();try{const data=await apiClient.json('POST','/chat/voice',{session_id:state.activeId,profile:draft,expected_revision:revision});if(target!==scope())return;profile=data.profile;revision=data.revision;say('声音档案已保存，之后的朗读使用新配置。');}catch(e){if(target===scope()){saveable=false;say(errorText(e)+' 请重新读取同一档案核对；不会自动再次提交。');}}finally{if(target===scope()){busy=false;paint();}}}
  function open(){if(!available()){showNotice('先打开已登录的聊天。');return;}setup();scopeChanged();window.ChatSettingsHub?.close();if(!dialog.open)dialog.showModal();void load();}
  function closeActive(){if(!dialog?.open)return false;dialog.close();return true;}
  async function speakText(text,id,settings,retryFailed=false){setup();scopeChanged();if(!available()||speechBusy||busy)return;const target=scope(),speechTicket=++speechSerial;owner=target;activeRequestId='';busySpeech(true);
    try{if(!settings&&profileOwner!==target){try{await fetchProfile(target,()=>speechTicket===speechSerial);}catch(_){if(target!==scope()||speechTicket!==speechSerial)return;profile=structuredClone(defaults);profileOwner=target;saveable=false;}}if(target!==scope()||speechTicket!==speechSerial)return;
      const chosen=settings||profile;if(!text.trim())throw Error('这条消息没有可朗读的话语。动作和图片不会当成话语朗读。');if(text.length>3500)throw Error('这条消息超过单次 3500 字朗读上限，原文保持完整。');
      bar.hidden=false;pause.hidden=true;progress.hidden=true;
      if(isCloudService(chosen.binding.service)){
        const cfg=serviceConfig(chosen.binding.service);if(!cfg.available)throw Error(cfg.reason||'当前服务器没有启用云端语音。');if(!cfg.models?.includes(chosen.binding.model||cfg.model))throw Error('所选模型未在当前服务器启用；请明确重新选择，原档案不会自动更换。');if(chosen.binding.service==='cosyvoice'&&!chosen.binding.voice_id&&!cfg.default_voice_id)throw Error('请先填写 CosyVoice 的真实音色 ID。');
        if(text.length>(cfg.max_characters||1500))throw Error('云端单次支持 1500 字朗读；原消息不会被截断。');
        speechStatus('正在生成云端语音…稍后会直接播放，请不要连续点击。');
        const body=id==='preview'?{session_id:state.activeId,preview_text:text,profile:chosen}:{session_id:state.activeId,message_id:String(id)};
        if(retryFailed)body.retry_failed=true;
        const audio=await apiClient.json('POST','/chat/voice/synthesize',body);
        if(target!==scope()||speechTicket!==speechSerial)return;
        if(audio.session_id!==state.activeId)throw Error('语音结果与当前会话不一致。');
        if(id!=='preview'&&audio.state==='skipped'&&audio.reason==='no_spoken_text'&&audio.message_id===String(id)){
          speechStatus('这条回复只有动作，没有台词。');return;
        }
        if(!/^[a-f0-9]{64}$/.test(audio.audio_id||''))throw Error('语音结果与当前会话不一致。');
        speechStatus(audio.cached?'正在播放缓存语音…':'正在下载语音…');
        const result=responseData(await nativeAsync('playCloudVoice',[state.activeId,audio.audio_id,String(id)],120000,request=>{activeRequestId=request;}));
        if(result?.ok!==true)throw Error(result?.message||'音频暂时无法播放。');
      }else{speechStatus('准备朗读…');receive(await command('speak',{text,message_id:String(id),language:chosen.language,voice_id:chosen.binding.voice_id,rate:chosen.rate,pitch:chosen.pitch}));}
    }catch(e){if(target===scope()&&speechTicket===speechSerial){speechStatus(errorText(e));pause.hidden=true;progress.hidden=true;}}
    finally{if(target===scope()&&speechTicket===speechSerial){busySpeech(false);if(isCloudService(chosenService(settings)))void refreshReceipts(target);}}
  }
  function chosenService(settings){return (settings||profile).binding.service;}
  async function refreshReceipts(target){try{const data=await apiClient.json('GET','/chat/voice?session_id='+encodeURIComponent(state.activeId));if(target===scope()){recent=Array.isArray(data.recent_audio)?data.recent_audio:[];paintRecent();}}catch(_){} }
  function speechText(message){
    const text=messageParts(message).filter(part=>['plain','text','speech'].includes(part.type)&&typeof part.text==='string'&&!['reasoning','tool_call','tool_call_result'].includes(part.chain_type)).map(part=>part.text).join('\n\n');
    // Same stage notation as the saved-reply endpoint, also needed by system TTS.
    const stack=[],spans=[],openings={'(':')','（':'）'};
    for(let i=0;i<text.length;i++){
      const char=text[i];
      if(openings[char])stack.push([i,openings[char]]);
      else if(stack.length&&char===stack.at(-1)[1]){
        const [start]=stack.pop();
        while(spans.length&&spans.at(-1)[0]>=start)spans.pop();
        spans.push([start,i+1]);
      }
    }
    if(!spans.length)return text.trim();
    const chunks=[];let end=0;
    for(const [start,stop] of spans){chunks.push(text.slice(end,start));end=stop;}
    chunks.push(text.slice(end));
    const spoken=chunks.join('').replace(/^[\s，。；、：,.;:]+/u,'').trim();
    return /[\p{L}\p{N}]/u.test(spoken)?spoken:'';
  }
  function speak(message){
    if(message?.role!=='assistant'||message.delivery!=='confirmed'||message.serverId==null)return;
    const text=speechText(message);
    if(!text){showNotice('这条回复没有可朗读的话语。');return;}
    void speakText(text,message.serverId);
  }
  async function recognize(){setup();scopeChanged();if(!available()||recognizing){showNotice('请先打开当前聊天，或结束正在进行的识别。');return;}const target=scope();recognizing=true;recognitionOwner=target;
    try{if(profileOwner!==target){try{await fetchProfile(target);}catch(_){if(target===scope()){profile=structuredClone(defaults);profileOwner=target;saveable=false;}}}if(target!==scope())return;
      const data=responseData(await nativeAsync('recognizeSpeech',[state.activeId,profile.language||'zh-CN'],180000));if(target!==scope()||data.cancelled)return;
      const draft=document.getElementById('draft');if(!draft||draft.disabled||draft.readOnly)throw Error('输入框当前不可编辑，识别结果未发送。');if(data.session_id!==state.activeId||typeof data.text!=='string')throw Error('识别结果与当前会话不匹配。');
      const value=draft.value+(draft.value?'\n':'')+data.text;if(value.length>(draft.maxLength>0?draft.maxLength:16000))throw Error('识别后草稿过长，原草稿未覆盖。');draft.value=value;saveDraft();draft.dispatchEvent(new Event('input',{bubbles:true}));draft.focus();showNotice('已加入语音识别文字，可修改后发送。');
    }catch(e){if(target===scope())showNotice(errorText(e));}finally{if(recognitionOwner===target){recognizing=false;recognitionOwner='';}}
  }
  document.addEventListener('DOMContentLoaded',()=>{setup();const entry=button('声音与语音输入',open,'menu-item');entry.id='menu-voice';document.getElementById('more-menu').append(entry);const input=button('语音转文字',recognize,'attachment-picker');document.querySelector('[data-compose-pane="attachments"]').prepend(input);document.getElementById('voice-button').setAttribute('aria-label','语音识别后编辑草稿');document.getElementById('voice-button').title='语音转文字';},{once:true});
  window.addEventListener('pagehide',stop);
  return {open,closeActive,scopeChanged,receive,speak,recognize,speechText};
})();
