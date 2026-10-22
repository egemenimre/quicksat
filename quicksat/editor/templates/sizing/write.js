// quicksat sizing editor: writing the folder's files from the project.

// ---------------------------------------------------------------- writing the files

function start(comments) {
  const lines = [...HEADER, ""];
  if ((comments || "").trim()) { commentsLines(lines, 0, comments); lines.push(""); }
  return lines;
}

const finish = (lines) => {
  while (lines[lines.length - 1] === "") lines.pop();
  return lines.join("\n") + "\n";
};

/** A block of fields under its key, with its comments field last. */
function block(lines, indent, key, pairs, comments) {
  const pad = " ".repeat(indent);
  lines.push(`${pad}${key}:`);
  for (const [k, v] of pairs) if (v !== "" && v != null) lines.push(`${pad}  ${k}: ${v}`);
  commentsLines(lines, indent + 2, comments);
}

function missionYaml() {
  const lines = start(M.comments);
  for (const key of ["altitude", "inclination", "duration"]) {
    helpLines(lines, 0, key);
    lines.push(`${key}: ${yq(M[key])}`);
  }
  return finish(lines);
}

function requirementsYaml() {
  const R = project.requirements;
  const S = R.agility.slews;
  const lines = start(R.comments);
  if (S.items.length || R.agility.comments.trim() || S.comments.trim()) {
    helpLines(lines, 0, "slews");
    lines.push("agility:");
    commentsLines(lines, 2, R.agility.comments);
    if (!S.items.length && !S.comments.trim()) lines.push("  slews: {}");
    else lines.push("  slews:");
    commentsLines(lines, 4, S.comments);
    for (const slew of S.items) {
      itemLines(lines, 4, slew.name, [["axis", ys(slew.axis)], ["angle", yq(slew.angle)], ["duration", yq(slew.duration)]], slew.comments);
    }
    lines.push("");
  }
  if (R.data.orbits_without_contact !== "" || R.data.comments.trim()) {
    helpLines(lines, 0, "required_storage");
    block(lines, 0, "data", [["orbits_without_contact", yn(R.data.orbits_without_contact)]], R.data.comments);
  }
  return finish(lines);
}

function massYaml() {
  const C = project.mass;
  const L = C.locations;
  const lines = start(C.comments);
  helpLines(lines, 0, "locations");
  if (!L.items.length && !L.comments.trim()) { lines.push("locations: {}"); return finish(lines); }
  lines.push("locations:");
  commentsLines(lines, 2, L.comments);
  for (const l of L.items) {
    itemLines(lines, 2, l.name, [["system_margin", yn(l.system_margin)], ["harness_fraction", yn(l.harness_fraction)], ["harness_margin", yn(l.harness_margin)], ["retained_in_orbit", l.retained_in_orbit ? "" : "false"]], l.comments);
  }
  return finish(lines);
}

function equipmentCsv() {
  const lines = [EQUIPMENT_COLUMNS.join(",")];
  for (const r of project.equipment) {
    lines.push([r.id, r.name, r.location, r.responsibility, r.subsystem, qText(r.unit_mass), r.margin, r.units, r.mass_class, r.comments].map(csvCell).join(","));
  }
  return lines.join("\n") + "\n";
}

function dataYaml() {
  const D = project.data;
  const lines = start(D.comments);
  const blocks = {
    generation: [["raw_datarate", yq(D.generation.raw_datarate)], ["compression_ratio", yn(D.generation.compression_ratio)], ["duty_cycle", yq(D.generation.duty_cycle)]],
    downlink: [["rate", yq(D.downlink.rate)], ["contacts_per_day", yn(D.downlink.contacts_per_day)], ["avg_contact_duration", yq(D.downlink.avg_contact_duration)]],
    storage: [["capacity", yq(D.storage.capacity)]],
  };
  for (const [key, pairs] of Object.entries(blocks)) {
    helpLines(lines, 0, key);
    block(lines, 0, key, pairs, D[key].comments);
    lines.push("");
  }
  return finish(lines);
}

function deltavYaml() {
  const D = project.deltav;
  const lines = start(D.comments);
  helpLines(lines, 0, "propulsion");
  block(lines, 0, "propulsion", [["isp", yq(D.propulsion.isp)]], D.propulsion.comments);
  lines.push("");
  helpLines(lines, 0, "margin");
  lines.push(`margin: ${yn(D.margin)}`);
  lines.push("");
  helpLines(lines, 0, "collision_avoidance");
  block(lines, 0, "collision_avoidance", [["return_burn", String(D.collision_avoidance.return_burn)]], D.collision_avoidance.comments);
  return finish(lines);
}

function manoeuvresCsv() {
  const lines = [MANOEUVRE_COLUMNS.join(",")];
  for (const r of project.manoeuvres) {
    lines.push([r.id, r.name, r.phase, r.type, qText(r.value), r.count, String(r.recurring), r.loss_factor, r.comments].map(csvCell).join(","));
  }
  return lines.join("\n") + "\n";
}

function agilityYaml() {
  const A = project.agility;
  const lines = start(A.comments);
  helpLines(lines, 0, "selected_case");
  if (A.selected) lines.push(`selected_case: ${ys(A.selected)}`);
  lines.push("");
  helpLines(lines, 0, "inertia_cases");
  lines.push("inertia_cases:");
  commentsLines(lines, 2, A.cases.comments);
  for (const c of A.cases.items) {
    const pairs = c.kind === "envelope"
      ? [["body", flowMap(["x", "y", "z"].map((axis) => [axis, yq(c.body[axis])]))],
         ["appendage_factor", flowMap(["roll", "pitch"].map((axis) => [axis, yn(c.appendage_factor[axis])]))],
         ["propellant", yq(c.propellant)]]
      : [["inertia", flowMap(["roll", "pitch"].map((axis) => [axis, yq(c.inertia[axis])]))]];
    block(lines, 2, ys(c.name), pairs, c.comments);
  }
  lines.push("");
  const W = A.wheels;
  helpLines(lines, 0, "wheels");
  block(lines, 0, "wheels", [["count", yn(W.count)], ["elevation", yq(W.elevation)], ["momentum", yq(W.momentum)], ["torque", yq(W.torque)], ["momentum_use_factor", yq(W.momentum_use_factor)], ["torque_derating", yq(W.torque_derating)]], W.comments);
  lines.push("");
  helpLines(lines, 0, "settling_time");
  lines.push(`settling_time: ${yq(A.settling_time)}`);
  return finish(lines);
}

/** Every file the folder saves: the mission, and the files of every budget. */
function projectFiles() {
  const n = project.names;
  const files = [{ kind: "mission", path: n.mission, text: missionYaml(), note: "the reference orbit and the design life" }];
  files.push({ kind: "requirements", path: n.requirements, text: requirementsYaml(), note: "what the mission asks of the spacecraft" });
  files.push({ kind: "mass", path: n.mass, text: massYaml(), note: "margins and harness" }, { kind: "equipment", path: n.equipment, text: equipmentCsv(), note: "the equipment list" });
  files.push({ kind: "data", path: n.data, text: dataYaml(), note: "the payload data flow" });
  files.push({ kind: "deltav", path: n.deltav, text: deltavYaml(), note: "the delta-V settings" }, { kind: "manoeuvres", path: n.manoeuvres, text: manoeuvresCsv(), note: "the manoeuvres" });
  files.push({ kind: "agility", path: n.agility, text: agilityYaml(), note: "the agility settings" });
  return files;
}
