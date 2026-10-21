#!/bin/sh
# RT-AC68U Merlin386.14_2 adapter template; generated bundle supplies LAN and owner values.
umask 077
lab_root=/jffs/tvsetup-split
lab_run=/tmp/tvsetup-split
lab_lock=/tmp/tvsetup-split.lock
lab_owner=tvsetup-owner-template
lab_cron=TVSetupSplit
lab_ipt=/usr/sbin/iptables

owned() {
    [ "$(cat "$lab_root/OWNER" 2>/dev/null)" = "$lab_owner" ]
}

right_mode() {
    [ "$(nvram get sw_mode)" = 1 ] && [ "$(nvram get lan_ipaddr)" = 192.168.50.1 ]
}

running() {
    lab_pid=$(cat "$lab_run/core.pid" 2>/dev/null)
    case "$lab_pid" in ''|*[!0-9]*) return 1;; esac
    [ "$lab_pid" -gt 1 ] || return 1
    kill -0 "$lab_pid" 2>/dev/null || return 1
    tr '\000' ' ' < "/proc/$lab_pid/cmdline" 2>/dev/null | grep -q "$lab_root"
}

api() {
    /usr/sbin/curl --config "$lab_root/api.conf" -f -sS --connect-timeout 2 --max-time 12 "$@"
}

clear_rules() {
    while "$lab_ipt" -t nat -D PREROUTING -i br0 -s 192.168.50.0/24 -j TVS_DNS 2>/dev/null; do :; done
    while "$lab_ipt" -t nat -D PREROUTING -i br0 -s 192.168.50.0/24 -p tcp -j TVS_TCP 2>/dev/null; do :; done
    while "$lab_ipt" -D FORWARD -i br0 -s 192.168.50.0/24 -j TVS_UDP 2>/dev/null; do :; done
    for lab_chain in TVS_DNS TVS_TCP; do
        "$lab_ipt" -t nat -F "$lab_chain" 2>/dev/null
        "$lab_ipt" -t nat -X "$lab_chain" 2>/dev/null
    done
    "$lab_ipt" -F TVS_UDP 2>/dev/null
    "$lab_ipt" -X TVS_UDP 2>/dev/null
    return 0
}

populate_rules() {
    "$lab_ipt" -t nat -N TVS_TCP || return 1
    for lab_net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
        "$lab_ipt" -t nat -A TVS_TCP -d "$lab_net" -j RETURN || return 1
    done
    # 198.19.0.0/16 is the ASUS fake-IP pool and must reach the proxy.
    "$lab_ipt" -t nat -A TVS_TCP -p tcp -j REDIRECT --to-ports 7892 || return 1
    "$lab_ipt" -t nat -N TVS_DNS || return 1
    "$lab_ipt" -t nat -A TVS_DNS -p udp --dport 53 -j REDIRECT --to-ports 1053 || return 1
    "$lab_ipt" -t nat -A TVS_DNS -p tcp --dport 53 -j REDIRECT --to-ports 1053 || return 1
    "$lab_ipt" -N TVS_UDP || return 1
    "$lab_ipt" -A TVS_UDP -d 192.168.0.0/16 -j RETURN || return 1
    # This initial profile proxies TCP; QUIC falls back to HTTPS over TCP.
    "$lab_ipt" -A TVS_UDP -p udp --dport 443 -j REJECT --reject-with icmp-port-unreachable || return 1
    "$lab_ipt" -t nat -I PREROUTING 1 -i br0 -s 192.168.50.0/24 -p tcp -j TVS_TCP || return 1
    "$lab_ipt" -t nat -I PREROUTING 1 -i br0 -s 192.168.50.0/24 -j TVS_DNS || return 1
    "$lab_ipt" -I FORWARD 1 -i br0 -s 192.168.50.0/24 -j TVS_UDP || return 1
}

apply_rules() {
    [ ! -f "$lab_root/DISABLED" ] && right_mode && running || { clear_rules; return 1; }
    [ -f "$lab_root/selection.initialized" ] || return 1
    clear_rules
    if ! populate_rules; then
        clear_rules
        return 1
    fi
}

register_watchdog() {
    cru a "$lab_cron" "* * * * * $lab_root/service.sh watchdog >/dev/null 2>&1"
}

take_lock() {
    if mkdir "$lab_lock" 2>/dev/null; then
        printf '%s' "$lab_owner" > "$lab_lock/OWNER"
        printf '%s' "$$" > "$lab_lock/PID"
        return 0
    fi
    [ "$(cat "$lab_lock/OWNER" 2>/dev/null)" = "$lab_owner" ] || return 1
    lab_previous=$(cat "$lab_lock/PID" 2>/dev/null)
    case "$lab_previous" in ''|*[!0-9]*) return 1;; esac
    if kill -0 "$lab_previous" 2>/dev/null; then return 1; fi
    rm -f "$lab_lock/PID" "$lab_lock/OWNER"
    rmdir "$lab_lock" 2>/dev/null || return 1
    take_lock
}

drop_lock() {
    if [ "$(cat "$lab_lock/PID" 2>/dev/null)" = "$$" ]; then
        rm -f "$lab_lock/PID" "$lab_lock/OWNER"
        rmdir "$lab_lock" 2>/dev/null
    fi
}

start_core() {
    owned && right_mode && [ ! -f "$lab_root/DISABLED" ] || return 1
    if running; then return 0; fi
    take_lock || return 0
    trap drop_lock EXIT
    if [ -e "$lab_run" ] && [ "$(cat "$lab_run/OWNER" 2>/dev/null)" != "$lab_owner" ]; then return 1; fi
    mkdir -p "$lab_run" || return 1
    chmod 700 "$lab_run"
    printf '%s' "$lab_owner" > "$lab_run/OWNER"
    if [ ! -x "$lab_run/mihomo-armv5" ]; then
        /bin/gunzip -c "$lab_root/core/mihomo-armv5.gz" > "$lab_run/mihomo-armv5.part" || return 1
        mv "$lab_run/mihomo-armv5.part" "$lab_run/mihomo-armv5" || return 1
        chmod 700 "$lab_run/mihomo-armv5"
    fi
    ulimit -c 0
    GOMEMLIMIT=64MiB GOGC=50 GOMAXPROCS=2 /bin/busybox nohup "$lab_run/mihomo-armv5" \
        -d "$lab_root" -f "$lab_root/config.json" </dev/null > "$lab_run/core.log" 2>&1 &
    printf '%s' "$!" > "$lab_run/core.pid"
    lab_ready=0
    for lab_try in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        sleep 1
        if api http://192.168.50.1:19090/version >/dev/null 2>&1; then lab_ready=1; break; fi
        running || return 1
    done
    [ "$lab_ready" = 1 ] || return 1
    if [ ! -f "$lab_root/selection.initialized" ]; then
        api -X PUT -H 'Content-Type: application/json' --data-binary @"$lab_root/selected.json" \
            http://192.168.50.1:19090/proxies/TVSETUP >/dev/null || return 1
        : > "$lab_root/selection.initialized"
    fi
    return 0
}

start() {
    owned && right_mode && [ ! -f "$lab_root/DISABLED" ] || return 1
    register_watchdog
    lab_wait=0
    while [ "$(nvram get wan0_state_t)" != 2 ] && [ "$lab_wait" -lt 20 ]; do
        sleep 2
        lab_wait=$((lab_wait + 1))
    done
    if start_core; then apply_rules; else clear_rules; return 1; fi
}

stop_core() {
    if running; then
        kill -TERM "$lab_pid" 2>/dev/null
        for lab_try in 1 2 3 4 5; do running || break; sleep 1; done
        if running; then kill -KILL "$lab_pid" 2>/dev/null; fi
    fi
    rm -f "$lab_run/core.pid"
}

stop() {
    clear_rules
    cru d "$lab_cron" 2>/dev/null
    stop_core
}

disable() {
    : > "$lab_root/DISABLED"
    stop
    # Restore the old global JFFS flag only if no unrelated scripts appeared.
    lab_clean=1
    for lab_path in /jffs/scripts/*; do
        [ -e "$lab_path" ] || continue
        case "$lab_path" in /jffs/scripts/services-start|/jffs/scripts/firewall-start) :;; *) lab_clean=0;; esac
    done
    if [ "$lab_clean" = 1 ] && (cd /jffs/scripts && /bin/busybox md5sum -c "$lab_root/hooks.md5" >/dev/null 2>&1); then
        lab_old=$(cat "$lab_root/original-jffs-flag" 2>/dev/null)
        case "$lab_old" in 0|1) nvram set "jffs2_scripts=$lab_old"; nvram commit;; esac
    fi
}

owned || { echo 'Refusing an unowned service directory'; exit 1; }
case "${1:-status}" in
    start) start;;
    start-core) start_core;;
    rules) apply_rules;;
    stop) stop;;
    disable) disable;;
    enable) rm -f "$lab_root/DISABLED"; nvram set jffs2_scripts=1; nvram commit; start;;
    watchdog)
        if [ -f "$lab_root/DISABLED" ]; then stop; exit 0; fi
        if ! right_mode; then stop; exit 1; fi
        if ! running; then
            clear_rules; start
        elif ! "$lab_ipt" -t nat -C PREROUTING -i br0 -s 192.168.50.0/24 -p tcp -j TVS_TCP 2>/dev/null; then
            apply_rules
        fi
        if [ -f "$lab_run/core.log" ] && [ "$(wc -c < "$lab_run/core.log")" -gt 262144 ]; then : > "$lab_run/core.log"; fi
        ;;
    status)
        if running; then echo "core_running pid=$lab_pid"; else echo core_stopped; fi
        "$lab_ipt" -t nat -L TVS_TCP -n -v 2>/dev/null
        "$lab_ipt" -t nat -L TVS_DNS -n -v 2>/dev/null
        ;;
    *) echo 'Usage: service.sh start|stop|disable|enable|status'; exit 1;;
esac
