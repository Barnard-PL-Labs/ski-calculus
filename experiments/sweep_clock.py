import os, time, sys
import manhattan_reasoning_gym as mrg
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(_ROOT, "ski_ga_fpga_k16.py")

class Regs(mrg.cloud.RegisterMap):
    CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C
    MAX_STEPS=0x10; CAND_SIZE=0x14; NUM_CORES=0x18
    TOTAL=0x1C; BEST=0x20; COUNT_BASE=0x40

N_INPUTS=2; TARGET_WORD=6; CAND_SIZE=16; MAX_STEPS=2000; RUN_SECONDS=5.0  # XOR [0,1,1,0]->6

def run_one(clock_hz, board):
    mhz = clock_hz/1e6
    r = {"mhz": mhz, "board": board, "built": False, "best": None, "thr": None, "note": ""}
    app = mrg.cloud.App(f"sweep{int(mhz)}", design=DESIGN, fpga_id=board,
                  sys_clk_freq=int(clock_hz), registers=Regs)
    print(f"[{mhz:.0f}MHz fpga{board}] building...", flush=True)
    try:
        app._program(); r["built"] = True
        print(f"[{mhz:.0f}MHz fpga{board}] programmed, running GA...", flush=True)
        try:
            app.write(Regs.SEED, 0x12345678); app.write(Regs.N_INPUTS, N_INPUTS)
            app.write(Regs.TARGET, TARGET_WORD); app.write(Regs.MAX_STEPS, MAX_STEPS)
            app.write(Regs.CAND_SIZE, CAND_SIZE)
            app.write(Regs.CTRL, 1); t0=time.monotonic(); time.sleep(RUN_SECONDS)
            total=app.read(Regs.TOTAL); el=time.monotonic()-t0; best=app.read(Regs.BEST)
            app.write(Regs.CTRL, 0)
            r["best"]=best; r["thr"]=int(total/el) if el else 0
        except Exception as e:
            r["note"]=f"run-fail {type(e).__name__}: {str(e)[:70]}"
    except Exception as e:
        r["note"]=f"build-fail {type(e).__name__}: {str(e)[:70]}"
    finally:
        try: app.release()
        except Exception: pass
    print(f"RESULT {mhz:.0f}MHz fpga{board}: built={r['built']} best={r['best']}/4 thr={r['thr']} {r['note']}", flush=True)
    return r

CLOCKS = [int(float(x)*1e6) for x in sys.argv[1].split(",")] if len(sys.argv)>1 else [50,100]
CLOCKS = [c if c>1000 else int(c*1e6) for c in CLOCKS]
results=[]
with ThreadPoolExecutor(max_workers=2) as ex:
    for i in range(0, len(CLOCKS), 2):
        batch=CLOCKS[i:i+2]
        futs=[ex.submit(run_one, clk, b) for b,clk in zip([0,1], batch)]
        results += [f.result() for f in futs]
print("\n=== SWEEP RESULTS (K=16, XOR) ===", flush=True)
for r in sorted(results, key=lambda x:x["mhz"]):
    v = "SOLVED 4/4" if r["best"]==4 else (f"BROKE best={r['best']}/4" if r["built"] else "NO-BUILD")
    print(f"  {r['mhz']:>5.0f} MHz | {v:14} | thr={r['thr']} | {r['note']}", flush=True)
