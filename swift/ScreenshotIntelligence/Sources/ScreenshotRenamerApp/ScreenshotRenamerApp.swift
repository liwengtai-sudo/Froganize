import AppKit
import SwiftUI

struct ScreenshotRenamerApp: App {
    @StateObject private var model: AppModel

    init() {
        let model = AppModel()
        _model = StateObject(wrappedValue: model)
        DispatchQueue.main.async {
            model.startIfNeeded()
        }
    }

    var body: some Scene {
        MenuBarExtra("Froganize · 截图智能", systemImage: model.isWorking ? "sparkles" : "text.viewfinder") {
            MenuContentView(model: model)
                .task { model.startIfNeeded() }
        }
        .menuBarExtraStyle(.menu)

        Settings {
            SettingsView(model: model)
                .task { model.startIfNeeded() }
        }
    }
}

private struct MenuContentView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Toggle("允许上传并自动处理新截图", isOn: Binding(
            get: { model.isEnabled },
            set: { model.isEnabled = $0 }
        ))

        Button("处理最近一张现有截图") {
            model.testMostRecentScreenshot()
        }
        .disabled(!model.isEnabled || model.isWorking)

        Button("撤销上一次重命名") {
            model.undoLatest()
        }
        .disabled(model.isWorking)

        Divider()

        Button("选择截图文件夹…") {
            model.chooseFolder()
        }

        if #available(macOS 14.0, *) {
            SettingsLink {
                Text("打开设置…")
            }
        } else {
            Button("打开设置…") {
                NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil, from: nil)
            }
        }

        Divider()

        Text(model.status)
        Text(model.folderPath)

        Divider()

        Button("退出") {
            NSApp.terminate(nil)
        }
    }
}
