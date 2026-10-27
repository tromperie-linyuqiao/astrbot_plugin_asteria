"""Native phone projection and message configuration administration.

Reads existing Presence snapshots, without refreshing collectors or importing
the old phone plugin. Only the listed message/music/cooldown settings persist.
Saving uses the console's shared lock, CAS and an actual SDK config-file reread.
No endpoint, token, device binding, sender ownership or activation is writable.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time

from astrbot.api.web import error_response, json_response, request

from .core.living.native_phone_messages import NativePhoneMessages
from .core.living.native_phone_companion import NativePhoneCompanion
from .core.living.native_phone_candidates import compile_rules
from .core.living.native_phone_status import NativePhoneStatus
from .core.living.models import plain
from .core.presence import PresenceLayer
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope


PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/phone'
DEFAULTS = {'living_phone_custom_lines':[], 'living_phone_app_cooldown_minutes':120,
            'living_phone_shared_cooldown_minutes':10,
            'living_phone_music_notifications_enabled':False, 'living_phone_music_cooldown_minutes':45}
LIMITS = {'living_phone_app_cooldown_minutes':(10,1440),'living_phone_shared_cooldown_minutes':(1,1440),
          'living_phone_music_cooldown_minutes':(10,1440)}
FIELDS = {
    'device.battery':('level','charging','charging_type','temperature_c','health','cycle_count'),
    'device.screen':('on','locked'), 'device.network':('type','roaming','metered'),
    'device.app':('foreground_package','foreground_label','foreground_since_epoch','foreground_minutes','swipe_events_per_min'),
    'device.audio':('headphones','ringer_mode'), 'device.device':('name','platform','os_version','battery_temp_c','power_save'),
    'user_activity':('steps_today','device_idle','last_unlock_epoch'), 'device.status':('online','stale'),
}
BOUNDARY = '采集沿用现有PPB来源，消息库与节奏由TLS原生服务维护。保存不会立即发送；开启音乐变化陪伴提示后，仅真实曲目变化且已确认绑定、授权和节奏允许时进入现有Chat队列，仍遵守安静时段，不改变QQ归属。'


class _Conflict(RuntimeError): pass
class _Unavailable(RuntimeError): pass


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate(values,library_config=None,*,budget=True):
    if type(values['living_phone_music_notifications_enabled']) is not bool:
        raise _InvalidRequest('音乐变化陪伴提示必须为明确的开启或关闭')
    for key,(low,high) in LIMITS.items():
        value = values[key]
        if type(value) is not int or not low<=value<=high:
            raise _InvalidRequest(f'{key} 必须是 {low}–{high} 的整数分钟数')
    lines = values['living_phone_custom_lines']
    if not isinstance(lines,list) or len(lines)>128 or any(not isinstance(line,str) for line in lines):
        raise _InvalidRequest('自定义消息必须为最多 128 项的文本列表')
    if len(json.dumps(lines,ensure_ascii=False).encode())>128*1024:
        raise _InvalidRequest('自定义消息库总文本不能超过 128 KiB')
    config=deepcopy(library_config) if library_config is not None else {}
    config['custom_lines']=lines
    library=NativePhoneMessages(**config)
    if budget:
        pools={}
        for row in library.list():pools.setdefault(row['package'],[]).append(row['text'])
        try:
            plain(pools,65536)
            plain([pools,[],None,None],65536)
            compile_rules(pools)
        except ValueError:
            raise _InvalidRequest('完整有效消息库超出 64 KiB 原生候选规则预算，请减少文案后保存') from None
    return values


def scalar(value):
    if type(value) is bool: return value
    if type(value) in (int,float) and math.isfinite(value): return value
    if isinstance(value,str):
        # Projection metadata is deliberately bounded; transport URLs or tokens
        # must never escape even if a provider put them in a display field.
        value = re.sub(r'https?://\S+','[地址已隐藏]',value[:512],flags=re.I)
        value = re.sub(r'(?i)(?:bearer\s+|token\s*[:=]\s*)[A-Za-z0-9._~+/=-]+','[凭据已隐藏]',value)
        return ' '.join(value.split())[:256]
    return None


def projection(domain,row):
    expected = 'phone.music' if domain=='music' else 'phone.device'
    if not isinstance(row,dict) or row.get('source') not in (None,expected): row = {}
    status = row.get('status','unknown')
    if status not in {'fresh','stale','unknown','disabled','unavailable','conflict'}: status='unknown'
    raw = row.get('value'); value = None
    if isinstance(raw,dict) and row.get('source')==expected:
        if domain=='music':
            value = {key:scalar(raw[key]) for key in ('event_type','playing','state') if key in raw}
            for section,keys in (('song_info',('title','artist','album')),('user_state',('state','playing','reliable','progress_ms','duration_ms','age_seconds','source','package'))):
                nested = raw.get(section)
                if isinstance(nested,dict): value[section]={key:scalar(nested[key]) for key in keys if key in nested}
        else: value={key:scalar(raw[key]) for key in FIELDS[domain] if key in raw}
        if not value:value=None
    meta = row.get('meta') if isinstance(row.get('meta'),dict) else {}
    return {'source':row.get('source') if row.get('source')==expected else None,'status':status,'value':value,
            'meta':{key:scalar(meta[key]) for key in ('observed_at','received_at','expires_at','evidence_kind','device_id') if key in meta}}


class NativePhoneWebApi:
    def __init__(self,plugin):
        self.plugin=plugin
        lock=getattr(plugin,'_native_console_config_lock',None)
        if lock is None:lock=threading.RLock();plugin._native_console_config_lock=lock
        self.lock=lock

    def register_routes(self):
        for name in ('state','status','status/read','library','config','config/save'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,
                getattr(self,'phone_'+name.replace('/','_')),['POST' if name=='config/save' else 'GET'],
                'TLS native authenticated phone '+name)

    def _runtime_snapshot(self):
        """Copy event-loop-owned library state before handing work to a thread."""
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        companion=getattr(getattr(host,'runtime',None),'phone_companion',None)
        reader=getattr(self.plugin,'_cfg',None)
        enabled=(reader('living_phone_companion_enabled',False) if callable(reader)
                 else self.plugin.config.get('living_phone_companion_enabled',False)) is True
        attached=isinstance(companion,NativePhoneCompanion)
        component_active=attached and companion.active is True
        active=component_active and enabled and isinstance(companion.messages,NativePhoneMessages)
        details={}
        if attached:
            for key,value in companion.diagnostics().items():
                if type(value) is bool or type(value) in (int,float) and math.isfinite(value):details[key]=value
                elif key in {'last_reason','last_admission_reason','music_last_reason'} and isinstance(value,str) and re.fullmatch('[a-z0-9_.:-]{1,96}',value):details[key]=value
        return {'library_config':deepcopy(companion.messages.export()['config']) if active else None,
                'phone_companion':{'active':bool(active),'enabled':enabled,'component_active':bool(component_active),
                                   'diagnostics':details},
                'boundary':('TLS 原生 App 伴随组件已启用，消息库按当前运行配置展示；手机投影仍保留实际上报来源，'
                            '不代表采集所有权已切换。'+BOUNDARY) if active else BOUNDARY}

    def _values(self):
        reader=getattr(self.plugin,'_cfg',None)
        return {key:deepcopy(reader(key,default) if callable(reader) else self.plugin.config.get(key,default))
                for key,default in DEFAULTS.items()}

    def _config_path(self):
        value=getattr(getattr(self.plugin,'config',None),'config_path',None)
        if not isinstance(value,(str,Path)) or not str(value):raise _Unavailable('SDK configuration path unavailable')
        return Path(value)

    def _persisted_document(self):
        path=self._config_path()
        if path.stat().st_size>8*1024*1024:raise _Unavailable('configuration capacity')
        encoded=path.read_bytes();raw=json.loads(encoded.decode('utf-8-sig'))
        if not isinstance(raw,dict):raise _Unavailable('configuration format')
        return raw,hashlib.sha256(encoded).hexdigest()

    def _snapshot(self):
        values=self._values();validate(values,budget=False)
        writable=callable(getattr(self.plugin.config,'save_config',None))
        file_digest=None;synchronized=False
        try:
            document,file_digest=self._persisted_document()
            persisted={key:document.get(key,default) for key,default in DEFAULTS.items()}==values
            # The SDK saver writes the whole plugin configuration. Refuse an
            # out-of-band file edit rather than overwrite unrelated settings.
            synchronized=persisted and all(key in self.plugin.config and self.plugin.config[key]==value
                for key,value in document.items() if key not in DEFAULTS)
        except (OSError,ValueError,RuntimeError):persisted=False
        try:self._config_path()
        except _Unavailable:writable=False
        return {'values':values,'revision':digest({'values':values,'file_sha256':file_digest}),
                'writable':writable,'persisted_verified':persisted,'config_synchronized':synchronized,'boundary':BOUNDARY}

    def _save(self,body,library_config=None):
        if set(body)!={'expected_revision','changes'}:raise _InvalidRequest('需要配置版本和列出的修改字段')
        changes=body['changes'];revision=body['expected_revision']
        if not isinstance(changes,dict) or not changes or set(changes)-set(DEFAULTS):
            raise _InvalidRequest('只能修改消息库、音乐变化提示和列出的冷却时间')
        if not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{64}',revision):raise _InvalidRequest('需要载入时的配置版本')
        with self.lock:
            current=self._snapshot()
            if current['revision']!=revision:raise _Conflict('phone configuration changed')
            if not current['config_synchronized']:raise _Conflict('persistent plugin configuration changed outside live owner')
            validate(dict(current['values'],**changes),library_config)
            config=self.plugin.config;saver=getattr(config,'save_config',None)
            if not current['writable'] or not callable(saver):raise _Unavailable('configuration persistence unavailable')
            old={key:(key in config,deepcopy(config.get(key))) for key in changes}
            try:config.update(deepcopy(changes));saver()
            except BaseException:
                for key,(existed,value) in old.items():
                    if existed:config[key]=value
                    else:config.pop(key,None)
                raise
            result=self._snapshot()
            if not result['persisted_verified']:
                # The saver may already have committed. Report an uncertain
                # save without blindly overwriting another writer or retrying.
                raise _Unavailable('configuration reread did not confirm save')
            return result

    def _state(self,query):
        if set(query)-set(SCOPE_FIELDS):raise _InvalidRequest('手机状态查询只接受完整会话身份')
        scope=_scope(dict(query))
        presence=getattr(getattr(self.plugin,'_presence',None),'api',None)
        if not isinstance(presence,PresenceLayer):raise _Unavailable('Presence unavailable')
        # This is an in-memory synchronous read on its owning event loop. Never
        # refresh a collector or touch transport credentials from this route.
        snapshot=presence.read(scope,now=time.time());rows=snapshot.get('states',{})
        return {'scope':scope,'generated_at':snapshot.get('generated_at'),'revision':snapshot.get('revision'),
                'states':{domain:projection(domain,rows.get(domain)) for domain in (*FIELDS,'music')},'boundary':BOUNDARY,
                'unified_status':NativePhoneStatus(self.plugin).read(scope)}

    async def _status(self,query,*,refresh=False):
        if set(query)-set(SCOPE_FIELDS)-{'device_id'}:raise _InvalidRequest('手机来源状态只接受完整会话与已分配设备')
        scope=_scope({key:query[key] for key in SCOPE_FIELDS if key in query})
        device=query.get('device_id')
        if device is not None and (not isinstance(device,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,64}',device)):
            raise _InvalidRequest('设备标识无效')
        reader=NativePhoneStatus(self.plugin)
        status=await reader.refresh(scope,device_id=device) if refresh else reader.read(scope,device_id=device)
        return {'scope':scope,'unified_status':status}

    def _library(self,query,library_config=None):
        if set(query)-{'package'}:raise _InvalidRequest('消息库查询仅接受 App 包名')
        package=query.get('package')
        with self.lock:
            values=self._values();validate(values,budget=False)
        config=deepcopy(library_config) if library_config is not None else {}
        config['custom_lines']=values['living_phone_custom_lines']
        library=NativePhoneMessages(**config)
        rows=library.list(package=package)
        return {'records':[{key:row[key] for key in ('id','package','text','kind','source','tags','hours','enabled')} for row in rows],
                'summary':library.describe(),'boundary':BOUNDARY,'sends':0,'llm_calls':0,
                'library_source':'runtime_native_phone_companion' if library_config is not None else 'configured_native_preview'}

    async def _respond(self,action):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            runtime_snapshot=self._runtime_snapshot()
            if action=='config/save':
                body=await request.json(default=None)
                if not isinstance(body,dict):raise _InvalidRequest('请求正文必须是 JSON 对象')
                result=await asyncio.to_thread(self._save,body,runtime_snapshot['library_config'])
                runtime_snapshot=self._runtime_snapshot()
            else:
                query=dict(getattr(request,'query',None) or {})
                if action=='state':result=self._state(query)
                elif action in {'status','status/read'}:result=await self._status(query,refresh=action=='status/read')
                elif action=='library':result=await asyncio.to_thread(self._library,query,runtime_snapshot['library_config'])
                else:
                    if query:raise _InvalidRequest('消息库配置不接受查询参数')
                    def read():
                        with self.lock:return self._snapshot()
                    result=await asyncio.to_thread(read)
            result.update(boundary=runtime_snapshot['boundary'],phone_companion=runtime_snapshot['phone_companion'])
            return json_response({'ok':True,'backend':'native','access':'authenticated_administrator',**result},headers={'Cache-Control':'no-store'})
        except _InvalidRequest as exc:return error_response(str(exc),status_code=400)
        except _Conflict:return error_response('手机消息配置已改变，请重新载入后保存',status_code=409)
        except (ValueError,TypeError):return error_response('手机状态或消息库参数无效，请检查包名、文案与分钟数',status_code=400)
        except (RuntimeError,OSError):return error_response('手机投影或配置存储暂不可用，保存结果请重新读取确认',status_code=503)
        except Exception:return error_response('手机管理操作失败，请稍后重试',status_code=500)

    async def phone_state(self):return await self._respond('state')
    async def phone_status(self):return await self._respond('status')
    async def phone_status_read(self):return await self._respond('status/read')
    async def phone_library(self):return await self._respond('library')
    async def phone_config(self):return await self._respond('config')
    async def phone_config_save(self):return await self._respond('config/save')
