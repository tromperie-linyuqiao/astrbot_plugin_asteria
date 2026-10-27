# 星栖 · Asteria Chat

面向 AstrBot 上 Asteria Living 的 Android 长期角色聊天客户端。复用 AstrBot 的认证、角色和 ChatService，不在客户端保存密码或独立实现角色大脑。

这是从既有客户端导出的可公开源码。默认不配置任何服务器、私人证书 pin、账号、角色卡、素材或签名密钥。首次打开时，请在设置填写你部署的 HTTPS API 地址、AstrBot 用户名和密码。API 前缀与反向代理配置由服务端仓库说明决定。

## 当前能力

- 文本、历史记录、附件、结构化互动、授权共享表情库。
- 独立的用户头像与当前角色头像、背景、会话设置。
- 经服务端授权的日程、记忆详情与修订历史、主动状态、手机感知入口。
- 用户主动开启的 Android 回复检查和通知状态诊断。它是本机后台检查，不是可靠服务器推送；系统勿扰、渠道和厂商后台限制仍会影响通知。

部分高级入口要求相应版本的 Asteria Living 服务器。角色、音乐、感知和长期资料来自你的服务器，不随源码附送。

## 自定义真实 APP 名称与图标

```sh
python client/asteria-chat/configure_brand.py --name "我的伙伴" --icon "/path/to/my-square-icon.png"
```

请使用你有权使用的方形 PNG（48–4096 像素、最多8MiB），先自行裁好头像。工具直接复制图像字节到原生 launcher 资源和 APP 品牌入口，不重绘、不修改原图、不改变聊天双方头像。完成后重新构建并用同一签名升级，Android 桌面图标与应用名称才会更新。

这不是任意替换已安装 APP 图标的运行时能力。Android 的动态会话快捷方式只用于通知关联，不能冒充 launcher 图标替换。

恢复原创星形图标：

```sh
python client/asteria-chat/configure_brand.py --reset-icon
```

## 离线构建

需要自行安装 JDK17、Android SDK35，以及 build-tools35.0.0。构建器不下载工具、不安装软件、不连接服务器、不生成签名密钥。Windows 和其他系统均可通过 `--sdk`、`--jdk` 明确指定工具路径；当前公开导出只进行必要编译/语法检查，未签名发布或真机验收。

使用你自行管理的现有签名文件。设置 `ASTERIA_CHAT_SIGNING_DIR` 为该目录，默认读取 `asteria-chat.p12` 和 `storepass.private.txt`，默认 alias `asteria-chat`。也可通过 `ASTERIA_CHAT_KEYSTORE`、`ASTERIA_CHAT_STOREPASS_FILE` 与 `ASTERIA_CHAT_KEY_ALIAS` 指定现有文件/alias。不要把目录、密码或私钥提交到仓库。

```sh
python client/asteria-chat/build_apk.py --inspect-web
# 将输出的 web_sha256 填入下一行；SDK、JDK路径换成你自己的。
python client/asteria-chat/build_apk.py --sdk "/path/to/sdk" --jdk "/path/to/jdk17" --expected-web-sha "输出的SHA" --run-id my-build-1
```

可选 `--server "https://example.com/your-chat-api"` 预置你自己的 API 前缀；默认留空。可选 `--certificate-sha256` 仅对精确编译默认服务器设置叶证书 pin。其余地址使用系统信任，绝不启用 trust-all。公开版不会指向原作者私人服务器。

公开应用 ID 为 `com.asteria.chat`，与原私人客户端隔离。此公开版不能覆盖升级原私人应用，也不自动带入原账号或资料。后续发布前请提升构建脚本中的版本号和 `VERSION_CODE`，保持你自己的签名以保留本地登录与设置。

## 隐私与授权

手机感知默认关闭，用户在系统中授权后才启用原采集适配器。仅声明现有7项权限，不申请全盘访问或默认定位。JWT 在 AndroidKeyStore 保护下加密保存；密码不落盘。QQ身份共享仍需真实私聊绑定与明确查阅授权，同名或管理员登录不会获得 QQ 私密资料权限。

发布包不包含他人的贴纸、角色照片、历史聊天、课表、生日、服务器运行数据或签名证书私钥。默认星形 APP 标识和中性角色占位图为本次代码绘制。
