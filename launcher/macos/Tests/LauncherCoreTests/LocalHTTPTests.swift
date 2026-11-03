import Foundation
import Network
import Testing
@testable import LauncherCore

/// An HTTP/1.1 server on a free loopback port that answers every request with `ok` and keeps the
/// connection open, counting the connections clients open.
private final class KeepAliveServer: @unchecked Sendable {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "keep-alive-server")
    private let lock = NSLock()
    private var opened = 0
    var connections: Int { lock.withLock { opened } }

    init() async throws {
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        listener = try NWListener(using: parameters)
        listener.newConnectionHandler = { [self] connection in
            lock.withLock { opened += 1 }
            connection.start(queue: queue)
            answer(connection, pending: Data())
        }
        await withCheckedContinuation { (ready: CheckedContinuation<Void, Never>) in
            listener.stateUpdateHandler = { if case .ready = $0 { ready.resume() } }
            listener.start(queue: queue)
        }
    }

    var url: URL { URL(string: "http://127.0.0.1:\(listener.port!.rawValue)/api/health")! }

    private func answer(_ connection: NWConnection, pending: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [self] data, _, done, error in
            var buffer = pending + (data ?? Data())
            while let end = buffer.range(of: Data("\r\n\r\n".utf8)) {
                buffer.removeSubrange(..<end.upperBound)
                let reply = "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok"
                connection.send(content: Data(reply.utf8), completion: .contentProcessed { _ in })
            }
            if done || error != nil { connection.cancel() } else { answer(connection, pending: buffer) }
        }
    }

    func stop() { listener.cancel() }
}

@Test func pollsReuseOneConnectionToTheEngine() async throws {
    let server = try await KeepAliveServer(); defer { server.stop() }
    for _ in 0..<3 {
        #expect(try await LocalHTTP.read(URLRequest(url: server.url)) == Data("ok".utf8))
    }
    #expect(server.connections == 1)
}
