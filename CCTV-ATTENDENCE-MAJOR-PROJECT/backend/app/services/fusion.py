"""Step 4c – Feature fusion.

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
        Concatenate *primary* (AdaFace) and *secondary* (Swin-T)
        embeddings and project to a single 512-D vector.
        """
        concat = np.concatenate(
            [primary.vector, secondary.vector]
        )  # (1024,)
        tensor = torch.from_numpy(concat).float().unsqueeze(0).to(self._device)
        fused = self._model(tensor).cpu().numpy().flatten()
        return FaceEmbedding(
            vector=fused.astype(np.float32),
            model_name="fused_ada_swin",
        )

    @torch.no_grad()
    def fuse_batch(
        self,
        primaries: list[FaceEmbedding],
        secondaries: list[FaceEmbedding],
    ) -> list[FaceEmbedding]:
        """
        Batch-fuse multiple embedding pairs.
        """
        if not primaries:
            return []

        concats = [
            np.concatenate([p.vector, s.vector])
            for p, s in zip(primaries, secondaries)
        ]
        batch = torch.from_numpy(np.stack(concats)).float().to(self._device)
        fused_batch = self._model(batch).cpu().numpy()

        return [
            FaceEmbedding(
                vector=fused_batch[i].astype(np.float32),
                model_name="fused_ada_swin",
            )
            for i in range(len(primaries))
        ]
