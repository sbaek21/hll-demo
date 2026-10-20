#!/usr/bin/env python3
"""
HyperLogLog live demo, PART 4: the same task (count distinct user_ids) in Spark on large data,
compared against the exact distinct count.

    python spark_demo.py --pause                # 20M clicks; Enter = next step (use this in class)
    python spark_demo.py --pause --rows 5000000 # smaller, if the laptop is slow
    python spark_demo.py                        # runs straight through (quick test)

  step 1  exact:  COUNT(DISTINCT user_id)
  step 2  HLL:    hll_sketch_agg per partition -> hll_union_agg -> hll_sketch_estimate

Spark's hll_* functions (Spark >= 3.5) wrap Apache DataSketches' HLL sketch.
Needs: pip install pyspark   and Java 17 or 21.   --verbose shows Spark/Java log messages.
"""
import argparse
import math
import os
import sys
import time
import traceback

if os.name == "nt":
    os.system("")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAUSE = False


def c(t, code):
    return f"\033[{code}m{t}\033[0m"


def bold(t): return c(t, "1")
def dim(t): return c(t, "90")
def green(t): return c(t, "92;1")


def wait():
    if PAUSE:
        try:
            input("")
        except EOFError:
            pass


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


def hide_java_messages():
    """Send the JVM's warnings (stderr) to /dev/null; errors are re-printed by main()."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)


def run(a):
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    spark = (SparkSession.builder.master("local[*]").appName("hll-demo")
             .config("spark.driver.memory", a.driver_memory)
             .config("spark.sql.shuffle.partitions", str(a.partitions))
             .config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    users = a.users or a.rows // 4

    # skewed clickstream: heavy users click a lot → many duplicate user_ids
    clicks = (spark.range(a.rows, numPartitions=a.partitions)
              .withColumn("user_id", (F.pow(F.rand(seed=42), 2) * users).cast("long"))
              .select("id", "user_id")
              .cache())
    clicks.count()
    # warm-up on tiny data, so neither method's timing includes one-time JVM start-up costs
    tiny = spark.range(1000).withColumn("partition", F.spark_partition_id())
    tiny.agg(F.countDistinct("id")).first()
    (tiny.groupBy("partition").agg(F.hll_sketch_agg("id", 12).alias("s"))
         .agg(F.hll_sketch_estimate(F.hll_union_agg("s"))).first())

    # ---------------------------------------------------------------- data
    print(bold(f"Spark {spark.version}") + dim(f"      {a.rows:,} clicks · {a.partitions} partitions") + "\n")
    print(dim(f"  {'click id':>10} {'user_id':>10}"))
    for r in clicks.limit(5).collect():
        print(f"  {r['id']:>10} {r['user_id']:>10}")
    print(dim(f"  {'…':>10} {'…':>10}"))
    wait()

    # ---------------------------------------------------------------- step 1: exact
    exact, t_exact = timed(lambda: clicks.agg(F.countDistinct("user_id")).first()[0])
    print()
    print(dim(f"  {'':<34}{'distinct':>12}{'time':>9}"))
    print(f"  {'exact   COUNT(DISTINCT user_id)':<34}{exact:>12,}{t_exact:>8.1f}s")
    wait()

    # ---------------------------------------------------------------- step 2: HLL, per partition + merge
    def hll_merged():
        per_part = (clicks.withColumn("partition", F.spark_partition_id())
                    .groupBy("partition").agg(F.hll_sketch_agg("user_id", 12).alias("sketch")))
        return per_part.agg(F.hll_sketch_estimate(F.hll_union_agg("sketch"))).first()[0]
    merged, t_hll = timed(hll_merged)

    parts = (clicks.withColumn("partition", F.spark_partition_id())
             .groupBy("partition")
             .agg(F.count("*").alias("rows"), F.hll_sketch_agg("user_id", 12).alias("sketch"))
             .select("partition", "rows", F.length("sketch").alias("bytes"),
                     F.hll_sketch_estimate("sketch").alias("est"))
             .orderBy("partition").collect())
    one = clicks.agg(F.hll_sketch_estimate(F.hll_sketch_agg("user_id", 12))).first()[0]

    print()
    print(dim(f"  {'partition':>10} {'rows':>12} {'registers':>10} {'sketch':>10} {'distinct (HLL)':>16}"))
    for r in parts:
        print(f"  {r['partition']:>10} {r['rows']:>12,} {2 ** 12:>10,} {r['bytes']:>8,} B {r['est']:>16,}")
    print()
    print(f"  {'merged  hll_union_agg':<34}{merged:>12,}")
    print(f"  {'one sketch, all rows':<34}{one:>12,}   " + green("✓ identical"))
    print()
    err = (merged - exact) / exact
    print(dim(f"  {'':<34}{'distinct':>12}{'time':>9}{'error':>9}"))
    print(f"  {'exact   COUNT(DISTINCT)':<34}{exact:>12,}{t_exact:>8.1f}s")
    print(f"  {'HLL     merged (8 partitions)':<34}{green(f'{merged:>12,}')}{t_hll:>8.1f}s{err:>+9.2%}")
    spark.stop()


def main():
    global PAUSE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=20_000_000)
    ap.add_argument("--users", type=int, default=None, help="user-id universe (default rows/4)")
    ap.add_argument("--partitions", type=int, default=8)
    ap.add_argument("--driver-memory", default="4g")
    ap.add_argument("--pause", action="store_true", help="wait for Enter between steps")
    ap.add_argument("--verbose", action="store_true", help="show Spark/Java log messages")
    a = ap.parse_args()
    PAUSE = a.pause
    print(dim("starting Spark …"), end="\r", flush=True)
    if not a.verbose:
        hide_java_messages()
    try:
        run(a)
    except KeyboardInterrupt:
        print("\n  (stopped)")
    except Exception:
        print("\nSpark failed. Run again with --verbose to see the details.\n")
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)


if __name__ == "__main__":
    main()
