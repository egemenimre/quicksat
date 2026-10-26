// quicksat scenario editor: the sections, each one block of a file.
//
// The Setup steps and the theme tabs both draw these, so each field is built once.
// Their explanations are in quicksat/editor/help/scenario.yaml and power.yaml.

function partOptions() {
  return model.parts.map((p) => [p.name, p.name + (p.count > 1 ? ` (${p.count} nodes)` : "")]);
}

// ---------------------------------------------------------------- places and copies

// OpenStreetMap's Nominatim search. Its usage policy allows at most one request a
// second, and no search as the user types, so a search runs on Enter or the button.
// The answers are kept, so the same text is asked only once.
const NOMINATIM = "https://nominatim.openstreetmap.org/search";
const placeAnswers = new Map();
let lastSearch = 0;

/** The places Nominatim finds for a text, at most 8: name, where, latitude, longitude. */
async function findPlaces(text) {
  if (placeAnswers.has(text)) return placeAnswers.get(text);
  const wait = lastSearch + 1000 - Date.now();
  if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  lastSearch = Date.now();
  const url = `${NOMINATIM}?${new URLSearchParams({ q: text, format: "jsonv2", limit: "8" })}`;
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Nominatim answered ${response.status}`);
  const places = (await response.json()).map((found) => ({
    name: found.name || found.display_name.split(",")[0],
    where: found.display_name,
    latitude: Number(found.lat),
    longitude: Number(found.lon),
  }));
  placeAnswers.set(text, places);
  return places;
}

/** A search box that adds a place found by Nominatim as a target. */
function placeSearch(list) {
  const results = el("div", { class: "search-results" });
  const input = el("input", { type: "search", class: "wide", placeholder: "Search a place, an address or a station",
    onkeydown: (event) => { if (event.key === "Enter") search(); } });
  const button = el("button", { class: "btn", text: "search", onclick: () => search() });
  async function search() {
    const text = input.value.trim();
    results.replaceChildren();
    if (!text) return;
    button.disabled = true;
    results.append(el("div", { class: "hint", text: "Searching…" }));
    try {
      const places = await findPlaces(text);
      results.replaceChildren();
      if (!places.length) results.append(el("div", { class: "hint", text: "Nominatim found no place of that name." }));
      for (const place of places) {
        results.append(el("button", { onclick: () => add(place) },
          el("b", { text: place.name }),
          el("small", { text: `  ${place.where} · ${place.latitude.toFixed(4)}°, ${place.longitude.toFixed(4)}°` })));
      }
    } catch (error) {
      results.replaceChildren(el("div", { class: "hint", text: `The search needs a connection to nominatim.openstreetmap.org (${error.message}). You can still type a target's position.` }));
    } finally {
      button.disabled = false;
    }
  }
  function add(place) {
    let name = place.name;
    for (let n = 2; list.some((target) => target.name === name); n++) name = `${place.name} ${n}`;
    list.push({ name, latitude: q(place.latitude, "deg"), longitude: q(place.longitude, "deg"), altitude: q("", "m"), min_elevation: q("", "deg"), comments: "" });
    input.value = "";
    results.replaceChildren();
    changed(true);
  }
  const credit = el("span", { class: "hint" },
    "Search by OpenStreetMap's Nominatim, online only. Data © ",
    el("a", { href: "https://www.openstreetmap.org/copyright", target: "_blank", rel: "noopener", text: "OpenStreetMap contributors" }),
    ". No altitude is given, so it is 0 m unless you set it.");
  return el("div", { class: "search" }, el("div", { class: "ctl" }, input, button, credit), results);
}

// ---------------------------------------------------------------- satellite targets

/** The files a satellite target can name, for the file pickers. */
const TARGET_FILE_TYPES = ".tle,.txt,.omm,.kvn,.xml,.json,.csv,.ecsv,.oem";

/** The element sets of each held file, by its name, read once for each text. */
const setsRead = new Map();

/** The element sets of a held satellite target's file, or null for a trajectory, a file not held, or text that does not read. */
function heldSets(name) {
  if (!targetFiles.has(name)) return null;
  const text = targetFiles.get(name);
  const read = setsRead.get(name);
  if (read && read.text === text) return read.sets;
  const sets = elementSets(name, text);
  setsRead.set(name, { text, sets });
  return sets;
}

/**
 * An epoch's distance from the start of the run, as text, and whether it is
 * more than 7 days from either end. A duration in orbits has no end on the
 * page, so the start alone counts then. The run checks both ends.
 */
function epochNote(epoch) {
  const start = Date.parse(`${S.start}Z`);
  const at = Date.parse(`${epoch}Z`);
  if (Number.isNaN(start) || Number.isNaN(at)) return [epoch, false];
  const unit = { s: 1, min: 60, h: 3600, d: 86400 }[S.duration.u];
  const end = unit && S.duration.v > 0 ? start + S.duration.v * unit * 1000 : start;
  const days = (ms) => Math.abs(ms) / 86400000;
  const far = Math.max(days(at - start), days(at - end)) > 7;
  return [`${days(at - start).toFixed(1)} d ${at < start ? "before" : "after"} the start`, far];
}

/** Add a satellite target, with a name of its own: the file's name for it, or that name and a number. */
function addSatTarget(name, source, file, object) {
  let unique = name;
  for (let n = 2; targetNames().includes(unique); n++) unique = `${name} ${n}`;
  // a target that cannot take its name from the file names its element set
  S.sat_targets.items.push({ name: unique, source, file, object: unique === name ? object : object || name, min_clearance: q("", "km"), comments: "" });
}

/** A file of several satellites, just added, whose satellites the step offers to add. */
let targetChoice = null;

/** Hold a satellite target's file, and add its satellite, or offer its satellites when it holds several. */
async function addTargetFile(file) {
  const text = await file.text();
  const kind = orbitFileKind(file.name, text);
  const sets = kind === "trajectory" ? null : elementSets(file.name, text);
  if (kind !== "trajectory" && !sets) {
    alert(`${file.name} does not read as a TLE file, an OMM file or a trajectory file.`);
    return;
  }
  targetFiles.set(file.name, text);
  sources[targetKind(file.name)] = { how: "file" };
  const stem = file.name.replace(/\.[^.]+$/, "");
  if (kind === "trajectory") addSatTarget(stem, kind, file.name, "");
  else if (sets.length === 1) addSatTarget(sets[0].name || stem, kind, file.name, "");
  else targetChoice = { name: file.name, kind, sets, chosen: new Set() };
  changed(true);
}

/** The satellites of a file just added, to choose from, with those already added marked. */
function targetChooser() {
  const choice = targetChoice;
  const added = new Set(S.sat_targets.items.filter((t) => t.file === choice.name).map((t) => pickedElementSet(choice.sets, t.object, t.name).set));
  const add = (indices) => {
    for (const i of indices) {
      const set = choice.sets[i];
      addSatTarget(set.name || `satellite ${set.number}`, choice.kind, choice.name, set.name ? "" : String(set.number));
    }
    targetChoice = null;
    changed(true);
  };
  const free = choice.sets.map((_, i) => i).filter((i) => !added.has(choice.sets[i]));
  return el("div", { class: "target-choice" },
    el("p", { class: "hint", text: `${choice.name} holds ${choice.sets.length} satellites. Choose the ones to add as targets. Each takes its name from the file.` }),
    el("div", { class: "choices" }, ...choice.sets.map((set, i) => el("label", { class: added.has(set) ? "added" : "" },
      el("input", {
        type: "checkbox", checked: choice.chosen.has(i), disabled: added.has(set),
        onchange: (e) => (e.target.checked ? choice.chosen.add(i) : choice.chosen.delete(i)),
      }),
      elementSetLabel(set),
      el("small", { text: added.has(set) ? " · added" : ` · epoch ${set.epoch ? set.epoch.slice(0, 10) : "unknown"}` })))),
    el("div", { class: "ctl" },
      el("button", { class: "btn primary", text: "add the chosen", onclick: () => add([...choice.chosen]) }),
      el("button", { class: "btn", text: `add all ${free.length}`, disabled: !free.length, onclick: () => add(free) }),
      el("button", { class: "btn", text: "cancel", onclick: () => { targetChoice = null; changed(true); } })));
}

/** The area that adds satellite targets from a file: its button, or a drop. */
function targetFileArea() {
  const input = el("input", {
    type: "file", accept: TARGET_FILE_TYPES, multiple: true, hidden: true,
    onchange: async (e) => {
      for (const file of e.target.files) await addTargetFile(file);
      e.target.value = "";
    },
  });
  const area = el("div", { class: "open-row drop-area" },
    el("label", { class: "btn primary" }, "Add from a file…", input),
    el("span", { class: "hint" }, "A TLE or OMM file with one satellite or a group of them, or a trajectory file.", el("br"), "Or drop the file here."));
  area.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.stopPropagation();
    area.classList.add("drag-over");
  });
  area.addEventListener("dragleave", (event) => {
    if (!area.contains(event.relatedTarget)) area.classList.remove("drag-over");
  });
  area.addEventListener("drop", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    area.classList.remove("drag-over");
    let dropped;
    try {
      dropped = await droppedFiles(event.dataTransfer);
    } catch (error) {
      alert(error.message);
      return;
    }
    if (dropped.isFolder) { alert("Drop a file here. A folder goes on the first Setup step."); return; }
    for (const { file } of dropped.files) await addTargetFile(file);
  });
  return el("div", {}, area, targetChoice && targetFiles.has(targetChoice.name) ? targetChooser() : null);
}

/** A satellite target's file: its kind, its name, and a button to choose it. */
function targetFileCell(item) {
  const held = targetFiles.has(item.file);
  return el("span", { class: "ctl" },
    selectInput(item, "source", [["tle", "TLE"], ["omm", "OMM"], ["trajectory", "trajectory"]], { onchange: () => item.source === "trajectory" && (item.object = "") }),
    textInput(item, "file", { placeholder: "a file", onchange: (value) => { item.file = value.trim(); changed(true); } }),
    el("label", { class: "btn small" }, "choose…", el("input", {
      type: "file", accept: TARGET_FILE_TYPES, hidden: true,
      onchange: async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const text = await file.text();
        targetFiles.set(file.name, text);
        sources[targetKind(file.name)] = { how: "file" };
        Object.assign(item, { file: file.name, source: orbitFileKind(file.name, text) });
        if (item.source === "trajectory") item.object = "";
        changed(true);
      },
    })),
    item.file && !held ? el("span", { class: "hint", text: "not held" }) : null);
}

/** Which satellite a target takes: a list of the file's satellites when it holds several, and a box otherwise. */
function objectCell(item) {
  if (item.source === "trajectory") return el("span", { class: "hint", text: "the file's only one" });
  const sets = heldSets(item.file);
  if (sets && sets.length > 1) {
    const names = sets.map((set) => set.name);
    const options = sets.map((set) => [set.name && names.indexOf(set.name) === names.lastIndexOf(set.name) ? set.name : String(set.number), elementSetLabel(set)]);
    return selectInput(item, "object", options, { blank: "by the target's name", onchange: () => {} });
  }
  return textInput(item, "object", { placeholder: sets ? "the only one" : "a name or a number" });
}

/** The epoch of the element set a target takes, and how far it is from the run, or what is wrong. */
function epochCell(item) {
  if (item.source === "trajectory") return el("span", { class: "hint", text: "checked when the run starts" });
  const sets = heldSets(item.file);
  if (!sets) return el("span", { class: "hint", text: targetFiles.has(item.file) ? "the file does not read" : "—" });
  const picked = pickedElementSet(sets, item.object, item.name);
  if (!picked.set) return el("span", { class: "bad", text: picked.problem });
  const [text, far] = epochNote(picked.set.epoch);
  return el("span", { class: far ? "warn nowrap" : "nowrap", text, title: `${elementSetLabel(picked.set)}, epoch ${picked.set.epoch.replace("T", " ")} UTC` });
}

/** The comments on the overall power subsystem, which head the Power pages. */
function powerComments() {
  if (!project.hasPower) return null;
  return el("div", { class: "overall" }, commentsBox(P, "Your comments on the overall power subsystem", {
    open: true,
    note: `Also for the cell efficiency, the loss factor and the system margin, which have no block of their own. They go in the comments field at the top of ${project.names.power}.`,
  }));
}

/** A copy of an equipment row of a group's table, with an id of its own. */
function copyEquipment(group, row) {
  let id = `${row.id}_2`;
  for (let n = 3; project.consumption[group].some((r) => r.id === id); n++) id = `${row.id}_${n}`;
  return { ...row, id, power: { ...row.power } };
}

/** For a folder with no power system file: say so, and offer to start one. */
function noPower(body) {
  body.append(el("p", { class: "hint", text: `This folder has no ${project.names.power}, as a scenario folder has none. Start one to size the power from this scenario.` }),
    el("button", { class: "btn", text: `add ${project.names.power}`, onclick: addPower }));
}

/** Start a power system file, for a scenario folder that has none. */
function addPower() {
  project.hasPower = true;
  fileAdded("power");
  changed(true);
}

/** Start a group's consumption file, for a folder that has none. */
function addConsumption(group) {
  project.hasConsumption[group] = true;
  fileAdded(consumptionKind(group));
  changed(true);
}

/** For a folder with no thermal file: say so, and offer to start one. */
function noThermal(body) {
  body.append(el("p", { class: "hint", text: `This folder has no ${project.names.payload_thermal}. Start one to sum the payload's heat over the run, and size its radiators and heaters. The folder sizes power only without it.` }),
    el("button", { class: "btn", text: `add ${project.names.payload_thermal}`, onclick: addThermal }));
}

/** Start the payload's thermal file, for a folder that has none. */
function addThermal() {
  project.hasThermal = true;
  fileAdded("payload_thermal");
  changed(true);
}

/** Whether the payload's consumption table shows its `thermal` column: with the thermal file, or when the file has the column. */
const showsThermalColumn = (group) => group === "payload" && (project.hasThermal || project.thermalColumn.payload);

/**
 * The modes a row of a group's consumption table needs: each of the group's
 * modes, and for the platform slew while the body turns. A slew column that
 * the file already has stays.
 */
const consumptionModes = (group) =>
  (group === "platform" && S.slew.enabled) || project.slewColumn[group] ? [...S.modes[group], SLEW] : S.modes[group];

/** The Modes step's table of one group's modes. */
function modesTable(group) {
  const modes = S.modes[group];
  const kind = modeKind(group);
  const table = el("table", { class: "items" });
  table.append(el("tr", {}, [`${group} mode`, "used by", ""].map((h) => el("th", { text: h }))));
  modes.forEach((name, index) => {
    const uses = usesOf(kind, name).filter((u) => !u.startsWith("a column"));
    const input = el("input", {
      type: "text", class: "name", value: name,
      onchange: (e) => {
        const to = e.target.value.trim();
        if (!to || to === name) { e.target.value = name; return; }
        if (modes.includes(to)) { e.target.value = name; alert(`There is already a ${group} mode called "${to}".`); return; }
        rename(kind, name, to);
        modes[index] = to;
        changed(true);
      },
    });
    table.append(el("tr", {},
      el("td", {}, input),
      el("td", { class: "hint", text: uses.length ? uses.join(", ") : "nothing yet" }),
      el("td", { class: "tools" }, itemTools(modes, index, { kind, name }))));
  });
  const add = el("div", { class: "add-row" }, el("button", {
    class: "btn", text: `+ ${group} mode`,
    onclick: () => {
      let name = "new mode";
      for (let n = 2; modes.includes(name); n++) name = `new mode ${n}`;
      modes.push(name);
      project.consumption[group].forEach((r) => (r.power[name] = ""));
      if (group === "payload") addFlowMode(T, name);
      changed(true);
    },
  }));
  return [el("h4", { text: `${groupTitle(group)} modes` }), table, add];
}

/** A group's consumption section: its table of equipment, or a button to start one. */
function consumptionSection(group) {
  const kind = consumptionKind(group);
  return {
    title: `${groupTitle(group)} consumption`, file: kind, wide: true,
    render(body) {
      if (!project.hasConsumption[group]) {
        body.append(el("p", { class: "hint", text: `This folder has no ${project.names[kind]}. Start one to give what each of the ${group}'s equipment draws in each of its modes.` }),
          el("button", { class: "btn", text: `add ${project.names[kind]}`, onclick: () => addConsumption(group) }));
        return;
      }
      const rows = project.consumption[group];
      const modes = consumptionModes(group);
      const thermalColumn = showsThermalColumn(group);
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["id", "name", "subsystem", "units on", "margin %", ...modes.map((m) => `${m} W`), "comments", ...(thermalColumn ? ["heat goes"] : []), ""].map((h) => el("th", { text: h }))));
      rows.forEach((item, index) => {
        const tr = el("tr");
        const power = (m) => (m === SLEW ? numberInput(item, "slew", { min: 0, width: 60 }) : numberInput(item.power, m, { min: 0, width: 60 }));
        tr.append(
          el("td", {}, textInput(item, "id", { cls: "name" })),
          el("td", {}, textInput(item, "name")),
          el("td", {}, textInput(item, "subsystem", { cls: "name" })),
          el("td", {}, numberInput(item, "units", { step: 1, min: 0, width: 55 })),
          el("td", {}, numberInput(item, "margin", { step: 1, min: 0, width: 55 })),
          ...modes.map((m) => el("td", {}, power(m))),
          el("td", {}, textInput(item, "comments", { cls: "wide" })),
          ...(thermalColumn ? [el("td", {}, selectInput(item, "thermal", THERMAL_VALUES, { blank: "choose" }))] : []),
          el("td", { class: "tools" }, itemTools(rows, index, { copy: (row) => copyEquipment(group, row) })));
        table.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ equipment",
        onclick: () => { rows.push({ id: "", name: "", subsystem: "", units: 1, margin: 5, power: Object.fromEntries(S.modes[group].map((m) => [m, ""])), slew: "", comments: "", thermal: "" }); changed(true); },
      })));
      const slew = group === "platform"
        ? ", and a slew column when the scenario has slews"
        : ". In a slew, the payload stays in one of its own modes, so it needs no slew column";
      body.append(el("p", { class: "hint", text: `One column per ${group} mode, from the Modes step${slew}. Every cell needs a power, 0 W included. The comments column is the CSV's own place for comments, and is kept as written.` }));
      if (thermalColumn) {
        body.append(el("p", { class: "hint", text: "Where each row's heat goes, for the payload's heat account: all of it inside the payload's MLI, outside it, or the heater row, which holds all the payload's heater lines together. One row at most is the heater row." }));
      }
    },
  };
}

// ---------------------------------------------------------------- sections

/** A time of day 12 h later, such as `01:30` for `13:30`, or the text as it is if it is not a time. */
function twelveHoursOn(time) {
  const match = /^(\d{1,2}):(\d{2})/.exec(time);
  if (!match) return time;
  return `${String((Number(match[1]) + 12) % 24).padStart(2, "0")}:${match[2]}${time.slice(match[0].length)}`;
}

/** The hint by the node time: which node it is, and the other node's time, 12 h away. */
function otherNodeText(sso) {
  const which = sso.node === "ltan" ? "ascending" : "descending";
  if (twelveHoursOn(sso.time) === sso.time) return `local time of the ${which} node`;
  return `local time of the ${which} node: the same orbit as ${sso.node === "ltan" ? "LTDN" : "LTAN"} ${twelveHoursOn(sso.time)}`;
}

/** The choice of node. Switching keeps the orbit: the time moves 12 h, to the other node's. */
function nodeChoice(sso) {
  const node = el("div", { class: "radio-row" });
  for (const [value, label] of [["ltan", "ascending (LTAN)"], ["ltdn", "descending (LTDN)"]]) {
    node.append(el("label", { class: sso.node === value ? "on" : "" },
      el("input", {
        type: "radio", checked: sso.node === value,
        onchange: () => { sso.time = twelveHoursOn(sso.time); sso.node = value; changed(true); },
      }),
      label));
  }
  return node;
}

const SECTIONS = {
  project: {
    title: "Folder", file: "all files",
    render(body) {
      body.append(openFolderButton());
      const targetRows = satTargetFiles().filter((name) => targetFiles.has(name)).map((name) => ({ kind: targetKind(name) }));
      const adds = { power: addPower, ...Object.fromEntries(GROUPS.map((group) => [consumptionKind(group), () => addConsumption(group)])), payload_thermal: addThermal };
      body.append(filesTable([{ rows: [...FILES.map(({ kind }) => ({ kind, add: adds[kind] })), ...targetRows] }]));
      body.append(commentsBox(S, "Your comments on the overall scenario", { open: true, note: `They go in the comments field at the top of ${project.names.scenario}. The comments on the overall power subsystem are in the Power steps.` }));
    },
  },

  orbit: {
    title: "Orbit", file: "scenario",
    render(body) {
      const o = S.orbit;
      const g = grid(body);
      row(g, "Where it comes from", radioRow(o, "source", [["sso", "sun-synchronous"], ["tle", "TLE file"], ["omm", "OMM file"], ["trajectory", "trajectory file"]]));
      if (o.source === "sso") {
        row(g, "Altitude", quantityInput(o.sso, "altitude", ["km"]), "averaged over one orbit");
        row(g, "Node", nodeChoice(o.sso), "switching keeps the orbit");
        const other = el("span", { class: "hint" });
        const showOther = () => { other.textContent = otherNodeText(o.sso); };
        row(g, o.sso.node.toUpperCase(), el("span", { class: "ctl" },
          el("input", { type: "time", value: o.sso.time, oninput: (e) => { o.sso.time = e.target.value; showOther(); changed(); } }),
          other));
        showOther();
      } else {
        const key = { tle: "tle_file", omm: "omm_file", trajectory: "trajectory_file" }[o.source];
        const accept = { tle: ".tle,.txt", omm: ".omm,.kvn,.xml,.json,.csv", trajectory: ".ecsv,.oem,.kvn" }[o.source];
        const held = orbitFile && orbitFile.name === o[key];
        row(g, "File", el("span", { class: "ctl" },
          textInput(o, key, { cls: "wide", placeholder: "a path, from this file's folder" }),
          el("label", { class: "btn small" }, "choose…", el("input", {
            type: "file", accept, hidden: true,
            onchange: async (e) => {
              const file = e.target.files[0];
              if (!file) return;
              o[key] = file.name;
              orbitFile = { name: file.name, text: await file.text() };
              sources.orbit = { how: "file" };
              changed(true);
            },
          }))), held ? "saved with the other files" : "not held by this page: keep it beside the scenario file");
      }
      body.append(commentsBox(o));
    },
  },

  time: {
    title: "Start, duration and step", file: "scenario",
    render(body) {
      const g = grid(body);
      row(g, "Start", el("span", { class: "ctl" },
        el("input", { type: "datetime-local", step: 1, value: S.start, oninput: (e) => { S.start = e.target.value; changed(); } }),
        el("span", { class: "unit", text: "UTC" })));
      row(g, "Duration", quantityInput(S, "duration", ["orbits", "min", "h", "d"]), "orbits or a time");
      row(g, "Time step", quantityInput(S, "step", ["s", "min"], { placeholder: "10" }), "10 s if left out");
      body.append(commentsBox(S, "Your comments on the overall scenario", { note: `Also for the start, duration and step, which have no block of their own. They go in the comments field at the top of ${project.names.scenario}.` }));
    },
  },

  model: {
    title: "3D model", file: "scenario",
    render(body) {
      const m = S.model;
      const g = grid(body);
      row(g, "Model file", el("span", { class: "ctl" },
        el("span", { text: m.file || "none: quicksat draws a plain 1 m cube" }),
        el("label", { class: "btn small" }, "choose GLB…", el("input", { type: "file", accept: ".glb", hidden: true, onchange: (e) => loadGlbFile(e.target.files[0]) })),
        m.file ? el("button", { class: "btn small danger", text: "use no model", onclick: () => { m.file = ""; changed(true); } }) : null));
      if (m.file && !model.bytes) row(g, "", el("span", { class: "hint", text: "This page does not hold the file, so it cannot show it or save it. Choose it to see its parts." }));
      row(g, "Parts found", el("span", { text: model.parts.length ? `${model.parts.length} named parts. Click one in the 3D panel to see it.` : "none" }));
      body.append(commentsBox(m));
    },
  },

  articulations: {
    title: "Articulations", file: "scenario",
    render(body) {
      const list = S.model.articulations.items;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "part"].map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        // The second line: how it turns, what it points at, where it parks and how far it turns
        const label = (text) => el("span", { class: "hint", text });
        const turns = el("span", { class: "ctl" }, label("turns about"), selectInput(item, "axis", AXES));
        const points = el("span", { class: "ctl" },
          label("points"), selectInput({ v: item.point[0] }, "v", AXES, { onchange: (v) => { item.point[0] = v; } }),
          label("at"), selectInput({ v: item.point[1] }, "v", directions(), { onchange: (v) => { item.point[1] = v; } }));
        const park = el("span", { class: "ctl wrap" }, label("parks in"));
        item.park.forEach((p, i) => park.append(el("span", { class: "ctl" },
          selectInput(p, "mode", parkModes(), { blank: "mode" }),
          quantityInput(p, "angle", ["deg"]),
          el("button", { class: "btn small danger", text: "×", onclick: () => { item.park.splice(i, 1); changed(true); } }))));
        park.append(el("button", { class: "btn small", text: "+ park", onclick: () => { item.park.push({ mode: "", angle: q(0, "deg") }); changed(true); } }));
        const range = el("span", { class: "ctl" }, label("turns within"));
        if (item.range) {
          range.append(quantityInput(item.range, "min", ["deg"]), " to ", quantityInput(item.range, "max", ["deg"]),
            el("button", { class: "btn small danger", text: "×", onclick: () => { item.range = null; changed(true); } }));
        } else {
          range.append(label("a full turn"), el("button", { class: "btn small", text: "limit…", onclick: () => { item.range = { min: q(-90, "deg"), max: q(90, "deg") }; changed(true); } }));
        }
        const tools = el("span", { class: "tools push" });
        const second = selectable(el("tr", { class: "second" }), { kind: "articulation", item });
        second.append(el("td", { colspan: 2 }, el("span", { class: "ctl wrap gap" }, turns, points, park, range, tools)));
        const first = selectable(el("tr", { class: "first" }), { kind: "articulation", item });
        first.append(
          el("td", {}, nameInput(item, null, () => list.map((a) => a.name))),
          el("td", {}, selectInput(item, "part", partOptions(), { blank: "choose a part", cls: "wide" })));
        tools.append(commentsButton(item, 2, tbody, second), " ", itemTools(list, index));
        tbody.append(first, second);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ articulation",
        onclick: () => { list.push({ name: `articulation ${list.length + 1}`, part: "", axis: "+y", point: ["-z", "sun"], park: [], range: null, comments: "" }); changed(true); },
      })));
      body.append(commentsBox(S.model.articulations, "Your comments on all the articulations"));
    },
  },

  gnd_targets: {
    title: "Ground targets", file: "scenario",
    render(body) {
      const list = S.gnd_targets.items;
      body.append(placeSearch(list));
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "latitude", "longitude", "altitude", "min elevation", ""].map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        const tr = selectable(el("tr"), { kind: "target", item });
        tr.append(
          el("td", {}, nameInput(item, "target", targetNames)),
          el("td", {}, quantityInput(item, "latitude", ["deg"])),
          el("td", {}, quantityInput(item, "longitude", ["deg"])),
          el("td", {}, quantityInput(item, "altitude", ["m", "km"], { placeholder: "0" })),
          el("td", {}, quantityInput(item, "min_elevation", ["deg"], { placeholder: "5" })),
          el("td", { class: "tools" }, commentsButton(item, 6, tbody, tr), " ", itemTools(list, index, { kind: "target", name: item.name })));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ target",
        onclick: () => { list.push({ name: `target ${list.length + 1}`, latitude: q(0, "deg"), longitude: q(0, "deg"), altitude: q("", "m"), min_elevation: q("", "deg"), comments: "" }); changed(true); },
      })));
      body.append(commentsBox(S.gnd_targets, "Your comments on all the targets"));
    },
  },

  sat_targets: {
    title: "Satellite targets", file: "scenario",
    render(body) {
      const list = S.sat_targets.items;
      body.append(targetFileArea());
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "file", "satellite", "min clearance", "epoch", ""].map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        const tr = selectable(el("tr"), { kind: "target", item });
        tr.append(
          el("td", {}, nameInput(item, "target", targetNames)),
          el("td", {}, targetFileCell(item)),
          el("td", {}, objectCell(item)),
          el("td", {}, quantityInput(item, "min_clearance", ["km"], { placeholder: "100" })),
          el("td", {}, epochCell(item)),
          el("td", { class: "tools" }, commentsButton(item, 6, tbody, tr), " ", itemTools(list, index, { kind: "target", name: item.name })));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(commentsBox(S.sat_targets, "Your comments on all the satellite targets"));
    },
  },

  attitudes: {
    title: "Attitudes", file: "scenario",
    render(body) {
      const list = S.attitudes.items;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "axis", "points at", "axis", "turns toward", "fallback", "offset", ""].map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        const tr = selectable(el("tr"), { kind: "attitude", item });
        const pair = (arr) => [
          el("td", {}, selectInput({ v: arr[0] }, "v", AXES, { onchange: (v) => { arr[0] = v; } })),
          el("td", {}, selectInput({ v: arr[1] }, "v", directions(), { onchange: (v) => { arr[1] = v; } })),
        ];
        tr.append(
          el("td", {}, nameInput(item, "attitude", attitudeNames)),
          ...pair(item.point),
          ...pair(item.constrain),
          el("td", {}, selectInput(item, "fallback", directions(), { blank: "default" })),
          el("td", {}, textInput(item, "offset", { placeholder: "such as x 30 deg" })),
          el("td", { class: "tools" }, commentsButton(item, 8, tbody, tr), " ", itemTools(list, index, { kind: "attitude", name: item.name })));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ attitude",
        onclick: () => { list.push({ name: `attitude ${list.length + 1}`, point: ["+z", "nadir"], constrain: ["-y", "orbit normal"], fallback: "", offset: "", comments: "" }); changed(true); },
      })));
      body.append(commentsBox(S.attitudes, "Your comments on all the attitudes"));
    },
  },

  slew: {
    title: "Attitude slew performance", file: "scenario",
    render(body) {
      const s = S.slew;
      const g = grid(body);
      row(g, "Slews", checkbox(s, "enabled", "turn between attitudes at a finite rate", { structure: true }), "off: instant changes");
      if (s.enabled) {
        row(g, "Fastest rate", quantityInput(s, "max_rate", ["deg/s"]), "rate, acceleration, or both");
        row(g, "Acceleration", quantityInput(s, "max_acceleration", ["deg/s2"]));
        row(g, "Settling time", quantityInput(s, "settling_time", ["s"], { placeholder: "0" }), "0 s if left out");
      }
      body.append(commentsBox(s));
    },
  },

  modes: {
    title: "Modes", file: "scenario", also: "and the consumption tables",
    render(body) {
      for (const group of GROUPS) body.append(...modesTable(group));
      body.append(el("p", { class: "hint", text: "The modes are not a block of the scenario file: they are the names the activities use. So they take no comments here. Describe a mode in the comments of the activities that use it, or in its consumption table." }));
    },
  },

  activities: {
    title: "Activities", file: "scenario", wide: true,
    render(body, { setup = false } = {}) {
      const list = S.activities;
      const table = el("table", { class: "items activities" });
      // with slews, the payload's mode in the turn into each activity
      const slews = S.slew.enabled;
      const headers = ["#", "title", "ends at", "", "attitude", "payload mode", "platform mode", ...(slews ? ["payload in slew"] : []), "expects", ""];
      table.append(el("tr", {}, headers.map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        const tr = selectable(el("tr"), { kind: "activity", item });
        const end = item.end;
        const text = el("div", { class: "trigger-text", text: triggerText(end), title: "The trigger as the scenario file writes it" });
        const refresh = () => { text.textContent = triggerText(end); };
        const detail = el("span", { class: "ctl" });
        if (end.kind === "duration") detail.append(quantityInput(end, "value", TIME_UNITS));
        if (end.kind === "latitude") detail.append(quantityInput(end, "latitude", ["deg"]), selectInput(end, "direction", ["either", "ascending", "descending"]));
        if (end.kind === "rise" || end.kind === "set") detail.append(selectInput(end, "target", targetNames(), { blank: "target" }));
        if (end.kind === "text") detail.append(textInput(end, "text", { cls: "wide", placeholder: "a trigger, as the file writes it" }));
        if (!["duration", "text"].includes(end.kind)) {
          detail.append(selectInput(end.offset, "sign", ["+", "-"]),
            el("input", { type: "number", step: "any", min: 0, value: end.offset.v, placeholder: "0", style: "width:55px", oninput: (e) => { end.offset.v = e.target.value === "" ? "" : Number(e.target.value); refresh(); changed(); } }),
            selectInput(end.offset, "u", TIME_UNITS));
        }
        detail.addEventListener("input", refresh);
        detail.addEventListener("change", refresh);
        // the activity before, in a repeated list the last for the first: the
        // same attitude means no turn into this one, so the choice does nothing
        const before = list[(index + list.length - 1) % list.length];
        const unturned = list.length > 1 && before.attitude === item.attitude;
        const inSlew = slews ? selectInput(item.mode, "in_slew", IN_SLEW_CHOICES) : null;
        if (inSlew && unturned) Object.assign(inSlew, { disabled: true, title: "The activity before has the same attitude, so there is no turn into this one" });
        tr.append(
          el("td", { class: "hint num", text: index + 1 }),
          // on the Activities tab, the activity's results in the designer's last run
          el("td", {}, textInput(item, "title", { cls: "name", placeholder: "what it is for" }), setup ? null : rowNote(index)),
          el("td", {}, selectInput(end, "kind", TRIGGERS, { onchange: () => {} })),
          el("td", {}, detail, text),
          // a new attitude can turn the next row's slew on or off, so the table is drawn again
          el("td", {}, selectInput(item, "attitude", attitudeNames(), { blank: "attitude", onchange: () => {} })),
          ...GROUPS.map((group) => el("td", {}, selectInput(item.mode, group, S.modes[group], { blank: group }))),
          ...(slews ? [el("td", {}, inSlew)] : []),
          el("td", {}, selectInput(item, "constraint", CONSTRAINTS.map((c) => [c, c || "anything"]))),
          el("td", { class: "tools" }, commentsButton(item, headers.length, tbody, tr), " ", itemTools(list, index, { order: true })));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ activity",
        onclick: () => { list.push({ title: `activity ${list.length + 1}`, end: trigger("duration"), attitude: attitudeNames()[0] || "", mode: { payload: S.modes.payload[0] || "", platform: S.modes.platform[0] || "", in_slew: PREV_ACTIVITY }, constraint: "", comments: "" }); changed(true); },
      })));
      body.append(el("p", { class: "hint", text: "The activities are a list, which has no place for a comments field of its own. Use each activity's comments, or the comments at the top of the file." }));
    },
  },

  panels: {
    title: "Solar panels", file: "power",
    render(body) {
      if (!project.hasPower) return noPower(body);
      const list = P.panels.items;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "from", "part, or normal and area", "fill ratio", ""].map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        const tr = selectable(el("tr"), { kind: "panel", item });
        const where = item.source === "part"
          ? selectInput(item, "part", partOptions(), { blank: "choose a part", cls: "wide" })
          : el("span", { class: "ctl" }, textInput(item, "normal", { placeholder: "+x, or 0, 1, -1" }), quantityInput(item, "area", ["m2"]));
        tr.append(
          el("td", {}, nameInput(item, null, () => list.map((p) => p.name))),
          el("td", {}, selectInput(item, "source", [["part", "the model"], ["typed", "typed in"]], { onchange: () => {} })),
          el("td", {}, where),
          el("td", {}, quantityInput(item, "fill_ratio", ["%"])),
          el("td", { class: "tools" }, commentsButton(item, 5, tbody, tr), " ", itemTools(list, index)));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ panel",
        onclick: () => { list.push({ name: `panel ${list.length + 1}`, source: model.parts.length ? "part" : "typed", part: "", normal: "+x", area: q(0.1, "m2"), fill_ratio: q(85, "%"), comments: "" }); changed(true); },
      })));
      body.append(commentsBox(P.panels, "Your comments on all the panels"));
    },
  },

  cells: {
    title: "Cells, losses and shading", file: "power",
    render(body, { setup = false } = {}) {
      if (!project.hasPower) return noPower(body);
      // In the Power tab this box heads the page, so the card leaves it out
      if (setup) body.append(powerComments());
      const g = grid(body);
      row(g, "Cell efficiency", quantityInput(P, "cell_efficiency", ["%"]), "at the cells' rated temperature");
      row(g, "Loss factor", numberInput(P, "loss_factor", { step: 0.01, min: 0, max: 1 }), "share of the power left, 0 to 1");
      const s = P.self_shadowing;
      row(g, "Self-shadowing", checkbox(s, "enabled", "the model shades its own panels", { structure: true, onchange: () => { s.present = true; } }));
      if (s.enabled) row(g, "Points a panel", numberInput(s, "points", { step: 1, min: 1, placeholder: "512" }), "512 if left out");
      body.append(commentsBox(s, "Your comments on self-shadowing"));
    },
  },

  battery: {
    title: "Battery", file: "power",
    render(body) {
      if (!project.hasPower) return noPower(body);
      const b = P.battery;
      const g = grid(body);
      row(g, "Battery", checkbox(b, "present", "the power system has a battery", { structure: true }), "for the power budget");
      if (b.present) {
        row(g, "Capacity", quantityInput(b, "capacity", ["W h", "kW h"]), "new and full");
        row(g, "Capacity factor", numberInput(b, "capacity_factor", { step: 0.01, min: 0, max: 1 }), "share left after fade");
        row(g, "Deepest discharge", quantityInput(b, "max_depth_of_discharge", ["%"]), "in each orbit");
        row(g, "Charge at the start", quantityInput(b, "initial_charge", ["%"], { placeholder: "100" }), "100% if left out");
        body.append(commentsBox(b));
      }
    },
  },

  conditioning: {
    title: "Power conditioning", file: "power",
    render(body) {
      if (!project.hasPower) return noPower(body);
      const c = P.conditioning;
      const g = grid(body);
      row(g, "Conditioning", checkbox(c, "present", "give the conditioning's efficiencies", { structure: true }), "for the power budget");
      if (c.present) {
        row(g, "Array regulator", numberInput(c, "array_regulator", { step: 0.01, min: 0, max: 1 }), "array to bus");
        row(g, "Battery charge", numberInput(c, "battery_charge", { step: 0.01, min: 0, max: 1 }), "bus into the battery");
        row(g, "Battery discharge", numberInput(c, "battery_discharge", { step: 0.01, min: 0, max: 1 }), "battery to the bus");
        row(g, "Distribution", numberInput(c, "distribution", { step: 0.01, min: 0, max: 1 }), "bus to the loads");
      }
      row(g, "System margin", quantityInput(P, "system_margin", ["%"]), "on all the loads, for the power budget");
      if (c.present) body.append(commentsBox(c));
    },
  },

  payload_consumption: consumptionSection("payload"),
  platform_consumption: consumptionSection("platform"),

  surfaces: {
    title: "Surfaces", file: "payload_thermal",
    render(body) {
      if (!project.hasThermal) return noThermal(body);
      const list = T.surfaces.items;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "from", "part, or normal and area", "absorptance", "emissivity", "temperature", "fixed", ""].map((h) => el("th", { text: h }))));
      const tbody = el("tbody");
      table.append(tbody);
      list.forEach((item, index) => {
        const tr = selectable(el("tr"), { kind: "surface", item });
        const where = item.source === "part"
          ? selectInput(item, "part", partOptions(), { blank: "choose a part", cls: "wide" })
          : el("span", { class: "ctl" }, textInput(item, "normal", { placeholder: "+x, or 0, 1, -1" }), quantityInput(item, "area", ["m2"]));
        tr.append(
          el("td", {}, nameInput(item, null, () => list.map((s) => s.name))),
          el("td", {}, selectInput(item, "source", [["part", "the model"], ["typed", "typed in"]], { onchange: () => {} })),
          el("td", {}, where),
          el("td", {}, numberInput(item, "absorptance", { step: 0.01, min: 0, max: 1, width: 60 })),
          el("td", {}, numberInput(item, "emissivity", { step: 0.01, min: 0, max: 1, width: 60 })),
          el("td", {}, quantityInput(item, "temperature", ["K"])),
          el("td", {}, checkbox(item, "fixed", "kept constant")),
          el("td", { class: "tools" }, commentsButton(item, 8, tbody, tr), " ", itemTools(list, index)));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ surface",
        onclick: () => { list.push({ name: `surface ${list.length + 1}`, source: model.parts.length ? "part" : "typed", part: "", normal: "+x", area: q(0.1, "m2"), absorptance: 0.2, emissivity: 0.85, temperature: q(273, "K"), fixed: false, comments: "" }); changed(true); },
      })));
      body.append(commentsBox(T.surfaces, "Your comments on all the surfaces"));
    },
  },

  heat_flows: {
    title: "Heat flows", file: "payload_thermal",
    render(body) {
      if (!project.hasThermal) return noThermal(body);
      const list = T.heat_flows.items;
      const modes = S.modes.payload;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["name", "given", "power, W, positive into the payload", ""].map((h) => el("th", { text: h }))));
      list.forEach((item, index) => {
        const given = selectInput({ v: item.byMode ? "each" : "one" }, "v", [["one", "for every mode"], ["each", "for each mode"]], {
          onchange: (value) => {
            item.byMode = value === "each";
            if (item.byMode) item.powers = Object.fromEntries(modes.map((mode) => [mode, item.power]));
            else item.power = modes.map((mode) => item.powers[mode]).find((watts) => watts !== "" && watts != null) ?? "";
          },
        });
        const powers = item.byMode
          ? el("span", { class: "ctl wrap" }, modes.map((mode) => el("span", { class: "ctl" }, el("span", { class: "hint", text: mode }), numberInput(item.powers, mode, { width: 60 }))))
          : numberInput(item, "power", { width: 70 });
        table.append(el("tr", {},
          el("td", {}, nameInput(item, null, () => list.map((f) => f.name))),
          el("td", {}, given),
          el("td", {}, powers),
          el("td", { class: "tools" }, itemTools(list, index))));
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ heat flow",
        onclick: () => { list.push({ name: `flow ${list.length + 1}`, byMode: false, power: 0, powers: {} }); changed(true); },
      })));
      body.append(el("p", { class: "hint", text: "A flow given for each mode needs a power in every payload mode, 0 W included. A flow has no comments field of its own: describe it in the comments on all the flows." }));
      body.append(commentsBox(T.heat_flows, "Your comments on all the heat flows"));
    },
  },

  earth: {
    title: "The Earth", file: "payload_thermal",
    render(body) {
      if (!project.hasThermal) return noThermal(body);
      const e = T.earth;
      const g = grid(body);
      row(g, "Albedo", numberInput(e, "albedo", { step: 0.01, min: 0, max: 1, placeholder: "0.30" }), "share of sunlight reflected, 0.30 if left out");
      row(g, "Infrared", quantityInput(e, "infrared", ["W/m2"], { placeholder: "237" }), "237 W/m² if left out");
      body.append(commentsBox(e));
    },
  },

  thermal_account: {
    title: "Heat account", file: "payload_thermal", also: "and the payload's heater row", wide: true,
    render(body) {
      if (!project.hasThermal) return noThermal(body);
      body.append(accountPanel());
    },
  },

  save: {
    title: "Save and view", file: "all files",
    render(body) {
      const files = projectFiles();
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["file", "size", ""].map((h) => el("th", { text: h }))));
      for (const file of files) {
        table.append(el("tr", {},
          el("td", {}, file.path, file.note ? el("span", { class: "hint", text: `  ${file.note}` }) : null),
          el("td", { class: "hint", text: `${(fileBytes(file).length / 1024).toFixed(1)} kB` }),
          el("td", { class: "tools" }, el("button", { class: "btn small", text: "download", onclick: () => download(file) }))));
      }
      body.append(table);
      body.append(reviewNote());
      const g = grid(body);
      row(g, "Help in the files", checkbox(state, "writeHelp", "write the # help lines", { structure: true }));
      body.append(el("div", { class: "add-row" },
        el("button", { class: "btn primary", text: `download ${project.name}.zip`, onclick: downloadZip }),
        el("button", { class: "btn", text: "go to the Files tab", onclick: () => showTab("files") })));
      body.append(el("h3", { class: "viewer-head", text: "The viewer" }), viewerPanel());
    },
  },
};
