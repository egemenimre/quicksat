// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests that the editor's page finds the same keys and comments as editor.py,
// run in Node from the repository with:
//
//     node --test "tests/**/*.test.js"
//
// quicksat/editor/templates/shared/open.js finds the # comments of a file opened
// in the browser. It must agree with comment_blocks in editor.py, or a comment
// would land in a different block depending on how the folder was opened. The
// cases and Python's answers are in open_cases.json. tests/editor/test_open_js.py
// writes them, and checks that they are still Python's.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OPEN = path.join(ROOT, "quicksat", "editor", "templates", "shared", "open.js");

// A script's functions are globals, as in the page. Run in this realm, the
// arrays they return compare with deepEqual.
vm.runInThisContext(fs.readFileSync(OPEN, "utf8"), { filename: OPEN });
const { keyLines, commentBlocks } = vm.runInThisContext("({ keyLines, commentBlocks })");

const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "open_cases.json"), "utf8"));

test("the cases hold the awkward layouts and quicksat's own files", () => {
  assert.ok(CASES.some((c) => c.name.startsWith("awkward: ")));
  assert.ok(CASES.some((c) => c.name.startsWith("sample/")));
});

for (const { name, text, keys, blocks } of CASES) {
  test(`the page finds Python's keys and comments: ${name}`, () => {
    assert.deepEqual(keyLines(text), keys);
    assert.deepEqual(commentBlocks(text), blocks);
  });
}
