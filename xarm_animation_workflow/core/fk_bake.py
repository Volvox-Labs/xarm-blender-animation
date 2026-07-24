"""Pure helpers for converting evaluated robot joint angles to FK controls."""

import math
from typing import Iterable, Optional, Sequence, Tuple


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def parse_rotation_axis(axis_spec: str) -> Tuple[int, int]:
    """Return ``(Euler index, sign)`` for specs such as ``Y`` or ``-Z``."""

    if not isinstance(axis_spec, str) or not axis_spec:
        raise ValueError("Rotation axis must be a non-empty string")

    sign = -1 if axis_spec.startswith("-") else 1
    axis_name = axis_spec[1:] if sign < 0 else axis_spec
    try:
        return _AXIS_INDEX[axis_name], sign
    except KeyError as exc:
        raise ValueError(f"Unsupported rotation axis: {axis_spec}") from exc


def nearest_equivalent_angle_deg(
    angle_deg: float,
    previous_deg: Optional[float],
    limits_deg: Tuple[float, float],
) -> float:
    """Choose the closest equivalent angle without leaving robot joint limits."""

    angle = float(angle_deg)
    if not math.isfinite(angle):
        raise ValueError("Joint angle must be finite")

    minimum, maximum = (float(limits_deg[0]), float(limits_deg[1]))
    if minimum > maximum:
        raise ValueError("Joint angle limits are reversed")

    first_turn = math.ceil((minimum - angle) / 360.0)
    last_turn = math.floor((maximum - angle) / 360.0)
    candidates = [
        angle + (360.0 * turn)
        for turn in range(first_turn, last_turn + 1)
    ]
    if not candidates:
        return max(minimum, min(maximum, angle))
    if previous_deg is None:
        return min(candidates, key=lambda value: abs(value - angle))

    previous = float(previous_deg)
    return min(
        candidates,
        key=lambda value: (abs(value - previous), abs(value - angle)),
    )


def select_adaptive_keyframes(
    samples: Sequence[Tuple[int, Sequence[float]]],
    tolerance_deg: float,
    maximum_gap_frames: int,
    mandatory_frames: Iterable[int] = (),
) -> list[int]:
    """Reduce joint samples while bounding linear joint-space deviation."""

    if not samples:
        return []
    if tolerance_deg < 0.0:
        raise ValueError("Key reduction tolerance cannot be negative")
    if maximum_gap_frames < 1:
        raise ValueError("Maximum key gap must be at least one frame")

    frames = [int(frame) for frame, _angles in samples]
    if frames != sorted(set(frames)):
        raise ValueError("FK bake sample frames must be unique and increasing")

    joint_count = len(samples[0][1])
    if joint_count == 0:
        raise ValueError("FK bake samples contain no joints")
    for _frame, angles in samples:
        if len(angles) != joint_count:
            raise ValueError("FK bake samples have inconsistent joint counts")
        if any(not math.isfinite(float(value)) for value in angles):
            raise ValueError("FK bake samples contain a non-finite joint angle")

    index_by_frame = {frame: index for index, frame in enumerate(frames)}
    selected = {0, len(samples) - 1}
    selected.update(
        index_by_frame[frame]
        for frame in mandatory_frames
        if frame in index_by_frame
    )

    # Preserve joint extrema and transitions into or out of stationary spans.
    stationary_epsilon = 1e-9
    for index in range(1, len(samples) - 1):
        previous_angles = samples[index - 1][1]
        current_angles = samples[index][1]
        next_angles = samples[index + 1][1]
        for joint_index in range(joint_count):
            incoming = float(current_angles[joint_index]) - float(
                previous_angles[joint_index]
            )
            outgoing = float(next_angles[joint_index]) - float(
                current_angles[joint_index]
            )
            direction_change = incoming * outgoing < 0.0
            stationary_change = (
                abs(incoming) <= stationary_epsilon
            ) != (
                abs(outgoing) <= stationary_epsilon
            )
            if direction_change or stationary_change:
                selected.add(index)
                break

    def split_interval(start_index: int, end_index: int) -> Optional[int]:
        if end_index <= start_index + 1:
            return None

        start_frame = frames[start_index]
        end_frame = frames[end_index]
        frame_span = end_frame - start_frame
        start_angles = samples[start_index][1]
        end_angles = samples[end_index][1]

        worst_index = None
        worst_error = -1.0
        for index in range(start_index + 1, end_index):
            fraction = (frames[index] - start_frame) / frame_span
            actual_angles = samples[index][1]
            error = max(
                abs(
                    float(actual_angles[joint_index])
                    - (
                        float(start_angles[joint_index])
                        + (
                            float(end_angles[joint_index])
                            - float(start_angles[joint_index])
                        )
                        * fraction
                    )
                )
                for joint_index in range(joint_count)
            )
            if error > worst_error:
                worst_error = error
                worst_index = index

        if worst_error > tolerance_deg:
            return worst_index
        if frame_span > maximum_gap_frames:
            midpoint = (start_frame + end_frame) * 0.5
            return min(
                range(start_index + 1, end_index),
                key=lambda index: abs(frames[index] - midpoint),
            )
        return None

    while True:
        additions = []
        ordered = sorted(selected)
        for start_index, end_index in zip(ordered, ordered[1:]):
            split_index = split_interval(start_index, end_index)
            if split_index is not None and split_index not in selected:
                additions.append(split_index)
        if not additions:
            break
        selected.update(additions)

    return [frames[index] for index in sorted(selected)]
