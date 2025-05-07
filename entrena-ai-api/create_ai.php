#!/usr/bin/env python
"""
Script simple para crear una IA personalizada.

Este script es una alternativa rápida para probar el flujo sin implementar el plugin de Moodle.
"""

import os
import json
import argparse
import httpx
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración por defecto
DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:8000")

def create_ai(course_id, user_id, folder_name="entrenaí"):
    """
    Llama al endpoint de creación de IA personalizada.
    
    Args:
        course_id: ID del curso en Moodle
        user_id: ID del usuario en Moodle
        folder_name: Nombre de la carpeta a crear (por defecto: "entrenaí")
        
    Returns:
        Respuesta del API como diccionario
    """
    url = f"{DEFAULT_API_URL}/moodle/create-virtual-ai"
    payload = {
        "course_id": course_id,
        "user_id": user_id,
        "folder_name": folder_name
    }
    
    print(f"Enviando solicitud a {url}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = httpx.post(url, json=payload)
        response.raise_for_status()
        
        result = response.json()
        print("\nRespuesta del servidor:")
        print(json.dumps(result, indent=2))
        
        if result.get("status") == "success":
            print("\n✅ IA personalizada creada exitosamente!")
            
            # Mostrar URL del chat si está disponible
            if "data" in result and "chat_url" in result["data"]:
                print(f"\nChat disponible en: {result['data']['chat_url']}")
            
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
    parser = argparse.ArgumentParser(description="Crear IA personalizada para un curso de Moodle")
    parser.add_argument("--course", "-c", type=int, required=True, help="ID del curso en Moodle")
    parser.add_argument("--user", "-u", type=int, required=True, help="ID del usuario en Moodle")
    parser.add_argument("--folder", "-f", type=str, default="entrenaí", help="Nombre de la carpeta (default: entrenaí)")
    parser.add_argument("--api-url", type=str, default=DEFAULT_API_URL, help=f"URL del API (default: {DEFAULT_API_URL})")
    
    args = parser.parse_args()
    
    # Actualizar URL del API si se proporciona
    global DEFAULT_API_URL
    DEFAULT_API_URL = args.api_url
    
    print("=== CrearAI - Herramienta para crear IA personalizada ===")
    print(f"API URL: {DEFAULT_API_URL}")
    print(f"Curso ID: {args.course}")
    print(f"Usuario ID: {args.user}")
    print(f"Nombre de carpeta: {args.folder}")
    print("="*50)
    
    # Crear la IA
    create_ai(args.course, args.user, args.folder)

if __name__ == "__main__":
    main() 