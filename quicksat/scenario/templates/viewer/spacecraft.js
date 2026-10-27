// ---------------------------------------------------------------- Spacecraft model

// Both views show the shape at this radius from the body's origin, whatever its
// size, so that any model fits them. The body axes reach past it.
const SHAPE_RADIUS = 1.25;
const AXIS_LENGTH = 1.45;

/** The farthest the object's bounding box reaches from the object's origin. */
function radiusOf(object) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return 0;
  return new THREE.Vector3(
    Math.max(-box.min.x, box.max.x),
    Math.max(-box.min.y, box.max.y),
    Math.max(-box.min.z, box.max.z),
  ).length();
}

/** Scales a shape, which must have no parent, out to SHAPE_RADIUS. */
function fitShape(shape) {
  shape.scale.setScalar(1);
  const radius = radiusOf(shape);
  shape.scale.setScalar(radius > 0 ? SHAPE_RADIUS / radius : 1);
}

/**
 * The spacecraft: its shape, in metres and fitted to the view, and in the
 * detailed version its body axes. The shape is the cube and the panel boxes
 * until `useModel` puts the 3D model in their place.
 */
function buildSpacecraft(detailed) {
  const group = new THREE.Group();
  const shape = new THREE.Group();
  const standIns = [];
  const markers = [];
  const body = new THREE.BoxGeometry(...BODY);
  standIns.push(new THREE.Mesh(body, new THREE.MeshStandardMaterial({ color: 0xc6ccd6, metalness: 0.35, roughness: 0.55 })));
  const panelMaterial = new THREE.MeshStandardMaterial({ color: 0x1b3d85, emissive: 0x050f24, metalness: 0.4, roughness: 0.35 });
  const edgeMaterial = new THREE.LineBasicMaterial({ color: 0x9fc4ee, transparent: true, opacity: 0.55 });
  const cellMaterial = new THREE.LineBasicMaterial({ color: 0x5fa8ff, transparent: true, opacity: 0.3 });
  if (detailed) standIns.push(new THREE.LineSegments(new THREE.EdgesGeometry(body), edgeMaterial));

  for (const panel of PANELS) {
    const inPlane = [0, 1, 2].filter((k) => k !== panel.axis);
    const extent = [0.02, 0.02, 0.02];
    extent[inPlane[0]] = panel.size_m[0];
    extent[inPlane[1]] = panel.size_m[1];
    const geometry = new THREE.BoxGeometry(...extent);
    const mesh = new THREE.Mesh(geometry, panelMaterial);
    mesh.position.set(...panel.centre_m);
    standIns.push(mesh);
    if (!detailed) continue;

    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), edgeMaterial);
    edges.position.copy(mesh.position);
    standIns.push(edges);
    // Cell lines on the face the normal points out of
    const points = [];
    const face = panel.centre_m.slice();
    face[panel.axis] += panel.normal[panel.axis] * 0.011;
    for (const [along, across] of [[0, 1], [1, 0]]) {
      const a = inPlane[along];
      const b = inPlane[across];
      const count = Math.max(1, Math.round(panel.size_m[along] / 0.125));
      for (let j = 1; j < count; j++) {
        const p = face.slice();
        const q = face.slice();
        p[a] = q[a] = face[a] - panel.size_m[along] / 2 + (j * panel.size_m[along]) / count;
        p[b] = face[b] - panel.size_m[across] / 2;
        q[b] = face[b] + panel.size_m[across] / 2;
        points.push(...p, ...q);
      }
    }
    const cells = new THREE.BufferGeometry();
    cells.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    standIns.push(new THREE.LineSegments(cells, cellMaterial));
    // The normal stays with a 3D model, which does not mark the panels. It and
    // the point where the panel's name sits form a group, so that the panel
    // can turn with an articulated part, and the Panels button can hide it.
    const normal = new THREE.Vector3(...panel.normal);
    const marker = new THREE.Group();
    const anchor = new THREE.Group();
    anchor.position.set(...panel.centre_m).addScaledVector(normal, 0.74);
    marker.add(new THREE.ArrowHelper(normal, new THREE.Vector3(...face), 0.55, VECTOR_COLOURS.normal, 0.12, 0.06), anchor);
    shape.add(marker);
    markers.push({ marker, anchor, articulation: panel.articulation });
  }
  shape.add(...standIns);
  fitShape(shape);
  group.add(shape);

  if (detailed) {
    AXIS_COLOURS.forEach((colour, k) => {
      const axis = new THREE.Vector3().setComponent(k, 1);
      group.add(new THREE.ArrowHelper(axis, new THREE.Vector3(), AXIS_LENGTH, colour, 0.1, 0.05));
    });
  }
  group.userData = { shape, standIns, markers };
  return group;
}

/** Puts a 3D model in place of a spacecraft's cube and panel boxes, fitted to the view. */
function useModel(spacecraft, model) {
  const { shape, standIns } = spacecraft.userData;
  spacecraft.remove(shape);
  shape.remove(...standIns);
  shape.add(model);
  fitShape(shape);
  spacecraft.add(shape);
  const joints = [];
  model.traverse((object) => {
    if (object.userData.joint !== undefined) joints.push(object);
  });
  spacecraft.userData.joints = joints;
  // A panel on an articulated part turns with it. power.js gives the panels
  // as the model draws itself, and the new copy has not turned yet, so each
  // marker keeps its place as it moves under the part.
  spacecraft.updateMatrixWorld(true);
  for (const { marker, articulation } of spacecraft.userData.markers) {
    const part = joints.find((object) => ARTICULATIONS[object.userData.joint].name === articulation);
    if (part) part.attach(marker);
  }
}

/**
 * Marks each node that an articulation turns, so that every copy of the model
 * finds it: the articulation's number, the axis, and the node's own rotation.
 * The axis is kept in the frame of the node's parent, which is the body frame
 * unless a parent node is turned.
 */
function markJoints(gltf) {
  const scene = gltf.scene;
  scene.updateMatrixWorld(true);
  const byNode = new Map();
  scene.traverse((object) => {
    const association = gltf.parser.associations.get(object);
    if (association && association.nodes !== undefined) byNode.set(association.nodes, object);
  });
  ARTICULATIONS.forEach((joint, j) => {
    const object = byNode.get(joint.node);
    if (!object) {
      console.warn(`The articulation ${joint.name} turns ${joint.part}, which the model's scene does not have.`);
      return;
    }
    const toParent = object.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
    object.userData.joint = j;
    object.userData.jointAxis = new THREE.Vector3(...AXIS_VECTORS[joint.axis]).applyQuaternion(toParent).toArray();
    object.userData.jointBase = object.quaternion.toArray();
  });
  return scene;
}

const jointTurn = new THREE.Quaternion();
const jointAxis = new THREE.Vector3();

/** Turns each articulated part of a spacecraft to its angle at the time cursor. */
function turnJoints(spacecraft) {
  for (const object of spacecraft.userData.joints || []) {
    const { joint, jointAxis: axis, jointBase: base } = object.userData;
    jointTurn.setFromAxisAngle(jointAxis.fromArray(axis), state.joints[joint] * D2R);
    object.quaternion.fromArray(base).premultiply(jointTurn);
  }
}

// Why the 3D model could not be shown, if it could not
let modelProblem = "";

/** The 3D model's scene, once decoded, or null without a model or when it cannot be read. */
const modelScene = new Promise((resolve) => {
  // the designer draws no model, and its data does not hold it
  if (!MODEL || DESIGNER) return resolve(null);
  const failed = (error) => {
    modelProblem = `${MODEL.name} could not be read: ${(error && error.message) || error}`;
    console.warn(modelProblem);
    resolve(null);
  };
  try {
    const bytes = Uint8Array.from(atob(MODEL.glb_base64), (c) => c.charCodeAt(0));
    new THREE.GLTFLoader().parse(bytes.buffer, "", (gltf) => resolve(markJoints(gltf)), failed);
  } catch (error) {
    failed(error);
  }
});

function makeRenderer(viewport) {
  try {
    const renderer = new THREE.WebGLRenderer({ canvas: viewport.querySelector("canvas"), antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x050c18);
    return renderer;
  } catch (error) {
    viewport.append(element("div", { class: "vp-message", text: "This browser could not start WebGL, so the 3D view is off." }));
    return null;
  }
}

function addToggles(container, items) {
  const buttons = {};
  for (const item of items) {
    const button = element("button", { class: "toggle" + (item.on ? " on" : ""), text: item.label, "data-help": item.help });
    button.addEventListener("click", () => {
      item.on = !item.on;
      button.classList.toggle("on", item.on);
      item.set(item.on);
    });
    container.append(button);
    item.set(item.on);
    buttons[item.label] = button;
  }
  return buttons;
}

/** Text that follows points in a 3D view. Each label sits over its point after a render. */
function labelLayer(viewport) {
  const layer = element("div", { class: "labels" });
  viewport.querySelector("canvas").after(layer);
  const labels = [];
  const projected = new THREE.Vector3();
  return {
    add(text, colour, offset = [0, 0]) {
      const label = { node: element("div", { class: "label3d", text, style: `color:${colour}` }), position: new THREE.Vector3(), visible: true, offset };
      layer.append(label.node);
      labels.push(label);
      return label;
    },
    place(camera, width, height) {
      for (const label of labels) {
        projected.copy(label.position).project(camera);
        const visible = label.visible && projected.z < 1 && Math.abs(projected.x) < 1.05 && Math.abs(projected.y) < 1.05;
        label.node.style.display = visible ? "" : "none";
        if (!visible) continue;
        const x = ((projected.x + 1) / 2) * width + label.offset[0];
        const y = ((1 - projected.y) / 2) * height + label.offset[1];
        label.node.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
      }
    },
  };
}

// ---------------------------------------------------------------- Track colours

/** The rows the tracks can be coloured by, and the views that redraw on a change. */
const trackColours = (() => {
  const listeners = [];
  const choices = [
    ["payload_mode", "Payload mode"],
    ["platform_mode", "Platform mode"],
    ["attitude", "Attitude"],
    ["illumination", "Illumination"],
  ];
  const box = $("#orbit-legend");
  const buttons = choices.map(([key, label]) =>
    element("button", { class: "toggle", text: label, "data-help": "colourBy", onclick: () => choose(key) }),
  );
  const rows = element("div");
  box.append(element("div", { class: "choose" }, buttons), rows);

  function choose(key) {
    state.colourBy = key;
    buttons.forEach((button, j) => button.classList.toggle("on", choices[j][0] === key));
    const shown = new Set(TRACKS[key].map((piece) => piece.value));
    const values = [...Object.keys(COLOURS).filter((v) => shown.has(v)), ...[...shown].filter((v) => !(v in COLOURS))];
    rows.replaceChildren(
      ...values.map((value) => element("div", {}, [element("span", { class: "swatch", style: `background:${colourOf(value)}` }), value])),
    );
    const label = choices.find(([k]) => k === key)[1].toLowerCase();
    $("#ground-title").innerHTML = `<b>Ground track</b> · by ${label}`;
    listeners.forEach((listener) => listener());
  }
  return {
    onChange(listener) {
      listeners.push(listener);
    },
    start() {
      choose(state.colourBy);
    },
  };
})();
