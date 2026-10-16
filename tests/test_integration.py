"""End-to-end test of the k8s CLI against a kind cluster seeded with assets/seed.yaml.

Skipped unless K8S_ENV_IT=1. Requires docker, kind and kubectl:

    K8S_ENV_IT=1 python3 -m unittest discover -s tests -v

The CLI runs with a sandboxed HOME, KUBECONFIG and PATH (kubectl only), so no real
cluster, kubeconfig or ~/.k8s-env is touched. The cluster is deleted at the end;
set K8S_ENV_IT_KEEP=1 to keep it, and the next run reuses it.
"""
from __future__ import annotations

import contextlib
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, 'k8s-env')
CLUSTER = 'k8s-env-it'
CONTEXT = f'kind-{CLUSTER}'
TMP = KUBECONFIG = ''
ENV: dict[str, str] = {}


def _sh(*cmd: str) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f'{" ".join(cmd)} failed:\n{proc.stderr}')
    return proc.stdout


def setUpModule() -> None:  # pylint: disable=invalid-name
    global TMP, KUBECONFIG  # pylint: disable=global-statement
    if not os.environ.get('K8S_ENV_IT'):
        raise unittest.SkipTest('set K8S_ENV_IT=1 to run')
    # Cleanups are registered as resources are created, so they also run if setup fails
    # midway; they run in reverse order (cluster deletion needs KUBECONFIG inside TMP).
    TMP = tempfile.mkdtemp(prefix='k8s-env-it-')
    unittest.addModuleCleanup(shutil.rmtree, TMP, ignore_errors=True)
    KUBECONFIG = os.path.join(TMP, 'kubeconfig')
    if not os.environ.get('K8S_ENV_IT_KEEP'):
        unittest.addModuleCleanup(_sh, 'kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', KUBECONFIG)
    # Reuse a kept cluster (K8S_ENV_IT_KEEP); kind writes only to our kubeconfig, never ~/.kube/config
    if CLUSTER not in _sh('kind', 'get', 'clusters').split():
        _sh('kind', 'create', 'cluster', '--name', CLUSTER, '--kubeconfig', KUBECONFIG)
    _sh('kind', 'export', 'kubeconfig', '--name', CLUSTER, '--kubeconfig', KUBECONFIG)
    _sh('kubectl', '--kubeconfig', KUBECONFIG, 'apply', '-f', os.path.join(ROOT, 'assets', 'seed.yaml'))
    _sh('kubectl', '--kubeconfig', KUBECONFIG, 'wait', 'deployment', '--all', '--all-namespaces',
        '--for=condition=Available', '--timeout=180s')

    # PATH holds only kubectl, so discovery finds just this cluster's kubectl context
    bin_dir, home = os.path.join(TMP, 'bin'), os.path.join(TMP, 'home')
    os.mkdir(bin_dir)
    os.mkdir(home)
    os.symlink(shutil.which('kubectl'), os.path.join(bin_dir, 'kubectl'))
    ENV.update(HOME=home, KUBECONFIG=KUBECONFIG, PATH=bin_dir)


@contextlib.contextmanager
def _cli(args: tuple[str, ...], stdin: str, env: dict[str, str] | None = None):
    # The CLI gets a pty as stdin (pickers and prompts require a terminal) with `stdin`
    # typed ahead. It runs in its own process group so child kubectl processes stop with it.
    master, slave = os.openpty()
    os.write(master, stdin.encode())
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, ENTRY, *args], stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**ENV, **(env or {})}, start_new_session=True,
    )
    try:
        yield proc
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
        proc.stdout.close()
        os.close(master)
        os.close(slave)


def k8s(*args: str, stdin: str = '', check: bool = True, env: dict[str, str] | None = None) -> str:
    with _cli(args, stdin, env) as proc:
        out = proc.communicate(timeout=120)[0].decode()
    if check and proc.returncode:
        raise AssertionError(f'k8s {" ".join(args)} exited {proc.returncode}:\n{out}')
    return out


@contextlib.contextmanager
def k8s_running(*args: str, until: str, stdin: str = ''):
    # For commands that run until stopped (port-forward, logs -f): yields once `until` shows up
    with _cli(args, stdin) as proc:
        out = b''
        while until.encode() not in out:
            ready, _, _ = select.select([proc.stdout], [], [], 30)
            chunk = os.read(proc.stdout.fileno(), 4096) if ready else b''
            if not chunk:
                raise AssertionError(f'k8s {" ".join(args)}: "{until}" never appeared:\n{out.decode()}')
            out += chunk
        yield out.decode()


def _active_env_file() -> str:
    with open(os.path.join(ENV['HOME'], '.k8s-env', 'active'), encoding='utf-8') as f:
        return f.read()


class TestCli(unittest.TestCase):
    def test_main_flow(self) -> None:
        # One scenario; each step builds on the state the previous one left
        self._add_envs()
        self._inspect()
        self._overrides()
        self._actions()
        self._manage_envs()

    def _add_envs(self) -> None:
        self.assertIn('No envs saved', k8s('env'))

        # env add: discovery lists the namespaces of the only kubectl context, alphabetically
        # kind's own local-path-storage namespace comes first
        out = k8s('env', 'add', 'shop/dev', stdin='3\n')
        self.assertIn(f'k8s @ {CONTEXT}\n', out)
        self.assertIn('2) payments', out)
        self.assertIn('3) shop', out)
        self.assertIn(f'Added shop/dev: k8s @ {CONTEXT} / shop', out)
        self.assertIn('Added payments/dev', k8s('env', 'add', 'payments/dev', stdin='2\n'))

        out = k8s('env')
        self.assertIn('payments\n  dev', out)
        self.assertIn(f'k8s @ {CONTEXT} / payments (active)', out)
        self.assertIn('Switched to shop/dev', k8s('env', 'set', 'shop/dev'))

    def _inspect(self) -> None:
        # Inspection against the active env
        out = k8s('pods')
        self.assertIn(f'[shop/dev] k8s @ {CONTEXT} / shop', out)
        self.assertIn('storefront-', out)
        self.assertIn('cart-', out)
        self.assertIn('storefront', k8s('services'))
        self.assertIn('payments', k8s('namespaces'))
        self.assertIn('Namespace shop:', k8s('status'))
        self.assertIn('ca.crt', k8s('configmaps', stdin='1\n'))
        self.assertIn('Replicas:', k8s('describe', 'deployment/storefront'))
        out = k8s('describe', 'storefront', stdin='4\n')    # 2 pods, then deployment, then service
        self.assertIn('4) service/storefront', out)
        self.assertIn('Endpoints:', out)
        self.assertIn('cart: checkout ok', k8s('logs', 'cart', '--tail', '3'))
        self.assertIn('Recent events in shop', k8s('events'))
        self.assertIn('Secrets in shop', k8s('secrets'))
        self.assertIn('CronJobs in shop', k8s('cronjobs'))

    def _overrides(self) -> None:
        # One-command overrides: -e and $K8S_ENV pick another env, -n another namespace
        self.assertIn('ledger-', k8s('-e', 'payments/dev', 'pods'))
        self.assertIn('ledger-', k8s('pods', env={'K8S_ENV': 'payments/dev'}))
        self.assertIn('ledger-', k8s('-n', 'payments', 'pods'))
        self.assertIn('No env named: nope', k8s('-e', 'nope', 'pods', check=False))

    def _actions(self) -> None:
        self.assertIn('storefront-', k8s('exec', 'storefront', '--', 'cat', '/etc/hostname', stdin='1\n'))
        with k8s_running('-e', 'payments/dev', 'logs', '-f', until='ledger: posted'):
            pass
        with k8s_running('pf', 'storefront', stdin='18080\n', until='Forwarding from'):
            with urllib.request.urlopen('http://127.0.0.1:18080', timeout=10) as resp:
                self.assertEqual(200, resp.status)
        self.assertIn('pf.storefront.80=18080', _active_env_file())
        self.assertIn('Done', k8s('restart', 'cart', stdin='1\n'))

    def _manage_envs(self) -> None:
        # Re-adding an existing env (no name given) keeps its name and port-forwards; names stay unique
        self.assertIn('Added shop/dev', k8s('env', 'add', stdin='3\n\n'))
        self.assertIn('pf.storefront.80=18080', _active_env_file())
        self.assertIn('Name already in use: shop/dev', k8s('env', 'add', 'shop/dev', stdin='2\n', check=False))

        # env kubectl points the (sandboxed) kubeconfig at an env and activates it
        self.assertIn('kubectl now using context', k8s('env', 'kubectl', 'payments/dev', stdin='y\n'))
        self.assertEqual('payments', _sh('kubectl', '--kubeconfig', KUBECONFIG, 'config', 'view',
                                         '--minify', '-o', 'jsonpath={..namespace}'))
        # env rename acts on the effective env: -e targets a non-active one, otherwise the active one
        self.assertIn('Renamed shop/dev to shop/main', k8s('-e', 'shop/dev', 'env', 'rename', 'shop/main'))
        self.assertIn('Cleared name on payments/dev', k8s('env', 'rename', stdin='\n'))
        # Deleting the (now unnamed, active) payments env: picker lists ungrouped envs first
        out = k8s('env', 'del', stdin='1\n')
        self.assertIn(f'Deleted k8s-{CONTEXT}-payments', out)
        self.assertIn('Switched to shop/main', out)
        self.assertIn('env kubectl', k8s('--help'))
