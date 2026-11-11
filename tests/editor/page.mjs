// The test page: run every test and list the results. Open it at
// /tests/editor/ with the app started as  sh run.sh --tests

const item = (r) => {
  const li = document.createElement("li"), group = document.createElement("span");
  group.className = "group";
  group.textContent = r.group;
  li.append(group, r.name);
  if (r.error) {
    const why = document.createElement("span");
    why.className = "why";
    why.textContent = r.error;
    li.append(why);
  }
  return li;
};

// Imported here, not at the top, so a test file that can't be loaded (a typing
// slip, a missing module) is reported on the page rather than leaving it blank
let results;
try {
  results = await (await import("./all.mjs")).run();
} catch (e) {
  results = [{ group: "page", name: "loading the tests", error: e?.message || String(e) }];
}
const failed = results.filter((r) => r.error);
const summary = document.querySelector("#summary");
summary.textContent = `${results.length - failed.length} passed, ${failed.length} failed`;
summary.className = failed.length ? "fail" : "pass";
document.title = `${failed.length ? "FAILED" : "Passed"} · Editor tests`;
document.querySelector("#failures").replaceChildren(...failed.map(item));
document.querySelector("#all").replaceChildren(...results.map(item));
// For anything driving the page rather than reading it
window.editorTests = { passed: results.length - failed.length, failed: failed.length, results };
