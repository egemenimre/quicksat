// quicksat editor: the helpers and the field controls, which every editor page
// shares.
//
// The page holds one project in memory. The Setup steps and the theme tabs draw
// the same sections from it, so they cannot disagree. Every change goes through
// `changed`, in frame.js, which re-runs the basic checks and refreshes what shows
// the files.
"use strict";

// ---------------------------------------------------------------- helpers

const $ = (selector, root = document) => root.querySelector(selector);

/** Build an element: el("div", {class: "x", text: "y", onclick: f}, child, ...). */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked") node.checked = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** A quantity: a value and a unit, such as q(510, "km"). An empty value is "". */
const q = (v, u) => ({ v, u });

/** A quantity as a file writes it, such as `510 km` or `3 orbits`. */
function qText(quantity) {
  if (!quantity || quantity.v === "" || quantity.v == null) return "";
  if (quantity.u === "orbits") return `${quantity.v} ${Number(quantity.v) === 1 ? "orbit" : "orbits"}`;
  return quantity.u ? `${quantity.v} ${quantity.u}` : `${quantity.v}`;
}

const blank = (quantity) => !quantity || quantity.v === "" || quantity.v == null;

const escapeHtml = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** Text, or "" for anything that is not text or a number. */
const str = (value) => (typeof value === "string" ? value : typeof value === "number" ? String(value) : "");

/** Bytes in base64, in pieces, as a long array would overflow a call's arguments. */
function bytesToBase64(bytes) {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

/** The bytes of a base64 text. */
const base64ToBytes = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));

const NUMBER_UNIT = /^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*)$/;

/** A number and its unit, from a number or text such as `510 km`; null if neither. */
function numberUnit(value) {
  if (typeof value === "number") return { v: value, u: "" };
  const match = String(value ?? "").trim().match(NUMBER_UNIT);
  return match ? { v: Number(match[1]), u: match[2].trim() } : null;
}

// ---------------------------------------------------------------- constants

/** The key of the user's notes in every block. No named item may take it. */
const RESERVED = "comments";

// ---------------------------------------------------------------- field controls

/** A grid of labelled fields. */
function grid(parent) {
  const node = el("div", { class: "fields" });
  parent.append(node);
  return node;
}

function row(gridNode, label, control, hint) {
  gridNode.append(el("label", {}, label, hint ? el("small", { text: hint }) : null), control);
}

function textInput(obj, key, { cls = "", placeholder = "", onchange } = {}) {
  return el("input", {
    type: "text", class: cls, value: obj[key] ?? "", placeholder,
    oninput: (e) => { if (!onchange) { obj[key] = e.target.value; changed(); } },
    onchange: (e) => { if (onchange) onchange(e.target.value, e.target); },
  });
}

function numberInput(obj, key, { step = "any", min, max, width, placeholder = "" } = {}) {
  return el("input", {
    type: "number", step, min, max, placeholder, value: obj[key] ?? "", style: width ? `width:${width}px` : null,
    oninput: (e) => { obj[key] = e.target.value === "" ? "" : Number(e.target.value); changed(); },
  });
}

/** A value with a unit chosen from a list. */
function quantityInput(obj, key, units, { placeholder = "" } = {}) {
  const quantity = obj[key] || (obj[key] = q("", units[0]));
  const value = el("input", {
    type: "number", step: "any", value: quantity.v, placeholder,
    oninput: (e) => { quantity.v = e.target.value === "" ? "" : Number(e.target.value); changed(); },
  });
  const unit = units.length === 1 && quantity.u === units[0]
    ? el("span", { class: "unit", text: units[0] })
    : selectInput(quantity, "u", units);
  return el("span", { class: "ctl" }, value, unit);
}

function selectInput(obj, key, options, { cls = "", onchange, blank: none } = {}) {
  const select = el("select", {
    class: cls,
    onchange: (e) => {
      obj[key] = e.target.value;
      if (onchange) onchange(e.target.value);
      changed(Boolean(onchange));
    },
  });
  if (none != null) select.append(el("option", { value: "", text: none }));
  for (const option of options) {
    const [value, label] = Array.isArray(option) ? option : [option, option];
    select.append(el("option", { value, text: label }));
  }
  const current = obj[key] ?? "";
  if (current !== "" && ![...select.options].some((o) => o.value === current)) {
    select.append(el("option", { value: current, text: `${current} (not defined)` }));
  }
  select.value = current;
  return select;
}

function checkbox(obj, key, label, { structure = false, onchange } = {}) {
  return el("label", { class: "ctl" },
    el("input", {
      type: "checkbox", checked: Boolean(obj[key]),
      onchange: (e) => { obj[key] = e.target.checked; if (onchange) onchange(e.target.checked); changed(structure); },
    }),
    label);
}

/** Choose one of several, shown as buttons. */
function radioRow(obj, key, options) {
  const node = el("div", { class: "radio-row" });
  for (const [value, label] of options) {
    node.append(el("label", { class: obj[key] === value ? "on" : "" },
      el("input", { type: "radio", checked: obj[key] === value, onchange: () => { obj[key] = value; changed(true); } }),
      label));
  }
  return node;
}

/** The user's comments on a block: written to its `comments` field, and never changed by the editor. */
function commentsBox(obj, label = "Your comments", { open = false, note } = {}) {
  const has = () => (obj.comments || "").trim() !== "";
  const summary = el("summary", {}, label, " ", el("span", { class: "has", text: has() ? "· written" : "" }));
  const area = el("textarea", {
    placeholder: "Comments you want to keep. They are saved in this block's comments field.",
    value: obj.comments || "",
    oninput: (e) => {
      obj.comments = e.target.value;
      summary.querySelector(".has").textContent = has() ? "· written" : "";
      changed();
    },
  });
  return el("details", { class: "comments", open: open || has() },
    summary, area,
    el("div", { class: "kept", text: note || "Kept through every edit and save. The lines starting with # in the file are help, and are rewritten on each save." }));
}

/** A small button that opens an item's comments in a row below it. */
function commentsButton(item, colspan, tbody, tr) {
  const has = () => (item.comments || "").trim() !== "";
  const button = el("button", { class: "btn small notebtn" + (has() ? " has" : ""), text: "comments", title: "Your comments on this item" });
  let noteRow = null;
  const open = () => {
    noteRow = el("tr", { class: "note-row" }, el("td", { colspan },
      el("textarea", {
        placeholder: "Comments you want to keep. They are saved in this item's comments field.",
        value: item.comments || "",
        oninput: (e) => { item.comments = e.target.value; button.classList.toggle("has", has()); changed(); },
      })));
    tr.after(noteRow);
  };
  button.addEventListener("click", () => {
    if (noteRow) { noteRow.remove(); noteRow = null; } else open();
  });
  if (has()) queueMicrotask(open);
  return button;
}

/**
 * Delete, and up and down for a list whose order means something, such as the
 * activities. Delete asks again when the item is in use. `copy` adds a copy button.
 */
function itemTools(list, index, { kind, name, order = false, copy } = {}) {
  const uses = kind ? usesOf(kind, name) : [];
  const key = `${kind}:${name}:${index}`;
  const pending = state.pendingDelete === key;
  return el("span", { class: "tools" },
    order && el("button", { class: "btn small", text: "↑", title: "Move up", disabled: index === 0, onclick: () => { [list[index - 1], list[index]] = [list[index], list[index - 1]]; changed(true); } }),
    order && el("button", { class: "btn small", text: "↓", title: "Move down", disabled: index === list.length - 1, onclick: () => { [list[index + 1], list[index]] = [list[index], list[index + 1]]; changed(true); } }),
    copy && el("button", { class: "btn small", text: "copy", title: "Add a copy below this one", onclick: () => { list.splice(index + 1, 0, copy(list[index])); changed(true); } }),
    pending ? el("span", { class: "confirm", text: ` used by ${uses.join(", ")}. ` }) : null,
    el("button", {
      class: "btn small danger", text: pending ? "delete anyway" : "delete",
      onclick: () => {
        if (uses.length && !pending) { state.pendingDelete = key; changed(true); return; }
        state.pendingDelete = null;
        list.splice(index, 1);
        changed(true);
      },
    }));
}

/** A name field that renames on change, and updates every use of the name. */
function nameInput(item, kind, siblings) {
  return textInput(item, "name", {
    cls: "name",
    onchange: (value, input) => {
      const name = value.trim();
      if (!name || name === item.name) { input.value = item.name; return; }
      if (siblings().filter((n) => n === name).length) {
        input.value = item.name;
        alert(`There is already one called "${name}".`);
        return;
      }
      if (kind) rename(kind, item.name, name);
      item.name = name;
      changed(true);
    },
  });
}
