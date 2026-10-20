#!/usr/bin/env python3
"""Backup charts for the slides (results/*.png). Uses ideal-random hashes, as in the paper's Fig. 4."""
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hll import HyperLogLog

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.size": 12, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 14,
    "axes.titleweight": "bold", "axes.titlecolor": INK, "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb", "lines.linewidth": 2, "legend.frameon": False, "axes.axisbelow": True,
})
rng = np.random.default_rng(2007)


def registers_from_hashes(x, b):
    width = 32 - b
    j = (x >> width).astype(np.int64)
    w = x & ((1 << width) - 1)
    r = np.where(w == 0, width + 1, width - np.floor(np.log2(np.maximum(w, 1))).astype(np.int64))
    reg = np.zeros(1 << b, dtype=np.int64)
    np.maximum.at(reg, j, r)
    return reg


def est(reg, b, which="hll"):
    h = HyperLogLog(b=b)
    h.registers = reg.tolist()
    return {"hll": h.estimate, "raw": h.raw_estimate, "loglog": h.loglog_estimate}[which]()


# 1. running relative error as the stream grows (paper Fig. 4 top)
b = 10
N = 1_000_000
x = rng.integers(0, 2**32, size=N, dtype=np.uint64)
ns = np.unique(np.logspace(1, 6, 300).astype(int))
reg = np.zeros(1 << b, dtype=np.int64)
prev = 0
errs = []
for n in ns:
    np.maximum(reg, registers_from_hashes(x[prev:n], b), out=reg)
    prev = n
    errs.append(est(reg, b) / n - 1)
se = 1.04 / math.sqrt(1 << b)
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(ns, np.array(errs) * 100, color=BLUE)
for s in (se, -se):
    ax.axhline(s * 100, color=INK2, linestyle="--", linewidth=1)
ax.axhline(0, color=INK2, linewidth=1)
ax.text(ns[2], se * 100 + 0.4, "±1.04/√m = ±3.25%", color=INK2)
ax.set_xscale("log")
ax.set_xlabel("distinct items seen so far (n)")
ax.set_ylabel("relative error (%)")
ax.set_title("One HLL (m = 1024, 640 bytes) watching a stream of 1M distinct items")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "running_error.png"), dpi=160)
plt.close(fig)

# 2. distribution of the estimate over many runs (paper Fig. 4 bottom)
trials, n = 1000, 100_000
e = np.array([est(registers_from_hashes(rng.integers(0, 2**32, size=n, dtype=np.uint64), b), b) / n - 1
              for _ in range(trials)])
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.hist(e * 100, bins=40, color=BLUE, edgecolor="#fcfcfb", linewidth=2, density=True)
xs = np.linspace(e.min(), e.max(), 300) * 100
sd = e.std() * 100
ax.plot(xs, np.exp(-0.5 * (xs / sd) ** 2) / (sd * math.sqrt(2 * math.pi)), color=ORANGE, label="Gaussian fit")
ax.set_xlabel("relative error (%)")
ax.set_ylabel("density")
within = [np.mean(np.abs(e) <= k * se) for k in (1, 2, 3)]
ax.set_title(f"{trials} runs, n = 100,000, m = 1024: observed σ = {e.std():.2%} (theory 3.25%)")
ax.legend(loc="upper right")
ax.text(0.01, 0.92, f"within 1σ / 2σ / 3σ: {within[0]:.0%} / {within[1]:.0%} / {within[2]:.0%}",
        transform=ax.transAxes, color=INK2)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "error_histogram.png"), dpi=160)
plt.close(fig)

# 3. error vs memory, HLL vs LOGLOG on identical registers
bs = range(4, 13)
ms, sh, sl = [], [], []
for bb in bs:
    eh, el = [], []
    for _ in range(300):
        r = registers_from_hashes(rng.integers(0, 2**32, size=200_000, dtype=np.uint64), bb)
        eh.append(est(r, bb) / 200_000 - 1)
        el.append(est(r, bb, "loglog") / 200_000 - 1)
    ms.append(1 << bb)
    sh.append(math.sqrt(np.mean(np.square(eh))))
    sl.append(math.sqrt(np.mean(np.square(el))))
ms = np.array(ms)
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(ms, np.array(sl) * 100, "o-", color=ORANGE, markersize=8, label="LOGLOG (geometric mean) observed")
ax.plot(ms, np.array(sh) * 100, "o-", color=BLUE, markersize=8, label="HyperLogLog (harmonic mean) observed")
ax.plot(ms, 130 / np.sqrt(ms), ":", color=ORANGE, linewidth=1.5, label="1.30/√m")
ax.plot(ms, 104 / np.sqrt(ms), ":", color=BLUE, linewidth=1.5, label="1.04/√m")
ax.set_xscale("log", base=2)
ax.set_yscale("log")
ax.set_yticks([2, 3, 5, 10, 20, 40], ["2", "3", "5", "10", "20", "40"])
ax.minorticks_off()
ax.set_xticks(ms, [f"{m}\n{math.ceil(m * 5 / 8)} B" for m in ms])
ax.set_xlabel("registers m  (memory at 5 bits/register)")
ax.set_ylabel("standard error (%)")
ax.set_title("Same registers, different average: HLL needs 64% of LOGLOG's memory")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(OUT, "hll_vs_loglog.png"), dpi=160)
plt.close(fig)

# 4. why the small-range correction exists
b = 10
m = 1 << b
ns = np.unique(np.linspace(1, 6 * m, 200).astype(int))
raw, cor = [], []
for n in ns:
    rr, cc = [], []
    for _ in range(30):
        r = registers_from_hashes(rng.integers(0, 2**32, size=n, dtype=np.uint64), b)
        rr.append(est(r, b, "raw") / n)
        cc.append(est(r, b) / n)
    raw.append(np.mean(rr))
    cor.append(np.mean(cc))
fig, ax = plt.subplots(figsize=(10, 4.5))
ax.plot(ns / m, raw, color=ORANGE, label="raw harmonic-mean estimate")
ax.plot(ns / m, cor, color=BLUE, label="with linear-counting correction (Fig. 3)")
ax.axhline(1, color=INK2, linewidth=1)
ax.axvline(2.5, color=INK2, linestyle="--", linewidth=1)
ax.text(2.55, 2.0, "switch at E = 5m/2", color=INK2)
ax.set_ylim(0.8, min(max(raw), 3))
ax.set_xlabel("n / m")
ax.set_ylabel("mean estimate / true n")
ax.set_title("Small cardinalities: raw HLL overestimates, linear counting fixes it (m = 1024)")
ax.legend(loc="upper right")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "small_range.png"), dpi=160)
plt.close(fig)

# 5. Spark: accuracy vs rsd (if spark results exist)
p = os.path.join(OUT, "spark_results.json")
if os.path.exists(p):
    R = json.load(open(p))
    a = R["approx"]
    labels = [f"rsd={r['rsd']}\nm={r['m']:,}" for r in a]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    axes[0].bar(labels, [abs(r["err"]) * 100 for r in a], color=BLUE, width=0.55)
    axes[0].plot(labels, [r["rsd"] * 100 for r in a], "o", color=ORANGE, markersize=9, label="target rsd")
    axes[0].set_ylabel("|relative error| (%)")
    axes[0].set_title("approx_count_distinct error")
    axes[0].legend()
    axes[1].bar(["exact"] + labels, [R["exact_time"]] + [r["time"] for r in a],
                color=[INK2] + [BLUE] * len(a), width=0.55)
    axes[1].set_ylabel("seconds")
    axes[1].set_title(f"query time on {R['rows']:,} rows")
    for ax in axes:
        ax.tick_params(axis="x", labelsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "spark_rsd.png"), dpi=160)
    plt.close(fig)
print("charts written to", OUT)
