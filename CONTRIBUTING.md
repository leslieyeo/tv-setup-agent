# 贡献指南

欢迎补充设备适配、故障测试和恢复流程。方法状态和证据要写清：一台设备成功，不等于整个品牌或所有固件均支持。

## 反馈问题

说明目标、实际行为、期望行为、相关命令和最小错误片段。按需要附品牌/销售型号、产品固件指纹、Android API/ABI，或路由型号/固件/内核/架构。

分享前删除账号、订阅URL、节点凭据、SSID/密码/PMK、MAC、序列号、SSH密钥、管理会话、个人设备地址和Wi-Fi二维码。不要上传整个 `.tvsetup/` 或完整日志。固件指纹若混入设备唯一标识，也要脱敏并说明匹配方式。

## 开发与测试

需要Python3.9+和POSIX shell；软件测试不连真实设备，无第三方Python依赖。

```sh
python3 -m unittest discover -s tests -v
python3 tvsetup.py check-package
python3 scripts/build_release.py
```

修改源码或文档后，最后一条命令重建 `package-manifest.json`。不要手工改清单掩盖不一致。发行ZIP放在仓库外：

```sh
python3 scripts/build_release.py --out ../tv-setup-agent-preview.zip
```

## 新适配要求

1. 记录样本与固件、来源hash；只采集和问题有关的系统APK、Manifest或厂商固件。
2. 优先正常设置和已有接口；私有调用核对导出、权限、身份和结构，不直接套另一品牌接口。
3. 实现精确匹配、只读探针、前置条件、最小变更、原值备份、恢复、验收和资源归属。
4. 针对真实可能的失败加测试：超时、断联、恢复失败、原值变化、服务冲突；避免只断言实现字符串。
5. 分开记录软件模拟和实机安装、恢复、首页、重启及播放结果。
6. 代码、恢复和证据完成后再接入执行路径，研究草案不能直接注册为已支持。

电视执行器在 `skills/tv-setup/scripts/tvsetup/tv.py`，匹配在 `profiles.py` 和 `profiles/`，路由参数化在 `router.py` 与 `assets/router/`。扩新接口应有明确代码分支，不能只添宽泛JSON记录。

详见 [adapter-research.md](skills/tv-setup/references/adapter-research.md)。

## 外部组件与提交

`assets/artifacts.json` 记录来源和摘要。更新时核对一手发布、安全公告、包名、API/ABI及必要签名，再验证兼容。hash错误应调查来源或上游变化，不关闭校验或自动切镜像。

修改桌面或helper时提供源码/补丁、更新摘要并保留许可。不要提交签名私钥、完整SDK、厂商固件、个人节点或生成的私有运行包。

每个提交围绕一个具体目的，说明触发、行为变化和验证。PR写实际环境、未测范围和人工确认项，未实测能力保持研究或预览状态。
