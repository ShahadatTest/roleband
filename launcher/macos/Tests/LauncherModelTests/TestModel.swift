import Foundation
import LauncherCore
@testable import RoleBandLauncher

extension LauncherModel {
    /// A model that reaches nothing on this Mac unless a test passes it: its registration, home,
    /// preferences and app location are fresh temporary ones, and the browser and login item are stand-ins.
    convenience init(registration: URL? = nil, installation: InstallationSource? = nil,
                     mode: LaunchMode = .owned(leftover: nil), ownedEngine: OwnedEngineService? = nil,
                     readStatus: @escaping @Sendable (Installation) async throws -> VerifiedStatus = StatusClient.read,
                     performScan: @escaping @Sendable (ScanAction, Installation, InstallationSource) async throws -> ScanOutcome = ScanClient.perform,
                     readSchedule: @escaping @Sendable (VerifiedStatus, InstallationSource, String) async throws -> ScheduleState = ScheduleClient.read,
                     performPause: @escaping @Sendable (PauseAction, Installation, InstallationSource, String) async throws -> ScheduleState = ScheduleClient.perform,
                     timezone: @escaping @Sendable () -> String = { TimeZone.current.identifier },
                     engine: EngineClient = EngineClient(),
                     readNotes: @escaping @Sendable (VerifiedStatus, InstallationSource) async throws -> InstalledNotes = ReleaseClient.read,
                     launcherVersion: String? = nil,
                     openBrowser: @escaping (URL) -> Bool = { _ in true },
                     preferences: UserDefaults? = nil,
                     loginService: LoginService = LoginService(state: { .off }, setEnabled: { _ in }, openSettings: {}),
                     bundleURL: URL? = nil, homeURL: URL? = nil, language: String? = nil,
                     updates: LauncherUpdates? = nil, installOperations: UpdateInstallerOperations? = nil,
                     updateNotice: UpdateNotice? = nil) {
        let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("launcher-model-\(UUID().uuidString)")
        let home = homeURL ?? scratch.appendingPathComponent("home")
        let registration = registration ?? HomeLayout(home).registration
        self.init(LauncherDependencies(
            mode: mode, ownedEngine: ownedEngine,
            registration: registration, installation: installation ?? .registration(registration), readStatus: readStatus,
            performScan: performScan, readSchedule: readSchedule, performPause: performPause, timezone: timezone,
            engine: engine, readNotes: readNotes, launcherVersion: launcherVersion, openBrowser: openBrowser,
            preferences: preferences ?? .scratch("launcher-model"),
            loginService: loginService, bundleURL: bundleURL ?? scratch.appendingPathComponent("RoleBand.app"),
            homeURL: home, language: language, updates: updates, installOperations: installOperations,
            updateNotice: updateNotice))
    }
}
