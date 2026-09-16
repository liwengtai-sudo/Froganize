<p align="center">
  <img src="src/dropnest/web_assets/froganize-organizing.svg" width="220" alt="Froganize 蛙仔拿着文件夹魔法杖">
</p>

<h1 align="center">Froganize</h1>

<p align="center"><strong>给桌面一点整理魔法。</strong></p>

Froganize 是一个本地优先、可撤销的 macOS 桌面文件整理工具。
它把 Desktop 第一层中可安全处理的文件和完整文件夹，按最后修改时间收进按年、月排列的 Timeline。

```text
Desktop/report.pdf
    ↓
Timeline/2026/2026-07/report.pdf
```

当前目标是 **v0.3.0 源码公开测试版**。仓库将首先提供可审阅、可测试、
可从源码运行的版本；暂不提供或承诺经过签名、公证的 macOS 安装包。

公开仓库：<https://github.com/liwengtai-sudo/Froganize>

![Froganize 当前原生界面，使用合成临时文件生成](media/github/native-dashboard.png)

## 主要功能

- **一键收好桌面**：原生 macOS 界面只需一次点击。
- **按月归档**：按项目最后修改时间进入 `Timeline/YYYY/YYYY-MM/`。
- **文件夹整体移动**：只处理 Desktop 第一层，不拆散文件夹内部结构。
- **绝不覆盖**：同名时使用 `report (1).pdf`、`Project (1)` 等安全名称。
- **安全跳过**：应用程序、隐藏项、临时文件、未完成下载、符号链接和无法安全判断的项目留在原位。
- **整理日历**：按操作日期查看整理批次和文件去向，并安全撤销最近一次整理。
- **CLI 工具**：支持初始化、预览、执行、状态检查和撤销。
- **截图智能（实验性集成）**：采用 BYOK，由用户填写 HTTPS OpenAI Chat
  Completions 兼容接口、模型名称和 API Key。完整 Swift 后台源码位于
  `swift/ScreenshotIntelligence/`。基础文件整理不需要 AI、API Key 或网络。

## 整理规则

### 时间依据

- 普通文件使用文件的 `st_mtime`（最后修改时间）。
- 顶层文件夹使用文件夹及其可读后代中最新的修改时间。
- 归档时转换为本地时区的年份和月份。
- 不使用文件创建时间，也不使用点击“收好桌面”的时间命名文件夹。

### 目标结构

```text
FroganizeWorkspace/
├── Inbox/                 # CLI 兼容入口
├── Timeline/
│   ├── 2025/
│   │   └── 2025-12/
│   └── 2026/
│       ├── 2026-07/
│       └── 2026-08/
└── .dropnest/
    ├── config.json
    └── history.jsonl
```

一次点击可能把不同项目收进不同月份。它们在历史中共享一个 batch ID，
所以仍然可以一次撤销；Timeline 中不会额外创建时间戳批次文件夹。

## 开始使用

第一次使用可以直接阅读[一分钟图文教程](docs/tutorial.zh-CN.md)。

### 环境要求

- macOS（原生图形界面仅在 macOS 上维护）
- Python 3.11+
- Git（只在通过 Git 获取源码时需要）
- Swift 5.9+ 和 macOS 13+（仅在构建可选的 Screenshot Intelligence 组件时需要）

### 从源码安装

克隆仓库后，在项目根目录执行：

```bash
git clone https://github.com/liwengtai-sudo/Froganize.git
cd Froganize
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,gui]"
```

### 启动原生界面

```bash
python -m dropnest.macos_app
```

打开应用只会读取 Desktop 第一层的文件系统元数据。
只有点击 **收好桌面** 后才会移动项目。

侧栏的 **整理日历** 会用金色日期标出有整理记录的日子。点击日期可以查看
当时移动的项目、目标路径和撤销状态；出于文件安全考虑，只有最近一次尚未
完全撤销的整理可以执行撤销，较早批次保持只读。

默认工作区是：

```text
~/Documents/FroganizeWorkspace
```

如果已存在 `~/Documents/DropNestWorkspace`，应用会继续使用这个旧工作区，
避免分裂现有 Timeline 和历史。

### 源码预览版的边界

- 当前 GitHub 候选只发布源码，不提交 `.app`、`.dmg`、虚拟环境或本机历史。
- `python -m dropnest.macos_app` 可以运行完整的一键整理、日历和撤销主线。
- `scripts/build_macos_distribution.sh` 可构建整理器本地测试包，但产物不是公开安装包。
- `scripts/build_unified_macos_prototype.sh` 使用仓库内 Swift 截图组件构建统一本地
  原型；生成的应用仍未经过 Developer ID 签名或 Apple 公证。
- 当前原生界面面向 Apple Silicon Mac；其他平台仍可运行部分 Python CLI 流程，
  但没有经过桌面产品验收。

## CLI 用法

CLI 仅处理明确指定工作区中 `Inbox/` 的第一层项目，适合开发和测试。

```bash
dropnest --help
dropnest --version

dropnest init /tmp/FroganizeDemo
dropnest preview /tmp/FroganizeDemo
dropnest sort /tmp/FroganizeDemo
dropnest status /tmp/FroganizeDemo
dropnest undo /tmp/FroganizeDemo
```

用临时目录进行安全体验：

```bash
dropnest init /tmp/FroganizeDemo
printf 'demo' > /tmp/FroganizeDemo/Inbox/report.txt
dropnest preview /tmp/FroganizeDemo
dropnest sort /tmp/FroganizeDemo
dropnest undo /tmp/FroganizeDemo
```

## 安全原则

Froganize 的文件操作默认保守：

- 只处理获得授权的 Desktop 或工作区 `Inbox/`。
- 只移动来源目录的第一层项目。
- 使用解析后的绝对路径校验工作区边界。
- 不跟随符号链接离开授权范围。
- 执行前重新检查源项目是否在规划后发生变化。
- 目标名称大小写无关检查，永不覆盖现有文件或文件夹。
- 历史只记录路径、时间和操作结果，不记录文件内容。
- 一个项目失败不会破坏其他项目或覆盖原有数据。

## 运行测试

所有文件操作测试都使用 pytest 临时目录，不会访问真实 Desktop、
Downloads 或用户主目录中的个人文件。

```bash
source .venv/bin/activate
python scripts/check_public_repo.py
pytest
python -m build
cd swift/ScreenshotIntelligence
swift run --disable-sandbox ScreenshotRenamerSelfTest
./Scripts/check-keychain-access-policy.sh
```

最近本地验证：完整测试见当前开发报告。

构建包含主界面、Python 文件操作助手和 Swift 截图智能组件的统一本地应用：

```bash
./scripts/build_unified_macos_prototype.sh
```

生成的 `dist/unified/Froganize.app` 仅供本地开发验证，没有经过
Developer ID 签名或 Apple 公证。

## 项目结构

```text
src/dropnest/
├── cli.py                 # 命令行入口
├── workspace.py           # 工作区和路径安全
├── planner.py             # 只读扫描和移动计划
├── sorter.py              # 安全执行和撤销
├── conflict.py            # 同名处理
├── history.py             # JSONL 历史
├── desktop_app.py         # 原生应用服务层
├── gui.py                 # Qt 原生界面
└── intelligence_*.py      # 实验性截图智能

swift/ScreenshotIntelligence/ # Swift 监听、AI Provider 与菜单栏组件
tests/                      # 临时目录测试
docs/                       # 需求、架构和开发记录
```

## 当前边界

当前 Public Beta 不做：

- App Store 上架和应用内购买。
- 用户账号、云同步或网络存储。
- 自动监听 Desktop 或后台常驻整理。
- 读取文档内容、全文索引或基于内容自动分类。

## 贡献

这是一个小型开源项目。欢迎提交 Issue 报告问题、安全边界或使用上的困惑。
修改代码前请先运行完整测试。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

问题反馈请参考 [SUPPORT.md](SUPPORT.md)，安全问题请参考
[SECURITY.md](SECURITY.md)，本地数据边界见 [PRIVACY.md](PRIVACY.md)。

## 许可证

Froganize 使用 [MIT License](LICENSE)。第三方依赖的许可与说明见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

**English summary:** Froganize is a local-first, reversible macOS Desktop
organizer. It moves safe top-level files and whole folders into
`Timeline/YYYY/YYYY-MM/` according to their last modification time. The current
release target is a source-only public beta. Signed and notarized macOS binaries
are intentionally out of scope until a separate distribution review is complete.
