// Undo history: a list of snapshots (strings) and a place in it. The page
// decides what a snapshot holds and when one is taken.

export class History {
  constructor(max = 100) {
    this.max = max;
    this.list = [];
    this.pos = -1;
  }

  // Add a snapshot after the current one, dropping any that were undone.
  // One equal to the current snapshot isn't a step, and returns false.
  record(snapshot) {
    if (snapshot === this.list[this.pos]) return false;
    this.list = this.list.slice(0, this.pos + 1);
    this.list.push(snapshot);
    if (this.list.length > this.max) this.list.shift();
    this.pos = this.list.length - 1;
    return true;
  }

  // Move back (-1) or forward (1). Returns the snapshot now current, or null
  // at either end.
  step(d) {
    const to = this.pos + d;
    if (to < 0 || to >= this.list.length) return null;
    this.pos = to;
    return this.list[to];
  }

  get canUndo() { return this.pos > 0; }
  get canRedo() { return this.pos < this.list.length - 1; }
}
