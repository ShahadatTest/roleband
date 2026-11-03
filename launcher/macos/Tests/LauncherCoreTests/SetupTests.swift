import Foundation
import Testing
@testable import LauncherCore

@Test func loginRequiresTheRunningCopyToBeInApplications() {
    let home = URL(fileURLWithPath: "/Users/fixture")
    #expect(AppLocation.isInstalled(URL(fileURLWithPath: "/Applications/RoleBand.app"), home: home))
    #expect(AppLocation.isInstalled(home.appendingPathComponent("Applications/RoleBand.app"), home: home))
    for path in ["/Volumes/RoleBand/RoleBand.app", "/private/tmp/RoleBand.app", "/Applications-old/RoleBand.app",
                 "/Applications/RoleBand.app/Contents/MacOS", "/Applications/RoleBand"] {
        #expect(!AppLocation.isInstalled(URL(fileURLWithPath: path), home: home))
    }
}

@Test func installedSetupOmitsInstallationInProgressAndBothNavigationDirections() {
    #expect(SetupStep.steps(installed: true) == [.welcome, .connection, .login, .done])
    #expect(SetupStep.connection.previous(installed: true) == .welcome)
    #expect(SetupStep.welcome.next(connected: false, installed: true) == .connection)
    #expect(SetupStep.steps(installed: false) == [.welcome, .installation, .connection, .login, .done])
    #expect(SetupStep.connection.previous(installed: false) == .installation)
    #expect(SetupStep.welcome.next(connected: false, installed: false) == .installation)
    #expect(SetupStep.installation.next(connected: true, installed: false) == .installation)
}
