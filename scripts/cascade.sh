#!/usr/bin/env bash
#
# cascade.sh — merge chapter branches forward (ch01 -> ch02 -> ... -> ch14).
#
# A fix belonging to chapter N is committed on chNN, then cascaded forward from
# there through every later chapter branch. Merges flow forward only; published
# chapter branches are never rebased.
#
# Usage:
#   scripts/cascade.sh [--dry-run] [--push] [start-branch]
#   scripts/cascade.sh --continue        # resume after resolving a merge conflict
#   scripts/cascade.sh --abort           # abort the in-progress merge and cascade
#
# start-branch defaults to the current branch. On a merge conflict the script
# stops; resolve the conflict, conclude the merge (git merge --continue), then
# run with --continue. git rerere is enabled so each recurring conflict only
# has to be resolved once.
#
# If an executable scripts/test.sh exists on a branch, it is run after each
# merge; a failing test halts the cascade on that branch.

set -euo pipefail

GIT_DIR="$(git rev-parse --git-dir)"
STATE_FILE="$GIT_DIR/CASCADE_STATE"
DRY_RUN=0
PUSH=0
MODE="start"
START_BRANCH=""

die() { echo "cascade: $*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --continue) MODE="continue" ;;
        --abort)    MODE="abort" ;;
        --dry-run)  DRY_RUN=1 ;;
        --push)     PUSH=1 ;;
        -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        ch[0-9][0-9]) START_BRANCH="$arg" ;;
        *) die "unknown argument: $arg" ;;
    esac
done

chapter_branches() {
    git for-each-ref --format='%(refname:short)' 'refs/heads/ch[0-9][0-9]' | sort
}

run_tests() {
    if [ -x scripts/test.sh ]; then
        echo "cascade: running tests on $1"
        ./scripts/test.sh || die "tests failed on $1 — fix, commit on $1, then rerun cascade from $1"
    fi
}

merge_step() {
    local prev="$1" next="$2"
    echo "cascade: merging $prev into $next"
    if [ "$DRY_RUN" -eq 1 ]; then
        return 0
    fi
    git switch --quiet "$next"
    if ! git merge --no-edit "$prev"; then
        save_state "$prev" "$next"
        cat >&2 <<EOF

cascade: merge conflict merging $prev into $next.
Resolve the conflicts, conclude the merge (git merge --continue),
then resume with: scripts/cascade.sh --continue
EOF
        exit 1
    fi
    run_tests "$next"
    if [ "$PUSH" -eq 1 ]; then
        git push origin "$next"
    fi
}

save_state() {
    printf 'PREV=%s\nNEXT=%s\n' "$1" "$2" > "$STATE_FILE"
}

case "$MODE" in
abort)
    git merge --abort 2>/dev/null || true
    rm -f "$STATE_FILE"
    echo "cascade: aborted."
    exit 0
    ;;
continue)
    [ -f "$STATE_FILE" ] || die "no cascade in progress (no state file)"
    # shellcheck disable=SC1090
    . "$STATE_FILE"
    [ -e "$GIT_DIR/MERGE_HEAD" ] && die "merge on $NEXT not concluded yet — run: git merge --continue"
    git diff --quiet && git diff --cached --quiet || die "uncommitted changes present — conclude the merge first"
    rm -f "$STATE_FILE"
    git switch --quiet "$NEXT"
    run_tests "$NEXT"
    if [ "$PUSH" -eq 1 ]; then git push origin "$NEXT"; fi
    START_BRANCH="$NEXT"
    ;;
start)
    git diff --quiet && git diff --cached --quiet || die "working tree not clean"
    [ -e "$GIT_DIR/MERGE_HEAD" ] && die "a merge is in progress — resolve it or run --abort"
    if [ -z "$START_BRANCH" ]; then
        START_BRANCH="$(git branch --show-current)"
        case "$START_BRANCH" in
            ch[0-9][0-9]) ;;
            *) die "current branch '$START_BRANCH' is not a chapter branch; pass one (e.g. ch03)" ;;
        esac
    fi
    git show-ref --verify --quiet "refs/heads/$START_BRANCH" || die "branch $START_BRANCH does not exist"
    ;;
esac

# Resolve each recurring cascade conflict only once.
git config rerere.enabled true
git config rerere.autoUpdate true

PREV="$START_BRANCH"
FOUND=0
for BR in $(chapter_branches); do
    if [ "$FOUND" -eq 1 ]; then
        merge_step "$PREV" "$BR"
        PREV="$BR"
    elif [ "$BR" = "$START_BRANCH" ]; then
        FOUND=1
    fi
done

[ "$FOUND" -eq 1 ] || die "branch $START_BRANCH not found among chapter branches"
echo "cascade: done (through $PREV)."
