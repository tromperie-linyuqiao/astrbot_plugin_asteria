# 公版原生 MC/PC 的新装入口：准确待办

本页是只读源码结论和下一批接线说明，**未实现、未启动服务、未做新装业务测试**。本次开源交付只确认源码、安装识别和品牌等实际范围，不能依据这份待办声称 MC/PC 已有独立新装运行模式。

## 现有可直接复用的链路

### MC 原生记忆

`NativeServerIntegrations` → `NativeMemoryCompanion` → 原 `MemoryCompanionService` → 原 `MemoryStore`、`ScopedStore`、classifier、summarizer、portrait → `NativeOwnedMCContextRuntime` → 现 Host 的 `runtime.memory`、Unified assembler 与真实 Persona observer。

`native_mc/service.py:MemoryCompanionService.__init__` 已会调用原 Store 的 `initialize()`建立原格式空库，不需再实现记忆数据库、索引或大脑。原 `NativeMemoryCompanion.prepare()`只是为了迁移而先要求现有 `memory_companion.db`，这是新装入口要明确区分的存储前置条件。

`NativeOwnedMCContextRuntime.activate()` 已安装同服务对象的 final-context provider、typed capture router；`main.py:_full_mc()` 与现有请求/群聊/响应 hooks 会读取 `integrations.mc_full`。没有必要再注册第二套 AstrBot Star 或另写捕获循环。

### PC 原生陪伴

`NativeServerIntegrations.observe_native_event(real_event)` → `NativePCFullOwner.observe_event` → 当前 Host 实际 Presence fullscope → 原 SDK conversation/persona selection → `NativePCService.bind_scope(scope,event_id,selected_persona)` → 原 PC 业务 state/host_tick → 原 `NativeBusinessDelivery` → 现统一消息队列。

这条真实范围绑定、事件ID、Persona核对可以直接复用。初始化 API 不能传一个用户名/QQ号/角色名就替代上述真实入站来源。

`NativePCService.initialize()` 已抑制原独立 scheduler/重复 SDK hook 修复/桥 watcher，只让当前 Host 驱动 `host_tick`。原 `NativePCDailyLifecycle` 与目标、计划、音乐读入口也已由 `NativeServerIntegrations._configure_pc_daily()` 接线，复用即可。

## 当前硬性迁移前置条件

| 文件/方法 | 当前行为 | 新装不能如何绕过 |
| --- | --- | --- |
| `native_mc_full_owner.py:_row/start_if_configured` | 必须有旧MC唯一registry；恢复分支检查真实旧实例退休 | 不能伪造一个 activated=false 的旧row或构造retired对象 |
| `native_mc/host_adapter.py:prepare` | 要求已有原格式主库文件 | 不能先touch空文件再声称已有旧库；应让真实原Store创建 |
| `native_pc_full_owner.py:_load_retirement` | 要求 `living_pc_binding_state.source_kind=retired_legacy_pc` 与原源码/配置pin | 不能给fresh用户填写假的hash或退休记录 |
| `native_pc_business/main.py:PrivateCompanionPlugin.__init__` | 构造时立即使用旧PC的 `StarTools.get_data_dir(PLUGIN_NAME)` 并打开持久化 | 不能构造后才改 `service.data_dir`，那时旧文件可能已经打开 |
| `native_pc_service.py:_tls_pin_sources` | 对 `native_pc_business/SOURCE-MANIFEST.json` 的每个实际业务文件校验SHA | 不能改源码却放宽校验；只对明确修改的源码重新生成相应记录 |
| `native_server_integrations.py:start` | 根据旧 full-native flags 构造/恢复迁移owner | 不应直接把私有生产flags/config复制为公版默认 |

## 建议最小实现：显式 fresh 模式，迁移模式保持原约束

不是重写 MC/PC，也不新建第二套权限/调度/模型系统。可增加一个很窄的 `core/living/public_bootstrap.py`，给当前原生业务创建**新的、真实的新装生命周期**。

### 1. 一次明确初始化和持久化标记

- 使用现插件配置保存 `public_native_mode='fresh'`、本模式真实建立时间和schema版本，不使用 `retired_legacy_pc`、旧实例来源或假的 `binding_sha256`。
- 初次 API 只选择 `memory/companion` 两项是否初始化，或无参数沿管理设置；不能提交 scope、Persona、真实入站事件或消息lease。
- 配置采用各自现有 `_conf_schema.json` 的中性默认值，并保存在现有 `living_mc/living_pc` 配置下。原本拥有的人格配置仍由 AstrBot 管理，不复制私人角色卡。
- 初次仅打开原服务和管理接口；scope 仍为空，UI明确「等待真实私聊与角色配置」。主动发送、读他人记忆、设备采集不能因初始化自动获权。
- 重新加载只恢复这个真实 fresh 标记所对应的服务/本插件私有数据路径；不搜索、导入或重放旧插件状态。

### 2. 实际冲突检查

新装只接受原 MC/PC 未安装且无旧运行对象的状态。发现任一旧插件registry条目、对应旧module活跃bridge、其原注册hook/tool/web入口，或现有其他owner实例时拒绝fresh并指向原迁移入口。

检查函数须在启动和后续现有 `legacy_quiesced/legacy_closed` callback 所需位置重新检查实际环境。它表达的是「没有冲突旧执行者」，不能写成无条件 `lambda: True` 或叫「旧实例已退休」。不需要为此发明全服务器审计框架。

若当前 TLS 有已经建立的旧切片 runtime，先沿其现有 close/drain 正常关闭，确认无在途后再接完整原生服务。不能让 typed capture 或最终上下文两边同时运行。

### 3. MC 的一个存储接缝

在 `NativeMemoryCompanion` 构造/prepare增加显式 `storage_mode='migrated'|'fresh'`，默认仍为migrated，原既有DB检查保持。

fresh时允许在本插件自己的 `public_native/memory/` 路径由 `MemoryCompanionService` 正常建立原 `memory_companion.db` / `req041_scoped.db`。这是原组件的新装库，不是另建一套记忆数据模型。

保留已存在来源不明数据时应拒绝覆盖；后续 fresh 模式重载则复用自己上次建立的数据。不要空文件伪装旧库，不接旧历史，不改旧库权限，不批量归属旧画像。

创建顺序复用原完整owner的实际顺序：

1. 构造一份 `NativeMemoryCompanion`，`integrations.mc_full` 指向它。
2. `await companion.prepare()`，由原服务创建/打开真实Store。
3. `runtime=NativeOwnedMCContextRuntime(plugin,host,companion)`，`integrations.mc=runtime`。
4. 沿现有 flags/配置接好 context 写入门禁，`await runtime.activate()`。
5. `await companion.start_workers(context_ready=真实runtime状态)`。
6. `companion.register_routes()`，沿原 `_register_tools('mc')`、`_toggle_full_commands('mc',True)`。

`_mc_full_owner` 可使用一个fresh生命周期薄控制器，至少实现现有调用方实际使用的 activate/start_if_configured/stop/close/status；`restore_legacy`在本模式明确不支持，不假造旧owner。

### 4. PC 的一个构造前数据路径参数

- `native_pc_business/main.py:PrivateCompanionPlugin.__init__` 增加可选keyword `data_dir=None`，在任何 `_rebuild_store_manager/_load_data` 前选择提供路径；默认保留原路径逻辑。
- `NativePCService.__init__` 接收并传给super，新装提供本插件 `public_native/companion/`。不能先构造后挪目录。
- 只重算SOURCE-MANIFEST中实际修改的 `main.py` 项；其他原业务SHA保持，Source guard保持。
- fresh controller可复用 `NativePCFullOwner` 的真实事件观察、`_authorize` Host权限、`_send`/platform adapter、tick和停止排空，但不能走它的 `_capture_old/_load_retirement`。
- `source_current/status`须反映当前真实新服务和其本地source pin，不能冒充旧源码或旧配置pin。原插件不存在应显示 `original_present=false`/fresh，不写「旧已停用/退休成功」。
- 服务仍是单份 `NativePCService`，传现有Host journal、现有 `NativeBusinessDelivery.dispatch/platform_action` 和音乐读adapter；`initialize/register_native_routes`沿现有方法。

### 5. NativeServerIntegrations 的选择和生命周期

- 启动时仅在显式fresh配置下选择上述控制器；私有生产迁移和原restore不改。
- 初始化成功后继续调用现有 `_refresh_native_crosslinks()`、`_configure_pc_daily()`，让 MC 使用同一个 PC extension_api，让主事件入口沿现有 `observe_native_event` 观察真实来源。
- 复用 `NativeServerIntegrations.close()` 的先关接纳、runtime drain、服务关闭顺序。失败保留对象引用/状态，不在未知时覆盖或再初始化。
- API重复初始化对已active同一对象只读返回状态，不创建第二份service。改变模式需先正常stop并核对，而不是自动调用旧restore。

### 6. 正常API与轻量UI

可在现有 `NativeServerIntegrationWebApi` 中追加 `public-native/status` GET、`public-native/initialize` POST、`public-native/stop` POST，复用 `_service()` 的 AstrBot登录和现有操作错误语义，不开平行HTTP服务。

现统一Console的服务卡增加「初始化原生记忆与陪伴」入口及真实fresh/awaiting_scope/active/blocked状态；不是管理员登录后默认制造用户scope。原模块管理UI与配置复用，不新造全部设置页。

## 预计涉及文件

1. 新 `core/living/public_bootstrap.py`：fresh控制器/状态、真实冲突检查、初始化入口。
2. `core/living/native_mc/host_adapter.py`：仅显式存储模式接缝。
3. `core/living/native_pc_service.py`：传递新装数据目录。
4. `core/living/native_pc_business/main.py`：构造前可选数据目录。
5. `core/living/native_pc_business/SOURCE-MANIFEST.json`：仅对应改动项重算。
6. `core/living/native_server_integrations.py`：mode选择、恢复、工具/command/交叉链接/关闭接线。
7. `server_integration_web_api.py`：现有鉴权下的三个窄操作。
8. 当前Console服务卡JS/HTML或配置schema中所需最小入口；不改聊天发送职责。

这些是必要的实际接线，不能只加按钮或新增说明文档后标为fresh功能完成。

## 后续一次集中验收重点

- 无旧MC/PC源码、registry和数据库的干净AstrBot环境实际初始化，真实Store schema建立，模式/状态回读。
- 真正私聊入站与原SDK Persona选择后，绑定完整scope、正常记忆/上下文/原PC读取；冷管理员调用仍无scope。
- 同API重复调用、reload恢复用同一份持久化，服务不重复、旧模式不误启。
- 存在旧注册者、已占用目标目录、来源未知数据时拒绝fresh，不停止旧插件，不覆盖资料。
- 原stop/close排空和失败保留对象；不把新的空库初始化误称旧资料迁移成功。

本次没有执行上述测试。本说明只用于下一批实施，不修改当前公版代码或生产服务。
