#!/usr/bin/env bash
# YouTube Mirror Bot launcher — auto-updates to the latest version on every
# launch (skip with --no-update). Installed by install.sh into ~/.local/bin.
META="$HOME/.yt-mirror/.install_meta.json"
SRC="$HOME/.yt-mirror/src"
REMOTE=$(python3 -c "import json; print(json.load(open('$META')).get('remote',''))" 2>/dev/null)
LAST_HEAD=$(python3 -c "import json; print(json.load(open('$META')).get('commit',''))" 2>/dev/null)

SKIP_UPDATE=false
for arg in "$@"; do [ "$arg" = "--no-update" ] && SKIP_UPDATE=true; done

if [ "$SKIP_UPDATE" = false ] && [ -n "$REMOTE" ] && command -v git >/dev/null 2>&1; then
    TMP_REPO="$HOME/.yt-mirror/.repo"
    echo "  Checking for updates from $REMOTE..."
    ok=0
    if [ -d "$TMP_REPO/.git" ]; then
        git -C "$TMP_REPO" fetch --depth 1 origin main >/dev/null 2>&1 \
            && git -C "$TMP_REPO" reset --hard origin/main >/dev/null 2>&1 && ok=1
        if [ "$ok" = 0 ]; then
            echo "  Update fetch failed — re-cloning..."
            rm -rf "$TMP_REPO"
        fi
    fi
    if [ ! -d "$TMP_REPO/.git" ]; then
        rm -rf "$TMP_REPO"
        git clone --depth 1 "$REMOTE" "$TMP_REPO" >/dev/null 2>&1 && ok=1
    fi
    if [ "$ok" = 1 ] && [ -f "$TMP_REPO/mirror.py" ]; then
        NEW_HEAD=$(git -C "$TMP_REPO" rev-parse --short HEAD 2>/dev/null)
        if [ -n "$NEW_HEAD" ] && [ "$NEW_HEAD" != "$LAST_HEAD" ]; then
            if [ -n "$LAST_HEAD" ]; then
                echo "  Updating $LAST_HEAD -> $NEW_HEAD..."
            else
                echo "  Installing latest ($NEW_HEAD)..."
            fi
            # Copy ALL source so new modules (e.g. verify_state.py) are never
            # missing from an existing installation.
            cp "$TMP_REPO"/*.py "$SRC/" 2>/dev/null
            cp "$TMP_REPO"/*.txt "$SRC/" 2>/dev/null
            cp "$TMP_REPO"/*.json "$SRC/" 2>/dev/null
            cp "$TMP_REPO"/*.sql "$SRC/" 2>/dev/null
            cp "$TMP_REPO/install.sh" "$SRC/" 2>/dev/null
            cp "$TMP_REPO/launcher.sh" "$SRC/" 2>/dev/null
            [ -d "$TMP_REPO/.github" ] && cp -r "$TMP_REPO/.github" "$SRC/" 2>/dev/null
            # Re-install deps only when requirements.txt actually changed
            REQ_SHA=$(sha256sum "$SRC/requirements.txt" 2>/dev/null | cut -d' ' -f1)
            META_REQ=$(python3 -c "import json; print(json.load(open('$META')).get('requirements_sha',''))" 2>/dev/null)
            if [ -n "$REQ_SHA" ] && [ "$REQ_SHA" != "$META_REQ" ]; then
                echo "  Dependencies changed — installing..."
                pip3 install --break-system-packages -q -r "$SRC/requirements.txt" 2>/dev/null \
                    || pip3 install -q -r "$SRC/requirements.txt" 2>/dev/null || true
            fi
            python3 - "$META" "$NEW_HEAD" "$REQ_SHA" <<'PYEOF'
import json, sys
meta, head, req_sha = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(meta))
d["commit"] = head
if req_sha:
    d["requirements_sha"] = req_sha
json.dump(d, open(meta, "w"))
PYEOF
            echo "  Up to date."
        else
            echo "  Already at latest ($NEW_HEAD)."
        fi
    elif [ "$ok" = 0 ]; then
        echo "  WARNING: could not fetch the latest version — running the existing copy."
        echo "          Check your network connection or remote access."
    fi
fi

ARGS=()
for arg in "$@"; do [ "$arg" != "--no-update" ] && ARGS+=("$arg"); done

if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    export PATH="$HOME/.local/bin:$PATH"
fi

cd "$SRC" || exit 1
exec python3 "$SRC/tui.py" "${ARGS[@]}"
