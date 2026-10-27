"""Authenticated explicit fictional-scene and interaction-preference editing.

Only NarrativeStore's current scene and interaction_mode are writable. Existing
participant knowledge and timeline are retained; no persona, observed memory,
legacy PC data, model, timer or sender is accessed. Normal authenticated
administration maintains exact-scope durable materials using an operation-local
store. Automatic context readers retain their independent genuine-chat scope
authority. Disk work runs off the AstrBot event loop.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.journal import JournalConflict, LivingJournal
from .core.living.models import canonical
from .core.living.narrative import NarrativeStore
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope

PAGE_API_PREFIX = '/astrbot_plugin_virtual_body/page/narrative'
SOURCE = 'webui.narrative'
MODES = frozenset({'normal','deep','rp','continue_plot','share','playful','quiet'})
BOUNDARY = ('此处只管理明确的虚构剧情和显式互动偏好。剧情标为角色扮演，不能当作真实经历；'
            '不会改写核心人格、写入事实记忆、发送消息或调用模型，也不迁移旧 PC 历史。')


class _Unavailable(RuntimeError): pass


def _revision(value,minimum=0):
    if type(value) is not int or not minimum<=value<=2147483647:
        raise _InvalidRequest('必须提供有效的 expected_revision；新建用 0，编辑用当前版本')
    return value


def _text(value,label,maximum,*,blank=False,multiline=False):
    if (not isinstance(value,str) or len(value)>maximum or not blank and not value.strip()
            or any(ord(c)<32 and (not multiline or c not in '\n\r\t') for c in value)):
        raise _InvalidRequest(f'{label} 必须是长度不超过 {maximum} 的有效文本')
    return value


def _now(store):
    value=store.clock()
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=253402300799:
        raise _Unavailable('narrative clock unavailable')
    return float(value)


def _expiry(value,now):
    try:
        if not isinstance(value,str) or len(value)>64:raise ValueError
        parsed=datetime.fromisoformat(value[:-1]+'+00:00' if value.endswith('Z') else value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError
        epoch=parsed.timestamp()
        if not math.isfinite(epoch) or not now<epoch<=now+31*86400:raise ValueError
        return epoch
    except (ValueError,TypeError,OverflowError,OSError):
        raise _InvalidRequest('expires_at 必须是带时区的 ISO 时间，且在未来 31 天内') from None


def _user_participant(scope):
    identity='user.'+hashlib.sha256(canonical(scope).encode()).hexdigest()
    if identity==scope['character_id']:
        raise _InvalidRequest('剧情参与者标识冲突')
    return identity


class NativeNarrativeWebApi:
    def __init__(self,plugin):self.plugin=plugin

    def register_routes(self):
        for name in ('state','scene/save','scene/status','preference/save'):
            self.plugin.context.register_web_api(PAGE_API_PREFIX+'/'+name,
                getattr(self,'narrative_'+name.replace('/','_')),['GET' if name=='state' else 'POST'],
                'TLS authenticated explicit fictional narrative '+name)

    def _resources(self):
        presence=getattr(self.plugin,'_presence',None)
        host=getattr(presence,'living_host',None)
        runtime=getattr(host,'runtime',None)
        unified=getattr(runtime,'unified',None)
        store=getattr(unified,'narrative',None)
        journal=getattr(host,'journal',None)
        if (getattr(self.plugin,'_stopping',False) or getattr(host,'_closed',True)
                or getattr(runtime,'active',False) is not True or getattr(unified,'active',False) is not True
                or getattr(unified,'runtime',None) is not runtime
                or not callable(getattr(unified,'scope_allowed',None)) or not isinstance(store,NarrativeStore)
                or not isinstance(journal,LivingJournal) or getattr(journal,'_closed',True)
                or getattr(runtime,'journal',None) is not journal or store.journal is not journal):
            raise _Unavailable('native narrative not attached')
        return presence,host,runtime,unified,store,journal

    def _check(self,resources,scope):
        if any(old is not new for old,new in zip(resources,self._resources())):
            raise _Unavailable('native narrative replaced')

    def _local(self,resources,scope,enabled):
        def authorize(operation,candidate):
            if (not enabled[0] or candidate!=scope
                    or operation not in {'read','write','preferences.write'}):return False
            self._check(resources,candidate)
            return True
        # Never change the runtime store's authorize callback or add a Presence
        # lease. Journal.put repeats this local check before and after SQL while
        # its existing transaction is still able to roll back.
        return NarrativeStore(resources[-1],authorize=authorize,clock=resources[-2].clock)

    @staticmethod
    def _parse(name,data):
        if not isinstance(data,dict):raise _InvalidRequest('需要 JSON 对象')
        if name=='state':
            if set(data)-set(SCOPE_FIELDS)-{'private'}:raise _InvalidRequest('查询只接受五项完整 scope')
            if isinstance(data.get('private'),str) and data['private'] in {'true','false'}:
                data={**data,'private':data['private']=='true'}
            return _scope(data),{}
        fields={'scene/save':{'scope','expected_revision','title','summary','unfinished_arcs','expires_at'},
                'scene/status':{'scope','expected_revision','status'},
                'preference/save':{'scope','expected_revision','interaction_mode'}}[name]
        if set(data)!=fields:raise _InvalidRequest('请提供全部指定字段；不能改写参与者、时间线、人格或其他场景')
        scope=_scope(data['scope']);values={key:value for key,value in data.items() if key!='scope'}
        _revision(values['expected_revision'],1 if name=='scene/status' else 0)
        if name=='scene/save':
            _text(values['title'],'title',120)
            _text(values['summary'],'summary',1600,blank=True,multiline=True)
            arcs=values['unfinished_arcs']
            if not isinstance(arcs,list) or len(arcs)>16:raise _InvalidRequest('unfinished_arcs 最多 16 项简短文本')
            for text in arcs:_text(text,'unfinished_arcs',240)
        elif name=='scene/status':
            if not isinstance(values['status'],str) or values['status'] not in {'paused','closed','active'}:
                raise _InvalidRequest('status 只能是 paused、closed 或 active')
        else:
            if not isinstance(values['interaction_mode'],str) or values['interaction_mode'] not in MODES:
                raise _InvalidRequest('interaction_mode 必须是受支持的明确互动偏好')
        return scope,values

    @staticmethod
    def _state(store,scope):
        record=store.read_scene(scope,'current',include_expired=True)
        preference=store.get_preference(scope,'interaction_mode')
        scene=None
        if record is not None:
            scene=deepcopy(record['data']['payload'])
            scene.update(revision=record['revision'],evidence_kind=record['data']['evidence_kind'],
                         updated_at=record['data']['updated_at'],expired=scene['expires_at']<=_now(store),
                         expires_at_iso=datetime.fromtimestamp(scene['expires_at'],timezone.utc).isoformat())
        mode=preference['data']['payload']['value'] if preference else 'normal'
        return dict(scene_id='current',scene=scene,interaction_mode=mode,
            preference_revision=preference['revision'] if preference else 0,
            preference_supported=mode in MODES,preference_evidence_kind='user_reported',
            scene_usable=bool(scene and scene['status']=='active' and not scene['expired']))

    @staticmethod
    def _save_scene(store,scope,values):
        revision=values['expected_revision']
        record=store.read_scene(scope,'current',include_expired=True)
        if (record['revision'] if record else 0)!=revision:raise JournalConflict('scene revision conflict')
        actor=scope['character_id'];user=_user_participant(scope)
        if record:
            scene=deepcopy(record['data']['payload'])
            participants=scene['participants']
            if not any(item['participant_id']==user for item in participants):
                if len(participants)>=12:raise _InvalidRequest('已有参与者已满；本页不会删除或覆盖其知识')
                participants.append(dict(participant_id=user,display_name='用户（剧情参与者）',known_facts=[]))
        else:
            scene=dict(scene_id='current',participants=[
                dict(participant_id=actor,display_name='角色（当前角色）',known_facts=[]),
                dict(participant_id=user,display_name='用户（剧情参与者）',known_facts=[])],
                timeline=[],unfinished_arcs=[],status='active')
        # Unchanged arcs keep their existing knowledge boundary and identity.
        previous=defaultdict(deque)
        for arc in scene['unfinished_arcs']:previous[arc['text']].append(arc)
        used_ids={arc['arc_id'] for arc in scene['unfinished_arcs']};arcs=[]
        for index,text in enumerate(values['unfinished_arcs']):
            if previous[text]:arcs.append(previous[text].popleft());continue
            nonce=0
            while True:
                arc_id='webui.arc.'+hashlib.sha256(canonical([scope,text,index,nonce]).encode()).hexdigest()[:32]
                if arc_id not in used_ids:break
                nonce+=1
            used_ids.add(arc_id)
            arcs.append(dict(arc_id=arc_id,text=text,known_to=[actor,user]))
        scene.update(source_id=SOURCE,title=values['title'],summary=values['summary'],unfinished_arcs=arcs,
                     expires_at=_expiry(values['expires_at'],_now(store)))
        return store.put_scene(scope,scene,expected_revision=revision)

    @staticmethod
    def _set_status(store,scope,values):
        record=store.read_scene(scope,'current',include_expired=True)
        if record is None:raise KeyError('scene missing')
        if record['revision']!=values['expected_revision']:raise JournalConflict('scene revision conflict')
        scene=deepcopy(record['data']['payload'])
        if scene['expires_at']<=_now(store):
            raise _InvalidRequest('场景已过期，不能通过状态切换复活；请先编辑场景并延长有效期')
        scene.update(source_id=SOURCE,status=values['status'])
        return store.put_scene(scope,scene,expected_revision=values['expected_revision'])

    async def _respond(self,name):
        try:username=getattr(request,'username',None)
        except RuntimeError:username=None
        if not isinstance(username,str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证',status_code=401)
        enabled=[True]
        try:
            resources=self._resources()
            data=dict(getattr(request,'query',None) or {}) if name=='state' else await request.json(default=None)
            scope,values=self._parse(name,data)
            self._check(resources,scope)
            store=self._local(resources,scope,enabled)
            def operate():
                store._allowed('read',scope)
                record=None
                if name=='scene/save':record=self._save_scene(store,scope,values)
                elif name=='scene/status':record=self._set_status(store,scope,values)
                elif name=='preference/save':
                    record=store.set_preference(scope,'interaction_mode',values['interaction_mode'],
                        source_id=SOURCE,expected_revision=values['expected_revision'])
                result=self._state(store,scope)
                store._allowed('read',scope)
                if record:result['written_revision']=record['revision']
                return result
            result=await asyncio.to_thread(operate)
            self._check(resources,scope)
            return json_response(dict(ok=True,backend='native',access='authenticated_administrator',scope=scope,
                authority='historical_administrator_materials',runtime_authority_granted=False,creates_private_session=False,
                boundary=BOUNDARY,scene_evidence_kind='roleplay_event',changes_core_persona=False,
                writes_real_world_memory=False,llm_calls=0,external_operations=0,**result),
                headers={'Cache-Control':'no-store'})
        except _InvalidRequest as error:
            return error_response(str(error),status_code=400)
        except JournalConflict:
            return error_response('剧情或偏好版本已改变，请刷新后再编辑',status_code=409)
        except PermissionError:
            return error_response('本次完整范围的剧情维护许可已撤销，请保留草稿并重新读取',status_code=403)
        except KeyError:
            return error_response('当前完整会话中还没有 current 场景',status_code=404)
        except ValueError:
            return error_response('剧情参数或存储记录无效，请检查范围、版本和有效期',status_code=400)
        except (RuntimeError,sqlite3.Error,OSError):
            return error_response('原生剧情暂不可用或正在重载',status_code=503)
        except Exception:
            return error_response('剧情操作失败，请稍后重试',status_code=500)
        finally:enabled[0]=False

    async def narrative_state(self):return await self._respond('state')
    async def narrative_scene_save(self):return await self._respond('scene/save')
    async def narrative_scene_status(self):return await self._respond('scene/status')
    async def narrative_preference_save(self):return await self._respond('preference/save')
