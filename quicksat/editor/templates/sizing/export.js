// quicksat sizing editor: the budgets as an Excel workbook, one sheet for each budget.
//
// The workbook is a copy of the Budgets tab, to read and to pass on. It holds the
// tab's figures and tables, with each number in full, as Python worked it out, and
// each number shows the decimals that the tab shows. It holds values only, with no
// formulas: the sizing files are where every figure comes from, so a change
// belongs in them.

// ---------------------------------------------------------------- the sheets

/** The row types that the notebooks write in bold, and the selected inertia case. */
const BOLD_ROWS = new Set(["subsystem_subtotal", "location_subtotal", "location_total", "dry_total", "propellant", "wet_total", "phase_subtotal", "subtotal", "margin", "total", "storage", "selected"]);

/** A number as the tab shows it: its full value, in the format of the tab's text. Text when there is no number. */
const numberCell = (text, value, font = "") => (value == null ? { v: text, font, right: true } : { v: value, fmt: excelFormat(text), text, font });

/** A number in a format of its own, or its text when there is no number, such as an infinite margin. */
const fixedCell = (value, fmt, text, font = "") => (value == null ? { v: text, font, right: true } : { v: value, fmt, text, font });

const heading = (titles, numbers = []) => titles.map((v, i) => ({ v, font: "head", right: numbers.includes(i) }));

/** A table as the tab draws it: its title, its headings, then its rows. `hide` leaves out columns by their key. */
function tableRows(title, table, { hide = [] } = {}) {
  const shown = table.columns.map((column, i) => [column, i]).filter(([column]) => !hide.includes(column.key));
  const rows = [[{ v: title, font: "bold" }], heading(shown.map(([column]) => column.title), shown.flatMap(([column], j) => (column.number ? [j] : [])))];
  for (const row of table.rows) {
    const font = row.type === "fails" ? "fail" : BOLD_ROWS.has(row.type) ? "bold" : "";
    rows.push(shown.map(([column, i]) => (column.number ? numberCell(row.cells[i], row.values[i], font) : { v: row.cells[i], font })));
  }
  return rows;
}

function figureRows(title, figures) {
  return [
    [{ v: title, font: "bold" }],
    heading(["Figure", "Value", "Unit", "Note"], [1]),
    ...figures.map((figure) => [figure.label, numberCell(figure.value, figure.number, figure.bad ? "fail" : ""), figure.unit, figure.note]),
  ];
}

/** The checks, with their figures in the design's unit, and their margins as a percent. */
function checkRows(checks) {
  if (!checks.length) return null;
  return [
    [{ v: "Checks", font: "bold" }],
    // the description last, so that it runs on into the empty cells beside it
    heading(["Verdict", "Check", "Design", "", "Limit", "Spare", "Unit", "Margin", "From", "Description"], [2, 4, 5, 7]),
    ...checks.map((check) => {
      const n = check.numbers;
      const font = check.passes ? "" : "fail";
      return [
        { v: check.verdict, font }, check.check,
        fixedCell(n.design, "0.00", check.design), n.at_most ? "≤" : "≥", fixedCell(n.limit, "0.00", check.limit),
        fixedCell(n.spare, "+0.00;-0.00;+0.00", check.spare, font), n.unit, fixedCell(n.margin, "+0.0%;-0.0%;+0.0%", check.margin, font),
        check.files.join(", "), check.description,
      ];
    }),
  ];
}

const errorRows = (text) => [[{ v: text, font: "fail" }]];

/** A sheet: its title, the files its figures come from, then its blocks of rows, a row apart. */
function sheet(name, title, files, blocks) {
  const rows = [[{ v: title, font: "title" }]];
  if (files) rows.push([{ v: `From ${files}`, font: "note" }]);
  for (const block of blocks.filter(Boolean)) rows.push([], ...block);
  return { name, rows };
}

/**
 * The sheets of the workbook, from the results that the tab shows. `about` holds
 * the `folder`, the time it is written `at`, the `source` of the results, the
 * files `changed` since they were worked out, and the files' `names` by kind.
 */
function budgetSheets(results, about) {
  const files = (kinds) => kinds.map((kind) => about.names[kind]).join(", ");
  const checksOf = (key) => results.checks.filter((check) => check.budget === key);
  const lines = [
    [{ v: "Folder", font: "bold" }, about.folder],
    [{ v: "Exported", font: "bold" }, about.at],
    [{ v: about.source, font: "note" }],
  ];
  if (about.changed.length) lines.push([{ v: `${about.changed.join(", ")} changed since, so these figures may be out of date.`, font: "fail" }]);
  lines.push([{ v: "A copy of the Budgets tab. The sizing files are the source of every figure: change them, not this workbook.", font: "note" }]);
  const sheets = [sheet("Overview", "quicksat sizing budgets", "", [
    lines,
    figureRows("Headline figures", results.overview),
    checkRows(results.checks),
    results.notes.length ? results.notes.map((note) => [{ v: note, font: "fail" }]) : null,
  ])];
  // a budget whose files are missing has no sheet, and one that quicksat cannot work out has its error
  const budget = (key, name, title, kinds, own) => {
    const worked = results.budgets[key];
    if (!worked) return;
    if (worked.error) sheets.push(sheet(name, title, files(kinds), [errorRows(`quicksat cannot work out this budget: ${worked.error}`)]));
    else sheets.push(...own(worked, files(kinds)));
  };
  budget("mass", "Mass", "Mass budget", ["equipment", "mass"], ({ figures, tables: t }, from) => [
    sheet("Mass in orbit", "Mass budget, in orbit", from, [
      figureRows("Figures", figures),
      tableRows("Mass budget", t.budget["10"]),
      tableRows("By location", t.by_location),
      tableRows("By subsystem", t.by_subsystem),
      tableRows("Through the mission", t.points),
    ]),
    sheet("Mass on ground", "Mass budget, on the ground (incl. launcher's side)", from, [tableRows("Mass budget", t.budget["00"])]),
  ]);
  budget("deltav", "Delta-V", "Delta-V budget", ["manoeuvres", "deltav", "mission"], ({ figures, tables: t }, from) => [
    sheet("Delta-V", "Delta-V budget", from, [
      figureRows("Figures", figures),
      checkRows(checksOf("deltav")),
      tableRows("Delta-V budget", t.budget),
      tableRows("By phase", t.by_phase),
      tableRows("By type", t.by_type),
      t.propellant ? tableRows("Propellant", t.propellant) : null,
    ]),
  ]);
  budget("data", "Data", "Data budget", ["data", "mission", "requirements"], ({ figures, tables: t }, from) => [
    sheet("Data", "Data budget", from, [figureRows("Figures", figures), checkRows(checksOf("data")), tableRows("Data budget", t.budget), tableRows("Storage", t.storage)]),
  ]);
  budget("agility", "Agility", "Agility budget", ["agility", "mission", "requirements"], (agility, from) => ["roll", "pitch"].map((axis) => {
    const variant = agility.variants[`${axis}|0`];
    const targets = agility.slews.filter((slew) => slew.axis === axis);
    const slews = variant.error ? [] : targets.length
      ? targets.map((slew) => tableRows(`Slew table, against ${slew.name}: ${slew.text}`, variant.tables[slew.name]))
      : [tableRows("Slew table", variant.tables[""])];
    return sheet(`Agility ${axis}`, `Agility budget about ${axis}, for the inertia case ${agility.selected} (full set of wheels)`, from, [
      variant.error ? errorRows(`quicksat cannot work out the inertia case ${agility.selected}: ${variant.error}`) : figureRows("Figures", variant.figures),
      checkRows(checksOf("agility").filter((check) => targets.some((slew) => slew.name === check.check))),
      ...slews,
      tableRows("Inertia cases", agility.tables.cases),
    ]);
  }));
  return sheets;
}

/** Write the budgets that the tab shows into an .xlsx workbook, and download it. */
function exportBudgets() {
  if (!budgets.results) return;
  const source = budgets.at
    ? `Worked out by the editor's server at ${budgets.at.toLocaleString()}, from the files on the page, saved or not.`
    : "Worked out by quicksat when the page was written.";
  const sheets = budgetSheets(budgets.results, {
    folder: project.name,
    at: new Date().toLocaleString(),
    source,
    changed: changedSince().map((kind) => project.names[kind]),
    names: project.names,
  });
  const folder = (project.name || "quicksat_project").replace(/[^A-Za-z0-9_.-]+/g, "_");
  saveBlob(xlsxBlob(sheets), `${folder}_budgets.xlsx`);
}

// ---------------------------------------------------------------- the .xlsx file
//
// An .xlsx file is a zip of XML parts: the workbook, one part for each sheet, and
// the styles. Each text is written in its own cell, so there is no table of
// shared strings. A cell is text, a number, or an object: its value `v`, its
// number format `fmt`, its `font`, and whether it is aligned `right`.

const SHEET_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const RELATIONSHIPS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const PACKAGE_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships";
const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';

/** The fonts of the styles part, by the names the cells give them. */
const XLSX_FONTS = { "": 0, bold: 1, head: 1, title: 2, fail: 3, note: 4 };

/** Text for XML, with its markup characters escaped, and the characters XML forbids left out. */
const xmlText = (text) => String(text)
  .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** A column's letters, from its index: 0 is A, and 26 is AA. */
function columnName(index) {
  let name = "";
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name;
  return name;
}

/**
 * The Excel format that shows a number as its text shows it: the same decimals,
 * the thousands separator, the sign and the percent. Python wrote the text, so
 * the workbook shows what the tab and the notebooks show, and holds the number
 * in full.
 */
function excelFormat(text) {
  const match = /^([+-]?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(%?)$/.exec(String(text).trim());
  if (!match) return "General";
  const [, sign, whole, decimals = "", percent] = match;
  const body = `${whole.includes(",") ? "#,##0" : "0"}${decimals ? `.${"0".repeat(decimals.length)}` : ""}${percent}`;
  return sign === "+" ? `+${body};-${body};+${body}` : body;
}

/**
 * A sheet's XML part, with its columns as wide as their texts, and printed to the
 * width of a landscape page. `styleOf` gives a cell's style.
 */
function worksheetXml(rows, styleOf) {
  const widths = [];
  const data = [];
  rows.forEach((row, r) => {
    const cells = [];
    const last = row.findLastIndex((cell) => cell != null && cell !== "" && (typeof cell !== "object" || (cell.v != null && cell.v !== "")));
    row.forEach((cell, c) => {
      if (cell == null || typeof cell !== "object") cell = { v: cell };
      const ref = `${columnName(c)}${r + 1}`;
      // an empty heading keeps its style, so the line under the headings runs on
      if (cell.v == null || cell.v === "") { if (cell.font === "head") cells.push(`<c r="${ref}" s="${styleOf(cell)}"/>`); return; }
      const style = styleOf(cell);
      const s = style ? ` s="${style}"` : "";
      cells.push(typeof cell.v === "number"
        ? `<c r="${ref}"${s}><v>${cell.v}</v></c>`
        : `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${xmlText(cell.v)}</t></is></c>`);
      // text at the end of its row, such as a title or a comment, runs on into the empty cells beside it
      if (c < last || typeof cell.v === "number" || cell.right) widths[c] = Math.max(widths[c] || 0, String(cell.text ?? cell.v).length);
    });
    if (cells.length) data.push(`<row r="${r + 1}">${cells.join("")}</row>`);
  });
  const cols = widths.length
    ? `<cols>${Array.from(widths, (w, i) => `<col min="${i + 1}" max="${i + 1}" width="${Math.min(60, Math.max(8, (w || 8) + 2))}" customWidth="1"/>`).join("")}</cols>`
    : "";
  return `${XML_HEAD}<worksheet xmlns="${SHEET_MAIN}"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>${cols}<sheetData>${data.join("")}</sheetData>`
    + '<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/><pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>';
}

/** The styles part: the fonts, a border under the headings, and each style the cells use. */
function stylesXml(styles, formats) {
  const font = (style = "", size = 11, color = "") => `<font>${style}<sz val="${size}"/>${color ? `<color rgb="${color}"/>` : ""}<name val="Calibri"/><family val="2"/></font>`;
  const numFmts = formats.length
    ? `<numFmts count="${formats.length}">${formats.map((code, i) => `<numFmt numFmtId="${164 + i}" formatCode="${xmlText(code)}"/>`).join("")}</numFmts>`
    : "";
  const xfs = styles.map(([fontId, fmt, right, border]) => `<xf numFmtId="${fmt}" fontId="${fontId}" fillId="0" borderId="${border}" xfId="0"`
    + `${fmt ? ' applyNumberFormat="1"' : ""}${fontId ? ' applyFont="1"' : ""}${border ? ' applyBorder="1"' : ""}`
    + (right ? ' applyAlignment="1"><alignment horizontal="right"/></xf>' : "/>"));
  return `${XML_HEAD}<styleSheet xmlns="${SHEET_MAIN}">${numFmts}`
    // in the order of XLSX_FONTS: plain, bold, the title, a failure in red, and a note in grey
    + `<fonts count="5">${font()}${font("<b/>")}${font("<b/>", 13)}${font("", 11, "FFC00000")}${font("<i/>", 11, "FF666666")}</fonts>`
    + '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    + '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FF999999"/></bottom><diagonal/></border></borders>'
    + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    + `<cellXfs count="${xfs.length}">${xfs.join("")}</cellXfs>`
    + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
}

/** The XML parts of a workbook of `sheets`, each a `name` and its `rows` of cells, by their paths in the zip. */
function xlsxParts(sheets) {
  const formats = [];
  const styles = [];
  const styleIds = new Map();
  const styleOf = (cell) => {
    let fmt = 0;
    if (cell.fmt && cell.fmt !== "General") {
      if (!formats.includes(cell.fmt)) formats.push(cell.fmt);
      fmt = 164 + formats.indexOf(cell.fmt);
    }
    const style = [XLSX_FONTS[cell.font || ""], fmt, cell.right ? 1 : 0, cell.font === "head" ? 1 : 0];
    const key = style.join("|");
    if (!styleIds.has(key)) { styleIds.set(key, styles.length); styles.push(style); }
    return styleIds.get(key);
  };
  styleOf({}); // the plain style comes first, as the default
  const parts = sheets.map((s, i) => [`xl/worksheets/sheet${i + 1}.xml`, worksheetXml(s.rows, styleOf)]);
  const type = (kind) => `application/vnd.openxmlformats-officedocument.spreadsheetml.${kind}+xml`;
  return [
    ["[Content_Types].xml", `${XML_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
      + `<Override PartName="/xl/workbook.xml" ContentType="${type("sheet.main")}"/><Override PartName="/xl/styles.xml" ContentType="${type("styles")}"/>`
      + parts.map(([path]) => `<Override PartName="/${path}" ContentType="${type("worksheet")}"/>`).join("") + "</Types>"],
    ["_rels/.rels", `${XML_HEAD}<Relationships xmlns="${PACKAGE_RELATIONSHIPS}"><Relationship Id="rId1" Type="${RELATIONSHIPS}/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
    ["xl/workbook.xml", `${XML_HEAD}<workbook xmlns="${SHEET_MAIN}" xmlns:r="${RELATIONSHIPS}"><sheets>`
      + sheets.map((s, i) => `<sheet name="${xmlText(s.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("") + "</sheets></workbook>"],
    ["xl/_rels/workbook.xml.rels", `${XML_HEAD}<Relationships xmlns="${PACKAGE_RELATIONSHIPS}">`
      + parts.map(([path], i) => `<Relationship Id="rId${i + 1}" Type="${RELATIONSHIPS}/worksheet" Target="${path.slice(3)}"/>`).join("")
      + `<Relationship Id="rId${parts.length + 1}" Type="${RELATIONSHIPS}/styles" Target="styles.xml"/></Relationships>`],
    ["xl/styles.xml", stylesXml(styles, formats)],
    ...parts,
  ];
}

/** An .xlsx workbook of `sheets`, as a file to download. */
function xlsxBlob(sheets) {
  const entries = xlsxParts(sheets).map(([name, text]) => ({ name, data: new TextEncoder().encode(text) }));
  return new Blob([zipBlob(entries)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}
