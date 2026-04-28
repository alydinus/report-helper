#!/bin/bash

SUPER=$(git rev-parse --show-superproject-working-tree 2>/dev/null)
if [ -n "$SUPER" ]; then
    PARENT_REPO="$SUPER"
else
    PARENT_REPO=$(git rev-parse --show-toplevel)
fi

LOG_FILE="$PARENT_REPO/hook.log"
SCRIPTS_DIR="$PARENT_REPO/scripts"
IMAGE_NAME="report"

ORIGIN=$(git rev-parse --show-toplevel)
ORIGIN_REL="${ORIGIN#$PARENT_REPO/}"
[ "$ORIGIN_REL" = "$ORIGIN" ] && ORIGIN_REL="<root>"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

{
    echo ""
    echo "=================================================="
    echo "=== post-commit @ $(date '+%Y-%m-%d %H:%M:%S') (from: $ORIGIN_REL) ==="
    echo "=================================================="
} >> "$LOG_FILE"

DATE=$(date +"%d-%m-%Y")
HASH=$(git rev-parse --short HEAD)
MSG=$(git log -1 --pretty=%B)

log "INPUT date=$DATE hash=$HASH msg=$MSG"

if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    log "IMAGE '$IMAGE_NAME' not found, building from $SCRIPTS_DIR ..."
    BUILD_OUT=$(docker build -t "$IMAGE_NAME" "$SCRIPTS_DIR" 2>&1)
    BUILD_STATUS=$?
    echo "$BUILD_OUT" >> "$LOG_FILE"
    if [ $BUILD_STATUS -ne 0 ]; then
        log "BUILD FAILED (exit=$BUILD_STATUS)"
        echo "post-commit: docker build failed (exit=$BUILD_STATUS), see $LOG_FILE" >&2
        exit 0
    fi
    log "BUILD OK"
else
    log "IMAGE '$IMAGE_NAME' found, skipping build"
fi

if [ -z "$GEMINI_API_KEY" ] && [ -f "$SCRIPTS_DIR/.gemini-key" ]; then
    GEMINI_API_KEY=$(tr -d '\n\r' < "$SCRIPTS_DIR/.gemini-key")
fi

log "RUN docker run --rm -e GEMINI_API_KEY=*** $IMAGE_NAME \"$DATE\" \"$HASH\" \"$MSG\""
RUN_OUT=$(docker run --rm \
    -e GEMINI_API_KEY="$GEMINI_API_KEY" \
    -e GEMINI_MODEL="${GEMINI_MODEL:-gemini-2.5-flash}" \
    "$IMAGE_NAME" "$DATE" "$HASH" "$MSG" 2>&1)
RUN_STATUS=$?

if [ -n "$RUN_OUT" ]; then
    echo "--- container output ---" >> "$LOG_FILE"
    echo "$RUN_OUT" >> "$LOG_FILE"
    echo "--- end container output ---" >> "$LOG_FILE"
fi

if [ $RUN_STATUS -eq 0 ]; then
    log "RESULT OK"
else
    log "RESULT FAIL (exit=$RUN_STATUS)"
    echo "post-commit: report failed (exit=$RUN_STATUS), see $LOG_FILE" >&2
fi

exit 0
