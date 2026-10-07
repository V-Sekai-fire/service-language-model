param(
    [string]$Tag = ("dev." + (Get-Date -Format 'yyyyMMdd.HHmmss')),
    [switch]$SkipPublish
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root
$releaseRoot = Join-Path $root 'release'
$releaseDir = Join-Path $releaseRoot $Tag
$stage = Join-Path $releaseDir 'payload'
$store = Join-Path $releaseDir 'desync-store'
$restore = Join-Path $releaseDir 'restore-check'
$assets = Join-Path $releaseDir 'assets'
$tools = Join-Path $releaseDir 'tools'
$desyncSource = Join-Path $releaseDir 'desync-source'
$desync = Join-Path $tools 'desync.exe'
$build = Join-Path $root 'tray\build'
$volumeLimit = 1900000000

function Set-GitHubReleaseToken {
    if (-not (Get-Command bao -ErrorAction SilentlyContinue)) {
        throw 'OpenBao CLI (bao) is required to publish through the GitHub secrets engine.'
    }

    if (-not $env:BAO_ADDR) {
        $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
        if (-not $tailscale) {
            throw 'Tailscale CLI is required to locate the OpenBao server.'
        }
        $tailnet = & $tailscale.Source status --json | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Could not read Tailscale status.' }
        $peer = @($tailnet.Peer.PSObject.Properties.Value |
            Where-Object { $_.HostName -eq 'weftspun-bao' -and $_.Online } |
            Sort-Object DNSName)[0]
        if (-not $peer -or -not $peer.TailscaleIPs) {
            throw 'No online weftspun-bao OpenBao server is available on Tailscale.'
        }
        $address = @($peer.TailscaleIPs | Where-Object { $_ -match '^\d+\.' })[0]
        if (-not $address) { throw 'The active OpenBao server has no IPv4 Tailscale address.' }
        $env:BAO_ADDR = "https://$address`:8200"
    }

    if (-not $env:BAO_TLS_SERVER_NAME) {
        $env:BAO_TLS_SERVER_NAME = 'weftspun-bao.internal'
    }
    $credentialDirectory = $env:BAO_CREDENTIALS_DIR
    if (-not $credentialDirectory) {
        $credentialDirectory = Join-Path $HOME '.bao-creds-windows-156928'
    }
    if (-not $env:BAO_CACERT) {
        $env:BAO_CACERT = Join-Path $credentialDirectory 'root-ca.pem'
    }
    if (-not $env:BAO_CLIENT_CERT) {
        $env:BAO_CLIENT_CERT = Join-Path $credentialDirectory 'client-fullchain.pem'
    }
    if (-not $env:BAO_CLIENT_KEY) {
        $keys = @(Get-ChildItem -LiteralPath $credentialDirectory -Filter '*-key.pem' -File -ErrorAction SilentlyContinue)
        if ($keys.Count -ne 1) {
            throw "Set BAO_CLIENT_KEY or provide exactly one client *-key.pem in $credentialDirectory."
        }
        $env:BAO_CLIENT_KEY = $keys[0].FullName
    }
    foreach ($path in @($env:BAO_CACERT, $env:BAO_CLIENT_CERT, $env:BAO_CLIENT_KEY)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "OpenBao mTLS credential file is missing: $path"
        }
    }

    $baoToken = & bao login -method=cert -no-store -token-only 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($baoToken -join ''))) {
        throw 'OpenBao certificate authentication failed.'
    }
    $env:BAO_TOKEN = ($baoToken -join '').Trim()
    $response = & bao read -format=json github/token installation_id=160444793 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'OpenBao could not mint a GitHub installation token for V-Sekai-fire.'
    }
    $githubToken = ($response | ConvertFrom-Json).data.token
    if ([string]::IsNullOrWhiteSpace($githubToken)) {
        throw 'OpenBao GitHub engine returned an empty installation token.'
    }
    $env:GH_TOKEN = $githubToken

    & gh api repos/V-Sekai-fire/service-language-model --jq .full_name | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'The OpenBao GitHub installation token cannot access the target repository.'
    }
}

if ($Tag -notmatch '^dev\.[A-Za-z0-9.-]+$') {
    throw "Release tag must begin with dev.: $Tag"
}

if (Test-Path -LiteralPath $releaseDir) {
    throw "Release workspace already exists: $releaseDir. Move it aside before starting a new build."
}

foreach ($task in @('dl-target', 'dl-draft', 'dl-prism')) {
    pixi run $task
    if ($LASTEXITCODE -ne 0) { throw "pixi run $task failed." }
}

pixi run cmake -S tray -B tray/build "-DLM_RELEASE_TAG=$Tag"
if ($LASTEXITCODE -ne 0) { throw 'Configuring the native release targets failed.' }
pixi run cmake --build tray/build --config Release
if ($LASTEXITCODE -ne 0) { throw 'Building the native release targets failed.' }

New-Item -ItemType Directory -Path $releaseDir | Out-Null
New-Item -ItemType Directory -Path $stage, $store, $assets, $tools, $restore | Out-Null

New-Item -ItemType Directory -Path (Join-Path $stage 'models') | Out-Null
foreach ($model in @(
    'Ternary-Bonsai-2-27B-Uncensored-Heretic-v2-PQ2_0.gguf',
    'Qwen3.8-27B-DFlash2-Q4_K_M.gguf'
)) {
    $modelPath = Join-Path $root "models\$model"
    if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
        throw "Required model file is missing: $modelPath"
    }
    Copy-Item -LiteralPath $modelPath -Destination (Join-Path $stage 'models')
}
Copy-Item -LiteralPath (Join-Path $root 'llama-prism') -Destination $stage -Recurse
Copy-Item -LiteralPath (Join-Path $build 'Release\language-model-tray.exe') -Destination $stage
Copy-Item -LiteralPath (Join-Path $root 'tray\resources') -Destination (Join-Path $stage 'resources') -Recurse

git clone --filter=blob:none --no-checkout https://github.com/V-Sekai-fire/multiplayer-fabric-desync.git $desyncSource
if ($LASTEXITCODE -ne 0) { throw 'Cloning the pinned V-Sekai desync source failed.' }
git -C $desyncSource checkout --detach 5140d6b273315da434a69f5bf095e7ba2427bd6e
if ($LASTEXITCODE -ne 0) { throw 'Checking out the pinned V-Sekai desync revision failed.' }
pixi run --manifest-path (Join-Path $root 'pixi.toml') go build -C $desyncSource -o $desync ./cmd/desync
if ($LASTEXITCODE -ne 0) { throw 'Building the pinned V-Sekai desync executable failed.' }

$index = Join-Path $releaseDir 'payload.caidx'
& $desync tar --index --store $store $index $stage
if ($LASTEXITCODE -ne 0) { throw 'Creating the single desync payload index failed.' }

& $desync verify --store $store
if ($LASTEXITCODE -ne 0) { throw 'Desync chunk-store verification failed.' }

& (Join-Path $build 'Release\payload-pack.exe') $store $assets
if ($LASTEXITCODE -ne 0) { throw 'Writing raw desync blob volumes failed.' }

$setup = Join-Path $build 'Release\language-model-setup.exe'
Copy-Item -LiteralPath $setup -Destination (Join-Path $assets 'setup.exe')
Copy-Item -LiteralPath $desync -Destination $assets
Copy-Item -LiteralPath $index -Destination $assets

$assetFiles = Get-ChildItem -LiteralPath $assets -File
foreach ($requiredAsset in @('setup.exe', 'desync.exe', 'payload.caidx')) {
    if (-not ($assetFiles | Where-Object { $_.Name -ceq $requiredAsset })) {
        throw "Required release asset is missing: $requiredAsset"
    }
}
$dataVolumes = @($assetFiles | Where-Object { $_.Name -match '^payload-data-[0-9]{3}\.bin$' } |
    Sort-Object Name)
if ($dataVolumes.Count -eq 0) {
    throw 'The payload packer did not produce any .bin data volumes.'
}
for ($i = 0; $i -lt $dataVolumes.Count; $i++) {
    $expectedName = 'payload-data-{0:D3}.bin' -f $i
    if ($dataVolumes[$i].Name -cne $expectedName) {
        throw 'The payload .bin volume set is incomplete or out of sequence.'
    }
}

$setupProcess = Start-Process -FilePath (Join-Path $assets 'setup.exe') `
    -ArgumentList ('--from "{0}" --target "{1}" --quiet' -f $assets, $restore) -Wait -PassThru
if ($setupProcess.ExitCode -ne 0) {
    throw "Native offline volume extraction or desync restore failed (exit code $($setupProcess.ExitCode))."
}

$expected = @{}
Get-ChildItem -LiteralPath $stage -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($stage.Length + 1)
    $expected[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}
$actual = @{}
Get-ChildItem -LiteralPath $restore -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($restore.Length + 1)
    $actual[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}
if ($expected.Count -ne $actual.Count) {
    throw 'Offline restored file paths or SHA-256 hashes do not match the staged payload.'
}
foreach ($relative in $expected.Keys) {
    if (-not $actual.ContainsKey($relative) -or $actual[$relative] -cne $expected[$relative]) {
        throw "Offline restored payload differs at $relative."
    }
}

$oversized = Get-ChildItem -LiteralPath $assets -File | Where-Object { $_.Length -ge $volumeLimit }
if ($oversized) {
    throw "Release assets must be below $volumeLimit bytes: $($oversized.Name -join ', ')"
}
if ((Get-ChildItem -LiteralPath $assets -File).Count -gt 1000) {
    throw 'A GitHub release cannot contain more than 1000 assets.'
}

foreach ($temporary in @($stage, $store, $restore, $tools, $desyncSource, $index)) {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}

if (-not $SkipPublish) {
    Set-GitHubReleaseToken
    $files = $assetFiles | Select-Object -ExpandProperty FullName
    gh release create $Tag @files --repo V-Sekai-fire/service-language-model --prerelease --title $Tag `
        --notes 'Windows online/offline installer. Run setup.exe with an Internet connection to download this exact dev release, or download every asset beside setup.exe for a fully offline installation. The offline restore uses the single payload.caidx index. Data volumes contain unchanged desync zstd chunks.'
    if ($LASTEXITCODE -ne 0) { throw "Publishing GitHub release $Tag failed." }
}

Write-Host "Release assets are ready at $assets"
if ($SkipPublish) { Write-Host 'Publishing skipped. Run gh release create with the assets above when ready.' }
