"""Run cpu_baseline.c (the exact FPGA workload) on Modal CPU containers.

For each container size C (Modal physical cores), run P concurrent copies of
the single-threaded baseline and sum their throughput -- same method as the
M4 full-chip number.

    modal run experiments/modal_cpu.py
"""
import pathlib

import modal

SRC = pathlib.Path(__file__).resolve().parent.parent / "cpu_baseline.c"

image = (
    modal.Image.debian_slim()
    .apt_install("gcc")
    .add_local_file(SRC, "/root/cpu_baseline.c", copy=True)
    .run_commands("gcc -O3 -o /root/cpu_baseline /root/cpu_baseline.c")
)
app = modal.App("ski-cpu-baseline", image=image)

SECS = 10.0


def _run(procs: int) -> dict:
    import os, re, subprocess
    out = subprocess.run(["lscpu"], capture_output=True, text=True).stdout
    model = next((l.split(":", 1)[1].strip() for l in out.splitlines()
                  if l.startswith("Model name")), "?")
    ps = [subprocess.Popen(["/root/cpu_baseline", str(SECS)], stdout=subprocess.PIPE, text=True)
          for _ in range(procs)]
    rates = [float(re.search(r"([\d.]+) candidates/sec", p.communicate()[0]).group(1)) for p in ps]
    return {"procs": procs, "total": sum(rates), "per_proc": sum(rates) / procs,
            "model": model, "affinity": len(os.sched_getaffinity(0))}


@app.function(cpu=1.0, memory=1024, timeout=600)
def bench_1(procs: int) -> dict:
    return {**_run(procs), "cores": 1}


@app.function(cpu=8.0, memory=1024, timeout=600)
def bench_8(procs: int) -> dict:
    return {**_run(procs), "cores": 8}


@app.function(cpu=32.0, memory=2048, timeout=600)
def bench_32(procs: int) -> dict:
    return {**_run(procs), "cores": 32}


@app.function(cpu=64.0, memory=4096, timeout=600)
def bench_64(procs: int) -> dict:
    return {**_run(procs), "cores": 64}


SIZES = {1: bench_1, 8: bench_8, 32: bench_32, 64: bench_64}


@app.local_entrypoint()
def main():
    calls = []
    for c, fn in SIZES.items():
        # 1 proc per requested core, and 2x to exploit hyperthreads (Modal
        # "cpu" = physical cores; each comes with 2 vCPUs).
        for p in sorted({c, 2 * c}):
            calls.append(fn.spawn(p))
    for r in sorted((c.get() for c in calls), key=lambda r: (r["cores"], r["procs"])):
        print(f"cores={r['cores']:>3} procs={r['procs']:>3} affinity={r['affinity']:>3} "
              f"total={r['total']:>13,.0f}/s  per_proc={r['per_proc']:>9,.0f}/s  {r['model']}")
