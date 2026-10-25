// quicksat scenario editor: writing the folder's files from the project.

function scenarioYaml() {
  const lines = [...HEADER, ""];
  if (S.comments.trim()) { commentsLines(lines, 0, S.comments); lines.push(""); }

  const o = S.orbit;
  helpLines(lines, 0, "orbit");
  lines.push("orbit:");
  commentsLines(lines, 2, o.comments);
  if (o.source === "sso") {
    helpLines(lines, 2, "sso");
    const sso = [["altitude", yq(o.sso.altitude)], [o.sso.node, JSON.stringify(o.sso.time)]];
    if (!o.sso.comments.trim()) lines.push(`  sso: ${flowMap(sso)}`);
    else {
      lines.push("  sso:");
      for (const [k, v] of sso) lines.push(`    ${k}: ${v}`);
      commentsLines(lines, 4, o.sso.comments);
    }
  } else {
    const key = ORBIT_KEYS[o.source];
    lines.push(`  ${key}: ${ys(o[key] || "")}`);
  }
  lines.push("");
  helpLines(lines, 0, "start");
  // the date field drops the seconds when they are zero
  lines.push(`start: ${/T\d{2}:\d{2}$/.test(S.start) ? S.start + ":00" : S.start}`);
  helpLines(lines, 0, "duration");
  lines.push(`duration: ${yq(S.duration)}`);
  if (!blank(S.step)) {
    helpLines(lines, 0, "step");
    lines.push(`step: ${yq(S.step)}`);
  }
  lines.push("");

  const m = S.model;
  const arts = m.articulations;
  if (m.file) {
    helpLines(lines, 0, "model");
    if (!arts.items.length && !m.comments.trim() && !arts.comments.trim()) {
      lines.push(`3d_model: ${ys(m.file)}`);
    } else {
      lines.push("3d_model:");
      lines.push(`  file: ${ys(m.file)}`);
      commentsLines(lines, 2, m.comments);
      if (arts.items.length || arts.comments.trim()) {
        helpLines(lines, 2, "articulations");
        lines.push("  articulations:");
        commentsLines(lines, 4, arts.comments);
        for (const a of arts.items) {
          const park = a.park.length ? flowMap(a.park.map((p) => [ys(p.mode), yq(p.angle)])) : "";
          const range = a.range ? `[${yq(a.range.min)}, ${yq(a.range.max)}]` : "";
          itemLines(lines, 4, a.name, [["part", ys(a.part)], ["axis", a.axis], ["point", `[${a.point.map(ys).join(", ")}]`], ["park", park], ["range", range]], a.comments);
        }
      }
    }
    lines.push("");
  }

  if (S.gnd_targets.items.length || S.gnd_targets.comments.trim()) {
    helpLines(lines, 0, "gnd_targets");
    lines.push("gnd_targets:");
    commentsLines(lines, 2, S.gnd_targets.comments);
    for (const t of S.gnd_targets.items) {
      itemLines(lines, 2, t.name, [["latitude", yq(t.latitude)], ["longitude", yq(t.longitude)], ["altitude", yq(t.altitude)], ["min_elevation", yq(t.min_elevation)]], t.comments);
    }
    lines.push("");
  }

  if (S.sat_targets.items.length || S.sat_targets.comments.trim()) {
    helpLines(lines, 0, "sat_targets");
    lines.push("sat_targets:");
    commentsLines(lines, 2, S.sat_targets.comments);
    for (const t of S.sat_targets.items) {
      const pairs = [[ORBIT_KEYS[t.source], ys(t.file)], ["object", t.object ? ys(t.object) : ""], ["min_clearance", yq(t.min_clearance)]];
      itemLines(lines, 2, t.name, pairs, t.comments);
    }
    lines.push("");
  }

  helpLines(lines, 0, "attitudes");
  lines.push("attitudes:");
  commentsLines(lines, 2, S.attitudes.comments);
  for (const a of S.attitudes.items) {
    const pair = (p) => `[${p.map(ys).join(", ")}]`;
    const turns = a.offset.split(",").map((t) => t.trim()).filter(Boolean);
    itemLines(lines, 2, a.name, [["point", pair(a.point)], ["constrain", pair(a.constrain)], ["fallback", a.fallback ? ys(a.fallback) : ""], ["offset", turns.length ? `[${turns.map(ys).join(", ")}]` : ""]], a.comments);
  }
  lines.push("");

  const s = S.slew;
  if (s.enabled) {
    helpLines(lines, 0, "slew");
    lines.push("slew:");
    for (const key of ["max_rate", "max_acceleration", "settling_time"]) if (!blank(s[key])) lines.push(`  ${key}: ${yq(s[key])}`);
    commentsLines(lines, 2, s.comments);
    lines.push("");
  }

  helpLines(lines, 0, "activities");
  lines.push("activities:");
  for (const a of S.activities) {
    // the modes as one mapping: {payload_mode: imaging, platform_mode: imaging}, and the
    // payload's mode in the slew into the activity where it is not the default
    const pairs = GROUPS.map((group) => [MODE_KEYS[group], a.mode[group] === "" ? "" : ys(a.mode[group])]);
    if (a.mode.in_slew !== PREV_ACTIVITY) pairs.push([IN_SLEW, a.mode.in_slew]);
    const modes = flowMap(pairs);
    const fields = [...[a.title, triggerText(a.end), a.attitude].filter((f) => f !== "").map(ys), modes, ...(a.constraint ? [ys(a.constraint)] : [])];
    if (!a.comments.trim()) { lines.push(`  - [${fields.join(", ")}]`); continue; }
    lines.push(`  - title: ${ys(a.title)}`);
    lines.push(`    end: ${ys(triggerText(a.end))}`);
    lines.push(`    attitude: ${ys(a.attitude)}`);
    lines.push(`    mode: ${modes}`);
    if (a.constraint) lines.push(`    constraint: ${a.constraint}`);
    commentsLines(lines, 4, a.comments);
  }
  return lines.join("\n") + "\n";
}

/** A typed-in normal as the file writes it: `+x`, or `[0, 1, -1]`. */
function normalText(text) {
  const normal = readNormalVector(text);
  if (normal === null) return ys(text);
  return typeof normal === "string" ? normal : `[${normal.join(", ")}]`;
}

function powerYaml() {
  const lines = [...HEADER, ""];
  if (P.comments.trim()) { commentsLines(lines, 0, P.comments); lines.push(""); }
  helpLines(lines, 0, "cell_efficiency");
  lines.push(`cell_efficiency: ${yq(P.cell_efficiency)}`);
  helpLines(lines, 0, "loss_factor");
  lines.push(`loss_factor: ${yn(P.loss_factor)}`);
  lines.push("");
  helpLines(lines, 0, "panels");
  lines.push("panels:");
  commentsLines(lines, 2, P.panels.comments);
  for (const p of P.panels.items) {
    const pairs = p.source === "part"
      ? [["part", ys(p.part)], ["fill_ratio", yq(p.fill_ratio)]]
      : [["normal", normalText(p.normal)], ["area", yq(p.area)], ["fill_ratio", yq(p.fill_ratio)]];
    itemLines(lines, 2, p.name, pairs, p.comments);
  }
  lines.push("");
  const s = P.self_shadowing;
  if (s.present || s.enabled) {
    helpLines(lines, 0, "self_shadowing");
    const pairs = [["enabled", String(s.enabled)], ["points", s.enabled ? yn(s.points) : ""]];
    if (!s.comments.trim()) lines.push(`self_shadowing: ${flowMap(pairs)}`);
    else {
      lines.push("self_shadowing:");
      for (const [k, v] of pairs) if (v !== "") lines.push(`  ${k}: ${v}`);
      commentsLines(lines, 2, s.comments);
    }
    lines.push("");
  }
  const b = P.battery;
  if (b.present) {
    helpLines(lines, 0, "battery");
    lines.push("battery:");
    lines.push(`  capacity: ${yq(b.capacity)}`);
    lines.push(`  capacity_factor: ${yn(b.capacity_factor)}`);
    lines.push(`  max_depth_of_discharge: ${yq(b.max_depth_of_discharge)}`);
    if (!blank(b.initial_charge)) lines.push(`  initial_charge: ${yq(b.initial_charge)}`);
    commentsLines(lines, 2, b.comments);
    lines.push("");
  }
  const c = P.conditioning;
  if (c.present) {
    helpLines(lines, 0, "conditioning");
    lines.push("conditioning:");
    for (const key of ["array_regulator", "battery_charge", "battery_discharge", "distribution"]) lines.push(`  ${key}: ${yn(c[key])}`);
    commentsLines(lines, 2, c.comments);
    lines.push("");
  }
  if (!blank(P.system_margin)) {
    helpLines(lines, 0, "system_margin");
    lines.push(`system_margin: ${yq(P.system_margin)}`);
  }
  while (lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n") + "\n";
}

function consumptionCsv(group) {
  const modes = consumptionModes(group);
  const thermalColumn = showsThermalColumn(group);
  const lines = [["equipment_id", "equipment_name", "subsystem", "units_on", "eqpt_margin", ...modes, "comments", ...(thermalColumn ? [THERMAL_COLUMN] : [])].map(csvCell).join(",")];
  const watts = (v) => (v === "" || v == null ? "" : `${v} W`);
  for (const r of project.consumption[group]) {
    const power = modes.map((m) => watts(m === SLEW ? r.slew : r.power[m]));
    lines.push([r.id, r.name, r.subsystem, r.units, r.margin, ...power, r.comments, ...(thermalColumn ? [r.thermal || ""] : [])].map(csvCell).join(","));
  }
  return lines.join("\n") + "\n";
}

/** A power for the file, such as `-3 W`, or "" when the field is empty. */
const yw = (value) => (value === "" || value == null ? "" : `${value} W`);

function thermalYaml() {
  const lines = [...HEADER, ""];
  if (T.comments.trim()) { commentsLines(lines, 0, T.comments); lines.push(""); }
  helpLines(lines, 0, "surfaces");
  lines.push("surfaces:");
  commentsLines(lines, 2, T.surfaces.comments);
  for (const s of T.surfaces.items) {
    const where = s.source === "part" ? [["part", ys(s.part)]] : [["normal", normalText(s.normal)], ["area", yq(s.area)]];
    const pairs = [...where, ["absorptance", yn(s.absorptance)], ["emissivity", yn(s.emissivity)], ["temperature", yq(s.temperature)], ["fixed_temperature", s.fixed ? "true" : ""]];
    itemLines(lines, 2, s.name, pairs, s.comments);
  }
  lines.push("");
  const flows = T.heat_flows;
  if (flows.items.length || flows.comments.trim()) {
    helpLines(lines, 0, "heat_flows");
    lines.push("heat_flows:");
    commentsLines(lines, 2, flows.comments);
    // a flow by mode takes a power for each of the payload's modes, as the Modes step names them
    for (const f of flows.items) {
      lines.push(`  ${ys(f.name)}: ${f.byMode ? flowMap(S.modes.payload.map((mode) => [ys(mode), yw(f.powers[mode])])) : yw(f.power)}`);
    }
    lines.push("");
  }
  const e = T.earth;
  if (e.present || yn(e.albedo) !== "" || !blank(e.infrared) || e.comments.trim()) {
    helpLines(lines, 0, "earth");
    const pairs = [["albedo", yn(e.albedo)], ["infrared", yq(e.infrared)]];
    if (!e.comments.trim()) lines.push(`earth: ${flowMap(pairs)}`);
    else {
      lines.push("earth:");
      for (const [k, v] of pairs) if (v !== "") lines.push(`  ${k}: ${v}`);
      commentsLines(lines, 2, e.comments);
    }
  }
  while (lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n") + "\n";
}

/**
 * A path to save a file under, inside the folder. A path that leaves the folder
 * cannot go in the zip, so the file goes in the folder itself, with a note.
 */
function savePath(name) {
  const path = String(name).replace(/\\/g, "/");
  if (!path.startsWith("/") && !/^[A-Za-z]:/.test(path) && !path.split("/").includes("..")) return { path };
  const base = path.split("/").pop();
  return { path: base, note: `the scenario names ${name}, so move it there` };
}

/** Every file the folder saves: the scenario, its model, orbit and satellite target files, and the power files. */
function projectFiles() {
  const files = [{ kind: "scenario", path: project.names.scenario, text: scenarioYaml() }];
  if (S.model.file && model.bytes) {
    const { path, note } = savePath(S.model.file);
    files.push({ kind: "model", path, bytes: model.bytes, note: note || "the 3D model" });
  }
  const key = ORBIT_KEYS[S.orbit.source];
  if (key && orbitFile && orbitFile.name === S.orbit[key]) {
    const { path, note } = savePath(S.orbit[key]);
    files.push({ kind: "orbit", path, text: orbitFile.text, note: note || "the orbit file" });
  }
  for (const name of satTargetFiles().filter((name) => targetFiles.has(name))) {
    const { path, note } = savePath(name);
    files.push({ kind: targetKind(name), path, text: targetFiles.get(name), note: note || "a satellite target's file" });
  }
  if (project.hasPower) files.push({ kind: "power", path: project.names.power, text: powerYaml() });
  for (const group of GROUPS) {
    const kind = consumptionKind(group);
    if (project.hasConsumption[group]) files.push({ kind, path: project.names[kind], text: consumptionCsv(group) });
  }
  if (project.hasThermal) files.push({ kind: "payload_thermal", path: project.names.payload_thermal, text: thermalYaml() });
  return files;
}
