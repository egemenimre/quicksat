// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests for the viewer's logic in quicksat/scenario/templates/viewer_logic.js,
// run in Node from the repository with:
//
//     node --test "tests/**/*.test.js"
//
// The file is loaded as the page loads it, as a plain script. The data is the
// power sample's own output.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const LOGIC = path.join(ROOT, "quicksat", "scenario", "templates", "viewer_logic.js");

// A script's functions and constants are globals, as in the page. Run in this
// realm, the arrays they return compare with deepEqual.
vm.runInThisContext(fs.readFileSync(LOGIC, "utf8"), { filename: LOGIC });
const { PAGE_VERSION, scenarioProblem, checkPower, joinEclipses, pieceAt, stepAt, attitudeFraction, jointAngle, lightFraction } =
  vm.runInThisContext(
    "({ PAGE_VERSION, scenarioProblem, checkPower, joinEclipses, pieceAt, stepAt, attitudeFraction, jointAngle, lightFraction })",
  );

/** The data a viewer folder gives the page, from its scenario.js and power.js. */
function readFolder(folder) {
  const window = {};
  for (const name of ["scenario.js", "power.js"]) {
    new Function("window", fs.readFileSync(path.join(ROOT, folder, name), "utf8"))(window);
  }
  return window.quicksat;
}

const { scenario, power } = readFolder(path.join("sample", "power", "output"));
const T = scenario.grid.t_s;
const ILLUMINATION = scenario.tracks.illumination;

test("the power sample's files pass the checks", () => {
  assert.equal(scenarioProblem(scenario), "");
  assert.deepEqual(checkPower(power, scenario), [power, ""]);
});

test("a missing, foreign or newer scenario.js stops the page, with the reason", () => {
  assert.match(scenarioProblem(undefined), /no scenario\.js/);
  assert.match(scenarioProblem({ format: "quicksat-power", version: 1 }), /not a quicksat scenario file/);
  const newer = { format: "quicksat-scenario", version: PAGE_VERSION + 1 };
  assert.match(scenarioProblem(newer), new RegExp(`version ${PAGE_VERSION + 1}, but this page reads version ${PAGE_VERSION}`));
});

test("power.js from another run, or with steps or panels missing, is left out with a note", () => {
  assert.deepEqual(checkPower(undefined, scenario), [null, ""]);
  const cases = [
    [(file) => (file.version = PAGE_VERSION + 1), /newer than this page/],
    [(file) => (file.scenario_id = "0000000000000000"), /another scenario\.js/],
    [(file) => file.grid.soc.pop(), /different number of time steps/],
    [(file) => file.grid.panel_w.pop(), /different number of panels/],
  ];
  for (const [change, note] of cases) {
    const file = structuredClone(power);
    change(file);
    const [shown, why] = checkPower(file, scenario);
    assert.equal(shown, null);
    assert.match(why, note);
  }
});

test("each eclipse joins its penumbra, umbra and penumbra", () => {
  const eclipses = joinEclipses(ILLUMINATION);
  const umbras = ILLUMINATION.filter((piece) => piece.value === "umbra");
  assert.ok(eclipses.length > 0);
  assert.equal(eclipses.length, umbras.length);
  eclipses.forEach((eclipse, k) => {
    assert.equal(pieceAt(ILLUMINATION, eclipse.start_s).value, "penumbra");
    assert.ok(eclipse.start_s < umbras[k].start_s && umbras[k].end_s < eclipse.end_s);
    assert.equal(pieceAt(ILLUMINATION, eclipse.end_s).value, "sunlit");
  });
});

test("a piece holds its start and not its end", () => {
  const list = [{ start_s: 0 }, { start_s: 10 }, { start_s: 25 }];
  const found = [-5, 0, 9.999, 10, 24.999, 25, 99].map((time) => list.indexOf(pieceAt(list, time)));
  assert.deepEqual(found, [0, 0, 0, 1, 1, 2, 2]);
});

test("the step at a time is found on a grid whose last step is shorter", () => {
  const t = [0, 10, 20, 25];
  assert.deepEqual(stepAt(t, 15), [1, 0.5]);
  assert.deepEqual(stepAt(t, 20), [2, 0]);
  assert.deepEqual(stepAt(t, 22.5), [2, 0.5]);
  // before the start and after the end, the ends of the run
  assert.deepEqual(stepAt(t, -3), [0, 0]);
  assert.deepEqual(stepAt(t, 40), [2, 1]);
});

test("the light runs through each penumbra from 1 at its sunlit edge to 0 at its umbra edge", () => {
  const at = (time) => lightFraction(ILLUMINATION, T, scenario.grid.light, time, stepAt(T, time)[0]);
  // from 1 ms after the piece's start to 1 ms before its end
  const through = (piece) =>
    Array.from({ length: 11 }, (_, k) => at(piece.start_s + 0.001 + ((piece.end_s - piece.start_s - 0.002) * k) / 10));
  for (const eclipse of joinEclipses(ILLUMINATION)) {
    const entry = pieceAt(ILLUMINATION, eclipse.start_s);
    const exit = pieceAt(ILLUMINATION, eclipse.end_s - 0.001);
    assert.equal(at(eclipse.start_s - 1), 1);
    assert.equal(at((entry.end_s + exit.start_s) / 2), 0);
    // the light meets each edge, whatever grid steps the penumbra holds
    const falling = through(entry);
    const rising = through(exit);
    assert.ok(falling[0] > 0.99 && falling[10] < 0.01);
    assert.ok(rising[0] < 0.01 && rising[10] > 0.99);
    for (let k = 1; k < 11; k++) {
      assert.ok(falling[k] <= falling[k - 1] && rising[k] >= rising[k - 1]);
    }
  }
});

test("an attitude change without a slew is instant, and a slew turns the body across the step", () => {
  const t = [0, 10, 20];
  const instant = [
    { value: "nadir", start_s: 0, end_s: 14 },
    { value: "sun pointing", start_s: 14, end_s: 20 },
  ];
  // from 10 to 20 s the body holds nadir until 14 s, then sun pointing
  assert.equal(attitudeFraction(instant, t, 1, 0.2, 12), 0);
  assert.equal(attitudeFraction(instant, t, 1, 0.6, 16), 1);
  // a step with no change in it turns as the grid gives
  assert.equal(attitudeFraction(instant, t, 0, 0.5, 5), 0.5);
  const slewing = [
    { value: "nadir", start_s: 0, end_s: 14 },
    { value: "slew", target: "sun pointing", start_s: 14, end_s: 20 },
  ];
  assert.equal(attitudeFraction(slewing, t, 1, 0.2, 12), 0.2);
});

test("a part parks at once when its mode parks it, and turns the short way otherwise", () => {
  const t = [0, 10, 20];
  const modes = [
    { value: "idle", start_s: 0, end_s: 14 },
    { value: "imaging", start_s: 14, end_s: 20 },
  ];
  const wing = { angle_deg: [170, 150, 0], park_modes: ["imaging"] };
  assert.equal(jointAngle(wing, modes, t, 1, 0.2, 12), 150);
  assert.equal(jointAngle(wing, modes, t, 1, 0.6, 16), 0);
  const free = { angle_deg: [170, -170, 0], park_modes: [] };
  assert.equal(jointAngle(free, modes, t, 1, 0.5, 15), -85);
  // from 170 to -170 deg, through 180 rather than through 0
  assert.equal(jointAngle(free, modes, t, 0, 0.5, 5), 180);
});
