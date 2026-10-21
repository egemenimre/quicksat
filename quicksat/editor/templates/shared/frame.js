// quicksat editor: the page's frame, which the scenario and the sizing editors
// share.
//
// The frame draws the tabs and the Setup steps, the information signs, the
// problems, the Files tab with its preview, and the review of the `#` comments
// written by hand. It opens a folder, or one file, in place of the ones the page
// holds. A page gives it these, by name:
//
//   DATA, project                 the files as read, and the project made of them
//   PAGE_TITLE, CHECKS_NOTE       the page's name, and what its checks leave out
//   TABS, STEPS, SECTIONS         the tabs, the steps and the sections
//   YAML_KINDS                    its YAML files' kinds
//   FILES                         the folder's files, by kind: [{kind}]
//   OPENERS                       how the folder, and each of its files, opens
//   projectFiles()                the files to save, each with its kind
//   fileComments(path)            the comments box of a whole file, or null
//   commentTarget(kind, path)     the block of a comment: [block, label, depth]
//   runChecks()                   its checks, which end with showProblems()
//
// and, if it needs them, the hooks in `page`. While the page has changes that
// are not saved, the frame keeps them in the browser's storage, as a draft, and
// offers it back after a reload. The help comes from the page's
// #help script, which Python fills from quicksat/editor/help/.

/** What a page may add to the frame's work. */
const page = {
  /** After a tab or a Setup step is shown. */
  onShow() {},
  /** Before a tab or a step is drawn. */
  beforeDraw() {},
  /** After a change, once the checks have run. */
  afterChange() {},
  /** Whether a tab or a step is greyed out, such as for a file the folder does not hold. */
  isOff: () => false,
  /** The text the Files tab shows for a binary file. */
  describeBinary: (file) => `A binary file of ${(file.bytes.length / 1024).toFixed(1)} kB.`,
  /** What the Files tab shows under its buttons, such as the scenario editor's viewer, or null. */
  filesExtra: () => null,
  /** The kind of a dropped file that no fixed name gives, such as a satellite target's file, or null. */
  kindOfFile: () => null,
  /** The path that the folder's opener looks for a saved file under, to read a draft back. */
  draftPath: (file) => file.path,
};

/** What the page shows: the tab, the Setup step, the open explanations, and more. */
const state = {
  tab: "setup",
  step: 0,
  visited: new Set([0]),
  openInfo: new Set(),
  writeHelp: true,
  file: "",
  pendingDelete: null,
  problems: [],
  // whether the review box in the Files tab is open: null until the user opens or closes it
  reviewOpen: null,
};

// ---------------------------------------------------------------- what reading noticed

/**
 * What the readers noticed, for each file: fields the page does not handle, and
 * values it read differently. A file opened again replaces its own notices.
 */
const notices = {
  files: {},
  reading: "",
  get unknown() { return Object.values(this.files).flatMap((file) => file.unknown); },
  get changed() { return Object.values(this.files).flatMap((file) => file.changed); },
};

/** Note something about the file being read: `unknown` or `changed`. */
function notice(kind, text) {
  const file = (notices.files[notices.reading] ||= { unknown: [], changed: [] });
  file[kind].push(text);
}

/** Read one file, with its notices in place of the ones it had. */
function readingFile(kind, read) {
  notices.reading = kind;
  notices.files[kind] = { unknown: [], changed: [] };
  try { return read(); } finally { notices.reading = ""; }
}

// ---------------------------------------------------------------- changes

let refreshTimer = 0;

/**
 * Note a change to the project. A change of structure, such as an item added,
 * deleted or renamed, redraws the current view. Every change re-runs the checks.
 */
function changed(structure = false) {
  if (structure) drawView();
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    runChecks();
    if (state.tab === "files") drawPreview();
    page.afterChange();
    keepDraft();
  }, 120);
}

// ---------------------------------------------------------------- tabs and steps

/** The file a section belongs to, by its name in this folder, and anything else it changes. */
const fileOf = (section) => (project.names[section.file] || section.file) + (section.also ? ` ${section.also}` : "");

function drawTabs() {
  $("#tabs").replaceChildren(...TABS.map((tab) => el("button", {
    "data-tab": tab.id, class: [state.tab === tab.id ? "active" : "", page.isOff(tab) ? "off" : ""].join(" "),
    onclick: () => showTab(tab.id),
  }, tab.title, el("span", { class: "count", hidden: true }))));
}

function showTab(id) {
  state.tab = id;
  state.pendingDelete = null;
  for (const section of document.querySelectorAll(".page")) section.classList.toggle("active", section.id === `page-${id}`);
  page.onShow();
  drawView();
  runChecks();
}

function showStep(i) {
  state.step = Math.max(0, Math.min(STEPS.length - 1, i));
  state.visited.add(state.step);
  state.pendingDelete = null;
  page.onShow();
  drawView();
  runChecks();
  const body = $(".step-body");
  if (body) body.scrollTop = 0;
}

function goToSection(section) {
  const step = STEPS.findIndex((s) => s.sections.includes(section));
  const tab = TABS.find((t) => (t.sections || []).includes(section));
  if (state.tab === "setup" && step >= 0) { showStep(step); return; }
  if (tab) {
    showTab(tab.id);
    const card = document.querySelector(`.card[data-section="${section}"]`);
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (step >= 0) { showTab("setup"); showStep(step); }
}

function drawView() {
  page.beforeDraw();
  drawTabs();
  const scroll = document.querySelector(".page.active .sheet, .page.active .step-body");
  const top = scroll ? scroll.scrollTop : 0;
  if (state.tab === "setup") drawSetup();
  else if (state.tab === "files") drawFiles();
  else drawSheet(TABS.find((t) => t.id === state.tab));
  const again = document.querySelector(".page.active .sheet, .page.active .step-body");
  if (again) again.scrollTop = top;
  showProblems();
}

/**
 * A section's information sign, the small "i" by its title, and the box it
 * opens. The box is open or closed for the section, wherever it is drawn: on its
 * card in a tab, and on its Setup step.
 */
function infoSign(id) {
  const info = el("div", { class: "info", html: INFO[id], hidden: !state.openInfo.has(id) });
  const ibtn = el("button", {
    class: "ibtn" + (state.openInfo.has(id) ? " on" : ""), text: "i", title: "What this is, the options and what follows",
    onclick: () => {
      if (state.openInfo.has(id)) state.openInfo.delete(id); else state.openInfo.add(id);
      info.hidden = !state.openInfo.has(id);
      ibtn.classList.toggle("on", state.openInfo.has(id));
    },
  });
  return [ibtn, info];
}

/** A theme tab: its introduction, a bar for each of its files, and a card for each section. */
function drawSheet(tab) {
  const sheet = $(`#sheet-${tab.id}`);
  const kinds = [...new Set(tab.sections.map((id) => SECTIONS[id].file))].filter((kind) => OPENERS[kind]);
  sheet.replaceChildren(el("p", { class: "sheet-intro", text: tab.intro }), ...kinds.map(fileBar));
  if (tab.top) sheet.append(tab.top() || "");
  for (const id of tab.sections) {
    const section = SECTIONS[id];
    const [ibtn, info] = infoSign(id);
    const body = el("div", { class: "card-body" }, info, el("div", { class: "problems", "data-section": id }));
    section.render(body, { setup: false });
    sheet.append(el("div", { class: "card" + (section.wide ? " wide" : ""), "data-section": id },
      el("div", { class: "card-head" }, el("span", { class: "title" }, el("b", { text: section.title })), ibtn, el("span", { class: "spacer" }), el("span", { class: "file", text: fileOf(section) })),
      body));
  }
}

function drawSetup() {
  const nav = $("#steps");
  nav.replaceChildren();
  STEPS.forEach((step, i) => {
    if (step.group) nav.append(el("div", { class: "group", text: step.group }));
    nav.append(el("button", {
      "data-step": i,
      class: [i === state.step ? "current" : "", state.visited.has(i) ? "visited" : "", page.isOff(step) ? "off" : ""].join(" "),
      onclick: () => showStep(i),
    }, el("span", { class: "num", text: i + 1 }), step.title));
  });
  const step = STEPS[state.step];
  // A step of one section has its sign by the step's title, and its box at the
  // top. A step of several has a sign by each section's heading, and the box
  // under it.
  const single = step.sections.length === 1;
  const signs = step.sections.map(infoSign);
  const form = el("div");
  if (single) form.append(signs[0][1]);
  if (step.top) form.append(step.top() || "");
  step.sections.forEach((id, k) => {
    const [ibtn, info] = signs[k];
    if (!single) form.append(el("h3", {}, SECTIONS[id].title, ibtn, el("span", { class: "file", text: fileOf(SECTIONS[id]) })), info);
    form.append(el("div", { class: "problems", "data-section": id }));
    SECTIONS[id].render(form, { setup: true });
  });
  const group = [...STEPS.slice(0, state.step + 1)].reverse().find((s) => s.group).group;
  const files = [...new Set(step.sections.map((id) => fileOf(SECTIONS[id])))].join(", ");
  $("#step").replaceChildren(
    el("div", { class: "step-head" },
      el("div", {}, el("div", { class: "where", text: `Step ${state.step + 1} of ${STEPS.length} · ${group} · ${files}` }), el("h2", {}, step.title, ...(single ? [signs[0][0]] : []))),
      el("div", { class: "step-nav" },
        el("button", { class: "btn", text: "← Back", disabled: state.step === 0, onclick: () => showStep(state.step - 1) }),
        state.step < STEPS.length - 1
          ? el("button", { class: "btn primary", text: "Next →", onclick: () => showStep(state.step + 1) })
          : el("button", { class: "btn primary", text: "Download the zip", onclick: downloadZip }))),
    el("div", { class: "step-body" }, form));
}

// ---------------------------------------------------------------- problems

/** Put the problems where they belong: the header, the tabs, the steps and the sections. */
function showProblems() {
  const errors = state.problems.filter((p) => p.level === "error");
  const chip = $("#checks-chip");
  chip.textContent = errors.length ? `${errors.length} problem${errors.length > 1 ? "s" : ""}` : "basic checks pass";
  chip.className = "chip " + (errors.length ? "bad" : "good");
  for (const tab of TABS) {
    const n = errors.filter((p) => (tab.sections || []).includes(p.section)).length;
    const count = document.querySelector(`#tabs button[data-tab=${tab.id}] .count`);
    if (count) { count.textContent = n; count.hidden = !n; }
  }
  STEPS.forEach((step, i) => {
    const button = document.querySelector(`#steps button[data-step="${i}"]`);
    if (button) button.classList.toggle("problem", errors.some((p) => step.sections.includes(p.section)));
  });
  for (const box of document.querySelectorAll(".problems[data-section]")) {
    box.replaceChildren(...state.problems.filter((p) => p.section === box.dataset.section)
      .map((p) => el("div", { class: p.level === "note" ? "note" : "", text: p.text })));
  }
  if (!$("#popover").hidden && $("#popover").dataset.kind === "checks") showChecksPopover();
  refreshFiles();
}

function showChecksPopover() {
  const pop = $("#popover");
  pop.dataset.kind = "checks";
  const where = (section) => {
    const step = STEPS.find((s) => s.sections.includes(section));
    return step ? step.title : section;
  };
  pop.replaceChildren(
    el("h4", { text: "The page's basic checks" }),
    ...state.problems.map((p) => el("a", {
      onclick: () => { goToSection(p.section); pop.hidden = true; },
      style: p.level === "note" ? "color: var(--amber)" : null,
    }, p.text, el("span", { text: `  ${where(p.section)}` }))),
    state.problems.length ? null : el("p", { text: "Nothing found." }),
    el("p", { text: `This is the simple check: names, units and ranges only. ${CHECKS_NOTE}` }),
    pythonChecks());
  pop.hidden = false;
}

/** The files that the full check refused, each with quicksat's message. */
function pythonChecks() {
  const refused = DATA.checks.filter((check) => check.ok === false);
  if (!refused.length) return null;
  return el("div", { class: "python-checks" },
    el("h4", { text: "The full check refused" }),
    ...refused.map((check) => el("div", { class: "bad" }, el("b", { text: check.file }), el("pre", { text: check.message }))));
}

// ---------------------------------------------------------------- the Files tab

function drawFiles() {
  const files = projectFiles();
  if (!files.some((f) => f.path === state.file)) state.file = files[0].path;
  const list = $("#filelist");
  list.replaceChildren(el("div", { class: "folder", text: `${project.name}/` }));
  for (const file of files) {
    list.append(el("button", {
      class: state.file === file.path ? "current" : "",
      onclick: () => { state.file = file.path; drawFiles(); },
    }, file.path, el("small", {}, file.note ? `${file.note} · ` : "", el("span", { "data-state": file.kind })),
      el("small", { class: "checks" }, "simple ", el("span", { "data-checks": file.kind }), " · full ", fullCheck("span", file.kind))));
  }
  list.append(el("div", { class: "actions" },
    el("label", {}, el("input", { type: "checkbox", checked: state.writeHelp, onchange: (e) => { state.writeHelp = e.target.checked; drawFiles(); } }), "write the # help lines"),
    el("button", { class: "btn primary", text: `download ${project.name}.zip`, onclick: downloadZip })));
  list.append(el("div", { class: "fields", style: "margin-top: 14px" },
    el("label", {}, "Folder name"),
    textInput(project, "name", { cls: "wide" })));
  const extra = page.filesExtra();
  if (extra) list.append(extra);
  for (const id of TABS.find((t) => t.id === "files").sections || []) list.append(el("div", { class: "problems", "data-section": id }));
  drawPreview(true);
  // the list is drawn anew, so fill in each file's state and simple check again
  refreshFiles();
}

/**
 * Show a file. A full redraw draws the head, the review and the file's comments
 * box. Otherwise only the text is refreshed, so typing is not interrupted.
 */
function drawPreview(full = false) {
  const files = projectFiles();
  const file = files.find((f) => f.path === state.file) || files[0];
  const preview = $("#preview");
  const text = file.bytes ? page.describeBinary(file) : null;
  const pre = preview.querySelector("pre.file");
  if (!full && pre && preview.dataset.file === file.path) {
    if (text) pre.textContent = text; else pre.innerHTML = highlight(file.text);
    return;
  }
  preview.dataset.file = file.path;
  const comments = fileComments(file.path);
  preview.replaceChildren(
    reviewPanel(),
    el("div", { class: "preview-head" },
      el("span", { class: "name", text: file.path }), file.note ? el("span", { class: "hint", text: file.note }) : null,
      el("span", { class: "spacer" }),
      el("span", { class: "hint", html: '<span style="color:var(--amber)">#</span> header &nbsp; <span style="color:#5d7598">#</span> help, rewritten &nbsp; <span style="color:var(--green)">comments</span> yours, kept' }),
      el("button", { class: "btn small", text: "download", onclick: () => download(file) })),
    comments ? el("div", { class: "preview-comments" }, comments) : el("div"),
    text ? el("pre", { class: "file", text }) : el("pre", { class: "file", html: highlight(file.text) }));
}

/** Colour a file's text: the header, the help lines, and the user's comments fields. */
function highlight(text) {
  const out = [];
  let inHeader = true;
  let blockIndent = -1;
  for (const line of text.split("\n")) {
    const indent = line.match(/^ */)[0].length;
    if (blockIndent >= 0 && (line.trim() === "" || indent > blockIndent)) { out.push(`<span class="u">${escapeHtml(line)}</span>`); continue; }
    blockIndent = -1;
    if (inHeader && line.startsWith("#")) { out.push(`<span class="h">${escapeHtml(line)}</span>`); continue; }
    inHeader = false;
    if (/^\s*#/.test(line)) { out.push(`<span class="c">${escapeHtml(line)}</span>`); continue; }
    const comments = line.match(/^(\s*(?:- )?)comments: (.*)$/);
    if (comments) {
      out.push(`<span class="u">${escapeHtml(line)}</span>`);
      if (comments[2] === "|-" || comments[2] === ">-") blockIndent = indent;
      continue;
    }
    out.push(escapeHtml(line));
  }
  return out.join("\n");
}

// ---------------------------------------------------------------- comments written by hand

const normalise = (text) => String(text).replace(/\s+/g, " ").trim().toLowerCase();

/** Every comment the editor writes itself: the header and the help. */
const generatedComments = () => new Set([...Object.values(YAML_HELP), HEADER.map((line) => line.replace(/^# ?/, "")).join(" ")].map(normalise));

/** The comments that the editor did not write, and so would replace on saving. */
let review = [];

/** List the comments of the files of `kinds`, in place of the ones they had. */
function reviewFiles(kinds) {
  const generated = generatedComments();
  review = review.filter((item) => !kinds.includes(item.kind));
  for (const kind of kinds) {
    const file = DATA.files[kind];
    if (!file || !file.comments) continue;
    for (const comment of file.comments) {
      if (generated.has(normalise(comment.text))) continue;
      const [target, label, depth = comment.path.length] = commentTarget(kind, comment.path);
      const key = comment.path.slice(depth).filter((part) => typeof part === "string").join(".");
      review.push({ kind, file: file.name, line: comment.line, path: comment.path, text: comment.text, key, target, label, status: "" });
    }
  }
  review.sort((a, b) => YAML_KINDS.indexOf(a.kind) - YAML_KINDS.indexOf(b.kind) || a.line - b.line);
}

const openReview = () => review.filter((item) => !item.status);

/** Move a comment into its block's comments. A comment on a field starts with the field's name. */
function moveComment(item) {
  const text = item.key ? `${item.key}: ${item.text.trim()}` : item.text.trim();
  item.target.comments = item.target.comments && item.target.comments.trim() ? `${item.target.comments.trim()}\n${text}` : text;
  item.status = "moved";
}

function settle(change) {
  change();
  updateBanner();
  drawView();
  changed();
}

/** The review of the comments written by hand, and what the reader could not keep. */
function reviewPanel() {
  const open = openReview();
  const panel = el("details", { class: "review", open: state.reviewOpen ?? (open.length > 0 || notices.unknown.length > 0) });
  panel.addEventListener("toggle", () => { state.reviewOpen = panel.open; });
  const count = open.length ? `${open.length} comment${open.length > 1 ? "s" : ""} written by hand` : "No comments left to review";
  panel.append(el("summary", {}, el("b", { text: count }), notices.unknown.length ? ` · ${notices.unknown.length} field${notices.unknown.length > 1 ? "s" : ""} the editor cannot keep` : ""));
  if (review.length) {
    panel.append(el("p", { class: "hint", text: "The files hold these # comments, which the editor did not write. Saving replaces every # line, so move each comment you want to keep into the comments field of its block. A comment on a field starts with the field's name." }));
    const table = el("table", { class: "items" });
    for (const item of review) {
      table.append(el("tr", {},
        el("td", { class: "hint", text: `${item.file}:${item.line}` }),
        el("td", {}, el("pre", { class: "comment-text" }, item.key ? el("span", { class: "key", text: `${item.key}: ` }) : null, item.text)),
        el("td", { class: "hint", text: `→ ${item.label}` }),
        el("td", { class: "tools" }, item.status
          ? el("span", { class: item.status === "moved" ? "done" : "hint", text: item.status === "moved" ? "moved" : "dropped" })
          : [el("button", { class: "btn small", text: "move", onclick: () => settle(() => moveComment(item)) }), " ",
             el("button", { class: "btn small danger", text: "drop", onclick: () => settle(() => { item.status = "dropped"; }) })])));
    }
    panel.append(el("div", { class: "scroll-x" }, table));
    if (open.length) {
      panel.append(el("div", { class: "add-row" },
        el("button", { class: "btn", text: "move all", onclick: () => settle(() => open.forEach(moveComment)) }),
        el("button", { class: "btn danger", text: "drop all", onclick: () => settle(() => open.forEach((item) => { item.status = "dropped"; })) })));
    }
  }
  if (notices.unknown.length) {
    panel.append(el("p", { class: "hint", text: "These fields are not in the editor, so saving leaves them out. Keep a copy of the file if you need them:" }),
      el("ul", {}, ...notices.unknown.map((text) => el("li", { text }))));
  }
  if (notices.changed.length) {
    panel.append(el("p", { class: "hint", text: "Read differently from how the files write them:" }),
      el("ul", {}, ...notices.changed.map((text) => el("li", { text }))));
  }
  return panel;
}

/** A line for the Save step: what is left to review before saving. */
function reviewNote() {
  const open = openReview();
  if (!open.length && !notices.unknown.length) return null;
  return el("p", { class: "warn" },
    open.length ? `${open.length} comment${open.length > 1 ? "s" : ""} written by hand would be lost on saving. ` : "",
    notices.unknown.length ? `${notices.unknown.length} field${notices.unknown.length > 1 ? "s are" : " is"} not in the editor, and would be left out. ` : "",
    el("button", { class: "btn small", text: "review in the Files tab", onclick: () => showTab("files") }));
}

/** The banner under the header, while there is something to review before saving. */
function updateBanner() {
  const banner = $("#banner");
  const open = openReview();
  if (!open.length && !notices.unknown.length) { banner.hidden = true; return; }
  banner.hidden = false;
  banner.replaceChildren(
    el("b", { text: "Before you save: " }),
    open.length ? `these files hold ${open.length} comment${open.length > 1 ? "s" : ""} written by hand, which saving would replace. ` : "",
    notices.unknown.length ? `${notices.unknown.length} field${notices.unknown.length > 1 ? "s are" : " is"} not in the editor. ` : "",
    el("button", { class: "btn small", text: "review them", onclick: () => showTab("files") }));
}

// ---------------------------------------------------------------- the folder's files

/** The explanation of the table of files and of the buttons, for each page's first step. */
const FILES_HELP = `<span class="k">The table of files</span>
<p><b>From</b> says where each file came from: the folder the page was written for, a folder you opened, or a file opened alone. A browser does not tell a page which folder a file opened alone came from.</p>
<p><b>State</b> says whether the file has changed: <i>unchanged</i> since it was opened, <i>modified</i>, <i>downloaded</i> when saved and not changed since, <i>saved into the folder</i> by the Activity Designer, or <i>new</i> for a file started on the page.</p>
<p><b>Simple check</b> is the page's own: names, units and ranges, run as you type. <b>Full check</b> is quicksat's own loaders, which read the files when Python wrote the page. A file opened since shows <i>not run</i>: write the page again for its full check. On a page that the Scenario Editor's server sends, a reload, or a run that creates the viewer, gives the full check too.</p>
<span class="k">Opening and saving</span>
<p><b>Open a folder</b> reads every file of the folder that the page knows, and fills every step. <b>Open</b>, on a row or on a tab, reads one file in place of that one. You can also drop a folder, or its files, on the first Setup step or anywhere on the page, and a file on its tab's bar. <b>download</b> saves one file, and the Files tab saves them all as a zip. Put the files back in the folder yourself: a browser cannot write into it.</p>
<p>Until you save, the page keeps a draft of your changes in the browser's storage, and offers it back when you reload the page or open it again.</p>`;

// ---------------------------------------------------------------- the help

// The help of the page's domains, by key, from quicksat/editor/help/: a step's
// title and information box, and the help written above a key of a saved file.
const HELP = JSON.parse($("#help").textContent);

/** Each step's information box, as HTML. */
const INFO = Object.fromEntries(Object.entries(HELP).filter(([, h]) => h.info)
  .map(([key, h]) => [key, `<h4>${h.title}</h4>\n${h.info.replace("{{files}}", FILES_HELP)}`]));

/** The help written as `#` lines above each key, when the user wants it. */
const YAML_HELP = Object.fromEntries(Object.entries(HELP).filter(([, h]) => h.file).map(([key, h]) => [key, h.file]));

/**
 * Where each file came from, by its kind: `{how, folder}`. `how` is `page` for a
 * file that Python wrote into the page, `folder` for one opened with its folder,
 * `file` for one opened alone, and `new` for one started on the page.
 */
const sources = {};

/** Each file's text, or bytes, as it was last opened or saved: a file that differs has changed. */
const savedText = {};

/**
 * How each file was last saved, by kind: `download` once the page has saved it,
 * `folder` once the editor's server has written it into the folder, and
 * otherwise not set.
 */
const savedBy = {};

/** Each file's text, or bytes, as saving would write it now, by kind. The help lines are always in. */
function currentTexts() {
  const writeHelp = state.writeHelp;
  state.writeHelp = true;
  try {
    return Object.fromEntries(projectFiles().map((file) => [file.kind, file.text ?? file.bytes]));
  } finally {
    state.writeHelp = writeHelp;
  }
}

/** Note the files of `kinds` as saved, as they are now: opened, downloaded, or saved into the folder. */
function markSaved(kinds, by = "") {
  const texts = currentTexts();
  for (const kind of kinds) {
    if (!(kind in texts)) continue;
    savedText[kind] = texts[kind];
    if (by) savedBy[kind] = by; else delete savedBy[kind];
  }
  keepDraft();
}

/**
 * Each file's state, by kind: `unchanged` since it was opened, `downloaded` or
 * `saved` into the folder and not changed since, `modified` since any of them,
 * `new` for a file never saved, or `absent` for one the page does not save.
 */
function fileStates() {
  const texts = currentTexts();
  const stateOf = (kind) => {
    if (!(kind in texts)) return "absent";
    if (!(kind in savedText)) return "new";
    if (texts[kind] !== savedText[kind]) return "modified";
    return { download: "downloaded", folder: "saved" }[savedBy[kind]] || "unchanged";
  };
  // the fixed kinds, and any the page saves beyond them, such as a satellite target's file
  const kinds = new Set([...FILES.map(({ kind }) => kind), ...Object.keys(texts)]);
  return Object.fromEntries([...kinds].map((kind) => [kind, stateOf(kind)]));
}

const STATE_TEXT = {
  unchanged: "unchanged",
  downloaded: "downloaded",
  saved: "saved into the folder",
  modified: "modified, not saved",
  new: "new, not saved",
  absent: "not in this folder",
};

/** Whether any file has changes that are not saved. */
const unsaved = () => Object.values(fileStates()).some((s) => s === "modified" || s === "new");

/** Whether the folder holds a file: one that the page's data lists as missing does not. */
const isHeld = (kind) => !(kind in DATA.files) || Boolean(DATA.files[kind]);

/** Note a file that the page starts, such as a power system added to a scenario folder. */
function fileAdded(kind) {
  if (!sources[kind]) sources[kind] = { how: "new" };
}

/** A file's name in the folder, by its kind. */
function fileName(kind) {
  const file = projectFiles().find((f) => f.kind === kind);
  return file ? file.path : project.names[kind] || kind;
}

/** Where a file came from, in words. */
function sourceText(kind) {
  const source = sources[kind];
  if (!source) return "";
  return {
    page: `from ${source.folder}/, when the page was written`,
    folder: `opened from the folder ${source.folder}/`,
    file: "opened alone: the browser does not tell the page its folder",
    new: "started on this page",
  }[source.how];
}

/** Save one file, as a download, and note it as saved. */
function downloadFile(kind) {
  const file = projectFiles().find((f) => f.kind === kind);
  if (!file) return;
  download(file);
  markSaved([kind], "download");
  refreshFiles();
}

function downloadButton(kind) {
  return el("button", { class: "btn small", text: "download", title: "Save this file, as a download", "data-download": kind, onclick: () => downloadFile(kind) });
}

/** A tab's bar for one of its files: its name, where it came from, its state, and Open and download. */
function fileBar(kind) {
  const bar = el("div", { class: "file-bar", title: OPENERS[kind] ? `Drop a file here, in place of ${project.names[kind]}` : null },
    el("b", { class: "file-name", text: fileName(kind) }),
    el("span", { class: "hint", text: sourceText(kind) }),
    el("span", { class: "file-state", "data-state": kind }),
    el("span", { class: "spacer" }),
    OPENERS[kind] ? openButton(kind) : null,
    downloadButton(kind));
  return OPENERS[kind] ? dropTarget(bar, kind) : bar;
}

/** The page's problems in a file's sections: [errors, notes]. */
function problemsOf(kind) {
  const mine = state.problems.filter((p) => SECTIONS[p.section] && SECTIONS[p.section].file === kind);
  return [mine.filter((p) => p.level === "error").length, mine.filter((p) => p.level === "note").length];
}

/** The full check of a file: what quicksat's loaders said when Python wrote the page. */
function fullCheck(tag, kind) {
  const name = fileName(kind);
  const check = DATA.checks.find((c) => c.file.split(" with ").includes(name));
  if (!check) return el(tag, { class: "hint", text: "—" });
  if (check.ok === null) return el(tag, { class: "hint", text: "not run", title: "Opened after Python wrote the page. Write the page again for the full check." });
  return check.ok ? el(tag, { class: "ok", text: "pass", title: `quicksat reads ${check.file}` }) : el(tag, { class: "bad", text: "refused", title: check.message });
}

/**
 * A table of the folder's files, for opening them: for each, where it came
 * from, whether it changed, its simple and full checks, and its buttons. `groups` are the rows, each group under an optional heading:
 * [{head, rows: [{kind, add}]}], where `add` starts a missing file.
 */
function filesTable(groups) {
  const table = el("table", { class: "items files-table" });
  table.append(el("tr", {}, ["file", "from", "state", "simple check", "full check", ""].map((h) => el("th", { text: h }))));
  for (const group of groups) {
    if (group.head) table.append(el("tr", { class: "group-row" }, el("td", { colspan: 6 }, group.head)));
    for (const { kind, add } of group.rows) {
      table.append(el("tr", {},
        el("td", {}, el("b", { text: fileName(kind) })),
        el("td", { class: "hint", text: sourceText(kind) }),
        el("td", { class: "file-state", "data-state": kind }),
        el("td", { "data-checks": kind }),
        fullCheck("td", kind),
        el("td", { class: "tools" },
          OPENERS[kind] ? openButton(kind) : null, " ",
          add ? el("button", { class: "btn small", text: "add", "data-add": kind, title: "Start this file on the page", onclick: add }) : null)));
    }
  }
  return el("div", { class: "scroll-x" }, table);
}

/** Show each file's state, its page checks, and which buttons apply, wherever the page shows them. */
function refreshFiles() {
  const states = fileStates();
  for (const node of document.querySelectorAll("[data-state]")) {
    const fileState = states[node.dataset.state] || "absent";
    node.textContent = STATE_TEXT[fileState];
    node.dataset.value = fileState;
  }
  for (const button of document.querySelectorAll("[data-download]")) button.disabled = states[button.dataset.download] === "absent";
  for (const button of document.querySelectorAll("[data-add]")) button.hidden = states[button.dataset.add] !== "absent";
  for (const cell of document.querySelectorAll("[data-checks]")) {
    const [errors, notes] = problemsOf(cell.dataset.checks);
    // a file with no fields of its own, such as the 3D model, has no checks of its own
    const absent = states[cell.dataset.checks] === "absent" || !Object.values(SECTIONS).some((section) => section.file === cell.dataset.checks);
    cell.className = absent ? "hint" : errors ? "bad" : notes ? "warn" : "ok";
    cell.textContent = absent ? "—" : errors ? `${errors} problem${errors > 1 ? "s" : ""}` : notes ? `${notes} note${notes > 1 ? "s" : ""}` : "pass";
  }
}

// ---------------------------------------------------------------- opening files

/**
 * Open a folder, or one file, in place of what the page holds. An opener picks
 * the files, reads them into `DATA` and the project, and returns the kinds of
 * the files it replaced. quicksat's loaders have not read them, so their checks
 * are marked as not run.
 */
async function openWith(kind, dropped = null) {
  const opener = OPENERS[kind];
  const what = kind === "folder" ? "a folder replaces every file" : `a file replaces ${project.names[kind] || "it"}`;
  if (unsaved() && !confirm(`Opening ${what} on this page. The changes you have not saved are lost.`)) return;
  const picked = dropped || (await pickFiles(opener.pick));
  if (!picked.files.length) return;
  const before = Object.fromEntries(Object.entries(DATA.files).map(([k, file]) => [k, file ? file.name : ""]));
  let kinds;
  try {
    kinds = await opener.open(picked);
  } catch (error) {
    alert(error.message);
    return;
  }
  if (!kinds) return;
  const names = (k) => [before[k], DATA.files[k] && DATA.files[k].name].filter(Boolean);
  DATA.checks = DATA.checks.filter((check) => !kinds.some((k) => names(k).some((name) => check.file.split(" with ").includes(name))));
  for (const k of kinds) if (DATA.files[k]) DATA.checks.push({ file: DATA.files[k].name, ok: null, message: "" });
  reviewFiles(kinds.filter((k) => YAML_KINDS.includes(k)));
  if (kind === "folder") {
    for (const k of Object.keys(sources)) delete sources[k];
    for (const k of Object.keys(savedText)) delete savedText[k];
    const held = Object.keys(currentTexts()).filter(isHeld);
    // a folder's files dropped loose come without their folder's name
    for (const k of held) sources[k] = picked.folder ? { how: "folder", folder: picked.folder } : { how: "file" };
    for (const k of Object.keys(currentTexts())) fileAdded(k);
    markSaved(held);
  } else {
    for (const k of kinds) sources[k] = { how: "file" };
    markSaved(kinds);
  }
  state.pendingDelete = null;
  showLabel();
  updateBanner();
  drawView();
  runChecks();
  page.afterChange();
}

/** The area that opens a folder in place of the page's files: its button, or a drop. */
function openFolderButton() {
  return dropTarget(el("div", { class: "open-row drop-area" },
    el("button", { class: "btn primary", text: "Open a folder…", onclick: () => openWith("folder") }),
    el("span", { class: "hint" }, OPENERS.folder.hint, el("br"), "Or drop the folder here, or its files.")), null);
}

// ---------------------------------------------------------------- dropping files

/**
 * The kind of file a name belongs to, if exactly one of the page's files has it,
 * or a kind the page's own `kindOfFile` gives it.
 */
function kindOfName(name) {
  const kinds = Object.keys(project.names).filter((kind) => OPENERS[kind] && project.names[kind] === name);
  if (kinds.length === 1) return kinds[0];
  return page.kindOfFile(name);
}

/**
 * Open what was dropped. A folder, or several files, open as a folder. One file
 * opens as the kind it was dropped on, or as the page's file of the same name.
 */
async function openDropped(transfer, kind) {
  let dropped;
  try {
    dropped = await droppedFiles(transfer);
  } catch (error) {
    alert(error.message);
    return;
  }
  if (!dropped.files.length) return;
  if (kind && dropped.isFolder) {
    alert(`Drop a file here, in place of ${project.names[kind]}. A folder goes on the first Setup step.`);
    return;
  }
  const single = dropped.files.length === 1 ? kindOfName(dropped.files[0].path) : null;
  const target = kind || (dropped.isFolder || dropped.files.length > 1 ? "folder" : single);
  if (!target) {
    alert(`${dropped.files[0].path} is not one of this page's files by its name. Drop it on its tab's bar, or drop the whole folder.`);
    return;
  }
  await openWith(target, dropped);
}

/** Let an element take drops, for a kind of file, or for the folder when kind is null. */
function dropTarget(node, kind) {
  node.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.stopPropagation();
    node.classList.add("drag-over");
  });
  node.addEventListener("dragleave", (event) => {
    if (!node.contains(event.relatedTarget)) node.classList.remove("drag-over");
  });
  node.addEventListener("drop", (event) => {
    event.preventDefault();
    event.stopPropagation();
    node.classList.remove("drag-over");
    openDropped(event.dataTransfer, kind);
  });
  return node;
}

// A drop anywhere else on the page is read as a drop on the first Setup step, so
// that the browser never leaves the page to show the dropped file
document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => {
  event.preventDefault();
  openDropped(event.dataTransfer, null);
});

/** The button that opens one file, of a kind, in place of the page's. */
function openButton(kind) {
  const opener = OPENERS[kind];
  return el("button", {
    class: "btn small", text: `Open ${opener.label}…`,
    title: `Open a file in place of ${project.names[kind] || opener.label}. ${opener.hint || ""}`.trim(),
    onclick: () => openWith(kind),
  });
}

/** The folder's name in the header and the page's title. */
function showLabel() {
  document.title = `${PAGE_TITLE} · ${DATA.label || project.name}`;
  $("#folder").textContent = DATA.label || project.name;
}

// ---------------------------------------------------------------- the draft

// While the page has changes that are not saved, it keeps them in the browser's
// storage, so that a reload or a closed tab does not lose them. The draft holds
// every file as saving would write it, where each came from, and how each was
// last saved. When the page starts and finds a draft, it offers to read it back,
// as it opens a folder. The storage is the browser's, on this computer only,
// with one draft for each page file, and one for each folder the server serves.

/** The draft's key in the browser's storage, set as the page starts. */
let draftKey = "";

/** Each file's text, or bytes, as the page started with it. */
const startTexts = {};

/** The draft found as the page started, until the user restores or discards it. */
let offeredDraft = null;

/** Whether the page holds changes that a reload would lose. */
function hasChanges() {
  if (!unsaved()) return false;
  const texts = currentTexts();
  const kinds = new Set([...Object.keys(texts), ...Object.keys(startTexts)]);
  return [...kinds].some((kind) => texts[kind] !== startTexts[kind]);
}

/**
 * The draft of the page as it is now. A binary file that the page started with
 * is not copied. Another one is copied in base64, unless `binary` is false.
 */
function makeDraft(binary) {
  const texts = currentTexts();
  const files = projectFiles().map((file) => {
    const entry = { kind: file.kind, path: file.path, read: page.draftPath(file) };
    if (file.text != null) entry.text = file.text;
    else if (file.bytes === startTexts[file.kind]) entry.start = true;
    else if (binary) entry.base64 = bytesToBase64(file.bytes);
    else entry.lost = true;
    return entry;
  });
  const saved = Object.fromEntries(Object.entries(savedText).map(([kind, text]) => [kind,
    text === texts[kind] ? { same: true } : typeof text === "string" ? { text } : text === startTexts[kind] ? { start: true } : { lost: true }]));
  return {
    time: new Date().toISOString(),
    files,
    saved,
    savedBy: { ...savedBy },
    sources: { ...sources },
    notices: notices.files,
    review: review.map(({ kind, file, line, path, text, key, status }) => ({ kind, file, line, path, text, key, status })),
  };
}

/** Write a value into the browser's storage. False if the browser refuses it, such as when it is full. */
function storeDraft(value) {
  try {
    localStorage.setItem(draftKey, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

/** Remove the draft from the browser's storage. */
function forgetDraft() {
  try { localStorage.removeItem(draftKey); } catch { /* storage that cannot be read holds no draft */ }
}

/** Keep the page's changes as the draft, or remove the draft once there are none. */
function keepDraft() {
  if (!draftKey) return;
  if (!hasChanges()) {
    // the draft found at the start stays until the user decides
    if (!offeredDraft) forgetDraft();
    return;
  }
  // a change made instead discards the draft on offer
  if (offeredDraft) closeDraftBar();
  if (!storeDraft(makeDraft(true))) storeDraft(makeDraft(false));
}

/** The draft in the browser's storage, or null. */
function recallDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(draftKey) || "null");
    return draft && Array.isArray(draft.files) ? draft : null;
  } catch {
    return null;
  }
}

/** The text a draft notes as saved, for a text file, or null. */
function draftSaved(draft, kind) {
  const saved = draft.saved[kind];
  if (!saved) return null;
  if (saved.same) return (draft.files.find((file) => file.kind === kind) || {}).text ?? null;
  if (saved.start) return null;
  return saved.text ?? null;
}

/** The names of the files, as a list in words. */
const nameList = (names) => (names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0] || "");

/** Look for a draft as the page starts, and offer it if it differs from the page. */
function offerDraft() {
  // the server's command names both its folders, and a page written into a folder is a file of its own
  draftKey = `quicksat-draft:${PAGE_TITLE}:${DATA.server ? DATA.server.command : location.pathname}`;
  Object.assign(startTexts, currentTexts());
  const draft = recallDraft();
  if (!draft) return;
  const differs = draft.files.filter((file) => (file.text != null ? file.text !== startTexts[file.kind] : !file.start));
  const kinds = new Set(draft.files.map((file) => file.kind));
  if (!differs.length && Object.keys(startTexts).every((kind) => kinds.has(kind))) {
    forgetDraft();
    return;
  }
  offeredDraft = draft;
  // a file from the folder that has changed on disk since the draft
  const moved = Object.keys(draft.sources).filter((kind) => draft.sources[kind].how === "page" && typeof startTexts[kind] === "string")
    .filter((kind) => { const saved = draftSaved(draft, kind); return saved != null && saved !== startTexts[kind]; });
  const time = new Date(draft.time);
  const when = Number.isNaN(time.getTime()) ? "" : ` from ${time.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
  const bar = $("#draft");
  bar.hidden = false;
  bar.replaceChildren(
    el("b", { text: "Changes not saved: " }),
    `this page kept a draft${when}, of ${nameList(differs.map((file) => file.path))}. `,
    moved.length ? `The folder's ${nameList(moved.map((kind) => draft.files.find((file) => file.kind === kind)?.path || kind))} changed on disk since, and restoring replaces it on the page. ` : "",
    draft.files.some((file) => file.lost) ? "The 3D model was too large for the browser's storage, so the draft does not hold it. " : "",
    "A change on the page discards the draft. ",
    el("button", { class: "btn small primary", text: "restore", onclick: restoreDraft }), " ",
    el("button", { class: "btn small danger", text: "discard", onclick: () => { closeDraftBar(); forgetDraft(); } }));
}

/** Close the offer of a draft. */
function closeDraftBar() {
  offeredDraft = null;
  $("#draft").hidden = true;
  $("#draft").replaceChildren();
}

/** Read the draft on offer back into the page, as a folder opens, with its files' states. */
async function restoreDraft() {
  const draft = offeredDraft;
  closeDraftBar();
  const files = draft.files.filter((file) => !file.lost).map((file) => {
    const content = file.text ?? (file.start ? startTexts[file.kind] : base64ToBytes(file.base64));
    // as `pickedFile` looks for it
    const path = file.read.trim().replace(/\\/g, "/").replace(/^(\.\/)+/, "");
    return { path, file: new File([content], path.split("/").pop()) };
  });
  const { folder, label } = DATA;
  const checks = DATA.checks;
  try {
    await OPENERS.folder.open({ folder: label, isFolder: true, files });
  } catch (error) {
    alert(`The draft does not read, so it is discarded: ${error.message}`);
    forgetDraft();
    return;
  }
  Object.assign(DATA, { folder, label });
  for (const file of draft.files) if (file.kind in project.names) project.names[file.kind] = file.path;
  for (const record of [sources, savedBy, savedText]) for (const kind of Object.keys(record)) delete record[kind];
  Object.assign(sources, draft.sources);
  Object.assign(savedBy, draft.savedBy);
  const texts = currentTexts();
  // a binary file reads back as new bytes, the same as the page's own
  const own = new Set(draft.files.filter((file) => file.start).map((file) => file.kind));
  for (const kind of own) startTexts[kind] = texts[kind];
  for (const [kind, saved] of Object.entries(draft.saved)) {
    // a file from the folder is compared with the folder as it is now
    if (sources[kind] && sources[kind].how === "page") { if (kind in startTexts) savedText[kind] = startTexts[kind]; }
    else if (saved.same) savedText[kind] = texts[kind];
    else if (saved.start) savedText[kind] = startTexts[kind];
    else if (saved.text != null) savedText[kind] = saved.text;
  }
  notices.files = draft.notices || {};
  review = (draft.review || []).map((item) => {
    const [target, itemLabel] = commentTarget(item.kind, item.path);
    return { ...item, target, label: itemLabel };
  });
  // quicksat's loaders read the files in the folder, not the draft's
  const states = fileStates();
  const changedNames = Object.keys(states).filter((kind) => states[kind] === "modified" || states[kind] === "new").map(fileName);
  DATA.checks = checks.map((check) => (check.file.split(" with ").some((name) => changedNames.includes(name)) ? { ...check, ok: null, message: "" } : check));
  state.pendingDelete = null;
  showLabel();
  updateBanner();
  drawView();
  runChecks();
  page.afterChange();
  keepDraft();
}

// ---------------------------------------------------------------- start

/** Start the page, once the page's own parts are ready. */
function startPage() {
  $("#checks-chip").addEventListener("click", () => {
    const pop = $("#popover");
    if (!pop.hidden && pop.dataset.kind === "checks") pop.hidden = true;
    else showChecksPopover();
  });
  document.addEventListener("keydown", (e) => e.key === "Escape" && ($("#popover").hidden = true));
  reviewFiles(YAML_KINDS);
  // a file the folder does not hold starts on the page, as new
  const held = Object.keys(currentTexts()).filter(isHeld);
  for (const kind of held) sources[kind] = { how: "page", folder: DATA.label || DATA.folder };
  for (const kind of Object.keys(currentTexts())) fileAdded(kind);
  markSaved(held);
  showLabel();
  showTab("setup");
  showStep(0);
  updateBanner();
  offerDraft();
}
