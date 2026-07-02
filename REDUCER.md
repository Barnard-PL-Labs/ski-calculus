# SKI combinator-calculus evaluator

Reduces [SKI combinator calculus](https://en.wikipedia.org/wiki/SKI_combinator_calculus)
terms to **weak head normal form (WHNF)** entirely in FPGA fabric — graph
reduction in block RAM, driven by a small state machine.

```
mrg run examples/ski_calculus/client_sdk.py
```

## The calculus

A term is a binary tree of *applications* whose leaves are the three
combinators `S`, `K`, `I`. There are three rewrite rules:

```
I x      -> x
K x y    -> x
S x y z  -> x z (y z)
```

These three suffice for Turing-complete computation. This example evaluates a
term by repeatedly rewriting the **head redex** (the leftmost-outermost one)
until the head combinator no longer has enough arguments — that is WHNF.
Arguments are *not* further reduced (the difference between WHNF and full
normal form). For example `S K K I` reduces `I`, and `S K K x` is the identity.

## How it works

The term graph lives in a block-RAM **heap**, one 32-bit node per cell:

```
bits [31:30] tag    0=APP  1=S  2=K  3=I
bits [29:15] right  node pointer (APP only)
bits [14: 0] left   node pointer (APP only)
```

The reduction engine (`design.py`):

1. **Unwinds the left spine** from the root, following `left` pointers, keeping
   a sliding window of the three innermost application nodes and their
   arguments. SKI's widest rule (`S`) needs only three arguments, so a 3-deep
   window replaces an unbounded spine stack.
2. When the spine bottoms out at a combinator, it **applies the matching rule**
   by overwriting the redex node in place (preserving sharing through the
   parent pointer), allocating two fresh `APP` nodes for `S`.
3. Re-unwinds and repeats until the head is under-applied (WHNF) or a guard
   fires.

Because SKI terms can diverge (e.g. `S I I (S I I)`), two guards stop the
hardware: a host-supplied **MAX_STEPS** cap and a **heap-overflow** check.

## Register / address map

512-word (9-bit) Wishbone window. Control registers occupy words 0–15; the heap
is words 16–511 (496 nodes), so node `i` is at byte `0x40 + i*4`.

| Reg          | Byte  | Access | Meaning                                   |
|--------------|-------|--------|-------------------------------------------|
| `CTRL`       | 0x00  | W / R  | W bit0 = start; R bit0 = done, bit1 = busy |
| `STATUS`     | 0x04  | R      | bit0 = heap overflow, bit1 = step-limit hit |
| `ROOT`       | 0x08  | R / W  | root node pointer                          |
| `NODE_COUNT` | 0x0C  | R / W  | nodes loaded (allocator start)             |
| `MAX_STEPS`  | 0x10  | R / W  | reduction-step cap (0 = unlimited)         |
| `STEPS`      | 0x14  | R      | reductions performed by the last run       |
| `ALLOC`      | 0x18  | R      | allocator high-water mark after the run    |
| `CAP`        | 0x1C  | R      | heap capacity in nodes (= 496)             |
| `HEAP`       | 0x40  | R / W  | node `i` at `0x40 + i*4`                    |

Host flow: write the serialized nodes to `HEAP`, set `ROOT` / `NODE_COUNT` /
`MAX_STEPS`, write `CTRL=1`, poll `CTRL` bit0, then read `ROOT` + the heap back
and walk the rewritten graph.

## Files

- `design.py` — Amaranth HDL: the WHNF reducer core + Wishbone slave.
- `ski_term.py` — pure-Python term builder, node (de)serializer, **reference
  WHNF reducer** (the oracle), and pretty-printer. No Amaranth/SDK imports.
- `client_sdk.py` — builds terms, reduces them on the FPGA, verifies each
  against the reference reducer.
- `tests/unit/` — node-encoding round-trips and address-map ↔ client sync.
- `tests/sim/` — drives the reducer in the Amaranth simulator and checks the
  rewritten graph against the reference reducer.

## Tests

```
pip install "amaranth>=0.5" pytest
pytest examples/ski_calculus/tests
```

## Limitations / ideas to extend

- **WHNF only.** Arguments aren't reduced. Extending to full normal form means
  recursing into arguments once the head is in WHNF (a redex work-stack).
- **Sharing via copy.** `I`/`K` rewrites copy the result node rather than using
  an indirection; children are still shared, but the redex node is duplicated.
- **Re-unwind per step** is O(spine) each reduction — simple, not the fastest.
  A persistent spine stack would cut the cycle count.
- **496-node heap**, bounded by the 512-word host window. A larger internal
  heap (not fully host-addressable) would allow bigger intermediate graphs.
