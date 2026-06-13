#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SignalPilot installer
#
# Usage:
#   bash install.sh            — install into a fresh .venv/ (recommended)
#   bash install.sh --dev      — also install dev/test dependencies
#   bash install.sh --no-venv  — install into whatever Python is active now
#
# Requires: Python 3.12+, pip or uv
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
IFS=$'\n\t'

# ── colours ──────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED='\033[0;31m' YELLOW='\033[1;33m' GREEN='\033[0;32m' CYAN='\033[0;36m'
  RESET='\033[0m'  BOLD='\033[1m'
else
  RED='' YELLOW='' GREEN='' CYAN='' RESET='' BOLD=''
fi

info() { echo -e "${CYAN}▸${RESET} $*"; }
ok()   { echo -e "${GREEN}✔${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()  {
  echo -e "\n${RED}${BOLD}✖  ERROR:${RESET} $1" >&2
  [[ -n "${2:-}" ]] && echo -e "   ${YELLOW}→ FIX:${RESET} $2" >&2
  exit 1
}
step() { echo -e "\n${BOLD}$1${RESET}"; }

# ── parse args ────────────────────────────────────────────────────────────────
DEV=false; USE_VENV=true
for arg in "$@"; do
  [[ "$arg" == "--dev" ]]     && DEV=true
  [[ "$arg" == "--no-venv" ]] && USE_VENV=false
done

echo ""
echo -e "${BOLD}⚡  PerfSage SignalPilot — installer${RESET}"
echo "────────────────────────────────────────────────────────────────"

# ── 1. Find Python 3.12+ ─────────────────────────────────────────────────────
step "1/4  Checking Python version"

PYTHON=""
for candidate in python3.12 python3.13 python3.14 python3 python; do
  command -v "$candidate" &>/dev/null || continue
  py_ver=$("$candidate" -c \
    "import sys; print(sys.version_info.major*100+sys.version_info.minor)" \
    2>/dev/null) || continue
  if [[ "$py_ver" -ge 312 ]]; then
    PYTHON="$candidate"
    human_ver=$("$candidate" -c \
      "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')")
    ok "Python $human_ver  ($PYTHON)"
    break
  fi
done

[[ -z "$PYTHON" ]] && die \
  "Python 3.12 or newer is required but was not found on PATH." \
  "Install it, then rerun this script:
         macOS  : brew install python@3.12    # https://brew.sh
         Ubuntu : sudo apt install python3.12
         Windows: winget install Python.Python.3.12
         Manual : https://python.org/downloads/"

# ── 2. Create / activate virtual environment ─────────────────────────────────
step "2/4  Setting up virtual environment"

VENV_DIR=".venv"

if $USE_VENV; then
  # If there's already an active venv that matches, skip creation
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    ok "Already inside a virtual environment: $VIRTUAL_ENV"
    PYTHON="python"
  else
    # Prefer uv (faster) if available, fall back to venv
    if command -v uv &>/dev/null; then
      if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating virtual environment with uv…"
        uv venv "$VENV_DIR" --python "$PYTHON" --quiet || \
          die "uv venv creation failed." "Try: rm -rf $VENV_DIR && bash install.sh"
        ok "Virtual environment created ($VENV_DIR/)"
      else
        ok "Reusing $VENV_DIR/"
      fi
      # shellcheck disable=SC1091
      source "$VENV_DIR/bin/activate" 2>/dev/null || \
        source "$VENV_DIR/Scripts/activate" 2>/dev/null || \
        die "Could not activate $VENV_DIR." "Try: rm -rf $VENV_DIR && bash install.sh"
      PYTHON="python"
    else
      if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating virtual environment…"
        "$PYTHON" -m venv "$VENV_DIR" || \
          die "venv creation failed." \
              "Try: $PYTHON -m pip install virtualenv && $PYTHON -m virtualenv $VENV_DIR"
        ok "Virtual environment created ($VENV_DIR/)"
      else
        ok "Reusing $VENV_DIR/"
      fi
      # shellcheck disable=SC1091
      source "$VENV_DIR/bin/activate" 2>/dev/null || \
        source "$VENV_DIR/Scripts/activate" 2>/dev/null || \
        die "Could not activate $VENV_DIR." "Try: rm -rf $VENV_DIR && bash install.sh"
      PYTHON="python"
    fi
  fi
else
  ok "Skipping venv creation (--no-venv). Using: $($PYTHON -c 'import sys; print(sys.executable)')"
fi

# ── 3. Upgrade pip, then install ─────────────────────────────────────────────
step "3/4  Installing SignalPilot"

EXTRAS=""; $DEV && EXTRAS="[dev]"

# uv-managed envs can use `uv pip install` directly (faster, no pip needed)
if [[ -n "${VIRTUAL_ENV:-}" ]] && command -v uv &>/dev/null; then
  info "Using uv for faster install…"
  uv pip install --upgrade pip --quiet 2>/dev/null || true   # best-effort
  uv pip install -e ".${EXTRAS}" --quiet || \
    die "uv pip install failed." \
        "Check the output above, then rerun: bash install.sh${DEV:+ --dev}"
else
  # Ensure pip is modern enough to handle pyproject.toml editable installs
  # (pip < 21.3 predates PEP 660 and will fail with the error you saw)
  info "Upgrading pip to ≥ 21.3 (required for pyproject.toml installs)…"
  "$PYTHON" -m pip install --upgrade pip --quiet 2>&1 || \
    die "pip upgrade failed." \
        "Run manually: $PYTHON -m pip install --upgrade pip"
  new_pip=$("$PYTHON" -m pip --version | awk '{print $2}')
  ok "pip $new_pip"

  info "Installing signalpilot${EXTRAS:+ (+ dev extras)}…"
  "$PYTHON" -m pip install -e ".${EXTRAS}" --quiet 2>&1 || \
    die "pip install failed." \
        "Check the output above, then rerun: bash install.sh${DEV:+ --dev}"
fi

ok "signalpilot installed"

# ── 4. Smoke-test + kubectl check ────────────────────────────────────────────
step "4/4  Verifying"

"$PYTHON" -m signalpilot --help > /dev/null 2>&1 || \
  die "signalpilot installed but the CLI failed to start." \
      "Run '$PYTHON -m signalpilot --help' to see the error in full."
ok "CLI entry-point working"

if command -v kubectl &>/dev/null; then
  ok "kubectl found  ($(kubectl version --client --short 2>/dev/null \
       | head -1 | sed 's/Client Version: //' || echo 'version unknown'))"
else
  warn "kubectl not found — needed to connect to your cluster."
  echo  "   → Install: https://kubernetes.io/docs/tasks/tools/"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "────────────────────────────────────────────────────────────────"
echo -e "${GREEN}${BOLD}  ✔  Ready!${RESET}"
echo ""
if $USE_VENV && [[ -z "${VIRTUAL_ENV:-}" ]]; then
  echo -e "  ${CYAN}Activate the venv before each new shell session:${RESET}"
  echo -e "    source $VENV_DIR/bin/activate"
  echo ""
fi
echo -e "  ${CYAN}Apply RBAC (one-time, read-only cluster access):${RESET}"
echo -e "    kubectl apply -f deploy/signalpilot-rbac.yaml"
echo ""
echo -e "  ${CYAN}Run your first analysis:${RESET}"
echo -e "    signalpilot analyze <namespace>"
echo -e "    signalpilot analyze <namespace> --deployment <name> --output report.html"
echo ""
echo -e "  ${CYAN}All commands:${RESET}"
echo -e "    signalpilot --help"
echo ""
