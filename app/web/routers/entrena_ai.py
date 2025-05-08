from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os

# Asumimos que los clientes y la configuración están en el proyecto principal
# y ajustamos las rutas de importación según sea necesario.
# Las importaciones relativas al paquete 'app' deberían funcionar si la aplicación
# se ejecuta correctamente (ej. con uvicorn app.web.main:app desde la raíz del proyecto).
# Eliminar importaciones duplicadas. Las originales al principio del archivo son suficientes.

# Las siguientes importaciones asumen que el directorio raíz del proyecto (que contiene 'app')
# está en PYTHONPATH. Esto es manejado por Python cuando se ejecuta un módulo de un paquete
# o cuando se usa uvicorn app.web.main:app desde la raíz.
from app.clientes.cliente_moodle import ClienteMoodle
from app.database.conector_qdrant import ConectorQdrant
from app.clientes.cliente_n8n import ClienteN8N  # Importar el nuevo cliente
from app.config.configuracion import configuracion

router = APIRouter(
    prefix="/entrenai",
    tags=["entrenai"],
)

# current_dir se necesita para Jinja2Templates si la ruta es relativa a este archivo.
current_dir = os.path.dirname(os.path.abspath(__file__))
# Configurar Jinja2Templates
# La ruta a templates es relativa a la ubicación de este archivo de router.
# Si main.py está en entrena-ai-api/ y el router está en entrena-ai-api/app/routers/
# y templates está en entrena-ai-api/app/templates/
# entonces la ruta desde el router es "../templates"
templates_path = os.path.join(current_dir, "..", "templates")
templates = Jinja2Templates(directory=templates_path)


# Modelo para la solicitud de creación de IA
class CreateAIRequest(BaseModel):
    course_id: int


# --- Clientes ---
# (Estos se inicializarán con la configuración cuando sea necesario)


def get_moodle_client():
    return ClienteMoodle(
        url_base=configuracion.obtener_url_moodle(),
        token=configuracion.obtener_token_moodle(),
    )


def get_qdrant_client():
    return ConectorQdrant(
        host=configuracion.obtener_qdrant_host(),
        puerto=configuracion.obtener_qdrant_puerto(),
        api_key=configuracion.obtener_qdrant_api_key(),
        usar_https=configuracion.obtener_qdrant_usar_https(),
    )


# --- Endpoints ---
@router.get("/", response_class=HTMLResponse)
async def get_entrenai_page(request: Request):
    """Sirve la página HTML principal para configurar la IA."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/courses")
async def get_moodle_courses(moodle_client: ClienteMoodle = Depends(get_moodle_client)):
    """Obtiene la lista de cursos de Moodle."""
    try:
        # El método obtener_cursos() no incluye categoría directamente.
        # El frontend ya maneja la posibilidad de que categoryname no esté.
        courses_raw = moodle_client.obtener_cursos()
        if courses_raw is None:
            courses_raw = []

        # El frontend espera 'id', 'fullname', y opcionalmente 'categoryname'.
        # Si necesitas categoryname, se requeriría una lógica adicional aquí o en el cliente.
        # Por ahora, pasamos lo que tenemos.
        courses = []
        for course_data in courses_raw:
            # Intentar obtener el nombre de la categoría si está disponible en la respuesta de obtener_cursos
            # Esto depende de la configuración de Moodle y la versión de la API.
            # A menudo, 'categoryid' está presente, y 'categoryname' podría estar o no.
            # Si 'categoryname' no está, el frontend lo manejará.
            courses.append(
                {
                    "id": course_data.get("id"),
                    "fullname": course_data.get("fullname"),
                    "shortname": course_data.get("shortname"),
                    "categoryid": course_data.get("categoryid"),
                    "categoryname": course_data.get("categoryname"),  # Puede ser None
                }
            )
        return courses
    except Exception as e:
        print(f"Error al obtener cursos de Moodle: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error al obtener cursos de Moodle: {str(e)}"
        )


@router.post("/create-ai")
async def create_ai_for_course(
    request_data: CreateAIRequest,
    moodle_client: ClienteMoodle = Depends(
        get_moodle_client
    ),  # Inyectar cliente Moodle
    qdrant_client: ConectorQdrant = Depends(
        get_qdrant_client
    ),  # Inyectar cliente Qdrant
    # ClienteN8N se instanciará directamente ya que no tiene dependencias complejas
):
    """
    Orquesta la creación de la IA para un curso específico.
    Esto implica:
    1. Asegurar la existencia de la colección en Qdrant.
    2. Crear y configurar un workflow en N8N.
    3. Crear/configurar la sección y recursos necesarios en Moodle.
    """
    course_id = request_data.course_id
    print(f"Iniciando creación de IA para curso ID: {course_id}")

    course_name_for_display = f"Curso {course_id}"  # Default
    course_name_slug = None

    try:
        # Obtener nombre del curso para usarlo en los nombres de recursos
        all_courses = (
            moodle_client.obtener_cursos()
        )  # Sincrónico, idealmente sería async
        current_course_info = next(
            (c for c in all_courses if c.get("id") == course_id), None
        )

        if current_course_info:
            raw_course_name = current_course_info.get("fullname", f"Curso {course_id}")
            course_name_for_display = raw_course_name  # Para N8N workflow name
            # Crear un slug simple para nombres de colección y toolName
            # Reemplazar espacios con guiones bajos y quitar caracteres no alfanuméricos
            course_name_slug = (
                "".join(
                    c if c.isalnum() or c in [" ", "-"] else "" for c in raw_course_name
                )
                .strip()
                .replace(" ", "_")
                .replace("-", "_")
            )
            course_name_slug = course_name_slug.lower()
            print(f"Nombre del curso: '{raw_course_name}', Slug: '{course_name_slug}'")
        else:
            print(
                f"Advertencia: No se pudo obtener información detallada para el curso ID {course_id}."
            )

        # 1. Asegurar colección en Qdrant
        # Pasar el slug del nombre del curso a Qdrant
        qdrant_collection_name = qdrant_client.asegurar_coleccion_curso(
            course_id, course_name_slug
        )
        if not qdrant_collection_name:
            raise HTTPException(
                status_code=500,
                detail=f"Error al asegurar la colección en Qdrant para el curso {course_id}",
            )
        print(f"Colección Qdrant '{qdrant_collection_name}' asegurada.")

        # 2. Crear/configurar workflow en N8N
        cliente_n8n = ClienteN8N()  # Instanciar cliente N8N
        _project_root_temp = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
        )
        workflow_json_path = os.path.join(_project_root_temp, "ai_chat_n8n.json")

        # Pasar el nombre completo del curso y el slug a N8N
        n8n_result = await cliente_n8n.crear_workflow_curso(
            course_id,
            workflow_json_path,
            course_name=course_name_for_display,
            course_name_slug=course_name_slug,
        )
        if not n8n_result or not n8n_result.get("id"):
            # El cliente N8N ya imprime errores detallados
            raise HTTPException(
                status_code=500,
                detail=f"Error al crear/configurar el workflow en N8N para el curso {course_id} ({course_name_for_display})",
            )

        workflow_id = n8n_result.get("id")
        n8n_webhook_url = n8n_result.get("webhook_url")
        print(f"Workflow N8N creado/configurado con ID: {workflow_id}")

        # 3. Crear/configurar sección y recursos en Moodle
        api_base_url = configuracion.obtener(
            "API_BASE_URL", "http://localhost:8000"
        )  # URL de esta API
        section_id = moodle_client.configurar_seccion_entrenai(
            course_id=course_id,
            api_base_url=api_base_url,
            n8n_webhook_url=n8n_webhook_url,
        )

        if section_id is None:
            raise HTTPException(
                status_code=500,
                detail=f"Error al configurar la sección o recursos en Moodle para el curso {course_id}",
            )
        print(f"Sección y recursos Moodle configurados en sección ID: {section_id}")

        # 4. Devolver respuesta exitosa

        return {
            "message": f"IA configurada exitosamente para el curso ID {course_id}",
            "qdrant_collection": qdrant_collection_name,
            "n8n_workflow_id": workflow_id if "workflow_id" in locals() else None,
            "n8n_chat_url": n8n_webhook_url,
            "moodle_section_id": section_id,
        }

    except HTTPException as http_exc:
        print(f"HTTPException en create_ai_for_course: {http_exc.detail}")
        raise http_exc  # Re-lanzar la excepción HTTP para que FastAPI la maneje
    except Exception as e:
        import traceback

        print(f"Error general en create_ai_for_course: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Error interno del servidor: {str(e)}"
        )


@router.get("/refresh-content/{course_id}")
async def refresh_course_content(course_id: int, request: Request):
    """
    Endpoint plantilla para refrescar los contenidos de un curso.
    Aquí iría la lógica para:
    1. Descargar nuevos archivos de la carpeta "Archivos IA" en Moodle.
    2. Procesarlos (extraer texto, generar embeddings).
    3. Actualizar la colección de Qdrant.
    """
    # TODO: Implementar la lógica de refresco de contenidos.
    # Por ahora, es solo una plantilla.

    # Simular acceso a Moodle y Qdrant
    moodle_client = get_moodle_client()
    # qdrant_client = get_qdrant_client() # Comentado ya que no se utiliza en la plantilla actual

    # Obtener información del curso filtrando la lista de todos los cursos
    all_courses = moodle_client.obtener_cursos()
    course_info_list = [c for c in all_courses if c.get("id") == course_id]

    if not course_info_list:
        raise HTTPException(
            status_code=404, detail=f"Curso con ID {course_id} no encontrado."
        )
    course_info = course_info_list[0]

    qdrant_collection_name = (
        f"{configuracion.obtener('QDRANT_COLLECTION_PREFIX', 'curso_')}{course_id}"
    )

    # Aquí iría la lógica de:
    # 1. Identificar la carpeta "Archivos IA" en la sección "Entrenai" del curso.
    # 2. Listar y descargar los archivos de esa carpeta.
    #    (Esto es complejo con la API estándar de Moodle, podría requerir web scraping o un plugin).
    # 3. Procesar cada archivo (usando ProcesadorArchivos de tu proyecto base).
    # 4. Generar embeddings y actualizar/insertar en Qdrant.

    return {
        "message": f"Plantilla para refrescar contenidos del curso ID {course_id}.",
        "course_name": course_info.get("fullname"),
        "qdrant_collection": qdrant_collection_name,
        "status": "No implementado aún. Este es un endpoint de plantilla.",
    }


# Podrías necesitar más endpoints o modelos Pydantic según evolucione.
