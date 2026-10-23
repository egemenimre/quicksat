// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests for the Sizing Editor's Excel export, in
// quicksat/editor/templates/sizing/export.js, run in Node from the repository
// with:
//
//     node --test "tests/**/*.test.js"
//
// The workbook comes from the sample's own page, sample/sizing/editor/editor.html,
// which holds the budgets as Python worked them out when it wrote the page. The
// zip is files.js's own.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const TEMPLATES = path.join(ROOT, "quicksat", "editor", "templates");
for (const file of [path.join(TEMPLATES, "shared", "files.js"), path.join(TEMPLATES, "sizing", "export.js")]) {
  vm.runInThisContext(fs.readFileSync(file, "utf8"), { filename: file });
}
const { budgetSheets, columnName, excelFormat, xlsxBlob, xlsxParts, xmlText } = vm.runInThisContext(
  "({ budgetSheets, columnName, excelFormat, xlsxBlob, xlsxParts, xmlText })",
);

const PAGE = fs.readFileSync(path.join(ROOT, "sample", "sizing", "editor", "editor.html"), "utf8");
const RESULTS = JSON.parse(/<script id="project" type="application\/json">([\s\S]*?)<\/script>/.exec(PAGE)[1]).results;
const NAMES = {
  mission: "mission.yaml", requirements: "requirements.yaml", mass: "mass_budget_config.yaml", equipment: "equipment.csv",
  data: "pl_dataflow_model.yaml", deltav: "delta_v_config.yaml", manoeuvres: "manoeuvres.csv", agility: "agility_config.yaml",
};
const ABOUT = { folder: "sample", at: "24/10/2026, 12:00:00", source: "Worked out by quicksat when the page was written.", changed: [], names: NAMES };

/** The workbook's parts, as text, by their paths. */
const partsOf = (sheets) => Object.fromEntries(xlsxParts(sheets));

/** Whether XML is well formed: its tags close in order, and its text escapes its markup. */
function assertWellFormed(name, xml) {
  const body = xml.replace(/^<\?xml[^>]*\?>\s*/, "");
  const open = [];
  for (const [, close, tag, empty] of body.matchAll(/<(\/?)([A-Za-z_][\w:.-]*)(?:\s[^<>]*?)?(\/?)>/g)) {
    if (empty) continue;
    if (close) assert.equal(open.pop(), tag, name);
    else open.push(tag);
  }
  assert.deepEqual(open, [], name);
  assert.ok(!/&(?!amp;|lt;|gt;|quot;)/.test(body), name);
  assert.ok(!body.replace(/<[^<>]*>/g, "").includes(">"), name);
}

/** The sheet's XML part, by the sheet's name. */
function sheetXml(sheets, name) {
  const index = sheets.findIndex((s) => s.name === name);
  assert.ok(index >= 0, name);
  return partsOf(sheets)[`xl/worksheets/sheet${index + 1}.xml`];
}

test("a number's format shows the decimals, thousands, sign and percent of its text", () => {
  assert.equal(excelFormat("62.00"), "0.00");
  assert.equal(excelFormat("1,234.57"), "#,##0.00");
  assert.equal(excelFormat("-2.89"), "0.00");
  assert.equal(excelFormat("3"), "0");
  assert.equal(excelFormat("+12.0"), "+0.0;-0.0;+0.0");
  assert.equal(excelFormat("87.4%"), "0.0%");
  assert.equal(excelFormat("+153.3%"), "+0.0%;-0.0%;+0.0%");
  // what is not a plain number is left to Excel
  assert.equal(excelFormat("1e-05"), "General");
  assert.equal(excelFormat("—"), "General");
});

test("columns are named as Excel names them", () => {
  assert.deepEqual([0, 25, 26, 51, 701, 702].map(columnName), ["A", "Z", "AA", "AZ", "ZZ", "AAA"]);
});

test("text is escaped for XML, and the characters XML forbids are left out", () => {
  assert.equal(xmlText('a < b & "c" > d\u0001'), "a &lt; b &amp; &quot;c&quot; &gt; d");
});

test("the sample has an overview, then a sheet for each budget, as the tab shows them", () => {
  const sheets = budgetSheets(RESULTS, ABOUT);
  assert.deepEqual(sheets.map((s) => s.name), ["Overview", "Mass in orbit", "Mass on ground", "Delta-V", "Data", "Agility roll", "Agility pitch"]);
});

test("every part is well formed, and no sheet is protected", () => {
  const sheets = budgetSheets(RESULTS, ABOUT);
  const parts = partsOf(sheets);
  assert.equal(Object.keys(parts)[0], "[Content_Types].xml");
  for (const [name, xml] of Object.entries(parts)) assertWellFormed(name, xml);
  // a protected sheet makes parts of a table hard to select
  sheets.forEach((_, i) => assert.doesNotMatch(parts[`xl/worksheets/sheet${i + 1}.xml`], /<sheetProtection/));
  for (const name of sheets.map((s) => s.name)) assert.match(parts["xl/workbook.xml"], new RegExp(`<sheet name="${name}"`));
});

test("each number of a table is written in full, with no formula", () => {
  const sheets = budgetSheets(RESULTS, ABOUT);
  const mass = RESULTS.budgets.mass.tables;
  for (const [name, table] of [["Mass in orbit", mass.budget["10"]], ["Mass on ground", mass.budget["00"]], ["Mass in orbit", mass.by_subsystem]]) {
    const xml = sheetXml(sheets, name);
    const numbers = table.rows.flatMap((row) => row.values).filter((value) => value != null);
    assert.ok(numbers.length > 10, name);
    for (const value of numbers) assert.ok(xml.includes(`<v>${value}</v>`), `${name}: ${value}`);
  }
  for (const s of sheets) assert.ok(!sheetXml(sheets, s.name).includes("<f>"), s.name);
  // the propellant required, as the tab shows it, and in full
  const required = RESULTS.budgets.deltav.tables.propellant.rows.find((row) => row.type === "total");
  assert.ok(String(required.values[1]).length > required.cells[1].length);
  assert.ok(sheetXml(sheets, "Delta-V").includes(`<v>${required.values[1]}</v>`));
});

test("the mass sheets hold the tables with comments and without subtotals", () => {
  const sheets = budgetSheets(RESULTS, ABOUT);
  const comment = RESULTS.budgets.mass.tables.budget["00"].rows.map((row) => row.cells.at(-1)).find(Boolean);
  for (const name of ["Mass in orbit", "Mass on ground"]) assert.ok(sheetXml(sheets, name).includes(xmlText(comment)), name);
  const subtotal = RESULTS.budgets.mass.tables.budget["11"].rows.find((row) => row.type === "subsystem_subtotal").cells[1];
  for (const name of ["Mass in orbit", "Mass on ground"]) assert.ok(!sheetXml(sheets, name).includes(subtotal), `${name}: ${subtotal}`);
  // the launcher's side is on the ground only
  assert.ok(sheetXml(sheets, "Mass on ground").includes("Launcher total"));
  assert.ok(!sheetXml(sheets, "Mass in orbit").includes("Launcher total"));
});

test("an agility sheet holds its own axis, with the full set of wheels, and its own checks", () => {
  const sheets = budgetSheets(RESULTS, ABOUT);
  const roll = sheetXml(sheets, "Agility roll");
  assert.ok(roll.includes("roll_40") && !roll.includes("Slew table, against pitch_40"));
  const figures = RESULTS.budgets.agility.variants["roll|0"].figures;
  for (const figure of figures) assert.ok(roll.includes(`<v>${figure.number}</v>`), figure.label);
});

test("the overview says when the figures are out of date", () => {
  const sheets = budgetSheets(RESULTS, { ...ABOUT, changed: ["equipment.csv"] });
  assert.ok(sheetXml(sheets, "Overview").includes("equipment.csv changed since, so these figures may be out of date."));
  assert.ok(!sheetXml(budgetSheets(RESULTS, ABOUT), "Overview").includes("out of date"));
});

test("a budget without its files has no sheet, and one that quicksat cannot work out has its error", () => {
  const results = { ...RESULTS, budgets: { ...RESULTS.budgets, mass: null, data: { error: "data volume needed" } } };
  const sheets = budgetSheets(results, ABOUT);
  assert.deepEqual(sheets.map((s) => s.name), ["Overview", "Delta-V", "Data", "Agility roll", "Agility pitch"]);
  assert.ok(sheetXml(sheets, "Data").includes("quicksat cannot work out this budget: data volume needed"));
});

test("the workbook is a zip of its parts", async () => {
  const blob = xlsxBlob(budgetSheets(RESULTS, ABOUT));
  assert.equal(blob.type, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.deepEqual([...bytes.slice(0, 4)], [0x50, 0x4b, 0x03, 0x04]);
});
