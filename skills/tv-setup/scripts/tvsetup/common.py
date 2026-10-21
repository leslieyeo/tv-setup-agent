from pathlib import Path
import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


class SetupError(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise SetupError("Refusing a symlink output")
    if not isinstance(data, (bytes, str)):
        data = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd, temp = tempfile.mkstemp(prefix=".tvsetup-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run(args, timeout=25, check=True, input=None, binary=False):
    result = subprocess.run([str(x) for x in args], input=input, capture_output=True,
                            text=not binary, timeout=timeout)
    if check and result.returncode:
        # Do not echo argv, stdin or a remote traceback: they may contain secrets.
        raise SetupError("Command failed (%s, exit %s)" % (Path(str(args[0])).name, result.returncode))
    return result


def private_host(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise SetupError("Use a literal private LAN address")
    if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
        raise SetupError("Only a private LAN target is accepted")
    return str(address)


def validate_serial(serial):
    if not serial or not re.fullmatch(r"[A-Za-z0-9_.:%-]{1,160}", serial):
        raise SetupError("Invalid ADB serial")
    if ":" in serial:
        host, port = serial.rsplit(":", 1)
        private_host(host)
        if port != "5555":
            raise SetupError("This release supports authorized legacy ADB port 5555; pair other transports separately")
    return serial


def resolve_adb(explicit=None):
    candidate = explicit or shutil.which("adb")
    if not candidate or not Path(candidate).is_file():
        raise SetupError("ADB missing: install Google's platform-tools, then provide --adb /path/to/adb")
    return str(Path(candidate).resolve())


def network_snapshot():
    system = platform.system()
    if system == "Darwin":
        result = run(["/sbin/route", "-n", "get", "default"], check=False, timeout=8)
        found = dict(re.findall(r"^\s*(gateway|interface):\s*(\S+)", result.stdout, re.M))
        return {"platform": system, "gateway": found.get("gateway"), "interface": found.get("interface")}
    if system == "Linux" and shutil.which("ip"):
        result = run(["ip", "-j", "route", "show", "default"], check=False, timeout=8)
        try:
            routes = json.loads(result.stdout)
            route = min(routes, key=lambda r: r.get("metric", 0)) if routes else {}
            return {"platform": system, "gateway": route.get("gateway"), "interface": route.get("dev")}
        except ValueError:
            pass
    return {"platform": system, "gateway": None, "interface": None, "supported": False}


def assert_network_unchanged(before, after=None):
    after = network_snapshot() if after is None else after
    if not before.get("gateway") or not before.get("interface"):
        raise SetupError("Default route unavailable; router writes are not safe to automate")
    if any(before.get(key) != after.get(key) for key in ("gateway", "interface")):
        raise SetupError("Computer default route changed: stop writes and inspect the active uplink")


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
