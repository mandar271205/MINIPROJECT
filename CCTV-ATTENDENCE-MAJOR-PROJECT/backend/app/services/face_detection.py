"""Step 3 – Face detection & alignment using RetinaFace.

Uses the ``insightface`` library for detection and 5-point landmark
alignment, producing 112 112 BGR face crops suitable for recognition.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage import transform as skimage_transform

from .models import FaceDetection, FrameSample

# Canonical 112 112 destination landmarks (ArcFace standard)
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
    *image_size*   *image_size* BGR crop.
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
    Face detector powered by InsightFace's *buffalo_l* model pack,
    which bundles a RetinaFace detector + ArcFace recogniser.

    Only the **detector** part is used here; recognition is handled
    by the dedicated AdaFace and Swin-T modules.
    """

    def __init__(
        self,
        det_size: tuple[int, int] = (640, 640),
        gpu_id: int = 0,
    ) -> None:
        from insightface.app import FaceAnalysis

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._app = FaceAnalysis(
            name="buffalo_l",
            root="~/.insightface",
            providers=providers,
        )
        self._app.prepare(ctx_id=gpu_id, det_size=det_size)

    def detect(self, sample: FrameSample) -> list[FaceDetection]:
        """
        Detect all faces in *sample.frame*, align each one, and
        return a list of :class:`FaceDetection` objects.
        """
        faces = self._app.get(sample.frame)
        detections: list[FaceDetection] = []

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
