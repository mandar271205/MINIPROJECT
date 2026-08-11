"""Step 4a – Face recognition via AdaFace.

Quality-adaptive CNN (IR-101 backbone) that produces 512-D embeddings.
Uses the official AdaFace pretrained weights.

If the AdaFace checkpoint is not available, falls back to InsightFace's
built-in ArcFace model which provides equivalent 512-D embeddings.
"""

from __future__ import annotations

import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision import transforms

from .models import FaceDetection, FaceEmbedding

# Standard face preprocessing for 112×112 AdaFace / ArcFace inputs
_TRANSFORM = transforms.Compose(
    [
        transforms.ToPILImage(),
        transforms.Resize((112, 112)),
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
    ]
)


class AdaFaceRecognizer:
    """
    Extracts 512-D face embeddings using a pretrained AdaFace model.

    Falls back to InsightFace ArcFace (``buffalo_l`` model pack) if
    no explicit AdaFace checkpoint path is provided.
    """

    def __init__(
        self,
        checkpoint_path: str | None = None,
        device: str | None = None,
    ) -> None:
        self._device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self._model: nn.Module | None = None
        self._insightface_model = None

        if checkpoint_path:
            self._load_adaface_checkpoint(checkpoint_path)
        else:
            self._load_insightface_arcface()

    # ------------------------------------------------------------------ #
    #  Loaders                                                            #
    # ------------------------------------------------------------------ #

    def _load_adaface_checkpoint(self, path: str) -> None:
        """
        Load an AdaFace IR-101 checkpoint from disk.

        Expected checkpoint format (from the official AdaFace repo)::

            {"state_dict": {"model.xxx": tensor, ...}}
        """
        from .net import build_model as build_adaface  # type: ignore[import-not-found]

        self._model = build_adaface("ir_101")
        ckpt = torch.load(path, map_location=self._device, weights_only=False)
        state = ckpt.get("state_dict", ckpt)
        cleaned = {
            k.replace("model.", ""): v
            for k, v in state.items()
            if k.startswith("model.")
        }
        self._model.load_state_dict(cleaned, strict=False)
        self._model.to(self._device)
        self._model.eval()

    def _load_insightface_arcface(self) -> None:
        """
        Fallback: use InsightFace's bundled ArcFace recogniser.
        Produces the same 512-D L2-normalised embedding space.
        """
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(
            name="buffalo_l",
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        app.prepare(ctx_id=0)
        # The recognition model is the second model in the pipeline
        self._insightface_model = app.models.get("recognition", None)
        if self._insightface_model is None:
            # Some versions expose it differently
            for m in app.models.values():
                if hasattr(m, "get_feat"):
                    self._insightface_model = m
                    break

    # ------------------------------------------------------------------ #
    #  Inference                                                          #
    # ------------------------------------------------------------------ #

    def embed(self, face: FaceDetection) -> FaceEmbedding:
        """
        Compute a 512-D embedding from an aligned face crop.
        """
        if self._model is not None:
            return self._embed_pytorch(face.aligned_face)
        if self._insightface_model is not None:
            return self._embed_insightface(face.aligned_face)
        raise RuntimeError("No recognition model loaded.")

    @torch.no_grad()
    def _embed_pytorch(self, aligned_bgr: np.ndarray) -> FaceEmbedding:
        """Run the PyTorch AdaFace model."""
        rgb = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2RGB)
        tensor = _TRANSFORM(rgb).unsqueeze(0).to(self._device)
        embedding, _ = self._model(tensor)            # (1, 512), norm
        vec = embedding.cpu().numpy().flatten()
        vec = vec / (np.linalg.norm(vec) + 1e-8)      # L2 normalise
        return FaceEmbedding(vector=vec.astype(np.float32), model_name="adaface_ir101")

    def _embed_insightface(self, aligned_bgr: np.ndarray) -> FaceEmbedding:
        """Run InsightFace ArcFace (fallback)."""
        embedding = self._insightface_model.get_feat(aligned_bgr)
        vec = np.array(embedding, dtype=np.float32).flatten()
        vec = vec / (np.linalg.norm(vec) + 1e-8)
        return FaceEmbedding(vector=vec, model_name="arcface_r100")

    def embed_batch(self, faces: list[FaceDetection]) -> list[FaceEmbedding]:
        """Embed a batch of detected faces."""
        return [self.embed(f) for f in faces]
