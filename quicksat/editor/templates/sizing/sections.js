// quicksat sizing editor: the sections, each one block of a file, and their
// explanations. The Setup steps and the theme tabs both draw these, so each
// field is built once.

// ---------------------------------------------------------------- the sections

const BUDGETS = {
  mass: { title: "Mass", files: ["mass", "equipment"], label: "the overall mass budget" },
  data: { title: "Data", files: ["data"], label: "the overall payload data flow" },
  deltav: { title: "Delta-V", files: ["deltav", "manoeuvres"], label: "the overall delta-V budget" },
  agility: { title: "Agility", files: ["agility"], label: "the overall agility budget" },
};

/** The comments on a whole file, which head its first step and its tab. */
function overallBox(key) {
  return el("div", { class: "overall" }, commentsBox(project[key], `Your comments on ${BUDGETS[key].label}`, {
    open: true, note: `They go in the comments field at the top of ${project.names[key]}.`,
  }));
}

const qField = (g, label, obj, key, units, hint) => row(g, label, quantityInput(obj, key, units), hint);
const pctField = (g, label, obj, key, hint) => row(g, label, quantityInput(obj, key, ["%"]), hint);

/** A text field with suggestions: the values already in use, and some usual ones. */
function suggest(input, id, values) {
  input.setAttribute("list", id);
  if (!document.getElementById(id)) document.body.append(el("datalist", { id }));
  const list = document.getElementById(id);
  list.replaceChildren(...[...new Set(values.filter(Boolean))].sort().map((v) => el("option", { value: v })));
  return input;
}

const SECTIONS = {
  folder: {
    title: "Folder", file: "all files",
    render(body) {
      body.append(openFolderButton());
      const rows = (kinds) => kinds.map((kind) => ({ kind }));
      const head = (key) => el("b", { text: `${BUDGETS[key].title} budget` });
      body.append(filesTable([
        { head: el("b", { text: "Mission, which every budget but the mass reads" }), rows: rows(["mission"]) },
        ...Object.keys(BUDGETS).map((key) => ({ head: head(key), rows: rows(BUDGETS[key].files) })),
      ]));
      body.append(el("p", { class: "hint", text: "The notebooks in sample/sizing/ read these files: mass_budget, data_budget, delta_v_budget, and agility_roll and agility_pitch." }));
    },
  },

  mission: {
    title: "Reference orbit and design life", file: "mission",
    render(body) {
      const g = grid(body);
      qField(g, "Altitude", M, "altitude", ["km", "m"], "circular, above the equator's radius");
      qField(g, "Inclination", M, "inclination", ["deg", "rad"]);
      qField(g, "Duration", M, "duration", ["yr", "d"], "the design life");
      body.append(missionLine());
      body.append(commentsBox(M, "Your comments on the mission", { note: "They go in the comments field at the top of mission.yaml." }));
    },
  },

  locations: {
    title: "Locations: margins and harness", file: "mass",
    render(body) {
      const L = project.mass.locations;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["location", "system margin", "harness", "harness margin", "", "used by", "", ""].map((h) => el("th", { text: h }))));
      L.items.forEach((item, index) => {
        const tr = el("tr");
        const count = project.equipment.filter((r) => r.location === item.name).length;
        tr.append(
          el("td", {}, nameInput(item, "location", locationNames)),
          el("td", {}, el("span", { class: "ctl" }, numberInput(item, "system_margin", { min: 0 }), el("span", { class: "unit", text: "%" }))),
          el("td", {}, el("span", { class: "ctl" }, numberInput(item, "harness_fraction", { min: 0 }), el("span", { class: "unit", text: "% of the equipment" }))),
          el("td", {}, el("span", { class: "ctl" }, numberInput(item, "harness_margin", { min: 0 }), el("span", { class: "unit", text: "%" }))),
          el("td", {}, checkbox(item, "retained_in_orbit", "stays in orbit")),
          el("td", { class: "hint", text: count ? `${count} row${count > 1 ? "s" : ""}` : "no rows" }),
          el("td", {}, commentsButton(item, 8, null, tr)),
          el("td", { class: "tools" }, itemTools(L.items, index, { kind: "location", name: item.name })));
        table.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" },
        el("button", { class: "btn", text: "+ location", onclick: () => {
          let name = "Location";
          for (let n = 2; locationNames().includes(name); n++) name = `Location ${n}`;
          L.items.push({ name, system_margin: 20, harness_fraction: 5, harness_margin: 25, retained_in_orbit: true, comments: "" });
          changed(true);
        } })));
      body.append(commentsBox(L, "Your comments on the locations"));
    },
  },

  equipment: {
    title: "Equipment", file: "equipment", wide: true,
    render(body) {
      const rows = project.equipment;
      const locations = [...new Set([...locationNames(), LAUNCHER])];
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["id", "name", "location", "responsibility", "subsystem", "unit mass", "margin %", "units", "class", "total", "comments", ""]
        .map((h) => el("th", { class: h === "total" ? "right" : "", text: h, title: h === "total" ? "units × unit mass, with the equipment margin" : null }))));
      const cells = [];
      rows.forEach((item, index) => {
        const tr = el("tr");
        const total = el("td", { class: "total" });
        cells.push({ item, tr, total });
        tr.append(
          el("td", {}, textInput(item, "id", { cls: "name" })),
          el("td", {}, textInput(item, "name", { cls: "mid" })),
          el("td", {}, selectInput(item, "location", locations)),
          el("td", {}, suggest(textInput(item, "responsibility", { cls: "short" }), "dl-responsibility", [...locations, ...rows.map((r) => r.responsibility)])),
          el("td", {}, suggest(textInput(item, "subsystem", { cls: "short" }), "dl-subsystem", ["ADCS", "COMM", "EPS", "OBDH", "Propulsion", "Structure", "Thermal", "Instrument", ...rows.map((r) => r.subsystem)])),
          el("td", {}, quantityInput(item, "unit_mass", ["kg", "g"])),
          el("td", {}, numberInput(item, "margin", { min: 0, width: 55 })),
          el("td", {}, numberInput(item, "units", { step: 1, min: 0, width: 50 })),
          el("td", {}, selectInput(item, "mass_class", MASS_CLASSES)),
          total,
          el("td", { class: "fill" }, textInput(item, "comments", { cls: "fill" })),
          el("td", { class: "tools" }, itemTools(rows, index, { copy: (r) => ({ ...r, id: `${r.id}_copy`, unit_mass: { ...r.unit_mass } }) })));
        table.append(tr);
      });
      const update = () => {
        const text = state.filter.trim().toLowerCase();
        for (const { item, tr, total } of cells) {
          const mass = rowMass(item);
          total.textContent = mass ? `${fmt(mass.withMargin, 2)} kg` : "";
          const shown = !text || [item.id, item.name, item.location, item.responsibility, item.subsystem, item.mass_class, item.comments].some((v) => String(v).toLowerCase().includes(text));
          tr.classList.toggle("hidden-row", !shown);
        }
      };
      update();
      live.add(update);
      body.append(el("div", { class: "add-row" },
        el("input", { type: "search", class: "wide", placeholder: "Show the rows that hold…", value: state.filter, oninput: (e) => { state.filter = e.target.value; update(); } }),
        el("span", { class: "hint", text: "Searches the id, the name, the location, the responsibility, the subsystem, the class and the comments." })));
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ equipment",
        onclick: () => { rows.push({ id: "", name: "", location: locationNames()[0] || "", responsibility: "", subsystem: "", unit_mass: q("", "kg"), margin: 10, units: 1, mass_class: "equipment", comments: "" }); changed(true); },
      })));
      body.append(totalsTable());
      body.append(el("p", { class: "hint", text: "These add the rows as entered. The notebook adds the harness and the system margins, and works out the mass cases. The comments column is the CSV's own place for comments, and is kept as written." }));
    },
  },

  generation: {
    title: "Payload data generation", file: "data",
    render(body) {
      const G = project.data.generation;
      const g = grid(body);
      qField(g, "Raw data rate", G, "raw_datarate", ["Mbit/s", "Gbit/s", "kbit/s"], "before compression");
      row(g, "Compression ratio", numberInput(G, "compression_ratio", { min: 1 }), "1 for none");
      pctField(g, "Duty cycle", G, "duty_cycle", "of each orbit");
      const line = el("div", { class: "derived" });
      const update = () => {
        const ok = !blank(G.raw_datarate) && G.compression_ratio > 0;
        line.replaceChildren(el("span", { class: "k", text: "after compression" }), ok ? el("b", { text: `${Number((G.raw_datarate.v / G.compression_ratio).toPrecision(5))} ${G.raw_datarate.u}` }) : "—");
      };
      update();
      live.add(update);
      body.append(line);
      body.append(commentsBox(G, "Your comments on the generation"));
    },
  },

  downlink: {
    title: "Downlink", file: "data",
    render(body) {
      const D = project.data.downlink;
      const g = grid(body);
      qField(g, "Rate", D, "rate", ["Mbit/s", "Gbit/s", "kbit/s"], "achieved throughput");
      row(g, "Contacts per day", numberInput(D, "contacts_per_day", { min: 0 }), "usable passes");
      qField(g, "Average contact", D, "avg_contact_duration", ["min", "s"], "usable length of a pass");
      body.append(commentsBox(D, "Your comments on the downlink"));
    },
  },

  storage: {
    title: "Storage", file: "data",
    render(body) {
      const S = project.data.storage;
      const g = grid(body);
      row(g, "Orbits without contact", numberInput(S, "orbits_without_contact", { min: 0 }), "the memory's sizing case");
      body.append(commentsBox(S, "Your comments on the storage"));
    },
  },

  dvconfig: {
    title: "Propulsion and margin", file: "deltav",
    render(body) {
      const D = project.deltav;
      const g = grid(body);
      qField(g, "Isp", D.propulsion, "isp", ["s"], "specific impulse");
      row(g, "Margin", el("span", { class: "ctl" }, numberInput(D, "margin", { min: 0 }), el("span", { class: "unit", text: "% on the total" })));
      row(g, "Collision avoidance", checkbox(D.collision_avoidance, "return_burn", "return burn: each avoidance comes back down"));
      body.append(commentsBox(D.propulsion, "Your comments on the propulsion"));
      body.append(commentsBox(D.collision_avoidance, "Your comments on collision avoidance"));
    },
  },

  manoeuvres: {
    title: "Manoeuvres", file: "manoeuvres", wide: true,
    render(body) {
      const rows = project.manoeuvres;
      const table = el("table", { class: "items" });
      table.append(el("tr", {}, ["id", "name", "phase", "type", "value", "count", "", "loss factor", "comments", ""].map((h) => el("th", { text: h }))));
      rows.forEach((item, index) => {
        const tr = el("tr");
        const units = VALUE_UNITS[item.type] || ["m"];
        tr.append(
          el("td", {}, textInput(item, "id", { cls: "name" })),
          el("td", {}, textInput(item, "name", { cls: "mid" })),
          el("td", {}, suggest(textInput(item, "phase", { cls: "short" }), "dl-phase", ["Commissioning", "Operations", "Disposal", ...rows.map((r) => r.phase)])),
          el("td", {}, selectInput(item, "type", MANOEUVRE_TYPES, { onchange: (type) => {
            const next = VALUE_UNITS[type] || ["m"];
            if (!next.includes(item.value.u)) item.value.u = next[0];
          } })),
          el("td", {}, quantityInput(item, "value", units)),
          el("td", {}, numberInput(item, "count", { min: 0, width: 55 })),
          el("td", {}, checkbox(item, "recurring", "per year")),
          el("td", {}, numberInput(item, "loss_factor", { min: 1, width: 55 })),
          el("td", { class: "fill" }, textInput(item, "comments", { cls: "fill" })),
          el("td", { class: "tools" }, itemTools(rows, index, { copy: (r) => ({ ...r, id: `${r.id}_copy`, value: { ...r.value } }) })));
        table.append(tr);
      });
      body.append(el("div", { class: "scroll-x" }, table));
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ manoeuvre",
        onclick: () => { rows.push({ id: "", name: "", phase: "Operations", type: "given", value: q("", "m/s"), count: 1, recurring: false, loss_factor: 1, comments: "" }); changed(true); },
      })));
    },
  },

  cases: {
    title: "Inertia cases", file: "agility",
    render(body) {
      const C = project.agility.cases;
      const table = el("table", { class: "items" });
      C.items.forEach((item, index) => {
        const first = el("tr", { class: "first" });
        const second = el("tr", { class: "second" });
        first.append(el("td", {}, el("span", { class: "ctl gap" },
          nameInput(item, null, () => C.items.map((c) => c.name)),
          radioRow(item, "kind", [["envelope", "envelope estimate"], ["stated", "stated inertia"]]),
          el("span", { class: "push ctl" }, commentsButton(item, 1, null, second), itemTools(C.items, index)))));
        const fields = item.kind === "envelope"
          ? [el("span", { class: "hint", text: "body" }),
             ...["x", "y", "z"].map((axis) => el("span", { class: "ctl" }, axis, quantityInput(item.body, axis, ["m"]))),
             el("span", { class: "hint", text: "appendage factor" }),
             ...["roll", "pitch"].map((axis) => el("span", { class: "ctl" }, axis, numberInput(item.appendage_factor, axis, { min: 1 }))),
             el("span", { class: "hint", text: "propellant aboard" }), quantityInput(item, "propellant", ["%"])]
          : [el("span", { class: "hint", text: "inertia" }),
             ...["roll", "pitch"].map((axis) => el("span", { class: "ctl" }, axis, quantityInput(item.inertia, axis, ["kg*m**2"])))];
        second.append(el("td", {}, el("span", { class: "ctl wrap gap" }, ...fields)));
        table.append(first, second);
      });
      body.append(table);
      body.append(el("div", { class: "add-row" }, el("button", {
        class: "btn", text: "+ case",
        onclick: () => {
          let name = "case";
          for (let n = 2; C.items.some((c) => c.name === name); n++) name = `case_${n}`;
          C.items.push({ name, kind: "envelope", ...envelope(), inertia: { roll: q("", "kg*m**2"), pitch: q("", "kg*m**2") }, comments: "" });
          changed(true);
        },
      })));
      body.append(commentsBox(C, "Your comments on the inertia cases"));
    },
  },

  wheels: {
    title: "Reaction wheels and settling", file: "agility",
    render(body) {
      const A = project.agility;
      const W = A.wheels;
      const g = grid(body);
      row(g, "Wheels", numberInput(W, "count", { step: 1, min: 1 }), "in the pyramid");
      qField(g, "Elevation", W, "elevation", ["deg"], "above the pyramid's base");
      qField(g, "Momentum", W, "momentum", ["N*m*s"], "nameplate, per wheel");
      qField(g, "Torque", W, "torque", ["N*m"], "nameplate, per wheel");
      pctField(g, "Momentum use factor", W, "momentum_use_factor", "kept for slews");
      pctField(g, "Torque derating", W, "torque_derating", "used in a slew");
      body.append(commentsBox(W, "Your comments on the wheels"));
      const s = grid(body);
      s.style.marginTop = "12px";
      qField(s, "Settling time", A, "settling_time", ["s", "min"], "after each slew");
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
  folder: `<h4>Folder</h4>
<p>This folder holds the input files of quicksat's sizing budgets. Each budget is a notebook, which reads its files and builds one table.</p>
<p>Saving always writes every budget's files. A folder that lacks a budget's files gets them started here, as new, for you to fill in.</p>
${FILES_HELP}
<span class="k">What follows</span>
<p>Data, delta-V and agility read <code>mission.yaml</code>, so the folder always holds it. Delta-V and agility also read the mass budget: delta-V for the dry mass, and agility for the mass of an envelope case. Without the mass files, their notebooks must give a mass instead.</p>
<p>These files share nothing with a scenario or power folder. The mission's orbit is a reference orbit for the budgets: it has no epoch and no node.</p>`,

  mission: `<h4>Reference orbit and design life</h4>
<p>The mission is a circular orbit and a design life. The other budgets read it from here, so they cannot disagree on the orbit.</p>
<span class="k">Altitude</span><p>Above the Earth's equatorial radius of 6378.1 km. quicksat models no eccentricity.</p>
<span class="k">Inclination</span><p>No budget reads it yet. It records the orbit that the budgets assume. A sun-synchronous orbit at 500 km has an inclination of about 97.4 deg.</p>
<span class="k">Duration</span><p>The design life. The delta-V budget multiplies each recurring manoeuvre's yearly count by it.</p>
<span class="k">What follows</span><p>The figures under the fields come from the altitude alone. The data budget uses the period and the orbits in a day. Delta-V uses the orbit's radius and speed. Agility uses the ground track speed.</p>`,

  locations: `<h4>Locations: margins and harness</h4>
<p>Every equipment row names a location, such as Platform or Payload. The location sets the row's system margin and harness, and whether it stays in orbit.</p>
<span class="k">System margin</span><p>In percent, on the location's subtotal, after each row's equipment margin.</p>
<span class="k">Harness</span><p>The harness is worked out, not listed. It is a percentage of the location's equipment mass before margin, without the propellant. The harness takes its own margin, and then the system margin.</p>
<span class="k">Stays in orbit</span><p>Untick it for hardware that leaves at separation.</p>
<span class="k">Launcher</span><p><code>Launcher</code> needs no entry. It has no margins and no harness, and leaves at separation. Any other location that the equipment names must be listed here.</p>`,

  equipment: `<h4>Equipment</h4>
<p>One row per item, with the mass of one unit and the number flown. The mass takes its unit, such as <code>750 g</code> or <code>62 kg</code>.</p>
<span class="k">Ids</span><p>An id has no spaces. Two rows may share an id only at different locations, such as the MLI on the payload and on the platform.</p>
<span class="k">Margin</span><p>The equipment margin, in percent, follows how mature the item is. A usual rule is 5 % for an item off the shelf, 10 % for one modified, and 20 % for a new design.</p>
<span class="k">Class</span><p><code>propellant</code> marks the propellant load. It never takes a margin, and the mass cases scale it from full to empty. Every other row is <code>equipment</code>.</p>
<span class="k">Responsibility and subsystem</span><p>They group the rows in the notebook's tables. They do not change the mass.</p>
<span class="k">What follows</span><p>The totals under the table add the rows as entered. The notebook adds the harness and the system margins.</p>`,

  generation: `<h4>Payload data generation</h4>
<p>What the payload makes in each orbit. The raw rate is divided by the compression ratio. The result flows for the duty cycle's share of each orbit.</p>
<span class="k">Raw data rate</span><p>The instrument's output before compression, such as <code>1000 Mbit/s</code>.</p>
<span class="k">Compression ratio</span><p>1 means no compression. It cannot be below 1.</p>
<span class="k">Duty cycle</span><p>The share of each orbit spent making data, up to 100 %. An imager that works only on the day side, over land, may need a few percent.</p>`,

  downlink: `<h4>Downlink</h4>
<p>What the link sends down. It is given per day, because ground contacts are counted over the station's day.</p>
<span class="k">Rate</span><p>The achieved throughput, not the symbol rate.</p>
<span class="k">Contacts per day</span><p>The usable passes in a day, from Mission Analysis. It need not be a whole number.</p>
<span class="k">Average contact</span><p>How long a usable pass lasts, on average.</p>`,

  storage: `<h4>Storage</h4>
<p>The memory is sized to hold the data of this many orbits without a usable pass. It need not be a whole number.</p>
<span class="k">What follows</span><p>The data budget compares what the payload makes with what the link sends. It then gives the memory for this case.</p>`,

  dvconfig: `<h4>Propulsion and margin</h4>
<p>The settings of the delta-V budget. The orbit and the design life come from <code>mission.yaml</code>.</p>
<span class="k">Isp</span><p>The specific impulse, for the rocket equation. Hydrazine monopropellant gives about 220 s.</p>
<span class="k">Margin</span><p>In percent, one allowance on the total delta-V.</p>
<span class="k">Collision avoidance</span><p>With the return burn, each avoidance goes up and comes back down, which doubles its delta-V. Leave it off when the satellite was due to be raised anyway. The avoidance then also pays off some of the drag make-up.</p>`,

  manoeuvres: `<h4>Manoeuvres</h4>
<p>One row per manoeuvre. Its type sets how the value turns into a delta-V, and the unit that the value takes.</p>
<table><tr><th>type</th><th>value</th><th>worked out as</th></tr>
<tr><td><code>altitude_change</code></td><td>a length</td><td>a Hohmann transfer between two circular orbits</td></tr>
<tr><td><code>collision_avoidance</code></td><td>a length</td><td>the same, doubled with the return burn</td></tr>
<tr><td><code>inclination_change</code></td><td>an angle</td><td>a plane change at the orbital speed</td></tr>
<tr><td><code>deorbit</code></td><td>a length</td><td>one burn that lowers the perigee to this altitude</td></tr>
<tr><td><code>given</code></td><td>a speed</td><td>taken as it is</td></tr></table>
<span class="k">Count and per year</span><p>How many times. With <b>per year</b> ticked, the count is per year, and is multiplied by the design life.</p>
<span class="k">Loss factor</span><p>The finite-burn and gravity losses, as a factor on the ideal delta-V. 1.0 is an impulsive burn, and the factor cannot be below 1.</p>
<span class="k">Phase</span><p>It groups the rows in the notebook's tables, such as Commissioning, Operations and Disposal.</p>`,

  cases: `<h4>Inertia cases</h4>
<p>Each case is one spacecraft, with one set of mass properties. The names are yours: the agility notebook asks for a case by its name.</p>
<span class="k">Envelope estimate</span><p>A uniform box, with a factor on each axis for the arrays, radiators and booms. Its inertia follows the mass from the mass budget, at the propellant level given.</p>
<span class="k">Stated inertia</span><p>The roll and pitch inertia, as a mass properties report gives them. It is a fixed number: nothing checks that it still matches the mass budget.</p>
<p>A case is one or the other, never both, so each figure has one source.</p>
<span class="k">Axes</span><p>x is along the track, y across it, and z towards nadir.</p>`,

  wheels: `<h4>Reaction wheels and settling</h4>
<p>A pyramid of reaction wheels, with its axis along yaw.</p>
<span class="k">Nameplate figures</span><p>The momentum and the torque of one wheel, as the vendor quotes them. The elevation is each wheel's angle above the pyramid's base.</p>
<span class="k">Use policy</span><p>The momentum use factor is the share of the momentum kept for slews. The rest stores disturbances. The torque derating is the share of the torque used in a slew. The rest is kept for control.</p>
<span class="k">Settling time</span><p>What the platform needs after a slew before the payload can work. It is added once, at the end of a manoeuvre.</p>
<span class="k">Not in the file</span><p>The time allowed for a slew. It is asked of a spacecraft, so the notebook passes it to each call.</p>`,

  save: `<h4>Save the files</h4>
<p>Saving writes each file again. The page writes its own help as lines that start with #. Your notes are kept in the comments fields.</p>
<p>Download the zip, or each file alone. Then put the files back in the folder, and run the notebooks.</p>`,
};
