# syntax=docker/dockerfile:1
#
# Lint, test, build and integration-test k8s-env with uv.
#
#   docker build -t k8s-env .                         # lint + unit tests + wheel + integration image
#   docker build --target dist -o dist .              # export the wheel to ./dist
#   docker run --rm --network host \
#     -v /var/run/docker.sock:/var/run/docker.sock k8s-env   # integration test (kind on the host's docker)
#
# The integration stage runs kind against the host's docker daemon (mounted socket).
# --network host lets kubectl in the container reach the kind API server and the
# port-forward the test opens, both bound to the host's 127.0.0.1.

# =============================================================================
# base: uv + Python
# =============================================================================
FROM ghcr.io/astral-sh/uv:0.12.21-python3.12-trixie-slim AS base

ENV UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /src

# =============================================================================
# deps: dev dependencies from the lockfile (cached until pyproject/uv.lock change)
# =============================================================================
FROM base AS deps

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# =============================================================================
# test: lint + unit tests (integration tests are deselected by default)
# =============================================================================
FROM deps AS test

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

RUN --mount=type=cache,target=/root/.cache/uv \
    uvx --with pytest pylint k8s_env/ tests/

# Exit code 5 means "no tests collected": fine while every test is an integration test
RUN uv run pytest || [ $? -eq 5 ]

# =============================================================================
# build: wheel + sdist into /src/dist
# =============================================================================
FROM test AS build

RUN --mount=type=cache,target=/root/.cache/uv \
    uv build

# =============================================================================
# dist: just the artifacts, for `docker build --target dist -o dist .`
# =============================================================================
FROM scratch AS dist

COPY --from=build /src/dist/ /

# =============================================================================
# integration (default): docker CLI + kind + kubectl, runs the kind-based test
# =============================================================================
FROM build AS integration

ARG TARGETARCH
ARG KIND_VERSION=v0.33.0
ARG KUBECTL_VERSION=v1.37.0

# Docker CLI only; the daemon is the host's, via the mounted socket
COPY --from=docker:29.8.2-cli /usr/local/bin/docker /usr/local/bin/docker

# kind and kubectl release binaries, verified against their published checksums
ADD --chmod=755 https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-${TARGETARCH} \
    /usr/local/bin/kind
ADD https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-${TARGETARCH}.sha256sum \
    /tmp/kind.sha256sum
ADD --chmod=755 https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl \
    /usr/local/bin/kubectl
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl.sha256 \
    /tmp/kubectl.sha256
RUN echo "$(cut -d' ' -f1 /tmp/kind.sha256sum)  /usr/local/bin/kind" | sha256sum -c - \
 && echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum -c - \
 && rm /tmp/kind.sha256sum /tmp/kubectl.sha256

CMD ["uv", "run", "pytest", "-m", "integration", "-v"]
