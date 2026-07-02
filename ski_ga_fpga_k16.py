"""Self-contained SKI GA throughput engine, K=16 cores (hardware demo).

Generated from ga_design.py; GAEngine is the unique Wishbone-port top.
"""

from amaranth.hdl import Array, Cat, Const, Elaboratable, Module, Mux, Signal
from amaranth.lib.memory import Memory

TAG_APP = 0
TAG_S = 1
TAG_K = 2
TAG_I = 3
TAG_T = 4
TAG_F = 5
TAG_BITS = 3
PTR_BITS = 14

PTR_I = 0
PTR_TRUE = 1
PTR_FALSE = 2
PTR_T = 3
PTR_F = 4
PREAMBLE = 5

LFSR_TAPS = 0x80200003  # x^32 + x^22 + x^2 + x^1 (maximal-length Galois)


# ==========================================================================
# ReducerCore
# ==========================================================================
class ReducerCore(Elaboratable):
    """WHNF reducer over an external heap memory (1-cycle registered read)."""

    def __init__(self, heap_depth=512):
        self.heap_depth = heap_depth
        self.start = Signal()
        self.busy = Signal()
        self.root = Signal(PTR_BITS)
        self.node_count = Signal(range(heap_depth + 1))
        self.max_steps = Signal(32)
        self.steps = Signal(32)
        self.overflow = Signal()
        self.step_limit = Signal()
        self.head_tag = Signal(TAG_BITS)
        self.mem_rdata = Signal(32)
        self.mem_raddr = Signal(PTR_BITS)
        self.mem_waddr = Signal(PTR_BITS)
        self.mem_wdata = Signal(32)
        self.mem_wen = Signal()

    def elaborate(self, platform):
        m = Module()
        alloc = Signal(range(self.heap_depth + 2))
        cur = Signal(PTR_BITS)
        root_r = Signal(PTR_BITS)
        max_steps_r = Signal(32)
        depth = Signal(2)
        a1 = Signal(PTR_BITS); a2 = Signal(PTR_BITS); a3 = Signal(PTR_BITS)
        g1 = Signal(PTR_BITS); g2 = Signal(PTR_BITS); g3 = Signal(PTR_BITS)

        node = self.mem_rdata
        node_tag = node[29:32]
        node_left = node[0:PTR_BITS]
        node_right = node[14:14 + PTR_BITS]
        alloc_p = Signal(PTR_BITS); alloc_p1 = Signal(PTR_BITS)
        m.d.comb += [alloc_p.eq(alloc), alloc_p1.eq(alloc + 1)]

        def begin_unwind():
            m.d.sync += [cur.eq(root_r), depth.eq(0)]

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.start):
                    m.d.sync += [
                        self.busy.eq(1), self.overflow.eq(0), self.step_limit.eq(0),
                        self.steps.eq(0), alloc.eq(self.node_count),
                        root_r.eq(self.root), max_steps_r.eq(self.max_steps),
                        cur.eq(self.root), depth.eq(0),
                    ]
                    m.next = "UNWIND_LOAD"
            with m.State("UNWIND_LOAD"):
                m.d.comb += self.mem_raddr.eq(cur)
                m.next = "UNWIND_EVAL"
            with m.State("UNWIND_EVAL"):
                m.d.comb += self.mem_raddr.eq(cur)
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
            with m.State("DISPATCH"):
                m.d.comb += self.mem_raddr.eq(cur)
                with m.If((max_steps_r != 0) & (self.steps >= max_steps_r)):
                    m.d.sync += [self.step_limit.eq(1), self.head_tag.eq(node_tag)]
                    m.next = "FINISH"
                with m.Elif((node_tag == TAG_I) & (depth >= 1)):
                    m.next = "I_LOAD"
                with m.Elif((node_tag == TAG_K) & (depth >= 2)):
                    m.next = "K_LOAD"
                with m.Elif((node_tag == TAG_S) & (depth >= 3)):
                    with m.If(alloc + 2 > self.heap_depth):
                        m.d.sync += [self.overflow.eq(1), self.head_tag.eq(node_tag)]
                        m.next = "FINISH"
                    with m.Else():
                        m.next = "S_W1"
                with m.Else():
                    m.d.sync += self.head_tag.eq(node_tag)
                    m.next = "FINISH"
            with m.State("I_LOAD"):
                m.d.comb += self.mem_raddr.eq(g1)
                m.next = "I_WRITE"
            with m.State("I_WRITE"):
                m.d.comb += [self.mem_waddr.eq(a1), self.mem_wdata.eq(node),
                             self.mem_wen.eq(1)]
                m.d.sync += self.steps.eq(self.steps + 1)
                begin_unwind(); m.next = "UNWIND_LOAD"
            with m.State("K_LOAD"):
                m.d.comb += self.mem_raddr.eq(g1)
                m.next = "K_WRITE"
            with m.State("K_WRITE"):
                m.d.comb += [self.mem_waddr.eq(a2), self.mem_wdata.eq(node),
                             self.mem_wen.eq(1)]
                m.d.sync += self.steps.eq(self.steps + 1)
                begin_unwind(); m.next = "UNWIND_LOAD"
            with m.State("S_W1"):
                m.d.comb += [self.mem_waddr.eq(alloc),
                             self.mem_wdata.eq(Cat(g1, g3, Const(TAG_APP, TAG_BITS))),
                             self.mem_wen.eq(1)]
                m.next = "S_W2"
            with m.State("S_W2"):
                m.d.comb += [self.mem_waddr.eq(alloc + 1),
                             self.mem_wdata.eq(Cat(g2, g3, Const(TAG_APP, TAG_BITS))),
                             self.mem_wen.eq(1)]
                m.next = "S_W3"
            with m.State("S_W3"):
                m.d.comb += [self.mem_waddr.eq(a3),
                             self.mem_wdata.eq(Cat(alloc_p, alloc_p1,
                                                   Const(TAG_APP, TAG_BITS))),
                             self.mem_wen.eq(1)]
                m.d.sync += [self.steps.eq(self.steps + 1), alloc.eq(alloc + 2)]
                begin_unwind(); m.next = "UNWIND_LOAD"
            with m.State("FINISH"):
                m.d.sync += self.busy.eq(0)
                m.next = "IDLE"
        return m


# ==========================================================================
# EvalCore
# ==========================================================================
class EvalCore(Elaboratable):
    """Score a candidate (held in an owned template heap) against a truth table.

    The template heap is written from outside via (t_waddr, t_wdata, t_wen) while
    ``~busy`` (the host or the generator loads it). Pulse ``start`` with
    tmpl_count/cand_root/n_inputs/target/max_steps valid; ``fitness`` is the
    matched-row count when ``busy`` falls.
    """

    def __init__(self, template_depth=64, work_depth=512, max_inputs=4):
        self.template_depth = template_depth
        self.work_depth = work_depth
        self.max_inputs = max_inputs
        # Control / params.
        self.start = Signal()
        self.busy = Signal()
        self.tmpl_count = Signal(range(template_depth + 1))
        self.cand_root = Signal(PTR_BITS)
        self.n_inputs = Signal(range(max_inputs + 1))
        self.target = Signal(1 << max_inputs)
        self.max_steps = Signal(32)
        self.fitness = Signal(16)
        self.overflow = Signal()
        self.step_limit = Signal()
        # External template write port.
        self.t_waddr = Signal(PTR_BITS)
        self.t_wdata = Signal(32)
        self.t_wen = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.tmpl = tmpl = Memory(shape=32, depth=self.template_depth, init=[])
        m.submodules.work = work = Memory(shape=32, depth=self.work_depth, init=[])
        t_rd = tmpl.read_port(domain="sync", transparent_for=[])
        t_wr = tmpl.write_port(domain="sync")
        w_rd = work.read_port(domain="sync", transparent_for=[])
        w_wr = work.write_port(domain="sync")
        m.submodules.reducer = reducer = ReducerCore(heap_depth=self.work_depth)
        m.d.comb += reducer.mem_rdata.eq(w_rd.data)

        # Template port: EvalCore reads during COPY; external writes otherwise.
        ev_t_raddr = Signal(PTR_BITS)
        use_ev_tmpl = Signal()
        with m.If(use_ev_tmpl):
            m.d.comb += t_rd.addr.eq(ev_t_raddr)
        with m.Else():
            m.d.comb += [t_wr.addr.eq(self.t_waddr), t_wr.data.eq(self.t_wdata),
                         t_wr.en.eq(self.t_wen & ~self.busy)]

        # Work port: reducer owns while busy, EvalCore otherwise.
        ev_w_raddr = Signal(PTR_BITS); ev_w_waddr = Signal(PTR_BITS)
        ev_w_wdata = Signal(32); ev_w_wen = Signal()
        with m.If(reducer.busy):
            m.d.comb += [w_rd.addr.eq(reducer.mem_raddr), w_wr.addr.eq(reducer.mem_waddr),
                         w_wr.data.eq(reducer.mem_wdata), w_wr.en.eq(reducer.mem_wen)]
        with m.Else():
            m.d.comb += [w_rd.addr.eq(ev_w_raddr), w_wr.addr.eq(ev_w_waddr),
                         w_wr.data.eq(ev_w_wdata), w_wr.en.eq(ev_w_wen)]

        row = Signal(self.max_inputs)
        n_rows = Signal(self.max_inputs + 1)
        m.d.comb += n_rows.eq(1 << self.n_inputs)
        ci = Signal(range(self.template_depth + 1))
        acc = Signal(PTR_BITS)
        wptr = Signal(PTR_BITS)
        k = Signal(range(self.max_inputs + 3))

        arg_ptr = Signal(PTR_BITS)
        input_bit = Signal()
        shamt = Signal(range(self.max_inputs + 1))
        m.d.comb += shamt.eq(self.n_inputs - 1 - k)
        m.d.comb += input_bit.eq((row >> shamt)[0])
        with m.If(k < self.n_inputs):
            m.d.comb += arg_ptr.eq(Mux(input_bit, PTR_TRUE, PTR_FALSE))
        with m.Elif(k == self.n_inputs):
            m.d.comb += arg_ptr.eq(PTR_T)
        with m.Else():
            m.d.comb += arg_ptr.eq(PTR_F)

        result_is_t = Signal(); result_is_f = Signal()
        m.d.comb += [result_is_t.eq(reducer.head_tag == TAG_T),
                     result_is_f.eq(reducer.head_tag == TAG_F)]
        target_bit = Signal()
        m.d.comb += target_bit.eq((self.target >> row)[0])

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.start):
                    m.d.sync += [self.busy.eq(1), self.fitness.eq(0), row.eq(0),
                                 self.overflow.eq(0), self.step_limit.eq(0)]
                    m.next = "ROW_INIT"
            with m.State("ROW_INIT"):
                m.d.sync += ci.eq(0)
                m.next = "COPY_RD"
            with m.State("COPY_RD"):
                m.d.comb += [use_ev_tmpl.eq(1), ev_t_raddr.eq(ci)]
                m.next = "COPY_WR"
            with m.State("COPY_WR"):
                m.d.comb += [use_ev_tmpl.eq(1), ev_t_raddr.eq(ci),
                             ev_w_waddr.eq(ci), ev_w_wdata.eq(t_rd.data), ev_w_wen.eq(1)]
                m.d.sync += ci.eq(ci + 1)
                with m.If(ci + 1 >= self.tmpl_count):
                    m.next = "BUILD_INIT"
                with m.Else():
                    m.next = "COPY_RD"
            with m.State("BUILD_INIT"):
                m.d.sync += [acc.eq(self.cand_root), wptr.eq(self.tmpl_count), k.eq(0)]
                m.next = "BUILD"
            with m.State("BUILD"):
                m.d.comb += [ev_w_waddr.eq(wptr),
                             ev_w_wdata.eq(Cat(acc, arg_ptr, Const(TAG_APP, TAG_BITS))),
                             ev_w_wen.eq(1)]
                m.d.sync += [acc.eq(wptr), wptr.eq(wptr + 1), k.eq(k + 1)]
                with m.If(k + 1 >= self.n_inputs + 2):
                    m.next = "REDUCE_START"
                with m.Else():
                    m.next = "BUILD"
            with m.State("REDUCE_START"):
                m.d.comb += [reducer.start.eq(1), reducer.root.eq(acc),
                             reducer.node_count.eq(wptr), reducer.max_steps.eq(self.max_steps)]
                m.next = "REDUCE_WAIT_BUSY"
            with m.State("REDUCE_WAIT_BUSY"):
                with m.If(reducer.busy):
                    m.next = "REDUCE_WAIT_DONE"
            with m.State("REDUCE_WAIT_DONE"):
                with m.If(~reducer.busy):
                    m.next = "CLASSIFY"
            with m.State("CLASSIFY"):
                m.d.sync += [self.overflow.eq(self.overflow | reducer.overflow),
                             self.step_limit.eq(self.step_limit | reducer.step_limit)]
                with m.If((result_is_t & (target_bit == 1)) |
                          (result_is_f & (target_bit == 0))):
                    m.d.sync += self.fitness.eq(self.fitness + 1)
                m.next = "ROW_NEXT"
            with m.State("ROW_NEXT"):
                with m.If(row + 1 >= n_rows):
                    m.next = "FINISH"
                with m.Else():
                    m.d.sync += row.eq(row + 1)
                    m.next = "ROW_INIT"
            with m.State("FINISH"):
                m.d.sync += self.busy.eq(0)
                m.next = "IDLE"
        return m


# ==========================================================================
# Generator
# ==========================================================================
class Generator(Elaboratable):
    """LFSR-driven random pure-SKI candidate generator.

    Writes a fresh preamble (5 fixed nodes) followed by ``cand_size`` random
    candidate nodes into a template heap via (t_waddr, t_wdata, t_wen). Every app
    node references only earlier candidate nodes (acyclic, in-range). Pulse
    ``start`` with ``seed`` (nonzero) and ``cand_size``; ``done`` pulses when the
    template is ready with ``tmpl_count`` / ``cand_root`` valid.
    """

    def __init__(self, template_depth=64, max_inputs=4):
        self.template_depth = template_depth
        self.start = Signal()
        self.seed = Signal(32)
        self.cand_size = Signal(range(template_depth + 1))
        self.busy = Signal()
        self.done = Signal()
        self.tmpl_count = Signal(range(template_depth + 1))
        self.cand_root = Signal(PTR_BITS)
        self.t_waddr = Signal(PTR_BITS)
        self.t_wdata = Signal(32)
        self.t_wen = Signal()

    def elaborate(self, platform):
        m = Module()
        lfsr = Signal(32)
        gi = Signal(range(self.template_depth + 1))
        pre_i = Signal(3)
        size_r = Signal(range(self.template_depth + 1))

        # Random fields from the current LFSR word.
        r = lfsr
        is_leaf_rand = (r[5:8] < 3)           # ~3/8 leaves among non-first nodes
        leaf_sel = r[8:10]
        leaf_tag = Mux(leaf_sel == 0, TAG_S, Mux(leaf_sel == 1, TAG_K, TAG_I))
        span = Signal(PTR_BITS)               # candidate nodes available so far
        m.d.comb += span.eq(gi - PREAMBLE)
        # Lemire-style bounded index: PREAMBLE + (rand8 * span) >> 8, always < gi.
        left_idx = Signal(PTR_BITS); right_idx = Signal(PTR_BITS)
        m.d.comb += [left_idx.eq(PREAMBLE + ((r[10:18] * span) >> 8)),
                     right_idx.eq(PREAMBLE + ((r[18:26] * span) >> 8))]

        def adv_lfsr():
            m.d.sync += lfsr.eq(Mux(lfsr[0], (lfsr >> 1) ^ LFSR_TAPS, lfsr >> 1))

        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += self.done.eq(0)
                with m.If(self.start):
                    m.d.sync += [self.busy.eq(1),
                                 lfsr.eq(Mux(self.seed == 0, 1, self.seed)),
                                 size_r.eq(self.cand_size), pre_i.eq(0)]
                    m.next = "PREAMBLE"
            with m.State("PREAMBLE"):
                m.d.comb += [self.t_waddr.eq(pre_i), self.t_wen.eq(1)]
                with m.Switch(pre_i):
                    with m.Case(PTR_I):
                        m.d.comb += self.t_wdata.eq(Const(TAG_I, TAG_BITS) << 29)
                    with m.Case(PTR_TRUE):
                        m.d.comb += self.t_wdata.eq(Const(TAG_K, TAG_BITS) << 29)
                    with m.Case(PTR_FALSE):
                        m.d.comb += self.t_wdata.eq(
                            Cat(Const(PTR_TRUE, PTR_BITS), Const(PTR_I, PTR_BITS),
                                Const(TAG_APP, TAG_BITS)))
                    with m.Case(PTR_T):
                        m.d.comb += self.t_wdata.eq(Const(TAG_T, TAG_BITS) << 29)
                    with m.Case(PTR_F):
                        m.d.comb += self.t_wdata.eq(Const(TAG_F, TAG_BITS) << 29)
                m.d.sync += pre_i.eq(pre_i + 1)
                with m.If(pre_i == PREAMBLE - 1):
                    m.d.sync += gi.eq(PREAMBLE)
                    m.next = "GEN"
            with m.State("GEN"):
                m.d.comb += [self.t_waddr.eq(gi), self.t_wen.eq(1)]
                # First candidate node must be a leaf (no earlier node to point to).
                with m.If((gi == PREAMBLE) | is_leaf_rand):
                    m.d.comb += self.t_wdata.eq(leaf_tag << 29)
                with m.Else():
                    m.d.comb += self.t_wdata.eq(
                        Cat(left_idx, right_idx, Const(TAG_APP, TAG_BITS)))
                adv_lfsr()
                m.d.sync += gi.eq(gi + 1)
                with m.If(gi + 1 >= PREAMBLE + size_r):
                    m.d.sync += [self.cand_root.eq(gi), self.tmpl_count.eq(gi + 1),
                                 self.busy.eq(0)]
                    m.next = "DONE"
            with m.State("DONE"):
                m.d.comb += self.done.eq(1)
                m.next = "IDLE"
        return m


# ==========================================================================
# GACore: autonomous generate -> evaluate -> track-best loop
# ==========================================================================
class GACore(Elaboratable):
    """One self-contained GA unit. Runs while ``run`` is high: generate a random
    candidate, score it against the target, update the best, count it, repeat."""

    def __init__(self, template_depth=64, work_depth=512, max_inputs=4):
        self.kw = dict(template_depth=template_depth, work_depth=work_depth,
                       max_inputs=max_inputs)
        self.run = Signal()
        self.seed = Signal(32)
        self.cand_size = Signal(range(template_depth + 1))
        self.n_inputs = Signal(range(max_inputs + 1))
        self.target = Signal(1 << max_inputs)
        self.max_steps = Signal(32)
        self.count = Signal(32)        # candidates evaluated
        self.best_fit = Signal(16)     # best fitness seen
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.gen = gen = Generator(self.kw["template_depth"], self.kw["max_inputs"])
        m.submodules.ev = ev = EvalCore(**self.kw)

        # Generator writes the template; route its write port into EvalCore.
        m.d.comb += [ev.t_waddr.eq(gen.t_waddr), ev.t_wdata.eq(gen.t_wdata),
                     ev.t_wen.eq(gen.t_wen),
                     ev.cand_root.eq(gen.cand_root), ev.tmpl_count.eq(gen.tmpl_count),
                     ev.n_inputs.eq(self.n_inputs), ev.target.eq(self.target),
                     ev.max_steps.eq(self.max_steps)]

        seed_r = Signal(32)
        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.run):
                    m.d.sync += [self.count.eq(0), self.best_fit.eq(0),
                                 self.busy.eq(1), seed_r.eq(self.seed)]
                    m.next = "GEN_START"
            with m.State("GEN_START"):
                m.d.comb += [gen.start.eq(1), gen.seed.eq(seed_r),
                             gen.cand_size.eq(self.cand_size)]
                m.next = "GEN_WAIT"
            with m.State("GEN_WAIT"):
                m.d.comb += [gen.seed.eq(seed_r), gen.cand_size.eq(self.cand_size)]
                with m.If(gen.done):
                    # Re-seed for the next candidate by perturbing the seed.
                    m.d.sync += seed_r.eq(seed_r + 1)
                    m.next = "EVAL_START"
            with m.State("EVAL_START"):
                m.d.comb += ev.start.eq(1)
                m.next = "EVAL_WAIT_BUSY"
            with m.State("EVAL_WAIT_BUSY"):
                with m.If(ev.busy):
                    m.next = "EVAL_WAIT_DONE"
            with m.State("EVAL_WAIT_DONE"):
                with m.If(~ev.busy):
                    m.d.sync += self.count.eq(self.count + 1)
                    with m.If(ev.fitness > self.best_fit):
                        m.d.sync += self.best_fit.eq(ev.fitness)
                    m.next = "NEXT"
            with m.State("NEXT"):
                with m.If(self.run):
                    m.next = "GEN_START"
                with m.Else():
                    m.d.sync += self.busy.eq(0)
                    m.next = "IDLE"
        return m


# GAEngine Wishbone register map.
GA_CTRL = 0          # W bit0=run; R bit0=any_busy
GA_SEED = 1          # R/W base seed
GA_N_INPUTS = 2      # R/W
GA_TARGET = 3        # R/W target truth table
GA_MAX_STEPS = 4     # R/W reduction step cap
GA_CAND_SIZE = 5     # R/W candidate node count
GA_NUM_CORES = 6     # R   number of cores (constant)
GA_TOTAL = 7         # R   total candidates evaluated (sum over cores)
GA_BEST = 8          # R   global best fitness (max over cores)
GA_COUNT_BASE = 16   # R   per-core count i at word 16+i


class GAEngine(Elaboratable):
    """K parallel GACores behind one Wishbone front-end (the throughput engine)."""

    def __init__(self, num_cores=16, template_depth=48, work_depth=256, max_inputs=4):
        self.num_cores = num_cores
        self.kw = dict(template_depth=template_depth, work_depth=work_depth,
                       max_inputs=max_inputs)
        self.max_inputs = max_inputs
        self.wb_cyc = Signal(); self.wb_stb = Signal(); self.wb_we = Signal()
        self.wb_adr = Signal(9); self.wb_dat_w = Signal(32); self.wb_sel = Signal(4)
        self.wb_dat_r = Signal(32); self.wb_ack = Signal()

    def elaborate(self, platform):
        m = Module()
        run = Signal()
        seed = Signal(32)
        n_inputs = Signal(range(self.max_inputs + 1))
        target = Signal(1 << self.max_inputs)
        max_steps = Signal(32)
        cand_size = Signal(range(self.kw["template_depth"] + 1))

        cores = []
        for i in range(self.num_cores):
            c = GACore(**self.kw)
            m.submodules[f"core{i}"] = c
            # Distinct seed per core for search diversity.
            m.d.comb += [c.run.eq(run), c.seed.eq(seed + (i * 0x9E3779B1)),
                         c.n_inputs.eq(n_inputs), c.target.eq(target),
                         c.max_steps.eq(max_steps), c.cand_size.eq(cand_size)]
            cores.append(c)

        # --- Async sequential aggregator ---------------------------------
        # The cores share nothing. The only cross-core values the host reads
        # (total candidates, best fitness, any-busy) are reduced by a tiny FSM
        # that sweeps the cores one per cycle and republishes a snapshot every
        # num_cores cycles. The reduction is O(1) hardware regardless of core
        # count -- no wide combinational tree to elaborate (a nested Mux/sum
        # over K cores was ~O(K^2) in the Verilog backend and stalled export at
        # high K) or to lengthen the critical path. total/best/any_busy are
        # registered snapshots, refreshed every num_cores cycles (sub-us; the
        # host only polls them between runs).
        total = Signal(32)
        best = Signal(16)
        any_busy = Signal()
        agg_idx = Signal(range(max(2, self.num_cores)))
        acc_total = Signal(32)
        acc_best = Signal(16)
        acc_busy = Signal()
        cur_count = Array([c.count for c in cores])[agg_idx]
        cur_best = Array([c.best_fit for c in cores])[agg_idx]
        cur_busy = Array([c.busy for c in cores])[agg_idx]
        agg_last = agg_idx == (self.num_cores - 1)
        nxt_best = Mux(cur_best > acc_best, cur_best, acc_best)
        m.d.sync += agg_idx.eq(Mux(agg_last, 0, agg_idx + 1))
        with m.If(agg_last):
            # publish this sweep (incl. the core read this cycle), then reset
            m.d.sync += [
                total.eq(acc_total + cur_count),
                best.eq(nxt_best),
                any_busy.eq(acc_busy | cur_busy),
                acc_total.eq(0), acc_best.eq(0), acc_busy.eq(0),
            ]
        with m.Else():
            m.d.sync += [
                acc_total.eq(acc_total + cur_count),
                acc_best.eq(nxt_best),
                acc_busy.eq(acc_busy | cur_busy),
            ]

        with m.If(self.wb_cyc & self.wb_stb & ~self.wb_ack):
            m.d.sync += self.wb_ack.eq(1)
        with m.Else():
            m.d.sync += self.wb_ack.eq(0)
        active_write = Signal()
        m.d.comb += active_write.eq(self.wb_cyc & self.wb_stb & self.wb_we & ~self.wb_ack)

        with m.If(active_write):
            with m.Switch(self.wb_adr):
                with m.Case(GA_CTRL):
                    m.d.sync += run.eq(self.wb_dat_w[0])
                with m.Case(GA_SEED):
                    m.d.sync += seed.eq(self.wb_dat_w)
                with m.Case(GA_N_INPUTS):
                    m.d.sync += n_inputs.eq(self.wb_dat_w)
                with m.Case(GA_TARGET):
                    m.d.sync += target.eq(self.wb_dat_w)
                with m.Case(GA_MAX_STEPS):
                    m.d.sync += max_steps.eq(self.wb_dat_w)
                with m.Case(GA_CAND_SIZE):
                    m.d.sync += cand_size.eq(self.wb_dat_w)

        count_sel = Signal(32)
        core_idx = Signal(range(max(2, self.num_cores)))
        m.d.comb += core_idx.eq(self.wb_adr - GA_COUNT_BASE)
        with m.If(self.wb_adr >= GA_COUNT_BASE):
            with m.Switch(core_idx):
                for i, c in enumerate(cores):
                    with m.Case(i):
                        m.d.comb += count_sel.eq(c.count)

        with m.Switch(self.wb_adr):
            with m.Case(GA_CTRL):
                m.d.comb += self.wb_dat_r.eq(Cat(run, any_busy))
            with m.Case(GA_SEED):
                m.d.comb += self.wb_dat_r.eq(seed)
            with m.Case(GA_N_INPUTS):
                m.d.comb += self.wb_dat_r.eq(n_inputs)
            with m.Case(GA_TARGET):
                m.d.comb += self.wb_dat_r.eq(target)
            with m.Case(GA_MAX_STEPS):
                m.d.comb += self.wb_dat_r.eq(max_steps)
            with m.Case(GA_CAND_SIZE):
                m.d.comb += self.wb_dat_r.eq(cand_size)
            with m.Case(GA_NUM_CORES):
                m.d.comb += self.wb_dat_r.eq(self.num_cores)
            with m.Case(GA_TOTAL):
                m.d.comb += self.wb_dat_r.eq(total)
            with m.Case(GA_BEST):
                m.d.comb += self.wb_dat_r.eq(best)
            with m.Default():
                m.d.comb += self.wb_dat_r.eq(count_sel)
        return m
