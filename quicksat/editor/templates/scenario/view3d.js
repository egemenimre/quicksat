// quicksat scenario editor: the 3D panel, which shows the model, its parts, the panels,
// the articulations and the attitudes' axes.

// The 3D panel is shown or hidden for each Setup step and each tab. It starts
// shown where it has something to show, and remembers the user's choice.
const viewKey = () => (state.tab === "setup" ? `step:${STEPS[state.step].sections[0]}` : `tab:${state.tab}`);

function wants3d() {
  const key = viewKey();
  if (key in state.show3d) return state.show3d[key];
  return state.tab === "setup" ? Boolean(STEPS[state.step].needs3d) : state.tab === "spacecraft";
}

function apply3d() {
  const on = wants3d();
  $("#main").classList.toggle("with-3d", on);
  $("#toggle-3d").classList.toggle("on", on);
  $("#toggle-3d").textContent = on ? "Hide 3D" : "Show 3D";
  if (on) requestAnimationFrame(() => view3d.resize());
}

function toggle3d() {
  state.show3d[viewKey()] = !wants3d();
  apply3d();
}

const view3d = (() => {
  const viewport = $("#viewport");
  const canvas = viewport.querySelector("canvas");
  let renderer = null;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x050c18);
  } catch (error) {
    viewport.append(el("div", { class: "vp-message", text: "This browser could not start WebGL, so the 3D view is off." }));
  }
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
  camera.up.set(0, 0, -1); // body z is nadir, so nadir is down on the screen
  const controls = renderer ? new THREE.OrbitControls(camera, canvas) : null;
  scene.add(new THREE.AmbientLight(0xffffff, 0.75));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(2, -3, -4);
  scene.add(sun);

  const root = new THREE.Group();
  const overlay = new THREE.Group();
  scene.add(root, overlay);
  const labels = [];
  const labelLayer = $("#labels");
  let size = 1;
  let turned = null;
  const highlightMaterial = new THREE.MeshStandardMaterial({ color: 0x22d3ee, emissive: 0x0e5a66, roughness: 0.5, side: THREE.DoubleSide });
  const toggles = { axes: true };

  const COLOURS = { x: "#f87171", y: "#34d399", z: "#60a5fa" };
  const axisVector = (axis) => {
    const v = new THREE.Vector3();
    v[axis[1]] = axis[0] === "-" ? -1 : 1;
    return v;
  };

  function label(text, colour, position) {
    const node = el("div", { class: "label3d", text, style: `color:${colour}` });
    labelLayer.append(node);
    labels.push({ node, position: position.clone() });
  }

  function arrow(direction, origin, length, colour, text) {
    const helper = new THREE.ArrowHelper(direction.clone().normalize(), origin, length, new THREE.Color(colour), length * 0.12, length * 0.06);
    overlay.add(helper);
    if (text) label(text, colour, origin.clone().add(direction.clone().normalize().multiplyScalar(length * 1.12)));
  }

  function frameCamera() {
    root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root);
    size = Math.max(...box.getSize(new THREE.Vector3()).toArray(), 0.5);
    camera.position.set(size * 1.7, size * 2.0, -size * 1.3);
    if (controls) { controls.target.set(0, 0, 0); controls.update(); }
  }

  /** The plain 1 m cube that quicksat draws without a model. */
  function cube() {
    root.clear();
    const box = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: 0x5b6b82, roughness: 0.8, transparent: true, opacity: 0.6 }));
    root.add(box, new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({ color: 0x9fb2cc })));
    model.parts = [];
    model.nodes = [];
    model.bytes = null;
    $("#model-name").textContent = "no model: a 1 m cube";
    frameCamera();
    drawParts();
  }

  /** Read the GLB's own JSON chunk, for the node names as the file writes them. */
  function glbJson(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const length = view.getUint32(12, true);
    return JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + length)));
  }

  function load(bytes, name) {
    return new Promise((resolve) => {
      let json;
      try { json = glbJson(bytes); } catch (error) { alert(`${name} is not a GLB file.`); return resolve(false); }
      new THREE.GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), "", (gltf) => {
        root.clear();
        root.add(gltf.scene);
        const nodeObjects = [];
        gltf.scene.traverse((object) => {
          const association = gltf.parser.associations.get(object);
          if (association && association.nodes !== undefined) nodeObjects[association.nodes] = object;
          if (object.isMesh) object.userData.material = object.material;
        });
        const counts = {};
        (json.nodes || []).forEach((n) => n.name && (counts[n.name] = (counts[n.name] || 0) + 1));
        model.parts = Object.entries(counts).map(([partName, count]) => ({ name: partName, count }));
        model.nodes = (json.nodes || []).map((n, i) => ({ name: n.name || `node ${i}`, object: nodeObjects[i], children: n.children || [] }));
        model.bytes = bytes;
        model.fileName = name;
        $("#model-name").textContent = name;
        frameCamera();
        drawParts();
        resolve(true);
      }, (error) => { alert(`${name} could not be read: ${error.message || error}`); resolve(false); });
    });
  }

  const objectsOf = (partName) => model.nodes.filter((n) => n.name === partName).map((n) => n.object).filter(Boolean);
  const meshesUnder = (object) => {
    const meshes = [];
    object.traverse((o) => o.isMesh && meshes.push(o));
    return meshes;
  };
  /** A node's own triangles: the node itself, or the primitives the loader put under it. */
  const ownMeshes = (object) => (object.isMesh ? [object] : object.children.filter((c) => c.isMesh && !model.nodes.some((n) => n.object === c)));

  /** A part's area, area-weighted normal and centre in body axes, and whether it is flat to 1 deg. */
  function partGeometry(partName) {
    const objects = objectsOf(partName);
    if (objects.length !== 1) return null;
    const meshes = ownMeshes(objects[0]);
    if (!meshes.length) return null;
    root.updateMatrixWorld(true);
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    const sum = new THREE.Vector3(), centre = new THREE.Vector3(), cross = new THREE.Vector3();
    const triangles = [];
    let area = 0;
    for (const mesh of meshes) {
      const position = mesh.geometry.attributes.position;
      const index = mesh.geometry.index;
      const count = index ? index.count : position.count;
      const vertex = (i, out) => out.fromBufferAttribute(position, index ? index.getX(i) : i).applyMatrix4(mesh.matrixWorld);
      for (let i = 0; i + 2 < count; i += 3) {
        vertex(i, a); vertex(i + 1, b); vertex(i + 2, c);
        cross.subVectors(b, a).cross(c.clone().sub(a));
        const triangleArea = cross.length() / 2;
        if (triangleArea === 0) continue;
        area += triangleArea;
        sum.add(cross);
        centre.add(a.clone().add(b).add(c).multiplyScalar(triangleArea / 3));
        triangles.push(cross.clone().normalize());
      }
    }
    if (!area) return null;
    const normal = sum.clone().normalize();
    const maxAngle = Math.max(...triangles.map((n) => (Math.acos(Math.min(1, Math.max(-1, n.dot(normal)))) * 180) / Math.PI));
    return { area, normal, centre: centre.multiplyScalar(1 / area), flat: maxAngle <= 1, maxAngle };
  }

  function drawParts() {
    const box = $("#parts");
    box.replaceChildren(el("div", { class: "k", text: model.nodes.length ? "Parts in the model" : "No parts: the model is a plain cube" }));
    const seen = new Set();
    for (const node of model.nodes) {
      if (seen.has(node.name)) continue;
      seen.add(node.name);
      const geometry = partGeometry(node.name);
      const count = model.nodes.filter((n) => n.name === node.name).length;
      const note = count > 1 ? `${count} nodes` : geometry ? (geometry.flat ? `flat, ${geometry.area.toFixed(4)} m²` : "not flat") : node.children.length ? `${node.children.length} children` : "";
      box.append(el("button", {
        class: state.selection && state.selection.kind === "part" && state.selection.name === node.name ? "on" : "",
        onclick: () => select({ kind: "part", name: node.name, item: node.name }),
      }, node.name, note ? el("small", { text: `  ${note}` }) : null));
    }
  }

  function resetTurn() {
    if (turned) { turned.object.quaternion.copy(turned.base); turned = null; }
    $("#turn").hidden = true;
  }

  function highlight(partName) {
    for (const object of objectsOf(partName)) for (const mesh of meshesUnder(object)) mesh.material = highlightMaterial;
  }

  function attitudeArrows(attitude) {
    arrow(axisVector(attitude.point[0]), new THREE.Vector3(), size * 1.05, "#22d3ee", `${attitude.point[0]} → ${attitude.point[1]}`);
    arrow(axisVector(attitude.constrain[0]), new THREE.Vector3(), size * 0.9, "#f5b13d", `${attitude.constrain[0]} → ${attitude.constrain[1]}`);
  }

  function update() {
    if (!renderer) return;
    overlay.clear();
    labels.length = 0;
    labelLayer.replaceChildren();
    root.traverse((o) => o.isMesh && o.userData.material && (o.material = o.userData.material));
    const selection = state.selection;
    if (!(selection && selection.kind === "articulation")) resetTurn();
    if (toggles.axes) {
      for (const axis of ["+x", "+y", "+z"]) arrow(axisVector(axis), new THREE.Vector3(), size * 0.75, COLOURS[axis[1]], axis[1]);
    }
    let text = "Select a part, an articulation, an attitude or a panel to see it here.";
    if (selection && selection.kind === "part") {
      highlight(selection.name);
      const g = partGeometry(selection.name);
      text = `<b>${escapeHtml(selection.name)}</b>` + (g ? ` · ${g.flat ? "flat" : `<span class="bad">not flat: faces differ by up to ${g.maxAngle.toFixed(0)}°</span>`} · ${g.area.toFixed(4)} m²` : " · no surface of its own");
      if (g && g.flat) arrow(g.normal, g.centre, size * 0.4, "#f5b13d", "normal");
    } else if (selection && selection.kind === "panel") {
      const p = selection.item;
      if (p.source === "part") {
        highlight(p.part);
        const g = partGeometry(p.part);
        if (g) {
          arrow(g.normal, g.centre, size * 0.45, "#f5b13d", `${p.name} normal`);
          const n = g.normal.toArray().map((v) => v.toFixed(3)).join(", ");
          text = `Panel <b>${escapeHtml(p.name)}</b> on <b>${escapeHtml(p.part)}</b> · ${g.flat ? "" : '<span class="bad">not flat</span> · '}area ${g.area.toFixed(4)} m² · normal [${n}] · cells ${(g.area * (p.fill_ratio.v || 0) / 100).toFixed(4)} m²`;
        } else text = `Panel <b>${escapeHtml(p.name)}</b>: <span class="bad">the part "${escapeHtml(p.part || "none")}" has no surface of its own${model.bytes ? "" : ", or the page holds no model"}</span>`;
      } else {
        const normal = readNormalVector(p.normal);
        if (normal) {
          const vector = typeof normal === "string" ? axisVector(normal) : new THREE.Vector3(...normal);
          arrow(vector, new THREE.Vector3(), size * 0.8, "#f5b13d", `${p.name}: ${p.normal}`);
        }
        text = `Panel <b>${escapeHtml(p.name)}</b> is typed in: ${escapeHtml(qText(p.area))} facing ${escapeHtml(p.normal)}. It has no part in the model, so it is not drawn, and is never shaded.`;
      }
    } else if (selection && selection.kind === "articulation") {
      const a = selection.item;
      const objects = objectsOf(a.part);
      highlight(a.part);
      if (objects.length === 1) {
        const object = objects[0];
        if (!turned || turned.object !== object) {
          resetTurn();
          turned = { object, base: object.quaternion.clone(), axis: a.axis };
          $("#turn-range").value = 0;
          $("#turn-value").textContent = "0°";
        }
        turned.axis = a.axis;
        $("#turn").hidden = false;
        $("#turn-label").textContent = `turn ${a.name}`;
        const origin = object.getWorldPosition(new THREE.Vector3());
        const along = axisVector(a.axis);
        arrow(along, origin, size * 0.5, "#a78bfa", `axis ${a.axis}`);
        arrow(along.clone().negate(), origin, size * 0.5, "#a78bfa", "");
        const pointing = axisVector(a.point[0]).applyQuaternion(object.quaternion);
        arrow(pointing, origin, size * 0.35, "#f5b13d", `${a.point[0]} → ${a.point[1]}`);
        text = `Articulation <b>${escapeHtml(a.name)}</b> turns <b>${escapeHtml(a.part)}</b> about ${a.axis}, through its origin, so that its ${a.point[0]} axis points as close to <b>${escapeHtml(a.point[1])}</b> as it can. Drag the slider to try it.`;
      } else {
        text = `Articulation <b>${escapeHtml(a.name)}</b>: <span class="bad">${objects.length ? "the name matches several parts" : `no part "${escapeHtml(a.part || "none")}"`}</span>`;
      }
    } else if (selection && selection.kind === "attitude") {
      const a = selection.item;
      attitudeArrows(a);
      text = `Attitude <b>${escapeHtml(a.name)}</b>: the body turns so that <b>${a.point[0]}</b> points at <b>${escapeHtml(a.point[1])}</b>, then turns about it until <b>${a.constrain[0]}</b> is as close as it can get to <b>${escapeHtml(a.constrain[1])}</b>.${a.offset ? ` Then it turns by ${escapeHtml(a.offset)}.` : ""}`;
    } else if (selection && selection.kind === "target") {
      text = S.sat_targets.items.includes(selection.item)
        ? `Target <b>${escapeHtml(selection.item.name)}</b> is another satellite, so it has nothing to show on the spacecraft. An attitude or an articulation can point an axis at it.`
        : `Target <b>${escapeHtml(selection.item.name)}</b> is on the ground, so it has nothing to show on the spacecraft. An attitude can point an axis at it.`;
    } else if (selection && selection.kind === "activity") {
      const a = selection.item;
      const attitude = S.attitudes.items.find((x) => x.name === a.attitude);
      if (attitude) attitudeArrows(attitude);
      text = `Activity <b>${escapeHtml(a.title || "with no title")}</b>: ${escapeHtml(a.attitude)}, mode ${escapeHtml(a.mode)}, until <b>${escapeHtml(triggerText(a.end))}</b>.`;
    }
    $("#readout").innerHTML = text;
    if (selection && selection.kind === "part") drawParts();
  }

  $("#turn-range").addEventListener("input", (e) => {
    if (!turned) return;
    const angle = Number(e.target.value);
    $("#turn-value").textContent = `${angle}°`;
    const turn = new THREE.Quaternion().setFromAxisAngle(axisVector(turned.axis), (angle * Math.PI) / 180);
    turned.object.quaternion.copy(turned.base).premultiply(turn);
    update();
  });

  function resize() {
    if (!renderer) return;
    const { clientWidth: w, clientHeight: h } = viewport;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  const projected = new THREE.Vector3();
  function frame() {
    requestAnimationFrame(frame);
    if (!renderer || !$("#main").classList.contains("with-3d")) return;
    if (canvas.width !== Math.round(viewport.clientWidth * renderer.getPixelRatio())) resize();
    renderer.render(scene, camera);
    const { clientWidth: w, clientHeight: h } = viewport;
    for (const { node, position } of labels) {
      projected.copy(position).project(camera);
      const visible = projected.z < 1 && Math.abs(projected.x) < 1.05 && Math.abs(projected.y) < 1.05;
      node.style.display = visible ? "" : "none";
      if (visible) node.style.transform = `translate(${((projected.x + 1) / 2) * w}px, ${((1 - projected.y) / 2) * h}px) translate(-50%, -50%)`;
    }
  }
  frame();

  $("#vtoggles").append(el("button", {
    class: "btn small on", text: "body axes",
    onclick: (e) => { toggles.axes = !toggles.axes; e.target.classList.toggle("on", toggles.axes); update(); },
  }));

  return { load, cube, update, resize, partGeometry };
})();

async function loadGlbFile(file) {
  if (!file) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (await view3d.load(bytes, file.name)) {
    S.model.file = file.name;
    sources.model = { how: "file" };
    state.selection = null;
    changed(true);
  }
}

/** Make a table row select its item in the 3D view when clicked. */
function selectable(tr, selection) {
  tr.addEventListener("focusin", () => select(selection));
  tr.addEventListener("click", () => select(selection));
  tr._selection = selection;
  // a row drawn again keeps its selection
  if (state.selection && state.selection.item === selection.item) tr.classList.add("selected");
  return tr;
}

function select(selection) {
  const before = state.selection;
  state.selection = selection;
  for (const tr of document.querySelectorAll("tr.selected")) tr.classList.remove("selected");
  for (const tr of document.querySelectorAll(".items tr")) {
    if (tr._selection && selection && tr._selection.item === selection.item) tr.classList.add("selected");
  }
  view3d.update();
  if ((before && before.item) !== (selection && selection.item)) sendSelection();
}
