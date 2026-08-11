"""Step 4b – Face recognition via Swin Transformer.

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
        self.backbone = timm.create_model(
            "swin_tiny_patch4_window7_224",
            pretrained=True,
            num_classes=0,          # remove classification head
        )
        feature_dim = self.backbone.num_features   # 768 for swin_tiny

        self.projection = nn.Sequential(
            nn.Linear(feature_dim, embedding_dim),
            nn.BatchNorm1d(embedding_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        features = self.backbone(x)                        # (B, 768)
        embedding = self.projection(features)              # (B, 512)
        embedding = nn.functional.normalize(embedding, p=2, dim=1)
        return embedding


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
        self._model = SwinFaceNet(embedding_dim=embedding_dim)

        if checkpoint_path:
            state = torch.load(
                checkpoint_path, map_location=self._device, weights_only=False
            )
            self._model.load_state_dict(state, strict=False)

        self._model.to(self._device)
        self._model.eval()

    @torch.no_grad()
    def embed(self, face: FaceDetection) -> FaceEmbedding:
        """
        Produce a 512-D embedding from an aligned face crop.
        """
        rgb = cv2.cvtColor(face.aligned_face, cv2.COLOR_BGR2RGB)
        tensor = _TRANSFORM(rgb).unsqueeze(0).to(self._device)
        vec = self._model(tensor).cpu().numpy().flatten()
        return FaceEmbedding(
            vector=vec.astype(np.float32),
            model_name="swin_tiny_face",
        )

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
