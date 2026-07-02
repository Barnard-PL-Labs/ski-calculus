import functools, time, sys
import manhattan_reasoning_gym as mrg
import manhattan_reasoning_gym._client as _client
from concurrent.futures import ThreadPoolExecutor
_client.poll_job = functools.partial(_client.poll_job, timeout=2700)
DESIGN="examples/ski_calculus/ski_ga_fpga_k50.py"
class Regs(mrg.RegisterMap):
    CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C
    MAX_STEPS=0x10; CAND_SIZE=0x14; NUM_CORES=0x18
    TOTAL=0x1C; BEST=0x20; COUNT_BASE=0x40
N_INPUTS=2; TARGET_WORD=6; CAND_SIZE=16; MAX_STEPS=2000; RUN_SECONDS=5.0; REPEATS=6

def run_clock(clock_hz, board):
    mhz=clock_hz/1e6
    app=mrg.App(f"gr{int(mhz)}", design=DESIGN, fpga_id=board,
                sys_clk_freq=int(clock_hz), registers=Regs)
    print(f"[{mhz:.0f}MHz fpga{board}] building...", flush=True)
    thrs=[]; solved=0; note=""
    try:
        app._program()
        app.write(Regs.N_INPUTS, N_INPUTS); app.write(Regs.TARGET, TARGET_WORD)
        app.write(Regs.MAX_STEPS, MAX_STEPS); app.write(Regs.CAND_SIZE, CAND_SIZE)
        for rep in range(REPEATS):
            try:
                app.write(Regs.SEED, 0x1000+rep*0x9E37)
                app.write(Regs.CTRL, 1); t0=time.monotonic(); time.sleep(RUN_SECONDS)
                total=app.read(Regs.TOTAL); el=time.monotonic()-t0; best=app.read(Regs.BEST)
                app.write(Regs.CTRL, 0)
                thrs.append(total/el); solved += (best==4)
                print(f"  [{mhz:.0f}MHz rep{rep}] thr={total/el:,.0f} best={best}/4", flush=True)
            except Exception as e:
                note=f"run-fail@rep{rep}: {type(e).__name__}"; break
    except Exception as e:
        note=f"build-fail: {type(e).__name__}: {str(e)[:60]}"
    finally:
        try: app.release()
        except Exception: pass
    if thrs:
        m=sum(thrs)/len(thrs); sd=(sum((x-m)**2 for x in thrs)/len(thrs))**0.5
        print(f"RESULT {mhz:.0f}MHz: n={len(thrs)} thr_mean={m:,.0f} thr_sd={sd:,.0f} solved={solved}/{len(thrs)} {note}", flush=True)
        return {"mhz":mhz,"mean":m,"sd":sd,"n":len(thrs),"solved":solved,"note":note}
    print(f"RESULT {mhz:.0f}MHz: NO DATA {note}", flush=True)
    return {"mhz":mhz,"mean":None,"note":note}

CLOCKS=[int(float(x)*1e6) for x in sys.argv[1].split(",")]
with ThreadPoolExecutor(max_workers=2) as ex:
    rs=[f.result() for f in [ex.submit(run_clock, c, b) for b,c in zip([0,1], CLOCKS)]]
print("\n=== GA REPRODUCIBILITY ===", flush=True)
for r in sorted(rs, key=lambda x:x["mhz"]):
    if r.get("mean"): print(f"  {r['mhz']:.0f} MHz | thr {r['mean']:,.0f} ± {r['sd']:,.0f} | solved {r['solved']}/{r['n']} | {r['note']}", flush=True)
    else: print(f"  {r['mhz']:.0f} MHz | {r['note']}", flush=True)
