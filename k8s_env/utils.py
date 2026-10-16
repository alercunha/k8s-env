from __future__ import annotations

import os
import re
import shutil
import sys

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.k8s-env')
ENV_VAR = 'K8S_ENV'
CMD = os.path.basename(sys.argv[0])

SYSTEM_NAMESPACES = frozenset({
    'kube-system', 'kube-public', 'kube-node-lease', 'default',
})

_VALIDATORS = {
    'tool':      re.compile(r'^(microk8s|minikube|k8s)$'),
    'context':   re.compile(r'^[A-Za-z0-9._:@-]+$'),
    'namespace': re.compile(r'^[a-z0-9][-a-z0-9]*[a-z0-9]?$'),
    'host':      re.compile(r'^[A-Za-z0-9._@:-]+$'),
    'name':      re.compile(r'^[a-z0-9][-_a-z0-9]*(/[a-z0-9][-_a-z0-9]*)?$'),
}


def validate(field_name: str, value: str) -> None:
    pattern = _VALIDATORS.get(field_name)
    if not pattern or not pattern.match(value):
        raise ValueError(f"Invalid {field_name}: '{value}'")


def is_available(binary: str) -> bool:
    return shutil.which(binary) is not None
