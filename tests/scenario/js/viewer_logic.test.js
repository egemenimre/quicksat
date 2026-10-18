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
// The file is loaded as the page loads it, as a plain script. The data in
// data/ is a copy of the power sample's output, sample/power/output/scenario.js
// and power.js. The sample changes with its notebook, and this copy changes
// only with the tests that read it. After a change to the viewer's data format,
// run the power notebook and copy the two files here again.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const LOGIC = path.join(ROOT, "quicksat", "scenario", "templates", "viewer_logic.js");
const DATA = path.join(__dirname, "data");

// A script's functions and constants are globals, as in the page. Run in this
// realm, the arrays they return compare with deepEqual.
vm.runInThisContext(fs.readFileSync(LOGIC, "utf8"), { filename: LOGIC });
const NAMES =
  "PAGE_VERSION, POWER_VERSION, scenarioProblem, checkPower, joinEclipses, pieceAt, stepAt, attitudeFraction, jointAngle, " +
  "lightFraction, excessPieces, passAt, earthFixed, geodeticOf, groundPoint, pointedTargets, arrowTargets, pointedSpans, " +
  "sharedSeconds, occurrenceAt, occurrencesOf, orbitMarks, viewFromHash";
const {
  PAGE_VERSION, POWER_VERSION, scenarioProblem, checkPower, joinEclipses, pieceAt, stepAt, attitudeFraction, jointAngle,
  lightFraction, excessPieces, passAt, earthFixed, geodeticOf, groundPoint, pointedTargets, arrowTargets, pointedSpans,
  sharedSeconds, occurrenceAt, occurrencesOf, orbitMarks, viewFromHash,
} = vm.runInThisContext(`({ ${NAMES} })`);

/** The data a viewer folder gives the page, from its scenario.js and power.js. */
function readFolder(folder) {
  const window = {};
  for (const name of ["scenario.js", "power.js"]) {
    new Function("window", fs.readFileSync(path.join(folder, name), "utf8"))(window);
  }
  return window.quicksat;
}

const { scenario, power } = readFolder(DATA);
const T = scenario.grid.t_s;
const ILLUMINATION = scenario.tracks.illumination;

test("the power sample's files pass the checks", () => {
  assert.equal(scenarioProblem(scenario), "");
  assert.deepEqual(checkPower(power, scenario), [power, ""]);
});

test("a missing, foreign, newer or older scenario.js stops the page, with the reason", () => {
  assert.match(scenarioProblem(undefined), /no scenario\.js/);
  assert.match(scenarioProblem({ format: "quicksat-power", version: 1 }), /not a quicksat scenario file/);
  const newer = { format: "quicksat-scenario", version: PAGE_VERSION + 1 };
  assert.match(scenarioProblem(newer), new RegExp(`version ${PAGE_VERSION + 1}, but this page reads version ${PAGE_VERSION}\\.`));
  const older = { format: "quicksat-scenario", version: PAGE_VERSION - 1 };
  assert.match(scenarioProblem(older), new RegExp(`version ${PAGE_VERSION - 1}, but this page reads version ${PAGE_VERSION}\\.`));
});

test("power.js of another version or run, or with steps or panels missing, is left out with a note", () => {
  assert.deepEqual(checkPower(undefined, scenario), [null, ""]);
  const reads = new RegExp(`but this page reads version ${POWER_VERSION}\\.`);
  const cases = [
    [(file) => (file.version = POWER_VERSION + 1), reads],
    [(file) => (file.version = POWER_VERSION - 1), reads],
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

test("the steps past the slew limits inside one attitude join into spans", () => {
  const t = [0, 10, 20, 30, 40, 50, 60, 70];
  const track = [
    { value: "track station", start_s: 0, end_s: 60 },
    { value: "slew", target: "nadir", start_s: 60, end_s: 70 },
  ];
  const attitude = {
    rate_deg_s: [0.5, 0.8, 0.9, 0.5, 0.5, 0.5, 0.9, null],
    acceleration_deg_s2: [null, 0.01, 0.01, 0.01, 0.01, 0.2, 0.01, null],
    max_rate_deg_s: 0.7,
    max_acceleration_deg_s2: 0.08,
  };
  // the rate passes from 10 to 30 s, and the acceleration at 50 s, which marks
  // the steps on both sides of it; the slew from 60 s is left out
  assert.deepEqual(excessPieces(t, attitude, track), [
    { start_s: 10, end_s: 30 },
    { start_s: 40, end_s: 60 },
  ]);
  // with no limits, nothing is passed
  assert.deepEqual(excessPieces(t, { ...attitude, max_rate_deg_s: null, max_acceleration_deg_s2: null }, track), []);
});

test("the sample's spans past the limits are its warnings' passes", () => {
  const spans = excessPieces(T, scenario.attitude, scenario.tracks.attitude);
  const attitudes = new Set(spans.map((span) => pieceAt(scenario.tracks.attitude, span.start_s).value));
  assert.deepEqual([...attitudes], ["track Svalbard"]);
});

test("a target is in view from the start of a pass to its end, and at the end of the run", () => {
  const passes = [
    { start_s: 10, end_s: 20 },
    { start_s: 30, end_s: 40 },
  ];
  assert.equal(passAt(passes, 5, 40), null);
  assert.equal(passAt(passes, 10, 40), passes[0]);
  assert.equal(passAt(passes, 19.999, 40), passes[0]);
  assert.equal(passAt(passes, 20, 40), null);
  assert.equal(passAt(passes, 40, 40), passes[1]);
  assert.equal(passAt(passes, 40, 50), null);
  assert.equal(passAt([], 10, 40), null);
});

test("the sample's positions give back its latitude and longitude in Earth-fixed axes", () => {
  const { r_km: r, q_earth: q, lat_deg: lat, lon_deg: lon } = scenario.grid;
  for (let k = 0; k < T.length; k += 7) {
    const fixed = earthFixed(q.slice(4 * k, 4 * k + 4), r.slice(3 * k, 3 * k + 3));
    const [latitude, longitude] = geodeticOf(fixed);
    assert.ok(Math.abs(latitude - lat[k]) < 1e-3, `latitude at step ${k}: ${latitude} against ${lat[k]}`);
    assert.ok(Math.abs(((longitude - lon[k] + 540) % 360) - 180) < 1e-3, `longitude at step ${k}`);
  }
});

test("a ground point's position and its geodetic place turn into each other", () => {
  for (const [latitude, longitude, altitude] of [[78.229, 15.408, 0.5], [0, 0, 0], [-90, 0, 0], [43.6, -120, 2], [89.99, 179, 500]]) {
    const [lat, lon] = geodeticOf(groundPoint(latitude, longitude, altitude));
    assert.ok(Math.abs(lat - latitude) < 1e-9, `latitude ${latitude}`);
    if (Math.abs(latitude) < 90) assert.ok(Math.abs(lon - longitude) < 1e-9, `longitude ${longitude}`);
  }
  // the polar radius is 21.4 km short of the equatorial one
  assert.ok(Math.abs(groundPoint(90, 0, 0)[2] - 6356.752) < 1e-3);
});

test("the body points at the targets of its attitude, and of each part its mode does not park", () => {
  const pointing = { attitudes: { "track RELAY": ["RELAY"] }, articulations: { antenna: "Svalbard" } };
  const attitudes = [
    { value: "nadir", start_s: 0, end_s: 10 },
    { value: "slew", target: "track RELAY", start_s: 10, end_s: 20 },
    { value: "track RELAY", start_s: 20, end_s: 40 },
  ];
  const modes = [
    { value: "idle", start_s: 0, end_s: 30 },
    { value: "downlink", start_s: 30, end_s: 40 },
  ];
  const joints = [{ name: "antenna", park_modes: ["downlink"] }];
  assert.deepEqual(pointedTargets(pointing, attitudes, modes, joints, 5), ["Svalbard"]);
  assert.deepEqual(pointedTargets(pointing, attitudes, modes, joints, 15), ["Svalbard"]);
  assert.deepEqual(pointedTargets(pointing, attitudes, modes, joints, 25), ["RELAY", "Svalbard"]);
  assert.deepEqual(pointedTargets(pointing, attitudes, modes, joints, 35), ["RELAY"]);
});

test("the spans the body points at each target join, and leave out its slews and parked parts", () => {
  const pointing = { attitudes: { "track RELAY": ["RELAY"], "track both": ["RELAY", "Svalbard"] }, articulations: { antenna: "Svalbard" } };
  const attitudes = [
    { value: "nadir", start_s: 0, end_s: 10 },
    { value: "slew", target: "track RELAY", start_s: 10, end_s: 20 },
    { value: "track RELAY", start_s: 20, end_s: 40 },
    { value: "track both", start_s: 40, end_s: 50 },
    { value: "nadir", start_s: 50, end_s: 60 },
  ];
  const modes = [
    { value: "idle", start_s: 0, end_s: 30 },
    { value: "downlink", start_s: 30, end_s: 45 },
    { value: "idle", start_s: 45, end_s: 60 },
  ];
  const joints = [{ name: "antenna", park_modes: ["downlink"] }];
  const spans = pointedSpans(pointing, attitudes, modes, joints);
  assert.deepEqual(spans, {
    RELAY: [{ start_s: 20, end_s: 50 }],
    Svalbard: [
      { start_s: 0, end_s: 30 },
      { start_s: 40, end_s: 60 },
    ],
  });
  // the same as pointedTargets at each time
  for (let t = 0.5; t < 60; t += 1) {
    const now = Object.keys(spans).filter((name) => passAt(spans[name], t, 60)).sort();
    assert.deepEqual(now, pointedTargets(pointing, attitudes, modes, joints, t).sort(), `at ${t} s`);
  }
  // a part that the model does not have points at nothing
  assert.deepEqual(pointedSpans(pointing, attitudes, modes, []).Svalbard, [{ start_s: 40, end_s: 50 }]);
  assert.equal(sharedSeconds(spans.Svalbard, 25, 45), 10);
  assert.equal(sharedSeconds(spans.Svalbard, 30, 40), 0);
  assert.equal(sharedSeconds([], 0, 60), 0);
});

test("the arrows go to the nearest targets in view, and to those the body points at", () => {
  const ranges = { A: 3000, B: 1200, C: 2500, D: 900, E: 4000 };
  assert.deepEqual(arrowTargets(["A", "B", "C"], ranges, [], 4), ["B", "C", "A"]);
  assert.deepEqual(arrowTargets(["A", "B", "C", "D", "E"], ranges, [], 4), ["D", "B", "C", "A"]);
  // a pointed target is drawn even out of view, and only once
  assert.deepEqual(arrowTargets(["A", "B", "C", "D", "E"], ranges, ["E", "B"], 2), ["D", "B", "E"]);
});

test("the sample's downlink points the body at Svalbard", () => {
  const svalbard = scenario.targets.find((target) => target.name === "Svalbard");
  assert.equal(svalbard.kind, "ground");
  assert.ok(svalbard.passes.length >= 2);
  const downlink = scenario.occurrences.find((o) => o.attitude === "track Svalbard");
  const middle = (downlink.start_s + downlink.end_s) / 2;
  assert.deepEqual(pointedTargets(scenario.pointing, scenario.tracks.attitude, scenario.tracks.mode, [], middle), ["Svalbard"]);
  // the downlink ends 2 min after Svalbard sets, so Svalbard is in view just before that
  assert.ok(passAt(svalbard.passes, downlink.end_s - 121, T[T.length - 1]));
  assert.equal(passAt(svalbard.passes, downlink.end_s - 119, T[T.length - 1]), null);
  // the turn to nadir fills those 2 min, so the body points at Svalbard through nearly all its pass
  const spans = pointedSpans(scenario.pointing, scenario.tracks.attitude, scenario.tracks.mode, []).Svalbard;
  const pass = passAt(svalbard.passes, middle, T[T.length - 1]);
  const span = passAt(spans, middle, T[T.length - 1]);
  assert.ok(pass.end_s < span.end_s && span.end_s < downlink.end_s - 100);
  assert.ok(sharedSeconds(spans, pass.start_s, pass.end_s) > 0.99 * (pass.end_s - pass.start_s));
});

// ---------------------------------------------------------------- The Activity Designer

// One pass of a list of three activities in a run of 100 s: the second has a
// negative duration, and the time after 60 s is unplanned
const ONE_PASS = [
  { repeat: 1, number: 1, start_s: 0, end_s: 30 },
  { repeat: 1, number: 2, start_s: 30, end_s: 20 },
  { repeat: 1, number: 3, start_s: 30, end_s: 60 },
];

test("the occurrence at a time is null where no activity plans the run", () => {
  assert.equal(occurrenceAt(ONE_PASS, 0, 100).number, 1);
  assert.equal(occurrenceAt(ONE_PASS, 29.9, 100).number, 1);
  // the negative duration takes no time, so the third is under way from 30 s
  assert.equal(occurrenceAt(ONE_PASS, 30, 100).number, 3);
  assert.equal(occurrenceAt(ONE_PASS, 59.9, 100).number, 3);
  assert.equal(occurrenceAt(ONE_PASS, 60, 100), null);
  assert.equal(occurrenceAt(ONE_PASS, 100, 100), null);
  assert.equal(occurrenceAt([], 10, 100), null);
  // in a planned run, the end of the run belongs to the last occurrence
  const full = [...ONE_PASS.slice(0, 2), { repeat: 1, number: 3, start_s: 30, end_s: 100 }];
  assert.equal(occurrenceAt(full, 100, 100).number, 3);
});

test("the occurrences of one activity leave out those that take no time", () => {
  const repeated = [...ONE_PASS, { repeat: 2, number: 1, start_s: 60, end_s: 90 }];
  assert.deepEqual(occurrencesOf(repeated, 1).map((o) => o.start_s), [0, 60]);
  assert.deepEqual(occurrencesOf(repeated, 2), []);
  assert.deepEqual(occurrencesOf(repeated, 4), []);
});

test("the orbit marks fall on each whole orbit up to the end of the run", () => {
  assert.deepEqual(orbitMarks(5691.055, 17073.164), [
    { time_s: 5691.055, label: "1 orbit" },
    { time_s: 11382.11, label: "2 orbits" },
    // three periods pass the end by 1 ms of rounding, so the mark sits on the end
    { time_s: 17073.164, label: "3 orbits" },
  ]);
  assert.deepEqual(orbitMarks(5691.055, 5000), []);
  assert.deepEqual(orbitMarks(0, 5000), []);
  assert.deepEqual(orbitMarks(null, 5000), []);
});

test("the view comes back from the address's hash, or null", () => {
  assert.deepEqual(viewFromHash("#t=1200.5&zoom=600,4200"), { t: 1200.5, zoom: [600, 4200] });
  assert.deepEqual(viewFromHash("#t=30"), { t: 30, zoom: null });
  assert.deepEqual(viewFromHash(""), { t: null, zoom: null });
  assert.deepEqual(viewFromHash("#t=x&zoom=9,3"), { t: null, zoom: null });
  assert.deepEqual(viewFromHash("#t=&zoom=1,2,3"), { t: null, zoom: null });
});
