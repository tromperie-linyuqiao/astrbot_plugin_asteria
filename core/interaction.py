"""Bounded, explicitly authored APP scene state in the original BodyStore.

This module never infers a user's pose from free text, advances a physical
value, starts a timer, or writes a file. The original session writer owns it.
"""
from __future__ import annotations

import math
from copy import deepcopy

SOURCE = 'owned_webchat_action'
POSES = {'sit': '坐着', 'stand': '站着', 'crouch': '蹲着',
         'lie_down': '躺着休息', 'lean_back': '靠着椅背', 'rest_on_desk': '趴在桌上'}
POSITIONS = {'approach': '走近角色', 'step_back': '与角色拉开距离', 'sit_beside': '坐在角色旁边'}
PART_EXTENSION = 'asteria.parts.20261104'
ADDED_PARTS = frozenset(('ear_base', 'ear_outer', 'forehead', 'temple', 'chin',
                        'hand_back', 'fingers', 'fingertips', 'tail_middle', 'tail_tip'))


def extend_profile_parts(builtin, override):
    """Add only this release's declared subregions to original known profiles.

    Existing IDs, values, labels and aliases stay verbatim, including a user's
    deliberately removed old part. Builtin chin already existed on matcha.
    """
    if (not isinstance(builtin, dict) or not isinstance(override, dict)
            or builtin.get('id') not in {'texas', 'matcha'} or builtin.get('id') != override.get('id')
            or not isinstance(override.get('parts'), list)):
        return override, False
    if isinstance(override.get('part_extension'), dict) and override['part_extension'].get('version') == PART_EXTENSION:
        return override, False  # Respect later explicit removal of a newly added part.
    allowed = ADDED_PARTS - ({'chin'} if builtin['id'] == 'matcha' else set())
    existing = {item.get('id') for item in override['parts'] if isinstance(item, dict)}
    added = [deepcopy(item) for item in builtin.get('parts') or []
             if isinstance(item, dict) and item.get('id') in allowed and item['id'] not in existing]
    if not added:
        return override, False
    result = deepcopy(override)
    result['parts'].extend(added)
    result['part_extension'] = {'version': PART_EXTENSION, 'source': 'builtin_profile',
                                'added_ids': [item['id'] for item in added]}
    return result, True


def normalize(value):
    if not isinstance(value, dict) or value.get('source') != SOURCE or value.get('mode') != 'narrative':
        return None
    result = {'source': SOURCE, 'mode': 'narrative'}
    for field, allowed in (('posture', POSES), ('position', POSITIONS)):
        item = value.get(field)
        if not isinstance(item, dict) or item.get('template') not in allowed:
            continue
        at = item.get('at')
        target = item.get('target')
        if (type(at) not in (int, float) or not math.isfinite(at) or not 0 < at < 253402214399
                or not isinstance(target, str) or len(target) > 80 or any(ord(c) < 32 for c in target)):
            continue
        result[field] = {'template': item['template'], 'target': target, 'at': at}
    return result


def apply(state, changes, profile, now):
    """Called only by the owned APP submit path inside the original writer."""
    if not isinstance(changes, dict) or set(changes) - {'posture', 'position', 'stops'}:
        raise ValueError('bounded APP interaction required')
    if type(now) not in (int, float) or not math.isfinite(now) or not 0 < now < 253402214399:
        raise ValueError('valid interaction time required')
    current = normalize(state.get('interaction')) or {'source': SOURCE, 'mode': 'narrative'}
    for field, allowed in (('posture', POSES), ('position', POSITIONS)):
        value = changes.get(field)
        if value is None:
            continue
        if (not isinstance(value, dict) or set(value) != {'template', 'target'}
                or value.get('template') not in allowed or not isinstance(value.get('target'), str)
                or len(value['target']) > 80 or any(ord(c) < 32 for c in value['target'])):
            raise ValueError('known APP interaction template required')
        current[field] = dict(value, at=now)
        if field == 'posture' and value['template'] in {'stand', 'crouch', 'lie_down', 'rest_on_desk'}:
            current.pop('position', None)
        if field == 'position' and value['template'] == 'sit_beside':
            current['posture'] = {'template': 'sit', 'target': 'beside_character', 'at': now}
    stops = changes.get('stops', [])
    known = {part['id'] for part in profile.get('parts', []) if part.get('id')}
    if (not isinstance(stops, list) or len(stops) > len(known)
            or any(not isinstance(pid, str) or pid not in known for pid in stops)):
        raise ValueError('known contact parts required')
    contacts = state.get('active_contact')
    if isinstance(contacts, dict):
        for pid in stops:
            contacts.pop(pid, None)
    state['interaction'] = current


def snapshot(state, profile):
    value = normalize(state.get('interaction')) if isinstance(state, dict) else None
    if value is None:
        return {'available': False, 'posture': None, 'position': None, 'contacts': []}
    result = dict(value, available=True, posture=None, position=None, contacts=[])
    for field, labels in (('posture', POSES), ('position', POSITIONS)):
        if field in value:
            result[field] = dict(value[field], label=labels[value[field]['template']])
    labels = {part['id']: part.get('label') or part['id'] for part in profile.get('parts', []) if part.get('id')}
    for pid, entry in (state.get('active_contact') or {}).items():
        if pid in labels and isinstance(entry, dict):
            result['contacts'].append({'part': pid, 'label': labels[pid],
                                       'action': str(entry.get('action') or '')[:12],
                                       'since': entry.get('since')})
    return result


def render(state, profile):
    value = snapshot(state, profile)
    if not value['available']:
        return ''
    descriptions = [value[field]['label'] for field in ('posture', 'position') if value.get(field)]
    contacts = '、'.join(str(item['action']) + '·' + item['label'] for item in value['contacts'])
    descriptions.append('当前持续接触：' + (contacts or '无'))
    return ('[本会话用户明确选择的虚构互动状态；不代表现实观察或角色已经同意；'
            '最新表达与停止要求优先]\n' + '；'.join(descriptions))[:600]
