import AppKit
import WebKit

// The WebView is only a window onto our owned loopback server. Account sign-in
// always opens in the system browser; web content receives no native bridge.
final class Studio: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var cover: NSView!
    var status: NSTextField!
    var progress: NSProgressIndicator!
    var retry: NSButton!
    var process: Process?
    var pipe: Pipe?
    var pending = Data()
    var quitting = false
    var quitPending = false
    var ready = false
    var failure = false
    var popups: [WKWebView] = []
    var downloads: [WKDownload] = []
    var smokeNavigationChecked = false
    var smokeExternalURLs: [String] = []
    var smoke = CommandLine.arguments.contains("--smoke-test")
    var port: Int { smoke ? (ProcessInfo.processInfo.environment["CLIPFOUNDRY_DESKTOP_TEST_PORT"].flatMap(Int.init) ?? 8765) : 8765 }
    var local: URL { URL(string: "http://127.0.0.1:\(port)")! }
    var base: URL {
        if smoke, let path = ProcessInfo.processInfo.environment["CLIPFOUNDRY_DESKTOP_TEST_BASE"] { return URL(fileURLWithPath: path) }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/ClipFoundry")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.appearance = NSAppearance(named: .darkAqua)
        menus()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 840),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "ClipFoundry"
        window.subtitle = "Your local video studio"
        window.minSize = NSSize(width: 960, height: 640)
        window.center()
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("ClipFoundryStudio")
        window.backgroundColor = NSColor(calibratedRed: 0.043, green: 0.059, blue: 0.114, alpha: 1)
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = smoke
        web = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        window.contentView!.addSubview(web)
        startupView()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        start()
    }

    func label(_ text: String, _ size: CGFloat, _ color: NSColor = .labelColor) -> NSTextField {
        let item = NSTextField(wrappingLabelWithString: text)
        item.font = .systemFont(ofSize: size, weight: size > 24 ? .bold : .regular)
        item.textColor = color
        item.alignment = .center
        return item
    }

    func startupView() {
        cover = NSView(frame: window.contentView!.bounds)
        cover.autoresizingMask = [.width, .height]
        cover.wantsLayer = true
        cover.layer?.backgroundColor = window.backgroundColor.cgColor
        window.contentView!.addSubview(cover)
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        let icon = NSImageView(image: NSApp.applicationIconImage)
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.widthAnchor.constraint(equalToConstant: 100).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 100).isActive = true
        stack.addArrangedSubview(icon)
        stack.addArrangedSubview(label("Your footage. Your studio.", 32))
        status = label("Starting ClipFoundry…", 15, .secondaryLabelColor)
        status.widthAnchor.constraint(equalToConstant: 500).isActive = true
        stack.addArrangedSubview(status)
        progress = NSProgressIndicator()
        progress.style = .spinning
        progress.controlSize = .regular
        progress.startAnimation(nil)
        stack.addArrangedSubview(progress)
        retry = NSButton(title: "Try again", target: self, action: #selector(start))
        retry.bezelStyle = .rounded
        retry.isHidden = true
        stack.addArrangedSubview(retry)
        let logs = NSButton(title: "View local logs", target: self, action: #selector(openLogs))
        logs.bezelStyle = .inline
        stack.addArrangedSubview(logs)
        cover.addSubview(stack)
        NSLayoutConstraint.activate([stack.centerXAnchor.constraint(equalTo: cover.centerXAnchor), stack.centerYAnchor.constraint(equalTo: cover.centerYAnchor, constant: -25)])
        let foot = label("Runs on your Mac · Closing the window keeps your studio running\nUse ClipFoundry → Quit to stop it.", 12, .tertiaryLabelColor)
        foot.translatesAutoresizingMaskIntoConstraints = false
        cover.addSubview(foot)
        NSLayoutConstraint.activate([foot.centerXAnchor.constraint(equalTo: cover.centerXAnchor), foot.bottomAnchor.constraint(equalTo: cover.bottomAnchor, constant: -30)])
    }

    @objc func start() {
        guard process?.isRunning != true, !quitting else { return }
        ready = false
        failure = false
        pending = Data()
        cover.isHidden = false
        retry.isHidden = true
        progress.isHidden = false
        progress.startAnimation(nil)
        status.stringValue = "Opening your Brain, clips and workspace…"
        let root = Bundle.main.bundleURL.appendingPathComponent("Contents")
        let task = Process()
        task.executableURL = root.appendingPathComponent("Resources/Python/bin/python3.12")
        task.arguments = ["-I", "-B", root.appendingPathComponent("Resources/desktop_runtime.py").path,
                          "--parent", String(ProcessInfo.processInfo.processIdentifier), "--session", UUID().uuidString,
                          "--port", String(port), "--base", base.path]
        var env = ProcessInfo.processInfo.environment
        for key in ["PYTHONPATH", "PYTHONHOME", "CLIPFOUNDRY_DATA", "CLIPFOUNDRY_DESKTOP_SESSION", "CLIPFOUNDRY_WORKERS"] { env.removeValue(forKey: key) }
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if smoke { env["CLIPFOUNDRY_WORKERS"] = "off" }
        task.environment = env
        let output = Pipe()
        pipe = output
        task.standardOutput = output
        task.standardError = FileHandle.nullDevice
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let bytes = handle.availableData
            if bytes.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.receive(bytes) }
        }
        task.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.process = nil
                self.pipe?.fileHandleForReading.readabilityHandler = nil
                if self.quitting { NSApp.reply(toApplicationShouldTerminate: true) }
                else if !self.failure { self.showError("The local studio stopped. Your saved work is still on this Mac. Click Try again to reopen it.") }
                self.retry.isEnabled = true
            }
        }
        process = task
        do { try task.run() }
        catch { process = nil; showError("ClipFoundry’s bundled tools could not open. Reinstall the complete app from the official download.") }
    }

    func receive(_ bytes: Data) {
        pending.append(bytes)
        while let newline = pending.firstIndex(of: 10) {
            let line = String(decoding: pending[..<newline], as: UTF8.self)
            pending.removeSubrange(...newline)
            let prefix = "CLIPFOUNDRY_DESKTOP "
            guard line.hasPrefix(prefix), let data = String(line.dropFirst(prefix.count)).data(using: .utf8),
                  let event = (try? JSONSerialization.jsonObject(with: data)) as? [String: String] else { continue }
            switch event["state"] {
            case "ready":
                ready = true
                web.load(URLRequest(url: local))
            case "error": showError(event["message"] ?? "The local studio could not start.")
            case "starting": status.stringValue = event["message"] ?? "Starting…"
            default: break
            }
        }
        if pending.count > 65536 { pending.removeAll() }
    }

    func showError(_ message: String) {
        failure = true
        cover.isHidden = false
        status.stringValue = message
        progress.stopAnimation(nil)
        progress.isHidden = true
        retry.isHidden = false
        retry.isEnabled = process?.isRunning != true
        window.subtitle = "Studio needs attention"
        if smoke { fputs("NATIVE_SMOKE_ERROR: \(message)\n", stderr); NSApp.terminate(nil) }
    }

    func isLocal(_ url: URL) -> Bool { url.scheme == "http" && url.host == "127.0.0.1" && url.port == port && url.user == nil && url.password == nil }
    func openExternal(_ url: URL) {
        if ["https", "http", "mailto"].contains(url.scheme ?? "") {
            if smoke { smokeExternalURLs.append(url.absoluteString) }
            else { NSWorkspace.shared.open(url) }
        }
    }

    func webView(_ view: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.absoluteString == "about:blank" { decisionHandler(.allow); return }
        if action.shouldPerformDownload { decisionHandler(isLocal(url) || url.scheme == "blob" ? .download : .cancel); return }
        if isLocal(url) && (action.targetFrame == nil || view !== web) {
            openExternal(url)
            popups.removeAll { $0 === view }
            decisionHandler(.cancel)
            return
        }
        if isLocal(url) || url.scheme == "blob" { decisionHandler(.allow) }
        else {
            // Hidden OAuth popup navigates from about:blank after the local API returns.
            if action.targetFrame?.isMainFrame != false { openExternal(url) }
            popups.removeAll { $0 === view }
            decisionHandler(.cancel)
        }
    }

    func webView(_ view: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        let popup = WKWebView(frame: .zero, configuration: configuration)
        popup.navigationDelegate = self
        popup.uiDelegate = self
        popups.append(popup)
        return popup
    }
    func webViewDidClose(_ view: WKWebView) { popups.removeAll { $0 === view } }
    func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) {
        guard view === web, ready else { return }
        cover.isHidden = true
        window.subtitle = "Running locally on your Mac"
        if smoke && !smokeNavigationChecked {
            smokeNavigationChecked = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                self.web.evaluateJavaScript("document.body.innerText") { value, error in
                    guard error == nil, let text = value as? String, text.contains("ClipFoundry") else { self.showError("Native WebView did not load the studio."); return }
                    self.smokeInteractions()
                }
            }
        }
    }
    func smokeInteractions() {
        // Real WebKit popup/Blob paths, using no platform account or external network.
        let script = """
        (() => {
            const guard = event => event.preventDefault(); window.addEventListener('beforeunload', guard);
            const leave = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(leave); window.removeEventListener('beforeunload', guard);
            if (!leave.defaultPrevented) throw new Error('Unsaved-change guard failed');
            const popup = window.open('about:blank', '_blank');
            if (popup) popup.location.href = 'https://example.com/clipfoundry-oauth-test';
            const legal = document.createElement('a'); legal.href='/legal/privacy'; legal.target='_blank'; document.body.append(legal); legal.click(); legal.remove();
            const link = document.createElement('a'); link.href=URL.createObjectURL(new Blob(['clipfoundry-synthetic-export'], {type:'text/plain'})); link.download='native-export.txt'; document.body.append(link); link.click(); link.remove();
            return true;
        })()
        """
        web.evaluateJavaScript(script) { _, error in
            if error != nil { self.showError("Native file/link checks could not run.") }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            guard self.smokeExternalURLs.contains("https://example.com/clipfoundry-oauth-test"),
                  self.smokeExternalURLs.contains(self.local.absoluteString + "/legal/privacy"),
                  self.web.url.map(self.isLocal) == true else { self.showError("External account/help links did not leave the studio correctly."); return }
            self.web.takeSnapshot(with: nil) { image, error in
                guard error == nil, let image = image, let data = image.tiffRepresentation,
                      let bitmap = NSBitmapImageRep(data: data), let png = bitmap.representation(using: .png, properties: [:]),
                      let folder = ProcessInfo.processInfo.environment["CLIPFOUNDRY_DESKTOP_EVIDENCE"] else { self.showError("Could not capture native window evidence."); return }
                do {
                    try png.write(to: URL(fileURLWithPath: folder).appendingPathComponent("native-studio.png"))
                    try "Native WebView, account/help links, export and unsaved-change event passed.\n".write(toFile: folder + "/webview-passed.txt", atomically: true, encoding: .utf8)
                } catch { self.showError("Could not save native window evidence."); return }
                print("NATIVE_WEBVIEW_PASSED")
                NSApp.terminate(nil)
            }
        }
    }
    func webView(_ view: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if view === web && (error as NSError).code != NSURLErrorCancelled { showError("The studio window could not connect. Quit and reopen ClipFoundry. Your saved work is preserved.") }
    }
    func webView(_ view: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) }
    }
    func webView(_ view: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ view: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "Continue"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }
    func webView(_ view: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let attachment = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().hasPrefix("attachment") ?? false
        decisionHandler(attachment || !response.canShowMIMEType ? .download : .allow)
    }
    func webView(_ view: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self; downloads.append(download) }
    func webView(_ view: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self; downloads.append(download) }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        if smoke, let folder = ProcessInfo.processInfo.environment["CLIPFOUNDRY_DESKTOP_EVIDENCE"] {
            completionHandler(URL(fileURLWithPath: folder).appendingPathComponent("native-export.txt"))
            return
        }
        let panel = NSSavePanel(); panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.url : nil) }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.removeAll { $0 === download } }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeAll { $0 === download }
        if (error as NSError).code != NSURLErrorCancelled {
            let alert = NSAlert(); alert.messageText = "The export could not be saved."; alert.informativeText = "Your clip is still available in ClipFoundry. Try exporting it again."; alert.beginSheetModal(for: window)
        }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard process?.isRunning == true else { return .terminateNow }
        if quitPending { return .terminateLater }
        quitPending = true
        if ready && !smoke {
            // Reuse the web editor's existing beforeunload guard, including video
            // imports in progress. No frontend bridge or duplicate dirty state.
            web.evaluateJavaScript("(() => { const e = new Event('beforeunload', {cancelable:true}); window.dispatchEvent(e); return e.defaultPrevented; })()") { value, _ in
                if value as? Bool == true {
                    self.window.makeKeyAndOrderFront(nil)
                    let alert = NSAlert()
                    alert.messageText = "Quit without saving?"
                    alert.informativeText = "You have unsaved changes or an import in progress. Keep editing to finish before quitting."
                    alert.addButton(withTitle: "Keep Editing")
                    alert.addButton(withTitle: "Quit Without Saving")
                    alert.beginSheetModal(for: self.window) { response in
                        if response == .alertSecondButtonReturn { self.stopForQuit() }
                        else { self.quitPending = false; NSApp.reply(toApplicationShouldTerminate: false) }
                    }
                } else { self.stopForQuit() }
            }
        } else { stopForQuit() }
        return .terminateLater
    }
    func stopForQuit() {
        quitting = true
        window.subtitle = "Finishing local shutdown…"
        if let task = process, task.isRunning { task.terminate() } // Watchdog stops only its own worker group.
        else { NSApp.reply(toApplicationShouldTerminate: true) }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { window.makeKeyAndOrderFront(nil); return true }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    @objc func openLogs() {
        let logs = base.appendingPathComponent("data/logs")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        NSWorkspace.shared.open(logs)
    }
    @objc func openBrowser() { if ready { NSWorkspace.shared.open(local) } }
    @objc func help() { NSWorkspace.shared.open(URL(string: "https://clipfoundry-studio.landryschreiner33.chatgpt.site")!) }
    @objc func about() { NSApp.orderFrontStandardAboutPanel(options: [.credits: NSAttributedString(string: "Your local video studio.\nBrain, clipping, captions and publishing on your Mac.\nThird-party licenses are included inside the app.")]) }
    func menus() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "About ClipFoundry", action: #selector(about), keyEquivalent: "").target = self
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide ClipFoundry", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit ClipFoundry", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); editItem.title = "Edit"; editItem.submenu = NSMenu(title: "Edit"); menu.addItem(editItem)
        for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            editItem.submenu!.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let studio = NSMenuItem(); studio.title = "Studio"; studio.submenu = NSMenu(title: "Studio"); menu.addItem(studio)
        studio.submenu!.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        studio.submenu!.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        studio.submenu!.addItem(.separator())
        studio.submenu!.addItem(withTitle: "Open in Browser", action: #selector(openBrowser), keyEquivalent: "").target = self
        studio.submenu!.addItem(withTitle: "View Local Logs", action: #selector(openLogs), keyEquivalent: "").target = self
        studio.submenu!.addItem(withTitle: "ClipFoundry Help", action: #selector(help), keyEquivalent: "").target = self
        NSApp.mainMenu = menu
    }
}

let app = NSApplication.shared
let studio = Studio()
app.delegate = studio
app.setActivationPolicy(.regular)
app.run()
