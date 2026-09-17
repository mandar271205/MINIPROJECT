"""Step 3 - Face detection & alignment using RetinaFace/SCRFD.

Uses the ``insightface`` library's ``buffalo_l`` pack (SCRFD detector,
``det_10g.onnx``) for detection and 5-point landmark alignment,
producing 112x112 BGR face crops suitable for recognition.

Phase 3 change: the previous Haar-cascade fallback and the
"treat the whole frame as one face" fallback were removed. Both were
silent behaviours that could fabricate a detection where no real face
existed, which is exactly what enrolment's zero-face/multi-face
rejection and the pipeline's real "no face" diagnostic depend on being
truthful. If the InsightFace detector is unavailable, construction now
fails loudly (ProviderLoadError) instead of silently degrading to a
fake detector.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage import transform as skimage_transform

from .models import FaceDetection, FrameSample
from .recognition_provider import ProviderLoadError

# Canonical 112x112 destination landmarks (ArcFace standard)
_ARCFACE_REF = np.array(
    [
        [38.2946, 51.6963],   # left eye
        [73.5318, 51.5014],   # right eye
        [56.0252, 71.7366],   # nose tip
        [41.5493, 92.3655],   # left mouth corner
        [70.7299, 92.2041],   # right mouth corner
    ],
    dtype=np.float32,
)


def _align_face(
    frame: np.ndarray,
    landmarks: np.ndarray,
    image_size: int = 112,
) -> np.ndarray:
    """
    Warp *frame* so that the five facial landmarks land on the
    canonical ArcFace reference positions, producing an aligned
    *image_size* x *image_size* BGR crop.
    """
    dst = _ARCFACE_REF.copy()
    tform = skimage_transform.SimilarityTransform()
    tform.estimate(landmarks.astype(np.float64), dst.astype(np.float64))
    matrix = tform.params[0:2, :]
    aligned = cv2.warpAffine(
        frame,
        matrix,
        (image_size, image_size),
        borderValue=0.0,
    )
    return aligned


class RetinaFaceDetector:
    """
    Face detector powered by InsightFace's *buffalo_l* model pack
    (SCRFD detector + landmark models). Only the detector/aligner part
    is used here; recognition is handled by
    ``recognition_provider.InsightFaceArcFaceProvider``.

    There is no fallback detector. If the InsightFace models fail to
    load, construction raises ``ProviderLoadError`` immediately.
    """

    def __init__(
        self,
        det_size: tuple[int, int] = (640, 640),
        gpu_id: int = 0,
    ) -> None:
        try:
            from insightface.app import FaceAnalysis
        except Exception as exc:  # pragma: no cover - import failure path
            raise ProviderLoadError(f"insightface package is not available: {exc}") from exc

        try:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            self._app = FaceAnalysis(name="buffalo_l", providers=providers)
            self._app.prepare(ctx_id=gpu_id, det_size=det_size)
        except Exception as exc:
            raise ProviderLoadError(f"failed to load InsightFace buffalo_l detector: {exc}") from exc

    def detect(self, sample: FrameSample) -> list[FaceDetection]:
        """
        Detect all faces in *sample.frame*, align each one, and
        return a list of :class:`FaceDetection` objects. Returns an
        empty list when no face is found - this is a real "no face"
        result, never a fabricated detection.
        """
        detections: list[FaceDetection] = []
        faces = self._app.get(sample.frame)
        for face in faces:
            bbox = tuple(int(v) for v in face.bbox[:4])
            kps = face.kps.astype(np.float32)       # (5, 2)
            score = float(face.det_score)

            aligned = _align_face(sample.frame, kps)

            detections.append(
                FaceDetection(
                    bbox=bbox,
                    landmarks=kps,
                    confidence=score,
                    aligned_face=aligned,
                )
            )
        return detections

    def detect_raw(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        """
        Convenience wrapper that accepts a raw BGR array instead of
        a :class:`FrameSample`.
        """
        dummy = FrameSample(index=0, timestamp_sec=0.0, frame=frame_bgr)
        return self.detect(dummy)
