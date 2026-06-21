//
//  WeMightBeCookedApp.swift
//  WeMightBeCooked
//

import SwiftUI
import MWDATCore

@main
struct WeMightBeCookedApp: App {
    init() {
        do {
            try Wearables.configure()
            print("MWDAT configured")
        } catch {
            print("MWDAT configure error:", error.localizedDescription)
        }
    }

    @StateObject private var rayBanManager = RayBanCaptureManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(rayBanManager)
                .onOpenURL { url in
                    print("App received URL:", url.absoluteString)
                    rayBanManager.handleMetaAICallback(url)
                }
        }
    }
}
