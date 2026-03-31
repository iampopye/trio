"""trio.ai installer — one command setup.

Usage:
    python install.py          # Install trio
    python install.py --dev    # Install with dev dependencies
"""

import os
import platform
import subprocess  # nosec B404
import sys

_INNER_FLAG = "--_inner"


def _pip_env():
    """Environment variables that fix SSL issues globally for all pip operations."""
    env = os.environ.copy()
    env["PIP_TRUSTED_HOST"] = "pypi.org files.pythonhosted.org"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def main():
    dev_mode = "--dev" in sys.argv
    is_inner = _INNER_FLAG in sys.argv
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not is_inner:
        print()
        print("  trio.ai installer")
        print("  -----------------")
        print()

    # Check Python version
    v = sys.version_info
    if v < (3, 10):
        print(f"  Error: Python 3.10+ required (you have {v.major}.{v.minor})")
        print()
        print("  Install Python 3.12+ from https://python.org/downloads")
        sys.exit(1)

    if not is_inner:
        print(f"  Python {v.major}.{v.minor}.{v.micro}")

    # Find project root
    if not os.path.exists(os.path.join(script_dir, "pyproject.toml")):
        print("  Error: Run this from the trio project root")
        sys.exit(1)

    # Auto-setup isolated environment (transparent to user)
    in_venv = sys.prefix != sys.base_prefix
    venv_dir = os.path.join(script_dir, ".venv")

    if not in_venv:
        if not os.path.isdir(venv_dir):
            print("  Setting up...")
            subprocess.run(  # nosec B603 B607
                [sys.executable, "-m", "venv", venv_dir],
                check=True, capture_output=True,
            )

        # Re-launch inside isolated env
        if platform.system() == "Windows":
            venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            venv_python = os.path.join(venv_dir, "bin", "python")

        if os.path.exists(venv_python):
            args = [a for a in sys.argv[1:] if a != _INNER_FLAG]
            result = subprocess.run(  # nosec B603 B607
                [venv_python, __file__, _INNER_FLAG] + args,
                env=_pip_env(),
            )
            if result.returncode == 0:
                _fix_path_for_venv(venv_dir)
                _print_success()
            sys.exit(result.returncode)
        else:
            print("  Warning: Setup failed, installing globally")

    # Remove conflicting 'trio' async library if present
    _remove_trio_conflict()

    # Install
    print("  Installing trio-ai...")
    extras = ".[all,dev]" if dev_mode else "."

    cmd = [sys.executable, "-m", "pip", "install", "-q", "-e", extras]
    result = subprocess.run(  # nosec B603 B607
        cmd, cwd=script_dir, capture_output=True, text=True, env=_pip_env()
    )

    if result.returncode != 0:
        print("  Error: Installation failed")
        stderr = result.stderr or ""
        lines = stderr.strip().split("\n")
        for line in lines[-5:]:
            print(f"    {line}")
        sys.exit(1)

    print("  Installed!")

    # Verify
    trio_path = _find_trio_command()
    if trio_path:
        print(f"  Command: {trio_path}")

    # Run doctor
    print()
    subprocess.run([sys.executable, "-m", "trio", "doctor"], cwd=script_dir)  # nosec B603 B607

    # Show next steps if user ran directly (not inner re-launch)
    if not is_inner:
        _print_success()


def _remove_trio_conflict():
    """Remove the 'trio' async library if installed — it conflicts with trio.ai."""
    try:
        result = subprocess.run(  # nosec B603 B607
            [sys.executable, "-m", "pip", "show", "trio"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and "trio" in result.stdout:
            # Check it's the async library, not our package
            if "Structured concurrency" in result.stdout or "trio-websocket" in result.stdout:
                subprocess.run(  # nosec B603 B607
                    [sys.executable, "-m", "pip", "uninstall", "-y", "trio", "trio-websocket"],
                    capture_output=True,
                )
    except Exception:
        pass  # nosec B110 — intentional silent fallback


def _print_success():
    """Print final success message."""
    print()
    print("  Done! Next steps:")
    print()
    if platform.system() == "Windows":
        print("  1. Restart your terminal")
        print("  2. Run: trio onboard")
    else:
        print("  Run: trio onboard")
    print()


def _find_trio_command():
    """Find the trio executable."""
    import shutil
    return shutil.which("trio")


def _fix_path_for_venv(venv_dir):
    """Make trio command available globally."""
    if platform.system() == "Windows":
        scripts = os.path.join(venv_dir, "Scripts")
        if os.path.isdir(scripts):
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS
                ) as key:
                    try:
                        current, _ = winreg.QueryValueEx(key, "PATH")
                    except FileNotFoundError:
                        current = ""
                    if scripts.lower() not in current.lower():
                        new_path = scripts + ";" + current if current else scripts
                        winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
            except Exception:
                pass  # nosec B110 — intentional silent fallback
    else:
        from pathlib import Path
        bin_dir = os.path.join(venv_dir, "bin")
        local_bin = Path.home() / ".local" / "bin"
        if local_bin.is_dir():
            trio_src = os.path.join(bin_dir, "trio")
            trio_dst = local_bin / "trio"
            if os.path.exists(trio_src) and not trio_dst.exists():
                try:
                    trio_dst.symlink_to(trio_src)
                except Exception:
                    pass  # nosec B110 — intentional silent fallback


if __name__ == "__main__":
    main()
