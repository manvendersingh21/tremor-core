"""scripts/cut_count.py removes only the ground that touches the border, keeping dark cloth inside the figure."""
import importlib.util
import pathlib

import numpy as np

spec = importlib.util.spec_from_file_location("cut_count", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cut_count.py")
cut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cut)


def test_ground_mask_keeps_inner_ground_coloured_pixels():
    rgb = np.full((9, 9, 3), 70.0)          # flat grey ground
    rgb[2:7, 2:7] = 10.0                    # a dark figure
    rgb[4, 4] = 70.0                        # a ground-coloured spot inside the figure
    m = cut.ground_mask(rgb, tol=20)
    assert m[0, 0] and m[8, 8] and m[1, 4]
    assert not m[3, 3] and not m[4, 4]      # the inside spot is not connected to the border
