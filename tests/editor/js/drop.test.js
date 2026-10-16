// quicksat Basic satellite sizing tool
//
// Copyright (C) Egemen Imre
//
// Licensed under GNU GPL v3.0. See LICENSE.md for more info.

// Tests that the editor's page reads a drop as the file picker does, run in Node
// from the repository with:
//
//     node --test "tests/**/*.test.js"
//
// A browser cannot be made to drop a folder from a script, so these stand-ins
// give `droppedFiles` in quicksat/editor/templates/shared/open.js the parts of
// the browser's drop that it reads: the items, their entries and the files.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const OPEN = path.resolve(__dirname, "..", "..", "..", "quicksat", "editor", "templates", "shared", "open.js");
vm.runInThisContext(fs.readFileSync(OPEN, "utf8"), { filename: OPEN });
const droppedFiles = vm.runInThisContext("droppedFiles");

/** A file's entry, as the browser gives it. */
const fileEntry = (name) => ({ name, isDirectory: false, file: (resolve) => resolve({ name }) });

/** A folder's entry, whose reader gives its children in batches of two, then an empty one. */
function folderEntry(name, children) {
  return {
    name,
    isDirectory: true,
    createReader() {
      const left = [...children];
      return { readEntries: (resolve) => resolve(left.splice(0, 2)) };
    },
  };
}

/** A drop of some entries, with the loose files the browser lists beside them. */
const drop = (entries, files = []) => ({
  items: entries.map((entry) => ({ kind: "file", webkitGetAsEntry: () => entry })),
  files,
});

test("a dropped folder gives each file with its path inside the folder", async () => {
  const folder = folderEntry("winter", [
    fileEntry("scenario.yaml"),
    fileEntry("power_system.yaml"),
    folderEntry("orbits", [fileEntry("sso.tle")]),
    fileEntry("power_consumption.csv"),
  ]);
  const dropped = await droppedFiles(drop([folder]));
  assert.equal(dropped.folder, "winter");
  assert.equal(dropped.isFolder, true);
  assert.deepEqual(
    dropped.files.map((entry) => entry.path),
    ["scenario.yaml", "power_system.yaml", "orbits/sso.tle", "power_consumption.csv"],
  );
});

test("loose files come with their names, and no folder", async () => {
  const files = [{ name: "scenario.yaml" }, { name: "spacecraft.glb" }];
  const dropped = await droppedFiles(drop(files.map((file) => fileEntry(file.name)), files));
  assert.deepEqual(dropped, { folder: "", files: files.map((file) => ({ path: file.name, file })), isFolder: false });
});

test("a folder dropped with anything else is refused", async () => {
  const two = drop([folderEntry("a", []), folderEntry("b", [])]);
  await assert.rejects(droppedFiles(two), /one folder/);
  const mixed = drop([folderEntry("a", []), fileEntry("scenario.yaml")], [{ name: "scenario.yaml" }]);
  await assert.rejects(droppedFiles(mixed), /one folder/);
});
