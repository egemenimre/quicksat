// ---------------------------------------------------------------- Orbit view

const orbitView = (() => {
  const viewport = $("#vp-orbit");
  const renderer = makeRenderer(viewport);
  const MM = 1 / 1000; // the scene is in Mm, so that the numbers stay small
  const RE = R_E * MM;
  const world = new THREE.Scene();
  // The near plane is as far out as the closest zoom allows, for depth precision
  const camera = new THREE.PerspectiveCamera(36, 1, 0.3, 4000);
  camera.up.set(0, 0, 1);
  const controls = renderer ? new THREE.OrbitControls(camera, renderer.domElement) : null;

  // The Earth, drawn in ITRS and turned into GCRS by q_earth
  const earth = new THREE.Group();
  earth.add(
    new THREE.Mesh(
      new THREE.SphereGeometry(RE, 96, 64),
      new THREE.MeshPhongMaterial({ color: 0x1f63b3, emissive: 0x06172d, specular: 0x1b2a40, shininess: 10 }),
    ),
  );
  const xyz = (lon, lat, radius) => [
    radius * Math.cos(lat * D2R) * Math.cos(lon * D2R),
    radius * Math.cos(lat * D2R) * Math.sin(lon * D2R),
    radius * Math.sin(lat * D2R),
  ];
  const lines = (points, colour, opacity) => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    return new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: colour, transparent: true, opacity }));
  };
  const gridPoints = [];
  for (let lon = -180; lon < 180; lon += 30) {
    for (let lat = -90; lat < 90; lat += 3) gridPoints.push(...xyz(lon, lat, RE * 1.0015), ...xyz(lon, lat + 3, RE * 1.0015));
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    for (let lon = -180; lon < 180; lon += 3) gridPoints.push(...xyz(lon, lat, RE * 1.0015), ...xyz(lon + 3, lat, RE * 1.0015));
  }
  const grid = lines(gridPoints, 0x7cc4ff, 0.2);
  const coastPoints = [];
  for (const line of coastlines) {
    for (let j = 0; j + 3 < line.length; j += 2) {
      coastPoints.push(...xyz(line[j], line[j + 1], RE * 1.003), ...xyz(line[j + 2], line[j + 3], RE * 1.003));
    }
  }
  const coast = lines(coastPoints, 0xcfeaff, 0.75);
  earth.add(grid, coast);
  world.add(earth);
  world.add(
    new THREE.Mesh(
      new THREE.SphereGeometry(RE * 1.035, 64, 48),
      new THREE.MeshBasicMaterial({ color: 0x3aa0ff, transparent: true, opacity: 0.07, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false }),
    ),
  );

  // Stars, from a fixed seed so that they are the same on every load
  let seed = 12345;
  const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
  const starPoints = [];
  for (let j = 0; j < 1500; j++) {
    const z = 2 * random() - 1;
    const a = 2 * Math.PI * random();
    const s = Math.sqrt(1 - z * z);
    starPoints.push(1500 * s * Math.cos(a), 1500 * s * Math.sin(a), 1500 * z);
  }
  const starGeometry = new THREE.BufferGeometry();
  starGeometry.setAttribute("position", new THREE.Float32BufferAttribute(starPoints, 3));
  world.add(new THREE.Points(starGeometry, new THREE.PointsMaterial({ color: 0x9fb4d6, size: 1.3, sizeAttenuation: false })));

  // The orbit, coloured by the chosen row. In the designer, the occurrences of
  // the activity selected in the list are drawn again over it, twice as thick,
  // and the rest of the track dims, as on the map.
  const trackGeometry = new THREE.LineGeometry();
  trackGeometry.setPositions(R.map((x) => x * MM));
  const trackMaterial = new THREE.LineMaterial({ linewidth: 2.2, vertexColors: true, worldUnits: false });
  const track = new THREE.Line2(trackGeometry, trackMaterial);
  const selectedMaterial = new THREE.LineMaterial({ linewidth: 4.4, vertexColors: true, worldUnits: false });
  const selectedTrack = new THREE.Group();
  selectedTrack.renderOrder = 1;
  world.add(track, selectedTrack);
  const background = new THREE.Color(0x050c18);
  function colourTrack() {
    const selected = state.selected === null ? [] : occurrencesOf(OCCURRENCES, state.selected);
    const colourAt = (k, colour) => colour.set(colourOf(pieceAt(TRACKS[state.colourBy], T[k]).value));
    const colours = [];
    const colour = new THREE.Color();
    for (let i = 0; i < N; i++) {
      colourAt(i, colour);
      if (selected.length) colour.lerp(background, 0.65);
      colours.push(colour.r, colour.g, colour.b);
    }
    trackGeometry.setColors(colours);
    for (const line of selectedTrack.children) line.geometry.dispose();
    selectedTrack.clear();
    for (const occurrence of selected) {
      const from = sampleAt(occurrence.start_s)[0];
      const [i, f] = sampleAt(occurrence.end_s);
      const to = f > 0 ? i + 1 : i;
      if (to <= from) continue;
      const positions = [];
      const pieceColours = [];
      for (let k = from; k <= to; k++) {
        positions.push(R[3 * k] * MM, R[3 * k + 1] * MM, R[3 * k + 2] * MM);
        colourAt(k, colour);
        pieceColours.push(colour.r, colour.g, colour.b);
      }
      const geometry = new THREE.LineGeometry();
      geometry.setPositions(positions);
      geometry.setColors(pieceColours);
      selectedTrack.add(new THREE.Line2(geometry, selectedMaterial));
    }
    dirty.orbit = true;
  }
  trackColours.onChange(colourTrack);

  // The spacecraft, far larger than life, and a marker to find it by. The
  // marker keeps the same size on screen: zoomed out it shows around the
  // model, and zoomed in the model hides it.
  const satellite = new THREE.Group();
  const model = buildSpacecraft(false);
  // The shape's radius, fitted to 1.25, shown as 62 km
  model.scale.setScalar(0.05);
  modelScene.then((scene) => {
    if (!scene) return;
    useModel(model, scene.clone());
    dirty.orbit = true;
  });
  const marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xff4d4d }));
  // the designer's data has no body orientation, so it shows the marker alone
  satellite.add(...(DESIGNER ? [] : [model]), marker);
  world.add(satellite);
  let viewHeight = 600;

  // The targets. A satellite target is a small marker that keeps its size on
  // screen, with its trajectory over the run as a faint line. A ground target
  // is a dot on the Earth, which turns with it. It sits on the drawn sphere, as
  // the coastlines do: on the ellipsoid, it would hide under the sphere near
  // the poles. Each is bright while in view of the spacecraft, and dim otherwise.
  // A ground target is pink and a satellite target lime.
  const satelliteMarks = new THREE.Group();
  const groundMarks = new THREE.Group();
  world.add(satelliteMarks);
  earth.add(groundMarks);
  const targetMarks = targetState.map((item) => {
    const mark = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 8), new THREE.MeshBasicMaterial({ color: targetColour(item.target) }));
    if (item.fixed) {
      mark.position.copy(item.fixed).setLength(RE * 1.004);
      groundMarks.add(mark);
    } else {
      // the page's three.js has line segments, not lines: each step is one
      const r = item.target.r_km;
      const steps = [];
      for (let k = 0; k + 5 < r.length; k += 3) steps.push(...r.slice(k, k + 6).map((x) => x * MM));
      satelliteMarks.add(mark, lines(steps, targetColour(item.target), 0.2));
    }
    return mark;
  });
  // The links: a bright line to each target that the attitude or a part points
  // at, in view or not, so that a line into the Earth shows a hidden target. A
  // fainter line goes to each other target in view. Each takes its target's
  // colour.
  const links = (opacity) => {
    const geometry = new THREE.BufferGeometry();
    const room = 6 * Math.max(TARGETS.length, 1);
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(room), 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(room), 3));
    const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity }));
    lines.frustumCulled = false;
    world.add(lines);
    return lines;
  };
  const pointLinks = links(0.95);
  const sightLinks = links(0.35);
  let targetsShown = true;
  let linksShown = true;
  const markAt = new THREE.Vector3();
  const linkColour = new THREE.Color();
  /** Where the view draws a target, in Mm: a ground target on the drawn sphere. */
  const drawnAt = (item, out) => {
    out.copy(item.r).multiplyScalar(MM);
    return item.fixed ? out.setLength(RE * 1.004) : out;
  };
  /** Joins the spacecraft to each of the targets, from the start of the line's buffer. */
  function joinTo(lines, items) {
    const { position, color } = lines.geometry.attributes;
    items.forEach((item, j) => {
      drawnAt(item, markAt);
      position.setXYZ(2 * j, state.r.x * MM, state.r.y * MM, state.r.z * MM);
      position.setXYZ(2 * j + 1, markAt.x, markAt.y, markAt.z);
      linkColour.set(targetColour(item.target));
      for (const end of [2 * j, 2 * j + 1]) color.setXYZ(end, linkColour.r, linkColour.g, linkColour.b);
    });
    lines.geometry.setDrawRange(0, 2 * items.length);
    position.needsUpdate = color.needsUpdate = true;
  }

  // The sun's direction and the Earth's shadow
  const sunArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), RE * 2.6, VECTOR_COLOURS.sun, RE * 0.12, RE * 0.06);
  const sunBall = new THREE.Mesh(new THREE.SphereGeometry(1.6, 32, 16), new THREE.MeshBasicMaterial({ color: 0xffd23f }));
  // The Earth's shadow: a dark umbra cone that narrows away from the Earth,
  // inside a lighter penumbra cone that widens. Their half-angles come from the
  // radii of the sun and the Earth at 1 au, about 0.26 and 0.27 degrees, as in
  // shadow_cones in quicksat/orbit/geometry.py. In low orbit the two walls are
  // a few tens of km apart, so the cones look like one. At a geostationary
  // orbit's distance, the penumbra is about 200 km wide on each side.
  //
  // Both are black. The penumbra is the lighter of the two, and where the two
  // overlap, the shadow is as dark as a single cone of 0.35 would be. Against
  // the near-black sky the ring at GEO is faint, but shows when zoomed in.
  //
  // Both cones start a little wider than the Earth. At the Earth's radius their
  // walls would meet the globe along the terminator, and the meshes would fight
  // over which is in front, which shows as a jagged edge. They are drawn round,
  // about the sphere the page draws, not the ellipsoid.
  const SUN_RADIUS_KM = 695700;
  const AU_KM = 149597870.7;
  const shadowLength = RE * 8;
  const shadowStart = RE * 1.004;
  const cone = (slope, opacity) => {
    const geometry = new THREE.CylinderGeometry(shadowStart, shadowStart + slope * shadowLength, shadowLength, 128, 1, true);
    geometry.translate(0, -shadowLength / 2, 0);
    const material = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false });
    return new THREE.Mesh(geometry, material);
  };
  const shadow = new THREE.Group();
  shadow.add(
    cone(Math.tan(Math.asin((SUN_RADIUS_KM + R_E) / AU_KM)), 0.15), // the penumbra
    cone(-Math.tan(Math.asin((SUN_RADIUS_KM - R_E) / AU_KM)), 0.25), // the umbra
  );
  world.add(sunArrow, sunBall, shadow);

  const sunlight = new THREE.DirectionalLight(0xffffff, 2.6);
  world.add(sunlight, new THREE.AmbientLight(0x9db4e0, 0.3));

  const labels = labelLayer(viewport);
  const sunLabel = labels.add("Sun", VECTOR_COLOURS.sun);
  const craftLabel = labels.add("Spacecraft", THEME.text, [0, -16]);
  // A target's name shows while it is in view
  const targetLabels = targetState.map((item) => labels.add(item.target.name, targetColour(item.target), [0, -12]));
  let size = { width: 1, height: 1 };
  // True when the Earth stands between the camera and `point`
  const behindEarth = (point) => {
    const ray = point.clone().sub(camera.position);
    const length = ray.length();
    ray.divideScalar(length);
    const b = camera.position.dot(ray);
    const discriminant = b * b - (camera.position.lengthSq() - RE * RE);
    if (discriminant <= 0) return false;
    const hit = -b - Math.sqrt(discriminant);
    return hit > 0 && hit < length;
  };

  // Start 60 deg from the orbit normal, so that the orbit shows as an
  // ellipse, and about 60 deg from the sun, so that the terminator shows
  const r0 = new THREE.Vector3(R[0], R[1], R[2]);
  const v0 = new THREE.Vector3(V[0], V[1], V[2]);
  const s0 = new THREE.Vector3(S[0], S[1], S[2]);
  const normal = r0.clone().cross(v0).normalize();
  if (normal.dot(s0) < 0) normal.negate();
  const towardSun = s0.clone().addScaledVector(normal, -normal.dot(s0)).normalize();
  const across = normal.clone().cross(towardSun);
  const eye = normal
    .clone()
    .multiplyScalar(0.5)
    .addScaledVector(towardSun, 0.87 * Math.cos(65 * D2R))
    .addScaledVector(across, 0.87 * Math.sin(65 * D2R))
    .add(new THREE.Vector3(0, 0, 0.25))
    .normalize();
  // Far enough out to see the whole orbit: 4.8 Earth radii for a low orbit,
  // and 2.6 times the orbit's radius for a higher one, such as GEO
  let orbitRadius = 0;
  for (let i = 0; i < N; i++) orbitRadius = Math.max(orbitRadius, Math.hypot(R[3 * i], R[3 * i + 1], R[3 * i + 2]) * MM);
  // and every satellite target's, such as a relay in GEO
  for (const { target } of targetState.filter((item) => item.lats)) {
    const r = target.r_km;
    for (let k = 0; k < r.length; k += 3) orbitRadius = Math.max(orbitRadius, Math.hypot(r[k], r[k + 1], r[k + 2]) * MM);
  }
  camera.position.copy(eye.multiplyScalar(Math.max(RE * 4.8, orbitRadius * 2.6)));
  const home = camera.position.clone();
  if (controls) {
    controls.minDistance = RE * 1.2;
    controls.maxDistance = RE * 60;
    controls.addEventListener("change", () => (dirty.orbit = true));
    controls.update();
  }

  let follow = false;
  const lastSatellite = new THREE.Vector3();
  const Y = new THREE.Vector3(0, 1, 0);
  const toggles = addToggles($("#orbit-toggles"), [
    { label: "Track", on: true, help: "track", set: (on) => (track.visible = selectedTrack.visible = on) },
    { label: "Grid", on: true, help: "grid", set: (on) => (grid.visible = on) },
    { label: "Coast", on: true, help: "coast", set: (on) => (coast.visible = on) },
    { label: "Shadow", on: true, help: "shadow", set: (on) => (shadow.visible = on) },
    ...(TARGETS.length
      ? [
          {
            label: "Targets",
            on: true,
            help: "targets",
            set: (on) => {
              targetsShown = on;
              satelliteMarks.visible = groundMarks.visible = on;
            },
          },
          { label: "Links", on: true, help: "links", set: (on) => (linksShown = on) },
        ]
      : []),
    { label: "Follow", on: false, help: "follow", set: (on) => (follow = on) },
  ].map((item) => ({ ...item, set: (on) => { item.set(on); dirty.orbit = true; } })));
  $("#orbit-toggles").append(
    element("button", {
      class: "toggle",
      text: "Reset view",
      "data-help": "orbitReset",
      onclick: () => {
        if (follow) toggles.Follow.click();
        camera.position.copy(home);
        camera.up.set(0, 0, 1);
        if (controls) {
          controls.target.set(0, 0, 0);
          controls.update();
        }
        dirty.orbit = true;
      },
    }),
  );

  return {
    /** Draw the track again, after the selected activity changes. */
    retrack: colourTrack,
    resize(width, height) {
      if (!renderer) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      trackMaterial.resolution.set(width, height);
      selectedMaterial.resolution.set(width, height);
      viewHeight = height;
      size = { width, height };
    },
    update() {
      earth.quaternion.copy(state.qEarth);
      satellite.position.copy(state.r).multiplyScalar(MM);
      if (!DESIGNER) {
        model.quaternion.copy(state.qBody);
        turnJoints(model);
      }
      sunlight.position.copy(state.sun).multiplyScalar(100);
      sunArrow.setDirection(state.sun);
      sunBall.position.copy(state.sun).multiplyScalar(300);
      shadow.quaternion.setFromUnitVectors(Y, state.sun);
      if (follow && controls) {
        const move = satellite.position.clone().sub(lastSatellite);
        camera.position.add(move);
        controls.target.add(move);
        controls.update();
      }
      lastSatellite.copy(satellite.position);
      const distance = camera.position.distanceTo(satellite.position);
      marker.scale.setScalar((6 * 2 * distance * Math.tan((camera.fov * D2R) / 2)) / viewHeight);
      sunLabel.position.copy(state.sun).multiplyScalar(RE * 2.85);
      craftLabel.position.copy(satellite.position);
      joinTo(pointLinks, linksShown ? targetState.filter((item) => state.pointed.has(item.target.name)) : []);
      joinTo(sightLinks, linksShown ? targetState.filter((item) => item.inView && !state.pointed.has(item.target.name)) : []);
      targetState.forEach((item, j) => {
        const mark = targetMarks[j];
        drawnAt(item, markAt);
        if (!item.fixed) mark.position.copy(markAt);
        mark.material.color.set(targetColour(item.target, item.inView));
        mark.scale.setScalar((3.5 * 2 * camera.position.distanceTo(markAt) * Math.tan((camera.fov * D2R) / 2)) / viewHeight);
        targetLabels[j].position.copy(markAt);
      });
    },
    render() {
      if (!renderer) return;
      renderer.render(world, camera);
      sunLabel.visible = !behindEarth(sunLabel.position);
      craftLabel.visible = !behindEarth(craftLabel.position);
      targetState.forEach((item, j) => {
        const label = targetLabels[j];
        label.visible = targetsShown && item.inView && !behindEarth(label.position);
      });
      labels.place(camera, size.width, size.height);
    },
  };
})();
