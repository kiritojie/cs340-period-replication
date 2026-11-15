#!/usr/bin/env bash
# Capture a command without changing PERIOD or interpreting a crash as success.
# Usage: bash capture_period_command.sh /absolute/new-step-directory -- command args...
# Run from the intended working directory. The step directory must not exist.
set -u
if [ "$#" -lt 3 ] || [ "$2" != -- ]; then
    printf 'Usage: %s /absolute/new-step-directory -- command [args...]\n' "$0" >&2
    exit 2
fi
evidence_step=$1
shift 2
case "$evidence_step" in
    /*) ;;
    *) printf 'Evidence directory must be absolute.\n' >&2; exit 2 ;;
esac
# mkdir without -p prevents accidental reuse/overwrite of an earlier step.
if ! mkdir -- "$evidence_step"; then
    exit 2
fi
{
    printf 'cwd=%s\n' "$PWD"
    printf 'started_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'command='
    printf ' %q' "$@"
    printf '\n'
    printf 'exit_code_scope=outer command (not necessarily the tested target)\n'
} > "$evidence_step/command.txt" || exit 2

"$@" > "$evidence_step/console.log" 2>&1
command_status=$?
printf '%s\n' "$command_status" > "$evidence_step/exit-code.txt" || exit 2
printf 'finished_utc=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$evidence_step/command.txt" || exit 2
printf 'exit_code=%s; evidence=%s\n' "$command_status" "$evidence_step"
exit "$command_status"
