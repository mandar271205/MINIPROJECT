"""Step 5 – Matching.

Compare a query embedding against the enrolled student database
using cosine similarity with vectorised NumPy operations.
"""

from __future__ import annotations

import numpy as np

from .models import EnrolledStudent, FaceEmbedding, MatchEvidence, MatchResult


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


def match_face_evidence(
    query: FaceEmbedding,
    enrolled: list[EnrolledStudent],
    threshold: float = 0.55,
) -> MatchEvidence:
    """
    Phase 4 - full top-1/top-2 evidence for one detection, for feeding
    into a face track's sliding-window vote (identity_voting.py).

    Never itself decides identity. Does not silently lower *threshold*
    - `above_threshold` simply reports whether the top-1 candidate
    cleared the caller-supplied value as-is.

    Handles safely:
      - no compatible templates -> all fields None, above_threshold=False
      - exactly one compatible template -> top2 fields None, margin None
      - a non-finite query vector -> all fields None, above_threshold=False
        (this is a defensive check; callers should already validate the
        embedding before calling)
      - tied similarities -> deterministic (stable sort keeps the
        earliest-indexed enrolled student as the higher-ranked one)
    """
    if not enrolled or not np.all(np.isfinite(query.vector)):
        return MatchEvidence(
            top1_student_id=None, top1_similarity=None,
            top2_student_id=None, top2_similarity=None,
            similarity_margin=None, above_threshold=False,
        )

    db_matrix = np.stack([s.embedding for s in enrolled])
    q = query.vector.reshape(1, -1)

    q_norm = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-8)
    db_norm = db_matrix / (np.linalg.norm(db_matrix, axis=1, keepdims=True) + 1e-8)

    similarities = (q_norm @ db_norm.T).flatten()

    # Stable sort: for tied similarities, the lower original index (the
    # earlier enrolled student) is ranked first - deterministic given a
    # fixed enrolled-list order.
    order = np.argsort(-similarities, kind="stable")

    top1_idx = int(order[0])
    top1_sim = float(similarities[top1_idx])
    top1_student = enrolled[top1_idx]

    top2_student_id = None
    top2_sim = None
    margin = None
    if len(enrolled) > 1:
        top2_idx = int(order[1])
        top2_sim = float(similarities[top2_idx])
        top2_student_id = enrolled[top2_idx].student_id
        margin = top1_sim - top2_sim

    return MatchEvidence(
        top1_student_id=top1_student.student_id,
        top1_similarity=top1_sim,
        top2_student_id=top2_student_id,
        top2_similarity=top2_sim,
        similarity_margin=margin,
        above_threshold=top1_sim >= threshold,
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
