// quicksat sizing editor: the project, read from the folder's files, the names
// and their uses, and the figures worked out from the fields.
//
// Python passes the files as YAML reads them when it writes the page, and
// open.js reads them the same way when the user opens a folder or a file. So
// this part only turns them into the page's fields. What it cannot keep, it
// notes, so that the page can say so before the user saves.

// ---------------------------------------------------------------- reading the files

const NUMBER_UNIT = /^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*)$/;

/** A number and its unit, from a number or text such as `500 km`; null if neither. */
function numberUnit(value) {
  if (typeof value === "number") return { v: value, u: "" };
  const match = String(value ?? "").trim().match(NUMBER_UNIT);
  return match ? { v: Number(match[1]), u: match[2].trim() } : null;
}

/** A quantity, with `unit` where the file gives none. */
function readQ(value, unit, where) {
  if (value == null || value === "") return q("", unit);
  const parsed = numberUnit(value);
  if (!parsed) { notice("changed", `${where}: "${value}" is not a number, and was left empty`); return q("", unit); }
  return q(parsed.v, parsed.u || unit);
}

/** A plain number, or "" when the field is empty or not a number. */
function readNum(value, where, fallback = "") {
  if (value == null || value === "") return fallback;
  const parsed = numberUnit(value);
  if (!parsed || parsed.u) { notice("changed", `${where}: "${value}" is not a plain number, and was left empty`); return ""; }
  return parsed.v;
}

/** A fraction, shown in percent: `5 %` or `0.05` both give 5 %. */
function readPercent(value, where, fallback = "") {
  if (value == null || value === "") return q(fallback, "%");
  const parsed = numberUnit(value);
  if (!parsed) { notice("changed", `${where}: "${value}" is not a number, and was left empty`); return q("", "%"); }
  if (parsed.u === "%" || parsed.u === "percent") return q(parsed.v, "%");
  if (!parsed.u) {
    notice("changed", `${where}: ${value} is read as ${Number((parsed.v * 100).toPrecision(12))} %`);
    return q(Number((parsed.v * 100).toPrecision(12)), "%");
  }
  notice("changed", `${where}: "${value}" is not a fraction, and was left empty`);
  return q("", "%");
}

function readBool(value, fallback) {
  if (typeof value === "boolean") return value;
  const text = String(value ?? "").trim().toLowerCase();
  if (["true", "yes", "1"].includes(text)) return true;
  if (["false", "no", "0"].includes(text)) return false;
  return fallback;
}

const mapOf = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});
const textOf = (value) => (typeof value === "string" ? value : "");

/** Note the keys that the editor does not know, which saving would leave out. */
function known(where, obj, keys) {
  for (const key of Object.keys(obj)) {
    if (key !== RESERVED && !keys.includes(key)) notice("unknown", `${where} › ${key}`);
  }
}

const NAMES = {
  mission: "mission.yaml",
  mass: "mass_budget_config.yaml",
  equipment: "equipment.csv",
  data: "pl_dataflow_model.yaml",
  deltav: "delta_v_config.yaml",
  manoeuvres: "manoeuvres.csv",
  agility: "agility_config.yaml",
};

const MASS_CLASSES = ["equipment", "propellant"];
const LAUNCHER = "Launcher";
const MANOEUVRE_TYPES = ["altitude_change", "collision_avoidance", "inclination_change", "deorbit", "given"];
const VALUE_UNITS = {
  altitude_change: ["km", "m"],
  collision_avoidance: ["m", "km"],
  inclination_change: ["deg"],
  deorbit: ["km", "m"],
  given: ["m/s"],
};
const EQUIPMENT_COLUMNS = ["equipment_id", "equipment_name", "location", "responsibility", "subsystem", "unit_mass", "eqpt_margin", "number_of_units", "mass_class", "comments"];
const MANOEUVRE_COLUMNS = ["manoeuvre_id", "manoeuvre_name", "phase", "manoeuvre_type", "value", "count", "recurring", "loss_factor", "comments"];

/** A CSV file's rows as objects, keyed by the header, noting any column the editor does not know. */
function csvRecords(file, columns) {
  if (!file) return [];
  for (const name of file.header) if (!columns.includes(name)) notice("unknown", `${file.name} › column ${name}`);
  return file.rows.map((cells) => Object.fromEntries(file.header.map((name, i) => [name, cells[i] ?? ""])));
}

function readMission(file) {
  const m = mapOf(file && file.data);
  known(NAMES.mission, m, ["altitude", "inclination", "duration"]);
  return {
    altitude: readQ(m.altitude, "km", "altitude"),
    inclination: readQ(m.inclination, "deg", "inclination"),
    duration: readQ(m.duration, "yr", "duration"),
    comments: textOf(m.comments),
  };
}

function readMass(file) {
  if (!file) {
    return { comments: "", locations: { comments: "", items: [
      { name: "Platform", system_margin: 20, harness_fraction: 5, harness_margin: 25, retained_in_orbit: true, comments: "" },
      { name: "Payload", system_margin: 20, harness_fraction: 5, harness_margin: 25, retained_in_orbit: true, comments: "" },
    ] } };
  }
  const m = mapOf(file.data);
  known(file.name, m, ["locations"]);
  const locations = mapOf(m.locations);
  return {
    comments: textOf(m.comments),
    locations: {
      comments: textOf(locations.comments),
      items: Object.entries(locations).filter(([name]) => name !== RESERVED).map(([name, value]) => {
        const l = mapOf(value);
        const where = `locations › ${name}`;
        known(`${file.name} › ${where}`, l, ["system_margin", "harness_fraction", "harness_margin", "retained_in_orbit"]);
        return {
          name,
          system_margin: readNum(l.system_margin, where, 0),
          harness_fraction: readNum(l.harness_fraction, where, 0),
          harness_margin: readNum(l.harness_margin, where, 0),
          retained_in_orbit: readBool(l.retained_in_orbit, true),
          comments: textOf(l.comments),
        };
      }),
    },
  };
}

function readEquipment(file) {
  return csvRecords(file, EQUIPMENT_COLUMNS).map((r, i) => ({
    id: r.equipment_id.trim(),
    name: r.equipment_name,
    location: r.location.trim(),
    responsibility: r.responsibility.trim(),
    subsystem: r.subsystem.trim(),
    unit_mass: readQ(r.unit_mass, "kg", `equipment row ${i + 2}`),
    margin: readNum(r.eqpt_margin, `equipment row ${i + 2}`),
    units: readNum(r.number_of_units, `equipment row ${i + 2}`),
    mass_class: (r.mass_class || "").trim().toLowerCase() || "equipment",
    comments: r.comments || "",
  }));
}

function readData(file) {
  const m = mapOf(file && file.data);
  if (file) known(file.name, m, ["generation", "downlink", "storage"]);
  const g = mapOf(m.generation), d = mapOf(m.downlink), s = mapOf(m.storage);
  if (file) {
    known(`${file.name} › generation`, g, ["raw_datarate", "compression_ratio", "duty_cycle"]);
    known(`${file.name} › downlink`, d, ["rate", "contacts_per_day", "avg_contact_duration"]);
    known(`${file.name} › storage`, s, ["orbits_without_contact"]);
  }
  return {
    comments: textOf(m.comments),
    generation: {
      raw_datarate: readQ(g.raw_datarate, "Mbit/s", "raw data rate"),
      compression_ratio: readNum(g.compression_ratio, "compression ratio", file ? "" : 1),
      duty_cycle: readPercent(g.duty_cycle, "duty cycle"),
      comments: textOf(g.comments),
    },
    downlink: {
      rate: readQ(d.rate, "Mbit/s", "downlink rate"),
      contacts_per_day: readNum(d.contacts_per_day, "contacts per day"),
      avg_contact_duration: readQ(d.avg_contact_duration, "min", "contact duration"),
      comments: textOf(d.comments),
    },
    storage: {
      orbits_without_contact: readNum(s.orbits_without_contact, "orbits without contact", file ? "" : 1),
      comments: textOf(s.comments),
    },
  };
}

function readDeltaV(file) {
  const m = mapOf(file && file.data);
  if (file) known(file.name, m, ["propulsion", "margin", "collision_avoidance"]);
  const p = mapOf(m.propulsion), c = mapOf(m.collision_avoidance);
  return {
    comments: textOf(m.comments),
    propulsion: { isp: readQ(p.isp, "s", "isp"), comments: textOf(p.comments) },
    margin: readNum(m.margin, "margin", 0),
    collision_avoidance: { return_burn: readBool(c.return_burn, true), comments: textOf(c.comments) },
  };
}

function readManoeuvres(file) {
  return csvRecords(file, MANOEUVRE_COLUMNS).map((r, i) => {
    const type = r.manoeuvre_type.trim();
    const units = VALUE_UNITS[type] || ["m"];
    return {
      id: r.manoeuvre_id.trim(),
      name: r.manoeuvre_name,
      phase: r.phase.trim(),
      type,
      value: readQ(r.value, units[0], `manoeuvre row ${i + 2}`),
      count: readNum(r.count, `manoeuvre row ${i + 2}`),
      recurring: readBool(r.recurring, false),
      loss_factor: readNum(r.loss_factor, `manoeuvre row ${i + 2}`, 1),
      comments: r.comments || "",
    };
  });
}

/** A new envelope case, or the envelope half of a case that states its inertia. */
const envelope = () => ({ body: { x: q("", "m"), y: q("", "m"), z: q("", "m") }, appendage_factor: { roll: 1, pitch: 1 }, propellant: q(100, "%") });

function readAgility(file) {
  const m = mapOf(file && file.data);
  if (file) known(file.name, m, ["inertia_cases", "wheels", "settling_time"]);
  const cases = mapOf(m.inertia_cases);
  const w = mapOf(m.wheels);
  if (file) known(`${file.name} › wheels`, w, ["count", "elevation", "momentum", "torque", "momentum_use_factor", "torque_derating"]);
  return {
    comments: textOf(m.comments),
    cases: {
      comments: textOf(cases.comments),
      items: Object.entries(cases).filter(([name]) => name !== RESERVED).map(([name, value]) => {
        const c = mapOf(value);
        const where = `inertia_cases › ${name}`;
        known(`${file.name} › ${where}`, c, ["body", "appendage_factor", "propellant", "inertia"]);
        const item = { name, kind: c.inertia ? "stated" : "envelope", ...envelope(), inertia: { roll: q("", "kg*m**2"), pitch: q("", "kg*m**2") }, comments: textOf(c.comments) };
        if (c.inertia && (c.body || c.appendage_factor)) notice("changed", `${where} states an inertia and also has an envelope: the editor keeps the stated inertia`);
        if (c.inertia) {
          const i = mapOf(c.inertia);
          item.inertia = { roll: readQ(i.roll, "kg*m**2", `${where} › roll`), pitch: readQ(i.pitch, "kg*m**2", `${where} › pitch`) };
        }
        const b = mapOf(c.body), f = mapOf(c.appendage_factor);
        if (c.body) item.body = { x: readQ(b.x, "m", `${where} › x`), y: readQ(b.y, "m", `${where} › y`), z: readQ(b.z, "m", `${where} › z`) };
        if (c.appendage_factor) item.appendage_factor = { roll: readNum(f.roll, `${where} › roll`), pitch: readNum(f.pitch, `${where} › pitch`) };
        if (c.propellant != null) item.propellant = readPercent(c.propellant, `${where} › propellant`);
        return item;
      }),
    },
    wheels: {
      count: readNum(w.count, "wheel count"),
      elevation: readQ(w.elevation, "deg", "wheel elevation"),
      momentum: readQ(w.momentum, "N*m*s", "wheel momentum"),
      torque: readQ(w.torque, "N*m", "wheel torque"),
      momentum_use_factor: readPercent(w.momentum_use_factor, "momentum use factor"),
      torque_derating: readPercent(w.torque_derating, "torque derating"),
      comments: textOf(w.comments),
    },
    settling_time: readQ(m.settling_time, "s", "settling time"),
  };
}

function readProject(data) {
  const f = data.files;
  return {
    name: data.folder,
    names: Object.fromEntries(Object.entries(NAMES).map(([key, name]) => [key, (f[key] && f[key].name) || name])),
    has: { mass: Boolean(f.mass || f.equipment), data: Boolean(f.data), deltav: Boolean(f.deltav || f.manoeuvres), agility: Boolean(f.agility) },
    ...Object.fromEntries(Object.entries(READERS).map(([kind, read]) => [kind, readingFile(kind, () => read(f[kind]))])),
  };
}

/** Each file's reader, by the file's kind. */
const READERS = { mission: readMission, mass: readMass, equipment: readEquipment, data: readData, deltav: readDeltaV, manoeuvres: readManoeuvres, agility: readAgility };

/** The folder's files: as Python wrote them into the page, or as the user opened them. */
let DATA = JSON.parse($("#project").textContent);
let project = readProject(DATA);
let M = project.mission;

// What the page shows, beyond the frame's: the equipment table's filter
Object.assign(state, { file: project.names.mission, filter: "" });

// ---------------------------------------------------------------- names and their uses

const locationNames = () => project.mass.locations.items.map((l) => l.name);

/** Where a name is used: a list of short descriptions. */
function usesOf(kind, name) {
  if (kind !== "location") return [];
  const rows = project.equipment.filter((r) => r.location === name).map((r) => r.id || "a row");
  return rows.length > 3 ? [...rows.slice(0, 3), `${rows.length - 3} more`] : rows;
}

function rename(kind, from, to) {
  if (kind === "location") for (const r of project.equipment) if (r.location === from) r.location = to;
}

// What the page shows from the fields, refreshed as they change without a redraw
const live = new Set();

// ---------------------------------------------------------------- figures from the fields

const R_EARTH_KM = 6378.1; // astropy's R_earth, the IAU 2015 nominal equatorial radius
const MU_EARTH = 398600.4418; // km**3/s**2, astropy's GM_earth

/** A quantity in a unit of `factors`, or null when it is empty or in another unit. */
function inUnit(quantity, factors) {
  if (blank(quantity) || !(quantity.u in factors)) return null;
  return quantity.v * factors[quantity.u];
}
const toKm = (quantity) => inUnit(quantity, { km: 1, m: 0.001 });
const toKg = (quantity) => inUnit(quantity, { kg: 1, g: 0.001 });
const fmt = (x, digits = 1) => Number(x).toLocaleString("en", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** The orbit's figures that the other budgets read, from the altitude alone. */
function missionFigures() {
  const altitude = toKm(M.altitude);
  if (altitude == null || !(altitude > 0)) return null;
  const radius = R_EARTH_KM + altitude;
  const period = 2 * Math.PI * Math.sqrt(radius ** 3 / MU_EARTH);
  const speed = Math.sqrt(MU_EARTH / radius);
  return { period, perDay: 86400 / period, speed, ground: (speed * R_EARTH_KM) / radius };
}

function missionLine() {
  const node = el("div", { class: "derived" });
  const update = () => {
    const f = missionFigures();
    node.replaceChildren(el("span", { class: "k", text: "from the altitude" }),
      f ? el("span", { html: `period <b>${fmt(f.period / 60, 2)} min</b> · <b>${fmt(f.perDay, 2)}</b> orbits a day · orbital speed <b>${fmt(f.speed, 3)} km/s</b> · ground track <b>${fmt(f.ground, 3)} km/s</b>` }) : "give an altitude in km or m");
  };
  update();
  live.add(update);
  return node;
}

/** A row's mass: one unit times the count, and with its margin. Propellant takes none. */
function rowMass(r) {
  const unit = toKg(r.unit_mass);
  if (unit == null || r.units === "") return null;
  const entered = unit * r.units;
  const margin = r.mass_class === "propellant" || r.margin === "" ? 0 : r.margin;
  return { entered, withMargin: entered * (1 + margin / 100) };
}

/** The rows as entered, added by location, with the propellant on its own. */
function equipmentTotals() {
  const groups = new Map();
  const add = (key, mass) => {
    const g = groups.get(key) || { rows: 0, entered: 0, withMargin: 0 };
    g.rows += 1;
    g.entered += mass.entered;
    g.withMargin += mass.withMargin;
    groups.set(key, g);
  };
  for (const r of project.equipment) {
    const mass = rowMass(r);
    if (mass) add(r.mass_class === "propellant" ? "propellant" : r.location || "no location", mass);
  }
  return groups;
}

function totalsTable() {
  const table = el("table", { class: "totals" });
  const update = () => {
    const groups = equipmentTotals();
    const keys = [...groups.keys()].filter((k) => k !== "propellant").sort();
    if (groups.has("propellant")) keys.push("propellant");
    let entered = 0, withMargin = 0, rows = 0;
    table.replaceChildren(el("tr", {}, ["as entered, by location", "rows", "units × unit mass", "with equipment margins"].map((h) => el("th", { text: h }))));
    for (const key of keys) {
      const g = groups.get(key);
      entered += g.entered; withMargin += g.withMargin; rows += g.rows;
      table.append(el("tr", {}, el("td", { text: key === "propellant" ? "propellant, full" : key }), el("td", { text: g.rows }), el("td", { text: `${fmt(g.entered, 2)} kg` }), el("td", { text: `${fmt(g.withMargin, 2)} kg` })));
    }
    table.append(el("tr", { class: "sum" }, el("td", { text: "all rows" }), el("td", { text: rows }), el("td", { text: `${fmt(entered, 2)} kg` }), el("td", { text: `${fmt(withMargin, 2)} kg` })));
  };
  update();
  live.add(update);
  return table;
}
