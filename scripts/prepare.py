#!/usr/bin/env python3
"""Prepare one CS2 player model for manual Workshop publishing."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile

from archives import extract_vpk, extract_zip, safe_path, vpk_index
from skin import glb, hand_weights

UPSTREAM = "https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER.git"
REVISION = "000c0f492761e0b396fa0eb264f0e679a23a18a7"
AG2 = {
    "animation/graphs/worldmodel/worldmodel.vnmgraph_c",
    "animation/graphs/viewmodel/viewmodel.vnmgraph_c",
    "animation/skeletons/characters/worldmodel.vnmskel_c",
    "animation/skeletons/characters/viewmodel.vnmskel_c",
}


def command(args, log=None, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=900, **kwargs)
    if log:
        log.write_text(result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        detail = f"see {log}" if log else (result.stderr or result.stdout).strip()[-500:]
        raise ValueError(f"{Path(args[0]).name} exited {result.returncode}: {detail}")
    return result.stdout


def tools_checkout(path):
    path = path.expanduser().resolve()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cs2-tools-", dir=path.parent) as work:
            checkout = Path(work) / "checkout"
            command(["git", "init", "-q", str(checkout)])
            command(["git", "-C", str(checkout), "fetch", "--depth=1", UPSTREAM, REVISION])
            command(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"])
            checkout.rename(path)
    prefix = ["git", "-C", str(path)]
    if command(prefix + ["rev-parse", "HEAD"]).strip() != REVISION:
        raise ValueError(f"Expected checkout {REVISION} at {path}")
    if command(prefix + ["status", "--porcelain", "--untracked-files=all"]):
        raise ValueError(f"Use a clean pinned tool checkout at {path}")
    return path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def legacy(path):
    return path.endswith(".vanmgrph_c") or "/animsets/" in path


def inventory(source, only=None):
    files = {}
    folded = {}
    for folder, directories, names in os.walk(source, followlinks=False):
        for name in directories + names:
            if (Path(folder) / name).is_symlink() or (Path(folder) / name).is_junction():
                raise ValueError(f"Linked input entry: {name}")
        for name in names:
            file = Path(folder) / name
            if not file.is_file():
                raise ValueError(f"Expected regular input: {file}")
            relative = file.relative_to(source).as_posix()
            if not relative.endswith("_c"):
                continue
            safe_path(relative)
            if relative.casefold() in folded:
                raise ValueError(f"Case-insensitive resource collision: {relative}")
            files[relative] = file
            folded[relative.casefold()] = relative
    candidates = []
    for relative, file in files.items():
        for match in re.finditer(r"(?:^|/)((?:phase2/)?characters/.*\.vmdl_c)$", relative):
            model = match[1]
            if only is None or file == only:
                candidates.append((relative[:-len(model)], model, file))
    return files, candidates


def choose(source, only, requested, refs):
    files, candidates = inventory(source, only)
    if requested:
        requested = safe_path(requested.removesuffix("_c") + "_c")
    found = []
    for prefix, model, path in candidates:
        if requested and requested != model:
            continue
        dependencies = set(refs(path))
        if requested or only or AG2 & dependencies or any(map(legacy, dependencies)):
            found.append((prefix, model, dependencies))
    if len(found) != 1:
        choices = ", ".join(model for _, model, _ in found[:15])
        raise ValueError(f"Expected one player model; found {len(found)}."
                         + (f" Select with --model: {choices}" if choices else
                            " Keep the original characters/... resource path and include its dependencies."))
    prefix, model, dependencies = found[0]
    selected = {name.removeprefix(prefix): file for name, file in files.items()
                if name.startswith(prefix)}
    return selected, model, dependencies


def closure(model, files, base, refs):
    queue = [model]
    present, stock, missing = set(), set(), set()
    while queue:
        relative = safe_path(queue.pop())
        if relative in present or relative in stock or relative in missing:
            continue
        if relative != model and relative in base:
            stock.add(relative)
        elif relative in files:
            present.add(relative)
            queue.extend(refs(files[relative]))
        else:
            missing.add(relative)
    return present, stock, missing


def array(data, key, pattern):
    match = re.search(r"\b" + key + r"\s*=\s*\[(.*?)\]", data, re.S)
    return re.findall(pattern, match[1]) if match else []


def model_structure(data, canonical, require_arms=True):
    bones = array(data, "m_boneName", r'"([^"]+)"')
    parents = [int(value) for value in array(data, "m_nParent", r"-?\d+")]
    if (len(bones) != len(parents) or len(set(bones)) != len(bones)
            or not all(-1 <= p < len(bones) for p in parents)):
        raise ValueError("Unexpected model skeleton metadata")
    hierarchy = {bone: bones[parent] if parent >= 0 else None
                 for bone, parent in zip(bones, parents, strict=True)}
    mismatch = [bone for bone, parent in canonical[:24]
                if bone not in hierarchy or hierarchy[bone] != parent]
    if mismatch:
        raise ValueError("Incompatible core skeleton: " + ", ".join(mismatch))
    groups = array(data, "m_meshGroups", r'"([^"]+)"')
    first = [i for i, group in enumerate(groups) if group.split("#&")[-1] == "firstperson_default"]
    masks = [int(value) for value in array(data, "m_refMeshGroupMasks", r"\d+")]
    lod = [int(value) for value in array(data, "m_refLODGroupMasks", r"\d+")]
    lod0 = [i for i, mask in enumerate(lod) if mask & 1]
    mesh = [i for i, mask in enumerate(masks) if len(first) == 1 and mask & (1 << first[0])]
    if mesh and (len(masks) != len(lod) or not set(mesh).issubset(lod0)):
        raise ValueError("First-person mesh is not in LOD0")
    if require_arms and not mesh:
        raise ValueError("No embedded first-person mesh in LOD0. Supply a complete compatible model.")
    return lod0, mesh


def model_data(cli, path, log):
    return command([cli, "-i", str(path), "-b", "DATA"], log)


def export_skin(cli, path, output, log):
    command([cli, "-d", "-i", str(path), "-o", str(output),
             "--gltf_export_format", "glb", "--gltf_export_animations"], log)
    if not output.is_file():
        raise ValueError(f"Source2Viewer did not produce a rigged GLB: {log}")


def copy_resources(files, names, target):
    for name in sorted(names):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[name], destination)
    return {name: target / name for name in names}


def repair_reference(upstream, cli, files, model, missing, dependencies, base, refs, work, logs, canonical):
    if len(missing) != 1 or not missing.issubset(dependencies):
        return files, []
    obsolete = next(iter(missing))
    data = model_data(cli, files[model], logs / "original-data.log")
    if not obsolete.startswith("characters/") or not obsolete.endswith(".vmdl_c"):
        return files, []
    if "/animsets/" in obsolete:
        if (obsolete != "characters/models/shared/animsets/animset_ct.vmdl_c"
                or digest(files[model]) != "6ebc7c80c53befdb2face68f0b74e9ed4be9998d5d2c5d05a08f8e6f3676ccd0"):
            raise ValueError(f"Obsolete animation include requires a reviewed migration: {obsolete}")
        operation, project = "anim-include-repair", "AnimIncludeRepair"
    elif "character_arm_config" in data:
        operation, project = "arm-reference-repair", "ResourceRepair"
    else:
        return files, []
    model_structure(data, canonical)
    repair_project = (upstream / "server/workshop/fifteen-models/tools" / operation / (project + ".csproj"))
    dotnet = shutil.which("dotnet")
    if not dotnet:
        raise ValueError(f"Install .NET 10 SDK to repair {obsolete}")
    present, _, _ = closure(model, files, base, refs)
    staged = copy_resources(files, present, work / "repair-input")
    # Keep the repaired model next to its dependencies for both VRF GLB exports.
    fixed = staged[model].with_name(staged[model].stem + "-repaired.vmdl_c")
    report = logs / "repair.json"
    command([dotnet, "run", "--project", str(repair_project), "-c", "Release",
             "--artifacts-path", str(work / "dotnet"), "--",
             str(staged[model]), str(fixed), obsolete.removesuffix("_c"), str(report)],
            logs / "repair.log")
    proof = json.loads(report.read_text(encoding="utf-8-sig"))
    if (not proof.get("StaticRepairPassed") or not proof.get("OnlyDataAndReferenceBlocksChanged")
            or proof["InputSHA256"] != digest(staged[model]) or proof["OutputSHA256"] != digest(fixed)):
        raise ValueError("Structured repair proof did not match the files")
    # Independently verify identical exported geometry and skin data.
    before, after = work / "before.glb", work / "after.glb"
    export_skin(cli, staged[model], before, logs / "repair-original-skin.log")
    original_doc, original_bin = glb(before)
    fixed.replace(staged[model])
    export_skin(cli, staged[model], after, logs / "repair-fixed-skin.log")
    repaired_doc, repaired_bin = glb(after)
    if original_bin != repaired_bin or any(original_doc.get(key) != repaired_doc.get(key)
            for key in ("meshes", "skins", "accessors", "bufferViews", "animations")):
        raise ValueError("The repair changed exported geometry, skin or animation")
    return files | {model: staged[model]}, [obsolete]


def compile_legacy(args, upstream, porter, files, model, ident, base, present, stock, missing, work, logs):
    if any(not legacy(path) for path in missing):
        raise ValueError("Missing original dependencies: " + ", ".join(sorted(missing)))
    compiler = args.cs2 / "game/bin/win64/resourcecompiler.exe" if args.cs2 else None
    if os.name != "nt" or not compiler or not compiler.is_file():
        raise ValueError("AG1 needs a Windows build machine with CS2 Workshop Tools. Set CS2_GAME or --cs2.")
    source = work / "legacy-input"
    copy_resources(files, present, source)
    manifest, base_file = work / "manifest.json", work / "base.txt"
    save_json(manifest, [{"Id": ident, "Path": model.removesuffix("_c"),
                          "OriginalSHA256": digest(files[model]), "AllDependencies": sorted(present | stock)}])
    base_file.write_text("\n".join(sorted(base)), encoding="utf-8")
    project = work / "conversion"
    vendor = upstream / "server/ag2-port/tools/vendor"
    results = porter.prepare(source, manifest, base_file, args.vrf, vendor / "ag2port.py",
                             vendor / "canonical_skeleton.txt", project)
    shutil.copytree(project / "reports", logs / "ag2")
    if len(results) != 1:
        raise ValueError("AG2 converter did not return one model result")
    if not results[0].get("StaticSourcePassed"):
        raise ValueError(f"AG2 source validation failed: {results[0].get('Failures') or results[0].get('Error')}")
    addon = f"keran_build_{uuid.uuid4().hex[:12]}"
    game = args.cs2 / "game/csgo_addons" / addon
    content = args.cs2 / "content/csgo_addons" / addon
    source_addon = project / "workshop-addon"
    try:
        shutil.copytree(source_addon / "content/csgo_addons/ks_ag2_repair", content)
        shutil.copytree(source_addon / "game/csgo_addons/ks_ag2_repair", game)
        output = game / model
        if output.exists():
            raise ValueError("Unexpected existing output in isolated compile project")
        save_json(logs / "compiler.json", {"CompilerSHA256": digest(compiler)})
        command([str(compiler), "-i", str(content / model.removesuffix("_c"))],
                logs / "compiler.log", cwd=compiler.parent)
        if not output.is_file():
            raise ValueError("Valve compiler produced no new .vmdl_c")
        preserved = json.loads((project / "reports/preserved-assets.json").read_text(encoding="utf-8"))
        for name, expected in preserved.items():
            if digest(game / safe_path(name)) != expected:
                raise ValueError(f"Compiler changed preserved material or texture: {name}")
        compiled = {p.relative_to(game).as_posix(): p for p in game.rglob("*")
                    if p.is_file() and p.name.endswith("_c")}
        return files | copy_resources(compiled, compiled, work / "compiled")
    finally:
        for path in (content, game):
            if path.is_dir():
                shutil.rmtree(path)


def prepare(args, upstream, work, result):
    sys.path[:0] = [str(upstream / "server/ag2-port/tools"), str(upstream / "server/tools")]
    import port_projects as porter
    from pack_workshop import pack
    from verify_vpk import inspect

    logs = args.output / "logs"
    source, only = args.input, None
    if source.is_file() and source.suffix.lower() in (".zip", ".vpk"):
        source = work / "extracted"
        source.mkdir()
        reader = extract_zip if args.input.suffix.lower() == ".zip" else extract_vpk
        reader(args.input, source)
    elif source.is_file() and source.name.endswith(".vmdl_c"):
        only = source
        source = next((p.parent for p in only.parents if p.name == "characters"), only.parent)
        if source.name == "phase2":
            source = source.parent
    elif not source.is_dir():
        raise ValueError("Input must be a ZIP, VPK, compiled .vmdl_c or resource directory")

    files, model, dependencies = choose(source, only, args.model, porter.refs)
    ident = args.id or re.sub(r"[^a-z0-9_-]+", "-", Path(model).name.removesuffix(".vmdl_c").lower()).strip("-_")[:48]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", ident) or ident == "default":
        raise ValueError("Model ID must be 1–48 lowercase letters/digits, underscores or hyphens, excluding default")
    result.update(Model=model, Id=ident, InputSHA256=digest(files[model]))
    base = set((upstream / "server/tools/base-resources-confirmed.txt").read_text().splitlines())
    stock_vpk = args.base_vpk or (args.cs2 / "game/csgo/pak01_dir.vpk" if args.cs2 else None)
    if stock_vpk:
        if stock_vpk.is_file():
            base = set(vpk_index(stock_vpk))
            result["StockResourceEvidence"] = "local CS2 VPK index"
        elif args.base_vpk:
            raise ValueError(f"Specified stock VPK does not exist: {stock_vpk}")
    result.setdefault("StockResourceEvidence", "pinned historical CS2 resource list")
    canonical = porter.canonical(upstream / "server/ag2-port/tools/vendor/canonical_skeleton.txt")
    present, stock, missing = closure(model, files, base, porter.refs)
    if AG2.issubset(dependencies):
        files, repaired = repair_reference(upstream, args.vrf, files, model, missing, dependencies,
                                           base, porter.refs, work, logs, canonical)
        result["RepairedReferences"] = repaired
    elif any(map(legacy, dependencies)) and not (AG2 & dependencies):
        files = compile_legacy(args, upstream, porter, files, model, ident, base, present, stock, missing,
                               work, logs)
        result["CompiledOnWindows"] = True
    else:
        raise ValueError("Unsupported animation graph or incomplete AG2 bindings")

    dependencies = set(porter.refs(files[model]))
    present, stock, missing = closure(model, files, base, porter.refs)
    if missing:
        raise ValueError("Missing dependencies: " + ", ".join(sorted(missing)))
    if not AG2.issubset(dependencies) or any(map(legacy, present | stock)):
        raise ValueError("AG2 bindings missing or legacy animation references remain")
    staged = copy_resources(files, present, work / "resources")
    model_metadata = model_data(args.vrf, staged[model], logs / "model-data.log")
    for index, (name, path) in enumerate(sorted(staged.items())):
        if name == model:
            continue
        log = logs / f"resource-{index:05}.log"
        try:
            model_data(args.vrf, path, log)
        except ValueError as error:
            raise ValueError(f"Unable to parse {name}: {error}") from error
        log.unlink()
    if re.search(r"\.vanmgrph\b|/animsets/", model_metadata):
        raise ValueError("Legacy animation references remain in model DATA")
    lod0, mesh = model_structure(model_metadata, canonical, require_arms=not result["CompiledOnWindows"])
    if mesh:
        exported = work / "skin.glb"
        export_skin(args.vrf, staged[model], exported, logs / "first-person-skin.log")
        result["FirstPersonWeightedBones"] = hand_weights(exported, lod0, mesh)
    else:
        result["FirstPersonWeightedBones"] = []
    result["FirstPerson"] = "embedded, positive hand/finger weights checked" if mesh else "stock arms expected"

    addon = f"keran_{ident.replace('-', '_')}_{digest(staged[model])[:8]}"
    addoninfo = ('"AddonInfo"\n{\n "addonversion" "1"\n'
                 f' "addonname" "{addon}"\n "addontitle" "CS2 Character {ident}"\n'
                 ' "addondescription" "CS2 community server player model resources."\n'
                 ' "IsPlayable" "0"\n}\n')
    (work / "resources/addoninfo.txt").write_text(addoninfo, encoding="utf-8")
    if sum(path.stat().st_size for path in staged.values()) > 1024**3:
        raise ValueError("Selected dependency closure exceeds the 1 GiB package limit")
    vpk = work / "workshop-vpk"
    pack(work / "resources", vpk)
    verification = inspect(vpk / "pak01_dir.vpk")
    hashes = {entry["Path"]: entry["SHA256"] for entry in verification["Entries"]}
    expected = {name: digest(path) for name, path in staged.items()}
    expected["addoninfo.txt"] = digest(work / "resources/addoninfo.txt")
    if hashes != expected:
        raise ValueError("VPK does not match the staged resources")

    artifact = work / "artifact"
    content = artifact / "addon/content/csgo_addons" / addon
    game = artifact / "addon/game/csgo_addons" / addon
    content.mkdir(parents=True)
    shutil.copytree(work / "resources", game)
    (content / "addoninfo.txt").write_text(addoninfo, encoding="utf-8")
    shutil.move(vpk, artifact / "workshop-vpk")
    config = {"Models": {ident: {"name": args.name or ident, "path": model.removesuffix("_c"),
                                  "permissions": [], "permissionsOr": [], "side": "All",
                                  "disableleg": False, "hideinmenu": False}}}
    save_json(artifact / "PlayerModelChanger.merge.json", config)
    save_json(artifact / "resources.sha256.json", hashes)
    template = Path(__file__).resolve().parents[1] / "references/workshop.md"
    guide = template.read_text(encoding="utf-8").replace("{{ADDON}}", addon).replace("{{ID}}", ident)
    (artifact / "UPLOAD-WORKSHOP.md").write_text(guide, encoding="utf-8")
    artifact.rename(args.output / "package")
    result.update(Status="prepared", Addon=addon, StockDependencies=sorted(stock),
                  CompiledModelSHA256=expected[model], VerifiedResources=len(expected),
                  VpkCRCVerified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", help="Exact internal .vmdl path when there are multiple player models")
    parser.add_argument("--id", help="Override the generated !model ID")
    parser.add_argument("--name", help="Override the menu display name")
    parser.add_argument("--vrf", default=os.getenv("CS2_VRF") or "Source2Viewer-CLI")
    parser.add_argument("--cs2", type=Path, default=os.getenv("CS2_GAME"))
    parser.add_argument("--base-vpk", type=Path)
    parser.add_argument("--tools", type=Path, default=Path.home() / ".cache/cs2-model-workshop" / REVISION)
    args = parser.parse_args()
    args.input = args.input.absolute()
    args.output = (args.output or args.input.with_name(args.input.stem + "-workshop")).resolve()
    if args.input.is_symlink() or args.input.is_junction():
        parser.error("Supply a regular input path")
    args.input = args.input.resolve()
    if not args.input.exists() or args.output.exists() or args.output.is_relative_to(args.input):
        parser.error("Input must exist and output must be a new directory outside the input")
    args.vrf = shutil.which(args.vrf)
    if not args.vrf:
        parser.error("Install Source2Viewer-CLI and set CS2_VRF or --vrf")
    args.vrf = str(Path(args.vrf).resolve())
    if args.cs2:
        args.cs2 = args.cs2.expanduser().resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "logs").mkdir()
    result = {"Status": "blocked", "CompiledOnWindows": False, "WorkshopUploaded": False,
              "GameVerified": False, "UpstreamToolRevision": REVISION}
    try:
        upstream = tools_checkout(args.tools)
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=args.output) as temporary:
            prepare(args, upstream, Path(temporary), result)
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, IndexError, struct.error,
            subprocess.SubprocessError, zipfile.BadZipFile) as error:
        result["Error"] = str(error)
        print(f"Blocked: {error}", file=sys.stderr)
    save_json(args.output / "report.json", result)
    if result["Status"] == "prepared":
        print(args.output / "package/UPLOAD-WORKSHOP.md")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
