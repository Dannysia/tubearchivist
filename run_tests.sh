#!/bin/bash

# run the backend test suite and linters in a throwaway container, with
# its own redis, from the deployed image with this tree mounted on /src.
#
#   ./run_tests.sh                 run the whole suite
#   ./run_tests.sh backend/common  run a subset, args go to pytest
#   ./run_tests.sh -k history -v   any pytest flags work
#   ./run_tests.sh lint            black, isort, flake8, codespell check
#   ./run_tests.sh format          let black and isort rewrite the files
#
# notes:
#
# - test_is_shorts makes a live request to youtube.com and fails without
#   outbound access.
# - dev dependency versions are pinned to requirements-dev.txt and
#   .pre-commit-config.yaml, keep them in sync.
# - lint is narrower than CI, which runs pre-commit: end-of-file fixer,
#   eslint and prettier have no equivalent here. run those from frontend/
#   as npm run lint and npx prettier --check .

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
CODESPELL_VERSION="2.4.2"


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


function run_codespell {
    echo "==> codespell"
    # the files pre-commit would hand the hook, plus untracked ones
    git -C "$REPO_DIR" ls-files -z --cached --others --exclude-standard \
        | grep -zvE '\.svg$|/migrations/|^frontend/package-lock\.json$' \
        | docker run --rm -i -e PYTHONDONTWRITEBYTECODE=1 \
            -v "$REPO_DIR":/src -w /src "$IMAGE" sh -c "
            pip install --quiet --no-input \
                'codespell==$CODESPELL_VERSION' >/dev/null 2>&1 </dev/null
            set -e
            xargs -0 python -m codespell_lib
        "
    echo "==> codespell clean"
}


function run_format {
    echo "==> black and isort, rewriting"
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
    # run from the repo root, conftest.py chdirs to rootdir/backend
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
        run_codespell
        ;;
    format)
        run_format
        ;;
    *)
        run_pytest "$@"
        ;;
esac

exit 0
