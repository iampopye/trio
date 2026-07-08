#!/usr/bin/env bash
# trio.ai — macOS / Linux installer
# Usage:  curl -fsSL https://riocloudsolutions.com/trio/install.sh | sh
#         curl -fsSL https://riocloudsolutions.com/trio/install.sh | sh -s -- uninstall

set -euo pipefail

# ── colors ──────────────────────────────────────────────────────────────────

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_MAGENTA=$'\033[35m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_GRAY=$'\033[90m'; C_BLUE=$'\033[34m'
else
  C_RESET=''; C_BOLD=''; C_DIM=''; C_CYAN=''; C_MAGENTA=''; C_GREEN=''
  C_YELLOW=''; C_RED=''; C_GRAY=''; C_BLUE=''
fi

# ── logo ────────────────────────────────────────────────────────────────────

show_logo() {
  echo
  echo "${C_CYAN}  ████████╗██████╗ ██╗ ██████╗   ${C_RESET}"
  echo "${C_CYAN}  ╚══██╔══╝██╔══██╗██║██╔═══██╗  ${C_RESET}"
  echo "${C_MAGENTA}     ██║   ██████╔╝██║██║   ██║  ${C_RESET}"
  echo "${C_MAGENTA}     ██║   ██╔══██╗██║██║   ██║  ${C_RESET}"
  echo "${C_BLUE}     ██║   ██║  ██║██║╚██████╔╝  ${C_RESET}"
  echo "${C_BLUE}     ╚═╝   ╚═╝  ╚═╝╚═╝ ╚═════╝   ${C_RESET}"
  echo "${C_GRAY}         your own AI. own it.    ${C_RESET}"
  echo
}

# ── spinner ─────────────────────────────────────────────────────────────────

SPIN_PID=""
SPIN_MSG=""

start_spin() {
  SPIN_MSG="$1"
  (
    frames='⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏'
    i=0
    while true; do
      f=$(echo "$frames" | cut -d' ' -f$((i % 10 + 1)))
      printf "\r${C_CYAN}%s${C_RESET} %s" "$f" "$SPIN_MSG"
      sleep 0.08
      i=$((i + 1))
    done
  ) &
  SPIN_PID=$!
  disown 2>/dev/null || true
}

stop_spin() {
  local status="${1:-ok}"; local msg="${2:-$SPIN_MSG}"
  if [ -n "$SPIN_PID" ]; then
    kill "$SPIN_PID" 2>/dev/null || true
    wait "$SPIN_PID" 2>/dev/null || true
    SPIN_PID=""
  fi
  printf "\r%80s\r" " "
  case "$status" in
    ok)   printf "${C_GREEN}✓${C_RESET}  %s\n" "$msg" ;;
    warn) printf "${C_YELLOW}!${C_RESET}  %s\n" "$msg" ;;
    *)    printf "${C_RED}✗${C_RESET}  %s\n" "$msg" ;;
  esac
}

# ── platform detection ─────────────────────────────────────────────────────

detect_os() {
  case "$(uname -s)" in
    Darwin*)  echo "macos" ;;
    Linux*)   echo "linux" ;;
    *)        echo "unknown" ;;
  esac
}

# ── python detection / install ─────────────────────────────────────────────

find_python() {
  for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      ver=$("$cmd" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
      major=$(echo "$ver" | cut -d. -f1)
      minor=$(echo "$ver" | cut -d. -f2)
      if [ "$major" = "3" ] && [ "$minor" -ge 10 ] 2>/dev/null; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

install_python_via_uv() {
  start_spin 'Installing uv (Astral Python toolchain)'
  if ! command -v uv >/dev/null 2>&1; then
    curl -fsSL https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    export PATH="$HOME/.local/bin:$PATH"
  fi
  stop_spin 'ok' 'uv installed'

  start_spin 'Installing Python 3.13 via uv'
  uv python install 3.13 >/dev/null 2>&1
  stop_spin 'ok' 'Python 3.13 installed'

  find_python
}

# ── PATH setup ──────────────────────────────────────────────────────────────

add_to_shell_profile() {
  local dir="$1"
  local shell_name; shell_name=$(basename "${SHELL:-/bin/bash}")
  local profile
  case "$shell_name" in
    zsh)  profile="$HOME/.zshrc" ;;
    fish) profile="$HOME/.config/fish/config.fish" ;;
    *)    profile="$HOME/.bashrc" ;;
  esac

  case ":$PATH:" in
    *":$dir:"*) return 0 ;;
  esac

  mkdir -p "$(dirname "$profile")"
  touch "$profile"

  if grep -q "# trio.ai PATH" "$profile" 2>/dev/null; then
    return 0
  fi

  if [ "$shell_name" = "fish" ]; then
    echo "set -gx PATH $dir \$PATH  # trio.ai PATH" >> "$profile"
  else
    echo "export PATH=\"$dir:\$PATH\"  # trio.ai PATH" >> "$profile"
  fi
  export PATH="$dir:$PATH"
}

# ── install ────────────────────────────────────────────────────────────────

install_trio() {
  show_logo
  printf "${C_GRAY}─────────────────────────────────────────────────${C_RESET}\n"
  printf "  ${C_BOLD}Installer for triobot (PyPI: triobot)${C_RESET}\n"
  printf "${C_GRAY}─────────────────────────────────────────────────${C_RESET}\n\n"

  local os; os=$(detect_os)
  start_spin "Detected OS: $os"
  stop_spin 'ok' "OS: $os"

  start_spin 'Checking for Python 3.10+'
  if py=$(find_python); then
    py_ver=$("$py" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    stop_spin 'ok' "Python $py_ver ($(command -v "$py"))"
  else
    stop_spin 'warn' 'Python 3.10+ not found — installing via uv'
    py=$(install_python_via_uv) || { printf "${C_RED}✗${C_RESET}  Could not install Python. Aborting.\n"; exit 2; }
  fi

  start_spin 'Upgrading pip'
  "$py" -m pip install --upgrade pip --quiet --disable-pip-version-check 2>/dev/null || true
  stop_spin 'ok' 'pip is current'

  start_spin 'Installing triobot from PyPI (30-90 sec)'
  if "$py" -m pip install --quiet triobot >/dev/null 2>&1; then
    stop_spin 'ok' 'triobot installed'
  else
    stop_spin 'err' 'pip install failed'
    printf "${C_RED}Try manually: $py -m pip install triobot${C_RESET}\n"
    exit 3
  fi

  ver=$("$py" -c "from importlib.metadata import version; print(version('triobot'))" 2>/dev/null || echo unknown)

  start_spin 'Setting up PATH'
  scripts_dir=$("$py" -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>/dev/null || echo "")
  if [ -n "$scripts_dir" ] && [ -d "$scripts_dir" ]; then
    add_to_shell_profile "$scripts_dir"
    stop_spin 'ok' "PATH updated: $scripts_dir"
  else
    stop_spin 'warn' "Could not auto-set PATH. Add manually: $scripts_dir"
  fi

  echo
  printf "${C_GRAY}─────────────────────────────────────────────────${C_RESET}\n"
  printf "  ${C_GREEN}✓ trio installed successfully (v%s)${C_RESET}\n" "$ver"
  printf "${C_GRAY}─────────────────────────────────────────────────${C_RESET}\n\n"
  printf "  ${C_BOLD}Next steps:${C_RESET}\n\n"
  printf "    ${C_CYAN}triobot${C_RESET}            ${C_GRAY}# interactive model picker + chat${C_RESET}\n"
  printf "    ${C_CYAN}trio agent${C_RESET}         ${C_GRAY}# chat directly${C_RESET}\n"
  printf "    ${C_CYAN}trio serve${C_RESET}         ${C_GRAY}# open the web UI on http://localhost:28337${C_RESET}\n"
  printf "    ${C_CYAN}trio doctor${C_RESET}        ${C_GRAY}# diagnose issues${C_RESET}\n"
  printf "    ${C_CYAN}trio --help${C_RESET}        ${C_GRAY}# full command list${C_RESET}\n\n"
  printf "  ${C_GRAY}If 'trio' command isn't found in a new terminal:${C_RESET}\n"
  printf "  ${C_GRAY}  1. Open a new shell, OR${C_RESET}\n"
  printf "  ${C_GRAY}  2. Run: source ~/.bashrc  (or ~/.zshrc)${C_RESET}\n\n"
}

uninstall_trio() {
  show_logo
  printf "  ${C_YELLOW}Uninstalling triobot...${C_RESET}\n"
  py=$(find_python) || { printf "  ${C_RED}Python not found — nothing to uninstall.${C_RESET}\n"; exit 0; }
  start_spin 'Removing triobot'
  "$py" -m pip uninstall -y triobot >/dev/null 2>&1 || true
  stop_spin 'ok' 'triobot removed'
  printf "  ${C_GRAY}Note: ~/.trio (your configs, sessions, memory) is preserved.${C_RESET}\n"
  printf "  ${C_GRAY}To remove fully: rm -rf ~/.trio${C_RESET}\n"
}

# ── entry ──────────────────────────────────────────────────────────────────

mode="${1:-install}"
case "$mode" in
  install)   install_trio ;;
  reinstall) uninstall_trio; install_trio ;;
  uninstall) uninstall_trio ;;
  *)         printf "${C_RED}Unknown mode '%s'. Use: install | reinstall | uninstall${C_RESET}\n" "$mode"; exit 64 ;;
esac
