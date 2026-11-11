"""Inspect actual positive hand and finger weights in Source2Viewer GLB exports."""

import json
import math
import struct

COMPONENTS = {5121: "B", 5123: "H", 5126: "f"}


def glb(path):
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw)
    if (magic, version, length) != (b"glTF", 2, len(raw)):
        raise ValueError("Invalid GLB header")
    json_length, kind = struct.unpack_from("<I4s", raw, 12)
    bin_header = 20 + json_length
    bin_length, bin_kind = struct.unpack_from("<I4s", raw, bin_header)
    if kind != b"JSON" or bin_kind != b"BIN\0" or bin_header + 8 + bin_length != len(raw):
        raise ValueError("Unexpected GLB chunks")
    return json.loads(raw[20:bin_header]), memoryview(raw)[bin_header + 8:]


def accessor(document, data, index, *, joints):
    entry = document["accessors"][index]
    component = entry["componentType"]
    view = document["bufferViews"][entry["bufferView"]]
    if (entry["type"] != "VEC4" or "sparse" in entry or view["buffer"] != 0
            or component not in COMPONENTS or (joints and component == 5126)
            or (not joints and component != 5126 and not entry.get("normalized"))):
        raise ValueError("Unsupported GLB skin accessor")
    unpack = struct.Struct("<4" + COMPONENTS[component])
    stride = view.get("byteStride", unpack.size)
    base = view.get("byteOffset", 0)
    start = base + entry.get("byteOffset", 0)
    count = entry["count"]
    end = start + max(count - 1, 0) * stride + unpack.size
    if not (count > 0 and stride >= unpack.size
            and 0 <= base <= start < end <= base + view["byteLength"] <= len(data)):
        raise ValueError("Invalid GLB accessor range")
    return count, (unpack.unpack_from(data, start + index * stride) for index in range(count))


def hand_weights(path, lod0, firstperson):
    document, data = glb(path)
    nodes = document["nodes"]
    meshes = document["meshes"]
    if len(meshes) != len(lod0) or not set(firstperson).issubset(lod0):
        raise ValueError("GLB meshes cannot be mapped to Source 2 LOD0")
    weighted = set()
    for source_index in firstperson:
        index = lod0.index(source_index)
        skins = {node["skin"] for node in nodes if node.get("mesh") == index and "skin" in node}
        if not skins:
            continue
        if len(skins) != 1:
            raise ValueError("Ambiguous GLB skins for a first-person mesh")
        bones = [nodes[i]["name"] for i in document["skins"][skins.pop()]["joints"]]
        for primitive in meshes[index]["primitives"]:
            attributes = primitive["attributes"]
            if "JOINTS_0" not in attributes and "WEIGHTS_0" not in attributes:
                continue
            joint_count, joints = accessor(document, data, attributes["JOINTS_0"], joints=True)
            weight_count, weights = accessor(document, data, attributes["WEIGHTS_0"], joints=False)
            if joint_count != weight_count:
                raise ValueError("Joint/weight stream lengths differ")
            for indices, values in zip(joints, weights, strict=True):
                for joint, weight in zip(indices, values, strict=True):
                    if not math.isfinite(weight) or weight < 0:
                        raise ValueError("Invalid GLB skin weight")
                    if weight > 1e-8:
                        weighted.add(bones[joint])
    if any("v_weapon" in bone.lower() for bone in weighted):
        raise ValueError("Legacy weapon bones still influence first-person geometry")
    for side in ("L", "R"):
        if f"hand_{side}" not in weighted or not any(
                bone.startswith("finger_") and bone.endswith(f"_{side}") for bone in weighted):
            raise ValueError(f"First-person hand or finger has no positive skin weight ({side})")
    return sorted(weighted)
