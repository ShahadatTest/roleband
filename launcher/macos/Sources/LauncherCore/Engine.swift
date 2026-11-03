import CryptoKit
import Darwin
import Foundation

public struct CommandOutput: Sendable {
    public let text: String
    public let exitCode: Int32
}

/// Swift's shared pool has one thread per core, so a command's wait suspends instead of
/// holding one. Foundation reports the exit on its own queue; a dispatch timer bounds the wait.
private final class CommandExit: @unchecked Sendable {
    private let lock = NSLock()
    private var ended = false
    private var waiters: [UUID: CheckedContinuation<Bool, Never>] = [:]

    func finish() {
        let waiting = lock.withLock {
            ended = true
            defer { waiters = [:] }
            return Array(waiters.values)
        }
        waiting.forEach { $0.resume(returning: true) }
    }

    /// True when the command ended within `timeout`. Cancellation does not cut the wait short:
    /// the command keeps its full time and the caller checks cancellation afterwards.
    func wait(timeout: TimeInterval) async -> Bool {
        await withCheckedContinuation { continuation in
            let id = UUID()
            let alreadyEnded = lock.withLock {
                if !ended { waiters[id] = continuation }
                return ended
            }
            if alreadyEnded { return continuation.resume(returning: true) }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout) { [self] in
                lock.withLock { waiters.removeValue(forKey: id) }?.resume(returning: false)
            }
        }
    }
}

enum CommandRunner {
    static func run(executable: URL, arguments: [String], timeout: TimeInterval = 3) async throws -> CommandOutput {
        try Task.checkCancellation()
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                               attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: directory) }
        let path = directory.appendingPathComponent("output")
        guard FileManager.default.createFile(atPath: path.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            throw ConnectionProblem.unavailable
        }
        let handle = try FileHandle(forWritingTo: path)
        defer { try? handle.close() }
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = handle
        process.standardError = handle
        let finished = CommandExit()
        process.terminationHandler = { _ in finished.finish() }
        try Task.checkCancellation()
        try process.run()
        if await !finished.wait(timeout: timeout) {
            if process.isRunning { process.terminate() }
            if await !finished.wait(timeout: 0.25), process.isRunning {
                kill(process.processIdentifier, SIGKILL)
            }
            throw ConnectionProblem.unavailable
        }
        try Task.checkCancellation()
        let reader = try FileHandle(forReadingFrom: path)
        defer { try? reader.close() }
        let data = try reader.read(upToCount: 65537) ?? Data()
        guard data.count <= 65536, let text = String(data: data, encoding: .utf8) else {
            throw ConnectionProblem.invalidResponse
        }
        return CommandOutput(text: text, exitCode: process.terminationStatus)
    }
}

public enum EngineState: String, Sendable {
    case running, stopped, unknown, unmatched
    public var key: String { "engine-" + rawValue }
}

private struct InstalledEngine: Equatable, Sendable {
    let plist: URL
    let program: URL
    let working: URL
    let root: URL
    let bytes: Data
    var target: String { "gui/\(getuid())/com.roleband" }

    static func load(_ installation: Installation, registration: URL, home: URL) throws -> Self {
        guard try Installation.load(registration) == installation,
              registration.standardizedFileURL == HomeLayout(home).registration.standardizedFileURL else {
            throw ConnectionProblem.invalidInstallation
        }
        let plist = HomeLayout(home).launchAgent
        let attributes = try FileManager.default.attributesOfItem(atPath: plist.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular,
              (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
              let mode = attributes[.posixPermissions] as? NSNumber, mode.intValue & 0o022 == 0,
              ((attributes[.size] as? NSNumber)?.intValue ?? Int.max) <= 32768 else {
            throw ConnectionProblem.invalidInstallation
        }
        let file = try FileHandle(forReadingFrom: plist)
        defer { try? file.close() }
        let bytes = try file.read(upToCount: 32769) ?? Data()
        guard bytes.count <= 32768,
              let item = try PropertyListSerialization.propertyList(from: bytes, format: nil) as? [String: Any],
              item["Label"] as? String == "com.roleband", item["Program"] == nil,
              let args = item["ProgramArguments"] as? [String], args.count == 1,
              let directory = item["WorkingDirectory"] as? String,
              args[0].hasPrefix("/"), directory.hasPrefix("/"),
              !args[0].contains(where: { $0.isNewline }), !directory.contains(where: { $0.isNewline }) else {
            throw ConnectionProblem.invalidInstallation
        }
        let program = URL(fileURLWithPath: args[0]).resolvingSymlinksInPath().standardizedFileURL
        let working = URL(fileURLWithPath: directory).resolvingSymlinksInPath().standardizedFileURL
        let root = program.deletingLastPathComponent().deletingLastPathComponent()
        guard program == root.appendingPathComponent("deploy/roleband"), working == root.appendingPathComponent("backend"),
              FileManager.default.isExecutableFile(atPath: program.path),
              FileManager.default.fileExists(atPath: working.path),
              SHA256.hash(data: Data(root.path.utf8)).map({ String(format: "%02x", $0) }).joined().hasPrefix(installation.instance) else {
            throw ConnectionProblem.identityMismatch
        }
        return Self(plist: plist, program: program, working: working, root: root, bytes: bytes)
    }

    func state(_ output: CommandOutput) -> EngineState {
        guard output.exitCode == 0, output.text.split(separator: "\n").first == "\(target) = {" else { return .unknown }
        let lines = output.text.components(separatedBy: "\n")
        var fields: [String: String] = [:]
        var arguments: [String] = []
        var readingArguments = false
        for line in lines.dropFirst() {
            if readingArguments {
                if line == "\t}" { readingArguments = false; continue }
                guard line.hasPrefix("\t\t"), !line.hasPrefix("\t\t\t") else { return .unknown }
                arguments.append(String(line.dropFirst(2)))
            } else if line.hasPrefix("\t"), !line.hasPrefix("\t\t") {
                if line == "\targuments = {" { readingArguments = true; continue }
                let pair = line.dropFirst().components(separatedBy: " = ")
                if pair.count == 2 {
                    guard fields.updateValue(pair[1], forKey: pair[0]) == nil else { return .unknown }
                }
            }
        }
        guard !readingArguments, lines.last(where: { !$0.isEmpty }) == "}",
              fields["path"] == plist.path, fields["type"] == "LaunchAgent",
              fields["program"] == program.path, fields["working directory"] == working.path,
              arguments == [program.path] else { return .unmatched }
        if fields["state"] == "running" || fields["job state"] == "running" { return .running }
        if let pid = fields["pid"] { guard let value = Int(pid), value == 0 else { return .unknown } }
        return fields["state"] == "not running" && fields["active count"] == "0" ? .stopped : .unknown
    }
}

public struct EngineClient: Sendable {
    private let command: @Sendable ([String]) async throws -> CommandOutput
    private let readStatus: @Sendable (Installation) async throws -> VerifiedStatus
    public init() {
        command = { arguments in
            try await CommandRunner.run(executable: URL(fileURLWithPath: "/bin/launchctl"), arguments: arguments)
        }
        readStatus = StatusClient.read
    }
    public init(command: @escaping @Sendable ([String]) async throws -> CommandOutput,
                readStatus: @escaping @Sendable (Installation) async throws -> VerifiedStatus = StatusClient.read) {
        self.command = command
        self.readStatus = readStatus
    }
    public func inspect(_ installation: Installation, registration: URL, home: URL) async -> EngineState {
        do {
            let engine = try InstalledEngine.load(installation, registration: registration, home: home)
            let result = try await command(["print", engine.target])
            guard try InstalledEngine.load(installation, registration: registration, home: home) == engine else { return .unmatched }
            return engine.state(result)
        } catch ConnectionProblem.identityMismatch { return .unmatched }
        catch { return .unknown }
    }
    public func logDirectory(_ installation: Installation, registration: URL, home: URL) -> URL? {
        guard let engine = try? InstalledEngine.load(installation, registration: registration, home: home) else { return nil }
        let directory = engine.root.appendingPathComponent("data/logs")
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory) && isDirectory.boolValue ? directory : nil
    }
    public func start(_ installation: Installation, registration: URL, home: URL) async throws {
        let engine = try InstalledEngine.load(installation, registration: registration, home: home)
        do {
            _ = try await readStatus(installation)
            throw ControlProblem.stateChanged
        } catch let error as URLError where [.cannotConnectToHost, .timedOut, .networkConnectionLost, .notConnectedToInternet].contains(error.code) {
        }
        let output = try await command(["print", engine.target])
        guard try InstalledEngine.load(installation, registration: registration, home: home) == engine,
              engine.state(output) == .stopped else { throw ControlProblem.stateChanged }
        try Task.checkCancellation()
        // Without -k, a concurrent start never turns this request into a forced restart.
        let result = try await command(["kickstart", engine.target])
        guard result.exitCode == 0 else { throw ConnectionProblem.unavailable }
    }
}
