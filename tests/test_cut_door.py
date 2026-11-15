"""scripts/cut_door.py: the doorway mask is a pointed arch between the gold rim's inner edges."""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("cut_door", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cut_door.py")
cut = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cut)


def test_leaf_mask_is_a_pointed_arch():
    m = cut.leaf_mask(200, 100)
    assert m[50, 100] and m[85, 66] and m[85, 134]          # the middle and both lower corners of the doorway
    assert not m[50, 20] and not m[50, 180]                    # outside the rim
    assert not m[95, 100]                                       # below the threshold
    assert m[15, 100] and not m[15, 66]                         # the apex is high in the middle, the sides start lower
