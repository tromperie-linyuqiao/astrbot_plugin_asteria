"""AstrBot-authenticated maintenance of the shared fictional-life ledger."""
from __future__ import annotations

import asyncio
import json
import sqlite3

from astrbot.api.web import error_response, json_response, request

from .core.living.autonomous_life import AutonomousLife
from .core.living.personal_space import PersonalSpace
from .core.living.personal_resources import PersonalResources
from .core.living.journal import JournalConflict, LivingJournal
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _integer, _scope, _text

PREFIX = '/astrbot_plugin_virtual_body/page/autonomous-life'
MAX_BODY = 64 * 1024
PERSONAL_READS = ('personal/resources','personal/resource-sources','personal/review-list','personal/review-preview','personal/overview','personal/records','personal/record','personal/history','personal/decision')
PERSONAL_WRITES = ('personal/collect','personal/review-confirm','personal/create','personal/update','personal/archive','personal/restore','personal/delete')
READS = PERSONAL_READS + ('overview', 'events', 'event', 'characters', 'character', 'threads', 'thread', 'shares', 'history', 'settings', 'worldline', 'actions/status', 'event/impact')
WRITES = PERSONAL_WRITES + ('event/create', 'event/correct', 'event/archive', 'event/restore',
          'character/create', 'character/update', 'character/archive', 'character/restore',
          'thread/create', 'thread/update', 'thread/archive', 'thread/restore', 'settings/save', 'advance', 'actions/control')
KINDS = {'event': ('events', 'list_events'), 'character': ('characters', 'list_characters'),
         'thread': ('threads', 'list_threads')}


class NativeAutonomousLifeWebApi:
    def __init__(self, plugin):
        self.plugin = plugin

    def register_routes(self):
        for route in READS + WRITES:
            async def handle(route=route):
                return await self._respond(route)
            # Keep the factory closure tied to this API instance so canonical
            # and compatibility routes reuse the same authenticated handler.
            handle.__asteria_owner__ = self
            self.plugin.context.register_web_api(PREFIX + '/' + route, handle,
                ['GET' if route in READS else 'POST'], 'TLS authenticated fictional life ' + route)

    def _resources(self):
        host = getattr(getattr(self.plugin, '_presence', None), 'living_host', None)
        runtime = getattr(host, 'runtime', None)
        source = getattr(runtime, 'autonomous_life', None)
        journal = getattr(host, 'journal', None)
        if (getattr(self.plugin, '_stopping', False) or getattr(host, '_closed', True)
                or getattr(runtime, 'active', False) is not True
                or not isinstance(source, AutonomousLife) or source.active is not True or not isinstance(journal, LivingJournal)
                or source.journal is not journal or journal._closed):
            raise RuntimeError('autonomous life unavailable')
        return host, runtime, source, journal

    def _same(self, resources):
        if any(before is not after for before, after in zip(resources, self._resources())):
            raise RuntimeError('autonomous life changed')

    def _facade(self, resources, scope):
        _, _, source, journal = resources
        def authorize(candidate, operation):
            self._same(resources)
            # Material maintenance only; sharing still needs the real sender.
            return candidate == scope and operation in {'read', 'write'}
        facade = AutonomousLife(journal, authorize=authorize, clock=source.clock,
            timezone=source.timezone, verify_memory_ref=source.verify_memory_ref)
        def resource_authorize(target, origin):
            self._same(resources)
            return target == scope and _scope(origin) == origin
        PersonalResources(facade,authorize_source=resource_authorize,
            enumerate_sources=lambda target: resource_authorize(target,scope))
        return facade

    @staticmethod
    def _body(route, data):
        if type(data) is not dict or len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > MAX_BODY:
            raise _InvalidRequest('生活档案请求无效或过大')
        if route in READS:
            allowed = set(SCOPE_FIELDS) | {'private'}
            if route in PERSONAL_READS:
                allowed |= {'kind','id','query','include_archived','include_invalid','limit','offset','resource_type','source_scope','status','category','sort'}
            elif route in {'events', 'characters', 'threads'}:
                allowed |= {'query', 'include_archived', 'include_invalid', 'limit', 'offset'}
            elif route in KINDS: allowed |= {'id'}
            elif route == 'shares': allowed |= {'event_id', 'limit'}
            elif route in {'worldline','event/impact'}: allowed |= {'event_id'}
            elif route == 'history': allowed |= {'kind', 'id', 'limit','offset','expected_revision'}
            if route == 'personal/history': allowed.add('expected_revision')
            if set(data) - allowed: raise _InvalidRequest('生活档案查询含未知字段')
            raw = {key: data.get(key) for key in SCOPE_FIELDS}
            if 'private' in data: raw['private'] = data['private'] is True or data['private'] == 'true'
            scope = _scope(raw)
        else:
            scope = _scope(data.get('scope'))
        return scope

    @staticmethod
    def _revision(data):
        value = data.get('expected_revision')
        if type(value) is not int or not 0 <= value <= 2 ** 53 - 1:
            raise _InvalidRequest('请先读取当前资料修订号')
        return value

    @staticmethod
    def _exact(data, fields):
        if set(data) != set(fields) | {'scope'}:
            raise _InvalidRequest('请求字段不完整或含多余字段')

    @staticmethod
    def _capacity(service, scope):
        """Count only validated current entities in the requested admin scope.

        Buckets describe retention, not dependency validity or whether an item
        is still ongoing. History and other Journal namespaces are not exposed.
        """
        from .core.living.autonomous_life import _NS as life_ns, _LIMIT as life_limit
        from .core.living.personal_space import _NS as personal_ns, _LIMIT as personal_limit
        scope=service._scope(scope);personal=PersonalSpace(service)
        kinds=[];totals=dict(total=0,active=0,archived=0,deleted=0,limit=0,remaining=0)
        with service.journal._lock:
            for kind,limit in {**life_limit,**personal_limit}.items():
                namespace=(life_ns if kind in life_limit else personal_ns)[kind]
                rows=service.journal.list(namespace,scope,limit=limit+1)
                if len(rows)>limit:raise RuntimeError('life retention exceeds supported capacity')
                counts=dict(kind=kind,total=len(rows),active=0,archived=0,deleted=0,limit=limit,remaining=limit-len(rows))
                for row in rows:
                    checked=(service._checked_row(kind,scope,row['key'],row) if kind in life_limit else
                        personal._checked_row(scope,kind,row['key'],row))
                    value=checked['data']
                    bucket='deleted' if value.get('deleted') is True else 'archived' if value['archived'] else 'active'
                    counts[bucket]+=1
                kinds.append(counts)
                for key in totals:totals[key]+=counts[key]
            service._scope(scope)
            return dict(scope_only=True,read_only=True,as_of=service._now(),totals=totals,kinds=kinds,
                archive_releases_capacity=False,active_semantics='not_archived_not_deleted',remaining_guarantees_write=False)

    def _operate(self, service, route, scope, data, actor):
        if route=='actions/status':
            from .core.living.life_choices import LifeChoices
            return LifeChoices(service).snapshot(scope)
        if route=='actions/control':
            from .core.living.life_choices import LifeChoices
            required={'scope','action','request_id','expected_revision'}
            optional={'target_kind','target_id','expected_target_revision','minutes','reason'}
            if not required.issubset(data) or set(data)-required-optional:raise _InvalidRequest('请选择明确的行动与当前版本')
            return LifeChoices(service).control(scope,action=data['action'],request_id=data['request_id'],
                expected_revision=self._revision(data),actor=actor,**{key:data[key] for key in optional if key in data})
        if route=='event/impact':
            return service.correction_impact(scope,_text(data.get('event_id'),'经历ID',160))
        if route=='worldline':
            from .core.living.life_worldline import project
            return project(service,scope,_text(data.get('event_id'),'经历ID',160))
        if route.startswith('personal/'):
            personal = PersonalSpace(service)
            operation = route.split('/',1)[1]
            resources = service.personal_resources
            if operation == 'resource-sources':
                resource_type = _text(data.get('resource_type'),'资源类型',16)
                if resource_type not in {'music','image'}: raise _InvalidRequest('请选择音乐或图片')
                directory = resources.sources(scope)
                rows=[]
                for row in directory['records']:
                    count=row.get('counts',{}).get(resource_type,{}).get('total',0)
                    if not count: continue
                    origin=row['source_scope']
                    label=('当前生活范围' if origin==scope else origin['platform']+' · 用户…'+origin['user_id'][-4:]+' · 会话…'+origin['session_id'][-8:])
                    rows.append(dict(scope=origin,label=label,count=count,type=resource_type))
                return dict(sources=rows,metadata_only=True)
            if operation == 'resources':
                origin = scope if not data.get('source_scope') else _scope(json.loads(data['source_scope']))
                return resources.list_resources(scope,_text(data.get('resource_type'),'资源类型',16),
                    source_scope=origin,query=_text(data.get('query',''),'搜索词',200,blank=True),
                    limit=_integer(data.get('limit',20),'limit',1,100),offset=_integer(data.get('offset',0),'offset',0,1000))
            if operation == 'collect':
                required={'request_id','resource_type','resource_id','source_scope','expected_resource_revision'}
                optional={'name','description','interest_id'}
                if not required <= set(data) or set(data)-required-optional-{'scope'}:raise _InvalidRequest('收藏请求字段无效')
                return resources.collect(scope,_text(data['request_id'],'请求ID',96),
                    _text(data['resource_type'],'资源类型',16),_text(data['resource_id'],'资源ID',128),
                    _scope(data['source_scope']),self._revision(dict(expected_revision=data['expected_resource_revision'])),
                    **{key:data[key] for key in optional if key in data})
            if operation == 'review-list':
                return personal.list_review(scope,query=_text(data.get('query',''),'搜索词',200,blank=True),
                    limit=_integer(data.get('limit',30),'limit',1,100),offset=_integer(data.get('offset',0),'offset',0,1000))
            if operation == 'review-preview':
                return personal.review_preview(scope,_text(data.get('kind'),'类别',24),_text(data.get('id'),'资料ID',160))
            if operation == 'review-confirm':
                self._exact(data,{'kind','id','expected_revision','source_token','reason','changes','confirmed'})
                if data['confirmed'] is not True:raise _InvalidRequest('请明确确认已核对资料内容')
                return personal.confirm_review(scope,_text(data['kind'],'类别',24),_text(data['id'],'资料ID',160),
                    self._revision(data),_text(data['source_token'],'来源版本',64),_text(data['reason'],'维护原因',400),
                    changes=data['changes'],confirmed=True,actor=actor)
            if operation == 'overview': return personal.overview(scope)
            if operation == 'decision': return personal.decision(scope)
            kind = _text(data.get('kind'), '私人资料类别', 24)
            if operation == 'records':
                for name in ('include_archived','include_invalid'):
                    value=data.get(name,False)
                    if type(value) is not bool and (type(value) is not str or value not in ('true','false')):
                        raise _InvalidRequest('资料筛选开关无效')
                return personal.list_records(scope, kind, query=_text(data.get('query',''), '搜索词',200,blank=True),
                    include_archived=data.get('include_archived') in (True,'true'),
                    include_invalid=data.get('include_invalid') in (True,'true'),
                    limit=_integer(data.get('limit',30),'limit',1,100), offset=_integer(data.get('offset',0),'offset',0,1000),
                    status=data.get('status',''),category=data.get('category',''),sort=data.get('sort','updated'))
            if operation in {'record','history'}:
                identity = _text(data.get('id'), '资料ID',160)
                if operation == 'history': return personal.history(scope,kind,identity,
                    limit=_integer(data.get('limit',20),'limit',1,100),offset=_integer(data.get('offset',0),'offset',0,50000),
                    expected_revision=_integer(data['expected_revision'],'expected_revision',0,2**53-1) if 'expected_revision' in data else None)
                value = personal.get_record(scope,kind,identity)
                if value is None: raise KeyError(identity)
                return dict(self._personal_links(service, scope, value), archive_links=personal.archive_links(scope,value))
            fields = {'kind','request_id','fields'} if operation == 'create' else {'kind','id','expected_revision','reason'} | ({'changes'} if operation == 'update' else set())
            # Only the authenticated maintenance origin can be assigned here.
            supplied_source = data.get('source')
            if operation == 'create' and supplied_source is not None:
                if type(supplied_source) is not dict or set(supplied_source) != {'kind','ref'} or supplied_source.get('kind') != 'operator':
                    raise _InvalidRequest('手动资料只能记录管理员来源')
                data = dict(data); data.pop('source')
            self._exact(data, fields)
            if operation == 'create':
                request_id = _text(data.get('request_id'),'请求ID',96)
                return personal.create(scope,kind,request_id,data['fields'],source={'kind':'operator','ref':_text(supplied_source['ref'],'来源说明',256) if supplied_source is not None else request_id})
            identity = _text(data.get('id'),'资料ID',160)
            kwargs = dict(expected_revision=self._revision(data),reason=_text(data.get('reason'),'维护原因',400),actor=actor)
            if operation == 'update': return personal.update(scope,kind,identity,changes=data['changes'],**kwargs)
            if operation == 'delete': return personal.delete(scope,kind,identity,**kwargs)
            return personal.archive(scope,kind,identity,archived=operation=='archive',**kwargs)
        if route == 'overview':
            with service.journal._lock:
                return dict(service.overview(scope),capacity=self._capacity(service,scope))
        if route == 'settings': return service.settings(scope)
        if route in {'events', 'characters', 'threads'}:
            def flag(name):
                value = data.get(name, False)
                if type(value) is not bool and (type(value) is not str or value not in ('true', 'false')): raise _InvalidRequest('资料筛选开关无效')
                return value is True or value == 'true'
            return getattr(service, 'list_' + route)(scope,
                query=_text(data.get('query', ''), '搜索词', 200, blank=True),
                include_archived=flag('include_archived'), include_invalid=flag('include_invalid'),
                limit=_integer(data.get('limit', 30), 'limit', 1, 100),
                offset=_integer(data.get('offset', 0), 'offset', 0, 1000))
        if route in KINDS:
            result = getattr(service, 'get_' + route)(scope, _text(data.get('id'), '资料ID', 160))
            if result is None: raise KeyError('life record absent')
            return result
        if route == 'shares':
            return service.share_history_view(scope, event_id=data.get('event_id'), limit=_integer(data.get('limit', 30), 'limit', 1, 100))
        if route == 'history':
            kind = data.get('kind')
            if kind not in KINDS: raise _InvalidRequest('资料类型无效')
            return service.history(scope, kind, _text(data.get('id'), '资料ID', 160),
                limit=_integer(data.get('limit', 20), 'limit', 1, 100),offset=_integer(data.get('offset',0),'offset',0,50000),
                expected_revision=_integer(data['expected_revision'],'expected_revision',0,2**53-1) if 'expected_revision' in data else None)
        kind, operation = route.split('/')
        if operation == 'create':
            self._exact(data, {'request_id', 'fields'})
            identity = _text(data['request_id'], '请求ID', 128)
            return getattr(service, 'create_' + kind)(scope, identity, data['fields'],
                source={'kind': 'operator', 'ref': identity})
        self._exact(data, {'id', 'expected_revision', 'reason'} | ({'changes'} if operation in {'correct', 'update'} else set()))
        identity = _text(data['id'], '资料ID', 160)
        kwargs = dict(expected_revision=self._revision(data), reason=_text(data['reason'], '修正原因', 400), actor=actor)
        if operation in {'archive', 'restore'}:
            return getattr(service, 'archive_' + kind)(scope, identity, archived=operation == 'archive', **kwargs)
        return getattr(service, operation + '_' + kind)(scope, identity, changes=data['changes'], **kwargs)

    @staticmethod
    def _personal_links(service, scope, record):
        value = dict(record)
        value['related_events'] = [row for identity in record['fields'].get('event_ids',[]) if (row := service.get_event(scope,identity))]
        value['related_people'] = [row for identity in record['fields'].get('character_ids',[]) if (row := service.get_character(scope,identity))]
        return value

    async def _respond(self, route):
        service = None
        try:
            actor = getattr(request, 'username', None)
            if not isinstance(actor, str) or not actor.strip():
                return error_response('请从已登录的 AstrBot 后台打开生活档案', status_code=401)
            resources = self._resources()
            if route in READS:
                data = dict(request.query)
            else:
                if request.query: raise _InvalidRequest('维护操作不接受查询参数')
                length = request.headers.get('Content-Length')
                if length is not None and (not str(length).isascii() or not str(length).isdigit() or int(length) > MAX_BODY):
                    raise _InvalidRequest('生活档案请求过大')
                data = await request.json(default=None)
            scope = self._body(route, data)
            service = self._facade(resources, scope)
            if route in {'advance', 'settings/save'}:
                coordinator = getattr(resources[1], 'life_coordinator', None)
                if coordinator is None: raise RuntimeError('life coordinator unavailable')
                if route == 'advance':
                    self._exact(data, set())
                    result = await coordinator.advance(scope, force=True)
                else:
                    self._exact(data, {'expected_revision', 'changes'})
                    if type(data['changes']) is not dict: raise _InvalidRequest('设置更改必须是对象')
                    result = await coordinator.configure(scope, expected_revision=self._revision(data),
                        changes=data['changes'], actor=actor, service=service)
            else:
                def operate():
                    self._same(resources)
                    value = self._operate(service, route, scope, data, actor)
                    self._same(resources)
                    return value
                result = await asyncio.to_thread(operate)
            self._same(resources)
            body = dict(ok=True, backend='autonomous_life', scope=scope, result=result,
                access='authenticated_administrator', evidence_kind='roleplay_event', creates_runtime_lease=False)
            if route in {'overview', 'personal/overview', 'personal/decision'}:
                coordinator = getattr(resources[1], 'life_coordinator', None)
                body['runtime'] = coordinator.status(scope, service=service) if coordinator else {'available': False}
            return json_response(body, headers={'Cache-Control': 'no-store'})
        except JournalConflict:
            return error_response('资料已经变化，请刷新后按最新版本修改', status_code=409)
        except PermissionError:
            return error_response('当前生活操作缺少真实会话授权；管理资料不会创建运行授权', status_code=403)
        except KeyError:
            return error_response('当前范围中没有这条生活资料或关联记录', status_code=404)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return error_response('字段无效，请核对内容、引用、修订号与时间', status_code=400)
        except (RuntimeError, sqlite3.Error, OSError):
            return error_response('生活服务暂不可用；写入结果未知时请刷新核对，不要重复提交', status_code=503)
        finally:
            if service is not None:
                service.stop()
