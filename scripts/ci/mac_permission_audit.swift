// Disposable CI screenshot inspection only. No clicks, consent changes or network.
import Foundation
import ImageIO
import Vision

guard ProcessInfo.processInfo.environment["CI"] == "true", CommandLine.arguments.count == 2 else {
    fatalError("Usage on disposable CI only: mac-permission-audit screenshot.png")
}
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fatalError("Cannot decode screenshot")
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US"]
request.usesLanguageCorrection = false
request.usesCPUOnly = true
try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
let text = lines.joined(separator: " ").lowercased()
let found = text.contains("local network") && text.contains("allow") &&
    (text.contains("python") || text.contains("freecad")) &&
    (text.contains("don't allow") || text.contains("don’t allow") || text.contains("find devices"))
let result: [String: Any] = ["permission_prompt_detected": found, "recognized_text": lines,
                           "scope": "Read-only local-network prompt detection; not generic dialog certification"]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(decoding: data, as: UTF8.self))
