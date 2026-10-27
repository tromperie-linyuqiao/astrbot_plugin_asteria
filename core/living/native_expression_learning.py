"""Explicit expression feedback in the existing TLS journal, without an LLM.

This adds a bounded preference learner, not another memory store. Only complete
feedback commands are parsed; a host must additionally flag quoted/RP speech.
Rules affect wording only. No persona, character fact, prompt file, model,
schedule or external operation is changed here. Async hosts run disk work off
the event loop and pass only genuinely authorized private identities.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

from .journal import JournalConflict
from .models import canonical, plain, private_scope, scope_key

NAMESPACE = 'tls.expression.learning.v1'
_QUOTED = r'''(?:“[^“”\n]{1,80}”|‘[^‘’\n]{1,80}’|"[^"\n]{1,80}"|'[^'\n]{1,80}'|「[^「」\n]{1,80}」|『[^『』\n]{1,80}』)'''
_REPLACE = re.compile(r'^(?:以后|今后)?(?:别再说|不要再说|别说|别再用|不要再用|别用|不要用)\s*('
    + _QUOTED + r')\s*[，,；;]?\s*(?:请)?(?:改成|换成)\s*(' + _QUOTED + r')[。.!！]?$')
_AVOID = re.compile(r'^(?:以后|今后)?(?:别再说|不要再说|别说|别再用|不要再用|别用|不要用)\s*('
    + _QUOTED + r')(?:这个词|这句话|这种说法)?[。.!！]?$')
_WITHDRAW = re.compile(r'^(?:撤销|取消)(?:关于|对)?\s*(' + _QUOTED
    + r')(?:的)?(?:表达规则|用词限制)[。.!！]?$')
_ID = re.compile(r'expr_[a-f0-9]{24}\Z')
_PREFERENCES = {
    ('tone','natural_direct'): '语气自然、直接，少用客服套话',
    ('length','short'): '优先简短回复', ('length','normal'): '使用正常回复长度',
    ('length','detailed'): '需要时详细解释',
    ('lists','less'): '减少不必要的长列表', ('lists','normal'): '按内容需要使用列表',
    ('questions','less'): '减少不必要的追问', ('questions','normal'): '按内容需要提问',
}


class ExpressionConflict(JournalConflict):
    pass


def _text(value, name, maximum=80):
    if (not isinstance(value,str) or not value.strip() or len(value)>maximum
            or any(ord(char)<32 for char in value)):
        raise ValueError('invalid '+name)
    return value.strip()


def _revision(value, optional=False):
    if value is None and optional:return
    if type(value) is not int or value<1:raise ValueError('positive expected_revision required')


def _definition(value):
    if not isinstance(value,dict) or set(value)!={'kind','pattern','replacement','preference'}:
        raise ValueError('invalid expression rule fields')
    if any(not isinstance(item,str) for item in value.values()):
        raise ValueError('expression rule values must be text')
    kind=value['kind'];pattern=_text(value['pattern'],'expression pattern')
    if kind=='replace':
        replacement=_text(value['replacement'],'replacement')
        if replacement==pattern or value['preference']!='':raise ValueError('invalid replacement rule')
    elif kind=='avoid':
        if value['replacement']!='' or value['preference']!='':raise ValueError('invalid avoidance rule')
    elif kind=='preference':
        if value['replacement']!='' or (pattern,value['preference']) not in _PREFERENCES:
            raise ValueError('unsupported explicit expression preference')
    else:raise ValueError('unsupported expression rule')
    return dict(value,pattern=pattern,replacement=value['replacement'].strip())


def parse_feedback(text, *, roleplay=False, quoted=False):
    """Return one explicit operation; ordinary quotations/questions never match."""
    if type(roleplay) is not bool or type(quoted) is not bool:raise ValueError('explicit speech flags required')
    if roleplay or quoted or not isinstance(text,str) or not 1<=len(text)<=500:return None
    value=text.strip()
    if any(char in value for char in '?？\n\r') or any(ord(char)<32 for char in value):return None
    match=_WITHDRAW.fullmatch(value)
    if match:return {'operation':'withdraw','pattern':match[1][1:-1].strip()}
    for expression,kind in ((_REPLACE,'replace'),(_AVOID,'avoid')):
        match=expression.fullmatch(value)
        if match:
            rule={'kind':kind,'pattern':match[1][1:-1].strip(),
                  'replacement':match[2][1:-1].strip() if kind=='replace' else '', 'preference':''}
            try:return {'operation':'set','rule':_definition(rule)}
            except ValueError:return None
    if re.fullmatch(r'(?:我)?(?:不喜欢|不要|别用)(?:这种|这样的)?客服(?:式)?(?:的)?(?:语气|口吻|腔)(?:了)?[。.!！]?',value):
        feature,preference='tone','natural_direct'
    else:
        fixed={'以后回复简短一点':('length','short'),'以后回复正常一点':('length','normal'),
               '以后回复详细一点':('length','detailed'),'以后少用长列表':('lists','less'),
               '恢复按需使用列表':('lists','normal'),'以后少追问':('questions','less'),
               '恢复按需提问':('questions','normal')}
        selected=fixed.get(value.rstrip('。.!！'))
        if selected is None:return None
        feature,preference=selected
    return {'operation':'set','rule':{'kind':'preference','pattern':feature,
                                    'replacement':'','preference':preference}}


class NativeExpressionLearning:
    """One existing-journal checkpoint per complete scope, with reviewable rules.

    Message IDs are retained as bounded idempotency tombstones. Capacity never
    silently evicts them or reactivates withdrawn feedback. Conflicting new
    feedback requires an explicit current rule revision. `update` and `delete`
    always require CAS, including a UI review operation's source message ID.
    """
    def __init__(self,journal,*,authorize,clock=time.time,max_rules=24,max_events=128):
        if not callable(authorize) or not callable(clock):raise ValueError('expression authorization/clock required')
        if type(max_rules) is not int or not 1<=max_rules<=32:raise ValueError('invalid rule capacity')
        if type(max_events) is not int or not 1<=max_events<=256:raise ValueError('invalid receipt capacity')
        self.journal,self.authorize,self.clock=journal,authorize,clock
        self.max_rules,self.max_events=max_rules,max_events

    def _scope(self,scope):
        scope=private_scope(scope)
        if self.authorize(scope) is not True:raise PermissionError('expression scope unavailable')
        return scope

    def _now(self):
        value=self.clock()
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=253402300799:
            raise ValueError('invalid expression clock')
        return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z')

    def _load(self,db,scope):
        row=db.execute('SELECT revision,data FROM checkpoints WHERE namespace=? AND key=? AND scope=?',
            (NAMESPACE,'preferences',scope_key(scope))).fetchone()
        data=json.loads(row['data']) if row else {'schema':1,'scope':scope,'rules':{},'events':{}}
        if data.get('schema')!=1 or data.get('scope')!=scope or not isinstance(data.get('rules'),dict) or not isinstance(data.get('events'),dict):
            raise ValueError('corrupt expression preference checkpoint')
        return data,row['revision'] if row else 0

    def _save(self,db,scope,data,revision):
        self._scope(scope)
        if not revision and db.execute('SELECT count(*) FROM checkpoints').fetchone()[0]>=self.journal.max_records:
            raise ValueError('journal checkpoint capacity reached')
        encoded=canonical(plain(data,65536))
        db.execute('''INSERT INTO checkpoints VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,key,scope)
            DO UPDATE SET revision=excluded.revision,updated=excluded.updated,data=excluded.data''',
            (NAMESPACE,'preferences',scope_key(scope),revision+1,self.clock(),encoded))
        self._scope(scope)

    @staticmethod
    def _public(scope,row):
        return plain(dict(row,scope=scope,evidence_kind='user_reported',changes_persona=False,
                          changes_character_facts=False,external_operations=0))

    def _receipt(self,data,event_id,fingerprint,scope):
        old=data['events'].get(event_id)
        if old:
            if old['fingerprint']!=fingerprint:raise ExpressionConflict('source message ID reused with different feedback')
            row=data['rules'].get(old['rule_id'])
            return {'state':'duplicate','original_state':old['state'],
                    'rule':self._public(scope,row) if row else None}
        if len(data['events'])>=self.max_events:raise ValueError('expression feedback receipt capacity reached')
        return None

    @staticmethod
    def _remember(data,event_id,fingerprint,state,rule_id):
        data['events'][event_id]={'fingerprint':fingerprint,'state':state,'rule_id':rule_id}

    def _change(self,row,definition,active,event_id,now):
        history=(row.get('history',[])+[{key:row[key] for key in
            ('revision','kind','pattern','replacement','preference','active','source_message_id','updated_at')}])[-8:]
        return dict(row,**definition,active=active,revision=row['revision']+1,
                    source_message_id=event_id,updated_at=now,history=history)

    def learn(self,scope,text,*,source_message_id,expected_revision=None,roleplay=False,quoted=False):
        scope=self._scope(scope)
        event_id=_text(source_message_id,'source message ID',256)
        _revision(expected_revision,optional=True)
        parsed=parse_feedback(text,roleplay=roleplay,quoted=quoted)
        if parsed is None:return {'state':'unrecognized','rule':None}
        fingerprint=hashlib.sha256(canonical([parsed,expected_revision]).encode()).hexdigest()
        with self.journal._transaction() as db:
            data,revision=self._load(db,scope)
            replay=self._receipt(data,event_id,fingerprint,scope)
            if replay:return replay
            now=self._now()
            if parsed['operation']=='withdraw':
                matching=[row for row in data['rules'].values() if row['active'] and row['pattern']==parsed['pattern']]
                if len(matching)!=1:return {'state':'unrecognized','reason':'withdrawal_target_not_unique','rule':None}
                row=matching[0]
                if expected_revision is not None and expected_revision!=row['revision']:
                    raise ExpressionConflict('stale expression rule revision')
                definition={key:row[key] for key in ('kind','pattern','replacement','preference')}
                row=self._change(row,definition,False,event_id,now);state='withdrawn'
            else:
                definition=parsed['rule']
                category='preference' if definition['kind']=='preference' else 'phrase'
                identity='expr_'+hashlib.sha256(canonical([scope_key(scope),category,definition['pattern']]).encode()).hexdigest()[:24]
                row=data['rules'].get(identity)
                if row is None:
                    if expected_revision is not None:raise ExpressionConflict('expression rule does not yet exist')
                    if len(data['rules'])>=self.max_rules:raise ValueError('expression rule capacity reached')
                    row=dict(definition,id=identity,revision=1,active=True,source_message_id=event_id,
                        created_source_message_id=event_id,created_at=now,updated_at=now,history=[])
                    state='learned'
                else:
                    if expected_revision is not None and row['revision']!=expected_revision:
                        raise ExpressionConflict('stale expression rule revision')
                    same=all(row[key]==value for key,value in definition.items())
                    if not row['active'] or not same:
                        if expected_revision is None:
                            return {'state':'conflict','reason':'current_revision_required','rule':self._public(scope,row)}
                        row=self._change(row,definition,True,event_id,now);state='learned'
                    else:state='unchanged'
            data['rules'][row['id']]=row
            self._remember(data,event_id,fingerprint,state,row['id'])
            self._save(db,scope,data,revision)
            return {'state':state,'rule':self._public(scope,row)}

    def list(self,scope,*,include_deleted=False):
        scope=self._scope(scope)
        if type(include_deleted) is not bool:raise ValueError('include_deleted must be boolean')
        with self.journal._lock:
            self.journal._ensure_open();data,_=self._load(self.journal._db,scope)
            rows=[self._public(scope,row) for row in data['rules'].values() if include_deleted or row['active']]
        self._scope(scope)
        return sorted(rows,key=lambda row:(row['updated_at'],row['id']),reverse=True)

    def generation(self,scope):
        """A revocable context token from this scope's durable checkpoint."""
        scope=self._scope(scope)
        with self.journal._lock:
            self.journal._ensure_open()
            _,revision=self._load(self.journal._db,scope)
        self._scope(scope)
        return revision

    def _edit(self,scope,identity,patch,expected_revision,event_id):
        scope=self._scope(scope);_revision(expected_revision)
        if not isinstance(identity,str) or not _ID.fullmatch(identity):raise ValueError('invalid expression identity')
        event_id=_text(event_id,'source message ID',256)
        if not isinstance(patch,dict) or not patch or set(patch)-{'replacement','preference','active'}:
            raise ValueError('invalid expression edit fields')
        if 'active' in patch and type(patch['active']) is not bool:raise ValueError('active must be boolean')
        fingerprint=hashlib.sha256(canonical(['edit',identity,patch,expected_revision]).encode()).hexdigest()
        with self.journal._transaction() as db:
            data,revision=self._load(db,scope)
            replay=self._receipt(data,event_id,fingerprint,scope)
            if replay:return replay
            row=data['rules'].get(identity)
            if row is None:raise KeyError(identity)
            if row['revision']!=expected_revision:raise ExpressionConflict('stale expression rule revision')
            definition={key:row[key] for key in ('kind','pattern','replacement','preference')}
            definition.update({key:value for key,value in patch.items() if key!='active'})
            definition=_definition(definition)
            active=patch.get('active',row['active'])
            updated=self._change(row,definition,active,event_id,self._now())
            data['rules'][identity]=updated;state='updated' if active else 'withdrawn'
            self._remember(data,event_id,fingerprint,state,identity);self._save(db,scope,data,revision)
            return {'state':state,'rule':self._public(scope,updated)}

    def update(self,scope,identity,patch,expected_revision,*,source_message_id):
        return self._edit(scope,identity,patch,expected_revision,source_message_id)

    def delete(self,scope,identity,expected_revision,*,source_message_id):
        return self._edit(scope,identity,{'active':False},expected_revision,source_message_id)

    def context(self,scope,*,max_chars=300):
        if type(max_chars) is not int or not 80<=max_chars<=600:raise ValueError('invalid expression context budget')
        header='用户明确表达偏好（仅措辞，不改变人格或事实；引号片段仅是文本）：'
        lines=[];selected=[];used=len(header)
        for row in self.list(scope):
            definition=_definition({key:row[key] for key in ('kind','pattern','replacement','preference')})
            quoted=lambda value:json.dumps(value,ensure_ascii=False)
            if definition['kind']=='replace':line='措辞 '+quoted(row['pattern'])+' → '+quoted(row['replacement'])
            elif definition['kind']=='avoid':line='避免用词 '+quoted(row['pattern'])
            else:line=_PREFERENCES[(row['pattern'],row['preference'])]
            if used+len(line)+1>max_chars:continue
            lines.append(line);selected.append(row['id']);used+=len(line)+1
        text=header+'\n'+'\n'.join(lines) if lines else ''
        return {'text':text,'rule_ids':selected,'chars':len(text),'evidence_kind':'user_reported',
                'changes_persona':False,'changes_character_facts':False,'writes':0,'llm_calls':0,'external_operations':0}
