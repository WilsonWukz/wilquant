# ADR-0001：vn.py 运行时边界

- 状态：有条件批准；仅批准“若采用 vn.py，则必须独立进程”的边界，运行时选型与实现未批准
- 日期：2026-07-20
- 决策范围：候选 vn.py 的进程隔离约束，不改变 Phase 2B、Phase 2C 顺序

## 背景

项目是 React + FastAPI 模块化单体，以 SQLite 保存控制状态，以 Parquet + DuckDB 保存和查询研究数据。项目自己的领域模型、A 股规则、OrderIntent、确定性风险、人工确认和审计链必须保持权威。

vn.py 被研究为可选的事件、OMS 和 Gateway 基础设施，而不是产品框架或领域模型。它不是已选定的唯一交易运行时；直接 QMT/XtQuant 或其他官方能力的独立 Adapter 仍保留。当前仓库尚无 Broker、回测、OrderIntent 或 vn.py 实现。

官方 vn.py 4.4.0 支持 Python 3.13，但核心依赖包含 PySide6、TA-Lib、NumPy 和 pandas。更关键的是，`MainEngine()` 构造会立即启动 EventEngine，并改变进程当前目录。真实 Gateway 还可能携带原生 DLL、账户单例和专属运行环境。

## 条件性决策

如果未来另行批准采用 vn.py，它必须运行在独立本地进程：

```text
React
  → FastAPI / 项目 Application Services
    → 项目内部 Ports
      → 本地 IPC Client
        → Vnpy Runtime Process
          → EventEngine / MainEngine / OMS / Gateway
```

具体边界：

1. 主后端的默认依赖和启动路径不导入 `vnpy`。
2. `domain/`、`application/`、API、策略、风险和 AI 不得导入 vn.py。
3. 只有 `integrations/vnpy/` 与 `infrastructure/brokers/vnpy/` 可引用 vn.py。
4. V1 只用 `importlib.metadata`/模块发现检查可用性，不构造 MainEngine。
5. V2 才允许在独立进程中构造运行时；不注册真实 Gateway，不打开 Qt GUI。
6. FastAPI 只持有项目内部 Port 或 IPC client，不持有 MainEngine/Gateway。
7. 默认配置全部禁用；未知 Gateway 拒绝加载；真实执行路径在 V8 明确授权前始终拒绝。
8. Phase 2A 的本地文件 Provider 与质量管道不依赖 vn.py；未来 VnpyMarketDataProvider 只是额外来源。

## 本 ADR 不代表

- 不代表已批准安装、检测、启动或实现 vn.py；Phase V1 仍需新的明确授权。
- 不代表 vn.py 是唯一或优先交易运行时；QMT/XtQuant 等能力可以通过不依赖 vn.py 的独立 Adapter 接入。
- 不改变 Phase 2B、Phase 2C 的优先级，也不授权进入任何交易接入阶段。
- 不改变当前系统只有 RESEARCH 模式的事实。

## 选择独立进程的理由

- 隔离 `os.chdir`、线程、Qt、TA-Lib 和 Gateway 原生库副作用。
- vn.py 或 Gateway 崩溃时不直接拖垮核心 Web/API。
- 可以用操作系统进程边界限制交易依赖和凭据范围。
- 更适合未来 QMT/XtQuant 的 Windows 专属环境。
- 核心项目在未安装 vn.py 时仍可完整启动、导入数据、回测和模拟。

## 被否决的方案

### 与 FastAPI 同进程

优点是实现和对象调用简单，但 `MainEngine` 的自动线程启动与进程级工作目录变更会污染 FastAPI 生命周期；重型 GUI/原生依赖也会进入核心环境。仅在独立实验中可用于对照，不作为目标架构。

### Fork 或复制 vn.py 源码

会造成升级困难、许可证维护负担和领域边界混乱。默认只使用固定版本的外部依赖；上游缺陷优先通过 Adapter/Subclass 处理。

### 让浏览器或策略直接访问 vn.py

会绕过项目的风险、人工确认、审计和数据质量管道，违反安全边界，永久禁止。

## 进程生命周期

```text
FastAPI 启动
  → 读取安全默认配置
  → 默认不启动 vn.py 进程

显式只读启用（V2+）
  → 校验模式和 allowlist
  → 启动本地 runtime 子进程
  → 完成版本/协议握手
  → 不连接 Gateway

显式只读连接（V6，另行授权）
  → 权限检查
  → 加载 allowlist 中的 READ_ONLY Gateway

FastAPI 关闭
  → 停止订阅
  → 请求 runtime 关闭 Gateway/MainEngine
  → 等待退出
  → 超时后标记异常并保留审计
```

不得在模块导入或普通 API 请求中启动 MainEngine。

## 数据与事件边界

```text
vn.py Event
  → Vnpy Mapper
  → Internal Event Envelope
  → IPC
  → Application Service
  → 幂等/去重/对账
  → SQLite 业务快照与追加审计
  → WebSocket DTO
```

不得序列化 vn.py 对象直接发送给前端。所有 Decimal、时区、交易所、外部 ID 和账户脱敏规则由集中 Mapper 处理。

## 安全配置

若未来授权实施，候选配置沿用现有 `QUANT_LAB_` 前缀；以下变量当前尚未进入 `.env.example` 或运行代码：

```dotenv
QUANT_LAB_VNPY_ENABLED=false
QUANT_LAB_VNPY_AUTO_START=false
QUANT_LAB_VNPY_AUTO_CONNECT=false
QUANT_LAB_VNPY_TRADING_ENABLED=false
QUANT_LAB_VNPY_RUNTIME_MODE=process
QUANT_LAB_VNPY_GATEWAY_ALLOWLIST=[]
QUANT_LAB_VNPY_DATA_GATEWAY=
QUANT_LAB_VNPY_TRADING_GATEWAY=
```

`TRADING_ENABLED=true` 永远不是充分条件。V8 前没有能够成功执行真实委托的代码路径。

## 升级策略

1. 固定经过验证的 vn.py 和 Gateway 版本，不跟随浮动 master。
2. 在独立兼容性环境更新锁文件并运行无 vn.py、假运行时、事件映射和架构测试。
3. 对对象字段、枚举、事件名和生命周期做契约测试。
4. 先升级测试运行时，再升级只读环境；真实 Gateway 需要单独批准。
5. 不静默修改 `site-packages`；必要补丁必须独立、可追踪并带测试。

## 回滚策略

- 若未来实施，保持候选 `QUANT_LAB_VNPY_ENABLED=false` 即可回到纯核心模式。
- 运行时进程、IPC client 和 Adapter 均为可移除基础设施，不改变领域表的权威语义。
- 禁用或卸载 vn.py 不得阻止核心后端、前端、本地导入、自有回测或 PaperBroker。
- 事件同步只追加审计和校正记录，不通过回滚删除历史事实。

## 结果与技术债

- 独立进程需要定义认证的本地 IPC、协议版本、超时和背压策略；在 V2 计划中确定。
- MainEngine 的工作目录副作用需要在 runtime 子进程内显式隔离。
- PySide6/TA-Lib 的安装可用性必须在独立环境验证，不能污染当前核心环境。
- QMT/XtQuant 兼容性必须在 V6 授权前单独形成评审文档。
