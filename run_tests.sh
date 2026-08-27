#!/bin/bash

# run the backend test suite and linters on this host.
#
# there is no python env on the host and the running tubearchivist
# container has no dev dependencies, so everything runs in a throwaway
# container built from the deployed image with this working tree bind
# mounted over /src. the running stack is never touched.
#
#   ./run_tests.sh                 run the whole suite
#   ./run_tests.sh backend/common  run a subset, args go to pytest
#   ./run_tests.sh -k history -v   any pytest flags work
#   ./run_tests.sh lint            black, isort and flake8 check only
#   ./run_tests.sh format          let black and isort rewrite the files
#
# notes:
#
# - a reachable redis is required or three test modules fail during
#   collection (downscale test_views, test_worker_views and task
#   test_config_schedule import it at module level). this script starts
#   its own throwaway redis rather than using archivist-redis, so the
#   live instance's keys are never touched.
# - elasticsearch is mocked in the tests, ES_URL only has to be set.
# - test_is_shorts in common/tests/test_src/test_helper.py makes a live
#   request to youtube.com and fails without outbound access. it is
#   unrelated to any local change.
# - dev dependency versions are pinned to requirements-dev.txt and
#   .pre-commit-config.yaml, keep them in sync.
# - the container runs as root over the bind mount, so any file it writes
#   comes back owned by root and unwritable on the host. that is what
#   PYTHONDONTWRITEBYTECODE is for: no __pycache__, nothing to chown.
#   format is the one mode that rewrites tracked files, so it runs as the
#   host user instead, with HOME pointed somewhere it can pip install.

set -euo pipefail

IMAGE="tubearchivist:downscale-dev"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETWORK="ta-test-tmp"
REDIS="ta-test-redis"

PYTEST_VERSION="9.1.1"
PYTEST_DJANGO_VERSION="4.14.0"
BLACK_VERSION="26.3.1"
ISORT_VERSION="8.0.1"
FLAKE8_VERSION="7.3.0"


function require_image {
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "no $IMAGE image, build it first with ./local_deploy.sh build"
        exit 1
    fi
}


function cleanup {
    docker rm -f "$REDIS" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
}


function run_lint {
    echo "==> black, isort, flake8"
    docker run --rm -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$REPO_DIR":/src -w /src "$IMAGE" sh -c "
        pip install --quiet --no-input \
            'black==$BLACK_VERSION' \
            'isort==$ISORT_VERSION' \
            'flake8==$FLAKE8_VERSION' >/dev/null 2>&1
        set -e
        # migrations are excluded globally in .pre-commit-config.yaml
        python -m black --line-length=79 --check \
            --extend-exclude '/migrations/' backend
        python -m isort --profile black -l 79 --check-only \
            --skip-glob '*/migrations/*' backend
        python -m flake8 --max-complexity=10 --max-line-length=79 \
            --extend-exclude '*/migrations/*' backend
    "
    echo "==> lint clean"
}


function run_format {
    echo "==> black and isort, rewriting"
    # as the caller, not root: this is the one mode that writes back to
    # the working tree, and root owned source is unwritable afterwards
    docker run --rm --user "$(id -u):$(id -g)" \
        -e HOME=/tmp \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -v "$REPO_DIR":/src -w /src "$IMAGE" sh -c "
        pip install --quiet --no-input --user \
            'black==$BLACK_VERSION' \
            'isort==$ISORT_VERSION' >/dev/null 2>&1
        set -e
        python -m black --line-length=79 \
            --extend-exclude '/migrations/' backend
        python -m isort --profile black -l 79 \
            --skip-glob '*/migrations/*' backend
    "
    echo "==> formatted, run ./run_tests.sh lint for flake8"
}


function run_pytest {
    trap cleanup EXIT

    echo "==> starting throwaway redis"
    docker network create "$NETWORK" >/dev/null 2>&1 || true
    docker rm -f "$REDIS" >/dev/null 2>&1 || true
    docker run -d --rm --name "$REDIS" --network "$NETWORK" redis >/dev/null

    echo "==> running pytest"
    # run from the repo root, backend/common/tests/conftest.py chdirs to
    # rootdir/backend itself
    docker run --rm --network "$NETWORK" \
        -v "$REPO_DIR":/src -w /src \
        -e PYTHONDONTWRITEBYTECODE=1 \
        -e TA_USERNAME=test \
        -e TA_PASSWORD=test \
        -e ELASTIC_PASSWORD=test \
        -e REDIS_CON="redis://$REDIS:6379" \
        -e ES_URL=http://127.0.0.1:9200 \
        "$IMAGE" sh -c "
            pip install --quiet --no-input \
                'pytest==$PYTEST_VERSION' \
                'pytest-django==$PYTEST_DJANGO_VERSION' >/dev/null 2>&1
            exec python -m pytest ${*:-backend}
        "
}


require_image

case "${1:-}" in
    lint)
        run_lint
        ;;
    format)
        run_format
        ;;
    *)
        run_pytest "$@"
        ;;
esac

exit 0
