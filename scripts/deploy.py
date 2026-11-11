#!/usr/bin/env python3
"""Deploy a prepared Workshop model to an existing Linux CS2 server over SSH."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import zlib

from archives import safe_path, vpk_index

PMC = "addons/counterstrikesharp/plugins/PlayerModelChanger"
FILES = (
    "cfg/multiaddonmanager/multiaddonmanager.cfg",
    "addons/counterstrikesharp/configs/plugins/PlayerModelChanger/PlayerModelChanger.json",
    f"{PMC}/resource-catalog.json",
)
WORKSHOP_ID = re.compile(r"[1-9][0-9]{0,19}")
MODEL_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
UNIT = re.compile(r"[\w@.-]+\.service", re.ASCII)


def workshop_id(value):
    if WORKSHOP_ID.fullmatch(value):
        return value
    url = urlsplit(value)
    ids = parse_qs(url.query).get("id", [])
    if (url.scheme == "https" and url.netloc == "steamcommunity.com"
            and url.path.rstrip("/") in ("/sharedfiles/filedetails", "/workshop/filedetails")
            and len(ids) == 1 and WORKSHOP_ID.fullmatch(ids[0])):
        return ids[0]
    raise ValueError("Supply the published Steam Workshop link or its numeric ID")


def read_packet(stream):
    size = struct.unpack("<i", receive(stream, 4))[0]
    if not 10 <= size <= 8192:
        raise ValueError("Invalid RCON response length")
    request, kind = struct.unpack("<ii", receive(stream, 8))
    body = receive(stream, size - 8)
    if not body.endswith(b"\0\0"):
        raise ValueError("Invalid RCON response terminator")
    return request, kind, body[:-2]


def receive(stream, size):
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise ValueError("RCON connection closed")
        data.extend(chunk)
    return data


def send_packet(stream, request, kind, body):
    if b"\0" in body or len(body) > 4086:
        raise ValueError("Invalid RCON request")
    stream.sendall(struct.pack("<iii", 10 + len(body), request, kind) + body + b"\0\0")


def rcon(port, password, command):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as stream:
        send_packet(stream, 10, 3, password.encode())
        for _ in range(4):
            request, kind, _ = read_packet(stream)
            if kind == 2:
                if request != 10:
                    raise ValueError("RCON authentication failed")
                break
        else:
            raise ValueError("No RCON authentication response")
        send_packet(stream, 11, 2, command.encode())
        send_packet(stream, 12, 2, b"echo CS2_MODEL_WORKSHOP_RCON_END")
        response = bytearray()
        for _ in range(256):
            request, _, data = read_packet(stream)
            if request == 12 and b"CS2_MODEL_WORKSHOP_RCON_END" in data:
                return response.decode("utf-8", errors="replace")
            if request == 11:
                response.extend(data)
        raise ValueError("RCON response exceeded the packet limit")


def password_for(csgo, filename):
    if filename:
        password = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
    else:
        password = os.getenv("RCON_PASSWORD")
        if not password:
            cfg = csgo / "cfg/server.cfg"
            values = re.findall(r'^\s*rcon_password\s+"([^"\r\n]+)"\s*(?://.*)?$',
                                cfg.read_text(encoding="utf-8-sig"), re.M) if cfg.is_file() else []
            password = values[0] if len(values) == 1 else None
    if not password:
        raise ValueError("Use --rcon-password-file pointing to a password file on the server")
    return password


def installation(csgo, service):
    candidates = set()
    if not csgo or not service:
        for entry in Path("/proc").glob("[0-9]*/exe"):
            try:
                exe = entry.resolve(strict=True)
                if exe.name != "cs2" or exe.parent.parent.name != "bin":
                    continue
                game = exe.parent.parent.parent / "csgo"
                cgroup = (entry.parent / "cgroup").read_text()
                units = [part for part in cgroup.split("/") if UNIT.fullmatch(part.strip())]
                if units:
                    candidates.add((game, units[-1].strip()))
            except (OSError, RuntimeError):
                continue
        matches = [(game, unit) for game, unit in candidates
                   if (not csgo or game == Path(csgo).resolve()) and (not service or unit == service)]
        if len(matches) != 1:
            raise ValueError("Cannot identify one CS2 systemd instance. Supply --csgo and --service.")
        game, unit = matches[0]
        csgo, service = csgo or str(game), service or unit
    if not UNIT.fullmatch(service) or service.startswith("-"):
        raise ValueError("Expected a systemd service such as cs2.service")
    csgo = Path(csgo).resolve(strict=True)
    for filename in FILES[:2]:
        path = csgo / filename
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(csgo):
            raise ValueError(f"Missing or linked installed configuration: {filename}")
    if not (csgo / PMC / "PlayerModelChanger.dll").is_file():
        raise ValueError("The compatible PlayerModelChanger fork must already be installed")
    return csgo, service


def read_settings(csgo):
    configs = []
    for name in FILES:
        path = csgo / name
        if path.is_symlink() or not path.resolve().is_relative_to(csgo):
            raise ValueError(f"Unsafe config path: {name}")
        configs.append(path.read_bytes() if path.exists() else None)
    return configs


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def parse_mam(raw, item):
    value = raw.decode("utf-8-sig")
    assignment = r'(?m)^([ \t]*mm_extra_addons[ \t]+)"([0-9, \t]*)"([ \t]*(?://[^\r\n]*)?)(?=\r?$)'
    matches = list(re.finditer(assignment, value))
    declarations = re.findall(r"(?m)^[ \t]*mm_extra_addons\b", value)
    if len(matches) != len(declarations) or len(matches) > 1:
        raise ValueError("Ambiguous mm_extra_addons assignments in MAM config")
    clients = re.findall(r'(?m)^[ \t]*mm_client_extra_addons[ \t]+"([^"\r\n]*)"', value)
    if any(item in (entry.strip() for entry in row.split(",")) for row in clients):
        raise ValueError("Remove the duplicate client-only Workshop entry first")
    if not matches:
        return (value.rstrip("\n") + f'\nmm_extra_addons "{item}"\n').encode(), False
    match = matches[0]
    ids = [entry.strip() for entry in match[2].split(",") if entry.strip()]
    if item in ids:
        return raw, True
    updated = value[:match.start(2)] + ",".join(ids + [item]) + value[match.end(2):]
    return updated.encode(), False


def package_data(package):
    model_file = Path(package) / "PlayerModelChanger.merge.json"
    models = json.loads(model_file.read_text(encoding="utf-8"))["Models"]
    if len(models) != 1:
        raise ValueError("Expected one generated model configuration")
    ident, model = next(iter(models.items()))
    if not MODEL_ID.fullmatch(ident) or ident == "default" or not model["path"].endswith(".vmdl"):
        raise ValueError("Invalid model ID or path")
    model_path = safe_path(model["path"] + "_c")
    if not model_path.startswith(("characters/", "phase2/characters/")):
        raise ValueError("Expected a character model path")
    hashes = json.loads((Path(package) / "resources.sha256.json").read_text(encoding="utf-8"))
    hashes.pop("addoninfo.txt", None)
    if model_path not in hashes:
        raise ValueError("Resource manifest does not contain the model")
    for path, digest in hashes.items():
        if safe_path(path) != path or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid resource manifest entry")
    return ident, model, hashes


def candidate_vpks(csgo, item, override):
    if override:
        return [Path(override).resolve()]
    game = csgo.parent
    install = game.parent
    dirs = (game / "bin/linuxsteamrt64", game / "bin/linux64", game, install, csgo,
            Path.home() / ".local/share/Steam", Path.home() / ".steam/steam")
    result = set()
    for root in dirs:
        folder = root / "steamapps/workshop/content/730" / item
        for path in folder.glob("*.vpk"):
            if not re.search(r"_\d{3}\.vpk$", path.name):
                result.add(path.resolve())
    return sorted(result)


def verify_archive(path, expected):
    entries = vpk_index(path)
    if not expected.keys() <= entries.keys():
        raise ValueError("Downloaded VPK does not contain the expected resources")
    unexpected = set(entries) - expected.keys() - {"addoninfo.txt"}
    if unexpected:
        raise ValueError("Downloaded VPK includes unexpected resources: " + ", ".join(sorted(unexpected)[:8]))
    archives = {path}
    for name, (chunk, offset, size, preload, crc) in entries.items():
        archives.add(chunk)
        digest = hashlib.sha256(preload)
        checksum = zlib.crc32(preload)
        with chunk.open("rb") as stream:
            stream.seek(offset)
            while size:
                block = stream.read(min(size, 1024**2))
                if not block:
                    raise ValueError(f"Truncated Workshop VPK entry: {name}")
                digest.update(block)
                checksum = zlib.crc32(block, checksum)
                size -= len(block)
        if checksum != crc or (name in expected and digest.hexdigest() != expected[name]):
            raise ValueError(f"Workshop content differs from the generated package: {name}")
    return {str(path): file_hash(path) for path in sorted(archives)}


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(csgo, item, override, hashes, console, timeout, already_configured):
    if not already_configured and not override:
        console(f"mm_download_addon {item}")
    deadline = time.monotonic() + (0 if override or already_configured else timeout)
    while True:
        candidates = candidate_vpks(csgo, item, override)
        errors, valid = [], []
        for path in candidates:
            try:
                valid.append((path, verify_archive(path, hashes)))
            except (OSError, ValueError, struct.error) as error:
                errors.append(str(error))
        if len(valid) == 1:
            return valid[0]
        if len(valid) > 1:
            raise ValueError("Multiple matching Workshop caches; select the MAM archive with --vpk")
        if time.monotonic() >= deadline:
            raise ValueError("Workshop download not verified. " + (" | ".join(errors) or
                             "Check visibility/download and use --vpk if MAM has a custom cache path."))
        time.sleep(2)


def merge_settings(before, item, ident, model, expected, vpk, archives):
    config = json.loads(before[1].decode("utf-8-sig"))
    models = config["Models"]
    original = models.get(ident)
    if original is not None and original != model:
        raise ValueError(f"Model ID {ident} already has another configuration")
    for key, entry in models.items():
        if key != ident and (entry["path"].casefold() == model["path"].casefold() or entry["name"] == model["name"]):
            raise ValueError(f"Model path or name conflicts with configured model {key}")
    models[ident] = model
    catalog = json.loads(before[2].decode("utf-8-sig")) if before[2] else {"Archives": {}, "Models": []}
    existing = catalog["Archives"]
    if not isinstance(existing, dict) or not isinstance(catalog["Models"], list):
        raise ValueError("Invalid existing PlayerModelChanger catalog")
    for name, old_hash in existing.items():
        archive = Path(name)
        if name in archives:
            if archives[name].lower() != old_hash.lower():
                raise ValueError("An existing Workshop archive changed; preserve its rollback version first")
            continue
        if not archive.is_absolute() or file_hash(archive).lower() != old_hash.lower():
            raise ValueError(f"Existing catalog archive is missing or changed: {archive}")
        if re.search(r"_\d{3}\.vpk$", archive.name):
            continue
        collision = {key.casefold() for key in vpk_index(archive)} & {key.casefold() for key in expected}
        if collision:
            raise ValueError(f"Resource path overlaps an existing Workshop addon: {min(collision)}")
    catalog["Archives"] = existing | archives
    catalog["Models"] = sorted(set(catalog["Models"]) | {model["path"]})
    mam, present = parse_mam(before[0], item)
    if present and (original != model or str(vpk) not in existing or model["path"] not in json.loads(
            before[2].decode("utf-8-sig"))["Models"]):
        raise ValueError("Workshop ID is already mounted with different settings; use a new Workshop item")
    return (mam, json_bytes(config), json_bytes(catalog)), present, len(models), len(catalog["Models"])


def snapshot(csgo, before, service, item):
    folder = csgo / ".cs2-model-workshop"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise ValueError("Server backup directory must be private and regular")
    backup = Path(tempfile.mkdtemp(prefix=f"{item}-", dir=folder))
    for index, (name, value) in enumerate(zip(FILES, before, strict=True)):
        if value is not None:
            (backup / str(index)).write_bytes(value)
    (backup / "snapshot.json").write_bytes(json_bytes({"service": service, "files": FILES,
                                                       "missing": [i for i, b in enumerate(before) if b is None]}))
    return backup


def write_config(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    metadata = path.stat() if path.exists() else (path.parent / "PlayerModelChanger.dll").stat()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".cs2-workshop-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(stream.fileno(), metadata.st_mode & 0o777)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def restart(service):
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    subprocess.run([*prefix, "systemctl", "restart", service], check=True, timeout=60)


def status(console):
    response = console("pmc_status")
    result = re.search(r"configured=(\d+); verifiedResources=(\d+);.*?resourceError=([^\r\n;]+)", response)
    if not result:
        raise ValueError("Compatible PlayerModelChanger did not respond to pmc_status")
    return int(result[1]), int(result[2]), result[3].strip()


def wait_for_status(console, expected, item, *, mounted, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = status(console)
            paths = console("mm_print_searchpaths")
            if not paths.strip() or "unknown command" in paths.lower():
                raise ValueError("MultiAddonManager search paths unavailable")
            contains_item = bool(re.search(rf"(?<!\d){item}(?!\d)", paths))
            if current == expected and contains_item == mounted:
                return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise ValueError("RCON did not verify the Workshop mount and PlayerModelChanger status")


@contextmanager
def deployment_lock(csgo):
    import fcntl

    folder = csgo / ".cs2-model-workshop"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise ValueError("Server backup directory must be private and regular")
    with (folder / "deploy.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def deploy_on_server(options):
    item, ident, model, hashes = (options[k] for k in ("item", "ident", "model", "hashes"))
    csgo, service = installation(options["csgo"], options["service"])
    password = password_for(csgo, options["rcon_password_file"])

    def console(command):
        return rcon(options["rcon_port"], password, command)

    with deployment_lock(csgo):
        before = read_settings(csgo)
        _, already = parse_mam(before[0], item)
        baseline = status(console)
        search_paths = console("mm_print_searchpaths")
        if not search_paths.strip() or "unknown command" in search_paths.lower():
            raise ValueError("Compatible MultiAddonManager did not respond to mm_print_searchpaths")
        if baseline[2] != "none" and (before[2] is not None or baseline[0] != 0):
            raise ValueError("Existing PlayerModelChanger resource status is unhealthy")
        vpk, archives = download(csgo, item, options["vpk"], hashes, console, options["timeout"], already)
        updated, present, count, verified = merge_settings(before, item, ident, model, hashes, vpk, archives)
        if present:
            wait_for_status(console, (count, verified, "none"), item, mounted=True, timeout=10)
            print(f"Already deployed and verified: !model {ident} (Workshop {item})")
            return
        if read_settings(csgo) != before:
            raise ValueError("Server configuration changed during download; rerun deployment")
        subprocess.run(["systemctl", "is-active", "--quiet", service], check=True, timeout=10)
        backup = snapshot(csgo, before, service, item)
        print(f"Rollback snapshot on server: {backup}", flush=True)
        changed = []
        try:
            for name, old, new in zip(FILES, before, updated, strict=True):
                if old != new:
                    write_config(csgo / name, new)
                    changed.append((name, old))
            restart(service)
            wait_for_status(console, (count, verified, "none"), item, mounted=True)
            if any(file_hash(Path(path)) != digest for path, digest in archives.items()):
                raise ValueError("Downloaded Workshop archive changed after restart")
        except BaseException:
            try:
                for name, value in reversed(changed):
                    write_config(csgo / name, value)
                if changed:
                    restart(service)
                    wait_for_status(console, baseline, item, mounted=False)
            except Exception as error:
                raise ValueError(f"Rollback could not be verified. Snapshot: {backup}") from error
            if changed:
                print("Previous configuration and server status restored.", file=sys.stderr)
            raise
    print(f"Server verified: Workshop {item}, !model {ident}. Client gameplay check remains manual.")


def remote_main(options):
    try:
        deploy_on_server(options)
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.SubprocessError) as error:
        print(f"Deployment blocked: {error}", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="Generated package/ directory")
    parser.add_argument("workshop", help="Published Workshop URL or ID")
    parser.add_argument("--server", required=True, help="SSH alias or user@host")
    parser.add_argument("--ssh-port", type=int)
    parser.add_argument("--csgo", help="Remote game/csgo path")
    parser.add_argument("--service", help="Remote systemd unit")
    parser.add_argument("--rcon-port", type=int, default=27015)
    parser.add_argument("--rcon-password-file", help="Remote password file, never the password itself")
    parser.add_argument("--vpk", help="Remote MAM cache VPK path for nonstandard layouts")
    parser.add_argument("--timeout", type=int, default=180, help="Workshop download timeout in seconds")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9_.@:\[\]-]+", args.server) or args.server.startswith("-"):
            raise ValueError("Invalid SSH destination")
        for port in (args.ssh_port, args.rcon_port):
            if port is not None and not 1 <= port <= 65535:
                raise ValueError("Invalid TCP port")
        if not 1 <= args.timeout <= 3600:
            raise ValueError("Invalid Workshop download timeout")
        item = workshop_id(args.workshop)
        ident, model, hashes = package_data(args.package)
        options = vars(args) | {"item": item, "ident": ident, "model": model, "hashes": hashes}
        # Stream code and the manifest over SSH stdin. The remote RCON password stays on the server.
        bootstrap = ('import json, sys, types; payload=json.load(sys.stdin); '
                     'archives=types.ModuleType("archives"); sys.modules["archives"]=archives; '
                     'exec(payload["archives"], archives.__dict__); '
                     'scope={"__name__":"remote_deploy"}; exec(payload["deploy"], scope); '
                     'sys.exit(scope["remote_main"](payload["options"]))')
        script = Path(__file__).resolve()
        payload = {"deploy": script.read_text(encoding="utf-8"),
                   "archives": script.with_name("archives.py").read_text(encoding="utf-8"),
                   "options": options}
        ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if args.ssh_port:
            ssh.extend(["-p", str(args.ssh_port)])
        result = subprocess.run([*ssh, args.server, "python3 -c " + shlex.quote(bootstrap)],
                                input=json_bytes(payload))
        return result.returncode
    except (OSError, ValueError, KeyError) as error:
        print(f"Deployment blocked: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
