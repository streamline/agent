FROM nousresearch/hermes-agent:latest

# Add hermes user to the host docker group (GID 988, the host's docker group)
RUN groupadd -fg 988 docker-host && usermod -aG 988 hermes

# Set Docker socket path so CLI connects without needing DOCKER_HOST env
ENV DOCKER_HOST=unix:///run/docker.sock

# Default entrypoint: /hermes.sh (unchanged from upstream)
# All per-bot config (SOUL, .env, auth) goes in the /opt/data volume — not in this image
