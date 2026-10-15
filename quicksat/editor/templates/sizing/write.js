// quicksat sizing editor: writing the folder's files from the project.

// ---------------------------------------------------------------- writing the files

const YAML_HELP = {
  altitude: "Above the Earth's equatorial radius. The orbit is circular.",
  inclination: "No budget reads it yet. It records the orbit the budgets assume.",
  duration: "The design life. It scales the recurring manoeuvres.",
  locations: "Each location's system margin, harness and harness margin, in percent, and whether it stays in orbit.",
  generation: "What the payload makes. The raw rate is divided by the compression ratio, and flows for the duty cycle's share of each orbit.",
  downlink: "What the link sends: the achieved throughput, the usable contacts in a day, and their average length.",
  storage: "The memory is sized for this many orbits without a usable contact.",
  propulsion: "The specific impulse, for the rocket equation.",
  margin: "In percent, one allowance on the total delta-V.",
  collision_avoidance: "return_burn is true when each avoidance comes back down, which doubles its delta-V.",
  inertia_cases: "Each case is an envelope estimate or a stated inertia, never both. An envelope is a body box with an appendage factor per axis, and follows the mass budget's mass. A stated inertia is fixed.",
  wheels: "A pyramid of reaction wheels about yaw. The momentum and the torque are nameplate figures per wheel. The use factor and the derating are the shares used in slews.",
  settling_time: "What the platform needs after a slew before the payload can work.",
};

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
    storage: [["orbits_without_contact", yn(D.storage.orbits_without_contact)]],
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
  files.push({ kind: "mass", path: n.mass, text: massYaml(), note: "margins and harness" }, { kind: "equipment", path: n.equipment, text: equipmentCsv(), note: "the equipment list" });
  files.push({ kind: "data", path: n.data, text: dataYaml(), note: "the payload data flow" });
  files.push({ kind: "deltav", path: n.deltav, text: deltavYaml(), note: "the delta-V settings" }, { kind: "manoeuvres", path: n.manoeuvres, text: manoeuvresCsv(), note: "the manoeuvres" });
  files.push({ kind: "agility", path: n.agility, text: agilityYaml(), note: "the agility settings" });
  return files;
}
