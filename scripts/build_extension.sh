#!/usr/bin/env bash
set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${WORKSPACE_DIR}/dist"
EXTENSION_DIR="${WORKSPACE_DIR}/extension"
ZIP_FILE="${DIST_DIR}/occaision.zip"

mkdir -p "${DIST_DIR}"
rm -f "${ZIP_FILE}"

# Optional: Version aktualisieren, falls als Parameter übergeben (z. B. 1.1.0 oder v1.1.0)
TARGET_VERSION="${1:-}"
if [ -n "${TARGET_VERSION}" ]; then
  CLEAN_VERSION="${TARGET_VERSION#v}"
  echo "📝 Aktualisiere Version in manifest.json auf ${CLEAN_VERSION}..."
  sed -i -E "s/\"version\":\s*\"[^\"]+\"/\"version\": \"${CLEAN_VERSION}\"/" "${EXTENSION_DIR}/manifest.json"
fi

echo "🔨 Baue Firefox WebExtension..."
cd "${EXTENSION_DIR}"
zip -q -r "${ZIP_FILE}" manifest.json background.js content.js panel.css

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "\n${GREEN}================================================================================${NC}"
echo -e "${GREEN}🎉 Firefox Extension erfolgreich gebaut: ${BOLD}dist/occaision.zip${NC}"
echo -e "${GREEN}================================================================================${NC}\n"

echo -e "${BOLD}📦 INSTALLATION & AKTUALISIERUNG IN FIREFOX:${NC}"
echo -e "--------------------------------------------------------------------------------"
echo -e "1. Öffne Firefox und gib folgende Adresse in die Adressleiste ein:"
echo -e "   ${BLUE}about:debugging#/runtime/this-firefox${NC}\n"

echo -e "2. Klicke auf den Button:"
echo -e "   ${BOLD}\"Temporäres Add-on laden...\"${NC} (engl. \"Load Temporary Add-on...\")\n"

echo -e "3. Datei auswählen:"
echo -e "   ${YELLOW}• Empfohlen für Entwicklung:${NC} Wähle direkt:"
echo -e "     ${BOLD}${EXTENSION_DIR}/manifest.json${NC}"
echo -e "   ${YELLOW}• Als ZIP-Paket:${NC} Wähle:"
echo -e "     ${BOLD}${ZIP_FILE}${NC}\n"

echo -e "4. ${BOLD}Aktualisieren nach Änderungen:${NC}"
echo -e "   Auf ${BLUE}about:debugging#/runtime/this-firefox${NC} einfach neben der Extension"
echo -e "   auf ${BOLD}\"Neu laden\"${NC} (Reload) klicken – Änderungen sind sofort aktiv!\n"

echo -e "5. ${BOLD}Berechtigungen bestätigen (falls erforderlich):${NC}"
echo -e "   Klicke nach der Installation einmal auf das Puzzle-/Extension-Icon"
echo -e "   in der Firefox-Toolbar, um den Zugriff auf das lokale Backend (127.0.0.1:8000)"
echo -e "   und die Zielseiten zu bestätigen."
echo -e "--------------------------------------------------------------------------------\n"
