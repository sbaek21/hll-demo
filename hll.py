"""
A from-scratch HyperLogLog, following Figure 3 of
Flajolet, Fusy, Gandouet, Meunier (2007), "HyperLogLog: the analysis of a
near-optimal cardinality estimation algorithm".

  - 32-bit hash  h(v)
  - first b bits  -> register index j       (m = 2^b registers)
  - remaining bits w -> rho(w) = position of leftmost 1-bit (rho(0^K) = K+1)
  - M[j] = max(M[j], rho(w))
  - estimate E = alpha_m * m^2 / sum_j 2^-M[j]     (normalised harmonic mean)
  - small-range correction (linear counting) and large-range correction

The class also keeps an optional per-register *bitmap* of every rho value it
has ever seen.  Real HLL does NOT store this (it only keeps the max); it is
there purely so the demo can show "which bits got turned on".
"""
from __future__ import annotations

import hashlib
import math

HASH_BITS = 32


def hash32(item) -> int:
    """Deterministic 32-bit hash (first 4 bytes of SHA-1, as the paper suggests sha1)."""
    data = item if isinstance(item, bytes) else str(item).encode("utf-8")
    return int.from_bytes(hashlib.sha1(data).digest()[:4], "big")


def rho(w: int, width: int) -> int:
    """Position of the leftmost 1-bit in a `width`-bit word (1-based). rho(0^K) = K+1."""
    if w == 0:
        return width + 1
    return width - w.bit_length() + 1


def alpha_exact(m: int) -> float:
    """alpha_m = (m * integral_0^inf log2((2+u)/(1+u))^m du)^-1, eq. (3) of the paper."""
    n, total = 20000, 0.0
    for i in range(1, n):
        t = i / n
        u = t / (1 - t)
        total += math.log2((2 + u) / (1 + u)) ** m / (1 - t) ** 2
    return 1.0 / (m * total / n)


def alpha(m: int) -> float:
    """Bias-correction constant alpha_m from Figure 3 of the paper (eq. 3 for m < 16)."""
    if m < 16:
        return round(alpha_exact(m), 4)
    if m == 16:
        return 0.673
    if m == 32:
        return 0.697
    if m == 64:
        return 0.709
    return 0.7213 / (1 + 1.079 / m)


class HyperLogLog:
    def __init__(self, b: int = 10, track_bitmaps: bool = False):
        if not 2 <= b <= 16:
            raise ValueError("b must be in [2, 16] (m = 4 .. 65536)")
        self.b = b
        self.m = 1 << b
        self.width = HASH_BITS - b  # bits left after the index
        self.registers = [0] * self.m  # Fig. 3 initialises to 0
        self.track_bitmaps = track_bitmaps
        self.bitmaps = [0] * self.m if track_bitmaps else None

    # ------------------------------------------------------------------ update
    def split(self, x: int):
        """Return (register index j, remainder w, rho(w)) for a 32-bit hash x."""
        j = x >> self.width
        w = x & ((1 << self.width) - 1)
        return j, w, rho(w, self.width)

    def add(self, item):
        """Add one item. Returns a dict describing what happened (for tracing)."""
        x = hash32(item)
        j, w, r = self.split(x)
        old = self.registers[j]
        if r > old:
            self.registers[j] = r
        if self.track_bitmaps:
            self.bitmaps[j] |= 1 << (r - 1)
        return {"item": item, "hash": x, "j": j, "w": w, "rho": r,
                "old": old, "new": self.registers[j], "changed": r > old}

    def add_hash(self, x: int):
        j, w, r = self.split(x)
        if r > self.registers[j]:
            self.registers[j] = r

    # ---------------------------------------------------------------- estimate
    def raw_estimate(self) -> float:
        z = 1.0 / sum(2.0 ** -r for r in self.registers)
        return alpha(self.m) * self.m * self.m * z

    def estimate_details(self) -> dict:
        """Every intermediate quantity of the Fig. 3 estimate, for explaining it."""
        m = self.m
        s = sum(2.0 ** -r for r in self.registers)
        z = 1.0 / s
        a = alpha(m)
        raw = a * m * m * z
        zeros = self.registers.count(0)
        two32 = 2.0 ** HASH_BITS
        if raw <= 2.5 * m and zeros > 0:
            final, regime = m * math.log(m / zeros), "small range -> linear counting m*ln(m/V)"
        elif raw <= two32 / 30:
            final, regime = raw, "intermediate range -> no correction"
        else:
            final, regime = -two32 * math.log(1 - raw / two32), "large range -> hash-collision correction"
        return {"m": m, "sum": s, "Z": z, "alpha": a, "raw": raw,
                "zeros": zeros, "final": final, "regime": regime}

    def estimate(self) -> float:
        return self.estimate_details()["final"]

    def loglog_estimate(self) -> float:
        """Durand-Flajolet LOGLOG on the same registers (geometric mean), for comparison."""
        mean = sum(self.registers) / self.m
        return 0.39701 * self.m * 2.0 ** mean

    # ------------------------------------------------------------------- merge
    def merge(self, other: "HyperLogLog") -> "HyperLogLog":
        """Union of two sketches = component-wise max of registers."""
        if other.b != self.b:
            raise ValueError("can only merge sketches with the same m")
        out = HyperLogLog(self.b)
        out.registers = [max(a, c) for a, c in zip(self.registers, other.registers)]
        return out

    def memory_bytes(self, bits_per_register: int = 5) -> int:
        return math.ceil(self.m * bits_per_register / 8)

    def standard_error(self) -> float:
        return 1.04 / math.sqrt(self.m)
