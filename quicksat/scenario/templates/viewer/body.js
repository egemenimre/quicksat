// ---------------------------------------------------------------- Body view

const bodyView = DESIGNER ? null : (() => {
  const viewport = $("#vp-body");
  const renderer = makeRenderer(viewport);
  const world = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 200);
  const controls = renderer ? new THREE.OrbitControls(camera, renderer.domElement) : null;
  if (controls) controls.addEventListener("change", () => (dirty.body = true));

  const spacecraft = buildSpacecraft(true);
  world.add(spacecraft);
  modelScene.then((scene) => {
    if (!scene) return;
    useModel(spacecraft, scene.clone());
    dirty.body = true;
  });
  // The velocity, the nadir and the orbit normal are close to the LVLH axes:
  // x along track, z nadir, and y minus the orbit normal
  const arrows = {};
  for (const name of ["velocity", "nadir", "orbitNormal", "sun"]) {
    arrows[name] = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1.8, VECTOR_COLOURS[name], 0.15, 0.075);
    world.add(arrows[name]);
  }
  const labels = labelLayer(viewport);
  const arrowLabels = {
    velocity: labels.add("Velocity", VECTOR_COLOURS.velocity),
    nadir: labels.add("Nadir", VECTOR_COLOURS.nadir),
    orbitNormal: labels.add("Orbit normal", VECTOR_COLOURS.orbitNormal),
    sun: labels.add("Sun", VECTOR_COLOURS.sun),
  };
  // An arrow to each target in view, the nearest first and at most MOST_ARROWS
  // of them, and to each target that the body or a part points at, in view or
  // not. Out of view, the arrow is dim.
  const targetArrows = targetState.map((item) => {
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1.8, targetColour(item.target), 0.15, 0.075);
    arrow.visible = false;
    world.add(arrow);
    return { item, arrow, label: labels.add(item.target.name, targetColour(item.target)) };
  });
  let targetArrowsShown = true;
  // Each panel's name sits just past its normal, at a point that turns with
  // the panel. Each body axis's name sits just past the axis.
  const panelLabels = spacecraft.userData.markers.map(({ anchor }, j) => ({
    label: labels.add(PANELS[j].name, VECTOR_COLOURS.normal),
    anchor,
  }));
  const axisLabels = ["x", "y", "z"].map((name, k) => ({
    label: labels.add(name, AXIS_COLOURS[k]),
    local: new THREE.Vector3().setComponent(k, AXIS_LENGTH + 0.17),
  }));
  let size = { width: 1, height: 1 };

  const sunlight = new THREE.DirectionalLight(0xfff4dc, 2.4);
  const headlight = new THREE.DirectionalLight(0x9db4e0, 0.5);
  camera.add(headlight);
  world.add(sunlight, camera, new THREE.AmbientLight(0x9db4e0, 0.45));

  let frame = "LVLH";
  const lvlh = new THREE.Matrix4();
  const toDisplay = new THREE.Quaternion();
  const direction = new THREE.Vector3();
  const nadir = new THREE.Vector3();
  const orbitNormal = new THREE.Vector3();

  function setFrame(name) {
    frame = name;
    $("#body-title").innerHTML =
      name === "LVLH" ? "<b>Body</b> · LVLH: x along track, z nadir" : "<b>Body</b> · GCRS axes";
    if (name === "LVLH") {
      // From above and behind the orbit plane, so that the velocity points
      // right, the nadir down, and the orbit normal up and to the right. Far
      // enough out that an arrow pointing straight up keeps its label in view.
      camera.up.set(0, 0, -1);
      camera.position.set(3.5, 5.8, -4.8);
    } else {
      camera.up.set(0, 0, 1);
      camera.position.set(5.5, -4.5, 3.2);
    }
    if (controls) {
      controls.target.set(0, 0, 0);
      controls.update();
    }
    dirty.body = true;
  }

  const frameButtons = ["LVLH", "GCRS"].map((name) =>
    element("button", { class: "toggle" + (name === "LVLH" ? " on" : ""), text: name, "data-help": name === "LVLH" ? "lvlh" : "gcrs" }),
  );
  frameButtons.forEach((button) =>
    button.addEventListener("click", () => {
      frameButtons.forEach((other) => other.classList.toggle("on", other === button));
      setFrame(button.textContent);
    }),
  );
  // With power, a button that shows or hides the panels' normals and names.
  // The browser remembers the choice, where it can.
  const panelButton = element("button", { class: "toggle", text: "Panels", "data-help": "panelMarks" });
  const showPanels = (on) => {
    for (const { marker } of spacecraft.userData.markers) marker.visible = on;
    for (const { label } of panelLabels) label.visible = on;
    panelButton.classList.toggle("on", on);
    dirty.body = true;
  };
  let panelsShown = true;
  try {
    panelsShown = localStorage.getItem("quicksat-viewer-panels") !== "0";
  } catch {
    // No storage, as in some private windows: show them
  }
  showPanels(panelsShown);
  panelButton.addEventListener("click", () => {
    panelsShown = !panelsShown;
    showPanels(panelsShown);
    try {
      localStorage.setItem("quicksat-viewer-panels", panelsShown ? "1" : "0");
    } catch {
      // The choice then lasts until the page is closed
    }
  });
  const targetButton = element("button", { class: "toggle on", text: "Targets", "data-help": "bodyTargets" });
  targetButton.addEventListener("click", () => {
    targetArrowsShown = !targetArrowsShown;
    targetButton.classList.toggle("on", targetArrowsShown);
    dirty.body = true;
  });
  $("#body-toggles").append(
    ...(TARGETS.length ? [targetButton] : []),
    ...(PANELS.length ? [panelButton] : []),
    ...frameButtons,
    element("button", { class: "toggle", text: "Reset view", "data-help": "bodyReset", onclick: () => setFrame(frame) }),
  );
  setFrame("LVLH");

  return {
    resize(width, height) {
      if (!renderer) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      size = { width, height };
    },
    update() {
      if (frame === "LVLH") {
        toDisplay.setFromRotationMatrix(lvlhMatrix(state.r, state.v, lvlh).transpose());
      } else {
        toDisplay.identity();
      }
      spacecraft.quaternion.copy(toDisplay).multiply(state.qBody);
      turnJoints(spacecraft);
      const directions = {
        velocity: state.v,
        nadir: nadir.copy(state.r).negate(),
        orbitNormal: orbitNormal.copy(state.r).cross(state.v),
        sun: state.sun,
      };
      for (const [name, vector] of Object.entries(directions)) {
        direction.copy(vector).normalize().applyQuaternion(toDisplay);
        arrows[name].setDirection(direction);
        arrowLabels[name].position.copy(direction).multiplyScalar(2.05);
      }
      // The sun's direction is the last one set
      sunlight.position.copy(direction).multiplyScalar(10);
      sunlight.intensity = 2.4 * state.light;
      const ranges = {};
      for (const item of targetState) ranges[item.target.name] = item.range;
      const inView = targetState.filter((item) => item.inView).map((item) => item.target.name);
      const drawn = new Set(arrowTargets(inView, ranges, [...state.pointed], MOST_ARROWS));
      for (const { item, arrow, label } of targetArrows) {
        const on = targetArrowsShown && drawn.has(item.target.name);
        arrow.visible = label.visible = on;
        if (!on) continue;
        direction.copy(item.r).sub(state.r).normalize().applyQuaternion(toDisplay);
        arrow.setDirection(direction);
        const colour = targetColour(item.target, item.inView);
        arrow.setColor(colour);
        label.node.style.color = colour;
        label.position.copy(direction).multiplyScalar(2.05);
      }
      spacecraft.updateMatrixWorld(true);
      for (const { label, anchor } of panelLabels) anchor.getWorldPosition(label.position);
      for (const { label, local } of axisLabels) label.position.copy(local).applyQuaternion(spacecraft.quaternion);
    },
    render() {
      if (!renderer) return;
      renderer.render(world, camera);
      labels.place(camera, size.width, size.height);
    },
  };
})();
