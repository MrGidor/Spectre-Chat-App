#!/usr/bin/env bash

# Resolve the absolute path of the client binary in the same directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="$SCRIPT_DIR/spectre-client-linux-amd64"

# Ensure the binary exists and is executable
if [ ! -x "$BINARY" ]; then
    echo "[!] Executable not found at $BINARY"
    exit 1
fi

# Function to detect active/installed terminal
detect_terminal() {
    # 1. Check if launched from an active terminal (PPID check)
    local parent_proc
    parent_proc=$(ps -o comm= -p $PPID 2>/dev/null)
    
    case "$parent_proc" in
        kitty|alacritty|konsole|gnome-terminal*|xfce4-terminal|foot|xterm|wezterm|ghostty)
            echo "$parent_proc"
            return
            ;;
    esac

    # 2. Check $TERM_PROGRAM environment variable
    if [ -n "$TERM_PROGRAM" ]; then
        echo "$TERM_PROGRAM"
        return
    fi

    # 3. Check Desktop Environment specific terminal defaults
    if [ -n "$XDG_CURRENT_DESKTOP" ]; then
        case "$XDG_CURRENT_DESKTOP" in
            *KDE*)      command -v konsole &>/dev/null && { echo "konsole"; return; } ;;
            *GNOME*)    command -v gnome-terminal &>/dev/null && { echo "gnome-terminal"; return; } ;;
            *XFCE*)     command -v xfce4-terminal &>/dev/null && { echo "xfce4-terminal"; return; } ;;
        esac
    fi

    # 4. Fallback search order for installed terminals
    for term in kitty alacritty foot konsole gnome-terminal xfce4-terminal wezterm ghostty xterm; do
        if command -v "$term" &>/dev/null; then
            echo "$term"
            return
        fi
    done
}

TERM_CMD=$(detect_terminal)

# If already running in an interactive terminal TTY, just execute directly
if [ -t 1 ]; then
    exec "$BINARY" "$@"
fi

# Otherwise, launch inside detected terminal
case "$TERM_CMD" in
    kitty)
        exec kitty --detach "$BINARY" "$@"
        ;;
    alacritty)
        exec alacritty -e "$BINARY" "$@"
        ;;
    konsole)
        exec konsole -e "$BINARY" "$@"
        ;;
    gnome-terminal*)
        exec gnome-terminal -- "$BINARY" "$@"
        ;;
    xfce4-terminal)
        exec xfce4-terminal -e "$BINARY" "$@"
        ;;
    foot)
        exec foot "$BINARY" "$@"
        ;;
    wezterm)
        exec wezterm start -- "$BINARY" "$@"
        ;;
    ghostty)
        exec ghostty -e "$BINARY" "$@"
        ;;
    xterm)
        exec xterm -e "$BINARY" "$@"
        ;;
    *)
        echo "[!] No supported terminal found to launch Spectre Client."
        exit 1
        ;;
esac
