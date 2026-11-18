# Feature: governance-as-code-mvp, Property 22: Path containment
import os

import pytest
from hypothesis import given, settings, strategies as st

from agip_shared.paths import PathEscapeError, resolve_within

_seg = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-.", min_size=1, max_size=8).filter(
    lambda s: s not in (".", "..")
)


@settings(max_examples=100)
@given(parts=st.lists(_seg, min_size=1, max_size=4))
def test_relative_inside_accepted(tmp_path_factory, parts):
    base = tmp_path_factory.mktemp("d")
    out = resolve_within(base, "/".join(parts))
    assert out.is_relative_to(base.resolve())


@settings(max_examples=100)
@given(pre=st.lists(_seg, max_size=2), post=st.lists(_seg, max_size=2), sep=st.sampled_from(["/", "\\"]))
def test_dotdot_rejected(tmp_path_factory, pre, post, sep):
    base = tmp_path_factory.mktemp("d")
    with pytest.raises(PathEscapeError):
        resolve_within(base, sep.join([*pre, "..", *post]))


@settings(max_examples=100)
@given(parts=st.lists(_seg, min_size=1, max_size=3), root=st.sampled_from(["/", "\\", "C:\\", "C:/", "\\\\srv\\"]))
def test_absolute_rejected(tmp_path_factory, parts, root):
    base = tmp_path_factory.mktemp("d")
    with pytest.raises(PathEscapeError):
        resolve_within(base, root + "/".join(parts))


@settings(max_examples=100)
@given(p=st.text(max_size=30))
def test_accept_iff_inside(tmp_path_factory, p):
    base = tmp_path_factory.mktemp("d")
    try:
        out = resolve_within(base, p)
    except PathEscapeError:
        return
    except (OSError, ValueError):
        return
    assert out.is_relative_to(base.resolve())


def test_symlink_escape_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    try:
        os.symlink(outside, data / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted")
    with pytest.raises(PathEscapeError):
        resolve_within(data, "link/x.json")


def test_empty_and_nul_rejected(tmp_path):
    for bad in ("", "a\x00b"):
        with pytest.raises(PathEscapeError):
            resolve_within(tmp_path, bad)
