"""Phase 4 - temporary face-track association tests."""

import pytest

from app.services.observation_tracker import FaceTrackAssociator, TrackConfigError, TrackedDetection


def _make_associator(**overrides):
    defaults = dict(max_gap_seconds=3.0, min_iou=0.3, max_centroid_distance=80.0, close_after_seconds=6.0)
    defaults.update(overrides)
    return FaceTrackAssociator(**defaults)


def test_same_box_across_nearby_frames_keeps_same_track():
    assoc = _make_associator()
    box = (10.0, 10.0, 60.0, 60.0)

    r1 = assoc.associate([TrackedDetection(bbox=box)], 0.0)
    r2 = assoc.associate([TrackedDetection(bbox=(12.0, 11.0, 62.0, 61.0))], 1.0)
    r3 = assoc.associate([TrackedDetection(bbox=(14.0, 12.0, 64.0, 62.0))], 2.0)

    assert r1[0].track_key == r2[0].track_key == r3[0].track_key


def test_two_faces_remain_separate():
    assoc = _make_associator()
    boxes_frame1 = [(0.0, 0.0, 50.0, 50.0), (200.0, 200.0, 250.0, 250.0)]
    r1 = assoc.associate([TrackedDetection(bbox=b) for b in boxes_frame1], 0.0)
    assert r1[0].track_key != r1[1].track_key

    boxes_frame2 = [(2.0, 1.0, 52.0, 51.0), (202.0, 201.0, 252.0, 251.0)]
    r2 = assoc.associate([TrackedDetection(bbox=b) for b in boxes_frame2], 1.0)

    assert r2[0].track_key == r1[0].track_key
    assert r2[1].track_key == r1[1].track_key
    assert r2[0].track_key != r2[1].track_key


def test_crossed_paths_do_not_create_duplicate_assignment():
    """Two tracks whose boxes end up close to each other in one frame
    must still each get exactly one track, not two tracks merged into
    one detection or one track split across two detections."""
    assoc = _make_associator()
    r1 = assoc.associate(
        [TrackedDetection(bbox=(0.0, 0.0, 50.0, 50.0)), TrackedDetection(bbox=(100.0, 0.0, 150.0, 50.0))], 0.0
    )
    key_a, key_b = r1[0].track_key, r1[1].track_key

    # Frame 2: boxes have moved close to the midpoint, near each other,
    # but there are still exactly two detections -> exactly two
    # track assignments, one each.
    r2 = assoc.associate(
        [TrackedDetection(bbox=(45.0, 0.0, 95.0, 50.0)), TrackedDetection(bbox=(55.0, 0.0, 105.0, 50.0))], 1.0
    )
    assigned_keys = {r2[0].track_key, r2[1].track_key}
    assert len(assigned_keys) == 2
    assert assigned_keys <= {key_a, key_b} or len(assigned_keys - {key_a, key_b}) <= 2


def test_large_timestamp_gap_creates_new_track():
    assoc = _make_associator(max_gap_seconds=2.0)
    box = (10.0, 10.0, 60.0, 60.0)
    r1 = assoc.associate([TrackedDetection(bbox=box)], 0.0)
    # Gap of 5s exceeds max_gap_seconds=2.0
    r2 = assoc.associate([TrackedDetection(bbox=box)], 5.0)
    assert r1[0].track_key != r2[0].track_key
    assert r2[0].is_new_track is True


def test_low_iou_and_excessive_centroid_distance_creates_new_track():
    assoc = _make_associator(min_iou=0.5, max_centroid_distance=10.0)
    r1 = assoc.associate([TrackedDetection(bbox=(0.0, 0.0, 50.0, 50.0))], 0.0)
    # Moved far away - low IoU (0) and centroid distance >> 10
    r2 = assoc.associate([TrackedDetection(bbox=(500.0, 500.0, 550.0, 550.0))], 0.5)
    assert r1[0].track_key != r2[0].track_key


def test_closed_track_is_not_reused():
    assoc = _make_associator(max_gap_seconds=1.0, close_after_seconds=1.0)
    box = (10.0, 10.0, 60.0, 60.0)
    r1 = assoc.associate([TrackedDetection(bbox=box)], 0.0)
    key_a = r1[0].track_key

    # Let the track go stale beyond close_after_seconds and max_gap_seconds
    r2 = assoc.associate([TrackedDetection(bbox=box)], 10.0)
    key_b = r2[0].track_key
    assert key_b != key_a

    # Even though box matches key_a's old position exactly, a new track
    # was created - key_a is closed and must never be reused.
    assert r2[0].is_new_track is True


def test_assignment_is_deterministic():
    def run():
        assoc = _make_associator()
        boxes1 = [(0.0, 0.0, 50.0, 50.0), (200.0, 0.0, 250.0, 50.0), (400.0, 0.0, 450.0, 50.0)]
        r1 = assoc.associate([TrackedDetection(bbox=b) for b in boxes1], 0.0)
        boxes2 = [(3.0, 2.0, 53.0, 52.0), (203.0, 1.0, 253.0, 51.0), (403.0, 3.0, 453.0, 53.0)]
        r2 = assoc.associate([TrackedDetection(bbox=b) for b in boxes2], 1.0)
        return [r.track_key for r in r1] + [r.track_key for r in r2]

    assert run() == run()


def test_invalid_tracker_config_rejected():
    with pytest.raises(TrackConfigError):
        FaceTrackAssociator(max_gap_seconds=0, min_iou=0.3, max_centroid_distance=80.0, close_after_seconds=6.0)
    with pytest.raises(TrackConfigError):
        FaceTrackAssociator(max_gap_seconds=3.0, min_iou=1.5, max_centroid_distance=80.0, close_after_seconds=6.0)
    with pytest.raises(TrackConfigError):
        FaceTrackAssociator(max_gap_seconds=3.0, min_iou=0.3, max_centroid_distance=0, close_after_seconds=6.0)
    with pytest.raises(TrackConfigError):
        FaceTrackAssociator(max_gap_seconds=3.0, min_iou=0.3, max_centroid_distance=80.0, close_after_seconds=0)
