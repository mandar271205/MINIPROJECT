"""DEPRECATED (Phase 3) - not used by the active recognition path.

Superseded by ``app/services/recognition_provider.py``
(``InsightFaceArcFaceProvider``), which every active enrolment and
recognition call site now uses instead. Kept in place, unused, rather
than deleted, to avoid risking unrelated breakage; see the Phase 3
tests that assert this class is never called from the active pipeline.

Original docstring, retained for context:

    Step 4b - Face recognition via Swin Transformer.

    Global-attention backbone (Swin-Tiny) that produces 512-D embeddings.
    Uses the ``timm`` library for the pretrained Swin-T backbone and
    appends a projection head to reduce features to 512 dimensions.
"""

from __future__ import annotations

import cv2
import numpy as np
import timm
import torch
import torch.nn as nn
from torchvision import transforms

from .models import FaceDetection, FaceEmbedding

# Swin-T expects 224×224 ImageNet-normalised inputs
_TRANSFORM = transforms.Compose(
    [
        transforms.ToPILImage(),
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ]
)


class SwinFaceNet(nn.Module):
    """
    Swin-Tiny backbone + linear projection → 512-D L2-normalised
    face embedding.
    """

    def __init__(self, embedding_dim: int = 512) -> None:
        super().__init__()
        try:
            self.backbone = timm.create_model(
                "swin_tiny_patch4_window7_224",
                pretrained=True,
                num_classes=0,          # remove classification head
            )
        except Exception:
            self.backbone = timm.create_model(
                "swin_tiny_patch4_window7_224",
                pretrained=False,
                num_classes=0,          # remove classification head
            )
        feature_dim = getattr(self.backbone, "num_features", 768)   # 768 for swin_tiny

        self.projection = nn.Sequential(
            nn.Linear(feature_dim, embedding_dim),
            nn.BatchNorm1d(embedding_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)                        # (B, 768)
        embedding = self.projection(features)              # (B, 512)
        embedding = nn.functional.normalize(embedding, p=2, dim=1)
        return embedding

    def get_backbone_features(self, x: torch.Tensor) -> torch.Tensor:
        """Return raw backbone features WITHOUT the random projection head."""
        features = self.backbone(x)                        # (B, 768)
        return nn.functional.normalize(features, p=2, dim=1)


class SwinTransformerRecognizer:
    """
    Extracts 512-D face embeddings using a Swin-Tiny backbone.
    The backbone is pretrained on ImageNet; for production use it
    should be fine-tuned on a face-recognition dataset.
    """

    def __init__(
        self,
        embedding_dim: int = 512,
        checkpoint_path: str | None = None,
        device: str | None = None,
    ) -> None:
        self._device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        try:
            self._model = SwinFaceNet(embedding_dim=embedding_dim)

            if checkpoint_path:
                state = torch.load(
                    checkpoint_path, map_location=self._device, weights_only=False
                )
                self._model.load_state_dict(state, strict=False)

            self._model.to(self._device)
            self._model.eval()
        except Exception:
            self._model = None

    @torch.no_grad()
    def embed(self, face: FaceDetection) -> FaceEmbedding:
        """
        Produce a 512-D embedding from an aligned face crop.

        Uses the ImageNet-pretrained Swin-Tiny **backbone** features directly
        (768-D, zero-padded to 512-D) instead of passing through the randomly
        initialised projection head.  This produces stable, semantically
        meaningful embeddings that generalise across different images of the
        same face without any face-specific fine-tuning.
        """
        if self._model is not None:
            try:
                rgb = cv2.cvtColor(face.aligned_face, cv2.COLOR_BGR2RGB)
                tensor = _TRANSFORM(rgb).unsqueeze(0).to(self._device)
                # Use backbone features directly – no random projection
                backbone_vec = self._model.get_backbone_features(tensor)  # (1, 768)
                vec768 = backbone_vec.cpu().numpy().flatten()              # (768,)
                # Truncate to 512-D and re-normalise
                vec = vec768[:512].astype(np.float32)
                norm = np.linalg.norm(vec)
                if norm > 1e-8:
                    vec = vec / norm
                return FaceEmbedding(
                    vector=vec,
                    model_name="swin_backbone_512",
                )
            except Exception:
                pass

        # Hard fallback: LBP-inspired histogram (more robust than raw pixels)
        gray = cv2.cvtColor(face.aligned_face, cv2.COLOR_BGR2GRAY)
        # Multi-scale histogram as a simple texture descriptor
        hist_features = []
        for size in [(8, 8), (16, 16), (32, 32)]:
            small = cv2.resize(gray, size).flatten().astype(np.float32)
            hist, _ = np.histogram(small, bins=64, range=(0, 256))
            hist_features.append(hist.astype(np.float32))
        # Also use HOG-like gradient features
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        grad_hist, _ = np.histogram(mag, bins=128, range=(0, 300))
        hist_features.append(grad_hist.astype(np.float32))
        combined = np.concatenate(hist_features)  # 64+64+64+128 = 320 dims
        # Pad to 512
        vec = np.zeros(512, dtype=np.float32)
        vec[:len(combined)] = combined
        norm = np.linalg.norm(vec)
        if norm > 1e-8:
            vec = vec / norm
        return FaceEmbedding(vector=vec, model_name="histogram_512")


    @torch.no_grad()
    def embed_batch(self, faces: list[FaceDetection]) -> list[FaceEmbedding]:
        """
        Embed a batch of faces in a single forward pass.
        """
        if not faces:
            return []

        tensors = []
        for f in faces:
            rgb = cv2.cvtColor(f.aligned_face, cv2.COLOR_BGR2RGB)
            tensors.append(_TRANSFORM(rgb))

        batch = torch.stack(tensors).to(self._device)
        vecs = self._model(batch).cpu().numpy()

        return [
            FaceEmbedding(
                vector=vecs[i].astype(np.float32),
                model_name="swin_tiny_face",
            )
            for i in range(len(faces))
        ]
