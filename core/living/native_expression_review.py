"""A manual review queue before the existing expression learner, isolated only.

Candidates never contribute context. Explicit approval and application reuse
the existing parser, stable rule IDs, CAS and feedback receipts. No Host hook,
persona writer, model, sender or second memory store is installed here.
"""
from contextlib import contextmanager
import hashlib
import json
import math

from .journal import JournalConflict, LivingJournal
from .models import canonical, plain, private_scope, scope_key
from .native_expression_learning import NativeExpressionLearning, parse_feedback

NAMESPACE = 'tls.expression.review.v1'
MAX_CANDIDATES = 64
_STATES = {'pending', 'approved', 'rejected', 'applied'}


def _text(value, maximum):
    if (type(value) is not str or not 1 <= len(value) <= maximum or value != value.strip()
            or any(ord(c) < 32 for c in value)):
        raise ValueError('bounded explicit review text required')
    return value


def _revision(value):
    if type(value) is not int or not 1 <= value < 2**53:
        raise ValueError('exact positive candidate revision required')


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class _ApplicationJournal:
    """Use the same transaction with an approval guard immediately before COMMIT.

    NativeExpressionLearning.learn uses only _transaction and max_records.
    This operation-local view opens no connection and owns no data or worker.
    """
    def __init__(self, journal, guard):
        self._journal, self._guard = journal, guard

    @property
    def max_records(self):
        return self._journal.max_records

    @contextmanager
    def _transaction(self):
        with self._journal._transaction() as db:
            self._guard()
            yield db
            self._guard()


class NativeExpressionReview:
    def __init__(self, journal, learner, *, authorize, review_authorize, clock=None,
                 max_candidates=MAX_CANDIDATES):
        if (not isinstance(journal, LivingJournal) or type(learner) is not NativeExpressionLearning
                or learner.journal is not journal or not callable(authorize) or not callable(review_authorize)
                or type(max_candidates) is not int or not 1 <= max_candidates <= MAX_CANDIDATES):
            raise ValueError('existing shared journal, expression learner and explicit review authority required')
        self.journal, self.learner = journal, learner
        self._journal, self._learner = journal, learner
        self.authorize, self.review_authorize = authorize, review_authorize
        self.clock = journal.clock if clock is None else clock
        if not callable(self.clock):
            raise ValueError('review clock required')
        self.max_candidates, self.active = max_candidates, True

    def _scope(self, scope, reviewer=None):
        scope = private_scope(scope)
        if (not self.active or self.journal is not self._journal or self.learner is not self._learner
                or self.learner.journal is not self._journal or self._journal._closed
                or self.authorize(dict(scope)) is not True
                or self.learner.authorize(dict(scope)) is not True):
            raise PermissionError('expression review scope or owner unavailable')
        if reviewer is not None:
            _text(reviewer, 128)
            if self.review_authorize(dict(scope), reviewer) is not True:
                raise PermissionError('explicit current human review authority required')
        return scope

    def _now(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 < now <= 253402214400:
            raise ValueError('valid review clock required')
        return now

    @contextmanager
    def _transaction(self, scope, reviewer=None):
        with self._journal._transaction() as db:
            self._scope(scope, reviewer)
            yield db
            self._scope(scope, reviewer)

    def _get(self, db, scope, identity):
        identity = _text(identity, 100)
        stored = db.execute('SELECT key,revision,updated,data FROM checkpoints WHERE namespace=? AND scope=? AND key=?',
                            (NAMESPACE, scope_key(scope), identity)).fetchone()
        if stored is None:
            return None
        row = json.loads(stored['data'])
        if (type(row) is not dict or row.get('schema') != 1 or row.get('scope') != scope
                or row.get('id') != identity or row.get('state') not in _STATES
                or row.get('parsed') != parse_feedback(row.get('feedback'))
                or row.get('signature') != _digest([row.get('feedback'), row.get('source_message_id')])):
            raise RuntimeError('invalid expression review provenance')
        return dict(row, revision=stored['revision'], updated_at=stored['updated'])

    def _save(self, db, scope, row, revision):
        self._scope(scope)
        clean = {key: value for key, value in row.items() if key not in {'revision', 'updated_at'}}
        encoded, now = canonical(plain(clean, 16384)), self._now()
        if revision == 0:
            count = db.execute('SELECT COUNT(*) FROM checkpoints WHERE namespace=? AND scope=?',
                               (NAMESPACE, scope_key(scope))).fetchone()[0]
            if count >= self.max_candidates or db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] >= self._journal.max_records:
                raise RuntimeError('expression review capacity reached')
            db.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?)',
                       (NAMESPACE, row['id'], scope_key(scope), 1, now, encoded))
        else:
            changed = db.execute('UPDATE checkpoints SET revision=?,updated=?,data=? WHERE namespace=? AND scope=? AND key=? AND revision=?',
                                 (revision + 1, now, encoded, NAMESPACE, scope_key(scope), row['id'], revision)).rowcount
            if changed != 1:
                raise JournalConflict('expression candidate revision changed')
        saved = self._get(db, scope, row['id'])
        if saved != dict(clean, revision=revision + 1, updated_at=now):
            raise RuntimeError('expression candidate readback differs')
        self._scope(scope)
        return saved

    def get(self, scope, identity):
        scope = self._scope(scope)
        with self._journal._lock:
            self._journal._ensure_open()
            row = self._get(self._journal._db, scope, identity)
        self._scope(scope)
        return row

    def list(self, scope):
        scope = self._scope(scope)
        with self._journal._lock:
            self._journal._ensure_open()
            keys = self._journal._db.execute('SELECT key FROM checkpoints WHERE namespace=? AND scope=? ORDER BY key LIMIT ?',
                                             (NAMESPACE, scope_key(scope), self.max_candidates + 1)).fetchall()
            if len(keys) > self.max_candidates:
                raise RuntimeError('expression review capacity exceeded')
            rows = [self._get(self._journal._db, scope, item[0]) for item in keys]
        self._scope(scope)
        return rows

    def propose(self, scope, feedback, *, source_message_id, roleplay=False, quoted=False):
        scope = self._scope(scope)
        source = _text(source_message_id, 256)
        parsed = parse_feedback(feedback, roleplay=roleplay, quoted=quoted)
        if parsed is None:
            return {'state': 'unrecognized', 'candidate': None}
        feedback = _text(feedback, 500)
        identity = 'expr_review.' + _digest([scope, source])
        signature = _digest([feedback, source])
        with self._transaction(scope) as db:
            old = self._get(db, scope, identity)
            if old is not None:
                if old['signature'] != signature:
                    raise JournalConflict('source message ID reused for different correction')
                return old
            pattern = parsed.get('rule', parsed).get('pattern')
            preference = parsed.get('rule', {}).get('kind') == 'preference'
            matching = [row for row in self.learner.list(scope, include_deleted=True)
                        if row['pattern'] == pattern and (parsed['operation'] == 'withdraw'
                        and row['active'] or parsed['operation'] == 'set' and (row['kind'] == 'preference') == preference)]
            if len(matching) > 1 or parsed['operation'] == 'withdraw' and not matching:
                return {'state': 'unrecognized', 'candidate': None}
            return self._save(db, scope, dict(schema=1, id=identity, scope=scope, feedback=feedback,
                source_message_id=source, signature=signature, parsed=parsed, state='pending',
                target_rule_id=matching[0]['id'] if matching else None,
                target_revision=matching[0]['revision'] if matching else None,
                created_at=self._now(), approval=None, application=None), 0)

    def _review(self, scope, identity, *, expected_revision, reviewer_id, request_id, approved, note=''):
        scope = self._scope(scope, reviewer_id)
        _revision(expected_revision); request_id = _text(request_id, 128)
        if type(note) is not str or len(note) > 240 or any(ord(c) < 32 for c in note):
            raise ValueError('bounded human review note required')
        decision = dict(request_id=request_id, reviewer_id=reviewer_id, approved=approved, note=note)
        with self._transaction(scope, reviewer_id) as db:
            row = self._get(db, scope, identity)
            if row is None:
                raise KeyError('expression candidate absent')
            prior = row['approval']
            if prior is not None and prior['request_id'] == request_id:
                if any(prior[key] != value for key, value in decision.items()):
                    raise JournalConflict('review request ID reused with a different decision')
                return row
            if row['revision'] != expected_revision or row['state'] != 'pending':
                raise JournalConflict('candidate was already reviewed or changed')
            row['state'] = 'approved' if approved else 'rejected'
            row['approval'] = dict(decision, reviewed_at=self._now(), candidate_revision=row['revision'] + 1)
            return self._save(db, scope, row, row['revision'])

    def approve(self, scope, identity, **review):
        return self._review(scope, identity, approved=True, **review)

    def reject(self, scope, identity, **review):
        return self._review(scope, identity, approved=False, **review)

    def apply(self, scope, identity, *, expected_revision, reviewer_id):
        scope = self._scope(scope, reviewer_id); _revision(expected_revision)
        row = self.get(scope, identity)
        if row is None:
            raise KeyError('expression candidate absent')
        approval = row['approval']
        if (row['state'] not in {'approved', 'applied'} or approval is None or approval['approved'] is not True
                or expected_revision not in {row['revision'], approval['candidate_revision']}):
            raise JournalConflict('current approved candidate required')
        event_id = 'expression.review.apply.' + _digest([scope, identity, approval['request_id']])
        def guard():
            self._scope(scope, reviewer_id)
            with self._journal._lock:
                current = self._get(self._journal._db, scope, identity)
            if (current is None or current['state'] not in {'approved', 'applied'}
                    or current['approval'] != approval or current['signature'] != row['signature']):
                raise JournalConflict('approved correction changed during application')
            return True
        # The original learner and callback remain untouched. Its public learn
        # method still owns parsing, rule identity, CAS, receipts and Context.
        local = NativeExpressionLearning(_ApplicationJournal(self._journal, guard),
            authorize=lambda candidate: candidate == scope and guard(), clock=self.learner.clock,
            max_rules=self.learner.max_rules, max_events=self.learner.max_events)
        result = local.learn(scope, row['feedback'], source_message_id=event_id,
                             expected_revision=row['target_revision'])
        if result.get('state') not in {'learned', 'unchanged', 'withdrawn', 'duplicate'} or result.get('rule') is None:
            raise JournalConflict('existing rule changed; review a fresh correction')
        with self._transaction(scope, reviewer_id) as db:
            current = self._get(db, scope, identity)
            if current['state'] != 'applied':
                current['state'] = 'applied'
                current['application'] = dict(source_message_id=event_id, rule_id=result['rule']['id'],
                    rule_revision=result['rule']['revision'], applied_at=self._now())
                current = self._save(db, scope, current, current['revision'])
        return dict(candidate=current, rule=result['rule'], state='applied',
                    changes_persona=False, creates_send_permission=False)

    def approve_and_apply(self, scope, identity, *, expected_revision, reviewer_id, request_id, note=''):
        """One UI action may invoke this method; the internal receipt is retryable."""
        reviewed = self.approve(scope, identity, expected_revision=expected_revision,
                                reviewer_id=reviewer_id, request_id=request_id, note=note)
        return self.apply(scope, identity, expected_revision=reviewed['revision'], reviewer_id=reviewer_id)

    def stop(self):
        self.active = False

    def close(self):
        self.stop()
