// quicksat sizing editor: the tabs and the Setup steps, where the comments
// written by hand belong, how a folder or a file is opened, and the start.

// ---------------------------------------------------------------- the tabs and the steps

const TABS = [
  { id: "setup", title: "Setup" },
  { id: "budgets", title: "Budgets", draw: drawBudgets, count: failingBudgets },
  { id: "mission", title: "Mission", sections: ["mission"], intro: "The reference orbit and the design life, from mission.yaml. The data, delta-V and agility budgets read them." },
  { id: "requirements", title: "Requirements", sections: ["slews", "required_storage"], intro: "What the mission asks of the spacecraft, from requirements.yaml. The agility and data budgets check their figures against it." },
  { id: "mass", title: "Mass", budget: "mass", top: () => overallBox("mass"), sections: ["locations"], intro: "The mass budget's settings: each location's margins and harness. The equipment list has a tab of its own." },
  { id: "equipment", title: "Equipment", budget: "mass", sections: ["equipment"], intro: "Every item of the spacecraft, from equipment.csv. The totals under the table add the rows as entered." },
  { id: "data", title: "Data", budget: "data", top: () => overallBox("data"), sections: ["generation", "downlink", "storage"], intro: "The payload data flow: what the payload makes, what the link sends, and the memory between passes." },
  { id: "deltav", title: "Delta-V", budget: "deltav", top: () => overallBox("deltav"), sections: ["dvconfig", "manoeuvres"], intro: "The delta-V budget: the propulsion, the margin and the manoeuvres." },
  { id: "agility", title: "Agility", budget: "agility", top: () => overallBox("agility"), sections: ["cases", "wheels"], intro: "The agility budget: the spacecraft cases, the wheels that slew them, and the settling time." },
  { id: "files", title: "Files", sections: ["folder"] },
];

const STEPS = [
  { group: "Start", title: "Folder", sections: ["folder"] },
  { group: "Mission", title: "Reference orbit and design life", sections: ["mission"] },
  { group: "Requirements", title: "Mission requirements", sections: ["slews", "required_storage"] },
  { group: "Mass", title: "Locations: margins and harness", sections: ["locations"], top: () => overallBox("mass") },
  { title: "Equipment", sections: ["equipment"] },
  { group: "Data", title: "Payload data generation", sections: ["generation"], top: () => overallBox("data") },
  { title: "Downlink and storage", sections: ["downlink", "storage"] },
  { group: "Delta-V", title: "Propulsion and margin", sections: ["dvconfig"], top: () => overallBox("deltav") },
  { title: "Manoeuvres", sections: ["manoeuvres"] },
  { group: "Agility", title: "Inertia cases", sections: ["cases"], top: () => overallBox("agility") },
  { title: "Reaction wheels and settling", sections: ["wheels"] },
  { group: "Finish", title: "Save the files", sections: ["save"] },
];

// ---------------------------------------------------------------- the Files tab

/** The file's own comments, for the files that can hold them. */
function fileComments(path) {
  const n = project.names;
  if (path === n.mission) return commentsBox(M, "Your comments on the mission", { note: "They go in the comments field at the top of the file." });
  if (path === n.requirements) return commentsBox(project.requirements, "Your comments on the requirements", { note: "They go in the comments field at the top of the file." });
  for (const key of ["mass", "data", "deltav", "agility"]) {
    if (path === n[key]) return commentsBox(project[key], `Your comments on ${BUDGETS[key].label}`, { note: "They go in the comments field at the top of the file." });
  }
  if (path.endsWith(".csv")) return el("p", { class: "hint", text: "A CSV has no place for comments on the whole file. Each row has its comments column." });
  return null;
}

// ---------------------------------------------------------------- comments written by hand

/**
 * The block a comment belongs to: the block itself, a name for it, and the depth
 * of its path. A comment on a field inside the block keeps the field's name.
 */
function commentTarget(kind, path) {
  const [first, second] = path;
  const find = (list, name) => list.find((x) => x.name === name);
  if (kind === "mission") return [M, "the mission", 0];
  if (kind === "requirements") {
    const R = project.requirements;
    const S = R.agility.slews;
    if (first === "agility") {
      const [, , name] = path;
      if (second !== "slews") return [R.agility, "agility", 1];
      return name != null && find(S.items, name) ? [find(S.items, name), `slews › ${name}`, 3] : [S, "agility › slews", 2];
    }
    if (first === "data") return [R.data, "data", 1];
    return [R, "the requirements", 0];
  }
  if (kind === "mass") {
    const L = project.mass.locations;
    if (first === "locations") return second != null && find(L.items, second) ? [find(L.items, second), `locations › ${second}`, 2] : [L, "locations", 1];
    return [project.mass, BUDGETS.mass.label, 0];
  }
  if (kind === "data") {
    if (["generation", "downlink", "storage"].includes(first)) return [project.data[first], first, 1];
    return [project.data, BUDGETS.data.label, 0];
  }
  if (kind === "deltav") {
    if (["propulsion", "collision_avoidance"].includes(first)) return [project.deltav[first], first, 1];
    return [project.deltav, BUDGETS.deltav.label, 0];
  }
  const C = project.agility.cases;
  if (first === "inertia_cases") return second != null && find(C.items, second) ? [find(C.items, second), `inertia_cases › ${second}`, 2] : [C, "inertia_cases", 1];
  if (first === "wheels") return [project.agility.wheels, "wheels", 1];
  return [project.agility, BUDGETS.agility.label, 0];
}

// ---------------------------------------------------------------- opening a folder or a file

const PAGE_TITLE = "quicksat Sizing Editor";

/** The kinds of the folder's YAML files, whose `#` comments the page reviews. */
const YAML_KINDS = ["mission", "requirements", "mass", "data", "deltav", "agility"];

/** The folder's files, by kind, in the order the Start step lists them. */
const FILES = Object.keys(NAMES).map((kind) => ({ kind }));

/** Use an opened file of a kind in place of the page's. */
function useFile(kind, file) {
  if (/\.csv$/i.test(NAMES[kind]) && !file.header) throw new Error(`${file.name} is not a CSV file.`);
  DATA.files[kind] = file;
  project[kind] = readingFile(kind, () => READERS[kind](file));
  project.names[kind] = file.name;
  if (kind === "mission") M = project.mission;
}

/** The opener of one file of a kind, for its tab. */
const fileOpener = (kind, label) => ({
  label,
  pick: { accept: /\.csv$/i.test(NAMES[kind]) ? ".csv" : ".yaml,.yml" },
  async open(picked) {
    useFile(kind, await readPicked(picked.files[0]));
    return [kind];
  },
});

const OPENERS = {
  folder: {
    pick: { folder: true },
    hint: "A folder with the sizing files: mission.yaml, and the files of the budgets it holds.",
    async open(picked) {
      const files = {};
      for (const [kind, name] of Object.entries(NAMES)) {
        const entry = pickedFile(picked, name);
        files[kind] = entry ? await readPicked(entry) : null;
      }
      if (!Object.values(files).some(Boolean)) throw new Error(`${picked.folder || "The folder"} holds none of the sizing files, such as mission.yaml or equipment.csv.`);
      notices.files = {};
      DATA = { ...DATA, folder: picked.folder, label: picked.folder, files, checks: [] };
      project = readProject(DATA);
      M = project.mission;
      state.file = project.names.mission;
      return Object.keys(NAMES);
    },
  },
  mission: fileOpener("mission", "a mission file"),
  requirements: fileOpener("requirements", "a requirements file"),
  mass: fileOpener("mass", "a mass settings file"),
  equipment: fileOpener("equipment", "an equipment list"),
  data: fileOpener("data", "a data flow file"),
  deltav: fileOpener("deltav", "a delta-V settings file"),
  manoeuvres: fileOpener("manoeuvres", "a manoeuvre list"),
  agility: fileOpener("agility", "an agility settings file"),
};

// ---------------------------------------------------------------- start

Object.assign(page, {
  beforeDraw: () => live.clear(),
  afterChange: () => {
    for (const update of live) update();
    scheduleBudgets();
  },
  // the folder's opener finds each file by its usual name
  draftPath: (file) => NAMES[file.kind],
  serverChanged: () => {
    if (server.state === "up" && changedSince().length) workOutBudgets();
    refreshBudgets();
  },
});

startPage();
// the results that Python worked out come from the files as the page first holds them
budgets.texts = budgetTexts();
