from __future__ import annotations

import numpy as np


def compute_embedding(image_path, model_name: str, detector_backend: str) -> np.ndarray:
    from deepface import DeepFace

    result = DeepFace.represent(
        img_path=image_path,
        model_name=model_name,
        detector_backend=detector_backend,
        enforce_detection=True,
    )
    return np.array(result[0]["embedding"], dtype=float)


def compute_embeddings_from_frame(frame, model_name: str, detector_backend: str) -> list[np.ndarray]:
    from deepface import DeepFace

    results = DeepFace.represent(
        img_path=frame,
        model_name=model_name,
        detector_backend=detector_backend,
        enforce_detection=True,
    )
    return [np.array(item["embedding"], dtype=float) for item in results]


def cosine_distance(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    return 1 - np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))


def best_match(embedding: np.ndarray, known_embeddings: list[np.ndarray]) -> tuple[int | None, float | None]:
    if not known_embeddings:
        return None, None
    distances = [cosine_distance(embedding, ref) for ref in known_embeddings]
    best_idx = int(np.argmin(distances))
    return best_idx, distances[best_idx]
