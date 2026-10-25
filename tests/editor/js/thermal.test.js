// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests for the Thermal tab's words on the editor's page, in
// quicksat/editor/templates/scenario/thermal.js, run in Node from the
// repository with:
//
//     node --test "tests/**/*.test.js"
//
// The Modes step renames and adds the payload's modes in the heat flows given
// by mode. The table by mode edits the heater row of the payload's consumption
// table, as the page holds it: the power of one unit in each mode, and the
// units on. The script draws nothing as it loads, so it needs no page.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const THERMAL = path.resolve(__dirname, "..", "..", "..", "quicksat", "editor", "templates", "scenario", "thermal.js");
// project.js's own rounding, which the script uses
globalThis.tidy = (x) => Number(Number(x).toPrecision(12));
vm.runInThisContext(fs.readFileSync(THERMAL, "utf8"), { filename: THERMAL });
const { addFlowMode, balanceHeaters, flowModes, flowsUsing, heaterRow, heaterWatts, renameFlowMode, roundUp, setHeaterWatts } = vm.runInThisContext(
  "({ addFlowMode, balanceHeaters, flowModes, flowsUsing, heaterRow, heaterWatts, renameFlowMode, roundUp, setHeaterWatts })",
);

/** The sample's heat flows, as the page reads them. */
const sampleFlows = () => ({
  heat_flows: {
    comments: "",
    items: [
      { name: "platform interface", byMode: false, power: -3, powers: {} },
      { name: "x-band rf", byMode: true, power: "", powers: { idle: 0, imaging: 0, downlink: -5 } },
    ],
  },
});

/** The sample's heater row, as the page reads it. */
const heater = (fields = {}) => ({
  id: "payload_heaters", units: 1, thermal: "heater", power: { idle: 35, imaging: 35, downlink: 35 }, ...fields,
});

test("the flows by mode name their modes, and a flow of one power names none", () => {
  const thermal = sampleFlows();
  assert.deepEqual(flowModes(thermal), ["idle", "imaging", "downlink"]);
  assert.deepEqual(flowsUsing(thermal, "downlink"), ["x-band rf"]);
  assert.deepEqual(flowsUsing(thermal, "safe"), []);
});

test("renaming a payload mode renames its cell in each flow by mode, in its place", () => {
  const thermal = sampleFlows();
  renameFlowMode(thermal, "downlink", "transfer");
  const [one, byMode] = thermal.heat_flows.items;
  assert.deepEqual(Object.entries(byMode.powers), [["idle", 0], ["imaging", 0], ["transfer", -5]]);
  assert.deepEqual(one.powers, {});
  assert.equal(one.power, -3);
  // a mode that no flow names changes nothing
  renameFlowMode(thermal, "safe", "survival");
  assert.deepEqual(flowModes(thermal), ["idle", "imaging", "transfer"]);
});

test("a new payload mode gets an empty cell in each flow by mode, and keeps a cell that is there", () => {
  const thermal = sampleFlows();
  addFlowMode(thermal, "safe");
  addFlowMode(thermal, "idle");
  const [one, byMode] = thermal.heat_flows.items;
  assert.deepEqual(byMode.powers, { idle: 0, imaging: 0, downlink: -5, safe: "" });
  assert.deepEqual(one.powers, {});
});

test("the heater row is the row marked heater", () => {
  const rows = [{ id: "a", thermal: "inside_mli" }, heater(), { id: "b", thermal: "outside_mli" }];
  assert.equal(heaterRow(rows).id, "payload_heaters");
  assert.equal(heaterRow(rows.filter((row) => row.thermal !== "heater")), null);
});

test("a mode's heater power is all the row's units together", () => {
  assert.equal(heaterWatts(heater(), "idle"), 35);
  assert.equal(heaterWatts(heater({ units: 2 }), "idle"), 70);
  assert.equal(heaterWatts(heater({ power: { idle: "" } }), "idle"), "");
});

test("setting a mode's heater power changes the power of one unit, and keeps the units", () => {
  const two = heater({ units: 2 });
  setHeaterWatts(two, "idle", 50);
  assert.equal(two.units, 2);
  assert.equal(two.power.idle, 25);
  assert.equal(heaterWatts(two, "idle"), 50);
  assert.equal(two.power.imaging, 35);
  // a row with no units on gets one, so that the power counts
  const none = heater({ units: 0 });
  setHeaterWatts(none, "imaging", 12.5);
  assert.deepEqual([none.units, none.power.imaging], [1, 12.5]);
  setHeaterWatts(none, "imaging", "");
  assert.equal(none.power.imaging, "");
});

test("the balancing power is rounded up to 0.1 W, and never below zero", () => {
  assert.equal(roundUp(67.49944889), 67.5);
  assert.equal(roundUp(67.4), 67.4);
  assert.equal(roundUp(2.0000000001), 2);
  assert.equal(roundUp(0), 0);
  assert.equal(roundUp(-3), 0);
});

test("balancing sets each mode's heater power from the table by mode", () => {
  const row = heater({ units: 2 });
  const modes = [
    { "payload mode": "idle", "balancing heater [W]": 67.49944889 },
    { "payload mode": "imaging", "balancing heater [W]": 0 },
    { "payload mode": "downlink", "balancing heater [W]": null },
  ];
  assert.deepEqual(balanceHeaters(row, modes), ["idle", "imaging"]);
  assert.equal(heaterWatts(row, "idle"), 67.5);
  assert.equal(row.power.idle, 33.75);
  assert.equal(heaterWatts(row, "imaging"), 0);
  // a mode with no balancing power keeps its heater
  assert.equal(heaterWatts(row, "downlink"), 70);
});
