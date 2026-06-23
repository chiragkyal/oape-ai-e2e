FROM registry.access.redhat.com/ubi9/go-toolset

USER 0
RUN dnf install -y git make jq && \
    dnf install -y 'dnf-command(config-manager)' && \
    dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo && \
    dnf install -y gh && \
    dnf clean all

WORKDIR /app

RUN go install golang.org/x/tools/cmd/goimports@latest && \
    curl -sSfL https://raw.githubusercontent.com/golangci/golangci-lint/master/install.sh | sh -s -- -b /usr/local/bin

COPY scripts/ci-monitor/ /app/scripts/ci-monitor/
COPY scripts/pr-agent/ /app/scripts/pr-agent/
COPY plugins /plugins
COPY deploy/config/ /config/

RUN git config --global user.name "openshift-app-platform-shift-bot" && \
    git config --global user.email "267347085+openshift-app-platform-shift-bot@users.noreply.github.com"

RUN chmod -R g=u /opt/app-root/src

USER 1001
