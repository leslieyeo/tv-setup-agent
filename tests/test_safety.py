from pathlib import Path
from types import SimpleNamespace
import base64
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/tv-setup/scripts"))
from tvsetup.common import SetupError, assert_network_unchanged, private_host, private_write, read_json, digest
from tvsetup.profiles import tv_profile
from tvsetup.tv import PolicySession, temporary_policy, restore_policy, install_tv
from tvsetup.plan import make_plan
from tvsetup.router import build_bundle, render_wireless
from tvsetup.artifacts import get_artifact

FINGERPRINT = read_json(ROOT / "skills/tv-setup/profiles/tv.json")[0]["match"]["ro.build.fingerprint"]
ORIGINAL = '[ {"strategies": [{"name":"pmStrategy", "enable":"true"}, {"name":"launcherStrategy","packages":[]}, {"name":"other","value":42}]} ]'


class FakeAdb:
    serial = "192.168.100.40:5555"

    def __init__(self, mode="success", known=True):
        self.policy, self.mode, self.helper = ORIGINAL, mode, False
        self.writes = []
        self.known = known
        self.fail_restore = mode == "restore-fails"
        self.tool_calls = 0

    def property(self, key):
        return FINGERPRINT if self.known else "OTHER/vendor/device:12/unknown:user/release-keys"

    def inspect(self):
        return {"ro.build.fingerprint": self.property(""), "ro.build.version.sdk": "30",
                "home": "com.gathin.tvhome/.MainActivity" if self.mode == "already-home" else "vendor.home/.Main"}

    def package_path(self, package):
        return "package:/data/app/existing/base.apk" if self.mode == "already-home" else ""

    def call(self, *args, **kwargs):
        if args[0] == "push":
            self.helper = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[0] == "install":
            if self.mode == "cancelled":
                return SimpleNamespace(returncode=1, stdout="", stderr="INSTALL_CANCELED_BY_USER")
            if self.mode == "timeout":
                raise subprocess.TimeoutExpired("adb", 180)
            if self.mode in ("rejected", "normal-blocked"):
                return SimpleNamespace(returncode=1, stdout="", stderr="INSTALL_FAILED_VERIFICATION_FAILURE")
            return SimpleNamespace(returncode=0, stdout="Success\n", stderr="")
        raise AssertionError(args)

    def shell(self, *args, **kwargs):
        if "TvInstallConfigTool" in args:
            self.tool_calls += 1
            index = args.index("TvInstallConfigTool")
            if args[index + 1] == "read":
                return SimpleNamespace(returncode=0, stdout="POLICY=" + self.policy + "\n")
            value = base64.b64decode(args[index + 2]).decode()
            if value == ORIGINAL and self.fail_restore:
                raise SetupError("simulated disconnect during restoration")
            self.policy = value
            self.writes.append(value)
            return SimpleNamespace(returncode=0, stdout="UPDATED=1\n")
        if args[0] == "rm":
            self.helper = False
            return SimpleNamespace(returncode=0, stdout="")
        if args[0] == "test":
            return SimpleNamespace(returncode=0 if self.helper else 1, stdout="")
        if args[0] == "sha256sum":
            return SimpleNamespace(returncode=0, stdout=digest(ROOT / "skills/tv-setup/assets/oem-policy.jar") + "  " + args[1])
        raise AssertionError(args)


def router_inventory():
    return {"computer": {"platform": "Darwin", "gateway": "192.168.200.1", "interface": "en0"},
            "router": {"host": "192.168.100.1", "lan_ip": "192.168.100.1", "authenticated_probe": True,
                       "productid": "RT-AC68U", "buildno": "386", "extendno": "14_2",
                       "kernel": "2.6.36.4brcmarm", "arch": "armv7l", "existing_proxy": "no",
                       "sw_mode": "1", "lan_iface": "br0", "jffs_scripts": "0", "existing_hooks": "0",
                       "ram_kb": "250000", "jffs_free_kb": "50000", "tmp_free_kb": "100000"}}


class TransactionTests(unittest.TestCase):
    def test_existing_helper_is_not_overwritten(self):
        adb = FakeAdb()
        adb.helper = True
        with self.assertRaises(SetupError):
            PolicySession(adb, Path("unused.json"), "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "app.smarttube.fdroid", FINGERPRINT)
        self.assertTrue(adb.helper)
        self.assertEqual(adb.writes, [])

    def test_user_cancellation_is_not_treated_as_oem_policy_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb("cancelled")
            with patch("tvsetup.tv.get_artifact", return_value=Path("fake.apk")):
                with self.assertRaises(SetupError):
                    install_tv(adb, "smarttube-fdroid", temp)
            self.assertEqual(adb.tool_calls, 0)

    def test_idempotent_home_install_preserves_the_original_recovery_record(self):
        with tempfile.TemporaryDirectory() as temp:
            original = {"home": "vendor.original/.Home", "marker": "preserve"}
            private_write(Path(temp) / "home-before.json", original)
            report = install_tv(FakeAdb("already-home"), "launcher-tcl", temp, set_home=True)
            self.assertTrue(report["already_installed"])
            self.assertEqual(read_json(Path(temp) / "home-before.json"), original)

    def test_success_restores_original_text_and_removes_helper(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb()
            PolicySession(adb, Path(temp) / "journal.json", "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "com.gathin.tvhome", FINGERPRINT, True)
            self.assertEqual(adb.policy, ORIGINAL)
            self.assertFalse(adb.helper)
            self.assertTrue(read_json(Path(temp) / "journal.json")["policy_restored"])
            patched = json.loads(adb.writes[0])[0]["strategies"]
            self.assertEqual(patched[2], {"name": "other", "value": 42})

    def test_install_rejection_also_restores(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb("rejected")
            with self.assertRaises(SetupError):
                PolicySession(adb, Path(temp) / "journal.json", "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "app.smarttube.fdroid", FINGERPRINT)
            self.assertEqual(adb.policy, ORIGINAL)
            self.assertFalse(adb.helper)

    def test_install_timeout_also_restores(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb("timeout")
            with self.assertRaises(subprocess.TimeoutExpired):
                PolicySession(adb, Path(temp) / "journal.json", "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "app.smarttube.fdroid", FINGERPRINT)
            self.assertEqual(adb.policy, ORIGINAL)
            self.assertFalse(adb.helper)

    def test_failed_restore_preserves_journal_and_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb("restore-fails")
            journal = Path(temp) / "journal.json"
            with self.assertRaises(SetupError):
                PolicySession(adb, journal, "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "app.smarttube.fdroid", FINGERPRINT)
            self.assertTrue(adb.helper)
            self.assertEqual(read_json(journal)["original_policy"], ORIGINAL)
            adb.fail_restore = False
            restore_policy(adb, journal)
            self.assertEqual(adb.policy, ORIGINAL)
            self.assertFalse(adb.helper)

    def test_malformed_policy_never_written_and_helper_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb()
            adb.policy = '[{"strategies": []}]'
            with self.assertRaises(SetupError):
                PolicySession(adb, Path(temp) / "journal.json", "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "app.smarttube.fdroid", FINGERPRINT)
            self.assertEqual(adb.writes, [])
            self.assertFalse(adb.helper)

    def test_firmware_drift_prevents_helper_and_writes(self):
        adb = FakeAdb(known=False)
        with self.assertRaises(SetupError):
            PolicySession(adb, Path("unused.json"), "/data/local/tmp/tvsetup-000000000001.jar").install("fake.apk", "app.smarttube.fdroid", FINGERPRINT)
        self.assertEqual(adb.writes, [])
        self.assertFalse(adb.helper)

    def test_unknown_model_install_failure_never_calls_private_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            adb = FakeAdb("normal-blocked", known=False)
            with patch("tvsetup.tv.get_artifact", return_value=Path("fake.apk")):
                with self.assertRaises(SetupError):
                    install_tv(adb, "smarttube-fdroid", temp)
            self.assertEqual(adb.tool_calls, 0)

    def test_policy_duplicate_strategy_rejected(self):
        data = json.loads(ORIGINAL)
        data[0]["strategies"].append({"name": "pmStrategy", "enable": "true"})
        with self.assertRaises(SetupError):
            temporary_policy(json.dumps(data), "app.smarttube.fdroid")


class GuardAndArtifactTests(unittest.TestCase):
    def test_network_drift_stops_writes(self):
        before = {"gateway": "192.168.200.1", "interface": "en0"}
        assert_network_unchanged(before, dict(before))
        with self.assertRaises(SetupError):
            assert_network_unchanged(before, {"gateway": "192.168.100.1", "interface": "en7"})

    def test_public_or_loopback_targets_rejected(self):
        for value in ("8.8.8.8", "127.0.0.1", "0.0.0.0", "host.invalid"):
            with self.assertRaises(SetupError):
                private_host(value)

    def test_private_state_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "state/report.json"
            private_write(file, {"safe": True})
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_bad_download_digest_leaves_no_artifact(self):
        class Response(io.BytesIO):
            def geturl(self):
                return "https://example.invalid/file"
        with tempfile.TemporaryDirectory() as temp:
            entry = {"test": {"url": "https://example.invalid/file", "filename": "file.apk", "max_bytes": 100, "sha256": "0" * 64}}
            with patch("tvsetup.artifacts.catalog", return_value=entry), patch("urllib.request.urlopen", return_value=Response(b"changed")):
                with self.assertRaises(SetupError):
                    get_artifact("test", temp)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_known_brand_with_different_firmware_is_not_a_match(self):
        self.assertIsNone(tv_profile({"ro.build.fingerprint": FINGERPRINT + "-different", "ro.build.version.sdk": "30"}))

    def test_research_draft_is_not_an_executable_adapter(self):
        with patch("tvsetup.profiles.read_json", return_value=[{"match": {"ro.build.fingerprint": FINGERPRINT}, "method": "draft-only"}]):
            self.assertIsNone(tv_profile({"ro.build.fingerprint": FINGERPRINT}))

    def test_plan_preserves_existing_proxy(self):
        inventory = router_inventory()
        inventory["router"]["existing_proxy"] = "yes"
        step = next(x for x in make_plan(inventory)["steps"] if x["step"] == "router-split-routing")
        self.assertEqual(step["mode"], "verify-existing")

    def test_plan_blocks_single_computer_uplink(self):
        inventory = router_inventory()
        inventory["computer"]["gateway"] = inventory["router"]["host"]
        step = next(x for x in make_plan(inventory)["steps"] if x["step"] == "router-split-routing")
        self.assertEqual(step["mode"], "needs-independent-uplink")


class RouterBundleTests(unittest.TestCase):
    def test_wrong_kernel_and_existing_hooks_do_not_fetch_or_render(self):
        with tempfile.TemporaryDirectory() as temp:
            for field, value in (("kernel", "unknown-new-kernel"), ("existing_hooks", "2")):
                inv = router_inventory()
                inv["router"][field] = value
                with patch("tvsetup.router.get_artifact") as fetch:
                    with self.assertRaises(SetupError):
                        build_bundle(inv, "unused", "unused", temp, Path(temp) / "out")
                    fetch.assert_not_called()

    def test_rendered_bundle_is_private_parameterized_and_shell_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            artifact = temp / "public-artifact"
            artifact.write_bytes(b"fixture-public-artifact")
            provider = temp / "authorized-provider.yaml"
            provider.write_text('proxies:\n- name: fixture-node\n  type: socks5\n  server: example.invalid\n  port: 1080\n')
            output = temp / "bundle"
            with patch("tvsetup.router.get_artifact", return_value=artifact):
                result = build_bundle(router_inventory(), provider, "fixture-node", temp, output)
            self.assertFalse(result["deployed"])
            config = read_json(output / "config.json")
            self.assertEqual(config["bind-address"], "192.168.100.1")
            self.assertEqual(config["proxy-providers"]["AUTHORIZED"]["type"], "file")
            self.assertEqual((output / "config.json").stat().st_mode & 0o777, 0o600)
            runtime = (output / "service.sh").read_text()
            self.assertIn("192.168.100.0/24", runtime)
            self.assertNotIn("192.168.50.1", runtime)
            self.assertNotIn("tvsetup-owner-template", runtime)
            self.assertIn("ROLLBACK_ARMED", (output / "activate-lan.sh").read_text())
            for script in output.glob("*.sh"):
                subprocess.run(["sh", "-n", str(script)], check=True, capture_output=True)

    def test_wireless_keeps_original_values_and_never_stores_plaintext_password(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            bundle = temp / "bundle"
            bundle.mkdir()
            private_write(bundle / "bundle-manifest.json", {"target_profile": "asus-rt-ac68u-merlin-386-14-2", "target_lan": "192.168.100.1", "owner": "fixture-owned"})
            keys = ["wan_ifname", "wan_ifnames", "wan0_ifname", "wan0_gw_ifname", "wan_iface", "wan0_hwaddr_x", "wan_hwaddr_x", "wan0_hwaddr", "lan_ifnames", "wanduck_down", "nat_redirect_enable", "ntp_server0", "ntp_server1"]
            values = {k: "" for k in keys}
            values.update(wan_ifname="eth0", lan_ifnames="vlan1 eth1 eth2")
            snapshot = temp / "snapshot.json"
            private_write(snapshot, {"lan_ip": "192.168.100.1", "wan_radio": "eth2", "radio_mac": "02:00:00:00:00:01", "nvram_before": values})
            secret = temp / "wifi.json"
            password = "fixture-only-password-1234"
            ssid = "guest'; touch X; #"
            private_write(secret, {"ssid": ssid, "password": password})
            render_wireless(bundle, snapshot, secret)
            target = bundle / "wireless-reference"
            for file in target.iterdir():
                self.assertNotIn(password, file.read_text())
            for file in target.glob("*.sh"):
                subprocess.run(["sh", "-n", str(file)], check=True, capture_output=True)
            check = subprocess.run(["sh", "-c", '. "$1"; printf "%s" "$WIFI_SSID"', "sh", str(target / "uplink.conf")], cwd=temp, capture_output=True, text=True, check=True)
            self.assertEqual(check.stdout, ssid)
            self.assertFalse((temp / "X").exists())
            self.assertEqual(read_json(target / "nvram-before.json"), values)


class InstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, str(ROOT / "scripts/build_release.py")], check=True, capture_output=True)
        spec = importlib.util.spec_from_file_location("toolkit_installer", ROOT / "install.py")
        cls.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.installer)

    def test_both_agents_use_one_source_and_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.installer.install(temp, "both")
            second = self.installer.install(temp, "both")
            left = Path(temp) / ".agents/skills/tv-setup"
            right = Path(temp) / ".claude/skills/tv-setup"
            self.assertEqual(left.resolve(), right.resolve())
            self.assertEqual(result["toolkit"], second["toolkit"])
            call = subprocess.run([sys.executable, str(left / "scripts/tvsetup.py"), "check-package"], capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(call.stdout)["package_valid"])

    def test_existing_skill_is_preserved_without_partial_toolkit(self):
        with tempfile.TemporaryDirectory() as temp:
            existing = Path(temp) / ".agents/skills/tv-setup"
            existing.mkdir(parents=True)
            (existing / "SKILL.md").write_text("owner's existing skill")
            with self.assertRaises(ValueError):
                self.installer.install(temp, "codex")
            self.assertEqual((existing / "SKILL.md").read_text(), "owner's existing skill")
            self.assertFalse((Path(temp) / ".tvsetup/toolkit").exists())

    def test_reinstall_reports_and_preserves_locally_modified_toolkit(self):
        with tempfile.TemporaryDirectory() as temp:
            self.installer.install(temp, "generic")
            file = Path(temp) / ".tvsetup/toolkit/tvsetup.py"
            file.write_text("# deliberate local modification\n")
            with self.assertRaises(ValueError):
                self.installer.install(temp, "generic")
            self.assertEqual(file.read_text(), "# deliberate local modification\n")

    def test_skill_works_when_copied_without_repository_siblings(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "tv-setup"
            shutil.copytree(ROOT / "skills/tv-setup", target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            call = subprocess.run([sys.executable, str(target / "scripts/tvsetup.py"), "check-package"], capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(call.stdout)["package_valid"])


if __name__ == "__main__":
    unittest.main()
