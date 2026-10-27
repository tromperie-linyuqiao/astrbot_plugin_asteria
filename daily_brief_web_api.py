"""Read-only daily brief over existing scoped date and agenda services.
No model, scheduler, event ingestion, send, new storage, or inferred experience.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import math
import sqlite3
from astrbot.api.web import error_response, json_response, request
from .important_dates_web_api import NativeImportantDatesWebApi
from .core.living.native_important_dates import date_zone, relevant_dates
from .core.living.native_agenda import NativeAgenda
from .memory_web_api import SCOPE_FIELDS, _InvalidRequest, _scope


class NativeDailyBriefWebApi(NativeImportantDatesWebApi):
    def register_routes(self):
        self.plugin.context.register_web_api('/astrbot_plugin_virtual_body/page/daily-brief/read',
            self.read, ['GET'], 'TLS read-only current-scope daily brief')

    async def read(self):
        try:
            username = getattr(request, 'username', None)
        except RuntimeError:
            username = None
        if not isinstance(username, str) or not username.strip():
            return error_response('需要通过 AstrBot 管理后台认证', status_code=401)
        service = None
        try:
            query = dict(getattr(request, 'query', None) or {})
            if set(query) - set(SCOPE_FIELDS) - {'timezone'}:
                raise _InvalidRequest('简报只接受完整会话和明确时区')
            scope = _scope({key: query.get(key) for key in SCOPE_FIELDS})
            timezone_name = query.get('timezone', 'UTC+08:00')
            zone = date_zone(timezone_name)
            resources = self._resources()
            runtime = resources[2]
            service = self._admin_service(resources, scope)
            sampled_authorities = {}
            def collect():
                self._same_resources(resources)
                now = service.clock()
                if type(now) not in (int, float) or not math.isfinite(now) or not 0 < now < 253402214400:
                    raise RuntimeError('invalid brief clock')
                day = datetime.fromtimestamp(now, zone).date()
                dates = service.export(scope, include_archived=False)
                definitions = [dict(row['fields'], id=row['id'], provenance=row['provenance'])
                    for row in dates['records']]
                projected = relevant_dates(definitions, now=now)
                upcoming = [dict(id=row['id'], title=row['title'], date=row['next_date'],
                    days_until=row['days_until'], timezone=row['timezone'], source=row['provenance']['kind'])
                    for row in projected[:20]]
                agenda = getattr(runtime, 'agenda', None)
                agenda_state = 'unavailable'
                today_rows, future_rows, scanned = [], [], 0
                if isinstance(agenda, NativeAgenda):
                    try:
                        rows = agenda.list(scope, limit=100, offset=0)
                        if getattr(runtime, 'agenda', None) is not agenda:
                            raise RuntimeError('agenda replaced')
                        agenda._scope(scope)
                        sampled_authorities['agenda'] = agenda
                        scanned = len(rows)
                        for row in rows:
                            due = datetime.fromisoformat(row['due_at'].replace('Z', '+00:00')).astimezone(zone)
                            if row['status'] != 'active':
                                continue
                            item = dict(id=row['id'], content=row['content'], due_at=row['due_at'],
                                status=row['status'], task_state=row['task_state'], source='tls_native_agenda',
                                delivery_confirmed=False)
                            if due.date() == day:
                                today_rows.append(item)
                            elif due.date() > day:
                                future_rows.append(item)
                        agenda_state = 'partial' if scanned == 100 else 'available'
                    except PermissionError:
                        agenda_state = 'session_required'
                    except (RuntimeError, sqlite3.Error, OSError):
                        agenda_state = 'unavailable'
                self._same_resources(resources)
                service._scope(scope)
                return dict(ok=True, scope=scope, day=day.isoformat(), timezone=timezone_name,
                    sampled_at=now, dates=dict(state='available', upcoming=upcoming,
                        total_relevant=len(projected), displayed=len(upcoming), definitions=dates['total'],
                        boundary='日期定义与计划，不表示经历或已发送提醒'),
                    agenda=dict(state=agenda_state, today=today_rows[:20], next=future_rows[:10],
                        scanned=scanned, today_in_sample=len(today_rows), next_in_sample=len(future_rows),
                        max_scanned=100, boundary='有界原生日程样本；任务确认与手机可见性另行验收'),
                    read_only=True, llm_calls=0, sends=0, atomic_cross_service_snapshot=False)
            result = await asyncio.to_thread(collect)
            self._same_resources(resources)
            sampled_agenda = sampled_authorities.get('agenda')
            if sampled_agenda is not None:
                if getattr(runtime, 'agenda', None) is not sampled_agenda:
                    raise RuntimeError('brief agenda owner changed')
                sampled_agenda._scope(scope)
            service._scope(scope)
            return json_response(result, headers={'Cache-Control': 'no-store'})
        except (_InvalidRequest, ValueError, TypeError):
            return error_response('请选择完整会话和有效时区', status_code=400)
        except PermissionError:
            return error_response('当前资料读取权限已改变', status_code=403)
        except Exception:
            return error_response('简报资料暂不可用，请稍后刷新；不会以默认数据替代', status_code=503)
        finally:
            if service is not None:
                service.stop()
