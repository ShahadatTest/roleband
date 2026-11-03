import Darwin
import Foundation

/// PID and kernel start time together prevent a recycled PID from receiving a stop.
struct OwnedProcess: Equatable, Sendable {
    let pid: pid_t
    let group: pid_t
    let seconds: UInt64
    let microseconds: UInt64

    static let marker = "ROLEBAND_ENGINE_OWNER"

    static func read(_ pid: pid_t) -> Self? {
        guard pid > 1 else { return nil }
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout.size(ofValue: info))
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size,
              info.pbi_uid == getuid(), info.pbi_status != SZOMB else { return nil }
        return Self(pid: pid, group: pid_t(info.pbi_pgid),
                    seconds: info.pbi_start_tvsec, microseconds: info.pbi_start_tvusec)
    }

    static func marked(_ token: String) throws -> [Self] {
        let count = proc_listallpids(nil, 0)
        guard count > 0 else { throw HostProblem.processInspection }
        var pids = [pid_t](repeating: 0, count: Int(count) + 1024)
        let found = pids.withUnsafeMutableBytes { proc_listallpids($0.baseAddress, Int32($0.count)) }
        guard found > 0, found < pids.count else { throw HostProblem.processInspection }
        return pids.prefix(Int(found)).compactMap { pid in
            guard let process = read(pid), environment(pid).contains("\(marker)=\(token)"),
                  read(pid) == process else { return nil }
            return process
        }
    }

    private static func environment(_ pid: pid_t) -> [String] {
        var mib = [CTL_KERN, KERN_PROCARGS2, pid]
        var size = 0
        guard sysctl(&mib, 3, nil, &size, nil, 0) == 0, size > 4, size <= 2 * 1024 * 1024 else { return [] }
        var bytes = [UInt8](repeating: 0, count: size)
        let result = bytes.withUnsafeMutableBytes { sysctl(&mib, 3, $0.baseAddress, &size, nil, 0) }
        guard result == 0 else { return [] }
        let argc = bytes.withUnsafeBytes { $0.loadUnaligned(as: Int32.self) }
        guard argc >= 0 else { return [] }
        var cursor = MemoryLayout<Int32>.size
        func skipString() {
            while cursor < size && bytes[cursor] != 0 { cursor += 1 }
            if cursor < size { cursor += 1 }
        }
        skipString() // The executable path precedes argv and its zero padding.
        while cursor < size && bytes[cursor] == 0 { cursor += 1 }
        for _ in 0..<argc { skipString() }
        return bytes[cursor..<size].split(separator: 0).map { String(decoding: $0, as: UTF8.self) }
    }

    var isPostgres: Bool { LaunchMode.executable(pid)?.lastPathComponent == "postgres" }
    var isAlive: Bool { Self.read(pid) == self }

    func matchesDatabase(_ directory: URL) -> Bool {
        guard let file = try? FileHandle(forReadingFrom: directory.appendingPathComponent("postmaster.pid")) else { return false }
        defer { try? file.close() }
        guard let data = try? file.read(upToCount: 8193), data.count <= 8192,
              let text = String(data: data, encoding: .utf8) else { return false }
        let lines = text.components(separatedBy: "\n")
        guard lines.count >= 3, pid_t(lines[0]) == pid, let began = UInt64(lines[2]),
              abs(Double(began) - Double(seconds)) <= 2 else { return false }
        return URL(fileURLWithPath: lines[1]).resolvingSymlinksInPath().standardizedFileURL.path == directory.resolvingSymlinksInPath().standardizedFileURL.path
    }

    func signal(_ number: Int32, group: Bool = false) throws {
        guard isAlive else { return }
        let target = group ? -self.group : pid
        guard !group || (self.group > 1 && self.group != getpgrp()) else { throw HostProblem.processInspection }
        if kill(target, number) != 0 && errno != ESRCH { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
    }
}

/// A direct child in a fresh group. Reaping belongs to this handle, including after SIGKILL.
final class OwnedChild: @unchecked Sendable {
    let pid: pid_t
    let identity: OwnedProcess?
    private var ended = false

    init(executable: URL, arguments: [String], environment: [String: String], log: URL, directory: URL? = nil) throws {
        var attributes: posix_spawnattr_t?
        var actions: posix_spawn_file_actions_t?
        posix_spawnattr_init(&attributes)
        posix_spawn_file_actions_init(&actions)
        defer {
            posix_spawnattr_destroy(&attributes)
            posix_spawn_file_actions_destroy(&actions)
        }
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGMASK | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_CLOEXEC_DEFAULT))
        posix_spawnattr_setpgroup(&attributes, 0)
        var mask = sigset_t(0)
        var defaults = sigset_t(0)
        sigemptyset(&mask)
        sigemptyset(&defaults)
        for number in [SIGTERM, SIGINT, SIGHUP, SIGPIPE] { sigaddset(&defaults, number) }
        posix_spawnattr_setsigmask(&attributes, &mask)
        posix_spawnattr_setsigdefault(&attributes, &defaults)
        posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0)
        posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, log.path, O_WRONLY | O_CREAT | O_APPEND, 0o600)
        posix_spawn_file_actions_adddup2(&actions, STDOUT_FILENO, STDERR_FILENO)
        if let directory { posix_spawn_file_actions_addchdir_np(&actions, directory.path) }
        let argv = ([executable.path] + arguments).map { strdup($0) }
        let env = environment.sorted(by: { $0.key < $1.key }).map { strdup("\($0.key)=\($0.value)") }
        defer { (argv + env).forEach { free($0) } }
        var argvPointers = argv + [nil]
        var envPointers = env + [nil]
        var launched: pid_t = 0
        let code = posix_spawn(&launched, executable.path, &actions, &attributes, &argvPointers, &envPointers)
        guard code == 0 else { throw POSIXError(POSIXErrorCode(rawValue: code) ?? .EIO) }
        pid = launched
        identity = OwnedProcess.read(launched)
    }

    func running() -> Bool {
        guard !ended else { return false }
        var status: Int32 = 0
        let result = waitpid(pid, &status, WNOHANG)
        if result == pid || (result < 0 && errno == ECHILD) { ended = true }
        return !ended
    }
}
