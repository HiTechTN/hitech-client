"""Video -> frames pipeline (backend-agnostic).

Upload a screen recording -> N JPEG frames (data-URLs) ready to send as
`image_url` parts to ANY vision backend. No state, no deps beyond ffmpeg.
"""
import base64
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter(prefix="/api/hc/media")

MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_FRAMES = 30


def _ffprobe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return max(0.0, float((r.stdout or "0").strip()))
    except Exception:
        return 0.0


@router.post("/video-frames")
async def video_frames(file: UploadFile = File(...),
                       fps: float = Form(1.0),
                       max_frames: int = Form(20),
                       width: int = Form(1280)):
    """Extract evenly-spaced JPEG frames from an uploaded video."""
    fps = min(max(float(fps or 1.0), 0.25), 4.0)
    max_frames = min(max(int(max_frames or 20), 1), MAX_FRAMES)
    width = min(max(int(width or 1280), 320), 1920)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="vidéo vide")
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="vidéo trop lourde (max 100 Mo)")
    with tempfile.TemporaryDirectory(prefix="hcf-vid-") as tmp:
        src = str(Path(tmp) / "in.mp4")
        Path(src).write_bytes(data)
        duration = _ffprobe_duration(src)
        if duration <= 0:
            raise HTTPException(status_code=422, detail="vidéo illisible")
        # even spacing across the whole clip (better than fixed fps for long videos)
        n = min(max_frames, max(1, int(duration * fps)))
        vf = f"fps={n}/{duration:.3f},scale={width}:-2"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", src,
                 "-vf", vf, "-q:v", "4", f"{tmp}/f%03d.jpg"],
                capture_output=True, timeout=120, check=True)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=422, detail="extraction trop longue")
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=422, detail="ffmpeg: extraction impossible")
        frames = []
        for jpg in sorted(Path(tmp).glob("f*.jpg"))[:n]:
            b64 = base64.b64encode(jpg.read_bytes()).decode()
            frames.append({"url": f"data:image/jpeg;base64,{b64}",
                           "t": round(len(frames) * duration / max(n, 1), 1)})
    return {"ok": True, "n_frames": len(frames), "duration_s": round(duration, 1),
            "frames": frames,
            "note": f"{len(frames)} images extraites — envoyez-les comme pièces jointes + décrivez ce qu'on doit y chercher."}
