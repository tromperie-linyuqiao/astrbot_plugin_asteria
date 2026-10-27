"""Owned APP reports into the existing PPB bridge; bridge credentials stay here.

The user explicitly selects an already assigned device. This does not create a
QQ/Presence lease, alter device ownership or run a second perception collector.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,HTTPRedirectHandler,build_opener

from .chat_expressions import ChatExpressions,ChatExpressionError
from .chat_identity import identity_service
from .chat_workspace import ChatWorkspace
from .models import canonical,plain
from .native_phone_status import NativePhoneStatus

NAMESPACE='tls.chat.perception'
SECTIONS=('basic','app','music')
INSTALL=re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z')
FIELDS={
 'battery':{'level':(int,0,100),'charging':bool,'charging_type':32,'temperature_c':(float,-40,100)},
 'screen':{'on':bool,'locked':bool},
 'network':{'type':32,'metered':bool,'roaming':bool},
 'audio':{'media_active':bool,'ringer_mode':32,'headphones':bool},
 'activity':{'device_idle':bool,'last_unlock_epoch':(float,0,4102444800)},
 'device':{'name':120,'platform':24,'os_version':32,'power_save':bool},
 'app':{'foreground_package':120,'foreground_label':60,'foreground_since_epoch':(float,0,4102444800),'foreground_minutes':(int,0,1440)},
 'music':{'schema_version':(int,1,1),'source':32,'state':32,'playing':bool,'observed_at':(float,1,4102444800),
     'title':160,'artist':160,'album':160,'package':160,'track_id':160,'session_id':160,
     'duration_ms':(int,0,604800000),'progress_ms':(int,0,604800000),'playback_speed':(float,0,4)},
}


def installation(value):
 if not isinstance(value,str) or not INSTALL.fullmatch(value):raise ChatExpressionError('本机标识无效，请重新打开感知设置')
 return value


def sections(value):
 if type(value)is not dict or set(value)!=set(SECTIONS) or any(type(v)is not bool for v in value.values()):
  raise ChatExpressionError('请选择明确的感知项目')
 return dict(value)


def frame(value,allowed,*,now):
 if type(value)is not dict or set(value)-set(FIELDS)-{'ts'} or len(canonical(value).encode())>32768:
  raise ChatExpressionError('感知数据字段或大小无效')
 stamp=value.get('ts')
 if type(stamp)not in(int,float) or not math.isfinite(stamp) or abs(now-stamp)>600:
  raise ChatExpressionError('手机时间与服务器相差过大，请同步时间')
 result={'ts':stamp}
 for name,raw in value.items():
  if name=='ts':continue
  category=name if name in ('app','music') else 'basic'
  if allowed[category] is not True:raise PermissionError('该感知项目尚未授权')
  if type(raw)is not dict or set(raw)-set(FIELDS[name]):raise ChatExpressionError('感知数据包含不支持的字段')
  clean={}
  for key,item in raw.items():
   rule=FIELDS[name][key]
   if rule is bool:
    if type(item)is not bool:raise ChatExpressionError('感知开关字段无效')
   elif type(rule)is int:
    if not isinstance(item,str) or len(item)>rule or any(ord(ch)<32 for ch in item):raise ChatExpressionError('感知文本字段无效')
   else:
    typ,low,high=rule
    if type(item)not in ((int,) if typ is int else (int,float)) or not math.isfinite(item) or not low<=item<=high:
     raise ChatExpressionError('感知数值字段无效')
   clean[key]=item
  if name=='music':
   if (clean.get('schema_version')!=1 or clean.get('source')not in ('media_session','unavailable')
     or clean.get('state')not in ('playing','paused','stopped','buffering','unknown') or type(clean.get('playing'))is not bool
     or abs(now-clean.get('observed_at',0))>600):raise ChatExpressionError('音乐状态来源无效')
  if clean:result[name]=clean
 if len(result)==1:raise ChatExpressionError('没有已授权的感知数据')
 return result


class _NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None


class ChatPhonePerception:
 def __init__(self,plugin,*,clock=time.time,forward=None):
  self.plugin,self.clock=plugin,clock
  self.links=identity_service(plugin)
  self.journal=self.links.journal
  self.forward=forward or self._forward

 def _phone(self):
  from .native_phone_service.runtime import NativePhoneService
  value=getattr(self.plugin,'_native_phone_service',None)
  if (not isinstance(value,NativePhoneService) or not value._active or value._music_stopping
    or getattr(self.plugin,'_stopping',False)):raise RuntimeError('原生手机感知服务暂不可用')
  return value

 def _access(self,username,session,*,optional=False):
  self.links._check();link=self.links.get(username,session)
  permission=bool(link and ChatWorkspace(self.links).settings(username,session)['values']['linked_perception'])
  try:phone=self._phone()
  except RuntimeError:
   if optional:return link,permission,None,[]
   raise
  devices=phone._music_devices_for_user(link['qq_scope']['user_id']) if permission else []
  return link,permission,phone,devices

 def _key(self,install):return 'config:'+installation(install)

 async def read_snapshot_current(self,username,session,install):
  # Opening/refreshing this owned panel is a read, not permission to start a
  # phone collector. Reuse the original client's lock, cache and HTTP timeout.
  baseline=await asyncio.to_thread(self.snapshot,username,session,install)
  link,permission,phone,devices=self._access(username,session,optional=True)
  native_scope=link.get('app_scope')if link else None
  if not permission or phone is None or not native_scope:return baseline
  reader=NativePhoneStatus(self.plugin,clock=self.clock)
  for device in devices[:16]:
   current=self._access(username,session,optional=True)
   if current[0]!=link or current[1]is not True or current[2]is not phone or current[3]!=devices:break
   try:await reader.refresh(native_scope,device_id=device)
   except (RuntimeError,PermissionError,ValueError,AttributeError):break
  return await asyncio.to_thread(self.snapshot,username,session,install)

 def snapshot(self,username,session,install):
  key=self._key(install);scope=ChatExpressions.message_scope(username,session)
  link,permission,phone,devices=self._access(username,session,optional=True)
  row=self.journal.fetch(NAMESPACE,key,scope);data=row['data'] if row else {}
  valid=bool(link and data.get('link_id')==link['link_id'] and permission and data.get('device_id')in devices)
  native_scope=link.get('app_scope')if link else None
  unified=NativePhoneStatus(self.plugin,clock=self.clock).read(native_scope or scope,
    device_id=data.get('device_id')if valid else None,include_reports=False)
  report=self.journal.fetch(NAMESPACE,'status:'+install,scope)
  latest=report['data']if report else {}
  proven=bool(valid and unified['access']['authorized'] and latest.get('device_id')==data.get('device_id')
    and latest.get('config_revision')==(row['revision']if row else None)and latest.get('link_id')==link['link_id'])
  unified['report']={'state':latest.get('state','unknown')if proven else 'unverified'if latest and valid else 'unknown',
    'started_at':latest.get('started_at')if proven else None,'completed_at':latest.get('completed_at')if proven else None,
    'http_status':latest.get('bridge_status')if proven and type(latest.get('bridge_status'))is int else None,
    'accepted':proven and latest.get('state')=='accepted','provenance':'existing_journal_report_receipt'if proven else None}
  return dict(installation_id=install,session_id=session,enabled=data.get('enabled')is True and valid,
    device_id=data.get('device_id')if valid else None,devices=[dict(id=v,label=v)for v in devices],
    sections=data.get('sections',dict.fromkeys(SECTIONS,False))if valid else dict.fromkeys(SECTIONS,False),
    revision=row['revision']if row else 0,linked=bool(link),permission_granted=permission,
    unified_status=unified,bridge_available=bool(phone and phone.client.configured),reason='phone_service_unavailable'if phone is None else
    'ready'if devices and permission and phone.client.configured else 'binding_required'if not link else
    'perception_permission_required'if not permission else 'device_binding_required'if not devices else 'bridge_unavailable')

 def save(self,username,session,body):
  if set(body)!={'installation_id','device_id','enabled','sections','consent','expected_revision'}:
   raise ChatExpressionError('感知设置字段无效')
  install=installation(body['installation_id']);selected=sections(body['sections'])
  if type(body['enabled'])is not bool or type(body['expected_revision'])is not int or body['expected_revision']<0:
   raise ChatExpressionError('请重新读取当前感知设置')
  scope=ChatExpressions.message_scope(username,session)
  with self.journal._lock:
   current=self.snapshot(username,session,install)
   if body['expected_revision']!=current['revision']:
    from .journal import JournalConflict
    raise JournalConflict('perception configuration changed')
   if body['enabled'] is False:
    prior=self.journal.fetch(NAMESPACE,self._key(install),scope)
    data=prior['data']if prior else {}
    # Withdrawal only changes this owned installation's grant. An unavailable
    # collector, revoked device map or unbound QQ must not prevent withdrawal.
    self.journal.put(NAMESPACE,self._key(install),scope,dict(data,enabled=False,
      sections=selected,installation_id=install,consent=False),
      expected_revision=current['revision'],authorize=self.links.current)
    return self.snapshot(username,session,install)
   link,permission,phone,devices=self._access(username,session)
   if body['enabled'] and (body['consent']is not True or not permission or body['device_id']not in devices or not any(selected.values())):
    raise PermissionError('请确认绑定、感知授权、设备和本次采集项目')
   if body['device_id']is not None and body['device_id']not in devices:raise PermissionError('不能选择其他用户的设备')
   if not current['revision'] and len(self.journal.list(NAMESPACE,scope,limit=65))>=64:
    raise ChatExpressionError('本会话感知设备配置已满')
   self.journal.put(NAMESPACE,self._key(install),scope,dict(enabled=body['enabled'],sections=selected,
     installation_id=install,device_id=body['device_id'],link_id=link['link_id']if link else None,consent=body['consent']is True),
     expected_revision=current['revision'],authorize=self.links.current)
  return self.snapshot(username,session,install)

 def _forward(self,phone,device,event,payload,current):
  # The existing Phone client owns its configured bridge address/token. No
  # arbitrary URL, credential or device is accepted from a mobile report.
  if current()is not True:raise PermissionError('感知授权已经变化')
  phone._sync_client();client=phone.client
  if not client.configured:raise RuntimeError('原感知桥连接尚未配置')
  request=Request(client.base_url+'/report?'+urlencode({'device_id':device}),
    data=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8'),
    headers={'Authorization':'Bearer '+client.token,'Content-Type':'application/json; charset=utf-8','Idempotency-Key':event},method='POST')
  if current()is not True:raise PermissionError('感知授权已经变化')
  try:
   with build_opener(_NoRedirect).open(request,timeout=min(float(client.timeout),8))as response:
    raw=response.read(262145)
    if len(raw)>262144:raise RuntimeError('感知桥返回过大')
    value=json.loads(raw)
  except HTTPError as error:
   if error.code in(400,401,403,404,409,429):return dict(state='rejected',bridge_status=error.code)
   raise RuntimeError('感知桥上报结果未知')from None
  if not isinstance(value,dict)or value.get('ok')is not True:raise RuntimeError('感知桥未确认上报')
  client.invalidate()
  return dict(state='accepted',bridge_status=200,duplicate=value.get('duplicate')is True,
    accepted_sections=[v for v in value.get('accepted_sections',[])if v in FIELDS])

 async def report(self,username,session,body):
  if set(body)!={'installation_id','event_id','frame'}:raise ChatExpressionError('上报字段无效')
  install=installation(body['installation_id']);event=installation(body['event_id'])
  before=await asyncio.to_thread(self.snapshot,username,session,install)
  if not before['enabled']:raise PermissionError('请先在APP明确启用当前设备感知')
  payload=frame(body['frame'],before['sections'],now=self.clock())
  link,permission,phone,devices=self._access(username,session)
  link_id=link['link_id'];scope=ChatExpressions.message_scope(username,session)
  def current():
   try:
    after=self.snapshot(username,session,install)
    return (self.links.current() and self._phone()is phone and self.links.get(username,session)['link_id']==link_id
      and after['enabled'] and after['revision']==before['revision'] and after['device_id']==before['device_id'])
   except (AttributeError,KeyError,RuntimeError,ChatExpressionError):return False
  status_key='status:'+install
  signature=hashlib.sha256(canonical(payload).encode()).hexdigest()
  def reserve():
   with self.journal._lock:
    if not current():raise PermissionError('感知授权已经变化')
    prior=self.journal.fetch(NAMESPACE,status_key,scope)
    if prior and prior['data']['event_id']==event:
     if prior['data']['frame_digest']!=signature:raise ChatExpressionError('同一上报编号内容不同')
     return prior['data'],False
    if prior and self.clock()-prior['data']['started_at']<10:raise ChatExpressionError('上报太频繁，请稍后再试')
    value=dict(event_id=event,frame_digest=signature,started_at=self.clock(),state='unknown',
      device_id=before['device_id'],config_revision=before['revision'],link_id=link_id)
    self.journal.put(NAMESPACE,status_key,scope,value,expected_revision=prior['revision']if prior else 0,authorize=current)
    return value,True
  state,new=await asyncio.to_thread(reserve)
  if not new:return dict(state=state['state'],duplicate=True,report_id=event)
  key='chat-'+hashlib.sha256(canonical([scope,install,event]).encode()).hexdigest()
  try:result=await asyncio.to_thread(self.forward,phone,before['device_id'],key,payload,current)
  except PermissionError:raise
  except Exception:return dict(state='unknown',report_id=event,retry=False)
  def finish():
   with self.journal._lock:
    prior=self.journal.fetch(NAMESPACE,status_key,scope)
    if prior and prior['data']['event_id']==event:
     self.journal.put(NAMESPACE,status_key,scope,dict(state,**result,completed_at=self.clock()),
       expected_revision=prior['revision'],authorize=current)
  await asyncio.to_thread(finish)
  return dict(result,report_id=event,received_at=self.clock(),retry=False)
