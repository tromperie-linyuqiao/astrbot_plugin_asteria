"""Read-only reverse dependency view over current scoped life records."""
from collections import deque

from .autonomous_life import _id
from .personal_space import PersonalSpace, KINDS, _LIMIT


def project(life, scope, event_id):
    scope = life._scope(scope)
    _id(event_id)
    personal = PersonalSpace(life)
    with life.journal._lock:
        snapshot = life._retrieval_snapshot(scope)
        root = snapshot['all_records']['event'].get(event_id)
        if root is None: raise KeyError('life event not found in this scope')
        records = {(kind, identity): record for kind, group in snapshot['all_records'].items()
                   for identity, record in group.items()}
        counts = dict(snapshot['coverage'])
        for kind in KINDS:
            values = []
            for offset in range(0, _LIMIT[kind], 200):
                values.extend(personal.list_records(scope, kind, include_archived=True,
                    include_invalid=True, limit=200, offset=offset)['records'])
            counts[kind] = len(values)
            records.update({(kind, row['id']): row for row in values})
        reverse = {}
        for key, row in records.items():
            # Character references capture stable identity, not relationship
            # state. Correcting a relationship source must not falsely claim
            # that every meeting with that identity is also invalidated.
            for ref in row.get('dependencies', []):
                if ref['kind'] not in {'event', 'interest', 'space'}: continue
                reverse.setdefault((ref['kind'], ref['id']), []).append(key)
        origin = ('event', event_id)
        distance, paths = {origin: 0}, {}
        queue = deque([origin])
        while queue:
            parent = queue.popleft()
            for child in reverse.get(parent, []):
                if child == origin: continue
                paths.setdefault(child, set()).add(parent)
                if child not in distance:
                    distance[child] = distance[parent] + 1
                    queue.append(child)
        affected = []
        for key in sorted(paths, key=lambda key: (distance[key], key)):
            row = records[key]
            affected.append(dict(kind=key[0], id=key[1],
                title=row['fields'].get('title', row['fields'].get('name', '')),
                revision=row['revision'], version=row['version'], valid=row['valid'],
                archived=row['archived'], deleted=row.get('deleted', False),
                direct=distance[key] == 1, distance=distance[key],
                via=[dict(kind=kind, id=identity) for kind, identity in sorted(paths[key])],
                invalid_reasons=row.get('invalid_reasons', row.get('invalid_dependencies', []))))
        memory_reviews = []
        for key in [origin, *sorted(paths)]:
            if key[0] != 'event': continue
            row = records[key]
            for ref in row.get('memory_refs', []):
                memory_reviews.append(dict(event_id=row['id'], event_revision=row['revision'],
                    memory_id=ref['id'], memory_revision=ref['revision'], linked_at=ref.get('linked_at'),
                    current=None, verification='not_revalidated', review_required=True,
                    reason='event_source_correction_requires_linked_memory_review'))
        life._scope(scope)
        return dict(root_event_id=event_id, root_revision=root['revision'], root_version=root['version'],
            affected=affected, direct=[row for row in affected if row['direct']],
            indirect=[row for row in affected if not row['direct']],
            linked_memory_reviews=memory_reviews,
            coverage=dict(records_scanned=len(records), affected=len(affected), current_records_only=True,
                character_identity_edges_propagated=False, retained_limits=dict(snapshot['coverage']['limits'], **_LIMIT),
                memory_contents_read=False, summaries_recomputed=False, memory_links_revalidated=False),
            read_only=True, rewrites_records=False, rewrites_history=False)
