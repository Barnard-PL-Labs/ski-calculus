import functools, time
import manhattan_reasoning_gym as mrg
import manhattan_reasoning_gym._client as _client
_client.poll_job = functools.partial(_client.poll_job, timeout=3000)  # ~100 min client wait
DESIGN="examples/ski_calculus/ski_ga_fpga_k50.py"
class Regs(mrg.RegisterMap):
    CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C
    MAX_STEPS=0x10; CAND_SIZE=0x14; NUM_CORES=0x18
    TOTAL=0x1C; BEST=0x20; COUNT_BASE=0x40
N=2; TGT=6; CS=16; MS=2000; RUN_S=5.0; REPS=6
def run_clock(mhz, board=0):
    app=mrg.App(f"k50_{mhz}", design=DESIGN, fpga_id=board,
                sys_clk_freq=int(mhz*1e6), registers=Regs)
    print(f"[{time.strftime('%H:%M')}] [{mhz}MHz] building (~80min)...", flush=True)
    try: app._program()
    except Exception as e:
        print(f"[{mhz}MHz] BUILD-FAIL {type(e).__name__}: {str(e)[:90]}", flush=True); return
    print(f"[{time.strftime('%H:%M')}] [{mhz}MHz] reserved, running GA", flush=True)
    thrs=[]; solved=0
    try:
        app.write(Regs.N_INPUTS,N); app.write(Regs.TARGET,TGT)
        app.write(Regs.MAX_STEPS,MS); app.write(Regs.CAND_SIZE,CS)
        for rep in range(REPS):
            app.write(Regs.SEED,0x1000+rep*0x9E37)
            app.write(Regs.CTRL,1); t0=time.monotonic(); time.sleep(RUN_S)
            total=app.read(Regs.TOTAL); el=time.monotonic()-t0; best=app.read(Regs.BEST)
            app.write(Regs.CTRL,0); thrs.append(total/el); solved+=(best==4)
            print(f"  [{mhz}MHz] rep{rep}: thr={total/el:,.0f} best={best}/4", flush=True)
    except Exception as e:
        print(f"[{mhz}MHz] RUN-FAIL {type(e).__name__}: {str(e)[:90]}", flush=True)
    finally:
        try: app.release()
        except Exception: pass
    clean=[t for t in thrs if t<50_000_000]
    if clean:
        m=sum(clean)/len(clean); sd=(sum((x-m)**2 for x in clean)/len(clean))**0.5
        print(f"RESULT K=50 @ {mhz}MHz: n={len(clean)} thr={m:,.0f} ± {sd:,.0f} solved={solved}/{len(thrs)}", flush=True)
for mhz in [80, 100]:
    run_clock(mhz)
print("ALL DONE", flush=True)
