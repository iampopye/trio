# trio.ai — Windows PowerShell installer
# Usage:  irm https://riocloudsolutions.com/trio/install.ps1 | iex
#
# Inspired by pi.dev's installer pattern. Adds:
#   - Python 3.10+ detection (auto-installs uv + Python if missing)
#   - Animated trio logo + spinner
#   - HKCU:Environment PATH registration with broadcast
#   - SSL fix (pip-system-certs) for corporate networks
#   - Install / Reinstall / Uninstall modes
#   - Post-install handoff to `triobot` interactive picker

#Requires -Version 5.1

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ── ANSI + color setup ───────────────────────────────────────────────────────

$Esc = [char]27
$Ansi = @{
    Reset   = "$Esc[0m"
    Bold    = "$Esc[1m"
    Dim     = "$Esc[2m"
    Cyan    = "$Esc[36m"
    Magenta = "$Esc[35m"
    Green   = "$Esc[32m"
    Yellow  = "$Esc[33m"
    Red     = "$Esc[31m"
    Gray    = "$Esc[90m"
    Blue    = "$Esc[34m"
}

if (-not ($Host.UI.RawUI.ForegroundColor)) { $Ansi.Keys | ForEach-Object { $Ansi[$_] = '' } }

function W($Text, $Color = 'Reset') { Write-Host "$($Ansi[$Color])$Text$($Ansi.Reset)" }
function WInline($Text, $Color = 'Reset') { Write-Host -NoNewline "$($Ansi[$Color])$Text$($Ansi.Reset)" }

# ── Logo ─────────────────────────────────────────────────────────────────────

function Show-Logo {
    Write-Host ""
    W "  ████████╗██████╗ ██╗ ██████╗   " "Cyan"
    W "  ╚══██╔══╝██╔══██╗██║██╔═══██╗  " "Cyan"
    W "     ██║   ██████╔╝██║██║   ██║  " "Magenta"
    W "     ██║   ██╔══██╗██║██║   ██║  " "Magenta"
    W "     ██║   ██║  ██║██║╚██████╔╝  " "Blue"
    W "     ╚═╝   ╚═╝  ╚═╝╚═╝ ╚═════╝   " "Blue"
    W "         your own AI. own it.    " "Gray"
    Write-Host ""
}

# ── Spinner ──────────────────────────────────────────────────────────────────

$script:SpinnerJob = $null

function Start-Spin($Message) {
    $script:SpinnerMessage = $Message
    $frames = @('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
    $script:SpinnerStopFile = [IO.Path]::GetTempFileName()
    $script:SpinnerJob = Start-Job -ArgumentList $Message, $frames, $script:SpinnerStopFile -ScriptBlock {
        param($msg, $frames, $stop)
        $i = 0
        while (-not (Test-Path $stop) -or (Get-Item $stop).Length -eq 0) {
            Write-Host -NoNewline "`r$([char]27)[36m$($frames[$i % $frames.Length])$([char]27)[0m $msg"
            Start-Sleep -Milliseconds 80
            $i++
        }
    }
}

function Stop-Spin($Status = 'ok', $Message = $null) {
    if (-not $script:SpinnerJob) { return }
    Set-Content -Path $script:SpinnerStopFile -Value 'stop'
    Wait-Job $script:SpinnerJob | Out-Null
    Remove-Job $script:SpinnerJob | Out-Null
    Remove-Item $script:SpinnerStopFile -ErrorAction SilentlyContinue
    Write-Host -NoNewline "`r"
    Write-Host -NoNewline (' ' * 80)
    Write-Host -NoNewline "`r"
    $icon = if ($Status -eq 'ok') { "$($Ansi.Green)✓$($Ansi.Reset)" } elseif ($Status -eq 'warn') { "$($Ansi.Yellow)!$($Ansi.Reset)" } else { "$($Ansi.Red)✗$($Ansi.Reset)" }
    $msg = if ($Message) { $Message } else { $script:SpinnerMessage }
    Write-Host "$icon  $msg"
    $script:SpinnerJob = $null
}

# ── PATH management ──────────────────────────────────────────────────────────

function Add-ToUserPath($Dir) {
    if (-not (Test-Path $Dir)) { return }
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $current) { $current = '' }
    $entries = $current -split ';' | Where-Object { $_ -ne '' }
    if ($entries -notcontains $Dir) {
        $newPath = ($entries + $Dir) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        $env:Path += ";$Dir"
        Broadcast-EnvChange
    }
}

function Broadcast-EnvChange {
    if (-not ('NativeMethods' -as [type])) {
        Add-Type -Namespace Native -Name NativeMethods -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError=true, CharSet=System.Runtime.InteropServices.CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, int Msg, IntPtr wParam, string lParam, int fuFlags, int uTimeout, out IntPtr lpdwResult);
'@
    }
    $HWND_BROADCAST = [IntPtr]0xffff
    $WM_SETTINGCHANGE = 0x1A
    $out = [IntPtr]::Zero
    [Native.NativeMethods]::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [IntPtr]::Zero, 'Environment', 2, 5000, [ref]$out) | Out-Null
}

# ── Python detection / install ───────────────────────────────────────────────

function Get-WorkingPython {
    foreach ($cmd in @('python', 'python3', 'py')) {
        try {
            $version = & $cmd --version 2>&1 | Out-String
            if ($version -match 'Python\s+(\d+)\.(\d+)') {
                $major = [int]$Matches[1]; $minor = [int]$Matches[2]
                if ($major -eq 3 -and $minor -ge 10) {
                    $path = (Get-Command $cmd -ErrorAction SilentlyContinue).Source
                    return [pscustomobject]@{ Cmd = $cmd; Path = $path; Version = "$major.$minor" }
                }
            }
        } catch {}
    }
    return $null
}

function Install-PythonViaUv {
    # uv = Astral's single-binary Python installer (much smaller than full Python.org bundle)
    W "  Installing Python via uv..." 'Gray'
    Start-Spin 'Downloading uv (Astral toolchain)'
    $uvDir = "$env:LOCALAPPDATA\trio\uv"
    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" 2>&1 | Out-Null
        Stop-Spin 'ok' 'uv installed'
    } catch {
        Stop-Spin 'err' 'uv install failed'
        throw "Could not install uv. Please install Python 3.10+ manually from https://www.python.org/downloads/ then re-run this installer."
    }
    Start-Spin 'Installing Python 3.13 via uv'
    & "$env:USERPROFILE\.local\bin\uv.exe" python install 3.13 2>&1 | Out-Null
    Stop-Spin 'ok' 'Python 3.13 installed'
    return Get-WorkingPython
}

# ── Pre-flight ───────────────────────────────────────────────────────────────

function Check-DiskSpace($MinGB = 2) {
    $drive = Get-PSDrive C
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt $MinGB) {
        throw "Not enough disk space on C: drive. Need ${MinGB}GB, have ${freeGB}GB."
    }
}

function Check-Network {
    try {
        $r = Invoke-WebRequest -Uri 'https://pypi.org' -UseBasicParsing -TimeoutSec 5
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# ── Install / Reinstall / Uninstall ──────────────────────────────────────────

function Install-Trio {
    Show-Logo
    W "─────────────────────────────────────────────────" 'Gray'
    W "  Installer for triobot (PyPI: triobot)" 'Bold'
    W "─────────────────────────────────────────────────" 'Gray'
    Write-Host ""

    # 1. Pre-flight
    Start-Spin 'Checking disk space'
    try { Check-DiskSpace -MinGB 2; Stop-Spin 'ok' 'Disk OK (≥2 GB on C:)' } catch { Stop-Spin 'err' $_.Exception.Message; throw }

    Start-Spin 'Checking network'
    if (Check-Network) { Stop-Spin 'ok' 'Network OK (pypi.org reachable)' } else { Stop-Spin 'warn' 'pypi.org not reachable — install may fail behind proxy' }

    # 2. Python
    Start-Spin 'Checking for Python 3.10+'
    $py = Get-WorkingPython
    if ($py) { Stop-Spin 'ok' "Python $($py.Version) at $($py.Path)" } else { Stop-Spin 'warn' 'Python 3.10+ not found — installing via uv'; $py = Install-PythonViaUv }
    if (-not $py) { throw 'Could not find or install Python 3.10+. Aborting.' }

    # 3. pip upgrade
    Start-Spin 'Upgrading pip'
    & $py.Cmd -m pip install --upgrade pip --quiet --disable-pip-version-check 2>&1 | Out-Null
    Stop-Spin 'ok' 'pip is current'

    # 4. SSL fix (Windows often blocks pypi.org TLS)
    Start-Spin 'Installing SSL helper (pip-system-certs)'
    & $py.Cmd -m pip install --quiet pip-system-certs 2>&1 | Out-Null
    Stop-Spin 'ok' 'SSL helper installed (uses Windows cert store)'

    # 5. Install triobot
    Start-Spin 'Installing triobot from PyPI (may take 30-90 sec)'
    & $py.Cmd -m pip install --quiet triobot 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Spin 'err' 'pip install failed'; throw 'triobot install failed. Try: python -m pip install triobot' }
    Stop-Spin 'ok' 'triobot installed'

    # 6. Get install version
    $ver = & $py.Cmd -c "import triobot, sys; print(getattr(triobot, '__version__', 'unknown'))" 2>$null
    if (-not $ver) {
        $ver = & $py.Cmd -c "from importlib.metadata import version; print(version('triobot'))" 2>$null
    }

    # 7. PATH setup
    Start-Spin 'Setting up PATH'
    $scriptsDir = & $py.Cmd -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>$null
    if ($scriptsDir -and (Test-Path $scriptsDir)) {
        Add-ToUserPath $scriptsDir
        Stop-Spin 'ok' "PATH updated: $scriptsDir"
    } else {
        Stop-Spin 'warn' "Could not auto-set PATH. Add manually: $scriptsDir"
    }

    # 8. Done
    Write-Host ""
    W "─────────────────────────────────────────────────" 'Gray'
    W "  ✓ trio installed successfully (v$ver)" 'Green'
    W "─────────────────────────────────────────────────" 'Gray'
    Write-Host ""
    W "  Next steps:" 'Bold'
    Write-Host ""
    WInline "    " 'Reset'; WInline 'triobot' 'Cyan'; W '            # interactive model picker + chat' 'Gray'
    WInline "    " 'Reset'; WInline 'trio agent' 'Cyan'; W '         # chat directly' 'Gray'
    WInline "    " 'Reset'; WInline 'trio serve' 'Cyan'; W '         # open the web UI on http://localhost:28337' 'Gray'
    WInline "    " 'Reset'; WInline 'trio doctor' 'Cyan'; W '        # diagnose issues' 'Gray'
    WInline "    " 'Reset'; WInline 'trio --help' 'Cyan'; W '        # full command list' 'Gray'
    Write-Host ""
    W "  If 'trio' command isn't found in a new terminal:" 'Gray'
    W "    1. Close and reopen your shell" 'Gray'
    W "    2. Or run: refreshenv (if you have chocolatey)" 'Gray'
    Write-Host ""
}

function Uninstall-Trio {
    Show-Logo
    W "  Uninstalling triobot..." 'Yellow'
    $py = Get-WorkingPython
    if (-not $py) { W "  Python not found — nothing to uninstall." 'Red'; return }
    Start-Spin 'Removing triobot'
    & $py.Cmd -m pip uninstall -y triobot 2>&1 | Out-Null
    Stop-Spin 'ok' 'triobot removed'
    W "  Note: ~/.trio (your configs, sessions, memory) is preserved." 'Gray'
    W "  To remove fully: Remove-Item -Recurse `$env:USERPROFILE\.trio" 'Gray'
}

# ── Entry ────────────────────────────────────────────────────────────────────

$mode = if ($args.Count -gt 0) { $args[0] } else { 'install' }

switch ($mode.ToLower()) {
    'install'   { Install-Trio }
    'reinstall' { Uninstall-Trio; Install-Trio }
    'uninstall' { Uninstall-Trio }
    default     { W "Unknown mode '$mode'. Use: install | reinstall | uninstall" 'Red'; exit 64 }
}
