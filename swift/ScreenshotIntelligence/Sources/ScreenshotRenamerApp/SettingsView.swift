import SwiftUI
import ScreenshotRenamerCore

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @State private var apiKey = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 5) {
                Text("Froganize Screenshot Intelligence")
                    .font(.title2.weight(.semibold))
                Text("为系统截图生成清楚、可搜索的名称")
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("AI 接口")
                        .font(.headline)
                    TextField(
                        "API 地址，例如 https://example.com/v1/chat/completions",
                        text: $model.customEndpointText
                    )
                    .textFieldStyle(.roundedBorder)
                    TextField("模型名称", text: $model.customModelText)
                        .textFieldStyle(.roundedBorder)
                    Button("保存 API 配置") {
                        model.saveCustomProviderConfiguration()
                    }
                    Text("填写支持 OpenAI Chat Completions 格式的 HTTPS 接口。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(model.apiKeyLabel)
                            .font(.headline)
                        Spacer()
                        Text(model.credentialDescription)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    HStack(spacing: 10) {
                        SecureField(
                            model.credentialDescription.hasPrefix("已保存") ? "••••••••••••" : "粘贴 API Key",
                            text: $apiKey
                        )
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 12)
                        .frame(height: 40)
                        .background(fieldBackground)

                        Button("保存") {
                            model.saveAPIKeyToKeychain(apiKey)
                            apiKey = ""
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(apiKey.trimmingCharacters(in: .whitespacesAndNewlines).count <= 20)

                        Button("测试连接") {
                            model.testConnection()
                        }
                        .buttonStyle(.bordered)
                        .disabled(!model.hasSavedCredential || model.isWorking)
                    }

                    Text("保存只写入 macOS 钥匙串，不会连接 AI 服务。只有点击“测试连接”或开启截图处理后才会发送请求。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

            }

            Divider()

            VStack(alignment: .leading, spacing: 16) {
                Toggle("允许上传并自动处理新截图", isOn: $model.isEnabled)

                Text("开启后，只有匹配的系统截图会上传到你配置的 AI 接口进行内容识别；其他桌面文件不会上传。关闭时不会上传任何截图。")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack {
                    Text("截图文件夹")
                        .font(.headline)
                    Spacer()
                    Text(model.folderPath)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Button("选择…") { model.chooseFolder() }
                }

                Text(model.status)
                    .font(.callout)
                    .foregroundStyle(model.status.contains("失败") || model.status.contains("缺少") ? .red : .secondary)
                    .textSelection(.enabled)
            }
        }
        .padding(28)
        .frame(width: 580)
        .onChange(of: model.provider) { _ in
            apiKey = ""
        }
    }

    private func field<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            content()
                .padding(.horizontal, 10)
                .frame(maxWidth: .infinity, minHeight: 40, alignment: .leading)
                .background(fieldBackground)
        }
    }

    private var fieldBackground: some View {
        RoundedRectangle(cornerRadius: 6)
            .fill(Color(nsColor: .controlBackgroundColor))
            .overlay {
                RoundedRectangle(cornerRadius: 6)
                    .stroke(Color.secondary.opacity(0.25), lineWidth: 1)
            }
    }
}
