import time
from manhattan_reasoning_gym import _client, _credentials
url = _client.DEFAULT_API_URL; key = _credentials.load(url)
FPGA = 0
# GA register map
CTRL=0x00; SEED=0x04; N_INPUTS=0x08; TARGET=0x0C; MAX_STEPS=0x10
CAND_SIZE=0x14; NUM_CORES=0x18; TOTAL=0x1C; BEST=0x20
N=2; TGT=6; CS=16; MS=2000; RUN_S=5.0; REPS=6

print("waiting for K=50 build to finish (fpga0 -> reserved)...", flush=True)
for _ in range(360):  # up to ~90 min
    st = _client.get_fpga(FPGA, key, url)["state"]
    if st == "reserved": break
    if st in ("idle", "error"):
        print(f"build did not reserve (state={st}) -- likely failed", flush=True); raise SystemExit
    time.sleep(15)
else:
    print("timed out waiting for reserved", flush=True); raise SystemExit

print("RESERVED -- running GA (K=50 @ 60 MHz)", flush=True)
nc = _client.read(FPGA, key, NUM_CORES, 1, url)[0]
print(f"cores reported = {nc}", flush=True)
_client.write(FPGA, key, N_INPUTS, [N], url); _client.write(FPGA, key, TARGET, [TGT], url)
_client.write(FPGA, key, MAX_STEPS, [MS], url); _client.write(FPGA, key, CAND_SIZE, [CS], url)
thrs=[]; solved=0
for rep in range(REPS):
    try:
        _client.write(FPGA, key, SEED, [0x1000+rep*0x9E37], url)
        _client.write(FPGA, key, CTRL, [1], url); t0=time.monotonic(); time.sleep(RUN_S)
        total=_client.read(FPGA, key, TOTAL, 1, url)[0]; el=time.monotonic()-t0
        best=_client.read(FPGA, key, BEST, 1, url)[0]
        _client.write(FPGA, key, CTRL, [0], url)
        thrs.append(total/el); solved += (best==4)
        print(f"  rep{rep}: thr={total/el:,.0f} best={best}/4", flush=True)
    except Exception as e:
        print(f"  rep{rep} fail: {type(e).__name__}: {str(e)[:70]}", flush=True)
clean=[t for t in thrs if t < 50_000_000]  # drop warm-up outliers
if clean:
    m=sum(clean)/len(clean); sd=(sum((x-m)**2 for x in clean)/len(clean))**0.5
    print(f"RESULT K=50 @ 60 MHz: n={len(clean)} thr_mean={m:,.0f} thr_sd={sd:,.0f} solved={solved}/{len(thrs)}", flush=True)
try: _client.release_session(FPGA, key, url); print("released", flush=True)
except Exception: pass
