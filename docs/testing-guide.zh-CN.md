# DropNest MVP 测试手册

> 本文是 **Inbox 命令行兼容模式**的回归测试手册。Froganize 0.3.0
> 的日常使用已经改为“桌面评估 → 点击收好桌面 → Timeline 归档”，请优先阅读
> [桌面版使用指南](desktop-guide.zh-CN.md)。本文保留用于维护底层 CLI 和安全逻辑。

这份手册写给第一次测试 DropNest 的维护者。你不需要理解测试代码，也不需要把自己的真实文件交给 DropNest。

完成本手册后，你会验证：

- DropNest 可以安装并启动；
- 自动化测试全部通过；
- 可以初始化一个工作区；
- `preview` 只预览、不移动文件；
- `sort` 能按最后修改时间整理文件；
- 文件夹会作为一个整体移动；
- 重名项目不会被覆盖；
- 隐藏、临时、云占位和符号链接会被跳过；
- 每次成功移动都会写入历史；
- `undo` 能撤销最近一次整理；
- 重复撤销不会破坏文件。

---

## 0. 开始前先看这里

### 你需要使用什么工具？

只需要一个终端。

在 macOS 上任选一种：

1. 打开系统的“终端”应用；或
2. 在 VS Code 中点击菜单 `终端` → `新建终端`。

以下所有灰色代码框中的命令，都要粘贴到终端中执行。一次执行一个步骤，不要把命令粘贴到 Python 文件里。

### 测试会在哪里创建文件？

自动化测试使用 pytest 提供的临时目录。

手动测试使用类似下面的一次性目录：

```text
/tmp/dropnest-manual.A1B2C3/DropNest Test Workspace
```

测试不会使用你的桌面、下载目录、主目录或真实工作文件。

### 哪些事情不要做？

- 不要把真实工作目录当成测试工作区。
- 不要把桌面、主目录或 `/` 当成工作区。
- 不要把本手册中的测试路径替换成真实资料路径。
- 不要使用 `sudo`。
- 不要安装全局 Python 依赖。
- 在看到 `preview` 的结果符合预期之前，不要运行 `sort`。

---

# 第一部分：自动化测试

自动化测试由代码执行，速度最快，也最适合判断当前代码是否健康。第一次测试时，请先完成这一部分。

## 第 1 步：进入 DropNest 项目目录

### 在哪里操作？

在刚刚打开的终端中。

### 执行什么？

```bash
cd "/path/to/DropNest"
pwd
```

### 应该看到什么？

`pwd` 应该完整输出：

```text
/path/to/DropNest
```

如果不是这个路径，先不要继续。重新复制上面的 `cd` 命令。

---

## 第 2 步：激活项目虚拟环境

### 在哪里操作？

仍然在同一个终端、同一个 DropNest 项目目录中。

### 执行什么？

```bash
source .venv/bin/activate
```

然后检查当前 Python：

```bash
which python
python --version
```

### 应该看到什么？

终端命令提示符前通常会出现：

```text
(.venv)
```

`which python` 的结果应该位于 DropNest 项目的 `.venv/bin/python` 中，例如：

```text
/path/to/DropNest/.venv/bin/python
```

Python 版本必须是 3.11 或更高，例如：

```text
Python 3.11.9
```

版本是 3.12 或 3.13 也可以。

### 如果提示 `.venv/bin/activate` 不存在

先确认你处于正确项目目录，然后创建虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 第 3 步：安装 DropNest 和测试依赖

### 执行什么？

```bash
python -m pip install -e ".[dev,gui]"
```

### 这条命令做了什么？

- 将当前项目以开发模式安装到 `.venv`；
- 安装 pytest；
- 创建可直接运行的 `dropnest` 命令；
- 修改源码后不需要反复重新安装。

它不会修改系统 Python，也不需要 `sudo`。

### 应该看到什么？

输出末尾不应出现红色的 `ERROR`。通常会看到类似：

```text
Successfully installed dropnest-0.3.0 ...
```

如果显示 `Requirement already satisfied`，也属于正常结果。

---

## 第 4 步：确认 CLI 可以启动

### 执行什么？

```bash
dropnest --version
```

预期结果：

```text
Froganize 0.3.0
```

再执行：

```bash
dropnest --help
```

### 应该看到什么？

帮助信息中应该包含：

```text
init
preview
sort
status
undo
```

如果终端显示 `command not found: dropnest`，请回到第 2、3 步，确认虚拟环境已激活并完成开发模式安装。

---

## 第 5 步：运行公开仓库预检和全部自动化测试

### 执行什么？

```bash
python scripts/check_public_repo.py
python -m pytest
```

### 应该看到什么？

第一条命令应显示：

```text
Public repository preflight passed.
```

它会检查准备提交的文件中是否混入常见密钥、本机历史、个人绝对路径、构建产物
或异常大的文件。随后 pytest 会列出测试进度，最后一行应该是绿色的通过结果，例如：

```text
... passed in ...s
```

测试数量以后可能增加，所以重点不是固定数字，而是：

- 显示 `passed`；
- 没有 `failed`；
- 没有 `error`。

### 如果测试失败怎么办？

先不要开始手动测试，也不要急着改代码。运行：

```bash
python -m pytest -x -vv
```

这个命令会在第一个失败处停止，并显示更完整的信息。记录以下内容：

1. 失败的测试文件；
2. 失败的测试函数；
3. `AssertionError` 或异常信息；
4. 失败前最后执行的命令。

---

# 第二部分：安全的手动完整测试

自动测试通过后，再进行这一部分。

这套测试会制造一个假的 Inbox，并亲自运行：

```text
init → preview → sort → status → undo
```

所有样本都是临时测试文件。

## 第 6 步：创建一次性测试位置

### 在哪里操作？

继续使用已经激活 `.venv` 的同一个终端。

先确认仍在项目目录：

```bash
pwd
```

然后创建临时目录：

```bash
DEMO_ROOT="$(mktemp -d /tmp/dropnest-manual.XXXXXX)"
DEMO_WORKSPACE="$DEMO_ROOT/DropNest Test Workspace"
printf '临时测试根目录：%s\n' "$DEMO_ROOT"
printf 'DropNest 测试工作区：%s\n' "$DEMO_WORKSPACE"
```

### 应该看到什么？

你会看到两个以 `/tmp/dropnest-manual.` 开头的路径，例如：

```text
临时测试根目录：/tmp/dropnest-manual.A1B2C3
DropNest 测试工作区：/tmp/dropnest-manual.A1B2C3/DropNest Test Workspace
```

后续命令中的 `$DEMO_ROOT` 和 `$DEMO_WORKSPACE` 都代表这两个临时路径。

重要：不要关闭这个终端。如果关闭，两个变量会丢失，需要从第 6 步重新开始。

---

## 第 7 步：初始化测试工作区

### 执行什么？

```bash
dropnest init "$DEMO_WORKSPACE"
```

### 应该看到什么？

开头应该是：

```text
Froganize workspace ready.
```

下面会列出创建的项目，包括：

```text
Inbox
Timeline
.dropnest
config.json
history.jsonl
```

检查实际目录：

```bash
find "$DEMO_WORKSPACE" -maxdepth 3 -print | sort
```

应该能找到：

```text
DropNest Test Workspace/Inbox
DropNest Test Workspace/Timeline
DropNest Test Workspace/.dropnest/config.json
DropNest Test Workspace/.dropnest/history.jsonl
```

### 顺便测试重复初始化

再次运行：

```bash
dropnest init "$DEMO_WORKSPACE"
```

应该继续成功，并显示已有项目被 `Preserved`，而不是删除或覆盖它们。

---

## 第 8 步：放入四个正常测试项目

我们准备三个文件和一个完整文件夹，并人为设置不同的最后修改时间。

### 8.1 创建 `report.pdf`

```bash
printf 'TEST REPORT\n' > "$DEMO_WORKSPACE/Inbox/report.pdf"
touch -t 202605151200 "$DEMO_WORKSPACE/Inbox/report.pdf"
```

它应该被归档到：

```text
Timeline/2026/2026-05/report.pdf
```

### 8.2 创建 `screenshot.png`

```bash
printf 'TEST SCREENSHOT\n' > "$DEMO_WORKSPACE/Inbox/screenshot.png"
touch -t 202606151200 "$DEMO_WORKSPACE/Inbox/screenshot.png"
```

它应该被归档到：

```text
Timeline/2026/2026-06/screenshot.png
```

### 8.3 创建多后缀文件 `research-data.tar.gz`

```bash
printf 'TEST ARCHIVE\n' > "$DEMO_WORKSPACE/Inbox/research-data.tar.gz"
touch -t 202607151200 "$DEMO_WORKSPACE/Inbox/research-data.tar.gz"
```

它应该被归档到：

```text
Timeline/2026/2026-07/research-data.tar.gz
```

### 8.4 创建完整文件夹 `Old Project`

```bash
mkdir -p "$DEMO_WORKSPACE/Inbox/Old Project/src"
printf 'print("test project")\n' > "$DEMO_WORKSPACE/Inbox/Old Project/src/main.py"
touch -t 202511151200 "$DEMO_WORKSPACE/Inbox/Old Project"
```

最顶层文件夹自己的修改时间是 2025 年 11 月，所以整个文件夹应该移动到：

```text
Timeline/2025/2025-11/Old Project
```

内部的 `src/main.py` 不会被拆出来。

---

## 第 9 步：放入五个应该被跳过的项目

### 执行什么？

```bash
printf 'hidden\n' > "$DEMO_WORKSPACE/Inbox/.DS_Store"
printf 'temporary\n' > "$DEMO_WORKSPACE/Inbox/~draft.docx"
printf 'temporary\n' > "$DEMO_WORKSPACE/Inbox/transfer.tmp"
printf 'placeholder\n' > "$DEMO_WORKSPACE/Inbox/photo.jpg.icloud"
printf 'outside workspace test target\n' > "$DEMO_ROOT/external-target.txt"
ln -s "$DEMO_ROOT/external-target.txt" "$DEMO_WORKSPACE/Inbox/external-link"
```

### 为什么要创建这些项目？

| 项目 | 预期跳过原因 |
|---|---|
| `.DS_Store` | 隐藏文件 |
| `~draft.docx` | 临时文件名 |
| `transfer.tmp` | `.tmp` 临时文件 |
| `photo.jpg.icloud` | 可可靠识别的 iCloud 占位形式 |
| `external-link` | 符号链接 |

`external-link` 特意指向工作区外的临时文件，用于确认 DropNest 不跟随符号链接逃出工作区。

---

## 第 10 步：制造一个安全的重名场景

我们提前在目标月份放一个同名文件：

```bash
mkdir -p "$DEMO_WORKSPACE/Timeline/2026/2026-07"
printf 'DO NOT OVERWRITE\n' > "$DEMO_WORKSPACE/Timeline/2026/2026-07/research-data.tar.gz"
```

现在 Inbox 和 Timeline 中各有一个 `research-data.tar.gz`。

DropNest 必须保留原文件，并把新文件计划为：

```text
research-data (1).tar.gz
```

注意它要完整保留 `.tar.gz` 多后缀。

---

## 第 11 步：检查测试前的文件

### 执行什么？

```bash
find "$DEMO_WORKSPACE" -maxdepth 5 -print | sort
```

### 你应该确认什么？

Inbox 中应该有 9 个顶层项目：

```text
report.pdf
screenshot.png
research-data.tar.gz
Old Project
.DS_Store
~draft.docx
transfer.tmp
photo.jpg.icloud
external-link
```

其中：

- 4 个应该移动；
- 5 个应该跳过。

---

## 第 12 步：运行 preview

这是最重要的安全步骤。`preview` 只展示计划，不移动文件。

### 执行什么？

```bash
dropnest preview "$DEMO_WORKSPACE"
```

### 应该看到什么？

正常项目以 `PLAN` 开头，跳过项目以 `SKIP` 开头。

你应该在输出中看到这些目标：

```text
Timeline/2026/2026-05/report.pdf
Timeline/2026/2026-06/screenshot.png
Timeline/2026/2026-07/research-data (1).tar.gz
Timeline/2025/2025-11/Old Project
```

摘要应该是：

```text
Froganize preview.
Planned: 4
Skipped: 5
Failed: 0
```

### 确认 preview 没有移动文件

再次检查 Inbox：

```bash
find "$DEMO_WORKSPACE/Inbox" -maxdepth 3 -print | sort
```

四个正常项目仍应位于 Inbox。此时：

- 不应该出现归档后的 `report.pdf`；
- 不应该出现归档后的 `screenshot.png`；
- `history.jsonl` 应该仍然是空文件。

检查历史行数：

```bash
wc -l "$DEMO_WORKSPACE/.dropnest/history.jsonl"
```

预期为：

```text
0
```

如果 preview 后文件已经移动，立即停止测试，不要运行 sort。

---

## 第 13 步：执行 sort

只有第 12 步完全符合预期时，才进行这一项。

### 执行什么？

```bash
dropnest sort "$DEMO_WORKSPACE"
```

### 应该看到什么？

成功项目以 `MOVED` 开头，跳过项目以 `SKIP` 开头。

摘要应该是：

```text
Froganize completed.
Moved: 4
Skipped: 5
Failed: 0
Archive: .../Timeline
Batch ID: ...
```

Batch ID 每次都不同，这是正常的。

### 检查整理结果

```bash
find "$DEMO_WORKSPACE" -maxdepth 6 -print | sort
```

应该找到：

```text
Timeline/2026/2026-05/report.pdf
Timeline/2026/2026-06/screenshot.png
Timeline/2026/2026-07/research-data.tar.gz
Timeline/2026/2026-07/research-data (1).tar.gz
Timeline/2025/2025-11/Old Project/src/main.py
```

重点确认：

1. 原来就在 Timeline 的 `research-data.tar.gz` 仍然存在；
2. Inbox 中的新文件改名为 `research-data (1).tar.gz`；
3. `Old Project/src/main.py` 仍在文件夹内部；
4. 五个跳过项目仍然留在 Inbox；
5. `external-target.txt` 仍在 `$DEMO_ROOT` 中且没有被移动。

---

## 第 14 步：检查 history

### 执行什么？

```bash
wc -l "$DEMO_WORKSPACE/.dropnest/history.jsonl"
```

预期行数：

```text
4
```

因为有四个项目成功移动，每个项目对应一条历史记录。

查看记录：

```bash
nl -ba "$DEMO_WORKSPACE/.dropnest/history.jsonl"
```

每一行应该是一个 JSON 对象，并包含类似字段：

```text
event_id
batch_id
event_type
source
destination
item_type
classification_time
result
```

四条记录的：

- `event_type` 应该是 `sort`；
- `result` 应该是 `success`；
- `batch_id` 应该相同；
- 历史中不应该出现 `TEST REPORT`、`TEST ARCHIVE` 等文件内容。

---

## 第 15 步：检查 status

### 执行什么？

```bash
dropnest status "$DEMO_WORKSPACE"
```

### 应该看到什么？

关键结果应为：

```text
Valid: yes
Inbox items: 5
Sortable: 0
Skipped: 5
Failed to inspect: 0
Archive months: 4
Latest moved: 4
Latest undo: not_started
Configuration valid: yes
History valid: yes
```

为什么 Inbox 还有 5 个项目？因为它们就是前面故意创建的五个跳过项目。

---

## 第 16 步：执行 undo

### 执行什么？

```bash
dropnest undo "$DEMO_WORKSPACE"
```

### 应该看到什么？

四个项目会以 `RESTORED` 开头。

摘要应该是：

```text
Froganize undo completed.
Restored: 4
Failed: 0
Undo batch ID: ...
```

### 检查恢复结果

```bash
find "$DEMO_WORKSPACE" -maxdepth 6 -print | sort
```

你应该重新在 Inbox 中看到：

```text
Inbox/report.pdf
Inbox/screenshot.png
Inbox/research-data.tar.gz
Inbox/Old Project/src/main.py
```

Timeline 中原本就存在的文件必须仍然存在：

```text
Timeline/2026/2026-07/research-data.tar.gz
```

DropNest 创建的空年份或月份目录可能继续保留。这是当前 MVP 的正常行为，undo 不负责删除空目录。

---

## 第 17 步：检查 undo 历史

### 执行什么？

```bash
wc -l "$DEMO_WORKSPACE/.dropnest/history.jsonl"
```

预期行数：

```text
8
```

其中：

- 前 4 条是 sort；
- 后 4 条是 undo。

查看全部记录：

```bash
nl -ba "$DEMO_WORKSPACE/.dropnest/history.jsonl"
```

undo 记录应该包含 `undo_of_event_id`，用于指出它撤销了哪一条 sort 记录。

---

## 第 18 步：测试重复 undo

### 执行什么？

```bash
dropnest undo "$DEMO_WORKSPACE"
```

### 应该看到什么？

```text
Nothing to undo in the latest sort batch.
```

这条命令应该正常结束，不应该再次移动文件，也不应该覆盖任何内容。

---

## 第 19 步：测试结束

你已经完成全部手动测试。

测试目录位于 `/tmp`，系统之后可以清理它。为了避免误删，不熟悉终端删除命令时可以直接保留，不需要手动删除。

如果你确实要删除，请先查看变量：

```bash
printf '%s\n' "$DEMO_ROOT"
```

只有当输出明确以 `/tmp/dropnest-manual.` 开头时，才可以删除这个一次性目录。

---

# 第三部分：如何判断测试是否通过

全部满足下表，才能判定本轮测试通过。

| 检查项 | 通过标准 |
|---|---|
| Python | 3.11 或更高 |
| CLI 版本 | `Froganize 0.3.0` |
| CLI 帮助 | 包含 init、preview、sort、status、undo |
| pytest | 所有测试 passed，无 failed/error |
| 初始化 | 工作区结构完整，重复初始化不报错 |
| preview | Planned 4、Skipped 5、Failed 0 |
| preview 安全 | 文件未移动，历史仍为 0 行 |
| sort | Moved 4、Skipped 5、Failed 0 |
| 时间分类 | 四个正常项目进入正确年月 |
| 文件夹 | Old Project 保持完整 |
| 重名保护 | 生成 `research-data (1).tar.gz`，原文件未覆盖 |
| 跳过规则 | 五个测试项目留在 Inbox |
| history | sort 后 4 行 |
| status | 工作区、配置和历史有效 |
| undo | Restored 4、Failed 0 |
| undo 历史 | undo 后共 8 行 |
| 重复 undo | 显示 Nothing to undo，不改变文件 |

---

# 第四部分：常见问题

## 问题 1：`command not found: dropnest`

原因通常是虚拟环境没有激活，或者项目尚未安装。

执行：

```bash
cd "/path/to/DropNest"
source .venv/bin/activate
python -m pip install -e ".[dev]"
dropnest --version
```

## 问题 2：`python` 版本低于 3.11

不要使用 `sudo`，也不要覆盖系统 Python。需要安装或选择一个 Python 3.11+ 解释器，然后重新创建 `.venv`。

在处理虚拟环境前先保留完整错误信息，不要直接删除现有 `.venv`。

## 问题 3：`$DEMO_WORKSPACE` 变成空字符串

这通常是因为关闭了创建变量的终端窗口。

不要继续执行剩余手动命令。打开新终端后，从第 1、2、6 步重新开始。

## 问题 4：preview 的数字不是 4、5、0

先运行：

```bash
find "$DEMO_WORKSPACE/Inbox" -maxdepth 3 -print | sort
```

检查是否漏建、拼错或重复创建了测试项目。不要在数字不符合预期时运行 sort。

## 问题 5：出现 `Error:`

普通用户错误默认不会显示很长的 Python traceback。

先保存当前错误。开发者需要定位时，可以把 `--debug` 放在子命令前：

```bash
dropnest --debug preview "$DEMO_WORKSPACE"
```

不要在真实工作区中用 debug 重复执行写操作。

## 问题 6：如何查看上一条命令是否成功？

执行完一条 DropNest 命令后，立即运行：

```bash
echo $?
```

含义：

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 存在项目级失败或状态问题 |
| `2` | 工作区、配置、历史等致命错误 |

---

# 第五部分：日常开发时的最短测试流程

以后每次修改代码，不必都重复整份手动手册。

先执行：

```bash
cd "/path/to/DropNest"
source .venv/bin/activate
python -m pytest
dropnest --version
dropnest --help
```

如果修改的是工作区安全、移动、历史或撤销功能，再额外执行：

```bash
python -m pytest tests/test_workspace.py -v
python -m pytest tests/test_sorter.py -v
python -m pytest tests/test_history_undo.py -v
python -m pytest tests/test_acceptance.py -v
```

准备发布版本或进行 MVP 验收时，再完整执行本手册的手动测试。
