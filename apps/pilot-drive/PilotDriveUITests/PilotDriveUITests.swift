import XCTest

final class PilotDriveUITests: XCTestCase {
    @MainActor
    func testPairingSurfaceSupportsAccessibilityTextAndLabels() {
        let app = XCUIApplication()
        app.launchArguments = [
            "-UIPreferredContentSizeCategoryName",
            "UICTContentSizeCategoryAccessibilityExtraExtraExtraLarge",
        ]
        app.launch()

        XCTAssertTrue(app.staticTexts["Pilot Drive"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Pair with Pilot Core"].exists)
        XCTAssertTrue(
            app.descendants(matching: .any)[
                "Pilot Core pairing code or API key bundle"
            ].exists
        )
        XCTAssertTrue(app.buttons["Pair securely"].exists)
    }
}
