import os, sys, pathlib
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from amaranth.back import verilog
import importlib.util
spec = importlib.util.spec_from_file_location("gak16", os.path.join(_ROOT, "ski_ga_fpga_k16.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
K = int(sys.argv[1]) if len(sys.argv) > 1 else 16
dut = m.GAEngine(num_cores=K)
ports = [dut.wb_cyc, dut.wb_stb, dut.wb_we, dut.wb_adr, dut.wb_dat_w,
         dut.wb_sel, dut.wb_dat_r, dut.wb_ack]
out = pathlib.Path(sys.argv[2])
out.write_text(verilog.convert(dut, name="ga_engine", ports=ports))
print(f"exported K={K} -> {out} ({out.stat().st_size} bytes)")
