from __future__ import annotations
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from k8s_env.k8s import KubeCtl
    from k8s_env.service import Env

ENV_FILE = '.k8s-env'

SYSTEM_NAMESPACES = frozenset({
    'kube-system', 'kube-public', 'kube-node-lease', 'default',
})

_VALIDATORS = {
    'tool':      re.compile(r'^(microk8s|microk8s-ssh|minikube|minikube-ssh|k8s)$'),
    'context':   re.compile(r'^[A-Za-z0-9._:@/-]+$'),
    'namespace': re.compile(r'^[a-z0-9][-a-z0-9]*[a-z0-9]?$'),
    'host':      re.compile(r'^[A-Za-z0-9._@:/-]+$'),
}


def validate(field_name: str, value: str) -> None:
    pattern = _VALIDATORS.get(field_name)
    if not pattern or not pattern.match(value):
        raise ValueError(f"Invalid {field_name}: '{value}'")


def is_available(binary: str) -> bool:
    return shutil.which(binary) is not None


@dataclass
class AppContext:
    env: Env | None = None
    kubectl: KubeCtl | None = None
    ns_override: str = ''
    env_path: str = ENV_FILE

    @property
    def namespace(self) -> str:
        if self.ns_override:
            return self.ns_override
        if self.env and self.env.namespace:
            return self.env.namespace
        raise SystemExit('No namespace set. Run: k8s-env use')
