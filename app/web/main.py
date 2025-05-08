from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Importar routers
from app.web.routers.moodle import router as moodle_router
from app.web.routers.entrena_ai import router as entrena_ai_router

# Cargar variables de entorno DESPUÉS de las importaciones
load_dotenv()

# Crear aplicación FastAPI
app = FastAPI(
    title="EntrenaAI API",
    description="API para integrar Moodle con inteligencia artificial personalizada",
    version="0.1.0",
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Para el POC permitimos cualquier origen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(moodle_router)
app.include_router(
    entrena_ai_router, prefix="/api/v1"
)  # Incluir el nuevo router con prefijo


# Ruta raíz
@app.get("/")
async def root():
    return {
        "message": "EntrenaAI API está funcionando",
        "documentation": "/docs",
        "endpoints": [
            {
                "path": "/moodle/create-virtual-ai",
                "method": "POST",
                "description": "Crear IA virtual personalizada",
            },
            {
                "path": "/moodle/incoming-files",
                "method": "POST",
                "description": "Procesar archivos nuevos",
            },
        ],
    }


# Para ejecutar con: uvicorn main:app --reload
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.web.main:app", host="0.0.0.0", port=8000, reload=True)
