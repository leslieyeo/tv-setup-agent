# AC68U 的 5GHz 上联、2.4GHz 下联

这是**精确固件的可生成参考适配**，不是所有 ASUS 都有的开关，也不是独立一键部署命令。原始单台实验验证了它；新用户必须重新完成现场验收。

目标结构：主路由5GHz → AC68U eth2 station/WAN → br0 的2.4GHz eth1和LAN → 客户端。保留路由/NAT/分流，5GHz 不再广播给客户端。普通中继/AP 模式会改变原分流前提，不能直接切过去。

## 准备与兼容

- 先完成有线分流和恢复测试。未知拓扑、已有 VLAN 或非 eth0 WAN / `vlan1 eth1 eth2` 桥成员应停止套用。
- 读原 WAN、桥、wanduck、NTP 字段，空值也保存；另外读取真实 eth2 MAC。不要从其他路由复制 MAC。
- 扫描主路由 SSID，核对 eth2 驱动实际允许的信道、WPA2/认证方式。原实验 CN/1 驱动只提供149–165，而主路由当时在44；这不证明其他设备也相同。
- 如果需要把主路由改为149/80MHz，先备份准确原值、说明短暂重连及速率影响、取得用户对这一具体变更的许可。不得自动改国家码、解锁功率或声称“穿墙模式”突破硬件限制。
- SSID/密码通过本地私有 JSON 提供给渲染器。密码不写进通用包；生成的 WPA2 PMK 同样是敏感凭据，要保护。

私有 `snapshot.json` 格式：

先用 `asus-wireless-snapshot --router ROUTER_LAN_IP --ssh-key PRIVATE_KEY --known-hosts VERIFIED_HOSTS --out PRIVATE_SNAPSHOT` 采集。该命令只读，私有写盘，不输出MAC或原始值。下面的结构只用于解释和人工核对。

```json
{
  "lan_ip": "ROUTER_LAN_IP",
  "wan_radio": "eth2",
  "radio_mac": "CAPTURE_FROM_THIS_ROUTER",
  "nvram_before": {
    "wan_ifname": "CAPTURE", "wan_ifnames": "CAPTURE",
    "wan0_ifname": "CAPTURE", "wan0_gw_ifname": "CAPTURE", "wan_iface": "CAPTURE",
    "wan0_hwaddr_x": "CAPTURE", "wan_hwaddr_x": "CAPTURE", "wan0_hwaddr": "CAPTURE",
    "lan_ifnames": "CAPTURE", "wanduck_down": "CAPTURE", "nat_redirect_enable": "CAPTURE",
    "ntp_server0": "CAPTURE", "ntp_server1": "CAPTURE"
  }
}
```

不要把示例占位值当快照。用户输入文件为 `{"ssid":"实际上联SSID","password":"本地隐藏输入的实际密码"}`，不在聊天索要密码。

```sh
python3 TOOL asus-wireless-render --bundle PRIVATE_BUNDLE --nvram-before PRIVATE_SNAPSHOT --wifi-secret-file PRIVATE_INPUT
```

## 受控实施

生成器只创建私有 `wireless-reference/`，不连接路由，不改主路由信道，不自动启用。先核对其 `REVIEW_REQUIRED.json` 和恢复脚本。

1. 在有线 WAN 仍连接、电脑独立主网上，安排设备端有界回退。先临时把 eth2 移出 br0，使用驱动 `ap 0 / sup_wpa / set_pmk / join` 验证关联和 DHCP。失败应完整恢复 AP/桥/有线，不改永久 NVRAM。
2. 精确固件的普通路由初始化会将 radio 改回 AP，持久化不能仅靠 `nvram set ...sta`。已生成的参考服务通过自有 services-start、service-event-end 钩子和每分钟自有 cron 恢复无线WAN。
3. 参考服务独立目录 `/jffs/tvsetup-uplink`。先保存原 hooks；在备份、hash和不覆盖其他插件的前提下，将无线启动放在 services-start 中、将网络重启事件恢复加入 service-event-end。维护变更后的 hooks 校验。停用 stock wanduck 时只操作经准确路径核对的 `/sbin/wanduck`；不批量杀名字相近的进程。
4. 原固件只监测蓝色有线口，需要暂停该检测并用无线状态维护。无线默认路由可用后重启原生 NTP 客户端；先核对原NTP是否已经有效，再决定是否使用参考服务中的阿里 NTP。订阅HTTPS依赖正确时间，不能用电脑手动设置时间代替独立校时。
5. 验证后请用户只拔两台路由之间的线，保留管理链。验证无线 NAT、国内/海外、DNS、时间、原节点、两项 cron，再做无上联线重启和独立客户端视频。最后拔管理线、恢复电脑网卡原值和临时SSH。

回退顺序：先接回主路由 LAN→ASUS WAN，再执行自有无线 service 的 disable/stop，核对恢复的原 WAN/桥/AP/NTP，最后再决定是否停分流；恢复主路由自动信道前先停依赖149的无线链。不要盲关全局JFFS。

两频段功率在原样本已是100%，没有额外可开的“穿墙”档。放置覆盖、长距离吞吐和4K稳定性需要现场测量，不能从设置值保证。
