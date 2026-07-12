"""Known-answer tests for export.shortest_axis_normals (item 13).

The exported normal is the covariance axis with the SMALLEST scale (flattest
direction) = the corresponding column of the Gaussian's rotation matrix. Uses
axis-aligned quats with unequal scales so the expected column is exact.
"""
import numpy as np

from precompute.stages.export import shortest_axis_normals

_S = np.sqrt(0.5)


def test_shortest_axis_normals_known():
    # (quat wxyz, scales_log, expected unit normal)
    cases = [
        # identity rotation -> columns are world axes; pick the min-scale axis
        (np.array([1.0, 0, 0, 0]), np.array([0.0, -1.0, 0.0]), np.array([0.0, 1.0, 0.0])),  # axis 1
        (np.array([1.0, 0, 0, 0]), np.array([-2.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])),  # axis 0
        # 90 deg about Z: R col2 = world Z; min scale on axis 2
        (np.array([_S, 0, 0, _S]), np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])),
        # 90 deg about X: R col1 = world +Z; min scale on axis 1
        (np.array([_S, _S, 0, 0]), np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    ]
    quats = np.stack([c[0] for c in cases]).astype(np.float32)
    scales = np.stack([c[1] for c in cases]).astype(np.float32)
    expected = np.stack([c[2] for c in cases]).astype(np.float32)

    normals = shortest_axis_normals(scales, quats)
    assert normals.shape == (4, 3)
    np.testing.assert_allclose(normals, expected, atol=1e-6)
    # always unit length
    np.testing.assert_allclose(np.linalg.norm(normals, axis=1), np.ones(4), atol=1e-6)
