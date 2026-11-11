// A test harness small enough to read in one go, so the editor's tests need
// nothing installed. The same test files run in a browser (index.html, served
// by the app when it's started with --tests) and under Node (run.mjs, in CI).
//
//   suite("geometry");
//   test("a box snaps to the label's edge", () => { eq(got, want); });

const tests = [];
let group = "";

export const suite = (name) => { group = name; };
export const test = (name, fn) => { tests.push({ group, name, fn }); };

// Values as text for a failure message. Sets are shown as their members.
const show = (v) => JSON.stringify(v, (k, x) => x instanceof Set ? { Set: [...x] } : x === undefined ? "(undefined)" : x);

// Equal all the way down: numbers and text by value, arrays in order, sets
// by their members, objects by their keys
function same(a, b) {
  if (a === b || (a !== a && b !== b)) return true;   // the second half: NaN equals NaN
  if (typeof a !== "object" || typeof b !== "object" || !a || !b) return false;
  if (a instanceof Set || b instanceof Set) {
    return a instanceof Set && b instanceof Set && a.size === b.size && [...a].every((x) => b.has(x));
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => k in b && same(a[k], b[k]));
}

const fail = (what, msg) => { throw new Error((what ? what + ": " : "") + msg); };

export const eq = (got, want, what = "") => { if (!same(got, want)) fail(what, `got ${show(got)}, expected ${show(want)}`); };
export const ok = (value, what = "") => { if (!value) fail(what, `got ${show(value)}, expected something true`); };
// Numbers that arithmetic may leave a hair apart
export const near = (got, want, what = "", by = 1e-9) => {
  if (!(Math.abs(got - want) <= by)) fail(what, `got ${show(got)}, expected ${show(want)} to within ${by}`);
};

// Run every test. Returns [{group, name, error}], error being null for a pass.
export async function run() {
  const results = [];
  for (const t of tests) {
    let error = null;
    try { await t.fn(); } catch (e) { error = e?.message || String(e); }
    results.push({ group: t.group, name: t.name, error });
  }
  return results;
}
