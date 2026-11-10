"""One read-only catalogue over existing scoped life and personal records."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from .autonomous_life import _LIMIT as LIFE_LIMIT, _query_terms, _normal, _text
from .personal_space import PersonalSpace, _LIMIT as PERSONAL_LIMIT, _NS as PERSONAL_NS

KINDS = tuple(LIFE_LIMIT) + tuple(PERSONAL_LIMIT)
MAX_OFFSET = sum(LIFE_LIMIT.values()) + sum(PERSONAL_LIMIT.values())


def _day(value, zone, *, end=False):
    if not value: return None
    if not isinstance(value,str) or len(value)!=10: raise ValueError('日期须为 YYYY-MM-DD')
    day=datetime.strptime(value,'%Y-%m-%d').date()
    if day.isoformat()!=value: raise ValueError('日期须为 YYYY-MM-DD')
    if end: day+=timedelta(days=1)
    return datetime.combine(day,time.min,tzinfo=zone).timestamp()


def search(life,scope,*,query='',kind='all',date_from='',date_to='',shared=False,limit=20,offset=0):
    """Date means occurrence for events, latest record update for other kinds.

    Counts and pagination follow filtering; in particular shared-only searches
    do not merely filter the current client page. No provider or model calls.
    """
    query=_text(query,200,empty=True)
    if kind not in ('all',*KINDS) or type(shared) is not bool: raise ValueError('无效的档案类型或分享筛选')
    if type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or not 0<=offset<=MAX_OFFSET:
        raise ValueError('档案分页超出范围')
    start,end=_day(date_from,life.timezone),_day(date_to,life.timezone,end=True)
    if start is not None and end is not None and start>=end: raise ValueError('开始日期不得晚于结束日期')
    scope=life._scope(scope);personal=PersonalSpace(life);terms=_query_terms(query);needle=_normal(query)
    with life.journal._lock:
        cache={};snapshot=life._retrieval_snapshot(scope,cache=cache)
        records=[record for rows in snapshot['all_records'].values() for record in rows.values()]
        scanned={k:len(v) for k,v in snapshot['all_records'].items()}
        for selected,maximum in PERSONAL_LIMIT.items():
            rows=life.journal.list(PERSONAL_NS[selected],scope,limit=maximum+1)
            if len(rows)>maximum: raise RuntimeError('私人资料超过支持的容量')
            scanned[selected]=len(rows)
            if kind not in ('all',selected) or shared: continue
            for row in rows:
                checked=personal._checked_row(scope,selected,row['key'],row)
                cache[('row',selected,row['key'])]=checked
                records.append(personal._project(scope,checked,cache))
        result=[]
        for row in records:
            if row['archived'] or row.get('deleted') or kind not in ('all',row['kind']):continue
            if shared and (row['kind']!='event' or not row.get('sharing',{}).get('ever_shared')):continue
            fields=row['fields'];stamp=fields.get('occurred_at') if row['kind']=='event' else row['updated_at']
            if start is not None and stamp<start or end is not None and stamp>=end:continue
            title=_normal(fields.get('title',fields.get('name','')))
            # Search human material only, never identity tuples, file paths or credentials.
            text=_normal(' '.join(str(fields.get(key,'')) for key in ('title','name','content','description','detail',
                'relationship','origin_note','questions','findings','explored','next_direction','goal')))
            hits=[term for term in terms if term in text]
            if query and not (needle in text or hits):continue
            score=(12 if needle and needle in title else 0)+(6 if needle and needle in text else 0)+len(hits)
            result.append(dict(kind=row['kind'],record=row,activity_at=stamp,
                time_kind='occurred_at' if row['kind']=='event' else 'updated_at',
                matched_by=['title' if needle and needle in title else 'content'] if query else ['recent'],score=score))
        result.sort(key=lambda row:(-row['score'],-row['activity_at'],row['record']['id']))
        life._retrieval_current(snapshot);life._scope(scope)
        return dict(records=result[offset:offset+limit],total=len(result),query=query,kind=kind,limit=limit,offset=offset,
            date_from=date_from,date_to=date_to,shared=shared,generation=snapshot['generation'],as_of=life._now(),
            time_basis='event_occurrence_other_record_update',timezone=str(life.timezone),
            coverage=dict(scanned=scanned,real_chats_searched=False,historical_versions_searched=False),
            read_only=True,evidence_kind='scoped_life_catalog')
