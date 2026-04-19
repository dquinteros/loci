#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/dquinteros/loci"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
PYENV_PYTHON_VERSION=3.10.16

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

# ── find a python 3.10+ interpreter ──────────────────────────────────────────

find_python() {
  for cmd in python3 python python3.10 python3.11 python3.12 python3.13; do
    if command -v "$cmd" &>/dev/null; then
      local major minor
      major=$("$cmd" -c 'import sys; print(sys.version_info.major)')
      minor=$("$cmd" -c 'import sys; print(sys.version_info.minor)')
      if [ "$major" -ge "$MIN_PYTHON_MAJOR" ] && [ "$minor" -ge "$MIN_PYTHON_MINOR" ]; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

check_sqlite_extensions() {
  local py="$1"
  "$py" -c "import sqlite3; sqlite3.connect(':memory:').enable_load_extension(True)" 2>/dev/null
}

# ── build flags for pyenv on macOS (Homebrew SQLite) ─────────────────────────

pyenv_build_env() {
  local env="PYTHON_CONFIGURE_OPTS=--enable-loadable-sqlite-extensions"
  if [[ "$OSTYPE" == darwin* ]] && command -v brew &>/dev/null; then
    brew list sqlite &>/dev/null || brew install sqlite
    local sqlite_prefix
    sqlite_prefix="$(brew --prefix sqlite)"
    env="$env LDFLAGS=-L${sqlite_prefix}/lib CPPFLAGS=-I${sqlite_prefix}/include PKG_CONFIG_PATH=${sqlite_prefix}/lib/pkgconfig"
  fi
  echo "$env"
}

# ── install pyenv + python if needed ─────────────────────────────────────────

install_python_via_pyenv() {
  bold "Python 3.10+ not found — installing via pyenv..."

  if ! command -v pyenv &>/dev/null; then
    bold "Installing pyenv..."
    if [[ "$OSTYPE" == darwin* ]] && command -v brew &>/dev/null; then
      brew install pyenv
    else
      curl -sSL https://pyenv.run | bash
      export PYENV_ROOT="$HOME/.pyenv"
      export PATH="$PYENV_ROOT/bin:$PATH"
      eval "$(pyenv init -)"
    fi
  fi

  bold "Installing Python ${PYENV_PYTHON_VERSION} via pyenv (with SQLite extension support)..."
  eval "$(pyenv_build_env) pyenv install -s ${PYENV_PYTHON_VERSION}"
  pyenv global "$PYENV_PYTHON_VERSION"

  export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
  export PATH="$PYENV_ROOT/shims:$PATH"
}

rebuild_python_via_pyenv() {
  bold "Python lacks SQLite extension support — rebuilding with pyenv..."
  if ! command -v pyenv &>/dev/null; then
    red "ERROR: your Python does not support SQLite loadable extensions."
    red "If using pyenv, reinstall with:"
    red "  $(pyenv_build_env) pyenv install --force ${PYENV_PYTHON_VERSION}"
    exit 1
  fi

  local current_version
  current_version="$(pyenv version-name 2>/dev/null || echo "")"
  local target="${current_version:-$PYENV_PYTHON_VERSION}"

  bold "Rebuilding Python ${target} with Homebrew SQLite..."
  eval "$(pyenv_build_env) pyenv install --force ${target}"

  PYTHON=$(find_python) || {
    red "ERROR: could not find a usable Python after pyenv rebuild."
    exit 1
  }
  if ! check_sqlite_extensions "$PYTHON"; then
    red "ERROR: rebuilt Python still lacks SQLite extension support."
    red "Try: $(pyenv_build_env) pyenv install --force ${target}"
    exit 1
  fi
  green "Rebuilt Python ${target} with SQLite extension support."
}

# ── main ─────────────────────────────────────────────────────────────────────

main() {
  bold "Installing loci..."

  PYTHON=$(find_python || true)

  if [ -z "$PYTHON" ]; then
    install_python_via_pyenv
    PYTHON=$(find_python) || {
      red "ERROR: could not find a usable Python after pyenv install."
      exit 1
    }
  fi

  green "Using Python: $($PYTHON --version)"

  if ! check_sqlite_extensions "$PYTHON"; then
    rebuild_python_via_pyenv
  fi

  bold "Installing loci from GitHub..."
  "$PYTHON" -m pip install --quiet --no-cache-dir --force-reinstall "git+${REPO}.git"

  bold "Registering loci with Claude Code..."
  loci install

  green ""
  green "Done! Restart Claude Code to activate loci."
}

main "$@"
