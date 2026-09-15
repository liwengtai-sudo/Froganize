# Froganize 项目交接简报

> 当前版本：`0.3.0`
> 当前状态：macOS Unified Prototype

## 这是什么？

Froganize 是一个 macOS 桌面一键收纳工具。它的新主线只解决一个高频
问题：**不在 Finder 里来回拖拽，点一次“收好桌面”，就把当前桌面收成
一个可撤销的整批快照。**

```text
打开 Froganize
→ 点击“收好桌面”
→ 扫描 Desktop 第一层
→ 排除不安全或不应移动的项目
→ 每个项目按自己的分类时间进入 Timeline/YYYY/YYYY-MM/
→ 可打开收纳结果，也可撤销最近一批
```

- 产品名：**Froganize**
- 吉祥物：**蛙仔**
- 标语：**给桌面一点整理魔法。**
- Python 包和兼容 CLI 仍叫 `dropnest`。

> 开发状态：一键“收好桌面”主线已实现，包括按月归档、安全排除、
> history、跨月整批撤销和原生主界面。

## 用户看到的两个能力

### 主应用

`Froganize.app` 打开原生 PySide6 窗口。主界面只突出一个主操作：

- 主按钮：**收好桌面**；
- 点击本身就是对本次整批移动的明确授权，不再追加勾选和二次确认；
- 处理 Desktop 第一层的普通文件和文件夹，文件夹永远整体移动；
- 每个项目按自己的分类时间进入 `Timeline/YYYY/YYYY-MM/`，不创建根级时间戳批次目录；
- 普通文件使用 `st_mtime`；文件夹使用其可读树中最新的 `mtime`，仍整体移动；
- 同一次点击在 history 中共享一个 batch ID，即使项目跨月也可整批撤销；
- 完成后显示移动、跳过和失败数，并提供“打开收纳结果”与“撤销”；
- 截图智能保留在次要入口，不与“收好桌面”争夺主流程。

主整理流程读取元数据，不读取普通文件内容，也不发起网络请求。

高频操作不需要用户理解时间阈值、评估分组或 Timeline 规则。旧 `dropnest`
CLI 仍保留 Inbox 来源和命令交互；它与原生一键主线共用
`Timeline/YYYY/YYYY-MM/` 存档结构。

### 主流程默认排除

下列项目必须留在桌面并显示跳过原因：

- `Froganize.app`、当前桌面快捷方式和已知旧启动器名；
- 隐藏项目；
- 临时文件和未完成下载；
- 符号链接；
- 云端占位、无法读取、不支持类型或任何无法安全处理的项目。

第一版宁可跳过也不猜测，不使用私有云盘 API 追求覆盖所有占位类型。

### 截图智能菜单栏 Agent

嵌套的 Swift 菜单栏组件负责：

- 监听用户明确选择的截图目录；
- 识别支持的系统截图名；
- 在用户明确开启后，把匹配截图发送给所选 AI Provider；
- 显示最近处理结果、暂停/继续、手动处理和设置。

正式打包环境中的 API Key 只从 macOS Keychain 读取。

## 融合架构

没有把 Python 重写成 Swift，也没有把 Swift 重写成 Python。

```text
Swift watcher / Vision provider
        │
        │ schema v1 JSON over stdin/stdout
        ▼
FroganizeFileOps (Python helper)
        │
        ├── validate authorized root + direct child
        ├── recheck pre-AI filesystem snapshot
        ├── sanitize and bound Unicode filename
        ├── allocate case-insensitive collision name
        ├── atomic no-overwrite rename
        ├── append activity / rollback / recover journal
        └── typed rename undo
```

Swift 不再直接调用文件移动 API，也不再拥有权威改名历史。AI 只能提供：

- `title`
- `summary`
- `category`
- `confidence`
- `sensitive`

AI 不能提供任意路径或决定最终文件操作。

## 关键 Python 模块

| 模块 | 作用 |
| --- | --- |
| `gui.py` | 主窗口、一键收纳状态、撤销与次要截图智能入口 |
| `desktop_app.py` | GUI 与安全整理核心之间的应用服务 |
| `planner.py` | Desktop 第一层元数据扫描、排除规则和确定性批次计划 |
| `sorter.py` | 执行按钮触发的批次计划、归档历史与撤销 |
| `intelligence_contract.py` | 严格、版本化 JSON 合同 |
| `agent_cli.py` | 单请求 stdin/stdout helper 入口 |
| `screenshot_operations.py` | 截图改名与撤销的确定性文件权限边界 |
| `intelligence_history.py` | 配置、活动 JSONL、journal 和 lock |
| `intelligence_status.py` | 不产生写入的主界面状态投影 |

## 不能破坏的安全边界

1. 打开应用不移动文件；用户点击“收好桌面”才是本次移动授权。
2. 文件夹始终作为一个整体，不拆散内部项目。
3. 不跟随符号链接，不允许路径穿越。
4. 按钮触发的规划和执行共用同一份计划，执行前复核来源快照。
5. 任何改名、归档和撤销都不得覆盖已有项目。
6. Screenshot Intelligence 默认关闭，上传前必须明确开启。
7. 截图上传前在 Swift 侧排除符号链接；AI 返回后 Python 再复核原文件。
8. Provider、网络、AI 响应或 helper 失败时宁可跳过，不能丢文件。
9. API Key 不进入 JSON、历史、日志或 Git。
10. 测试只使用临时目录和假 Provider/helper，不接触真实 Desktop。

## 本地状态

归档历史仍在工作区：

```text
WORKSPACE/.dropnest/history.jsonl
```

截图智能的非秘密状态默认在：

```text
~/Library/Application Support/Froganize/
├── intelligence/config.json
├── intelligence/activity.jsonl
└── operations/
```

两类历史在 0.3 中保持不同事件语义；主窗口只读展示截图智能摘要。截图图片和 API Key
不会写入这些历史。

## 如何运行与测试？

Python：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,gui,packaging]"
python -m pytest -q
```

Swift Agent（已迁入主仓库）：

```bash
cd swift/ScreenshotIntelligence
TZ=UTC swift run --disable-sandbox ScreenshotRenamerSelfTest
./Scripts/build-app.sh
```

使用已安装的真实 Python helper 跑跨语言临时目录闭环：

```bash
FROGANIZE_E2E_HELPER="$(cd ../.. && pwd)/.venv/bin/froganize-fileops" \
  TZ=UTC swift run --disable-sandbox ScreenshotRenamerSelfTest
```

统一本地原型：

```bash
./scripts/build_unified_macos_prototype.sh
open "dist/unified/Froganize.app"
```

该产物是 ad-hoc 签名的本机开发原型，不是 Developer ID 签名或 Apple 公证的公开版。

## 品牌和界面原则

- **Froganize** 名称、黄色蛙仔和“文件夹魔法杖”故事必须保留。
- 蛙仔用来表达空闲、检查、收纳、完成、部分失败和撤销状态。
- IP 是品牌和情感反馈，不得变成额外教程、故事关卡或操作步骤。
- 主界面的信息层级必须服务于一个按钮，不让截图智能或旧评估界面喧宾夺主。

## 当前限制

- Swift 源码、构建脚本、隐私描述和自检已经迁入
  `swift/ScreenshotIntelligence/`，统一构建不再依赖相邻项目。
- 没有使用真实 API Key 或执行付费 Provider 测试；Provider 行为通过解析和错误路径测试。
- 归档操作和截图改名各自使用安全锁与原子操作，但尚未共享同一个跨操作全局 lock；
  并发冲突依靠快照复核和原子 no-overwrite 安全失败。
- 截图活动与 Timeline 归档历史尚未合并成完整的统一活动时间线。
- 本地应用尚未 Developer ID 签名、公证或适合公开下载。

## 下一位维护者先做什么？

1. 先读 `FROGANIZE_MERGE_PLAN.md`、`docs/architecture.md`、本文件和 `git status`。
2. 不要 `reset`、`clean` 或覆盖当前大量未提交的产品工作。
3. 一键批次规则继续由 planner/sorter 维护，不把文件规则移入 GUI
   或 AI prompt。
4. 用临时目录添加失败路径测试后再改变文件行为。
5. 未经授权不执行 `git commit`、`git push` 或发布。

> 一句话记住：主线是“一键把桌面收进月度 Timeline”；蛙仔给出状态，Python
> 负责安全执行，截图 AI 只是次要能力。
