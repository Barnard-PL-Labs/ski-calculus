"""SKI combinator-calculus evaluator (weak head normal form) as a Wishbone B4 slave.

The three rewrite rules of SKI calculus:

    I x      -> x
    K x y    -> x
    S x y z  -> x z (y z)

A term is a binary tree whose leaves are the combinators S, K, I and whose
internal nodes are *application*. We store that tree as a graph in block RAM
(the "heap") and reduce it in place. This design reduces to **weak head normal
form** (WHNF): it repeatedly rewrites the head redex on the left spine until the
head combinator no longer has enough arguments. Arguments are *not* reduced --
that is the difference between WHNF and full normal form.

Node format (one 32-bit word per heap node):

    bits [31:30] tag   0 = APP, 1 = S, 2 = K, 3 = I
    bits [29:15] right  node pointer (only meaningful for APP)
    bits [14: 0] left   node pointer (only meaningful for APP)

Reduction engine (FSM):
  - Unwind the left spine from the root, following ``left`` pointers, keeping a
    sliding window of the three *innermost* application nodes encountered
    (a1 closest to the head, then a2, a3) and their argument pointers
    (g1, g2, g3 = the ``right`` child of each). Because SKI's widest rule (S)
    needs only three arguments, a 3-deep window is all the reducer ever needs --
    no unbounded spine stack.
  - When the spine bottoms out at a combinator, apply the matching rule by
    overwriting the redex node in place (which preserves sharing through the
    parent pointer) and, for S, allocating two fresh APP nodes.
  - Re-unwind from the root and repeat until the head combinator is
    under-applied (WHNF) or a guard fires.

Guards (SKI terms can diverge, e.g. ``S I I (S I I)``):
  - MAX_STEPS: stop after a host-supplied number of reductions (0 = unlimited).
  - heap overflow: stop if an S-reduction would run past the heap.

The host loads the initial graph into the heap, sets ROOT, optionally MAX_STEPS,
writes CTRL.start, polls CTRL.done, then walks the rewritten graph back from
ROOT. See client_sdk.py.

Requires Amaranth >= 0.5.
"""

from amaranth.hdl import Cat, Const, Elaboratable, Module, Signal
from amaranth.lib.memory import Memory

# --- Node tags ---
TAG_APP = 0
TAG_S = 1
TAG_K = 2
TAG_I = 3

# --- Node bit layout ---
PTR_BITS = 15  # left/right pointer width
TAG_BITS = 2

# --- Address map (32-bit words within the 512-word / 9-bit Wishbone window) ---
# Words 0..15 are control/status registers; the heap starts at word 16.
CTRL_WORD = 0        # W bit0 = start (auto-clears). R bit0 = done, bit1 = busy.
STATUS_WORD = 1      # R: bit0 = overflow, bit1 = step-limit hit
ROOT_WORD = 2        # R/W: root node pointer
NODE_COUNT_WORD = 3  # R/W: number of nodes the host loaded (allocator start)
MAX_STEPS_WORD = 4   # R/W: reduction step cap (0 = unlimited)
STEPS_WORD = 5       # R: reductions performed by the last run
ALLOC_WORD = 6       # R: allocator high-water mark after the last run
CAP_WORD = 7         # R: heap capacity in nodes (hardware constant)

HEAP_BASE_WORD = 16
WINDOW_WORDS = 512                       # 9-bit Wishbone address space
HEAP_DEPTH = WINDOW_WORDS - HEAP_BASE_WORD  # 496 nodes, host-addressable


def encode_app(left: int, right: int) -> int:
    """Pack an application node (left, right child pointers) into a 32-bit word."""
    return (TAG_APP << 30) | ((right & 0x7FFF) << 15) | (left & 0x7FFF)


def encode_comb(tag: int) -> int:
    """Pack a combinator leaf (TAG_S / TAG_K / TAG_I) into a 32-bit word."""
    return (tag & 0x3) << 30


def decode(word: int) -> tuple[int, int, int]:
    """Unpack a node word into (tag, left, right)."""
    return (word >> 30) & 0x3, word & 0x7FFF, (word >> 15) & 0x7FFF


class SKISlave(Elaboratable):
    """Wishbone B4 slave exposing the SKI WHNF reducer and its node heap.

    Wishbone timing matches the other examples: registered single-cycle ack,
    combinational read data, ``~wb_ack`` guard against a held strobe. While the
    reducer is busy the heap memory ports belong to the FSM; the host should
    only touch the heap (load the graph, read the result) while idle.
    """

    def __init__(self, heap_depth=HEAP_DEPTH):
        self.heap_depth = heap_depth
        addr_bits = (WINDOW_WORDS - 1).bit_length()  # 9

        # Wishbone inputs.
        self.wb_cyc = Signal()
        self.wb_stb = Signal()
        self.wb_we = Signal()
        self.wb_adr = Signal(addr_bits)
        self.wb_dat_w = Signal(32)
        self.wb_sel = Signal(4)
        # Wishbone outputs.
        self.wb_dat_r = Signal(32)
        self.wb_ack = Signal()

    def elaborate(self, platform):
        m = Module()

        # --- Heap memory: one registered read port, one registered write port.
        # The ports are muxed between the host (when idle) and the FSM (when busy).
        m.submodules.heap = heap = Memory(shape=32, depth=self.heap_depth, init=[])
        rd = heap.read_port(domain="sync", transparent_for=[])
        wr = heap.write_port(domain="sync")

        # --- Control / status registers.
        root = Signal(PTR_BITS)
        node_count = Signal(range(self.heap_depth + 1))
        max_steps = Signal(32)
        steps = Signal(32)
        alloc = Signal(range(self.heap_depth + 1))
        done = Signal(init=1)
        busy = Signal()
        overflow = Signal()
        step_limit = Signal()

        # --- Wishbone bookkeeping.
        with m.If(self.wb_cyc & self.wb_stb & ~self.wb_ack):
            m.d.sync += self.wb_ack.eq(1)
        with m.Else():
            m.d.sync += self.wb_ack.eq(0)

        active_write = Signal()
        m.d.comb += active_write.eq(
            self.wb_cyc & self.wb_stb & self.wb_we & ~self.wb_ack
        )

        is_heap = Signal()
        heap_word = Signal(range(self.heap_depth))
        m.d.comb += [
            is_heap.eq(self.wb_adr >= HEAP_BASE_WORD),
            heap_word.eq(self.wb_adr - HEAP_BASE_WORD),
        ]

        start_pulse = Signal()

        # --- Host register writes (only honoured while idle).
        with m.If(active_write & ~busy):
            with m.Switch(self.wb_adr):
                with m.Case(CTRL_WORD):
                    m.d.comb += start_pulse.eq(self.wb_dat_w[0])
                with m.Case(ROOT_WORD):
                    m.d.sync += root.eq(self.wb_dat_w[:PTR_BITS])
                with m.Case(NODE_COUNT_WORD):
                    m.d.sync += node_count.eq(self.wb_dat_w)
                with m.Case(MAX_STEPS_WORD):
                    m.d.sync += max_steps.eq(self.wb_dat_w)

        # --- Host register reads (combinational).
        with m.Switch(self.wb_adr):
            with m.Case(CTRL_WORD):
                m.d.comb += self.wb_dat_r.eq(Cat(done, busy))
            with m.Case(STATUS_WORD):
                m.d.comb += self.wb_dat_r.eq(Cat(overflow, step_limit))
            with m.Case(ROOT_WORD):
                m.d.comb += self.wb_dat_r.eq(root)
            with m.Case(NODE_COUNT_WORD):
                m.d.comb += self.wb_dat_r.eq(node_count)
            with m.Case(MAX_STEPS_WORD):
                m.d.comb += self.wb_dat_r.eq(max_steps)
            with m.Case(STEPS_WORD):
                m.d.comb += self.wb_dat_r.eq(steps)
            with m.Case(ALLOC_WORD):
                m.d.comb += self.wb_dat_r.eq(alloc)
            with m.Case(CAP_WORD):
                m.d.comb += self.wb_dat_r.eq(self.heap_depth)
            with m.Default():
                # Heap read: registered port latched mem[heap_word] last cycle.
                m.d.comb += self.wb_dat_r.eq(rd.data)

        # --- Memory port routing. Default = host; FSM states override below.
        fsm_raddr = Signal(PTR_BITS)
        fsm_waddr = Signal(PTR_BITS)
        fsm_wdata = Signal(32)
        fsm_wen = Signal()

        with m.If(busy):
            m.d.comb += [
                rd.addr.eq(fsm_raddr),
                wr.addr.eq(fsm_waddr),
                wr.data.eq(fsm_wdata),
                wr.en.eq(fsm_wen),
            ]
        with m.Else():
            m.d.comb += [
                rd.addr.eq(heap_word),
                wr.addr.eq(heap_word),
                wr.data.eq(self.wb_dat_w),
                wr.en.eq(active_write & is_heap),
            ]

        # --- Reduction engine state.
        cur = Signal(PTR_BITS)         # current node while unwinding the spine
        depth = Signal(2)              # apps seen this unwind, saturating at 3
        a1 = Signal(PTR_BITS)          # innermost app ptr (its left is the head)
        a2 = Signal(PTR_BITS)
        a3 = Signal(PTR_BITS)
        g1 = Signal(PTR_BITS)          # arg of a1 (right child)
        g2 = Signal(PTR_BITS)
        g3 = Signal(PTR_BITS)
        node = Signal(32)              # latched node word under inspection
        m.d.comb += node.eq(rd.data)

        node_tag = node[30:32]
        node_left = node[0:PTR_BITS]
        node_right = node[15:15 + PTR_BITS]

        # Full-width (PTR_BITS) views of the allocator, so Cat() packs the node
        # fields at the right bit offsets (alloc itself is only ~9 bits wide).
        alloc_p = Signal(PTR_BITS)
        alloc_p1 = Signal(PTR_BITS)
        m.d.comb += [alloc_p.eq(alloc), alloc_p1.eq(alloc + 1)]

        def begin_unwind():
            """Restart spine unwinding from the root."""
            m.d.sync += [cur.eq(root), depth.eq(0)]

        with m.FSM():
            with m.State("IDLE"):
                with m.If(start_pulse):
                    m.d.sync += [
                        busy.eq(1), done.eq(0),
                        overflow.eq(0), step_limit.eq(0),
                        steps.eq(0), alloc.eq(node_count),
                    ]
                    begin_unwind()
                    m.next = "UNWIND_LOAD"

            # Present the read address for mem[cur]; data is valid next cycle.
            with m.State("UNWIND_LOAD"):
                m.d.comb += fsm_raddr.eq(cur)
                m.next = "UNWIND_EVAL"

            # Consume mem[cur]. If APP, shift the window and descend left;
            # otherwise we have reached the head combinator.
            with m.State("UNWIND_EVAL"):
                m.d.comb += fsm_raddr.eq(cur)
                with m.If(node_tag == TAG_APP):
                    m.d.sync += [
                        a1.eq(cur), a2.eq(a1), a3.eq(a2),
                        g1.eq(node_right), g2.eq(g1), g3.eq(g2),
                        cur.eq(node_left),
                    ]
                    with m.If(depth != 3):
                        m.d.sync += depth.eq(depth + 1)
                    m.next = "UNWIND_LOAD"
                with m.Else():
                    m.next = "DISPATCH"

            # Decide which rule applies, or declare WHNF. node_tag still holds
            # the head combinator's tag (cur/rd.addr unchanged since EVAL).
            with m.State("DISPATCH"):
                m.d.comb += fsm_raddr.eq(cur)
                # Guards first.
                with m.If((max_steps != 0) & (steps >= max_steps)):
                    m.d.sync += step_limit.eq(1)
                    m.next = "FINISH"
                with m.Elif((node_tag == TAG_I) & (depth >= 1)):
                    m.next = "I_LOAD"
                with m.Elif((node_tag == TAG_K) & (depth >= 2)):
                    m.next = "K_LOAD"
                with m.Elif((node_tag == TAG_S) & (depth >= 3)):
                    with m.If(alloc + 2 > self.heap_depth):
                        m.d.sync += overflow.eq(1)
                        m.next = "FINISH"
                    with m.Else():
                        m.next = "S_W1"
                with m.Else():
                    m.next = "FINISH"  # under-applied head -> WHNF

            # I x -> x : copy node[g1] into the redex a1.
            with m.State("I_LOAD"):
                m.d.comb += fsm_raddr.eq(g1)
                m.next = "I_WRITE"
            with m.State("I_WRITE"):
                m.d.comb += [
                    fsm_waddr.eq(a1), fsm_wdata.eq(node), fsm_wen.eq(1),
                ]
                m.d.sync += steps.eq(steps + 1)
                begin_unwind()
                m.next = "UNWIND_LOAD"

            # K x y -> x : copy node[g1] into the redex a2.
            with m.State("K_LOAD"):
                m.d.comb += fsm_raddr.eq(g1)
                m.next = "K_WRITE"
            with m.State("K_WRITE"):
                m.d.comb += [
                    fsm_waddr.eq(a2), fsm_wdata.eq(node), fsm_wen.eq(1),
                ]
                m.d.sync += steps.eq(steps + 1)
                begin_unwind()
                m.next = "UNWIND_LOAD"

            # S x y z -> x z (y z): two fresh APP nodes, then rewrite redex a3.
            with m.State("S_W1"):
                m.d.comb += [
                    fsm_waddr.eq(alloc),
                    fsm_wdata.eq(Cat(g1, g3, Const(TAG_APP, TAG_BITS))),
                    fsm_wen.eq(1),
                ]
                m.next = "S_W2"
            with m.State("S_W2"):
                m.d.comb += [
                    fsm_waddr.eq(alloc + 1),
                    fsm_wdata.eq(Cat(g2, g3, Const(TAG_APP, TAG_BITS))),
                    fsm_wen.eq(1),
                ]
                m.next = "S_W3"
            with m.State("S_W3"):
                m.d.comb += [
                    fsm_waddr.eq(a3),
                    fsm_wdata.eq(Cat(alloc_p, alloc_p1, Const(TAG_APP, TAG_BITS))),
                    fsm_wen.eq(1),
                ]
                m.d.sync += [steps.eq(steps + 1), alloc.eq(alloc + 2)]
                begin_unwind()
                m.next = "UNWIND_LOAD"

            with m.State("FINISH"):
                m.d.sync += [busy.eq(0), done.eq(1)]
                m.next = "IDLE"

        return m
