# 电视安装与恢复

CLI 示例中的地址使用用户现场提供的值，不复制实验环境地址。`TOOL` 指本 Skill 的 `scripts/tvsetup.py`。

```sh
python3 TOOL doctor --tv TV_IP:5555 --adb /path/to/adb --out .tvsetup/state/inventory.json
python3 TOOL plan --inventory .tvsetup/state/inventory.json
python3 TOOL tv-install launcher-tcl --tv TV_IP:5555 --set-home
python3 TOOL tv-install smarttube-fdroid --tv TV_IP:5555
```

`--adb` 可省略，前提是 ADB 在 PATH。Shell 中使用真实脚本路径和地址，不执行带 `TOOL`、`TV_IP` 的示例原文。

桌面适配包针对 `TCL/tc8000_ay30a2/...:11/.../2026030620:user/release-keys`，样本销售型号 FF75F295C-FA65。其他固件只读研究；不把该包里的 TCL 原生设置面板调用当作其他电视的通用 API。

安装器先尝试普通包管理器。已安装的包跳过，不自动卸载或覆盖不同签名。只有精确匹配、且出现明确安装限制时才调用 `content://com.tcl.providers.config/InstallConfig`：读取原始完整 JSON → 私有恢复日志先落盘 → 仅暂停 `pmStrategy`，桌面安装时追加它自身的 launcher allowlist → 安装 → finally 原文恢复并读回逐字比较 → 删除本次随机路径 helper。

这里使用已有 shell UID 可访问的导出 Provider，不提权。不要直接对未知固件调用写接口。如果普通安装报签名冲突、磁盘不足或网络断开，不能以停用系统策略代替诊断。

若 ADB 中断、进程被强制杀死或恢复失败，保留 journal，不删除恢复 helper。重新接上同一台、同一固件后：

```sh
python3 TOOL recover-policy --tv TV_IP:5555 --journal .tvsetup/state/policy-PACKAGE.json
python3 TOOL restore-home --tv TV_IP:5555 --journal .tvsetup/state/home-before.json
```

恢复首页只还原实际保存的原组件，不卸载应用。用户后来自己改过默认首页时保护其选择，不覆盖。硬断电/kill -9 不能保证 Python finally 执行，日志恢复是必要补充，不宣称任何中断都能现场自动恢复。

已验证的本机改版桌面来源、补丁和许可位于包内 `assets/oem/`、`assets/licenses/`。它不是上游官方发行 APK，也不覆盖第三方既有签名。后续更新先核对来源和签名。
