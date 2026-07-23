import AppKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(
        Data("usage: generate_app_icon.swift SOURCE OUTPUT\n".utf8)
    )
    exit(2)
}

let sourceURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
guard let mark = NSImage(contentsOf: sourceURL) else {
    fatalError("Could not load Pilot mark at \(sourceURL.path)")
}

let canvasSize = NSSize(width: 1024, height: 1024)
let colorSpace = CGColorSpaceCreateDeviceRGB()
guard let context = CGContext(
    data: nil,
    width: Int(canvasSize.width),
    height: Int(canvasSize.height),
    bitsPerComponent: 8,
    bytesPerRow: Int(canvasSize.width) * 4,
    space: colorSpace,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
) else { fatalError("Could not create Pilot app icon context") }

let colors = [
    CGColor(red: 0.025, green: 0.045, blue: 0.105, alpha: 1),
    CGColor(red: 0.055, green: 0.025, blue: 0.125, alpha: 1),
    CGColor(red: 0.020, green: 0.105, blue: 0.115, alpha: 1),
] as CFArray
let gradient = CGGradient(
    colorsSpace: colorSpace,
    colors: colors,
    locations: [0, 0.52, 1]
)!
context.drawLinearGradient(
    gradient,
    start: CGPoint(x: 0, y: 1024),
    end: CGPoint(x: 1024, y: 0),
    options: []
)
context.setFillColor(CGColor(red: 0.10, green: 0.82, blue: 0.92, alpha: 0.09))
context.fillEllipse(in: CGRect(x: 165, y: 165, width: 694, height: 694))

var proposed = NSRect(origin: .zero, size: mark.size)
guard let markImage = mark.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else {
    fatalError("Could not decode Pilot mark")
}
context.draw(markImage, in: CGRect(x: 92, y: 92, width: 840, height: 840))

guard
    let rendered = context.makeImage(),
    let destination = CGImageDestinationCreateWithURL(
        outputURL as CFURL,
        UTType.png.identifier as CFString,
        1,
        nil
    )
else { fatalError("Could not render Pilot app icon") }
CGImageDestinationAddImage(destination, rendered, nil)
guard CGImageDestinationFinalize(destination) else {
    fatalError("Could not save Pilot app icon")
}
