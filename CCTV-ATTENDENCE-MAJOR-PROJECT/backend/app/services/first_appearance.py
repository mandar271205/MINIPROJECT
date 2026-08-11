"""Step 6 – First-appearance tracker.

Keeps the earliest timestamp at which each student was matched,
along with the match confidence at that first sighting.
"""

from __future__ import annotations

from .models import FirstAppearance, MatchResult


class FirstAppearanceTracker:
    """Track the earliest detection per student across all frames."""

    def __init__(self) -> None:
        # student_id -> {"name": str, "timestamp": float, "confidence": float}
        self._records: dict[int, dict] = {}

    def update(
        self,
        match: MatchResult,
        timestamp_sec: float,
    ) -> None:
        """
        Record a sighting for the matched student.
        Only the **earliest** sighting is retained.

        Parameters
        ----------
        match : MatchResult
            A positive match result (``is_match=True``).
        timestamp_sec : float
            The video timestamp (seconds) at which the face was detected.
        """
        if not match.is_match or match.student_id is None:
            return

        sid = match.student_id
        if sid not in self._records or timestamp_sec < self._records[sid]["timestamp"]:
            self._records[sid] = {
                "name": match.student_name or "",
                "timestamp": timestamp_sec,
                "confidence": match.similarity,
            }

    def get(self, student_id: int) -> FirstAppearance | None:
        """Return the first-appearance record for a single student."""
        rec = self._records.get(student_id)
        if rec is None:
            return None
        return FirstAppearance(
            student_id=student_id,
            student_name=rec["name"],
            first_seen_sec=rec["timestamp"],
            confidence=rec["confidence"],
        )

    def get_all(self) -> list[FirstAppearance]:
        """Return first-appearance records for every detected student."""
        return [
            FirstAppearance(
                student_id=sid,
                student_name=rec["name"],
                first_seen_sec=rec["timestamp"],
                confidence=rec["confidence"],
            )
            for sid, rec in sorted(self._records.items())
        ]

    @property
    def detected_student_ids(self) -> set[int]:
        """Set of student IDs that have been seen at least once."""
        return set(self._records.keys())

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, student_id: int) -> bool:
        return student_id in self._records
