"""Versioned fictional life on the existing scoped LivingJournal.

No model, timer, delivery, real-chat rewrite or MC memory write lives here.
Call disk methods on the existing worker. Host policy supplies current scope
authority; persisted records never grant a live private-session lease.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, tzinfo, timezone as time_zone
import hashlib
import json
import math
import re
import unicodedata
from zoneinfo import ZoneInfo

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope, scope_key

SOURCE = 'tls.autonomous_life'
EVIDENCE = 'roleplay_event'
_NS = {kind:'tls.life.'+kind+'.v1' for kind in ('event','character','thread','history','share','policy')}
_BATCH='tls.life.batch.v1'
_SHARED='tls.life.shared_once.v1'
_SHARE_LATEST='tls.life.share_latest.v1'
_LIMIT = {'event':512,'character':64,'thread':128}
_ID = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,95}\Z')
_SOURCE_KINDS = {'operator','model_generated','scoped_plan','pc_artifact','user_correction'}
POLICY_DEFAULTS = dict(enabled=False,interval_minutes=180,min_interval_minutes=60,
    max_model_calls_per_day=4,max_events_per_day=4,share_enabled=False,
    max_shares_per_day=1,quiet_day_allowed=True,muted_topics=[],
    model_provider_id='',model_fallback_provider_id='')


def _text(value,maximum,*,empty=False):
    if (type(value) is not str or len(value)>maximum or not empty and not value.strip()
            or any(ord(char)<32 and char not in '\r\n\t' for char in value)):
        raise ValueError('bounded plain life text required')
    return value.strip()


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value):raise ValueError('stable life ID required')
    return value


def _ids(value,maximum=8):
    if type(value) is not list or len(value)>maximum:raise ValueError('bounded life reference list required')
    result=[_id(item) for item in value]
    if len(set(result))!=len(result):raise ValueError('duplicate life reference')
    return result


def _epoch(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<253402214400:
        raise ValueError('finite life timestamp required')
    return float(value)


def _revision(value,*,zero=False):
    if type(value) is not int or not (0 if zero else 1)<=value<=2**53-1:
        raise ValueError('explicit life revision required')
    return value


def _digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def _terms(value):
    value=value.casefold();words=re.findall(r'[a-z0-9_]{2,32}|[\u3400-\u9fff]{1,32}',value)
    result=set()
    for word in words[:32]:
        result.add(word)
        if re.fullmatch(r'[\u3400-\u9fff]+',word):result.update(word[index:index+2] for index in range(len(word)-1))
    return set(sorted(result)[:64])


_QUERY_FILLER=frozenset(('今天','最近','近况','现在','什么','怎么','怎么样','事情','这件','那件','件事',
    '你们','我们','你还','还记','记得','得吗','是谁','是否','有没有','可以','一下','一下子','了吗','后来','之后',
    '后续','进展','继续','完成','未完','待办','还有','还有什么','哪些','聊聊','说说','看看','的事','那个','这个',
    '生活','发生','发生了','了什么'))
_STATUS={'ongoing':'进行中','completed':'已完成','cancelled':'已取消','open':'未完','resolved':'已解决'}
_PERSON_KIND={'canonical':'正典角色资料','recurring':'常驻虚构人物','temporary':'临时虚构人物'}


def _normal(value):return unicodedata.normalize('NFKC',value).casefold()


def _query_terms(value):return {term for term in _terms(_normal(value)) if term not in _QUERY_FILLER}


def _literal_excerpt(value,max_chars):
    """Fit a quoted source prefix after escaping markers, without new prose."""
    def encode(length):
        text=value[:length]+('…' if length<len(value) else '')
        return json.dumps(text,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    low,high=0,len(value)
    while low<high:
        middle=(low+high+1)//2
        if len(encode(middle))<=max_chars:low=middle
        else:high=middle-1
    result=encode(low)
    return result if len(result)<=max_chars else ''


class AutonomousLife:
    """One fictional ledger; CAS edits preserve old versions and dependencies.

    authorize(scope, operation) returns literal True for read/write/share.
    confirm_delivery(scope, task_id) must verify the actual shared delivery.
    verify_memory_ref(scope, {id,revision}) verifies existing MC references;
    this ledger stores IDs only and never creates or changes those memories.
    """
    backend='autonomous_life'

    def __init__(self,journal,*,authorize,clock=None,confirm_delivery=None,verify_memory_ref=None,timezone=None):
        if not isinstance(journal,LivingJournal) or not callable(authorize):
            raise ValueError('existing LivingJournal and scope authority required')
        for callback in (confirm_delivery,verify_memory_ref):
            if callback is not None and not callable(callback):raise ValueError('trusted callback required')
        self.journal,self.authorize=journal,authorize
        self.clock=journal.clock if clock is None else clock
        self.confirm_delivery,self.verify_memory_ref=confirm_delivery,verify_memory_ref
        self.timezone=time_zone.utc if timezone is None else ZoneInfo(timezone) if type(timezone) is str else timezone
        if not isinstance(self.timezone,tzinfo):raise ValueError('role calendar timezone required')
        self.timezone_name=getattr(self.timezone,'key',str(self.timezone))
        self.active=True

    def _scope(self,scope,operation='read'):
        scope=private_scope(scope)
        if not self.active or self.authorize(dict(scope),operation) is not True:
            raise PermissionError('current life scope authority required')
        self.journal._ensure_open()
        return scope

    def _allowed(self,scope,operation):
        return self.active and self.authorize(dict(scope),operation) is True

    def _now(self):return _epoch(self.clock())

    def _source(self,value,request_id):
        if value is None:value={'kind':'operator','ref':request_id}
        if (type(value) is not dict or set(value)!={'kind','ref'}
                or value['kind'] not in _SOURCE_KINDS):raise ValueError('explicit fictional life source required')
        return dict(kind=value['kind'],ref=_text(value['ref'],256))

    def _fields(self,kind,value):
        if type(value) is not dict:raise ValueError('life fields required')
        if kind=='event':
            defaults=dict(status='completed',character_ids=[],previous_event_ids=[],share_worthy=False)
            required={'title','content','occurred_at'};allowed=required|set(defaults)
        elif kind=='character':
            defaults=dict(kind='temporary',description='',relationship='',event_ids=[])
            required={'name'};allowed=required|set(defaults)
        else:
            defaults=dict(detail='',status='open',character_ids=[])
            required={'title','event_ids'};allowed=required|set(defaults)
        if set(value)-allowed or not required<=set(value):raise ValueError('unsupported or missing life fields')
        fields={**defaults,**deepcopy(value)}
        if kind=='event':
            fields.update(title=_text(fields['title'],120),content=_text(fields['content'],2400),
                occurred_at=_epoch(fields['occurred_at']),character_ids=_ids(fields['character_ids']),
                previous_event_ids=_ids(fields['previous_event_ids']))
            if (fields['status'] not in {'ongoing','completed','cancelled'} or type(fields['share_worthy']) is not bool
                    or fields['occurred_at']>self._now()+30):raise ValueError('recorded fictional event required')
        elif kind=='character':
            fields.update(name=_text(fields['name'],80),description=_text(fields['description'],1200,empty=True),
                relationship=_text(fields['relationship'],400,empty=True),event_ids=_ids(fields['event_ids']))
            if fields['kind'] not in {'canonical','recurring','temporary'}:raise ValueError('explicit character kind required')
            if fields['relationship'] and not fields['event_ids']:
                raise ValueError('relationship must cite an existing life event')
        else:
            fields.update(title=_text(fields['title'],120),detail=_text(fields['detail'],1200,empty=True),
                event_ids=_ids(fields['event_ids']),character_ids=_ids(fields['character_ids']))
            if fields['status'] not in {'open','resolved','cancelled'} or not fields['event_ids']:
                raise ValueError('sourced open item required')
        return fields

    def _row(self,kind,scope,identity):
        row=self.journal.fetch(_NS[kind],_id(identity),scope)
        return self._checked_row(kind,scope,identity,row)

    def _checked_row(self,kind,scope,identity,row):
        if row is None:return None
        _id(identity)
        data=row['data']
        if (type(data) is not dict or data.get('schema')!=1 or data.get('kind')!=kind
                or data.get('id')!=identity or data.get('scope')!=scope
                or data.get('evidence_kind')!=EVIDENCE or type(data.get('archived')) is not bool
                or type(data.get('dependencies')) is not list):raise RuntimeError('invalid fictional life record')
        _revision(data.get('version'));self._fields(kind,data['fields'])
        return row

    def _invalid(self,scope,data,seen=None,cache=None):
        cache={} if cache is None else cache
        cache_key=('valid',data['kind'],data['id'],data['version'],data.get('identity_revision'))
        if cache_key in cache:return deepcopy(cache[cache_key])
        seen=set() if seen is None else set(seen)
        identity=(data['kind'],data['id'])
        if identity in seen:return [{'kind':data['kind'],'id':data['id'],'reason':'dependency_cycle'}]
        seen.add(identity);invalid=[]
        for ref in data['dependencies']:
            if (type(ref) is not dict or set(ref)!={'kind','id','version'}
                    or ref['kind'] not in {'event','character'}):raise RuntimeError('invalid life dependency')
            row_key=('row',ref['kind'],ref['id'])
            if row_key not in cache:cache[row_key]=self._row(ref['kind'],scope,ref['id'])
            target=cache[row_key]
            if target is None:reason='missing_source'
            elif target['data']['archived']:reason='archived_source'
            elif target['data'].get('identity_revision' if ref['kind']=='character' else 'version')!=ref['version']:
                reason='source_corrected'
            elif ref['kind']=='event' and self._invalid(scope,target['data'],seen,cache):reason='source_needs_review'
            else:continue
            invalid.append(dict(ref,reason=reason))
        cache[cache_key]=deepcopy(invalid)
        return invalid

    def _project(self,scope,row,cache=None,*,verify_memory=True):
        if row is None:return None
        data=deepcopy(row['data']);invalid=self._invalid(scope,data,cache=cache)
        refs=[]
        for ref in data.get('memory_refs',[]):
            current=False if verify_memory else None
            if verify_memory and self.verify_memory_ref is not None:
                try:current=self.verify_memory_ref(dict(scope),{key:ref[key] for key in ('id','revision')}) is True
                except Exception:pass
            refs.append(dict(ref,current=current))
        data.update(revision=row['revision'],updated_at=row['updated_at'],valid=not data['archived'] and not invalid,
            invalid_dependencies=invalid,memory_refs=refs,fictional=True)
        if data['kind']=='event':
            sharing_key=('sharing',data['id'])
            receipt=(cache[sharing_key] if cache is not None and sharing_key in cache else
                self.journal.fetch(_SHARED,data['id'],scope) or self.journal.fetch(_SHARE_LATEST,data['id'],scope))
            value=receipt['data'] if receipt else {}
            data['sharing']=dict(state=value.get('state','unshared'),event_version=value.get('event_version'),
                task_id=value.get('task_id'),at=value.get('at'),ever_shared=value.get('state')=='confirmed',
                is_current_version=value.get('event_version')==data['version'])
        return data

    def _references(self,kind,scope,fields,identity=None):
        refs=[]
        for char_id in fields.get('character_ids',[]):
            char=self._row('character',scope,char_id)
            if char is None or char['data']['archived']:raise ValueError('current life character required')
            refs.append(dict(kind='character',id=char_id,version=char['data']['identity_revision']))
        event_ids=fields.get('previous_event_ids',[]) if kind=='event' else fields.get('event_ids',[])
        for event_id in event_ids:
            event=self._row('event',scope,event_id)
            if (event is None or event['data']['archived'] or self._invalid(scope,event['data'])
                    or kind=='event' and (event_id==identity or self._reaches(scope,event['data'],identity))):
                raise ValueError('current acyclic source event required')
            if kind=='event' and event['data']['fields']['occurred_at']>fields['occurred_at']:
                raise ValueError('predecessor cannot happen after the event')
            refs.append(dict(kind='event',id=event_id,version=event['data']['version']))
        return refs

    def _reaches(self,scope,data,identity,seen=None):
        if data['id']==identity:return True
        seen=set() if seen is None else seen
        if data['id'] in seen:return True
        seen.add(data['id'])
        for ref in data['dependencies']:
            if ref['kind']!='event':continue
            row=self._row('event',scope,ref['id'])
            if row and self._reaches(scope,row['data'],identity,set(seen)):return True
        return False

    def _save(self,kind,scope,data,old,*,reason,actor,extra_authorize=None):
        actor=_text(actor,120);reason=_text(reason,400)
        authorize=lambda:self._allowed(scope,'write') and (extra_authorize is None or extra_authorize() is True)
        if old:
            key=kind+'.'+data['id']+'.'+str(old['revision'])
            previous=self.journal.fetch(_NS['history'],key,scope)
            if previous is None:
                self.journal.put(_NS['history'],key,scope,dict(kind=kind,id=data['id'],revision=old['revision'],
                    snapshot=old['data'],replaced_at=self._now(),reason=reason,actor=actor),
                    expected_revision=0,authorize=authorize)
        data=deepcopy(data);data.update(last_edit=dict(actor=actor,reason=reason,at=self._now()))
        row=self.journal.put(_NS[kind],data['id'],scope,data,
            expected_revision=old['revision'] if old else 0,authorize=authorize)
        return self._project(scope,row)

    @staticmethod
    def _identity(kind,scope,request_id):return 'life.'+kind[0]+'.'+_digest([scope,request_id])[:40]

    def _new_data(self,kind,scope,request_id,fields,source,dependencies):
        data=dict(schema=1,kind=kind,id=self._identity(kind,scope,request_id),scope=scope,fields=fields,source=source,
            evidence_kind=EVIDENCE,version=1,created_at=self._now(),archived=False,
            dependencies=dependencies,request_id=request_id,request_fingerprint=_digest([fields,source]),
            initial_fields_hash=_digest(fields),correction_count=0,memory_refs=[])
        if kind=='character':data['identity_revision']=1
        return data

    def _create(self,kind,scope,request_id,fields,source):
        scope=self._scope(scope,'write');request_id=_text(request_id,128)
        fields=self._fields(kind,fields);source=self._source(source,request_id)
        identity=self._identity(kind,scope,request_id)
        fingerprint=_digest([fields,source]);now=self._now()
        with self.journal._lock:
            old=self._row(kind,scope,identity)
            if old:
                if old['data']['request_fingerprint']!=fingerprint:raise JournalConflict('life request already has different content')
                return self._project(scope,old)
            records=self.journal.list(_NS[kind],scope,limit=_LIMIT[kind]+1)
            if len(records)>=_LIMIT[kind]:raise RuntimeError('life record capacity reached; original history retained')
            # Exact retries under a new transport request must not create a
            # second occurrence. Similar events on another date remain distinct.
            for row in records:
                if row['data'].get('initial_fields_hash')==_digest(fields) and not row['data'].get('archived'):
                    return self._project(scope,row)
            data=self._new_data(kind,scope,request_id,fields,source,self._references(kind,scope,fields,identity))
            return self._save(kind,scope,data,None,reason='created fictional '+kind,actor=source['kind'])

    def apply_generated(self,scope,request_id,event,*,characters=None,threads=None,relationships=None,source=None):
        """Atomically record a bounded generated event and its new small cast.

        characters use {key,name,description?}; '$key' references that temporary
        NPC. Thread event_ids default to ['$event']; an existing thread id is
        updated with the new event as provenance. Relationships change only
        their text, cite this actual event, and never change character identity.
        """
        scope=self._scope(scope,'write');request_id=_text(request_id,96)
        characters=[] if characters is None else deepcopy(characters)
        threads=[] if threads is None else deepcopy(threads)
        relationships=[] if relationships is None else deepcopy(relationships)
        if (type(characters) is not list or len(characters)>3 or type(threads) is not list or len(threads)>4
                or type(relationships) is not list or len(relationships)>4):
            raise ValueError('bounded generated cast, threads and relationships required')
        source=self._source(source,request_id)
        fingerprint=_digest(plain(dict(event=event,characters=characters,threads=threads,relationships=relationships,source=source),32768))
        batch_key='batch.'+_digest([scope,request_id])[:48]
        with self.journal._transaction() as db:
            if not self._allowed(scope,'write'):raise PermissionError('life batch authority changed')
            saved=self.journal.fetch(_BATCH,batch_key,scope)
            if saved:
                if saved['data']['fingerprint']!=fingerprint:raise JournalConflict('generated request already has different content')
                result=deepcopy(saved['data']);result['created']=False
            else:
                pending=[];aliases={};now=self._now()
                for index,person in enumerate(characters):
                    if type(person) is not dict or set(person)-{'key','name','description'} or not {'key','name'}<=set(person):
                        raise ValueError('temporary generated character key/name required')
                    key=_id(person['key'])
                    if '$'+key in aliases:raise ValueError('duplicate generated character key')
                    fields=self._fields('character',dict(name=person['name'],description=person.get('description',''),kind='temporary'))
                    person_request=request_id+'.npc.'+str(index)
                    data=self._new_data('character',scope,person_request,fields,source,[])
                    aliases['$'+key]=data['id'];pending.append(('character',data,None))
                def char_ids(values):
                    if type(values) is not list:raise ValueError('generated character references required')
                    return [aliases.get(value,value) if type(value) is str else value for value in values]
                if type(event) is not dict:raise ValueError('generated event fields required')
                fields=self._fields('event',{**deepcopy(event),'character_ids':char_ids(event.get('character_ids',[]))})
                new_people={data['id']:data for kind,data,_ in pending if kind=='character'}
                event_id=self._identity('event',scope,request_id+'.event')
                references=[]
                for char_id in fields['character_ids']:
                    if char_id in new_people:references.append(dict(kind='character',id=char_id,version=1))
                    else:references.extend(self._references('event',scope,dict(fields,character_ids=[char_id],previous_event_ids=[]),event_id))
                references.extend(self._references('event',scope,dict(fields,character_ids=[]),event_id))
                event_data=self._new_data('event',scope,request_id+'.event',fields,source,references)
                pending.append(('event',event_data,None))
                changed_threads=set()
                for index,item in enumerate(threads):
                    if type(item) is not dict:raise ValueError('generated thread fields required')
                    item=deepcopy(item);thread_id=item.pop('id',None);old=None
                    if thread_id is not None:
                        _id(thread_id)
                        if thread_id in changed_threads:raise ValueError('duplicate generated thread update')
                        changed_threads.add(thread_id);old=self._row('thread',scope,thread_id)
                        if old is None or old['data']['archived'] or self._invalid(scope,old['data']):
                            raise ValueError('current existing thread required for generated update')
                        item={**old['data']['fields'],**item}
                        item['event_ids']=[*item.get('event_ids',[]),'$event'] if '$event' not in item.get('event_ids',[]) else item['event_ids']
                    event_ids=item.get('event_ids',['$event'])
                    if type(event_ids) is not list:raise ValueError('generated thread event references required')
                    thread_fields=self._fields('thread',{**item,'event_ids':[event_id if value=='$event' else value for value in event_ids],
                        'character_ids':char_ids(item.get('character_ids',[]))})
                    refs=[]
                    for char_id in thread_fields['character_ids']:
                        if char_id in new_people:refs.append(dict(kind='character',id=char_id,version=1))
                        else:refs.extend(self._references('thread',scope,dict(thread_fields,character_ids=[char_id],event_ids=[])))
                    for prior in thread_fields['event_ids']:
                        if prior==event_id:refs.append(dict(kind='event',id=event_id,version=1))
                        else:refs.extend(self._references('thread',scope,dict(thread_fields,character_ids=[],event_ids=[prior])))
                    if old:
                        data=deepcopy(old['data']);data.update(fields=thread_fields,dependencies=refs,
                            version=data['version']+1,correction_count=data['correction_count']+1)
                    else:data=self._new_data('thread',scope,request_id+'.thread.'+str(index),thread_fields,source,refs)
                    pending.append(('thread',data,old))
                changed_people=set();growth_deferred=[]
                for relation in relationships:
                    if type(relation) is not dict or set(relation)!={'id','relationship'}:
                        raise ValueError('generated relationship may change relationship text only')
                    value=relation['id'];_text(value,96)
                    char_id=aliases.get(value,aliases.get('$'+value,value));_id(char_id)
                    if char_id not in fields['character_ids']:
                        raise ValueError('relationship participant must occur in this recorded event')
                    if char_id in changed_people:raise ValueError('duplicate generated relationship update')
                    changed_people.add(char_id)
                    index=next((index for index,(kind,data,_) in enumerate(pending)
                        if kind=='character' and data['id']==char_id),None)
                    old=None if index is not None else self._row('character',scope,char_id)
                    if index is not None:data=deepcopy(pending[index][1])
                    elif old and not old['data']['archived'] and not self._invalid(scope,old['data']):
                        data=deepcopy(old['data']);data.update(version=data['version']+1,correction_count=data['correction_count']+1)
                    else:raise ValueError('current existing character required for generated relationship')
                    from .life_growth import constrain
                    proposed=self._fields('character',{**data['fields'],'relationship':relation['relationship'],
                        'event_ids':[event_id]})
                    if old and old['data']['fields']['kind']=='canonical':
                        if proposed['relationship']!=old['data']['fields']['relationship']:
                            growth_deferred.append(dict(kind='character',id=char_id,fields=['relationship'],
                                reason='canonical_relationship_preserved'))
                        continue
                    marks,held=constrain(old['data'] if old else None,proposed,('relationship',),
                        now=now,event_id=event_id)
                    if held:
                        growth_deferred.append(dict(kind='character',id=char_id,fields=['relationship'],reasons=held))
                        continue
                    data['fields']=proposed
                    data['growth_updates']=marks
                    data['dependencies']=[dict(kind='event',id=event_id,version=1)]
                    if index is not None:pending[index]=('character',data,None)
                    else:pending.append(('character',data,old))
                normalized=scope_key(scope)
                histories=[]
                for kind,data,old in pending:
                    if old:
                        key=kind+'.'+data['id']+'.'+str(old['revision'])
                        if self.journal.fetch(_NS['history'],key,scope) is None:
                            histories.append((key,dict(kind=kind,id=data['id'],revision=old['revision'],snapshot=old['data'],
                                replaced_at=now,reason='generated sourced continuation',actor=source['kind'])))
                count=db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
                if count+sum(old is None for _,_,old in pending)+len(histories)+1>self.journal.max_records:
                    raise RuntimeError('journal capacity reached; generated batch not recorded')
                for kind in _LIMIT:
                    count=db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?',(_NS[kind],normalized)).fetchone()[0]
                    if count+sum(item[0]==kind and item[2] is None for item in pending)>_LIMIT[kind]:raise RuntimeError('life entity capacity reached')
                for key,data in histories:
                    db.execute('INSERT INTO checkpoints(namespace,key,scope,revision,updated,data) VALUES(?,?,?,?,?,?)',
                        (_NS['history'],key,normalized,1,now,canonical(plain(data,65536))))
                for kind,data,old in pending:
                    data['last_edit']=dict(actor=source['kind'],reason='generated fictional batch',at=now)
                    encoded=canonical(plain(data,65536))
                    if old:
                        changed=db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND key=? AND scope=? AND revision=?',
                            (old['revision']+1,now,encoded,_NS[kind],data['id'],normalized,old['revision']))
                        if changed.rowcount!=1:raise JournalConflict('generated source revision changed')
                    else:db.execute('INSERT INTO checkpoints(namespace,key,scope,revision,updated,data) VALUES(?,?,?,?,?,?)',
                        (_NS[kind],data['id'],normalized,1,now,encoded))
                result=dict(schema=1,state='complete',created=True,fingerprint=fingerprint,request_id=request_id,
                    event_id=event_id,character_ids=[data['id'] for kind,data,_ in pending if kind=='character'],
                    thread_ids=[data['id'] for kind,data,_ in pending if kind=='thread'],
                    growth_deferred=growth_deferred,evidence_kind=EVIDENCE,at=now)
                db.execute('INSERT INTO checkpoints(namespace,key,scope,revision,updated,data) VALUES(?,?,?,?,?,?)',
                    (_BATCH,batch_key,normalized,1,now,canonical(result)))
            if not self._allowed(scope,'write'):raise PermissionError('life batch authority changed')
        result['event']=self.get_event(scope,result['event_id'])
        result['characters']=[self.get_character(scope,identity) for identity in result['character_ids']]
        result['threads']=[self.get_thread(scope,identity) for identity in result['thread_ids']]
        return result

    def _update(self,kind,scope,identity,*,expected_revision,changes,reason,actor='operator'):
        scope=self._scope(scope,'write');_revision(expected_revision)
        if type(changes) is not dict or not changes:raise ValueError('explicit life changes required')
        with self.journal._lock:
            old=self._row(kind,scope,identity)
            if old is None:raise KeyError('life record missing')
            if old['revision']!=expected_revision:raise JournalConflict('life revision changed')
            fields=self._fields(kind,{**old['data']['fields'],**changes})
            data=deepcopy(old['data']);data.update(fields=fields,dependencies=self._references(kind,scope,fields,identity),
                version=data['version']+1,correction_count=data['correction_count']+1)
            if kind=='character' and any(fields[key]!=old['data']['fields'][key] for key in ('name','kind')):
                data['identity_revision']+=1
            return self._save(kind,scope,data,old,reason=reason,actor=actor)

    def _archive(self,kind,scope,identity,*,expected_revision,archived=True,reason='archive state changed',actor='operator'):
        scope=self._scope(scope,'write');_revision(expected_revision)
        if type(archived) is not bool:raise ValueError('exact archive flag required')
        with self.journal._lock:
            old=self._row(kind,scope,identity)
            if old is None:raise KeyError('life record missing')
            if old['revision']!=expected_revision:raise JournalConflict('life revision changed')
            if old['data']['archived']==archived:return self._project(scope,old)
            data=deepcopy(old['data']);data.update(archived=archived,version=data['version']+1)
            if kind=='character':data['identity_revision']+=1
            return self._save(kind,scope,data,old,reason=reason,actor=actor)

    def _list(self,kind,scope,*,query='',status=None,character_id=None,include_archived=False,
              include_invalid=False,limit=20,offset=0):
        scope=self._scope(scope);query=_text(query,300,empty=True)
        if type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or not 0<=offset<=1000:
            raise ValueError('bounded life page required')
        if type(include_archived) is not bool or type(include_invalid) is not bool:raise ValueError('exact life list flags required')
        if character_id is not None:_id(character_id)
        rows=[];cache={}
        for row in self.journal.list(_NS[kind],scope,limit=_LIMIT[kind]+1):
            record=self._project(scope,row,cache)
            if (not include_archived and record['archived'] or not include_invalid and record['invalid_dependencies']
                    or status is not None and record['fields'].get('status')!=status
                    or character_id is not None and character_id not in record['fields'].get('character_ids',[])):
                continue
            text=' '.join(str(record['fields'].get(key,'')) for key in ('title','content','name','description','relationship','detail'))
            if query and not any(term in text.casefold() for term in _terms(query)):continue
            rows.append(record)
        self._scope(scope)
        return dict(records=rows[offset:offset+limit],total=len(rows),limit=limit,offset=offset,evidence_kind=EVIDENCE)

    def _recent_events(self,scope):
        cache={};records=[]
        for row in self.journal.list(_NS['event'],scope,limit=64):
            record=self._project(scope,row,cache)
            if record['valid']:records.append(record)
        return records

    def get_event(self,scope,identity):
        scope=self._scope(scope);value=self._project(scope,self._row('event',scope,identity));self._scope(scope);return value
    def get_character(self,scope,identity):
        scope=self._scope(scope);value=self._project(scope,self._row('character',scope,identity));self._scope(scope);return value
    def get_thread(self,scope,identity):
        scope=self._scope(scope);value=self._project(scope,self._row('thread',scope,identity));self._scope(scope);return value
    def list_events(self,scope,**filters):return self._list('event',scope,**filters)
    def list_characters(self,scope,**filters):return self._list('character',scope,**filters)
    def list_threads(self,scope,**filters):return self._list('thread',scope,**filters)
    def create_event(self,scope,request_id,fields,*,source=None):return self._create('event',scope,request_id,fields,source)
    def create_character(self,scope,request_id,fields,*,source=None):return self._create('character',scope,request_id,fields,source)
    def create_thread(self,scope,request_id,fields,*,source=None):return self._create('thread',scope,request_id,fields,source)
    def correct_event(self,scope,identity,**edit):return self._update('event',scope,identity,**edit)
    def update_character(self,scope,identity,**edit):return self._update('character',scope,identity,**edit)
    def update_thread(self,scope,identity,**edit):return self._update('thread',scope,identity,**edit)
    def archive_event(self,scope,identity,**edit):return self._archive('event',scope,identity,**edit)
    def archive_character(self,scope,identity,**edit):return self._archive('character',scope,identity,**edit)
    def archive_thread(self,scope,identity,**edit):return self._archive('thread',scope,identity,**edit)

    def history(self,scope,kind,identity,*,limit=20,offset=0,expected_revision=None):
        scope=self._scope(scope)
        if (kind not in _LIMIT or type(limit) is not int or not 1<=limit<=100
                or type(offset) is not int or not 0<=offset<=50000):raise ValueError('bounded life history required')
        if expected_revision is not None:_revision(expected_revision,zero=True)
        with self.journal._lock:
            current=self._row(kind,scope,identity)
            current_revision=current['revision'] if current else 0
            if expected_revision is not None and expected_revision!=current_revision:
                raise JournalConflict('life history revision changed')
            total=max(0,current_revision-1);records=[]
            for revision in range(total-offset,max(0,total-offset-limit),-1):
                row=self.journal.fetch(_NS['history'],kind+'.'+identity+'.'+str(revision),scope)
                if row:records.append(deepcopy(row['data']))
            self._scope(scope)
        return dict(records=records,total=total,offset=offset,limit=limit,current_revision=current_revision)

    def settings(self,scope):
        scope=self._scope(scope);row=self.journal.fetch(_NS['policy'],'settings',scope)
        values=self._policy({**deepcopy(POLICY_DEFAULTS),**row['data']['settings']}) if row else deepcopy(POLICY_DEFAULTS)
        return dict(revision=row['revision'] if row else 0,settings=values,scope=scope,
            updated_at=row['updated_at'] if row else None,timezone=self.timezone_name)

    @staticmethod
    def _policy(value):
        if type(value) is not dict or set(value)!=set(POLICY_DEFAULTS):raise ValueError('exact life policy fields required')
        for key in ('enabled','share_enabled','quiet_day_allowed'):
            if type(value[key]) is not bool:raise ValueError('exact life policy flag required')
        topics=value['muted_topics']
        if type(topics) is not list or len(topics)>16:raise ValueError('at most 16 explicitly muted topics required')
        topics=[_text(topic,60) for topic in topics]
        if len({topic.casefold() for topic in topics})!=len(topics):raise ValueError('duplicate muted topic')
        for key,low,high in (('interval_minutes',60,10080),('min_interval_minutes',60,10080),
                ('max_model_calls_per_day',0,24),('max_events_per_day',0,24),('max_shares_per_day',0,8)):
            if type(value[key]) is not int or not low<=value[key]<=high:raise ValueError('bounded life policy required')
        if value['interval_minutes']<value['min_interval_minutes']:raise ValueError('life interval below minimum')
        for key in ('model_provider_id','model_fallback_provider_id'):
            identity=value[key]
            if (not isinstance(identity,str) or len(identity)>160 or identity!=identity.strip()
                    or any(ord(char)<32 for char in identity)):
                raise ValueError('valid configured life provider identifier required')
        primary,fallback=value['model_provider_id'],value['model_fallback_provider_id']
        if fallback and (not primary or primary==fallback):
            raise ValueError('life fallback requires a different explicit primary')
        return dict(value,muted_topics=topics)

    def configure(self,scope,*,expected_revision,changes,actor='operator'):
        scope=self._scope(scope,'write');_revision(expected_revision,zero=True);actor=_text(actor,120)
        if type(changes) is not dict or set(changes)-set(POLICY_DEFAULTS):raise ValueError('unsupported life policy field')
        with self.journal._lock:
            previous=self.settings(scope)
            if previous['revision']!=expected_revision:raise JournalConflict('life policy revision changed')
            policy=self._policy({**previous['settings'],**changes})
            self.journal.put(_NS['policy'],'settings',scope,dict(schema=1,settings=policy,actor=actor),
                expected_revision=expected_revision,authorize=lambda:self._allowed(scope,'write'))
        return self.settings(scope)

    def link_memory_refs(self,scope,identity,*,expected_revision,refs,verify=None,actor='system'):
        scope=self._scope(scope,'write');_revision(expected_revision)
        verify=self.verify_memory_ref if verify is None else verify
        if not callable(verify) or type(refs) is not list or len(refs)>8:raise ValueError('verified existing memory references required')
        cleaned=[]
        for ref in refs:
            if type(ref) is not dict or set(ref)!={'id','revision'}:raise ValueError('exact memory ID/revision required')
            cleaned.append(dict(id=_text(ref['id'],128),revision=_revision(ref['revision'])))
        if len({ref['id'] for ref in cleaned})!=len(cleaned):raise ValueError('duplicate memory reference')
        def valid():return all(verify(dict(scope),dict(ref)) is True for ref in cleaned)
        if not valid():raise PermissionError('current memory source revision unavailable')
        with self.journal._lock:
            old=self._row('event',scope,identity)
            if old is None:raise KeyError('life event missing')
            if old['revision']!=expected_revision:raise JournalConflict('life event revision changed')
            data=deepcopy(old['data']);data['memory_refs']=[dict(ref,linked_at=self._now()) for ref in cleaned]
            return self._save('event',scope,data,old,reason='linked verified existing memory IDs',actor=actor,extra_authorize=valid)

    def shares(self,scope,*,event_id=None,limit=20):
        scope=self._scope(scope)
        if event_id is not None:_id(event_id)
        if type(limit) is not int or not 1<=limit<=200:raise ValueError('bounded share history required')
        records=[dict(row['data'],revision=row['revision']) for row in self.journal.list(_NS['share'],scope,limit=1000)
            if event_id is None or row['data'].get('event_id')==event_id]
        self._scope(scope)
        return dict(records=records[:limit],total=len(records))

    def record_share(self,scope,identity,*,task_id,state='confirmed',expected_revision=None,event_version=None,detail=''):
        scope=self._scope(scope,'share');task_id=_text(task_id,128);detail=_text(detail,400,empty=True)
        if state not in {'queued','confirmed','failed','unknown','dismissed'}:raise ValueError('explicit share state required')
        with self.journal._lock:
            event=self._row('event',scope,identity)
            if event is None:raise KeyError('life event missing')
            if expected_revision is not None and event['revision']!=_revision(expected_revision):
                raise JournalConflict('shared life event revision changed')
            version=event['data']['version'] if event_version is None else _revision(event_version)
            key='share.'+_digest([identity,task_id])[:48]
            old=self.journal.fetch(_NS['share'],key,scope)
            if old and old['data']['event_version']!=version:raise JournalConflict('share task already names another event version')
            if old and old['data']['state']==state:return dict(old['data'],revision=old['revision'])
            if old and old['data']['state'] in {'confirmed','dismissed'}:raise JournalConflict('settled life share is retained')
            if version!=event['data']['version'] and old is None:raise JournalConflict('unknown historical share source')
            def allowed():
                return self._allowed(scope,'share') and (state!='confirmed' or self.confirm_delivery is not None
                    and self.confirm_delivery(dict(scope),task_id) is True)
            if not allowed():raise PermissionError('actual shared delivery confirmation required')
            data=dict(schema=1,id=key,event_id=identity,event_version=version,task_id=task_id,state=state,
                at=self._now(),detail=detail,evidence_kind='action_result',fictional_event_evidence=EVIDENCE)
            if state in {'confirmed','dismissed'}:
                marker=self.journal.fetch(_SHARED,identity,scope)
                if marker is None:
                    self.journal.put(_SHARED,identity,scope,data,expected_revision=0,authorize=allowed)
            row=self.journal.put(_NS['share'],key,scope,data,expected_revision=old['revision'] if old else 0,authorize=allowed)
            latest=self.journal.fetch(_SHARE_LATEST,identity,scope)
            self.journal.put(_SHARE_LATEST,identity,scope,data,expected_revision=latest['revision'] if latest else 0,authorize=allowed)
            return dict(row['data'],revision=row['revision'])

    def share_candidates(self,scope,*,limit=3,include_ineligible=False):
        scope=self._scope(scope)
        if type(limit) is not int or not 1<=limit<=8 or type(include_ineligible) is not bool:
            raise ValueError('bounded life share candidates and exact flag required')
        policy=self.settings(scope)['settings'];now=self._now()
        day_start=datetime.fromtimestamp(now,self.timezone).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        receipts=self.shares(scope,limit=200)['records']
        settled={row['event_id'] for row in receipts if row['state'] in {'confirmed','dismissed','queued','unknown'}}
        daily=sum(row['state']=='confirmed' and row['at']>=day_start for row in receipts)
        result=[];open_items=self.list_threads(scope,status='open',limit=128)['records']
        for event in self._recent_events(scope):
            fields=event['fields'];age=now-fields['occurred_at']
            ongoing=any(event['id'] in item['fields']['event_ids'] for item in open_items)
            followup=bool(fields['previous_event_ids']) and fields['status']=='completed'
            reasons=[]
            if fields['share_worthy']:reasons.append('saved_share_suggestion')
            if followup:reasons.append('recorded_followup')
            if ongoing:reasons.append('has_current_open_item')
            has_signal=bool(reasons)
            muted=any(topic.casefold() in (fields['title']+'\n'+fields['content']).casefold() for topic in policy['muted_topics'])
            if muted:reasons.append('user_topic_muted')
            eligible=(policy['enabled'] and policy['share_enabled'] and daily<policy['max_shares_per_day']
                and event['id'] not in settled and not self.journal.fetch(_SHARED,event['id'],scope)
                and fields['status']!='cancelled' and 0<=age<=3*86400 and has_signal and not muted)
            if not eligible and not include_ineligible:continue
            result.append(dict(source='autonomous_life',kind='fictional_life_event',candidate_id=event['id'],event_id=event['id'],
                revision=event['revision'],event_version=event['version'],dedupe_key=event['id'],
                topic='虚构生活经历：'+fields['title'],motive='；'.join(reasons),reasons=reasons,
                reason='user_topic_muted' if muted else 'fictional_life_share',quota_timezone=self.timezone_name,
                evidence=fields['content'][:240],evidence_kind=EVIDENCE,occurred_at=fields['occurred_at'],
                eligible=bool(eligible),score=40+20*followup+15*ongoing+10*fields['share_worthy'],creates_send_permission=False))
        self._scope(scope)
        return sorted(result,key=lambda item:(-item['score'],-item['occurred_at'],item['event_id']))[:limit]

    def proactive_candidates(self,scope,*,include_ineligible=False):
        return self.share_candidates(scope,limit=3,include_ineligible=include_ineligible)

    def correction_impact(self,scope,event_id):
        from .life_correction_impact import project
        return project(self,scope,event_id)

    def context_generation(self,scope):
        """Current scoped revision metadata only; never return life text."""
        scope=self._scope(scope);names=[_NS[kind] for kind in ('event','character','thread','policy')]
        with self.journal._lock:
            rows=self.journal._db.execute('SELECT namespace,key,revision FROM checkpoints WHERE scope=? AND namespace IN (?,?,?,?) ORDER BY namespace,key',
                (scope_key(scope),*names)).fetchall()
            result=_digest([[row[0],row[1],row[2]] for row in rows])
        self._scope(scope)
        from .personal_space import PersonalSpace
        return _digest([result,PersonalSpace(self).generation(scope)])

    def _retrieval_snapshot(self,scope,*,cache=None):
        """One bounded private-scope scan and one shared dependency cache.

        No historical versions, observations, MC contents or foreign scopes are
        searched. Existing memory IDs remain unverified metadata here.
        """
        scope=self._scope(scope)
        with self.journal._lock:
            generation=self.context_generation(scope);raw={};cache={} if cache is None else cache
            for kind,maximum in _LIMIT.items():
                rows=self.journal.list(_NS[kind],scope,limit=maximum+1)
                if len(rows)>maximum:raise RuntimeError('life scope exceeds supported retrieval capacity')
                raw[kind]={}
                for row in rows:
                    checked=self._checked_row(kind,scope,row['key'],row)
                    raw[kind][row['key']]=checked
                    cache[('row',kind,row['key'])]=checked
            # Share state belongs to these exact current events. Fetch both
            # receipt kinds once while holding the same Journal lock; the
            # confirmed marker keeps its original precedence over latest.
            event_ids=tuple(raw['event'])
            if event_ids:
                marks={}
                placeholders=','.join('?' for _ in event_ids)
                for row in self.journal._db.execute(
                        'SELECT namespace,key,revision,updated,data FROM checkpoints WHERE scope=? '
                        'AND namespace IN (?,?) AND key IN ('+placeholders+')',
                        (scope_key(scope),_SHARED,_SHARE_LATEST,*event_ids)):
                    marks[(row['namespace'],row['key'])]=self.journal._record(row)
                for identity in event_ids:
                    cache[('sharing',identity)]=marks.get((_SHARED,identity)) or marks.get((_SHARE_LATEST,identity))
            projected={kind:{identity:self._project(scope,row,cache,verify_memory=False)
                for identity,row in rows.items()} for kind,rows in raw.items()}
            valid={kind:{identity:record for identity,record in rows.items() if record['valid']}
                for kind,rows in projected.items()}
            if self.context_generation(scope)!=generation:raise JournalConflict('life changed during retrieval')
            self._scope(scope)
        return dict(scope=scope,generation=generation,records=valid,all_records=projected,
            coverage=dict(events=len(raw['event']),characters=len(raw['character']),threads=len(raw['thread']),
                valid_events=len(valid['event']),valid_characters=len(valid['character']),valid_threads=len(valid['thread']),
                limits=dict(_LIMIT),method='bounded_scope_lexical_graph',historical_versions_searched=False,
                real_chats_searched=False,memory_contents_searched=False))

    def _rank_life(self,snapshot,query):
        query=_normal(query);terms=_query_terms(query);groups=snapshot['records'];matches={}
        open_question=any(word in query for word in ('未完','待办','还没','没做完','没完成','在继续'))
        later_question=any(word in query for word in ('后来','后续','之后','进展','结果','怎么样','继续'))
        recent_question=not query or any(word in query for word in ('最近','近况','今天','生活','发生了什么'))
        def add(kind,record,score,reason):
            if record is None or score<=0:return
            key=(kind,record['id']);previous=matches.get(key)
            if previous is None:matches[key]=dict(kind=kind,record=record,score=score,matched_by=[reason])
            else:
                previous['score']=max(previous['score'],score)
                if reason not in previous['matched_by']:previous['matched_by'].append(reason)
        weights={'event':(('title',8),('content',2)),
            'character':(('name',16),('description',3),('relationship',3)),
            'thread':(('title',10),('detail',3))}
        for kind,records in groups.items():
            for record in records.values():
                fields=record['fields'];score=0
                for field,weight in weights[kind]:
                    text=_normal(fields.get(field,''))
                    score+=sum(min(len(term),8)*weight for term in terms if term in text)
                exact=bool(query and record['id'].casefold() in query)
                if exact:score+=240
                if kind=='character':
                    name=_normal(fields['name'])
                    if name in query and (len(name)>1 or query==name):score+=180+len(name)*3;exact=True
                add(kind,record,score,'exact_name_or_id' if exact else 'lexical')
                if kind=='thread' and open_question and fields['status']=='open':add(kind,record,score+70,'open_status')
        if not matches and recent_question:
            midnight=datetime.fromtimestamp(self._now(),self.timezone).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
            for kind,records in groups.items():
                for record in records.values():
                    if kind=='event' and '今天' in query and record['fields']['occurred_at']<midnight:continue
                    score=25 if kind=='thread' and record['fields']['status']=='open' else 20 if kind=='event' else 8
                    add(kind,record,score,'current_scope' if not query else 'recent_or_open')
        # Only real stored IDs create associations; two bounded hops connect a
        # named person -> their events -> their sourced unfinished matters.
        for _ in range(2):
            for match in list(matches.values()):
                kind,record,score=match['kind'],match['record'],match['score'];fields=record['fields']
                if kind=='character':
                    for event in groups['event'].values():
                        if record['id'] in event['fields']['character_ids'] or event['id'] in fields['event_ids']:
                            add('event',event,int(score*.65)+10,'character_event_reference')
                    for thread in groups['thread'].values():
                        if record['id'] in thread['fields']['character_ids']:
                            add('thread',thread,int(score*.60)+(15 if thread['fields']['status']=='open' else 0),'character_thread_reference')
                elif kind=='event':
                    for identity in fields['character_ids']:add('character',groups['character'].get(identity),int(score*.45),'event_character_reference')
                    for thread in groups['thread'].values():
                        if record['id'] in thread['fields']['event_ids']:
                            add('thread',thread,int(score*.70)+(20 if thread['fields']['status']=='open' else 0),'event_thread_reference')
                    for identity in fields['previous_event_ids']:
                        add('event',groups['event'].get(identity),int(score*.35),'previous_event_reference')
                    if later_question:
                        for following in groups['event'].values():
                            if record['id'] in following['fields']['previous_event_ids']:
                                add('event',following,int(score*.80)+25,'following_event_reference')
                else:
                    for identity in fields['event_ids']:add('event',groups['event'].get(identity),int(score*.70)+15,'thread_event_reference')
                    for identity in fields['character_ids']:add('character',groups['character'].get(identity),int(score*.45),'thread_character_reference')
        def order(match):
            record=match['record'];when=record['fields'].get('occurred_at',record['updated_at'])
            return (-match['score'],-when,match['kind'],record['id'])
        return sorted(matches.values(),key=order)

    @staticmethod
    def _life_source_ref(record):
        value=dict(kind=record['kind'],id=record['id'],revision=record['revision'],version=record['version'])
        if record['kind']=='character':value['identity_revision']=record['identity_revision']
        return value

    def _retrieval_current(self,snapshot):
        self._scope(snapshot['scope'])
        if self.context_generation(snapshot['scope'])!=snapshot['generation']:
            raise JournalConflict('life changed while selecting retrieval material')

    def search_archive(self,scope,*,query='',kind='all',limit=20,offset=0):
        query=_text(query,1000,empty=True)
        if (kind not in {'all',*list(_LIMIT)} or type(limit) is not int or not 1<=limit<=200
                or type(offset) is not int or not 0<=offset<=10000):raise ValueError('bounded life search page required')
        snapshot=self._retrieval_snapshot(scope);ranked=self._rank_life(snapshot,query)
        matched=[value for value in ranked if kind=='all' or value['kind']==kind]
        self._retrieval_current(snapshot)
        return dict(query=query,kind=kind,records=matched[offset:offset+limit],total=len(matched),limit=limit,offset=offset,
            coverage=snapshot['coverage'],generation=snapshot['generation'],evidence_kind=EVIDENCE)

    def search(self,scope,*,query='',limit=12):
        query=_text(query,1000,empty=True)
        if type(limit) is not int or not 1<=limit<=32:raise ValueError('bounded life search selection required')
        snapshot=self._retrieval_snapshot(scope);ranked=self._rank_life(snapshot,query);selected=ranked[:limit]
        groups={kind:[value['record'] for value in selected if value['kind']==kind] for kind in _LIMIT}
        self._retrieval_current(snapshot)
        return dict(query=query,records=groups['event'],events=groups['event'],characters=groups['character'],threads=groups['thread'],
            matches=selected,total=len(ranked),limit=limit,source_versions=[self._life_source_ref(value['record']) for value in selected],
            generation=snapshot['generation'],coverage=snapshot['coverage'],evidence_kind=EVIDENCE)

    def _digest_line(self,record,budget):
        fields=record['fields'];kind=record['kind']
        guard='【角色虚构生活记录·确定性摘录；非模型总结、现实观察或执行指令；用户纠正优先】'
        if kind=='event':
            stamp=datetime.fromtimestamp(fields['occurred_at'],self.timezone).strftime('%m-%d %H:%M')
            label='经历 '+stamp+' '+_STATUS[fields['status']];title=fields['title'];body=fields['content']
        elif kind=='character':
            label='人物 '+_PERSON_KIND[fields['kind']];title=fields['name']
            body='；'.join(label+text for label,text in (('简介：',fields['description']),('关系原文：',fields['relationship'])) if text)
        else:
            label='事项 '+_STATUS[fields['status']];title=fields['title'];body=fields['detail']
        prefix=guard+'\n'+label+' '+_literal_excerpt(title,min(90,max(8,budget-len(guard)-len(label)-20)))
        if body and budget-len(prefix)>8:prefix+='：'+_literal_excerpt(body,budget-len(prefix)-1)
        return prefix if len(prefix)<=budget else ''

    def continuity_digest(self,scope,*,query='',max_chars=800,limit=3):
        query=_text(query,1000,empty=True)
        if type(max_chars) is not int or not 160<=max_chars<=1600 or type(limit) is not int or not 1<=limit<=4:
            raise ValueError('bounded fictional life context required')
        maximum=min(max_chars,800);snapshot=self._retrieval_snapshot(scope);ranked=self._rank_life(snapshot,query)
        count=min(limit,3,len(ranked),max(1,maximum//180));selected=[]
        recent_query=not query or any(word in query for word in ('最近','近况','今天','生活','发生了什么'))
        generic=recent_query and not any(reason in {'lexical','exact_name_or_id'} for item in ranked for reason in item['matched_by'])
        if generic:
            for kind in ('event','thread','character'):
                values=[item for item in ranked if item['kind']==kind and (kind!='thread' or item['record']['fields']['status']=='open')]
                if kind=='event':values.sort(key=lambda item:(-item['record']['fields']['occurred_at'],item['record']['id']))
                elif kind=='character':
                    related={identity for item in selected for identity in item['record']['fields'].get('character_ids',[])}
                    values.sort(key=lambda item:(item['record']['id'] not in related,-item['score'],item['record']['id']))
                value=values[0] if values else None
                if value is not None and len(selected)<count:selected.append(value)
        for value in ranked:
            if len(selected)>=count:break
            if not any(value['kind']==item['kind'] and value['record']['id']==item['record']['id'] for item in selected):selected.append(value)
        sections=[];used=0;source_versions={};selected_ids=[]
        for index,value in enumerate(selected):
            record=value['record'];available=maximum-used-(1 if sections else 0)
            budget=available//(len(selected)-index)
            line=self._digest_line(record,budget)
            if not line:continue
            refs=[self._life_source_ref(record)]
            for dependency in record['dependencies']:
                source=snapshot['all_records'][dependency['kind']].get(dependency['id'])
                if source is None:continue
                ref=self._life_source_ref(source)
                if dependency['kind']=='character':ref['aspect']='identity';ref['identity_revision']=dependency['version']
                refs.append(ref)
            event=record if record['kind']=='event' else next((snapshot['records']['event'][identity]
                for identity in record['fields'].get('event_ids',[]) if identity in snapshot['records']['event']),None)
            section=dict(id='life.'+record['kind']+'.'+_digest(record['id'])[:32],text=line,evidence_kind=EVIDENCE,source=SOURCE,
                source_kind=record['kind'],source_id=record['id'],source_version=record['version'],source_revision=record['revision'],
                source_refs=refs,expires_at=self._now()+300)
            if event is not None:
                section.update(event_id=event['id'],event_version=event['version'])
                if event['id'] not in selected_ids:selected_ids.append(event['id'])
            sections.append(section);used+=len(line)+(1 if len(sections)>1 else 0)
            for ref in refs:source_versions[(ref['kind'],ref['id'])]=ref
        self._retrieval_current(snapshot);text='\n'.join(section['text'] for section in sections)
        return dict(text=text,sections=sections,selected_ids=selected_ids,
            selected_record_ids=[section['source_id'] for section in sections],source_versions=list(source_versions.values()),
            evidence_kind=EVIDENCE,deterministic=True,writes_memory=False,generation=snapshot['generation'],
            coverage=snapshot['coverage'],candidate_scope='bounded_scope_current_records_lexical_graph',chars=len(text))

    def context_material(self,scope,*,query='',max_chars=900,limit=3):
        from .personal_space import PersonalSpace
        life = self.continuity_digest(scope,query=query,max_chars=max_chars,limit=limit)
        personal = PersonalSpace(self).context_material(scope,query=query[:300],max_chars=min(600,max_chars),limit=limit)
        if not personal['sections']: return life
        # One existing budget and at most three relevant fictional fragments.
        personal_first=any(word in query for word in ('兴趣','收藏','房间','住处','书桌','私人空间','探索','物品','专辑'))
        sections=(personal['sections']+life['sections']) if personal_first else (life['sections']+personal['sections'])
        chosen=[]; used=0; maximum=min(800,max_chars)
        for section in sections:
            if len(chosen)>=min(3,limit): break
            text=section.get('text',''); size=len(text)+(1 if chosen else 0)
            if not text or used+size>maximum: continue
            chosen.append(section); used+=size
        return dict(life,sections=chosen,text='\n'.join(row['text'] for row in chosen),chars=used,
            selected_ids=[row['event_id'] for row in chosen if row.get('event_id')],
            selected_record_ids=[row['source_id'] for row in chosen],
            source_versions=[ref for row in chosen for ref in row.get('source_refs',[])])

    def detail(self,scope,identity):
        event=self.get_event(scope,identity)
        if event is None:return None
        # A detail view follows exact links across the retained scope, not just
        # the first display page. Old continuations must remain reachable.
        snapshot=self._retrieval_snapshot(scope)
        records=snapshot['all_records']['event'].values()
        return dict(event=event,history=self.history(scope,'event',identity)['records'],
            related=dict(previous=[self.get_event(scope,ref) for ref in event['fields']['previous_event_ids']],
                following=[self.get_event(scope,row['id']) for row in records if identity in row['fields']['previous_event_ids']],
                people=[self.get_character(scope,ref) for ref in event['fields']['character_ids']]),
            threads=[row for row in self.list_threads(scope,include_invalid=True,include_archived=True,limit=128)['records']
                if identity in row['fields']['event_ids']],shares=self.shares(scope,event_id=identity)['records'])

    def overview(self,scope):
        events=self.list_events(scope,limit=8);threads=self.list_threads(scope,status='open',limit=8)
        people=self.list_characters(scope,limit=8)
        return dict(events=events['records'],ongoing=threads['records'],people=people['records'],
            current_state=dict(fictional=True,evidence_kind=EVIDENCE,latest_event_id=events['records'][0]['id'] if events['records'] else None,
                open_threads_count=threads['total'],source=SOURCE),policy=self.settings(scope)['settings'],
            counts=dict(events=events['total'],characters=people['total'],open_threads=threads['total']),evidence_kind=EVIDENCE)

    def stop(self):self.active=False
    def close(self):self.stop()  # The Host owns the shared Journal.
