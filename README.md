# 星栖 Asteria

**适用于 AstrBot 的角色陪伴插件，配套 Asteria Chat Android 客户端。**

![AstrBot](https://img.shields.io/badge/AstrBot-4.26.6%2B-6b73e8)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue)
![Android](https://img.shields.io/badge/Client-Android-green)

星栖把角色状态、长期记忆、场景互动和日常陪伴整合到 AstrBot 中。你可以在原生管理页面维护角色与资料，也可以通过 Asteria Chat 与角色长期聊天。

## 主要功能

| 功能 | 说明 |
| --- | --- |
| 角色与持续状态 | 管理虚拟身体、接触反馈、位置、空间与心绪，让角色状态在对话间保持连续。 |
| 记忆与偏好 | 维护长期资料、偏好和共同经历，支持查阅、修正及修订历史。 |
| 场景互动 | 结合现有角色设定与 RP 场景，接收文字和自定义动作。 |
| 日程与提醒 | 管理一次性或周期日程、重要日期和待办，按权限与时段发送提醒。 |
| 感知与陪伴 | 接入经过授权的手机、应用和音乐状态，用于上下文与主动陪伴。 |
| 表情与媒体 | 使用共享素材库，维护表情语义、使用偏好及重复冷却。 |
| 原生管理页面 | 在 AstrBot 后台集中查看模块状态、角色、资料和配置。 |
| Asteria Chat | Android 长期聊天客户端，支持历史、附件、头像背景、动作组合与通知设置。 |

各项能力按实际配置和授权运行。没有连接的数据源会显示未接入；手机采集与主动发送需要单独开启。

## 安装插件

在 AstrBot「插件 → 安装插件 → 从链接安装」填写：

```text
https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria
```

也可以从 [Releases](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/releases) 下载源码 ZIP，通过文件安装。

安装后，在已安装插件中打开「星栖 Asteria」的管理页面。首次使用请先配置角色和授权用户，参见 [安装说明](INSTALL.md)。不要在同一实例中同时启用承担相同职责的两份插件。

### 在插件市场中查看

在「插件市场 → 插件源管理」添加星栖的插件源：

```text
https://raw.githubusercontent.com/tromperie-linyuqiao/astrbot_plugin_asteria/main/market.json
```

无法连接 GitHub 原始文件时，可使用以下镜像：

```text
https://cdn.jsdelivr.net/gh/tromperie-linyuqiao/astrbot_plugin_asteria@main/market.json
```

这是项目维护的插件源。官方公共市场收录状态以 AstrBot Cloud 的审核结果为准。

## Asteria Chat

[下载 Android 安装包](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/releases) · [客户端说明](client/asteria-chat/README.md)

当前公开客户端为 **1.7.0**，服务端为 **0.69.0**，增加会话缓存、投递中心、消息关联记忆与通知偏好。

客户端连接你自己的 AstrBot 服务，复用现有角色、模型与聊天历史。默认不预置服务器或账号。服务端连接配置见 [反向代理示例](deploy/nginx-chat.conf.example)。

### 自定义名称与软件图标

准备一张有权使用的方形 PNG，在构建前运行：

```sh
python client/asteria-chat/configure_brand.py --name "我的伙伴" --icon "/path/to/avatar.png"
```

重新构建后，Android 桌面名称与图标会使用你的设置。`--reset-icon` 可恢复默认星形图标；聊天中用户与角色的头像分别设置，不会互相覆盖。

## 使用要求与当前状态

- 实际开发基线为 AstrBot 4.26.6；建议使用兼容的4.x版本。
- 本项目仍为预览版本。完整 MC/PC 业务的新安装初始化尚未完成，相关高级入口不能直接代替首次配置，详见 [安装说明](INSTALL.md)。
- Android 后台提醒受通知权限和系统后台策略影响，目前使用本机检查机制，并非可靠远程推送。
- 连接手机状态、共享资料和发送主动消息均需明确授权；默认不附带私人角色、图片、账号、资料或密钥。

## 文档与反馈

- [安装与配置](INSTALL.md)
- [Asteria Chat 使用与构建](client/asteria-chat/README.md)
- [版本说明](RELEASE.md)
- [提交问题](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/issues)

## 许可

项目按 [AGPL v3](LICENSE) 发布。第三方组件保留各自许可，见 [NOTICE](NOTICE) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。
