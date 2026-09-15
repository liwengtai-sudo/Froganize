import Darwin
import Foundation
import ScreenshotRenamerCore

let arguments = Array(CommandLine.arguments.dropFirst())
switch ScreenshotExecutableMode.parse(arguments: arguments) {
case .control:
    Task.detached {
        let code = await ScreenshotControlCLI.run()
        Darwin.exit(code)
    }
    dispatchMain()
case .graphicalApplication:
    ScreenshotRenamerApp.main()
case .invalid:
    FileHandle.standardError.write(Data("Unsupported arguments.\n".utf8))
    Darwin.exit(EX_USAGE)
}
