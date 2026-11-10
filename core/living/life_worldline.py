"""Bounded, source-backed views over the existing fictional life journal.

This module does not infer edges from names/time, mutate preferences, run a
model, or store a parallel graph. Historical changes are inspection metadata,
never an independent source of current facts.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy

from .autonomous_life import EVIDENCE, _NS as LIFE_NS, _LIMIT as LIFE_LIMIT, _digest, _id
from .personal_space import PersonalSpace, KINDS, _NS as PERSONAL_NS, _LIMIT as PERSONAL_LIMIT

LIMITS = dict(nodes=60, edges=128, depth=2, growth=12, history_per_record=6)
GROWTH_FIELDS = dict(character=('relationship',), interest=('attention','status','next_direction'),
                     exploration=('findings','status'))


def _node(record):
    fields=record['fields']
    return dict(id=record['id'],kind=record['kind'],title=fields.get('title',fields.get('name',''))[:120],
        summary=next((fields.get(key,'') for key in ('content','description','detail','relationship') if fields.get(key)), '')[:240],
        status=fields.get('status',fields.get('attention','')),valid=record['valid'],
        archived=record['archived'],revision=record['revision'],version=record['version'],
        evidence_kind=EVIDENCE,invalid_dependencies=deepcopy(record.get('invalid_dependencies',record.get('invalid_reasons',[]))),
        occurred_at=fields.get('occurred_at'),source_kind=record.get('source',{}).get('kind',''))


def _links(record):
    """The owning record is the provenance of every returned edge."""
    identity=record['id'];kind=record['kind'];fields=record['fields']
    for previous in fields.get('previous_event_ids',[]):yield previous,identity,'continues'
    for person in fields.get('character_ids',[]):yield person,identity,'involves'
    for event in fields.get('event_ids',[]):yield event,identity,'grounds'
    if fields.get('interest_id'):yield fields['interest_id'],identity,'explores' if kind=='exploration' else 'collects'
    if fields.get('space_id'):yield fields['space_id'],identity,'contains'


def project(life,scope,event_id,personal=None):
    """Read an explicit event's two-hop neighborhood, including review state.

    The established per-scope ledger limits bound scans. Shared caches avoid
    rechecking the same life source repeatedly. Private collection provider
    metadata is never copied into this projection. No real chat is searched.
    """
    scope=life._scope(scope);event_id=_id(event_id)
    personal=PersonalSpace(life) if personal is None else personal
    if not isinstance(personal,PersonalSpace) or personal.life is not life:
        raise ValueError('same scoped personal-space service required')
    with life.journal._lock:
        raw={};cache={};counts={}
        for kind,maximum in {**LIFE_LIMIT,**PERSONAL_LIMIT}.items():
            namespace=LIFE_NS[kind] if kind in LIFE_LIMIT else PERSONAL_NS[kind]
            rows=life.journal.list(namespace,scope,limit=maximum+1)
            if len(rows)>maximum:raise RuntimeError('life worldline exceeds supported scope capacity')
            counts[kind]=len(rows)
            for row in rows:
                if kind in LIFE_LIMIT:
                    life._checked_row(kind,scope,row['key'],row)
                    cache[('row',kind,row['key'])]=row
                # Deleted private items stay in retained provenance, not here.
                if row['data'].get('deleted'):continue
                raw[row['key']]=(kind,row)
        root=raw.get(event_id)
        if root is None or root[0]!='event':raise KeyError(event_id)
        all_edges=[];neighbors=defaultdict(set);seen=set()
        for kind,row in raw.values():
            data=row['data']
            for source,target,relation in _links(data):
                if source not in raw or target not in raw or source==target:continue
                key=(source,target,relation,data['id'])
                if key in seen:continue
                seen.add(key)
                all_edges.append(dict(zip(('from','to','relation'),(source,target,relation)),
                    source_id=data['id'],source_kind=kind,source_version=data['version']))
                neighbors[source].add(target);neighbors[target].add(source)
        distance={event_id:0};queue=deque([event_id])
        while queue:
            identity=queue.popleft()
            if distance[identity]>=LIMITS['depth']:continue
            for target in sorted(neighbors[identity]):
                if target not in distance:
                    distance[target]=distance[identity]+1;queue.append(target)
        ordered=sorted(distance,key=lambda identity:(distance[identity],-raw[identity][1]['updated_at'],identity))
        chosen=ordered[:LIMITS['nodes']];selected=set(chosen);projected={};personal_cache={}
        for identity in chosen:
            kind,row=raw[identity]
            value=life._project(scope,row,cache,verify_memory=False) if kind in LIFE_LIMIT else personal._project(scope,row,personal_cache)
            projected[identity]=value
        relevant=[edge for edge in all_edges if edge['from'] in distance and edge['to'] in distance]
        selected_edges=[edge for edge in relevant if edge['from'] in selected and edge['to'] in selected]
        selected_edges.sort(key=lambda edge:(max(distance[edge['from']],distance[edge['to']]),edge['from'],edge['to'],edge['relation']))
        edges=[]
        for edge in selected_edges[:LIMITS['edges']]:
            valid=all(projected[identity]['valid'] for identity in (edge['from'],edge['to'],edge['source_id']))
            edges.append(dict(edge,valid=valid))
        growth=[];history_truncated=False;eligible_changes=0
        for identity in chosen:
            record=projected[identity];kind=record['kind']
            if kind not in GROWTH_FIELDS or not record['valid']:continue
            history=(life.history(scope,kind,identity,limit=LIMITS['history_per_record']) if kind in LIFE_LIMIT
                else personal.history(scope,kind,identity,limit=LIMITS['history_per_record']))
            history_truncated |= history['total']>LIMITS['history_per_record']
            newer=record
            for prior in history['records']:
                older=prior['snapshot'];refs=newer['fields'].get('event_ids',[])
                # A changed relationship/interest must cite current valid life
                # sources. Corrected old dependencies are inspection history,
                # not a current growth claim.
                invalid=(life._invalid(scope,newer,cache=cache) if kind in LIFE_LIMIT
                    else personal._invalid(scope,newer,cache=personal_cache))
                if refs and not invalid and not newer.get('archived') and not newer.get('deleted'):
                    for field in GROWTH_FIELDS[kind]:
                        before,after=older['fields'].get(field),newer['fields'].get(field)
                        if before==after:continue
                        eligible_changes+=1
                        growth.append(dict(id=identity,kind=kind,title=_node(record)['title'],field=field,
                            before=deepcopy(before),after=deepcopy(after),revision=newer.get('revision'),
                            version=newer['version'],source_event_ids=list(refs),
                            source_event_refs=[dict(id=ref['id'],version=ref['version'])
                                for ref in newer.get('dependencies',[]) if ref['kind']=='event'],
                            valid=True,changed_at=newer.get('last_edit',{}).get('at',newer.get('updated_at')),
                            evidence_kind=EVIDENCE,current_value=deepcopy(record['fields'].get(field)),
                            history=True))
                newer=dict(older,revision=prior['revision'])
        growth.sort(key=lambda row:(-(row['changed_at'] or 0),row['id'],row['field']))
        growth=growth[:LIMITS['growth']]
        life._scope(scope)
        missing_nodes=max(0,len(distance)-len(chosen));missing_edges=len(relevant)-len(edges)
        return dict(event_id=event_id,root_id=event_id,nodes=[_node(projected[identity]) for identity in chosen],
            edges=edges,growth=growth,limits=dict(LIMITS),generation=_digest([
                [kind,identity,row['revision']] for identity,(kind,row) in sorted(raw.items())]),
            coverage=dict(scanned=counts,matched_nodes=len(distance),omitted_nodes=missing_nodes,
                omitted_edges=missing_edges,invalid_nodes=sum(not record['valid'] for record in projected.values()),
                growth_omitted=max(0,eligible_changes-len(growth)),history_truncated=history_truncated,
                truncated=bool(missing_nodes or missing_edges or eligible_changes>len(growth) or history_truncated),
                method='explicit_reference_neighborhood',real_chats_searched=False),
            evidence_kind=EVIDENCE,fictional=True,read_only=True)
