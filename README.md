# Service language model

## Windows online/offline release

On a Windows x64 build machine with Visual Studio 2022 C++ build tools, Pixi, network access for the initial model/tool downloads, Tailscale access to OpenBao, and the OpenBao mTLS credential bundle, run:

```powershell
.\release.ps1
```

This builds a prerelease tagged `dev.<timestamp>`. To build and verify locally without publishing:

```powershell
.\release.ps1 -SkipPublish
```

The release has one `payload.caidx` index covering the staged Windows binaries, runtime DLLs, icons, and model files. Desync creates the local content-addressed store. Its chunk objects are already zstd blobs, so the native volume packer copies their bytes unchanged into a small set of large `.bin` data volumes with only path/length framing; it does not recompress, ZIP, or tar them.

`setup.exe` supports both delivery paths:

- **Online:** Download only `setup.exe` and run it while connected to the Internet. If the release assets are not beside it, setup asks to download the matching `dev.*` release from GitHub. Use `setup.exe --online` to start the download directly.
- **Offline:** Download all release assets into one directory, then run `setup.exe` there. Setup uses only the adjacent files; `setup.exe --offline` disables the online fallback.

Both paths use the release's single `payload.caidx` index. Setup reconstructs and verifies the desync store from the raw volumes before restoring the files. Setup requests administrator access and installs the shared application under `%ProgramData%\V-Sekai\ServiceLanguageModel`. It registers the tray to start at sign-in for the installing user. API keys, logs, and model slot state are kept separately under `%LOCALAPPDATA%\V-Sekai\ServiceLanguageModel`, so the shared ProgramData installation remains usable by standard users.

Uninstall with `setup.exe --uninstall` (administrator access required). Close the tray first; uninstall removes the current user's sign-in entry and deletes the shared application directory.

The release command uses the OpenBao GitHub secrets engine to mint a short-lived installation token, embeds its validated `dev.*` tag in setup, verifies a local desync restore against the staged file SHA-256 hashes before publishing, and rejects assets at or above 1,900,000,000 bytes. Set `BAO_CREDENTIALS_DIR` if the mTLS bundle is not in its default user-profile directory; local `BAO_*` connection settings can also be supplied when needed. Local artifacts are written under `release\<tag>\assets`. The installed computer needs neither Python, Pixi, Go, nor tar. Offline installation needs no network; online installation downloads the release assets over HTTPS.

The portable `language-model-install` target uses the same desync index and `.bin` volume format. Use `language-model-install --from <asset-folder>` for an offline install, or `language-model-install --online --tag dev.<version>` to download that GitHub release. It restores into the current directory unless `--target <folder>` is provided. The asset set must contain a desync executable built for the target platform, the single `payload.caidx` index, and all consecutively numbered `payload-data-*.bin` volumes.
