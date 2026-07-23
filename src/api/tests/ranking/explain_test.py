"""Pure-python tests for the mark normalization (no database)."""

from ranking.explain import _assign_marks


def _levels(deltas):
    return [level for _sign, level in _assign_marks(deltas)]


def _signs(deltas):
    return [sign for sign, _level in _assign_marks(deltas)]


def test_equal_fields_all_get_one_mark():
    # nothing stands out, nothing is negligible -> every field reads as one mark
    assert _levels([0.2, 0.2, 0.2, 0.2, 0.2, 0.2]) == [1] * 6


def test_small_but_real_fields_still_marked():
    # a dominant field earns two marks, but the small-yet-used fields still get
    # one rather than collapsing to nothing
    assert _levels([1.0, 0.03, 0.03, 0.03, 0.03, 0.03]) == [2, 1, 1, 1, 1, 1]


def test_only_negligible_fields_read_as_nothing():
    # fields the model barely moved (below the used floor) are the only zeros
    levels = _levels([0.9, 0.3, 0.08, 0.0005, 0.0003, 0.0])
    assert levels[0] == 2 and levels[1] == 1 and levels[2] == 1
    assert levels[3:] == [0, 0, 0]


def test_no_signal_is_all_zero():
    assert _levels([0, 0, 0, 0, 0, 0]) == [0] * 6


def test_sign_follows_delta_direction():
    # removing a field that lowered the score -> +, that raised it -> −
    signs = _signs([0.4, -0.3, 0.2, -0.15, 0.15, -0.1])
    assert signs == [1, -1, 1, -1, 1, -1]


def test_zero_level_iff_zero_sign():
    marks = _assign_marks([0.5, 0.001, -0.4, 0.0, -0.2, 0.05])
    for sign, level in marks:
        assert (level == 0) == (sign == 0)
