# Edit the ARG defaults below and open a PR to trigger a workflow run.
# CI will extract these values and pass them to the agent-worker.
FROM registry.access.redhat.com/ubi9/ubi-micro:9.6

ARG EP_URL="https://github.com/openshift/enhancements/pull/1914"
ARG REPO_URL="https://github.com/openshift/cert-manager-operator.git"
ARG BASE_BRANCH="cert-manager-1.18"

RUN echo "EP_URL=${EP_URL}" > /params.env && \
    echo "REPO_URL=${REPO_URL}" >> /params.env && \
    echo "BASE_BRANCH=${BASE_BRANCH}" >> /params.env
