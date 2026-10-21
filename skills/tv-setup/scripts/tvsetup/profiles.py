from .common import ROOT, read_json


def tv_profile(device):
    profiles = read_json(ROOT / "profiles/tv.json")
    for profile in profiles:
        if profile.get("method") != "tcl-install-config-transaction" or not profile.get("match", {}).get("ro.build.fingerprint"):
            continue
        if all(device.get(k) == v for k, v in profile["match"].items()):
            return profile
    return None


def router_profile(device):
    profiles = read_json(ROOT / "profiles/router.json")
    for profile in profiles:
        if profile.get("id") != "asus-rt-ac68u-merlin-386-14-2" or not all(profile.get("match", {}).get(k) for k in ("productid", "buildno", "extendno", "kernel", "arch")):
            continue
        if all(device.get(k) == v for k, v in profile["match"].items()):
            return profile
    return None
