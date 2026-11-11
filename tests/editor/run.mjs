// Run the editor's tests under Node:  node tests/editor/run.mjs
// CI does; the same tests run in a browser from the page beside this file.
import { run } from "./all.mjs";

const results = await run();
const failed = results.filter((r) => r.error);
for (const r of failed) console.log(`FAIL  ${r.group}: ${r.name}\n      ${r.error}`);
console.log(`${results.length - failed.length} passed, ${failed.length} failed`);
process.exit(failed.length ? 1 : 0);
