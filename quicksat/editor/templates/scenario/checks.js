// quicksat scenario editor: the page's own checks.

/** What the page's checks leave to the run, for the checks pop-over. */
const CHECKS_NOTE = "Whether the triggers come, the constraints hold and the battery lasts needs the Python run.";

/** The page's own checks: names, units and ranges. Proper checks need the Python run. */
function runChecks() {
  const problems = [];
  const add = (section, text, level = "error") => problems.push({ section, text, level });
  const pct = (section, label, quantity, low = 0, high = 100) => {
    if (blank(quantity)) add(section, `${label} is missing`);
    else if (quantity.u !== "%") add(section, `${label} must be in %, got ${qText(quantity)}`);
    else if (quantity.v < low || quantity.v > high) add(section, `${label} must be from ${low} to ${high} %`);
  };
  const fraction = (section, label, value) => {
    if (value === "" || value == null) add(section, `${label} is missing`);
    else if (!(value > 0 && value <= 1)) add(section, `${label} must be above 0 and at most 1`);
  };
  const positive = (section, label, quantity) => {
    if (blank(quantity)) add(section, `${label} is missing`);
    else if (!(quantity.v > 0)) add(section, `${label} must be above zero`);
  };
  const names = (section, kind, list) => {
    const seen = new Set();
    for (const item of list) {
      if (!item.name.trim()) add(section, `a ${kind} has no name`);
      if (item.name === RESERVED) add(section, `no ${kind} can be called "${RESERVED}": the name is kept for comments`);
      if (seen.has(item.name)) add(section, `two ${kind}s are called "${item.name}"`);
      seen.add(item.name);
    }
  };
  const dirs = new Set(directions());

  // Orbit and time
  const o = S.orbit;
  if (o.source === "sso") {
    positive("orbit", "the altitude", o.sso.altitude);
    if (!/^\d{1,2}:\d{2}(:\d{2})?$/.test(o.sso.time)) add("orbit", `the ${o.sso.node.toUpperCase()} must be a time of day, such as 13:30`);
  } else {
    const key = { tle: "tle_file", omm: "omm_file", trajectory: "trajectory_file" }[o.source];
    if (!o[key]) add("orbit", "no file is chosen");
    else if (!(orbitFile && orbitFile.name === o[key])) add("orbit", `this page does not hold ${o[key]}, so saving leaves it out: keep it beside the scenario file`, "note");
  }
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(S.start)) add("time", "the start must be a date and a time");
  positive("time", "the duration", S.duration);
  if (!blank(S.step) && !(S.step.v > 0)) add("time", "the time step must be above zero");
  if (S.duration.u !== "orbits" && S.duration.v > 0) {
    const hours = S.duration.v * ({ s: 1 / 3600, min: 1 / 60, h: 1, d: 24 }[S.duration.u] || 1);
    if (hours > 48) add("time", `a run of ${hours.toFixed(0)} h is long: quicksat is meant for an orbit to a day or two`, "note");
  }

  // Model and articulations
  const partNames = new Set(model.parts.map((p) => p.name));
  const partCount = (name) => (model.parts.find((p) => p.name === name) || {}).count || 0;
  const checkPart = (section, what, part) => {
    if (!part) add(section, `${what} names no part`);
    else if (!model.bytes) return;
    else if (!partNames.has(part)) add(section, `${what}: the model has no part "${part}"`);
    else if (partCount(part) > 1) add(section, `${what}: "${part}" names ${partCount(part)} parts`);
  };
  if (S.model.articulations.items.length && !S.model.file) add("articulations", "articulations need a 3D model");
  names("articulations", "articulation", S.model.articulations.items);
  for (const a of S.model.articulations.items) {
    checkPart("articulations", `articulation ${a.name}`, a.part);
    if (a.axis.slice(1) === a.point[0].slice(1)) add("articulations", `articulation ${a.name} turns about the axis it points, so the turn cannot move it`);
    if (!dirs.has(a.point[1])) add("articulations", `articulation ${a.name}: "${a.point[1]}" is not a direction or a target`);
    for (const p of a.park) if (!parkModes().includes(p.mode)) add("articulations", `articulation ${a.name} parks in a mode the platform never has: "${p.mode || "none"}"`);
    if (a.range && !(a.range.min.v >= -180 && a.range.min.v < a.range.max.v && a.range.max.v <= 180)) add("articulations", `articulation ${a.name}: the range must rise within -180 to 180 deg`);
  }

  // Targets and attitudes
  names("gnd_targets", "target", S.gnd_targets.items);
  for (const t of S.gnd_targets.items) {
    if (blank(t.latitude) || Math.abs(t.latitude.v) > 90) add("gnd_targets", `target ${t.name}: the latitude must be from -90 to 90 deg`);
    if (blank(t.longitude)) add("gnd_targets", `target ${t.name}: the longitude is missing`);
    if (!blank(t.min_elevation) && !(t.min_elevation.v >= 0 && t.min_elevation.v < 90)) add("gnd_targets", `target ${t.name}: the minimum elevation must be from 0 up to 90 deg`);
    if (BUILT_IN_DIRECTIONS.includes(t.name)) add("gnd_targets", `target ${t.name} has the name of a built-in direction`);
  }
  names("sat_targets", "target", S.sat_targets.items);
  const grounds = new Set(S.gnd_targets.items.map((t) => t.name));
  for (const t of S.sat_targets.items) {
    if (grounds.has(t.name)) add("sat_targets", `target ${t.name} is a ground target too: a target's name must be its own`);
    if (BUILT_IN_DIRECTIONS.includes(t.name)) add("sat_targets", `target ${t.name} has the name of a built-in direction`);
    if (!blank(t.min_clearance) && !(t.min_clearance.v >= 0)) add("sat_targets", `target ${t.name}: the minimum clearance must be 0 or more`);
    if (t.source === "trajectory" && t.object) add("sat_targets", `target ${t.name}: a trajectory file holds one satellite, so it takes no satellite of its own`);
    if (!t.file) { add("sat_targets", `target ${t.name}: no file is chosen`); continue; }
    if (!targetFiles.has(t.file)) { add("sat_targets", `target ${t.name}: this page does not hold ${t.file}, so saving leaves it out: keep it beside the scenario file`, "note"); continue; }
    const kind = orbitFileKind(t.file, targetFiles.get(t.file));
    if (kind !== t.source) { add("sat_targets", `target ${t.name}: ${t.file} reads as a ${kind === "trajectory" ? kind : kind.toUpperCase()} file`); continue; }
    if (kind === "trajectory") continue;
    const sets = heldSets(t.file);
    if (!sets) { add("sat_targets", `target ${t.name}: ${t.file} does not read as a ${kind.toUpperCase()} file`); continue; }
    const picked = pickedElementSet(sets, t.object, t.name);
    if (!picked.set) add("sat_targets", `target ${t.name}: ${picked.problem}`);
    else if (epochNote(picked.set.epoch)[1]) add("sat_targets", `target ${t.name}: its epoch is more than 7 days from the run, where SGP4 loses accuracy`, "note");
  }
  names("attitudes", "attitude", S.attitudes.items);
  if (!S.attitudes.items.length) add("attitudes", "there must be at least one attitude");
  for (const a of S.attitudes.items) {
    if (a.name === SLEW) add("attitudes", 'no attitude can be called "slew": the run uses it while the body turns');
    if (a.name === UNPLANNED) add("attitudes", 'no attitude can be called "unplanned": the run uses it after the last activity');
    if (a.point[0].slice(1) === a.constrain[0].slice(1)) add("attitudes", `attitude ${a.name}: the two body axes lie on one line`);
    if (a.point[1] === a.constrain[1]) add("attitudes", `attitude ${a.name}: both axes aim at ${a.point[1]}`);
    for (const d of [a.point[1], a.constrain[1], a.fallback].filter(Boolean)) if (!dirs.has(d)) add("attitudes", `attitude ${a.name}: "${d}" is not a direction or a target`);
    if (a.fallback && [a.point[1], a.constrain[1]].includes(a.fallback)) add("attitudes", `attitude ${a.name}: the fallback must be a third direction`);
    for (const turn of a.offset.split(",").map((t) => t.trim()).filter(Boolean)) {
      if (!/^[xyz]\s+[-+]?(\d+\.?\d*|\.\d+)\s*(deg|rad)$/.test(turn)) add("attitudes", `attitude ${a.name}: an offset turn reads like "x 30 deg", got "${turn}"`);
    }
  }

  // Slews and modes
  const s = S.slew;
  if (s.enabled) {
    if (blank(s.max_rate) && blank(s.max_acceleration)) add("slew", "a slew needs the fastest rate, the acceleration, or both");
    for (const [key, label] of [["max_rate", "the fastest rate"], ["max_acceleration", "the acceleration"]]) if (!blank(s[key]) && !(s[key].v > 0)) add("slew", `${label} must be above zero`);
  }
  for (const group of GROUPS) {
    const modes = S.modes[group];
    if (modes.includes(SLEW)) add("modes", `no ${group} mode can be called "slew": the run gives the platform that mode while the body turns`);
    if (modes.includes(UNPLANNED)) add("modes", `no ${group} mode can be called "unplanned"`);
    if (new Set(modes).size !== modes.length) add("modes", `two ${group} modes have the same name`);
  }

  // Activities
  if (!S.activities.length) add("activities", "there must be at least one activity");
  S.activities.forEach((a, i) => {
    const n = i + 1;
    if (!a.title.trim()) add("activities", `activity ${n} has no title`);
    if (!attitudeNames().includes(a.attitude)) add("activities", `activity ${n}: no attitude "${a.attitude || "none"}"`);
    for (const group of GROUPS) {
      const mode = a.mode[group];
      if (!mode.trim()) add("activities", `activity ${n} has no ${group} mode`);
      else if (mode === SLEW) add("activities", `activity ${n}: no mode can be called "slew"`);
      else if (mode === UNPLANNED) add("activities", `activity ${n}: no mode can be called "unplanned"`);
    }
    if (a.end.kind === "duration" && !(a.end.value.v > 0)) add("activities", `activity ${n}: the duration must be above zero`);
    if (a.end.kind === "text") add("activities", `activity ${n}: the editor cannot read the trigger "${a.end.text}"; quicksat may`, "note");
    if (["rise", "set"].includes(a.end.kind) && !targetNames().includes(a.end.target)) add("activities", `activity ${n}: no target "${a.end.target || "none"}"`);
    if (a.end.kind === "latitude" && !(Math.abs(a.end.latitude.v) <= 90)) add("activities", `activity ${n}: a latitude must be from -90 to 90 deg`);
  });

  // Power
  if (project.hasPower) {
    names("panels", "panel", P.panels.items);
    if (!P.panels.items.length) add("panels", "there must be at least one panel");
    for (const p of P.panels.items) {
      pct("panels", `panel ${p.name}: the fill ratio`, p.fill_ratio, 0.000001, 100);
      if (p.source === "part") {
        checkPart("panels", `panel ${p.name}`, p.part);
        if (model.bytes && partNames.has(p.part) && partCount(p.part) === 1) {
          const geometry = view3d.partGeometry(p.part);
          if (!geometry) add("panels", `panel ${p.name}: "${p.part}" has no surface of its own`);
          else if (!geometry.flat) add("panels", `panel ${p.name}: "${p.part}" is not flat (its faces differ by up to ${geometry.maxAngle.toFixed(0)} deg)`);
        }
      } else {
        if (!readNormalVector(p.normal)) add("panels", `panel ${p.name}: the normal is a body axis, such as +x, or three numbers, such as 0, 1, -1`);
        positive("panels", `panel ${p.name}: the area`, p.area);
        add("panels", `panel ${p.name} is typed in, so it is never shaded and shades nothing`, "note");
      }
    }
    pct("cells", "the cell efficiency", P.cell_efficiency, 0.000001, 100);
    fraction("cells", "the loss factor", P.loss_factor);
    if (P.self_shadowing.enabled && !P.panels.items.some((p) => p.source === "part")) add("cells", "self-shadowing is on, but no panel comes from the model", "note");
    const b = P.battery;
    if (b.present) {
      positive("battery", "the capacity", b.capacity);
      fraction("battery", "the capacity factor", b.capacity_factor);
      pct("battery", "the deepest discharge", b.max_depth_of_discharge, 0.000001, 100);
      if (!blank(b.initial_charge)) pct("battery", "the starting charge", b.initial_charge, 0.000001, 100);
    }
    if (P.conditioning.present) {
      for (const key of ["array_regulator", "battery_charge", "battery_discharge", "distribution"]) fraction("conditioning", key.replace("_", " "), P.conditioning[key]);
    }
    if (!blank(P.system_margin)) pct("conditioning", "the system margin", P.system_margin);
  }
  // the power budget needs both consumption files, so one alone is flagged
  if (project.hasPower && GROUPS.some((group) => project.hasConsumption[group])) {
    for (const group of GROUPS) {
      const kind = consumptionKind(group);
      if (!project.hasConsumption[group]) add(kind, `the power budget needs ${project.names[kind]} too`);
    }
  }
  for (const group of GROUPS.filter((g) => project.hasConsumption[g])) {
    const section = consumptionKind(group);
    const rows = project.consumption[group];
    if (!rows.length) add(section, "the table needs at least one equipment");
    const ids = rows.map((r) => r.id);
    for (const id of new Set(ids.filter((id, i) => id && ids.indexOf(id) !== i))) add(section, `two rows have the id "${id}"`);
    rows.forEach((r, i) => {
      const what = r.id || `row ${i + 1}`;
      if (!r.id) add(section, `row ${i + 1} has no id`);
      else if (/\s/.test(r.id)) add(section, `${what}: an id has no spaces`);
      if (/\s/.test(r.subsystem)) add(section, `${what}: a subsystem has no spaces`);
      const missing = consumptionModes(group).filter((m) => {
        const value = m === SLEW ? r.slew : r.power[m];
        return value === "" || value == null;
      });
      if (missing.length) add(section, `${what}: no power for ${missing.join(", ")}`);
    });
  }

  state.problems = problems;
  showProblems();
}

/** A typed-in normal as three numbers: from an axis, such as +x, or from 0, 1, -1. */
function readNormalVector(text) {
  const value = String(text).trim();
  if (AXES.includes(value)) return value;
  const numbers = value.replace(/^\[|\]$/g, "").split(",").map((v) => v.trim());
  if (numbers.length !== 3 || numbers.some((v) => v === "" || isNaN(Number(v)))) return null;
  if (numbers.every((v) => Number(v) === 0)) return null;
  return numbers.map(Number);
}
