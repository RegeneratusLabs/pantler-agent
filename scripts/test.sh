#!/usr/bin/env bash
# Run every test in the repo.
#
#   ./scripts/test.sh          engine pin + tool surface + kernel + BFF + plugins + shell
#   ./scripts/test.sh python   the seam, the kernel, the BFF and every plugin suite
#   ./scripts/test.sh web      the shell only
#   ./scripts/test.sh engine   the pin and the tool surface only
#   ./scripts/test.sh golden   one real conversation through the gateway (not in `all`: it
#                              writes, and it needs a working model credential)
#
# This is also what CI runs (.github/workflows/ci.yml): the workflow schedules these
# commands, it does not re-implement them.
#
# The Python tests use the standard library's unittest rather than pytest: the kernel's
# pyproject promises `dependencies = []`, and a test runner that needs installing undercuts
# that for no benefit at this size.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# The engine's interpreter, because it is the one guaranteed to exist here. Any Python 3.11+
# works — `tomllib` is the only version-sensitive thing the kernel uses. A CI runner has no
# engine tools directory: the glob matches nothing, `ls` fails, and under `set -e` that would
# end the script before the fallback below, so the failure is swallowed here and `python3` is
# used instead.
PY="${PANTLER_PYTHON:-}"
if [[ -z "${PY}" ]]; then
  for home in "${HERMES_HOME:-}" "${HOME}/.hermes" "${ROOT}/.hermes-dev"; do
    [[ -n "${home}" ]] || continue
    candidate="$(ls -d "${home}"/tools/python-*/bin/python3 2>/dev/null | head -1 || true)"
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then PY="${candidate}"; break; fi
  done
fi
if [[ -z "${PY}" || ! -x "${PY}" ]]; then
  PY="$(command -v python3)"
fi

WHAT="${1:-all}"
SKIPPED=()

run_python() {
  echo "== kernel seam =="
  # The kernel's import contract (the design notes §1) as a build failure. It belongs in this half of
  # the suite rather than in the engine half because it reads source and needs no gateway —
  # in CI the engine half has no engine to talk to, and a check that always skips is not a check.
  "$ROOT/scripts/check-seam.py"
  echo "== distribution preflight =="
  # The distribution payload is the one artefact the engine never inspects: it validates hub
  # installs and agent-written skills, not a distribution_owned tree. This is skillcheck's first
  # slice — the house rules for shipped skills, the manifest's own coherence, and the shipped
  # defaults (the internal capability plan §3 item A5).
  "$ROOT/scripts/check-distribution.py"
  echo
  echo "== kernel =="
  PYTHONPATH=core/src "$PY" -m unittest discover -s core/tests -t core/tests
  echo
  echo "== scripts =="
  # The harnesses in scripts/ that make judgements rather than measurements: the scenario runner
  # decides pass from fail, and a bug there is a green suite that proves nothing.
  "$PY" -m unittest discover -s scripts/tests -t scripts/tests
  echo
  echo "== bff =="
  PYTHONPATH=core/src:app/server "$PY" -m unittest discover -s app/server/tests -t app/server/tests
  echo
  echo "== plugins =="
  # Each plugin's suite is self-contained and stdlib-only, like the kernel. The soil
  # engine's tests load the plugin the way Hermes does, so a broken entry point fails
  # here rather than at session start.
  for plugin in plugins/*/; do
    [ -d "${plugin}tests" ] || continue
    echo "-- ${plugin%/} --"
    "$PY" -m unittest discover -s "${plugin}tests" -t "${plugin}tests"
  done
}

run_engine() {
  # The two assertions that are about the engine rather than about our code. Both are
  # cheap, and both fail loudly on drift: the pin (the design notes invariant 4, plus the rule
  # that the dev engine and the operator's Hermes never differ) and the tool surface
  # (invariant 3). The surface check needs a running gateway; with none, it is skipped
  # rather than failed, so this stays runnable in CI and on a fresh clone.
  echo "== engine pin =="
  "$ROOT/scripts/engine-pin.sh"
  echo
  echo "== tool surface =="
  local code=0
  "$ROOT/scripts/toolset-check.py" || code=$?
  case "$code" in
    0) ;;
    3) SKIPPED+=("the tool surface (no gateway at ${PANTLER_API:-http://127.0.0.1:8644} — start pantler-engine to include it)") ;;
    4) SKIPPED+=("the tool surface (a gateway is up, but this shell has no API key)") ;;
    *) exit 1 ;;
  esac
}

run_golden() {
  # `scripts/golden.py` asserted nothing and nobody called it. It judges now, and this is the
  # caller — deliberately not part of `all`: it drives the live gateway, which means it needs a
  # working upstream credential and it may write an invoice draft into the operator's store.
  echo "== golden conversation =="
  local code=0
  "$ROOT/scripts/golden.py" --turns "Reply with exactly: seam-ok" || code=$?
  case "$code" in
    0) ;;
    *) exit "$code" ;;
  esac
}

run_web() {
  echo "== shell =="
  # The identity module's pair, and the guard that reads it: the identifiers are decided now
  # (2026-11-01), and the checker proves none of them is still a placeholder
  # (the internal audit IDN-1, IDN-3).
  node "$ROOT/scripts/identity-check.mjs"
  # A subshell: the suite used to leave the caller in app/web.
  (
    cd app/web
    npm run --silent typecheck
    npx vitest run
    # A real build must complete now: the guard refuses placeholders, and there are none left.
    npm run --silent build >/dev/null
    echo "identity guard: a release build accepts the decided identifiers"
  )
}

run_desktop() {
  echo "== desktop host =="
  # The Electron-free half: paths, the first-run key, readiness probes and the supervisor. The
  # window needs a display and a packaged payload, so it is not here; what decides whether a
  # child starts, restarts or is stopped is.
  (
    cd app/desktop
    node --test "test/**/*.test.mjs"
  )
}

case "$WHAT" in
  engine) run_engine ;;
  python) run_python ;;
  web)    run_web ;;
  desktop) run_desktop ;;
  golden) run_golden ;;
  all)    run_engine; echo; run_python; echo; run_web; echo; run_desktop ;;
  *)      echo "usage: $0 [all|engine|python|web|desktop|golden]" >&2; exit 2 ;;
esac

echo
# "All green" used to be unconditional, so a run where the tool surface was skipped for want of
# a key read exactly like a run that checked it (the internal audit SCR-5).
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo "green, with checks skipped:"
  for skipped in "${SKIPPED[@]}"; do echo "  - ${skipped}"; done
else
  echo "all green"
fi
