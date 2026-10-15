// quicksat sizing editor: the page's own checks.

// ---------------------------------------------------------------- the checks

/** What the page's checks leave to the notebooks, for the checks pop-over. */
const CHECKS_NOTE = "The budgets themselves come from the notebooks.";

/** The page's own checks: names, units and ranges. The budgets themselves need the notebooks. */
function runChecks() {
  const problems = [];
  const add = (section, text, level = "error") => problems.push({ section, text, level });
  const positive = (section, label, quantity) => {
    if (blank(quantity)) add(section, `${label} is missing`);
    else if (!(quantity.v > 0)) add(section, `${label} must be above zero`);
  };
  const atLeast = (section, label, value, low) => {
    if (value === "" || value == null) add(section, `${label} is missing`);
    else if (!(value >= low)) add(section, `${label} must be ${low} or more`);
  };
  const pct = (section, label, quantity, low = 0, high = 100) => {
    if (blank(quantity)) add(section, `${label} is missing`);
    else if (!(quantity.v >= low && quantity.v <= high)) add(section, `${label} must be ${low > 0 ? "above 0 and at most" : `from ${low} to`} ${high} %`);
  };
  const noSpace = (section, label, text) => {
    if (!String(text).trim()) add(section, `${label} is missing`);
    else if (/\s/.test(String(text).trim())) add(section, `${label} has a space: "${text}"`);
  };
  const unique = (section, kind, names) => {
    const seen = new Set();
    for (const name of names) {
      if (!name.trim()) add(section, `a ${kind} has no name`);
      if (name === RESERVED) add(section, `no ${kind} can be called "${RESERVED}": the name is kept for comments`);
      if (seen.has(name)) add(section, `two ${kind}s are called "${name}"`);
      seen.add(name);
    }
  };

  // Mission
  positive("mission", "the altitude", M.altitude);
  if (!blank(M.inclination) && !(M.inclination.v >= 0 && M.inclination.v <= (M.inclination.u === "rad" ? Math.PI : 180))) add("mission", "the inclination must be from 0 to 180 deg");
  if (blank(M.inclination)) add("mission", "the inclination is missing");
  positive("mission", "the duration", M.duration);
  const km = toKm(M.altitude);
  if (km != null && km > 2000) add("mission", `${fmt(km, 0)} km is above low Earth orbit; quicksat's budgets are meant for it`, "note");

  // Mass
  if (project.has.mass) {
    const L = project.mass.locations.items;
    unique("locations", "location", L.map((l) => l.name));
    for (const l of L) {
      noSpace("locations", `location ${l.name}: the name`, l.name);
      for (const key of ["system_margin", "harness_fraction", "harness_margin"]) atLeast("locations", `location ${l.name}: the ${key.replace("_", " ")}`, l[key], 0);
      if (l.name === LAUNCHER && l.retained_in_orbit) add("locations", `${LAUNCHER} is listed and stays in orbit, unlike its default`, "note");
      if (!project.equipment.some((r) => r.location === l.name)) add("locations", `no equipment is at ${l.name}`, "note");
    }
    const listed = new Set([...L.map((l) => l.name), LAUNCHER]);
    const pairs = new Set();
    project.equipment.forEach((r, i) => {
      const what = r.id || `row ${i + 1}`;
      noSpace("equipment", `${what}: the id`, r.id);
      if (!r.name.trim()) add("equipment", `${what}: the name is missing`);
      noSpace("equipment", `${what}: the location`, r.location);
      if (r.location && !listed.has(r.location)) add("equipment", `${what}: the location "${r.location}" is not in the locations`);
      noSpace("equipment", `${what}: the responsibility`, r.responsibility);
      noSpace("equipment", `${what}: the subsystem`, r.subsystem);
      if (blank(r.unit_mass)) add("equipment", `${what}: the unit mass is missing`);
      else if (toKg(r.unit_mass) == null) add("equipment", `${what}: "${qText(r.unit_mass)}" is not a mass`);
      else if (r.unit_mass.v < 0) add("equipment", `${what}: the unit mass cannot be below zero`);
      atLeast("equipment", `${what}: the margin`, r.margin, 0);
      if (r.units === "" || !(Number.isInteger(r.units) && r.units >= 0)) add("equipment", `${what}: the units must be a whole number, 0 or more`);
      if (r.mass_class === "propellant" && r.margin > 0) add("equipment", `${what}: propellant never takes a margin, so its ${r.margin} % is not used`, "note");
      const pair = `${r.id}@${r.location}`;
      if (r.id && pairs.has(pair)) add("equipment", `two rows at ${r.location} have the id "${r.id}"`);
      pairs.add(pair);
    });
    if (!project.equipment.length) add("equipment", "the list needs at least one row");
  }

  // Data
  if (project.has.data) {
    const { generation: G, downlink: D, storage: S } = project.data;
    positive("generation", "the raw data rate", G.raw_datarate);
    atLeast("generation", "the compression ratio", G.compression_ratio, 1);
    pct("generation", "the duty cycle", G.duty_cycle);
    if (blank(D.rate)) add("downlink", "the rate is missing");
    atLeast("downlink", "the contacts per day", D.contacts_per_day, 0);
    if (blank(D.avg_contact_duration)) add("downlink", "the average contact is missing");
    atLeast("storage", "the orbits without contact", S.orbits_without_contact, 0);
  }

  // Delta-V
  if (project.has.deltav) {
    const D = project.deltav;
    positive("dvconfig", "the Isp", D.propulsion.isp);
    atLeast("dvconfig", "the margin", D.margin, 0);
    if (!project.has.mass) add("dvconfig", "without a mass budget, the delta-V notebook must give the dry mass", "note");
    project.manoeuvres.forEach((r, i) => {
      const what = r.id || `row ${i + 1}`;
      noSpace("manoeuvres", `${what}: the id`, r.id);
      noSpace("manoeuvres", `${what}: the phase`, r.phase);
      if (!MANOEUVRE_TYPES.includes(r.type)) add("manoeuvres", `${what}: "${r.type}" is not a manoeuvre type`);
      else if (!VALUE_UNITS[r.type].includes(r.value.u)) add("manoeuvres", `${what}: a ${r.type} takes ${VALUE_UNITS[r.type].join(" or ")}, not ${r.value.u}`);
      if (blank(r.value)) add("manoeuvres", `${what}: the value is missing`);
      atLeast("manoeuvres", `${what}: the count`, r.count, 0);
      atLeast("manoeuvres", `${what}: the loss factor`, r.loss_factor, 1);
    });
    const ids = project.manoeuvres.map((r) => r.id).filter(Boolean);
    for (const id of new Set(ids.filter((id, i) => ids.indexOf(id) !== i))) add("manoeuvres", `two rows have the id "${id}"`, "note");
    if (!project.manoeuvres.length) add("manoeuvres", "the list needs at least one manoeuvre");
  }

  // Agility
  if (project.has.agility) {
    const A = project.agility;
    unique("cases", "case", A.cases.items.map((c) => c.name));
    if (!A.cases.items.length) add("cases", "there must be at least one case");
    for (const c of A.cases.items) {
      if (c.kind === "envelope") {
        for (const axis of ["x", "y", "z"]) positive("cases", `case ${c.name}: the body's ${axis}`, c.body[axis]);
        for (const axis of ["roll", "pitch"]) atLeast("cases", `case ${c.name}: the ${axis} appendage factor`, c.appendage_factor[axis], 1);
        pct("cases", `case ${c.name}: the propellant aboard`, c.propellant);
        if (!project.has.mass) add("cases", `case ${c.name} needs a mass, and this folder has no mass budget`, "note");
      } else {
        for (const axis of ["roll", "pitch"]) positive("cases", `case ${c.name}: the ${axis} inertia`, c.inertia[axis]);
      }
    }
    const W = A.wheels;
    if (W.count === "" || !(Number.isInteger(W.count) && W.count >= 1)) add("wheels", "the wheels must be a whole number, 1 or more");
    if (blank(W.elevation) || !(W.elevation.v >= 0 && W.elevation.v <= 90)) add("wheels", "the elevation must be from 0 to 90 deg");
    positive("wheels", "the momentum", W.momentum);
    positive("wheels", "the torque", W.torque);
    pct("wheels", "the momentum use factor", W.momentum_use_factor, 0.000001);
    pct("wheels", "the torque derating", W.torque_derating, 0.000001);
    if (blank(A.settling_time)) add("wheels", "the settling time is missing");
  }

  state.problems = problems;
  showProblems();
}
