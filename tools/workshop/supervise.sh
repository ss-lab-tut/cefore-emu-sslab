#!/bin/bash
# Workshop campaign supervisor: keep campaign.py running until the manifest is
# fully processed. campaign.py's crash-safe jsonl journal + resume ("ok" jobs
# are skipped on relaunch) makes blind relaunching idempotent, so this loop is
# safe even after SIGKILL mid-run. Run detached as root:
#   sudo setsid nohup tools/workshop/supervise.sh <manifest> <outdir> \
#        >> <outdir>/supervisor.log 2>&1 &
set -u
MANIFEST="$1"
OUT="$2"
REPO=/home/lab_shared/cefore-emu-sslab
PY=$REPO/.venv/bin/python3
cd "$REPO"

while true; do
  # Another live campaign (e.g. the initial foreground-launched one) owns the
  # run; wait rather than double-drive Mininet, which is single-instance.
  if pgrep -f "campaign.py --manifest" >/dev/null; then
    sleep 30
    continue
  fi

  # All manifest jobs terminal? (ok / failed / skipped_memory counted once per id)
  if $PY - "$MANIFEST" "$OUT/campaign_state.jsonl" <<'EOF'
import json, sys
manifest, journal = sys.argv[1], sys.argv[2]
want = {j["id"] for j in json.load(open(manifest))["jobs"]}
done = set()
try:
    for line in open(journal):
        j = json.loads(line)
        if j.get("status") in ("ok", "failed", "skipped_memory"):
            done.add(j["job_id"])
except FileNotFoundError:
    pass
sys.exit(0 if want <= done else 1)
EOF
  then
    echo "[supervisor] all jobs terminal; exiting $(date -Is)"
    touch "$OUT/CAMPAIGN_DONE"
    exit 0
  fi

  echo "[supervisor] (re)launching campaign $(date -Is)"
  mn -c >/dev/null 2>&1
  $PY tools/workshop/campaign.py --manifest "$MANIFEST" --out "$OUT"
  echo "[supervisor] campaign exited rc=$? $(date -Is)"
  sleep 10
done
