import time, sys, random
import manhattan_reasoning_gym as mrg
from concurrent.futures import ThreadPoolExecutor
N=4; ELEM_BITS=8; TRIALS=150
class Regs(mrg.cloud.RegisterMap):
    CTRL=0x0000; CYCLES=0x0004; DIM=0x0008; A_BASE=0x0040; B_BASE=0x0080; C_BASE=0x00C0
def to_signed(w,bits=32): return w-(1<<bits) if w&(1<<(bits-1)) else w
def flatten(m):
    mask=(1<<ELEM_BITS)-1; return [e&mask for row in m for e in row]
def reference(a,b): return [[sum(a[i][k]*b[k][j] for k in range(N)) for j in range(N)] for i in range(N)]
def rand_mat(rng): return [[rng.randint(-128,127) for _ in range(N)] for _ in range(N)]

def run_clock(clock_hz, board):
    mhz=clock_hz/1e6
    # NB: the matrix_mult design is NOT in this SKI repo -- it lives in the main
    # Manhattan-Reasoning-Cloud repo. Point `design=` at that checkout to run this.
    app=mrg.cloud.App(f"mm{int(mhz)}", design="examples/matrix_mult/design.py",
                      fpga_id=board, sys_clk_freq=int(clock_hz), registers=Regs)
    rng=random.Random(12345)  # identical matrix stream across all clocks
    r={"mhz":mhz,"built":False,"trials":0,"mult_err":0,"elem_err":0,"note":""}
    print(f"[{mhz:.0f}MHz fpga{board}] building...", flush=True)
    try:
        app._program(); r["built"]=True
        print(f"[{mhz:.0f}MHz fpga{board}] programmed, running {TRIALS} multiplies...", flush=True)
        for t in range(TRIALS):
            a=rand_mat(rng); b=rand_mat(rng)
            try:
                app.write(Regs.A_BASE, flatten(a)); app.write(Regs.B_BASE, flatten(b))
                app.write(Regs.CTRL,1)
                for _ in range(50):
                    if app.read(Regs.CTRL)&1: break
                words=app.read(Regs.C_BASE, count=N*N)
                c=[[to_signed(words[i*N+j]) for j in range(N)] for i in range(N)]
                ref=reference(a,b)
                if c!=ref:
                    r["mult_err"]+=1
                    r["elem_err"]+=sum(1 for i in range(N) for j in range(N) if c[i][j]!=ref[i][j])
                r["trials"]+=1
            except Exception as e:
                r["note"]=f"run-fail@trial{t}: {type(e).__name__}"; break
    except Exception as e:
        r["note"]=f"build-fail: {type(e).__name__}: {str(e)[:60]}"
    finally:
        try: app.release()
        except Exception: pass
    elem_rate = r["elem_err"]/(r["trials"]*16) if r["trials"] else None
    print(f"RESULT {mhz:.0f}MHz: built={r['built']} trials={r['trials']} "
          f"mult_err={r['mult_err']} elem_err={r['elem_err']} elem_err_rate={elem_rate} {r['note']}", flush=True)
    return r

CLOCKS=[int(float(x)*1e6) for x in sys.argv[1].split(",")]
with ThreadPoolExecutor(max_workers=2) as ex:
    futs=[ex.submit(run_clock, clk, b) for b,clk in zip([0,1], CLOCKS)]
    rs=[f.result() for f in futs]
print("\n=== MATMUL ERROR-RATE RESULTS ===", flush=True)
for r in sorted(rs, key=lambda x:x["mhz"]):
    er=r["elem_err"]/(r["trials"]*16) if r["trials"] else None
    print(f"  {r['mhz']:>4.0f} MHz | trials={r['trials']:4} | mult_err={r['mult_err']:4} | elem_err_rate={er} | {r['note']}", flush=True)
