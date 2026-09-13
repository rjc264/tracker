# 🐳 BAC Expense Tracker - Con Docker

¡Mucho más simple! No necesitas instalar Python, solo Docker.

## 📦 Requisitos

- **Docker** instalado ([descargar](https://www.docker.com/products/docker-desktop))
- **Docker Compose** (viene con Docker Desktop)

Verifica:
```bash
docker --version
docker-compose --version
```

## 🚀 Instalación (5 minutos)

### 1️⃣ Descarga los archivos

Crea una carpeta:
```bash
mkdir expense-tracker
cd expense-tracker
```

Descarga estos archivos en esa carpeta:
```
expense-tracker/
├── Dockerfile
├── docker-compose.yml
├── docker-compose-prod.yml
├── entrypoint.sh
├── gmail_reader.py
├── requirements.txt
├── dashboard.html
└── setup.py
```

### 2️⃣ Obtén credenciales de Gmail

1. Ve a: https://console.cloud.google.com
2. Crea un proyecto nuevo: "Expense Tracker BAC"
3. Busca y habilita "Gmail API"
4. Ve a "Credenciales" → "Crear credencial"
5. Tipo: "OAuth 2.0 - Aplicación de escritorio"
6. Descarga el JSON
7. Renómbralo a `credentials.json`
8. Crea carpeta `config` y ponlo ahí:

```bash
mkdir config
# Coloca credentials.json en config/
```

### 3️⃣ Configurar Gmail (Primera vez)

```bash
docker-compose run expense-tracker setup
```

Se abrirá tu navegador. Autoriza el acceso a Gmail. ✅

### 4️⃣ Primera sincronización

```bash
docker-compose run expense-tracker sync
```

¡Verás tus gastos siendo sincronizados! 📊

### 5️⃣ Ver dashboard

```bash
docker-compose up dashboard
```

Luego abre en tu navegador:
```
http://localhost:8080
```

¡Listo! 🎉

---

## 💻 Comandos útiles

### Sincronizar gastos ahora
```bash
docker-compose run expense-tracker sync
```

### Ejecutar en segundo plano (sincroniza cada hora)
```bash
docker-compose up -d expense-tracker
```

### Ver logs en tiempo real
```bash
docker-compose logs -f expense-tracker
```

### Detener containers
```bash
docker-compose down
```

### Limpiar todo (cuidado!)
```bash
docker-compose down -v
```

### Ejecutar comando personalizado
```bash
docker-compose run expense-tracker shell
```

---

## 🏭 Para Producción (VPS/Servidor)

Usa `docker-compose-prod.yml`:

```bash
docker-compose -f docker-compose-prod.yml up -d
```

Características:
- ✅ Sincronización automática cada hora
- ✅ Health checks
- ✅ Límites de recursos
- ✅ Reinicio automático
- ✅ Logs persistentes

---

## 📊 Estructura de datos

```bash
expense-tracker/
├── config/              ← Tus credenciales (NO SUBIR A GIT)
│   ├── credentials.json
│   └── token.json
├── data/                ← Tus gastos (backup local)
│   └── expenses.json
└── docker-compose.yml
```

---

## 🔒 Seguridad

- ✅ `config/` está en `.gitignore` (no se sube a Git)
- ✅ `data/` es local en tu máquina
- ✅ Docker aísla la aplicación
- ✅ Permisos restringidos en volúmenes

**Nunca compartas:**
- `config/credentials.json`
- `config/token.json`
- `data/expenses.json`

---

## 🆘 Troubleshooting

### "Docker no está instalado"
Descarga desde: https://www.docker.com/products/docker-desktop

### "Error: credentials.json no encontrado"
Crea `config/` y coloca tu `credentials.json` ahí:
```bash
mkdir -p config
# Descarga credentials.json en config/
```

### "Error: conexión a Gmail"
Elimina `config/token.json`:
```bash
rm config/token.json
docker-compose run expense-tracker setup
```

### "Dashboard no carga"
```bash
# Verifica que el dashboard está corriendo
docker-compose up dashboard

# En otra terminal
docker-compose run expense-tracker sync

# Abre http://localhost:8080
```

### Ver logs detallados
```bash
docker-compose logs -f
```

---

## 📈 Opciones avanzadas

### Cambiar la hora de sincronización (Producción)

En `docker-compose-prod.yml`:
```yaml
environment:
  - SYNC_HOUR=7      # Cambiar a la hora que quieras
  - SYNC_MINUTE=0    # Cambiar minuto
```

### Aumentar límites de memoria
```yaml
deploy:
  resources:
    limits:
      memory: 1G     # Cambiar según necesites
```

### Usar volumen externo
```bash
docker volume create expense-tracker-data

# En docker-compose.yml:
volumes:
  - expense-tracker-data:/app/data
```

---

## 🎯 Flujo típico

```bash
# Setup inicial (una vez)
docker-compose run expense-tracker setup

# Ver gastos
docker-compose run expense-tracker sync

# Abrir dashboard
docker-compose up dashboard
# http://localhost:8080

# Sincronización automática diaria (producción)
docker-compose -f docker-compose-prod.yml up -d
```

---

## 📱 Cambios futuros

- [ ] Agregar más bancos
- [ ] Exportar a PDF/Excel
- [ ] Alertas por email
- [ ] Mobile app
- [ ] Base de datos PostgreSQL

---

## ✅ Ventajas de Docker

- ✅ **Sin instalar Python** - Todo viene en el contenedor
- ✅ **Reproducible** - Funciona igual en tu PC, Mac, Linux, VPS
- ✅ **Aislado** - No interfiere con otras apps
- ✅ **Fácil actualizar** - Solo actualiza el Dockerfile
- ✅ **Backups simples** - Backup de `config/` y `data/`
- ✅ **Escala fácil** - Funciona igual en un server

¡Disfruta tu sistema de tracking! 💰

---

**¿Preguntas?** Avísame en cualquier paso.
