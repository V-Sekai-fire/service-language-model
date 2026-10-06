"""Pack/unpack release files with zstd only (no tar).
pack.py [paths...]   default llama-prism -> flat dist/<path with / as __>.zst; files over PART bytes become <path>.zst.000, .001, ...
                     .gguf gets level 1, everything else 19.
pack.py -d [dist]    restore everything under dist/ into the current directory."""
import subprocess, sys
from pathlib import Path

PART = 1_900_000_000
BUF = 1 << 24


def pack(f: Path):
    level = "-1" if f.suffix == ".gguf" else "-19"
    base = Path("dist") / (f.as_posix().replace("/", "__") + ".zst")
    base.parent.mkdir(parents=True, exist_ok=True)
    split = f.stat().st_size > PART
    with f.open("rb") as src:
        i = 0
        while True:
            out = base.with_name(f"{base.name}.{i:03d}") if split else base
            left = PART if split else None
            p = subprocess.Popen(["zstd", level, "-T0", "-q", "-f", "-o", str(out)], stdin=subprocess.PIPE)
            wrote = 0
            while left is None or left > 0:
                data = src.read(BUF if left is None else min(BUF, left))
                if not data:
                    break
                p.stdin.write(data)
                wrote += len(data)
                if left is not None:
                    left -= len(data)
            p.stdin.close()
            if p.wait():
                sys.exit(1)
            print(f"{out} {out.stat().st_size / 1e6:.1f} MB")
            if not split or wrote < PART:
                break
            i += 1


def unpack(root: Path):
    groups = {}
    for p in sorted(root.glob("*")):
        name = p.name
        if name.endswith(".zst"):
            groups.setdefault(p.with_name(name[:-4]), []).append(p)
        elif name[-3:].isdigit() and name[:-3].endswith(".zst."):
            groups.setdefault(p.with_name(name[:-8]), []).append(p)
    for target, parts in groups.items():
        dest = Path(*target.name.split("__"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as o:
            for part in parts:
                subprocess.run(["zstd", "-d", "-q", "-c", str(part)], stdout=o, check=True)
        print(dest)


args = sys.argv[1:]
if args[:1] == ["-d"]:
    unpack(Path(args[1] if len(args) > 1 else "dist"))
else:
    for root in map(Path, args or ["llama-prism"]):
        for f in [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file() and ".cache" not in p.parts):
            pack(f)


