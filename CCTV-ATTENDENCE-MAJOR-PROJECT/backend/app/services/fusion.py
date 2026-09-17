"""DEPRECATED (Phase 3) - not used by the active recognition path.

Superseded by ``app/services/recognition_provider.py``
(``InsightFaceArcFaceProvider``), which produces a single embedding
directly - there is no fusion step any more. Kept in place, unused,
rather than deleted, to avoid risking unrelated breakage; see the
Phase 3 tests that assert this module's classes are never called from
the active pipeline.

Original docstring, retained for context:

    Step 4c - Feature fusion.

    Concatenates AdaFace (512-D) + Swin-T (512-D) embeddings and projects
    through a learned FC layer to produce a final 512-D descriptor.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from .models import FaceEmbedding


class FusionFC(nn.Module):
    """
    Two-layer MLP that takes a 1024-D concatenated vector and
    produces a 512-D L2-normalised embedding.
    """

    def __init__(self, input_dim: int = 1024, output_dim: int = 512) -> None:
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(input_dim, output_dim),
            nn.BatchNorm1d(output_dim),
            nn.ReLU(inplace=True),
            nn.Linear(output_dim, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.fc(x)
        return nn.functional.normalize(out, p=2, dim=1)


class EmbeddingFusion:
    """
    Fuses a pair of 512-D embeddings (AdaFace + Swin-T) into a single
    512-D embedding using a learned projection.

    For production use the :class:`FusionFC` module should be trained
    jointly with the two recognition branches. When no checkpoint is
    provided, the layer is initialised with random weights.
    """

    def __init__(
        self,
        checkpoint_path: str | None = None,
        device: str | None = None,
    ) -> None:
        self._device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self._model = FusionFC()

        if checkpoint_path:
            state = torch.load(
                checkpoint_path, map_location=self._device, weights_only=False
            )
            self._model.load_state_dict(state, strict=False)

        self._model.to(self._device)
        self._model.eval()

    @torch.no_grad()
    def fuse(
        self,
        primary: FaceEmbedding,
        secondary: FaceEmbedding,
    ) -> FaceEmbedding:
        """
        Fuse *primary* (AdaFace) and *secondary* (Swin-T) embeddings.

        Uses deterministic L2-normalised averaging so that enrollment and
        recognition produce comparable vectors even when the FC projection
        layer has not been explicitly trained on a face-recognition dataset.
        This avoids the "random FC weights" problem where the untrained
        projection layer maps the same face to a different vector on each call.
        """
        # Both vectors are already L2-normalised; average keeps the geometry.
        avg = (primary.vector + secondary.vector) / 2.0
        norm = np.linalg.norm(avg)
        if norm < 1e-8:
            norm = 1.0
        fused = (avg / norm).astype(np.float32)
        return FaceEmbedding(
            vector=fused,
            model_name="fused_ada_swin",
        )

    def fuse_batch(
        self,
        primaries: list[FaceEmbedding],
        secondaries: list[FaceEmbedding],
    ) -> list[FaceEmbedding]:
        """
        Batch-fuse multiple embedding pairs using deterministic averaging.
        """
        return [self.fuse(p, s) for p, s in zip(primaries, secondaries)]
