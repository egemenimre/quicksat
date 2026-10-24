// quicksat scenario editor: the project, read from the folder's files.
//
// Python passes the files as YAML reads them when it writes the page, and
// open.js reads them the same way when the user opens a folder or a file. So
// this part only turns them into the page's fields. What it cannot keep, it
// notes, so that the page can say so before the user saves.

// ---------------------------------------------------------------- constants

const AXES = ["+x", "-x", "+y", "-y", "+z", "-z"];
const BUILT_IN_DIRECTIONS = ["nadir", "sun", "orbit normal", "velocity", "ground velocity"];
const CONSTRAINTS = ["", "sunlit", "penumbra", "umbra", "eclipse"];
const TIME_UNITS = ["s", "min", "h"];
const TRIGGERS = [
  ["duration", "after a duration"],
  ["eclipse entry", "eclipse entry"],
  ["umbra entry", "umbra entry"],
  ["umbra exit", "umbra exit"],
  ["eclipse exit", "eclipse exit"],
  ["ascending node", "ascending node"],
  ["descending node", "descending node"],
  ["latitude", "latitude crossing"],
  ["rise", "a target rises"],
  ["set", "a target sets"],
  ["text", "as written"],
];
const SLEW = "slew";
/** The attitude and mode rows' value after the last activity, in the Activity Designer's run. */
const UNPLANNED = "unplanned";
/** The two parts of the spacecraft that each have a mode at a time: the payload, and the platform that carries it. */
const GROUPS = ["payload", "platform"];
/** The keys of an activity's modes in the file, by group: `payload_mode` and `platform_mode`. */
const MODE_KEYS = Object.fromEntries(GROUPS.map((group) => [group, `${group}_mode`]));
/** The key of an activity's modes that says which mode the payload is in during the slew into the activity. */
const IN_SLEW = "payload_mode_in_slew";
/** Its two values, the default first, with their labels on the page. */
const IN_SLEW_CHOICES = [["prev_activity", "prev activity"], ["this_activity", "this activity"]];
const PREV_ACTIVITY = IN_SLEW_CHOICES[0][0];
const groupTitle = (group) => group[0].toUpperCase() + group.slice(1);
/** A group's consumption file, as the page's files name its kind. */
const consumptionKind = (group) => `${group}_consumption`;
/** The key that names an orbit's file, for each kind of file. */
const ORBIT_KEYS = { tle: "tle_file", omm: "omm_file", trajectory: "trajectory_file" };

/** The folder's files: as Python wrote them into the page, or as the user opened them. */
let DATA = JSON.parse($("#project").textContent);

// ---------------------------------------------------------------- reading values

const NUMBER_UNIT = /^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*)$/;

/** A number and its unit, from a number or text such as `510 km`; null if neither. */
function numberUnit(value) {
  if (typeof value === "number") return { v: value, u: "" };
  const match = String(value ?? "").trim().match(NUMBER_UNIT);
  return match ? { v: Number(match[1]), u: match[2].trim() } : null;
}

const tidy = (x) => Number(Number(x).toPrecision(12));

/** A quantity, with `unit` where the file gives none. */
function readQ(value, unit, where) {
  if (value == null || value === "") return q("", unit);
  const parsed = numberUnit(value);
  if (!parsed) { notice("changed", `${where}: "${value}" is not a number, and was left empty`); return q("", unit); }
  const u = /^orbits?$/i.test(parsed.u) ? "orbits" : parsed.u || unit;
  return q(parsed.v, u);
}

/** A fraction, shown in percent: `30 %` or `0.30` both give 30 %. */
function readPercent(value, where) {
  if (value == null || value === "") return q("", "%");
  const parsed = numberUnit(value);
  if (!parsed) { notice("changed", `${where}: "${value}" is not a number, and was left empty`); return q("", "%"); }
  if (parsed.u === "") return q(tidy(parsed.v * 100), "%");
  return q(parsed.v, parsed.u);
}

/** A fraction, shown as a plain number: `80 %` or `0.80` both give 0.8. */
function readFraction(value, where) {
  if (value == null || value === "") return "";
  const parsed = numberUnit(value);
  if (!parsed) { notice("changed", `${where}: "${value}" is not a number, and was left empty`); return ""; }
  return parsed.u === "%" ? tidy(parsed.v / 100) : parsed.v;
}

/** Note the keys of a block that the editor does not handle. */
function knownKeys(obj, keys, where) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return;
  for (const key of Object.keys(obj)) if (!keys.includes(key)) notice("unknown", `${where} › ${key}`);
}

/** The named items of a section, without its own `comments`. */
function namedItems(section) {
  if (!section || typeof section !== "object" || Array.isArray(section)) return [];
  return Object.entries(section).filter(([name, value]) => !(name === RESERVED && typeof value === "string"));
}

const sectionComments = (section) => (section && typeof section[RESERVED] === "string" ? section[RESERVED] : "");

// ---------------------------------------------------------------- triggers

/** One activity's trigger, as the builder holds it. */
const trigger = (kind, extra = {}) => ({
  kind, value: q(20, "min"), latitude: q(45, "deg"), direction: "either", target: "",
  offset: { sign: "+", v: "", u: "min" }, text: "", ...extra,
});

const OFFSET = String.raw`(?: ?([+-]) ?((?:\d+\.?\d*|\.\d+)) ?([a-z]+))?`;
const EVENT_RE = new RegExp(String.raw`^(eclipse entry|eclipse exit|umbra entry|umbra exit|ascending node|descending node|latitude ([+-]?(?:\d+\.?\d*|\.\d+)) ?([a-z]+)(?: (ascending|descending))?)${OFFSET}$`, "i");
const RISE_SET_RE = new RegExp(String.raw`^(.+?) (rise|set)${OFFSET}$`, "i");
const DURATION_RE = /^((?:\d+\.?\d*|\.\d+)) ?([a-z]+)$/i;

/**
 * A trigger from its text, by the same grammar as quicksat's. Text that does not
 * read is kept as it is, under "as written". A trigger that reads keeps its text
 * too, which the file gets back for as long as the trigger is not changed.
 */
function parseTrigger(text) {
  const end = readTrigger(text);
  if (end.kind !== "text") { end.written = String(text ?? "").trim(); end.writtenAs = triggerText(end); }
  return end;
}

function readTrigger(text) {
  const tidied = String(text ?? "").trim().replace(/\s+/g, " ");
  const offset = (sign, v, u) => ({ sign: sign || "+", v: v === undefined ? "" : Number(v), u: u || "min" });
  let match = tidied.match(EVENT_RE);
  if (match) {
    const [, event, latitude, unit, direction, sign, v, u] = match;
    if (latitude !== undefined) {
      return trigger("latitude", { latitude: q(Number(latitude), unit), direction: direction ? direction.toLowerCase() : "either", offset: offset(sign, v, u) });
    }
    return trigger(event.toLowerCase(), { offset: offset(sign, v, u) });
  }
  match = tidied.match(DURATION_RE);
  if (match) return trigger("duration", { value: q(Number(match[1]), match[2]) });
  match = tidied.match(RISE_SET_RE);
  if (match) {
    const [, target, edge, sign, v, u] = match;
    return trigger(edge.toLowerCase(), { target, offset: offset(sign, v, u) });
  }
  return trigger("text", { text: tidied });
}

/** The text of a trigger, as `scenario.yaml` writes it: as the file had it, if unchanged. */
function triggerText(end) {
  const text = builtTriggerText(end);
  return end.written && text === end.writtenAs ? end.written : text;
}

function builtTriggerText(end) {
  let text;
  switch (end.kind) {
    case "duration": return qText(end.value);
    case "text": return end.text;
    case "latitude": text = `latitude ${qText(end.latitude)}${end.direction === "either" ? "" : " " + end.direction}`; break;
    case "rise": case "set": text = `${end.target || "?"} ${end.kind}`; break;
    default: text = end.kind;
  }
  const offset = end.offset;
  if (offset && offset.v !== "" && Number(offset.v) !== 0) text += ` ${offset.sign} ${offset.v} ${offset.u}`;
  return text;
}

// ---------------------------------------------------------------- the scenario file

/** A node's local time, `ltan` or `ltdn`, as `HH:MM`, from `"13:30"`, `10.5 h`, or the minutes YAML makes of an unquoted 13:30. */
function readNodeTime(value, key) {
  if (typeof value === "number") {
    notice("changed", `orbit › sso › ${key}: an unquoted ${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")} reads as ${value} in YAML; the editor writes it in quotes`);
    return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
  }
  const text = String(value ?? "").trim();
  if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(text)) return text.padStart(text.length + (text.indexOf(":") === 1 ? 1 : 0), "0");
  const parsed = numberUnit(text);
  if (parsed && parsed.u === "h") {
    const minutes = Math.round(parsed.v * 60);
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  }
  return text;
}

/** The start as the date-and-time field shows it: `2026-10-01T09:00:00`. */
function readStart(value) {
  let text = String(value ?? "").trim().replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T00:00:00";
  const zone = text.match(/(Z|[+-]00:00)$/);
  if (zone) text = text.slice(0, -zone[0].length);
  else if (/[+-]\d{2}:\d{2}$/.test(text)) notice("changed", `start: "${value}" has a time zone, which the date field cannot show; set the time in UTC`);
  return text;
}

function readArticulation(name, raw) {
  const where = `3d_model › articulations › ${name}`;
  knownKeys(raw, ["part", "axis", "point", "range", "park", "comments"], where);
  const point = Array.isArray(raw.point) ? raw.point.map(str) : ["-z", "sun"];
  const park = raw.park && typeof raw.park === "object" ? Object.entries(raw.park).map(([mode, angle]) => ({ mode, angle: readQ(angle, "deg", where) })) : [];
  const range = Array.isArray(raw.range) && raw.range.length === 2 ? { min: readQ(raw.range[0], "deg", where), max: readQ(raw.range[1], "deg", where) } : null;
  return { name, part: str(raw.part), axis: str(raw.axis) || "+y", point, park, range, comments: str(raw.comments) };
}

/** A satellite target: where its orbit comes from, the element set it takes, and its clearance. */
function readSatTarget(name, raw) {
  const where = `sat_targets › ${name}`;
  knownKeys(raw, ["tle_file", "omm_file", "trajectory_file", "object", "min_clearance", "comments"], where);
  const source = raw.omm_file ? "omm" : raw.trajectory_file ? "trajectory" : "tle";
  return {
    name, source, file: str(raw[ORBIT_KEYS[source]]), object: str(raw.object),
    min_clearance: readQ(raw.min_clearance, "km", where), comments: str(raw.comments),
  };
}

function readActivity(raw, index) {
  const where = `activities › ${index + 1}`;
  let fields = {};
  if (Array.isArray(raw)) {
    const [title, end, attitude, mode, constraint] = raw;
    fields = { title, end, attitude, mode, constraint };
  } else if (raw && typeof raw === "object") {
    knownKeys(raw, ["title", "end", "attitude", "mode", "constraint", "comments"], where);
    fields = raw;
  }
  return {
    title: str(fields.title), end: parseTrigger(fields.end), attitude: str(fields.attitude), mode: readModes(fields.mode, where),
    constraint: str(fields.constraint), comments: str(fields.comments),
  };
}

/**
 * An activity's modes: the payload's and the platform's, written
 * `{payload_mode: imaging, platform_mode: imaging}`, and the payload's mode in
 * the slew into the activity, `in_slew`, from an optional `payload_mode_in_slew`.
 */
function readModes(raw, where) {
  const blankModes = { payload: "", platform: "", in_slew: PREV_ACTIVITY };
  if (raw === undefined || raw === null || raw === "") return blankModes;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    notice("changed", `${where}: the mode "${raw}" gives neither the payload's nor the platform's, and was left empty`);
    return blankModes;
  }
  knownKeys(raw, [...Object.values(MODE_KEYS), IN_SLEW], `${where} › mode`);
  let inSlew = str(raw[IN_SLEW]) || PREV_ACTIVITY;
  if (!IN_SLEW_CHOICES.some(([value]) => value === inSlew)) {
    notice("changed", `${where}: ${IN_SLEW} "${inSlew}" is neither ${IN_SLEW_CHOICES.map(([value]) => value).join(" nor ")}, and was set to ${PREV_ACTIVITY}`);
    inSlew = PREV_ACTIVITY;
  }
  return { payload: str(raw[MODE_KEYS.payload]), platform: str(raw[MODE_KEYS.platform]), in_slew: inSlew };
}

function readScenario(raw) {
  raw = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  knownKeys(raw, ["comments", "orbit", "start", "duration", "step", "3d_model", "gnd_targets", "sat_targets", "attitudes", "slew", "activities"], "scenario");
  const orbitRaw = raw.orbit && typeof raw.orbit === "object" ? raw.orbit : {};
  knownKeys(orbitRaw, ["comments", "sso", "tle_file", "omm_file", "trajectory_file"], "orbit");
  const ssoRaw = orbitRaw.sso && typeof orbitRaw.sso === "object" ? orbitRaw.sso : null;
  knownKeys(ssoRaw, ["altitude", "ltan", "ltdn", "comments"], "orbit › sso");
  // the local time of one node: the ascending one, unless only the descending one is given
  const node = ssoRaw && ssoRaw.ltdn != null && ssoRaw.ltan == null ? "ltdn" : "ltan";
  if (ssoRaw && ssoRaw.ltan != null && ssoRaw.ltdn != null) notice("changed", "orbit › sso has both ltan and ltdn, which quicksat refuses; the editor keeps ltan");
  const source = ssoRaw ? "sso" : orbitRaw.tle_file ? "tle" : orbitRaw.omm_file ? "omm" : orbitRaw.trajectory_file ? "trajectory" : "sso";

  const modelRaw = raw["3d_model"];
  const modelMap = modelRaw && typeof modelRaw === "object" ? modelRaw : { file: modelRaw };
  knownKeys(modelRaw && typeof modelRaw === "object" ? modelRaw : null, ["file", "articulations", "comments"], "3d_model");

  const slewRaw = raw.slew && typeof raw.slew === "object" ? raw.slew : null;
  knownKeys(slewRaw, ["max_rate", "max_acceleration", "settling_time", "comments"], "slew");

  return {
    comments: str(raw.comments),
    orbit: {
      source,
      sso: {
        altitude: ssoRaw ? readQ(ssoRaw.altitude, "km", "orbit › sso › altitude") : q(500, "km"),
        node,
        time: ssoRaw ? readNodeTime(ssoRaw[node], node) : "10:30",
        comments: ssoRaw ? str(ssoRaw.comments) : "",
      },
      tle_file: str(orbitRaw.tle_file),
      omm_file: str(orbitRaw.omm_file),
      trajectory_file: str(orbitRaw.trajectory_file),
      comments: str(orbitRaw.comments),
    },
    start: readStart(raw.start),
    duration: readQ(raw.duration, "h", "duration"),
    step: readQ(raw.step, "s", "step"),
    model: {
      file: str(modelMap.file),
      comments: str(modelMap.comments),
      articulations: {
        comments: sectionComments(modelMap.articulations),
        items: namedItems(modelMap.articulations).map(([name, value]) => readArticulation(name, value || {})),
      },
    },
    gnd_targets: {
      comments: sectionComments(raw.gnd_targets),
      items: namedItems(raw.gnd_targets).map(([name, t]) => {
        t = t || {};
        knownKeys(t, ["latitude", "longitude", "altitude", "min_elevation", "comments"], `gnd_targets › ${name}`);
        return {
          name, latitude: readQ(t.latitude, "deg", name), longitude: readQ(t.longitude, "deg", name),
          altitude: readQ(t.altitude, "m", name), min_elevation: readQ(t.min_elevation, "deg", name), comments: str(t.comments),
        };
      }),
    },
    sat_targets: {
      comments: sectionComments(raw.sat_targets),
      items: namedItems(raw.sat_targets).map(([name, t]) => readSatTarget(name, t || {})),
    },
    attitudes: {
      comments: sectionComments(raw.attitudes),
      items: namedItems(raw.attitudes).map(([name, a]) => {
        a = a || {};
        knownKeys(a, ["point", "constrain", "fallback", "offset", "comments"], `attitudes › ${name}`);
        const pair = (p, fallback) => (Array.isArray(p) && p.length === 2 ? p.map(str) : fallback);
        return {
          name, point: pair(a.point, ["+z", "nadir"]), constrain: pair(a.constrain, ["-y", "orbit normal"]),
          fallback: str(a.fallback), offset: Array.isArray(a.offset) ? a.offset.map(str).join(", ") : "", comments: str(a.comments),
        };
      }),
    },
    slew: {
      enabled: Boolean(slewRaw),
      max_rate: readQ(slewRaw && slewRaw.max_rate, "deg/s", "slew"),
      max_acceleration: readQ(slewRaw && slewRaw.max_acceleration, "deg/s2", "slew"),
      settling_time: readQ(slewRaw && slewRaw.settling_time, "s", "slew"),
      comments: slewRaw ? str(slewRaw.comments) : "",
    },
    activities: Array.isArray(raw.activities) ? raw.activities.map(readActivity) : [],
  };
}

// ---------------------------------------------------------------- the power files

/** A typed-in normal as the field shows it: an axis, or three numbers. */
const readNormal = (value) => (Array.isArray(value) ? value.join(", ") : str(value) || "+x");

function readPower(raw) {
  raw = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  knownKeys(raw, ["comments", "cell_efficiency", "loss_factor", "panels", "self_shadowing", "battery", "conditioning", "system_margin"], "power system");
  const shadowRaw = raw.self_shadowing && typeof raw.self_shadowing === "object" ? raw.self_shadowing : null;
  knownKeys(shadowRaw, ["enabled", "points", "comments"], "self_shadowing");
  const batteryRaw = raw.battery && typeof raw.battery === "object" ? raw.battery : null;
  knownKeys(batteryRaw, ["capacity", "capacity_factor", "max_depth_of_discharge", "initial_charge", "comments"], "battery");
  const conditioningRaw = raw.conditioning && typeof raw.conditioning === "object" ? raw.conditioning : null;
  const CONDITIONING = ["array_regulator", "battery_charge", "battery_discharge", "distribution"];
  knownKeys(conditioningRaw, [...CONDITIONING, "comments"], "conditioning");
  const b = batteryRaw || {};
  const c = conditioningRaw || {};
  return {
    comments: str(raw.comments),
    cell_efficiency: readPercent(raw.cell_efficiency, "cell_efficiency"),
    loss_factor: readFraction(raw.loss_factor, "loss_factor"),
    panels: {
      comments: sectionComments(raw.panels),
      items: namedItems(raw.panels).map(([name, p]) => {
        p = p || {};
        knownKeys(p, ["part", "normal", "area", "fill_ratio", "comments"], `panels › ${name}`);
        return {
          name, source: p.part != null ? "part" : "typed", part: str(p.part), normal: readNormal(p.normal),
          area: readQ(p.area, "m2", name), fill_ratio: readPercent(p.fill_ratio, `panels › ${name}`), comments: str(p.comments),
        };
      }),
    },
    self_shadowing: {
      present: Boolean(shadowRaw), enabled: Boolean(shadowRaw && shadowRaw.enabled),
      points: shadowRaw && shadowRaw.points != null ? shadowRaw.points : "", comments: shadowRaw ? str(shadowRaw.comments) : "",
    },
    battery: {
      present: Boolean(batteryRaw),
      capacity: readQ(b.capacity, "W h", "battery"), capacity_factor: readFraction(b.capacity_factor, "battery"),
      max_depth_of_discharge: readPercent(b.max_depth_of_discharge, "battery"), initial_charge: readPercent(b.initial_charge, "battery"),
      comments: str(b.comments),
    },
    conditioning: {
      present: Boolean(conditioningRaw),
      ...Object.fromEntries(CONDITIONING.map((key) => [key, readFraction(c[key], "conditioning")])),
      comments: str(c.comments),
    },
    system_margin: readPercent(raw.system_margin, "system_margin"),
  };
}

/** A power with no file yet: starting values only. */
const newPower = () => readPower({ cell_efficiency: "30 %", loss_factor: 0.8, panels: {} });

const FIXED_COLUMNS = ["equipment_id", "equipment_name", "subsystem", "units_on", "eqpt_margin", "comments"];

/** A power in watts, from text such as `10 W` or `0.5 kW`. */
function readWatts(value, where) {
  const quantity = readQ(value, "W", where);
  if (blank(quantity)) return "";
  const scale = { W: 1, kW: 1000, mW: 0.001 }[quantity.u];
  if (scale === undefined) { notice("changed", `${where}: "${value}" is not in W, and was left empty`); return ""; }
  return tidy(quantity.v * scale);
}

function readConsumption(file) {
  const header = (file.header || []).map((cell) => cell.trim());
  const modes = header.filter((cell) => cell && !FIXED_COLUMNS.includes(cell) && cell !== SLEW);
  const at = (row, name) => { const i = header.indexOf(name); return i < 0 ? "" : (row[i] ?? "").trim(); };
  const number = (text) => (text === "" || isNaN(Number(text)) ? text : Number(text));
  return {
    modes,
    slewColumn: header.includes(SLEW),
    rows: (file.rows || []).map((row, i) => {
      const where = `${file.name}, row ${i + 2}`;
      return {
        id: at(row, "equipment_id"), name: at(row, "equipment_name"), subsystem: at(row, "subsystem"),
        units: number(at(row, "units_on")), margin: number(at(row, "eqpt_margin")),
        power: Object.fromEntries(modes.map((mode) => [mode, readWatts(at(row, mode), where)])),
        slew: header.includes(SLEW) ? readWatts(at(row, SLEW), where) : "",
        comments: at(row, "comments"),
      };
    }),
  };
}

// ---------------------------------------------------------------- the project

/**
 * Each group's modes: the activities' first, then for the platform the park
 * angles', then `columns`, the consumption tables', by the group.
 */
function collectModes(scenario, columns) {
  const modes = Object.fromEntries(GROUPS.map((group) => [group, []]));
  const addMode = (group, mode) => mode && mode !== SLEW && !modes[group].includes(mode) && modes[group].push(mode);
  for (const group of GROUPS) scenario.activities.forEach((a) => addMode(group, a.mode[group]));
  scenario.model.articulations.items.forEach((a) => a.park.forEach((p) => addMode("platform", p.mode)));
  for (const group of GROUPS) columns[group].forEach((mode) => addMode(group, mode));
  return modes;
}

/** A consumption file with no rows, for a group whose folder has none. */
const noConsumption = () => ({ modes: [], slewColumn: false, rows: [] });

function readProject(data) {
  const files = data.files;
  const scenario = readingFile("scenario", () => readScenario(files.scenario.data));
  const consumption = Object.fromEntries(GROUPS.map((group) => {
    const file = files[consumptionKind(group)];
    return [group, file ? readingFile(consumptionKind(group), () => readConsumption(file)) : noConsumption()];
  }));
  scenario.modes = collectModes(scenario, { payload: consumption.payload.modes, platform: consumption.platform.modes });
  const byGroup = (value) => Object.fromEntries(GROUPS.map((group) => [group, value(group)]));
  return {
    name: data.folder || "quicksat_project",
    names: {
      scenario: files.scenario.name,
      power: files.power ? files.power.name : "power_system.yaml",
      ...Object.fromEntries(GROUPS.map((group) => {
        const file = files[consumptionKind(group)];
        return [consumptionKind(group), file ? file.name : `${group}_consumption.csv`];
      })),
    },
    scenario,
    hasPower: Boolean(files.power),
    power: files.power ? readingFile("power", () => readPower(files.power.data)) : newPower(),
    hasConsumption: byGroup((group) => Boolean(files[consumptionKind(group)])),
    slewColumn: byGroup((group) => consumption[group].slewColumn),
    consumption: byGroup((group) => consumption[group].rows),
  };
}

let project = readProject(DATA);

// The 3D model's bytes and part names, set when a GLB is decoded, and the orbit
// file's text, which the save writes back beside the scenario
const model = { fileName: "", bytes: null, parts: [], nodes: [] };
let orbitFile = DATA.orbit_file ? { name: DATA.orbit_file.name, text: DATA.orbit_file.text } : null;
// The satellite targets' files that the page holds, as text by name: each once,
// however many targets take an element set from it
const targetFiles = new Map(DATA.target_files.map((file) => [file.name, file.text]));

// What the page shows, beyond the frame's: the item selected in the 3D panel,
// and whether the panel is shown on each step and tab
Object.assign(state, { file: project.names.scenario, selection: null, show3d: {} });

let S = project.scenario;
let P = project.power;

// ---------------------------------------------------------------- names and their uses

const attitudeNames = () => S.attitudes.items.map((a) => a.name);
const targetNames = () => [...S.gnd_targets.items, ...S.sat_targets.items].map((t) => t.name);
/** The files that the satellite targets name, each once, in the order of the targets. */
const satTargetFiles = () => [...new Set(S.sat_targets.items.map((t) => t.file).filter(Boolean))];
/** The kind of a satellite target's file among the page's files: one kind for each file. */
const targetKind = (name) => `target:${name}`;
const directions = () => [...BUILT_IN_DIRECTIONS, ...targetNames()];
/** The modes a park angle can name: the platform's, and slew while the body turns, when there are slews. */
const parkModes = () => (S.slew.enabled ? [...S.modes.platform, SLEW] : S.modes.platform);
/** The kind of a group's mode, for its uses and its renames. */
const modeKind = (group) => `${group} mode`;

/** Where a name is used: a list of short descriptions. */
function usesOf(kind, name) {
  const uses = [];
  if (kind === "attitude") {
    S.activities.forEach((a, i) => a.attitude === name && uses.push(`activity ${i + 1}`));
  } else if (kind === "target") {
    S.attitudes.items.forEach((a) => [a.point[1], a.constrain[1], a.fallback].includes(name) && uses.push(`attitude ${a.name}`));
    S.model.articulations.items.forEach((a) => a.point[1] === name && uses.push(`articulation ${a.name}`));
    S.activities.forEach((a, i) => (["rise", "set"].includes(a.end.kind) && a.end.target === name) && uses.push(`activity ${i + 1}`));
  } else if (GROUPS.some((group) => kind === modeKind(group))) {
    const group = GROUPS.find((g) => kind === modeKind(g));
    S.activities.forEach((a, i) => a.mode[group] === name && uses.push(`activity ${i + 1}`));
    if (group === "platform") {
      S.model.articulations.items.forEach((r) => r.park.some((p) => p.mode === name) && uses.push(`articulation ${r.name}`));
    }
    if (project.hasConsumption[group]) uses.push(`a column of the ${group}'s consumption table`);
  }
  return uses;
}

/** Rename an item, and every field that names it. */
function rename(kind, from, to) {
  if (kind === "attitude") {
    S.activities.forEach((a) => a.attitude === from && (a.attitude = to));
  } else if (kind === "target") {
    // a satellite target that takes its element set by its own name keeps it, by the old name
    const satellite = S.sat_targets.items.find((t) => t.name === from);
    if (satellite && !satellite.object && (heldSets(satellite.file) || []).length > 1) satellite.object = from;
    S.attitudes.items.forEach((a) => {
      if (a.point[1] === from) a.point[1] = to;
      if (a.constrain[1] === from) a.constrain[1] = to;
      if (a.fallback === from) a.fallback = to;
    });
    S.model.articulations.items.forEach((a) => a.point[1] === from && (a.point[1] = to));
    S.activities.forEach((a) => a.end.target === from && (a.end.target = to));
  } else if (GROUPS.some((group) => kind === modeKind(group))) {
    const group = GROUPS.find((g) => kind === modeKind(g));
    S.activities.forEach((a) => a.mode[group] === from && (a.mode[group] = to));
    if (group === "platform") S.model.articulations.items.forEach((r) => r.park.forEach((p) => p.mode === from && (p.mode = to)));
    project.consumption[group].forEach((row) => {
      row.power[to] = row.power[from];
      delete row.power[from];
    });
  }
}
