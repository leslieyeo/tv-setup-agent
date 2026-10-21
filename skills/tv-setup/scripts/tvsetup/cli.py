import argparse
import json
import sys
import subprocess
from pathlib import Path
from . import __version__
from .adb import Adb
from .artifacts import get_artifact
from .common import ROOT, SetupError, private_write, read_json, assert_network_unchanged, private_host
from .discovery import doctor, wireless_snapshot
from .plan import make_plan
from .tv import install_tv, playback_probe, restore_policy, restore_home


def main(argv=None):
    parser = argparse.ArgumentParser(description="TV Setup Agent：设备识别、受控安装、路由适配及播放验收")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="Read-only computer, TV and optional router inventory")
    p.add_argument("--tv", help="Authorized private-IP:5555 or USB ADB serial")
    p.add_argument("--adb")
    p.add_argument("--router")
    p.add_argument("--ssh-key")
    p.add_argument("--known-hosts")
    p.add_argument("--ssh-user", default="admin")
    p.add_argument("--out", default=".tvsetup/state/inventory.json")
    p = sub.add_parser("plan", help="Generate a staged plan; no device writes")
    p.add_argument("--inventory", required=True)
    p.add_argument("--out", default=".tvsetup/state/plan.json")
    p = sub.add_parser("tv-install", help="Install an explicitly selected pinned application")
    p.add_argument("artifact", choices=["launcher-tcl", "smarttube-fdroid"])
    p.add_argument("--tv", required=True)
    p.add_argument("--adb")
    p.add_argument("--set-home", action="store_true")
    p.add_argument("--state", default=".tvsetup/state")
    p = sub.add_parser("recover-policy", help="Recover this exact TV's saved OEM installation policy")
    p.add_argument("--tv", required=True)
    p.add_argument("--adb")
    p.add_argument("--journal", required=True)
    p = sub.add_parser("restore-home", help="Restore this exact TV's saved original launcher without uninstalling applications")
    p.add_argument("--tv", required=True)
    p.add_argument("--adb")
    p.add_argument("--journal", required=True)
    p = sub.add_parser("playback-test", help="Start the public Blender sample and observe playback progress")
    p.add_argument("--tv", required=True)
    p.add_argument("--adb")
    p.add_argument("--state", default=".tvsetup/state")
    p = sub.add_parser("fetch", help="Download a hash-pinned upstream artifact")
    p.add_argument("artifact")
    p.add_argument("--cache", default=".tvsetup/cache")
    p = sub.add_parser("asus-bundle", help="Render a private staged ASUS wired-routing bundle; never deploy implicitly")
    p.add_argument("--inventory", required=True)
    p.add_argument("--provider-file", required=True, help="Explicitly authorized local Clash provider YAML/JSON")
    p.add_argument("--selected-node", required=True)
    p.add_argument("--cache", default=".tvsetup/cache")
    p.add_argument("--out", required=True)
    p = sub.add_parser("asus-wireless-render", help="Prepare the exact eth2 station reference plus original NVRAM recovery; no deployment")
    p.add_argument("--bundle", required=True)
    p.add_argument("--nvram-before", required=True)
    p.add_argument("--wifi-secret-file", required=True, help="Private JSON with ssid/password, supplied by the user")
    p = sub.add_parser("asus-wireless-snapshot", help="Read the exact router's original WAN/NTP fields and eth2 MAC into a private recovery file")
    p.add_argument("--router", required=True)
    p.add_argument("--ssh-key", required=True)
    p.add_argument("--known-hosts", required=True)
    p.add_argument("--ssh-user", default="admin")
    p.add_argument("--out", required=True)
    p = sub.add_parser("adapter-draft", help="Create a non-executable unknown-device research record")
    p.add_argument("--inventory", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("check-package", help="Verify the bundled artifact digests and packaged resources")
    p = sub.add_parser("guard-network", help="Check the live computer route against the saved baseline before router writes")
    p.add_argument("--inventory", required=True)
    p.add_argument("--router", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor(Adb(args.tv, args.adb) if args.tv else None, args.router, args.ssh_key, args.known_hosts, args.ssh_user)
            private_write(args.out, result)
        elif args.command == "plan":
            result = make_plan(read_json(args.inventory))
            private_write(args.out, result)
        elif args.command == "tv-install":
            adb = Adb(args.tv, args.adb)
            adb.connect()
            result = install_tv(adb, args.artifact, args.state, args.set_home)
        elif args.command == "recover-policy":
            adb = Adb(args.tv, args.adb)
            adb.connect()
            result = restore_policy(adb, args.journal)
        elif args.command == "playback-test":
            adb = Adb(args.tv, args.adb)
            adb.connect()
            result = playback_probe(adb, args.state)
        elif args.command == "restore-home":
            adb = Adb(args.tv, args.adb)
            adb.connect()
            result = restore_home(adb, args.journal)
        elif args.command == "fetch":
            result = {"path": str(get_artifact(args.artifact, args.cache))}
        elif args.command == "asus-bundle":
            from .router import build_bundle
            result = build_bundle(read_json(args.inventory), args.provider_file, args.selected_node, args.cache, args.out)
        elif args.command == "adapter-draft":
            result = {"schema": 1, "status": "research-only", "executable": False,
                      "inventory": read_json(args.inventory), "evidence": [], "rollback": None,
                      "next": "Read skills/tv-setup/references/adapter-research.md; validate identity, narrow IPC permissions and recovery before implementing any writes"}
            private_write(args.out, result)
        elif args.command == "asus-wireless-render":
            from .router import render_wireless
            result = render_wireless(args.bundle, args.nvram_before, args.wifi_secret_file)
        elif args.command == "asus-wireless-snapshot":
            result = wireless_snapshot(args.router, args.ssh_key, args.known_hosts, args.out, args.ssh_user)
        elif args.command == "check-package":
            from .artifacts import catalog
            for name, entry in catalog().items():
                if "bundled" in entry:
                    get_artifact(name, Path("."))
            assert (ROOT / "SKILL.md").is_file()
            result = {"package_valid": True, "version": __version__, "device_compatibility_proven": False}
        elif args.command == "guard-network":
            before = read_json(args.inventory)["computer"]
            assert_network_unchanged(before)
            if before.get("gateway") == private_host(args.router) or before.get("interface", "").startswith(("utun", "tun", "wg", "ppp")):
                raise SetupError("Independent physical computer uplink has not been established")
            result = {"default_route_unchanged": True, "independent_uplink": True}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SetupError, ValueError, OSError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except subprocess.SubprocessError as error:
        print(json.dumps({"ok": False, "error": type(error).__name__,
                          "next": "Inspect the saved recovery journal; do not retry a device write blindly"}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('{"ok":false,"error":"Interrupted; preserve recovery journals"}', file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
