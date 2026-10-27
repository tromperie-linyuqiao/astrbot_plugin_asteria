"""Bounded read-only AstrBot statistics source, owned by TLS.
No fallback database, old plugin calls, plaintext cache or connection survives a query.
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
import json
import time


class InsightSourceUnavailable(RuntimeError):
    pass


class NativeInsightReadStore:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock

    def _read(self, operation):
        if not self.path.is_file():
            raise InsightSourceUnavailable('database_missing')
        connection = None
        try:
            connection = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            deadline = time.monotonic() + 3
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            return operation(connection)
        except sqlite3.Error as exc:
            raise InsightSourceUnavailable('database_schema_or_read_unavailable') from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _columns(db, table):
        if table not in {'provider_stats', 'conversations'}:
            raise ValueError('fixed insight table required')
        return {row['name'] for row in db.execute('PRAGMA table_info(' + table + ')')}

    def usage(self, days, *, session_id=None):
        def read(db):
            columns = self._columns(db, 'provider_stats')
            if not {'created_at', 'provider_id'} <= columns:
                raise InsightSourceUnavailable('provider_stats_schema_unavailable')
            if session_id is not None and 'umo' not in columns:
                raise InsightSourceUnavailable('scoped_usage_not_supported')
            model = "COALESCE(NULLIF(provider_model,''),provider_id)" if 'provider_model' in columns else 'provider_id'
            tokens = '+'.join('COALESCE(' + name + ',0)' for name in
                             ('token_input_other', 'token_input_cached', 'token_output') if name in columns)
            if not tokens:
                raise InsightSourceUnavailable('token_statistics_unavailable')
            since = self.clock() - days * 86400
            where, args = "julianday(created_at)>=julianday(?,'unixepoch')", [since]
            if session_id is not None:
                where += ' AND umo=?'; args.append(session_id)
            ttft = 'AVG(time_to_first_token)' if 'time_to_first_token' in columns else 'NULL'
            rows = [dict(row) for row in db.execute('SELECT substr(' + model + ',1,120) model,COUNT(*) calls,'
                'SUM(' + tokens + ') tokens,' + ttft + ' avg_ttft FROM provider_stats WHERE ' + where +
                ' GROUP BY ' + model + ' ORDER BY calls DESC LIMIT 31', args)]
            daily = [dict(row) for row in db.execute("SELECT date(created_at,'+8 hours') day,COUNT(*) calls,SUM(" +
                tokens + ') tokens FROM provider_stats WHERE ' + where + ' GROUP BY day ORDER BY day LIMIT 91', args)]
            hourly = [dict(row) for row in db.execute("SELECT CAST(strftime('%H',created_at,'+8 hours') AS INT) hour,"
                'COUNT(*) calls FROM provider_stats WHERE ' + where + ' GROUP BY hour ORDER BY calls DESC LIMIT 5', args)]
            totals = dict(db.execute('SELECT COUNT(*) calls,COALESCE(SUM(' + tokens + '),0) tokens FROM provider_stats WHERE ' + where, args).fetchone())
            return dict(state='available' if totals['calls'] else 'empty', by_model=rows[:30], daily=daily,
                hourly=hourly, totals=totals, models_truncated=len(rows)>30, days=days,
                coverage='current_private_session' if session_id is not None else 'administrator_server_aggregate',
                monetary_cost='not_available_without_pricing', time_zone='UTC+08:00', atomic_across_queries=False)
        return self._read(read)

    def conversations(self, *, since, session_id=None, limit=60):
        if type(limit) is not int or not 1 <= limit <= 60:
            raise ValueError('bounded conversation sample required')
        def read(db):
            columns = self._columns(db, 'conversations')
            if not {'user_id', 'content', 'updated_at'} <= columns:
                raise InsightSourceUnavailable('conversation_schema_unavailable')
            where, args = 'julianday(updated_at)>=julianday(?)', [since]
            if session_id is not None:
                where += ' AND user_id=?'; args.append(session_id)
            # Bound the cumulative returned text before Python materializes it.
            sql = '''WITH chosen AS (
                SELECT content,updated_at,length(CAST(content AS BLOB)) bytes,
                    ROW_NUMBER() OVER(ORDER BY updated_at DESC,rowid DESC) pos
                FROM conversations WHERE ''' + where + ''' ORDER BY updated_at DESC,rowid DESC LIMIT ?),
                bounded AS (SELECT *,SUM(COALESCE(bytes,0)) OVER(ORDER BY pos) budget FROM chosen)
                SELECT CASE WHEN bytes<=262144 AND budget<=2097152 THEN content ELSE NULL END content,
                    updated_at,CASE WHEN bytes>262144 OR budget>2097152 THEN 1 ELSE 0 END oversize
                FROM bounded ORDER BY pos'''
            rows = [dict(row) for row in db.execute(sql, [*args, limit])]
            if any(row['oversize'] for row in rows):
                raise InsightSourceUnavailable('conversation_sample_budget_exceeded')
            for row in rows:
                if row['content'] is None:continue
                try:messages=json.loads(row['content'])
                except (ValueError,TypeError):raise InsightSourceUnavailable('conversation_json_unavailable')
                if not isinstance(messages,list):raise InsightSourceUnavailable('conversation_shape_unavailable')
            return rows
        return self._read(read)
