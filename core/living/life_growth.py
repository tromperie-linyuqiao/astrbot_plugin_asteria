"""Daily source-backed restraint for generated changes, never manual correction."""
from copy import deepcopy

GROWTH_INTERVAL_SECONDS = 24 * 3600


def constrain(old_data, fields, names, *, now, event_id, event_version=1):
    """Keep a recent generated direction until its minimum interval has passed.

    This is not a psychological score or semantic truth judgement. Source
    provenance and original character identity checks remain in their owners.
    """
    previous = old_data['fields'] if old_data else {}
    marks = deepcopy((old_data or {}).get('growth_updates', {}))
    deferred = []
    for name in names:
        if fields.get(name) == previous.get(name): continue
        mark = marks.get(name)
        if mark and now < mark['at'] + GROWTH_INTERVAL_SECONDS:
            fields[name] = previous.get(name)
            deferred.append(dict(field=name, reason='growth_cooldown',
                next_eligible_at=mark['at']+GROWTH_INTERVAL_SECONDS,
                source_event_id=mark['event_id'], source_version=mark['event_version']))
        else:
            marks[name] = dict(at=now, event_id=event_id, event_version=event_version)
    return marks, deferred
