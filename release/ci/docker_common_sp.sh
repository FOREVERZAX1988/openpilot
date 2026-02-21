if [ "$1" = "base" ]; then
  export DOCKER_IMAGE=sunnypilot-base
  export DOCKER_FILE=Dockerfile.sunnypilot_base
elif [ "$1" = "prebuilt" ]; then
  export DOCKER_IMAGE=sunnypilot-prebuilt
  export DOCKER_FILE=Dockerfile.sunnypilot
else
  echo "Invalid docker build image: '$1'"
  exit 1
fi

if [ -z "${DOCKER_REGISTRY:-}" ]; then
  echo "DOCKER_REGISTRY must be set (e.g. registry.example.com/namespace)"
  exit 1
fi
export DOCKER_REGISTRY
export COMMIT_SHA=$(git rev-parse HEAD)

TAG_SUFFIX=$2
LOCAL_TAG=$DOCKER_IMAGE$TAG_SUFFIX
REMOTE_TAG=$DOCKER_REGISTRY/$LOCAL_TAG
REMOTE_SHA_TAG=$DOCKER_REGISTRY/$LOCAL_TAG:$COMMIT_SHA
