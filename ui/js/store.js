// Shared state for one surface. Subscribers receive (state, changedKeys).

export const store = {
  state: null,
  subs: new Set(),

  set(patch) {
    Object.assign(this.state, patch);
    const changed = new Set(Object.keys(patch));
    for (const fn of this.subs) {
      try { fn(this.state, changed); } catch (err) { console.error(err); }
    }
  },

  subscribe(fn) {
    this.subs.add(fn);
    return () => this.subs.delete(fn);
  },
};
