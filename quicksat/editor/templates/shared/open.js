// quicksat editor: opening files in the browser.
//
// A page opens a folder, or one file, that the user picks. YAML is read with
// js-yaml, CSV with the reader below, and the `#` comments are found with the
// same rules as `comment_blocks` in editor.py. The two must agree: a test runs
// both on quicksat's own files.

/**
 * The schema closest to PyYAML's safe loader: YAML's core types, with merge
 * keys. Dates are kept as text, as the page reads them as text anyway.
 */
const YAML_SCHEMA = typeof jsyaml === "undefined" ? null : jsyaml.CORE_SCHEMA.extend({ implicit: [jsyaml.types.merge] });

/** A YAML file for the page: its name, its data and its comments, as editor.py gives them. */
function readYaml(name, text) {
  let data;
  try {
    data = jsyaml.load(text, { schema: YAML_SCHEMA, filename: name });
  } catch (error) {
    const where = error.mark ? `, line ${error.mark.line + 1}` : "";
    throw new Error(`${name} is not valid YAML${where}: ${error.reason || error.message}`);
  }
  return { name, data: data ?? null, comments: commentBlocks(text) };
}

/** A CSV file for the page: its header and its rows of text, without the empty rows. */
function readCsv(name, text) {
  const rows = parseCsv(text);
  return { name, header: rows[0] || [], rows: rows.slice(1).filter((row) => row.some((cell) => cell.trim())) };
}

/** The rows of a CSV text, as Python's csv module reads them: quotes, doubled quotes, and line breaks in quotes. */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  let started = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') quoted = false; else cell += c;
    } else if (c === '"') { quoted = true; started = true; } else if (c === ",") { row.push(cell); cell = ""; started = true; } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      if (started || cell) row.push(cell);
      rows.push(row);
      row = []; cell = ""; started = false;
    } else { cell += c; started = true; }
  }
  if (started || cell) { row.push(cell); rows.push(row); }
  return rows;
}

// ---------------------------------------------------------------- the comments

const LINE_BREAK = /\r\n|\r|\n/;
const indentOf = (line) => line.length - line.replace(/^ +/, "").length;

/** The comment at the end of a line of YAML, outside any quotes, or null. */
function inlineComment(line) {
  let quote = null;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quote !== null) { if (c === quote) quote = null; } else if (c === "'" || c === '"') quote = c; else if (c === "#" && i > 0 && (line[i - 1] === " " || line[i - 1] === "\t")) return line.slice(i + 1).trim();
  }
  return null;
}

/**
 * The place of every key and every list item in a YAML text, with its path:
 * [line, column, path], counted from 0, in the order of the file, as editor.py's
 * `_key_lines` finds them with PyYAML's nodes. It reads the layouts that YAML
 * files use: block mappings and lists, flow collections over one line or more,
 * quoted and plain values, and block scalars, whose lines it skips.
 */
function keyLines(text) {
  const lines = text.split(LINE_BREAK);
  const found = [];
  const stack = []; // the open blocks: { indent, seq, path, count }
  let pending = null; // a key or a list item whose value starts on a later line
  let scalarIndent = -1; // a block scalar's lines are indented more than this
  const top = () => stack[stack.length - 1];

  /** The quoted text at `line`, `i`, which may run over several lines: its end, and its value. */
  function quoted(n, i) {
    const q = lines[n][i];
    let value = "";
    let j = i + 1;
    for (;;) {
      const line = lines[n];
      if (j >= line.length) {
        if (n + 1 >= lines.length) return { n, i: j, value };
        n += 1; j = 0; value += " ";
        continue;
      }
      const c = line[j];
      if (q === '"' && c === "\\") { value += c + (line[j + 1] ?? ""); j += 2; continue; }
      if (c === q) {
        if (q === "'" && line[j + 1] === "'") { value += "'"; j += 2; continue; }
        try { value = q === '"' ? JSON.parse(`"${value}"`) : value; } catch { /* keep the text as written */ }
        return { n, i: j + 1, value };
      }
      value += c;
      j += 1;
    }
  }

  /** A mapping key at `line`, `col`: its value, and where the text after its colon starts; or null. */
  function keyAt(n, col) {
    const line = lines[n];
    const c = line[col];
    if (c === '"' || c === "'") {
      const end = quoted(n, col);
      if (end.n !== n) return null;
      let j = end.i;
      while (line[j] === " " || line[j] === "\t") j += 1;
      return line[j] === ":" && (j + 1 >= line.length || line[j + 1] === " " || line[j + 1] === "\t") ? { key: end.value, after: j + 1 } : null;
    }
    if ("[]{},#&*!|>%@`".includes(c)) return null;
    for (let j = col; j < line.length; j++) {
      if (line[j] === "#" && j > col && (line[j - 1] === " " || line[j - 1] === "\t")) return null;
      if (line[j] === ":" && (j + 1 >= line.length || line[j + 1] === " " || line[j + 1] === "\t")) return { key: line.slice(col, j).trim(), after: j + 1 };
    }
    return null;
  }

  // ------------------------------------------ flow collections: [a, b] and {k: v}

  const cursor = (n, i) => ({ n, i });
  const at = (cur) => (cur.n < lines.length ? lines[cur.n][cur.i] : undefined);

  /** Move past spaces, line ends and comments. False at the end of the text. */
  function skipSpace(cur) {
    for (;;) {
      if (cur.n >= lines.length) return false;
      const line = lines[cur.n];
      if (cur.i >= line.length) { cur.n += 1; cur.i = 0; continue; }
      const c = line[cur.i];
      if (c === " " || c === "\t") { cur.i += 1; continue; }
      if (c === "#" && (cur.i === 0 || line[cur.i - 1] === " " || line[cur.i - 1] === "\t")) { cur.i = line.length; continue; }
      return true;
    }
  }

  /** Move past a value inside a flow collection: a collection, quoted text, or plain text. */
  function flowValue(cur, path) {
    const c = at(cur);
    if (c === "[" || c === "{") { flow(cur, path); return; }
    if (c === '"' || c === "'") { const end = quoted(cur.n, cur.i); cur.n = end.n; cur.i = end.i; return; }
    const line = lines[cur.n];
    while (cur.i < line.length && !",]}".includes(line[cur.i]) && !(line[cur.i] === "#" && line[cur.i - 1] === " ")) cur.i += 1;
  }

  /** A flow collection, from its opening bracket. */
  function flow(cur, path) {
    const seq = at(cur) === "[";
    const close = seq ? "]" : "}";
    cur.i += 1;
    let index = 0;
    while (skipSpace(cur)) {
      const c = at(cur);
      if (c === close) { cur.i += 1; return; }
      if (c === ",") { cur.i += 1; continue; }
      if (seq) {
        found.push([cur.n, cur.i, [...path, index]]);
        flowValue(cur, [...path, index]);
        index += 1;
        continue;
      }
      const start = cursor(cur.n, cur.i);
      let key;
      if (c === '"' || c === "'") {
        const end = quoted(cur.n, cur.i);
        key = end.value; cur.n = end.n; cur.i = end.i;
      } else {
        const line = lines[cur.n];
        let j = cur.i;
        while (j < line.length && !",}".includes(line[j]) && !(line[j] === ":" && (j + 1 >= line.length || " ,]}".includes(line[j + 1])))) j += 1;
        key = line.slice(cur.i, j).trim();
        cur.i = j;
      }
      found.push([start.n, start.i, [...path, key]]);
      if (!skipSpace(cur)) return;
      if (at(cur) === ":") {
        cur.i += 1;
        if (skipSpace(cur) && !",}".includes(at(cur))) flowValue(cur, [...path, key]);
      }
    }
  }

  // ------------------------------------------ block collections

  /** The list whose items start at `col`, opened or found. */
  function listAt(n, col) {
    if (pending && col >= pending.indent) {
      if (pending.item) found.push([n, col, pending.path]);
      stack.push({ indent: col, seq: true, path: pending.path, count: -1 });
      pending = null;
      return top();
    }
    pending = null;
    while (stack.length && top().indent > col) stack.pop();
    if (stack.length && top().seq && top().indent === col) return top();
    if (!stack.length) { stack.push({ indent: col, seq: true, path: [], count: -1 }); return top(); }
    return null;
  }

  /** The mapping whose keys start at `col`, opened or found. */
  function mapAt(n, col) {
    if (pending && col > pending.indent) {
      if (pending.item) found.push([n, col, pending.path]);
      stack.push({ indent: col, seq: false, path: pending.path });
      pending = null;
      return top();
    }
    pending = null;
    while (stack.length && (top().indent > col || (top().seq && top().indent >= col))) stack.pop();
    if (stack.length && !top().seq && top().indent === col) return top();
    if (!stack.length) { stack.push({ indent: col, seq: false, path: [] }); return top(); }
    return null;
  }

  /** A value that starts at `line`, `col`. Returns the last line it takes. */
  function value(n, col, path, parentIndent, inItem) {
    const line = lines[n];
    let c = line[col];
    while (c === "&" || c === "!") {
      while (col < line.length && line[col] !== " ") col += 1;
      while (line[col] === " ") col += 1;
      c = line[col];
      if (c === undefined || c === "#") { pending = { path, indent: parentIndent }; return n; }
    }
    if (c === "[" || c === "{") { const cur = cursor(n, col); flow(cur, path); return cur.n; }
    if (c === "|" || c === ">") { scalarIndent = parentIndent; return n; }
    if (c === '"' || c === "'") return quoted(n, col).n;
    if (inItem && c === "-" && (col + 1 >= line.length || line[col + 1] === " ")) {
      stack.push({ indent: col, seq: true, path, count: -1 });
      return entry(n, col);
    }
    if (inItem && keyAt(n, col)) {
      stack.push({ indent: col, seq: false, path });
      return entry(n, col);
    }
    return n;
  }

  /** The block node that starts at `line`, `col`: a list item, a key, or plain text. Returns the last line it takes. */
  function entry(n, col) {
    const line = lines[n];
    if (line[col] === "-" && (col + 1 >= line.length || line[col + 1] === " ")) {
      const list = listAt(n, col);
      if (!list) return n;
      list.count += 1;
      const path = [...list.path, list.count];
      let v = col + 1;
      while (line[v] === " ") v += 1;
      if (v >= line.length || line[v] === "#") { pending = { path, indent: col, item: true }; return n; }
      found.push([n, v, path]);
      return value(n, v, path, col, true);
    }
    const key = keyAt(n, col);
    if (!key) { pending = null; return n; }
    const map = mapAt(n, col);
    if (!map) return n;
    const path = [...map.path, key.key];
    found.push([n, col, path]);
    let v = key.after;
    while (line[v] === " " || line[v] === "\t") v += 1;
    if (v >= line.length || line[v] === "#") { pending = { path, indent: col }; return n; }
    return value(n, v, path, col, false);
  }

  for (let n = 0; n < lines.length; n++) {
    const line = lines[n];
    if (scalarIndent >= 0) {
      if (!line.trim() || indentOf(line) > scalarIndent) continue;
      scalarIndent = -1;
    }
    const col = indentOf(line);
    const rest = line.slice(col);
    if (!rest.trim() || rest.startsWith("#") || rest.startsWith("%") || /^(---|\.\.\.)(\s|$)/.test(rest)) continue;
    n = entry(n, col);
  }
  return found;
}

/**
 * Every `#` comment in a YAML text, with the key it belongs to: the same rules,
 * and the same result, as `comment_blocks` in editor.py.
 */
function commentBlocks(text) {
  const keys = keyLines(text);
  const lines = text.split(LINE_BREAK);
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  const blocks = [];
  let current = null;
  lines.forEach((line, n) => {
    const stripped = line.replace(/^\s+/, "");
    if (stripped.startsWith("#")) {
      let body = stripped.slice(1);
      if (body.startsWith(" ")) body = body.slice(1);
      if (current && current.end === n - 1) {
        current.lines.push(body);
        current.end = n;
      } else {
        current = { start: n, end: n, lines: [body], indent: line.length - stripped.length };
        blocks.push(current);
      }
      return;
    }
    current = null;
    const comment = inlineComment(line);
    if (comment !== null) {
      const key = keys.find(([at]) => at === n);
      blocks.push({ start: n, end: n, lines: [comment], path: key ? key[2] : [] });
    }
  });
  return blocks.map((block) => ({
    line: block.start + 1,
    text: block.lines.join("\n").replace(/^\n+|\n+$/g, ""),
    path: block.path || ownerOf(keys, block, lines),
    inline: Boolean(block.path),
  }));
}

/** The path of the key that a block of full-line comments belongs to, as `_owner` in editor.py. */
function ownerOf(keys, block, lines) {
  const below = keys.find(([line]) => line > block.end);
  if (!below) return [];
  const [keyLine, column, path] = below;
  if (column < block.indent) {
    const siblings = keys.filter(([line, col]) => line < block.start && col === block.indent);
    if (siblings.length) return siblings[siblings.length - 1][2].slice(0, -1);
  }
  const after = block.end + 1;
  if (after < keyLine && !lines[after].trim()) return path.slice(0, -1);
  return path;
}

// ---------------------------------------------------------------- picking files

/**
 * Ask the user for files, and resolve with them once picked: the folder's name,
 * if a folder was picked, and each file with its path inside that folder.
 */
function pickFiles({ folder = false, multiple = false, accept = "" } = {}) {
  return new Promise((resolve) => {
    const input = el("input", { type: "file", accept: accept || null, multiple: multiple || folder || null, hidden: true });
    if (folder) input.webkitdirectory = true;
    input.addEventListener("change", () => {
      const files = [...input.files].map((file) => {
        const parts = (file.webkitRelativePath || file.name).split("/");
        return { path: folder ? parts.slice(1).join("/") : file.name, file };
      });
      const name = folder && files.length ? (input.files[0].webkitRelativePath || "").split("/")[0] : "";
      input.remove();
      resolve({ folder: name, files });
    });
    document.body.append(input);
    input.click();
  });
}

/**
 * The files of a drop, as `pickFiles` gives them: one folder, with each file's
 * path inside it, or loose files, with no folder. `folder` is true for a folder.
 * The browser lets go of the drop's items once the event ends, so they are taken
 * before anything waits.
 */
async function droppedFiles(transfer) {
  const entries = [...transfer.items].filter((item) => item.kind === "file").map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry());
  const loose = [...transfer.files];
  const folders = entries.filter((entry) => entry && entry.isDirectory);
  if (!folders.length) return { folder: "", files: loose.map((file) => ({ path: file.name, file })), isFolder: false };
  if (folders.length > 1 || entries.length > 1) throw new Error("Drop one folder, or files, but not both or several folders.");
  const files = [];
  await readFolderEntry(folders[0], "", files);
  return { folder: folders[0].name, files, isFolder: true };
}

/** Each file under a dropped folder, with its path inside the folder. */
async function readFolderEntry(entry, prefix, files) {
  const reader = entry.createReader();
  for (;;) {
    // a reader gives a folder's entries in batches, until one comes back empty
    const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) return;
    for (const child of batch) {
      const path = prefix + child.name;
      if (child.isDirectory) await readFolderEntry(child, `${path}/`, files);
      else files.push({ path, file: await new Promise((resolve, reject) => child.file(resolve, reject)) });
    }
  }
}

/** A picked file by its path in the folder, such as `spacecraft.glb` or `./orbits/sso.tle`. */
function pickedFile(picked, path) {
  if (typeof path !== "string" || !path.trim()) return null;
  const wanted = path.trim().replace(/\\/g, "/").replace(/^(\.\/)+/, "");
  return picked.files.find((entry) => entry.path === wanted) || null;
}

/** The YAML or CSV of a picked file, read for the page. */
async function readPicked(entry) {
  const text = await entry.file.text();
  return /\.csv$/i.test(entry.path) ? readCsv(entry.path, text) : readYaml(entry.path, text);
}
