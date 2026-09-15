# Froganize 社交发布手册（历史素材）

> 本文与 `media/xiaohongshu/` 保留早期“7 天建议 + 逐项选择”方向的宣传草稿。
> 当前暂不发布这些内容；未来如恢复宣传，必须先按根目录 README 的一键主线重做。

这份手册把 GitHub 与小红书素材串成一个真实、不过度营销的发布流程。

## 发布定位

一句话：

> 一只让你先看清、再选择、还能撤销的桌面整理青蛙。

内容重点不是“自动化有多强”，而是：

1. 桌面杂乱但不等于想删除；
2. 推荐和决定应该分开；
3. 文件工具必须克制、可解释、可恢复；
4. 代码和安全规则可以公开检查。

## 素材索引

- GitHub 主视觉：`media/github/hero.png`
- GitHub Social Preview：`media/github/social-preview.png`
- 功能图：`media/github/features.png`
- Before / After：`media/github/before-after.png`
- 流程图：`media/github/workflow.png`
- 吉祥物立绘与场景：`media/brand/`
- 三套小红书封面：`media/xiaohongshu/covers/`
- 七张正文图：`media/xiaohongshu/slides/`
- 标题、正文、标签与 CTA：`media/xiaohongshu/copy.zh-CN.md`

## GitHub 发布后要做的联动

1. 在仓库 About 中添加一句清晰描述和相关 Topics。
2. 在 Settings → Social preview 上传
   `media/github/social-preview.png`。
3. 把真实仓库 URL 填入小红书文案。
4. 把真实小红书主页填入 README 的 Community 区域。
5. 小红书置顶评论补充 GitHub 链接和当前安装限制。
6. GitHub Issue 模板收集来自小红书的复现信息，不让反馈散落在评论区。

## 首发节奏

### 第一篇：为什么重新设计

- 封面：`cover-01-mascot.png`
- 重点：从 Inbox 流程转向“桌面 → 评估 → Timeline”
- CTA：询问用户最怕整理软件做什么

### 第二篇：真实使用流程

- 封面：`cover-03-product.png`
- 重点：一周建议、三个结果、默认全不选、确认收起与撤销；清理只在更多工具中出现
- CTA：邀请 Developer Preview 测试

### 第三篇：文件安全怎么做

- 封面：`cover-02-pain-point.png`
- 重点：规划/执行分离、同名不覆盖、变更检测、元数据历史
- CTA：引导到 GitHub 的 architecture 与 tests

## 发布前核对

- [ ] 所有 `{{...}}` 占位符已替换。
- [ ] GitHub remote 与仓库 URL 已确认。
- [ ] 小红书主页或账号名已确认。
- [ ] README 中的安装方式与当前发布产物一致。
- [ ] Social Preview 小于 1 MB。
- [ ] 截图没有用户名、真实路径或个人文件。
- [ ] 没有声称 Windows、DMG、Homebrew 或 PyPI 已经可用。
- [ ] 没有空的 Star History。
- [ ] 最新完整测试通过。
- [ ] 置顶评论说明这是 Developer Preview，重要文件请保持备份。
