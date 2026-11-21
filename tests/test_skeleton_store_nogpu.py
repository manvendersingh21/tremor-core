"""store --no-gpu: the ladder is the 763B only."""
from skeleton.apps.store.store import make_assistant


def test_no_gpu_ladder_is_the_763b_only():
    assert make_assistant(False, no_gpu=True).ladder == ["cloud-deepseek"]
    assert make_assistant(False).ladder == ["gpu-small", "cloud-deepseek"]
