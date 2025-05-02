# Sistema de Procesamiento de Documentos de Moodle

Este proyecto implementa un sistema para recolectar, procesar y analizar documentos desde una plataforma Moodle. El sistema extrae contenido de Moodle, lo procesa utilizando técnicas de OCR y NLP, y lo almacena en bases de datos para su posterior análisis.

## Componentes Principales

El sistema consta de varios componentes interconectados:

1. **Recolector de Moodle**: Extrae recursos de cursos de Moodle utilizando su API.
2. **Procesador de Archivos**: Procesa diferentes tipos de archivos (PDF, HTML, etc.) para extraer su contenido textual.
3. **Base de Datos MongoDB**: Almacena los documentos extraídos y procesados.
4. **Servicio CDC (Change Data Capture)**: Monitorea cambios en MongoDB y envía eventos a RabbitMQ.
5. **Cola RabbitMQ**: Gestiona eventos de cambios en los datos de forma asíncrona.
6. **Procesador en tiempo real ByteWax**: Procesa datos de la cola en tiempo real para:
   - Limpiar textos
   - Convertir a formato Markdown
   - Dividir en fragmentos (trunks)
   - Generar contexto para RAG (Context Augmented Retrieval)
   - Generar embeddings vectoriales
7. **Base de Datos Vectorial Qdrant**: Almacena textos limpios y embeddings para búsqueda semántica.

## Arquitectura

```
┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│   Moodle    │───>│ Recolector  │───>│ Procesador   │───>│  MongoDB    │
└─────────────┘    └─────────────┘    └──────────────┘    └──────┬──────┘
                                                                 │
                                                                 ▼
┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│   Qdrant    │<───│  ByteWax    │<───│   RabbitMQ   │<───│ Servicio CDC │
└─────────────┘    └─────────────┘    └──────────────┘    └──────────────┘
```

## Requisitos

- Python 3.12+
- Docker y Docker Compose
- Acceso a una instalación de Moodle con API habilitada
- Espacio de almacenamiento suficiente para documentos y bases de datos

## Instalación y Configuración

1. Clonar el repositorio:
   ```bash
   git clone <repositorio>
   cd <directorio>
   ```

2. Configurar variables de entorno:
   ```bash
   cp env-example .env
   ```
   Editar `.env` con las configuraciones necesarias.

3. Instalar dependencias (desarrollo local):
   ```bash
   pip install -r requirements.txt
   ```

4. Iniciar los servicios con Docker Compose:
   ```bash
   docker-compose up -d
   ```

## Uso

### Recolección de Documentos

Para recolectar documentos de Moodle:

```python
from app.clientes import RecolectorMoodle
from app.config import configuracion

# Crear recolector
recolector = RecolectorMoodle(
    url_moodle=configuracion.obtener_url_moodle(),
    token=configuracion.obtener_token_moodle(),
    directorio_descargas=configuracion.obtener_directorio_descargas(),
)

# Descargar recursos de un curso específico
id_curso = 2
tipos_recursos = ["resource", "file", "folder"]
archivos_descargados = recolector.extractor.descargar_recursos_curso(id_curso, tipos_recursos)
```

### Monitoreo de Cambios (CDC)

El servicio CDC se ejecuta automáticamente como parte del despliegue Docker:

```bash
# Para ejecutar manualmente (si es necesario)
python -m app.servicio_cdc
```

### Procesamiento en Tiempo Real (ByteWax)

El servicio ByteWax se ejecuta automáticamente como parte del despliegue Docker:

```bash
# Para ejecutar manualmente (si es necesario)
python -m app.servicio_bytewax
```

## Servicios Docker

- **mongodb**: Base de datos de documentos (puerto 27017)
- **mongo-express**: Interfaz web para MongoDB (puerto 8082)
- **rabbitmq**: Cola de mensajes (puertos 5672, 15672)
- **qdrant**: Base de datos vectorial (puertos 6333, 6334)
- **moodle**: Instancia de Moodle (puerto 8081)
- **mariadb**: Base de datos para Moodle (puerto 3307)
- **servicio-cdc**: Servicio de monitoreo de cambios
- **servicio-bytewax**: Servicio de procesamiento en tiempo real

## Licencia

Este proyecto está licenciado bajo [especificar licencia]. 