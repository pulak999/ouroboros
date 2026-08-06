#!/usr/bin/env bash
#
# Smoke test for sweep_controls.c's command-list parser.
#
# Every case here is rejected inside load_cmds(), which runs before
# build_ladder(), so this script never opens /dev/nvidiactl and never touches a
# GPU. It is safe on a shared box and needs no root.
#
# Covers code.md findings E1 (parse-buffer overflow) and E2 (a bad template
# silently becoming a zeroed params buffer).
#
# Usage:  bash tools/effectmap/test_load_cmds.sh
# Exit:   0 all cases behaved, 1 otherwise.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/sweep_controls"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0

if ! gcc -O2 -Wall -Wextra -o "$BIN" "$HERE/sweep_controls.c"; then
    echo "FAIL: sweep_controls.c did not build"
    exit 1
fi

# $1 label, $2 expected exit code, $3 substring expected in stderr, $4 file body
check() {
    local label="$1" want_rc="$2" want_msg="$3" body="$4"
    local f="$TMP/cmds.txt" err="$TMP/err.txt"
    printf '%s\n' "$body" > "$f"

    "$BIN" --cmds "$f" --out "$TMP/out.jsonl" >/dev/null 2>"$err"
    local rc=$?

    if [ "$rc" -ne "$want_rc" ]; then
        echo "FAIL [$label]: exit $rc, expected $want_rc"
        sed 's/^/       /' "$err"
        fails=$((fails + 1))
        return
    fi
    if ! grep -qF "$want_msg" "$err"; then
        echo "FAIL [$label]: stderr missing '$want_msg'"
        sed 's/^/       /' "$err"
        fails=$((fails + 1))
        return
    fi
    echo "ok   [$label]"
}

# MAX_HEX_CHARS is 4096, so 4098 hex characters is over the legal maximum and
# must be reported rather than truncated into a plausible template. Keep the
# count even, or the odd-length check fires first and this case never runs.
long_hex="$(head -c 4098 /dev/zero | tr '\0' 'a')"
check "template over MAX_HEX_CHARS" 3 "template longer than MAX_HEX_CHARS" \
      "0x20801303 444 $long_hex"

check "odd hex length" 3 "odd number of hex characters" \
      "0x20801303 444 abc"

check "template exceeds paramsSize" 3 "larger than the declared paramsSize" \
      "0x20801303 4 aabbccddeeff"

check "non-hex character" 3 "non-hex character in template" \
      "0x20801303 444 zzzzzzzz"

# A line longer than the buffer must be reported and drained, never split into
# a second bogus command.
huge="$(head -c 6000 /dev/zero | tr '\0' 'a')"
check "over-long line" 3 "longer than" "0x20801303 444 $huge"

if [ "$fails" -eq 0 ]; then
    echo "PASS: all load_cmds rejection cases behaved"
    exit 0
fi
echo "FAILED: $fails case(s)"
exit 1
