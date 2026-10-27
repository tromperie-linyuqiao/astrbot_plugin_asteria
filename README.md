# 星栖 Asteria — AstrBot 伴侣系统

![AstrBot](https://img.shields.io/badge/for-AstrBot-6b73e8) ![License](https://img.shields.io/badge/license-AGPL--3.0-blue) ![Android](https://img.shields.io/badge/client-Android-green)

面向 **AstrBot** 的持续角色与聊天系统。插件叫 **星栖 Asteria**，Android 客户端叫 **Asteria Chat**。本仓库公开源码，不携带维护者私人角色、账号、服务器、聊天记录或签名密钥。

## 安装到 AstrBot

在 AstrBot「插件 → 安装插件 → 从链接安装」填写 `https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria.git`。
支持范围声明 `>=4.26.6,<5.0.0`；实际宿主基线为4.26.6，声明不等于每个版本都已实测。
插件加载后可在已安装页面看到「星栖 Asteria · AstrBot 伴侣系统」，并进入 console/home/status 等管理页面。

官方市场需要通过 AstrBot Cloud 提交审核；GitHub topics 和 release tag 不是市场收录证明。当前可从仓库直接安装。

## 功能与边界

持续角色状态、身体与空间、Presence、可维护记忆与偏好、RP、资料、日程、主动消息和手机感知的实现均在源码中；Asteria Chat 复用 AstrBot 原认证、角色、ChatService与TLS业务，不另建模型大脑。

**新安装不等同原服务器迁移。** 空白名单不授予任何人角色权限；默认关闭原生执行权与主动来源，不带旧插件数据或退休证明。MC/PC旧实例接管控制器是迁移入口，不能把其私有退休配置复制到新安装或自动停用他人的插件。首次配置和目前尚需初始化的完整业务见 [INSTALL.md](INSTALL.md)。不把源码存在称新用户全功能已经验收。

公开版保留兼容标识 `astrbot_plugin_virtual_body`、固定兼容包名及 `/astrbot_plugin_virtual_body/page/` 路由，避免已有数据与页面认证断开；仓库名、显示名和客户端品牌统一为 Asteria。维护者为 [tromperie-linyuqiao](https://github.com/tromperie-linyuqiao)，公开维护命名空间为 tromperie-linyuqiao；原作者在NOTICE中保留，不表示上游背书。

## 自定义 Chat 名称和软件图标

源码在 [client/asteria-chat](client/asteria-chat)。先执行：

```sh
python client/asteria-chat/configure_brand.py --name "我的伴侣" --icon /path/to/my-square.png
```

这会真正修改下一次构建的 Android 桌面图标和APP品牌，不改聊天双方头像。可 `--reset-icon` 恢复原创星形。它是构建定制，Android不允许应用在安装后任意替换包内图标，不能与桌面快捷方式混称。

构建需 Android SDK35、JDK17、自己的签名目录；不生成或上传维护者私钥。默认服务器留空，首次使用需配置自己部署的HTTPS接口。[客户端说明](client/asteria-chat/README.md) · [反向代理示例](deploy/nginx-chat.conf.example)

## 安全与许可

主动发送必须有真实来源、身份和许可；位置、手机采集默认关闭，由用户授予系统权限。QQ与APP记忆不能按昵称自动合并。后台回复提醒沿原本机检查，**不是可靠远程推送**，受Android与厂商后台限制。

源码使用AGPL v3及保留的第三方许可，完整说明见 [NOTICE](NOTICE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。用户自行添加的图片、角色和资料须拥有相应使用权。

私人生产环境已有的测试只属于原范围；本公开树的实际检查结果会在 [RELEASE.md](RELEASE.md) 中列出，尚未执行的全新安装/设备测试不声称通过。

## 在 AstrBot 市场中直接显示本插件

在「插件市场 → 插件源管理 → 添加源」填写：
`https://raw.githubusercontent.com/tromperie-linyuqiao/astrbot_plugin_asteria/main/market.json`。
这是本仓库维护的单插件来源，使用官方schema1；不会替换你的官方来源，也不自动安装其他插件。
官方公共市场仍须 AstrBot Cloud 提交审核，添加自己的源不等于官方收录。

公开版本身份为 `tromperie-linyuqiao/astrbot_plugin_virtual_body`，与历史私有 `menglimi/...` 身份不同。
不要把公开版与私用版同时运行，也不要直接覆盖原运行配置；本轮不会改动维护者的线上私用实例。
