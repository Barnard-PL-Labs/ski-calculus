"""Pure-Python SKI term utilities: build, serialize, reduce, read back.

No Amaranth or SDK imports, so both ``client_sdk.py`` and the tests can use it.
This module also holds the *reference* WHNF reducer that the hardware is checked
against.

Term representation: a term is either

  * a combinator leaf: the string ``"S"``, ``"K"``, or ``"I"``; or
  * an application: a 2-tuple ``(func, arg)`` of terms.

So ``S K K`` (which is ``(S K) K``) is ``(("S", "K"), "K")``.
"""

from __future__ import annotations

# --- Node tags (must match design.py) ---
TAG_APP = 0
TAG_S = 1
TAG_K = 2
TAG_I = 3

_COMB_TAG = {"S": TAG_S, "K": TAG_K, "I": TAG_I}
_TAG_COMB = {TAG_S: "S", TAG_K: "K", TAG_I: "I"}


# --------------------------------------------------------------------------
# Building terms
# --------------------------------------------------------------------------
S, K, I = "S", "K", "I"


def App(*terms):
    """Left-associated application: ``App(S, K, K)`` == ``((S, K), K)``.

    With one argument, returns it unchanged.
    """
    if not terms:
        raise ValueError("App needs at least one term")
    result = terms[0]
    for t in terms[1:]:
        result = (result, t)
    return result


# --------------------------------------------------------------------------
# Node encoding (must match design.py)
# --------------------------------------------------------------------------
def encode_app(left: int, right: int) -> int:
    return (TAG_APP << 30) | ((right & 0x7FFF) << 15) | (left & 0x7FFF)


def encode_comb(tag: int) -> int:
    return (tag & 0x3) << 30


def decode(word: int) -> tuple[int, int, int]:
    return (word >> 30) & 0x3, word & 0x7FFF, (word >> 15) & 0x7FFF


# --------------------------------------------------------------------------
# Serialize a term into a flat heap of node words
# --------------------------------------------------------------------------
def serialize(term) -> tuple[list[int], int]:
    """Flatten a term into ``(nodes, root)``.

    ``nodes`` is a list of 32-bit node words; ``root`` is the index of the
    term's top node. Every combinator leaf and application gets its own node
    (a uniform heap, matching the hardware).
    """
    nodes: list[int] = []

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


# --------------------------------------------------------------------------
# Read a term back out of a (possibly rewritten) heap
# --------------------------------------------------------------------------
def parse(nodes, root: int, max_nodes: int = 100_000):
    """Reconstruct a term tree from heap ``nodes`` starting at ``root``.

    Shared subgraphs are unfolded into a tree. ``max_nodes`` guards against
    cyclic/corrupt graphs.
    """
    budget = [max_nodes]

    def walk(ptr: int):
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("graph too large or cyclic during readback")
        tag, left, right = decode(nodes[ptr])
        if tag == TAG_APP:
            return (walk(left), walk(right))
        return _TAG_COMB[tag]

    return walk(root)


# --------------------------------------------------------------------------
# Reference WHNF reducer (the oracle the hardware is compared to)
# --------------------------------------------------------------------------
def reduce_whnf(term, max_steps: int = 0):
    """Reduce ``term`` to weak head normal form.

    Returns ``(result, steps, hit_limit)``. ``max_steps == 0`` means unlimited
    (caller is responsible for termination). Mirrors the hardware: leftmost-
    outermost spine reduction, arguments left untouched.
    """
    steps = 0
    hit_limit = False
    while True:
        spine = []
        t = term
        while isinstance(t, tuple):
            spine.append(t)
            t = t[0]
        head = t
        n = len(spine)

        if max_steps and steps >= max_steps:
            hit_limit = True
            break

        if head == "I" and n >= 1:
            x = spine[n - 1][1]
            term = _rebuild(spine, 1, x)
        elif head == "K" and n >= 2:
            x = spine[n - 1][1]
            term = _rebuild(spine, 2, x)
        elif head == "S" and n >= 3:
            x = spine[n - 1][1]
            y = spine[n - 2][1]
            z = spine[n - 3][1]
            term = _rebuild(spine, 3, ((x, z), (y, z)))
        else:
            break  # head under-applied -> WHNF
        steps += 1

    return term, steps, hit_limit


def _rebuild(spine, arity: int, replacement):
    """Replace the redex (``arity``-th app from the head) with ``replacement``,
    re-applying the application nodes that sat above it."""
    n = len(spine)
    term = replacement
    for i in range(n - arity - 1, -1, -1):
        term = (term, spine[i][1])
    return term


# --------------------------------------------------------------------------
# Pretty-printing
# --------------------------------------------------------------------------
def pretty(term) -> str:
    """Render a term with minimal parentheses (application left-associative)."""
    if isinstance(term, str):
        return term

    def render(t, *, arg: bool) -> str:
        if isinstance(t, str):
            return t
        left, right = t
        s = f"{render(left, arg=False)} {render(right, arg=True)}"
        return f"({s})" if arg else s

    return render(term, arg=False)
