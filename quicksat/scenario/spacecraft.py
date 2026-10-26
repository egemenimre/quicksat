# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The spacecraft's 3D model, a binary glTF (GLB) file, in body axes and metres.

`read_glb_json` checks the file for the viewer, and `read_model` gives each part's
triangles in body axes, for power. `docs/guides/scenario/prepare_a_3d_model.md` says how
to prepare one.

"""

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

UNSUPPORTED_EXTENSIONS = {
    "KHR_draco_mesh_compression": "Draco compression",
    "EXT_meshopt_compression": "meshopt compression",
    "KHR_texture_basisu": "Basis Universal textures",
}
"""The extensions the viewer cannot decode, with what each is."""


def read_glb_json(path: Path) -> dict:
    """
    The JSON part of a GLB file, after checking that the viewer can read it.

    Parameters
    ----------
    path : Path
        The GLB file

    Returns
    -------
    gltf : dict
        The glTF JSON

    Raises
    ------
    ValueError
        If the file is not a glTF 2 GLB, its length is wrong, or it needs an extension
        the viewer lacks
    """
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(
            f"{path.name} is not a GLB file: it does not start with 'glTF'"
        )
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError(f"{path.name} is glTF version {version}, and only 2 is read")
    if length != len(data):
        raise ValueError(
            f"{path.name} is damaged: its header gives {length} bytes, but it holds "
            f"{len(data)}"
        )
    chunk_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON":
        raise ValueError(f"{path.name} is damaged: its first chunk is not JSON")
    gltf = json.loads(data[20 : 20 + chunk_length])

    needed = [
        UNSUPPORTED_EXTENSIONS[name]
        for name in gltf.get("extensionsRequired", [])
        if name in UNSUPPORTED_EXTENSIONS
    ]
    if needed:
        raise ValueError(
            f"{path.name} needs {' and '.join(needed)}, which the viewer cannot "
            "decode. Export it without compression."
        )
    return gltf


def _scene_roots(gltf: dict) -> list[int]:
    """The root nodes of the scene that the model shows."""
    scenes = gltf.get("scenes", [])
    scene = scenes[gltf.get("scene", 0)] if scenes else {"nodes": []}
    return list(scene.get("nodes", []))


def node_index(gltf: dict, name: str, user: str = "an articulation") -> int:
    """
    The index of the one node in the model's scene with a name.

    Parameters
    ----------
    gltf : dict
        The glTF JSON
    name : str
        The node's name
    user : str, optional
        What needs the node, for the error

    Returns
    -------
    index : int
        The node's index in `nodes`

    Raises
    ------
    ValueError
        If no node, or more than one, has the name
    """
    nodes = gltf.get("nodes", [])
    # the nodes the scene draws: its roots and all their children
    drawn, waiting = set(), _scene_roots(gltf)
    while waiting:
        index = waiting.pop()
        if index not in drawn:
            drawn.add(index)
            waiting.extend(nodes[index].get("children", []))
    matches = sorted(i for i in drawn if nodes[i].get("name") == name)
    if len(matches) != 1:
        found = "no node" if not matches else f"{len(matches)} nodes"
        raise ValueError(
            f"the model has {found} named '{name}' in its scene, and {user} "
            "needs exactly one"
        )
    return matches[0]


COMPONENT_TYPES = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
"""The numpy type of each glTF component type."""

ELEMENT_WIDTHS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
"""The number of components in each glTF element type."""

TRIANGLES, TRIANGLE_STRIP, TRIANGLE_FAN = 4, 5, 6
"""The glTF primitive modes that draw triangles. The other modes draw points and
lines, which have no area."""


@dataclass(frozen=True)
class ModelPart:
    """
    One node of the 3D model that has a mesh, with its triangles in body axes.

    Parameters
    ----------
    name : str
        The node's name, empty if none
    node : int
        The node's index in `nodes`
    triangles : ndarray
        The triangles' corners in body axes, in m, counter-clockwise from the front,
        shape (m, 3, 3)
    ancestors : tuple of int
        The nodes above it, from the scene's root down
    """

    name: str
    node: int
    triangles: np.ndarray
    ancestors: tuple[int, ...]


@dataclass(frozen=True)
class ModelGeometry:
    """
    The triangles of a 3D model, as its scene places them, in body axes.

    Parameters
    ----------
    parts : list of ModelPart
        Every node with triangles
    origins : dict of int to ndarray
        Every node's origin in body axes, in m, by index
    """

    parts: list[ModelPart]
    origins: dict[int, np.ndarray]


def _node_matrix(node: dict) -> np.ndarray:
    """A node's transform from its own axes to its parent's, as a 4x4 matrix."""
    if "matrix" in node:
        # glTF writes the matrix column by column
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * np.array(node.get("scale", [1.0, 1.0, 1.0]))
    matrix[:3, 3] = node.get("translation", [0.0, 0.0, 0.0])
    return matrix


def _binary_chunk(data: bytes, name: str) -> bytes:
    """The binary chunk of a GLB file, empty if it has none."""
    json_length = struct.unpack_from("<I", data, 12)[0]
    start = 20 + json_length
    if start + 8 > len(data):
        return b""
    length, kind = struct.unpack_from("<I4s", data, start)
    if kind != b"BIN\0":
        raise ValueError(f"{name} is damaged: its second chunk is not binary")
    return data[start + 8 : start + 8 + length]


def _triangle_corners(indices: np.ndarray, mode: int) -> np.ndarray:
    """
    The vertex indices of each triangle of a primitive, a strip or fan unrolled to face
    one way, shape (m, 3).
    """
    if mode == TRIANGLES:
        return indices[: len(indices) // 3 * 3].reshape(-1, 3)
    steps = np.arange(max(len(indices) - 2, 0))
    if mode == TRIANGLE_STRIP:
        first = np.where(steps % 2 == 0, steps, steps + 1)
        second = np.where(steps % 2 == 0, steps + 1, steps)
        return np.stack([indices[first], indices[second], indices[steps + 2]], 1)
    return np.stack(
        [np.full_like(steps, indices[0]), indices[steps + 1], indices[steps + 2]], 1
    )


def _accessor(gltf: dict, binary: bytes, index: int, name: str) -> np.ndarray:
    """
    One accessor's values from the GLB's binary chunk, refusing values stored outside
    the file.
    """
    item = gltf["accessors"][index]
    if "bufferView" not in item:
        raise ValueError(
            f"{name}: accessor {index} has no data in the file, and quicksat reads "
            "only data stored in the GLB"
        )
    view = gltf["bufferViews"][item["bufferView"]]
    if "uri" in gltf["buffers"][view["buffer"]]:
        raise ValueError(
            f"{name} keeps its vertices in another file, and quicksat reads only "
            "data stored in the GLB"
        )
    kind = np.dtype(COMPONENT_TYPES[item["componentType"]])
    width = ELEMENT_WIDTHS[item["type"]]
    stride = view.get("byteStride", width * kind.itemsize)
    values = np.ndarray(
        (item["count"], width),
        kind,
        binary,
        view.get("byteOffset", 0) + item.get("byteOffset", 0),
        (stride, kind.itemsize),
    )
    return values if width > 1 else values[:, 0]


def _mesh_triangles(
    gltf: dict, binary: bytes, mesh: int, matrix: np.ndarray, name: str
) -> np.ndarray:
    """
    One mesh's triangles placed in body axes by a node's transform, turned round where
    it mirrors space.
    """
    pieces = [np.empty((0, 3, 3))]
    for primitive in gltf["meshes"][mesh]["primitives"]:
        mode = primitive.get("mode", TRIANGLES)
        if mode not in (TRIANGLES, TRIANGLE_STRIP, TRIANGLE_FAN):
            continue
        positions = _accessor(gltf, binary, primitive["attributes"]["POSITION"], name)
        positions = positions.astype(float) @ matrix[:3, :3].T + matrix[:3, 3]
        if "indices" in primitive:
            indices = _accessor(gltf, binary, primitive["indices"], name).astype(int)
        else:
            indices = np.arange(len(positions))
        pieces.append(positions[_triangle_corners(indices, mode)])
    triangles = np.concatenate(pieces)
    if np.linalg.det(matrix[:3, :3]) < 0:
        triangles = triangles[:, ::-1]
    return triangles


def read_model(path: Path) -> ModelGeometry:
    """
    The triangles of every part of a GLB model, in body axes, with points and lines left
    out.

    Parameters
    ----------
    path : Path
        The GLB file

    Returns
    -------
    geometry : ModelGeometry
        The parts and the node origins

    Raises
    ------
    ValueError
        If `read_glb_json` refuses the file, or its vertices are outside it
    """
    gltf = read_glb_json(path)
    binary = _binary_chunk(path.read_bytes(), path.name)
    nodes = gltf.get("nodes", [])
    parts, origins = [], {}
    # each entry: a node, its parent's transform to body axes, and the nodes
    # above it
    waiting: list[tuple[int, np.ndarray, tuple[int, ...]]] = [
        (root, np.eye(4), ()) for root in _scene_roots(gltf)
    ]
    while waiting:
        index, parent, ancestors = waiting.pop(0)
        node = nodes[index]
        matrix = parent @ _node_matrix(node)
        origins[index] = matrix[:3, 3]
        if "mesh" in node:
            triangles = _mesh_triangles(gltf, binary, node["mesh"], matrix, path.name)
            if len(triangles):
                parts.append(
                    ModelPart(node.get("name", ""), index, triangles, ancestors)
                )
        waiting.extend(
            (child, matrix, (*ancestors, index)) for child in node.get("children", [])
        )
    return ModelGeometry(parts, origins)
