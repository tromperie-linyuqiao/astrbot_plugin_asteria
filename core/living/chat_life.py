"""Owned Chat access to the same life ledger; no second store or model call."""
from __future__ import annotations

from .chat_identity import identity_service
from .chat_workspace import ChatWorkspace
from .personal_space import PersonalSpace
from .life_chat_links import LifeChatLinks, resolve_reference


def resources(api, username, session):
    host, runtime, _, _, app_scope = api._app_memory_resources(username, session)
    service = getattr(runtime, 'autonomous_life', None)
    coordinator = getattr(runtime, 'life_coordinator', None)
    if service is None or coordinator is None or not service.active:
        raise RuntimeError('自主生活服务尚未接入')
    scope = app_scope
    links = identity_service(api.plugin)
    link = links.get(username, session.session_id)
    # A previously confirmed identity link permits this specific fictional
    # archive to follow the real PC owner. It is not a QQ memory-write lease.
    pc = getattr(getattr(api.plugin, '_native_server_integrations', None), 'pc_full', None)
    source = getattr(getattr(pc, 'service', None), '_tls_primary_scope', None)
    if (source != app_scope and link and link.get('app_scope') == app_scope
            and source == link.get('qq_scope') and links.current() is True
            and ChatWorkspace(links).settings(username, session.session_id)['values']['shared_memory']
            and host.authorized_scope(source) and host._native_memory_allowed(source)):
        scope = source
    service._scope(scope)
    return host, runtime, service, coordinator, scope


def current(api, username, session, original):
    now = resources(api, username, session)
    if any(a is not b for a,b in zip(now[:4], original[:4])) or now[4] != original[4]:
        raise PermissionError('生活档案来源已变化，请刷新')
    return True


def chat_links(api, username, session, item):
    return LifeChatLinks(item[2], item[4], username, session.session_id,
        current=lambda: current(api, username, session, item))


def resolve_references(api, username, session, parts):
    chosen=[part for part in (parts or []) if isinstance(part,dict) and part.get('type')=='life_reference']
    if not chosen: return {}
    if len(chosen)>1: raise ValueError('每条消息只关联一项经历')
    item=resources(api,username,session)
    with item[2].journal._lock:
        value=resolve_reference(item[2],item[4],chosen[0])
        current(api,username,session,item)
        return {value.get('record_id',value.get('event_id')):value}


def _personal_browser_record(record):
    """The mobile browser needs content/status, never a foreign identity tuple."""
    value=dict(record);value['fields']=dict(record['fields'])
    value['fields'].pop('resource_scope',None)
    if record.get('resource'):
        value['resource']=dict(record['resource']);value['resource'].pop('source_scope',None)
    return value


def get(api, username, session, query):
    item = resources(api, username, session)
    _, _, service, coordinator, scope = item
    with service.journal._lock:
        current(api, username, session, item)
        if query.get('id') and query.get('view') != 'personal': raise ValueError('资料ID须指定私人生活视图')
        targets = [name for name in ('event_id', 'person_id', 'thread_id') if query.get(name)]
        searching = any(name in query for name in ('query', 'kind', 'limit', 'offset'))
        if len(targets) > 1 or targets and searching:
            raise ValueError('请选择一项生活资料或搜索档案')
        if query.get('view') == 'catalog':
            if targets or query.get('id'): raise ValueError('目录搜索不能同时指定资料编号')
            from .life_catalog import search
            if query.get('shared','false') not in ('true','false'): raise ValueError('分享筛选无效')
            result=search(service,scope,query=query.get('query',''),kind=query.get('kind','all'),
                date_from=query.get('date_from',''),date_to=query.get('date_to',''),shared=query.get('shared')=='true',
                limit=int(query.get('limit',20)),offset=int(query.get('offset',0)))
            for row in result['records']:
                if row['kind'] not in ('event','character','thread'): row['record']=_personal_browser_record(row['record'])
            value=dict(catalog=result)
        elif query.get('view') == 'worldline':
            if targets!=['event_id'] or searching or query.get('id'): raise ValueError('世界线需要明确经历编号')
            from .life_worldline import project
            value=dict(worldline=project(service,scope,query['event_id']))
            value['worldline']['chat_links']=chat_links(api,username,session,item).list(query['event_id'])
        elif query.get('view') == 'personal':
            if targets: raise ValueError('私人资料与经历查询不能混用')
            personal = PersonalSpace(service)
            kind = query.get('kind','all')
            if query.get('id'):
                row = personal.get_record(scope,kind,query['id'])
                if row is None or row['archived'] or row.get('deleted'): raise KeyError(query['id'])
                events = [value for identity in row['fields'].get('event_ids',[]) if (value := service.get_event(scope,identity)) and value['valid'] and not value['archived']]
                people = [value for identity in row['fields'].get('character_ids',[]) if (value := service.get_character(scope,identity)) and value['valid'] and not value['archived']]
                value = dict(personal=dict(record=_personal_browser_record(row),links=[_personal_browser_record(link) for link in personal.archive_links(scope,row)],events=events,people=people,record_state='current' if row['valid'] else 'needs_review'))
            elif kind == 'all' and not any(query.get(key) for key in ('query','status','category')) and query.get('sort','updated') == 'updated':
                overview = personal.overview(scope)
                collections=personal.list_records(scope,'collection',include_invalid=True,limit=8)
                overview['recent_collections']=collections['records']
                overview['counts']=dict(overview['counts'],collection=collections['total'])
                for name in ('spaces','recent_collections','active_interests','planned_explorations'):
                    overview[name]=[_personal_browser_record(row) for row in overview.get(name,[])]
                page = personal.list_records(scope, 'all', include_invalid=True,
                    limit=int(query.get('limit',20)), offset=int(query.get('offset',0)))
                page['records'] = [_personal_browser_record(row) for row in page['records']]
                value = dict(personal=dict(page, overview=overview, decision=overview.get('decision')))
            else:
                page=personal.list_records(scope,kind,query=query.get('query',''),include_invalid=True,
                    limit=int(query.get('limit',20)),offset=int(query.get('offset',0)),
                    status=query.get('status',''),category=query.get('category',''),sort=query.get('sort','updated'))
                page['records']=[_personal_browser_record(row) for row in page['records']]
                value = dict(personal=page)
        elif query.get('view') is not None:
            raise ValueError('未知生活视图')
        elif searching:
            kind = query.get('kind', 'all')
            limit, offset = int(query.get('limit', 20)), int(query.get('offset', 0))
            if not 1 <= limit <= 50 or not 0 <= offset <= 1000:
                raise ValueError('生活档案搜索范围无效')
            value = dict(search=service.search_archive(scope, query=query.get('query', ''),
                kind=kind, limit=limit, offset=offset))
        elif query.get('event_id'):
            value = service.detail(scope, query['event_id'])
            if not value or value.get('event') is None: raise KeyError(query['event_id'])
            value['chat_links']=chat_links(api,username,session,item).list(query['event_id'])
        elif query.get('person_id'):
            person = service.get_character(scope, query['person_id'])
            if person is None: raise KeyError(query['person_id'])
            value = dict(person=person, events=service.list_events(scope, character_id=person['id'])['records'])
        elif query.get('thread_id'):
            thread = service.get_thread(scope, query['thread_id'])
            if thread is None: raise KeyError(query['thread_id'])
            value = dict(thread=thread,
                events=[row for identity in thread['fields']['event_ids'] if (row := service.get_event(scope, identity))],
                people=[row for identity in thread['fields']['character_ids'] if (row := service.get_character(scope, identity))])
        else:
            value = service.overview(scope)
            from .chat_daily_view import project
            value.update(project(item[1], scope, value, now=service.journal.clock()))
        value = dict(value, status=coordinator.status(scope), session_id=session.session_id, scope=scope,
            evidence_kind='roleplay_event', shared_fictional_archive=scope['platform'] != 'webchat')
        current(api, username, session, item)
        return value


def post(api, username, session, body, *, saved_message=None):
    item = resources(api, username, session)
    service, scope = item[2], item[4]
    if body['action']=='follow_up' and ('record_kind' in body or 'record_id' in body):
        if any(body.get(key) for key in ('event_id','person_id','thread_id')): raise ValueError('追问只能选择一项资料')
        from .life_chat_links import reference_record
        with service.journal._lock:
            current(api,username,session,item)
            kind,identity=body.get('record_kind'),body.get('record_id')
            row=reference_record(service,scope,kind,identity)
            if not row or not row['valid'] or row['archived'] or row.get('deleted'):raise ValueError('请先核对这项资料')
            reference=resolve_reference(service,scope,dict(type='life_reference',record_kind=kind,record_id=identity,record_revision=row['revision']))
            current(api,username,session,item)
            return dict(session_id=session.session_id,record_kind=kind,record_id=identity,record_revision=row['revision'],
                draft='想听你接着聊聊“'+reference['label']+'”，最近有什么新的想法？',reference=reference)
    targets = [name for name in ('event_id', 'person_id', 'thread_id') if body.get(name)]
    if len(targets) != 1 or body['action'] in {'correct','link_message','forget_link'} and targets != ['event_id']:
        raise ValueError('请选择一项可操作的生活资料')
    target = targets[0]; identity = body[target]
    with service.journal._lock:
        current(api, username, session, item)
        if body['action']=='link_message':
            if saved_message is None: raise PermissionError('需要正式会话消息')
            value=dict(link=chat_links(api,username,session,item).add(identity,body.get('expected_revision'),
                saved_message,body.get('relation'),body.get('note',''),body.get('request_id')))
        elif body['action']=='forget_link':
            value=dict(link=chat_links(api,username,session,item).remove(identity,body.get('link_id'),body.get('expected_revision')))
        elif body['action'] == 'follow_up':
            reader = {'event_id': service.get_event, 'person_id': service.get_character, 'thread_id': service.get_thread}[target]
            record = reader(scope, identity)
            if record is None: raise KeyError(identity)
            if not record['valid'] or record['archived']: raise ValueError('请先修正这条经历的关联来源')
            fields = record['fields']
            draft = ('想听你接着聊聊“'+fields['title']+'”，后来怎么样了？' if target == 'event_id' else
                '想听你聊聊“'+fields['name']+'”，你们之间有什么故事？' if target == 'person_id' else
                '之前的“'+fields['title']+'”现在怎么样了？'+('这件事后来如何收尾的？' if fields['status'] == 'resolved' else '想听你接着聊。'))
            value = {target: identity, target.removesuffix('_id')+'_revision': record['revision'], 'draft': draft}
            if target=='event_id':
                value['reference']=dict(type='life_reference',event_id=identity,event_revision=record['revision'],label=fields['title'])
        else:
            event = service.get_event(scope, identity)
            if event is None: raise KeyError(identity)
            changes = body.get('changes')
            if not isinstance(changes, dict) or not changes or set(changes)-{'title','content','status'}:
                raise ValueError('仅可修正这条虚构经历的标题、内容和状态')
            request_id = body.get('request_id')
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128: raise ValueError('缺少修正请求编号')
            saved = service.correct_event(scope, identity, expected_revision=body.get('expected_revision'),
                changes=changes, reason='用户在Chat修正虚构经历', actor='chat:'+username[:80])
            value = dict(event=saved, affected='dependent_versions_require_review', request_id=request_id)
        current(api, username, session, item)
        return dict(value, session_id=session.session_id)
