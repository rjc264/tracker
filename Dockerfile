FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar scripts
COPY gmail_reader.py .
COPY setup.py .
COPY entrypoint.sh .

# Hacer ejecutable el entrypoint
RUN chmod +x entrypoint.sh

# Crear directorio para credenciales y datos
RUN mkdir -p /app/config /app/data

# Volumen para datos persistentes
VOLUME ["/app/config", "/app/data"]

# Entrypoint
ENTRYPOINT ["./entrypoint.sh"]
CMD ["sync"]
