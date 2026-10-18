// The viewer's logic that needs no browser: the checks on the data files, and
// the values between grid steps. The page inlines this file in a script of its
// own, ahead of its main script, which calls these functions. The tests in
// tests/scenario/js/ load it in Node. So nothing here may touch the page, the
// window or the libraries: each function takes its data as arguments.
"use strict";

const PAGE_VERSION = 7;
const POWER_VERSION = 2;

const pad = (value) => String(value).padStart(2, "0");
const clamp = (x, lo, hi) => Math.min(Math.max(x, lo), hi);

// ---------------------------------------------------------------- Checks on the data files

/** Why the page cannot show this scenario data, or "" when it can. */
function scenarioProblem(scenario) {
  if (!scenario) {
    return (
      "This folder has no scenario.js, so there is nothing to show. The page reads its data from the " +
      "files next to it. Run the notebook that writes this folder again."
    );
  }
  if (scenario.format !== "quicksat-scenario" || !Number.isInteger(scenario.version)) {
    return "scenario.js is not a quicksat scenario file.";
  }
  if (scenario.version !== PAGE_VERSION) {
    return (
      `scenario.js is version ${scenario.version}, but this page reads version ${PAGE_VERSION}. ` +
      "Run the notebook again: it writes a matching page and data into the folder."
    );
  }
  return "";
}

/** The power data, if power.js is here and belongs to this scenario.js, and why not otherwise. */
function checkPower(power, scenario) {
  if (!power) return [null, ""];
  if (power.format !== "quicksat-power" || !Number.isInteger(power.version)) {
    return [null, "power.js is not a quicksat power file."];
  }
  if (power.version !== POWER_VERSION) {
    return [null, `power.js is version ${power.version}, but this page reads version ${POWER_VERSION}.`];
  }
  if (power.scenario_id !== scenario.id) {
    return [null, "power.js was written with another scenario.js, so it may not match this run."];
  }
  const n = scenario.grid.t_s.length;
  const grid = power.grid;
  const lengths = [grid.generated_w, grid.consumed_w, grid.soc, ...grid.sun_cos, ...grid.panel_w].map(
    (a) => a.length,
  );
  if (lengths.some((length) => length !== n)) {
    return [null, "power.js has a different number of time steps from scenario.js."];
  }
  if (grid.panel_w.length !== power.spacecraft.panels.length) {
    return [null, "power.js gives the power of a different number of panels from its panel list."];
  }
  return [power, ""];
}

/**
 * The eclipses, each from its entry to its exit. The illumination track splits
 * an eclipse into penumbra, umbra and penumbra, so touching shadow pieces join.
 */
function joinEclipses(illumination) {
  return illumination
    .filter((piece) => piece.value !== "sunlit")
    .reduce((joined, piece) => {
      const last = joined[joined.length - 1];
      if (last && last.end_s === piece.start_s) last.end_s = piece.end_s;
      else joined.push({ start_s: piece.start_s, end_s: piece.end_s });
      return joined;
    }, []);
}

// ---------------------------------------------------------------- Tracks and the grid

/** The last item of a list sorted by `start_s` that starts at or before `time`. */
function pieceIndexAt(list, time) {
  let lo = 0;
  let hi = list.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (list[mid].start_s <= time) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

function pieceAt(list, time) {
  return list[pieceIndexAt(list, time)];
}

/** The text a track piece shows. A slew names the attitude it turns into. */
const pieceText = (piece) => (piece.value === "slew" && piece.target ? `${piece.target} (slewing)` : piece.value);

/**
 * The grid step that holds `time`, and how far `time` is along it, from 0 to 1.
 * The times `t` are regular, but for the last step, which may be shorter.
 */
function stepAt(t, time) {
  const n = t.length;
  const at = clamp(time, 0, t[n - 1]);
  let i = clamp(Math.floor(at / (t[1] - t[0])), 0, n - 2);
  while (i > 0 && t[i] > at) i--;
  while (i < n - 2 && t[i + 1] <= at) i++;
  return [i, clamp((at - t[i]) / (t[i + 1] - t[i]), 0, 1)];
}

/** An angle in degrees between two others, the short way round. */
function angleBetween(a, b, f) {
  return a + (((b - a + 540) % 360) - 180) * f;
}

// ---------------------------------------------------------------- Values between grid steps

/**
 * How far to turn the body from grid step `i` to `i + 1` at `time`, which is
 * `f` of the way along the step. An attitude change without a slew is instant.
 * Where one falls inside the step, this keeps the attitude of the side `time`
 * is on, 0 or 1, rather than turning across the step. A slew turns the body
 * smoothly, so across its edges this gives `f`, as anywhere else.
 */
function attitudeFraction(attitudeTrack, t, i, f, time) {
  const here = pieceAt(attitudeTrack, t[i]);
  const next = pieceAt(attitudeTrack, t[i + 1]);
  const instant = next.start_s > t[i] && next.value !== "slew" && here.value !== "slew";
  if (!instant) return f;
  return time < next.start_s ? 0 : 1;
}

/**
 * The angle of an articulation at `time`, in grid step `i`, `f` of the way
 * along it. A mode change parks or frees a part at once. Inside a step that
 * holds one, this keeps the angle of the side `time` is on, as for an instant
 * attitude change.
 */
function jointAngle(joint, modeTrack, t, i, f, time) {
  const angles = joint.angle_deg;
  const here = pieceAt(modeTrack, t[i]);
  const next = pieceAt(modeTrack, t[i + 1]);
  const parks = joint.park_modes.includes(here.value) || joint.park_modes.includes(next.value);
  if (next.start_s > t[i] && parks) return angles[time < next.start_s ? i : i + 1];
  return angleBetween(angles[i], angles[i + 1], f);
}

/**
 * The fraction of the sun's disk seen at `time`, in grid step `i`. It follows
 * the illumination track: exactly 1 when sunlit and 0 in the umbra. In the
 * penumbra it runs straight between the grid values inside the penumbra and its
 * edges, where it is 1 on the sunlit side and 0 on the umbra side. A plain line
 * between grid values would not do: a 10 s step can jump a whole 9 s penumbra,
 * and would then show part of the sun at a time that is sunlit.
 */
function lightFraction(illumination, t, light, time, i) {
  const index = pieceIndexAt(illumination, time);
  const piece = illumination[index];
  if (piece.value === "sunlit") return 1;
  if (piece.value === "umbra") return 0;
  const edge = (neighbour) => (!neighbour ? null : neighbour.value === "sunlit" ? 1 : neighbour.value === "umbra" ? 0 : null);
  const before = edge(illumination[index - 1]);
  const after = edge(illumination[index + 1]);
  let [t0, v0] = [t[i], light[i]];
  let [t1, v1] = [t[i + 1], light[i + 1]];
  if (t0 < piece.start_s && before !== null) [t0, v0] = [piece.start_s, before];
  if (t1 > piece.end_s && after !== null) [t1, v1] = [piece.end_s, after];
  return clamp(t1 > t0 ? v0 + ((v1 - v0) * (time - t0)) / (t1 - t0) : v0, 0, 1);
}

/**
 * The spans where the body turns faster than the slew block allows, from the
 * Attitude data: each step whose rate passes the rate limit, or with an
 * acceleration past its limit at either end. As in the run's warnings, only
 * steps inside one attitude count: the slews, and the steps across an
 * attitude's ends, are left out. Neighbouring steps join into one piece,
 * `{start_s, end_s}`. A limit that is null is never passed.
 */
function excessPieces(t, attitude, attitudeTrack) {
  const over = (value, limit) => limit !== null && value !== null && value !== undefined && value > limit;
  // a step wholly inside one piece of the attitude track, other than a slew
  const inside = (k) => {
    if (k < 0 || k >= t.length - 1) return false;
    const piece = pieceAt(attitudeTrack, t[k]);
    return piece.value !== "slew" && t[k + 1] <= piece.end_s;
  };
  const rate = attitude.rate_deg_s;
  const acceleration = attitude.acceleration_deg_s2;
  const pieces = [];
  for (let k = 0; k < t.length - 1; k++) {
    if (!inside(k)) continue;
    const passed =
      over(rate[k], attitude.max_rate_deg_s) ||
      (inside(k - 1) && over(acceleration[k], attitude.max_acceleration_deg_s2)) ||
      (inside(k + 1) && over(acceleration[k + 1], attitude.max_acceleration_deg_s2));
    if (!passed) continue;
    const last = pieces[pieces.length - 1];
    if (last && last.end_s === t[k]) last.end_s = t[k + 1];
    else pieces.push({ start_s: t[k], end_s: t[k + 1] });
  }
  return pieces;
}

// ---------------------------------------------------------------- Targets

const WGS84_RADIUS_KM = 6378.137;
const WGS84_FLATTENING = 1 / 298.257223563;

/**
 * The pass of a target under way at `time`, or null when it is out of view.
 * Each pass, `{start_s, end_s}`, holds its start and not its end, as the run's
 * intervals do. The end of the run, `runEnd`, counts as inside the pass that
 * reaches it, so that the last time of the grid is not out of view.
 */
function passAt(passes, time, runEnd) {
  if (!passes.length) return null;
  const pass = pieceAt(passes, time);
  const inside = pass.start_s <= time && (time < pass.end_s || (time === runEnd && pass.end_s === runEnd));
  return inside ? pass : null;
}

/**
 * A vector in GCRS turned into Earth-fixed axes. `q` turns Earth-fixed vectors
 * into GCRS, as `q_earth` does, with its scalar last: [x, y, z, w]. So the
 * vector turns by its inverse.
 */
function earthFixed(q, v) {
  const [x, y, z, w] = [-q[0], -q[1], -q[2], q[3]];
  // v + w t + q × t, with t = 2 q × v
  const tx = 2 * (y * v[2] - z * v[1]);
  const ty = 2 * (z * v[0] - x * v[2]);
  const tz = 2 * (x * v[1] - y * v[0]);
  return [v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx)];
}

/**
 * The geodetic latitude and the longitude, in degrees, of an Earth-fixed
 * position in km, on the WGS84 ellipsoid. Bowring's method, refined three
 * times, which is far closer than the map can show.
 */
function geodeticOf(position) {
  const [x, y, z] = position;
  const a = WGS84_RADIUS_KM;
  const f = WGS84_FLATTENING;
  const b = a * (1 - f);
  const e2 = f * (2 - f);
  const across = Math.hypot(x, y);
  let reduced = Math.atan2(z, (1 - f) * across);
  let latitude = 0;
  for (let k = 0; k < 3; k++) {
    latitude = Math.atan2(z + (e2 / (1 - e2)) * b * Math.sin(reduced) ** 3, across - e2 * a * Math.cos(reduced) ** 3);
    reduced = Math.atan2((1 - f) * Math.sin(latitude), Math.cos(latitude));
  }
  return [(latitude * 180) / Math.PI, (Math.atan2(y, x) * 180) / Math.PI];
}

/** A ground point's Earth-fixed position in km, from its geodetic latitude and longitude in degrees and its height in km. */
function groundPoint(latitude, longitude, altitude) {
  const lat = (latitude * Math.PI) / 180;
  const lon = (longitude * Math.PI) / 180;
  const e2 = WGS84_FLATTENING * (2 - WGS84_FLATTENING);
  const n = WGS84_RADIUS_KM / Math.sqrt(1 - e2 * Math.sin(lat) ** 2);
  return [
    (n + altitude) * Math.cos(lat) * Math.cos(lon),
    (n + altitude) * Math.cos(lat) * Math.sin(lon),
    (n * (1 - e2) + altitude) * Math.sin(lat),
  ];
}

/**
 * The targets that the body points at, at `time`: those that the attitude in
 * effect names, unless the body is slewing, and the target of each
 * articulation that its mode does not park. `pointing` is scenario.js's.
 */
function pointedTargets(pointing, attitudeTrack, modeTrack, articulations, time) {
  const names = [...(pointing.attitudes[pieceAt(attitudeTrack, time).value] || [])];
  const mode = pieceAt(modeTrack, time).value;
  for (const [name, target] of Object.entries(pointing.articulations)) {
    const joint = articulations.find((item) => item.name === name);
    if (joint && !joint.park_modes.includes(mode)) names.push(target);
  }
  return [...new Set(names)];
}

/**
 * The targets the body view draws an arrow to: those in view, the nearest
 * first, at most `most` of them, and then each target in `always`, in view or
 * not. `ranges` gives each target's range by its name.
 */
function arrowTargets(inView, ranges, always, most) {
  const nearest = [...inView].sort((a, b) => ranges[a] - ranges[b]).slice(0, most);
  return [...new Set([...nearest, ...always])];
}

/**
 * When the body or a part points at each target, by the target's name: its
 * spans of time in time order, with the spans that touch or overlap joined.
 * The rules are those of `pointedTargets`, over the whole run.
 */
function pointedSpans(pointing, attitudeTrack, modeTrack, articulations) {
  const spans = {};
  const add = (name, piece) => (spans[name] ||= []).push({ start_s: piece.start_s, end_s: piece.end_s });
  for (const piece of attitudeTrack) {
    for (const name of pointing.attitudes[piece.value] || []) add(name, piece);
  }
  for (const [name, target] of Object.entries(pointing.articulations)) {
    const joint = articulations.find((item) => item.name === name);
    if (!joint) continue;
    for (const piece of modeTrack) if (!joint.park_modes.includes(piece.value)) add(target, piece);
  }
  for (const [name, list] of Object.entries(spans)) {
    spans[name] = list
      .sort((a, b) => a.start_s - b.start_s)
      .reduce((joined, span) => {
        const last = joined[joined.length - 1];
        if (last && span.start_s <= last.end_s) last.end_s = Math.max(last.end_s, span.end_s);
        else joined.push(span);
        return joined;
      }, []);
  }
  return spans;
}

/** The seconds that `spans`, apart from each other, share with the time from `start` to `end`. */
function sharedSeconds(spans, start, end) {
  return spans.reduce((sum, span) => sum + Math.max(0, Math.min(end, span.end_s) - Math.max(start, span.start_s)), 0);
}

// ---------------------------------------------------------------- The Activity Designer

/**
 * The occurrence under way at `time`, or null in the time that no activity
 * plans, after the last one. Each occurrence holds its start and not its end,
 * and the end of the run, `runEnd`, counts as inside the one that reaches it.
 * An occurrence with a negative duration takes no time, so the next one, which
 * starts with it, is the one under way.
 */
function occurrenceAt(occurrences, time, runEnd) {
  if (!occurrences.length) return null;
  const occurrence = pieceAt(occurrences, time);
  const end = Math.max(occurrence.start_s, occurrence.end_s);
  const inside = occurrence.start_s <= time && (time < end || (time === runEnd && end === runEnd));
  return inside ? occurrence : null;
}

/** The occurrences of the activity with this number in the list, each that takes time. */
function occurrencesOf(occurrences, number) {
  return occurrences.filter((occurrence) => occurrence.number === number && occurrence.end_s > occurrence.start_s);
}

/**
 * A mark at each whole orbit from the start, up to the end of the run: its
 * time in seconds, and its label, such as "1 orbit" and "2 orbits". Both the
 * period and the end are rounded to 1 ms, so a mark may pass the end by that
 * much for each orbit.
 */
function orbitMarks(period, runEnd) {
  const marks = [];
  if (!(period > 0)) return marks;
  for (let k = 1; k * period <= runEnd + 0.001 * k; k++) {
    marks.push({ time_s: Math.min(k * period, runEnd), label: `${k} orbit${k === 1 ? "" : "s"}` });
  }
  return marks;
}

/**
 * The view that the Activity Designer passes on from one run to the next, in
 * the address's hash, such as `#t=1200&zoom=600,4200`: the time cursor, and the
 * start and end of the timeline's zoom, in seconds. Each is null when the hash
 * lacks it, or holds something else.
 */
function viewFromHash(hash) {
  const fields = new URLSearchParams(String(hash || "").replace(/^#/, ""));
  const number = (text) => (text !== null && text.trim() !== "" && Number.isFinite(Number(text)) ? Number(text) : null);
  const zoom = (fields.get("zoom") || "").split(",").map(number);
  const ordered = zoom.length === 2 && zoom[0] !== null && zoom[1] !== null && zoom[0] < zoom[1];
  return { t: number(fields.get("t")), zoom: ordered ? zoom : null };
}
