#!/usr/bin/env python3
"""Figure: overclocking past STA timing closure on a real ECP5-85.

Measured GA candidate-throughput vs requested SoC clock, with regimes shaded,
the STA-predicted ceiling marked, the bit-exact-correct span (matmul probe)
annotated, and the marginal control-bridge failure zone hatched. Edit the DATA
block and run:  python paper/make_fig_overclock.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---- measured data ----
STA_MHZ = 94            # nextpnr static-timing prediction (K=16 engine)
MM_CLEAN_TO = 128       # matmul bit-exact correct through this clock (0 errors)
BRIDGE_LO, BRIDGE_HI = 125, 130   # marginal/probabilistic bridge failure zone

# GA candidate throughput, M cand/s.  err = std over 6 repeats (0 = single shot)
THR_MHZ = [50, 100, 110, 120]
THR     = [1.036, 2.035, 2.261, 2.481]
THR_ERR = [0.0, 0.0, 0.104, 0.118]

BLUE, ORANGE, GREY = "#1f5fb4", "#e08a1e", "#777777"
fig, ax = plt.subplots(figsize=(3.35, 2.5))

ax.axvspan(45, BRIDGE_LO, color="#e9f4e9", zorder=0)        # clean + correct
ax.axvspan(BRIDGE_LO, BRIDGE_HI, facecolor="#f6dada", hatch="///",
           edgecolor="#c98a8a", lw=0.0, zorder=0)           # marginal bridge
ax.axvspan(BRIDGE_HI, 145, color="#f0caca", zorder=0)       # dead

ax.axvline(STA_MHZ, color=GREY, ls="--", lw=0.9, zorder=1)
ax.annotate("STA\nbound", xy=(STA_MHZ, 0.1), xytext=(STA_MHZ - 16, 0.25),
            fontsize=6.3, color=GREY, ha="center")

# bit-exact-correct span (matmul probe): an arrow from baseline to 128
ax.annotate("", xy=(MM_CLEAN_TO, 0.55), xytext=(50, 0.55),
            arrowprops=dict(arrowstyle="|-|", color=ORANGE, lw=1.1))
ax.text(89, 0.66, "matmul bit-exact correct", fontsize=6.0, color=ORANGE, ha="center")

xs = [m for m, t in zip(THR_MHZ, THR) if t is not None]
ys = [t for t in THR if t is not None]
es = [e for e, t in zip(THR_ERR, THR) if t is not None]
ax.errorbar(xs, ys, yerr=es, fmt="o-", color=BLUE, lw=1.6, ms=4, capsize=2,
            zorder=3, label="GA throughput")
# clean-linear reference (from 50 MHz baseline) to show the deficit
ax.plot([50, 130], [1.036, 1.036 * 130 / 50], ls=":", color=GREY, lw=0.9,
        zorder=2, label="clock-linear")

ax.set_xlabel("requested SoC clock (MHz)")
ax.set_ylabel("GA throughput (M cand/s)", color=BLUE)
ax.tick_params(axis="y", labelcolor=BLUE)
ax.set_xlim(45, 145)
ax.set_ylim(0, 2.9)
ax.text(127.5, 2.6, "bridge\ndies", fontsize=6.3, color="#b03030", ha="center")
ax.legend(fontsize=6.0, loc="lower right", framealpha=0.9)
ax.set_title("Overclocking a real ECP5-85 past STA", fontsize=8, loc="left")
fig.tight_layout(pad=0.3)
fig.savefig("paper/figures/fig_overclock.pdf")
fig.savefig("paper/figures/fig_overclock.png", dpi=300)
print("wrote paper/figures/fig_overclock.{pdf,png}")
