<#
.SYNOPSIS
  Stage the Windows runtime payload the desktop installer carries.

.DESCRIPTION
  Produces, under app/desktop/payload/runtime:

    python/            a pinned CPython, copied from uv's standalone build
    site-packages/     the engine's dependencies and pantler_core, resolved at build time
    engine/            the engine source at the pinned commit (git archive, no .git)
    launcher.py        the shim that puts source + deps on sys.path and calls the CLI
    profile-template/  a profile as `profile install` made it, minus user state and the key

  The operator never installs Python, uv, Node or git, and first run does not touch the
  network: the host copies the profile template and starts the bundled interpreter.

  Why a shim and not a venv: a venv's python.exe is a redirector, and Windows refuses it
  when it starts a packaged interpreter (the engine's apps/desktop/BUILDING.md documents the
  same trap). The shim mirrors the POSIX .hermes/bin/hermes launcher instead.

.PARAMETER EngineDir
  The engine checkout at the commit in engine-pin.json. The caller checks the pin.

.PARAMETER RepoRoot
  The pantler checkout. Defaults to this script's parent.

.PARAMETER OutDir
  The payload runtime directory. Defaults to app/desktop/payload/runtime.

.PARAMETER PythonVersion
  The interpreter line to bundle. The engine's dependencies are pinned in its uv.lock.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$EngineDir,
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [string]$OutDir = (Join-Path $PSScriptRoot '..\app\desktop\payload\runtime'),
  [string]$PythonVersion = '3.14'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Step([string]$Message) { Write-Host "`n== $Message" }
function Assert-LastExit([string]$What) {
  if ($LASTEXITCODE -ne 0) { throw "$What failed with exit code $LASTEXITCODE" }
}

$EngineDir = (Resolve-Path -LiteralPath $EngineDir).Path
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path (Join-Path $EngineDir 'pyproject.toml'))) {
  throw "not an engine checkout: $EngineDir"
}
if (-not (Test-Path (Join-Path $RepoRoot 'core\pyproject.toml'))) {
  throw "not the pantler checkout: $RepoRoot"
}

$OutDir = [IO.Path]::GetFullPath($OutDir)
if (Test-Path -LiteralPath $OutDir) { Remove-Item -LiteralPath $OutDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$work = Join-Path ([IO.Path]::GetTempPath()) ("pantler-payload-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $work | Out-Null

try {
  Step 'uv (build-time only; it never reaches the operator)'
  python -m pip install --quiet --disable-pip-version-check uv
  Assert-LastExit 'pip install uv'

  Step "CPython $PythonVersion"
  $env:UV_PYTHON_INSTALL_DIR = Join-Path $work 'python'
  uv python install $PythonVersion --no-bin
  Assert-LastExit 'uv python install'
  $python = ((& uv python find $PythonVersion) | Select-Object -Last 1).Trim()
  if (-not (Test-Path -LiteralPath $python)) { throw "uv produced no interpreter at $python" }
  Copy-Item -LiteralPath (Split-Path -Parent $python) -Destination (Join-Path $OutDir 'python') -Recurse
  $python = Join-Path $OutDir 'python\python.exe'
  if (-not (Test-Path -LiteralPath $python)) { throw "the copied runtime has no python.exe" }

  Step 'the engine and the kernel into one dependency tree'
  $venv = Join-Path $work 'venv'
  uv venv --python $python $venv
  Assert-LastExit 'uv venv'
  $venvPython = Join-Path $venv 'Scripts\python.exe'
  # The lock, not a fresh resolution: resolving the project fresh picks the current
  # browser-harness metadata, whose pillow==12.3.0 pin conflicts with the engine's
  # pillow==13.0.0. `--frozen` uses the engine's own uv.lock, which already encodes the
  # platform markers. The project is installed too, because `profile install` reads its
  # version from the distribution metadata; the launcher still puts the staged source first.
  $env:UV_PROJECT_ENVIRONMENT = $venv
  # The API server imports aiohttp, which the engine ships only in an extra; the base set
  # runs the gateway but cannot open the seam (`AIOHTTP_AVAILABLE` false). `messaging` is the
  # extra that carries it (and the chat-platform deps the phone tier will want); staging every
  # extra instead doubled the installer to 457 MB for providers this product does not ship.
  uv sync --frozen --no-dev --extra messaging --project $EngineDir --python $python
  Assert-LastExit 'engine dependencies'
  Remove-Item Env:\UV_PROJECT_ENVIRONMENT
  uv pip install --python $venvPython (Join-Path $RepoRoot 'core')
  Assert-LastExit 'kernel install'
  # The office plugin's format layer (python-docx, openpyxl, python-pptx and their tree) is staged
  # here so the operator never installs anything. The pinned requirements file is the declaration;
  # the `licences` job in ci.yml scans it alongside the npm closure.
  uv pip install --python $venvPython -r (Join-Path $RepoRoot 'plugins\office\requirements.txt')
  Assert-LastExit 'office libraries'
  Copy-Item -LiteralPath (Join-Path $venv 'Lib\site-packages') -Destination (Join-Path $OutDir 'site-packages') -Recurse

  Step 'the engine source at the pin'
  $engineOut = Join-Path $OutDir 'engine'
  New-Item -ItemType Directory -Path $engineOut | Out-Null
  git -C $EngineDir archive --format=tar HEAD | tar -x -C $engineOut
  Assert-LastExit 'engine archive'

  # The engine reads its own version from an install stamp beside the code (pm/paths.py);
  # without git and without a stamp it says "unknown", and `profile install` then refuses the
  # distribution's `hermes_requires`. This is the stamp a packaged build carries.
  $pin = Get-Content (Join-Path $RepoRoot 'engine-pin.json') -Raw | ConvertFrom-Json
  $stamp = [ordered]@{
    commit          = $pin.commit
    branch          = $null
    baseVersion     = ($pin.tag -replace '^v', '')
    displayVersion  = ($pin.tag -replace '^v', '')
    distance        = 0
    source          = 'build'
    dirty           = $false
    distribution    = 'desktop-app'
    updateMechanism = 'external'
    commitDate      = [int][double]::Parse((Get-Date -UFormat %s))
  }
  [IO.File]::WriteAllText(
    (Join-Path $engineOut 'install-stamp.json'),
    ($stamp | ConvertTo-Json),
    (New-Object System.Text.UTF8Encoding($false))
  )

  Step 'the launcher shim'
  $launcher = @'
"""Start the bundled engine: bundled interpreter, this shim, the source and the deps.

Windows refuses a venv's python.exe when it starts a packaged interpreter, so the payload
never runs one (apps/desktop/BUILDING.md). This is the POSIX launcher's equivalent: put the
engine source and the dependency tree on sys.path and call the CLI entry point.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "engine"), os.path.join(HERE, "site-packages")]

if not os.environ.get("HERMES_HOME"):
    raise SystemExit("HERMES_HOME is not set; the desktop host owns it")

import hermes_bootstrap  # noqa: F401,E402  (Windows UTF-8 stdio and import hardening)
from hermes_cli.main import main  # noqa: E402

raise SystemExit(main())
'@
  $launcherPath = Join-Path $OutDir 'launcher.py'
  [IO.File]::WriteAllText($launcherPath, $launcher, (New-Object System.Text.UTF8Encoding($false)))

  Step 'the profile template'
  $profileHome = Join-Path $work 'home'
  New-Item -ItemType Directory -Force -Path $profileHome | Out-Null
  $env:HERMES_HOME = $profileHome
  & $python -I $launcherPath profile install (Join-Path $RepoRoot 'distribution') --name pantler -y
  Assert-LastExit 'profile install'
  $template = Join-Path $OutDir 'profile-template'
  Copy-Item -LiteralPath (Join-Path $profileHome 'profiles\pantler') -Destination $template -Recurse

  # User state never ships. The key especially: a baked API_SERVER_KEY would be the same on
  # every install, and the host generates the profile's own on first run.
  foreach ($name in @(
      'state.db', 'state.db-wal', 'state.db-shm', 'state.db-journal',
      'records.db', 'sessions', 'logs', 'cron', 'attachments', 'auth.json',
      '.clean_shutdown', '.curator_state', '.curator_ledger.jsonl', '.usage.json')) {
    $target = Join-Path $template $name
    if (Test-Path -LiteralPath $target) {
      Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
    }
  }
  $envFile = Join-Path $template '.env'
  if (Test-Path -LiteralPath $envFile) {
    $kept = Get-Content -LiteralPath $envFile | Where-Object { $_ -notmatch '^\s*API_SERVER_KEY\s*=' }
    [IO.File]::WriteAllLines($envFile, $kept, (New-Object System.Text.UTF8Encoding($false)))
  }

  Write-Host '--- profile template config.yaml (first 40 lines) ---'
  Get-Content -LiteralPath (Join-Path $template 'config.yaml') -TotalCount 40 | ForEach-Object { Write-Host $_ }

  Step 'verify the launcher can import and run the engine'
  & $python -I $launcherPath --version
  Assert-LastExit 'launcher --version'

  Step 'payload size'
  $bytes = (Get-ChildItem -LiteralPath $OutDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
  Write-Host ("pantler payload: {0:N0} MB at {1}" -f ($bytes / 1MB), $OutDir)
}
finally {
  if (Test-Path -LiteralPath $work) {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
  }
}
