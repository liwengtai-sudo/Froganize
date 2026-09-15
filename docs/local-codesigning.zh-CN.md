# Froganize 本机稳定签名指南

这套流程只解决一个本机开发问题：让多次重新构建的 Froganize 截图组件保持
相同的 macOS **designated requirement**，从而避免钥匙串把每个 ad-hoc 构建都
当成一个新应用。

它不需要 Apple Developer 付费账号，但也不等同于 Developer ID、Gatekeeper
认可或 Apple 公证，产物不能作为公开下载版本发布。

## 为什么 ad-hoc 构建会重复询问

ad-hoc 签名没有稳定的证书身份。程序二进制一变化，签名身份也会变化。钥匙串
不会静默相信“名字相同但身份已变化”的程序，因此会再次要求用户确认。

稳定本机签名使用同一枚本机私钥和自签名证书。嵌套截图组件继续使用固定 Bundle
ID `app.froganize.Froganize.ScreenshotIntelligence`；即使后续构建的 CDHash 改变，
证书锚定的 designated requirement 仍可保持不变。

## 安全边界

- 创建脚本只有在维护者亲自运行并输入 `CREATE` 后才会修改钥匙串。
- 脚本不使用 `sudo`，也不会在正常构建时自动运行。
- 证书只被当前 macOS 用户信任为代码签名用途，并包含 Code Signing EKU。
- 私钥以不可导出方式导入，访问列表只指定系统 `/usr/bin/codesign`；不会使用
  “允许所有应用访问”。
- 临时私钥只在权限为 `0700` 的随机临时目录内短暂存在，脚本退出时删除。
- 本机可运行的恶意软件仍可能调用 `codesign` 尝试使用该密钥。因此只应在自己
  控制的 Mac 上创建，且绝不能把这枚身份当成公开发布证书。

## 一次性创建

先关闭正在运行的 Froganize，再从项目根目录显式运行：

```bash
./scripts/create_local_codesign_identity.sh
```

系统可能要求解锁“登录”钥匙串或确认用户级信任设置，这是预期行为。无需打开
“钥匙串访问”手工制作证书，也不应选择“允许所有应用访问”。完成后，脚本会用：

```bash
security find-identity -v -p codesigning "$HOME/Library/Keychains/login.keychain-db"
```

确认该证书包含私钥并能被 macOS 识别为代码签名身份，然后打印唯一的 SHA-1
指纹。若钥匙串被锁定或系统拒绝信任设置，可先在“钥匙串访问”中解锁“登录”
钥匙串，再处理脚本报告的残留同名证书；不要盲目创建第二枚同名证书。

脚本实际采用的关键限制是：

- X.509 `keyUsage = digitalSignature`；
- `extendedKeyUsage = 1.3.6.1.5.5.7.3.3`（Code Signing）；
- `security add-trusted-cert -r trustRoot -p codeSign`，仅配置当前用户域的代码签名
  信任；
- `security import 私钥 -x -T /usr/bin/codesign`（让 `security` 自动识别 PEM），
  私钥不可导出且不开放给所有应用。

如果证书写入后私钥导入或身份验证失败，脚本会按本次随机证书的 SHA-1 指纹尝试
回滚本次身份（证书、对应私钥和信任设置），不会按名称删除已有项目。如果失败
发生在私钥写入之前，则退回到只删除该指纹的证书。若 macOS 拒绝自动回滚，
脚本会打印需要在“钥匙串访问”中核对的精确 SHA-1；确认指纹一致后再手动删除。

## 使用稳定身份构建

每次构建前显式设置脚本打印的 SHA-1 指纹：

```bash
export FROGANIZE_LOCAL_CODESIGN_IDENTITY="证书的40位SHA-1指纹"
unset FROGANIZE_CODESIGN_IDENTITY
unset FROGANIZE_NOTARY_PROFILE
./scripts/build_unified_macos_prototype.sh
```

构建器会对 helper、嵌套截图组件和外层应用从内到外签名，禁用不适用于自签名
证书的安全时间戳，并拒绝把本机身份用于公证。若生成的 designated requirement
没有证书哈希锚点，构建会安全失败。

`FROGANIZE_LOCAL_CODESIGN_IDENTITY` 与面向公开发布的
`FROGANIZE_CODESIGN_IDENTITY` 互斥，不能同时设置。

## 两次构建验证

第一次构建后保留一份只读对照，再修改代码并进行第二次构建：

```bash
ditto "dist/unified/Froganize.app" "/tmp/Froganize-old.app"
./scripts/build_unified_macos_prototype.sh
./scripts/verify_local_codesign_stability.sh \
  "/tmp/Froganize-old.app" \
  "dist/unified/Froganize.app"
```

验证器要求：

- 两个嵌套组件都不是 ad-hoc 签名；
- Bundle ID 固定；
- designated requirement 本身包含固定 Bundle ID 和证书哈希锚点，且不包含
  `cdhash`；
- 两次构建的 designated requirement 完全相同。

CDHash 可以因为二进制变化而不同；这不影响上述稳定身份。

## 正确迁移 API Key 的顺序

1. 先创建稳定本机签名身份。
2. 用该身份构建并安装唯一的桌面 Froganize。
3. 验证已安装嵌套组件不是 ad-hoc 签名。
4. 再从新面板保存或迁移 API Key，创建 Froganize 专用钥匙串项目。
5. 后续只使用同一签名身份重建。

不要先让 ad-hoc 版本创建新的钥匙串项目，否则新项目仍会绑定不稳定身份并再次
弹窗。也不要为了消除弹窗把钥匙串项目改成“允许所有应用访问”。

## 与公开发布的区别

本机自签名证书只在这台 Mac、这个用户的信任设置中有效。分享给其他人的应用仍
会被视为未知来源。公开分发必须另行使用 Developer ID Application 证书、
Hardened Runtime、公证和 stapling；参见 [macOS 发布手册](macos-release.zh-CN.md)。
