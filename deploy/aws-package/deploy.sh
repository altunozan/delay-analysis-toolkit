#!/usr/bin/env bash
# ---------------------------------------------------------------------
# Build → push → roll the ECS service. The ONLY routine command after
# first-time setup (README_DEPLOY.md steps 1-4). Run from this folder:
#
#   AWS_REGION=eu-west-1 ./deploy.sh v1.0.1
#
# The argument is the image tag (default: a timestamp).
# ---------------------------------------------------------------------
set -euo pipefail

REGION="${AWS_REGION:?set AWS_REGION, e.g. eu-west-1}"
REPO_NAME="${ECR_REPO:-delay-toolkit}"
CLUSTER="${ECS_CLUSTER:-delay-toolkit}"
SERVICE="${ECS_SERVICE:-delay-toolkit}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG="${1:-$(date +%Y%m%d-%H%M%S)}"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${ECR}/${REPO_NAME}:${TAG}"

echo "==> building ${IMAGE}"
# linux/amd64 explicitly: Apple-Silicon laptops otherwise push arm64
# images that Fargate (x86 by default) refuses to start.
docker build --platform linux/amd64 -t "$IMAGE" "$HERE"

echo "==> pushing"
aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$ECR"
docker push "$IMAGE"

echo "==> pointing the service at the new image"
TD=$(aws ecs describe-task-definition --task-definition delay-toolkit \
     --region "$REGION" --query taskDefinition)
NEW_TD=$(echo "$TD" | python3 -c "
import json, sys
td = json.load(sys.stdin)
td['containerDefinitions'][0]['image'] = '$IMAGE'
for k in ('taskDefinitionArn', 'revision', 'status', 'requiresAttributes',
          'compatibilities', 'registeredAt', 'registeredBy'):
    td.pop(k, None)
json.dump(td, sys.stdout)
")
ARN=$(aws ecs register-task-definition --region "$REGION" \
      --cli-input-json "$NEW_TD" \
      --query taskDefinition.taskDefinitionArn --output text)
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" \
    --service "$SERVICE" --task-definition "$ARN" \
    --force-new-deployment >/dev/null

echo "==> rolling. Watch with:"
echo "    aws ecs wait services-stable --cluster $CLUSTER --services $SERVICE --region $REGION"
echo "Done: $IMAGE"
