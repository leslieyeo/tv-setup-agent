import base64
import copy
import json
import secrets
import time
from pathlib import Path
from .common import ROOT, SetupError, now, private_write, read_json
from .artifacts import get_artifact
from .profiles import tv_profile


def temporary_policy(original, package, launcher=False):
    """Change just the reviewed strategies, preserving unknown fields verbatim on restore."""
    if len(original.encode()) > 32768:
        raise SetupError("OEM policy exceeds the reviewed size limit")
    data = json.loads(original)
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0].get("strategies"), list):
        raise SetupError("Unexpected OEM policy format")
    temporary = copy.deepcopy(data)
    matches = {"pmStrategy": 0, "launcherStrategy": 0}
    for item in temporary[0]["strategies"]:
        name = item.get("name")
        if name == "pmStrategy":
            matches[name] += 1
            if item.get("enable") not in ("true", "false"):
                raise SetupError("Unexpected pmStrategy state")
            item["enable"] = "false"
        if launcher and name == "launcherStrategy":
            matches[name] += 1
            allowed = item.setdefault("packages", [])
            if not isinstance(allowed, list):
                raise SetupError("Unexpected launcher allowlist")
            if package not in allowed:
                allowed.append(package)
    if matches["pmStrategy"] != 1 or (launcher and matches["launcherStrategy"] != 1):
        raise SetupError("Reviewed OEM strategies missing or duplicated")
    return json.dumps(temporary, ensure_ascii=False, separators=(",", ":"))


class PolicySession:
    def __init__(self, adb, journal, remote):
        self.adb, self.journal, self.remote = adb, Path(journal), remote

    def tool(self, *args):
        return self.adb.shell("env", "CLASSPATH=" + self.remote, "app_process", "/system/bin",
                              "TvInstallConfigTool", *args).stdout

    def read(self):
        rows = [x[7:] for x in self.tool("read").splitlines() if x.startswith("POLICY=")]
        if len(rows) != 1:
            raise SetupError("Could not read one OEM policy")
        json.loads(rows[0])
        return rows[0]

    def write(self, value):
        if "UPDATED=1" not in self.tool("write", base64.b64encode(value.encode()).decode()):
            raise SetupError("OEM policy update failed")
        if self.read() != value:
            raise SetupError("OEM policy read-back differs")

    def install(self, apk, package, fingerprint, launcher=False):
        if self.adb.property("ro.build.fingerprint") != fingerprint:
            raise SetupError("Firmware changed before OEM write")
        if self.adb.shell("test", "-e", self.remote, check=False).returncode == 0:
            raise SetupError("Temporary helper path is already in use; preserve the existing file")
        helper = get_artifact("oem-policy", self.journal.parent / "cache")
        self.adb.call("push", str(helper), self.remote)
        original = None
        restored = False
        armed = False
        state = {"package": package, "fingerprint": fingerprint, "serial": self.adb.serial,
                 "remote": self.remote, "phase": "reading", "created_at": now()}
        try:
            original = self.read()
            patched = temporary_policy(original, package, launcher)
            state.update(original_policy=original, phase="armed")
            private_write(self.journal, state)
            armed = True
            try:
                self.write(patched)
                state["phase"] = "installing"
                private_write(self.journal, state)
                result = self.adb.call("install", "--streaming", str(apk), timeout=180, check=False)
                state["install_exit"] = result.returncode
                if result.returncode or "Success" not in result.stdout:
                    raise SetupError("TV rejected the APK; policy restoration will still run")
                state["installed"] = True
            finally:
                # Keep journal and helper if restoration fails, so recovery remains possible.
                self.write(original)
                restored = True
                state.update(phase="restored", policy_restored=True)
        finally:
            if not armed or restored:
                self.adb.shell("rm", "-f", self.remote)
                state["helper_removed"] = self.adb.shell("test", "-e", self.remote, check=False).returncode == 1
            private_write(self.journal, state)


def install_tv(adb, artifact, state_dir, set_home=False):
    state_dir = Path(state_dir)
    if artifact not in ("launcher-tcl", "smarttube-fdroid"):
        raise SetupError("Unapproved application artifact")
    device = adb.inspect()
    profile = tv_profile(device)
    entry = read_json(ROOT / "assets/artifacts.json")[artifact]
    package = entry["package"]
    if artifact == "launcher-tcl" and not profile:
        raise SetupError("This launcher build is verified only for the exact TCL profile; use adapter research")
    if int(device["ro.build.version.sdk"] or 0) < entry["min_sdk"]:
        raise SetupError("TV Android version is below this artifact's minimum")
    if set_home and artifact != "launcher-tcl":
        raise SetupError("Only the launcher can become HOME")
    report = {"package": package, "artifact": artifact, "already_installed": bool(adb.package_path(package)),
              "installed": False, "home_changed": False, "created_at": now()}
    if not report["already_installed"]:
        apk = get_artifact(artifact, state_dir / "cache")
        # Try the normal package manager first. An unknown model never gets an OEM write.
        result = adb.call("install", "--streaming", str(apk), check=False, timeout=180)
        if result.returncode or "Success" not in result.stdout:
            restriction = "INSTALL_FAILED_VERIFICATION_FAILURE" in (result.stdout + result.stderr)
            if not profile or not restriction:
                raise SetupError("Normal installation failed; no reviewed OEM fallback applies. Inspect the device and create an adapter")
            session = PolicySession(adb, state_dir / ("policy-" + package + ".json"),
                                    "/data/local/tmp/tvsetup-" + secrets.token_hex(6) + ".jar")
            session.install(apk, package, device["ro.build.fingerprint"], artifact == "launcher-tcl")
        if not adb.package_path(package):
            raise SetupError("Installed package not found")
        report["installed"] = True
    if set_home and device["home"] != "com.gathin.tvhome/.MainActivity":
        # Capture the actual previous HOME; no package or account data is removed on rollback.
        if not device["home"]:
            raise SetupError("No original HOME could be resolved; choose the default launcher interactively")
        if (state_dir / "home-before.json").exists():
            raise SetupError("An earlier HOME recovery record exists; preserve it and use a fresh state directory")
        private_write(state_dir / "home-before.json", {"serial": adb.serial,
                      "fingerprint": device["ro.build.fingerprint"], "home": device["home"]})
        result = adb.shell("cmd", "package", "set-home-activity", "com.gathin.tvhome/.MainActivity", check=False)
        if result.returncode:
            raise SetupError("HOME change failed; installed apps are retained")
        actual = adb.shell("cmd", "package", "resolve-activity", "--brief", "-a",
                           "android.intent.action.MAIN", "-c", "android.intent.category.HOME").stdout
        if "com.gathin.tvhome/.MainActivity" not in actual:
            raise SetupError("Default HOME verification failed")
        report["home_changed"] = True
    private_write(state_dir / ("install-" + package + ".json"), report)
    return report


def restore_home(adb, journal):
    import re
    state = read_json(journal)
    device = adb.inspect()
    if state.get("serial") != adb.serial or state.get("fingerprint") != device["ro.build.fingerprint"]:
        raise SetupError("HOME recovery record belongs to another device or firmware")
    original = state.get("home", "")
    if not re.fullmatch(r"[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+", original):
        raise SetupError("Original HOME component was not captured correctly")
    if device["home"] == original:
        return {"home_already_restored": True}
    if device["home"] != "com.gathin.tvhome/.MainActivity":
        raise SetupError("The viewer changed HOME since installation; preserve that choice")
    adb.shell("cmd", "package", "set-home-activity", original)
    actual = adb.inspect()["home"]
    if actual != original:
        raise SetupError("Original HOME verification failed")
    return {"home_restored": True, "applications_removed": False}


def restore_policy(adb, journal):
    state = read_json(journal)
    if state.get("serial") != adb.serial or adb.property("ro.build.fingerprint") != state["fingerprint"]:
        raise SetupError("Recovery journal belongs to another device or firmware")
    if state.get("phase") == "restored":
        return {"already_restored": True}
    if "original_policy" not in state:
        raise SetupError("No original policy was saved; do not guess it")
    import re
    if not re.fullmatch(r"/data/local/tmp/tvsetup-[0-9a-f]{12}\.jar", state.get("remote", "")):
        raise SetupError("Recovery helper is outside this installer's owned path format")
    session = PolicySession(adb, journal, state["remote"])
    helper = get_artifact("oem-policy", Path(journal).parent / "cache")
    if adb.shell("test", "-e", session.remote, check=False).returncode == 0:
        from .common import digest
        recorded = adb.shell("sha256sum", session.remote).stdout.split()
        if not recorded or recorded[0] != digest(helper):
            raise SetupError("Existing recovery helper differs; do not overwrite or execute it")
    else:
        adb.call("push", str(helper), session.remote)
    session.write(state["original_policy"])
    state.update(phase="restored", policy_restored=True, restored_at=now())
    private_write(journal, state)
    adb.shell("rm", "-f", session.remote)
    return {"policy_restored": True}


def playback_probe(adb, state_dir, seconds=8):
    if not adb.package_path("app.smarttube.fdroid"):
        raise SetupError("SmartTube F-Droid is not installed")
    adb.shell("input", "keyevent", "KEYCODE_WAKEUP")
    adb.shell("am", "start", "-W", "-a", "android.intent.action.VIEW", "-d",
              "https://www.youtube.com/watch?v=aqz-KE-bpKQ", "-p", "app.smarttube.fdroid")
    samples = []
    import re
    for _ in range(3):
        time.sleep(seconds)
        raw = adb.shell("dumpsys", "media_session").stdout
        match = re.search(r"package=app.smarttube.fdroid[\s\S]*?state=PlaybackState \{state=(\d+), position=(\d+), buffered position=(\d+)", raw)
        samples.append({"state": int(match[1]) if match else None,
                        "position_ms": int(match[2]) if match else None})
    moving = len([x for x in samples if x["position_ms"] is not None]) == 3 and samples[-1]["position_ms"] > samples[0]["position_ms"]
    report = {"samples": samples, "progress_observed": moving, "picture_and_sound_confirmed": False,
              "next": "Ask the viewer to confirm picture, sound and remote control; black ADB screenshots alone do not prove display failure"}
    private_write(Path(state_dir) / "playback.json", report)
    return report
