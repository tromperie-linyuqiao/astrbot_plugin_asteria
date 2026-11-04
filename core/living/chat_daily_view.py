"""Read-only mobile projection of scoped plans and existing fictional history."""
from datetime import datetime
from .native_important_dates import date_zone


def project(runtime, scope, overview, *, now):
    plans = getattr(runtime, 'scoped_daily_plans', None)
    zone_name = getattr(plans, 'timezone_name', 'UTC+08:00')
    zone = date_zone(zone_name)
    day = datetime.fromtimestamp(now, zone).date().isoformat()
    items, updated, available = [], None, plans is not None
    if plans is not None:
        for plan in plans.list(scope, day=day, limit=64)['records']:
            updated = max(updated or 0, plan['updated_at'])
            for item in plan['items']:
                status = 'cancelled' if plan['status'] == 'cancelled' else {
                    'pending': 'planned', 'completed': 'completed', 'cancelled': 'cancelled'
                }[item['status']]
                items.append(dict(id=item['id'], title=item['title'],
                    start_at=item['scheduled_at'], end_at=None, status=status,
                    detail=item.get('description', ''), source='tls.scoped_daily_plan',
                    completed_at=item.get('completed_at')))
    items.sort(key=lambda row: (row['start_at'], row['id']))
    ongoing = [row for row in overview.get('events', [])
               if row.get('valid') and not row.get('archived')
               and row.get('fields', {}).get('status') == 'ongoing']
    current = None
    if ongoing:
        row = ongoing[0]
        current = dict(id=row['id'], title=row['fields']['title'],
                       status='ongoing', updated_at=row.get('updated_at'))
    next_item = next((row for row in items if row['status'] == 'planned'
                      and row['start_at'] >= now), None)
    return dict(schedule=dict(date=day, timezone=zone_name, updated_at=updated,
                              available=available, items=items),
                daily_brief=dict(as_of=now, current=current, next=next_item,
                                 summary=overview.get('current_state', {}).get('summary', ''),
                                 fictional=True))
