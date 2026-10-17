// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests that the editor's page finds the same satellites in a file as quicksat,
// run in Node from the repository with:
//
//     node --test "tests/**/*.test.js"
//
// quicksat/editor/templates/scenario/elements.js lists the element sets of a
// satellite target's file. It must agree with read_tle_sets and read_omm_sets,
// or the page would offer a satellite that the run cannot pick. The cases and
// Python's answers are in element_cases.json. tests/editor/test_elements_js.py
// writes them, and checks that they are still Python's.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const TEMPLATES = path.resolve(__dirname, "..", "..", "..", "quicksat", "editor", "templates");
// elements.js reads a CSV with open.js's parseCsv, as the page does
for (const file of [path.join(TEMPLATES, "shared", "open.js"), path.join(TEMPLATES, "scenario", "elements.js")]) {
  vm.runInThisContext(fs.readFileSync(file, "utf8"), { filename: file });
}
const { elementSets, orbitFileKind, pickedElementSet, elementSetLabel } = vm.runInThisContext(
  "({ elementSets, orbitFileKind, pickedElementSet, elementSetLabel })",
);

const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "element_cases.json"), "utf8"));

test("the cases hold TLE files and every form of OMM", () => {
  const names = CASES.map((c) => c.name);
  for (const end of [".tle", ".json", ".kvn", ".xml", ".csv"]) assert.ok(names.some((name) => name.endsWith(end)), end);
});

for (const { name, text, sets } of CASES) {
  test(`${name}: the same satellites as quicksat, with their epochs`, () => {
    const found = elementSets(name, text);
    assert.deepEqual(
      found.map((set) => [set.name, set.number]),
      sets.map((set) => [set.name, set.number]),
    );
    // the epochs agree to the millisecond, as each side rounds its own
    found.forEach((set, j) => {
      const gap = Math.abs(Date.parse(`${set.epoch}Z`) - Date.parse(`${sets[j].epoch}Z`));
      assert.ok(gap <= 1, `${set.name}: ${set.epoch} against ${sets[j].epoch}`);
    });
  });
}

test("a trajectory file holds no element sets, and text that reads as none gives null", () => {
  assert.equal(orbitFileKind("inspector.oem", "CCSDS_OEM_VERS = 2.0"), "trajectory");
  assert.equal(orbitFileKind("inspector.ecsv", "# %ECSV 1.0"), "trajectory");
  assert.equal(elementSets("inspector.oem", "CCSDS_OEM_VERS = 2.0"), null);
  assert.equal(elementSets("notes.tle", "not a TLE\n"), null);
});

test("a target takes its element set by object, by its name, or as the only one", () => {
  const relays = CASES.find((c) => c.name === "relays.tle");
  const sets = elementSets(relays.name, relays.text);
  assert.equal(pickedElementSet(sets, "relay-03", "anything").set.number, 90003);
  assert.equal(pickedElementSet(sets, "90004", "anything").set.name, "RELAY-04");
  assert.equal(pickedElementSet(sets, "", "RELAY-05").set.number, 90005);
  assert.match(pickedElementSet(sets, "", "relay").problem, /no element set named or numbered "relay"/);
  const one = CASES.find((c) => c.name === "sso_510km.tle");
  const only = elementSets(one.name, one.text);
  assert.equal(pickedElementSet(only, "", "anything").set.number, 99999);
  assert.match(pickedElementSet(only, "RELAY-01", "anything").problem, /no element set/);
  assert.equal(elementSetLabel(only[0]), "catalogue number 99999");
  assert.equal(elementSetLabel(sets[0]), "RELAY-01 (90001)");
});
