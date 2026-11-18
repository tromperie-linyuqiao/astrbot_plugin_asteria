"""Opt-in idle companionship for an authenticated WebChat private session."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from random import randint
from secrets import token_hex
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api import logger

from .chat_delivery import COMPANION_SOURCE_CATEGORIES, ChatDeliveryAdapter, NAMESPACE as DELIVERY_NAMESPACE, key_for
from .chat_devices import ChatDevices
from .chat_expressions import ChatExpressions
from .chat_identity import identity_service
from .chat_sync import has_saved_companion_delivery
from .chat_workspace import actual_app_scope
from .delivery_sender import AstrBotDeliveryAdapter, BeforeDispatchError
from .delivery_types import DeliveryPolicy, delivery_quiet_window
from .journal import JournalConflict
from .models import scope_key

NAMESPACE = 'tls.chat.companion_mode'
KEY = 'mode'
LANE = 'chat_companion'
DURATIONS = {30, 60, 120}
REST_DURATIONS = {15, 30, 60}
IDLE_MIN_SECONDS = 300
IDLE_MAX_SECONDS = 600
RECENT_USER_TEXT_SECONDS = 30 * 60
SIGNOFF_MAX_AGE_SECONDS = max(DURATIONS) * 60
RECENT_SAVED_TEXT_COUNT = 6


class CompanionUnavailable(RuntimeError):
    pass


def _zone(name):
    if not isinstance(name, str) or not name or len(name) > 80:
        raise ValueError('请选择有效的当地时区')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('请选择有效的当地时区') from exc


def _anchor(rows, *, include_latest_user=False):
    # Real chat activity and the latest user's own words have separate clocks.
    token, seconds, latest_user = None, 0.0, (0.0, '')
    for row in rows:
        content = row.content
        if not isinstance(content, dict) or content.get('type') not in {'user', 'bot'}:
            continue
        kind = content['type']
        refs = content.get('refs') or {}
        if kind == 'bot' and isinstance(refs, dict) and refs.get('source') in {
                'tls_chat_direct', 'qq_confirmed_proactive'}:
            continue
        stamp = row.created_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        row_time = stamp.timestamp()
        if token is None:
            token, seconds = str(row.id), row_time
        if not include_latest_user:
            break
        if kind != 'user':
            continue
        message = content.get('message', '')
        if isinstance(message, list):
            message = ' '.join(part['text'] for part in message if isinstance(part, dict)
                and part.get('type') == 'plain' and isinstance(part.get('text'), str))
        latest_user = row_time, message.strip()[:400] if isinstance(message, str) else ''
        # A media-only message still replaces the previous user topic.
        break
    return token, seconds, latest_user


def _recent_text_keys(data):
    last = data.get('last_text_key')
    keys = data.get('recent_text_keys', ())
    return list(dict.fromkeys(key for key in (last, *keys) if key))[:RECENT_SAVED_TEXT_COUNT]


def _rest_deadline(data, now):
    deadline = data.get('rest_until')
    return deadline if deadline and deadline > now else None


class ChatCompanionMode:
    def __init__(self, plugin, host, links, *, clock, delay=None, generator=None, adapter=None):
        self.plugin, self.host, self.links, self.clock = plugin, host, links, clock
        self.journal = links.journal
        self._delay = delay or self._idle_delay
        self._generator, self._adapter = generator, adapter
        self.chat = None
        self._due = {}
        self._active = {}
        self._restored = False
        self._writes_during_restore: set[tuple[str, str]] | None = None

    def _idle_delay(self):
        return randint(IDLE_MIN_SECONDS, max(IDLE_MIN_SECONDS, IDLE_MAX_SECONDS-self.plugin._tick_seconds()))

    @property
    def live(self):
        return self.links.current() and self.host.runtime.active

    @property
    def has_work(self):
        return self.live and (not self._restored or
            bool(self.chat and any(due <= self.clock() for due in self._due.values())))

    def bind(self, chat):
        self.chat = chat

    def _fetch(self, username, session_id):
        return self.journal.fetch(NAMESPACE, KEY, ChatExpressions.message_scope(username, session_id))

    async def _row(self, username, session_id):
        return await asyncio.to_thread(self._fetch, username, session_id)

    async def _save(self, username, session_id, prior, data):
        if not self.live:
            raise CompanionUnavailable('陪伴服务正在更新')
        result = await asyncio.to_thread(self.journal.put, NAMESPACE, KEY,
            ChatExpressions.message_scope(username, session_id), data,
            expected_revision=prior['revision'] if prior else 0, authorize=lambda: self.live)
        if self._writes_during_restore is not None:
            self._writes_during_restore.add((username, session_id))
        self._track(username, session_id, result['data'])
        return result

    def _track(self, username, session_id, data):
        key = username, session_id
        now = self.clock()
        unexpired = data['expires_at'] > now
        active = data['state'] == 'active' and unexpired
        paused_rest = _rest_deadline(data, now) if data['state'] == 'paused' and unexpired else None
        if active or paused_rest:
            self._active[key] = (data['scope'], data['expires_at'] if active else paused_rest)
        else:
            self._active.pop(key, None)
        if data.get('pending_task'):
            self._due[key] = data['next_evaluation_at']
        elif active:
            self._due[key] = min(data['next_evaluation_at'], data['expires_at'])
        else:
            self._due.pop(key, None)

    async def _restore(self):
        writes: set[tuple[str, str]] = set()
        self._writes_during_restore = writes
        try:
            records = await asyncio.to_thread(self.journal.companion_mode_records)
            now = self.clock()
            for item in records:
                data = item['data']
                username, session_id = data['username'], data['session_id']
                if (username, session_id) in writes:
                    # A completed Web request has already projected the newer record.
                    continue
                if item['scope_hash'] != scope_key(ChatExpressions.message_scope(username, session_id)):
                    continue
                if data.get('pending_task'):
                    self._track(username, session_id, data)
                elif data['state'] == 'active' and data['expires_at'] > now:
                    if data['next_evaluation_at'] <= now:
                        try:
                            await self._save(username, session_id, item, dict(data,
                                next_evaluation_at=now+self._delay(), anchor_at=now, reason='scheduled'))
                        except JournalConflict:
                            pass
                    else:
                        self._track(username, session_id, data)
                elif data['state'] == 'paused' and data['expires_at'] > now and _rest_deadline(data, now):
                    self._track(username, session_id, data)
            self._restored = True
        finally:
            self._writes_during_restore = None

    def _view(self, session_id, row, scope):
        data = row['data'] if row else {}
        state = data.get('state', 'off') if scope is not None else 'unavailable'
        reason = data.get('reason')
        expires = data.get('expires_at')
        now = self.clock()
        if state in {'active','paused'} and expires <= now:
            state, reason = 'expired', 'expired'
        if scope is None:
            reason = 'waiting_for_real_app_message'
        elif data.get('scope') and data['scope'] != scope:
            state, reason = 'off', 'session_changed'
        rest_until = _rest_deadline(data, now) if state in {'active','paused'} else None
        if state == 'active' and rest_until:
            reason = 'resting'
        elif reason == 'resting':
            reason = 'delivery_unknown' if data.get('pending_task') else 'scheduled'
        from .chat_companion_context import companion_model_status
        model_status = companion_model_status(self.plugin,scope) if scope else None
        next_evaluation = data.get('next_evaluation_at')
        view = dict(session_id=session_id, state=state, reason=reason,
            timezone=data.get('timezone'), expires_at=expires if state in {'active','paused','expired'} else None,
            rest_until=rest_until,
            delivery_pending=bool(scope and data.get('scope') == scope and data.get('pending_task')),
            next_evaluation_at=next_evaluation if state == 'active' and next_evaluation < expires else None,
            intervals_minutes=[5,10], model_status=model_status)
        if state == 'active':
            try:
                zone = _zone(data.get('timezone'))
                quiet = self._quiet_window(zone, now, forecast_until=expires)
                if quiet['quiet_all_day']:
                    view['quiet_all_day'] = True
                until = quiet['quiet_until']
                view['quiet_until'] = until if until > now and not quiet['quiet_all_day'] else None
                if view['quiet_until'] is not None:
                    wall_now = datetime.fromtimestamp(now, zone).replace(tzinfo=None)
                    wall_end = datetime.fromtimestamp(until, zone).replace(tzinfo=None)
                    if wall_end <= wall_now:
                        view['quiet_end_after_rollback'] = True
                if 'next_quiet_from' in quiet:
                    start = quiet['next_quiet_from']
                    end = quiet['next_quiet_until']
                    view.update(next_quiet_from=start, next_quiet_until=end)
                    local_start = datetime.fromtimestamp(start, zone).replace(tzinfo=None)
                    local_end = datetime.fromtimestamp(end, zone).replace(tzinfo=None)
                    if local_end <= local_start:
                        view['next_quiet_end_after_rollback'] = True
            except ValueError:
                # A malformed quiet setting must not hide status or prevent pausing.
                pass
        return view

    async def view(self, username, session_id, session):
        return self._view(session_id, await self._row(username, session_id),
            actual_app_scope(self.plugin, username, session))

    async def inspect_status(self, username, session_id, scope):
        """Read a selected App private scope without exposing receipt identifiers."""
        chat = self.chat
        if chat is None or not await self._owned(chat, username, session_id, scope):
            return None
        row = await self._row(username, session_id)
        if not await self._owned(chat, username, session_id, scope):
            return None
        data = row['data'] if row else {}
        if data and data.get('scope') != scope:
            return None
        view = self._view(session_id, row, scope)
        result = {key:view[key] for key in ('state','reason','expires_at','rest_until','next_evaluation_at')}
        result['receipt'] = 'unknown' if data.get('pending_task') else 'saved' if data.get('last_text_key') else 'none'
        return result

    async def apply(self, username, session_id, session, body):
        action = body.get('action')
        if action not in ('start', 'pause', 'resume', 'stop', 'rest', 'end_rest'):
            raise ValueError('陪伴模式操作无效')
        fields = {'session_id', 'action'}
        if action in ('start','resume'):
            fields |= {'timezone','duration_minutes','installation_id'}
        elif action == 'rest':
            fields.add('rest_minutes')
        if set(body)-fields:
            raise ValueError('陪伴模式请求字段无效')
        prior = await self._row(username, session_id)
        old = prior['data'] if prior else {}
        now = self.clock()
        raw_scope = actual_app_scope(self.plugin, username, session)
        if action in ('pause','stop'):
            state = 'paused' if action == 'pause' else 'off'
            reason = 'paused' if action == 'pause' else 'stopped'
            if not old or old['state'] == state or (action == 'pause' and old['state'] != 'active'):
                return self._view(session_id, prior, raw_scope)
            if old.get('pending_task'):
                reason = 'delivery_unknown'
            value = dict(old, state=state, reason=reason)
            if action == 'stop':
                value['rest_until'] = None
            saved = await self._save(username, session_id, prior, value)
            return self._view(session_id, saved, raw_scope)
        if raw_scope is None:
            raise PermissionError('请先在这个 App 会话正常聊天')
        if action in ('rest','end_rest'):
            if (old.get('scope') != raw_scope or old.get('state') not in ('active','paused')
                    or old['expires_at'] <= now):
                raise JournalConflict('这段陪伴已结束，请重新开启')
            if action == 'rest':
                if old['state'] != 'active':
                    raise JournalConflict('请先继续陪伴')
                minutes = body.get('rest_minutes')
                if type(minutes) is not int or minutes not in REST_DURATIONS:
                    raise ValueError('请选择 15、30 或 60 分钟休息')
                rest_until = min(now+60*minutes, old['expires_at'])
                reason = 'resting'
            else:
                if not _rest_deadline(old, now):
                    return self._view(session_id, prior, raw_scope)
                rest_until = None
                reason = 'scheduled' if old['state'] == 'active' else 'paused'
                if old.get('pending_task'):
                    reason = 'delivery_unknown'
            anchor = rest_until or now
            value = dict(old, rest_until=rest_until, reason=reason, anchor_at=anchor,
                next_evaluation_at=anchor+self._delay())
            saved = await self._save(username, session_id, prior, value)
            return self._view(session_id, saved, raw_scope)
        if old.get('pending_task'):
            await self._reconcile(self.chat,username,session_id,prior)
            prior = await self._row(username,session_id)
            old = prior['data']
            if old.get('pending_task'):
                raise JournalConflict('上次陪伴消息送达结果未知，等待核对')
        if old.get('state') == 'active' and old['expires_at'] > now and old['scope'] == raw_scope:
            return self._view(session_id, prior, raw_scope)
        if action == 'resume' and (old.get('state') != 'paused' or old.get('expires_at',0) <= now or old.get('scope') != raw_scope):
            raise JournalConflict('这段陪伴已结束，请重新开启')
        tz = _zone(body.get('timezone', old.get('timezone'))).key
        minutes = body.get('duration_minutes', 60)
        if type(minutes) is not int or minutes not in DURATIONS:
            raise ValueError('请选择 30、60 或 120 分钟')
        history = old if old.get('scope') == raw_scope else {}
        installation_id = history.get('installation_id')
        if 'installation_id' in body:
            from .chat_perception import installation
            installation_id = installation(body['installation_id'])
        expires = old['expires_at'] if action == 'resume' else now+60*minutes
        rest_until = _rest_deadline(old, now) if action == 'resume' else None
        anchor = rest_until or now
        value = dict(username=username, session_id=session_id, scope=raw_scope, state='active',
            reason='resting' if rest_until else 'scheduled', timezone=tz,
            installation_id=installation_id, expires_at=expires, rest_until=rest_until,
            next_evaluation_at=anchor+self._delay(), anchor_at=anchor, last_text_key=history.get('last_text_key'),
            recent_text_keys=_recent_text_keys(history), evaluations=old.get('evaluations',0) if action == 'resume' else 0)
        saved = await self._save(username, session_id, prior, value)
        return self._view(session_id, saved, raw_scope)

    def suppress_ordinary(self, scope):
        """Pause the ordinary lane only for the same explicitly enabled scope."""
        if (not self.live or scope['platform'] != 'webchat'
                or scope['bot_id'] != 'webchat'):
            return False
        tail = scope['session_id'].split(':',2)[-1]
        prefix = 'webchat!'+scope['user_id']+'!'
        if not tail.startswith(prefix):
            return False
        active = self._active.get((scope['user_id'],tail[len(prefix):]))
        return bool(active and active[0] == scope and active[1] > self.clock())

    async def tick(self):
        if not self._restored:
            await self._restore()
        if not self.live or self.chat is None:
            return
        due = [key for key, when in sorted(self._due.items(), key=lambda item: item[1]) if when <= self.clock()]
        if due:
            try:
                await self._step(*due[0])
            except (JournalConflict, CompanionUnavailable):
                return
            except Exception as exc:
                self._due[due[0]] = self.clock()+self._delay()
                logger.warning('TLS companion evaluation failed: '+type(exc).__name__)

    async def _owned(self, chat, username, session_id, scope):
        session = await chat.db.get_platform_session_by_id(session_id)
        return (self.live and chat is self.chat and session is not None and session.creator == username
            and session.session_id == session_id and session.platform_id == 'webchat' and session.is_group == 0
            and actual_app_scope(self.plugin, username, session) == scope)

    async def _hold(self, chat, username, session_id, data):
        rest_until = _rest_deadline(data, self.clock())
        if rest_until:
            return 'resting', rest_until
        devices = ChatDevices(self.journal, current=lambda: self.live)
        if (await asyncio.to_thread(devices.view,username,session_id))['voice']:
            return 'active_call', None
        if chat.running_convs.get(session_id, False) or chat.get_active_chat_runs(username, session_id):
            return 'recent_chat', None
        now = self.clock()
        quiet_until = self._quiet_window(_zone(data['timezone']), now)['quiet_until']
        if quiet_until > now:
            return 'quiet_hours', quiet_until
        return None

    def _quiet_window(self, zone, now, *, forecast_until=None):
        settings = DeliveryPolicy().as_dict()
        settings['quiet_hours'] = self.plugin._cfg('living_native_delivery_quiet_hours', '')
        return delivery_quiet_window(settings, now, zone=zone, forecast_until=forecast_until)

    async def _history(self, chat, session_id, limit=12):
        return await chat.db.get_platform_message_history(platform_id='webchat', user_id=session_id, page_size=limit)

    async def _step(self, username, session_id):
        prior = await self._row(username, session_id)
        if not prior:
            self._due.pop((username,session_id),None)
            return
        now, data, chat = self.clock(), prior['data'], self.chat
        if data.get('pending_task'):
            await self._reconcile(chat, username, session_id, prior)
            return
        if data['state'] != 'active' or data['expires_at'] <= now:
            self._track(username,session_id,data)
            return
        if data['next_evaluation_at'] > now:
            self._track(username,session_id,data)
            return
        if not await self._owned(chat,username,session_id,data['scope']):
            await self._delay_row(username, session_id, prior, 'waiting_for_real_app_message')
            return
        hold = await self._hold(chat, username, session_id, data)
        if hold:
            reason, recheck_by = hold
            await self._delay_row(username, session_id, prior, reason, recheck_by=recheck_by)
            return
        history_anchor = _anchor(await self._history(chat,session_id), include_latest_user=True)
        _, last, (user_at, user_text) = history_anchor
        recent_text = user_text if user_at >= now-RECENT_USER_TEXT_SECONDS else ''
        if last > data['anchor_at']:
            next_due = last+self._delay()
            if now < next_due:
                await self._save(username,session_id,prior,dict(data,
                    anchor_at=last,next_evaluation_at=next_due,reason='recent_chat'))
                return
        from .chat_companion_context import generate_companion_message, user_requested_quiet
        if user_at >= now-SIGNOFF_MAX_AGE_SECONDS and user_requested_quiet(user_text):
            await self._delay_row(username, session_id, prior, 'user_requested_quiet',
                                  anchor_at=max(last, data['anchor_at']))
            return
        attempt = data.get('evaluations',0)+1
        reservation = await self._delay_row(username,session_id,prior,'scheduled',anchor_at=self.clock(),
            evaluations=attempt)
        generator = self._generator or generate_companion_message
        result = await generator(self.plugin, scope=data['scope'], username=username, session_id=session_id,
            timezone=data['timezone'], now=self.clock(), recent_text=recent_text,
            installation_id=data.get('installation_id'), attempt=attempt)
        text = result.get('text') if isinstance(result, dict) else result
        validate = result.get('validate') if isinstance(result, dict) else None
        text = text.strip()[:280] if isinstance(text,str) else ''
        fingerprint = sha256(' '.join(text.split()).encode()).hexdigest() if text else None
        if not fingerprint or fingerprint in _recent_text_keys(data):
            await self._delay_row(username,session_id,reservation,'no_candidate')
            return

        async def before_store(expected):
            if validate is not None and not await validate():
                return False
            if not await self._owned(chat,username,session_id,data['scope']):
                return False
            # Editing the latest WebChat message keeps its history row ID.
            latest_anchor = _anchor(await self._history(chat,session_id), include_latest_user=True)
            if latest_anchor != history_anchor or await self._hold(chat, username, session_id, data):
                return False
            current = await self._row(username,session_id)
            return (current is not None and current['revision'] == expected['revision']
                and current['data']['state'] == 'active' and current['data']['expires_at'] > self.clock()
                and self.live and chat is self.chat)

        if not await before_store(reservation):
            return
        summary = result if isinstance(result, dict) else {}
        kinds = [item.get('kind') for item in summary.get('sources', ()) if isinstance(item, dict)]
        task = dict(id='chat-companion-'+token_hex(16), scope=data['scope'],
            session=data['scope']['session_id'], text=text, images=[], delivery_lane=LANE,
            companion_sources=[kind for kind in COMPANION_SOURCE_CATEGORIES if kind in kinds],
            companion_composition=summary.get('composition'))
        adapter = self._adapter
        if adapter is None:
            adapter = ChatDeliveryAdapter(self.plugin,
                AstrBotDeliveryAdapter(self.plugin.context,media_root=self.journal.path.parent),database=chat.db)
        prepared = adapter.prepare(task)
        pending = await self._save(username,session_id,reservation,
            dict(reservation['data'], pending_task=task['id'],pending_text_key=fingerprint,reason='delivery_unknown'))
        try:
            delivered = await adapter.send(task,prepared,before_store=lambda: before_store(pending))
        except BeforeDispatchError:
            delivered = False
        if delivered is not None:
            await self._finish_attempt(username,session_id,task['id'],'saved' if delivered else 'scheduled')

    async def _delay_row(self,username,session_id,prior,reason,*,recheck_by=None,**extra):
        due = self.clock() + self._delay()
        if recheck_by is not None:
            # A near quiet-hours boundary should not cost another full idle interval.
            # Keep checking live settings at the normal cadence during longer holds.
            due = min(due, recheck_by)
        return await self._save(username,session_id,prior,dict(prior['data'],
            reason=reason,next_evaluation_at=due,**extra))

    async def _finish_attempt(self,username,session_id,task_id,reason):
        row = await self._row(username,session_id)
        if row is None or row['data'].get('pending_task') != task_id:
            return
        value = dict(row['data'])
        value.pop('pending_task')
        fingerprint = value.pop('pending_text_key',None)
        if reason == 'saved' and fingerprint:
            recent = _recent_text_keys(value)
            value['last_text_key'] = fingerprint
            value['recent_text_keys'] = list(dict.fromkeys((fingerprint, *recent)))[:RECENT_SAVED_TEXT_COUNT]
        now = self.clock()
        rest_until = _rest_deadline(value, now)
        anchor = rest_until or now
        state_reason = 'paused' if value['state'] == 'paused' else 'stopped'
        if value['state'] == 'active':
            state_reason = 'resting' if rest_until else reason
        value.update(reason=state_reason, next_evaluation_at=anchor+self._delay(), anchor_at=anchor)
        try:
            await self._save(username,session_id,row,value)
        except JournalConflict:
            # The saved history is still the authority if stop raced this write.
            pass

    async def _reconcile(self,chat,username,session_id,row):
        data=row['data']
        if not await self._owned(chat,username,session_id,data['scope']):
            if data['expires_at'] > self.clock():
                self._due[(username,session_id)] = self.clock()+self._delay()
            else:
                self._due.pop((username,session_id),None)
            return
        key = key_for(dict(scope=data['scope'],id=data['pending_task']))
        receipt = await asyncio.to_thread(self.journal.fetch, DELIVERY_NAMESPACE,key,
            ChatExpressions.message_scope(username,session_id))
        if receipt is None:
            await self._finish_attempt(username,session_id,data['pending_task'],'scheduled')
            return
        saved = receipt['data']['state'] == 'stored' or await has_saved_companion_delivery(chat.db, session_id, key)
        if saved and await self._owned(chat,username,session_id,data['scope']):
            await self._finish_attempt(username,session_id,data['pending_task'],'saved')
        elif data['expires_at'] > self.clock():
            self._due[(username,session_id)] = self.clock()+self._delay()
        else:
            self._due.pop((username,session_id),None)


def service_for(plugin):
    from .chat_expressions import ChatExpressionError
    try:
        links = identity_service(plugin)
    except ChatExpressionError as exc:
        raise CompanionUnavailable('陪伴模式暂不可用') from exc
    host = plugin._presence.living_host
    mode = getattr(host,'chat_companion_mode',None)
    if not links.current():
        raise CompanionUnavailable('陪伴模式暂不可用')
    if mode is None or mode.journal is not links.journal:
        mode = host.chat_companion_mode = ChatCompanionMode(plugin,host,links,clock=host.clock)
        last = getattr(getattr(plugin,'_native_chat_web_api',None),'_last_bound_chat',None)
        if last is not None:
            mode.bind(last)
    return mode
