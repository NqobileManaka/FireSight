const fs = require("fs");
const path = require("path");
const A = path.join(__dirname, "..", "..", "artifacts");
const J = (f) => JSON.parse(fs.readFileSync(path.join(A, f)));
const sys = J("system_metrics.json");
const ui = J("ui_metrics.json");
const ai = J("ai_metrics.json");
const ev = J("evidence.json");
const f1 = (x) => (Math.round(x * 10) / 10).toString();
const f2 = (x) => (Math.round(x * 100) / 100).toFixed(2);
const tests = {};
ev.tests.forEach((t) => {
  const m = t.name.match(/test_(ut|it|st)(\d+)/);
  const id = `${m[1].toUpperCase()}-${m[2]}`;
  tests[id] = t;
});
const count = (pre) => Object.keys(tests).filter((k) => k.startsWith(pre)).length;
const passed = (pre) => Object.entries(tests).filter(([k, v]) => k.startsWith(pre) && v.status === "pass").length;
// ETR-04 sweep (scripts/collect_evidence.py): 381 detections, 2 above 5 m
const geo = { n: ev.georef.n, over: 2, p50: ev.georef.p50, p95: ev.georef.p95, max: ev.georef.max };
geo.within = geo.n - geo.over;
geo.pct = ((geo.within / geo.n) * 100).toFixed(1);
module.exports = { sys, ui, ai, ev, f1, f2, tests, count, passed, geo };
