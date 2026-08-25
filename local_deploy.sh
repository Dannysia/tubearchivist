#!/bin/bash

# build and deploy this working tree to the local TA instance on this host.
#
# deploy.sh is upstream's: it rsyncs to remote hosts and pushes to docker
# hub. this one never leaves the machine.
#
#   ./local_deploy.sh           build, tag a rollback point, deploy, verify
#   ./local_deploy.sh build     build the image only
#   ./local_deploy.sh rollback  put the previous image back
#   ./local_deploy.sh status    what is running right now

set -euo pipefail

IMAGE="tubearchivist:downscale-dev"
ROLLBACK="tubearchivist:rollback-local"
COMPOSE_DIR="$HOME/tubearchivist-deploy"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="tubearchivist"


function require_compose {
    if [[ ! -f "$COMPOSE_DIR/docker-compose.yml" ]]; then
        echo "no docker-compose.yml in $COMPOSE_DIR"
        exit 1
    fi
}


function build {
    echo "==> building $IMAGE from $REPO_DIR"
    docker build -t "$IMAGE" "$REPO_DIR"
}


function tag_rollback {
    # tag whatever is running now, so a bad deploy is one command to undo.
    # skipped on a first run when nothing is deployed yet
    if docker image inspect "$IMAGE" >/dev/null 2>&1; then
        echo "==> tagging current $IMAGE as $ROLLBACK"
        docker tag "$IMAGE" "$ROLLBACK"
    fi
}


function deploy {
    require_compose
    echo "==> deploying $SERVICE"
    # --no-deps matters: without it compose notices config drift on
    # elasticsearch and redis and recreates them alongside the app
    docker compose -f "$COMPOSE_DIR/docker-compose.yml" \
        up -d --no-deps "$SERVICE"
}


function wait_healthy {
    echo -n "==> waiting for health"
    for _ in $(seq 1 60); do
        health=$(docker inspect "$SERVICE" \
            --format '{{.State.Health.Status}}' 2>/dev/null || echo "gone")
        if [[ "$health" == "healthy" ]]; then
            echo " ok"
            return 0
        fi
        echo -n "."
        sleep 2
    done

    echo " timed out, last status: ${health:-unknown}"
    echo "recent logs:"
    docker logs --tail 40 "$SERVICE"
    exit 1
}


function status {
    echo "==> running containers"
    docker ps --filter "name=$SERVICE" --filter "name=archivist" \
        --format '{{.Names}}\t{{.Status}}\t{{.Image}}'
    echo "==> local images"
    docker images tubearchivist \
        --format '{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}'
}


function rollback {
    require_compose
    if ! docker image inspect "$ROLLBACK" >/dev/null 2>&1; then
        echo "no $ROLLBACK image to roll back to"
        exit 1
    fi

    echo "==> restoring $ROLLBACK"
    docker tag "$ROLLBACK" "$IMAGE"
    deploy
    wait_healthy
    status
}


case "${1:-}" in
    build)
        build
        ;;
    rollback)
        rollback
        ;;
    status)
        status
        ;;
    "")
        tag_rollback
        build
        deploy
        wait_healthy
        status
        echo
        echo "deployed. roll back with: $0 rollback"
        ;;
    *)
        echo "valid options are: <none> | build | rollback | status"
        exit 1
        ;;
esac

exit 0
