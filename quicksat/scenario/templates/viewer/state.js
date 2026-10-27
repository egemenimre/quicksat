// ---------------------------------------------------------------- State

const state = {
  t: 0,
  playing: false,
  speed: 300,
  page: "scenario",
  colourBy: "payload_mode",
  // the number of the activity that the designer's list has selected, or null
  selected: null,
  r: new THREE.Vector3(),
  v: new THREE.Vector3(),
  sun: new THREE.Vector3(),
  qBody: new THREE.Quaternion(),
  qEarth: new THREE.Quaternion(),
  lat: 0,
  lon: 0,
  beta: 0,
  light: 1,
  // the angle of each articulation, in degrees
  joints: ARTICULATIONS.map(() => 0),
  k: 0,
};
// Each target at the time cursor: its position in GCRS, in km, its place on the
// map, whether it is in view, and its range. A ground target's position is fixed
// to the Earth. A satellite's point below it is worked out once for each time
// of the grid, from its position and the Earth's orientation.
const targetState = TARGETS.map((target) => {
  const item = { target, r: new THREE.Vector3(), lat: 0, lon: 0, inView: false, range: 0, fixed: null, lats: null, lons: null };
  if (target.kind === "ground") {
    item.fixed = new THREE.Vector3(...groundPoint(target.latitude_deg, target.longitude_deg, target.altitude_km));
    [item.lat, item.lon] = [target.latitude_deg, target.longitude_deg];
  } else {
    item.lats = new Float64Array(N);
    item.lons = new Float64Array(N);
    for (let k = 0; k < N; k++) {
      const fixed = earthFixed(Q_EARTH.slice(4 * k, 4 * k + 4), target.r_km.slice(3 * k, 3 * k + 3));
      [item.lats[k], item.lons[k]] = geodeticOf(fixed);
    }
  }
  return item;
});
// The targets that the body and its parts point at, at the time cursor
state.pointed = new Set();
const dirty = { orbit: true, body: true, ground: true, charts: true, readouts: true };
const markAll = () => Object.keys(dirty).forEach((key) => (dirty[key] = true));

function updateState() {
  const [i, f] = sampleAt(state.t);
  vectorAt(R, i, f, state.r);
  vectorAt(V, i, f, state.v);
  vectorAt(S, i, f, state.sun).normalize();
  quaternionAt(Q_EARTH, i, f, state.qEarth);
  // the designer's data has no body orientation and no joint angles
  if (!DESIGNER) {
    // instant attitude changes and parking parts happen at once, not across the step
    quaternionAt(Q_BODY, i, attitudeFraction(TRACKS.attitude, T, i, f, state.t), state.qBody);
    ARTICULATIONS.forEach((joint, j) => {
      state.joints[j] = jointAngle(joint, TRACKS.platform_mode, T, i, f, state.t);
    });
  }
  state.lat = LAT[i] + (LAT[i + 1] - LAT[i]) * f;
  state.lon = ((angleBetween(LON[i], LON[i + 1], f) + 540) % 360) - 180;
  state.beta = BETA[i] + (BETA[i + 1] - BETA[i]) * f;
  state.light = lightFraction(TRACKS.illumination, T, LIGHT, state.t, i);
  state.k = f < 0.5 ? i : i + 1;
  for (const item of targetState) {
    if (item.fixed) {
      item.r.copy(item.fixed).applyQuaternion(state.qEarth);
    } else {
      vectorAt(item.target.r_km, i, f, item.r);
      item.lat = item.lats[i] + (item.lats[i + 1] - item.lats[i]) * f;
      item.lon = ((angleBetween(item.lons[i], item.lons[i + 1], f) + 540) % 360) - 180;
    }
    item.inView = passAt(item.target.passes, state.t, T_END) !== null;
    item.range = item.r.distanceTo(state.r);
  }
  state.pointed = new Set(pointedTargets(POINTING, TRACKS.attitude, TRACKS.platform_mode, ARTICULATIONS, state.t));
  markAll();
}

function setTime(time) {
  state.t = clamp(time, 0, T_END);
  updateState();
  reportView();
}

const lightAt = (time) => pieceAt(TRACKS.illumination, time).value;
// The occurrence under way, or null in the time after the last one
const activityAt = (time) => occurrenceAt(OCCURRENCES, time, T_END);

// ---------------------------------------------------------------- The Activity Designer

/**
 * Send a message to the editor's page, which holds the designer in a frame.
 * Both pages come from the editor's server, so they share an origin.
 */
function tellEditor(type, fields = {}) {
  if (!DESIGNER || window.parent === window) return;
  window.parent.postMessage({ source: "quicksat-designer", type, ...fields }, location.origin);
}

/** Select an activity of the list by its number, or none with null. Its occurrences stand out. */
function select(number) {
  state.selected = number;
  groundView.retrack();
  orbitView.retrack();
  dirty.charts = true;
}

/**
 * A click on the timeline or on the track: the time cursor moves there, and the
 * activity under way then is selected, here and in the editor's list.
 */
function pick(time) {
  setTime(time);
  const occurrence = activityAt(state.t);
  select(occurrence ? occurrence.number : null);
  tellEditor("pick", { number: state.selected });
}

// The time cursor and the charts' zoom go to the editor a moment after they
// stop changing. The editor passes them back in the address of the next run,
// so that the view stays where it was.
let viewTimer = null;
function reportView() {
  if (!DESIGNER) return;
  clearTimeout(viewTimer);
  viewTimer = setTimeout(() => {
    const [from, to] = charts.shown();
    tellEditor("view", { t: state.t, zoom: [from, to] });
  }, 300);
}
