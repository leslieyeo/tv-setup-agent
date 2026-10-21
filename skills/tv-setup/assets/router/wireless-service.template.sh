#!/bin/sh
# One 5 GHz station as WAN; preserve routed LAN and the existing Mihomo service.
umask 077
up_root=/jffs/tvsetup-uplink
up_run=/tmp/tvsetup-uplink
up_lock=/tmp/tvsetup-uplink.lock
up_owner=tvsetup-owner-template
up_cron=TVSetupUplink

owned() { [ "$(cat "$up_root/OWNER" 2>/dev/null)" = "$up_owner" ]; }
right_router() {
    [ "$(nvram get productid)" = RT-AC68U ] && [ "$(nvram get sw_mode)" = 1 ] &&
    [ "$(nvram get lan_ipaddr)" = 192.168.50.1 ]
}
take_lock() {
    if mkdir "$up_lock" 2>/dev/null; then
        printf '%s' "$up_owner" > "$up_lock/OWNER"
        printf '%s' "$$" > "$up_lock/PID"
        return 0
    fi
    [ "$(cat "$up_lock/OWNER" 2>/dev/null)" = "$up_owner" ] || return 1
    up_previous=$(cat "$up_lock/PID" 2>/dev/null)
    case "$up_previous" in ''|*[!0-9]*) return 1;; esac
    kill -0 "$up_previous" 2>/dev/null && return 1
    rm -f "$up_lock/OWNER" "$up_lock/PID"
    rmdir "$up_lock" 2>/dev/null || return 1
    take_lock
}
drop_lock() {
    if [ "$(cat "$up_lock/PID" 2>/dev/null)" = "$$" ]; then
        rm -f "$up_lock/OWNER" "$up_lock/PID"
        rmdir "$up_lock" 2>/dev/null
    fi
}
prepare_runtime() {
    if [ -e "$up_run" ] && [ "$(cat "$up_run/OWNER" 2>/dev/null)" != "$up_owner" ]; then return 1; fi
    mkdir -p "$up_run" || return 1
    chmod 700 "$up_run"
    printf '%s' "$up_owner" > "$up_run/OWNER"
}
wireless_linked() {
    [ "$(/usr/sbin/wl -i eth2 ap 2>/dev/null)" = 0 ] || return 1
    /usr/sbin/wl -i eth2 status 2>/dev/null | grep -Fq "SSID: \"$WIFI_SSID\"" || return 1
    /usr/sbin/wl -i eth2 assoc 2>/dev/null | grep -q BSSID
}
ready() {
    [ "$(nvram get wan0_ifname)" = eth2 ] && [ "$(nvram get wan0_state_t)" = 2 ] &&
    wireless_linked && ip route | grep -q '^default .* dev eth2'
}
pause_wired_detection() {
    # The stock detector tests the blue Ethernet port, not this wireless uplink.
    nvram set wanduck_down=1
    nvram set nat_redirect_enable=0
    for up_pid in $(pidof wanduck 2>/dev/null); do
        case "$up_pid" in ''|*[!0-9]*) continue;; esac
        [ "$up_pid" -gt 1 ] || continue
        up_cmd=$(tr '\000' ' ' < "/proc/$up_pid/cmdline" 2>/dev/null)
        case "$up_cmd" in '/sbin/wanduck '|'/sbin/wanduck') kill -TERM "$up_pid";; esac
    done
}
sync_time() {
    # Start the firmware's own NTP client after the wireless default route exists.
    nvram set ntp_server0=ntp.aliyun.com
    nvram set ntp_server1=ntp1.aliyun.com
    service restart_ntpd >/dev/null 2>&1
}
start() {
    owned && right_router || return 1
    if [ -f "$up_root/ENABLED" ]; then
        cru a "$up_cron" "* * * * * $up_root/service.sh watchdog >/dev/null 2>&1"
    fi
    take_lock || return 0
    trap drop_lock EXIT
    prepare_runtime || return 1
    if ready; then
        pause_wired_detection
        if [ "$(nvram get ntp_ready)" != 1 ] || [ "$(date -u +%Y)" -lt 2025 ]; then sync_time; fi
        return 0
    fi
    pause_wired_detection
    service stop_wan >/dev/null 2>&1
    sleep 3
    nvram set wan_ifname=eth2
    nvram set wan_ifnames=eth2
    nvram set wan0_ifname=eth2
    nvram set wan0_gw_ifname=eth2
    nvram set wan_iface=eth2
    nvram set "wan0_hwaddr_x=$WIFI_MAC"
    nvram set "wan_hwaddr_x=$WIFI_MAC"
    nvram set "wan0_hwaddr=$WIFI_MAC"
    nvram set 'lan_ifnames=vlan1 eth1'
    brctl delif br0 eth2 2>/dev/null
    /usr/sbin/wl -i eth2 down || return 1
    /usr/sbin/wl -i eth2 apsta 0 || return 1
    /usr/sbin/wl -i eth2 ap 0 || return 1
    /usr/sbin/wl -i eth2 wet 0 || return 1
    /usr/sbin/wl -i eth2 wsec 4 || return 1
    /usr/sbin/wl -i eth2 wpa_auth 128 || return 1
    /usr/sbin/wl -i eth2 sup_wpa 1 || return 1
    /usr/sbin/wl -i eth2 set_pmk "$WIFI_PMK" || return 1
    /usr/sbin/wl -i eth2 up || return 1
    /usr/sbin/wl -i eth2 join "$WIFI_SSID" imode bss amode wpa2psk || return 1
    up_joined=0
    for up_try in 1 2 3 4 5 6 7 8 9 10; do
        sleep 1
        if wireless_linked; then up_joined=1; break; fi
    done
    [ "$up_joined" = 1 ] || return 1
    service start_wan >/dev/null 2>&1
    up_ready=0
    for up_try in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        sleep 1
        if ready; then up_ready=1; break; fi
    done
    [ "$up_ready" = 1 ] || return 1
    sync_time
    /jffs/tvsetup-split/service.sh rules >/dev/null 2>&1
    echo WIRELESS_ROUTED_WAN_READY
}
stop() {
    owned && right_router || return 1
    take_lock || return 1
    trap drop_lock EXIT
    cru d "$up_cron" 2>/dev/null
    service stop_wan >/dev/null 2>&1
    sleep 3
    /bin/sh "$up_root/restore-nvram.sh" || return 1
    /usr/sbin/wl -i eth2 disassoc 2>/dev/null
    /usr/sbin/wl -i eth2 down
    /usr/sbin/wl -i eth2 sup_wpa 0
    /usr/sbin/wl -i eth2 apsta 0
    /usr/sbin/wl -i eth2 ap 1
    /usr/sbin/wlconf eth2 up
    /usr/sbin/wlconf eth2 start
    brctl addif br0 eth2 2>/dev/null
    service start_wan >/dev/null 2>&1
    if [ "$(nvram get wanduck_down)" != 1 ] && ! pidof wanduck >/dev/null 2>&1; then
        /bin/busybox nohup /sbin/wanduck </dev/null > "$up_run/restored-wanduck.log" 2>&1 &
    fi
    for up_try in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if [ "$(nvram get wan0_state_t)" = 2 ] && ip route | grep -q '^default .* dev eth0'; then break; fi
        sleep 1
    done
    /jffs/tvsetup-split/service.sh rules >/dev/null 2>&1
    service restart_ntpd >/dev/null 2>&1
    echo ORIGINAL_WIRED_WAN_RESTORED
}

owned && right_router || { echo WRONG_ROUTER_OR_UNOWNED_DIRECTORY; exit 1; }
. "$up_root/uplink.conf"
case "${1:-status}" in
    start) start;;
    stop) stop;;
    enable)
        : > "$up_root/ENABLED"
        cru a "$up_cron" "* * * * * $up_root/service.sh watchdog >/dev/null 2>&1"
        start;;
    disable) rm -f "$up_root/ENABLED"; stop;;
    watchdog)
        [ -f "$up_root/ENABLED" ] || exit 0
        if ! ready; then
            start
        else
            pause_wired_detection
            if [ "$(nvram get ntp_ready)" != 1 ] || [ "$(date -u +%Y)" -lt 2025 ]; then sync_time; fi
        fi;;
    status)
        if ready; then echo WIRELESS_UPLINK_READY; else echo WIRELESS_UPLINK_NOT_READY; fi
        ip route
        /usr/sbin/wl -i eth2 status
        ;;
    *) echo 'Usage: service.sh start|stop|enable|disable|status'; exit 1;;
esac
