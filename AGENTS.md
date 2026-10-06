# Repository guidance

- This repository launches Strata through Pixi; use `pixi run serve` to start it.
- Keep `pixi.toml` and `pixi.lock` in sync when changing dependencies.
- The bundled Strata engine is built for CUDA 12. Keep both platform toolkit
  constraints below CUDA 13 so the engine resolves matching runtime libraries.
- Before serving this IQ2_XS model, create its native expert pack with
  `tools/iq_pack.py`; the native pack uses ggml CPU kernels and avoids the
  AVX-512-only canonical Q2_0 CPU path.
- The IQ2_XS server also needs the Qwen MTP runtime. Keep its fetch, pack, and
  runtime-generation tasks as dependencies of `serve`.
- The supported minimum GPU is an RTX 3090. The launcher defaults to CUDA device
  `0`; additional GPUs, such as an RTX 4090, are optional. Set
  `CUDA_VISIBLE_DEVICES` before `pixi run serve` to select extra devices (for
  example, `0,1`).
- Keep the Windows and Linux `serve` task behavior aligned when changing
  launcher setup.
- Do not rely on edits made directly under the downloaded `Strata-src` tree.
  If an upstream source change is needed, keep it as a tracked patch file and
  apply it from the launcher.
