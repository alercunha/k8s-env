#!/usr/bin/env bash
# Regenerate assets/demo.gif from assets/demo.tape.
#
# Spins up an isolated minikube profile, seeds synthetic namespaces, and runs
# VHS against a sandboxed HOME/KUBECONFIG/PATH so no real cluster, context, or
# trust state is ever touched or recorded.
#
# Requirements: minikube, kubectl, vhs, ttyd, ffmpeg.
set -euo pipefail

# Kept short: the minikube profile name becomes the k8s node name, which shows
# in `kubectl get pods -o wide` — a long node name would overflow the GIF width.
PROFILE=kdemo
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

for bin in minikube kubectl vhs ttyd ffmpeg; do
  command -v "$bin" >/dev/null || { echo "missing dependency: $bin" >&2; exit 1; }
done

# `minikube start/delete` rewrites the real ~/.kube/config (contexts and
# current-context), even though recording itself uses an isolated KUBECONFIG.
# Snapshot it and the active context up front, and restore on exit no matter
# how we leave — so regenerating the GIF never disturbs the user's clusters.
KUBECONFIG_FILE="${KUBECONFIG:-$HOME/.kube/config}"
SNAPSHOT="$(mktemp)"
TMP="$(mktemp -d)"
[ -f "$KUBECONFIG_FILE" ] && cp "$KUBECONFIG_FILE" "$SNAPSHOT"
PREV_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"

cleanup() {
  echo "==> cleaning up: deleting profile $PROFILE and restoring kubeconfig"
  minikube delete -p "$PROFILE" >/dev/null 2>&1 || true
  [ -s "$SNAPSHOT" ] && cp "$SNAPSHOT" "$KUBECONFIG_FILE"
  [ -n "$PREV_CONTEXT" ] && kubectl config use-context "$PREV_CONTEXT" >/dev/null 2>&1 || true
  rm -f "$SNAPSHOT"
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "==> starting isolated minikube profile: $PROFILE"
minikube start -p "$PROFILE" --driver=docker >/dev/null

echo "==> seeding demo namespaces"
kubectl --context "$PROFILE" apply -f assets/seed.yaml >/dev/null
kubectl --context "$PROFILE" -n shop     rollout status deploy/storefront --timeout=120s
kubectl --context "$PROFILE" -n shop     rollout status deploy/cart       --timeout=120s
kubectl --context "$PROFILE" -n payments rollout status deploy/ledger     --timeout=120s

# Isolated kubeconfig containing only this cluster, context renamed to "demo".
KC="$TMP/kubeconfig"
kubectl --context "$PROFILE" config view --flatten --minify >"$KC"
kubectl --kubeconfig "$KC" config rename-context "$PROFILE" demo >/dev/null
kubectl --kubeconfig "$KC" config use-context demo >/dev/null

# Record against the working-tree code, not whatever `k8s` is installed on PATH.
# The shim is named `k8s` so the basename shown in banners/help stays `k8s`.
SHIM="$TMP/bin"; mkdir -p "$SHIM"
cat >"$SHIM/k8s" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$REPO_ROOT")
from k8s_env.cli import main
main()
EOF
chmod +x "$SHIM/k8s"

# Sandbox: throwaway HOME (isolates trust dir) + empty working dir + a PATH
# that puts the shim first and excludes /snap/bin so microk8s is not discovered.
export K8S_DEMO_HOME="$TMP/home";   mkdir -p "$K8S_DEMO_HOME"
export K8S_DEMO_WORK="$TMP/work";   mkdir -p "$K8S_DEMO_WORK"
export K8S_DEMO_KC="$KC"
export K8S_DEMO_PATH="$SHIM:/usr/local/bin:/usr/bin:/bin"

echo "==> recording (vhs assets/demo.tape -> assets/demo.gif)"
vhs assets/demo.tape

echo "==> done: assets/demo.gif"
