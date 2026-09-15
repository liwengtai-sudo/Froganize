# Froganize macOS 签名、公证与发布操作手册

> **0.2 历史发布流程：** 本文中的 `dist/macos/Froganize-0.2.0-*` 名称描述
> 整理器单体管线，不代表当前 0.3 Unified Prototype。0.3 本机融合构建请先看
> `FROGANIZE_MERGE_PLAN.md` 和 `scripts/build_unified_macos_prototype.sh`；在加入
> Developer ID、公证和 DMG 发布步骤前，不要把统一本地包描述为公开版本。

> 适用范围：把 Froganize 作为可直接下载的 macOS 应用发布，不经过 Mac App
> Store。本文按第一次发布 Mac 应用的操作顺序编写。

## 先看结论

Froganize 的应用和 DMG 构建流程已经准备好。当前这台 Mac 还缺一个关键条件：

```text
Developer ID Application 证书及其私钥
```

你需要亲自完成 Apple 账号、付费会员和证书步骤。我可以在证书安装完成后继续
执行构建、公证、验证和发布准备。

## 安全红线

以下内容不要发给我，也不要放进 Git、聊天截图、README、Issue 或 `.env`：

- Apple Account 密码；
- Apple 两步验证码；
- app-specific password；
- `.p12` 证书备份及其密码；
- App Store Connect API 私钥（`.p8`）；
- 钥匙串导出文件；
- 任何私钥或 token。

本项目的构建脚本只接收“证书显示名称”和“钥匙串 profile 名称”，不会要求把
实际密码写进项目。

> 如果当前目标仅是让**同一台 Mac 上的反复开发构建**保持稳定钥匙串身份，暂时
> 不公开下载，也可以不购买会员。请改用
> [本机稳定签名指南](local-codesigning.zh-CN.md)。那是本机自签名方案，不是
> Developer ID，不能代替本手册的公开发布流程。

---

## A. 当前电脑已经具备什么

截至 2026-08-09，本机检查结果：

| 项目 | 状态 |
| --- | --- |
| macOS | 15.6.1，Apple silicon `arm64` |
| 自包含 `Froganize.app` | 已完成 |
| 本地 ad-hoc 签名 DMG | 已完成 |
| Xcode Command Line Tools | 已安装 |
| `notarytool` | 已安装，版本 1.1.0 |
| `stapler` | 已安装 |
| Developer ID 身份 | **缺失：`0 valid identities found`** |
| Apple 公证 | 尚未进行 |

你不需要重新安装 Python，也暂时不需要购买域名。

---

## B. 第一步：选择个人账号还是组织账号

官方入口：

- [Apple Developer Program 注册入口](https://developer.apple.com/programs/enroll/)
- [Apple 官方注册要求说明](https://developer.apple.com/help/account/membership/program-enrollment)

### 如果 Froganize 以你个人名义发布

选择 **Individual / 个人**。这通常最适合个人开源项目。

- 不需要公司；
- 不需要 D‑U‑N‑S Number；
- 不需要为了注册而先购买域名；
- Apple 会使用你的法定姓名，不要填写网名或项目名代替姓名。

### 如果要以公司或组织名义发布

选择 **Organization / 组织**。Apple 目前要求组织具备：

- 合法实体；
- D‑U‑N‑S Number；
- 有权代表组织签约的人；
- 与组织域名关联的工作邮箱；
- 可公开访问、内容有效的组织网站。

因此：**个人注册不需要域名；组织注册才可能需要官网和域名。** 如果目前没有
正式公司主体，建议先选择个人账号，不要为了这个阶段临时注册一个空壳网站。

### 这一步的完成标志

- [ ] 已决定个人或组织类型；
- [ ] Apple Account 已开启双重认证；
- [ ] 姓名、地址、手机号等账号信息真实且最新。

---

## C. 第二步：加入 Apple Developer Program

### 方式一：网页注册

1. 打开 [Apple Developer Program 注册入口](https://developer.apple.com/programs/enroll/)。
2. 点击 **Start Your Enrollment**。
3. 使用准备作为开发者账号的 Apple Account 登录。
4. 阅读并同意 Apple Developer Agreement。
5. 选择 **Individual** 或 **Organization**。
6. 按页面要求完成身份资料和验证。
7. 核对会员协议并付款。
8. 等待 Apple 的确认邮件。

Apple 官方当前列出的标准年费是 99 美元，实际支付会根据地区、当地货币和税费
显示，以付款页面为准。不要通过非 Apple 网站购买所谓“开发者证书”。

### 方式二：Apple Developer App

官方说明：

- [Apple Developer App 官方页面](https://developer.apple.com/app/)
- [通过 Apple Developer App 注册](https://developer.apple.com/help/account/membership/enrolling-in-the-app)

操作：

1. 从 App Store 安装 Apple Developer App。
2. 打开 App，进入 **Account / 账户**。
3. 使用开启了双重认证的 Apple Account 登录。
4. 点击 **Enroll Now**。
5. 按提示完成身份验证、协议和付款。

### 这一步的完成标志

登录 [Apple Developer Account](https://developer.apple.com/account/) 后，可以看到
有效会员状态，而不是仅有免费的 Apple Developer Agreement。

- [ ] 收到 Apple Developer Program 激活邮件；
- [ ] Membership 显示 Active；
- [ ] 可以进入 Certificates, Identifiers & Profiles。

> 如果付款后 24 小时仍未激活，使用注册页面给出的 Enrollment ID 联系
> [Apple Developer Support](https://developer.apple.com/contact/)。

---

## D. 第三步：找到并记录 Team ID

官方说明：

- [Apple Team ID 说明](https://developer.apple.com/help/glossary/team-id/)

操作：

1. 登录 [Apple Developer Account](https://developer.apple.com/account/)。
2. 打开 **Membership details / 会员详细信息**。
3. 找到 **Team ID**。
4. 只记录这串 10 位字符，例如：

```text
AB12C3DE45
```

Team ID 不是密码，可以用于构建配置；但仍建议不要把无关账号页面截图公开。

### 这一步的完成标志

- [ ] 已记录准确的 10 位 Team ID；
- [ ] 确认当前登录的是准备发布 Froganize 的团队。

---

## E. 第四步：在本机生成 CSR

CSR 是 Certificate Signing Request。它会在这台 Mac 的钥匙串中生成一对密钥，
然后把申请文件上传给 Apple。私钥不会上传。

官方说明：

- [Apple：创建 Certificate Signing Request](https://developer.apple.com/help/account/certificates/create-a-certificate-signing-request)

操作：

1. 按 `Command + Space` 打开 Spotlight。
2. 搜索并打开 **Keychain Access / 钥匙串访问**。
3. 在屏幕顶部菜单选择：
   **Keychain Access → Certificate Assistant → Request a Certificate From a Certificate Authority**。
4. `User Email Address`：填写 Apple Developer Account 使用的邮箱。
5. `Common Name`：填写容易辨认的名称，例如：

   ```text
   Froganize Developer ID 2026
   ```

6. `CA Email Address`：留空。
7. 选择 **Saved to disk / 存储到磁盘**。
8. 不选择“Let me specify key pair information”，除非 Apple 页面明确要求。
9. 点击 Continue，把文件保存到一个容易找到的临时位置。

生成的文件类似：

```text
CertificateSigningRequest.certSigningRequest
```

### 非常重要

之后下载的 `.cer` 必须安装回**生成这个 CSR 的同一台 Mac、同一个用户钥匙串**。
否则证书可能没有对应私钥，无法用于签名。

### 这一步的完成标志

- [ ] 得到一个 `.certSigningRequest` 文件；
- [ ] 没有把 CSR 对应私钥导出或上传到其他网站。

---

## F. 第五步：创建 Developer ID Application 证书

官方入口和说明：

- [Certificates, Identifiers & Profiles](https://developer.apple.com/account/resources/certificates/list)
- [Apple：创建 Developer ID 证书](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)

> 手动创建 Developer ID 证书通常要求 Account Holder 权限。个人会员本人就是
> Account Holder。不要选择 `Apple Development`、`Apple Distribution` 或
> `Developer ID Installer`，Froganize 的 `.app` 需要的是
> **Developer ID Application**。

操作：

1. 打开 [证书列表](https://developer.apple.com/account/resources/certificates/list)。
2. 点击左上角 **＋**。
3. 在 Software 分类下选择 **Developer ID**。
4. 点击 Continue。
5. 如果页面继续询问类型，选择 **Developer ID Application**。
6. 点击 **Choose File**。
7. 选择上一步生成的 `.certSigningRequest`。
8. 点击 Continue。
9. 证书生成后点击 Download。

下载结果通常是一个 `.cer` 文件。

### 这一步的完成标志

- [ ] Apple 证书页面显示 Developer ID Application；
- [ ] 已下载 `.cer` 文件；
- [ ] 没有选择 Developer ID Installer。

---

## G. 第六步：安装并验证证书和私钥

1. 双击下载的 `.cer` 文件。
2. 系统会将它安装到当前用户钥匙串。
3. 打开“钥匙串访问”。
4. 左侧选择 **login / 登录**钥匙串。
5. 选择 **My Certificates / 我的证书**。
6. 找到：

   ```text
   Developer ID Application: 你的姓名或组织名 (TEAMID)
   ```

7. 点击证书左侧的小三角。下面必须出现一条 private key / 私钥。

然后在 Terminal 执行：

```bash
security find-identity -v -p codesigning
```

正确结果类似：

```text
1) ABCDEF... "Developer ID Application: YOUR NAME (AB12C3DE45)"
   1 valid identities found
```

### 常见问题

#### 仍然显示 `0 valid identities found`

依次检查：

1. `.cer` 是否安装到了 `login` 钥匙串；
2. “我的证书”中是否能展开看到私钥；
3. CSR 是否在这台 Mac 上生成；
4. 是否误创建了 `Developer ID Installer`；
5. 证书是否过期或被撤销。

只有证书、没有私钥时不能签名。不要反复创建大量证书；先确认原 CSR 对应的
私钥是否还在。

### 建议备份

在“我的证书”中选择证书和私钥，导出为加密 `.p12`，设置强密码，并保存到
受保护的密码库或离线备份。不要把 `.p12` 放进 DropNest 项目或云端公共链接。

### 这一步的完成标志

- [ ] 钥匙串中证书下面能看到私钥；
- [ ] Terminal 显示 `1 valid identities found` 或更多；
- [ ] 已复制完整的证书显示名称，后面构建时需要使用。

完成到这里后，你就可以回来告诉我：

```text
Developer ID 已安装，security 显示 valid identity。
```

不要把证书私钥、密码或完整钥匙串发给我。

---

## H. 第七步：创建 app-specific password

这一密码只用于 `notarytool` 访问 Apple 公证服务，不是你的 Apple Account 主
密码。Apple Account 必须先启用双重认证。

官方入口和说明：

- [Apple Account](https://account.apple.com/)
- [Apple：创建 app-specific password](https://support.apple.com/102654)

操作：

1. 登录 [Apple Account](https://account.apple.com/)。
2. 打开 **Sign-In and Security / 登录与安全性**。
3. 打开 **App-Specific Passwords / App 专用密码**。
4. 点击 Generate / 生成。
5. 标签填写：

   ```text
   Froganize Notary
   ```

6. Apple 会生成一串专用密码。
7. 临时复制它，下一步存入钥匙串后就不再需要写进任何文件。

不要使用 Apple Account 主密码代替它。修改 Apple Account 主密码后，现有的
app-specific password 可能会被撤销，需要重新生成并更新钥匙串 profile。

---

## I. 第八步：把公证凭据安全存入钥匙串

官方技术说明：

- [Apple：自定义公证工作流](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)

在 Terminal 中运行下面的命令。把邮箱和 Team ID 换成自己的值；不要添加
`--password` 参数，这样 `notarytool` 会使用不可见的安全输入提示：

```bash
xcrun notarytool store-credentials "froganize-notary" \
  --apple-id "你的 Apple Account 邮箱" \
  --team-id "你的 10 位 TEAMID"
```

出现 password 提示时：

1. 粘贴刚生成的 app-specific password；
2. Terminal 不显示字符是正常现象；
3. 按 Return；
4. `notarytool` 会先验证，再保存到 macOS 钥匙串。

成功结果应说明 credentials validated，并且 profile 已保存。项目中只会使用
profile 名称：

```text
froganize-notary
```

验证 profile：

```bash
xcrun notarytool history --keychain-profile "froganize-notary"
```

第一次没有历史记录并不代表失败；重点是命令能够认证，而不是返回凭据错误。

### 常见错误

- `Invalid credentials`：检查 Apple ID、Team ID 和 app-specific password；
- `No Keychain password item found`：profile 名称不一致，重新执行 store-credentials；
- `401`：凭据错误、密码已撤销，或账号无对应 Team 权限；
- 修改 Apple 主密码后失效：重新生成 app-specific password 并覆盖该 profile。

---

## J. 第九步：构建、签名并提交公证

先在 Finder 中找到 DropNest 项目文件夹，右键并选择“新建位于文件夹位置的
终端窗口”；或者在 Terminal 中进入自己的项目路径：

```bash
cd "/你的绝对路径/DropNest"
```

然后执行：

```bash
source .venv/bin/activate
security find-identity -v -p codesigning
```

从输出中复制双引号内的完整身份，例如：

```text
Developer ID Application: YOUR NAME (AB12C3DE45)
```

再执行：

```bash
export FROGANIZE_CODESIGN_IDENTITY="Developer ID Application: YOUR NAME (AB12C3DE45)"
export FROGANIZE_NOTARY_PROFILE="froganize-notary"
./scripts/build_macos_distribution.sh
```

脚本会按顺序执行：

1. 使用 PyInstaller 构建自包含 `Froganize.app`；
2. 用 Developer ID 签署内部 Python、动态库和应用；
3. 启用 Hardened Runtime 和 secure timestamp；
4. 验证 `.app` 签名；
5. 制作标准 Applications 安装目标的 DMG；
6. 签署 DMG；
7. 使用 `notarytool` 上传并等待 Apple 结果；
8. Apple 返回 Accepted 后 staple ticket；
9. 验证 stapled ticket；
10. 运行 Gatekeeper 评估；
11. 最后生成 SHA-256。

正式发布构建会拒绝本机专用的 Desktop 安装目标。公开 DMG 使用 Applications
是标准做法；你自己的桌面版本可以继续保留，不影响公开安装包。

成功产物名称：

```text
dist/macos/Froganize-0.2.0-macos-arm64-notarized.dmg
dist/macos/Froganize-0.2.0-macos-arm64-notarized.dmg.sha256
```

看到下面这句话才表示整个自动流程成功：

```text
Release state: Developer ID signed, notarized, stapled, and assessed.
```

---

## K. 第十步：人工复核最终产物

### 1. 验证 App 签名

```bash
codesign --verify --deep --strict --verbose=2 dist/macos/Froganize.app
codesign --display --verbose=4 dist/macos/Froganize.app
```

检查输出中存在：

- `Authority=Developer ID Application: ...`；
- 正确的 `TeamIdentifier`；
- secure timestamp；
- Hardened Runtime 信息。

### 2. 验证 DMG ticket

```bash
xcrun stapler validate \
  dist/macos/Froganize-0.2.0-macos-arm64-notarized.dmg
```

### 3. 验证 Gatekeeper

```bash
spctl --assess --type open --context context:primary-signature --verbose=2 \
  dist/macos/Froganize-0.2.0-macos-arm64-notarized.dmg
```

预期结果包含 `accepted`。

### 4. 验证 SHA-256

```bash
shasum -a 256 -c \
  dist/macos/Froganize-0.2.0-macos-arm64-notarized.dmg.sha256
```

预期结果是 `OK`。

### 5. 如果 Apple 拒绝公证

查看最近提交：

```bash
xcrun notarytool history --keychain-profile "froganize-notary"
```

复制失败提交的 Submission ID，然后查看日志：

```bash
xcrun notarytool log "SUBMISSION-ID" \
  --keychain-profile "froganize-notary"
```

不要反复盲目提交。先根据日志修复签名、Hardened Runtime、timestamp、无效
二进制或 entitlement 问题，再重新构建完整产物。

---

## L. 第十一步：在另一台干净 Mac 验收

不能只在构建电脑上测试，因为本机可能已经信任证书、缓存 ticket 或保留旧文件。

建议找一台没有安装过 Froganize 的 Apple silicon Mac：

1. 通过浏览器下载最终 DMG；
2. 不使用 `xattr -d`、右键绕过或关闭 Gatekeeper；
3. 双击 DMG；
4. 把 Froganize 拖入 Applications；
5. 第一次正常双击打开；
6. 确认开发者名称和 Apple 验证提示正常；
7. 允许必要的 Desktop 文件访问；
8. 确认打开时只评估，不自动移动；
9. 用合成文件验证评估、归档和撤销；
10. 验证退出、再次打开、升级覆盖和卸载；
11. 确认应用打开独立窗口，不启动 8765 服务、不打开浏览器，也不显示终端或
    Python 依赖错误。

如果必须让用户执行“允许任何来源”、删除 quarantine 或关闭系统安全设置，说明
签名/公证流程仍然不合格，不能公开发布。

---

## M. 第十二步：GitHub Releases 发布

域名不是这一阶段的必需品。第一版建议使用 GitHub Releases：

1. 先确认 GitHub 仓库地址和公开支持渠道；
2. 提交并审核代码；
3. 创建版本 tag；
4. 为对应 tag 创建 GitHub Release；
5. 上传最终 notarized DMG；
6. 上传 `.sha256`；
7. 在 Release Notes 中写清支持的 macOS 和 Apple silicon；
8. 从 Release 页面重新下载并复验 SHA-256 和首次启动。

不要上传：

- `unsigned.dmg`；
- `signed-unnotarized.dmg`；
- `.p12`、`.p8`、app-specific password；
- 钥匙串文件；
- 带有真实个人桌面文件的测试包。

---

## N. 最终发布清单

- [ ] Apple Developer Program 已激活；
- [ ] Team ID 已确认；
- [ ] Developer ID Application 证书已安装；
- [ ] 证书下存在私钥；
- [ ] `security find-identity` 显示 valid identity；
- [ ] app-specific password 已存入钥匙串 profile；
- [ ] 本地 134 项自动测试通过；
- [ ] Developer ID 签名构建成功；
- [ ] Apple 公证状态为 Accepted；
- [ ] ticket staple 与 validate 成功；
- [ ] Gatekeeper 返回 accepted；
- [ ] SHA-256 返回 OK；
- [ ] 干净 Mac 完整验收通过；
- [ ] GitHub Release 只包含最终公证产物；
- [ ] 没有提交或泄漏任何凭据。

## 官方参考

- [Apple Developer Program](https://developer.apple.com/programs/)
- [Program enrollment](https://developer.apple.com/help/account/membership/program-enrollment)
- [Developer ID](https://developer.apple.com/developer-id/)
- [Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)
- [Create a CSR](https://developer.apple.com/help/account/certificates/create-a-certificate-signing-request)
- [Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [App-specific passwords](https://support.apple.com/102654)
- [PyInstaller macOS signing](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)
