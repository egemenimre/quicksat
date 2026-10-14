// quicksat editor: the tabs, the Setup steps, the Files tab, the review of the
// comments written by hand, and the start.

const TABS = [
  { id: "setup", title: "Setup" },
  { id: "orbit", title: "Orbit and time", sections: ["orbit", "time"], intro: "Trajectory definition and the scenario duration." },
  { id: "spacecraft", title: "Spacecraft", sections: ["model", "articulations", "panels"], intro: "The 3D model, the parts that turn, and the solar panels on it. Select an item to see it in the 3D panel." },
  { id: "operations", title: "Operations", sections: ["targets", "attitudes", "slew", "modes"], intro: "How the spacecraft points, how fast it turns, and the modes it works in." },
  { id: "activities", title: "Activities", sections: ["activities"], intro: "What the spacecraft does, in order: one repeat of the list, which the run repeats until the duration ends." },
  { id: "power", title: "Power", sections: ["cells", "battery", "conditioning"], intro: "The power system: the cells and their losses, the battery and the power conditioning.", top: powerComments },
  { id: "consumption", title: "Consumption", sections: ["consumption"], intro: "What each equipment draws in each mode, from the consumption file." },
  { id: "files", title: "Files", sections: ["project"] },
];

const STEPS = [
  { group: "Start", title: "Folder", section: "project" },
  { group: "Orbit and time", title: "Orbit", section: "orbit" },
  { title: "Start, duration and step", section: "time" },
  { group: "Spacecraft", title: "3D model", section: "model", needs3d: true },
  { title: "Articulations", section: "articulations", needs3d: true },
  { group: "Operations", title: "Ground targets", section: "targets" },
  { title: "Attitudes", section: "attitudes", needs3d: true },
  { title: "Attitude slew performance", section: "slew" },
  { title: "Modes", section: "modes" },
  { title: "Activities", section: "activities" },
  { group: "Power", title: "Solar panels", section: "panels", needs3d: true },
  { title: "Cells, losses and shading", section: "cells" },
  { title: "Battery", section: "battery" },
  { title: "Power conditioning", section: "conditioning" },
  { title: "Consumption", section: "consumption" },
  { group: "Finish", title: "Save the files", section: "save" },
];

function drawTabs() {
  const nav = $("#tabs");
  nav.replaceChildren(...TABS.map((tab) => el("button", {
    "data-tab": tab.id, class: state.tab === tab.id ? "active" : "",
    onclick: () => showTab(tab.id),
  }, tab.title, el("span", { class: "count", hidden: true }))));
}

function showTab(id) {
  state.tab = id;
  state.pendingDelete = null;
  for (const button of document.querySelectorAll("#tabs button")) button.classList.toggle("active", button.dataset.tab === id);
  for (const page of document.querySelectorAll(".page")) page.classList.toggle("active", page.id === `page-${id}`);
  apply3d();
  drawView();
  runChecks();
}

function goToSection(section) {
  const step = STEPS.findIndex((s) => s.section === section);
  const tab = TABS.find((t) => (t.sections || []).includes(section));
  if (state.tab === "setup" && step >= 0) { showStep(step); return; }
  if (tab) {
    showTab(tab.id);
    const card = document.querySelector(`.card[data-section="${section}"]`);
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (step >= 0) { showTab("setup"); showStep(step); }
}

function drawView() {
  const scroll = document.querySelector(".page.active .sheet, .page.active .step-body");
  const top = scroll ? scroll.scrollTop : 0;
  if (state.tab === "setup") drawSetup();
  else if (state.tab === "files") drawFiles();
  else drawSheet(TABS.find((t) => t.id === state.tab));
  const again = document.querySelector(".page.active .sheet, .page.active .step-body");
  if (again) again.scrollTop = top;
  showProblems();
}

function drawSheet(tab) {
  const sheet = $(`#sheet-${tab.id}`);
  sheet.replaceChildren(el("p", { class: "sheet-intro", text: tab.intro }));
  if (tab.top) sheet.append(tab.top() || "");
  for (const id of tab.sections) {
    const section = SECTIONS[id];
    const [ibtn, info] = infoSign(id);
    const body = el("div", { class: "card-body" }, info, el("div", { class: "problems", "data-section": id }));
    section.render(body, { setup: false });
    sheet.append(el("div", { class: "card", "data-section": id },
      el("div", { class: "card-head" }, el("span", { class: "title" }, el("b", { text: section.title })), ibtn, el("span", { class: "spacer" }), el("span", { class: "file", text: fileOf(section) })),
      body));
  }
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

/** The file a section belongs to, by its name in this folder. */
function fileOf(section) {
  return { "scenario.yaml": project.names.scenario, "power_system.yaml": project.names.power, "power_consumption.csv": project.names.consumption }[section.file] || section.file;
}

function drawSetup() {
  const nav = $("#steps");
  nav.replaceChildren();
  STEPS.forEach((step, i) => {
    if (step.group) nav.append(el("div", { class: "group", text: step.group }));
    nav.append(el("button", {
      "data-step": i,
      class: [i === state.step ? "current" : "", state.visited.has(i) ? "visited" : ""].join(" "),
      onclick: () => showStep(i),
    }, el("span", { class: "num", text: i + 1 }), step.title));
  });
  const step = STEPS[state.step];
  const section = SECTIONS[step.section];
  const form = el("div", {}, el("div", { class: "problems", "data-section": step.section }));
  section.render(form, { setup: true });
  const group = [...STEPS.slice(0, state.step + 1)].reverse().find((s) => s.group).group;
  const [ibtn, info] = infoSign(step.section);
  $("#step").replaceChildren(
    el("div", { class: "step-head" },
      el("div", {}, el("div", { class: "where", text: `Step ${state.step + 1} of ${STEPS.length} · ${group} · ${fileOf(section)}` }), el("h2", {}, step.title, ibtn)),
      el("div", { class: "step-nav" },
        el("button", { class: "btn", text: "← Back", disabled: state.step === 0, onclick: () => showStep(state.step - 1) }),
        state.step < STEPS.length - 1
          ? el("button", { class: "btn primary", text: "Next →", onclick: () => showStep(state.step + 1) })
          : el("button", { class: "btn primary", text: "Download the zip", onclick: downloadZip }))),
    el("div", { class: "step-body" }, info, form));
}

function showStep(i) {
  state.step = Math.max(0, Math.min(STEPS.length - 1, i));
  state.visited.add(state.step);
  state.pendingDelete = null;
  apply3d();
  drawSetup();
  runChecks();
  const body = $(".step-body");
  if (body) body.scrollTop = 0;
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
  list.append(pythonChecks());
  drawPreview(true);
}

/** The file's own comments, for the files that can hold them. */
function fileComments(path) {
  if (path === project.names.scenario) return commentsBox(S, "Your comments on the overall scenario", { note: "They go in the comments field at the top of the file." });
  if (project.hasPower && path === project.names.power) return commentsBox(P, "Your comments on the overall power subsystem", { note: "They go in the comments field at the top of the file." });
  if (path.endsWith(".csv")) return el("p", { class: "hint", text: "A CSV has no place for comments on the whole file. Each row has its comments column." });
  return null;
}

/**
 * Show a file. A full redraw draws the head, the review and the file's comments
 * box. Otherwise only the text is refreshed, so typing is not interrupted.
 */
function drawPreview(full = false) {
  const files = projectFiles();
  const file = files.find((f) => f.path === state.file) || files[0];
  const preview = $("#preview");
  const text = file.bytes
    ? `A binary GLB file of ${(file.bytes.length / 1024).toFixed(1)} kB, with ${model.parts.length} named parts:\n\n${model.parts.map((p) => "  " + p.name).join("\n")}`
    : null;
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
const GENERATED = new Set([...Object.values(YAML_HELP), HEADER.map((line) => line.replace(/^# ?/, "")).join(" ")].map(normalise));

/** The block a comment belongs to, found from its key's path, and a name for it. */
function commentTarget(kind, path) {
  const [first, second, third] = path;
  const item = (section, name) => section.items.find((x) => x.name === name);
  if (kind === "power") {
    if (first === "panels") return second != null && item(P.panels, second) ? [item(P.panels, second), `panels › ${second}`] : [P.panels, "panels"];
    if (["self_shadowing", "battery", "conditioning"].includes(first)) return [P[first], first];
    return [P, `the overall power subsystem`];
  }
  if (first === "orbit") return second === "sso" && S.orbit.source === "sso" ? [S.orbit.sso, "orbit › sso"] : [S.orbit, "orbit"];
  if (first === "3d_model") {
    const arts = S.model.articulations;
    if (second === "articulations") return third != null && item(arts, third) ? [item(arts, third), `articulations › ${third}`] : [arts, "articulations"];
    return [S.model, "3d_model"];
  }
  if (first === "targets" || first === "attitudes") {
    return second != null && item(S[first], second) ? [item(S[first], second), `${first} › ${second}`] : [S[first], first];
  }
  if (first === "slew") return [S.slew, "slew"];
  if (first === "activities" && typeof second === "number" && S.activities[second]) {
    return [S.activities[second], `activity ${second + 1}, ${S.activities[second].title}`];
  }
  return [S, "the overall scenario"];
}

/** The comments that the editor did not write, and so would replace on saving. */
const review = (() => {
  const items = [];
  for (const [kind, file] of [["scenario", DATA.files.scenario], ["power", DATA.files.power]]) {
    if (!file) continue;
    for (const comment of file.comments) {
      if (GENERATED.has(normalise(comment.text))) continue;
      const [target, label] = commentTarget(kind, comment.path);
      items.push({ file: file.name, line: comment.line, text: comment.text, target, label, status: "" });
    }
  }
  return items;
})();

const openReview = () => review.filter((item) => !item.status);

function moveComment(item) {
  const text = item.text.trim();
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
    panel.append(el("p", { class: "hint", text: "The files hold these # comments, which the editor did not write. Saving replaces every # line, so move each comment you want to keep into the comments field of its block." }));
    const table = el("table", { class: "items" });
    for (const item of review) {
      table.append(el("tr", {},
        el("td", { class: "hint", text: `${item.file}:${item.line}` }),
        el("td", {}, el("pre", { class: "comment-text", text: item.text })),
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

// ---------------------------------------------------------------- start

$("#glb-input").addEventListener("change", (e) => loadGlbFile(e.target.files[0]));
$("#toggle-3d").addEventListener("click", toggle3d);
$("#hide-3d").addEventListener("click", toggle3d);
$("#checks-chip").addEventListener("click", () => {
  const pop = $("#popover");
  if (!pop.hidden && pop.dataset.kind === "checks") pop.hidden = true;
  else showChecksPopover();
});
document.addEventListener("keydown", (e) => e.key === "Escape" && ($("#popover").hidden = true));
window.addEventListener("resize", () => view3d.resize());

document.title = `quicksat File Editor · ${DATA.label || project.name}`;
$("#folder").textContent = DATA.label || project.name;
drawTabs();
const glb = DATA.model ? Uint8Array.from(atob(DATA.model.glb_base64), (c) => c.charCodeAt(0)) : null;
(glb ? view3d.load(glb, DATA.model.name) : Promise.resolve(false)).then((loaded) => {
  if (!loaded) view3d.cube();
  showTab("setup");
  showStep(0);
  view3d.update();
  updateBanner();
});
