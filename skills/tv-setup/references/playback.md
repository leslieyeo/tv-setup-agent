# YouTube 兼容与端侧验收

1. 复现屏幕原文并记录当前官方应用版本。谷歌[设备列表](https://support.google.com/youtube/answer/7582560)明确部分型号仍不支持；[技术要求提示说明](https://support.google.com/youtube/answer/6098135?hl=zh-Hans)没有公开每台机器命中哪项检查。不能直接断言是硬件不足、电视旧或缺Google服务。
2. 用电视本身验证DNS、HTTPS和图片服务；经电脑Clash成功不证明电视已连通。网络已有独立分流时不改电视全局代理；临时探针只用本次随机路径并在finally清理。
3. 官方App无法运行时评估厂商正常固件更新、浏览器或兼容TV客户端。不要为了“官方”盲目刷国际版固件或安装来源不明的GMS全家桶。
4. 本包固定候选为 **SmartTube F-Droid 32.56 / Android5+ / ARMv7、ARM64、x86**。作者[曾公告历史构建环境感染](https://github.com/yuliskov/SmartTube)，因此采用[F-Droid独立编译并签名](https://f-droid.org/packages/app.smarttube.fdroid/)的版本，文件SHA和签名依据F-Droid签名仓库索引核对。包内hash锁定防止替换；未来接口失效时检查F-Droid/项目最新一手发布和公告，不在失败后切换随机镜像或关闭签名检查。

```sh
python3 TOOL tv-install smarttube-fdroid --tv TV_IP:5555
python3 TOOL playback-test --tv TV_IP:5555
```

先匿名播放公开Blender测试视频。`playback-test`只观察进度，不自动宣称听到声音/看见画面；电视硬件视频层可能不出现在ADB截图里。让现场观众确认实际音画、遥控器首页/确认/返回/暂停，测试结束避免留下无必要的后台播放。

首个可用视频不等于所有内容已验证：账号登录、会员内容、投屏、语音搜索、HDR和长时间4K各自记录是否测试。4K60缓冲时先比较1080p60，区分无线吞吐、节点、解码，不把缓冲误判成设备完全不兼容。

交付写清实际图标和入口。原官方YouTube保留时，说明目前可用的是SmartTube F-Droid。程序可安装/可打开与实际可播放分开验收；需要购买外接设备才能继续时再取得该明确选择。
