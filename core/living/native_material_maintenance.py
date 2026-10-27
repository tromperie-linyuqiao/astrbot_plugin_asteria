"""Logical material backup/append restore and derived-index maintenance.

Uses the existing memory store, product managers and LivingJournal. This is
neither a database image nor a scheduler/ownership/lease restoration API.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time

from .journal import JournalConflict, LivingJournal
from .models import canonical, private_scope, scope_key
from .native_material_diagnostics import _read_snapshot
from .native_memory import NativeMemoryStore, _tokens
from .native_memory_transfer import NativeMemoryTransfer, _TYPES, _FIELDS, MAX_BYTES as MEMORY_BYTES
from .native_personal_materials import (NativePersonalMaterials, EDIT_FIELDS, personal_contract,
    PERSONAL_CAPACITY)

SCHEMA = 'tls.logical_material_backup.v1'
NAMESPACE = 'tls.material.maintenance.v1'
KINDS = ('memories', 'agreements', 'goal_definitions')
MAX_BYTES = 768 * 1024
_REQUEST = re.compile(r'[A-Za-z0-9_.:-]{1,96}\Z')


class MaintenanceOutcomeUnknown(RuntimeError):
    """A prior append may have committed; retain its request and inspect it."""


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def _plain(value):
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(raw.encode('utf-8')) > MAX_BYTES:
        raise ValueError('logical backup exceeds the 768 KiB document limit')
    return json.loads(raw)


class NativeMaterialMaintenance:
    def __init__(self, store, *, authorize, journal=None, goals=None, clock=time.time):
        if not isinstance(store, NativeMemoryStore) or not callable(authorize):
            raise TypeError('existing native store and dynamic authority required')
        if journal is not None and not isinstance(journal, LivingJournal):
            raise TypeError('existing shared journal required')
        self.store, self.authorize, self.journal, self.goals, self.clock = store, authorize, journal, goals, clock
        self.transfer = NativeMemoryTransfer(store, authorize=authorize, clock=clock)
        self.personal = NativePersonalMaterials(store, authorize=authorize, clock=clock)

    def check(self, scope):
        scope = private_scope(scope)
        if self.authorize(scope) is not True:
            raise PermissionError('current material scope unavailable')
        return scope

    @staticmethod
    def _owned(row, scope):
        if (row.get('owner_bot_id')!=scope['bot_id'] or row.get('persona_id')!=scope['character_id']
                or row.get('platform')!=scope['platform'] or row.get('session_id')!=scope['session_id']
                or row.get('subject')!={'kind':'user','id':scope['user_id']}):
            raise ValueError('stored material identity is inconsistent; manual inspection required')

    def status(self, scope):
        scope = self.check(scope)
        counts = self.store.stats(scope)
        personal = self.personal.list(scope, include_archived=True, limit=1)
        goals = self.goals.export(scope) if self.goals is not None else None
        size = None
        try:
            size = self.store.path.stat().st_size
        except OSError:
            pass
        journal = self.journal.stats() if self.journal is not None else None
        self.check(scope)
        return dict(schema='tls.material_maintenance.status.v1', scope=scope,
            capacity=dict(memories=dict(used=counts['total'], limit=None,
                note='原生记忆没有配置条数上限，不将未知容量显示为零'),
                agreements=dict(used=personal['total'], limit=PERSONAL_CAPACITY,
                    remaining=max(0, PERSONAL_CAPACITY-personal['total'])),
                goal_definitions=dict(used=goals['total'] if goals else None,
                    limit=getattr(self.goals, 'max_goals', None)),
                journal=dict(used=journal['checkpoints'] if journal else None,
                    limit=self.journal.max_records if self.journal else None,
                    scope='host_shared_not_this_user'),
                native_database_bytes=size, native_database_bytes_scope='shared_sqlite_file_not_this_user_only',
                filesystem_free_bytes=None),
            logical_types=list(KINDS), restorable_types=['memories', 'agreements'],
            restore_strategy='append_only_never_overwrite',
            excluded=['database_images','attachments','credentials','delivery_ledger','tasks','leases',
                'deduplication_events','goal_progress','goal_applied_events','share_claims'],
            full_host_restore=False, sends=0, model_calls=0)

    def export(self, scope, *, kinds=None, limit=20, offset=0):
        scope = self.check(scope)
        kinds = list(KINDS if kinds is None else kinds)
        if (not kinds or len(set(kinds)) != len(kinds) or set(kinds)-set(KINDS)
                or type(limit) is not int or not 1 <= limit <= 20
                or type(offset) is not int or not 0 <= offset <= 1000000):
            raise ValueError('choose supported types and a page of 1..20 records')
        sections = {}
        if 'memories' in kinds:
            with _read_snapshot(self.store, self.store._check_open):
                self.check(scope)
                generation = self.store.data_generation(scope)
                rows = self.store.list(scope, limit=limit, offset=offset, include_deleted=True)
                count = self.store.stats(scope)['total']
            records, excluded, scanned = [], [], 0
            for row in rows:
                self._owned(row,scope)
                if personal_contract(row, scope):
                    excluded.append(dict(id=row['id'], reason='managed_agreement_in_separate_section')); scanned+=1; continue
                if row.get('lifecycle') == 'deleted':
                    excluded.append(dict(id=row['id'], reason='archived_memory_not_automatically_restored')); scanned+=1; continue
                kind = row.get('memory_type')
                if kind not in _TYPES:
                    excluded.append(dict(id=row['id'], reason='specialized_material_requires_its_own_manager')); scanned+=1; continue
                original_kind=row.get('evidence_kind')
                if original_kind not in {'user_reported','real_observation','roleplay_event','model_inference','action_result'}:
                    excluded.append(dict(id=row['id'], reason='unrecognized_evidence_requires_manual_review')); scanned+=1; continue
                # Preserve the stronger fictional/inference boundary even if
                # an old record used a generic fact/preference type label.
                if original_kind=='roleplay_event':kind='roleplay_event'
                elif original_kind=='model_inference':kind='model_inference'
                elif original_kind=='action_result':kind='utterance'
                meta = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
                tags = meta.get('tags', [])
                tags = tags if isinstance(tags, list) and len(tags) <= 16 and all(isinstance(x,str) and 0<len(x)<=32 for x in tags) else []
                # A detached backup is not renewed sensor evidence. Preserve
                # provenance in the envelope and require explicit user report
                # confirmation when appending it into the current database.
                item = dict(id=row['id'], content=row['content'], memory_type=kind,
                    evidence_kind=_TYPES[kind], tags=list(dict.fromkeys(tags)),
                    source='maintenance:' + str(row.get('source_id',''))[:110], updated_at=row['updated_at'])
                if len(json.dumps([record['item'] for record in records]+[item],ensure_ascii=False).encode())>MEMORY_BYTES:
                    break
                records.append(dict(item=item, provenance=dict(source_id=row.get('source_id'),
                    original_evidence_kind=original_kind, original_memory_type=row.get('memory_type'),
                    original_revision=row['revision'])))
                scanned+=1
            sections['memories'] = dict(records=records, excluded=excluded,
                generation=generation, total=count, offset=offset, scanned=scanned,
                has_more=offset+scanned<count, next_offset=offset+scanned if offset+scanned<count else None,
                restore_evidence='user_confirmed_report_not_new_sensor_observation')
        if 'agreements' in kinds:
            sections['agreements'] = self.personal.export_batch(scope, include_archived=True, limit=limit, offset=offset)
        if 'goal_definitions' in kinds:
            if self.goals is None:
                sections['goal_definitions'] = dict(available=False, reason='goal_manager_unavailable')
            else:
                source = self.goals.export(scope, include_archived=True)
                rows = source['records'][offset:offset+limit]
                sections['goal_definitions'] = dict(available=True,
                    records=[dict(id=row['id'], fields=row['fields'], archived=row['archived'],
                        source_revision=row['revision']) for row in rows],
                    total=source['total'], offset=offset, has_more=offset+len(rows)<source['total'],
                    next_offset=offset+len(rows) if offset+len(rows)<source['total'] else None,
                    restore_supported=False, reason='定义快照；进度和应用事件不回放，请在目标专页维护')
        bundle = dict(schema=SCHEMA, scope=scope, created_at=self.clock(), limit=limit, offset=offset,
            sections=sections, logical_only=True, cross_store_atomic=False,
            includes_files=False, includes_execution_state=False)
        bundle['sha256'] = digest(bundle)
        self.check(scope)
        return _plain(bundle)

    def _bundle(self, scope, bundle, kind):
        value = _plain(bundle)
        if (type(value) is not dict or value.get('schema') != SCHEMA or value.get('scope') != scope
                or value.get('logical_only') is not True or value.get('includes_execution_state') is not False
                or kind not in ('memories','agreements') or kind not in value.get('sections', {})):
            raise ValueError('matching scoped logical backup and a restorable section required')
        sha = value.pop('sha256', None)
        if not isinstance(sha, str) or digest(value) != sha:
            raise ValueError('logical backup checksum mismatch')
        return value['sections'][kind], sha

    def restore_preview(self, scope, bundle, *, kind):
        scope = self.check(scope)
        section, sha = self._bundle(scope, bundle, kind)
        if kind == 'memories':
            records = section.get('records')
            if not isinstance(records, list) or not 1 <= len(records) <= 20:
                raise ValueError('memory restore requires 1..20 supported records')
            items = []
            for record in records:
                if type(record) is not dict or set(record) != {'item','provenance'} or not isinstance(record['item'],dict) or set(record['item'])-_FIELDS:
                    raise ValueError('invalid logical memory record')
                items.append(record['item'])
            payload = json.dumps(items, ensure_ascii=False)
            plan = self.transfer.preview(scope, payload, confirm_real_world=True)
            can = plan['counts']['failed'] == 0
            manager_sha = plan['preview_sha']
        else:
            # Existing product import preserves archived/conflicting records;
            # it never revives or overwrites them through a backup operation.
            payload = section
            plan = self.personal.preview_import(scope, payload)
            can, manager_sha = plan['can_import'], plan['preview_sha']
        result = dict(schema='tls.material.restore.preview.v1', scope=scope, kind=kind,
            bundle_sha256=sha, manager_preview=plan, manager_preview_sha=manager_sha,
            can_restore=can, append_only=True, overwrites=0, source_attribution='user_confirmed_logical_backup',
            confirmation='本人确认将此备份资料追加到完全相同的范围；不覆盖现有记录，不恢复任务/账本/权限。')
        result['preview_sha256'] = digest(result)
        return result

    def _receipt(self, scope, request_id):
        if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
            raise ValueError('stable maintenance request id required')
        key = 'request:' + digest(request_id)
        with self.store._lock:
            self.store._check_open(); self.check(scope)
            bulk=self._bulk_receipt(scope,request_id)
        if bulk is not None:
            return key,dict(data=bulk)
        if self.journal is None:
            raise RuntimeError('shared journal unavailable for maintenance audit')
        return key, self.journal.fetch(NAMESPACE, key, scope)

    def receipt(self, scope, request_id):
        scope = self.check(scope)
        _, record = self._receipt(scope, request_id)
        self.check(scope)
        return dict(found=record is not None, receipt=record['data'] if record else None,
            retry_automatically=False)

    def restore_confirm(self, scope, bundle, *, kind, preview_sha256, request_id, confirmed=False):
        scope = self.check(scope)
        if confirmed is not True:
            raise PermissionError('explicit restore confirmation required')
        key, previous = self._receipt(scope, request_id)
        section, sha = self._bundle(scope, bundle, kind)
        signature = digest(['restore', scope, kind, sha, preview_sha256])
        if previous:
            if previous['data'].get('signature') != signature:
                raise JournalConflict('maintenance request reused for another operation')
            if previous['data'].get('state') == 'completed':
                return dict(previous['data'], replayed=True)
            raise MaintenanceOutcomeUnknown('prior logical restore needs receipt/record reconciliation')
        preview = self.restore_preview(scope, bundle, kind=kind)
        if preview['preview_sha256'] != preview_sha256 or preview['can_restore'] is not True:
            raise JournalConflict('restore preview changed or contains unresolved conflicts')
        pending = dict(operation='logical_restore', signature=signature, state='pending', kind=kind,
            bundle_sha256=sha, preview_sha256=preview_sha256, started_at=self.clock(),
            records_overwritten=0, execution_state_restored=False)
        self.journal.put(NAMESPACE, key, scope, pending, expected_revision=0, authorize=lambda:self.authorize(scope) is True)
        if kind == 'memories':
            payload = json.dumps([record['item'] for record in section['records']], ensure_ascii=False)
            result = self.transfer.import_records(scope, payload, request_id='maintenance:'+digest(request_id),
                preview_sha=preview['manager_preview_sha'], confirmed=True, confirm_real_world=True)
        else:
            result = self.personal.confirm_import(scope, section,
                preview_sha=preview['manager_preview_sha'], request_id='maintenance:'+digest(request_id), owner_confirmed=True)
        self.check(scope)
        records = result.get('records', [])
        summary = dict(state=result.get('state','committed'),
            created=result.get('created',result.get('imported_count',0)), duplicates=result.get('duplicates',0),
            records=[{name:row[name] for name in ('id','revision','lifecycle','status') if name in row}
                for row in records])
        completed = dict(pending, state='completed', completed_at=self.clock(), result=summary)
        self.journal.put(NAMESPACE, key, scope, completed, expected_revision=1, authorize=lambda:self.authorize(scope) is True)
        self.journal.audit('material.logical_restore', scope, sha, 'completed', dict(kind=kind,
            request_sha256=digest(request_id), overwrite_count=0))
        return completed

    def _index_plan(self, scope, limit):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('index repair preview is bounded to 1..200 records')
        key = scope_key(scope)
        records = self.store.list(scope, limit=limit, include_deleted=True)
        changes = []
        for row in records:
            self._owned(row,scope)
            raw=self.store._raw(key,row['id'])
            if (raw is None or raw['revision']!=row['revision'] or raw['lifecycle']!=row['lifecycle']
                    or json.loads(raw['data'])!=row):
                raise ValueError('material row/source columns are inconsistent; index repair refused')
            expected = set() if row['lifecycle'] == 'deleted' else set(_tokens(row['content']))
            actual = {value[0] for value in self.store._db.execute(
                'SELECT token FROM tls_native_memory_terms WHERE scope=? AND record_id=?', (key,row['id']))}
            if expected != actual:
                changes.append(dict(id=row['id'], revision=row['revision'], expected=sorted(expected),
                    actual=sorted(actual), source_sha256=digest(row)))
        orphan = [dict(token=row[0], id=row[1]) for row in self.store._db.execute(
            'SELECT t.token,t.record_id FROM tls_native_memory_terms t LEFT JOIN tls_native_memories m '
            'ON m.scope=t.scope AND m.id=t.record_id WHERE t.scope=? AND m.id IS NULL '
            'ORDER BY t.record_id,t.token LIMIT 501', (key,))]
        if len(orphan)>500:
            raise ValueError('orphan index exceeds one repair batch; requires dedicated maintenance')
        return dict(generation=self.store.data_generation(scope), scanned=len(records),
            truncated=self.store.stats(scope)['total']>len(records), changes=changes, orphan=orphan)

    def repair_preview(self, scope, *, limit=100):
        scope = self.check(scope)
        with _read_snapshot(self.store, self.store._check_open):
            self.check(scope); plan = self._index_plan(scope, limit); self.check(scope)
        return dict(schema='tls.material.index_repair.preview.v1', scope=scope, preview_sha256=digest(plan),
            limit=limit, generation=plan['generation'], scanned=plan['scanned'], truncated=plan['truncated'],
            records=[dict(id=row['id'], revision=row['revision'], missing_terms=len(set(row['expected'])-set(row['actual'])),
                stale_terms=len(set(row['actual'])-set(row['expected']))) for row in plan['changes']],
            orphan_index_references=len(plan['orphan']), repairable=len(plan['changes'])+len(plan['orphan']),
            changes_only='derived_lexical_index', source_records_modified=0,
            missing_archive_references='report_only_no_guess_or_reassignment')

    def repair_confirm(self, scope, *, preview_sha256, request_id, limit=100, confirmed=False):
        scope = self.check(scope)
        if confirmed is not True:
            raise PermissionError('explicit derived-index repair confirmation required')
        key, previous = self._receipt(scope, request_id)
        signature = digest(['index_repair', scope, limit, preview_sha256])
        if previous:
            if previous['data'].get('signature') != signature:
                raise JournalConflict('maintenance request reused')
            if previous['data'].get('state') == 'completed':return dict(previous['data'],replayed=True)
            raise MaintenanceOutcomeUnknown('prior repair outcome needs reconciliation')
        pending = dict(operation='derived_index_repair', signature=signature, state='pending',
            preview_sha256=preview_sha256, started_at=self.clock())
        self.journal.put(NAMESPACE,key,scope,pending,expected_revision=0,authorize=lambda:self.authorize(scope) is True)
        with self.store.transaction():
            self.check(scope); plan = self._index_plan(scope,limit)
            if digest(plan) != preview_sha256:raise JournalConflict('index/source changed since repair preview')
            sk = scope_key(scope)
            for row in plan['changes']:
                self.store._db.execute('DELETE FROM tls_native_memory_terms WHERE scope=? AND record_id=?',(sk,row['id']))
                self.store._db.executemany('INSERT INTO tls_native_memory_terms VALUES(?,?,?)',
                    [(sk,token,row['id']) for token in row['expected']])
            for row in plan['orphan']:
                self.store._db.execute('DELETE FROM tls_native_memory_terms WHERE scope=? AND token=? AND record_id=?',
                    (sk,row['token'],row['id']))
            self.check(scope)
        completed = dict(pending,state='completed',completed_at=self.clock(), repaired_records=len(plan['changes']),
            orphan_index_references_removed=len(plan['orphan']), source_records_modified=0,
            memories_deleted=0, execution_ledger_modified=False)
        self.journal.put(NAMESPACE,key,scope,completed,expected_revision=1,authorize=lambda:self.authorize(scope) is True)
        self.journal.audit('material.index_repair',scope,preview_sha256,'completed',
            dict(repaired_records=len(plan['changes']),orphan_index_references_removed=len(plan['orphan'])))
        return completed

    @staticmethod
    def _ordinary_reason(row,scope):
        try:NativeMaterialMaintenance._owned(row,scope)
        except ValueError:return '资料身份字段不一致，请单项核对'
        metadata=row.get('metadata') if isinstance(row.get('metadata'),dict) else {}
        if (row.get('memory_type') not in _TYPES or row.get('source_id') in
                {'tls.personal.panel','tls.core.tool','tls.chat.profile_candidates'}
                or any(key in metadata for key in ('managed_by','native_profile_candidates',
                    'profile_dimension','projection_kind'))):
            return '特殊资料由其专用面板维护，不进入普通记忆批量操作'
        if row.get('lifecycle') not in {'stable_memory','deleted'}:
            return '当前资料生命周期不支持此批量操作'
        return ''

    def records(self,scope,*,include_archived=False,limit=20,offset=0):
        scope=self.check(scope)
        if (type(include_archived) is not bool or type(limit) is not int or not 1<=limit<=20
                or type(offset) is not int or not 0<=offset<=1000000):
            raise ValueError('bounded current material list required')
        with _read_snapshot(self.store,self.store._check_open):
            self.check(scope)
            rows=self.store.list(scope,limit=limit,offset=offset,include_deleted=include_archived)
            stats=self.store.stats(scope)
            total=stats['total' if include_archived else 'active']
            generation=self.store.data_generation(scope)
            result=[]
            for row in rows:
                reason=self._ordinary_reason(row,scope)
                result.append(dict(id=row['id'],revision=row['revision'],content=None if reason.startswith('资料身份') else row['content'],
                    memory_type=row['memory_type'],evidence_kind=row['evidence_kind'],source_id=row['source_id'],
                    archived=row['lifecycle']=='deleted',updated_at=row['updated_at'],
                    bulk_eligible=not reason,held_reason=reason))
            self.check(scope)
        return dict(schema='tls.material.bulk.list.v1',scope=scope,records=result,total=total,
            generation=generation,limit=limit,offset=offset,has_more=offset+len(rows)<total,
            next_offset=offset+len(rows) if offset+len(rows)<total else None,
            permanent_delete_supported=False,specialized_records_selectable=False)

    @staticmethod
    def _bulk_items(operation,items):
        if operation not in {'archive','restore'}:
            raise ValueError('only soft archive and restore are supported')
        if not isinstance(items,list) or not 1<=len(items)<=20:
            raise ValueError('select 1..20 records in one full scope')
        result=[];seen=set()
        for row in items:
            if (type(row) is not dict or set(row)!={'id','expected_revision'}
                    or not isinstance(row['id'],str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}',row['id'])
                    or type(row['expected_revision']) is not int or not 1<=row['expected_revision']<=2**53-1
                    or row['id'] in seen):
                raise ValueError('distinct record IDs and exact observed revisions required')
            seen.add(row['id']);result.append(dict(row))
        return sorted(result,key=lambda row:row['id'])

    def _bulk_plan(self,scope,operation,items):
        rows=[]
        for item in items:
            current=self.store.get(scope,item['id'],include_deleted=True)
            row=dict(id=item['id'],expected_revision=item['expected_revision'],current_revision=None,
                status='missing',reason='当前范围找不到该记录',content=None)
            if current is not None:
                reason=self._ordinary_reason(current,scope)
                row.update(current_revision=current['revision'],content=None if reason.startswith('资料身份') else current['content'],
                    archived=current['lifecycle']=='deleted',source_sha256=digest(current))
                if reason:row.update(status='unsupported',reason=reason)
                elif current['revision']!=item['expected_revision']:
                    row.update(status='conflict',reason='记录已修改，请刷新当前修订后重新选择')
                elif (current['lifecycle']=='deleted')==(operation=='archive'):
                    row.update(status='unchanged',reason='已处于目标状态，确认时保留原修订')
                else:row.update(status='ready',reason='仅软归档' if operation=='archive' else '恢复原记录，不重新生成或复制')
            rows.append(row)
        result=dict(schema='tls.material.bulk.preview.v1',scope=scope,operation=operation,items=items,
            records=rows,counts={name:sum(row['status']==name for row in rows)
                for name in ('ready','unchanged','missing','unsupported','conflict')},
            can_apply=all(row['status'] in {'ready','unchanged'} for row in rows),
            atomic=True,permanent_delete=False,execution_ledger_modified=False)
        result['preview_sha256']=digest(result)
        return result

    def bulk_preview(self,scope,*,operation,items):
        scope=self.check(scope);items=self._bulk_items(operation,items)
        with _read_snapshot(self.store,self.store._check_open):
            self.check(scope);result=self._bulk_plan(scope,operation,items);self.check(scope)
        return result

    def _bulk_receipt(self,scope,request_id):
        event='maintenance_bulk_'+digest(request_id)
        row=self.store._db.execute('SELECT fingerprint FROM tls_native_memory_events WHERE scope=? AND id=?',
            (scope_key(scope),event)).fetchone()
        if row is None:return None
        value=json.loads(row[0])
        if (type(value) is not dict or value.get('schema')!='tls.material.bulk.receipt.v1'
                or value.get('scope')!=scope or value.get('state')!='completed'
                or not isinstance(value.get('signature'),str) or not isinstance(value.get('records'),list)):
            raise MaintenanceOutcomeUnknown('stored material batch receipt is inconsistent')
        return value

    def bulk_confirm(self,scope,*,operation,items,preview_sha256,request_id,confirmed=False):
        scope=self.check(scope);items=self._bulk_items(operation,items)
        if confirmed is not True:raise PermissionError('explicit material batch confirmation required')
        if (not isinstance(request_id,str) or not _REQUEST.fullmatch(request_id)
                or not isinstance(preview_sha256,str) or not re.fullmatch('[a-f0-9]{64}',preview_sha256)):
            raise ValueError('stable request and exact preview required')
        signature=digest(['ordinary_memory_bulk',scope,operation,items,preview_sha256])
        event='maintenance_bulk_'+digest(request_id)
        if self.journal is not None:
            self.check(scope)
            foreign=self.journal.fetch(NAMESPACE,'request:'+digest(request_id),scope)
            self.check(scope)
            if foreign is not None:raise JournalConflict('request ID was already used by another maintenance operation')
        with self.store.transaction():
            self.check(scope)
            previous=self._bulk_receipt(scope,request_id)
            if previous is not None:
                if previous['signature']!=signature:raise JournalConflict('material request reused for different records')
                self.check(scope);return dict(previous,replayed=True)
            plan=self._bulk_plan(scope,operation,items)
            if plan['preview_sha256']!=preview_sha256 or not plan['can_apply']:
                raise JournalConflict('batch preview changed or includes unresolved conflicts')
            outcomes=[]
            for planned in plan['records']:
                self.check(scope)
                if planned['status']=='unchanged':
                    row=self.store.get(scope,planned['id'],include_deleted=True)
                else:
                    callback=self.store.delete if operation=='archive' else self.store.restore
                    row=callback(scope,planned['id'],planned['expected_revision'])
                outcomes.append(dict(id=row['id'],before_revision=planned['current_revision'],revision=row['revision'],
                    archived=row['lifecycle']=='deleted',status='unchanged' if planned['status']=='unchanged' else 'applied'))
            receipt=dict(schema='tls.material.bulk.receipt.v1',scope=scope,signature=signature,
                state='completed',operation=operation,preview_sha256=preview_sha256,records=outcomes,
                changed=sum(row['status']=='applied' for row in outcomes),completed_at=self.clock(),
                atomic=True,receipt_committed_with_records=True,permanent_deletions=0,
                execution_ledger_modified=False,generation=self.store.data_generation(scope))
            self.store._db.execute('INSERT INTO tls_native_memory_events VALUES(?,?,?,?)',
                (scope_key(scope),event,canonical(receipt),outcomes[0]['id']))
            self.check(scope)
        audit='unavailable'
        if self.journal is not None:
            try:
                self.journal.audit('material.bulk_'+operation,scope,digest(request_id),'completed',
                    dict(changed=receipt['changed'],selected=len(items),preview_sha256=preview_sha256))
                audit='recorded'
            except (RuntimeError,OSError,sqlite3.Error):
                audit='separate_audit_unconfirmed_atomic_store_receipt_available'
        return dict(receipt,replayed=False,audit=audit)
