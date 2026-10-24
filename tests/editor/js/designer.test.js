// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests for the Activity Designer's words on the editor's page, in
// quicksat/editor/templates/scenario/designer.js, run in Node from the
// repository with:
//
//     node --test "tests/**/*.test.js"
//
// The script listens for the frame's messages as it loads, so the window is a
// stand-in that takes the listener. The rows are as the server's `design`
// answers them, from `activity_rows`.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const DESIGNER = path.resolve(__dirname, "..", "..", "..", "quicksat", "editor", "templates", "scenario", "designer.js");
globalThis.window = { addEventListener() {} };
vm.runInThisContext(fs.readFileSync(DESIGNER, "utf8"), { filename: DESIGNER });
const { activityKey, designer, designerChanged, generate, lengthText, periodText, rowParts } = vm.runInThisContext(
  "({ activityKey, designer, designerChanged, generate, lengthText, periodText, rowParts })",
);

/** A row of the server's answer, with nothing to report but its count. */
const row = (fields) => ({
  number: 1, count: 1, statuses: {}, outside_s: null, slew_s: null, excesses: 0,
  peak_rate_deg_s: null, peak_acceleration_deg_s2: null, ...fields,
});
const LIMITS = { max_rate_deg_s: 0.7, max_acceleration_deg_s2: 0.08 };

test("a row says how many times its activity came", () => {
  assert.deepEqual(rowParts(row({}), LIMITS), [["count", "once"]]);
  assert.deepEqual(rowParts(row({ count: 3 }), LIMITS), [["count", "3 times"]]);
  assert.deepEqual(rowParts(row({ count: 0 }), LIMITS), [["count", "not reached in the run"]]);
});

test("a row gives each status as a failure, a warning or plain, as the viewer colours it", () => {
  const statuses = { "outside constraint": 2, "slew starts early": 1, "cut at end": 1 };
  assert.deepEqual(rowParts(row({ count: 3, statuses, outside_s: 6.5 }), LIMITS), [
    ["count", "3 times"],
    ["fail", "outside constraint 2 times, up to 6.5 s outside"],
    ["warn", "slew starts early once"],
    ["plain", "cut at end once"],
  ]);
  // the time outside is to a tenth of a second
  assert.equal(rowParts(row({ statuses: { "outside constraint": 1 }, outside_s: 1829.536 }), LIMITS)[1][1], "outside constraint once, up to 1829.5 s outside");
  assert.deepEqual(rowParts(row({ statuses: { "negative duration": 1, "event never came": 1 } }), LIMITS).slice(1), [
    ["fail", "negative duration once"],
    ["warn", "event never came once"],
  ]);
});

test("a turn faster than the slew block allows is a warning, with the peak against the limit", () => {
  const rate = row({ excesses: 1, peak_rate_deg_s: 0.84071, peak_acceleration_deg_s2: 0.0074 });
  assert.deepEqual(rowParts(rate, LIMITS)[1], ["warn", "turns faster than the slew limits once: 0.84 deg/s, limit 0.7 deg/s"]);
  const both = row({ count: 2, excesses: 2, peak_rate_deg_s: 0.9, peak_acceleration_deg_s2: 0.1 });
  assert.equal(
    rowParts(both, LIMITS)[1][1],
    "turns faster than the slew limits 2 times: 0.90 deg/s, limit 0.7 deg/s and 0.1000 deg/s², limit 0.08 deg/s²",
  );
  // a limit left out of the slew block is never passed
  const noRate = row({ excesses: 1, peak_rate_deg_s: 0.9, peak_acceleration_deg_s2: 0.1 });
  assert.equal(rowParts(noRate, { ...LIMITS, max_rate_deg_s: null })[1][1], "turns faster than the slew limits once: 0.1000 deg/s², limit 0.08 deg/s²");
});

test("the period gives the run and one pass of the list in time and in orbits", () => {
  const result = { duration_s: 17073.164, period_s: 5691.055, pass_s: 3869.976 };
  assert.equal(periodText(result), "Scenario: 4 h 45 min, 3.00 orbits · one pass of the list: 1 h 04 min, 0.68 orbits");
  assert.equal(periodText({ ...result, pass_s: null }), "Scenario: 4 h 45 min, 3.00 orbits · one pass of the list is longer than the run");
  assert.equal(periodText({ ...result, pass_s: 0 }), "Scenario: 4 h 45 min, 3.00 orbits · the list is empty");
  assert.equal(lengthText(1800), "30 min");
  assert.equal(lengthText(3600), "1 h 00 min");
});

test("a row changes for the run only through the fields the run reads", () => {
  const item = { title: "downlink", end: { kind: "set", target: "Svalbard" }, attitude: "track Svalbard", mode: "downlink", constraint: "", comments: "" };
  assert.equal(activityKey({ ...item, comments: "a note" }), activityKey(item));
  assert.notEqual(activityKey({ ...item, end: { kind: "set", target: "Kiruna" } }), activityKey(item));
  assert.notEqual(activityKey({ ...item, mode: "idle" }), activityKey(item));
  assert.equal(activityKey(undefined), "");
});

test("a change made while a run is under way leaves the run out of date", async () => {
  // stand-ins for the page and the server that a run reaches; the server
  // answers when the test says
  let answer;
  Object.assign(globalThis, {
    server: { state: "up" },
    S: { activities: [] },
    document: { querySelectorAll: () => [] },
    serverUrl: (path) => `/quicksat/${path}?key=k`,
    runFiles: () => [],
    checkServer: () => {},
    fetch: () => new Promise((resolve) => { answer = resolve; }),
  });
  designer.frame = {};
  const reply = (run) => {
    answer({ text: async () => JSON.stringify({ ok: true, rows: [] }) });
    return run;
  };

  // the first run has no result before it, and the change still counts
  let run = generate();
  designerChanged();
  await reply(run);
  assert.equal(designer.stale, true);

  // a run with no change during it is current
  await reply(generate());
  assert.equal(designer.stale, false);

  // a change during a later run
  run = generate();
  designerChanged();
  await reply(run);
  assert.equal(designer.stale, true);
});
