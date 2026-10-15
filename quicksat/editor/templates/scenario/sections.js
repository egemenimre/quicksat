// quicksat scenario editor: the sections, each one block of a file, and their explanations.
//
// The Setup steps and the theme tabs both draw these, so each field is built once.

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

/** The comments on the overall power subsystem, which head the Power pages. */
function powerComments() {
  if (!project.hasPower) return null;
  return el("div", { class: "overall" }, commentsBox(P, "Your comments on the overall power subsystem", {
    open: true,
    note: `Also for the cell efficiency, the loss factor and the system margin, which have no block of their own. They go in the comments field at the top of ${project.names.power}.`,
  }));
}

/** A copy of an equipment row, with an id of its own. */
function copyEquipment(row) {
  let id = `${row.id}_2`;
  for (let n = 3; project.consumption.some((r) => r.id === id); n++) id = `${row.id}_${n}`;
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

/** Start a consumption file, for a folder that has none. */
function addConsumption() {
  project.hasConsumption = true;
  fileAdded("consumption");
  changed(true);
}

/** The modes a consumption row needs: each mode, and slew while the body turns. */
const consumptionModes = () => (S.slew.enabled || project.slewColumn ? [...S.modes, SLEW] : S.modes);

// ---------------------------------------------------------------- sections

const SECTIONS = {
  project: {
    title: "Folder", file: "all files",
    render(body) {
      body.append(openFolderButton());
      body.append(filesTable([{ rows: FILES.map(({ kind }) => ({ kind, add: { power: addPower, consumption: addConsumption }[kind] })) }]));
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
        row(g, "LTAN", el("span", { class: "ctl" },
          el("input", { type: "time", value: o.sso.ltan, oninput: (e) => { o.sso.ltan = e.target.value; changed(); } }),
          el("span", { class: "hint", text: "local time of the ascending node" })));
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

  targets: {
    title: "Ground targets", file: "scenario",
    render(body) {
      const list = S.targets.items;
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
      body.append(commentsBox(S.targets, "Your comments on all the targets"));
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
    title: "Modes", file: "scenario", also: "and the consumption table",
    render(body) {
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["mode", "used by", ""].map((h) => el("th", { text: h }))));
      S.modes.forEach((name, index) => {
        const uses = usesOf("mode", name).filter((u) => !u.startsWith("a column"));
        const input = el("input", {
          type: "text", class: "name", value: name,
          onchange: (e) => {
            const to = e.target.value.trim();
            if (!to || to === name) { e.target.value = name; return; }
            if (S.modes.includes(to)) { e.target.value = name; alert(`There is already a mode called "${to}".`); return; }
            rename("mode", name, to);
            S.modes[index] = to;
            changed(true);
          },
        });
        table.append(el("tr", {},
          el("td", {}, input),
          el("td", { class: "hint", text: uses.length ? uses.join(", ") : "nothing yet" }),
          el("td", { class: "tools" }, itemTools(S.modes, index, { kind: "mode", name }))));
      });
      body.append(table);
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ mode",
        onclick: () => {
          let name = "new mode";
          for (let n = 2; S.modes.includes(name); n++) name = `new mode ${n}`;
          S.modes.push(name);
          project.consumption.forEach((r) => (r.power[name] = ""));
          changed(true);
        },
      })));
      body.append(el("p", { class: "hint", text: "The modes are not a block of the scenario file: they are the names the activities use. So they take no comments here. Describe a mode in the comments of the activities that use it, or in the consumption table." }));
    },
  },

  activities: {
    title: "Activities", file: "scenario", wide: true,
    render(body) {
      const list = S.activities;
      const table = el("table", { class: "items activities" });
      table.append(el("tr", {}, ["#", "title", "ends at", "", "attitude", "mode", "expects", ""].map((h) => el("th", { text: h }))));
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
        tr.append(
          el("td", { class: "hint num", text: index + 1 }),
          el("td", {}, textInput(item, "title", { cls: "name", placeholder: "what it is for" })),
          el("td", {}, selectInput(end, "kind", TRIGGERS, { onchange: () => {} })),
          el("td", {}, detail, text),
          el("td", {}, selectInput(item, "attitude", attitudeNames(), { blank: "attitude" })),
          el("td", {}, selectInput(item, "mode", S.modes, { blank: "mode" })),
          el("td", {}, selectInput(item, "constraint", CONSTRAINTS.map((c) => [c, c || "anything"]))),
          el("td", { class: "tools" }, commentsButton(item, 8, tbody, tr), " ", itemTools(list, index, { order: true })));
        tbody.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ activity",
        onclick: () => { list.push({ title: `activity ${list.length + 1}`, end: trigger("duration"), attitude: attitudeNames()[0] || "", mode: S.modes[0] || "", constraint: "", comments: "" }); changed(true); },
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

  consumption: {
    title: "Consumption", file: "consumption", wide: true,
    render(body) {
      if (!project.hasConsumption) {
        body.append(el("p", { class: "hint", text: `This folder has no ${project.names.consumption}. Start one to give what each equipment draws in each mode.` }),
          el("button", { class: "btn", text: `add ${project.names.consumption}`, onclick: addConsumption }));
        return;
      }
      const rows = project.consumption;
      const modes = consumptionModes();
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["id", "name", "subsystem", "units on", "margin %", ...modes.map((m) => `${m} W`), "comments", ""].map((h) => el("th", { text: h }))));
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
          el("td", { class: "tools" }, itemTools(rows, index, { copy: copyEquipment })));
        table.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ equipment",
        onclick: () => { rows.push({ id: "", name: "", subsystem: "", units: 1, margin: 5, power: Object.fromEntries(S.modes.map((m) => [m, ""])), slew: "", comments: "" }); changed(true); },
      })));
      body.append(el("p", { class: "hint", text: "One column per mode, from the Modes section, and a slew column when the scenario has slews. Every cell needs a power, 0 W included. The comments column is the CSV's own place for comments, and is kept as written." }));
    },
  },

  save: {
    title: "Save the files", file: "all files",
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
    },
  },
};

// ---------------------------------------------------------------- information boxes

const INFO = {
  project: `<h4>The folder</h4>
    <p>The editor works on one folder of input files. A scenario folder holds the scenario file, with the 3D model and any orbit file it names. A power folder also holds the power system file and the consumption file, with its own copy of the scenario, as quicksat's domains keep their own files.</p>
    ${FILES_HELP}
    <span class="k">Comments</span>
    <p>Every block of a file has a <code>comments</code> field for your own comments. The editor keeps them through every edit and save. The lines that start with <code>#</code> are help that the editor writes. It rewrites them on each save, so do not keep your own comments there.</p>`,
  orbit: `<h4>Trajectory definition</h4>
    <p>The orbit sets where the satellite is at each step: when it is in sunlight, what it flies over, and which ground stations see it.</p>
    <span class="k">Options</span>
    <p><b>Sun-synchronous:</b> quicksat builds a TLE from the altitude and the LTAN, with its epoch at the start time. The quickest way to begin.</p>
    <p><b>TLE or OMM file:</b> a real element set, such as one from CelesTrak. The file must hold exactly one.</p>
    <p><b>Trajectory file:</b> positions and velocities at times, in ECSV or CCSDS OEM. Use it for an orbit from another tool, such as GMAT.</p>
    <span class="k">Consequences</span>
    <p>The LTAN sets the beta angle, and so the eclipse length and the power. A 13:30 LTAN and a 10:30 LTAN give about the same eclipses, but the sun is on the other side of the orbit plane.</p>`,
  time: `<h4>Start, duration and step</h4>
    <p><b>Start</b> is in UTC. It fixes the sun's position, and with it the eclipses and the season.</p>
    <p><b>Duration</b> is a time, such as <code>6 h</code>, or a number of orbits, such as <code>3 orbits</code>.</p>
    <span class="k">What one orbit is</span>
    <p>One orbit is the <b>nodal period</b>: the time from one ascending node to the next, where the satellite crosses the equator going north. It is a little shorter than the time to come back to the same point in space, because the orbit plane turns.</p>
    <p>A duration in orbits counts whole periods <b>from the start time</b>. The run does not have to start at a node. Power counts its orbits the same way.</p>
    <span class="k">The time step</span>
    <p>The orbit and the eclipses are worked out at each step. Event times are refined between the steps to 1 ms, so a coarser step does not move them. But an event shorter than one step can be missed, and the plots get coarser.</p>
    <span class="k">Consequences</span>
    <p>Runs are meant to be short: an orbit to a day or two. Three orbits at 10 s take about 4 s.</p>`,
  model: `<h4>The 3D model</h4>
    <p>A GLB file, in body axes and metres, with its origin at the point the body turns about. The viewer draws it, and the power panels take their area and direction from its parts.</p>
    <span class="k">Options</span>
    <p>With no model, quicksat draws a plain 1 m cube, and every panel must be typed in.</p>
    <span class="k">Consequences</span>
    <p>Name the parts in the model: the panels and the articulations refer to them by name. A part that turns, such as a wing, must be one node, with its origin on its drive axis.</p>`,
  articulations: `<h4>Articulations</h4>
    <p>A part of the model that turns about one axis, such as a solar wing. At each step it turns until one of its own axes points as close to a direction as the turn allows. A solar wing turns its cells, here <code>-z</code>, toward the sun.</p>
    <span class="k">What it can point at</span>
    <p>The same directions as the attitudes: the sun, nadir, the orbit normal, the velocity, the ground velocity, and the ground targets. So an antenna on a one-axis drive can follow a ground station. A second spacecraft would need an orbit of its own, which quicksat does not have.</p>
    <span class="k">Options</span>
    <p><b>Park angles</b> hold it still in a mode, such as during imaging, or while the body slews. A <b>range</b> limits the turn.</p>
    <span class="k">Consequences</span>
    <p>No drive is simulated: the angle is set from the geometry at each step. When the direction lies along the axis, the part keeps its last angle.</p>`,
  targets: `<h4>Ground targets</h4>
    <p>Points on the ground that an attitude can point at, such as a ground station. Each gives two triggers: <code>name rise</code> and <code>name set</code>, when it starts and stops seeing the satellite.</p>
    <p>The search asks OpenStreetMap's Nominatim, so it needs a connection. It finds towns, addresses, and many ground stations by name, such as SvalSat. Check a station's position: a town's is its centre, which can lie some way from the station. The text you search for is sent to openstreetmap.org.</p>
    <span class="k">Options</span>
    <p>The altitude is above the WGS84 ellipsoid. The minimum elevation sets when the target sees the satellite: 5 deg if left out.</p>`,
  attitudes: `<h4>Attitudes</h4>
    <p>Each attitude points one body axis at a direction, and turns a second body axis as close as it can get to another direction. Select one to see its axes in the 3D panel.</p>
    <span class="k">Options</span>
    <p>The directions are nadir, sun, orbit normal, velocity, ground velocity, and the targets. The <b>fallback</b> takes the second direction's place where it is parallel to the first. By default it is the first of orbit normal, nadir and velocity that the attitude does not use. An <b>offset</b> turns the result, such as <code>x 30 deg</code> for a roll. Several turns are separated by commas.</p>
    <span class="k">Consequences</span>
    <p>The two directions must differ. Constraining an axis to nadir while pointing at the sun makes the body spin fast when the sun is near the nadir line.</p>`,
  slew: `<h4>Attitude slew performance</h4>
    <p>How the body turns from one attitude to the next: from rest to rest, about one axis, then it settles.</p>
    <span class="k">Options</span>
    <p>Give the fastest rate, the acceleration, or both. With the rate alone, the turn starts and stops at full rate at once. With the acceleration alone, the turn speeds up until the midpoint.</p>
    <span class="k">Consequences</span>
    <p>The turn takes time from the end of the activity before, so each activity starts in its own attitude. Bigger turns take longer. With slews off, attitude changes are instant. With slews on, the mode reads <code>slew</code> while the body turns, so the consumption table needs a slew column.</p>`,
  modes: `<h4>Modes</h4>
    <p>What the spacecraft is doing, such as idle, imaging or downlink. Each activity names one. Any name will do, except <code>slew</code>, which the run gives the time spent turning.</p>
    <span class="k">Consequences</span>
    <p>The consumption table has one column per mode. Renaming a mode here renames it in the activities, the park angles and that table.</p>`,
  activities: `<h4>Activities</h4>
    <p>One repeat of what the spacecraft does. Each activity starts where the one before ends, and ends at its trigger. The run repeats the list until the duration ends.</p>
    <p>The <b>title</b> says what the activity is for. The tables, the Gantt chart and the viewer show it. Two activities may share a title.</p>
    <span class="k">Triggers</span>
    <p>A duration, or the next event after the activity starts: a shadow edge, a node, a latitude crossing, or a target's rise or set. An event can take an offset, such as <code>eclipse entry + 2 min</code>.</p>
    <span class="k">Consequences</span>
    <p>The <b>expects</b> column is the illumination the activity needs. The run reports any time spent outside it. Only the run can tell whether a trigger ever comes, so this page cannot check that.</p>`,
  panels: `<h4>Solar panels</h4>
    <p>A panel names a flat part of the 3D model, which gives its area and the direction its cells face. A panel on a wing turns with it. Select one to see its normal.</p>
    <span class="k">Options</span>
    <p><b>Typed in:</b> a direction and an area, for a model without panel parts. The direction is a body axis, such as <code>+x</code>, or three numbers, such as <code>0, 1, -1</code>. It stays fixed in body axes, is never shaded, and shades nothing.</p>
    <span class="k">Consequences</span>
    <p>The fill ratio is the share of the part that the cells cover.</p>`,
  cells: `<h4>Cells, losses and shading</h4>
    <p><b>Cell efficiency</b> is at the cells' rated temperature, such as 30% for triple-junction GaAs.</p>
    <p><b>Loss factor</b> is every loss up to the array's output, as the share of power left: temperature, ageing, mismatch, UV and the array's wiring. Set it for the year being sized, such as the end of life.</p>
    <span class="k">Self-shadowing</span>
    <p>Whether the rest of the model shades the panels, such as a housing shading the deck cells. More points give a finer result, and take longer.</p>`,
  battery: `<h4>Battery</h4>
    <p><b>Capacity</b> is what it holds when new and full. The <b>capacity factor</b> is the share left in the year being sized, after fade.</p>
    <span class="k">Consequences</span>
    <p>The deepest discharge is a limit on each orbit: 30% is usual in low orbit, where the battery cycles some 5500 times a year. The generation needs no battery: only the power budget does.</p>`,
  conditioning: `<h4>Power conditioning</h4>
    <p>An efficiency for each path the energy takes. Energy that goes through the battery pays both of its paths.</p>
    <span class="k">Margin</span>
    <p>The system margin is on all the loads together, on top of each equipment's own margin.</p>`,
  consumption: `<h4>Consumption</h4>
    <p>One row for each powered equipment: the power of one unit in each mode, how many units are on, and its margin in percent.</p>
    <span class="k">Slews</span>
    <p>With slews on, the mode reads <code>slew</code> while the body turns, so each row needs its power in a slew column too.</p>`,
  save: `<h4>Saving</h4>
    <p>Download one zip, which holds the folder, or the files one by one. Put them back in the folder they came from, then run the notebooks again.</p>
    <p>The files start with a few lines that say how comments work. Your own comments are in the <code>comments</code> fields. The other <code>#</code> lines are help, which the editor rewrites on each save. Turn the help off for shorter files.</p>`,
};
