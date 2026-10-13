// quicksat editor: writing the folder's files from the project.

const HEADER = [
  "# Written by the quicksat editor. Lines that start with # are help text: the",
  "# editor writes them, and rewrites them each time it saves this file. Put the",
  "# comments you want to keep in a comments field. Every block has one, and the",
  "# editor keeps them as they are.",
];

const YAML_HELP = {
  orbit: "The orbit, given one of four ways: sso, tle_file, omm_file or trajectory_file. A relative path is taken from the folder of this file.",
  sso: "For a sun-synchronous orbit, quicksat builds the TLE, with its epoch at the start time. The altitude is averaged over one orbit. The LTAN is in quotes, because YAML reads an unquoted 13:30 as the number 810.",
  start: "UTC.",
  duration: "A time, or a number of orbits. One orbit is the nodal period: from one ascending node to the next. It is counted from the start time.",
  step: "The orbit and the eclipses are worked out on this grid. Events are refined to 1 ms between the steps.",
  model: "The spacecraft's 3D model: a GLB file in body axes and metres, with its origin at the point the body turns about.",
  articulations: "Parts of the model that turn about one axis until the axis in point is as close to its direction as the turn allows. park holds the part still in a mode.",
  targets: "Ground points that an attitude can point at. Each gives the triggers name rise and name set. The altitude is above the WGS84 ellipsoid.",
  attitudes: "Each attitude points one body axis at a direction, and turns a second as close as it can get to another. The directions are nadir, sun, orbit normal, velocity, ground velocity, and the targets.",
  slew: "How the body turns between attitudes: rest to rest about one axis, then it settles. Leave the block out for instant changes.",
  activities: "One repeat of the list. Each activity starts where the one before ends, and ends at its trigger: [title, trigger, attitude, mode, expected illumination]. An activity with comments is written as a map, with the same fields named.",
  cell_efficiency: "The cells' efficiency at their rated temperature.",
  loss_factor: "Every loss up to the array's output, as the share of the power left, for the year being sized.",
  panels: "Each panel names a flat part of the 3D model, or gives a normal and an area. fill_ratio is the share of the part that the cells cover.",
  self_shadowing: "Whether the rest of the model shades the panels. points is about how many sample points each panel gets.",
  battery: "capacity is what it holds when new and full. capacity_factor is the share left after fade. max_depth_of_discharge is the deepest it may go in each orbit.",
  conditioning: "The efficiency of each path the energy takes. Energy through the battery pays both of its paths.",
  system_margin: "The margin on all the loads together, on top of each equipment's margin.",
};

const ORBIT_KEYS = { tle: "tle_file", omm: "omm_file", trajectory: "trajectory_file" };

function scenarioYaml() {
  const lines = [...HEADER, ""];
  if (S.comments.trim()) { commentsLines(lines, 0, S.comments); lines.push(""); }

  const o = S.orbit;
  helpLines(lines, 0, "orbit");
  lines.push("orbit:");
  commentsLines(lines, 2, o.comments);
  if (o.source === "sso") {
    helpLines(lines, 2, "sso");
    const sso = [["altitude", yq(o.sso.altitude)], ["ltan", JSON.stringify(o.sso.ltan)]];
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

  if (S.targets.items.length || S.targets.comments.trim()) {
    helpLines(lines, 0, "targets");
    lines.push("targets:");
    commentsLines(lines, 2, S.targets.comments);
    for (const t of S.targets.items) {
      itemLines(lines, 2, t.name, [["latitude", yq(t.latitude)], ["longitude", yq(t.longitude)], ["altitude", yq(t.altitude)], ["min_elevation", yq(t.min_elevation)]], t.comments);
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
    const fields = [a.title, triggerText(a.end), a.attitude, a.mode, a.constraint].filter((f) => f !== "").map(ys);
    if (!a.comments.trim()) { lines.push(`  - [${fields.join(", ")}]`); continue; }
    lines.push(`  - title: ${ys(a.title)}`);
    lines.push(`    end: ${ys(triggerText(a.end))}`);
    lines.push(`    attitude: ${ys(a.attitude)}`);
    lines.push(`    mode: ${ys(a.mode)}`);
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

function consumptionCsv() {
  const modes = consumptionModes();
  const lines = [["equipment_id", "equipment_name", "subsystem", "units_on", "eqpt_margin", ...modes, "comments"].map(csvCell).join(",")];
  const watts = (v) => (v === "" || v == null ? "" : `${v} W`);
  for (const r of project.consumption) {
    const power = modes.map((m) => watts(m === SLEW ? r.slew : r.power[m]));
    lines.push([r.id, r.name, r.subsystem, r.units, r.margin, ...power, r.comments].map(csvCell).join(","));
  }
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

/** Every file the folder saves: the scenario, its model and orbit file, and the power files. */
function projectFiles() {
  const files = [{ path: project.names.scenario, text: scenarioYaml() }];
  if (S.model.file && model.bytes) {
    const { path, note } = savePath(S.model.file);
    files.push({ path, bytes: model.bytes, note: note || "the 3D model" });
  }
  const key = ORBIT_KEYS[S.orbit.source];
  if (key && orbitFile && orbitFile.name === S.orbit[key]) {
    const { path, note } = savePath(S.orbit[key]);
    files.push({ path, text: orbitFile.text, note: note || "the orbit file" });
  }
  if (project.hasPower) files.push({ path: project.names.power, text: powerYaml() });
  if (project.hasConsumption) files.push({ path: project.names.consumption, text: consumptionCsv() });
  return files;
}

function downloadZip() {
  const folder = (project.name || "quicksat_project").replace(/[^A-Za-z0-9_.-]+/g, "_");
  saveBlob(zipBlob(projectFiles().map((f) => ({ name: `${folder}/${f.path}`, data: fileBytes(f) }))), `${folder}.zip`);
}
