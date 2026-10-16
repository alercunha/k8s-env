#!/usr/bin/env bash
# Regenerate assets/demo.gif from assets/demo.tape.
#
# Spins up an isolated kind cluster, seeds synthetic namespaces, and runs
# VHS against a sandboxed HOME/KUBECONFIG/PATH so no real cluster, context, or
# ~/.k8s-env is ever touched or recorded.
#
# Requirements: docker, kind, kubectl, vhs, ttyd, ffmpeg.
set -euo pipefail

# Kept short: the node name (<cluster>-control-plane) shows in
# `kubectl get pods -o wide` — a long one would overflow the GIF width.
CLUSTER=kdemo
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

for bin in docker kind kubectl vhs ttyd ffmpeg; do
  command -v "$bin" >/dev/null || { echo "missing dependency: $bin" >&2; exit 1; }
done

TMP="$(mktemp -d)"
KC="$TMP/kubeconfig"

# kind reads and writes only $KC, never ~/.kube/config
cleanup() {
  echo "==> cleaning up: deleting kind cluster $CLUSTER"
  kind delete cluster --name "$CLUSTER" --kubeconfig "$KC" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "==> creating kind cluster: $CLUSTER"
kind create cluster --name "$CLUSTER" --kubeconfig "$KC" >/dev/null

echo "==> seeding demo namespaces"
kubectl --kubeconfig "$KC" apply -f assets/seed.yaml >/dev/null
kubectl --kubeconfig "$KC" wait deployment --all --all-namespaces --for=condition=Available --timeout=180s

kubectl --kubeconfig "$KC" config rename-context "kind-$CLUSTER" demo >/dev/null

# Record against the working-tree code, not whatever `k8s` is installed on PATH.
# The shim is named `k8s` so the basename shown in banners/help stays `k8s`.
# PATH holds only this bin, so discovery sees just the demo context.
BIN="$TMP/bin"; mkdir -p "$BIN"
cat >"$BIN/k8s" <<EOF
#!$(command -v python3)
import sys
sys.path.insert(0, "$REPO_ROOT")
from k8s_env.cli import main
main()
EOF
chmod +x "$BIN/k8s"
ln -s "$(command -v kubectl)" "$(command -v clear)" "$BIN/"

export K8S_DEMO_HOME="$TMP/home";   mkdir -p "$K8S_DEMO_HOME"
export K8S_DEMO_KC="$KC"
export K8S_DEMO_PATH="$BIN"

echo "==> recording (vhs assets/demo.tape -> assets/demo.gif)"
vhs assets/demo.tape

echo "==> done: assets/demo.gif"
