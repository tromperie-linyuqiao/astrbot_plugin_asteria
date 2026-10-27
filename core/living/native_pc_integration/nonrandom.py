"""Native date/weather reasons sharing the one existing proactive lane.

Only source state and receipts use the existing journal. There is no second
sender, queue, probability loop or model provider. A selected reason remains
bound to the shared lane's one immutable generated candidate and final gate.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import hashlib
import inspect
import re
from ..journal import JournalConflict
from ..models import canonical, Observation, EvidenceKind, private_scope
from ..native_important_dates import NativeImportantDates, relevant_dates, date_zone
from ..native_proactive_companion import NativeProactiveCompanion, event_id_for, NAMESPACE as PROACTIVE_NAMESPACE
from ..delivery_types import make_task

NAMESPACE = 'tls.native.pc.reasons.v1'
STATE = 'tls.native.pc.reason_state.v1'
_ACTIVE = {'generating', 'imaging', 'submitting', 'queued'}
_FINAL = {'acked', 'failed', 'dropped', 'blocked', 'duplicate', 'unknown'}


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def weather_observation(text):
    if type(text) is not str or not text.strip() or len(text) > 120 or any(ord(c) < 32 for c in text):
        raise ValueError('bounded actual weather summary required')
    category, severity = 'other', 1
    for candidate, value, markers in (
        ('thunder', 4, ('雷暴', '雷阵雨', '打雷', '雷电')),
        ('heavy_rain', 4, ('暴雨', '大暴雨', '特大暴雨', '大雨')),
        ('snow', 4, ('暴雪', '大雪', '中雪', '小雪', '雨夹雪', '降雪')),
        ('dust', 4, ('沙尘暴', '扬沙', '浮尘')),
        ('rain', 3, ('阵雨', '中雨', '小雨', '降雨', '下雨', '雨天')),
        ('fog', 3, ('大雾', '浓雾', '雾霾', '雾')),
        ('wind', 3, ('大风', '强风', '狂风', '阵风')),
        ('clear', 1, ('晴朗', '晴天', '晴')), ('cloud', 1, ('阴天', '多云', '阴'))):
        if any(marker in text.lower() for marker in markers): category, severity = candidate, value; break
    match = re.search(r'(-?\d+(?:\.\d+)?)\s*(?:°\s*c|℃|摄氏度)', text, flags=re.I)
    return dict(text=text, category=category, severity=severity, temperature=float(match[1]) if match else None)


def weather_change(before, after):
    old, new = before['category'], after['category']; kind, topic, score = '', '', 0
    labels = dict(thunder='突然开始打雷', heavy_rain='雨势突然变大', rain='外面开始下雨', snow='外面开始下雪',
        fog='外面突然起雾', wind='外面的风突然变大', dust='外面出现沙尘天气', clear='外面的天突然放晴', cloud='外面的天色明显转阴')
    wet = {'rain', 'heavy_rain', 'thunder', 'snow'}
    if old != new and new in labels:
        if old in wet and new in {'clear', 'cloud', 'other'}: kind, topic, score = 'precipitation_stopped', '外面的雨雪停了', 78
        elif new in {'thunder', 'heavy_rain', 'snow', 'dust'}: kind, topic, score = 'weather_to_' + new, labels[new], 92
        elif new in {'rain', 'fog', 'wind'}: kind, topic, score = 'weather_to_' + new, labels[new], 86
    a, b = before['temperature'], after['temperature']
    if a is not None and b is not None and abs(b-a) >= 5 and not kind:
        kind, topic, score = 'temperature_jump', '气温突然升高了' if b>a else '气温突然降下来了', 84 if abs(b-a)>=8 else 78
    if not kind: return None
    return dict(kind=kind, topic=topic, score=score, fingerprint=f'{kind}:{old}>{new}:{round(b, 1) if b is not None else "na"}')


class NativePCNonRandom:
    def __init__(self, proactive, dates, *, authorize, read_weather=None, read_special=None, clock=None, timezone='Asia/Shanghai'):
        if not isinstance(proactive, NativeProactiveCompanion) or not isinstance(dates, NativeImportantDates) or not callable(authorize):
            raise ValueError('existing proactive lane and date definitions required')
        if proactive.runtime.journal is not dates.journal: raise ValueError('one existing living journal required')
        if read_weather is not None and not callable(read_weather): raise ValueError('optional current weather reader required')
        self.proactive, self.dates, self.journal = proactive, dates, dates.journal
        self.authorize, self.read_weather, self.clock, self.timezone = authorize, read_weather, clock or dates.clock, timezone
        self.read_special = read_special
        date_zone(timezone); self.active = True; self._serial = asyncio.Lock()
        self._bindings = (proactive, dates, self.journal, authorize, read_weather, self.clock)

    def _allowed(self, scope, source):
        try:
            return (self.active and all(a is b for a,b in zip(self._bindings,(self.proactive,self.dates,self.journal,self.authorize,self.read_weather,self.clock)))
                and self.authorize(dict(scope), source) is True and self.proactive._allowed(scope))
        except Exception: return False

    def _put(self, ns, key, scope, data, revision, source):
        return self.journal.put(ns,key,scope,data,expected_revision=revision,authorize=lambda:self._allowed(scope,source))

    def _date_reason(self, scope):
        if not self._allowed(scope, 'important_date'): return None
        rows = self.dates.export(scope, include_archived=False)['records']
        entries = [dict(row['fields'], id=row['id'], revision=row['revision'], archived=row['archived']) for row in rows if row['provenance']['kind']=='user_explicit']
        for item in relevant_dates(entries, now=self.clock()):
            # One occurrence per real date, not one message every poll/day.
            key = digest(['important_date', scope, item['id'], item['next_date']])
            if self.journal.fetch(NAMESPACE,key,scope): continue
            topic = '已登记的重要日期：' + item['title'] + '；日期' + item['next_date'] + '；还有' + str(item['days_until']) + '天。'
            if item['note']: topic += '用户备注：' + item['note'] + '。'
            topic += '这是未来日期定义，只自然关心，不声称已经庆祝或发生。'
            return dict(key=key, source='important_date', topic=topic,
                evidence=dict(id=item['id'],revision=item['revision'],next_date=item['next_date']), score=item['priority'])
        return None

    async def _weather_reason(self, scope):
        if self.read_weather is None or not self._allowed(scope,'environment_change'): return None
        value = self.read_weather(dict(scope))
        if inspect.isawaitable(value): value = await value
        obs = value if isinstance(value,Observation) else Observation.from_dict(value)
        now = self.clock()
        if (obs.scope != scope or obs.observation_type != 'weather' or obs.evidence_kind != EvidenceKind.REAL_OBSERVATION
                or not obs.valid_at(now) or type(obs.payload) is not dict or set(obs.payload) != {'text'}):
            return None
        current = weather_observation(obs.payload['text']); state = self.journal.fetch(STATE,'weather',scope)
        old = state['data'] if state else None
        if old and old['observation_id'] == obs.observation_id: return None
        data = dict(observation_id=obs.observation_id, observation=current, observed_at=obs.observed_at,
            last_offered_at=old['last_offered_at'] if old else 0., fingerprints=old['fingerprints'] if old else {})
        self._put(STATE,'weather',scope,data,state['revision'] if state else 0,'environment_change')
        if old is None or obs.observed_at <= old['observed_at']: return None
        change = weather_change(old['observation'],current)
        hour = datetime.fromtimestamp(now,date_zone(self.timezone)).hour
        if not change or not 6 <= hour < 23: return None
        fingerprint = change['fingerprint']; history = data['fingerprints']
        if (now - history.get(fingerprint,0) < 5400 or now - data['last_offered_at'] < 1200 and change['score'] < 90): return None
        key = digest(['environment_change',scope,obs.observation_id,fingerprint])
        if self.journal.fetch(NAMESPACE,key,scope): return None
        topic = ('已观察到天气变化：' + current['text'] + '；' + change['topic']
            + '。只依据这次观测自然关心，不虚构用户在户外，不扩写预报。')
        return dict(key=key,source='environment_change',topic=topic,
            evidence=dict(observation_id=obs.observation_id,expires_at=obs.expires_at,fingerprint=fingerprint),score=change['score'])

    async def _current_reason(self, scope, reason):
        if not self._allowed(scope,reason['source']): return False
        if reason['source'] == 'special_calendar':
            current = await self._special_reason(scope, include_existing=True)
            return bool(current and all(current[k] == reason[k] for k in ('key', 'source', 'topic', 'evidence')))
        if reason['source'] == 'important_date':
            row = self.dates.get(scope,reason['evidence']['id'])
            return bool(row and row['provenance']['kind']=='user_explicit' and row['revision']==reason['evidence']['revision'] and not row['archived'] and row['fields']['enabled']
                and any(item['next_date']==reason['evidence']['next_date'] for item in relevant_dates([dict(row['fields'],archived=row['archived'])],now=self.clock())))
        if reason['source'] != 'environment_change' or self.read_weather is None or self.clock() >= reason['evidence']['expires_at']: return False
        value = self.read_weather(dict(scope))
        if inspect.isawaitable(value): value = await value
        obs = value if isinstance(value,Observation) else Observation.from_dict(value)
        return (self._allowed(scope,'environment_change') and obs.scope==scope and obs.observation_type=='weather'
            and obs.evidence_kind==EvidenceKind.REAL_OBSERVATION and obs.observation_id==reason['evidence']['observation_id'] and obs.valid_at(self.clock()))

    async def tick(self, scope):
        scope = private_scope(scope)
        async with self._serial:
            pointer = self.journal.fetch(STATE,'active_reason',scope)
            if pointer:
                prior = self.journal.fetch(NAMESPACE,pointer['data']['key'],scope)
                if prior and prior['data']['phase'] not in _FINAL:
                    return await self._reconcile(scope,prior)
            reason = None; prior = None
            if pointer:
                prior = self.journal.fetch(NAMESPACE,pointer['data']['key'],scope)
                if prior and prior['data']['phase']=='blocked' and prior['data']['engine_event_id'] != event_id_for(self.clock()):
                    if await self._current_reason(scope,prior['data']):
                        reason = {key:prior['data'][key] for key in ('key','source','topic','evidence','score')}
            reason = reason or await self._special_reason(scope) or self._date_reason(scope) or await self._weather_reason(scope)
            if reason is None: return dict(state='idle',reason='no_current_nonrandom_reason')
            existing = await self.proactive._fetch(scope); event_id = event_id_for(self.clock())
            if existing and (existing['data']['phase'] in _ACTIVE or existing['data']['event_id']==event_id):
                return dict(state='deferred',reason='existing_shared_lane_event_retained')
            if not await self._current_reason(scope,reason): return dict(state='blocked',reason='source_no_longer_current')
            work = dict(reason,phase='attempting',engine_event_id=event_id,
                task_id=make_task(scope,event_id,text='identity',now=self.clock())['id'],started_at=self.clock())
            previous = self.journal.fetch(NAMESPACE,reason['key'],scope)
            row = self._put(NAMESPACE,reason['key'],scope,work,previous['revision'] if previous else 0,reason['source'])
            self._put(STATE,'active_reason',scope,dict(key=reason['key']),pointer['revision'] if pointer else 0,reason['source'])
            if reason['source'] == 'special_calendar':
                result = await self.proactive.tick(scope,reason['topic'],text_only=True,expires_at=reason['evidence']['expires_at'])
            else:
                result = await self.proactive.tick(scope,reason['topic'])
            actual = await self.proactive._fetch(scope)
            if actual and actual['data']['event_id']==event_id and actual['data'].get('signature')==digest([scope,event_id,reason['topic']]):
                work.update(phase=actual['data']['phase'],task_id=actual['data']['task_id'])
            elif result.get('state') in {'blocked','disabled','busy'}:
                # Known no-admission remains an audit receipt. Another source
                # can be considered on a later host tick, never a second send.
                work['phase']='blocked'
            else: work['phase']='unknown'
            self._put(NAMESPACE,reason['key'],scope,work,row['revision'],reason['source'])
            if reason['source']=='environment_change' and work['phase']!='blocked':
                state=self.journal.fetch(STATE,'weather',scope)
                if state:
                    value=dict(state['data']); history={key:stamp for key,stamp in value['fingerprints'].items() if self.clock()-stamp<5400}
                    history[reason['evidence']['fingerprint']]=self.clock()
                    value.update(last_offered_at=self.clock(),fingerprints=history)
                    self._put(STATE,'weather',scope,value,state['revision'],'environment_change')
            return dict(result,source=reason['source'],source_event_id=reason['key'])

    async def _reconcile(self, scope, row):
        work=dict(row['data']); source=work['source']
        if not self._allowed(scope,source): return dict(state='blocked',reason='source_execution_not_owned')
        actual=await self.proactive._fetch(scope)
        if not actual or actual['data']['event_id']!=work['engine_event_id'] or actual['data'].get('signature')!=digest([scope,work['engine_event_id'],work['topic']]):
            work['phase']='unknown'; self._put(NAMESPACE,work['key'],scope,work,row['revision'],source)
            return dict(state='unknown',reason='shared_lane_result_unresolved',automatic_retry=False)
        result=await self.proactive._reconcile(scope,actual)
        latest=await self.proactive._fetch(scope); work.update(phase=latest['data']['phase'],task_id=latest['data']['task_id'])
        self._put(NAMESPACE,work['key'],scope,work,row['revision'],source)
        return dict(result,source=source,source_event_id=work['key'])

    def owns_task(self, scope, task):
        try:
            scope=private_scope(scope); pointer=self.journal.fetch(STATE,'active_reason',scope)
            row=self.journal.fetch(NAMESPACE,pointer['data']['key'],scope) if pointer else None
            if not row or task.get('scope')!=scope: return False
            if row['data']['task_id']==task.get('id'): return True
            # A clock bucket can turn between this orchestrator and the shared
            # lane's first await. Keep that matching topic routed to this gate
            # (which denies the mismatched ID), never bypass source validation.
            actual=self.journal.fetch(PROACTIVE_NAMESPACE,'pending',scope)
            return bool(actual and actual['data']['task_id']==task.get('id')
                and actual['data']['signature']==digest([scope,actual['data']['event_id'],row['data']['topic']]))
        except Exception: return False

    async def delivery_allowed(self, scope, task):
        """Task-aware source freshness; the existing lane remains the sender gate."""
        try:
            scope=private_scope(scope); pointer=self.journal.fetch(STATE,'active_reason',scope)
            if not pointer: return False
            row=self.journal.fetch(NAMESPACE,pointer['data']['key'],scope)
            if not row or row['data']['task_id']!=task.get('id') or row['data']['phase'] not in _ACTIVE|{'attempting'}: return False
            return await self._current_reason(scope,row['data'])
        except Exception: return False

    def stop(self): self.active=False
    async def _special_reason(self, scope, *, include_existing=False):
        if not callable(self.read_special) or not self._allowed(scope, 'special_calendar'):
            return None
        value = self.read_special(dict(scope))
        if inspect.isawaitable(value): value = await value
        if not value or value.get('source') != 'special_calendar': return None
        if not include_existing and self.journal.fetch(NAMESPACE, value['key'], scope): return None
        return value

    def diagnostics(self): return dict(active=self.active,source_kinds=['important_date','environment_change','special_calendar'],
        independent_scheduler=False,uses_existing_proactive_lane=True,grants_authority=False)
