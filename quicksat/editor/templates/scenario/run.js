// quicksat scenario editor: the viewer, which the editor's local server makes.
//
// A page that the server sends holds `DATA.server`: the start of its addresses,
// the server's key, which each address ends with, and the input and output folders. Its "Create the
// viewer" button sends the page's files to the server, which runs them with
// quicksat and writes the viewer into the output folder. The page asks the
// server every few seconds whether it still answers, and every 10 min while it
// is out of view, so that the server knows that a page is open. A page opened
// from a file has no server, so the button is greyed out, with how to start
// one. Stop the server, in the header, stops it when the user is done.

/** The viewer's state: the server, the run going on, and the last run's answer. */
const viewer = {
  /** `none` on a page opened from a file, `up` while the server answers, `down` once it has stopped, `moved` once it has a new key. */
  server: DATA.server ? "up" : "none",
  running: false,
  /** The last run's answer from the server, or null. */
  result: null,
  /** The viewer pages in the output folder. */
  pages: DATA.server ? [...DATA.server.viewers] : [],
};

/** The server's address for a name, such as `status`, with the key at its end. */
const serverUrl = (name) => `${DATA.server.base}${name}?key=${DATA.server.key}`;

/** The viewer page that a run of these files writes. */
const viewerPage = () => (project.hasPower && project.hasConsumption ? "power_viewer.html" : "scenario_viewer.html");

/**
 * The files to run, as the server takes them. A model, an orbit file or a
 * satellite target's file goes by the name the scenario gives it, so that the
 * run finds it there.
 */
function runFiles() {
  const key = ORBIT_KEYS[S.orbit.source];
  const named = { model: S.model.file, orbit: key ? S.orbit[key] : "", ...Object.fromEntries(satTargetFiles().map((name) => [targetKind(name), name])) };
  return projectFiles().map((file) => ({
    kind: file.kind,
    name: named[file.kind] || file.path,
    ...(file.bytes ? { base64: bytesToBase64(file.bytes) } : { text: file.text }),
  }));
}

/** Ask the server whether it still answers, and redraw the panels if that changed. */
async function checkServer() {
  if (!DATA.server || viewer.running) return;
  let now = "down";
  try {
    const response = await fetch(serverUrl("status"), { cache: "no-store" });
    if (response.ok) {
      now = "up";
      viewer.pages = (await response.json()).viewers;
    } else if (response.status === 404) now = "moved";
  } catch {
    now = "down";
  }
  setServer(now);
}

/** Note the server's state, and redraw what shows it, if it changed. */
function setServer(now) {
  if (now === viewer.server) return;
  viewer.server = now;
  drawViewerPanels();
  designerServerChanged();
  drawStopButton();
}

/** Show the header's Stop the server button while the server answers. */
function drawStopButton() {
  $("#stop-server").hidden = viewer.server !== "up";
}

/** Stop the server, after a confirm. The page stays open, with how to start the server again. */
async function stopServer() {
  if (viewer.server !== "up") return;
  const lost = unsaved() ? " Some changes on this page are not saved yet. After the stop, you can still download them from the Files tab." : "";
  if (!confirm(`Stop the editor's server? This page stays open, but it can no longer run quicksat or save into the folder.${lost}`)) return;
  let result;
  try {
    const response = await fetch(serverUrl("stop"), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    result = await response.json();
  } catch {
    // no answer: the server may have stopped already
    checkServer();
    return;
  }
  if (result.ok) setServer("down");
  else alert(result.error);
}

/** Send the page's files to the server, which runs them and writes the viewer. */
async function createViewer() {
  if (viewer.server !== "up" || viewer.running) return;
  viewer.running = true;
  viewer.result = null;
  drawViewerPanels();
  let result;
  try {
    const response = await fetch(serverUrl("run"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: runFiles() }),
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
  viewer.running = false;
  viewer.result = result;
  if (result.ok && !viewer.pages.includes(result.page)) viewer.pages.push(result.page);
  // the run read the files with quicksat's loaders: their full check is now this one
  const ran = new Set(result.checks.map((check) => check.file));
  DATA.checks = [...DATA.checks.filter((check) => !ran.has(check.file)), ...result.checks];
  drawView();
  checkServer();
}

/** The link that opens a viewer page, in one browser tab that each opening reuses. */
function viewerLink(name, text) {
  return el("a", { class: "btn", href: serverUrl(`viewer/${name}`), target: "quicksat-viewer", text });
}

/** The command that starts the server, for the information box: the one that started it, if any. */
const serveCommand = () => (DATA.server ? DATA.server.command : `python -m quicksat.editor serve ${DATA.label || "FOLDER"} OUTPUT`);

/** Why the button is greyed out, and how to start the server. */
function serverHelp() {
  const command = el("pre", { class: "command", text: serveCommand() });
  if (viewer.server === "none") {
    return el("div", { class: "info" },
      el("h4", { text: "Start the editor's server" }),
      el("p", { text: "This page was opened from a file, so it cannot run quicksat. The editor's server can. It serves this page from your computer, runs the files and writes the viewer." }),
      el("p", { text: "In a terminal, where quicksat is installed, run:" }),
      command,
      el("p", { html: `Give the folder of input files in place of <code>${escapeHtml(DATA.label || "FOLDER")}</code>, and the folder for the viewer in place of <code>OUTPUT</code>. The server opens this editor in your browser, with the folder's files. Keep its window open while you work.` }),
      el("p", { text: "The changes made on this page are not in the folder yet. Save them first, and put the files back in the folder." }));
  }
  const unsaved = "The changes made on this page are not in the folder yet. Save them first, and put the files back in the folder.";
  if (viewer.server === "moved") {
    return el("div", { class: "info" },
      el("h4", { text: "The server has a new key" }),
      el("p", { text: `The server was started again, so this page's key no longer works. Open the address that the server printed when it started. ${unsaved}` }));
  }
  return el("div", { class: "info" },
    el("h4", { text: "The server has stopped" }),
    el("p", { text: `This page cannot reach the editor's server, so it cannot run the files. The server stops when you click Stop the server, or by itself after ${DATA.server.idle_h} h with no editor page open. To start it again, run this in a terminal:` }),
    command,
    el("p", { text: `Then open the address it prints: each start has a new key. ${unsaved}` }));
}

/** What the last run said: where the viewer went, or why there is none. */
function runResult() {
  const result = viewer.result;
  if (viewer.running) return el("p", { class: "hint", text: "quicksat is running the files. This takes a few seconds, or more for a long run." });
  if (!result) return null;
  if (!result.ok) {
    return el("div", { class: "python-checks" },
      el("div", { class: "bad" }, el("b", { text: "No viewer: " }), result.error),
      ...result.checks.filter((check) => !check.ok).map((check) => el("div", { class: "bad" }, el("b", { text: check.file }), el("pre", { text: check.message }))));
  }
  return el("div", { class: "run-result" },
    el("p", {}, el("span", { class: "ok", text: "Viewer written " }), `in ${result.seconds} s, to ${DATA.server.output}/${result.page}.`),
    el("details", {}, el("summary", { text: "The run's results" }), el("pre", { class: "report", text: result.report })));
}

/** Fill a viewer panel: the button, the link to the viewer, and the last run. */
function fillViewerPanel(node) {
  const up = viewer.server === "up";
  const page = viewerPage();
  const exists = viewer.pages.includes(page);
  node.replaceChildren(...[
    el("div", { class: "run-row" },
      el("button", {
        class: "btn primary", "data-create-viewer": "",
        text: viewer.running ? "Running…" : exists ? "Update the viewer" : "Create the viewer",
        disabled: !up || viewer.running,
        title: up ? `Run the files on this page, and write ${page}` : "Start the editor's server to run the files",
        onclick: createViewer,
      }),
      up && exists && !viewer.running ? viewerLink(page, "Open the viewer") : null),
    up ? el("p", { class: "hint", text: `The run uses the files as they are on this page, saved or not. It writes the viewer into ${DATA.server.output}/, and does not change the files in ${DATA.server.folder}/.` }) : serverHelp(),
    runResult(),
  ].filter(Boolean));
}

/** A panel for the viewer, which the Files tab and the last Setup step show. */
function viewerPanel() {
  const node = el("div", { class: "viewer-panel", "data-viewer-panel": "" });
  fillViewerPanel(node);
  return node;
}

/** Fill every viewer panel on the page again. */
function drawViewerPanels() {
  for (const node of document.querySelectorAll("[data-viewer-panel]")) fillViewerPanel(node);
}

if (DATA.server) {
  // every few seconds in view, and every 10 min out of it: the server stops by
  // itself once no page has asked for `DATA.server.idle_h`
  setInterval(() => document.visibilityState === "visible" && checkServer(), 4000);
  setInterval(() => document.visibilityState !== "visible" && checkServer(), 600000);
  window.addEventListener("focus", checkServer);
  $("#stop-server").addEventListener("click", stopServer);
  drawStopButton();
}
