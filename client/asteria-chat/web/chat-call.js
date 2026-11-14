'use strict';
/* One explicit call; finalized local turns use the original prepared-composition sender. */
window.ChatCall = (() => {
  let dialog,bar,note,turnsBox,replyBox,role,level,startButton,muteButton,endButton,importButton,silence,mode,myTurnButton;
  let callId='',owner='',active=false,muted=false,held=false,output=false,modelReady=false,busy=false,draining=false,blocked=false,scheduled=false,lastSequence=0,voiceReplies=false;
  let waiting=[],history=[],renderedTurns='',voiceEpoch=0,capturing=false,interrupting=false;
  const paceKey='texas-call-pace-v1';
  const scope=()=>JSON.stringify([state.server,state.username,state.activeId,chatAuthEpoch]);
  const available=()=>state.authenticated&&!!state.activeId&&(!primaryConnectionId()||state.activeId===primaryConnectionId());
  const current=()=>!!callId&&owner===scope();
  const node=(tag,text,cls='')=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;n.className=cls;return n;};
  const button=(text,fn,cls='text-button')=>{const b=node('button',text,cls);b.type='button';b.onclick=fn;return b;};
  const unknown=()=>state.messages.some(m=>m.role==='user'&&['unknown','send-unknown'].includes(m.delivery));
  const say=text=>{if(note)note.textContent=text;};
  async function command(action,extra={}){
    const target=scope(),id=callId;
    const value=responseData(await nativeAsync('phoneCall',[state.activeId,JSON.stringify({action,call_id:id,...extra})],action==='start'?180000:20000));
    if(target!==scope()||id!==callId)throw Error('原通话已结束或当前角色已变化。');
    if(value?.ok!==true)throw Error(value?.message||'通话操作未完成。');return value;
  }
  function setup(){if(dialog)return;
    dialog=node('dialog',undefined,'settings-dialog call-dialog');dialog.id='phone-call-dialog';dialog.setAttribute('aria-labelledby','call-title');
    const content=node('section',undefined,'call-content'),head=node('div',undefined,'dialog-heading'),title=node('h2','电话模式');title.id='call-title';head.append(title,button('收起',()=>dialog.close()));content.append(head);
    role=node('p','当前角色','call-role');content.append(role,node('p','停顿分句后自动发送。双向语音会朗读角色回复，播放时暂停收音。录音在本机识别。','appearance-help'));
    const options=node('div',undefined,'call-options'),label=node('label','收句节奏');silence=node('select');silence.id='call-silence';silence.setAttribute('aria-label','分句停顿');for(const [value,text] of [[1000,'快速 · 1秒'],[1800,'标准 · 1.8秒'],[2500,'耐心 · 2.5秒']]){const option=node('option',text);option.value=value;silence.append(option);}silence.value='1800';try{const saved=localStorage.getItem(paceKey);if(['1000','1800','2500'].includes(saved))silence.value=saved;}catch(_){}silence.onchange=()=>{try{localStorage.setItem(paceKey,silence.value);}catch(_){say('节奏本次已应用，本机保存未完成。');}};label.append(silence);options.append(label);
    const modeLabel=node('label','通话方式');
    mode=node('select');mode.id='call-mode';mode.setAttribute('aria-label','通话方式');
    for(const [value,text] of [['text','语音输入 · 文字回复'],['voice','双向语音 · 轮流说话']]){
      const option=node('option',text);option.value=value;mode.append(option);
    }
    modeLabel.append(mode);options.prepend(modeLabel);
    importButton=button('导入离线语音模型',importModel);importButton.id='call-import-model';options.append(importButton);content.append(options);
    const modelHelp=node('details'),summary=node('summary','首次使用：离线模型');modelHelp.append(summary,node('p','先把交付目录中的“SenseVoice 离线语音模型.zip”传到手机，再点击导入。约239 MB，导入一次即可跨聊天使用，不需要转文字 Key。导入不会读取私人录音，也不会开始收音。','appearance-help'));content.append(modelHelp);
    level=node('progress');level.id='call-level';level.max=100;level.value=0;level.setAttribute('aria-label','麦克风输入音量');content.append(level);
    note=node('p','先导入模型，再点击开始通话。','call-status');note.id='call-status';note.setAttribute('role','status');content.append(note);
    turnsBox=node('div',undefined,'call-turns');turnsBox.id='call-turns';turnsBox.setAttribute('aria-label','最近识别和发送的片段');content.append(turnsBox);
    replyBox=node('p','文字回复会继续保存在当前聊天。','call-reply');replyBox.id='call-reply';content.append(replyBox);
    const controls=node('div',undefined,'call-controls');startButton=button('开始通话 · 自动发送',()=>start(false),'primary-button');startButton.id='call-start';muteButton=button('静音',toggleMute);muteButton.id='call-mute';endButton=button('结束通话',end);endButton.id='call-end';myTurnButton=button('我来说',takeTurn);myTurnButton.id='call-my-turn';controls.append(startButton,myTurnButton,muteButton,endButton,button('现在发送这句',async()=>{if(current()&&active&&!muted&&!output)try{receive(await command('finish_turn'));}catch(e){say(errorText(e));}}),button('在此设备继续',()=>start(true)));  content.append(controls,node('p','收起面板可继续通话。静音会关闭麦克风；结束会丢弃未发送片段，已经提交的消息仍需在聊天记录中核对。','appearance-help'));dialog.append(content);document.body.append(dialog);
    dialog.addEventListener('cancel',event=>{event.preventDefault();dialog.close();});
    bar=node('section',undefined,'call-bar');bar.id='call-bar';bar.hidden=true;bar.setAttribute('aria-label','电话模式收音状态');bar.append(node('span','电话模式'),button('打开',open),button('静音',toggleMute),button('结束',end),button('我来说',takeTurn));document.querySelector('.chat-header').after(bar);
  }
  function paint(){if(!dialog)return;
    const valid=available();role.textContent=document.getElementById('conversation-title')?.textContent||'当前角色';
    startButton.hidden=active;startButton.disabled=!valid||active||busy||draining||!modelReady;muteButton.hidden=!active;muteButton.disabled=!active||busy;endButton.disabled=!active&&!busy;silence.disabled=active||busy;mode.disabled=active||busy;importButton.disabled=active||busy;
    muteButton.textContent=muted||held?'继续通话':'静音';importButton.textContent=modelReady?'模型已就绪 · 重新导入':'导入离线语音模型';
    myTurnButton.hidden=!active||!output;myTurnButton.disabled=interrupting||busy;
    bar.children[4].hidden=myTurnButton.hidden;bar.children[4].disabled=myTurnButton.disabled;
    const phase=interrupting?'正在停止播放':output?(window.ChatVoice?.phase()==='playing'?'角色正在说话':window.ChatVoice?.phase()==='paused'?'声音已暂停 · 麦克风已静音':'正在准备角色声音'):muted||held?'麦克风已静音':draining||state.sending||state.remoteRunning?'整理输入／等待回复':capturing?'正在听你说':'正在整理输入';
    bar.hidden=!active;bar.firstElementChild.textContent='电话 · '+phase;bar.children[2].textContent=muted||held?'继续':'静音';
    const latest=state.messages.filter(m=>m.role==='assistant'&&m.delivery==='confirmed').at(-1);if(latest)replyBox.textContent='对方：'+String(latest.text||'').slice(0,600);
    const key=owner+'|'+history.slice(-24).map(item=>item.sequence+':'+item.status).join('|');
    if(key!==renderedTurns){renderedTurns=key;turnsBox.replaceChildren();for(const item of history.slice(-24)){const row=node('article',undefined,'call-turn'),stateText=node('small',item.status),text=node('p',item.text);row.dataset.sequence=item.sequence;row.append(stateText,text,button('复制到草稿',()=>copyToDraft(item)));turnsBox.append(row);}}
  }
  function copyToDraft(item){if(owner!==scope()){say('当前角色已变化，这段文字没有写入新聊天。');return;}const draft=$('draft'),next=draft.value+(draft.value?'\n':'')+item.text;if(next.length>draft.maxLength){say('草稿空间不足，原文字保持不变。');return;}draft.value=next;draft.dispatchEvent(new Event('input',{bubbles:true}));say('已复制到当前草稿，可自行编辑发送。');}
  async function open(){setup();scopeChanged();if(!available()){showNotice('先打开当前角色的聊天，再使用电话模式。');return;}hideMoreMenu();window.ChatComposer?.closePanel();$('draft').blur();if(!dialog.open)dialog.showModal();paint();
    try{const value=await command('status');modelReady=value.model_ready===true;if(value.active){if(!callId){callId=value.call_id;owner=scope();}receive(value);}else if(!active)say(modelReady?'离线模型已就绪。点击开始后，停顿分句会自动发送。':'请先导入离线语音模型。');paint();}catch(e){say(errorText(e));}
  }
  async function importModel(){if(active||busy)return;busy=true;paint();const target=scope();try{const data=responseData(await nativeAsync('importCallModel',[state.activeId],600000));if(target!==scope())return;if(data.cancelled){say('已取消导入，没有开始收音。');return;}if(data.ok!==true||data.model_ready!==true)throw Error(data.message||'模型导入未完成。');modelReady=true;say('离线模型已就绪，可以开始通话。');}catch(e){if(target===scope())say(errorText(e));}finally{busy=false;paint();}}
  async function start(takeover=false){if(!available()||active||busy||draining||!modelReady)return;if(unknown()){say('有消息结果尚未确认，请先同步聊天记录，再开始通话。');return;}
    owner=scope();callId='call-'+(crypto.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
    const ticket=callId;const accepts=()=>current()&&callId===ticket;
    let startingNative=false;
    voiceReplies=mode.value==='voice';lastSequence=0;waiting=[];history=[];blocked=false;busy=true;paint();
    try{
      if(voiceReplies){
        say('正在核对当前角色的声音档案…');
        if(!await window.ChatVoice.prepareCall(accepts)||!accepts())return;
        await window.ChatDevices.acquire(ticket,takeover);if(!accepts()){window.ChatDevices.release(ticket);return;}
      }
      say('正在申请麦克风并准备本机收音…');startingNative=true;
      receive(await command('start',{silence_ms:Number(silence.value),voice_replies:voiceReplies}));
    }catch(e){
      if(accepts()){if(startingNative)try{native().endPhoneCall?.();}catch(_){}active=false;window.ChatDevices?.release(ticket);say(errorText(e));}
    }finally{if(callId===ticket){busy=false;paint();}}
  }
  async function toggleMute(){if(!current()||!active||busy)return;busy=true;paint();try{const resume=muted||held;if(resume&&unknown()){say('上一条发送仍未确认，请先同步聊天记录。');return;}if(resume)blocked=false;receive(await command(resume?'resume':'mute'));}catch(e){say(errorText(e));}finally{busy=false;paint();stateChanged();}}
  function end(){if(!callId&&!active)return;voiceEpoch++;const endedId=callId;void window.ChatVoice?.cancelCallReply(endedId).then(stopped=>{if(stopped)window.ChatDevices?.release(endedId);});callId='';active=false;blocked=true;busy=false;for(const item of waiting)item.status=item.inflight?'通话已结束 · 已提交片段请到聊天核对':'通话已结束 · 未发送';waiting=[];try{native().endPhoneCall?.();}catch(_){}say('通话已结束 · 麦克风已关闭');if(level)level.value=0;paint();}
  function scopeChanged(){if(owner&&owner!==scope()){end();callId='';owner='';waiting=[];history=[];lastSequence=0;modelReady=false;if(dialog?.open)dialog.close();paint();}}
  function receive(value){if(!current()||value?.call_id!==callId||value.session_id!==state.activeId)return;
    capturing=value.capturing===true;active=value.active===true;muted=value.muted===true;held=value.held===true;output=value.output===true;
    if(typeof value.voice_replies==='boolean'){voiceReplies=value.voice_replies;mode.value=voiceReplies?'voice':'text';}
    if(value.model_ready===true)modelReady=true;if(level)level.value=Math.min(100,(value.level||0)*500);if(value.message)say(value.message);
    for(const item of value.turns||[]){if(!Number.isInteger(item.sequence)||item.sequence<=lastSequence||typeof item.text!=='string'||!item.text.trim()||item.text.length>16000)continue;lastSequence=item.sequence;const turn={sequence:item.sequence,text:item.text,status:'等待发送',inflight:false};waiting.push(turn);history.push(turn);}
    if(history.length>48)history.splice(0,history.length-48);
    if(!active){const endedId=callId;void window.ChatVoice?.cancelCallReply(endedId).then(stopped=>{if(stopped)window.ChatDevices?.release(endedId);});for(const item of waiting)item.status=item.inflight?'通话已结束 · 已提交片段请核对':'通话已结束 · 未发送';waiting=[];}
    paint();stateChanged();
  }
  function stateChanged(){scopeChanged();if(!current()||!active||muted||output||blocked||draining||scheduled||!waiting.length)return;scheduled=true;queueMicrotask(()=>{scheduled=false;void drain();});}
  async function drain(){if(draining||!current()||!active||muted||output||blocked)return;draining=true;const target=owner,id=callId;
    try{while(current()&&callId===id&&active&&!muted&&!output&&!blocked&&waiting.length){
      if(state.sending||state.loading||state.attaching||state.remoteRunning)break;
      if(unknown()){blocked=true;receive(await command('hold'));say('有消息结果待确认，电话已暂停，不会自动重发。');break;}
      const turn=waiting[0];turn.status='正在提交';turn.inflight=true;paint();
      const receipt=await sendMessage({preventDefault(){}},{kind:'composition',scope:{server:state.server,username:state.username,sessionId:state.activeId},text:turn.text,files:[],parts:[{type:'text',text:turn.text,fragment_id:id+'-'+turn.sequence}],consume:false});
      if(owner!==target||callId!==id||!active)return;
      turn.inflight=false;
      if(!receipt?.started&&!receipt?.failed){turn.status='等待当前聊天空闲';paint();break;}
      waiting.shift();turn.status=receipt?.confirmed?(receipt.failed?'消息已保存 · 回复未完成':'已由聊天确认'):'结果未知 · 不会重发';paint();
      if(!receipt?.confirmed||receipt.failed){blocked=true;await command('ack',{sequence:turn.sequence});receive(await command('hold'));say('请先同步聊天记录核对结果，再明确继续。当前片段不会自动重发。');break;}
      receive(await command('ack',{sequence:turn.sequence}));
      if(voiceReplies&&receipt.reply)await playReply(receipt.reply,id);
    }}catch(e){if(owner===target&&callId===id&&active){blocked=true;try{receive(await command('hold'));}catch(_){}say(errorText(e)+' 自动发送已暂停，请核对聊天。');}}
    finally{draining=false;paint();}
  }
  async function playReply(message,id){
    const epoch=voiceEpoch;
    const sameCall=()=>current()&&callId===id&&active&&epoch===voiceEpoch;
    const accepts=()=>sameCall()&&!muted&&!held&&!blocked;
    if(!accepts()||output||!window.ChatVoice.speechText(message).trim())return;
    await window.ChatDevices.check(id);if(!accepts())return;
    receive(await command('output',{output:true}));
    if(sameCall()&&!output)throw Error('麦克风未暂停，语音未播放。');
    try{
      if(accepts()){
        say('正在生成角色语音，麦克风已暂停。');
        await window.ChatVoice.speakCallReply(message,id,accepts);
      }
    }finally{
      if(sameCall())receive(await command('output',{output:false}));
    }
  }
  async function takeTurn(){
    if(!current()||!active||!output||interrupting)return;
    const id=callId;voiceEpoch++;interrupting=true;paint();
    try{
      const stopped=await window.ChatVoice.cancelCallReply(id);
      if(!current()||callId!==id||!active)return;
      if(!stopped){receive(await command('hold'));say('停止播放未确认，已保持静音，请结束通话后重试。');return;}
      receive(await command('output',{output:false}));
      say(muted||held?'播放已停止 · 麦克风保持静音':'我来说 · 正在听你说');
    }catch(e){say(errorText(e));}finally{interrupting=false;paint();}
  }
  function setOutputActive(value){if(current()&&active)void command('output',{output:!!value}).then(receive).catch(()=>{});}
  document.addEventListener('DOMContentLoaded',()=>{setup();const entry=button('电话模式',open,'menu-item');entry.id='menu-phone-call';$('more-menu').append(entry);$('call-entry').addEventListener('click',open);paint();},{once:true});
  window.addEventListener('pagehide',end);
  return {open,end,receive,scopeChanged,stateChanged,setOutputActive,takeTurn,voiceStateChanged:paint};
})();
