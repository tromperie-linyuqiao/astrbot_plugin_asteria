"""Read-only bounded diagnostics for the existing native material stores.

No migration, repair, deletion, index rebuild, model, sender or worker is owned.
Native rows use one full private identity. Archive statistics are an explicitly
separate administrator dataset and never attributed to the requested identity.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from contextlib import contextmanager
import hashlib
import json
import re
import time

from .models import canonical,private_scope,scope_key
from .native_memory import NativeMemoryStore
from .native_history_archive import NativeHistoryArchive

KINDS=frozenset({'real_observation','user_reported','model_inference','roleplay_event','action_result'})
TYPES=frozenset({'fact','preference','event','utterance','roleplay_event','model_inference'})
REFERENCE=re.compile(r'ha_[a-f0-9]{64}\Z')


class MaterialDiagnosticsConflict(RuntimeError):
    pass


@contextmanager
def _read_snapshot(store,open_check):
    # A deferred read transaction is not a write reservation and never enters
    # the stores' BEGIN IMMEDIATE mutation API. Never roll back someone else's
    # transaction when called reentrantly from an unrelated write operation.
    with store._lock:
        open_check()
        if store._db.in_transaction:raise MaterialDiagnosticsConflict('store already in transaction')
        store._db.execute('BEGIN')
        try:yield store._db
        finally:
            if store._db.in_transaction:store._db.execute('ROLLBACK')


class NativeMaterialDiagnostics:
    backend='native_material_diagnostics'

    def __init__(self,store,*,authorize,archive=None,clock=time.time):
        if not isinstance(store,NativeMemoryStore) or not callable(authorize) or not callable(clock):
            raise ValueError('existing native store and scope authority required')
        if archive is not None and not isinstance(archive,NativeHistoryArchive):
            raise ValueError('existing native read-only archive required')
        self.store,self.archive,self.authorize,self.clock=store,archive,authorize,clock

    def check(self,scope):
        scope=private_scope(scope)
        if self.authorize(scope) is not True:raise PermissionError('current genuine scope unavailable')
        return scope

    def preview(self,scope,*,limit=200,include_archive=True):
        scope=self.check(scope)
        if type(limit) is not int or not 1<=limit<=1000 or type(include_archive) is not bool:
            raise ValueError('bounded diagnostic options required')
        with _read_snapshot(self.store,self.store._check_open):
            self.check(scope)
            generation=self.store.data_generation(scope)
            counts=self.store.stats(scope)
            records=self.store.list(scope,limit=limit,offset=0,include_deleted=True)
            self.check(scope)
        source_counts=Counter();kind_counts=Counter();type_counts=Counter();groups=defaultdict(list)
        missing_evidence=0;refs=[];unrecognized_refs=0
        for row in records:
            # Store rows must still correspond to the exact requested identity;
            # a corrupt payload is a failure, never silently remapped to it.
            if (row.get('owner_bot_id')!=scope['bot_id'] or row.get('persona_id')!=scope['character_id']
                    or row.get('platform')!=scope['platform'] or row.get('session_id')!=scope['session_id']
                    or not isinstance(row.get('subject'),dict) or row['subject'].get('id')!=scope['user_id']):
                raise ValueError('native record identity inconsistent')
            kind=row.get('evidence_kind');kind_counts[kind if kind in KINDS else 'unknown']+=1
            typ=row.get('memory_type');type_counts[typ if typ in TYPES else 'other']+=1
            if kind not in KINDS or not isinstance(row.get('source_id'),str) or not row['source_id'].strip():missing_evidence+=1
            metadata=row.get('metadata');metadata=metadata if isinstance(metadata,dict) else {}
            adoption=metadata.get('history_adoption');adoption=adoption if isinstance(adoption,dict) else {}
            material=metadata.get('memory_transfer');material=material if isinstance(material,dict) else {}
            if material and row.get('source_id')=='memory.imported':source='user_supplied_material'
            elif adoption:source='reviewed_historical_material'
            elif kind=='real_observation':source='recorded_observation'
            elif kind=='roleplay_event':source='fictional_roleplay'
            elif kind=='model_inference':source='model_inference'
            else:source='explicit_or_other_native_source'
            source_counts[source]+=1
            reference=adoption.get('archive_id')
            if reference is not None:
                if isinstance(reference,str) and REFERENCE.fullmatch(reference):refs.append((row['id'],reference))
                else:unrecognized_refs+=1
            if row.get('lifecycle')!='deleted' and isinstance(row.get('content'),str):
                # Exact content AND type AND evidence class. Equal wording is
                # only a review candidate, never authority to merge/delete.
                key=(row['content'],row.get('memory_type'),row.get('evidence_kind'))
                groups[key].append(row['id'])
        duplicate_groups=[]
        for identities in groups.values():
            if len(identities)<2:continue
            identities=sorted(identities)
            duplicate_groups.append(dict(group_id=hashlib.sha256(canonical([scope_key(scope),identities]).encode()).hexdigest(),
                record_ids=identities[:20],total_records=len(identities),members_truncated=len(identities)>20))
        duplicate_groups.sort(key=lambda row:row['group_id'])
        references=dict(checked=0,available=0,missing=0,unknown=len(refs),invalid=unrecognized_refs,
            records=[],records_truncated=len(refs)>50)
        archive_report=dict(state='not_requested' if not include_archive else 'unavailable',
            dataset='administrator_read_only_history_archive',attributed_to_requested_scope=False,
            retrieval_enabled=False,scope_mapping_performed=False)
        if include_archive and self.archive is not None:
            if self.archive.retrieval_enabled is not False:raise RuntimeError('archive retrieval boundary changed')
            with _read_snapshot(self.archive,self.archive._open) as db:
                self.check(scope)
                total=db.execute('SELECT count(*) FROM history_archive_records').fetchone()[0]
                holds=db.execute('SELECT hold_json FROM history_archive_records ORDER BY id LIMIT ?',(limit,)).fetchall()
                hold_counts=Counter()
                for row in holds:
                    codes=json.loads(row[0])
                    for code in ('missing_historical_persona','missing_historical_bot'):
                        if code in codes:hold_counts[code]+=1
                reference_ids=sorted({ref for _,ref in refs})
                found=set()
                if reference_ids:
                    marks=','.join('?' for _ in reference_ids)
                    found={row[0] for row in db.execute('SELECT id FROM history_archive_records WHERE id IN ('+marks+')',reference_ids)}
                self.check(scope)
            archive_report.update(state='available',total_records=total,scanned_records=len(holds),scan_limit=limit,
                truncated=total>len(holds),sample_counts=dict(hold_counts),sample_scope='bounded_archive_sample_not_this_user',
                content_or_identity_rows_returned=False)
            references.update(checked=len(refs),available=sum(ref in found for _,ref in refs),
                missing=sum(ref not in found for _,ref in refs),unknown=0,
                records=[dict(record_id=identity,state='available' if ref in found else 'missing') for identity,ref in refs[:50]])
        self.check(scope)
        return dict(schema='tls.native_material_diagnostics.v1',backend=self.backend,sampled_at=self.clock(),
            scope=scope,read_only=True,cross_store_atomic_snapshot=False,native=dict(counts=counts,generation=generation,scan_limit=limit,
                scanned_records=len(records),truncated=counts['total']>len(records),includes_soft_deleted=True,
                sample_counts=dict(evidence_kinds=dict(kind_counts),memory_types=dict(type_counts),
                    source_categories=dict(source_counts),missing_evidence=missing_evidence),
                evidence_check='source_id_and_supported_evidence_kind_fields_only_not_truth_verification',
                duplicate_candidates=duplicate_groups[:50],duplicate_groups_total=len(duplicate_groups),
                duplicate_groups_truncated=len(duplicate_groups)>50,
                duplicate_rule='exact_content_plus_type_plus_evidence_kind_in_scanned_non_deleted_rows'),
            archive=archive_report,references=references,
            business_use=dict(llm_context_used='unknown',platform_ack='not_observed_here',phone_visible='not_observed_here'),
            writes=0,repairs=0,deletions=0,llm_calls=0,sends=0,
            available_maintenance=dict(logical_backup=True,append_restore_requires_preview_and_confirmation=True,
                safe_repair='derived_lexical_index_only',missing_originals='manual_review_no_reassignment',
                duplicate_resolution='manual_review_no_automatic_merge_or_delete'),
            boundary='只读体检与候选预览；重复不是删除指令，软删除不会物理清理；历史未归属统计不关联当前用户；不证明资料已被LLM使用。逻辑备份、追加恢复及派生索引修复使用独立明确确认入口。')
