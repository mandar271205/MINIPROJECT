"""Step 5 – Matching.

Compare a query embedding against the enrolled student database
using cosine similarity with vectorised NumPy operations.
"""

from __future__ import annotations

import numpy as np

from .models import EnrolledStudent, FaceEmbedding, MatchResult


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def match_face(
    query: FaceEmbedding,
    enrolled: list[EnrolledStudent],
    threshold: float = 0.55,
) -> MatchResult:
    """
    Find the best matching enrolled student for *query*.

    Uses vectorised matrix multiplication for speed when the
    enrolled list is large.

    Parameters
    ----------
    query : FaceEmbedding
        The 512-D embedding of the detected face.
    enrolled : list[EnrolledStudent]
        All enrolled students with their stored embeddings.
    threshold : float
        Minimum cosine similarity for a positive match.

    Returns
    -------
    MatchResult
        Contains the best student match (or None if below threshold).
    """
    if not enrolled:
        return MatchResult(
            student_id=None,
            student_name=None,
            similarity=0.0,
            is_match=False,
        )

    # Build (N, 512) matrix of enrolled embeddings
    db_matrix = np.stack([s.embedding for s in enrolled])   # (N, 512)
    q = query.vector.reshape(1, -1)                         # (1, 512)

    # L2-normalise both sides
    q_norm = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-8)
    db_norm = db_matrix / (
        np.linalg.norm(db_matrix, axis=1, keepdims=True) + 1e-8
    )

    # Cosine similarities via matrix multiply
    similarities = (q_norm @ db_norm.T).flatten()           # (N,)

    best_idx = int(np.argmax(similarities))
    best_sim = float(similarities[best_idx])

    if best_sim >= threshold:
        best = enrolled[best_idx]
        return MatchResult(
            student_id=best.student_id,
            student_name=best.name,
            similarity=best_sim,
            is_match=True,
        )

    return MatchResult(
        student_id=None,
        student_name=None,
        similarity=best_sim,
        is_match=False,
    )


def match_face_top_k(
    query: FaceEmbedding,
    enrolled: list[EnrolledStudent],
    k: int = 5,
    threshold: float = 0.55,
) -> list[MatchResult]:
    """
    Return the top-*k* matches above *threshold*, sorted by
    descending similarity.
    """
    if not enrolled:
        return []

    db_matrix = np.stack([s.embedding for s in enrolled])
    q = query.vector.reshape(1, -1)

    q_norm = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-8)
    db_norm = db_matrix / (
        np.linalg.norm(db_matrix, axis=1, keepdims=True) + 1e-8
    )

    similarities = (q_norm @ db_norm.T).flatten()

    # Get top-k indices
    top_indices = np.argsort(similarities)[::-1][:k]

    results = []
    for idx in top_indices:
        sim = float(similarities[idx])
        if sim < threshold:
            break
        s = enrolled[idx]
        results.append(
            MatchResult(
                student_id=s.student_id,
                student_name=s.name,
                similarity=sim,
                is_match=True,
            )
        )
    return results
