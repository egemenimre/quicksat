// quicksat sizing editor: the Budgets tab, every budget as quicksat works it out.
//
// Python works out the budgets, with the same methods as the notebooks: when it
// writes the page, and on the editor's server a moment after each change. The
// results arrive as text, so the page formats no number of its own. Without the
// server, the tab shows the results from when the page was written, and says
// which files have changed since.

/** The budgets, as the tab shows them, and its controls. */
const budgets = {
  /** The results shown: from when Python wrote the page, or from the server's last work-out. */
  results: DATA.results || null,
  /** When the server worked them out, or null for the page's own. */
  at: null,
  /** The files' texts that the results come from, by kind, to tell when the page has changed since. */
  texts: null,
  running: false,
  /** Whether a change came in while a work-out was going on. */
  again: false,
  /** Why the last work-out failed, or "". */
  error: "",
  timer: null,
  /** The tab's page: overview, mass, deltav, data or agility. */
  view: "overview",
  inOrbit: true,
  subtotals: false,
  massComments: true,
  deltavComments: true,
  axis: "roll",
  degraded: false,
  /** The slew that the slew table checks against, by name, or "" for none. */
  target: null,
};

const BUDGET_VIEWS = [
  { id: "overview", title: "Overview", intro: "Summary dashboard for the budgets." },
  { id: "mass", title: "Mass", files: ["equipment", "mass"], intro: "The mass budget, as mass_budget.ipynb shows it." },
  { id: "deltav", title: "Delta-V", files: ["manoeuvres", "deltav", "mission"], intro: "The delta-V budget and its propellant, as delta_v_budget.ipynb shows them." },
  { id: "data", title: "Data", files: ["data", "mission", "requirements"], intro: "The payload data flow and the storage, as data_budget.ipynb shows them." },
  { id: "agility", title: "Agility", files: ["agility", "mission", "requirements"], intro: "The slews about each axis, as agility_roll.ipynb and agility_pitch.ipynb show them." },
];

// ---------------------------------------------------------------- the work-out

/** The files' texts on the page now, by kind. */
const budgetTexts = () => Object.fromEntries(projectFiles().map((file) => [file.kind, file.text]));

/** The kinds of the files that changed since the results were worked out. */
function changedSince() {
  if (!budgets.texts) return [];
  const now = budgetTexts();
  return Object.keys(now).filter((kind) => now[kind] !== budgets.texts[kind]);
}

/** Work the budgets out again a moment after a change, while the server answers. */
function scheduleBudgets() {
  clearTimeout(budgets.timer);
  if (server.state === "up" && changedSince().length) budgets.timer = setTimeout(workOutBudgets, 600);
  refreshBudgets();
}

/** Send the page's files to the server, which works out every budget. */
async function workOutBudgets() {
  if (server.state !== "up") return;
  if (budgets.running) { budgets.again = true; return; }
  const texts = budgetTexts();
  budgets.running = true;
  refreshBudgets();
  let result;
  try {
    const response = await fetch(serverUrl("budgets"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: Object.entries(texts).map(([kind, text]) => ({ kind, text })) }),
    });
    const text = await response.text();
    try {
      result = JSON.parse(text);
    } catch {
      result = { ok: false, error: `The server refused the work-out: ${text}` };
    }
  } catch {
    result = { ok: false, error: "The server did not answer. It may have stopped: see its window." };
  }
  budgets.running = false;
  if (result.ok) {
    budgets.results = result.results;
    budgets.texts = texts;
    budgets.at = new Date();
    budgets.error = "";
  } else budgets.error = result.error;
  if (budgets.again || (result.ok && changedSince().length)) {
    budgets.again = false;
    workOutBudgets();
  }
  refreshBudgets();
  if (!result.ok) checkServer();
}

/** Redraw what shows the budgets: the tab's title, and the tab when it is open. */
function refreshBudgets() {
  showProblems();
  if (state.tab === "budgets") drawBudgets();
}

// ---------------------------------------------------------------- what the results say

const resultsOf = (key) => (budgets.results ? budgets.results.budgets[key] : null);
const checksOf = (key) => (budgets.results ? budgets.results.checks.filter((check) => check.budget === key) : []);

/** The budgets with a failing check, for the tab's title. */
const failingBudgets = () => new Set((budgets.results ? budgets.results.checks : []).filter((check) => !check.passes).map((check) => check.budget)).size;

/** A budget's mark in the list: whether its checks pass, or why there are none. */
function budgetMark(key) {
  if (key === "overview") {
    const failing = failingBudgets();
    return failing ? ["✕", "problem", `${failing} budget${failing > 1 ? "s" : ""} with a failing check`] : ["✓", "visited", "every check passes"];
  }
  const results = resultsOf(key);
  if (!results) return ["–", "off", "the folder holds no files for it"];
  if (results.error) return ["!", "problem", "quicksat cannot work it out"];
  const checks = checksOf(key);
  if (!checks.length) return ["–", "", "no check"];
  return checks.every((check) => check.passes) ? ["✓", "visited", "its checks pass"] : ["✕", "problem", "a check fails"];
}

// ---------------------------------------------------------------- drawing

/** A table of text, as Python sent it. `hide` leaves out columns by their key. */
function budgetTable(table, { hide = [] } = {}) {
  const shown = table.columns.map((column, i) => [column, i]).filter(([column]) => !hide.includes(column.key));
  const node = el("table", { class: "items budget" },
    el("tr", {}, shown.map(([column]) => el("th", { class: column.number ? "right" : "", text: column.title }))));
  for (const row of table.rows) {
    node.append(el("tr", { class: `rt-${row.type}` },
      shown.map(([column, i]) => el("td", { class: [column.number ? "right" : "", `col-${column.key}`].join(" "), text: row.cells[i] }))));
  }
  return el("div", { class: "scroll-x" }, node);
}

/** A card, as on the other tabs, with a note of where its table comes from. */
function budgetCard(title, body, { files = "", source = "", wide = false } = {}) {
  return el("div", { class: "card" + (wide ? " wide" : "") },
    el("div", { class: "card-head" },
      el("span", { class: "title" }, el("b", { text: title })),
      files ? el("span", { class: "file", text: files }) : null,
      el("span", { class: "spacer" }),
      source ? el("span", { class: "source", text: source, title: "The same table as the notebook's, from the same method" }) : null),
    el("div", { class: "card-body" }, body));
}

function figuresRow(figures) {
  return el("div", { class: "figs" }, figures.map((figure) => el("div", { class: "fig" + (figure.bad ? " bad" : "") },
    el("div", { class: "k", text: figure.label }),
    el("div", { class: "v" }, figure.value, figure.unit ? el("u", { text: figure.unit }) : null),
    el("div", { class: "s", text: figure.note }))));
}

/** The checks, with their verdicts and the files their limits come from. */
function checksTable(checks) {
  const table = el("table", { class: "items budget checks" },
    el("tr", {}, ["", "check", "", "design", "limit", "spare", "margin", "from"].map((h, i) => el("th", { class: i >= 3 && i <= 6 ? "right" : "", text: h }))));
  for (const check of checks) {
    const tone = check.passes ? "" : "neg";
    table.append(el("tr", { class: check.passes ? "" : "bad-row" },
      el("td", {}, el("span", { class: `verdict ${check.passes ? "pass" : "fail"}`, text: check.verdict })),
      el("td", { class: "name", text: check.check }),
      el("td", { class: "wrap", text: check.description }),
      el("td", { class: "right", text: check.design }),
      el("td", { class: "right", text: check.limit }),
      el("td", { class: `right ${tone}`, text: check.spare }),
      el("td", { class: `right ${tone}`, text: check.margin }),
      el("td", { class: "file wrap", text: check.files.join(", ") })));
  }
  return el("div", { class: "scroll-x" }, table);
}

/** Two choices or more, as the editors' radio rows draw them. */
function choiceRow(options, current, choose) {
  return el("div", { class: "radio-row" }, options.map(([value, label]) => el("label", {
    class: value === current ? "on" : "",
    text: label,
    onclick: () => { choose(value); drawBudgets(); },
  })));
}

function tick(label, value, choose) {
  return el("label", { class: "tick" }, el("input", { type: "checkbox", checked: value, onchange: (e) => { choose(e.target.checked); drawBudgets(); } }), label);
}

/** What a budget's page shows when there are no results for it. */
function missingBudget(key) {
  const results = resultsOf(key);
  if (!budgets.results) return el("p", { class: "hint", text: "The page holds no results. Write the page again, or start the editor's server." });
  if (!results) return el("p", { class: "hint", text: "The folder holds no files for this budget, so there is nothing to work out." });
  return el("div", { class: "budget-error" }, el("b", { text: "quicksat cannot work out this budget: " }), results.error);
}

function overviewBody() {
  const results = budgets.results;
  if (!results) return [missingBudget("overview")];
  const parts = [figuresRow(results.overview)];
  parts.push(budgetCard("Checks", results.checks.length
    ? [checksTable(results.checks), el("p", { class: "hint", text: "The margin is the spare as a share of what the design needs or uses. The requirements come from requirements.yaml, on the Requirements tab." })]
    : el("p", { class: "hint", text: "No budget has a check yet. The delta-V budget checks its propellant, and the data and agility budgets check the requirements in requirements.yaml." }), { wide: true }));
  for (const note of results.notes) parts.push(el("div", { class: "budget-error", text: note }));
  return parts;
}

/** A budget's checks, above its tables, when it has any. */
function ownChecks(key) {
  const checks = checksOf(key);
  return checks.length ? budgetCard("Checks", checksTable(checks), { wide: true }) : null;
}

function massBody() {
  const results = resultsOf("mass");
  if (!results || results.error) return [missingBudget("mass")];
  const t = results.tables;
  const variant = t.budget[`${budgets.inOrbit ? 1 : 0}${budgets.subtotals ? 1 : 0}`];
  return [
    figuresRow(results.figures),
    el("div", { class: "controls" },
      choiceRow([[true, "In orbit"], [false, "On the ground (incl. launcher's side)"]], budgets.inOrbit, (v) => { budgets.inOrbit = v; }),
      tick("subsystem subtotals", budgets.subtotals, (v) => { budgets.subtotals = v; }),
      tick("comments", budgets.massComments, (v) => { budgets.massComments = v; })),
    budgetCard("Mass budget", budgetTable(variant, { hide: budgets.massComments ? [] : ["comments"] }), { files: fileList(["equipment", "mass"]), source: "MassBudget.tabulated_mass()", wide: true }),
    el("div", { class: "pair" },
      budgetCard("By location", budgetTable(t.by_location), { source: "by_location()" }),
      budgetCard("By subsystem", budgetTable(t.by_subsystem), { source: "by_subsystem()" }),
      budgetCard("Through the mission", budgetTable(t.points), { source: "on_ground_mass(), in_orbit_mass()" })),
  ];
}

function deltavBody() {
  const results = resultsOf("deltav");
  if (!results || results.error) return [missingBudget("deltav")];
  const t = results.tables;
  return [
    figuresRow(results.figures),
    ownChecks("deltav"),
    el("div", { class: "controls" }, tick("comments", budgets.deltavComments, (v) => { budgets.deltavComments = v; })),
    budgetCard("Delta-V budget", budgetTable(t.budget, { hide: budgets.deltavComments ? [] : ["comments"] }), { files: fileList(["manoeuvres", "deltav"]), source: "DeltaVBudget.tabulated_deltav()", wide: true }),
    el("div", { class: "pair" },
      budgetCard("By phase", budgetTable(t.by_phase), { source: "by_phase()" }),
      budgetCard("By type", budgetTable(t.by_type), { source: "by_type()" }),
      t.propellant ? budgetCard("Propellant", budgetTable(t.propellant), { source: "propellant_mass()" }) : null),
  ];
}

function dataBody() {
  const results = resultsOf("data");
  if (!results || results.error) return [missingBudget("data")];
  const t = results.tables;
  return [
    figuresRow(results.figures),
    ownChecks("data"),
    el("div", { class: "pair two" },
      budgetCard("Data budget", budgetTable(t.budget), { files: fileList(["data", "mission"]), source: "DataBudget.tabulated_data()" }),
      budgetCard("Storage", budgetTable(t.storage), { source: "storage_required()" })),
  ];
}

function agilityBody() {
  const results = resultsOf("agility");
  if (!results || results.error) return [missingBudget("agility")];
  const targets = results.slews.filter((slew) => slew.axis === budgets.axis);
  if (budgets.target === null || (budgets.target && !targets.some((slew) => slew.name === budgets.target))) budgets.target = targets.length ? targets[0].name : "";
  const variant = results.variants[`${budgets.axis}|${budgets.degraded ? 1 : 0}`];
  const targetSelect = el("select", { onchange: (e) => { budgets.target = e.target.value; drawBudgets(); } },
    [...targets.map((slew) => el("option", { value: slew.name, text: `${slew.name}: ${slew.text}` })), el("option", { value: "", text: "no slew" })]);
  targetSelect.value = budgets.target;
  const table = variant.error ? null : variant.tables[budgets.target];
  return [
    ownChecks("agility"),
    el("div", { class: "controls" },
      choiceRow([["roll", "Roll"], ["pitch", "Pitch"]], budgets.axis, (v) => { budgets.axis = v; budgets.target = null; }),
      tick("one wheel failed", budgets.degraded, (v) => { budgets.degraded = v; }),
      el("label", { class: "tick" }, "check against ", targetSelect),
      el("span", { class: "hint", text: `For the inertia case ${results.selected}, which the Agility tab selects.` })),
    variant.error ? el("div", { class: "budget-error" }, el("b", { text: `quicksat cannot work out the inertia case ${results.selected}: ` }), variant.error) : figuresRow(variant.figures),
    table ? budgetCard("Slew table", budgetTable(table), { files: fileList(["agility", "mission"]), source: "AgilityBudget.tabulated_agility()", wide: true }) : null,
    budgetCard("Inertia cases", budgetTable(results.tables.cases), { source: "for each case, as agility_roll.ipynb compares them", wide: true }),
  ];
}

const fileList = (kinds) => kinds.map((kind) => project.names[kind]).join(", ");

/** The line that says where the figures come from, and how fresh they are. */
function budgetsState() {
  const changed = changedSince().map((kind) => project.names[kind]);
  const command = DATA.server ? DATA.server.command : `python -m quicksat.editor serve ${DATA.label || "FOLDER"}`;
  if (server.state === "up") {
    if (budgets.error) return el("div", { class: "budget-error" }, el("b", { text: "The budgets were not worked out again: " }), budgets.error);
    if (budgets.running || changed.length) return el("div", { class: "budget-state", text: "Working out the budgets again, from the files on this page…" });
    const at = budgets.at ? `at ${budgets.at.toLocaleTimeString()}` : "when the page was loaded";
    return el("div", { class: "budget-state", text: `Worked out by quicksat ${at}, from the files on this page, saved or not. They follow each change.` });
  }
  const why = server.state === "none"
    ? "This page was opened from a file, so these figures are the ones quicksat worked out when Python wrote it."
    : server.state === "moved"
      ? "The editor's server was started again, so this page's key no longer works. These figures stop following your changes."
      : "The editor's server has stopped, so these figures stop following your changes.";
  const stale = changed.length ? ` ${nameList(changed)} changed since, so they may be out of date.` : "";
  return el("div", { class: "stale-banner" }, `${why}${stale} To work them out as you edit, run the editor's server, and open the address it prints:`,
    el("pre", { class: "command", text: command }));
}

/** The Budgets tab: the list of budgets, and the page of the one chosen. */
function drawBudgets() {
  const nav = el("nav", { class: "steps" }, el("div", { class: "group", text: "Budgets" }));
  for (const view of BUDGET_VIEWS) {
    const [mark, cls, title] = budgetMark(view.id);
    nav.append(el("button", { class: [view.id === budgets.view ? "current" : "", cls].join(" "), title, onclick: () => { budgets.view = view.id; drawBudgets(); } },
      el("span", { class: "num", text: mark }), view.title));
  }
  const view = BUDGET_VIEWS.find((v) => v.id === budgets.view);
  const body = { overview: overviewBody, mass: massBody, deltav: deltavBody, data: dataBody, agility: agilityBody }[view.id]();
  const scroll = document.querySelector("#page-budgets .step-body");
  const top = scroll ? scroll.scrollTop : 0;
  $("#page-budgets").replaceChildren(nav,
    el("div", { class: "step" },
      el("div", { class: "step-head" },
        el("div", {}, el("div", { class: "where", text: view.files ? `Budgets · ${fileList(view.files)}` : "Budgets" }), el("h2", { text: view.title })),
        el("p", { class: "intro", text: view.intro })),
      el("div", { class: "step-body" + (server.state !== "up" && changedSince().length ? " stale" : "") }, budgetsState(), ...body.filter(Boolean))));
  const again = document.querySelector("#page-budgets .step-body");
  if (again) again.scrollTop = top;
}
