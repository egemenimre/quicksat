// quicksat scenario editor: the tabs and the Setup steps, where the comments
// written by hand belong, how a folder or a file is opened, and the start.

const PAGE_TITLE = "quicksat Scenario Editor";

/** The kinds of the folder's YAML files, whose `#` comments the page reviews. */
const YAML_KINDS = ["scenario", "power"];

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
  { group: "Start", title: "Folder", sections: ["project"] },
  { group: "Orbit and time", title: "Orbit", sections: ["orbit"] },
  { title: "Start, duration and step", sections: ["time"] },
  { group: "Spacecraft", title: "3D model", sections: ["model"], needs3d: true },
  { title: "Articulations", sections: ["articulations"], needs3d: true },
  { group: "Operations", title: "Ground targets", sections: ["targets"] },
  { title: "Attitudes", sections: ["attitudes"], needs3d: true },
  { title: "Attitude slew performance", sections: ["slew"] },
  { title: "Modes", sections: ["modes"] },
  { title: "Activities", sections: ["activities"] },
  { group: "Power", title: "Solar panels", sections: ["panels"], needs3d: true },
  { title: "Cells, losses and shading", sections: ["cells"] },
  { title: "Battery", sections: ["battery"] },
  { title: "Power conditioning", sections: ["conditioning"] },
  { title: "Consumption", sections: ["consumption"] },
  { group: "Finish", title: "Save the files", sections: ["save"] },
];

/** The file's own comments, for the files that can hold them. */
function fileComments(path) {
  if (path === project.names.scenario) return commentsBox(S, "Your comments on the overall scenario", { note: "They go in the comments field at the top of the file." });
  if (project.hasPower && path === project.names.power) return commentsBox(P, "Your comments on the overall power subsystem", { note: "They go in the comments field at the top of the file." });
  if (path.endsWith(".csv")) return el("p", { class: "hint", text: "A CSV has no place for comments on the whole file. Each row has its comments column." });
  return null;
}

/**
 * The block a comment belongs to, found from its key's path: the block, a name
 * for it, and the length of the block's own path.
 */
function commentTarget(kind, path) {
  const [first, second, third] = path;
  const item = (section, name) => section.items.find((x) => x.name === name);
  if (kind === "power") {
    if (first === "panels") return second != null && item(P.panels, second) ? [item(P.panels, second), `panels › ${second}`, 2] : [P.panels, "panels", 1];
    if (["self_shadowing", "battery", "conditioning"].includes(first)) return [P[first], first, 1];
    return [P, "the overall power subsystem", 0];
  }
  if (first === "orbit") return second === "sso" && S.orbit.source === "sso" ? [S.orbit.sso, "orbit › sso", 2] : [S.orbit, "orbit", 1];
  if (first === "3d_model") {
    const arts = S.model.articulations;
    if (second === "articulations") return third != null && item(arts, third) ? [item(arts, third), `articulations › ${third}`, 3] : [arts, "articulations", 2];
    return [S.model, "3d_model", 1];
  }
  if (first === "targets" || first === "attitudes") {
    return second != null && item(S[first], second) ? [item(S[first], second), `${first} › ${second}`, 2] : [S[first], first, 1];
  }
  if (first === "slew") return [S.slew, "slew", 1];
  if (first === "activities" && typeof second === "number" && S.activities[second]) {
    return [S.activities[second], `activity ${second + 1}, ${S.activities[second].title}`, 2];
  }
  return [S, "the overall scenario", 0];
}

// ---------------------------------------------------------------- opening a folder or a file

/** Whether a YAML file's data reads like one of a kind: a scenario, or a power system. */
const looksLike = {
  scenario: (data) => Boolean(data && typeof data === "object" && "orbit" in data && "activities" in data),
  power: (data) => Boolean(data && typeof data === "object" && "panels" in data),
  consumption: (file) => file.header.includes("equipment_id") && file.header.includes("units_on"),
};

/** The 3D model and the orbit file that the scenario names, taken from the picked files when they are there. */
async function takeModelAndOrbit(picked) {
  const glb = pickedFile(picked, S.model.file);
  if (glb) {
    const bytes = new Uint8Array(await glb.file.arrayBuffer());
    if (!(await view3d.load(bytes, S.model.file))) view3d.cube();
  } else if (!(model.bytes && model.fileName === S.model.file)) view3d.cube();
  const key = ORBIT_KEYS[S.orbit.source];
  const orbit = key && pickedFile(picked, S.orbit[key]);
  if (orbit) orbitFile = { name: S.orbit[key], text: await orbit.file.text() };
  else if (!(key && orbitFile && orbitFile.name === S.orbit[key])) orbitFile = null;
  state.selection = null;
}

/** A picked file of a kind: by its usual name, or else by what it holds. */
async function findPicked(picked, name, test) {
  const usual = pickedFile(picked, name);
  if (usual) return readPicked(usual);
  for (const entry of picked.files.filter((e) => !e.path.includes("/") && /\.(ya?ml|csv)$/i.test(e.path))) {
    let file;
    try { file = await readPicked(entry); } catch { continue; } // a file that does not read is not the one
    if (test(file)) return file;
  }
  return null;
}

/** The modes in the consumption table's columns, as they are now. */
const consumptionColumns = () => [...new Set(project.consumption.flatMap((row) => Object.keys(row.power)))];

const OPENERS = {
  folder: {
    pick: { folder: true },
    hint: "A folder with a scenario file, and the power files if it has them. Its 3D model and orbit file come with it.",
    async open(picked) {
      const scenario = await findPicked(picked, "scenario.yaml", (file) => file.data !== undefined && looksLike.scenario(file.data));
      if (!scenario) throw new Error(`${picked.folder || "The folder"} holds no scenario file: a YAML file with an orbit and activities, such as scenario.yaml.`);
      const power = await findPicked(picked, "power_system.yaml", (file) => file.data !== undefined && looksLike.power(file.data));
      const consumption = await findPicked(picked, "power_consumption.csv", (file) => Boolean(file.header) && looksLike.consumption(file));
      notices.files = {};
      DATA = { ...DATA, folder: picked.folder, label: picked.folder, files: { scenario, power, consumption }, model: null, orbit_file: null, checks: [] };
      project = readProject(DATA);
      S = project.scenario;
      P = project.power;
      await takeModelAndOrbit(picked);
      state.file = project.names.scenario;
      return ["scenario", "power", "consumption"];
    },
  },
  scenario: {
    label: "a scenario file",
    pick: { multiple: true },
    hint: "Pick its 3D model and its orbit file with it, to keep them with the scenario.",
    async open(picked) {
      const entry = picked.files.find((e) => /\.ya?ml$/i.test(e.path));
      if (!entry) throw new Error("Pick a scenario file: a YAML file with an orbit and activities.");
      const file = await readPicked(entry);
      if (!file.data || typeof file.data !== "object") throw new Error(`${file.name} holds no scenario.`);
      DATA.files.scenario = file;
      const scenario = readingFile("scenario", () => readScenario(file.data));
      scenario.modes = collectModes(scenario, consumptionColumns());
      project.scenario = S = scenario;
      project.names.scenario = file.name;
      await takeModelAndOrbit(picked);
      return ["scenario"];
    },
  },
  power: {
    label: "a power system file",
    pick: { accept: ".yaml,.yml" },
    async open(picked) {
      const file = await readPicked(picked.files[0]);
      DATA.files.power = file;
      project.power = P = readingFile("power", () => readPower(file.data));
      project.hasPower = true;
      project.names.power = file.name;
      return ["power"];
    },
  },
  consumption: {
    label: "a consumption file",
    pick: { accept: ".csv" },
    async open(picked) {
      const file = await readPicked(picked.files[0]);
      if (!file.header) throw new Error(`${file.name} is not a CSV file.`);
      DATA.files.consumption = file;
      const consumption = readingFile("consumption", () => readConsumption(file));
      project.consumption = consumption.rows;
      project.slewColumn = consumption.slewColumn;
      project.hasConsumption = true;
      project.names.consumption = file.name;
      for (const mode of consumption.modes) if (!S.modes.includes(mode)) S.modes.push(mode);
      return ["consumption"];
    },
  },
};

// ---------------------------------------------------------------- start

Object.assign(page, {
  onShow: apply3d,
  afterChange: () => view3d.update(),
  describeBinary: (file) => `A binary GLB file of ${(file.bytes.length / 1024).toFixed(1)} kB, with ${model.parts.length} named parts:\n\n${model.parts.map((p) => "  " + p.name).join("\n")}`,
});

$("#glb-input").addEventListener("change", (e) => loadGlbFile(e.target.files[0]));
$("#toggle-3d").addEventListener("click", toggle3d);
$("#hide-3d").addEventListener("click", toggle3d);
window.addEventListener("resize", () => view3d.resize());

const glb = DATA.model ? Uint8Array.from(atob(DATA.model.glb_base64), (c) => c.charCodeAt(0)) : null;
(glb ? view3d.load(glb, DATA.model.name) : Promise.resolve(false)).then((loaded) => {
  if (!loaded) view3d.cube();
  startPage();
  view3d.update();
});
