# Android 作品分享与 App Links 接入

安卓复用现有 PrintFilm 账号、内容、播放和分享 API，不增加第二套分享后端。本仓库不含 Android 工程，以下 Kotlin/Manifest 片段由安卓团队接入实际项目，并用发布签名真机验证。

## 后台配置和部署

系统管理 → 站点设置：

- 开启作品分享，填写真实公网 HTTPS 分享基址（无子路径）。
- 填写 Android 包名 `marketplace_share_android_package_name`，必须等于应用 `applicationId`。
- 填写 `marketplace_share_android_sha256_fingerprints`，每行一条完整 SHA-256 证书指纹，格式为32组冒号分隔的十六进制字节。服务端统一大写、去重；包名与指纹须一起填或一起清空。
- Google Play 安装包填写 Play Console → 应用完整性中的**应用签名密钥证书**指纹，不是上传密钥指纹。其他渠道填写实际安装包签名证书；证书轮换可同时登记多个指纹。不将调试证书登记到生产域名。

无需填写 Apple Team ID 即可使用安卓分享；Apple 关联配置独立用于 iOS。分享链接本身只依赖分享开关、有效域名及现有 App 内容开放条件。

部署后确认以下地址直接返回 HTTP 200、`application/json`，无需登录、无重定向、不会被 SPA 或 WAF 登录页接管：

```text
https://实际分享域名/.well-known/assetlinks.json
```

服务端依据后台配置返回：

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "实际应用包名",
      "sha256_cert_fingerprints": ["实际完整证书SHA-256指纹"]
    }
  }
]
```

配置缺失或格式无效返回503，不发布虚假关联。停止创建新分享不会撤销域名关联，历史链接仍重新检查内容可见性。配置更新响应不缓存，但 Android 系统仍可能保留验证结果，需要设备重新验证。

仓库 `frontend/nginx.conf` 和 `deploy/nginx.local.conf` 已补充验证路径代理；外层网关/CDN也必须放行 `/.well-known/assetlinks.json` 和 `/s/`。每个实际分享域名分别提供对应验证文件，域名、子域名不能混用。

## Manifest 与链接接收

在接收链接的 Activity 加入独立 intent-filter，示例域名必须替换成后台填写的真实主机名；保留原应用启动配置：

```xml
<activity android:name=".MainActivity" android:exported="true">
    <intent-filter android:autoVerify="true">
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="https"
              android:host="share.example.com"
              android:pathPrefix="/s/" />
    </intent-filter>
</activity>
```

在 `onCreate` 和 `onNewIntent` 都处理 `intent.data`；不要依赖特定 Activity 启动模式。冷启动先等待导航就绪，保存待打开作品；重复收到同一链接避免重复压栈，必要登录后继续导航。

接收规则：

1. 只接受 HTTPS、配置的精确域名、默认443端口和 `/s/{public_id}`，拒绝账号密码、非预期查询参数/片段。当前 public_id 为32位十六进制字符串。
2. 使用关闭自动重定向的 HTTP 客户端 GET 该业务链接。遇到404/503等显示本地化不可用提示，不能自行拼接其他内容或 OSS 地址。
3. 对302的 `Location` 再校验：仍为相同 HTTPS 来源，只允许 `/marketplace/works/{id}` 或 `/marketplace/series/{id}?episode_id={id}`，ID 为正整数。拒绝外域及任意网页/WebView跳转，不自动跟随重定向链。
4. 将校验通过的业务编号交给现有内容详情/系列分集 API，随后创建播放会话；分享链接不是播放地址，不授予收费内容权益。
5. 未安装 App、域名验证失败、用户关闭“打开支持的链接”时，由浏览器打开原 Web 落地页。安卓设置和不同厂商行为可能影响唤起，不能承诺始终打开 App。

## 创建分享、系统分享及复制

先检查 capabilities 中的 `sharing_enabled`。单视频与当前分集分别请求：

```http
POST /api/marketplace/app/v1/works/{id}/share-sessions
POST /api/marketplace/app/v1/episodes/{id}/share-sessions
Accept-Language: zh-CN
Content-Type: application/json

{"anonymous_id":"持久随机安装标识至少16字符"}
```

登录用户带 Bearer Token，可省略匿名标识；游客使用随机持久安装标识，不采集硬件指纹。返回 `url`、`title`、`description`、`cover_url`、`token`、`expires_at` 等。只分享返回的 HTTPS 业务 URL，不分享播放令牌、HLS、OSS 或原片文件。全系列分享不在本期范围。

系统分享示例（在 UI 线程执行；数据通过上述 API 获取）：

```kotlin
val sendIntent = Intent(Intent.ACTION_SEND).apply {
    type = "text/plain"
    putExtra(Intent.EXTRA_SUBJECT, share.title)
    putExtra(Intent.EXTRA_TEXT, "${share.title}\n${share.url}")
}
activity.startActivity(Intent.createChooser(sendIntent, localizedShareTitle))
```

调用前确认 Activity 可用，处理没有可用目标或启动异常。分享标题使用本地化资源，不将用户作品标题自动翻译。关闭分享面板后继续停留当前视频，不中断已有播放会话。

**Android 分享计数口径：**打开分享面板、选中应用以及 `Activity.RESULT_OK` 均不能证明作品已发送。首期系统分享只提供真实发送入口，不能据此上报 `completed`。仅当未来某目标 SDK 明确提供可靠完成回调时才上报；不要把 Chooser 的目标选择回调当成发送成功。无法可靠识别取消时不强行上报 `cancelled`，会话自然过期。

复制链接使用 `ClipboardManager.setPrimaryClip(ClipData.newPlainText(share.title, share.url))`；无异常成功写入剪贴板后上报 `copied`。若创建分享后身份发生变化（游客登录、切换账号），重新创建会话，不能用新身份补报旧会话。

```http
POST /api/marketplace/app/v1/share-sessions/{token}/events
Content-Type: application/json

{"action":"copied","anonymous_id":"创建时的同一标识"}
```

收到 `share_count` 后覆盖当前展示值，不自行加一；返回值已包含真实数与运营初始值。`counted=true` 在重复响应中也可能出现，不代表再次增长。同身份同作品滚动24小时最多计一次。

上报前用本地持久队列保存原 token、动作、到期时间和身份引用；断网/5xx退避重试原事件，不重新创建分享。有效期24小时，410终止补报；401等待同账号登录，404停止补报。退出账号时暂停其队列，绝不换用另一个账号或游客身份提交。token 不写入普通日志、崩溃上报或埋点；服务端也不接受客户端传入任意视频对象路径。

## 真机验收

1. 发布签名安装包与验证文件包名、指纹完全一致；Play 和其他发行渠道分别核对。
2. Android 12+ 可使用开发工具命令检查、触发重新验证（替换实际包名）：

```sh
adb shell pm verify-app-links --re-verify com.example.app
adb shell pm get-app-links com.example.app
adb shell am start -W -a android.intent.action.VIEW -c android.intent.category.BROWSABLE -d 'https://share.example.com/s/真实作品public_id'
```

3. 冷启动、热启动、未安装、用户禁用关联时的网页回退；单视频与指定分集定位准确。
4. 游客免费完整播放、收费短试看、已购版本按权益播放；下架或封禁不能通过分享绕过限制。
5. 分享面板取消/选择应用不误计数；复制成功、重试、双设备及登录切换不重复计数或跨账号提交。
6. 域名配置缺失、无效证书、网络中断、过期会话和证书轮换有明确处理；中英文系统提示正确。

本地自动化测试只验证配置、路由和统计边界，不代表真实域名验证、系统分享或 Android 真机已通过。

参考：[Android App Links](https://developer.android.com/training/app-links)、[验证 App Links](https://developer.android.com/training/app-links/verify-android-applinks)、[系统分享](https://developer.android.com/training/sharing/send)。
