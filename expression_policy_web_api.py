"""Administrator configuration and read-only previews for ordinary reply assets."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading

from astrbot.api.web import error_response, json_response, request

from .core.living.native_expression_assets import ExpressionAssetConflict, ExpressionAssetError, NativeExpressionAssets
from .core.living.native_expression_reply import (
    NativeExpressionReplyAdapter, NativeExpressionReplyPolicy, SETTINGS_DEFAULTS, validate_settings,
)
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope, _text

PAGE_API_PREFIX='/astrbot_plugin_virtual_body/page/expression-policy'
BOUNDARY=('这里只配置普通私聊纯文本模型回复内附加最多一张人工素材；走同一普通回复钩子的 RP 文本共用此策略，'
    '没有独立 RP 配额。主动消息仍采用已有图像服务策略，功能通知保持其原有实现，均不受此页控制。'
    '停用回复表情不影响素材管理；预览不发送、不调用模型、不占频率，不能代替真实事件的最终准入和平台送达确认。')
SUPPORT={'ordinary_private_reply':True,'rp_uses_same_plain_reply_lane':True,
    'independent_rp_policy':False,'proactive_policy':False,'functional_notification_policy':False}


class _Unavailable(RuntimeError):pass
class _Conflict(RuntimeError):pass


def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


class NativeExpressionPolicyWebApi:
    def __init__(self,plugin):
        self.plugin=plugin
        lock=getattr(plugin,'_native_console_config_lock',None)
        if lock is None:lock=threading.RLock();plugin._native_console_config_lock=lock
        self.lock=lock

    def register_routes(self):
        for name in ('config','config/save','preview'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,
                getattr(self,'expression_policy_'+name.replace('/','_')),['GET' if name=='config' else 'POST'],
                'TLS authenticated ordinary reply expression policy '+name)

    def _values(self):
        reader=getattr(self.plugin,'_cfg',None)
        values={key:deepcopy(reader(key,default) if callable(reader) else self.plugin.config.get(key,default))
            for key,default in SETTINGS_DEFAULTS.items()}
        return validate_settings(values)

    def _config_path(self):
        value=getattr(getattr(self.plugin,'config',None),'config_path',None)
        if not isinstance(value,(str,Path)) or not str(value):raise _Unavailable('SDK config path unavailable')
        return Path(value)

    def _persisted(self):
        path=self._config_path()
        if path.stat().st_size>8*1024*1024:raise _Unavailable('SDK config capacity')
        raw=path.read_bytes();document=json.loads(raw.decode('utf-8-sig'))
        if not isinstance(document,dict):raise _Unavailable('SDK config format')
        return document,hashlib.sha256(raw).hexdigest()

    def _snapshot(self):
        values=self._values();file_digest=None;synchronized=False
        writable=callable(getattr(self.plugin.config,'save_config',None))
        try:
            document,file_digest=self._persisted()
            persisted={key:document.get(key,default) for key,default in SETTINGS_DEFAULTS.items()}==values
            synchronized=persisted and all(key in self.plugin.config and self.plugin.config[key]==value
                for key,value in document.items() if key not in SETTINGS_DEFAULTS)
        except (OSError,ValueError,RuntimeError):persisted=False
        try:self._config_path()
        except _Unavailable:writable=False
        policy=self._policy()
        return {'values':values,'revision':_digest({'values':values,'file_sha256':file_digest}),
            'writable':writable,'persisted_verified':persisted,'config_synchronized':synchronized,
            'runtime_attached':policy is not None and policy.active,
            'hot_apply_available':policy is not None and policy.active and callable(policy.settings)}

    def _save(self,body):
        if set(body)!={'changes','expected_revision'}:raise _InvalidRequest('需要 changes 和 expected_revision')
        changes=body['changes'];revision=body['expected_revision']
        if not isinstance(changes,dict) or not changes or set(changes)-set(SETTINGS_DEFAULTS):
            raise _InvalidRequest('只能修改普通回复表情启停、每日上限和间隔')
        if not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{64}',revision):
            raise _InvalidRequest('需要载入配置时的版本')
        with self.lock:
            current=self._snapshot()
            if current['revision']!=revision:raise _Conflict('expression policy revision changed')
            if not current['config_synchronized']:raise _Conflict('SDK file changed outside current live config')
            validate_settings(dict(current['values'],**changes))
            config=self.plugin.config;saver=getattr(config,'save_config',None)
            if not current['writable'] or not callable(saver):raise _Unavailable('SDK config persistence unavailable')
            previous={key:(key in config,deepcopy(config.get(key))) for key in changes}
            try:config.update(deepcopy(changes));saver()
            except BaseException:
                for key,(existed,value) in previous.items():
                    if existed:config[key]=value
                    else:config.pop(key,None)
                raise
            result=self._snapshot()
            if not result['persisted_verified'] or not result['config_synchronized']:
                # The SDK may have committed. Preserve evidence by not blindly
                # writing old bytes or retrying a save whose result is unknown.
                raise _Unavailable('SDK file reread did not confirm save')
            return result

    def _runtime(self):
        host=getattr(getattr(self.plugin,'_presence',None),'living_host',None)
        return getattr(host,'runtime',None)

    def _assets(self):
        service=getattr(self._runtime(),'expression_assets',None)
        if not isinstance(service,NativeExpressionAssets) or not service.active:
            raise _Unavailable('native expression assets unavailable')
        return service

    def _policy(self):
        adapter=getattr(self._runtime(),'expression_reply',None)
        policy=getattr(adapter,'policy',None)
        return policy if isinstance(adapter,NativeExpressionReplyAdapter) and isinstance(policy,NativeExpressionReplyPolicy) else None

    def _check(self,service,policy,scope):
        if self._assets() is not service or self._policy() is not policy:
            raise _Unavailable('expression services replaced')
        if service.authorize(dict(scope)) is not True:raise PermissionError('expression asset scope unavailable')

    def _preview(self,body,service,policy):
        if set(body)!={'scope','text'}:raise _InvalidRequest('预览只接受完整 scope 和示例回复 text')
        scope=_scope(body['scope']);text=_text(body['text'],'示例回复',2000)
        self._check(service,policy,scope)
        selected=service.select(scope,text,limit=1);asset=None
        if selected['state']=='selected':
            row=selected['assets'][0]
            service.read_bytes(scope,row['id'],expected_revision=row['revision'])
            current=service.get(scope,row['id'])
            if current is None:raise KeyError('preview asset removed')
            if current['revision']!=row['revision'] or not current['enabled']:
                raise ExpressionAssetConflict('preview asset changed')
            asset={'id':row['id'],'revision':row['revision'],'caption':row['caption'],'tags':list(row['tags']),
                'media':{key:row[key] for key in ('media_type','format','width','height','frames','byte_size')},
                'preview_request':{'method':'GET','path':'page/assets/preview',
                    'query':{**{key:scope[key] for key in SCOPE_FIELDS},'id':row['id'],'expected_revision':row['revision']}},
                'match_explanation':'按用户人工标签、人工说明进行确定性文字匹配；未识别图片内容或推断情绪。'}
        frequency=(policy.preflight(scope) if policy is not None and policy.active else
            {'checked':False,'state':'preflight_unavailable','eligible':False,'reservation_written':False})
        self._check(service,policy,scope)
        bubbles=[{'type':'text','text':text}]
        if asset is not None and frequency.get('checked') and frequency.get('eligible'):
            bubbles.append({'type':'image','id':asset['id'],'revision':asset['revision'],
                'caption':asset['caption'],'media':asset['media'],'preview_request':asset['preview_request']})
        return {'scope':scope,'match_state':selected['state'],'asset':asset,'bubbles':bubbles,'frequency':frequency,
            'max_images':1,'hypothetical_plain_reply':True,'real_event_checks_complete':False,
            'remaining_checks':['private_sdk_event','command_or_proactive_filter','all_plain_result','message_dedup','final_owner_and_result'],
            'reservation_written':False,'delivery_confirmed':False}

    async def _respond(self,action):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        try:
            if action=='config':
                if dict(getattr(request,'query',None) or {}):raise _InvalidRequest('策略配置不接受查询参数')
                def read():
                    with self.lock:return self._snapshot()
                result=await asyncio.to_thread(read)
            else:
                body=await request.json(default=None)
                if not isinstance(body,dict):raise _InvalidRequest('请求正文必须是 JSON 对象')
                if action=='config/save':result=await asyncio.to_thread(self._save,body)
                else:
                    service,policy=self._assets(),self._policy()
                    result=await asyncio.to_thread(self._preview,body,service,policy)
                    self._check(service,policy,result['scope'])
            return json_response({'ok':True,'backend':'native_expression_reply','access':'authenticated_administrator',
                'boundary':BOUNDARY,'support':SUPPORT,'llm_calls':0,'sends':0,**result},headers={'Cache-Control':'no-store'})
        except _InvalidRequest as error:return error_response(str(error),status_code=400)
        except (_Conflict,ExpressionAssetConflict):return error_response('策略配置或素材版本已改变，请刷新后重试',status_code=409)
        except PermissionError:return error_response('该完整私聊范围未获原生素材授权，请先在目标私聊发话',status_code=403)
        except KeyError:return error_response('匹配素材已不在当前范围中',status_code=404)
        except (ValueError,TypeError):return error_response('请检查策略范围、上限、间隔和预览文字',status_code=400)
        except (ExpressionAssetError,RuntimeError,sqlite3.Error,OSError):return error_response('策略或素材存储暂不可用，请重新读取确认保存结果',status_code=503)
        except Exception:return error_response('表情策略操作失败，请稍后重试',status_code=500)

    async def expression_policy_config(self):return await self._respond('config')
    async def expression_policy_config_save(self):return await self._respond('config/save')
    async def expression_policy_preview(self):return await self._respond('preview')
