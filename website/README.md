# Froganize 官网

`website/` 是可直接部署到 GitHub Pages 的纯静态官网。它介绍当前
Froganize 0.3 主线：点击一次“收好桌面”，将通过安全检查的桌面
顶层文件和完整文件夹，按最后修改年月移入
`Timeline/YYYY/YYYY-MM/`。

官网不连接文件系统，也不执行整理、撤销或截图分析。

## 本地预览

在项目根目录运行：

```bash
python3 -m http.server 4173 --bind 127.0.0.1 --directory website
```

然后打开：

```text
http://127.0.0.1:4173/
```

按 `Control + C` 停止。本地预览只监听回环地址，不会把官网暴露到局域网或
互联网。

## 公开域名

主站地址为：

```text
https://www.froganize.com/
```

HTML 已包含 canonical、Open Graph、Twitter Card 和 JSON-LD 结构化数据。
`robots.txt` 指向 `sitemap.xml`。

## GitHub Pages 发布

`.github/workflows/pages.yml` 只会把这个目录作为静态站点上传到
GitHub Pages。它不会打包应用、本机配置、测试临时文件或 Git 私有备份。

仓库公开后：

1. 进入 GitHub 仓库的 **Settings → Pages**。
2. 将 **Source** 设为 **GitHub Actions**。
3. 在 GitHub 个人设置的 **Pages** 中验证 `froganize.com`。
4. 将仓库 Pages 的 **Custom domain** 设为 `www.froganize.com`。
5. 在域名 DNS 中将 `www` 的 CNAME 指向 GitHub Pages 默认域名，
   并按 GitHub 文档配置根域 A 记录。
6. DNS 生效后启用 **Enforce HTTPS**。

源码的唯一公开地址是：

```text
https://github.com/liwengtai-sudo/Froganize
```

## 文件

- `index.html`：产品首页、截图智能说明和蛙仔故事；
- `changelog.html`：已完成功能和公开进度；
- `privacy.html`：隐私、网络和文件安全边界；
- `styles.css`：响应式设计系统；
- `robots.txt` 和 `sitemap.xml`：搜索引擎入口；
- `assets/native-dashboard.png`：使用合成文件生成的当前原生界面截图；
- `assets/social-preview.png`：1280 × 640 社交分享图。

## 隐私与性能

官网不包含外部字体、分析脚本、Cookie、遥测或网络素材。页面中的文件名
和界面截图均来自合成演示数据，不含真实桌面内容。

## 发布边界

官网已使用真实 GitHub 仓库作为唯一源码入口。在 Developer ID
签名和 Apple 公证完成之前，不公开下载本地构建的 `.app` 或
`.dmg`。
