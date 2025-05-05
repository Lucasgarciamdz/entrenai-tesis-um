# Makefile para exportar variables de entorno y ejecutar Docker Compose

.PHONY: up down restart ps logs clean help

# Verificar si existe el archivo .env
check-env:
	@if [ ! -f .env ]; then \
		echo "Archivo .env no encontrado. Por favor, crea uno basado en env-example."; \
		exit 1; \
	fi

# Exportar variables de entorno y levantar contenedores
up: check-env
	@echo "Exportando variables de entorno y levantando contenedores..."
	@set -a && . ./.env && set +a && docker compose up -d

# Exportar variables de entorno y levantar contenedores con logs
up-logs: check-env
	@echo "Exportando variables de entorno y levantando contenedores con logs..."
	@set -a && . ./.env && set +a && docker compose up

# Detener contenedores
down:
	@echo "Deteniendo contenedores..."
	@docker compose down

# Reiniciar contenedores
restart: down up
	@echo "Contenedores reiniciados"

# Mostrar estado de los contenedores
ps:
	@docker compose ps

# Mostrar logs de los contenedores
logs:
	@docker compose logs -f

# Limpiar volúmenes (¡cuidado! eliminará todos los datos)
clean:
	@echo "¡ATENCIÓN! Esta acción eliminará todos los volúmenes y datos."
	@read -p "¿Estás seguro? (s/N): " confirm; \
	if [ "$$confirm" = "s" ] || [ "$$confirm" = "S" ]; then \
		docker compose down -v; \
		echo "Volúmenes eliminados"; \
	else \
		echo "Operación cancelada"; \
	fi

# Mostrar ayuda
help:
	@echo "Comandos disponibles:"
	@echo "  make up         - Exporta variables de .env y levanta contenedores en modo detached"
	@echo "  make up-logs    - Exporta variables de .env y levanta contenedores mostrando logs"
	@echo "  make down       - Detiene los contenedores"
	@echo "  make restart    - Reinicia los contenedores"
	@echo "  make ps         - Muestra el estado de los contenedores"
	@echo "  make logs       - Muestra los logs de los contenedores"
	@echo "  make clean      - Elimina contenedores y volúmenes (¡cuidado!)"
	@echo "  make help       - Muestra esta ayuda"