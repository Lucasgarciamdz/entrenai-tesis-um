import httpx
import json
import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime
import logging

# Configuración del router
router = APIRouter(prefix="/moodle", tags=["moodle"])
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO) # Or DEBUG for more verbosity


# Helper function to format Moodle API parameters
def rest_api_parameters(in_args, prefix='', out_dict=None):
    if out_dict is None:
        out_dict = {}
    if not isinstance(in_args, (list, dict)):
        if prefix:
            out_dict[prefix] = in_args
        return out_dict
    if isinstance(in_args, list):
        for idx, item in enumerate(in_args):
            rest_api_parameters(item, f"{prefix}[{idx}]", out_dict)
    elif isinstance(in_args, dict):
        for key, item in in_args.items():
            new_prefix = f"{prefix}[{key}]" if prefix else key
            rest_api_parameters(item, new_prefix, out_dict)
    return out_dict

async def _llamada_moodle_api(
    moodle_config: dict, wsfunction: str, params: dict, client: httpx.AsyncClient
) -> Any:
    api_url = f"{moodle_config['url'].rstrip('/')}/webservice/rest/server.php"
    response = None # Initialize response to None
    response_text = "No response captured before error." 
    base_payload = {
        "wstoken": moodle_config["token"],
        "moodlewsrestformat": "json",
        "wsfunction": wsfunction,
    }
    flattened_ws_params = rest_api_parameters(params)
    final_payload = {**base_payload, **flattened_ws_params}
    logger.info(f"Llamando a Moodle API: {wsfunction} con payload keys: {list(final_payload.keys())}")
    # Avoid logging sensitive data like tokens in full payload for production
    # logger.debug(f"Payload completo para {wsfunction}: {final_payload}")

    try:
        response = await client.post(api_url, data=final_payload)
        response.raise_for_status()
        json_response = response.json()
        logger.info(f"Respuesta de Moodle API ({wsfunction}) exitosa.")
        # logger.debug(f"Respuesta JSON de {wsfunction}: {json_response}")

        if isinstance(json_response, dict) and (
            json_response.get("exception") or json_response.get("errorcode")
        ):
            error_message = json_response.get("message", str(json_response))
            error_code = json_response.get("errorcode")
            detail = f"Error en API Moodle ({wsfunction}): {error_message} (Código: {error_code})"
            logger.error(detail)
            raise HTTPException(status_code=502, detail=detail)
        return json_response
    except httpx.HTTPStatusError as e:
        error_details = "No details available"
        if e.response and hasattr(e.response, 'text'):
            error_details = e.response.text
        try:
            error_json = e.response.json()
            if isinstance(error_json, dict) and (error_json.get("exception") or error_json.get("errorcode")):
                error_message = error_json.get("message", str(error_json))
                error_code = error_json.get("errorcode")
                detail_msg = f"Error HTTP de API Moodle ({wsfunction}) al llamar a {e.request.url}: {e.response.status_code} - {error_message} (Código: {error_code})"
            else:
                detail_msg = f"Error HTTP de API Moodle ({wsfunction}) al llamar a {e.request.url}: {e.response.status_code} - {error_details}"
        except json.JSONDecodeError:
            detail_msg = f"Error HTTP de API Moodle ({wsfunction}) al llamar a {e.request.url}: {e.response.status_code} - {error_details}"
        logger.error(detail_msg, exc_info=True)
        raise HTTPException(status_code=502, detail=detail_msg)
    except httpx.RequestError as e:
        detail = f"Error de red o solicitud al contactar API Moodle ({wsfunction}): {str(e)}"
        logger.error(detail, exc_info=True)
        raise HTTPException(status_code=503, detail=detail)
    except json.JSONDecodeError as e_json: # Capture specific JSONDecodeError
        current_response_text = "Response object not available or has no text."
        if response and hasattr(response, 'text'): # Check if response object exists and has text
            current_response_text = response.text
        detail = f"Error al decodificar JSON de respuesta de Moodle para {wsfunction}. Respuesta: {current_response_text}. Error: {str(e_json)}"
        logger.error(detail, exc_info=True)
        raise HTTPException(status_code=500, detail=detail)

async def crear_y_configurar_seccion_plugin(
    moodle_config: dict, course_id: int, position: int, nombre_seccion: str, resumen_seccion: str = "", client: Optional[httpx.AsyncClient] = None
) -> Optional[dict]:
    close_client_locally = False
    if client is None:
        client = httpx.AsyncClient()
        close_client_locally = True
    
    new_section_id = None
    new_section_number = None

    try:
        params_crear = {"courseid": course_id, "position": position, "number": 1}
        logger.info(f"Intentando crear sección en Moodle: course_id={course_id}, position={position}, nombre='{nombre_seccion}'")
        respuesta_crear = await _llamada_moodle_api(
            moodle_config, "local_wsmanagesections_create_sections", params_crear, client
        )
        logger.info(f"Respuesta de 'local_wsmanagesections_create_sections': {respuesta_crear}")

        if not isinstance(respuesta_crear, list) or not respuesta_crear:
            logger.error(f"Respuesta inesperada al crear sección con plugin: {respuesta_crear}")
            return None
        
        nueva_seccion_info_raw = respuesta_crear[0]
        new_section_id = nueva_seccion_info_raw.get("id")
        new_section_number = nueva_seccion_info_raw.get("sectionnumber") # Idealmente el plugin devuelve esto
        
        if new_section_number is None: # Fallback si 'sectionnumber' no está
             new_section_number = nueva_seccion_info_raw.get("section") # Otro nombre común para el número de sección

        if new_section_id is None:
            logger.error(f"No se pudo obtener 'id' de la sección creada con plugin. Respuesta: {nueva_seccion_info_raw}")
            return None
        
        update_type = "id" # Actualizar por ID es más robusto
        update_section_ref = new_section_id
        
        # Si new_section_number es None, no podemos usar 'type':'num' para actualizar.
        # El ejemplo del plugin usa 'type':'num' y 'section': (el número de sección).
        # Si el plugin devuelve el número de sección, es mejor usarlo.
        if new_section_number is not None:
            update_type = "num"
            update_section_ref = new_section_number
            logger.info(f"Sección creada con ID: {new_section_id}, Número de sección: {new_section_number}. Actualizando por número.")
        else:
            logger.warning(f"Sección creada con ID: {new_section_id}, pero sin número de sección en la respuesta. Actualizando por ID.")


        params_actualizar = {
            "courseid": course_id,
            "sections": [
                {
                    "type": update_type, 
                    "section": update_section_ref, 
                    "name": nombre_seccion,
                    "summary": resumen_seccion,
                    "summaryformat": 1,
                    "visible": 1,
                    "highlight": 0,  # Added based on plugin example
                    # Using an empty list for sectionformatoptions, assuming it's acceptable or will use defaults.
                    # If specific options are needed, they should be passed or configured.
                    # Example from plugin docs: [{'name': 'level', 'value': '0'}]
                    "sectionformatoptions": [], 
                }
            ],
        }
        
        ws_function_for_update = "local_wsmanagesections_update_sections"
        logger.critical(f"PRE-CALL CHECK FOR SECTION UPDATE: wsfunction='{ws_function_for_update}', params_courseid='{params_actualizar.get('courseid')}', section_type='{params_actualizar['sections'][0]['type']}', section_ref='{params_actualizar['sections'][0]['section']}'")
        
        logger.info(f"Intentando actualizar sección (ID: {new_section_id}, Ref: {update_section_ref}) con nombre '{nombre_seccion}' usando {ws_function_for_update}")
        
        await _llamada_moodle_api(
            moodle_config, ws_function_for_update, params_actualizar, client
        )
        logger.info(f"Llamada a {ws_function_for_update} para sección ID {new_section_id} completada.")
        
        return {"id": new_section_id, "number": new_section_number if new_section_number is not None else "Desconocido"}

    except Exception as e:
        logger.error(f"Error en crear_y_configurar_seccion_plugin: {str(e)}", exc_info=True)
        return None
    finally:
        if close_client_locally and client:
            await client.aclose()

async def agregar_recurso_moodle(
    moodle_config: dict,
    course_id: int,
    section_id: int, 
    modulename: str,
    name: str,
    intro: str,
    introformat: int = 1,
    externalurl: Optional[str] = None,
    display: Optional[int] = 0, 
    client: Optional[httpx.AsyncClient] = None
) -> Optional[int]:
    close_client_locally = False
    if client is None:
        client = httpx.AsyncClient()
        close_client_locally = True

    try:
        module_options: List[dict[str, Any]] = []
        # Moodle espera options como una lista de dicts {'name': key, 'value': val}
        # PERO core_course_add_module en realidad espera los parámetros del módulo directamente
        # anidados, no bajo una clave 'options'.
        # Ejemplo: params={'courseid': ..., 'sectionid': ..., 'modulename': 'url', 
        #                 'name': 'Google', 'externalurl': 'http://google.com', ...}
        # La función rest_api_parameters se encargará de aplanar esto si es necesario.
        
        params_agregar = {
            "courseid": course_id,
            "sectionid": section_id, 
            "modulename": modulename,
            "name": name, # Nombre del recurso
            "intro": intro, # Descripción/Introducción
            "introformat": introformat,
        }

        if modulename == "url":
            if externalurl is None:
                logger.error("externalurl es requerido para el módulo url")
                raise ValueError("externalurl es requerido para el módulo url")
            params_agregar["externalurl"] = externalurl
            params_agregar["display"] = display
        elif modulename == "folder":
            # Opciones específicas de folder si las hay, por ejemplo 'display', 'showexpanded'
            # params_agregar["display"] = 0 # 0 = inline on course page, 1 = on separate page
            # params_agregar["showexpanded"] = 1 # 1 = expand folder content, 0 = collapse
            pass # Usar valores por defecto de Moodle

        logger.info(f"Intentando agregar recurso '{modulename}' con nombre '{name}' en sección ID {section_id}")
        respuesta_agregar = await _llamada_moodle_api(
            moodle_config, "core_course_add_module", params_agregar, client
        )
        logger.info(f"Respuesta de 'core_course_add_module' para '{name}': {respuesta_agregar}")

        cmid = None
        if isinstance(respuesta_agregar, dict) and respuesta_agregar.get("cmid"):
            cmid = respuesta_agregar["cmid"]
        elif isinstance(respuesta_agregar, list) and respuesta_agregar and isinstance(respuesta_agregar[0], dict) and respuesta_agregar[0].get("cmid"):
             cmid = respuesta_agregar[0]["cmid"]
        
        if cmid is not None:
            logger.info(f"Recurso '{name}' ({modulename}) agregado con cmid: {cmid}")
            return cmid
        else:
            logger.error(f"No se pudo obtener 'cmid' al agregar recurso {modulename} '{name}'. Respuesta: {respuesta_agregar}")
            return None

    except Exception as e:
        logger.error(f"Error en agregar_recurso_moodle ({modulename} '{name}'): {str(e)}", exc_info=True)
        return None
    finally:
        if close_client_locally and client:
            await client.aclose()

# Modelos de datos
class CreateAIRequest(BaseModel):
    course_id: int = Field(..., description="ID del curso en Moodle")
    user_id: int = Field(..., description="ID del usuario en Moodle")
    # folder_name ya no se usa directamente para crear la sección principal, se usa "ENTRENAI"
    # y la carpeta interna "Archivos para Contexto de Inteligencia Artificial"

class FileInfo(BaseModel):
    filename: str
    url: str
    timestamp: datetime = Field(default_factory=datetime.now)
    file_id: Optional[int] = None

class FilesEvent(BaseModel):
    course_id: int
    files: List[FileInfo]

# Funciones para obtener configuración
def get_moodle_config():
    return {
        "url": os.getenv("MOODLE_URL", "http://localhost:8081"),
        "token": os.getenv("MOODLE_TOKEN", ""),
    }

def get_qdrant_config():
    return {
        "url": os.getenv("QDRANT_URL", "http://localhost:6333"),
        "api_key": os.getenv("QDRANT_API_KEY", ""),
    }

def get_n8n_config():
    return {
        "url": os.getenv("N8N_URL", "http://localhost:5678"),
        "api_key": os.getenv("N8N_API_KEY", ""),
    }

@router.post("/create-virtual-ai", status_code=201)
async def create_virtual_ai(
    request: CreateAIRequest,
    moodle_config: dict = Depends(get_moodle_config),
    qdrant_config: dict = Depends(get_qdrant_config),
    n8n_config: dict = Depends(get_n8n_config),
):
    async with httpx.AsyncClient(timeout=60.0) as client: # Usar un solo cliente para todas las llamadas
        try:
            # 1. Crear y configurar la sección "ENTRENAI" en Moodle
            nombre_seccion_entrenai = "ENTRENAI"
            resumen_seccion_entrenai = "Sección para la Inteligencia Artificial ENTRENAI y sus recursos."
            # Posición 0 para que esté lo más arriba posible (según solicitud del usuario)
            # El plugin local_wsmanagesections_create_sections usa 'position' como el número de sección
            # *antes* de la cual se insertará la nueva.
            # Si position=0, se inserta antes de la sección 0 (generalmente la cabecera del curso).
            # Si position=1, se inserta antes de la sección 1 (convirtiéndose en la nueva sección 1).
            # El usuario especificó "seccion 0, la primera posicion".
            # Si Moodle no permite crear una sección temática con índice 0, el plugin podría fallar o
            # crearla como la primera sección temática (índice 1).
            # Se usará position=0 según lo solicitado.
            
            logger.info(f"Iniciando creación de IA virtual para curso ID: {request.course_id}")
            seccion_entrenai_info = await crear_y_configurar_seccion_plugin(
                moodle_config,
                request.course_id,
                position=0, 
                nombre_seccion=nombre_seccion_entrenai,
                resumen_seccion=resumen_seccion_entrenai,
                client=client
            )

            if not seccion_entrenai_info or "id" not in seccion_entrenai_info:
                raise HTTPException(
                    status_code=500, # Internal Server Error
                    detail=f"Error crítico: No se pudo crear o configurar la sección '{nombre_seccion_entrenai}' en Moodle.",
                )
            entrenai_section_id = seccion_entrenai_info["id"]
            logger.info(f"Sección '{nombre_seccion_entrenai}' creada/configurada con ID: {entrenai_section_id}")
            
            # 2. Crear colección en Qdrant (lógica existente)
            collection_name = f"curso_{request.course_id}"
            logger.info(f"Creando colección en Qdrant: {collection_name}")
            qdrant_result = await create_qdrant_collection( # Esta función ya usa httpx.AsyncClient internamente
                collection_name=collection_name, qdrant_config=qdrant_config
            )
            logger.info(f"Resultado de creación de colección Qdrant: {qdrant_result}")

            # 3. Crear workflow en N8n (lógica existente)
            logger.info(f"Creando workflow en N8n para curso {request.course_id}")
            workflow_id = await create_n8n_workflow( # Esta función ya usa httpx.AsyncClient internamente
                course_id=request.course_id,
                collection_name=collection_name,
                n8n_config=n8n_config,
            )
            logger.info(f"Workflow N8n creado/activado con ID: {workflow_id}")

            # 4. Crear Carpeta "Archivos para Contexto de Inteligencia Artificial" en la sección ENTRENAI
            nombre_carpeta_contexto = "Archivos para Contexto de Inteligencia Artificial"
            intro_carpeta_contexto = "Carpeta para los archivos que utilizará ENTRENAI para generar respuestas."
            logger.info(f"Creando carpeta '{nombre_carpeta_contexto}' en sección ID {entrenai_section_id}")
            carpeta_contexto_cmid = await agregar_recurso_moodle(
                moodle_config,
                request.course_id,
                entrenai_section_id,
                modulename="folder",
                name=nombre_carpeta_contexto,
                intro=intro_carpeta_contexto,
                client=client
            )
            if carpeta_contexto_cmid is None:
                logger.warning(f"No se pudo crear la carpeta '{nombre_carpeta_contexto}' en la sección {entrenai_section_id}.")
            else:
                logger.info(f"Carpeta '{nombre_carpeta_contexto}' creada con cmid: {carpeta_contexto_cmid}")

            # 5. Crear Enlace "Refrescar Archivos de Contexto"
            # URL base de FastAPI (localhost:8000 por defecto)
            # El endpoint de refresco debe ser GET para que un link funcione directamente.
            # Si /moodle/incoming-files es POST, este link no lo activará directamente.
            # Se crea el link; la funcionalidad del endpoint de refresco es responsabilidad del usuario.
            # Usaremos una URL hipotética GET que el usuario deberá implementar.
            # El usuario indicó "localhost" para pruebas.
            api_base_url_for_links = "http://localhost:8000" # Asumiendo que FastAPI corre en 8000
            url_refresco = f"{api_base_url_for_links}/moodle/course/{request.course_id}/trigger-file-refresh" # Endpoint GET hipotético
            nombre_url_refresco = "Refrescar Archivos de Contexto (IA)"
            intro_url_refresco = "Haz clic aquí para indicarle al sistema que procese los archivos más recientes de la carpeta de contexto."
            logger.info(f"Creando URL de refresco '{nombre_url_refresco}' apuntando a {url_refresco}")
            
            refresco_cmid = await agregar_recurso_moodle(
                moodle_config,
                request.course_id,
                entrenai_section_id,
                modulename="url",
                name=nombre_url_refresco,
                externalurl=url_refresco,
                intro=intro_url_refresco,
                client=client
            )
            if refresco_cmid is None:
                 logger.warning(f"No se pudo crear el enlace URL de refresco.")
            else:
                logger.info(f"Enlace URL de refresco creado con cmid: {refresco_cmid}")


            # 6. Crear Enlace "Chat con ENTRENAI"
            url_chat_n8n = f"{n8n_config['url'].rstrip('/')}/webhook/{workflow_id}"
            nombre_url_chat = "Chat con ENTRENAI"
            intro_url_chat = "Accede al chat interactivo con la inteligencia artificial personalizada para este curso."
            logger.info(f"Creando URL de chat '{nombre_url_chat}' apuntando a {url_chat_n8n}")

            chat_cmid = await agregar_recurso_moodle(
                moodle_config,
                request.course_id,
                entrenai_section_id,
                modulename="url",
                name=nombre_url_chat,
                externalurl=url_chat_n8n,
                intro=intro_url_chat,
                display=2, # Abrir en nueva ventana
                client=client
            )
            if chat_cmid is None:
                logger.warning(f"No se pudo crear el enlace URL del chat.")
            else:
                logger.info(f"Enlace URL de chat creado con cmid: {chat_cmid}")

            # Devolver resultado
            return {
                "status": "success",
                "message": "Inteligencia virtual ENTRENAI configurada exitosamente en Moodle.",
                "data": {
                    "course_id": request.course_id,
                    "entrenai_section_id": entrenai_section_id,
                    "entrenai_section_number": seccion_entrenai_info.get("number", "Desconocido"),
                    "context_folder_cmid": carpeta_contexto_cmid,
                    "refresh_link_cmid": refresco_cmid,
                    "chat_link_cmid": chat_cmid,
                    "collection_name": collection_name,
                    "qdrant_result": qdrant_result,
                    "workflow_id": workflow_id,
                    "chat_url_n8n": url_chat_n8n,
                },
            }
        except HTTPException: # Re-raise HTTPExceptions para que FastAPI las maneje
            raise
        except Exception as e:
            logger.error(f"Error general al crear la inteligencia virtual para el curso {request.course_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Error general al crear la inteligencia virtual: {str(e)}"
            )

@router.post("/incoming-files", status_code=200)
async def incoming_files(
    event: FilesEvent,
    moodle_config: dict = Depends(get_moodle_config), # No se usa moodle_config aquí actualmente
):
    try:
        logger.info(f"Evento de archivos entrantes recibido para curso {event.course_id}: {len(event.files)} archivos.")
        # Esta función solo registra los archivos por ahora
        # La implementación completa debería:
        # 1. Verificar si los archivos ya están procesados en MongoDB
        # 2. Descargar los nuevos archivos (usando cliente Moodle y URLs de FileInfo)
        # 3. Procesarlos usando la lógica existente (ej. Bytewax)
        # 4. Guardarlos en MongoDB
        # 5. Encolar el procesamiento de vectores para Qdrant

        return {
            "status": "success",
            "message": f"Evento de {len(event.files)} archivos para el curso {event.course_id} registrado. Implementación de procesamiento pendiente.",
            "files_received": [file.dict() for file in event.files]
        }
    except Exception as e:
        logger.error(f"Error al procesar el evento de archivos entrantes: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error al procesar el evento de archivos: {str(e)}"
        )

# La función create_moodle_folder original se elimina ya que no se usa y era incorrecta para carpetas de recursos.

async def create_qdrant_collection(collection_name: str, qdrant_config: dict) -> dict:
    """Crea una colección en Qdrant"""
    # Esta función ya usa su propio httpx.AsyncClient
    async with httpx.AsyncClient() as client:
        headers = {}
        if qdrant_config["api_key"]:
            headers["api-key"] = qdrant_config["api_key"]

        logger.info(f"Verificando/Creando colección Qdrant: {collection_name}")
        response = await client.get(
            f"{qdrant_config['url']}/collections/{collection_name}", headers=headers
        )

        if response.status_code == 200:
            logger.info(f"Colección Qdrant '{collection_name}' ya existe.")
            return {
                "status": "exists",
                "collection_name": collection_name,
                "message": "La colección ya existe",
            }

        payload = {
            "name": collection_name,
            "vectors": {
                "size": 384, 
                "distance": "Cosine",
            },
        }
        logger.info(f"Creando colección Qdrant '{collection_name}' con payload: {payload}")
        response = await client.put(
            f"{qdrant_config['url']}/collections/{collection_name}",
            json=payload,
            headers=headers,
        )

        if response.status_code != 200:
            detail = f"Error al crear colección en Qdrant '{collection_name}': {response.text}"
            logger.error(detail)
            raise HTTPException(status_code=500,detail=detail)
        
        logger.info(f"Colección Qdrant '{collection_name}' creada exitosamente.")
        return {
            "status": "created",
            "collection_name": collection_name,
            "message": "Colección creada exitosamente",
        }

async def create_n8n_workflow(
    course_id: int, collection_name: str, n8n_config: dict
) -> str:
    """Crea un workflow en N8n basado en la plantilla proporcionada"""
    # Esta función ya usa su propio httpx.AsyncClient
    async with httpx.AsyncClient() as client:
        headers = {
            "X-N8N-API-KEY": n8n_config["api_key"],
            "Content-Type": "application/json",
        }
        workflow_template_path = "ai_chat_n8n.json"
        logger.info(f"Creando workflow N8n para curso {course_id} usando plantilla '{workflow_template_path}'")

        try:
            with open(workflow_template_path, "r") as f:
                workflow_template = json.load(f)

            workflow_template["name"] = f"EntrenaAI - Curso {course_id}"
            logger.info(f"Nombre del workflow N8n: {workflow_template['name']}")

            for node in workflow_template["nodes"]:
                if node.get("type") == "@n8n/n8n-nodes-langchain.vectorStoreQdrant":
                    node["parameters"]["qdrantCollection"]["value"] = collection_name
                    node["parameters"]["qdrantCollection"]["cachedResultName"] = collection_name
                    
                    # Actualizar filtro si existe
                    if "options" in node["parameters"] and "searchFilterJson" in node["parameters"]["options"]:
                        try:
                            search_filter = json.loads(node["parameters"]["options"]["searchFilterJson"])
                            if "should" in search_filter: # Asumiendo estructura específica
                                for condition in search_filter["should"]:
                                    if condition.get("key") == "metadata.batch": # Ejemplo
                                        condition["match"]["value"] = course_id # Actualizar ID del curso
                            node["parameters"]["options"]["searchFilterJson"] = json.dumps(search_filter)
                            logger.info(f"Filtro de Qdrant en N8n actualizado para collection '{collection_name}', course_id '{course_id}'")
                        except json.JSONDecodeError:
                            logger.warning("No se pudo parsear searchFilterJson en nodo Qdrant de N8n.")
                        except KeyError:
                            logger.warning("Estructura inesperada en searchFilterJson de N8n.")


            logger.info(f"Enviando plantilla de workflow a N8n: {n8n_config['url']}/api/workflows")
            response = await client.post(
                f"{n8n_config['url'].rstrip('/')}/api/workflows",
                json=workflow_template,
                headers=headers,
            )

            if response.status_code not in [200, 201]:
                detail = f"Error al crear workflow en N8n: {response.status_code} - {response.text}"
                logger.error(detail)
                raise HTTPException(status_code=500, detail=detail)

            result = response.json()
            workflow_id = result.get("id")
            if not workflow_id:
                detail = f"No se pudo obtener ID del workflow N8n creado. Respuesta: {result}"
                logger.error(detail)
                raise HTTPException(status_code=500, detail=detail)
            
            logger.info(f"Workflow N8n creado con ID: {workflow_id}. Activando...")
            
            activate_response = await client.post(
                f"{n8n_config['url'].rstrip('/')}/api/workflows/{workflow_id}/activate",
                headers=headers,
            )

            if activate_response.status_code not in [200, 201]:
                detail = f"Error al activar workflow N8n ID {workflow_id}: {activate_response.status_code} - {activate_response.text}"
                logger.error(detail)
                # No necesariamente fallar toda la operación si solo la activación falla, pero loguear severamente.
                # raise HTTPException(status_code=500, detail=detail) # Opcional: fallar si la activación es crítica
            else:
                logger.info(f"Workflow N8n ID {workflow_id} activado exitosamente.")

            return str(workflow_id)

        except FileNotFoundError:
            detail = f"No se encontró la plantilla de workflow N8n: '{workflow_template_path}'"
            logger.error(detail)
            raise HTTPException(status_code=500, detail=detail)
        except Exception as e:
            detail = f"Error inesperado durante creación de workflow N8n: {str(e)}"
            logger.error(detail, exc_info=True)
            raise HTTPException(status_code=500, detail=detail)
