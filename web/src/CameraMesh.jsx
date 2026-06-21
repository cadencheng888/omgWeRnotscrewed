import { useEffect, useRef } from 'react'

// Browser-side MediaPipe Face Mesh overlay (468 landmarks). Globals come from
// the CDN <script> tags in index.html: FaceMesh, Camera, drawConnectors,
// drawLandmarks, FACEMESH_TESSELATION.
export default function CameraMesh({ open, onClose }) {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const video = videoRef.current
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const FaceMesh = window.FaceMesh
    const Camera = window.Camera
    if (!FaceMesh || !Camera) { console.warn('MediaPipe not loaded'); return }

    const mesh = new FaceMesh({ locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}` })
    mesh.setOptions({ maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5, minTrackingConfidence: 0.5 })
    mesh.onResults((res) => {
      ctx.save()
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.translate(canvas.width, 0); ctx.scale(-1, 1) // mirror for selfie view
      ctx.drawImage(res.image, 0, 0, canvas.width, canvas.height)
      const faces = res.multiFaceLandmarks
      if (faces) for (const lm of faces) {
        window.drawConnectors(ctx, lm, window.FACEMESH_TESSELATION, { color: 'rgba(161,161,170,0.28)', lineWidth: 1 })
        window.drawLandmarks(ctx, lm, { color: '#34d399', lineWidth: 1, radius: 1.1 })
      }
      ctx.restore()
    })

    const cam = new Camera(video, { onFrame: async () => { await mesh.send({ image: video }) }, width: 480, height: 360 })
    cam.start().catch((e) => console.warn('camera start failed', e))

    return () => {
      try { cam.stop() } catch (e) { /* noop */ }
      if (video && video.srcObject) { video.srcObject.getTracks().forEach((t) => t.stop()); video.srcObject = null }
      try { mesh.close() } catch (e) { /* noop */ }
    }
  }, [open])

  if (!open) return null
  return (
    <div className="fixed right-6 bottom-6 z-50 rounded-2xl overflow-hidden border border-white/10 shadow-2xl bg-black" style={{ animation: 'popIn .3s ease both' }}>
      <div className="flex items-center justify-between px-3 py-2 bg-zinc-900/90 border-b border-white/10">
        <span className="mono text-[11px] tracking-wider text-zinc-400">face mesh · mediapipe</span>
        <button onClick={onClose} className="text-zinc-500 hover:text-rose-400 text-sm leading-none px-1">✕</button>
      </div>
      <video ref={videoRef} playsInline style={{ display: 'none' }} />
      <canvas ref={canvasRef} width={480} height={360} className="block" style={{ width: 480, height: 360 }} />
    </div>
  )
}
