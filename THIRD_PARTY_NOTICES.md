# 第三方组件与许可

星栖的原创部分采用 AGPL-3.0-or-later。包含的第三方代码及依赖保留各自权利；本发行可统一按 AGPL v3 使用。

| 组件 | 来源与许可 | 分发方式 |
| --- | --- | --- |
| 主动消息组件 | DBJD-CR / Pancakes-Labs，astrbot_plugin_proactive_chat，AGPL-3.0 | 随源码分发，保留原有来源和许可声明。 |
| pinyin-pro 3.24.2 | zh-lx，MIT | 随页面分发，脚本和 licenses/pinyin-pro-3.24.2-LICENSE.txt 保留完整许可。 |
| Three.js r160 | three.js authors，MIT | 可选视图通过 CDN 加载，许可见 licenses/three-r160-LICENSE.txt。 |
| AstrBot | AstrBot contributors，AGPL-3.0-or-later | 外部宿主，不随本仓库打包。 |

aiohttp、Pillow、LunarCalendar、ephem 与 pytz 通过依赖安装，各自许可证独立适用，未将它们的库源码打包进本插件。

历史导入来源：部分记忆服务和管理视图源于 Memory Companion；部分陪伴业务和管理视图源于 Private Companion。这些代码与视图经过 Asteria 接线和模块重构，继承代码不声称全原创，原有来源索引和声明保留；正常运行无需旧插件安装。详见 docs/system/FRONTEND_PROVENANCE.md。

原始代码中的版权和来源声明继续保留。用户自行添加的图片、角色、音乐及其他资料，不自动适用本项目代码许可证，使用者需确认相应权利。
