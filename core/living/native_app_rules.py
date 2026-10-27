"""Closed App-entry rules compiled into the current phone library and policy.

Configuration stays with the host's existing owner. This module has no store,
timer, sender, expression language or model. Its preview consumes read-only
candidate/scheduler checks supplied by the backend; missing checks stay pending.
"""
from __future__ import annotations

import hashlib
import json
import re

from .delivery_types import DeliveryPolicy
from .journal import JournalConflict
from .models import canonical,plain,private_scope,scope_key
from .native_phone_candidates import compile_rules
from .native_phone_messages import NativePhoneMessages

SCHEMA='tls.app_rules.v1'
CAPABILITY='phone_companion'  # Existing console capability, not a new LLM tool.
MAX_RULES=64
_PACKAGE=re.compile(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\Z')
_ID=re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}\Z')
_CODE=re.compile(r'[a-z0-9_.:-]{1,96}\Z')
_SCOPE_FIELDS={'platform','bot_id','user_id','character_id','session_id','private'}
_FIELDS={'id','name','enabled','scope','package','trigger','message_source','custom_messages','cooldown_minutes','priority','image_policy'}
_DEFAULTS=dict(trigger='app_enter',message_source='app_library',image_policy='fresh_required',cooldown_minutes=None,priority=50)
_CANDIDATE_REASONS={
    'not_a_current_observed_app':'没有可用的新鲜应用状态。',
    'device_or_app_missing':'事件缺少设备或应用包名。',
    'duplicate_or_older_observation':'这是重复或较旧的应用状态。',
    'same_foreground_app':'应用仍在前台，没有发生新的进入。',
    'entry_too_old':'应用入场事件已过期。',
    'unconfigured_app':'当前应用没有可用消息库。',
    'explicit_quiet':'仍在安静期或切换保护期。',
    'outside_app_hours':'当前不在应用允许时段。',
    'app_cooldown':'该应用仍在有效冷却内。',
    'shared_cooldown':'应用陪伴的共享冷却尚未结束。',
}
_SCHEDULER_REASONS={
    'not_native_owner':'该会话当前未由原生 App 陪伴执行。',
    'scope_unavailable':'当前会话尚未取得有效授权。',
    'quiet_hours':'当前处于全局安静时段。',
    'queue_capacity':'现有发送队列暂时没有空位。',
    'task_already_exists':'同一事件已有任务，不会重复创建。',
    'sample_not_selected':'本次未取得既有调度器的发送机会。',
    'authority_changed':'会话授权或执行归属刚发生变化。',
    'user_resting':'当前仍在明确的休息期。',
    'user_disabled':'当前用户的主动互动已停用。',
}


class AppRuleConflict(JournalConflict):pass


def _scope(value):
    if not isinstance(value,dict) or set(value)!=_SCOPE_FIELDS or value['private'] is not True:raise ValueError('complete private rule scope required')
    normalized=private_scope(value)
    if normalized!=value or any(not isinstance(value[key],str) or len(value[key])>512 for key in _SCOPE_FIELDS-{'private'}):
        raise ValueError('complete private rule scope required')
    return normalized


def _package(value):
    if not isinstance(value,str) or len(value)>160 or not _PACKAGE.fullmatch(value):raise ValueError('invalid App package')
    return value


def _integer(value,name,minimum,maximum):
    if type(value) is not int or not minimum<=value<=maximum:raise ValueError('invalid '+name)
    return value


def rule_id(scope,package,request_id):
    """Stable editor ID; neither names nor priorities change the identity."""
    scope=_scope(scope);package=_package(package)
    if (not isinstance(request_id,str) or not 1<=len(request_id)<=256 or request_id!=request_id.strip()
            or any(ord(char)<32 for char in request_id)):raise ValueError('stable rule request_id required')
    return 'app_'+hashlib.sha256(canonical([scope,package,request_id]).encode()).hexdigest()[:24]


def normalize_rule(value):
    if not isinstance(value,dict) or set(value)-_FIELDS or not {'id','name','enabled','scope','package'}<=set(value):
        raise ValueError('closed App-entry rule fields required')
    row=dict(_DEFAULTS,**value)
    if not isinstance(row['id'],str) or not _ID.fullmatch(row['id']):raise ValueError('bounded stable rule ID required')
    if (not isinstance(row['name'],str) or not row['name'].strip() or len(row['name'])>64
            or any(ord(char)<32 for char in row['name'])):raise ValueError('bounded rule name required')
    if type(row['enabled']) is not bool:raise ValueError('explicit rule enabled flag required')
    row['scope']=_scope(row['scope']);row['package']=_package(row['package'])
    if row['trigger']!='app_enter' or row['message_source'] not in {'app_library','custom'} or row['image_policy']!='fresh_required':
        raise ValueError('only App entry, local messages and fresh required images are supported')
    if row['message_source']=='custom':
        lines=row.get('custom_messages')
        if (not isinstance(lines,list) or not 1<=len(lines)<=100
                or any(not isinstance(line,str) or not line.strip() or len(line)>600
                    or line!=line.strip() or any(ord(c)<32 for c in line) for line in lines)
                or len(set(lines))!=len(lines)):
            raise ValueError('one to 100 distinct plain custom messages required')
    elif 'custom_messages' in row:
        raise ValueError('custom messages require the custom source')
    if row['cooldown_minutes'] is not None:_integer(row['cooldown_minutes'],'rule cooldown',10,1440)
    _integer(row['priority'],'rule priority',0,100)
    return plain(row)


def parse_rule_config(value):
    """Read the single existing-owner JSON field; no coercion or persistence."""
    if isinstance(value,str):
        if len(value.encode('utf-8'))>65536:raise ValueError('App rule configuration exceeds 64 KiB')
        try:value=json.loads(value)
        except (ValueError,RecursionError):raise ValueError('valid App rule JSON list required') from None
    if not isinstance(value,(list,tuple)) or len(value)>MAX_RULES:raise ValueError('at most 64 App rules required')
    return value


def _check(value,label):
    if value is None:return None
    if (not isinstance(value,dict) or type(value.get('allowed')) is not bool
            or not isinstance(value.get('reason'),str) or not _CODE.fullmatch(value['reason'])):
        raise ValueError('backend '+label+' check required')
    return value


class NativeAppRules:
    """A detached configuration view; export still needs host CAS persistence."""
    def __init__(self,rules=()):
        self._rules=[];self.revision='';self.configure(rules)

    def configure(self,rules,*,expected_revision=None):
        if expected_revision is not None and expected_revision!=self.revision:raise AppRuleConflict('App rule configuration changed')
        rules=parse_rule_config(rules)
        normalized=[normalize_rule(row) for row in rules];seen=set()
        for row in normalized:
            identity=(scope_key(row['scope']),row['id'])
            if identity in seen:raise ValueError('duplicate App rule ID in the same scope')
            seen.add(identity)
        normalized.sort(key=lambda row:(scope_key(row['scope']),row['package'],-row['priority'],row['id']))
        normalized=plain(normalized,65536);revision=hashlib.sha256(canonical(normalized).encode()).hexdigest()
        if revision==self.revision:return False
        self._rules,self.revision=normalized,revision;return True

    def list(self,scope):
        scope=_scope(scope)
        return plain([row for row in self._rules if row['scope']==scope],65536)

    def replace_for_scope(self,scope,rules,*,expected_revision=None):
        """Stage only this scope; no save, reload, sender or journal is invoked."""
        scope=_scope(scope)
        rules=parse_rule_config(rules)
        selected=[normalize_rule(row) for row in rules]
        if any(row['scope']!=scope for row in selected):raise ValueError('foreign scope cannot be replaced')
        return self.configure([row for row in self._rules if row['scope']!=scope]+selected,expected_revision=expected_revision)

    def export(self):
        return dict(schema=SCHEMA,revision=self.revision,rules=plain(self._rules,65536))

    @staticmethod
    def _winner(rows):
        active=[row for row in rows if row['enabled']]
        return min(active or rows,key=lambda row:(-row['priority'],row['id'])) if rows else None

    def compile(self,scope,library,*,hour,app_cooldown_minutes=120,shared_cooldown_minutes=10):
        scope=_scope(scope)
        if not isinstance(library,NativePhoneMessages):raise ValueError('current native phone library required')
        _integer(hour,'local hour',0,23);_integer(app_cooldown_minutes,'global App cooldown',10,1440)
        _integer(shared_cooldown_minutes,'shared cooldown',1,1440)
        scoped=self.list(scope);groups={}
        for row in scoped:groups.setdefault(row['package'],[]).append(row)
        pools=library.candidate_rules(hour=hour,tags=())
        packages=set(pools)|{row['package'] for row in library.list(include_disabled=True)}|set(groups)
        if len(packages)>128:raise ValueError('existing App policy capacity exceeded')
        policies={}
        for package in sorted(packages):
            winner=self._winner(groups.get(package,[]))
            requested=winner['cooldown_minutes'] if winner else None
            policies[package]=dict(enabled=winner['enabled'] if winner else True,
                rule_id=winner['id'] if winner else None,name=winner['name'] if winner else None,
                priority=winner['priority'] if winner else 50,rule_cooldown_minutes=requested,
                effective_cooldown_minutes=max(app_cooldown_minutes,requested or app_cooldown_minutes),
                image_policy='fresh_required',message_source=winner['message_source'] if winner else 'app_library')
            if winner and winner['message_source']=='custom':
                pools[package]=list(winner['custom_messages'])
        effective={package:lines for package,lines in pools.items() if policies[package]['enabled']}
        try:
            plain([effective,[],None,None],65536)
            compiled=compile_rules(effective)
        except ValueError:raise ValueError('effective App messages exceed the existing 64 KiB policy budget') from None
        payload=dict(scope=scope,rules=scoped,library_revision=library.revision,
            per_app=policies,shared_cooldown_minutes=shared_cooldown_minutes)
        return dict(scope=scope,config_revision=self.revision,rules_digest=hashlib.sha256(canonical(payload).encode()).hexdigest(),
            candidate_rules=plain(effective,65536),per_app=plain(policies,65536),
            candidate_rules_bytes=len(canonical(compiled).encode()),shared_cooldown_minutes=shared_cooldown_minutes)

    def preview(self,scope,event,library,*,hour,rule_id=None,app_cooldown_minutes=120,shared_cooldown_minutes=10,
                candidate_check=None,preflight=None,delivery_policy=None):
        """Explain a supplied App-entry sample; backend checks are never invented.

        The API must compute candidate_check/preflight itself, not accept those
        permission decisions from a browser. Actual execution rechecks both.
        """
        scope=_scope(scope)
        if not isinstance(event,dict) or set(event)!={'trigger','package'}:raise ValueError('explicit App event sample required')
        package=_package(event['package'])
        if not isinstance(event['trigger'],str):raise ValueError('explicit sample trigger required')
        plan=self.compile(scope,library,hour=hour,app_cooldown_minutes=app_cooldown_minutes,shared_cooldown_minutes=shared_cooldown_minutes)
        candidate_check=_check(candidate_check,'candidate');preflight=_check(preflight,'scheduler')
        if delivery_policy is not None and not isinstance(delivery_policy,DeliveryPolicy):raise ValueError('actual delivery policy required')
        scoped=self.list(scope);app_rows=[row for row in scoped if row['package']==package];winner=self._winner(app_rows)
        selected=next((row for row in scoped if row['id']==rule_id),None) if rule_id is not None else winner
        policy=plan['per_app'].get(package,dict(enabled=True,effective_cooldown_minutes=app_cooldown_minutes,
            rule_cooldown_minutes=None,priority=50))
        limits=dict(global_app_cooldown_minutes=app_cooldown_minutes,requested_rule_cooldown_minutes=policy['rule_cooldown_minutes'],
            effective_app_cooldown_minutes=policy['effective_cooldown_minutes'],shared_cooldown_minutes=shared_cooldown_minutes,
            scheduler=None if delivery_policy is None else dict(daily_limit=delivery_policy.daily_limit,
                min_interval_minutes=delivery_policy.min_interval_seconds/60,recent_chat_minutes=delivery_policy.recent_chat_seconds/60,
                quiet_enabled=delivery_policy.quiet_enabled,quiet_start=delivery_policy.quiet_start,quiet_end=delivery_policy.quiet_end))
        result=dict(match=False,blocked=False,state='not_matched',reason='not_matched',matched_rule=None,package=package,
            effective_cooldown_minutes=policy['effective_cooldown_minutes'],explanations=[],registered_capability=CAPABILITY,
            image_policy='fresh_required',output_sample=None,output_basis='current_custom_first_eligible' if policy.get('message_source')=='custom' else 'current_library_first_eligible',
            priority=policy['priority'],rules_digest=plan['rules_digest'],effective_limits=limits,pending_checks=[],
            preview_only=True,llm_calls=0,sends=0,writes_business=False)
        def finish(reason,explanation,*,match=False,blocked=False,state='not_matched'):
            result.update(match=match,blocked=blocked,state=state,reason=reason)
            result['explanations'].append(explanation);return result
        if rule_id is not None and selected is None:return finish('rule_not_found','当前完整会话中找不到这条规则。')
        if selected is not None and selected['package']!=package:return finish('package_mismatch','示例应用与这条规则的应用不同。')
        if event['trigger']!='app_enter':return finish('trigger_mismatch','此规则只处理进入应用事件。')
        if selected is not None and not selected['enabled']:
            result['matched_rule']=selected
            return finish('rule_disabled','这条规则已停用。',blocked=True,state='blocked')
        if rule_id is not None and winner and selected['id']!=winner['id']:
            result['matched_rule']=winner
            return finish('higher_priority_rule','同一应用由更高优先级或稳定排序在前的规则接管。',blocked=True,state='blocked')
        result['matched_rule']=winner
        if not policy['enabled']:return finish('rule_disabled','当前会话中该应用的规则已停用。',blocked=True,state='blocked')
        pool=plan['candidate_rules'].get(package,[])
        if not pool:return finish('message_pool_unavailable','当前应用没有符合时段、标签与启用状态的文本消息池。',match=True,blocked=True,state='blocked')
        result['output_sample']=pool[0]
        requested=policy['rule_cooldown_minutes']
        if requested is not None and requested<app_cooldown_minutes:
            result['explanations'].append('规则设为'+str(requested)+'分钟，但全局至少'+str(app_cooldown_minutes)+'分钟，当前按'+str(policy['effective_cooldown_minutes'])+'分钟执行。')
        else:result['explanations'].append('有效应用冷却为'+str(policy['effective_cooldown_minutes'])+'分钟，共享冷却仍独立生效。')
        result['explanations'].append('调用现有 App 图文陪伴；当前仅支持新图，预览不生成图片。')
        if candidate_check is None:result['pending_checks'].append('app_entry_and_cooldown')
        elif not candidate_check['allowed']:
            return finish(candidate_check['reason'],_CANDIDATE_REASONS.get(candidate_check['reason'],'应用入场与冷却检查尚未允许。'),match=True,blocked=True,state='blocked')
        elif candidate_check.get('text') in pool:
            result['output_sample']=candidate_check['text'];result['output_basis']='existing_candidate_preview'
        if preflight is None:result['pending_checks'].append('scheduler')
        elif not preflight['allowed']:
            return finish(preflight['reason'],_SCHEDULER_REASONS.get(preflight['reason'],'现有调度器未允许本次发送机会。'),match=True,blocked=True,state='blocked')
        if result['pending_checks']:return finish('checks_pending','规则条件符合，仍有运行检查尚未提供；不能据此判断将发送。',match=True,state='pending')
        return finish('ready','将调用 App 陪伴；实际执行仍由现有候选、图像与调度链路最终复核。',match=True,state='ready')

