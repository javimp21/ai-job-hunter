#!/usr/bin/env bash
# Invoked by ai-job-hunter-notify-failure@<unit>.service (OnFailure=) to tell
# Telegram that a unit failed. Usage: notify-failure.sh <failed unit name>
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$here/lib/common.sh"
cd "$SHARED_DIR"
"$CURRENT_LINK/.venv/bin/ai-job-hunter" notify system \
    --text "Fallo la unidad ${1:-desconocida} en el servidor. Detalles: journalctl -u ${1:-desconocida}"
