"""Generate the figures for the ALIFE LBW paper from the measured numbers.

Outputs vector PDF (for the paper) + PNG (preview) into paper/figures/.
Design: Okabe-Ito colorblind-safe palette, despined axes, direct labels,
no chartjunk. Run:  python paper/make_figures.py
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)

# --- Okabe-Ito colorblind-safe palette ---
BLUE = "#0072B2"     # FPGA
ORANGE = "#E69F00"   # CPU
GREY = "#999999"
LIGHTBLUE = "#56B4E9"

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 9,
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "legend.fontsize": 8,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
    "figure.dpi": 120,
})

# ---------- Measured data ----------
cores = [4, 8, 16]
thru = [241_670, 512_152, 1_021_698]          # candidates/sec, measured
PER_CORE = 63_723                              # linear-fit slope (cand/s/core)
MAX_CORES = 60                                 # LUT-bound ceiling (synthesis)
PROJ_FULL = PER_CORE * MAX_CORES               # ~3.82M/s projected full chip
M4_FULLCHIP = 2_416_488                        # measured, Apple M4 all-core


def millions(x, _):
    return f"{x/1e6:.0f}M" if x else "0"


def millions1(x, _):
    return f"{x/1e6:.1f}M" if x else "0"


# ===================================================================
# Figure 1 — throughput scales linearly with cores
# ===================================================================
fig, ax = plt.subplots(figsize=(3.5, 2.8))

# ideal linear line through origin (the model)
xs = [0, MAX_CORES]
ax.plot(xs, [0, PER_CORE * MAX_CORES], "--", color=GREY, lw=1.1, zorder=1,
        label=f"linear model (≈{PER_CORE/1e3:.0f}k/core)")

# projection segment + endpoint
ax.plot([16, MAX_CORES], [PER_CORE * 16, PROJ_FULL], ":", color=BLUE, lw=1.6,
        zorder=2)
ax.scatter([MAX_CORES], [PROJ_FULL], s=42, facecolor="white", edgecolor=BLUE,
           lw=1.6, zorder=4)
ax.annotate(f"~{MAX_CORES} cores (LUT-bound)\n"
            r"$\rightarrow$ " + f"~{PROJ_FULL/1e6:.1f}M/s (proj.)",
            xy=(MAX_CORES, PROJ_FULL), xytext=(MAX_CORES - 2, PROJ_FULL - 0.95e6),
            ha="right", va="top", fontsize=7.5, color=BLUE)

# full M4 reference line
ax.axhline(M4_FULLCHIP, color=ORANGE, lw=1.1, ls=(0, (4, 2)), zorder=1)
ax.annotate("full Apple M4 (10 cores, measured)", xy=(1, M4_FULLCHIP),
            xytext=(1.5, M4_FULLCHIP + 0.10e6), fontsize=7.3, color=ORANGE)

# measured points
ax.plot(cores, thru, "-", color=BLUE, lw=1.8, zorder=3)
ax.scatter(cores, thru, s=46, color=BLUE, zorder=5, label="measured (hardware)")
ax.annotate("1.02M/s\n(K=16)", xy=(16, thru[2]), xytext=(18.5, thru[2] - 0.15e6),
            fontsize=7.5, color=BLUE, va="top")

ax.set_xlim(0, MAX_CORES + 2)
ax.set_ylim(0, 4.1e6)
ax.set_xlabel("parallel cores  (K)")
ax.set_ylabel("candidate evaluations / sec")
ax.set_yticks([0, 1e6, 2e6, 3e6, 4e6])
ax.yaxis.set_major_formatter(FuncFormatter(millions))
ax.set_xticks([0, 4, 8, 16, 30, 45, 60])
ax.grid(axis="y", color="#E6E6E6", lw=0.7, zorder=0)
ax.legend(loc="upper left", frameon=False, handlelength=1.6,
          bbox_to_anchor=(0.0, 1.02))
fig.tight_layout(pad=0.4)
fig.savefig(OUT / "fig1_scaling.pdf")
fig.savefig(OUT / "fig1_scaling.png", dpi=300)
plt.close(fig)

# ===================================================================
# Figure 2 — efficiency vs a modern CPU (two panels)
# ===================================================================
fig, (axa, axb) = plt.subplots(1, 2, figsize=(6.8, 2.7))

# Both panels are COST per evaluation -> lower (shorter bar) is better, and the
# FPGA is the short/winning bar in both. (Energy/eval and cycles/eval are the
# reciprocals of the throughput metrics, so the ratios are unchanged.)
labels = ["ECP5-85\nFPGA", "Apple M4\nCPU"]
LOWER = r"$\downarrow$ lower is better"


def lower_better_note(ax):
    ax.annotate(LOWER, xy=(0.04, 0.93), xycoords="axes fraction",
                fontsize=7.3, color=GREY, style="italic")


# Panel (a): energy per evaluation (µJ). power figures are estimates.
PWR = [3.0, 22.0]                                  # Watts: ECP5 (est.), M4 (est.)
chip_thru = [PROJ_FULL, M4_FULLCHIP]               # full-chip eval/s
energy_uJ = [p / t * 1e6 for p, t in zip(PWR, chip_thru)]   # micro-joules / eval
bars = axa.bar(labels, energy_uJ, color=[BLUE, ORANGE], width=0.62, zorder=3)
for b, v in zip(bars, energy_uJ):
    axa.annotate(f"{v:.2f} µJ", xy=(b.get_x() + b.get_width()/2, v),
                 xytext=(0, 3), textcoords="offset points", ha="center",
                 fontsize=8.5)
axa.set_ylabel("energy / evaluation  (µJ)")
axa.set_title("(a)  energy per evaluation", fontsize=9, loc="left")
axa.set_ylim(0, max(energy_uJ) * 1.2)
axa.grid(axis="y", color="#E6E6E6", lw=0.7, zorder=0)
axa.annotate("≈12× less", xy=(0, 0), xytext=(0.5, energy_uJ[1] * 0.5),
             ha="center", fontsize=10.5, color=BLUE, fontweight="bold")
lower_better_note(axa)

# Panel (b): hardware cost per sustained throughput (chip-only, rough estimates).
# Both axes here are clock-rate-independent (unlike cycles/eval), and both are
# the total-cost-of-ownership argument against a CPU farm.
COST = [40, 130]                          # USD: ECP5-85 (~$40), M4 die (~$130 est.)
cost_per = [c / (t / 1e6) for c, t in zip(COST, chip_thru)]   # $ per (Meval/s)
bars = axb.bar(labels, cost_per, color=[BLUE, ORANGE], width=0.62, zorder=3)
for b, v in zip(bars, cost_per):
    axb.annotate(f"${v:.0f}", xy=(b.get_x() + b.get_width()/2, v),
                 xytext=(0, 3), textcoords="offset points", ha="center",
                 fontsize=8.5)
axb.set_ylabel("hardware $ per (Meval/s)")
axb.set_title("(b)  cost per throughput", fontsize=9, loc="left")
axb.set_ylim(0, max(cost_per) * 1.18)
axb.grid(axis="y", color="#E6E6E6", lw=0.7, zorder=0)
axb.annotate("≈5× less", xy=(0, 0), xytext=(0.5, cost_per[1] * 0.5),
             ha="center", fontsize=10.5, color=BLUE, fontweight="bold")
lower_better_note(axb)

fig.tight_layout(pad=0.6)
fig.savefig(OUT / "fig2_efficiency.pdf")
fig.savefig(OUT / "fig2_efficiency.png", dpi=300)
plt.close(fig)

print("wrote:")
for p in sorted(OUT.glob("*")):
    print("  ", p.relative_to(OUT.parent))
print(f"\nkey numbers: per-core={PER_CORE:,}/s  proj_full={PROJ_FULL:,.0f}/s  "
      f"energy/eval FPGA={energy_uJ[0]:.2f}uJ CPU={energy_uJ[1]:.2f}uJ "
      f"(ratio {energy_uJ[1]/energy_uJ[0]:.1f}x)  $/Meval/s "
      f"FPGA={cost_per[0]:.1f} CPU={cost_per[1]:.1f} "
      f"(ratio {cost_per[1]/cost_per[0]:.1f}x)")
