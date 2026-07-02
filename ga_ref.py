"""Reference model for the hardware SKI genetic-algorithm engine (stages S2-S6).

Mirrors the hardware's node format and memory layout so the Amaranth design
(ga_design.py) can be checked against it. Boolean semantics and fitness come
from ski_bool (already trusted); this module adds the 3-bit-tag node encoding
the hardware uses (it needs two extra inert atom tags, T and F, for reading a
Church boolean's branch out) and the fixed "preamble" memory layout.

Node word (32 bits):
    bits [31:29] tag    0=APP 1=S 2=K 3=I 4=T 5=F
    bits [27:14] right   14-bit node pointer (APP only)
    bits [13: 0] left    14-bit node pointer (APP only)

Template memory layout (loaded by the host / written by the generator):
    index 0 : I            (combinator)
    index 1 : K            (= Church TRUE)
    index 2 : APP(1, 0)    (K I = Church FALSE)
    index 3 : T            (inert sentinel atom)
    index 4 : F            (inert sentinel atom)
    index 5.. : candidate term nodes
"""

from __future__ import annotations

from ski_term import App  # noqa: F401  (re-exported for convenience)

# --- Tags ---
TAG_APP = 0
TAG_S = 1
TAG_K = 2
TAG_I = 3
TAG_T = 4
TAG_F = 5

PTR_BITS = 14
_COMB_TAG = {"S": TAG_S, "K": TAG_K, "I": TAG_I, "T": TAG_T, "F": TAG_F}
_TAG_COMB = {v: k for k, v in _COMB_TAG.items()}

# --- Fixed preamble layout (must match ga_design.py) ---
PTR_I = 0
PTR_TRUE = 1      # K
PTR_FALSE = 2     # APP(K, I)
PTR_T = 3         # sentinel atom
PTR_F = 4         # sentinel atom
PREAMBLE = 5


def encode_app(left: int, right: int) -> int:
    return (TAG_APP << 29) | ((right & 0x3FFF) << 14) | (left & 0x3FFF)


def encode_comb(tag: int) -> int:
    return (tag & 0x7) << 29


def decode(word: int) -> tuple[int, int, int]:
    return (word >> 29) & 0x7, word & 0x3FFF, (word >> 14) & 0x3FFF


def preamble_nodes() -> list[int]:
    """The five fixed nodes that every template starts with."""
    nodes = [0] * PREAMBLE
    nodes[PTR_I] = encode_comb(TAG_I)
    nodes[PTR_TRUE] = encode_comb(TAG_K)
    nodes[PTR_FALSE] = encode_app(PTR_TRUE, PTR_I)  # K I
    nodes[PTR_T] = encode_comb(TAG_T)
    nodes[PTR_F] = encode_comb(TAG_F)
    return nodes


def serialize_template(term) -> tuple[list[int], int]:
    """Build the template memory image for a candidate term.

    Returns (template_nodes, cand_root). Candidate nodes are appended after the
    fixed preamble; leaves S/K/I become their own nodes (uniform heap).
    """
    nodes = preamble_nodes()

    def emit(t) -> int:
        if isinstance(t, str):
            nodes.append(encode_comb(_COMB_TAG[t]))
            return len(nodes) - 1
        left, right = t
        li = emit(left)
        ri = emit(right)
        nodes.append(encode_app(li, ri))
        return len(nodes) - 1

    root = emit(term)
    return nodes, root


def parse(nodes, root: int, max_nodes: int = 100_000):
    """Reconstruct a term tree from a heap image (atoms render as 'T'/'F')."""
    budget = [max_nodes]

    def walk(ptr: int):
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("graph too large or cyclic")
        tag, left, right = decode(nodes[ptr])
        if tag == TAG_APP:
            return (walk(left), walk(right))
        return _TAG_COMB[tag]

    return walk(root)


def target_word(target_bits: list[int]) -> int:
    """Pack a truth table (row r -> bit r) into an integer register value."""
    word = 0
    for r, b in enumerate(target_bits):
        if b:
            word |= (1 << r)
    return word
