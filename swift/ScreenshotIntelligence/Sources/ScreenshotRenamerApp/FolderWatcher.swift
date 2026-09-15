import Foundation

final class FolderWatcher {
    private var source: DispatchSourceFileSystemObject?
    private var fileDescriptor: Int32 = -1

    func start(watching directoryURL: URL, onChange: @escaping () -> Void) throws {
        stop()

        fileDescriptor = open(directoryURL.path, O_EVTONLY)
        guard fileDescriptor >= 0 else {
            throw CocoaError(.fileReadNoPermission)
        }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fileDescriptor,
            eventMask: [.write, .extend, .attrib, .rename, .delete],
            queue: DispatchQueue(label: "app.froganize.screenshot-intelligence.folder-watcher", qos: .utility)
        )

        source.setEventHandler(handler: onChange)
        source.setCancelHandler { [fileDescriptor] in
            if fileDescriptor >= 0 {
                close(fileDescriptor)
            }
        }
        source.resume()
        self.source = source
    }

    func stop() {
        source?.cancel()
        source = nil
        fileDescriptor = -1
    }

    deinit {
        stop()
    }
}
