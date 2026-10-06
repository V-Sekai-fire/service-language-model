"""PQ2_0 weights on MLX without converting them, the way the CUDA backend does it.

The GGUF's raw 34-byte blocks (fp16 scale + 128 two-bit codes, value = (code - 1) * scale) are memory-mapped
and handed to Metal untouched. Small batches use a fused decode + dot kernel (CUDA's mmvq path); batches of
DEQUANT_MIN_ROWS or more decode to fp16 once and use a regular matmul (CUDA's dequantize + cuBLAS path).

python pq2_mlx.py <model.gguf>    check both paths against a numpy reference on a real tensor
"""
import struct
import sys
from dataclasses import dataclass

import mlx.core as mx
import numpy as np

QK = 128
BLOCK_BYTES = 34
GGML_TYPE_PQ2_0 = 142
DEQUANT_MIN_ROWS = 128

_SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


@dataclass
class Tensor:
    name: str
    shape: tuple  # (rows, cols) as in the model: cols is the contiguous, quantized axis
    type: int
    offset: int


class _Reader:
    def __init__(self, f):
        self.f = f

    def read(self, fmt):
        return struct.unpack("<" + fmt, self.f.read(struct.calcsize("<" + fmt)))[0]

    def string(self):
        return self.f.read(self.read("Q")).decode("utf-8", "replace")

    def value(self, t):
        if t == 8:
            return self.string()
        if t == 9:
            et, n = self.read("I"), self.read("Q")
            return [self.value(et) for _ in range(n)]
        return self.read(_SCALARS[t])


def open_gguf(path):
    """Returns (tensors by name, memory-mapped uint8 view of the data section)."""
    with open(path, "rb") as f:
        r = _Reader(f)
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        version = r.read("I")
        if version < 2:
            raise ValueError(f"GGUF v{version} is not supported")
        n_tensors, n_kv = r.read("Q"), r.read("Q")
        alignment = 32
        for _ in range(n_kv):
            key, t = r.string(), r.read("I")
            v = r.value(t)
            if key == "general.alignment":
                alignment = v
        tensors = {}
        for _ in range(n_tensors):
            name = r.string()
            dims = tuple(r.read("Q") for _ in range(r.read("I")))
            ty, off = r.read("I"), r.read("Q")
            tensors[name] = Tensor(name, dims[::-1], ty, off)
        start = (f.tell() + alignment - 1) // alignment * alignment
    return tensors, np.memmap(path, dtype=np.uint8, mode="r", offset=start)


def raw_blocks(tensors, data, name):
    """The tensor's blocks as a [rows, cols / 128, 34] uint8 array, still in ggml's layout."""
    t = tensors[name]
    if t.type != GGML_TYPE_PQ2_0:
        raise ValueError(f"{name} is type {t.type}, not PQ2_0")
    rows, cols = t.shape
    if cols % QK:
        raise ValueError(f"{name}: {cols} columns is not a multiple of {QK}")
    n = rows * cols // QK * BLOCK_BYTES
    return mx.array(np.asarray(data[t.offset : t.offset + n]).reshape(rows, cols // QK, BLOCK_BYTES))


# Two simdgroups per threadgroup, one output row each. 4 lanes share a block (32 codes = 4 ushort loads each),
# so the 32 lanes read 8 blocks per step. The scale is applied once per lane-block after the integer-valued sum.
_MATVEC = mx.fast.metal_kernel(
    name="pq2_0_matvec",
    input_names=["w", "x"],
    output_names=["y"],
    header="#include <metal_stdlib>\nusing namespace metal;\n",
    source="""
        uint sg = thread_position_in_grid.x / 32;
        uint lane = thread_position_in_grid.x % 32;
        uint row = sg;
        uint m = thread_position_in_grid.y;
        if (row >= N) return;
        uint nb = K / 128;
        uint sub = lane % 4;
        const device uint8_t* wr = w + (ulong)row * nb * 34;
        const device T* xr = x + (ulong)m * K;
        float acc = 0.0f;
        for (uint b = lane / 4; b < nb; b += 8) {
            const device uint8_t* blk = wr + (ulong)b * 34;
            float d = float(as_type<half>(ushort(blk[0] | (blk[1] << 8))));
            const device ushort* qp = (const device ushort*)(blk + 2) + sub * 4;
            const device vec<T, 4>* xb = (const device vec<T, 4>*)(xr + b * 128 + sub * 32);
            float s = 0.0f;
            for (uint j = 0; j < 4; ++j) {
                uint q = qp[j];
                for (uint i = 0; i < 2; ++i) {
                    float4 xv = float4(xb[j * 2 + i]);
                    float4 c = float4((q >> (8 * i)) & 3u, (q >> (8 * i + 2)) & 3u,
                                      (q >> (8 * i + 4)) & 3u, (q >> (8 * i + 6)) & 3u) - 1.0f;
                    s += dot(c, xv);
                }
            }
            acc += d * s;
        }
        acc = simd_sum(acc);
        if (lane == 0) y[(ulong)m * N + row] = T(acc);
    """,
)

_DEQUANT = mx.fast.metal_kernel(
    name="pq2_0_dequant",
    input_names=["w"],
    output_names=["out"],
    header="#include <metal_stdlib>\nusing namespace metal;\n",
    source="""
        uint idx = thread_position_in_grid.x;
        uint b = idx / 128;
        uint j = idx % 128;
        const device uint8_t* blk = w + (ulong)b * 34;
        float d = float(as_type<half>(ushort(blk[0] | (blk[1] << 8))));
        uint q = (blk[2 + j / 4] >> ((j % 4) * 2)) & 3u;
        out[idx] = half((float(q) - 1.0f) * d);
    """,
)


def dequantize(blocks):
    """fp16 [rows, cols] from raw blocks."""
    rows, nb, _ = blocks.shape
    (out,) = _DEQUANT(
        inputs=[blocks],
        output_shapes=[(rows * nb * QK,)],
        output_dtypes=[mx.float16],
        grid=(rows * nb * QK, 1, 1),
        threadgroup=(256, 1, 1),
    )
    return out.reshape(rows, nb * QK)


def matvec(blocks, x):
    """x [M, K] @ W.T for raw blocks W [N, K / 128, 34], decoded inside the kernel."""
    n, nb, _ = blocks.shape
    m, k = x.shape
    (y,) = _MATVEC(
        inputs=[blocks, x],
        template=[("T", x.dtype), ("K", k), ("N", n)],
        output_shapes=[(m, n)],
        output_dtypes=[x.dtype],
        grid=(n * 32, m, 1),
        threadgroup=(64, 1, 1),
    )
    return y


class PQ2Linear:
    """y = x @ W.T with W kept as raw PQ2_0 blocks."""

    def __init__(self, blocks):
        self.blocks = blocks

    def __call__(self, x):
        shape = x.shape
        x2 = x.reshape(-1, shape[-1])
        if x2.shape[0] >= DEQUANT_MIN_ROWS:
            y = x2 @ dequantize(self.blocks).astype(x2.dtype).T
        else:
            y = matvec(self.blocks, x2)
        return y.reshape(*shape[:-1], -1)


def reference(blocks_np, x_np):
    """float32 numpy decode of the same blocks, following ggml's dequantize_row_pq2_0."""
    rows, nb, _ = blocks_np.shape
    d = blocks_np[:, :, :2].copy().view(np.float16).astype(np.float32).reshape(rows, nb, 1)
    q = blocks_np[:, :, 2:]
    codes = np.stack([(q >> s) & 3 for s in (0, 2, 4, 6)], axis=-1).reshape(rows, nb, QK)
    w = ((codes.astype(np.float32) - 1.0) * d).reshape(rows, nb * QK)
    return x_np.astype(np.float32) @ w.T


def _check(path):
    tensors, data = open_gguf(path)
    names = [n for n, t in tensors.items() if t.type == GGML_TYPE_PQ2_0]
    if not names:
        sys.exit("no PQ2_0 tensors in this file")
    print(f"{len(names)} PQ2_0 tensors")
    rng = np.random.default_rng(0)
    for name in [names[0], names[len(names) // 2], names[-1]]:
        blocks = raw_blocks(tensors, data, name)
        rows, cols = tensors[name].shape
        # Row subset keeps the numpy reference quick; the kernels see the same bytes either way.
        blocks = blocks[: min(rows, 512)]
        linear = PQ2Linear(blocks)
        for m in (1, 4, DEQUANT_MIN_ROWS + 5):
            x_np = rng.standard_normal((m, cols)).astype(np.float16)
            got = np.array(linear(mx.array(x_np))).astype(np.float32)
            want = reference(np.array(blocks), x_np)
            err = np.abs(got - want).max() / (np.abs(want).max() + 1e-9)
            print(f"{name} {blocks.shape[0]}x{cols} M={m}: max rel err {err:.2e}")
            if err > 2e-2:
                sys.exit("MISMATCH")
    print("ok")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    _check(sys.argv[1])
