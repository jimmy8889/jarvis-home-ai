import XCTest
@testable import Pilot

final class PilotApplicationDelegateTests: XCTestCase {
    @MainActor
    func testForegroundFinishDoesNotCompleteANextBackgroundGeneration() {
        let registry = PilotBackgroundSessionEvents()
        let identifier = "pilot-background-session-test"
        var completionCount = 0

        // A resident foreground session can finish without UIKit supplying a
        // relaunch completion handler. That event must not become a stale token.
        registry.complete(identifier: identifier)
        registry.register(identifier: identifier) {
            completionCount += 1
        }

        XCTAssertEqual(completionCount, 0)
        registry.complete(identifier: identifier)
        XCTAssertEqual(completionCount, 1)
    }

    @MainActor
    func testReplacingAHandlerReleasesTheOlderSystemCallback() {
        let registry = PilotBackgroundSessionEvents()
        let identifier = "pilot-background-session-test"
        var firstCount = 0
        var secondCount = 0

        registry.register(identifier: identifier) { firstCount += 1 }
        registry.register(identifier: identifier) { secondCount += 1 }

        XCTAssertEqual(firstCount, 1)
        XCTAssertEqual(secondCount, 0)
        registry.complete(identifier: identifier)
        XCTAssertEqual(secondCount, 1)
    }
}
