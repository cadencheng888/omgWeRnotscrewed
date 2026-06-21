import Foundation
import SwiftUI
import UIKit
import MWDATCore
import MWDATCamera
import Combine
import AVFoundation
import Speech

@MainActor
final class RayBanCaptureManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var isStreaming = false
    @Published var registrationStatus = "unknown"
    @Published var latestTranscript = ""
    @Published var isTranscribing = false

    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    private var webSocket: URLSessionWebSocketTask?

    // Meta Ray-Ban / MWDAT
    private let wearables: WearablesInterface = Wearables.shared
    private var deviceSession: DeviceSession?
    private var rayBanStream: MWDATCamera.Stream?

    private var stateListenerToken: AnyListenerToken?
    private var videoFrameListenerToken: AnyListenerToken?
    private var errorListenerToken: AnyListenerToken?

    private nonisolated(unsafe) var lastFrameSent = Date.distantPast

    override init() {
        super.init()
        registrationStatus = "\(wearables.registrationState)"
    }

    // MARK: - Laptop WebSocket

    func connect(host: String, port: UInt16) async throws {
        let urlString = "ws://\(host):\(port)/ws/iphone"

        guard let url = URL(string: urlString) else {
            throw NSError(
                domain: "RayBanCaptureManager",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Bad WebSocket URL"]
            )
        }

        let task = URLSession.shared.webSocketTask(with: url)
        self.webSocket = task
        task.resume()

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            task.sendPing { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            }
        }

        isConnected = true
        sendStatus("iPhone connected to laptop WebSocket")
        receiveLoop()
    }

    private func receiveLoop() {
        webSocket?.receive { [weak self] result in
            Task { @MainActor in
                switch result {
                case .success:
                    self?.receiveLoop()

                case .failure(let error):
                    print("WebSocket receive error:", error.localizedDescription)
                    self?.isConnected = false
                    self?.isStreaming = false
                }
            }
        }
    }

    func stop() {
        stopStreaming()
        isConnected = false
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
    }

    // MARK: - Ray-Ban Registration

    func registerRayBans() {
        Task {
            do {
                registrationStatus = "starting registration"
                sendStatus("Ray-Ban: starting registration")
                sendStatus("Ray-Ban registration before: \(wearables.registrationState)")

                try await wearables.startRegistration()

                registrationStatus = "registration launched; waiting for Meta AI callback"
                sendStatus("Ray-Ban: registration launched. Finish approval in Meta AI.")
                sendStatus("Ray-Ban registration current state: \(wearables.registrationState)")

            } catch {
                let errorText = "\(error)"
                registrationStatus = "registration failed"
                sendStatus("Ray-Ban registration failed: \(errorText)")
                print("Ray-Ban registration error:", errorText)
            }
        }
    }

    func handleMetaAICallback(_ url: URL) {
        sendStatus("Ray-Ban: received Meta AI callback URL: \(url.absoluteString)")
        print("Meta AI callback URL:", url.absoluteString)

        Task {
            do {
                _ = try await wearables.handleUrl(url)

                registrationStatus = "\(wearables.registrationState)"
                sendStatus("Ray-Ban callback handled")
                sendStatus("Ray-Ban registration after callback: \(registrationStatus)")

            } catch {
                let errorText = "\(error)"
                registrationStatus = "callback failed"
                sendStatus("Ray-Ban callback failed: \(errorText)")
                print("Ray-Ban callback error:", errorText)
            }
        }
    }

    // MARK: - Streaming

    func startStreaming(mode: InputMode) async throws {
        switch mode {
        case .rayBan:
            try await startRayBanStreaming()
        case .iPhone:
            throw NSError(
                domain: "RayBanCaptureManager",
                code: 30,
                userInfo: [NSLocalizedDescriptionKey: "iPhone camera streaming isn't implemented yet — only Ray-Ban Camera works right now."]
            )
        }
    }

    func startRayBanStreaming() async throws {
        guard isConnected else {
            throw NSError(
                domain: "RayBanCaptureManager",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Laptop is not connected"]
            )
        }

        isStreaming = true

        do {
            try await startRayBanCamera()
            sendStatus("Streaming Ray-Ban camera")
        } catch {
            isStreaming = false
            throw error
        }
    }

    func stopStreaming() {
        isStreaming = false

        Task {
            await stopRayBanCamera()
        }

        sendStatus("Streaming stopped")
    }

    // MARK: - Ray-Ban Camera

    private func startRayBanCamera() async throws {
        sendStatus("Ray-Ban: starting camera setup")
        sendStatus("Ray-Ban registration state: \(wearables.registrationState)")

        let permission = Permission.camera

        let selector = AutoDeviceSelector(wearables: wearables)

        sendStatus("Ray-Ban: waiting for an active device")

        for await device in selector.activeDeviceStream() {
            if device != nil {
                sendStatus("Ray-Ban: active device found")
                break
            }
        }

        let session = try wearables.createSession(deviceSelector: selector)
        self.deviceSession = session

        sendStatus("Ray-Ban: session created")

        let stateStream = session.stateStream()
        try session.start()

        sendStatus("Ray-Ban: session start requested")

        var started = false

        for await state in stateStream {
            sendStatus("Ray-Ban session state: \(state)")

            if state == .started {
                started = true
                break
            }

            if state == .stopped {
                break
            }
        }

        guard started else {
            throw NSError(
                domain: "RayBanCaptureManager",
                code: 21,
                userInfo: [NSLocalizedDescriptionKey: "Ray-Ban session did not start"]
            )
        }

        sendStatus("Ray-Ban: session started")

        var status: PermissionStatus

        do {
            status = try await wearables.checkPermissionStatus(permission)
            sendStatus("Ray-Ban camera permission status: \(status)")
        } catch {
            sendStatus("Ray-Ban camera permission check failed (\(error)) — requesting permission directly instead")
            status = .denied
        }

        if status != .granted {
            sendStatus("Ray-Ban: requesting camera permission")
            status = try await wearables.requestPermission(permission)
            sendStatus("Ray-Ban camera permission after request: \(status)")
        }

        guard status == .granted else {
            throw NSError(
                domain: "RayBanCaptureManager",
                code: 20,
                userInfo: [NSLocalizedDescriptionKey: "Ray-Ban camera permission denied"]
            )
        }

        sendStatus("Ray-Ban: camera permission granted")

        let config = StreamConfiguration(
            videoCodec: VideoCodec.raw,
            resolution: StreamingResolution.low,
            frameRate: 24
        )

        guard let stream = try session.addStream(config: config) else {
            throw NSError(
                domain: "RayBanCaptureManager",
                code: 22,
                userInfo: [NSLocalizedDescriptionKey: "Could not create Ray-Ban camera stream"]
            )
        }

        self.rayBanStream = stream
        sendStatus("Ray-Ban: stream created")

        stateListenerToken = stream.statePublisher.listen { [weak self] state in
            Task { @MainActor in
                self?.sendStatus("Ray-Ban stream state: \(state)")
            }
        }

        videoFrameListenerToken = stream.videoFramePublisher.listen { [weak self] frame in
            Task { @MainActor in
                self?.sendStatus("Ray-Ban: video frame received")
                self?.handleRayBanVideoFrame(frame)
            }
        }

        errorListenerToken = stream.errorPublisher.listen { [weak self] error in
            Task { @MainActor in
                self?.sendStatus("Ray-Ban stream error: \(error.localizedDescription)")
            }
        }

        await stream.start()
        sendStatus("Ray-Ban: stream start requested")
    }

    private func stopRayBanCamera() async {
        stateListenerToken = nil
        videoFrameListenerToken = nil
        errorListenerToken = nil

        if let stream = rayBanStream {
            rayBanStream = nil
            await stream.stop()
        }

        deviceSession?.stop()
        deviceSession = nil
    }

    private func handleRayBanVideoFrame(_ frame: VideoFrame) {
        guard let image = frame.makeUIImage() else {
            sendStatus("Ray-Ban: failed to convert video frame to UIImage")
            return
        }

        let now = Date()
        guard now.timeIntervalSince(lastFrameSent) > 0.5 else { return }
        lastFrameSent = now

        guard let jpegData = image.jpegData(compressionQuality: 0.35) else {
            sendStatus("Ray-Ban: failed to encode frame as JPEG")
            return
        }

        sendImage(jpegData.base64EncodedString())
    }

    // MARK: - Audio Transcription (Bluetooth mic, not MWDAT)

    func startTranscription() {
        guard !isTranscribing else { return }

        SFSpeechRecognizer.requestAuthorization { [weak self] authStatus in
            guard let self else { return }
            Task { @MainActor in
                guard authStatus == .authorized else {
                    self.sendStatus("Speech recognition not authorized: \(authStatus.rawValue)")
                    return
                }
                self.requestMicPermissionAndStart()
            }
        }
    }

    private func requestMicPermissionAndStart() {
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            guard let self else { return }
            Task { @MainActor in
                guard granted else {
                    self.sendStatus("Microphone permission denied")
                    return
                }
                self.beginAudioEngine()
            }
        }
    }

    private func beginAudioEngine() {
        guard let speechRecognizer, speechRecognizer.isAvailable else {
            sendStatus("Speech recognizer unavailable")
            return
        }

        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(
                .playAndRecord,
                mode: .default,
                options: [.defaultToSpeaker]
            )
            try audioSession.setActive(true)
        } catch {
            sendStatus("Audio session error: \(error.localizedDescription)")
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if speechRecognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.recognitionRequest = request

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            request.append(buffer)
        }

        audioEngine.prepare()

        do {
            try audioEngine.start()
        } catch {
            sendStatus("Audio engine error: \(error.localizedDescription)")
            return
        }

        isTranscribing = true
        sendStatus("Transcription started — input route: \(audioSession.currentRoute.inputs.map { $0.portName })")

        recognitionTask = speechRecognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            Task { @MainActor in
                if let result {
                    let text = result.bestTranscription.formattedString
                    self.latestTranscript = text
                    self.sendJSON(["type": "transcript", "text": text])
                }
                if error != nil || (result?.isFinal ?? false) {
                    self.stopTranscription()
                }
            }
        }
    }

    func stopTranscription() {
        guard isTranscribing else { return }

        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        isTranscribing = false

        do {
            try AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
        } catch {
            sendStatus("Audio session deactivate error: \(error.localizedDescription)")
        }

        sendStatus("Transcription stopped")
    }

    // MARK: - Debug

    func debugPermissions() {
        debugRayBanStatus()
    }

    func debugRayBanStatus() {
        sendStatus("Ray-Ban registration state: \(wearables.registrationState)")
        sendStatus("Ray-Ban: \(wearables.devices.count) device(s) known to SDK")
        for device in wearables.devices {
            sendStatus("Ray-Ban device: \(device)")
        }

        Task {
            do {
                let cameraStatus = try await wearables.checkPermissionStatus(.camera)
                sendStatus("Ray-Ban camera permission: \(cameraStatus)")
            } catch {
                sendStatus("Ray-Ban permission check error: \(error)")
            }
        }
    }

    // MARK: - Send JSON

    private func sendStatus(_ message: String) {
        sendJSON([
            "type": "status",
            "message": message
        ])
    }

    nonisolated private func sendImage(_ base64: String) {
        Task { @MainActor in
            self.sendJSON([
                "type": "image",
                "image_base64": base64
            ])
        }
    }

    private func sendJSON(_ object: [String: Any]) {
        guard let webSocket else {
            print("No WebSocket. Local message:", object)
            return
        }

        do {
            let data = try JSONSerialization.data(withJSONObject: object)
            guard let string = String(data: data, encoding: .utf8) else { return }

            webSocket.send(.string(string)) { error in
                if let error {
                    print("WebSocket send error:", error.localizedDescription)
                }
            }
        } catch {
            print("JSON error:", error.localizedDescription)
        }
    }
}
