#!/usr/bin/env bash
# bootstrap/lib/role_clone_check.sh — role/clone pairing cross-check (#1409)
#
# bin/hos-worker and bin/hos-overseer each fix a role (by which script you
# invoke) and derive REPO_ROOT from their own location on disk, but never
# cross-check the pairing against the registry (~/.config/hos/projects.conf).
# A launcher run from the wrong clone (e.g. `hos-worker` typed while sitting
# in a project's registered Overseer clone) authenticates fine — the bot
# token matches the role the *script* asserts, not the clone it's running
# in — and starts a session with a silent role/location mismatch.
#
# _hos_check_role_clone fails loudly only for the concrete case the registry
# can actually prove wrong: this exact clone path is registered as the
# *other* role's root for some project. An unregistered clone (first install,
# predates registration) is not an error here — same fail-open convention
# bin/hos-human already uses for its own registry lookup (#1407).
#
# Usage (after REPO_ROOT is resolved, before auth):
#   # shellcheck source=bootstrap/lib/role_clone_check.sh
#   source "$REPO_ROOT/bootstrap/lib/role_clone_check.sh"
#   _hos_check_role_clone worker "$REPO_ROOT" || exit 1
_hos_check_role_clone() {
  local role="$1" repo_root="$2"
  local other_role
  if [[ "$role" == "worker" ]]; then
    other_role="overseer"
  else
    other_role="worker"
  fi

  local projects_conf="${HOME}/.config/hos/projects.conf"
  [[ -f "$projects_conf" ]] || return 0

  local repo_root_norm="${repo_root%/}"
  local key val prefix val_norm
  while IFS='=' read -r key val; do
    [[ "$key" =~ ^([A-Za-z0-9_]+)_${other_role}_root$ ]] || continue
    prefix="${BASH_REMATCH[1]}"
    val_norm="${val%/}"
    if [[ -n "$val_norm" && "$val_norm" == "$repo_root_norm" ]]; then
      echo "hos-${role}: role/clone mismatch — $repo_root_norm is registered as" \
        "'${prefix}_${other_role}_root' in $projects_conf, not '${prefix}_${role}_root'." \
        "Run hos-${other_role} here instead, or fix the registry." >&2
      return 1
    fi
  done < <(grep -E "^[A-Za-z0-9_]+_${other_role}_root=" "$projects_conf")

  return 0
}
