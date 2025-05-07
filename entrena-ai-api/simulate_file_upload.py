#!/usr/bin/env python
"""
Script para simular la subida de archivos a Moodle y enviar la notificación al backend.

Este script es una utilidad para probar el flujo sin tener que subir archivos reales a Moodle.
"""

import os
import json
import argparse
import httpx
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración por defecto
DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:8000")

def notify_file_upload(course_id, files):
    """
    Notifica al backend que se han subido archivos.
    
    Args:
        course_id: ID del curso en Moodle
        files: Lista de diccionarios con información de los archivos
            - filename: Nombre del archivo
            - url: URL del archivo en Moodle
            - file_id: ID del archivo en Moodle (opcional)
            
    Returns:
        Respuesta del API como diccionario
    """
    url = f"{DEFAULT_API_URL}/moodle/incoming-files"
    
    # Asegurarnos de que todos los archivos tengan timestamp
    for file in files:
        if "timestamp" not in file:
            file["timestamp"] = datetime.now().isoformat()
    
    payload = {
        "course_id": course_id,
        "files": files
    }
    
    print(f"Enviando notificación a {url}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = httpx.post(url, json=payload)
        response.raise_for_status()
        
        result = response.json()
        print("\nRespuesta del servidor:")
        print(json.dumps(result, indent=2))
        
        if result.get("status") == "success":
            print(f"\n✅ Notificación enviada exitosamente: {result.get('message', '')}")
            return result
        else:
            print(f"\n❌ Error: {result.get('message', 'Error desconocido')}")
            return None
            
    except httpx.HTTPStatusError as e:
        print(f"\n❌ Error HTTP {e.response.status_code}: {e.response.text}")
        return None
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        return None

def main():
    """Función principal que ejecuta el script."""
    parser = argparse.ArgumentParser(description="Simular subida de archivos a Moodle")
    parser.add_argument("--course", "-c", type=int, required=True, help="ID del curso en Moodle")
    parser.add_argument("--file", "-f", action="append", required=True, help="Ruta del archivo a simular (puede usarse múltiples veces)")
    parser.add_argument("--api-url", type=str, default=DEFAULT_API_URL, help=f"URL del API (default: {DEFAULT_API_URL})")
    
    args = parser.parse_args()
    
    # Actualizar URL del API si se proporciona
    global DEFAULT_API_URL
    DEFAULT_API_URL = args.api_url
    
    print("=== SimularArchivos - Herramienta para simular subida de archivos ===")
    print(f"API URL: {DEFAULT_API_URL}")
    print(f"Curso ID: {args.course}")
    print(f"Archivos: {', '.join(args.file)}")
    print("="*50)
    
    # Preparar información de archivos
    files_info = []
    for file_path in args.file:
        if not os.path.exists(file_path):
            print(f"⚠️ Advertencia: El archivo {file_path} no existe. Se enviará de todos modos.")
        
        filename = os.path.basename(file_path)
        # Simulamos una URL de Moodle
        url = f"http://localhost:8081/pluginfile.php/123/mod_resource/content/1/{filename}"
        
        files_info.append({
            "filename": filename,
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "file_id": 1000 + len(files_info)  # ID ficticio
        })
    
    # Enviar notificación
    notify_file_upload(args.course, files_info)

if __name__ == "__main__":
    main() 