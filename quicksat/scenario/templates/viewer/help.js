// ---------------------------------------------------------------- Explanations

/** What each window, value and button is, for the box that appears on hover. */
const HELP = {
  orbit: {
    title: "Orbit view",
    text:
      "The orbit in GCRS, the Earth-centred frame that does not turn with the Earth. The Earth and its " +
      "coastlines turn under the orbit. The track takes its colours from the row chosen in the legend. The " +
      "yellow arrow points at the sun. The Earth's shadow is two dark cones: the umbra, and around it the " +
      "lighter penumbra. The two part only far from the Earth, as in a high orbit. The ground targets are " +
      "pink and the satellite targets lime: bright while in view, and dim otherwise. Drag to turn the view, right-drag to pan, and scroll to zoom.",
  },
  body: {
    title: "Body view",
    text:
      "The spacecraft, with its body axes x, y and z in red, green and blue. The arrows show the velocity, " +
      "the nadir, the orbit normal and the sun. The first three are close to the LVLH axes: x along track, " +
      "z nadir, and y minus the orbit normal. The spacecraft is the 3D model that 3d_model names in the " +
      "scenario file, or a 1 m cube without one. It is scaled to fit the view. The parts that the scenario " +
      "names as articulations, such as solar wings, turn toward their direction, such as the sun. An " +
      "arrow points at each of the nearest targets in view, and at the targets the body or a part points at: " +
      "pink for a ground target, and lime for a satellite.",
  },
  ground: {
    title: "Ground track",
    text:
      "The point below the spacecraft, in geodetic latitude and longitude. The track has the same colours " +
      "as the orbit view. The dark area is the night side, and the dashed line is the terminator. The " +
      "yellow dot is the point below the sun, and the red dot is the spacecraft. A lime circle is the point " +
      "below a satellite target, and a pink square a ground target, each filled while in view.",
  },
  timeline: {
    title: "Timeline",
    text:
      "The illumination, the attitude, and the payload's and the platform's modes against time, as the " +
      "scenario run gives them. The platform's mode reads slew while the body turns. A red box " +
      "marks an activity outside its constraint. A dashed red line marks an activity with a negative " +
      "duration. A dashed amber box marks an event that never came. A dashed line marks each whole orbit " +
      "from the start. In the Activity Designer, an amber band marks a turn faster than the slew block " +
      "allows, a box marks each occurrence of the activity selected in the list, and grey bars mark the time " +
      "after the list ends, which no activity plans. Click to move the time cursor, drag to zoom, and " +
      "double-click to zoom out.",
  },
  power: {
    title: "Power",
    text:
      "The power that the panels generate, and the power that the payload's and the platform's modes consume, " +
      "in watts. The buttons show " +
      "or hide each line. The shaded bands are eclipses. All of it comes from power.js.",
  },
  powerNow: {
    title: "Current power",
    text:
      "The power at the time cursor: the total generated, with each panel under it, the consumed, the net and " +
      "the battery's charge. Each colour matches its line on the charts.",
  },
  powerSetup: {
    title: "Power setup",
    text:
      "The power setup as power.js gives it, such as the panels, the battery and what each payload and " +
      "platform mode consumes. It " +
      "does not change with time. The power file itself is on the Inputs tab.",
  },
  net: {
    title: "Net power",
    text:
      "The power generated less the power consumed, in watts. Above zero, the surplus can charge the battery. " +
      "Below zero, the battery covers the deficit. The Power page shows the two apart, and each panel. The " +
      "shaded bands are eclipses.",
  },
  generated: { title: "Generated", text: "Show or hide the power that all the panels generate together." },
  consumed: {
    title: "Consumed",
    text: "Show or hide the power that the spacecraft consumes, set by the payload's and the platform's modes.",
  },
  panelPower: { title: "Panel", text: "Show or hide the power that this panel generates." },
  wide: {
    title: "Wide",
    text:
      "Put the charts across the full width, under the views. The 3D views and the map get smaller. Click " +
      "again to go back. The browser remembers the choice.",
  },
  battery: {
    title: "Battery",
    text:
      "The battery's state of charge, as a percentage of its capacity. The dashed red line is the lowest " +
      "charge allowed, set by the depth of discharge limit.",
  },
  current: {
    title: "Current data",
    text: "The state of the run at the time cursor. It changes as the scenario plays, or as you move the cursor.",
  },
  time: { title: "Time", text: "The time from the start of the run to the time cursor." },
  orbits: {
    title: "Orbits",
    text:
      "The orbits from the start of the run to the time cursor. One orbit is the period that a duration in " +
      "orbits counts: the nodal period for an element set. The timeline marks each whole orbit.",
  },
  payload_mode: {
    title: "Payload mode",
    text:
      "What the payload is doing, as the activity under way names it. Any name works. In a slew, it is " +
      "the mode of the activity before, or of the activity after where that activity asks for it. Power " +
      "gives each payload mode its consumption, from the payload's consumption file.",
  },
  platform_mode: {
    title: "Platform mode",
    text:
      "What the platform that carries the payload is doing, as the activity under way names it, or slew " +
      "while the body turns. Any name works. The parts of the 3D model park by it. Power gives each " +
      "platform mode its consumption, from the platform's consumption file.",
  },
  attitude: {
    title: "Attitude",
    text:
      "How the body is pointed, by the attitude's name in the scenario file. Each attitude fixes one body axis " +
      "on a direction, such as the nadir, the sun or a ground target, and turns a second axis as close as it can " +
      "get to another. During a slew, the body turns into the next attitude, shown as, for example, " +
      "nadir (slewing). Without slews, attitude changes are instant.",
  },
  illumination: {
    title: "Illumination",
    text:
      "Whether the spacecraft is sunlit, in the penumbra, where the Earth hides part of the sun, or in " +
      "the umbra, where it hides all of it. The shadow is cast by the sun's disk on the WGS84 ellipsoid.",
  },
  title: {
    title: "Activity",
    text:
      "The title of the activity under way, as the scenario file gives it first in each activity, such as " +
      "imaging 45 deg lat. It names what the activity is for.",
  },
  activity: {
    title: "Activity",
    text:
      "The activity under way: its number in the scenario file's list, and which repeat of the list it " +
      "belongs to. The Activities tab lists every one.",
  },
  beta: {
    title: "Beta angle",
    text:
      "The angle between the sun direction and the orbit plane. It changes little over a run, so the start " +
      "date and the orbit set it.",
  },
  position: {
    title: "Position",
    text:
      "The geodetic latitude and longitude of the point below the spacecraft, and its altitude. The " +
      "altitude is above a sphere of the Earth's equatorial radius, 6378.1 km.",
  },
  sunBody: {
    title: "Sun in body axes",
    text:
      "The unit vector from the spacecraft to the sun, in body axes. In an attitude that points an axis at " +
      "the sun, that axis reads 1 or -1, which checks the pointing.",
  },
  panels: {
    title: "Sun on panels",
    text:
      "The cosine of the sun angle on each panel. 1 means the panel faces the sun. 0 means it is edge-on, " +
      "faces away, or is in eclipse.",
  },
  colourBy: {
    title: "Track colours",
    text: "Choose the timeline row that colours the track, here and on the ground track.",
  },
  track: { title: "Track", text: "Show or hide the orbit track." },
  grid: { title: "Grid", text: "Show or hide the latitude and longitude lines on the Earth, every 30 degrees." },
  coast: { title: "Coast", text: "Show or hide the coastlines on the Earth." },
  shadow: {
    title: "Shadow",
    text:
      "Show or hide the Earth's shadow: the dark umbra cone, which narrows away from the Earth, and the " +
      "lighter penumbra cone around it, which widens.",
  },
  articulation: {
    title: "Articulation",
    text:
      "A part of the 3D model that turns about one body axis toward a direction, such as a solar wing toward the sun. Its " +
      "angle is zero where the model draws it. In a platform mode that parks it, it holds a fixed angle instead. " +
      "The scenario file sets them under 3d_model.",
  },
  light: {
    title: "Sunlight",
    text:
      "The fraction of the sun's disk seen from the spacecraft: 100 % when sunlit, and 0 % in the umbra. In " +
      "the penumbra the Earth hides part of the sun, and the fraction falls or rises through it. The square " +
      "fades with it. Power will scale the panels' output by it.",
  },
  follow: {
    title: "Follow",
    text: "Keep the camera on the spacecraft as it moves. Dragging still turns the view around it.",
  },
  orbitReset: { title: "Reset view", text: "Put the camera back where it started, and turn Follow off." },
  lvlh: {
    title: "LVLH",
    text:
      "Show the body in LVLH axes, which turn with the orbit: x along track, y minus the orbit normal, and " +
      "z nadir. An attitude that points z at the nadir and keeps -y on the orbit normal then stands still.",
  },
  gcrs: {
    title: "GCRS",
    text: "Show the body in GCRS axes, which stay fixed in space. The arrows then turn as the spacecraft orbits.",
  },
  bodyReset: { title: "Reset view", text: "Put the camera back where it started, for the axes in use." },
  panelMarks: {
    title: "Panels",
    text:
      "Show or hide each solar panel's normal and name. A panel on an articulated part, such as a solar " +
      "wing, turns with it. The browser remembers the choice.",
  },
  zoomFull: { title: "Full", text: "Show the whole run on the charts." },
  zoomOrbit: { title: "1 orbit", text: "Show one orbit on the charts, centred on the time cursor." },
  zoom30: { title: "30 min", text: "Show 30 minutes on the charts, centred on the time cursor." },
  play: { title: "Play", text: "Play or pause the scenario. The space bar does the same." },
  start: { title: "Reset", text: "Stop, and go back to the start of the run. The Home key does the same." },
  speed: { title: "Speed", text: "How fast the scenario plays, in seconds of the run for each second." },
  slider: {
    title: "Time",
    text:
      "The time cursor. Drag it to move through the run. The arrow keys step one time step, or a minute " +
      "with Shift.",
  },
  tabScenario: {
    title: "Scenario",
    text: "Run through the scenario: the 3D views, the map, the timeline and the current data. With power, the net power and the battery too.",
  },
  tabPower: {
    title: "Power",
    text: "The timeline over a larger power chart and the battery, with the current power and the power setup beside them.",
  },
  tabThermal: {
    title: "Thermal",
    text:
      "The payload's heat account over the run, as the Scenario Editor's Thermal tab shows it: by payload mode, by " +
      "activity and by whole orbit, the net heat since the start, and the surfaces.",
  },
  tabAttitude: {
    title: "Attitude",
    text: "The body's roll, pitch and yaw, its turn rate and its acceleration over the run, with the warnings, and the attitude files to download.",
  },
  attitudeAngles: {
    title: "Roll, pitch and yaw",
    text:
      "The body against LVLH: x along the track, y minus the orbit normal, z nadir. Yaw turns about z, then pitch about the new y, " +
      "then roll about the newest x. A nadir attitude reads zero. Near a pitch of ±90°, roll and yaw are not well defined, and they " +
      "jump. A jump across ±180° is left as a gap. An amber band marks where the body turns faster than the slew block allows.",
  },
  bodyRate: {
    title: "Body rate",
    text:
      "How fast the body turns, over each time step, about whatever axis. The dashed line is the slew block's maximum rate. " +
      "An attitude change with no slew is instant, so it has no rate and shows as a gap.",
  },
  bodyAcceleration: {
    title: "Acceleration",
    text:
      "The change of the turn rate, as a vector, between two time steps: a change of the axis counts as well as one of the rate. " +
      "The dashed line is the slew block's maximum acceleration. Both are averages over a step, so a short peak reads low.",
  },
  attitudeNow: { title: "Current attitude", text: "The attitude, its angles against LVLH, and the body rate and acceleration, at the time cursor." },
  attitudeFiles: {
    title: "Download",
    text: "The attitude, and each articulation's angle, as ECSV files: the same files that write_attitude_files writes from Python.",
  },
  downloadAttitude: {
    title: "Attitude file",
    text:
      "The time, the quaternion qx qy qz qw and the attitude in effect. The quaternion has its scalar last, and turns body " +
      "vectors into GCRS.",
  },
  downloadArticulation: {
    title: "Articulation file",
    text: "The time, the part's angle about its drive axis, and whether it is parked, for this articulation alone.",
  },
  warnings: {
    title: "Warnings",
    text:
      "Each orbit far from its element set's epoch, or close to an end of its trajectory. Then each attitude " +
      "that turns the body faster, or with more acceleration, than the slew block allows, such as tracking a " +
      "ground station overhead.",
  },
  tabActivities: { title: "Activities", text: "Every occurrence of every activity, with its times, its slew and its statuses." },
  tabInputs: {
    title: "Inputs",
    text: "The scenario, power, consumption and thermal files as written, the orbit and the target files, and the conventions.",
  },
  tabTargets: {
    title: "Targets",
    text: "When each ground and satellite target is in view, its passes, and where each target is or where its orbit came from.",
  },
  lanes: {
    title: "In view",
    text:
      "A row for each target, with a bar for each pass: the time the target is in view. A ground target is in " +
      "view above its minimum elevation. A satellite target is in view while the line between the two " +
      "satellites keeps its minimum clearance above the Earth. The thin light bar under the passes is the " +
      "time the attitude or a part points at the target, in view or not. Every pass is drawn, whether it is " +
      "used or not. Click to move the time cursor.",
  },
  targetsNow: {
    title: "Targets now",
    text:
      "Each target at the time cursor: its range from the spacecraft, whether it is out of view, and whether the " +
      "attitude or a part points at it.",
  },
  passes: {
    title: "Passes",
    text:
      "Every time a target is in view, in time order. A pass under way at the start or the end of the run is " +
      "cut there. Pointed at is the time in the pass that the attitude or a part points at the target, and is " +
      "blank for a pass that is not used. The closest range is at the time steps in the pass. Click a pass to " +
      "move the time cursor to it.",
  },
  targetSources: {
    title: "Sources",
    text:
      "Where each ground target is, and where each satellite target's orbit came from: its file, its element " +
      "set and its epoch, or its trajectory's span. An epoch more than 7 days from either end of the run is " +
      "amber. Each also has its time in view, and how long and how many times the attitude or a part points at it.",
  },
  inView: { title: "In view", text: "The targets in view of the spacecraft at the time cursor. The Targets page has more." },
  targets: { title: "Targets", text: "Show or hide the targets, and the satellite targets' trajectories." },
  links: {
    title: "Links",
    text:
      "Show or hide the lines from the spacecraft: a bright one to each target that the attitude or a part " +
      "points at, in view or not, and a faint one to each other target in view.",
  },
  bodyTargets: {
    title: "Targets",
    text:
      "Show or hide the arrows to the targets: the nearest four in view, and each target that the body or a part " +
      "points at. An arrow to a target out of view is dim.",
  },
  orbitShown: {
    title: "3D Orbit View",
    text:
      "Show or hide the orbit in 3D, beside the map. Hide it to give the map its width on a narrow screen. " +
      "The browser remembers the choice.",
  },
  passTracks: {
    title: "Passes",
    text: "Show the track of each satellite target in view over its current pass, from its rise to its set.",
  },
  tabResults: { title: "Results", text: "The summary, the checks, and which data files were found." },
};

/**
 * The box that explains whatever the pointer rests on. It appears after a
 * moment, below the element, or above it when there is no room below.
 */
(function explanations() {
  const box = element("div", { class: "help", hidden: "" });
  document.body.append(box);
  let target = null;
  let timer = null;

  function hide() {
    clearTimeout(timer);
    box.hidden = true;
  }

  function show(node) {
    const help = HELP[node.dataset.help];
    if (!help) return;
    box.replaceChildren(element("b", { text: help.title }), help.text);
    box.hidden = false;
    const rect = node.getBoundingClientRect();
    const left = Math.min(rect.left, innerWidth - 8 - box.offsetWidth);
    const below = rect.bottom + 6;
    const top = below + box.offsetHeight > innerHeight - 8 ? rect.top - 6 - box.offsetHeight : below;
    box.style.left = `${Math.max(8, left)}px`;
    box.style.top = `${Math.max(8, top)}px`;
  }

  document.addEventListener("pointerover", (event) => {
    const node = event.target.closest("[data-help]");
    if (node === target) return;
    target = node;
    hide();
    if (node) timer = setTimeout(() => show(node), 250);
  });
  document.addEventListener("pointerout", (event) => {
    if (!event.relatedTarget) {
      target = null;
      hide();
    }
  });
  // A click on a button or a view hides the box. A tap on a touch screen
  // shows it, and the next tap elsewhere hides it.
  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse") hide();
  });
  document.addEventListener("scroll", hide, true);
})();
