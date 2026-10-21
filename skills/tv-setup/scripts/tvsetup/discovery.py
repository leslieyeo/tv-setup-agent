import re
import urllib.request
from pathlib import Path
from .common import SetupError, network_snapshot, now, private_host, private_write, run
from .profiles import router_profile, tv_profile


def ssh_command(host, key, known_hosts, user="admin"):
    host = private_host(host)
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,31}", user):
        raise SetupError("Invalid SSH user")
    for path in (key, known_hosts):
        if not Path(path).is_file():
            raise SetupError("Provide a task-local SSH key and a verified known_hosts file")
    return ["ssh", "-i", str(Path(key).resolve()), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(Path(known_hosts).resolve()),
            "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5", user + "@" + host]


def inspect_router(host, key=None, known_hosts=None, user="admin"):
    host = private_host(host)
    data = {"host": host, "authenticated_probe": False, "profile": None}
    if key or known_hosts:
        if not key or not known_hosts:
            raise SetupError("SSH key and known_hosts must be provided together")
        script = """set -eu
printf 'productid=%s\n' "$(nvram get productid)"
printf 'buildno=%s\n' "$(nvram get buildno)"
printf 'extendno=%s\n' "$(nvram get extendno)"
printf 'kernel=%s\n' "$(uname -r)"
printf 'arch=%s\n' "$(uname -m)"
printf 'lan_ip=%s\n' "$(nvram get lan_ipaddr)"
printf 'lan_iface=%s\n' "$(nvram get lan_ifname)"
printf 'sw_mode=%s\n' "$(nvram get sw_mode)"
printf 'jffs_scripts=%s\n' "$(nvram get jffs2_scripts)"
printf 'ram_kb=%s\n' "$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
printf 'jffs_free_kb=%s\n' "$(df -k /jffs | tail -n 1 | awk '{print $4}')"
printf 'tmp_free_kb=%s\n' "$(df -k /tmp | tail -n 1 | awk '{print $4}')"
printf 'existing_hooks=%s\n' "$(ls /jffs/scripts 2>/dev/null | wc -l)"
if [ -d /jffs/codex-asus-split ] || [ -d /jffs/tvsetup-split ]; then echo existing_proxy=yes; else echo existing_proxy=no; fi
"""
        raw = run(ssh_command(host, key, known_hosts, user) + [script], timeout=20).stdout
        for line in raw.splitlines():
            k, sep, value = line.partition("=")
            if sep and k in {"productid", "buildno", "extendno", "kernel", "arch", "lan_ip", "lan_iface", "sw_mode",
                             "jffs_scripts", "ram_kb", "jffs_free_kb", "tmp_free_kb", "existing_hooks", "existing_proxy"}:
                data[k] = value.strip()
        data["authenticated_probe"] = True
        matched = router_profile(data)
        data["profile"] = matched["id"] if matched else None
    else:
        # Never treat a TCP connection through a desktop TUN as proof of a router.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open("http://" + host + "/Main_Login.asp", timeout=4) as response:
                raw = response.read(256000).decode("utf-8", errors="replace")
            data["public_identity_hint"] = "ASUS" if re.search(r"ASUS|ASUSTeK|RT-AC68U", raw, re.I) else "unrecognized"
        except Exception as error:
            data["public_probe_error"] = type(error).__name__
        data["next"] = "Read-only authenticated identity is required before writing; do not infer model from gateway address"
    return data


def doctor(adb=None, router=None, key=None, known_hosts=None, user="admin"):
    result = {"schema": 1, "created_at": now(), "computer": network_snapshot(), "tv": None, "router": None}
    if adb:
        device = adb.inspect()
        match = tv_profile(device)
        device["profile"] = match["id"] if match else None
        result["tv"] = device
    if router:
        result["router"] = inspect_router(router, key, known_hosts, user)
    return result


def wireless_snapshot(host, key, known_hosts, output, user="admin"):
    identity = inspect_router(host, key, known_hosts, user)
    if not identity.get("profile"):
        raise SetupError("Wireless snapshot is supported only on the exact ASUS profile")
    script = """set -eu
for snapshot_key in wan_ifname wan_ifnames wan0_ifname wan0_gw_ifname wan_iface wan0_hwaddr_x wan_hwaddr_x wan0_hwaddr lan_ifnames wanduck_down nat_redirect_enable ntp_server0 ntp_server1; do
  printf '%s=%s\n' "$snapshot_key" "$(nvram get "$snapshot_key")"
done
printf 'radio_mac=%s\n' "$(/usr/sbin/wl -i eth2 cur_etheraddr)"
"""
    raw = run(ssh_command(host, key, known_hosts, user) + [script], timeout=20).stdout
    values = {}
    mac = None
    for line in raw.splitlines():
        key_name, sep, value = line.partition("=")
        if not sep:
            raise SetupError("Unexpected newline in NVRAM snapshot; preserve the original values manually")
        if key_name == "radio_mac":
            match = re.search(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", value)
            mac = match.group(0) if match else None
        else:
            if key_name in values:
                raise SetupError("Duplicate NVRAM snapshot field")
            values[key_name] = value
    if len(values) != 13 or not mac:
        raise SetupError("Incomplete wireless recovery snapshot")
    private_write(output, {"lan_ip": identity["lan_ip"], "wan_radio": "eth2", "radio_mac": mac, "nvram_before": values})
    return {"saved": str(Path(output).resolve()), "original_fields": 13, "device_values_printed": False, "device_changes": False}
