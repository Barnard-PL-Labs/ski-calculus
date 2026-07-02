"""Unit tests: node encoding round-trips, term serialize/parse, address map.

Pure Python -- no Amaranth needed. design.py is loaded dynamically only to pin
its constants against ski_term and client_sdk, the way matrix_mult does.
"""

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(_ROOT))
import ski_term as st  # noqa: E402


def _load_design():
    spec = importlib.util.spec_from_file_location("ski_design", _ROOT / "design.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ModuleNotFoundError as e:  # amaranth not installed
        pytest.skip(f"amaranth unavailable: {e}")
    return mod


# --- Encoding round-trips ------------------------------------------------
def test_comb_roundtrip():
    for tag in (st.TAG_S, st.TAG_K, st.TAG_I):
        word = st.encode_comb(tag)
        assert st.decode(word) == (tag, 0, 0)


def test_app_roundtrip():
    word = st.encode_app(123, 456)
    tag, left, right = st.decode(word)
    assert (tag, left, right) == (st.TAG_APP, 123, 456)


def test_app_fields_independent():
    # left and right must not bleed into each other or the tag.
    word = st.encode_app(0x7FFF, 0)
    assert st.decode(word) == (st.TAG_APP, 0x7FFF, 0)
    word = st.encode_app(0, 0x7FFF)
    assert st.decode(word) == (st.TAG_APP, 0, 0x7FFF)


# --- serialize / parse round-trips --------------------------------------
def test_serialize_parse_roundtrip():
    term = st.App(st.S, st.K, st.App(st.K, st.I))
    nodes, root = st.serialize(term)
    assert st.parse(nodes, root) == term


def test_serialize_leaf():
    nodes, root = st.serialize(st.I)
    assert len(nodes) == 1
    assert st.decode(nodes[root]) == (st.TAG_I, 0, 0)


def test_serialize_node_count():
    # n leaves + (n-1) applications for a binary tree of n leaves.
    term = st.App(st.S, st.K, st.K)  # 3 leaves
    nodes, _ = st.serialize(term)
    assert len(nodes) == 3 + 2


# --- Address map agrees with design.py ----------------------------------
def test_design_constants_match_ski_term():
    design = _load_design()
    assert (design.TAG_APP, design.TAG_S, design.TAG_K, design.TAG_I) == (
        st.TAG_APP, st.TAG_S, st.TAG_K, st.TAG_I,
    )
    assert design.encode_app(7, 9) == st.encode_app(7, 9)
    assert design.encode_comb(st.TAG_K) == st.encode_comb(st.TAG_K)


def test_heap_fits_window():
    design = _load_design()
    assert design.HEAP_BASE_WORD + design.HEAP_DEPTH == design.WINDOW_WORDS
    # Every control register sits below the heap.
    for name in ("CTRL_WORD", "STATUS_WORD", "ROOT_WORD", "NODE_COUNT_WORD",
                 "MAX_STEPS_WORD", "STEPS_WORD", "ALLOC_WORD", "CAP_WORD"):
        assert getattr(design, name) < design.HEAP_BASE_WORD


def test_client_regs_match_design():
    design = _load_design()
    try:
        spec = importlib.util.spec_from_file_location(
            "ski_client", _ROOT / "client_sdk.py")
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
    except ModuleNotFoundError as e:
        pytest.skip(f"SDK unavailable: {e}")
    # Client byte offsets == design word offsets * 4.
    assert client.Regs.CTRL == design.CTRL_WORD * 4
    assert client.Regs.ROOT == design.ROOT_WORD * 4
    assert client.Regs.NODE_COUNT == design.NODE_COUNT_WORD * 4
    assert client.Regs.MAX_STEPS == design.MAX_STEPS_WORD * 4
    assert client.Regs.HEAP == design.HEAP_BASE_WORD * 4


# --- Reference reducer sanity -------------------------------------------
def test_reference_I():
    out, steps, limit = st.reduce_whnf(st.App(st.I, st.K))
    assert out == "K" and steps == 1 and not limit


def test_reference_K():
    out, steps, _ = st.reduce_whnf(st.App(st.K, st.S, st.I))
    assert out == "S" and steps == 1


def test_reference_S():
    # S K K x  ->  x  (the standard identity-from-S-K-K)
    out, steps, _ = st.reduce_whnf(st.App(st.S, st.K, st.K, st.I))
    assert out == "I"


def test_reference_step_limit():
    # omega = S I I (S I I) diverges; bounded run must stop and flag it.
    sii = st.App(st.S, st.I, st.I)
    omega = st.App(sii, sii)
    _, steps, limit = st.reduce_whnf(omega, max_steps=5)
    assert limit and steps == 5
