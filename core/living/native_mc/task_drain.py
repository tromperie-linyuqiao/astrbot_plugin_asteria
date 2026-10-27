"""Bounded await-chain inspection for the two MC lifecycle owners.

The existing handoff walk and its captured C GC primitive remain the base.
This adds only the exact CPython async-generator asend/athrow shapes already
identified by the task diagnostic. Unknown terminals remain unknown.
"""
from __future__ import annotations

import asyncio
from types import AsyncGeneratorType, CodeType, CoroutineType, GeneratorType, ModuleType

from .. import native_core_handoff as audit
from ..native_core_task_diagnostics import _OPAQUE


def nested_codes(code):
    result, pending = [], [code]
    while pending:
        current = pending.pop()
        if type(current) is not CodeType:
            raise RuntimeError('actual compiled memory source required')
        result.append(current)
        if len(result) > 65536:
            raise RuntimeError('memory source code capacity exceeded')
        pending.extend(value for value in current.co_consts if type(value) is CodeType)
    return tuple(result)


def source_codes(source, filename):
    return nested_codes(audit._compiled(source, filename))


def _walk(root, future_type):
    codes, current, seen = [], root, set()
    opaque = dict(_OPAQUE)
    for _ in range(audit.MAX_DEPTH):
        if current is None:
            return tuple(codes), False
        if id(current) in seen:
            return tuple(codes), True
        seen.add(id(current))
        kind = type(current)
        if kind is CoroutineType:
            code, following = current.cr_code, current.cr_await
        elif kind is GeneratorType:
            code, following = current.gi_code, current.gi_yieldfrom
        elif kind is AsyncGeneratorType:
            code, following = current.ag_code, current.ag_await
        elif kind is future_type:
            return tuple(codes), False
        elif kind is audit._COROUTINE_WRAPPER_TYPE or kind in opaque:
            primitive = audit._GC_GET_REFERENTS
            module = audit._GC_MODULE
            if (primitive is None or type(module) is not ModuleType
                    or vars(module).get('get_referents') is not primitive):
                return tuple(codes), True
            references = primitive(current)
            expected = CoroutineType if kind is audit._COROUTINE_WRAPPER_TYPE else AsyncGeneratorType
            if type(references) is not list or not 1 <= len(references) <= 4:
                return tuple(codes), True
            matching = [value for value in references if type(value) is expected]
            if (len(matching) != 1 or kind is audit._COROUTINE_WRAPPER_TYPE and len(references) != 1):
                return tuple(codes), True
            current = matching[0]
            continue
        else:
            return tuple(codes), True
        codes.append(code)
        current = following
    return tuple(codes), current is not None


def task_codes(task):
    iterator = asyncio.get_running_loop().create_future().__await__()
    return _walk(asyncio.Task.get_coro(task), type(iterator))


def task_chain(task, codes):
    iterator = asyncio.get_running_loop().create_future().__await__()
    future_type = type(iterator)
    try:
        found, _ = audit._task_chain(task, codes, future_type)
    except Exception:
        found = False
    try:
        walked, unknown = _walk(asyncio.Task.get_coro(task), future_type)
    except Exception:
        return found, True
    approved = {(code.co_filename, code.co_name) for code in codes}
    return found or any((code.co_filename, code.co_name) in approved for code in walked), unknown
