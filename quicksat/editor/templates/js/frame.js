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
//   TABS, STEPS, SECTIONS, INFO   the tabs, the steps, the sections and their help
//   YAML_HELP, YAML_KINDS         the help it writes, and its YAML files' kinds
//   OPENERS                       how the folder, and each of its files, opens
//   projectFiles()                the files to save
//   fileComments(path)            the comments box of a whole file, or null
//   commentTarget(kind, path)     the block of a comment: [block, label, depth]
//   runChecks()                   its checks, which end with showProblems()
//
// and, if it needs them, the hooks in `page`.

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
  dirty: false,
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
  state.dirty = true;
  if (structure) drawView();
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    runChecks();
    if (state.tab === "files") drawPreview();
    page.afterChange();
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

/** A theme tab: its introduction, a button to open each of its files, and a card for each section. */
function drawSheet(tab) {
  const sheet = $(`#sheet-${tab.id}`);
  const kinds = [...new Set(tab.sections.map((id) => SECTIONS[id].file))].filter((kind) => OPENERS[kind]);
  sheet.replaceChildren(el("div", { class: "sheet-head" },
    el("p", { class: "sheet-intro", text: tab.intro }),
    el("span", { class: "spacer" }),
    ...kinds.map(openButton)));
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
    el("p", { text: `These check names, units and ranges only. ${CHECKS_NOTE}` }),
    pythonChecks());
  pop.hidden = false;
}

/** What quicksat's own loaders said of the files when the page was written. */
function pythonChecks() {
  return el("div", { class: "python-checks" },
    el("h4", { text: "quicksat's loaders, when this page was written" }),
    ...DATA.checks.map((check) => check.ok === null
      ? el("div", { class: "opened" }, el("b", { text: check.file }), " was opened in the browser, so quicksat's loaders have not read it")
      : el("div", { class: check.ok ? "ok" : "bad" }, el("b", { text: check.file }), check.ok ? " reads with no problem" : el("pre", { text: check.message }))),
    DATA.checks.length ? null : el("div", { class: "opened", text: "None: the files were opened in the browser." }));
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
    }, file.path, file.note ? el("small", { text: file.note }) : null));
  }
  list.append(el("div", { class: "actions" },
    el("label", {}, el("input", { type: "checkbox", checked: state.writeHelp, onchange: (e) => { state.writeHelp = e.target.checked; drawFiles(); } }), "write the # help lines"),
    el("button", { class: "btn primary", text: `download ${project.name}.zip`, onclick: downloadZip })));
  list.append(el("div", { class: "fields", style: "margin-top: 14px" },
    el("label", {}, "Folder name", el("small", { text: "the zip's folder" })),
    textInput(project, "name", { cls: "wide" })));
  for (const id of TABS.find((t) => t.id === "files").sections || []) list.append(el("div", { class: "problems", "data-section": id }));
  list.append(pythonChecks());
  drawPreview(true);
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
      review.push({ kind, file: file.name, line: comment.line, text: comment.text, key, target, label, status: "" });
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
  const panel = el("details", { class: "review", open: open.length > 0 || notices.unknown.length > 0 });
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

// ---------------------------------------------------------------- opening files

/**
 * Open a folder, or one file, in place of what the page holds. An opener picks
 * the files, reads them into `DATA` and the project, and returns the kinds of
 * the files it replaced. quicksat's loaders have not read them, so their checks
 * are marked as not run.
 */
async function openWith(kind) {
  const opener = OPENERS[kind];
  const what = kind === "folder" ? "a folder replaces every file" : `a file replaces ${project.names[kind] || "it"}`;
  if (state.dirty && !confirm(`Opening ${what} on this page. The changes you have not saved are lost.`)) return;
  const picked = await pickFiles(opener.pick);
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
  state.dirty = false;
  state.pendingDelete = null;
  showLabel();
  updateBanner();
  drawView();
  runChecks();
  page.afterChange();
}

/** The button that opens a folder in place of the page's files. */
function openFolderButton() {
  return el("div", { class: "open-row" },
    el("button", { class: "btn primary", text: "Open a folder…", onclick: () => openWith("folder") }),
    el("span", { class: "hint", text: OPENERS.folder.hint }));
}

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
  showLabel();
  showTab("setup");
  showStep(0);
  updateBanner();
}
