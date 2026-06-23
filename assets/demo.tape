# VHS tape for the k8s-env README demo.  Regenerate with: assets/record.sh
#
# record.sh seeds an isolated minikube cluster and exports a sandboxed
# HOME / KUBECONFIG / PATH (as K8S_DEMO_* env vars) so nothing real is
# recorded.  The hidden setup block below applies them before recording.
#
# Framerate is kept low: at this resolution VHS drops frames at the default
# (~50) framerate, which compresses every Sleep and ruins the read timing.

Output assets/demo.gif

Set Shell bash
Set FontSize 40
Set Width 3200
Set Height 1900
Set Padding 50
Set Framerate 10
Set Theme "Catppuccin Mocha"
Set TypingSpeed 25ms

# Demo: add a context, list pods, tail filtered logs, exec into a pod,
# port-forward a service and curl it, glance at status, then show help.

# --- sandbox setup (not shown) ----------------------------------------------
Hide
Type 'export HOME="$K8S_DEMO_HOME" KUBECONFIG="$K8S_DEMO_KC" PATH="$K8S_DEMO_PATH"'  Enter
Type 'cd "$K8S_DEMO_WORK"'  Enter
Type `export PS1='\[\e[38;5;213m\]demo\[\e[0m\] \[\e[2m\]❯\[\e[0m\] '`  Enter
Type "clear"  Enter
Show
Sleep 500ms

# --- 1) add a context: pick a namespace, give it a slug ---------------------
Type `k8s ctx add  # scan all clusters, pick a namespace, pin it as a context`  Sleep 1.5s  Enter
Sleep 3s
Type "2"                    Sleep 400ms  Enter
Sleep 1s
Type "shop"                 Sleep 400ms  Enter
Sleep 4s

# --- 2) list pods -----------------------------------------------------------
Hide
Type "clear"  Enter
Show
Type `k8s pods  # pods in the active namespace — no --context, no -n, it just knows`  Sleep 1.5s  Enter
Sleep 4.5s

# --- 3) logs, filtered to the cart pod --------------------------------------
Enter  Sleep 800ms
Type `k8s logs cart --tail 8  # tail logs by fuzzy name — say "cart", skip the 20-char pod id`  Sleep 1.5s  Enter
Sleep 4.5s

# --- 4) exec into a pod (filtered), look around, exit -----------------------
Hide
Type "clear"  Enter
Show
Type `k8s exec storefront  # shell into a pod by fuzzy name — asks if several match`  Sleep 1.5s  Enter
Sleep 2s
Type "1"                    Sleep 400ms  Enter
Sleep 1.5s
Type `ls  # now we're inside the container`  Sleep 1s  Enter
Sleep 2.5s
Enter  Sleep 800ms
Type `exit  # ...and back to the host`  Sleep 1s  Enter
Sleep 2s

# --- 5) port-forward, then curl through it ----------------------------------
Hide
Type "clear"  Enter
Show
Type `k8s pf storefront  # port-forward a service by name — ports figured out for you`  Sleep 1.5s  Enter
Sleep 1.5s
Type "8080"                 Sleep 400ms  Enter
Sleep 2s
Ctrl+Z
Sleep 1s
Enter  Sleep 800ms
Type `bg  # background it so we keep the terminal`  Sleep 1s  Enter
Sleep 1.5s
Enter  Sleep 800ms
Type `curl -sI localhost:8080 | head -4  # and nginx is right there on the forwarded port`  Sleep 1.5s  Enter
Sleep 3s
Enter  Sleep 800ms
Type `kill %1  # stop the forward — done`  Sleep 1s  Enter
Sleep 2s

# --- 6) status: one-glance health -------------------------------------------
Hide
Type "clear"  Enter
Show
Type `k8s status  # one-glance health — nodes, pods, deployments, services`  Sleep 1.5s  Enter
Sleep 4.5s

# --- 7) help: the whole toolkit ---------------------------------------------
Hide
Type "clear"  Enter
Show
Type `k8s --help  # the whole toolkit, one screen`  Sleep 1.5s  Enter
Sleep 5.5s
