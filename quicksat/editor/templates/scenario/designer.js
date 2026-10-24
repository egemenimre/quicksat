// quicksat scenario editor: the Activity Designer, on the Activities tab.
//
// With the editor's server, the tab shows the run in a frame above the list of
// activities: the map, and the timeline with each target's passes. Generate
// scenario sends the page's files to the server, which runs the scenario alone,
// once or with repeats, and writes nothing. The frame then loads the viewer's
// page with the run inside. The frame and the list tell each other which
// activity is selected, through messages. Save into the folder writes the
// scenario file into the input folder, through the server. A page opened from a
// file, or whose server has stopped, shows the list alone.

/** The designer's state: the last run, the frame, and the last save. */
const designer = {
  /** Whether the list repeats until the run ends. Off at first, and kept in no file. */
  repeat: false,
  running: false,
  saving: false,
  /** The server's answer to the last run, or null. */
  result: null,
  /** Each activity as the last run read it, to tell which rows changed since. */
  ranRows: [],
  /** Whether anything on the page changed since the last run. */
  stale: false,
  /** How many changes the page has had, to tell whether a run's answer is still current. */
  changes: 0,
  /** The time cursor and the zoom that the frame last reported, in seconds, or null. */
  view: null,
  /** How many times the frame has loaded a run, so that each load is a new address. */
  loads: 0,
  /** The frame, made the first time the tab is shown with the server. */
  frame: null,
  /** What the last save said: `{ok, text}`, or null. */
  saved: null,
};

/** Whether the designer can run: the page came from the editor's server, which still answers. */
const designing = () => server.state === "up";

/** An activity's fields that the run reads, as text, to compare with the last run's. */
const activityKey = (item) =>
  item ? JSON.stringify([item.title, item.end, item.attitude, item.mode, item.constraint]) : "";

/** A time in seconds, as hours and minutes. */
function lengthText(seconds) {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min` : `${minutes} min`;
}

// ---------------------------------------------------------------- the frame

/** Send a message to the frame: the viewer's page, from the same server. */
function tellFrame(type, fields = {}) {
  const frame = designer.frame && designer.frame.contentWindow;
  if (frame) frame.postMessage({ source: "quicksat-designer", type, ...fields }, location.origin);
}

/** The number of the selected activity in the list, from 1, or null. */
function selectedNumber() {
  const selection = state.selection;
  if (!selection || selection.kind !== "activity") return null;
  const index = S.activities.indexOf(selection.item);
  return index >= 0 ? index + 1 : null;
}

/** Tell the frame which activity the list has selected. `select` in view3d.js calls it. */
function sendSelection() {
  if (designer.frame) tellFrame("select", { number: selectedNumber() });
}

/** The frame picked an activity, or none: select its row, and bring it into view. */
function pickedInFrame(number) {
  const item = number ? S.activities[number - 1] : null;
  select(item ? { kind: "activity", item } : null);
  if (!item) return;
  const row = [...document.querySelectorAll("#sheet-activities .items tr")].find((tr) => tr._selection && tr._selection.item === item);
  if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

window.addEventListener("message", (event) => {
  const message = event.data;
  if (!designer.frame || event.origin !== location.origin || event.source !== designer.frame.contentWindow) return;
  if (!message || message.source !== "quicksat-designer") return;
  if (message.type === "ready") sendSelection();
  else if (message.type === "pick") pickedInFrame(Number.isInteger(message.number) ? message.number : null);
  else if (message.type === "view" && Number.isFinite(message.t)) designer.view = { t: message.t, zoom: message.zoom };
});

/** The frame's address for the last run, with the view it had, so that the view stays where it was. */
function frameAddress() {
  const view = designer.view;
  const zoom = view && Array.isArray(view.zoom) ? `&zoom=${view.zoom.map((v) => v.toFixed(1)).join(",")}` : "";
  const hash = view ? `#t=${view.t.toFixed(1)}${zoom}` : "";
  return `${serverUrl("designer")}&load=${++designer.loads}${hash}`;
}

/** The split between the frame and the list, as the frame's height in pixels, which the browser keeps. */
const SPLIT_KEY = "quicksat-designer-split";

function setSplit(height) {
  const pageNode = $("#page-activities");
  const most = Math.max(160, pageNode.clientHeight - 140);
  pageNode.style.setProperty("--frame-height", `${Math.round(Math.min(Math.max(height, 160), most))}px`);
}

/** Make the frame and its divider, once. A frame moved in the page would load again, so it stays put. */
function makeFrame() {
  if (designer.frame) return;
  designer.frame = el("iframe", { title: "The run, as the viewer shows it", src: serverUrl("designer") });
  $("#designer-frame").append(designer.frame);
  try {
    const stored = Number(localStorage.getItem(SPLIT_KEY));
    if (stored > 0) setSplit(stored);
  } catch {
    // No storage, as in some private windows: the frame keeps its first height
  }
  const divider = $("#designer-divider");
  divider.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    const pageNode = $("#page-activities");
    pageNode.classList.add("dragging");
    const top = pageNode.getBoundingClientRect().top;
    const move = (e) => setSplit(e.clientY - top);
    const up = () => {
      pageNode.classList.remove("dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      try {
        localStorage.setItem(SPLIT_KEY, String(designer.frame.parentNode.clientHeight));
      } catch {
        // The split then lasts until the page is closed
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
}

/** Show or hide the frame, as the server answers, and run once when the tab first opens. */
function showDesigner() {
  const on = state.tab === "activities" && designing();
  $("#page-activities").classList.toggle("designing", on);
  if (!on) return;
  makeFrame();
  if (!designer.result && !designer.running) generate();
}

// ---------------------------------------------------------------- the run

/** Send the page's files to the server, which runs the scenario for the frame. */
async function generate() {
  if (!designing() || designer.running) return;
  designer.running = true;
  const ran = S.activities.map(activityKey);
  const changes = designer.changes;
  drawDesignerBar();
  let result;
  try {
    const response = await fetch(serverUrl("design"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: runFiles(), repeat: designer.repeat }),
    });
    const text = await response.text();
    try {
      result = JSON.parse(text);
    } catch {
      result = { ok: false, error: `The server refused the run: ${text}`, checks: [] };
    }
  } catch {
    result = { ok: false, error: "The server did not answer. It may have stopped: see its window.", checks: [] };
  }
  designer.running = false;
  designer.result = result;
  if (result.ok) {
    designer.ranRows = ran;
    // a change made while the run was under way is not in it
    designer.stale = designer.changes !== changes;
    designer.frame.src = frameAddress();
  }
  drawDesignerBar();
  refreshRowNotes();
  checkServer();
}

/**
 * The results of one activity in the last run, as a line under its title, or
 * null without the server. The line is there before the first run too, so that
 * a run fills it without drawing the list again.
 */
function rowNote(index) {
  if (!designing()) return null;
  const node = el("div", { class: "run-text", "data-run-note": index });
  fillRowNote(node, index);
  return node;
}

function fillRowNote(node, index) {
  const result = designer.result;
  if (!result || !result.ok) {
    node.className = "run-text";
    node.textContent = "";
    return;
  }
  if (activityKey(S.activities[index]) !== (designer.ranRows[index] || "")) {
    node.className = "run-text changed";
    node.textContent = "changed since the last run";
    return;
  }
  const row = result.rows[index];
  if (!row) {
    node.className = "run-text";
    node.textContent = "";
    return;
  }
  node.className = "run-text";
  node.replaceChildren(...rowParts(row, result).map(([kind, text]) =>
    el("div", { class: `run-${kind}` }, PART_LABELS[kind] ? el("b", { text: `${PART_LABELS[kind]}: ` }) : null, text)));
}

/**
 * How each status of an occurrence counts, as the viewer's activity table
 * colours it: a `fail`, a `warn`ing to look at, or `plain`.
 */
const STATUS_KINDS = {
  "outside constraint": "fail",
  "negative duration": "fail",
  "event never came": "warn",
  "slew starts early": "warn",
  "cut at end": "plain",
};

/** The label in front of a part of each kind. */
const PART_LABELS = { fail: "FAIL", warn: "WARNING" };

/**
 * What a run made of one activity, from the server's row for it, as short
 * parts, each with its kind. The first, a `count`, says how many times the
 * activity came. Each status other than ok follows, by its kind in
 * `STATUS_KINDS`. A turn faster than the slew block allows is a warning.
 */
function rowParts(row, result) {
  const times = (count) => (count === 1 ? "once" : `${count} times`);
  const parts = [["count", row.count === 0 ? "not reached in the run" : times(row.count)]];
  for (const [status, count] of Object.entries(row.statuses)) {
    const outside = status === "outside constraint" && row.outside_s !== null ? `, up to ${Number(row.outside_s.toFixed(1))} s outside` : "";
    parts.push([STATUS_KINDS[status] || "plain", `${status} ${times(count)}${outside}`]);
  }
  if (row.excesses) {
    const limits = [];
    if (result.max_rate_deg_s !== null && row.peak_rate_deg_s > result.max_rate_deg_s) {
      limits.push(`${row.peak_rate_deg_s.toFixed(2)} deg/s, limit ${result.max_rate_deg_s} deg/s`);
    }
    if (result.max_acceleration_deg_s2 !== null && row.peak_acceleration_deg_s2 > result.max_acceleration_deg_s2) {
      limits.push(`${row.peak_acceleration_deg_s2.toFixed(4)} deg/s², limit ${result.max_acceleration_deg_s2} deg/s²`);
    }
    parts.push(["warn", `turns faster than the slew limits ${times(row.excesses)}: ${limits.join(" and ")}`]);
  }
  return parts;
}

/** Update each row's results in place, after a change that drew nothing again. */
function refreshRowNotes() {
  for (const node of document.querySelectorAll("[data-run-note]")) fillRowNote(node, Number(node.dataset.runNote));
}

// ---------------------------------------------------------------- the save

/** Why the scenario cannot be saved into the folder now, or "". */
function saveProblem() {
  const name = project.names.scenario;
  if (!(sources.scenario && sources.scenario.how === "page") || !(name in (DATA.server.sha256 || {}))) {
    return `The scenario on this page was not written from ${DATA.server.folder}/, so it is not saved there. Download it instead.`;
  }
  if (!S.activities.length) return "A saved scenario needs at least one activity.";
  return "";
}

/** Write the scenario file into the input folder, through the server, after a confirm. */
async function saveIntoFolder() {
  if (!designing() || designer.saving) return;
  const problem = saveProblem();
  if (problem) {
    designer.saved = { ok: false, text: problem };
    drawDesignerBar();
    return;
  }
  const name = project.names.scenario;
  const open = openReview().filter((item) => item.kind === "scenario").length;
  const lost = open ? ` ${open} comment${open > 1 ? "s" : ""} written by hand would be lost: review them in the Files tab first.` : "";
  if (!confirm(`Replace ${name} in ${DATA.server.folder}/ with the scenario on this page? Its comments are written as the page holds them.${lost}`)) return;
  designer.saving = true;
  drawDesignerBar();
  const file = projectFiles().find((f) => f.kind === "scenario");
  let result;
  try {
    const response = await fetch(serverUrl("save"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: [{ name, text: file.text, sha256: DATA.server.sha256[name] }] }),
    });
    result = await response.json();
  } catch {
    result = { ok: false, error: "The server did not answer. It may have stopped: see its window." };
  }
  designer.saving = false;
  if (result.ok) {
    for (const saved of result.files) DATA.server.sha256[saved.name] = saved.sha256;
    markSaved(["scenario"], "folder");
    refreshFiles();
    designer.saved = { ok: true, text: `Saved into ${DATA.server.folder}/${name}.` };
  } else {
    designer.saved = { ok: false, text: result.error };
  }
  drawDesignerBar();
}

// ---------------------------------------------------------------- the bar

/** The run's length and one pass of the list, in time and in orbits. */
function periodText(result) {
  const orbits = (seconds) => (seconds / result.period_s).toFixed(2);
  const run = `Scenario: ${lengthText(result.duration_s)}, ${orbits(result.duration_s)} orbits`;
  if (result.pass_s === null) return `${run} · one pass of the list is longer than the run`;
  if (result.pass_s === 0) return `${run} · the list is empty`;
  return `${run} · one pass of the list: ${lengthText(result.pass_s)}, ${orbits(result.pass_s)} orbits`;
}

/** The status of the last run, as a few words. */
function statusText() {
  const result = designer.result;
  if (designer.running) return ["", "Generating…"];
  if (!result) return ["", ""];
  if (!result.ok) return ["bad", result.error];
  if (designer.stale) return ["warn", "Changed since the last run"];
  return ["ok", `Generated in ${result.seconds} s`];
}

/** Fill the bar above the list: the buttons, the status, the period, and the run's warnings or errors. */
function fillDesignerBar(node) {
  if (!designing()) {
    node.replaceChildren(serverHelp());
    return;
  }
  const result = designer.result;
  const [cls, status] = statusText();
  const refused = result && !result.ok ? result.checks.filter((check) => !check.ok) : [];
  const warnings = result && result.ok ? result.warnings : [];
  node.replaceChildren(...[
    el("div", { class: "run-row" },
      el("button", {
        class: "btn primary", text: designer.running ? "Generating…" : "Generate scenario", disabled: designer.running,
        title: "Run the scenario on this page, as it is now, and show the result above", onclick: generate,
      }),
      el("label", { class: "check", title: "Repeat the list until the run ends, as the scenario file does" },
        // during a run, the change waits for the next one, and the bar says so
        el("input", { type: "checkbox", checked: designer.repeat, onchange: (e) => { designer.repeat = e.target.checked; designerChanged(); generate(); } }),
        " Repeat the list"),
      el("button", {
        class: "btn", text: designer.saving ? "Saving…" : "Save into the folder", disabled: designer.saving,
        title: `Write ${project.names.scenario} into ${DATA.server.folder}/`, onclick: saveIntoFolder,
      }),
      el("span", { class: `run-status ${cls}`, text: status })),
    result && result.ok ? el("p", { class: "hint period", text: periodText(result) }) : null,
    designer.saved ? el("p", { class: designer.saved.ok ? "saved ok" : "saved bad", text: designer.saved.text }) : null,
    refused.length ? el("div", { class: "python-checks" }, ...refused.map((check) => el("div", { class: "bad" }, el("b", { text: check.file }), el("pre", { text: check.message })))) : null,
    warnings.length ? el("div", { class: "run-warnings" }, ...warnings.map((text) => el("p", { class: "warn" }, el("b", { text: "WARNING: " }), text))) : null,
  ].filter(Boolean));
  $("#designer-frame").classList.toggle("running", designer.running);
}

/** The bar above the list, for the tab's top. */
function designerBar() {
  const node = el("div", { class: "designer-bar viewer-panel", "data-designer-bar": "" });
  fillDesignerBar(node);
  return node;
}

/** Fill the bar again, wherever it is. */
function drawDesignerBar() {
  for (const node of document.querySelectorAll("[data-designer-bar]")) fillDesignerBar(node);
}

/** A change anywhere on the page makes the last run out of date, and any run under way. */
function designerChanged() {
  designer.changes += 1;
  if (designer.result && designer.result.ok && !designer.stale) {
    designer.stale = true;
    drawDesignerBar();
  }
  refreshRowNotes();
}

/**
 * The server answered again, or stopped: show or hide the frame, and draw the
 * tab again, with each row's results or without them.
 */
function designerServerChanged() {
  showDesigner();
  if (state.tab === "activities") drawView();
  else drawDesignerBar();
}

/** The button on the Setup step's plain list that opens the Activity Designer. */
function openDesignerButton() {
  return el("div", { class: "add-row" },
    el("button", { class: "btn primary", text: "Open the Activity Designer", onclick: () => showTab("activities") }),
    el("span", { class: "hint", text: designing() ? "The Activities tab runs the list and shows the result above it." : "The Activities tab runs the list with the editor's server." }));
}
