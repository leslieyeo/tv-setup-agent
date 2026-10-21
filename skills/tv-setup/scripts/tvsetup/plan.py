import hashlib
import json
from .common import now
from .profiles import tv_profile, router_profile


def make_plan(report):
    steps = []
    tv = report.get("tv")
    if not tv:
        steps.append({"step": "discover-tv", "mode": "needs-input", "reason": "Authorize ADB and supply the TV LAN address or USB serial"})
    else:
        profile = tv_profile(tv)
        if not profile:
            steps.append({"step": "research-launcher-adapter", "mode": "read-only", "reason": "No exact firmware match; do not reuse another brand's private interface"})
        else:
            steps.append({"step": "install-launcher", "mode": "skip" if tv.get("packages", {}).get("com.gathin.tvhome", {}).get("installed") else "supported", "adapter": profile["id"]})
        sdk = int(tv.get("ro.build.version.sdk") or 0)
        steps.append({"step": "install-smarttube-fdroid", "mode": "skip" if tv.get("packages", {}).get("app.smarttube.fdroid", {}).get("installed") else ("standard-adb" if sdk >= 21 else "unsupported")})
    router = report.get("router")
    if router:
        match = router_profile(router) if router.get("authenticated_probe") else None
        if router.get("existing_proxy") == "yes":
            mode, why = "verify-existing", "Existing proxy deployment detected; preserve it and test from the TV"
        elif not match:
            mode, why = "read-only-research", "Router firmware/kernel/CPU compatibility not established"
        elif report["computer"].get("gateway") == router["host"]:
            mode, why = "needs-independent-uplink", "The computer currently depends on the router to be modified"
        elif router.get("existing_hooks") != "0" or router.get("jffs_scripts") != "0":
            mode, why = "needs-hook-adapter", "Existing startup scripts must be preserved; the fresh-router bundle refuses to replace them"
        else:
            mode, why = "agent-staged", "Generate an owned ASUS bundle, test core/DNS/rules, then startup and reboot separately"
        steps.append({"step": "router-split-routing", "mode": mode, "reason": why})
    else:
        steps.append({"step": "network-path", "mode": "verify-first", "reason": "If the TV already reaches YouTube, no router changes are needed"})
    steps.append({"step": "playback-and-recovery", "mode": "required", "checks": ["home launch", "media progress", "viewer picture and sound", "pause/resume", "temporary resources removed"]})
    stable = {"schema": 1, "inventory": report, "steps": steps}
    plan_id = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]
    return {**stable, "plan_id": plan_id, "created_at": now(), "mutations_started": False}
