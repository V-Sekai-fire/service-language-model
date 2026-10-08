"""Benchmark a running llama-server (started with `pixi run serve`).

Usage: pixi run benchmark [--url URL] [--n-predict N] [--runs N] [--concurrency 1,4]
"""
import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

def _default_port():
    try:
        with open(".port") as f:
            return f.read().strip()
    except OSError:
        return None
    return None
PROMPT = (
    "Write a long, detailed technical essay about how speculative decoding speeds up "
    "large language model inference, covering draft models, verification, acceptance "
    "rates, batching, and KV cache management. Begin now.\n\n"
)


def load_key():
    key = os.environ.get("LLAMA_API_KEY")
    if key or not os.path.exists(".env"):
        return key
    with open(".env") as f:
        for line in f:
            if line.strip().startswith("LLAMA_API_KEY="):
                return line.strip().split("=", 1)[1].strip(" \"'")
    return None


def request(url, key, n_predict, prompt_repeat, slot_seed):
    # A unique prefix per request prevents prompt-cache hits from skewing prefill numbers.
    prompt = f"[{slot_seed}] " + PROMPT * prompt_repeat
    body = json.dumps({
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0,
        "cache_prompt": False,
        "ignore_eos": True,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{url}/completion", data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read().decode())


def run_batch(url, key, concurrency, n_predict, prompt_repeat, tag):
    results = [None] * concurrency
    errors = []

    def worker(i):
        try:
            results[i] = request(url, key, n_predict, prompt_repeat, f"{tag}-{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start
    if errors:
        raise RuntimeError(f"{len(errors)} request(s) failed: {errors[0]}")
    return results, wall


def summarize(results, wall):
    timings = [r.get("timings", {}) for r in results]
    generated = sum(t.get("predicted_n", 0) for t in timings)
    prompt_tokens = sum(t.get("prompt_n", 0) for t in timings)
    row = {
        "agg_tg": generated / wall if wall else 0.0,
        "per_req_tg": statistics.mean(t.get("predicted_per_second", 0.0) for t in timings),
        "per_req_pp": statistics.mean(t.get("prompt_per_second", 0.0) for t in timings),
        "prompt_tokens": prompt_tokens,
        "generated": generated,
        "wall": wall,
    }
    drafted = sum(t.get("draft_n", 0) for t in timings)
    accepted = sum(t.get("draft_n_accepted", 0) for t in timings)
    row["accept"] = accepted / drafted if drafted else None
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    default_url = ("http://127.0.0.1:" + _default_port() if _default_port()
                   else "http://127.0.0.1:9931")
    p.add_argument("--url", default=default_url)
    p.add_argument("--n-predict", type=int, default=256, help="tokens generated per request")
    p.add_argument("--prompt-repeat", type=int, default=40, help="prompt length multiplier (~45 tokens each)")
    p.add_argument("--runs", type=int, default=3, help="measured runs per concurrency level")
    p.add_argument("--concurrency", default="1,4", help="comma-separated parallel request counts")
    args = p.parse_args()
    levels = [int(c) for c in args.concurrency.split(",")]
    key = load_key()

    try:
        req = urllib.request.Request(f"{args.url}/health")
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError:
        pass  # /health may require auth or report loading; the first request will say more
    except Exception as e:
        print(f"Server not reachable at {args.url} ({e}). Start it with `pixi run serve` first.")
        return 1

    print(f"Warming up against {args.url} ...")
    run_batch(args.url, key, 1, 16, 1, "warmup")

    header = f"{'conc':>4} {'pp t/s':>9} {'tg t/s/req':>11} {'tg t/s total':>13} {'accept':>7} {'wall s':>7}"
    print(header)
    print("-" * len(header))
    for c in levels:
        rows = []
        for run in range(args.runs):
            results, wall = run_batch(args.url, key, c, args.n_predict, args.prompt_repeat, f"c{c}r{run}")
            rows.append(summarize(results, wall))
        accepts = [r["accept"] for r in rows if r["accept"] is not None]
        accept = f"{statistics.mean(accepts) * 100:6.1f}%" if accepts else "    n/a"
        print(
            f"{c:>4} {statistics.median(r['per_req_pp'] for r in rows):>9.1f} "
            f"{statistics.median(r['per_req_tg'] for r in rows):>11.1f} "
            f"{statistics.median(r['agg_tg'] for r in rows):>13.1f} "
            f"{accept:>7} {statistics.median(r['wall'] for r in rows):>7.1f}"
        )
    print(f"\nMedian of {args.runs} run(s); {args.n_predict} tokens/request, "
          f"~{args.prompt_repeat * 45} prompt tokens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
