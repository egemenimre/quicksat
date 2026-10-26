// quicksat scenario editor: the payload's thermal file, and the Thermal tab's
// heat account.
//
// The heat flows given by mode follow the payload's modes: a rename on the
// Modes step renames their cells, and a new mode gets an empty cell. The heater
// powers stay in the payload's consumption file, in its heater row, so the
// account's table by mode edits that row.
//
// quicksat works out the account on the editor's server, which keeps the run
// and the surfaces' heat between requests. So a change to the heaters, the
// flows or the dissipation is quick to work out again. Without the server, the
// tab says how to start it.

/** The values of the payload consumption file's `thermal` column. */
const THERMAL_VALUES = [["inside_mli", "inside MLI"], ["outside_mli", "outside MLI"], ["heater", "heater"]];
const HEATER = "heater";

// ---------------------------------------------------------------- the flows and the modes

/** The payload modes that the heat flows given by mode name, each once. */
function flowModes(thermal) {
  const modes = [];
  for (const flow of thermal.heat_flows.items) {
    if (flow.byMode) for (const mode of Object.keys(flow.powers)) if (!modes.includes(mode)) modes.push(mode);
  }
  return modes;
}

/** Rename a payload mode in every heat flow given by mode. */
function renameFlowMode(thermal, from, to) {
  for (const flow of thermal.heat_flows.items) {
    if (!flow.byMode || !(from in flow.powers)) continue;
    flow.powers = Object.fromEntries(Object.entries(flow.powers).map(([mode, watts]) => [mode === from ? to : mode, watts]));
  }
}

/** Give every heat flow given by mode an empty cell for a new payload mode, which the checks flag until it is filled. */
function addFlowMode(thermal, mode) {
  for (const flow of thermal.heat_flows.items) if (flow.byMode && !(mode in flow.powers)) flow.powers[mode] = "";
}

/** The heat flows given by mode that use a payload mode, by name. */
const flowsUsing = (thermal, mode) => thermal.heat_flows.items.filter((flow) => flow.byMode && mode in flow.powers).map((flow) => flow.name);

// ---------------------------------------------------------------- the heater row

/** The payload's heater row: the row whose `thermal` is `heater`, or null. */
const heaterRow = (rows) => rows.find((row) => row.thermal === HEATER) || null;

/** The heater power in one payload mode, all the row's units together, in W, or "" when the cell is blank. */
function heaterWatts(row, mode) {
  const each = row.power[mode];
  if (each === "" || each == null) return "";
  return tidy(Number(row.units || 0) * Number(each));
}

/**
 * Set the heater power in one payload mode, all the row's units together. The
 * row keeps its units, and the power of one unit changes. A row with no units on
 * gets one.
 */
function setHeaterWatts(row, mode, watts) {
  if (watts === "" || watts == null) { row.power[mode] = ""; return; }
  if (!(Number(row.units) > 0)) row.units = 1;
  row.power[mode] = tidy(Number(watts) / Number(row.units));
}

/** A balancing heater power, rounded up to 0.1 W, so that the mode does not end in deficit. */
const roundUp = (watts) => Math.max(0, Math.ceil(watts * 10 - 1e-6) / 10);

/**
 * Set each mode's heater power to its balancing power, from the account's table
 * by mode. Returns the modes set.
 */
function balanceHeaters(row, modeRows) {
  const set = [];
  for (const entry of modeRows) {
    const balancing = entry["balancing heater [W]"];
    if (balancing == null) continue;
    setHeaterWatts(row, entry["payload mode"], roundUp(balancing));
    set.push(entry["payload mode"]);
  }
  return set;
}

// ---------------------------------------------------------------- the work-out

/** The account, as the tab shows it, and the state of its work-out. */
const thermal = {
  /** The server's last results, or null. */
  results: null,
  /** The files' texts the results come from, by kind, to tell when the page has changed since. */
  texts: null,
  /** When the server worked them out. */
  at: null,
  /** Whether the server reused its run and surfaces' heat for them. */
  reused: false,
  seconds: null,
  running: false,
  /** Whether a change came in while a work-out was going on. */
  again: false,
  /** Why the last work-out failed, or "", and what quicksat's loaders said. */
  error: "",
  checks: [],
  timer: null,
};

/** The files' texts on the page now, by kind. */
const accountTexts = () => Object.fromEntries(projectFiles().map((file) => [file.kind, file.text ?? file.bytes.length]));

/** Whether the page has changed since the account was worked out. */
function accountStale() {
  if (!thermal.texts) return false;
  const now = accountTexts();
  return Object.keys({ ...now, ...thermal.texts }).some((kind) => now[kind] !== thermal.texts[kind]);
}

/** Send the page's files to the server, which works out the heat account. */
async function workOutThermal() {
  if (server.state !== "up") return;
  if (thermal.running) { thermal.again = true; return; }
  const texts = accountTexts();
  thermal.running = true;
  refreshThermal();
  let result;
  try {
    const response = await fetch(serverUrl("thermal"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: runFiles() }),
    });
    const text = await response.text();
    try {
      result = JSON.parse(text);
    } catch {
      result = { ok: false, error: `The server refused the work-out: ${text}`, checks: [] };
    }
  } catch {
    result = { ok: false, error: "The server did not answer. It may have stopped: see its window.", checks: [] };
  }
  thermal.running = false;
  thermal.checks = result.checks || [];
  if (result.ok) {
    Object.assign(thermal, { results: result.results, texts, at: new Date(), reused: result.reused, seconds: result.seconds, error: "" });
  } else thermal.error = result.error;
  if (thermal.again || (result.ok && accountStale())) {
    thermal.again = false;
    workOutThermal();
  }
  refreshThermal();
  if (!result.ok) checkServer();
}

/** Work the account out again a moment after a change, once it has been worked out and while its tab is open. */
function scheduleThermal() {
  clearTimeout(thermal.timer);
  if (server.state === "up" && thermal.results && state.tab === "thermal" && accountStale()) thermal.timer = setTimeout(workOutThermal, 600);
  refreshThermal();
}

/** Draw the account again wherever the page shows it. */
function refreshThermal() {
  for (const node of document.querySelectorAll("[data-thermal-account]")) fillAccount(node);
}

// ---------------------------------------------------------------- drawing

/** A number with one decimal, or a dash for none. */
const one = (value) => (value == null || Number.isNaN(value) ? "–" : Number(value).toFixed(1));

/** The columns of the account's tables, after their first: the mean power of each term, then the net. */
const TERM_COLUMNS = [
  ["dissipation [W]", "dissipation"], ["heaters [W]", "heaters"], ["heat flows [W]", "heat flows"],
  ["sun [W]", "sun"], ["albedo [W]", "albedo"], ["Earth infrared [W]", "Earth IR"], ["emitted [W]", "emitted"],
  ["net [W]", "net W"], ["net [Wh]", "net W h"], ["ΔT [K]", "ΔT K"],
];

/** A cell of a number, red when it is the net and negative, amber when positive. */
function numberCell(key, value) {
  const tone = key.startsWith("net") && value != null ? (value < 0 ? "neg" : value > 0 ? "pos" : "") : "";
  return el("td", { class: `right ${tone}`, text: one(value) });
}

/** A table of the account: one row for each activity, mode or orbit. `extra` adds cells at the end of a row. */
function accountTable(rows, first, { lead = [], extra = null, extraHeads = [] } = {}) {
  const table = el("table", { class: "items budget account" });
  table.append(el("tr", {},
    [first[1], ...lead.map(([, title]) => title), ...TERM_COLUMNS.map(([, title]) => title), ...extraHeads].map((h, i) => el("th", { class: i ? "right" : "", text: h }))));
  for (const entry of rows) {
    const note = entry["ΔT note"];
    table.append(el("tr", { title: note ? `No ΔT: ${note}` : null },
      el("td", { class: "name", text: entry[first[0]] }),
      ...lead.map(([key]) => el("td", { class: "right", text: typeof entry[key] === "number" && !Number.isInteger(entry[key]) ? one(entry[key]) : entry[key] })),
      ...TERM_COLUMNS.map(([key]) => numberCell(key, entry[key])),
      ...(extra ? extra(entry) : [])));
  }
  return el("div", { class: "scroll-x" }, table);
}

/** The heater power of a mode, as a field that writes the heater row. */
function heaterCell(row, mode) {
  return el("td", { class: "right" }, el("input", {
    type: "number", step: "any", min: 0, value: heaterWatts(row, mode), style: "width:70px",
    title: `The heater row ${row.id}'s power in ${mode}, all its units together. It is the consumption file's power of one unit times the units on.`,
    onchange: (e) => { setHeaterWatts(row, mode, e.target.value === "" ? "" : Number(e.target.value)); changed(); },
  }));
}

/** The plot of the net heat since the start, over the payload's modes. */
function accountPlot(results) {
  const node = el("div", { class: "account-plot" });
  if (typeof uPlot === "undefined") return node;
  const modes = [...new Set(results.bands.map((band) => band.mode))];
  const colours = ["rgba(59,130,246,0.16)", "rgba(245,177,61,0.20)", "rgba(52,211,153,0.18)", "rgba(244,114,182,0.18)", "rgba(167,139,250,0.20)", "rgba(148,163,184,0.18)"];
  const colourOf = (mode) => colours[modes.indexOf(mode) % colours.length];
  const bands = (u) => {
    const { ctx, bbox } = u;
    ctx.save();
    for (const band of results.bands) {
      const left = u.valToPos(band.start_min, "x", true);
      const right = u.valToPos(band.end_min, "x", true);
      ctx.fillStyle = colourOf(band.mode);
      ctx.fillRect(left, bbox.top, right - left, bbox.height);
    }
    ctx.restore();
  };
  const legend = el("div", { class: "band-legend" }, modes.map((mode) => el("span", {}, el("i", { style: `background:${colourOf(mode).replace(/[\d.]+\)$/, "0.6)")}` }), mode)));
  const draw = () => {
    const width = Math.max(320, Math.min(1100, node.clientWidth || 900));
    const plot = new uPlot({
      width, height: 260,
      scales: { x: { time: false } },
      axes: [
        { label: "time from the start, min", stroke: "#8ea3bf", grid: { stroke: "#1b2a40" } },
        { label: "net heat in, W h", stroke: "#8ea3bf", grid: { stroke: "#1b2a40" } },
      ],
      series: [{ label: "min" }, { label: "net heat in", stroke: "#f5b13d", width: 1.5, value: (u, v) => (v == null ? "" : `${v.toFixed(1)} W h`) }],
      hooks: { drawClear: [bands] },
      legend: { show: false },
    }, [results.t_min, results.energy_wh]);
    node.replaceChildren(plot.root, legend);
  };
  requestAnimationFrame(draw);
  return node;
}

/** What the server's last work-out said, and its buttons. */
function fillAccount(node) {
  const up = server.state === "up";
  const results = thermal.results;
  const rows = project.consumption.payload;
  const heater = heaterRow(rows);
  const parts = [];
  const status = thermal.running
    ? "quicksat is computing the heat account."
    : thermal.error
      ? ""
      : results
        ? `Computed at ${thermal.at.toLocaleTimeString()} in ${thermal.seconds} s${thermal.reused ? ", from the kept run" : ""}${accountStale() ? ". The page has changed since." : "."}`
        : "";
  parts.push(el("div", { class: "run-row" },
    el("button", {
      class: "btn primary", text: thermal.running ? "Computing…" : "Compute", disabled: !up || thermal.running,
      title: up ? "Run the files on this page, and compute the payload's heat account" : "Start the editor's server to compute the account",
      onclick: workOutThermal,
    }),
    el("button", {
      class: "btn", text: "Balance", disabled: !results || !heater || thermal.running,
      title: heater ? `Set each mode's heater power to its balancing power, in the heater row ${heater.id}` : "The payload's consumption table has no heater row",
      onclick: () => { balanceHeaters(heater, results.modes); changed(true); },
    }),
    status ? el("span", { class: "hint", text: status }) : null));
  if (!up) parts.push(serverHelp());
  if (thermal.error) {
    parts.push(el("div", { class: "python-checks" },
      el("div", { class: "bad" }, el("b", { text: "No heat account: " }), thermal.error),
      ...thermal.checks.filter((check) => !check.ok).map((check) => el("div", { class: "bad" }, el("b", { text: check.file }), el("pre", { text: check.message })))));
  }
  if (results) {
    parts.push(el("h4", { text: "By payload mode" }));
    parts.push(accountTable(results.modes, ["payload mode", "mode"], {
      lead: [["time [min]", "min"]],
      extraHeads: ["balancing heater W", heater ? `heater W, ${heater.id}` : "heater W"],
      extra: (entry) => [
        el("td", { class: "right", text: one(entry["balancing heater [W]"]) }),
        heater ? heaterCell(heater, entry["payload mode"]) : el("td", { class: "hint", text: "no heater row" }),
      ],
    }));
    parts.push(el("p", { class: "hint", text: "The heaters are set for each payload mode. Edit a mode's heater power here, and it goes in the heater row of the payload's consumption table. Balance sets each mode's to its balancing power, rounded up to 0.1 W: the heater power that brings the mode's net energy over the run to zero, and never below zero. The powers take no margins." }));
    parts.push(el("h4", { text: "By activity" }));
    parts.push(accountTable(results.activities, ["activity", "activity"], { lead: [["occurrences", "times"], ["time [min]", "min"]] }));
    parts.push(el("h4", { text: "The net heat in since the start" }), accountPlot(results));
    if (results.orbits.length) {
      parts.push(el("h4", { text: "By whole orbit" }));
      parts.push(accountTable(results.orbits, ["orbit", "orbit"]));
    }
    parts.push(el("h4", { text: "The surfaces" }), surfaceTable(results.surfaces));
    if (results.notes.length) parts.push(el("div", { class: "notes" }, results.notes.map((text) => el("p", { class: "hint", text }))));
  }
  node.replaceChildren(...parts);
}

/** The surfaces over the run: the sun they see and the heat they absorb and emit. */
function surfaceTable(rows) {
  const columns = [
    ["lowest sun angle [deg]", "sun angle from"], ["highest sun angle [deg]", "to, deg"], ["in sun [min]", "in sun, min"],
    ["peak sun [W]", "peak sun W"], ["mean sun [W]", "mean sun W"], ["mean view factor", "view factor"], ["mean albedo [W]", "albedo W"],
    ["mean Earth infrared [W]", "Earth IR W"], ["emitted [W]", "emitted W"],
  ];
  const table = el("table", { class: "items budget account" },
    el("tr", {}, ["surface", ...columns.map(([, title]) => title)].map((h, i) => el("th", { class: i ? "right" : "", text: h }))));
  for (const entry of rows) {
    table.append(el("tr", {}, el("td", { class: "name", text: entry.surface }),
      ...columns.map(([key]) => el("td", { class: "right", text: key === "mean view factor" ? Number(entry[key]).toFixed(3) : one(entry[key]) }))));
  }
  return el("div", { class: "scroll-x" }, table);
}

/** The account's panel, which the Thermal tab shows. */
function accountPanel() {
  const node = el("div", { class: "viewer-panel account-panel", "data-thermal-account": "" });
  fillAccount(node);
  return node;
}
