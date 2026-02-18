FROM registry.access.redhat.com/ubi9/go-toolset

# Install system dependencies required by operator tooling
USER 0
RUN dnf install -y \
        git \
        make && \
    # Install GitHub CLI
    dnf install -y 'dnf-command(config-manager)' && \
    dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo && \
    dnf install -y gh && \
    dnf install -y python3.11 && \
    dnf install -y python3.11-pip && \
    dnf clean all

WORKDIR /app

# Install Python dependencies
COPY server/requirements.txt .
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY server/main.py server/vertex_client.py server/context_loader.py server/config.json ./
COPY server/tools ./tools/

# Copy plugins directory (contains commands, skills, fixtures)
# context_loader.py resolves: Path(__file__).parent.parent / "plugins" / "oape"
# With __file__=/app/context_loader.py, parent.parent=/, so it expects /plugins/oape
COPY plugins /plugins

# Copy root-level files needed for context
COPY AGENTS.md CLAUDE.md team-repos.csv /

USER 1001

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
