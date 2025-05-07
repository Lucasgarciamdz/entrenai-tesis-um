# EntrenaAI - Integración Moodle con IA Personalizada

Este proyecto permite crear chatbots de IA personalizada para cursos de Moodle, utilizando los documentos del curso como base de conocimiento.

## Descripción

EntrenaAI es una prueba de concepto (POC) que integra:

- **Moodle**: LMS donde están los cursos y documentos
- **FastAPI**: Backend para gestionar la creación y procesamiento 
- **Qdrant**: Base de datos vectorial para almacenar embeddings
- **N8n**: Plataforma para gestionar el flujo de trabajo y el chatbot
- **MongoDB**: Almacenamiento de documentos procesados
- **RabbitMQ**: Cola de mensajes para procesamiento asíncrono

## Requisitos Previos

- Python 3.8+
- Docker y Docker Compose
- Moodle con API habilitada
- N8n funcionando
- Credenciales de acceso a todas las plataformas

## Instalación

1. Clona el repositorio:
   ```bash
   git clone https://tu-repositorio/entrena-ai-api.git
   cd entrena-ai-api
   ```

2. Crea un entorno virtual e instala las dependencias:
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   pip install fastapi uvicorn httpx python-dotenv pymongo pika
   ```

3. Crea un archivo `.env` con las variables de entorno necesarias:
   ```
   # Configuración de la API
   PORT=8000
   HOST=0.0.0.0
   LOG_LEVEL=INFO
   
   # Configuración de Moodle
   MOODLE_URL=http://localhost:8081
   MOODLE_TOKEN=tu_token_de_moodle
   
   # Configuración de Qdrant
   QDRANT_URL=http://localhost:6333
   QDRANT_API_KEY=
   
   # Configuración de N8n
   N8N_URL=http://localhost:5678
   N8N_API_KEY=tu_api_key_de_n8n
   
   # Configuración de MongoDB
   MONGODB_HOST=localhost
   MONGODB_PORT=27017
   MONGODB_USERNAME=admin
   MONGODB_PASSWORD=password
   MONGODB_DATABASE=moodle_db
   
   # Configuración de RabbitMQ
   RABBITMQ_HOST=localhost
   RABBITMQ_PORT=5672
   RABBITMQ_USERNAME=guest
   RABBITMQ_PASSWORD=guest
   RABBITMQ_QUEUE_NAME=moodle_changes
   ```

4. Inicia el servicio:
   ```bash
   uvicorn main:app --reload
   ```

## Configuración de Moodle

### 1. Habilitar WebServices en Moodle

1. Accede a tu Moodle como administrador
2. Ve a Administración del sitio > Características avanzadas
3. Activa los servicios web
4. Guarda los cambios

### 2. Crear un Token de API

1. Ve a Administración del sitio > Plugins > Servicios web > Gestionar tokens
2. Crea un nuevo token para un usuario con permisos adecuados
3. Copia el token generado y añádelo a tu archivo `.env`

### 3. Instalar Plugin Requerido

Para que Moodle notifique a nuestro backend cuando se suben archivos, necesitamos un plugin que capture esos eventos.

**Nota importante:** Este es un paso manual que deberás realizar. Puedes:

- Usar un plugin existente como [Event Webhooks](https://moodle.org/plugins/local_webhooks)
- Crear un plugin personalizado siguiendo las [instrucciones de desarrollo de Moodle](https://docs.moodle.org/dev/Main_Page)

#### Ejemplo de configuración del plugin Event Webhooks:

1. Instala el plugin en tu Moodle
2. Configura un nuevo webhook:
   - Nombre: EntrenaAI - Archivos nuevos
   - URL: http://tu-backend/moodle/incoming-files
   - Eventos: \core\event\course_module_created (para archivos nuevos)
   - Formato de payload: JSON

## Uso

### 1. Crear una IA personalizada para un curso

Envía una solicitud POST al endpoint `/moodle/create-virtual-ai`:

```bash
curl -X 'POST' \
  'http://localhost:8000/moodle/create-virtual-ai' \
  -H 'Content-Type: application/json' \
  -d '{
  "course_id": 2,
  "user_id": 3,
  "folder_name": "entrenaí"
}'
```

Esto creará:
- Una carpeta en Moodle
- Una colección en Qdrant
- Un workflow en N8n con un chatbot

### 2. Subir archivos al curso

1. Ve al curso en Moodle
2. Busca la carpeta "entrenaí" (o el nombre que hayas elegido)
3. Sube archivos a esta carpeta

El sistema debería:
- Detectar los archivos nuevos
- Enviar una notificación a nuestra API
- Procesar los archivos y vectorizarlos
- Actualizar la base de conocimiento del chatbot

### 3. Usar el chatbot

El chatbot estará disponible en la URL devuelta por la API al crear la IA personalizada.

## Estructura del Proyecto

```
entrena-ai-api/
├── app/
│   ├── routers/
│   │   ├── __init__.py
│   │   └── moodle.py
│   └── __init__.py
├── main.py
├── .env
└── README.md
```

## Consideraciones para Producción

Este es un POC y requiere mejoras antes de usarse en producción:

1. **Seguridad**: Implementar autenticación adecuada
2. **Manejo de errores**: Mejorar el manejo de excepciones
3. **Logging**: Añadir un sistema de logging completo
4. **Pruebas**: Desarrollar pruebas unitarias y de integración
5. **Dockerización**: Empaquetar la aplicación en contenedores

## Recursos Adicionales

- [Documentación de la API de Moodle](https://docs.moodle.org/dev/Web_service_API_functions)
- [Documentación de Qdrant](https://qdrant.tech/documentation/)
- [Documentación de N8n](https://docs.n8n.io/) 