'use strict';

/* One panel lifetime, over the existing account/session identity. No storage or I/O. */
window.ChatSessionScope = Object.freeze({
  create(readState, isOpen) {
    let generation = 0, bound = null;
    const pending = new Map();
    const key = () => { const s = readState(); return JSON.stringify([s.server, s.username, s.activeId]); };
    const invalidate = () => { generation++; bound = null; };
    const ticket = () => bound && Object.freeze({ ...bound, generation });
    const current = t => !!t && !!bound && isOpen() && readState().authenticated
      && t.generation === generation && t.owner === bound.owner && t.owner === key()
      && t.session === bound.session && t.session === readState().activeId;
    return Object.freeze({
      key, invalidate, ticket, current,
      enter() { invalidate(); bound = { owner: key(), session: readState().activeId }; return ticket(); },
      active() { return current(ticket()); },
      async settlePrevious(t) {
        const request = pending.get(t.owner);
        if (request) { try { await request; } catch (_) { /* A read cannot prove a previous write succeeded. */ } }
        return current(t);
      },
      waiting(t) { return !!t && pending.has(t.owner); },
      track(t, request) { pending.set(t.owner, request); },
      release(t, request) { if (pending.get(t.owner) === request) pending.delete(t.owner); },
    });
  },
});
