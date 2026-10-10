# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The spacecraft's 3D model, a binary glTF (GLB) file.

The scenario file names the model with `3d_model`, and the viewer draws it in
place of its plain cube. The model must be in body axes and in metres, with its
origin at the point the body turns about. glTF puts +y up by convention, but
quicksat takes the axes as they are: the model's x, y and z are the body's.

A GLB file holds a header, a JSON chunk that describes the scene, and a binary
chunk with the vertices. This module reads the header and the JSON, to check the
file before the viewer gets it.

A part of the model can turn, such as a solar wing. The scenario file names it
as an articulation, by the name of its node. The node turns about an axis
through its own origin, and its children turn with it.

"""

import json
import struct
from pathlib import Path

UNSUPPORTED_EXTENSIONS = {
    "KHR_draco_mesh_compression": "Draco compression",
    "EXT_meshopt_compression": "meshopt compression",
    "KHR_texture_basisu": "Basis Universal textures",
}
"""Extensions the viewer cannot decode, with what each one is. Each needs a
decoder that the page does not carry."""


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
        The glTF JSON: the scene, its nodes, meshes and materials

    Raises
    ------
    ValueError
        If the file is not a GLB file of glTF version 2, if its length does not
        match its header, or if it needs an extension the viewer cannot decode
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


def node_index(gltf: dict, name: str) -> int:
    """
    The index of the one node in the model's scene with a given name.

    Parameters
    ----------
    gltf : dict
        The glTF JSON, as `read_glb_json` returns it
    name : str
        The node's name

    Returns
    -------
    index : int
        The node's index in the glTF `nodes` list

    Raises
    ------
    ValueError
        If no node in the scene has the name, or more than one has it
    """
    nodes = gltf.get("nodes", [])
    scenes = gltf.get("scenes", [])
    scene = scenes[gltf.get("scene", 0)] if scenes else {"nodes": []}
    # the nodes the scene draws: its roots and all their children
    drawn, waiting = set(), list(scene.get("nodes", []))
    while waiting:
        index = waiting.pop()
        if index not in drawn:
            drawn.add(index)
            waiting.extend(nodes[index].get("children", []))
    matches = sorted(i for i in drawn if nodes[i].get("name") == name)
    if len(matches) != 1:
        found = "no node" if not matches else f"{len(matches)} nodes"
        raise ValueError(
            f"the model has {found} named '{name}' in its scene, and an "
            "articulation needs exactly one"
        )
    return matches[0]
