#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SignalPilot installer
#
# Usage:
#   bash install.sh            — recommended: venv + auto-link to PATH
#   bash install.sh --dev      — also install dev/test dependencies
#   bash install.sh --no-venv  — install into whatever Python is currently active
#
# After running this script, `signalpilot` will work in any new terminal
# without needing to activate the venv manually.
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

info()  { echo -e "  ${CYAN}▸${RESET} $*"; }
ok()    { echo -e "  ${GREEN}✔${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
die()   {
  echo ""
  echo -e "  ${RED}${BOLD}✖  ERROR:${RESET}  $1" >&2
  if [[ -n "${2:-}" ]]; then
    echo -e "  ${YELLOW}→ FIX:${RESET}" >&2
    # indent each fix line
    while IFS= read -r line; do
      echo -e "     $line" >&2
    done <<< "$2"
  fi
  echo "" >&2
  exit 1
}
step() { echo -e "\n  ${BOLD}$*${RESET}"; }

# ── args ─────────────────────────────────────────────────────────────────────
DEV=false; USE_VENV=true
for arg in "$@"; do
  [[ "$arg" == "--dev" ]]     && DEV=true
  [[ "$arg" == "--no-venv" ]] && USE_VENV=false
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "  ${BOLD}⚡  PerfSage SignalPilot — installer${RESET}"
echo "  ─────────────────────────────────────────────────────────────"

# ── 1. Find Python 3.12+ ─────────────────────────────────────────────────────
step "1/5  Python 3.12+"

PYTHON=""
for candidate in python3.12 python3.13 python3.14 python3 python; do
  command -v "$candidate" &>/dev/null || continue
  py_num=$("$candidate" -c \
    "import sys; print(sys.version_info.major*100+sys.version_info.minor)" \
    2>/dev/null) || continue
  if [[ "$py_num" -ge 312 ]]; then
    PYTHON="$candidate"
    human_ver=$("$candidate" -c \
      "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}.{v.micro}')")
    ok "Found $PYTHON  ($human_ver)"
    break
  fi
done

[[ -z "$PYTHON" ]] && die \
  "Python 3.12 or newer is required but was not found on PATH." \
  "Install it, then rerun:
    macOS  : brew install python@3.12      # https://brew.sh
    Ubuntu : sudo apt install python3.12
    Windows: winget install Python.Python.3.12
    Manual : https://python.org/downloads/"

# ── 2. Virtual environment ────────────────────────────────────────────────────
step "2/5  Virtual environment"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON=""

if $USE_VENV; then
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    ok "Already inside a virtual environment ($VIRTUAL_ENV)"
    PYTHON="python"
    VENV_PYTHON="$(command -v python)"
  else
    if command -v uv &>/dev/null; then
      if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating venv with uv…"
        uv venv "$VENV_DIR" --python "$PYTHON" --quiet || \
          die "uv venv failed." "rm -rf $VENV_DIR && bash install.sh"
        ok "Created $VENV_DIR/"
      else
        ok "Reusing $VENV_DIR/"
      fi
    else
      if [[ ! -d "$VENV_DIR" ]]; then
        info "Creating venv…"
        "$PYTHON" -m venv "$VENV_DIR" || \
          die "venv creation failed." \
              "$PYTHON -m pip install virtualenv\n$PYTHON -m virtualenv $VENV_DIR"
        ok "Created $VENV_DIR/"
      else
        ok "Reusing $VENV_DIR/"
      fi
    fi

    # Activate
    activate="$VENV_DIR/bin/activate"
    [[ ! -f "$activate" ]] && activate="$VENV_DIR/Scripts/activate"
    # shellcheck disable=SC1090
    source "$activate" 2>/dev/null || \
      die "Could not activate $VENV_DIR." "rm -rf $VENV_DIR && bash install.sh"
    PYTHON="python"
    VENV_PYTHON="$VENV_DIR/bin/python"
    [[ -f "$VENV_DIR/Scripts/python.exe" ]] && VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
  fi
else
  VENV_PYTHON="$(command -v "$PYTHON")"
  ok "Using existing Python: $VENV_PYTHON"
fi

# ── 3. Install package ────────────────────────────────────────────────────────
step "3/5  Installing SignalPilot"

EXTRAS=""; $DEV && EXTRAS="[dev]"

if [[ -n "${VIRTUAL_ENV:-}" ]] && command -v uv &>/dev/null; then
  info "Installing with uv…"
  uv pip install --upgrade pip --quiet 2>/dev/null || true
  uv pip install -e ".${EXTRAS}" --quiet || \
    die "uv pip install failed." \
        "bash install.sh${DEV:+ --dev}  (check output above)"
else
  info "Upgrading pip  (old pip can't handle pyproject.toml installs)…"
  "$PYTHON" -m pip install --upgrade pip --quiet 2>&1 || \
    die "pip upgrade failed." "$PYTHON -m pip install --upgrade pip"
  new_pip=$("$PYTHON" -m pip --version | awk '{print $2}')
  ok "pip $new_pip"
  info "Installing…"
  "$PYTHON" -m pip install -e ".${EXTRAS}" --quiet 2>&1 || \
    die "pip install -e . failed." \
        "bash install.sh${DEV:+ --dev}  (check output above)"
fi

ok "Package installed"

# ── 4. Verify CLI runs ────────────────────────────────────────────────────────
step "4/5  Sanity check"

"$PYTHON" -m signalpilot --help > /dev/null 2>&1 || \
  die "signalpilot installed but the CLI crashed." \
      "$PYTHON -m signalpilot --help  (run to see full error)"
ok "CLI works via python -m signalpilot"

if command -v kubectl &>/dev/null; then
  ok "kubectl found"
else
  warn "kubectl not found — needed to talk to your cluster."
  echo  "     Install: https://kubernetes.io/docs/tasks/tools/"
fi

# ── 5. Link signalpilot onto PATH ─────────────────────────────────────────────
# Goal: after this step, 'signalpilot' works in any new terminal
# without the user ever needing to 'source .venv/bin/activate'
step "5/5  Linking signalpilot onto PATH"

WRAPPER_CONTENT="#!/usr/bin/env bash
# Auto-generated by SignalPilot installer.
# Calls the venv Python directly so no manual activation is needed.
exec \"$VENV_PYTHON\" -m signalpilot \"\$@\""

LINKED=false
LINK_PATH=""

# Try locations that are already on PATH, in preference order:
#   ~/.local/bin   — standard user bin on modern Linux/macOS
#   ~/bin          — common on older setups
#   /usr/local/bin — system-wide (may need sudo, skip silently if so)
for bin_dir in "$HOME/.local/bin" "$HOME/bin" "/usr/local/bin"; do
  # Skip if not on PATH (we'll add it below for ~/.local/bin)
  # Skip /usr/local/bin unless it's already writable (no sudo prompts)
  if [[ "$bin_dir" == "/usr/local/bin" ]]; then
    [[ -w "$bin_dir" ]] || continue
  fi

  # Create directory if missing (safe for user-owned dirs)
  if [[ ! -d "$bin_dir" ]] && [[ "$bin_dir" != "/usr/local/bin" ]]; then
    mkdir -p "$bin_dir"
  fi

  if [[ -w "$bin_dir" ]]; then
    printf '%s\n' "$WRAPPER_CONTENT" > "$bin_dir/signalpilot"
    chmod +x "$bin_dir/signalpilot"
    LINK_PATH="$bin_dir/signalpilot"
    LINKED=true
    ok "Wrapper written to $LINK_PATH"
    break
  fi
done

if ! $LINKED; then
  warn "Could not write to ~/.local/bin, ~/bin, or /usr/local/bin."
  warn "You will need to activate the venv manually:  source $VENV_DIR/bin/activate"
fi

# ── Make sure the bin directory is on PATH (add to shell config if needed) ───
PATH_UPDATED=false
if $LINKED && [[ -n "$LINK_PATH" ]]; then
  LINK_DIR="$(dirname "$LINK_PATH")"

  if ! echo "$PATH" | tr ':' '\n' | grep -qx "$LINK_DIR"; then
    # Not on PATH in this session. Detect shell config file.
    SHELL_RC=""
    case "${SHELL:-}" in
      */zsh)   SHELL_RC="$HOME/.zshrc" ;;
      */bash)  SHELL_RC="$HOME/.bashrc" ;;
      */fish)  SHELL_RC="$HOME/.config/fish/config.fish" ;;
    esac
    # Fallback: zshrc if it exists, else bashrc
    [[ -z "$SHELL_RC" && -f "$HOME/.zshrc" ]]  && SHELL_RC="$HOME/.zshrc"
    [[ -z "$SHELL_RC" && -f "$HOME/.bashrc" ]] && SHELL_RC="$HOME/.bashrc"

    if [[ -n "$SHELL_RC" ]]; then
      EXPORT_LINE='export PATH="$HOME/.local/bin:$PATH"'
      [[ "$LINK_DIR" != "$HOME/.local/bin" ]] && \
        EXPORT_LINE="export PATH=\"$LINK_DIR:\$PATH\""

      if ! grep -qF "$LINK_DIR" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# Added by SignalPilot installer" >> "$SHELL_RC"
        echo "$EXPORT_LINE" >> "$SHELL_RC"
        ok "Added $LINK_DIR to PATH in $SHELL_RC"
        PATH_UPDATED=true
      else
        ok "$LINK_DIR already in $SHELL_RC"
        PATH_UPDATED=true
      fi
    else
      warn "Could not detect shell config file. Add this line manually:"
      echo  "     export PATH=\"$LINK_DIR:\$PATH\""
    fi

    # Also export for this session so the summary command is accurate
    export PATH="$LINK_DIR:$PATH"
  else
    ok "$LINK_DIR is already on PATH"
    PATH_UPDATED=true
  fi
fi

# ── Verify the command is now on PATH ─────────────────────────────────────────
if $LINKED; then
  if command -v signalpilot &>/dev/null; then
    ok "signalpilot is on PATH — command ready"
  else
    warn "signalpilot wrapper written but not yet on PATH in this shell."
    echo  "     Open a new terminal, or reload now:"
    if [[ -n "${SHELL_RC:-}" ]]; then
      echo  "     source $SHELL_RC"
    fi
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "  ─────────────────────────────────────────────────────────────"
echo -e "  ${GREEN}${BOLD}✔  Installation complete!${RESET}"
echo ""

if $LINKED && $PATH_UPDATED; then
  echo -e "  ${YELLOW}${BOLD}ACTION REQUIRED:${RESET}  Open a new terminal (or run the line below),"
  echo -e "  then ${BOLD}signalpilot${RESET} will work everywhere without any activation step:"
  echo ""
  [[ -n "${SHELL_RC:-}" ]] && echo -e "    source ${SHELL_RC}" || \
    echo -e "    export PATH=\"$(dirname "$LINK_PATH"):\$PATH\""
  echo ""
elif ! $LINKED; then
  echo -e "  ${YELLOW}${BOLD}ACTION REQUIRED:${RESET}  Activate the venv before using signalpilot:"
  echo ""
  echo -e "    source $VENV_DIR/bin/activate"
  echo ""
fi

echo -e "  ${CYAN}Apply RBAC  (one-time, read-only cluster access):${RESET}"
echo -e "    kubectl apply -f deploy/signalpilot-rbac.yaml"
echo ""
echo -e "  ${CYAN}Run your first analysis:${RESET}"
echo -e "    signalpilot analyze <namespace>"
echo -e "    signalpilot analyze <namespace> --deployment <name> --output report.html"
echo ""
echo -e "  ${CYAN}All commands:${RESET}  signalpilot --help"
echo ""
