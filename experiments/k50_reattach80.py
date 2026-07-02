import time
from manhattan_reasoning_gym import _client, _credentials
url=_client.DEFAULT_API_URL; key=_credentials.load(url); FPGA=0; MHZ=80
CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C; MAX_STEPS=0x10
CAND_SIZE=0x14; NUM_CORES=0x18; TOTAL=0x1C; BEST=0x20
N=2; TGT=6; CS=16; MS=2000; RUN_S=5.0; REPS=6
def safe(fn, *a, tries=6):
    for i in range(tries):
        try: return fn(*a)
        except Exception as e:
            if i==tries-1: raise
            time.sleep(4)
print(f"[{time.strftime('%H:%M')}] waiting for {MHZ}MHz build -> fpga0 reserved (blip-tolerant)...", flush=True)
for _ in range(400):  # ~100 min
    try: st=_client.get_fpga(FPGA,key,url)["state"]
    except Exception: time.sleep(10); continue
    if st=="reserved": break
    if st in ("idle","error"): print(f"build did not reserve (state={st}) -- failed",flush=True); raise SystemExit
    time.sleep(15)
else:
    print("timed out",flush=True); raise SystemExit
print(f"[{time.strftime('%H:%M')}] RESERVED -- running GA @ {MHZ}MHz",flush=True)
nc=safe(_client.read,FPGA,key,NUM_CORES,1,url)[0]; print(f"cores={nc}",flush=True)
for reg,val in [(N_INPUTS,N),(TARGET,TGT),(MAX_STEPS,MS),(CAND_SIZE,CS)]:
    safe(_client.write,FPGA,key,reg,[val],url)
thrs=[]; solved=0
for rep in range(REPS):
    try:
        safe(_client.write,FPGA,key,SEED,[0x1000+rep*0x9E37],url)
        safe(_client.write,FPGA,key,CTRL,[1],url); t0=time.monotonic(); time.sleep(RUN_S)
        total=safe(_client.read,FPGA,key,TOTAL,1,url)[0]; el=time.monotonic()-t0
        best=safe(_client.read,FPGA,key,BEST,1,url)[0]
        safe(_client.write,FPGA,key,CTRL,[0],url)
        thrs.append(total/el); solved+=(best==4)
        print(f"  rep{rep}: thr={total/el:,.0f} best={best}/4",flush=True)
    except Exception as e:
        print(f"  rep{rep} fail: {type(e).__name__}",flush=True)
clean=[t for t in thrs if t<50_000_000]
if clean:
    m=sum(clean)/len(clean); sd=(sum((x-m)**2 for x in clean)/len(clean))**0.5
    print(f"RESULT K=50 @ {MHZ}MHz: n={len(clean)} thr={m:,.0f} ± {sd:,.0f} solved={solved}/{len(thrs)}",flush=True)
try: safe(_client.release_session,FPGA,key,url); print("released",flush=True)
except Exception: pass
