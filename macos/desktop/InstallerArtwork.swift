import AppKit

// Installer layout artwork, drawn at 2x. App icons are rendered by Finder.
let size = NSSize(width: 1400, height: 880)
let image = NSImage(size: size)
image.lockFocus()
NSColor(calibratedRed: 0.055, green: 0.063, blue: 0.09, alpha: 1).setFill()
NSRect(origin: .zero, size: size).fill()
func text(_ value: String, x: CGFloat, y: CGFloat, size: CGFloat, color: NSColor, weight: NSFont.Weight = .regular) {
    (value as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [.font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color])
}
text("YOUR LOCAL VIDEO STUDIO", x: 90, y: 760, size: 21, color: NSColor(calibratedRed: 0.71, green: 0.62, blue: 0.95, alpha: 1), weight: .semibold)
text("Make room for your next great clip.", x: 90, y: 680, size: 43, color: .white, weight: .bold)
text("Drag ClipFoundry into Applications.", x: 90, y: 617, size: 27, color: .lightGray)
text("→", x: 650, y: 345, size: 74, color: NSColor(calibratedRed: 0.71, green: 0.62, blue: 0.95, alpha: 1))
text("Then open ClipFoundry from Applications or your Dock.", x: 90, y: 123, size: 23, color: .lightGray)
text("Brain · Clipping · Captions · Publishing", x: 90, y: 73, size: 20, color: .gray)
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
