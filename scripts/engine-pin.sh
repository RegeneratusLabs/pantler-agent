#!/usr/bin/env bash
# The engine pin, in one place, asserted everywhere.
#
# Two engines run on this machine and they are never on different revisions:
#
#   .hermes-dev/src/hermes-agent   the mirror this repo owns, and the tree the
#                                  dev engine unit runs (the design notes invariant 4 —
#                                  "pin the engine and mirror the source")
#   ~/.hermes/hermes-agent         the checkout the operator's own Hermes runs
#
# They share nothing but the pin. The rule is deliberate: the assistant must
# behave the same in both, so a re-pin moves both or neither. `engine-pin.json`
# is the single source of truth; this script is the rule as code.
#
# Usage:
#   ./scripts/engine-pin.sh            assert the pin (exit 1 on drift)
#   ./scripts/engine-pin.sh --report   print what each tree is on, assert nothing
#
# Absent trees are skipped, not failed: CI has no personal install, and a fresh
# clone has no mirror yet. What is present must match.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN="$ROOT/engine-pin.json"
MIRROR="${PANTLER_ENGINE_MIRROR:-$ROOT/.hermes-dev/src/hermes-agent}"
PERSONAL="${PANTLER_ENGINE_PERSONAL:-$HOME/.hermes/hermes-agent}"
UNIT="${PANTLER_ENGINE_UNIT:-pantler-engine}"

usage() {
  echo "usage: $0 [--report|--help]" >&2
}

report_only=false
case "${1:-}" in
  "") ;;
  --report) report_only=true ;;
  -h|--help) usage; exit 0 ;;
  *) echo "engine-pin: unknown argument: $1" >&2; usage; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo "engine-pin: only one argument is accepted" >&2
  usage
  exit 2
fi

if [ ! -f "$PIN" ]; then
  # Before `read_pin`: a missing pin under `set -e` was a Python traceback, not this sentence.
  echo "engine-pin: $PIN is missing — the pin is the rule (the design notes invariant 4)" >&2
  exit 1
fi

read_pin() { # $1 = key
  python3 - "$PIN" "$1" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))
except (OSError, ValueError):
    print("")
PY
}

head_of() { # $1 = path → commit, or empty when not a git checkout
  # `-e`, not `-d`: in a linked worktree `.git` is a file holding `gitdir: …`, and requiring a
  # directory reported a real checkout as "not a git checkout — skipped"
  # (the internal audit SCR-4).
  [ -e "$1/.git" ] || { printf ''; return; }
  git -C "$1" rev-parse HEAD 2>/dev/null || printf ''
}

dirty_tree() { # $1 = path → what is dirty, or empty when the tree is clean
  # `rev-parse HEAD` says which commit is checked out, not what is on disk. A modified or
  # untracked file inside the engine tree read as "at the pin" while `M engine.py` and
  # `?? implant.py` sat in it (the internal security audit A19-SC-3).
  local path="$1" porcelain first count
  porcelain="$(git -C "$path" status --porcelain --untracked-files=normal 2>/dev/null || true)"
  if [ -n "$porcelain" ]; then
    count="$(printf '%s\n' "$porcelain" | wc -l | tr -d ' ')"
    first="$(printf '%s\n' "$porcelain" | head -n 1)"
    # Porcelain v1 is `XY path`: two status columns, a space, then the path.
    printf '%s' "${first:3}"
    if [ "$count" -gt 1 ]; then
      printf ' (and %s more)' "$((count - 1))"
    fi
    return 0
  fi
  # `status` covers this too, and both are required: a future porcelain flag or a git quirk
  # that hides a tracked modification from `status` still has to fail here.
  if ! git -C "$path" diff --quiet HEAD 2>/dev/null; then
    printf 'a tracked change git status did not report'
    return 0
  fi
  return 1
}

PIN_TAG="$(read_pin tag)"
PIN_COMMIT="$(read_pin commit)"
PIN_CHANNEL="$(read_pin channel)"

if [ -z "$PIN_COMMIT" ]; then
  echo "engine-pin: $PIN has no commit" >&2
  exit 1
fi

# The tag comes from a repository-writable JSON file and used to be printed verbatim inside a
# command the operator is told to paste. Refuse anything that is not a tag, and print the
# *commit* from here on: a tag can be moved, the commit it was pinned at cannot
# (the internal security audit A19-SC-4).
if [ -z "$PIN_TAG" ] || [[ ! "$PIN_TAG" =~ ^v[0-9][A-Za-z0-9.+-]*$ ]]; then
  printf 'engine-pin: %s records no tag, or one this guard will not print: %s\n' "$PIN" "$(printf '%q' "$PIN_TAG")" >&2
  exit 1
fi

short() { printf '%s' "${1:0:12}"; }

# Every value interpolated into a suggested command goes through this. `$MIRROR` is
# environment-overridable and a path with a space or a `;` is exactly what the unquoted
# message used to hand an operator to paste (the internal security audit A19-SC-4).
quote() { printf '%q' "$1"; }

status=0
CHECKED=0
SKIPPED=()
printf 'engine pin: %s (%s, %s)\n' "$PIN_TAG" "$(short "$PIN_COMMIT")" "$PIN_CHANNEL"

check_tree() { # $1 = label, $2 = path
  local label="$1" path="$2" head
  if [ ! -d "$path" ]; then
    printf '  %-9s %s\n' "$label" "absent — skipped"
    SKIPPED+=("$label (absent)")
    return 0
  fi
  head="$(head_of "$path")"
  if [ -z "$head" ]; then
    printf '  %-9s %s\n' "$label" "$path is not a git checkout — skipped"
    SKIPPED+=("$label (not a git checkout)")
    return 0
  fi
  CHECKED=$((CHECKED + 1))
  if [ "$head" = "$PIN_COMMIT" ]; then
    local dirty
    if dirty="$(dirty_tree "$path")"; then
      printf '  %-9s %s  DIRTY — %s\n' "$label" "$(short "$head")" "$dirty"
      return 2
    fi
    printf '  %-9s %s  at the pin\n' "$label" "$(short "$head")"
    return 0
  fi
  local described
  described="$(git -C "$path" describe --tags --always 2>/dev/null || echo '?')"
  printf '  %-9s %s  DRIFT (on %s)\n' "$label" "$(short "$head")" "$described"
  return 1
}

state=0
check_tree mirror "$MIRROR" || state=$?
if [ "$state" -eq 2 ]; then
  echo "          → the mirror is on the pin's commit but modified: commit, stash or discard the change" >&2
  status=1
elif [ "$state" -ne 0 ]; then
  echo "          → re-pin the mirror: git -C $(quote "$MIRROR") checkout --detach $(quote "$PIN_COMMIT")" >&2
  status=1
fi
state=0
check_tree personal "$PERSONAL" || state=$?
if [ "$state" -eq 2 ]; then
  echo "          → the operator's checkout is modified; the pin asserts the tree, not just the commit" >&2
  status=1
elif [ "$state" -ne 0 ]; then
  echo "          → the rule is no drift between the two: move both to $(quote "$PIN_COMMIT")" >&2
  status=1
fi

# The dev unit must run the mirror, not the shared checkout: a unit still on
# ~/.local/bin/hermes silently runs whatever the operator's install is on.
if [ ! -d "$MIRROR" ]; then
  # Nothing to be pointed at: with no mirror, comparing the unit against an absent path called a
  # correct unit drift and announced the pin had moved when it had not.
  printf '  %-9s %s\n' "unit" "no mirror to run — skipped"
  SKIPPED+=("unit (no mirror)")
elif command -v systemctl >/dev/null 2>&1 && systemctl --user cat "$UNIT" >/dev/null 2>&1; then
  exec_line="$(systemctl --user show "$UNIT" -p ExecStart --value 2>/dev/null || true)"
  if printf '%s' "$exec_line" | grep -q "$MIRROR"; then
    printf '  %-9s runs the mirror\n' "unit"
  else
    printf '  %-9s NOT the mirror — %s\n' "unit" "$UNIT still starts another tree"
    echo "          → point ExecStart at $(quote "$MIRROR")/.hermes/bin/hermes" >&2
    status=1
  fi
else
  printf '  %-9s no user unit — skipped\n' "unit"
  SKIPPED+=("unit (no systemd user unit)")
fi

if $report_only; then
  exit 0
fi
if [ "$status" -ne 0 ]; then
  # Lead with the commit, not the tag: the tag is a label someone can move, the commit is the
  # revision both trees were pinned to (the internal security audit A19-SC-4).
  echo "engine-pin: DRIFT — the pin is $(short "$PIN_COMMIT") ($PIN_TAG)" >&2
  exit 1
fi
if [ "${#SKIPPED[@]}" -gt 0 ]; then
  skipped_list=""
  for item in "${SKIPPED[@]}"; do
    skipped_list="${skipped_list:+${skipped_list}, }${item}"
  done
  echo "engine-pin: ${CHECKED} tree(s) at the pin; not checked: ${skipped_list}"
else
  echo "engine-pin: both trees at the pin"
fi
