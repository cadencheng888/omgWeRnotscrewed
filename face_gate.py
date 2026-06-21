"""
On-device face presence gate (OpenCV Haar cascade).

Privacy feature for Conversation mode: the agent only captures audio when a face
is detected in front of the camera at a good talking distance. Runs entirely
on-device — no frames ever leave the machine.

Fails OPEN: if no camera is available (or it can't be opened), is_present()
returns True so the audio pipeline still works, with a clear warning. Tune with
env vars FACE_CAMERA_INDEX and FACE_MIN_RATIO.
"""

import os
import threading
import time

import cv2

_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


class FaceGate:
    def __init__(self, camera_index=0, min_face_ratio=0.10, grace=2.0):
        # min_face_ratio: face-box width / frame width to count as "good talking
        # distance" (bigger = closer). grace: keep "present" this long after the
        # last detection so brief misses don't flicker the gate.
        self.camera_index = int(os.environ.get("FACE_CAMERA_INDEX", camera_index))
        self.min_face_ratio = float(os.environ.get("FACE_MIN_RATIO", min_face_ratio))
        self.grace = grace
        self._cascade = cv2.CascadeClassifier(_CASCADE_PATH)
        self._last_seen = 0.0
        self._running = False
        self._camera_ok = True
        self._thread = None

    def start(self):
        if self._running:
            return
        self._camera_ok = True  # reset so a restart re-attempts the camera
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def camera_ok(self) -> bool:
        return self._camera_ok

    def is_present(self) -> bool:
        if not self._camera_ok:
            return True  # fail open — no camera, don't block capture
        return (time.monotonic() - self._last_seen) < self.grace

    def _loop(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap or not cap.isOpened():
            print("[face] no camera available — gating disabled (capturing always)")
            self._camera_ok = False
            return
        print(f"[face] camera {self.camera_index} open — gating audio on face presence")
        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.1)
                    continue
                h, w = frame.shape[:2]
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
                )
                # a face wide enough in frame == close enough to be talking to you
                if any((fw / w) >= self.min_face_ratio for (x, y, fw, fh) in faces):
                    self._last_seen = time.monotonic()
                time.sleep(0.1)  # ~10 fps to save CPU / battery
        finally:
            cap.release()


if __name__ == "__main__":
    # Standalone camera self-test:  python face_gate.py
    print("Opening camera for a 10s self-test (grant camera permission if prompted)…")
    g = FaceGate()
    g.start()
    time.sleep(1.5)
    if not g.camera_ok():
        print("\n❌ Camera could NOT be opened.")
        print("   Fix one of these:")
        print("   • System Settings → Privacy & Security → Camera → enable your")
        print("     terminal app (Terminal / iTerm / VS Code), then fully quit & reopen it.")
        print("   • Try another camera index:  FACE_CAMERA_INDEX=1 python face_gate.py")
        raise SystemExit(1)
    print("✅ Camera opened. Move in/out of frame:\n")
    for i in range(10):
        print(f"  t={i}s   face in view: {g.is_present()}")
        time.sleep(1)
    g.stop()
    print("\n✅ Camera + face detection work. If the SERVER still doesn't gate,")
    print("   it's running stale code — restart it: lsof -ti tcp:8000 | xargs kill -9; python server.py")
