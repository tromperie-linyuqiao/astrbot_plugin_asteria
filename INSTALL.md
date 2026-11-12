# 星栖 Asteria 安装与使用

星栖是 AstrBot 的角色陪伴插件。它提供角色状态、记忆、互动、日程和生活档案，可在 AstrBot 网页管理台中使用，也可按需连接 Android 端 Asteria Chat。

## 安装前确认版本

| 项目 | 版本 |
| --- | --- |
| AstrBot 兼容范围 | `>=4.26.6,<5.0.0` |
| 插件 GitHub 主分支 | **0.77.5**，包含 Qzone 图片异步 DNS 修复 |
| 最新 GitHub Release 的插件 ZIP | **0.75.17** |
| Android 客户端 | 公开 APK **2.7.1**，主分支源码 **2.7.18（code96）** |

需要安装 **0.77.5** 时，选下面的仓库链接方式。市场页和 GitHub Release 各自显示实际可安装的版本；上传文件前请核对版本。Android 主分支功能要使用对应构建，最新版生活档案接口要求插件 **0.77.0 或更新**。 [公开发行记录](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/releases) · [插件版本页](https://cloud.astrbot.app/plugin/tromperie-linyuqiao/astrbot_plugin_asteria?tab=versions)

## 1. 安装插件

1. 登录 AstrBot 网页管理台，在「插件 → 已安装」右下角点击「安装插件」，选择「从链接安装」。
2. 粘贴仓库地址并确认安装。

   ```text
   https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria
   ```

3. 返回「已安装」，确认 **星栖 Asteria** 已启用、版本符合预期。插件标识为 `astrbot_plugin_asteria`。
4. 打开插件管理页。若出现「加载失败」，先查看该条错误或 AstrBot 日志，处理报错原因后再重载星栖。 [AstrBot 官方插件操作说明](https://docs.astrbot.app/use/plugin.html)

如需文件安装，从 [GitHub Releases](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/releases) 下载标明版本的插件 ZIP，在同一入口选择「从文件安装」。服务器仍需能获取安装所需依赖。APK 仅用于 Android 手机。

## 2. 完成首次配置

1. 在 AstrBot 的模型提供商中接入自己的对话模型，在使用的配置中选定模型。模型服务地址、凭据和角色设定均由部署者提供。
2. 在星栖管理页核对角色和目标会话，按需填写授权用户。中性角色模板位于 [data/profiles/example.json](data/profiles/example.json)，模板白名单为空。
3. 先在授权会话里完成一次普通对话，再回管理页确认相应角色与会话。之后按需开启记忆、生活、陪伴或主动消息。自动生活涉及独立模型预算，主动消息需要明确的目标和发送授权。生活档案暂无条目可以是正常初始状态。
4. 新安装的运行资料在 AstrBot 的 `data/plugin_data/astrbot_plugin_asteria/`；自定义角色文件可放在该目录的 `profiles/`。部署配置、凭据及个人资料应保存在自己的环境。

Asteria 自带记忆、陪伴与主动服务。仅使用管理页和 Chat 时可直接连接 AstrBot；有 QQ 接入需求时再配置所选适配器。

## 3. 可选：连接 Android 客户端

1. 按 [HTTPS 反向代理示例](deploy/nginx-chat.conf.example) 配置自己的 API 前缀。示例对外提供 `/asteria-api/auth/login` 和 `/asteria-api/chat/*`，上游和证书由部署者配置。
2. 安装 [公开 Asteria Chat APK](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/releases)，在客户端填写 HTTPS API 基础地址，例如 `https://chat.example.com/asteria-api`，然后使用你授权的账号登录。
3. 先确认能打开会话并读取历史。若登录成功但会话请求返回 `404`，优先核对 API 前缀和代理上游；若返回 `401`，核对登录状态及代理是否传递 Authorization。
4. 公版包名为 `com.asteria.chat`，与私人 Texas Chat 的包名不同。公版默认使用系统证书信任，服务器地址、证书与签名材料由部署者管理。已有公版安装的覆盖更新需要相同包名和签名。

语音服务和音色按需配置。Android 的锁屏收件、通知栏和横幅受系统权限及后台策略影响，分别以实际设备表现为准。 [客户端说明](client/asteria-chat/README.md)

## 4. 更新已有实例与回退

- 更新前备份插件配置、运行数据和自定义素材。优先从「已安装」更新原实例，保留原安装目录与配置映射。
- 从旧版迁移时，磁盘目录可能仍叫 `astrbot_plugin_virtual_body`，注册名可显示为 `astrbot_plugin_asteria`。已有旧资料且新目录为空时可继续原位使用；两边都有资料时需先核对归属，避免手工合并或同时启用两份实例。
- 更新后重新核对已启用版本、管理页、授权会话、历史及原有资料。需要回退时，优先恢复对应版本的插件代码；涉及数据结构或配置变更时先核对兼容性并保留更新后新增的数据。

反馈安装问题时，带上 AstrBot 版本、插件版本、安装方式、出错步骤及脱敏错误摘要即可。 [项目问题反馈](https://github.com/tromperie-linyuqiao/astrbot_plugin_asteria/issues)
