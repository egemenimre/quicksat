// ---------------------------------------------------------------- Data and its checks

function stop(message) {
  document.body.innerHTML = "";
  document.body.append(element("div", { class: "empty" }, [element("div", { text: message })]));
  throw new Error(message);
}

if (typeof THREE === "undefined" || typeof uPlot === "undefined" || typeof scenarioProblem === "undefined") {
  stop("This is the page's source, without its libraries. Build the page with viewer_page() in quicksat.scenario.viewer.");
}
const DATA = window.quicksat || {};
const scenario = DATA.scenario;
if (scenarioProblem(scenario)) stop(scenarioProblem(scenario));
const [power, powerNote] = checkPower(DATA.power, scenario);
// The Activity Designer's page, which the editor's server sends with the run's
// data inside, or null for the normal viewer. Its data has no body
// orientation, no roll, pitch and yaw, and no joint angles, so the page draws
// the orbit, the map and the timeline only, with no body view. The run may
// stop before its end.
const DESIGNER = scenario.designer || null;

const THEME = {
  accent: "#22d3ee",
  text: "#cdd9ea",
  muted: "#7d93b3",
  dim: "#4f6789",
  grid: "rgba(36, 64, 95, 0.55)",
  tick: "rgba(36, 64, 95, 0.9)",
  chartBg: "#070f1d",
  eclipseBand: "rgba(47, 61, 85, 0.45)",
  generated: "#2dd4bf",
  generatedFill: "rgba(45, 212, 191, 0.13)",
  netSwatch: "linear-gradient(90deg, #2dd4bf 50%, #f5b13d 50%)",
  consumed: "#f5b13d",
  consumedFill: "rgba(245, 177, 61, 0.16)",
  soc: "#22d3ee",
  socFill: "rgba(34, 211, 238, 0.12)",
  limit: "#f87171",
  excessBand: "rgba(245, 177, 61, 0.22)",
  critical: "#f87171",
  warning: "#f5b13d",
};
const MUTED_VALUE = "#898781"; // the notebook's colour for a value past its palette
const VECTOR_COLOURS = { velocity: "#7fd1ff", nadir: "#ff8c42", orbitNormal: "#c084fc", sun: "#ffd23f", normal: "#2dd4bf" };
const AXIS_COLOURS = ["#f87171", "#4ade80", "#60a5fa"];
const SPEEDS = [10, 30, 60, 120, 300, 600, 1200];
const D2R = Math.PI / 180;

const GRID = scenario.grid;
const T = GRID.t_s;
const N = T.length;
const T_END = T[N - 1];
const STEP = T[1] - T[0];
const R = GRID.r_km;
const V = GRID.v_km_s;
const S = GRID.sun;
const Q_BODY = GRID.q_body;
const Q_EARTH = GRID.q_earth;
const LAT = GRID.lat_deg;
const LON = GRID.lon_deg;
const BETA = GRID.beta_deg;
// The fraction of the sun's disk seen
const LIGHT = GRID.light;
const MINUTES = T.map((t) => t / 60);
const PERIOD = scenario.orbit.period_s;
const R_E = scenario.earth_radius_km;
const START_MS = Date.parse(scenario.start + "Z");
const TRACKS = scenario.tracks;
// The eclipses, each from its entry to its exit
const ECLIPSES = joinEclipses(TRACKS.illumination);
const ROWS = [
  ["illumination", "ILLUMINATION"],
  ["attitude", "ATTITUDE"],
  ["payload_mode", "PAYLOAD"],
  ["platform_mode", "PLATFORM"],
];
const OCCURRENCES = scenario.occurrences;
// A scenario read from text, not a file, has no file name
const SCENARIO_FILE = scenario.scenario_file || "the scenario";
const COLOURS = scenario.colours;
// Without power.js there are no panels, and the body is a plain 1 m cube
const PANELS = power ? power.spacecraft.panels : [];
// The colour of each panel's line on the Power page, apart from the colours
// of the generated and consumed lines
const PANEL_COLOURS = ["#a78bfa", "#f472b6", "#60a5fa", "#a3e635", "#fb7185", "#c084fc", "#38bdf8", "#facc15"];
const panelColour = (j) => PANEL_COLOURS[j % PANEL_COLOURS.length];
// The net power, which is the generated less the consumed
const NET_W = power ? power.grid.generated_w.map((generated, k) => generated - power.grid.consumed_w[k]) : [];
const BODY = power ? power.spacecraft.body_m : [1, 1, 1];
// The spacecraft's 3D model, or null without one. It takes the place of the
// cube and the panel boxes once it is decoded.
const MODEL = scenario.model;
// The parts of the model that turn, such as solar wings. Each has its angle at
// each time of the grid.
const ARTICULATIONS = MODEL ? MODEL.articulations : [];
// The body's attitude for the Attitude page: roll, pitch and yaw, the rates,
// the slew limits and the files to download
const ATTITUDE = scenario.attitude;
const EXCESSES = excessPieces(T, ATTITUDE, TRACKS.attitude);
// The ground and satellite targets: each with its passes, and a satellite with
// its positions at each time of the grid. `pointing` names the targets of each
// attitude and articulation.
const TARGETS = scenario.targets;
const POINTING = scenario.pointing;
// Every pass of every target, in time order, for the Targets page's table
const PASSES = TARGETS.flatMap((target) => target.passes.map((pass) => ({ target, ...pass }))).sort(
  (a, b) => a.start_s - b.start_s,
);
// When the body or a part points at each target, by its name
// The parts park by the platform's mode
const POINTED = pointedSpans(POINTING, TRACKS.attitude, TRACKS.platform_mode, ARTICULATIONS);
// A ground target is pink and a satellite target lime: bright while in view,
// and dim otherwise
const TARGET_COLOURS = { ground: ["#f472b6", "#7a4763"], satellite: ["#a3e635", "#567b2a"] };
const targetColour = (target, inView = true) => TARGET_COLOURS[target.kind][inView ? 0 : 1];
// The body view draws an arrow to at most this many targets in view, the nearest
const MOST_ARROWS = 4;
const AXIS_VECTORS = { "+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0], "+z": [0, 0, 1], "-z": [0, 0, -1] };
const MONO = getComputedStyle(document.body).fontFamily;

// ---------------------------------------------------------------- Helpers

const $ = (selector) => document.querySelector(selector);
const colourOf = (value) => COLOURS[value] || MUTED_VALUE;

const coastlines = (() => {
  try {
    return JSON.parse($("#coastlines").textContent);
  } catch (error) {
    return [];
  }
})();

/** White text on a dark fill, and near-black on a light one, as the notebook's plots do. */
function textOn(fill) {
  const n = parseInt(fill.slice(1), 16);
  const luminance = (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
  return luminance < 0.5 ? "#ffffff" : "#0b0b0b";
}

function clockText(seconds) {
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return (h ? `${h}h ${pad(m)}m ` : `${m}m `) + `${pad(s % 60)}s`;
}

/** UTC as start plus the seconds. A browser's clock ignores leap seconds. */
function utcText(seconds, withDate = true) {
  const text = new Date(START_MS + seconds * 1000).toISOString().replace("T", " ");
  return withDate ? text.slice(0, 19) : text.slice(11, 19);
}

function numberText(x, digits = 3) {
  return String(Number(x.toFixed(digits)));
}

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

/** The grid step that holds `time`, and how far `time` is along it. */
function sampleAt(time) {
  return stepAt(T, time);
}

/** The nearest grid index to `time`. */
function indexAt(time) {
  const [i, f] = sampleAt(time);
  return f < 0.5 ? i : i + 1;
}

function vectorAt(array, i, f, out) {
  const a = 3 * i;
  return out.set(
    array[a] + (array[a + 3] - array[a]) * f,
    array[a + 1] + (array[a + 4] - array[a + 1]) * f,
    array[a + 2] + (array[a + 5] - array[a + 2]) * f,
  );
}

/** A quaternion between two grid steps, the short way round. */
function quaternionAt(array, i, f, out) {
  const a = 4 * i;
  const sign = array[a] * array[a + 4] + array[a + 1] * array[a + 5] + array[a + 2] * array[a + 6] + array[a + 3] * array[a + 7] < 0 ? -1 : 1;
  return out
    .set(
      array[a] + (sign * array[a + 4] - array[a]) * f,
      array[a + 1] + (sign * array[a + 5] - array[a + 1]) * f,
      array[a + 2] + (sign * array[a + 6] - array[a + 2]) * f,
      array[a + 3] + (sign * array[a + 7] - array[a + 3]) * f,
    )
    .normalize();
}

/** LVLH to GCRS: x along track, y minus the orbit normal, z nadir. */
function lvlhMatrix(r, v, out) {
  const z = r.clone().negate().normalize();
  const y = r.clone().cross(v).negate().normalize();
  const x = y.clone().cross(z);
  return out.makeBasis(x, y, z);
}

// The designer's layout: the track colours move to the map, and each target's
// passes to the timeline, before the views and the charts are built
if (DESIGNER) {
  document.body.classList.add("designer");
  $("#vp-ground").append($("#orbit-legend"));
  $("#charts").classList.add("designer");
  if (TARGETS.length) {
    $("#charts").classList.add("lanes");
    $("#charts").append($("#head-lanes"), $("#chart-lanes"));
  }
}
