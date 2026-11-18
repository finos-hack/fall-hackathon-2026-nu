import os

import pytest

from agip_shared.hashing import canonical_json, input_hash
from agip_shared.paths import PathEscapeError, resolve_within


def test_canonical_json_sorted_no_whitespace():
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_input_hash_stable_and_sensitive():
    h = input_hash("m", {"a": 1, "b": 2}, ["q"])
    assert h == input_hash("m", {"b": 2, "a": 1}, ["q"])
    assert len(h) == 64
    assert h != input_hash("m2", {"a": 1, "b": 2}, ["q"])
    assert h != input_hash("m", {"a": 1, "b": 3}, ["q"])
    assert h != input_hash("m", {"a": 1, "b": 2}, ["q2"])


def test_resolve_within_ok(tmp_path):
    assert resolve_within(tmp_path, "a/b.txt") == tmp_path.resolve() / "a" / "b.txt"


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/passwd", "C:\\x", "..\\x", ""])
def test_resolve_within_rejects(tmp_path, bad):
    with pytest.raises(PathEscapeError):
        resolve_within(tmp_path, bad)


def test_resolve_within_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    try:
        os.symlink(outside, data / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(PathEscapeError):
        resolve_within(data, "link/f.txt")
