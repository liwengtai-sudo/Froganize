# 一分钟学会 Froganize

[English](tutorial.md) · [安全合成兼容性 Demo](../demo/README.md)

> **macOS 源码公测版。** 当前仓库暂不提供经过签名、公证的安装包。第一次使用
> 任何文件整理工具前，请备份重要文件。

![使用合成临时文件生成的 Froganize 当前原生界面](../media/github/native-dashboard.png)

Froganize 会把 Desktop 第一层中所有可安全移动的项目，按最后修改月份收进
`Timeline/YYYY/YYYY-MM/`。仅仅打开应用不会移动任何内容。

## 第一步：从源码安装

在仓库根目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,gui]"
```

需要 macOS 和 Python 3.11 或更高版本。当前原生界面主要在 Apple Silicon Mac
上测试。

## 第二步：打开 Froganize

```bash
python -m dropnest.macos_app
```

应用会在 Documents 中创建或继续使用本地工作区，只评估 Desktop 最外层项目，
并告诉你哪些可以移动、哪些必须留在原位。评估只读取文件系统元数据，不读取
文档内容。

macOS 第一次使用时可能询问 Desktop 文件夹权限。只有在你希望 Froganize 检查
并整理桌面时才允许。

## 第三步：查看评估结果

- 普通文件和完整文件夹在安全时会进入待收好范围。
- 隐藏项、临时文件、未完成下载、符号链接、应用程序和无法安全判断的项目会
  留在原位，并显示原因。
- 文件夹永远作为一个整体，不会拆开内部内容。

普通文件使用 `st_mtime`；文件夹使用可读目录树中最新的修改时间。不会使用
创建时间，也不会用点击按钮的当前时间给目录命名。

## 第四步：点击“收好桌面”

点击一次，就授权执行当前显示的准确计划。每个安全项目进入自己的修改月份：

```text
Desktop/report.pdf  →  Timeline/2026/2026-07/report.pdf
```

不同月份的项目仍共享同一个历史批次。同名时会使用 `report (1).pdf` 等新名称，
绝不覆盖已有文件或文件夹。

## 第五步：查看记录或撤销

打开“整理日历”，可以按日期查看批次、原始名称和目标位置。Froganize 可以撤销
最近一次尚未撤销的成功桌面整理。目标已经消失或原位置已有同名项目时，会明确
报告并停止该项目，不会覆盖。

## 可选的截图智能

截图智能目前是默认关闭的实验功能，需要使用者自己的兼容 AI Provider 凭证。
完整 Swift 后台源码位于 `swift/ScreenshotIntelligence/`。桌面整理、日历和撤销
都不需要 AI，也不需要网络。

## 不碰真实桌面也能练习

请使用[安全合成兼容性 Demo](../demo/README.md)。它只在临时目录创建测试文件，
用于验证保留的安全、同名冲突和撤销逻辑，不会接触真实桌面。

日常主线只有：**打开 → 看一眼 → 收好桌面 → 完成**。
