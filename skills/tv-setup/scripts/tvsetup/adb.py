import re
import shlex
from .common import SetupError, resolve_adb, run, validate_serial


class Adb:
    def __init__(self, serial, executable=None):
        self.serial = validate_serial(serial)
        self.executable = resolve_adb(executable)

    def call(self, *args, **kwargs):
        return run([self.executable, "-s", self.serial, *args], **kwargs)

    def shell(self, *args, **kwargs):
        # adb shell ultimately invokes a remote shell, even with argv supplied.
        return self.call("shell", shlex.join([str(x) for x in args]), **kwargs)

    def connect(self):
        if ":" in self.serial:
            result = run([self.executable, "connect", self.serial], timeout=12, check=False)
            if result.returncode:
                raise SetupError("TV ADB is unreachable: check power, current IP and the computer-to-TV LAN path")
        result = self.call("get-state", check=False)
        if result.returncode or result.stdout.strip() != "device":
            raise SetupError("ADB is offline or not authorized: keep TV on, use its current address and allow its debugging prompt")

    def property(self, key):
        return self.shell("getprop", key).stdout.strip()

    def package_path(self, package):
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.]+", package):
            raise SetupError("Invalid package name")
        return self.shell("pm", "path", package, check=False).stdout.strip()

    def inspect(self):
        self.connect()
        keys = ["ro.product.manufacturer", "ro.product.model", "ro.product.device",
                "ro.build.fingerprint", "ro.build.version.sdk", "ro.build.version.release",
                "ro.build.version.security_patch", "ro.product.cpu.abilist"]
        data = {key: self.property(key) for key in keys}
        packages = {}
        for package in ["com.gathin.tvhome", "com.google.android.youtube.tv", "app.smarttube.fdroid"]:
            path = self.package_path(package)
            version = None
            if path:
                raw = self.shell("dumpsys", "package", package).stdout
                match = re.search(r"versionName=(\S+)", raw)
                version = match.group(1) if match else None
            packages[package] = {"installed": bool(path), "version": version}
        home = self.shell("cmd", "package", "resolve-activity", "--brief", "-a",
                          "android.intent.action.MAIN", "-c", "android.intent.category.HOME").stdout
        data.update(serial=self.serial, packages=packages,
                    home=next((x.strip() for x in home.splitlines() if "/" in x), None),
                    http_proxy_configured=self.shell("settings", "get", "global", "http_proxy").stdout.strip() not in ("", "null", ":0"))
        return data
