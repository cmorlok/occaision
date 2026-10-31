FROM mcr.microsoft.com/devcontainers/python:3.11-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# 1. Install OS packages required for image processing (rembg, pillow-heif), nodejs and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libheif-dev \
    nodejs \
    npm \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Install official Antigravity CLI (agy) system-wide to /usr/local/bin
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir /usr/local/bin \
    && chmod +x /usr/local/bin/agy

# 3. Pre-install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# 4. Rename default 'vscode' user and group to 'developer'
RUN if id -u vscode >/dev/null 2>&1; then \
        usermod -l developer -d /home/developer -m vscode && \
        groupmod -n developer vscode && \
        if [ -f /etc/sudoers.d/vscode ]; then mv /etc/sudoers.d/vscode /etc/sudoers.d/developer && sed -i 's/vscode/developer/g' /etc/sudoers.d/developer; fi; \
    fi

# Switch back to dialog for any interactive usage
ENV DEBIAN_FRONTEND=dialog
