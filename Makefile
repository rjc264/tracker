.PHONY: help setup sync daemon logs down clean dashboard shell build

help:
	@echo "🐳 BAC Expense Tracker - Docker Commands"
	@echo ""
	@echo "Primeros pasos:"
	@echo "  make setup        - Configurar Gmail (primera vez)"
	@echo "  make sync         - Sincronizar gastos ahora"
	@echo "  make dashboard    - Ver dashboard (http://localhost:8080)"
	@echo ""
	@echo "Operación:"
	@echo "  make daemon       - Ejecutar sincronización cada hora (background)"
	@echo "  make logs         - Ver logs en tiempo real"
	@echo "  make down         - Detener todos los servicios"
	@echo ""
	@echo "Desarrollo:"
	@echo "  make build        - Construir imagen Docker"
	@echo "  make shell        - Abrir shell interactivo"
	@echo "  make clean        - Limpiar todo (⚠️ borrar datos)"
	@echo ""

setup:
	@echo "🔧 Configurando Gmail..."
	docker-compose run --rm expense-tracker setup

sync:
	@echo "🔄 Sincronizando gastos..."
	docker-compose run --rm expense-tracker sync

daemon:
	@echo "👾 Iniciando daemon (sincroniza cada hora)..."
	docker-compose up -d expense-tracker
	@echo "✅ Corriendo en background. Ver logs con: make logs"

dashboard:
	@echo "📊 Iniciando dashboard..."
	docker-compose up dashboard
	@echo "✅ Abre http://localhost:8080"

logs:
	@echo "📋 Logs en tiempo real..."
	docker-compose logs -f

down:
	@echo "🛑 Deteniendo servicios..."
	docker-compose down

clean:
	@echo "🗑️  Limpiando todo (⚠️ esto borra los datos)..."
	docker-compose down -v
	rm -rf config/ data/ *.log
	@echo "✅ Limpieza completada"

build:
	@echo "🔨 Construyendo imagen Docker..."
	docker-compose build --no-cache

shell:
	@echo "📝 Abriendo shell interactivo..."
	docker-compose run --rm expense-tracker shell

# Producción
prod-up:
	@echo "🚀 Iniciando en producción..."
	docker-compose -f docker-compose-prod.yml up -d

prod-down:
	@echo "🛑 Deteniendo producción..."
	docker-compose -f docker-compose-prod.yml down

prod-logs:
	@echo "📋 Logs de producción..."
	docker-compose -f docker-compose-prod.yml logs -f

# Desarrollo
dev-up:
	@echo "👨‍💻 Iniciando en desarrollo..."
	docker-compose up -d
	docker-compose logs -f

dev-rebuild:
	@echo "🔨 Reconstruyendo en desarrollo..."
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d
	docker-compose logs -f

# Backup
backup:
	@echo "💾 Haciendo backup..."
	tar -czf backup-$(shell date +%Y%m%d-%H%M%S).tar.gz config/ data/
	@echo "✅ Backup completado"

# Status
status:
	@echo "📊 Estado de servicios:"
	docker-compose ps
