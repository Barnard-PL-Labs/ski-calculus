"""K=50 PLL sweep with a pinned timing-closure target.

Uses the SDK's sys-clk / timing-target split: every build closes P&R at the
same TARGET_MHZ, so only the physical PLL rate differs between points.

  python experiments/k50_clock_sweep.py [pll_mhz,...] [target_mhz] [board,...]

Defaults: clocks 60,80,100,110,120 / target 60 / boards 0,1,2,4,5.
"""
import functools, os, sys, time
import manhattan_reasoning_gym as mrg
import manhattan_reasoning_gym._client as _client
from concurrent.futures import ThreadPoolExecutor

# Extend past the SDK's 40-min default poll: builds are serialized server-side
# (MAX_CONCURRENT_BUILDS=1), so the deadline must cover queue wait for the last
# submission, not just its own P&R -- K=50 on the split-domain firmware runs
# 1.5-2h per build, so a 4-5 point sweep needs an overnight-scale deadline.
_client.poll_job = functools.partial(_client.poll_job, timeout=36000)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(_ROOT, "ski_ga_fpga_k50.py")

class Regs(mrg.cloud.RegisterMap):
    CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C
    MAX_STEPS=0x10; CAND_SIZE=0x14; NUM_CORES=0x18
    TOTAL=0x1C; BEST=0x20; COUNT_BASE=0x40

N=2; TGT=6; CS=16; MS=2000; RUN_S=5.0; REPS=6  # XOR [0,1,1,0] -> 6

CLOCKS = [float(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else [60, 80, 100, 110, 120]
TARGET_MHZ = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
BOARDS = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0, 1, 2, 4, 5]

def run_clock(mhz, board):
    r = {"mhz": mhz, "board": board, "built": False, "thrs": [], "solved": 0, "note": ""}
    app = mrg.cloud.App(f"k50s{int(mhz)}", design=DESIGN, fpga_id=board,
                        sys_clk_freq=int(mhz*1e6), timing_target_mhz=TARGET_MHZ,
                        registers=Regs)
    print(f"[{time.strftime('%H:%M')}] [{mhz:.0f}MHz fpga{board}] building (target {TARGET_MHZ:.0f}MHz, ~80min)...", flush=True)
    try:
        app._program(); r["built"] = True
        print(f"[{time.strftime('%H:%M')}] [{mhz:.0f}MHz fpga{board}] programmed, running GA", flush=True)
        app.write(Regs.N_INPUTS, N); app.write(Regs.TARGET, TGT)
        app.write(Regs.MAX_STEPS, MS); app.write(Regs.CAND_SIZE, CS)
        for rep in range(REPS):
            try:
                app.write(Regs.SEED, 0x1000 + rep*0x9E37)
                app.write(Regs.CTRL, 1); t0 = time.monotonic(); time.sleep(RUN_S)
                total = app.read(Regs.TOTAL); el = time.monotonic() - t0
                best = app.read(Regs.BEST)
                app.write(Regs.CTRL, 0)
                r["thrs"].append(total/el); r["solved"] += (best == 4)
                print(f"  [{mhz:.0f}MHz rep{rep}] thr={total/el:,.0f} best={best}/4", flush=True)
            except Exception as e:
                r["note"] = f"run-fail@rep{rep}: {type(e).__name__}: {str(e)[:60]}"
                print(f"[{time.strftime('%H:%M')}] [{mhz:.0f}MHz fpga{board}] {r['note']}", flush=True)
                break
    except Exception as e:
        r["note"] = f"build-fail: {type(e).__name__}: {str(e)[:200]}"
        print(f"[{time.strftime('%H:%M')}] [{mhz:.0f}MHz fpga{board}] {r['note']}", flush=True)
    finally:
        try: app.release()
        except Exception: pass
    return r

with ThreadPoolExecutor(max_workers=len(BOARDS)) as ex:
    futs = []
    for i in range(0, len(CLOCKS), len(BOARDS)):
        batch = CLOCKS[i:i+len(BOARDS)]
        futs += [ex.submit(run_clock, c, b) for c, b in zip(batch, BOARDS)]
    results = [f.result() for f in futs]

print(f"\n=== K=50 PLL SWEEP (closure target {TARGET_MHZ:.0f} MHz, XOR) ===", flush=True)
for r in sorted(results, key=lambda x: x["mhz"]):
    clean = [t for t in r["thrs"] if t < 50_000_000]  # drop warm-up outliers
    if clean:
        m = sum(clean)/len(clean); sd = (sum((x-m)**2 for x in clean)/len(clean))**0.5
        print(f"  {r['mhz']:>5.0f} MHz | thr {m:,.0f} ± {sd:,.0f} | solved {r['solved']}/{len(r['thrs'])} | {r['note']}", flush=True)
    else:
        print(f"  {r['mhz']:>5.0f} MHz | {'NO-BUILD' if not r['built'] else 'NO DATA'} | {r['note']}", flush=True)
