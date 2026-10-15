// quicksat editor: writing YAML and CSV text, the zip, and the downloads.

/** The lines at the top of every YAML file the editor writes. */
const HEADER = [
  "# Written by the quicksat editor. Lines that start with # are help text: the",
  "# editor writes them, and rewrites them each time it saves this file. Put the",
  "# comments you want to keep in a comments field. Every block has one, and the",
  "# editor keeps them as they are.",
];

/** A YAML scalar: plain when that reads back as the same string, otherwise in double quotes. */
function ys(value) {
  const text = String(value);
  const plainChars = /^[A-Za-z0-9_+\-./() %]+$/;
  const special = /^(true|false|yes|no|on|off|y|n|null|~)$/i;
  const numeric = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;
  if (text === "" || !plainChars.test(text) || special.test(text) || numeric.test(text) || /^\s|\s$/.test(text) || /^- /.test(text) || /^%/.test(text)) {
    return JSON.stringify(text);
  }
  return text;
}

/** A quantity for the file, or "" when it is empty, so that the field is left out. */
const yq = (quantity) => (blank(quantity) ? "" : ys(qText(quantity)));

/** A plain number for the file, or "" when the field is empty. */
const yn = (value) => (value === "" || value == null ? "" : String(value));

/** Write help lines from `YAML_HELP`, wrapped to 80 characters, when the user wants help. */
function helpLines(lines, indent, key) {
  if (!state.writeHelp || !YAML_HELP[key]) return;
  const pad = " ".repeat(indent);
  const width = 80 - indent - 2;
  let line = "";
  for (const word of YAML_HELP[key].split(" ")) {
    if ((line + " " + word).trim().length > width) { lines.push(`${pad}# ${line.trim()}`); line = ""; }
    line += " " + word;
  }
  if (line.trim()) lines.push(`${pad}# ${line.trim()}`);
}

/**
 * The comments field. A short comment takes one line. A long one is folded with
 * `>-` over lines of 80 characters, which YAML reads back as the same text. Text
 * with line breaks of its own is kept as it is, with `|-`.
 */
function commentsLines(lines, indent, text) {
  text = (text || "").trim();
  if (!text) return;
  const pad = " ".repeat(indent);
  if (!text.includes("\n")) {
    const line = `${pad}comments: ${ys(text)}`;
    if (line.length <= 80 || /  |\t/.test(text)) { lines.push(line); return; }
    lines.push(`${pad}comments: >-`);
    let row = "";
    for (const word of text.split(" ")) {
      if (row && pad.length + 2 + row.length + 1 + word.length > 80) { lines.push(`${pad}  ${row}`); row = ""; }
      row = row ? `${row} ${word}` : word;
    }
    lines.push(`${pad}  ${row}`);
    return;
  }
  lines.push(`${pad}comments: |-`);
  for (const line of text.split("\n")) lines.push(line ? `${pad}  ${line}` : "");
}

/** A flow map, such as {part: Wing +y, axis: +y}, leaving out the empty values. */
const flowMap = (pairs) => `{${pairs.filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}: ${v}`).join(", ")}}`;

/**
 * Write a named item: on one line when it has no comments, or as a block with its
 * comments field when it has.
 */
function itemLines(lines, indent, name, pairs, comments) {
  const pad = " ".repeat(indent);
  if (!(comments || "").trim()) { lines.push(`${pad}${ys(name)}: ${flowMap(pairs)}`); return; }
  lines.push(`${pad}${ys(name)}:`);
  for (const [k, v] of pairs) if (v !== "" && v != null) lines.push(`${pad}  ${k}: ${v}`);
  commentsLines(lines, indent + 2, comments);
}

/** A CSV cell, quoted when it holds a comma, a quote or a line break. */
function csvCell(value) {
  const text = value == null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

// ---------------------------------------------------------------- downloads

const fileBytes = (file) => file.bytes || new TextEncoder().encode(file.text);

function saveBlob(blob, name) {
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function download(file) {
  saveBlob(new Blob([fileBytes(file)]), file.path.split("/").pop());
}

/** Every file of the page, in one zip with the folder's name. */
function downloadZip() {
  const folder = (project.name || "quicksat_project").replace(/[^A-Za-z0-9_.-]+/g, "_");
  saveBlob(zipBlob(projectFiles().map((f) => ({ name: `${folder}/${f.path}`, data: fileBytes(f) }))), `${folder}.zip`);
  markSaved(projectFiles().map((file) => file.kind), "export");
  refreshFiles();
}

// A zip with no compression: CRC-32, a local header per file, then the central directory
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** A zip of `entries`, each a name with its folder and its bytes, stored without compression. */
function zipBlob(entries) {
  const now = new Date();
  const time = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
  const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  const parts = [];
  const central = [];
  let offset = 0;
  const put = (view, fields) => fields.forEach(([at, value, size]) => (size === 4 ? view.setUint32(at, value, true) : view.setUint16(at, value, true)));
  for (const { name, data } of entries) {
    const nameBytes = new TextEncoder().encode(name);
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    put(local, [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x0800, 2], [8, 0, 2], [10, time, 2], [12, date, 2], [14, crc, 4], [18, data.length, 4], [22, data.length, 4], [26, nameBytes.length, 2], [28, 0, 2]]);
    const entry = new DataView(new ArrayBuffer(46));
    put(entry, [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x0800, 2], [10, 0, 2], [12, time, 2], [14, date, 2], [16, crc, 4], [20, data.length, 4], [24, data.length, 4], [28, nameBytes.length, 2], [30, 0, 2], [32, 0, 2], [34, 0, 2], [36, 0, 2], [38, 0, 4], [42, offset, 4]]);
    parts.push(local, nameBytes, data);
    central.push(entry, nameBytes);
    offset += 30 + nameBytes.length + data.length;
  }
  const size = central.reduce((n, part) => n + part.byteLength, 0);
  const end = new DataView(new ArrayBuffer(22));
  put(end, [[0, 0x06054b50, 4], [4, 0, 2], [6, 0, 2], [8, entries.length, 2], [10, entries.length, 2], [12, size, 4], [16, offset, 4], [20, 0, 2]]);
  return new Blob([...parts, ...central, end], { type: "application/zip" });
}
