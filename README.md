# 星栖 Asteria

**适用于 AstrBot 的角色陪伴插件，配套 Asteria Chat Android 客户端。**

![AstrBot](https://img.shields.io/badge/AstrBot-4.26.6%2B-6b73e8)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue)
![Android](https://img.shields.io/badge/Client-Android-green)

星栖把角色状态、长期记忆、场景互动和日常陪伴整合到 AstrBot 中。你可以在统一管理页面维护角色与资料，也可以通过 Asteria Chat 与角色长期聊天。

## 主要功能

| 功能 | 说明 |
| --- | --- |
| 角色与持续状态 | 管理虚拟身体、接触反馈、位置、空间与心绪，让角色状态在对话间保持连续。 |
| 记忆与偏好 | 维护长期资料、偏好和共同经历，支持查阅、修正及修订历史。 |
| 场景互动 | 结合现有角色设定与 RP 场景，接收文字和自定义动作。 |
| 日程与提醒 | 管理一次性或周期日程、重要日期和待办，按权限与时段发送提醒。 |
| 感知与陪伴 | 接入经过授权的手机、应用和音乐状态，用于上下文与主动陪伴。 |
| 表情与媒体 | 使用共享素材库，维护表情语义、使用偏好及重复冷却。 |
| 生活与数字档案 | 查阅生活时间线、相关角色与线索，维护私人空间、兴趣和收藏资源。 |
| 声音与朗读 | 保存会话声音档案，使用设备朗读、系统语音输入或自行配置的云端语音。 |
| 统一管理页面 | 在 AstrBot 后台集中查看模块状态、角色、资料和配置。 |
| Asteria Chat | Android 长期聊天客户端，支持历史、附件、头像背景、动作组合与通知设置。 |

各项能力按实际配置和授权运行。没有连接的数据源会显示未接入；手机采集与主动发送需要单独开启。

## 控制台修复（0.75.3）

- 补齐改名后的生活档案、私人空间与兴趣接口，沿原资料和权限读取；读取失败与真实空档案分开显示。
- 修复完整角色资料的同源导航，准确区分陪伴服务运行状态和未启用的额外调度器。
- 新增“资料中心 → 语料与聊天偏好”独立分区，支持 `#chat_corpus` 直达，复用当前登录账号的 WebChat 会话库。
- 本轮只更新插件控制台；Asteria Chat 仍为 2.7.0，未生成新 APK。

## 日常与主动消息修复（0.75.4）

- 准备虚构日常前先按角色时区核对日期；没有未来时段或可用目标时保留明确原因，不生成无用准备记录。
- 回执丢失时只读核对原日期、角色、会话及计划来源；完整证明才解除等待，不自动重发或清除旧未知记录。
- 历史分享记录与最近推进状态分开显示；主动消息展示后台已有的当前阻止原因和处理方向。
- 本轮更新插件控制台与日常接口，客户端保持原版本。既有资料、来源与用户设置保留。

## 语料资料库工作台（0.75.5）

- 修复 AstrBot 页面桥成功响应解包后，已有语料无法加载的问题。
- 在后台创建逻辑资料库，逐块录入、修改和停用参考文本；保留原条目和修订。
- 为参考资料库设置语境匹配、关键词匹配或每次提供候选；排除词优先，沿原候选数量与上下文预算。
- 账号、角色及会话权限不变；旧客户端接口保持，资料库不新建物理数据库或自动调用模型。

## 本轮改进

- 细分部位与用户动作，保存姿态、相对位置和接触状态；明确结束接触，持续状态不靠时间重复增加数值。
- 今日近况与计划时间线，区分计划、完成和取消；页面与正常回复读取同一份授权资料。
- 简洁的普通文本语料库与明确偏好。可选标签，本地缩小候选，正常回复模型自行采用；没有额外选材模型请求。
- App 部位搜索、轻量动效和减少动态支持；已有账号、草稿与消息结果未知保护保留。

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

当前源码：**Asteria 0.75.5 / Asteria Chat 2.7.0（code 78）**。本轮发布客户端源码；Releases 中旧版本 APK 不代表本轮版本，请按客户端说明自行构建。

客户端连接你自己的 AstrBot 服务，复用现有角色、模型与聊天历史。默认不预置服务器或账号。服务端连接配置见 [反向代理示例](deploy/nginx-chat.conf.example)。

### 自定义名称与软件图标

准备一张有权使用的方形 PNG，在构建前运行：

```sh
python client/asteria-chat/configure_brand.py --name "我的伙伴" --icon "/path/to/avatar.png"
```

重新构建后，Android 桌面名称与图标会使用你的设置。`--reset-icon` 可恢复默认星形图标；聊天中用户与角色的头像分别设置，不会互相覆盖。

## 使用要求与当前状态

- 实际开发基线为 AstrBot 4.26.6；建议使用兼容的4.x版本。
- 本项目仍为预览版本。记忆、陪伴和主动服务由 Asteria 自身运行，不要求安装历史来源插件。首次使用仍需配置模型、角色、目标权限和各项开关，详见 [安装说明](INSTALL.md)。
- Android 后台提醒受通知权限和系统后台策略影响，目前使用本机检查机制，并非可靠远程推送。
- 连接手机状态、共享资料和发送主动消息均需明确授权；默认不附带私人角色、图片、账号、资料或密钥。

## 文档与反馈

- [安装与配置](INSTALL.md)
- [Asteria Chat 使用与构建](client/asteria-chat/README.md)
- [版本说明](RELEASE.md)
- [提交问题](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/issues)

## 许可

项目按 [AGPL v3](LICENSE) 发布。第三方组件保留各自许可，见 [NOTICE](NOTICE) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。
