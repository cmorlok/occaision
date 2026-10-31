#!/usr/bin/env bash
set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="seller-assistant"
TAG="${1:-latest}"
FULL_IMAGE="${IMAGE_NAME}:${TAG}"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "\n${BLUE}================================================================================${NC}"
echo -e "${BOLD}🐳 Docker Build: ${FULL_IMAGE}${NC}"
echo -e "${BLUE}================================================================================${NC}\n"

# Verify docker CLI is available on the host
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Fehler: 'docker' wurde im Pfad nicht gefunden!${NC}"
    echo "Bitte stelle sicher, dass dieses Skript auf dem Docker-fähigen Host ausgeführt wird."
    exit 1
fi

echo -e "Arbeitsverzeichnis: ${WORKSPACE_DIR}"
echo -e "Baue Docker-Image ${BOLD}${FULL_IMAGE}${NC}...\n"

cd "${WORKSPACE_DIR}"
docker build -t "${FULL_IMAGE}" -f Dockerfile .

echo -e "\n${GREEN}================================================================================${NC}"
echo -e "${GREEN}🎉 Docker Image erfolgreich gebaut: ${BOLD}${FULL_IMAGE}${NC}"
echo -e "${GREEN}================================================================================${NC}\n"

echo -e "${BOLD}🚀 CONTAINER STARTEN (HOST):${NC}"
echo -e "--------------------------------------------------------------------------------"
echo -e "1. ${YELLOW}Container im Hintergrund starten:${NC}"
echo -e "   ${BOLD}docker run -d \\${NC}"
echo -e "     ${BOLD}--name seller-assistant \\${NC}"
echo -e "     ${BOLD}-p 8000:8000 \\${NC}"
echo -e "     ${BOLD}-v \"\$(pwd)/data:/app/data\" \\${NC}"
echo -e "     ${BOLD}--env-file .env \\${NC}"
echo -e "     ${BOLD}--restart unless-stopped \\${NC}"
echo -e "     ${BOLD}${FULL_IMAGE}${NC}\n"

echo -e "2. ${YELLOW}Status & Logs überprüfen:${NC}"
echo -e "   docker ps --filter \"name=seller-assistant\""
echo -e "   docker logs -f seller-assistant\n"

echo -e "3. ${YELLOW}Web-Dashboard öffnen:${NC}"
echo -e "   ${BLUE}http://127.0.0.1:8000/${NC}\n"

echo -e "4. ${YELLOW}Container stoppen / entfernen:${NC}"
echo -e "   docker stop seller-assistant && docker rm seller-assistant"
echo -e "--------------------------------------------------------------------------------\n"
