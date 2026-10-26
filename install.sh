#!/usr/bin/env bash
# ProofPress installer for macOS / Linux.
#
#   ./install.sh            install everything below
#   ./install.sh --cli      put `proofpress` on your PATH (~/.local/bin, added to your shell profile;
#                           set PROOFPRESS_NO_PROFILE=1 to skip editing the profile)
#   ./install.sh --deps     pip install markdown + pillow
#   ./install.sh --skill    link the skill into ~/.claude/skills/proofpress (Claude Code)
#   ./install.sh --mcp      register the MCP server with Claude Code (user scope)
#
# Nothing here needs sudo. Re-running is safe.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PROOFPRESS_PYTHON:-python3}"

NEED_RELOAD=""
want_all=1; want_cli=0; want_deps=0; want_skill=0; want_mcp=0
for a in "$@"; do
  want_all=0
  case "$a" in
    --cli) want_cli=1;; --deps) want_deps=1;; --skill) want_skill=1;; --mcp) want_mcp=1;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "unknown option $a"; exit 1;;
  esac
done
[[ $want_all == 1 ]] && { want_cli=1; want_deps=1; want_skill=1; want_mcp=1; }

command -v "$PY" >/dev/null || { echo "python3 not found. Install Python 3.9+ first."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9+ required ($("$PY" --version))"; exit 1; }
chmod +x "$ROOT/cli/proofpress" "$ROOT/cli/proofpress-mcp" "$ROOT/mcp/server.py"

if [[ $want_deps == 1 ]]; then
  echo "== Python packages (markdown for HTML, pillow for hero images)"
  if "$PY" -m pip install --user -r "$ROOT/requirements.txt" 2>/dev/null; then
    echo "   installed"
  else
    echo "   pip refused (common with Homebrew Python). Either run:"
    echo "     $PY -m pip install --user --break-system-packages -r $ROOT/requirements.txt"
    echo "   or use a virtualenv and set PROOFPRESS_PYTHON to its python."
  fi
fi

if [[ $want_cli == 1 ]]; then
  echo "== CLI"
  mkdir -p "$HOME/.local/bin"
  ln -sf "$ROOT/cli/proofpress" "$HOME/.local/bin/proofpress"
  echo "   linked ~/.local/bin/proofpress"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
      PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
      case "${SHELL:-}" in
        */zsh) PROFILE="$HOME/.zshrc" ;;
        */bash) if [[ "$(uname)" == "Darwin" ]]; then PROFILE="$HOME/.bash_profile"; else PROFILE="$HOME/.bashrc"; fi ;;
        *) PROFILE="$HOME/.profile" ;;
      esac
      if [[ "${PROOFPRESS_NO_PROFILE:-}" == "1" ]]; then
        echo "   add this to your shell profile:  $PATH_LINE"
      elif grep -qsF "$PATH_LINE" "$PROFILE"; then
        echo "   $PROFILE already adds ~/.local/bin to PATH"
      else
        printf '\n# Added by ProofPress installer\n%s\n' "$PATH_LINE" >> "$PROFILE"
        echo "   added ~/.local/bin to PATH in $PROFILE"
      fi
      NEED_RELOAD="$PROFILE"
      ;;
  esac
fi

if [[ $want_skill == 1 ]]; then
  echo "== Claude Code skill"
  mkdir -p "$HOME/.claude/skills"
  if [[ -e "$HOME/.claude/skills/proofpress" && ! -L "$HOME/.claude/skills/proofpress" ]]; then
    echo "   ~/.claude/skills/proofpress exists and is not a link; leaving it alone"
  else
    ln -sfn "$ROOT/skills/proofpress" "$HOME/.claude/skills/proofpress"
    echo "   linked ~/.claude/skills/proofpress"
  fi
fi

if [[ $want_mcp == 1 ]]; then
  echo "== MCP server"
  if command -v claude >/dev/null; then
    claude mcp remove proofpress -s user >/dev/null 2>&1 || true
    claude mcp add proofpress -s user -- "$PY" "$ROOT/mcp/server.py" && echo "   registered with Claude Code (user scope)"
  else
    echo "   Claude Code CLI not found. Add this to your MCP client config:"
    echo "   {\"mcpServers\": {\"proofpress\": {\"command\": \"$PY\", \"args\": [\"$ROOT/mcp/server.py\"], \"env\": {\"PROOFPRESS_PROJECT\": \"/path/to/your/project\"}}}}"
  fi
fi

echo
if [[ -n "$NEED_RELOAD" ]]; then
  echo "To use the proofpress command in THIS terminal, run:  source $NEED_RELOAD"
  echo "(new terminal windows pick it up automatically)"
  echo
fi
echo "Done. Next:"
echo "  proofpress init ~/my-site --name \"My Product\""
echo "  proofpress ui --project ~/my-site"
