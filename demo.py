#!/usr/bin/env python3
"""
HyperLogLog live demo, parts 1-3 (part 4 is spark_demo.py).

    python demo.py scan              # PART 1: 16-register HLL scans items; Enter = next item
    python demo.py scan --auto 1.5   #         same, plays by itself (1.5 s per item)
    python demo.py estimate          # PART 2: how the bit patterns become one number (--scale adds m=1024 on 200k clicks)
    python demo.py merge             # PART 3: 2 machines -> 2 sketches -> keep the bigger number == one computer (--big: 4 x 80,000 clicks)
    python demo.py accuracy          # extra:  error ~ 1.04/sqrt(m); HLL vs LOGLOG on the same registers

Options: --no-color (plain text), --no-clear (don't clear the screen between items; for recording).
Needs only the Python standard library.
"""
import argparse
import math
import os
import random
import statistics
import sys
import time

from hll import HyperLogLog

# ---------------------------------------------------------------- terminal setup
if os.name == "nt":
    os.system("")  # turns on ANSI colour handling in the Windows console
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

COLOR, CLEAR = True, True


def c(t, code):
    return f"\033[{code}m{t}\033[0m" if COLOR else t


def blue(t): return c(t, "94;1")
def orange(t): return c(t, "33")
def red(t): return c(t, "91;1")
def green(t): return c(t, "92;1")
def dim(t): return c(t, "90")
def bold(t): return c(t, "1")
def on_blue(t): return c(t, "44;97;1")
def on_green(t): return c(t, "42;30;1")


def clear():
    if CLEAR:
        print("\033[2J\033[H", end="")


def wait(auto, msg="Enter = next"):
    if auto is None:
        try:
            input(dim(f"  [{msg}]") if msg else "")
        except EOFError:
            print()
    elif auto > 0:
        time.sleep(auto)


def title(text):
    print(bold("=" * 78))
    print(bold(text))
    print(bold("=" * 78))


# ---------------------------------------------------------------- drawing
def hash_bits(x, b, width=32):
    """index bits | leading zeros, the first 1, the rest"""
    s = format(x, f"0{width}b")
    idx, rest = s[:b], s[b:]
    k = rest.find("1")
    tail = orange(rest) if k < 0 else orange(rest[:k]) + red(rest[k]) + dim(rest[k + 1:])
    return blue(idx) + " | " + tail


def grid(h, hit=None, positions=10):
    """Registers x bit positions.  1 on blue = bit turned on;  1 on green = the max (what HLL stores)."""
    out = [dim("              bit position ρ →")]
    out.append(dim("  register   ") + " ".join(f"{p:>2}" for p in range(1, positions + 1)) + dim("    stored M[j]"))
    for j in range(h.m):
        cells = []
        for p in range(1, positions + 1):
            on = h.bitmaps[j] >> (p - 1) & 1
            if on and p == h.registers[j]:
                cells.append(on_green(" 1"))
            elif on:
                cells.append(on_blue(" 1"))
            else:
                cells.append(dim(" ·"))
        label = f"  reg {j:>2} {format(j, '04b')}"
        label = red(label + " ◀") if j == hit else dim(label + "  ")
        out.append(f"{label} " + " ".join(cells) + f"    M[{j:>2}] = {h.registers[j]}")
    return "\n".join(out)


# ---------------------------------------------------------------- PART 1
B_SMALL = 2                     # 2 index bits → m = 4 registers
STREAM = ["alice", "carol", "dave", "alice", "grace", "erin", "frank", "niaj"]


def build_small():
    """The part-1 sketch, built silently (used by part 2)."""
    h = HyperLogLog(b=B_SMALL, track_bitmaps=True)
    for item in STREAM:
        h.add(item)
    return h, set(STREAM)


def scan_screen(h, step, ev=None, item=None, before=None, positions=6):
    """Data only: header, hash bits, register, rho, and the registers x bits grid."""
    clear()
    print(bold(f"HyperLogLog   m = {h.m}") + dim(f"      item {step}/{len(STREAM)}") + "\n")
    if ev is None:
        print(f"  item    {dim('-')}\n  hash    {dim('-')}\n")
    else:
        s = format(ev["hash"], "032b")
        idx, rest = s[:h.b], s[h.b:]
        k = ev["rho"] - 1
        print(f"  item    {bold(item)}")
        print(f"  hash    {blue(idx)} {orange(rest[:k])}{red(rest[k:k + 1])}{dim(rest[k + 1:])}")
        print(f"          {blue('^' * h.b)} {' ' * k}{red('^')}")
        reg_label, rho_label = f"register {ev['j']}", f"ρ = {ev['rho']}"
        print(f"          {blue(reg_label)}   {red(rho_label)}\n")
    print(dim("  reg" + " " * (h.b + 4) + "ρ " + " ".join(f"{p:>2}" for p in range(1, positions + 1)) + "     M"))
    for j in range(h.m):
        cells = []
        for p in range(1, positions + 1):
            on = h.bitmaps[j] >> (p - 1) & 1
            new_bit = (ev is not None and j == ev["j"] and p == ev["rho"]
                       and not (before[j] >> (p - 1) & 1))
            if new_bit:
                cells.append(c(" 1", "41;97;1"))          # the bit this item turned on
            elif on and p == h.registers[j]:
                cells.append(on_green(" 1"))              # highest bit = stored value
            elif on:
                cells.append(on_blue(" 1"))               # bit seen earlier
            else:
                cells.append(dim(" ·"))
        here = ev is not None and j == ev["j"]
        lab = f"{j:>4} {format(j, f'0{h.b}b')}"
        lab = red("▶" + lab) if here else " " + dim(lab)
        mval = f"{h.registers[j]:>2}"
        if here and ev["changed"]:
            mval = green(f"{ev['old']:>2} → {ev['new']}")
        elif here:
            mval = bold(mval)
        print(f" {lab}    " + " ".join(cells) + f"    {mval}")


def part_scan(auto):
    h = HyperLogLog(b=B_SMALL, track_bitmaps=True)   # build: 4 empty registers
    scan_screen(h, 0)
    wait(auto, "")
    for i, item in enumerate(STREAM, 1):
        before = list(h.bitmaps)
        ev = h.add(item)                          # hash → register → rho → max
        scan_screen(h, i, ev, item, before)
        wait(auto, "")


# ---------------------------------------------------------------- PART 2
def part_estimate(auto, scale=False):
    h, seen = build_small()
    d = h.estimate_details()
    clear()
    print(bold(f"HyperLogLog   m = {h.m}") + dim(f"      after {len(STREAM)} items") + "\n")
    print(dim(f"  {'reg':>8} {'M':>3} {'2^M':>8} {'2^-M':>8}"))
    for j, r in enumerate(h.registers):
        print(f"  {j:>3} {format(j, f'0{h.b}b'):>4} {r:>3} {2 ** r:>8} {2.0 ** -r:>8.4f}")
    wait(auto, "")
    raw_s, final_s = f"{d['raw']:.2f}", f"{d['final']:.2f}"
    print()
    def row(label, value):
        print(f"  {label:<16}= {value}")
    row("Σ 2^-M", f"{d['sum']:.4f}")
    row("Z = 1/Σ", f"{d['Z']:.4f}")
    row(f"α_{d['m']}", f"{d['alpha']}")
    row("E = α·m²·Z", f"{d['alpha']} × {d['m']}² × {d['Z']:.4f} = {bold(raw_s)}")
    row("empty registers", f"{d['zeros']}" + (f"   →  m·ln(m/V) = {final_s}" if d["final"] != d["raw"] else ""))
    print()
    row("estimate", green(final_s))
    row("exact", f"{len(seen)}")
    if not scale:
        return
    wait(auto, "")

    clear()
    print(bold("HyperLogLog   m = 1024") + dim("      640 bytes · 200,000 clicks") + "\n")
    rng = random.Random(7)
    big, exact = HyperLogLog(b=10), set()
    se = big.standard_error()
    print(f"  expected error 1.04/√m = ±{se:.2%}\n")
    print(dim(f"  {'clicks':>11} {'exact':>15} {'HLL':>13} {'error':>9}  ≤2σ"))
    for i in range(1, 200_001):
        uid = f"user{rng.randrange(200_000)}"
        big.add(uid)
        exact.add(uid)
        if i in (100, 1_000, 10_000, 50_000, 100_000, 200_000):
            e = big.estimate()
            err = (e - len(exact)) / len(exact)
            tag = green("✓") if abs(err) <= 2 * se else red("✗")
            print(f"  {i:>11,} {len(exact):>15,} {e:>13,.0f} {err:>+9.2%}  {tag}")
            if auto is not None and auto > 0:
                time.sleep(min(auto, 0.6))
    set_mb = (sys.getsizeof(exact) + sum(sys.getsizeof(u) for u in exact)) / 1e6
    print(f"\n  memory   HLL {bold('640 B')}   ·   exact set {bold(f'{set_mb:.1f} MB')}")


# ---------------------------------------------------------------- PART 3
MACHINE_A = ["alice", "carol", "dave", "grace"]     # the same 8 items as part 1,
MACHINE_B = ["alice", "erin", "frank", "niaj"]      # split over 2 machines; alice is on both


def small_grid(h, positions=6):
    """Registers x bit positions for one machine (data only)."""
    lines = [dim("  reg" + " " * (h.b + 3) + "ρ " + " ".join(f"{p:>2}" for p in range(1, positions + 1)) + "     M")]
    for j in range(h.m):
        cells = []
        for p in range(1, positions + 1):
            on = h.bitmaps[j] >> (p - 1) & 1
            if on and p == h.registers[j]:
                cells.append(on_green(" 1"))
            elif on:
                cells.append(on_blue(" 1"))
            else:
                cells.append(dim(" ·"))
        lines.append(f"  {j:>3} {format(j, f'0{h.b}b')}    " + " ".join(cells) + f"    {h.registers[j]:>2}")
    return "\n".join(lines)


def part_merge(auto, counts=False):
    a = HyperLogLog(b=B_SMALL, track_bitmaps=True)   # machine A builds its own sketch
    b = HyperLogLog(b=B_SMALL, track_bitmaps=True)   # machine B builds its own sketch
    for x in MACHINE_A:
        a.add(x)
    for x in MACHINE_B:
        b.add(x)
    merged = a.merge(b)                               # keep the bigger number per register
    one = HyperLogLog(b=B_SMALL)                      # one computer reading everything
    for x in MACHINE_A + MACHINE_B:
        one.add(x)

    clear()
    print(bold(f"HyperLogLog   m = {a.m}") + dim("      2 machines") + "\n")
    print(f"  machine A   {bold(', '.join(MACHINE_A))}")
    print(small_grid(a) + "\n")
    print(f"  machine B   {bold(', '.join(MACHINE_B))}")
    print(small_grid(b))
    wait(auto, "")

    print()
    print(dim(f"  {'reg':>8}   A    B    max   one computer"))
    for j in range(a.m):
        va, vb = a.registers[j], b.registers[j]
        sa = green(f"{va:>4}") if va >= vb else dim(f"{va:>4}")
        sb = green(f"{vb:>4}") if vb >= va else dim(f"{vb:>4}")
        print(f"  {j:>3} {format(j, f'0{a.b}b'):>4} {sa} {sb}  {bold(f'{merged.registers[j]:>5}')}"
              f"   {one.registers[j]:>3}")
    same = merged.registers == one.registers
    print("\n  max = one computer   " + (green("✓ identical") if same else red("✗")))
    if not counts:
        return
    wait(auto, "")

    da, db = len(set(MACHINE_A)), len(set(MACHINE_B))
    exact = len(set(MACHINE_A + MACHINE_B))
    est = f"{merged.estimate():.2f}"
    print()
    print(dim(f"  {'':<22}{'distinct':>10}"))
    print(f"  {'machine A':<22}{da:>10}")
    print(f"  {'machine B':<22}{db:>10}")
    print(f"  {'A + B':<22}{da + db:>10}   " + red("✗"))
    print(f"  {'merged HLL estimate':<22}{green(f'{est:>10}')}")
    print(f"  {'exact':<22}{exact:>10}")


def part_merge_big(auto):
    rng = random.Random(11)
    parts = [[f"user{rng.randrange(d * 40_000, d * 40_000 + 100_000)}" for _ in range(80_000)] for d in range(4)]
    clear()
    title("PART 3 · merging partial results: 4 partitions, built independently")
    print(dim("\n  4 partitions of 80,000 clicks each; returning users appear in several partitions\n"))
    sketches = []
    for i, p in enumerate(parts):
        s = HyperLogLog(b=10)
        for u in p:
            s.add(u)
        sketches.append(s)
        print(f"  worker {i}: sketched {len(p):,} clicks   estimate {s.estimate():>8,.0f}   exact {len(set(p)):>7,}"
              f"   → sends {s.memory_bytes()} bytes")
    wait(auto, "Enter = merge")

    merged = sketches[0]
    for s in sketches[1:]:
        merged = merged.merge(s)
    single = HyperLogLog(b=10)
    for p in parts:
        for u in p:
            single.add(u)

    cols = 12
    print(f"\n  first {cols} of 1,024 registers   {dim('(green = the partition holding the max)')}\n")
    print("  " + " " * 13 + "".join(f"{j:>4}" for j in range(cols)))
    for i, s in enumerate(sketches):
        row = ""
        for j in range(cols):
            v = f"{s.registers[j]:>4}"
            row += green(v) if s.registers[j] == merged.registers[j] else dim(v)
        print(f"  partition {i}  {row}")
    print("  " + "-" * (13 + 4 * cols))
    print(f"  {bold('max-merge')}    " + "".join(bold(f"{merged.registers[j]:>4}") for j in range(cols)))
    print(f"  one pass     " + "".join(f"{single.registers[j]:>4}" for j in range(cols)) + dim("   ← one machine reading everything"))
    same = merged.registers == single.registers
    print(f"\n  merged == one pass over all data?  "
          + (green(f"YES, all {merged.m} registers identical") if same else red("NO")))
    wait(auto, "Enter = compare with exact")

    exact_union = len(set().union(*map(set, parts)))
    naive = sum(len(set(p)) for p in parts)
    m_est = merged.estimate()
    print(f"\n  {'distinct users across all partitions':<40}{'value':>10}{'error':>10}")
    print(f"  {'exact':<40}{exact_union:>10,}")
    print(f"  {'HLL, merged from 4 × 640-byte sketches':<40}{m_est:>10,.0f}{(m_est - exact_union) / exact_union:>+10.2%}")
    print(f"  {'adding the 4 per-partition counts':<40}{naive:>10,}{(naive - exact_union) / exact_union:>+10.1%}  "
          + red("← distinct counts don't add"))
    print(dim("\n  max is associative, commutative and idempotent → any split, any order, any overlap.\n"
              "  So the reduce step ships 640 bytes per worker instead of every distinct id."))


# ---------------------------------------------------------------- extra
def part_accuracy(trials=200, n=50_000, seed=3):
    clear()
    title("EXTRA · error shrinks like 1/√m;  HLL (harmonic) vs LOGLOG (geometric) on the same registers")
    print(f"\n  {trials} runs per row, n = {n:,} random hashes each\n")
    print(f"  {'m':>6} {'bytes':>6} {'HLL theory':>11} {'HLL observed':>13} {'LOGLOG observed':>16} {'LOGLOG theory':>14}")
    rng = random.Random(seed)
    for b in (4, 6, 8, 10):
        m = 1 << b
        e_h, e_l = [], []
        for _ in range(trials):
            h = HyperLogLog(b=b)
            regs = [0] * m
            width = 32 - b
            for _ in range(n):
                x = rng.getrandbits(32)
                j, w = x >> width, x & ((1 << width) - 1)
                r = width + 1 if w == 0 else width - w.bit_length() + 1
                if r > regs[j]:
                    regs[j] = r
            h.registers = regs
            e_h.append(h.estimate() / n - 1)
            e_l.append(h.loglog_estimate() / n - 1)
        sd_h = math.sqrt(statistics.fmean(x * x for x in e_h))
        sd_l = math.sqrt(statistics.fmean(x * x for x in e_l))
        print(f"  {m:>6} {HyperLogLog(b).memory_bytes():>6} {1.04 / math.sqrt(m):>11.2%} {sd_h:>13.2%}"
              f" {sd_l:>16.2%} {1.30 / math.sqrt(m):>14.2%}")
    print(dim("\n  Same accuracy as LOGLOG with (1.04/1.30)² ≈ 64% of the memory."))


def main():
    global COLOR, CLEAR
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", choices=["scan", "estimate", "merge", "accuracy"])
    ap.add_argument("--auto", type=float, default=None, metavar="SECONDS",
                    help="play by itself, pausing SECONDS between steps (0 = no pauses)")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--no-clear", action="store_true", help="never clear the screen")
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--counts", action="store_true", help="merge: also compare with adding per-machine counts")
    ap.add_argument("--big", action="store_true", help="merge: 4 machines x 80,000 clicks, 1,024 registers")
    ap.add_argument("--scale", action="store_true", help="estimate: also show m=1024 on 200,000 clicks")
    a = ap.parse_args()
    COLOR, CLEAR = not a.no_color, not a.no_clear
    try:
        {"scan": lambda: part_scan(a.auto),
         "estimate": lambda: part_estimate(a.auto, a.scale),
         "merge": lambda: part_merge_big(a.auto) if a.big else part_merge(a.auto, a.counts),
         "accuracy": lambda: part_accuracy(a.trials)}[a.part]()
    except KeyboardInterrupt:
        print("\n  (stopped)")


if __name__ == "__main__":
    main()
