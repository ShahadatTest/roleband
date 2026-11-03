import CryptoKit
import Foundation
import Security

/// Synchronous signature checks for launch time, before any task runs. Updates use
/// `UpdateBundleVerifier`, which asks `codesign` the same questions.
public enum CodeSigning {
    /// The rule an app's updates must meet: its stamped `RoleBandUpdateRequirement`, or else its own
    /// leaf certificate. An app with no certificate states no rule, so nothing meets it.
    public static func rule(of app: URL) -> String? {
        if let info = NSDictionary(contentsOf: app.appendingPathComponent("Contents/Info.plist")) as? [String: Any],
           let stamped = try? UpdateBundleVerifier.signingRule(info) {
            return stamped
        }
        var code: SecStaticCode?
        var information: CFDictionary?
        guard SecStaticCodeCreateWithPath(app as CFURL, [], &code) == errSecSuccess, let code,
              SecCodeCopySigningInformation(code, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
              let certificates = (information as? [String: Any])?[kSecCodeInfoCertificates as String] as? [SecCertificate],
              let leaf = certificates.first else { return nil }
        let digest = Insecure.SHA1.hash(data: SecCertificateCopyData(leaf) as Data).map { String(format: "%02X", $0) }.joined()
        return "certificate leaf = H\"\(digest)\""
    }

    /// Whether `candidate` is intact, nested code included, and meets the rule `running` states.
    public static func meetsRule(_ candidate: URL, of running: URL) -> Bool {
        var code: SecStaticCode?
        var requirement: SecRequirement?
        guard let rule = rule(of: running),
              SecRequirementCreateWithString(rule as CFString, [], &requirement) == errSecSuccess, let requirement,
              SecStaticCodeCreateWithPath(candidate as CFURL, [], &code) == errSecSuccess, let code else { return false }
        let flags = SecCSFlags(rawValue: kSecCSStrictValidate | kSecCSCheckNestedCode | kSecCSCheckAllArchitectures)
        return SecStaticCodeCheckValidity(code, flags, requirement) == errSecSuccess
    }
}
