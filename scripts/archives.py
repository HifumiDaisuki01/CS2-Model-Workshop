"""Read package paths and extract Valve VPK entries without running input files."""

import shutil
import stat
import struct
import zipfile
import zlib
from pathlib import Path

MAX_FILES = 100_000
MAX_BYTES = 16 * 1024**3


def safe_path(name):
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((" ", "."))
                or any(c in '\\:*?"<>|' or ord(c) < 32 for c in part)
                or part.split(".")[0].upper() in reserved):
            raise ValueError(f"Unsafe package path: {name!r}")
    return name


def vpk_index(path):
    """Return VPK member metadata without reading the archive payload."""
    with path.open("rb") as stream:
        magic, version, size = struct.unpack("<III", stream.read(12))
        if magic != 0x55AA1234 or version not in (1, 2) or size > 64 * 1024**2:
            raise ValueError(f"Unsupported VPK: {path}")
        header = 12 if version == 1 else 28
        stream.seek(header)
        tree = stream.read(size)
    if len(tree) != size:
        raise ValueError("Truncated VPK directory")
    cursor = 0

    def word():
        nonlocal cursor
        end = tree.index(0, cursor)
        value = tree[cursor:end].decode("utf-8")
        cursor = end + 1
        return value

    entries = {}
    folded = set()
    while ext := word():
        while folder := word():
            while leaf := word():
                crc, preload, archive, offset, size, marker = struct.unpack_from("<IHHIIH", tree, cursor)
                cursor += 18
                if marker != 0xFFFF or cursor + preload > len(tree):
                    raise ValueError("Invalid VPK entry")
                name = safe_path(("" if folder == " " else folder + "/") + leaf
                                 + ("" if ext == " " else "." + ext))
                if name.casefold() in folded:
                    raise ValueError(f"Duplicate VPK path: {name}")
                folded.add(name.casefold())
                if archive == 0x7FFF:
                    chunk, start = path, header + len(tree) + offset
                else:
                    if not path.name.lower().endswith("_dir.vpk"):
                        raise ValueError("Split VPK must use its *_dir.vpk as input")
                    chunk = path.with_name(f"{path.name[:-8]}_{archive:03d}.vpk")
                    start = offset
                entries[name] = (chunk, start, size, tree[cursor:cursor + preload], crc)
                cursor += preload
    if cursor != len(tree):
        raise ValueError("Unexpected trailing VPK directory data")
    return entries


def extract_vpk(path, target):
    entries = vpk_index(path)
    if len(entries) > MAX_FILES or sum(e[2] + len(e[3]) for e in entries.values()) > MAX_BYTES:
        raise ValueError("VPK exceeds extraction limits")
    for name, (chunk, start, size, preload, expected_crc) in entries.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if chunk.is_symlink():
            raise ValueError(f"Linked VPK chunk: {chunk.name}")
        with chunk.open("rb") as source, destination.open("xb") as output:
            source.seek(start)
            output.write(preload)
            crc = zlib.crc32(preload)
            while size:
                data = source.read(min(size, 1024**2))
                if not data:
                    raise ValueError(f"Truncated VPK member: {name}")
                size -= len(data)
                crc = zlib.crc32(data, crc)
                output.write(data)
        if crc != expected_crc:
            raise ValueError(f"VPK CRC mismatch: {name}")


def extract_zip(path, target):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_BYTES:
            raise ValueError("ZIP exceeds extraction limits")
        seen = set()
        for member in members:
            name = safe_path(member.filename.removesuffix("/"))
            kind = stat.S_IFMT(member.external_attr >> 16)
            if name.casefold() in seen or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f"Unsupported or duplicate ZIP member: {name}")
            seen.add(name.casefold())
            destination = target / name
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)
