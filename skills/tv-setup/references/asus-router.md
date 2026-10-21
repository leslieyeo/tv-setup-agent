# ASUS 分流：先验证，再分阶段部署

当前提供 RT-AC68U / Merlin386.14_2 / Linux2.6.36.4brcmarm 的**参数化预览运行包**。原始实验已实际成功；重新参数化后的安装包尚未在另一台全新路由器完成验收。其他原厂、梅林、OpenWrt、CPU/内核不得套用。

## 识别、凭据和电脑出口

1. 用户已能正常使用现有网络时先从电视测试。网络已满足需求则跳过路由改造。
2. 管理地址本身不是身份。`doctor --router ...` 公开 HTTP 结果只是提示；带用户授权的任务 SSH key 和已经核实指纹的 known_hosts 才能读型号、内核、内存、JFFS、模式。不要自动接受变更的主机密钥。
3. SSH 尚未开启时，通过路由器正常管理员界面完成本地认证及配置备份。管理员密码用隐藏输入；仅开启 LAN 管理、使用任务密钥，记录原 SSH 状态。关闭调试时恢复该原值；不能为省事开放 WAN SSH。
4. Mac/Linux 保持独立主网出口，辅助网卡只走路由器 LAN 管理，不带网关或 DNS。备份网络服务原值，写入前后比较默认 gateway/interface。不要让即将重启的测试路由成为电脑唯一出口；不要无条件把用户网卡改成 DHCP 或固定 IP。

```sh
python3 TOOL doctor --tv TV_IP:5555 --router ROUTER_LAN_IP --ssh-key PRIVATE_KEY --known-hosts VERIFIED_HOSTS --out .tvsetup/state/inventory.json
python3 TOOL asus-bundle --inventory .tvsetup/state/inventory.json --provider-file AUTHORIZED_PROVIDER_FILE --selected-node 'SELECTED_NODE' --out .tvsetup/private/asus-bundle
python3 TOOL guard-network --inventory .tvsetup/state/inventory.json --router ROUTER_LAN_IP
```

只读取用户明确选定的 provider 文件。首版为**本地节点文件导入**，没有从 Clash 任意账号自动抽取订阅，也没有封装订阅自动刷新。需要自动刷新时先取得该订阅授权，扩展 provider 的 HTTPS 更新与缓存，然后验证电脑关闭后由路由自身更新。

运行包默认拒绝已有代理、已有启动脚本、非 br0/路由模式、非 /24 LAN 或资源不足的环境。遇到这些情况应新增适配或采用现有插件，不清空 `/jffs/scripts`。将 core.gz 放 JFFS、原始约56MB核心解到 /tmp；不要在约128MB /tmp 同时解压两份。

## Agent 的部署阶段

本预览版 CLI **生成运行包，不直接下发或标记验证通过**。Agent 按下面步骤，用本地 SSH/文件工具执行可审查的具体计划；不把这段说明当已完成部署。

1. 重读现场身份，写入前后运行 `guard-network` 比较电脑默认出口；失败先修复管理链，不继续。私有 bundle 的 `bundle-manifest.json` 指定 OWNED 目录 `/jffs/tvsetup-split`、SHA-256、LAN 和 owner。远程目标必须不存在；先创建有该 owner 的私有目录，再传输清单中的普通文件，拒绝归档绝对路径、`..`、symlink。校验远程摘要；不要复制包外其他客户的目录。
2. 在远端运行 `stage-core.sh`。它核对型号/固件、原启动开关、空 hooks、原服务冲突，执行核心 `-v` 和 `-t`，只启动显式代理。核心失败时停止自有进程，不启用透明规则。为每次网络切换安排有时限的设备端回退，不仅依赖电脑 finally。
3. 从管理链显式使用代理测试国内 HTTPS、Google204、YouTube200，核对实际所选节点及中国规则。此类旧 ASUS curl 可能没有 `-x` 支持；在电脑使用 curl 显式代理并绑定管理接口，避免把电脑 Clash 的成功算给路由器。验证 DNS1053 的 UDP/TCP、核心配置、LAN API授权、WAN端口封闭。只有证据确实通过，才在远端写 `CORE_VERIFIED`。
4. 先运行 `arm-rollback.sh` 安排路由器端10分钟回退，再运行 `activate-lan.sh`。后者检查自有回退进程确实存在，仅增加自有 TVS_* 链和 LAN53 重定向，UDP443拒绝以回落 TCP；不清空全局 iptables。检查国内直连与海外规则选择，TCP/UDP DNS53，并让一台关闭自带 VPN/蜂窝的客户端实际播放。通过后才写 `LAN_VERIFIED`，运行 `disarm-rollback.sh` 解除本轮计时回退。未通过不要伪造标志；计时到期会停分流并恢复本次 hooks。定时器是运行期保护，重启不保留它，不能替代启动恢复设计。
5. 运行 `enable-boot.sh`，仅在空 hooks 的已知原始环境配置自启及 watchdog。检查回退脚本；经本轮具体授权后重启 ASUS，验证核心、原节点、DNS、NTP/时间、客户端视频和 WAN 22/80/443/7890/7892/1053/19090 不可达。不能用“API恢复”代替整体验收。
6. 恢复临时 SSH、管理凭据和电脑网卡原设置；清理本次临时目录与进程。保留运行服务、私有节点、恢复备份和摘要。用户断开电脑后复验。

`rollback.sh` 只停止自有核心、清除 TVS_* 和自有 cron，且仅在 hash 仍匹配时移除本次 hooks。不会回写整份旧防火墙，也不清空用户后来添加的脚本。无线回程部署还需先执行其独立恢复，不能直接关闭全局 JFFS。

协议范围：初版是 TCP 透明代理、DNS 分流、IPv6代理关闭、QUIC回落，其他 UDP 未代理。不要将它描述成全协议 VPN。
