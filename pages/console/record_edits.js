'use strict';

window.TLSRecordEdits = Object.freeze({
  changes(values, base) {
    return Object.fromEntries(Object.entries(values).filter(([field, value]) =>
      JSON.stringify(value) !== JSON.stringify(base[field])));
  },
  conflicts(local, base, latest) {
    return Object.keys(local).filter(field => {
      const refreshed = JSON.stringify(latest[field]);
      return refreshed !== JSON.stringify(base[field]) && refreshed !== JSON.stringify(local[field]);
    });
  },
});
