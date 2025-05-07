import httpx
import json
import os
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# Configuración del router
router = APIRouter(prefix="/moodle", tags=["moodle"])

# Modelos de datos
class CreateAIRequest(BaseModel):
    course_id: int = Field(..., description="ID del curso en Moodle")
    user_id: int = Field(..., description="ID del usuario en Moodle")
    folder_name: str = Field(default="entrenaí", description="Nombre de la carpeta a crear")

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

# Endpoints
@router.post("/create-virtual-ai", status_code=201)
async def create_virtual_ai(
    request: CreateAIRequest,
    moodle_config: dict = Depends(get_moodle_config),
    qdrant_config: dict = Depends(get_qdrant_config),
    n8n_config: dict = Depends(get_n8n_config),
):
    try:
        # 1. Crear carpeta en Moodle
        folder_id = await create_moodle_folder(
            course_id=request.course_id,
            folder_name=request.folder_name,
            moodle_config=moodle_config
        )
        
        # 2. Crear colección en Qdrant
        collection_name = f"curso_{request.course_id}"
        qdrant_result = await create_qdrant_collection(
            collection_name=collection_name,
            qdrant_config=qdrant_config
        )
        
        # 3. Crear workflow en N8n
        workflow_id = await create_n8n_workflow(
            course_id=request.course_id,
            collection_name=collection_name,
            n8n_config=n8n_config
        )
        
        # Devolver resultado
        return {
            "status": "success",
            "message": "Inteligencia virtual creada exitosamente",
            "data": {
                "course_id": request.course_id,
                "folder_id": folder_id,
                "folder_name": request.folder_name,
                "collection_name": collection_name,
                "workflow_id": workflow_id,
                "chat_url": f"{n8n_config['url']}/webhook/{workflow_id}"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear la inteligencia virtual: {str(e)}")

@router.post("/incoming-files", status_code=200)
async def incoming_files(
    event: FilesEvent,
    moodle_config: dict = Depends(get_moodle_config),
):
    try:
        # Esta función solo registra los archivos por ahora
        # La implementación completa debería:
        # 1. Verificar si los archivos ya están procesados en MongoDB
        # 2. Descargar los nuevos archivos
        # 3. Procesarlos usando la lógica existente
        # 4. Guardarlos en MongoDB
        # 5. Encolar el procesamiento de vectores
        
        return {
            "status": "success",
            "message": f"Se procesaron {len(event.files)} archivos para el curso {event.course_id}",
            "pending_implementation": "Esta función solo registra los archivos recibidos, pero no implementa la descarga y procesamiento completo"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar los archivos: {str(e)}")

# Funciones auxiliares
async def create_moodle_folder(course_id: int, folder_name: str, moodle_config: dict) -> int:
    """Crea una carpeta en un curso de Moodle usando la API de Moodle"""
    
    async with httpx.AsyncClient() as client:
        # Parámetros para la API de Moodle
        params = {
            "wstoken": moodle_config["token"],
            "wsfunction": "core_course_create_categories",
            "moodlewsrestformat": "json",
            "categories[0][name]": folder_name,
            "categories[0][parent]": course_id,
            "categories[0][description]": "Carpeta para subir archivos para entrenar la IA"
        }
        
        response = await client.post(f"{moodle_config['url']}/webservice/rest/server.php", params=params)
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Error al crear carpeta en Moodle: {response.text}")
        
        # El ID de la carpeta creada estaría en la respuesta
        # Nota: La implementación real deberá adaptarse a la estructura exacta de la respuesta
        result = response.json()
        
        # Simulación para el POC
        folder_id = result[0]["id"] if isinstance(result, list) and len(result) > 0 else 999
        
        return folder_id

async def create_qdrant_collection(collection_name: str, qdrant_config: dict) -> dict:
    """Crea una colección en Qdrant"""
    
    async with httpx.AsyncClient() as client:
        headers = {}
        if qdrant_config["api_key"]:
            headers["api-key"] = qdrant_config["api_key"]
        
        # Verificar si la colección ya existe
        response = await client.get(
            f"{qdrant_config['url']}/collections/{collection_name}",
            headers=headers
        )
        
        # Si la colección ya existe, devolver información
        if response.status_code == 200:
            return {
                "status": "exists",
                "collection_name": collection_name,
                "message": "La colección ya existe"
            }
        
        # Crear la colección si no existe
        payload = {
            "name": collection_name,
            "vectors": {
                "size": 384,  # Dimensión por defecto para embeddings
                "distance": "Cosine"
            }
        }
        
        response = await client.put(
            f"{qdrant_config['url']}/collections/{collection_name}",
            json=payload,
            headers=headers
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Error al crear colección en Qdrant: {response.text}")
        
        return {
            "status": "created",
            "collection_name": collection_name,
            "message": "Colección creada exitosamente"
        }

async def create_n8n_workflow(course_id: int, collection_name: str, n8n_config: dict) -> str:
    """Crea un workflow en N8n basado en la plantilla proporcionada"""
    
    async with httpx.AsyncClient() as client:
        headers = {
            "X-N8N-API-KEY": n8n_config["api_key"],
            "Content-Type": "application/json"
        }
        
        # Cargar la plantilla de workflow
        try:
            with open("ai_chat_n8n.json", "r") as f:
                workflow_template = json.load(f)
                
            # Modificar la plantilla para el curso específico
            workflow_template["name"] = f"EntrenaAI - Curso {course_id}"
            
            # Buscar y actualizar el nodo de Qdrant Vector Store
            for node in workflow_template["nodes"]:
                if node["type"] == "@n8n/n8n-nodes-langchain.vectorStoreQdrant":
                    node["parameters"]["qdrantCollection"]["value"] = collection_name
                    node["parameters"]["qdrantCollection"]["cachedResultName"] = collection_name
                    # Actualizar el filtro para incluir el ID del curso
                    search_filter = json.loads(node["parameters"]["options"]["searchFilterJson"])
                    if "should" in search_filter:
                        for condition in search_filter["should"]:
                            if "key" in condition and condition["key"] == "metadata.batch":
                                condition["match"]["value"] = course_id
                    node["parameters"]["options"]["searchFilterJson"] = json.dumps(search_filter)
            
            # Crear el workflow en N8n
            response = await client.post(
                f"{n8n_config['url']}/api/workflows",
                json=workflow_template,
                headers=headers
            )
            
            if response.status_code not in [200, 201]:
                raise HTTPException(status_code=500, detail=f"Error al crear workflow en N8n: {response.text}")
            
            result = response.json()
            workflow_id = result.get("id", "unknown")
            
            # Activar el workflow
            activate_response = await client.post(
                f"{n8n_config['url']}/api/workflows/{workflow_id}/activate",
                headers=headers
            )
            
            if activate_response.status_code not in [200, 201]:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Error al activar workflow en N8n: {activate_response.text}"
                )
            
            return workflow_id
            
        except FileNotFoundError:
            raise HTTPException(
                status_code=500, 
                detail="No se encontró la plantilla de workflow ai_chat_n8n.json"
            ) 