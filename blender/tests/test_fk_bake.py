"""Tests for Blender-independent FK bake angle helpers."""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).parents[2]
    / "xarm_animation_workflow"
    / "core"
    / "fk_bake.py"
)
SPEC = importlib.util.spec_from_file_location("fk_bake", MODULE_PATH)
fk_bake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fk_bake)


class FKBakeHelpersTest(unittest.TestCase):
    def test_parse_rotation_axis(self):
        self.assertEqual(fk_bake.parse_rotation_axis("Y"), (1, 1))
        self.assertEqual(fk_bake.parse_rotation_axis("-Z"), (2, -1))

    def test_rejects_unknown_axis(self):
        with self.assertRaises(ValueError):
            fk_bake.parse_rotation_axis("Q")

    def test_selects_nearest_equivalent_inside_limits(self):
        self.assertEqual(
            fk_bake.nearest_equivalent_angle_deg(-359.0, 2.0, (-360.0, 360.0)),
            1.0,
        )

    def test_does_not_unwrap_past_joint_limits(self):
        self.assertEqual(
            fk_bake.nearest_equivalent_angle_deg(
                -130.0,
                130.0,
                (-131.9, 131.9),
            ),
            -130.0,
        )

    def test_adaptive_reduction_obeys_maximum_gap(self):
        samples = [(frame, [float(frame)]) for frame in range(11)]
        selected = fk_bake.select_adaptive_keyframes(
            samples,
            tolerance_deg=0.01,
            maximum_gap_frames=6,
        )
        self.assertEqual(selected, [0, 5, 10])

    def test_adaptive_reduction_retains_curve_deviation(self):
        samples = [
            (0, [0.0, 0.0]),
            (1, [1.0, 0.0]),
            (2, [4.0, 0.0]),
            (3, [3.0, 0.0]),
            (4, [4.0, 0.0]),
        ]
        selected = fk_bake.select_adaptive_keyframes(
            samples,
            tolerance_deg=0.1,
            maximum_gap_frames=6,
        )
        self.assertIn(2, selected)
        self.assertIn(3, selected)

    def test_adaptive_reduction_preserves_authored_frames(self):
        samples = [(frame, [float(frame)]) for frame in range(10)]
        selected = fk_bake.select_adaptive_keyframes(
            samples,
            tolerance_deg=0.1,
            maximum_gap_frames=20,
            mandatory_frames={3, 7},
        )
        self.assertEqual(selected, [0, 3, 7, 9])


if __name__ == "__main__":
    unittest.main()
