import Darwin
import Foundation

extension Process {
    /// `waitUntilExit()` waits on the run loop of the thread that launched the
    /// process. An async test resumes on any thread of the pool, so that wait can
    /// miss the exit and never return. `isRunning` does not depend on the thread.
    func reap() {
        while isRunning { usleep(10_000) }
    }

    /// Ends a fixture process, killing it if it ignores SIGTERM for five seconds.
    func stopAndReap() {
        guard isRunning else { return }
        terminate()
        let deadline = ProcessInfo.processInfo.systemUptime + 5
        while isRunning {
            if ProcessInfo.processInfo.systemUptime > deadline { kill(processIdentifier, SIGKILL) }
            usleep(10_000)
        }
    }
}
