"""Compress release files one by one with zstd (no tar): dist/<path>.zst.
Usage: pack.py [paths...]  (default: llama-prism). .gguf gets level 1, everything else 19."""
import subprocess, sys
from pathlib import Path

for root in map(Path, sys.argv[1:] or ["llama-prism"]):
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    for f in files:
        out = Path("dist") / (str(f) + ".zst")
        out.parent.mkdir(parents=True, exist_ok=True)
        level = "-1" if f.suffix == ".gguf" else "-19"
        subprocess.run(["zstd", level, "-T0", "-q", "-f", str(f), "-o", str(out)], check=True)
        print(f"{out} {out.stat().st_size / 1e6:.1f} MB")
