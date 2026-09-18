"""Phase 4 - sliding-window identity voting per temporary face track.

Confirms a student identity for a track only after enough consistent
evidence accumulates across the track's most recent observations -
never from a single frame/observation. This is evidence accumulation,
not an immediate final identity decision; see pipeline.py for how a
CONFIRMED track's evidence is the only thing allowed to feed the
temporary legacy attendance output.

Development defaults only (see Config.IDENTITY_*) - not scientifically
calibrated thresholds. Real calibration requires labelled footage.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..utils.config_validation import ConfigValidationError, validate_voting_config


class VotingConfigError(ValueError):
    pass


@dataclass
class VoteObservation:
    """The minimal shape voting needs, decoupled from the ORM model so
    this module has no database dependency."""
    top1_student_id: int | None
    top1_similarity: float | None
    top2_student_id: int | None
    top2_similarity: float | None
    above_threshold: bool
    timestamp_sec: float


@dataclass
class VoteResult:
    state: str
    confirmed_student_id: int | None
    mean_confidence: float | None
    max_confidence: float | None
    support_count: int
    support_ratio: float
    identity_conflict: bool
    conflict_reason: str | None
    confirmation_timestamp_sec: float | None


class IdentityVotingEngine:
    def __init__(
        self,
        *,
        window_size: int,
        min_support: int,
        min_support_ratio: float,
        min_mean_confidence: float,
        min_margin: float,
        conflict_support: int,
        unlock_policy: str = "never",
    ) -> None:
        try:
            validate_voting_config(
                {
                    "IDENTITY_VOTE_WINDOW_SIZE": window_size,
                    "IDENTITY_MIN_SUPPORT": min_support,
                    "IDENTITY_MIN_SUPPORT_RATIO": min_support_ratio,
                    "IDENTITY_MIN_MEAN_CONFIDENCE": min_mean_confidence,
                    "IDENTITY_MIN_MARGIN": min_margin,
                    "IDENTITY_CONFLICT_SUPPORT": conflict_support,
                    "IDENTITY_UNLOCK_POLICY": unlock_policy,
                }
            )
        except ConfigValidationError as exc:
            raise VotingConfigError(str(exc)) from exc
        self.window_size = window_size
        self.min_support = min_support
        self.min_support_ratio = min_support_ratio
        self.min_mean_confidence = min_mean_confidence
        self.min_margin = min_margin
        self.conflict_support = conflict_support
        self.unlock_policy = unlock_policy

    def vote(
        self,
        observations: list[VoteObservation],
        *,
        previous_confirmed_student_id: int | None = None,
    ) -> VoteResult:
        """Votes over the most recent `window_size` observations only -
        older observations never affect the current result."""
        window = observations[-self.window_size:]

        if not window:
            return VoteResult(
                state="UNCONFIRMED", confirmed_student_id=None, mean_confidence=None,
                max_confidence=None, support_count=0, support_ratio=0.0,
                identity_conflict=False, conflict_reason=None, confirmation_timestamp_sec=None,
            )

        valid = [
            o for o in window
            if o.top1_student_id is not None and o.above_threshold and o.top1_similarity is not None
        ]

        if not valid:
            # Evidence exists (faces were detected and embedded), but
            # nothing in the window ever qualified as a candidate.
            return VoteResult(
                state="UNKNOWN", confirmed_student_id=None, mean_confidence=None,
                max_confidence=None, support_count=0, support_ratio=0.0,
                identity_conflict=False, conflict_reason=None, confirmation_timestamp_sec=None,
            )

        support: dict[int, list[VoteObservation]] = {}
        for o in valid:
            support.setdefault(o.top1_student_id, []).append(o)

        ranked = sorted(
            support.items(),
            key=lambda kv: (-len(kv[1]), -(sum(x.top1_similarity for x in kv[1]) / len(kv[1])), kv[0]),
        )
        best_sid, best_obs = ranked[0]
        best_count = len(best_obs)
        best_ratio = best_count / len(window)
        best_mean_sim = sum(o.top1_similarity for o in best_obs) / best_count
        best_max_sim = max(o.top1_similarity for o in best_obs)
        margins = [
            (o.top1_similarity - o.top2_similarity) if o.top2_similarity is not None else 1.0
            for o in best_obs
        ]
        best_mean_margin = sum(margins) / len(margins)

        second_sid, second_obs = (ranked[1] if len(ranked) > 1 else (None, []))
        second_count = len(second_obs)
        is_tied_support = second_sid is not None and second_count == best_count

        # --- Identity lock: a track already confirmed for a student ---
        # A single/weak conflicting observation never switches or
        # un-confirms the identity. Only >= conflict_support strong
        # conflicting observations mark identity_conflict, and even
        # then the confirmed_student_id is preserved (never silently
        # switched to the conflicting candidate).
        if previous_confirmed_student_id is not None:
            conflicting = {
                sid: obs for sid, obs in support.items() if sid != previous_confirmed_student_id
            }
            strong_conflicts = {sid: obs for sid, obs in conflicting.items() if len(obs) >= self.conflict_support}
            locked_obs = support.get(previous_confirmed_student_id, [])
            locked_mean = (
                sum(o.top1_similarity for o in locked_obs) / len(locked_obs) if locked_obs else None
            )
            locked_max = max((o.top1_similarity for o in locked_obs), default=None)

            if strong_conflicts:
                conflicting_ids = sorted(strong_conflicts.keys())
                return VoteResult(
                    state="AMBIGUOUS",
                    confirmed_student_id=previous_confirmed_student_id,
                    mean_confidence=locked_mean, max_confidence=locked_max,
                    support_count=len(locked_obs), support_ratio=len(locked_obs) / len(window),
                    identity_conflict=True,
                    conflict_reason=(
                        f"{len(strong_conflicts)} competing candidate(s) {conflicting_ids} each "
                        f"received >= {self.conflict_support} supporting observations in the window"
                    ),
                    confirmation_timestamp_sec=None,
                )

            return VoteResult(
                state="CONFIRMED",
                confirmed_student_id=previous_confirmed_student_id,
                mean_confidence=locked_mean, max_confidence=locked_max,
                support_count=len(locked_obs), support_ratio=len(locked_obs) / len(window) if window else 0.0,
                identity_conflict=False, conflict_reason=None,
                confirmation_timestamp_sec=None,  # caller keeps the original confirmation timestamp
            )

        # --- Not yet confirmed: decide UNCONFIRMED / CONFIRMED / UNKNOWN / AMBIGUOUS ---
        if is_tied_support:
            return VoteResult(
                state="AMBIGUOUS", confirmed_student_id=None,
                mean_confidence=best_mean_sim, max_confidence=best_max_sim,
                support_count=best_count, support_ratio=best_ratio,
                identity_conflict=False,
                conflict_reason=f"tied support between candidates {sorted([best_sid, second_sid])}",
                confirmation_timestamp_sec=None,
            )

        meets_confirmation = (
            best_count >= self.min_support
            and best_ratio >= self.min_support_ratio
            and best_mean_sim >= self.min_mean_confidence
            and best_mean_margin >= self.min_margin
        )

        # A real second candidate close behind the best one, or a thin
        # margin against a genuine competitor, is ambiguity - not a
        # confident unknown and not "just needs more evidence". The
        # margin already reflects per-observation top-2 competition
        # even when that runner-up never itself became anyone's top-1
        # (e.g. a consistent close-second on every frame), so this
        # check does not require a distinct second top-1 candidate.
        has_real_margin_data = any(o.top2_similarity is not None for o in best_obs)
        if has_real_margin_data and best_mean_margin < self.min_margin:
            return VoteResult(
                state="AMBIGUOUS", confirmed_student_id=None,
                mean_confidence=best_mean_sim, max_confidence=best_max_sim,
                support_count=best_count, support_ratio=best_ratio,
                identity_conflict=False,
                conflict_reason=f"insufficient similarity margin against competing candidate {second_sid}",
                confirmation_timestamp_sec=None,
            )

        if meets_confirmation:
            confirmation_ts = min(o.timestamp_sec for o in best_obs)
            return VoteResult(
                state="CONFIRMED", confirmed_student_id=best_sid,
                mean_confidence=best_mean_sim, max_confidence=best_max_sim,
                support_count=best_count, support_ratio=best_ratio,
                identity_conflict=False, conflict_reason=None,
                confirmation_timestamp_sec=confirmation_ts,
            )

        if best_count < self.min_support or best_ratio < self.min_support_ratio:
            # Not enough consistent evidence yet - may still confirm
            # later as more observations arrive.
            return VoteResult(
                state="UNCONFIRMED", confirmed_student_id=None,
                mean_confidence=best_mean_sim, max_confidence=best_max_sim,
                support_count=best_count, support_ratio=best_ratio,
                identity_conflict=False, conflict_reason=None, confirmation_timestamp_sec=None,
            )

        # Enough count/ratio, but confidence or margin fell short - a
        # real candidate exists but doesn't reliably cross threshold.
        return VoteResult(
            state="UNKNOWN", confirmed_student_id=None,
            mean_confidence=best_mean_sim, max_confidence=best_max_sim,
            support_count=best_count, support_ratio=best_ratio,
            identity_conflict=False, conflict_reason=None, confirmation_timestamp_sec=None,
        )
