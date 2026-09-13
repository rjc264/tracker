#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

CONFIG_DIR="${CONFIG_DIR:-/app/config}"
DATA_DIR="${DATA_DIR:-/app/data}"

echo -e "${BLUE}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     💰 BAC Expense Tracker - Docker Edition         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════╝${NC}"

# Crear directorios si no existen
mkdir -p "$CONFIG_DIR" "$DATA_DIR"

# Comando principal
COMMAND="${1:-sync}"

case "$COMMAND" in
  setup)
    echo -e "${YELLOW}🔧 Iniciando configuración de Gmail...${NC}"
    echo -e "${YELLOW}Asegúrate de tener credentials.json en ./config/${NC}"
    echo ""
    python3 setup.py
    ;;

  sync)
    echo -e "${YELLOW}🔄 Sincronizando gastos desde Gmail...${NC}"
    echo ""

    # Verificar que exista credentials.json
    if [ ! -f "$CONFIG_DIR/credentials.json" ]; then
      echo -e "${RED}❌ Error: No se encontró $CONFIG_DIR/credentials.json${NC}"
      echo -e "${YELLOW}Pasos:${NC}"
      echo "1. Obtén las credenciales de Google Cloud Console"
      echo "2. Coloca credentials.json en la carpeta ./config/"
      echo "3. Vuelve a ejecutar este comando"
      exit 1
    fi

    # Copiar credenciales al directorio de trabajo si es necesario
    if [ ! -f "/app/credentials.json" ]; then
      cp "$CONFIG_DIR/credentials.json" /app/
    fi

    python3 gmail_reader.py
    echo ""
    echo -e "${GREEN}✅ Sincronización completada${NC}"
    echo -e "${GREEN}📊 Abre http://localhost:8080 para ver el dashboard${NC}"
    ;;

  daemon)
    echo -e "${YELLOW}🔄 Ejecutando en modo daemon (sincroniza cada hora)...${NC}"
    while true; do
      echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} Sincronizando..."
      python3 gmail_reader.py
      echo -e "${GREEN}✅ Sincronización completada. Próxima en 1 hora.${NC}"
      sleep 3600
    done
    ;;

  shell)
    echo -e "${YELLOW}📝 Abriendo shell interactivo...${NC}"
    /bin/bash
    ;;

  *)
    echo -e "${YELLOW}Uso:${NC}"
    echo "  docker-compose run expense-tracker setup    # Configurar Gmail (primera vez)"
    echo "  docker-compose run expense-tracker sync     # Sincronizar gastos ahora"
    echo "  docker-compose up expense-tracker          # Ejecutar en daemon (cada hora)"
    echo "  docker-compose run expense-tracker shell    # Abrir shell"
    echo ""
    echo -e "${YELLOW}Ejemplos:${NC}"
    echo "  # Setup inicial:"
    echo "  docker-compose run expense-tracker setup"
    echo ""
    echo "  # Sincronizar ahora:"
    echo "  docker-compose run expense-tracker sync"
    echo ""
    echo "  # Ver el dashboard:"
    echo "  open http://localhost:8080"
    exit 1
    ;;
esac

exit 0
