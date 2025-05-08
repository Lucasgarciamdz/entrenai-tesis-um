# app/clientes/cliente_n8n.py
import httpx
import json
import os
from typing import Optional, Dict, Any, List  # Añadir List
import traceback  # Importar traceback para logging de errores

# Asumiendo que la configuración es accesible de forma similar a otros clientes
# Necesitamos ir dos niveles arriba desde app/clientes/ para llegar a app/
from ..config.configuracion import configuracion


class ClienteN8N:
    """Cliente básico para interactuar con la API REST de N8N."""

    def __init__(self):
        """Inicializa el cliente N8N."""
        self.api_url = configuracion.obtener(
            "N8N_URL_API"
        )  # ej: http://localhost:5678/api/v1
        self.api_key = configuracion.obtener("N8N_API_KEY")
        self.base_url = configuracion.obtener(
            "N8N_URL_BASE"
        )  # ej: http://localhost:5678

        if not self.api_url or not self.api_key:
            print(
                "ADVERTENCIA: N8N_URL_API o N8N_API_KEY no están configuradas en el entorno."
            )
            # Considerar lanzar un error si la configuración es esencial para la operación
            # raise ValueError("Configuración de N8N incompleta (URL o API Key)")

    async def crear_workflow_curso(
        self,
        course_id: int,
        workflow_base_json_path: str,
        course_name: Optional[str] = None,
        course_name_slug: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Crea o encuentra un workflow en N8N para un curso específico, personalizando una plantilla base.

        Args:
            course_id: ID del curso.
            workflow_base_json_path: Ruta al archivo JSON de la plantilla del workflow.
            course_name: Nombre completo del curso (para el nombre del workflow).
            course_name_slug: Slug del nombre del curso (para el toolName).

        Returns:
            Un diccionario con la información del workflow creado/existente (incluyendo 'id' y 'webhook_url')
            o None si hubo un error.
        """
        if not self.api_url or not self.api_key:
            print("Error: Configuración de N8N incompleta para crear/obtener workflow.")
            return None

        # Construir nombre esperado del workflow
        if course_name:
            expected_workflow_name = (
                f"EntrenAI Chat - Curso {course_id} ({course_name})"
            )
        else:
            expected_workflow_name = f"EntrenAI Chat - Curso {course_id}"

        # Verificar si ya existe un workflow con ese nombre
        existing_workflows = await self.obtener_workflows(
            params={"name": expected_workflow_name, "limit": 1}
        )  # limit=1 es optimización
        if existing_workflows and len(existing_workflows) > 0:
            existing_workflow = existing_workflows[0]
            workflow_id = existing_workflow.get("id")
            print(
                f"Workflow '{expected_workflow_name}' ya existe con ID: {workflow_id}. No se creará uno nuevo."
            )

            n8n_webhook_url = None
            if self.base_url and workflow_id:
                n8n_webhook_url = f"{self.base_url.rstrip('/')}/webhook/{workflow_id}"
                print(
                    f"URL del webhook de N8N (chat) para workflow existente: {n8n_webhook_url}"
                )
            else:
                print(
                    "Advertencia: N8N_URL_BASE no configurada o ID de workflow no encontrado, no se puede generar URL de chat para workflow existente."
                )

            return {
                "id": workflow_id,
                "webhook_url": n8n_webhook_url,
                "raw_response": existing_workflow,
            }

        # Si no existe, proceder a crearlo
        print(
            f"No se encontró workflow existente con nombre '{expected_workflow_name}'. Se procederá a crear uno nuevo."
        )

        if not os.path.exists(workflow_base_json_path):
            print(
                f"Error: Archivo base del workflow no encontrado en {workflow_base_json_path}"
            )
            return None

        try:
            with open(workflow_base_json_path, "r") as f:
                n8n_workflow_data = json.load(f)

            # --- Personalización del Workflow ---
            n8n_workflow_data["name"] = expected_workflow_name
            # n8n_workflow_data["active"] = True # El campo 'active' es de solo lectura al crear, se activa después si es necesario.

            # Obtener prefijo de colección y construir nombre de colección Qdrant
            qdrant_collection_prefix = configuracion.obtener(
                "QDRANT_COLLECTION_PREFIX", "curso_"
            )
            if course_name_slug:
                # Limitar longitud del slug si es necesario
                max_slug_len = 50  # Ajustar si es necesario
                safe_slug = course_name_slug[:max_slug_len]
                qdrant_collection_name = (
                    f"{qdrant_collection_prefix}{course_id}_{safe_slug}"
                )
            else:
                qdrant_collection_name = f"{qdrant_collection_prefix}{course_id}"

            # Construir toolName
            tool_name = f"herramienta_curso_{course_id}"
            if course_name_slug:
                max_slug_len_tool = 40  # Limitar un poco más para toolName
                safe_slug_tool = course_name_slug[:max_slug_len_tool]
                tool_name = f"herramienta_curso_{course_id}_{safe_slug_tool}"

            node_modified = False
            for node in n8n_workflow_data.get("nodes", []):
                # Buscar el nodo específico de Qdrant Vector Store
                if node.get("type") == "@n8n/n8n-nodes-langchain.vectorStoreQdrant":
                    if "parameters" in node:
                        # Actualizar el nombre de la colección Qdrant
                        if "qdrantCollection" in node["parameters"] and isinstance(
                            node["parameters"]["qdrantCollection"], dict
                        ):
                            node["parameters"]["qdrantCollection"]["value"] = (
                                qdrant_collection_name
                            )

                        # Actualizar el nombre de la herramienta
                        node["parameters"]["toolName"] = tool_name

                        # Asegurar que 'options' existe y establecer 'searchFilterJson' a un objeto vacío
                        if "options" not in node["parameters"]:
                            node["parameters"]["options"] = {}
                        node["parameters"]["options"]["searchFilterJson"] = (
                            "{}"  # Filtro vacío
                        )

                        print(
                            f"Nodo Qdrant modificado para la colección: {qdrant_collection_name} y toolName: {tool_name}"
                        )
                        node_modified = True
                        # Romper el bucle si solo hay un nodo Qdrant que modificar
                        # break

            if not node_modified:
                print(
                    f"Advertencia: No se encontró un nodo de tipo '@n8n/n8n-nodes-langchain.vectorStoreQdrant' en la plantilla {workflow_base_json_path} para modificar."
                )
            # --- Fin Personalización ---

            # Eliminar campos que N8N gestiona internamente y no deben enviarse al crear
            # según la documentación proporcionada y errores previos.
            keys_to_remove_root = [
                "id",
                "versionId",
                "meta",
                "pinData",
                "tags",
                "active",
            ]  # 'active' ya estaba comentado
            for key in keys_to_remove_root:
                n8n_workflow_data.pop(key, None)

            # Eliminar webhookId de los nodos ChatTrigger, ya que N8N lo generará.
            # La documentación de request muestra "webhookId": "string", pero es más seguro
            # dejar que N8N lo asigne al crear un nuevo workflow desde una plantilla.
            for node in n8n_workflow_data.get("nodes", []):
                if node.get("type") == "@n8n/n8n-nodes-langchain.chatTrigger":
                    if "webhookId" in node:
                        del node["webhookId"]
                    # También es prudente eliminarlo de parameters si estuviera allí, aunque no es común
                    if "parameters" in node and "webhookId" in node["parameters"]:
                        del node["parameters"]["webhookId"]

            headers = {
                "X-N8N-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }
            # Asegurarse de que la URL no tenga doble barra al final
            create_workflow_url = f"{self.api_url.rstrip('/')}/workflows"

            async with httpx.AsyncClient(timeout=30.0) as client:  # Añadir timeout
                print(
                    f"Enviando solicitud POST a {create_workflow_url} para crear workflow..."
                )
                # Imprimir el payload que se va a enviar para depuración
                # print(f"Payload N8N: {json.dumps(n8n_workflow_data, indent=2)}")
                response = await client.post(
                    create_workflow_url, json=n8n_workflow_data, headers=headers
                )

                if response.status_code not in [
                    200,
                    201,
                ]:  # 201 Creado, 200 OK (podría ser actualización)
                    error_detail = response.text
                    try:
                        # Intentar obtener el detalle del error del JSON si es posible
                        error_json = response.json()
                        error_detail = error_json.get("message", error_detail)
                    except json.JSONDecodeError:
                        pass  # Mantener el texto plano si no es JSON
                    print(
                        f"Error al crear workflow en N8N ({response.status_code}): {error_detail}"
                    )
                    return None

                created_workflow_info = response.json()
                workflow_id = created_workflow_info.get("id")

                if not workflow_id:
                    print(
                        f"Error: La respuesta de N8N fue exitosa ({response.status_code}) pero no contenía un ID de workflow."
                    )
                    print(f"Respuesta N8N: {created_workflow_info}")
                    return None

                print(f"Workflow creado/actualizado en N8N con ID: {workflow_id}")

                # Construir URL del webhook
                n8n_webhook_url = None
                if self.base_url:
                    # Asumiendo que el path del webhook es el ID del workflow por defecto
                    # (N8N genera esto automáticamente para triggers webhook si no se especifica path)
                    n8n_webhook_url = (
                        f"{self.base_url.rstrip('/')}/webhook/{workflow_id}"
                    )
                    print(f"URL del webhook de N8N (chat): {n8n_webhook_url}")
                else:
                    print(
                        "Advertencia: N8N_URL_BASE no configurada, no se puede generar URL de chat."
                    )

                return {
                    "id": workflow_id,
                    "webhook_url": n8n_webhook_url,
                    "raw_response": created_workflow_info,  # Devolver respuesta completa por si se necesita más info
                }

        except httpx.RequestError as exc:
            print(f"Error de red al contactar N8N en {exc.request.url!r}: {exc}")
            return None
        except FileNotFoundError:
            print(
                f"Error crítico: No se encontró el archivo base del workflow en {workflow_base_json_path}"
            )
            return None
        except json.JSONDecodeError:
            print(
                f"Error crítico: El archivo base del workflow {workflow_base_json_path} no es un JSON válido."
            )
            return None
        except Exception as e:
            print(
                f"Error inesperado al crear workflow N8N para curso {course_id}: {e}\n{traceback.format_exc()}"
            )
            return None

    async def obtener_workflows(
        self, params: Optional[Dict[str, Any]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene una lista de workflows de N8N, opcionalmente filtrada por parámetros.

        Args:
            params: Un diccionario de parámetros de consulta para la API (ej. {"name": "Mi Workflow"}).

        Returns:
            Una lista de diccionarios de workflows o None si hay un error.
        """
        if not self.api_url or not self.api_key:
            print("Error: Configuración de N8N incompleta para obtener workflows.")
            return None

        headers = {"X-N8N-API-KEY": self.api_key, "Accept": "application/json"}
        list_workflows_url = f"{self.api_url.rstrip('/')}/workflows"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                print(
                    f"Enviando solicitud GET a {list_workflows_url} con params: {params}"
                )
                response = await client.get(
                    list_workflows_url, headers=headers, params=params
                )

                if response.status_code != 200:
                    error_detail = response.text
                    try:
                        error_json = response.json()
                        error_detail = error_json.get("message", error_detail)
                    except json.JSONDecodeError:
                        pass
                    print(
                        f"Error al obtener workflows de N8N ({response.status_code}): {error_detail}"
                    )
                    return None

                # La API de N8N para listar workflows devuelve un objeto con una clave "data" que contiene la lista.
                response_data = response.json()
                if (
                    isinstance(response_data, dict)
                    and "data" in response_data
                    and isinstance(response_data["data"], list)
                ):
                    return response_data["data"]
                else:
                    # Si la respuesta no es el formato esperado (ej. en algunas versiones antiguas o configuraciones)
                    # y es directamente una lista, la devolvemos.
                    if isinstance(response_data, list):
                        print(
                            "Advertencia: La API de workflows devolvió una lista directamente en lugar de {'data': [...]}."
                        )
                        return response_data
                    print(
                        f"Error: Formato de respuesta inesperado al listar workflows: {response_data}"
                    )
                    return None

        except httpx.RequestError as exc:
            print(
                f"Error de red al contactar N8N para obtener workflows en {exc.request.url!r}: {exc}"
            )
            return None
        except Exception as e:
            print(
                f"Error inesperado al obtener workflows de N8N: {e}\n{traceback.format_exc()}"
            )
            return None


# Podríamos instanciarlo globalmente si se usa a menudo, o instanciar bajo demanda.
# cliente_n8n = ClienteN8N()
