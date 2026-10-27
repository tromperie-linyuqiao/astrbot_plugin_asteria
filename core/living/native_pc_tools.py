"""Install the original PC tool names through TLS's existing FunctionTool API.

Factory construction never registers SDK handlers. The full owner installs its
returned tools only after actual old-plugin retirement; every call repeats the
real event/scope/current-owner checks and uses the original method schema.
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import re

import docstring_parser
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.provider.func_tool_manager import PY_TO_JSON_TYPE, SUPPORTED_TYPES

from .models import private_scope
from .native_pc_service import NativePCService

_HOOKS = Path(__file__).resolve().parent / 'native_pc_business/EVENT-HOOKS.json'


def _definition(method):
    """Mirror the actual SDK decorator parser without invoking the decorator."""
    signature = inspect.signature(method)
    doc = docstring_parser.parse(inspect.getdoc(method) or '')
    keyword_fields = any(parameter.kind == inspect.Parameter.VAR_KEYWORD
                         for parameter in signature.parameters.values())
    properties = {}
    for argument in doc.params:
        name, type_name = argument.arg_name, argument.type_name
        parameter = signature.parameters.get(name)
        # Several original PC tools intentionally expose their documented
        # fields through **kwargs. Keep that real signature contract instead
        # of treating those original, SDK-supported schemas as missing args.
        if ((parameter is None and not keyword_fields)
                or parameter is not None and parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                or name in {'self', 'event'} or not type_name):
            raise ValueError('native PC tool documentation and real signature disagree: ' + name)
        match = re.fullmatch(r'(\w+)\[(\w+)\]', type_name)
        subtype = None
        if match: type_name, subtype = match.groups()
        type_name = PY_TO_JSON_TYPE.get(type_name, type_name)
        subtype = PY_TO_JSON_TYPE.get(subtype, subtype) if subtype else None
        if type_name not in SUPPORTED_TYPES or subtype and subtype not in SUPPORTED_TYPES:
            raise ValueError('unsupported original PC tool parameter type')
        value = dict(type=type_name, description=argument.description or '')
        if type_name == 'array' and subtype: value['items'] = dict(type=subtype)
        properties[name] = value
    # The existing SDK's spec_to_func creates exactly object/properties; do not
    # invent required/default/extra-field semantics different from old tools.
    return (doc.description or '').strip(), dict(type='object', properties=properties)


class NativePCFunctionTool(FunctionTool):
    def __init__(self, controller, service, method_name, name):
        original = getattr(service, method_name)
        description, parameters = _definition(original)
        super().__init__(name=name, description=description, parameters=parameters)
        self._controller, self._service, self._method_name = controller, service, method_name
        self._original = getattr(original, '__func__', original)
        self.handler_module_path = type(service).__module__

    async def call(self, context, **kwargs):
        owner, service = self._controller, self._service
        if (getattr(owner, 'active', False) is not True or getattr(owner, 'service', None) is not service
                or not service.active or not owner.legacy_closed() or not service.native_source_current()):
            return 'TLS 角色日常服务未取得唯一执行权，未执行操作。'
        event = getattr(getattr(context, 'context', None), 'event', None)
        if event is None: return '没有真实聊天事件，未执行操作。'
        try:
            session = str(getattr(event, 'unified_msg_origin', '') or '')
            scope = private_scope(owner._host().presence.peek_scope_for_session(session))
            if (scope['session_id'] != session or str(event.get_sender_id()) != scope['user_id']
                    or str(event.get_self_id()) != scope['bot_id'] or not event.is_private_chat()
                    or event.get_group_id() or not owner._authorize('hook', scope)):
                raise PermissionError
        except (AttributeError, TypeError, ValueError, PermissionError):
            return '当前真实用户、角色或会话授权不足，未执行操作。'
        original = getattr(service, self._method_name)
        if getattr(original, '__func__', original) is not self._original:
            return '角色工具实现已变化，请等待当前运行环境重新接线。'
        # Uses the real method signature/doc captured above, not the guard
        # wrapper's *args. pc_manage_memo still enters the original native memo
        # runtime selector and its persistent owner/claim contracts.
        inspect.signature(original).bind(event, **kwargs)
        value = service.hook(self._method_name)(event, **kwargs)
        if inspect.isasyncgen(value):
            # This is how the actual SDK FunctionToolManager consumes a legacy
            # decorated handler: preserve its final yielded tool result, without
            # sending a second message for intermediate yields.
            last = None
            async for result in value: last = result
            return last
        if inspect.isawaitable(value): return await value
        return value


def factorytools(controller):
    """Return tools for context.add_llm_tools(*tools); does not install them."""
    service = getattr(controller, 'service', None)
    if (getattr(controller, 'active', False) is not True or not isinstance(service, NativePCService)
            or service.active is not True or not controller.legacy_closed() or not service.native_source_current()):
        return []
    rows = json.loads(_HOOKS.read_text(encoding='utf-8'))['hooks']
    result, names = [], set()
    for row in rows:
        if row['module'] != 'main.py' or not row['decorator'].startswith('filter.llm_tool('): continue
        expression = ast.parse(row['decorator'], mode='eval').body
        if not isinstance(expression, ast.Call): raise ValueError('literal original PC tool decorator required')
        named = next((keyword.value for keyword in expression.keywords if keyword.arg == 'name'), None)
        name = ast.literal_eval(named) if named is not None else row['function']
        if type(name) is not str or not name or name in names: raise ValueError('unique original PC tool name required')
        names.add(name)
        result.append(NativePCFunctionTool(controller, service, row['function'], name))
    return result
