#!/usr/bin/env bash
# bootstrap/lib/sandbox_paths.sh — pure path helpers for sandbox-policy generation (#1221).
# Sourced by hos_install.sh (and, in a future round, bootstrap/validate_setup.sh). No
# top-level side effects; safe to re-source.

# _hos_claude_project_state <home> <target_repo>
# Echoes Claude Code's project-state dir for <target_repo> under <home>. Returns 1
# (echoing nothing) when it cannot be derived safely — caller must treat that as
# "unresolved", never guess a fallback.
_hos_claude_project_state() {
  local home="${1:-}" repo="${2:-}"
  [[ -n "$home" && -n "$repo" ]] || return 1
  [[ "$repo" == /* ]] || return 1
  repo="${repo%/}"; [[ -n "$repo" && "$repo" != "/" ]] || return 1
  home="${home%/}"; [[ -n "$home" ]] || return 1
  [[ "$repo" =~ ^[A-Za-z0-9/-]+$ ]] || return 1
  printf '%s\n' "${home}/.claude/projects/${repo//\//-}"
}

# _hos_path_is_ancestor_or_equal <candidate> <other>
# 0 if candidate == other, or candidate is a prefix directory of other.
_hos_path_is_ancestor_or_equal() {
  local a="${1%/}" b="${2%/}"
  [[ -n "$a" && -n "$b" ]] || return 1
  [[ "$a" == "$b" || "$b" == "$a"/* ]]
}
