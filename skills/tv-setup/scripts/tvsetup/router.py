"""Render owned, reviewable router stages. No implicit router or computer writes."""
from pathlib import Path
import hashlib
import ipaddress
import json
import re
import secrets
import shlex
from .artifacts import get_artifact
from .common import ROOT, SetupError, digest, private_host, private_write
from .profiles import router_profile


def render_service(template, lan_ip, lan_cidr):
    private_host(lan_ip)
    network = ipaddress.ip_network(lan_cidr, strict=True)
    if ipaddress.ip_address(lan_ip) not in network or network.prefixlen != 24:
        raise SetupError("This adapter currently supports /24 LANs only")
    result = template.replace("192.168.50.0/24", str(network)).replace("192.168.50.1", lan_ip)
    if "192.168.50.1" in result and lan_ip != "192.168.50.1":
        raise SetupError("Unresolved LAN address in runtime")
    return result


def build_bundle(inventory, provider_file, selected_node, cache, output):
    router = inventory.get("router") or {}
    profile = router_profile(router) if router.get("authenticated_probe") else None
    if not profile:
        raise SetupError("An exact authenticated ASUS firmware/kernel profile is required")
    if router.get("existing_proxy") != "no":
        raise SetupError("Existing proxy deployment preserved; verify or adopt it instead of replacing it")
    if router.get("existing_hooks") != "0" or router.get("jffs_scripts") != "0":
        raise SetupError("Fresh-router adapter refuses to replace existing startup scripts")
    if router.get("sw_mode") != "1" or router.get("lan_iface") != "br0":
        raise SetupError("Router must already be in routed mode with br0 LAN")
    computer = inventory.get("computer") or {}
    if not computer.get("gateway") or computer["gateway"] == router["host"] or not computer.get("interface"):
        raise SetupError("Use an independent computer uplink before router changes")
    for key, required in [("ram_kb", 196608), ("jffs_free_kb", 28000), ("tmp_free_kb", 80000)]:
        if int(router.get(key, "0")) < required:
            raise SetupError("Router resource preflight failed: " + key)
    lan_ip = private_host(router["lan_ip"])
    if ipaddress.ip_address(lan_ip).version != 4:
        raise SetupError("This ASUS adapter requires an IPv4 LAN")
    if router["host"] != lan_ip:
        raise SetupError("SSH management target must be the verified LAN address")
    network = ipaddress.ip_network(lan_ip + "/24", strict=False)
    provider = Path(provider_file).read_bytes()
    if not provider or len(provider) > 4 * 1024 * 1024:
        raise SetupError("Explicit provider file is empty or too large")
    if not selected_node or len(selected_node) > 512 or any(ord(c) < 32 for c in selected_node):
        raise SetupError("Invalid selected node name")
    output = Path(output)
    if output.exists():
        raise SetupError("Output already exists; existing private bundle preserved")
    # Download and validate all public artifacts before creating the private bundle.
    artifacts = {name: get_artifact(name, cache) for name in ("mihomo-armv5", "cn-domains", "cn-ip")}
    output.mkdir(parents=True, mode=0o700)
    owner = "tvsetup-" + secrets.token_hex(12)
    secret = secrets.token_urlsafe(32)
    root = "/jffs/tvsetup-split"
    runtime = "/tmp/tvsetup-split"
    direct = ["IP-CIDR," + subnet + ",DIRECT,no-resolve" for subnet in
              ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "224.0.0.0/4")]
    config = {
        "mixed-port": 7890, "redir-port": 7892, "allow-lan": True, "bind-address": lan_ip,
        "external-controller": lan_ip + ":19090", "secret": secret, "ipv6": False,
        "mode": "rule", "log-level": "warning", "unified-delay": True, "tcp-concurrent": False,
        "tun": {"enable": False}, "profile": {"store-selected": True, "store-fake-ip": False},
        "proxy-providers": {"AUTHORIZED": {"type": "file", "path": "./providers/authorized.yaml"}},
        "proxy-groups": [{"name": "TVSETUP", "type": "select", "use": ["AUTHORIZED"]}],
        "rule-providers": {
            "cn-domains": {"type": "file", "path": "./rules/cn-domains.mrs", "behavior": "domain", "format": "mrs"},
            "cn-ip": {"type": "file", "path": "./rules/cn-ip.mrs", "behavior": "ipcidr", "format": "mrs"}},
        "rules": direct + ["RULE-SET,cn-domains,DIRECT", "RULE-SET,cn-ip,DIRECT,no-resolve", "MATCH,TVSETUP"],
        "dns": {"enable": True, "listen": lan_ip + ":1053", "ipv6": False,
                "enhanced-mode": "fake-ip", "fake-ip-range": "198.19.0.1/16",
                "fake-ip-filter": ["*.lan", "*.local", "localhost", "+.pool.ntp.org", "+.ntp.org", "time.*.com"],
                "default-nameserver": ["223.5.5.5", "119.29.29.29"],
                "proxy-server-nameserver": ["223.5.5.5", "119.29.29.29"],
                "direct-nameserver": ["223.5.5.5", "119.29.29.29"],
                "nameserver": ["https://1.1.1.1/dns-query#TVSETUP"],
                "nameserver-policy": {"rule-set:cn-domains": ["223.5.5.5", "119.29.29.29"]}}
    }
    files = {"config.json": json.dumps(config, ensure_ascii=False, indent=2).encode(),
             "providers/authorized.yaml": provider, "selected.json": json.dumps({"name": selected_node}, ensure_ascii=False).encode(),
             "api.conf": ('header = "Authorization: Bearer ' + secret + '"\n').encode(),
             "OWNER": owner.encode(), "original-jffs-flag": b"0"}
    template = (ROOT / "assets/router/service.sh").read_text()
    template = template.replace("tvsetup-owner-template", owner)
    files["service.sh"] = render_service(template, lan_ip, str(network)).encode()
    for name, relative in [("mihomo-armv5", "core/mihomo-armv5.gz"), ("cn-domains", "rules/cn-domains.mrs"), ("cn-ip", "rules/cn-ip.mrs")]:
        files[relative] = artifacts[name].read_bytes()
    quoted_owner = shlex.quote(owner)
    identity = f'''test "$(nvram get productid)" = RT-AC68U
test "$(nvram get buildno)" = 386
test "$(nvram get extendno)" = 14_2
test "$(uname -r)" = 2.6.36.4brcmarm
test "$(nvram get sw_mode)" = 1
test "$(nvram get lan_ipaddr)" = {shlex.quote(lan_ip)}
test "$(nvram get lan_ifname)" = br0
test "$(cat {root}/OWNER)" = {quoted_owner}
'''
    # These stages are deliberately separate: the Agent must verify the previous stage.
    files["stage-core.sh"] = (f'''#!/bin/sh
set -eu
umask 077
{identity}
test "$(nvram get jffs2_scripts)" = 0
test -z "$(ls -A /jffs/scripts)"
test ! -d /jffs/codex-asus-split
test ! -d /jffs/codex-asus-uplink
if /usr/sbin/iptables-save | grep -q TVS_; then exit 30; fi
test ! -e {runtime}
mkdir {runtime}
chmod 700 {runtime}
printf '%s' {quoted_owner} > {runtime}/OWNER
stage_ok=0
trap 'if [ "$stage_ok" != 1 ]; then {root}/service.sh stop >/dev/null 2>&1; fi' EXIT
gunzip -c {root}/core/mihomo-armv5.gz > {runtime}/mihomo-armv5
chmod 700 {runtime}/mihomo-armv5
{runtime}/mihomo-armv5 -v > {root}/runtime-version.txt
GOMEMLIMIT=64MiB GOGC=50 GOMAXPROCS=2 {runtime}/mihomo-armv5 -d {root} -f {root}/config.json -t > {root}/config-check.txt 2>&1
{root}/service.sh start-core
stage_ok=1
''').encode()
    files["activate-lan.sh"] = (f'''#!/bin/sh
set -eu
{identity}
test -f {root}/CORE_VERIFIED
test "$(cat {root}/ROLLBACK_ARMED)" = {quoted_owner}
test -f {root}/rollback-timer.pid
timer_pid=$(cat {root}/rollback-timer.pid)
case "$timer_pid" in ''|*[!0-9]*) exit 40;; esac
test "$timer_pid" -gt 1
kill -0 "$timer_pid"
case "$(tr '\\000' ' ' < /proc/$timer_pid/cmdline)" in *'{root}/rollback-after.sh'*) :;; *) exit 41;; esac
{root}/service.sh start
''').encode()
    files["arm-rollback.sh"] = (f'''#!/bin/sh
set -eu
umask 077
{identity}
test ! -e {root}/ROLLBACK_ARMED
printf '%s' {quoted_owner} > {root}/ROLLBACK_ARMED
/bin/busybox nohup /bin/sh {root}/rollback-after.sh </dev/null >{root}/rollback-timer.log 2>&1 &
echo $! > {root}/rollback-timer.pid
''').encode()
    files["rollback-after.sh"] = (f'''#!/bin/sh
sleep 600
if [ "$(cat {root}/ROLLBACK_ARMED 2>/dev/null)" = {quoted_owner} ]; then
  /bin/sh {root}/rollback.sh
  rm -f {root}/ROLLBACK_ARMED
fi
''').encode()
    files["disarm-rollback.sh"] = (f'''#!/bin/sh
set -eu
{identity}
test -f {root}/LAN_VERIFIED
test "$(cat {root}/ROLLBACK_ARMED)" = {quoted_owner}
rm -f {root}/ROLLBACK_ARMED
# The timer observes the absent flag and exits harmlessly; do not kill an unrelated or recycled PID.
''').encode()
    files["enable-boot.sh"] = (f'''#!/bin/sh
set -eu
umask 077
{identity}
test -f {root}/LAN_VERIFIED
test "$(nvram get jffs2_scripts)" = 0
test -z "$(ls -A /jffs/scripts)"
cat > /jffs/scripts/services-start <<'TVSETUP_HOOK'
#!/bin/sh
{root}/service.sh start >/tmp/tvsetup-startup.log 2>&1 &
TVSETUP_HOOK
cat > /jffs/scripts/firewall-start <<'TVSETUP_HOOK'
#!/bin/sh
{root}/service.sh rules >/dev/null 2>&1
exit 0
TVSETUP_HOOK
chmod 700 /jffs/scripts/services-start /jffs/scripts/firewall-start
cd /jffs/scripts
/bin/busybox md5sum services-start firewall-start > {root}/hooks.md5
nvram set jffs2_scripts=1
nvram commit
''').encode()
    files["rollback.sh"] = (f'''#!/bin/sh
set -eu
{identity}
{root}/service.sh disable
# Keep provider/config/OWNER until the owner has exported recovery evidence.
# Remove startup scripts only when both still match this installation.
if [ -f {root}/hooks.md5 ] && (cd /jffs/scripts && /bin/busybox md5sum -c {root}/hooks.md5 >/dev/null 2>&1); then
  rm -f /jffs/scripts/services-start /jffs/scripts/firewall-start
fi
''').encode()
    for name, data in files.items():
        private_write(output / name, data)
        if name.endswith(".sh"):
            (output / name).chmod(0o700)
    manifest = {name: digest(output / name) for name in files}
    private_write(output / "bundle-manifest.json", {"owner": owner, "target_profile": profile["id"],
                  "target_lan": lan_ip, "lan_cidr": str(network), "remote_root": root,
                  "scope": "wired-fresh-merlin-only", "files": manifest,
                  "packaging_tests_only": True, "requires_agent_staged_verification": True})
    return {"rendered": True, "path": str(output.resolve()), "owner": owner, "contains_credentials": True,
            "deployed": False, "wireless_uplink": "Read the version-specific wireless adapter reference before extending this wired bundle",
            "next": "Follow references/asus-router.md, preserve the computer uplink, and verify each remote stage before marking CORE_VERIFIED or LAN_VERIFIED"}


def render_wireless(bundle, snapshot_file, wifi_file):
    """Prepare the exact-radio reference, without touching either router or its channels."""
    bundle = Path(bundle)
    meta = json.loads((bundle / "bundle-manifest.json").read_text())
    if meta["target_profile"] != "asus-rt-ac68u-merlin-386-14-2":
        raise SetupError("No exact wireless reference for this router")
    snapshot = json.loads(Path(snapshot_file).read_text())
    required = {"wan_ifname", "wan_ifnames", "wan0_ifname", "wan0_gw_ifname", "wan_iface",
                "wan0_hwaddr_x", "wan_hwaddr_x", "wan0_hwaddr", "lan_ifnames", "wanduck_down",
                "nat_redirect_enable", "ntp_server0", "ntp_server1"}
    values = snapshot.get("nvram_before")
    if not isinstance(values, dict) or set(values) != required:
        raise SetupError("Capture exactly the documented original WAN/NTP fields, including empty values")
    if snapshot.get("lan_ip") != meta["target_lan"] or snapshot.get("wan_radio") != "eth2":
        raise SetupError("Wireless snapshot target or radio differs")
    if values["lan_ifnames"] != "vlan1 eth1 eth2" or values["wan_ifname"] != "eth0":
        raise SetupError("Custom bridge/VLAN topology needs another adapter")
    for value in values.values():
        if not isinstance(value, str) or any(c in value for c in "\0\r\n"):
            raise SetupError("Invalid NVRAM snapshot value")
    mac = snapshot.get("radio_mac", "")
    if not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", mac):
        raise SetupError("Capture the actual eth2 radio MAC; never copy another installation's MAC")
    wifi = json.loads(Path(wifi_file).read_text())
    ssid, password = wifi.get("ssid", ""), wifi.get("password", "")
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or any(c in ssid for c in "\0\r\n"):
        raise SetupError("Invalid upstream SSID")
    if not isinstance(password, str):
        raise SetupError("Wi-Fi password must be a string in the private input file")
    if re.fullmatch(r"[0-9a-fA-F]{64}", password):
        pmk = password.lower()
    elif 8 <= len(password.encode()) <= 63:
        pmk = hashlib.pbkdf2_hmac("sha1", password.encode(), ssid.encode(), 4096, 32).hex()
    else:
        raise SetupError("This adapter supports WPA2 passphrases or 64-hex PMKs only")
    target = bundle / "wireless-reference"
    if target.exists():
        raise SetupError("Existing wireless recovery data preserved")
    target.mkdir(mode=0o700)
    owner = meta["owner"] + "-uplink"
    template = (ROOT / "assets/router/wireless-service.template.sh").read_text()
    template = template.replace("tvsetup-owner-template", owner).replace("192.168.50.1", meta["target_lan"])
    private_write(target / "service.sh", template)
    (target / "service.sh").chmod(0o700)
    private_write(target / "OWNER", owner)
    private_write(target / "uplink.conf", "\n".join(k + "=" + shlex.quote(v) for k, v in
                  [("WIFI_SSID", ssid), ("WIFI_PMK", pmk), ("WIFI_MAC", mac)]) + "\n")
    restore = "#!/bin/sh\nset -eu\n" + "\n".join("nvram set " + shlex.quote(k + "=" + values[k]) for k in sorted(values)) + "\n"
    private_write(target / "restore-nvram.sh", restore)
    (target / "restore-nvram.sh").chmod(0o700)
    private_write(target / "nvram-before.json", values)
    private_write(target / "REVIEW_REQUIRED.json", {"deployed": False, "enabled": False,
                  "portability_status": "reference-needs-live-validation", "lan_ip": meta["target_lan"],
                  "checks_before_use": ["upstream visible in eth2 allowed channels", "WPA2 supported", "independent computer uplink", "bounded rollback armed", "services-start and service-event-end backups", "do not reduce regulatory restrictions"],
                  "checks_after_use": ["wireless DHCP and NAT", "TCP and UDP DNS", "domestic direct and YouTube playback", "ntp_ready=1", "wire-free reboot recovery", "WAN management ports closed"]})
    return {"rendered": True, "path": str(target.resolve()), "deployed": False,
            "plaintext_wifi_password_saved": False, "derived_pmk_is_sensitive": True,
            "next": "The Agent must follow references/wireless-uplink.md; rendering does not prove successful deployment"}
