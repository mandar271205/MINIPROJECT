"""
CCTV Attendance System (DeepFace version)
==========================================
Uses DeepFace for embedding-based face matching.
No training needed. Works on Windows with a simple pip install.

Requirements:
    pip install deepface opencv-python numpy pandas tqdm

Usage:
    python cctv_attendance.py
"""

import os
import zipfile
import cv2
import numpy as np
import pandas as pd
from datetime import timedelta
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#         ✅ CONFIGURE THESE 3 VARS
# ─────────────────────────────────────────────

ZIP_PATH         = ""
VIDEO_PATH       = ""
GRACE_PERIOD_MIN = 15                   # Grace period in minutes from video start (second 0 = shift start)

# ─────────────────────────────────────────────
#         ⚙️  OPTIONAL TUNING (don't need to touch)
# ─────────────────────────────────────────────

FRAME_SAMPLE_EVERY = 2.0                      # Sample one frame every N seconds
MATCH_THRESHOLD    = 0.55                     # Cosine distance threshold (0.4–0.6 good for CCTV)
MODEL_NAME         = "Facenet512"             # Options: "Facenet512", "ArcFace", "Facenet"
DETECTOR_BACKEND   = "opencv"                 # Options: "opencv" (fast), "retinaface" (accurate)
EXTRACT_DIR        = "_ref_faces_extracted"   # Temp folder for unzipped images
OUTPUT_CSV         = "attendance_report.csv"  # Output file name

# ─────────────────────────────────────────────────────────────────────────────


def seconds_to_hhmmss(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


def load_reference_faces(zip_path: str, extract_dir: str) -> dict:
    """
    Unzip reference images and compute face embeddings for each person.
    Image filename (without extension) = person's name.
    e.g. Asim_Khan.jpg → "Asim Khan"
    """
    from deepface import DeepFace

    log.info(f"📦 Extracting ZIP: {zip_path}")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)

    supported = (".jpg", ".jpeg", ".png", ".webp")
    image_files = []
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f.lower().endswith(supported) and not f.startswith("__MACOSX"):
                image_files.append(os.path.join(root, f))

    log.info(f"🖼️  Found {len(image_files)} reference image(s). Building embeddings...")

    known_encodings = {}
    for img_path in image_files:
        name = os.path.splitext(os.path.basename(img_path))[0].replace("_", " ").strip()
        try:
            result = DeepFace.represent(
                img_path=img_path,
                model_name=MODEL_NAME,
                detector_backend=DETECTOR_BACKEND,
                enforce_detection=True
            )
            embedding = np.array(result[0]["embedding"])
            known_encodings[name] = embedding
            log.info(f"  ✅ Encoded: {name}")
        except Exception as e:
            log.warning(f"  ⚠️  Could not encode {img_path}: {e} — skipping.")

    log.info(f"✔️  {len(known_encodings)} people registered.\n")
    return known_encodings


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return 1 - np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def process_video(video_path: str, known_encodings: dict) -> dict:
    """
    Sample frames from the video, detect + encode faces,
    match against reference embeddings using cosine distance.
    Returns: { person_name: first_detected_video_second }
    """
    from deepface import DeepFace

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    fps          = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s   = total_frames / fps
    sample_step  = int(fps * FRAME_SAMPLE_EVERY)

    log.info(f"🎥 Video: {video_path}")
    log.info(f"   FPS={fps:.1f} | Duration={seconds_to_hhmmss(duration_s)} | Total frames={total_frames}")
    log.info(f"   Sampling every {FRAME_SAMPLE_EVERY}s → ~{int(duration_s / FRAME_SAMPLE_EVERY)} frames to check\n")

    known_names = list(known_encodings.keys())
    known_vecs  = list(known_encodings.values())
    first_seen  = {}
    frame_idx   = 0

    total_samples = max(1, int(total_frames / sample_step))
    pbar = tqdm(total=total_samples, desc="Processing video", unit="frame")

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        video_second = frame_idx / fps

        # Resize for speed
        small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)

        try:
            # Detect + encode all faces in this frame
            faces = DeepFace.represent(
                img_path=small,
                model_name=MODEL_NAME,
                detector_backend=DETECTOR_BACKEND,
                enforce_detection=True
            )

            for face_data in faces:
                face_vec = np.array(face_data["embedding"])

                # Compare against all registered people
                distances = [cosine_distance(face_vec, ref_vec) for ref_vec in known_vecs]
                best_idx  = int(np.argmin(distances))
                best_dist = distances[best_idx]

                if best_dist <= MATCH_THRESHOLD:
                    matched_name = known_names[best_idx]
                    if matched_name not in first_seen:
                        first_seen[matched_name] = video_second
                        log.info(
                            f"  👤 Detected: {matched_name} at "
                            f"{seconds_to_hhmmss(video_second)} into video "
                            f"(dist={best_dist:.3f})"
                        )

        except Exception:
            # No face detected in this frame — normal, just skip
            pass

        # Early exit if everyone found
        if len(first_seen) == len(known_names):
            log.info("✅ All registered people detected — stopping early.")
            break

        frame_idx += sample_step
        pbar.update(1)

    pbar.close()
    cap.release()
    return first_seen


def compute_attendance(known_encodings: dict, first_seen: dict) -> pd.DataFrame:
    """
    Video second 0 = shift start.
    0 → GRACE_PERIOD_MIN * 60  →  Present
    Beyond grace period         →  Late
    Never detected              →  Absent
    """
    grace_period_sec = GRACE_PERIOD_MIN * 60

    rows = []
    for name in known_encodings:
        if name not in first_seen:
            status      = "Absent"
            detected_at = "-"
        else:
            vid_sec     = first_seen[name]
            detected_at = seconds_to_hhmmss(vid_sec)
            status      = "Present" if vid_sec <= grace_period_sec else "Late"

        rows.append({
            "Name":                   name,
            "Status":                 status,
            "Detected At (in video)": detected_at,
        })

    df = pd.DataFrame(rows).sort_values("Name").reset_index(drop=True)
    return df


def print_summary(df: pd.DataFrame):
    print("\n" + "═" * 55)
    print("              📋  ATTENDANCE REPORT")
    print(f"         Grace Period: {GRACE_PERIOD_MIN} mins from video start")
    print("═" * 55)
    for _, row in df.iterrows():
        icon = {"Present": "✅", "Late": "🕐", "Absent": "❌"}.get(row["Status"], "?")
        print(f"  {icon}  {row['Name']:<25} {row['Status']:<10}  {row['Detected At (in video)']}")
    print("═" * 55)
    counts = df["Status"].value_counts()
    print(f"  Present: {counts.get('Present', 0)}  |  Late: {counts.get('Late', 0)}  |  Absent: {counts.get('Absent', 0)}")
    print("═" * 55 + "\n")


def main():
    log.info("🚀 CCTV Attendance System Starting...\n")

    # Step 1: Load reference faces from ZIP
    known_encodings = load_reference_faces(ZIP_PATH, EXTRACT_DIR)
    if not known_encodings:
        log.error("No valid faces found in ZIP. Exiting.")
        return

    # Step 2: Process video
    first_seen = process_video(VIDEO_PATH, known_encodings)

    # Step 3: Compute attendance
    df = compute_attendance(known_encodings, first_seen)

    # Step 4: Output
    print_summary(df)
    df.to_csv(OUTPUT_CSV, index=False)
    log.info(f"💾 Report saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()