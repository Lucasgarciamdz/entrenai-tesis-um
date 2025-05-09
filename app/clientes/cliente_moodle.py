"""
Cliente para interactuar con la API REST de Moodle.

Este módulo contiene la clase ClienteMoodle que permite realizar
peticiones a la API de Moodle y obtener información de cursos y recursos.
"""

import requests
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin


class MoodleAPIException(Exception):
    """Excepción personalizada para errores de la API de Moodle."""

    def __init__(
        self,
        message: str,
        errorcode: Optional[str] = None,
        wsfunction: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.errorcode = errorcode
        self.wsfunction = wsfunction
        self.details = details

    def __str__(self):
        return f"MoodleAPIException: {super().__str__()} (Function: {self.wsfunction}, ErrorCode: {self.errorcode}, Details: {self.details})"


class ClienteMoodle:
    """Cliente para interactuar con la API REST de Moodle."""

    def __init__(self, url_base: str, token: str):
        """
        Inicializa el cliente de Moodle.

        Args:
            url_base: URL base de la instalación de Moodle
            token: Token de autenticación para la API web
        """
        self.url_base = url_base.rstrip("/")
        self.token = token
        self.endpoint = f"{self.url_base}/webservice/rest/server.php"

    def _hacer_peticion(
        self, funcion: str, parametros: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Realiza una petición a la API de Moodle.

        Args:
            funcion: Nombre de la función de la API (wsfunction)
            parametros: Parámetros adicionales para la llamada

        Returns:
            Respuesta de la API en formato diccionario

        Raises:
            requests.HTTPError: Si la petición falla
            MoodleAPIException: Si la respuesta de Moodle indica un error.
        """
        params = {
            "wstoken": self.token,
            "moodlewsrestformat": "json",
            "wsfunction": funcion,
        }

        if parametros:
            # Aplanar diccionarios anidados como 'instance' si existen
            params_aplanados = {}
            for key, value in parametros.items():
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        params_aplanados[f"{key}[{sub_key}]"] = sub_value
                elif isinstance(
                    value, list
                ):  # Si el valor es una lista (como 'sections')
                    for i, item in enumerate(value):
                        if isinstance(
                            item, dict
                        ):  # Si el item de la lista es un diccionario
                            for sub_key, sub_value in item.items():
                                params_aplanados[f"{key}[{i}][{sub_key}]"] = sub_value
                        else:  # Si el item de la lista es un valor simple
                            params_aplanados[f"{key}[{i}]"] = item
                else:
                    params_aplanados[key] = value
            params.update(params_aplanados)

        # print(f"DEBUG Moodle Request Params for {funcion}: {params}") # Descomentar para ver params finales

        respuesta = requests.get(self.endpoint, params=params, timeout=30)

        respuesta.raise_for_status()

        json_response = respuesta.json()
        print(
            f"DEBUG Moodle Parsed JSON Response for function {funcion}: {json_response}"
        )

        if isinstance(json_response, dict) and (
            "exception" in json_response or "errorcode" in json_response
        ):
            error_message = json_response.get("message", str(json_response))
            error_code = json_response.get("errorcode")
            exception_type = json_response.get("exception")

            print(f"ERROR Moodle API para {funcion}: {json_response}")

            # Mensaje específico si falla core_course_edit_section con invalidparameter
            if (
                funcion == "core_course_edit_section"
                and error_code == "invalidparameter"
            ):
                error_message = (
                    f"Error al llamar a '{funcion}': {error_message}. "
                    "La función singular 'core_course_edit_section' no acepta los parámetros proporcionados (probablemente porque intenta añadir en lugar de actualizar, o falta el ID de sección). "
                    "Verifique la estructura de parámetros requerida por esta función específica en su Moodle."
                )
            # Mensaje específico si falla core_course_edit_module con invalidparameter
            elif (
                funcion == "core_course_edit_module"
                and error_code == "invalidparameter"
            ):
                error_message = (
                    f"Error al llamar a '{funcion}': {error_message}. "
                    "La función singular 'core_course_edit_module' no acepta los parámetros proporcionados (probablemente porque intenta añadir en lugar de actualizar, o falta el ID del módulo/sección, o la estructura 'instance' es incorrecta). "
                    "Verifique la estructura de parámetros requerida por esta función específica en su Moodle."
                )

            raise MoodleAPIException(
                message=error_message,
                errorcode=error_code,
                wsfunction=funcion,
                details=json_response,
            )

        if funcion == "core_course_get_contents":
            if not isinstance(json_response, list):
                print(
                    f"ADVERTENCIA: core_course_get_contents no devolvió una lista. Tipo: {type(json_response)}, Valor: {json_response}"
                )

        return json_response

    def obtener_cursos(self) -> List[Dict[str, Any]]:
        """Obtiene la lista de todos los cursos disponibles."""
        return self._hacer_peticion("core_course_get_courses")

    def obtener_contenido_curso(self, id_curso: int) -> List[Dict[str, Any]]:
        """Obtiene el contenido completo de un curso específico."""
        return self._hacer_peticion("core_course_get_contents", {"courseid": id_curso})

    # NUEVAS FUNCIONES CON PLUGIN Y CORRECCIONES
    def crear_seccion_con_plugin(
        self, course_id: int, position: int, nombre_seccion: str, resumen_seccion: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Crea una nueva sección usando local_wsmanagesections_create_sections y luego
        la actualiza con local_wsmanagesections_update_sections.
        Devuelve un diccionario con 'id' y 'number' (sectionnumber) de la sección si tiene éxito.
        """
        try:
            # 1. Crear la sección
            params_crear = {"courseid": course_id, "position": position, "number": 1}
            print(f"CLIENTE_MOODLE: Creando sección con plugin: {params_crear}")
            respuesta_crear = self._hacer_peticion(
                "local_wsmanagesections_create_sections", params_crear
            )
            print(f"CLIENTE_MOODLE: Respuesta de creación de sección: {respuesta_crear}")

            if not isinstance(respuesta_crear, list) or not respuesta_crear:
                print(f"CLIENTE_MOODLE: Error - Respuesta inesperada al crear sección con plugin: {respuesta_crear}")
                return None
            
            nueva_seccion_info_raw = respuesta_crear[0]
            new_section_id = nueva_seccion_info_raw.get("sectionid") # CORREGIDO: Usar 'sectionid' en lugar de 'id'
            new_section_number = nueva_seccion_info_raw.get("sectionnumber")
            
            if new_section_number is None:
                 new_section_number = nueva_seccion_info_raw.get("section")

            if new_section_id is None:
                print(f"CLIENTE_MOODLE: Error - No se pudo obtener 'id' de la sección creada con plugin. Respuesta: {nueva_seccion_info_raw}")
                return None
            
            update_type = "id" 
            update_section_ref = new_section_id
            if new_section_number is not None:
                update_type = "num"
                update_section_ref = new_section_number
                print(f"CLIENTE_MOODLE: Sección creada con ID: {new_section_id}, Número: {new_section_number}. Actualizando por número.")
            else:
                print(f"CLIENTE_MOODLE: Sección creada con ID: {new_section_id}, sin número de sección. Actualizando por ID.")

            # 2. Actualizar la sección (nombre, resumen, visibilidad)
            params_actualizar = {
                "courseid": course_id,
                "sections": [
                    {
                        "type": update_type,
                        "section": update_section_ref,
                        "name": nombre_seccion,
                        "summary": resumen_seccion,
                        "summaryformat": 1,  # HTML
                        "visible": 1,
                        "highlight": 0,
                        "sectionformatoptions": [],
                    }
                ],
            }
            print(f"CLIENTE_MOODLE: Actualizando sección ID {new_section_id} con nombre '{nombre_seccion}' usando local_wsmanagesections_update_sections")
            self._hacer_peticion(
                "local_wsmanagesections_update_sections", params_actualizar
            )
            print(f"CLIENTE_MOODLE: Sección ID {new_section_id} actualizada con nombre '{nombre_seccion}'.")
            
            return {"id": new_section_id, "number": new_section_number if new_section_number is not None else "Desconocido"}

        except MoodleAPIException as e:
            print(f"CLIENTE_MOODLE: Error de API Moodle en crear_seccion_con_plugin: {e}")
            raise  # Re-lanza la excepción para que el llamador la maneje
        except Exception as e_gen:
            print(f"CLIENTE_MOODLE: Error general inesperado en crear_seccion_con_plugin: {e_gen}")
            raise MoodleAPIException(message=f"Error general en crear_seccion_con_plugin: {str(e_gen)}")


    def agregar_recurso_curso(
        self,
        course_id: int,
        section_id: int,
        modulename: str, # 'folder', 'url', 'label', etc.
        name: str,
        intro: str = "",
        introformat: int = 1,
        # Parámetros específicos del módulo (aplanados por _hacer_peticion)
        **kwargs: Any,
    ) -> Optional[int]:
        """
        Agrega un recurso (módulo) a una sección de un curso usando core_course_add_module.
        Devuelve el cmid (ID del módulo del curso) si tiene éxito.
        """
        try:
            # Parámetros base para core_course_add_module
            # La función _hacer_peticion se encarga de aplanar los parámetros.
            # Moodle espera los parámetros del módulo directamente, no bajo 'options' o 'instance'.
            params_api = {
                "courseid": course_id,
                "sectionid": section_id,
                "modulename": modulename,
                "name": name,
                "intro": intro,
                "introformat": introformat,
            }
            # Añadir parámetros específicos del módulo (ej. externalurl, display para 'url')
            params_api.update(kwargs)

            print(f"CLIENTE_MOODLE: Intentando agregar recurso '{modulename}' con nombre '{name}' en sección ID {section_id}. Params: {params_api}")
            
            # La función ws 'core_course_add_module' espera los parámetros del módulo como un array de objetos
            # bajo la clave 'options'. Cada objeto tiene 'name' y 'value'.
            # Esto contradice la documentación de Moodle para algunas versiones/casos.
            # El ejemplo de `rest_api_parameters` y el uso común es aplanar todo.
            # Sin embargo, `core_course_add_module` es especial.
            # Vamos a reestructurar `params_api` para que `_hacer_peticion` lo aplane correctamente
            # si `core_course_add_module` espera `options[0][name]=...`, `options[0][value]=...`
            
            # Corrección: core_course_add_module espera los parámetros del módulo como una lista de diccionarios
            # bajo la clave 'options'.
            # Ejemplo: options[0][name]=name, options[0][value]=value_of_name
            # options[1][name]=externalurl, options[1][value]=value_of_externalurl
            
            # Reestructuramos los parámetros para que se ajusten al formato esperado por core_course_add_module
            # que es una lista de diccionarios para 'options'.
            
            # Los parámetros comunes ya están en params_api.
            # Los kwargs son los específicos del módulo.
            
            # La función `core_course_add_module` espera los parámetros del módulo
            # como una lista de diccionarios bajo la clave 'options'.
            # Ejemplo: 'options[0][name]=name', 'options[0][value]=My Folder Name'
            #          'options[1][name]=intro', 'options[1][value]=Description'
            
            # El método _hacer_peticion ya aplana los diccionarios y listas.
            # Si pasamos params_api como está, se aplanará a:
            # courseid=X, sectionid=Y, modulename=folder, name=N, intro=I, externalurl=U (si existe)
            # Esto es lo que espera `core_course_add_module` según la documentación de Moodle para ws.
            # No necesita la estructura 'options[0][name]' para esta función específica.

            respuesta_api = self._hacer_peticion(
                "core_course_add_module", params_api
            )
            print(f"CLIENTE_MOODLE: Respuesta de 'core_course_add_module' para '{name}': {respuesta_api}")

            cmid = None
            # La respuesta puede ser un objeto o una lista con un objeto
            if isinstance(respuesta_api, dict) and respuesta_api.get("cmid"):
                cmid = respuesta_api["cmid"]
            elif isinstance(respuesta_api, list) and respuesta_api and isinstance(respuesta_api[0], dict) and respuesta_api[0].get("cmid"):
                cmid = respuesta_api[0]["cmid"]
            
            if cmid is not None:
                print(f"CLIENTE_MOODLE: Recurso '{name}' ({modulename}) agregado con cmid: {cmid}")
                return cmid
            else:
                print(f"CLIENTE_MOODLE: Error - No se pudo obtener 'cmid' al agregar recurso {modulename} '{name}'. Respuesta: {respuesta_api}")
                # Podría ser que la respuesta sea una lista vacía en éxito sin cmid, o un warning.
                # Si hay warnings, Moodle a veces devuelve una lista de advertencias.
                if isinstance(respuesta_api, dict) and "warnings" in respuesta_api and respuesta_api.get("warnings"):
                    print(f"CLIENTE_MOODLE: Advertencias de Moodle: {respuesta_api['warnings']}")
                    # Si hay 'instanceid' o algo similar, podría ser útil.
                    if respuesta_api.get("instanceid"): # A veces devuelve instanceid en lugar de cmid
                         print(f"CLIENTE_MOODLE: Se obtuvo instanceid: {respuesta_api['instanceid']}, pero se esperaba cmid.")
                return None

        except MoodleAPIException as e:
            print(f"CLIENTE_MOODLE: Error de API Moodle en agregar_recurso_curso ({modulename} '{name}'): {e}")
            raise
        except Exception as e_gen:
            print(f"CLIENTE_MOODLE: Error general inesperado en agregar_recurso_curso ({modulename} '{name}'): {e_gen}")
            raise MoodleAPIException(message=f"Error general en agregar_recurso_curso: {str(e_gen)}")

    # FIN DE NUEVAS FUNCIONES PRINCIPALES (crear_seccion_con_plugin, agregar_recurso_curso)

    # Nuevo método orquestador
    def configurar_seccion_entrenai(
        self,
        course_id: int,
        api_base_url: str, # Para el enlace de refresco
        n8n_webhook_url: Optional[str], # Para el enlace del chat
        nombre_seccion_principal: str = "ENTRENAI",
        nombre_carpeta_contexto: str = "Archivos para Contexto de Inteligencia Artificial", # Usado en el texto del summary
        nombre_url_refresco: str = "Refrescar Archivos de Contexto (IA)",
        nombre_url_chat: str = "Chat con ENTRENAI",
    ) -> Optional[int]:
        """
        Configura la sección 'ENTRENAI' en el curso.
        Crea la sección usando el plugin y establece su resumen para incluir
        instrucciones para la carpeta y los enlaces HTML.
        """
        try:
            print(f"CLIENTE_MOODLE: Iniciando configuración de sección '{nombre_seccion_principal}' para curso ID {course_id}")

            # 1. Construir el HTML para el resumen de la sección
            #    Este HTML contendrá las instrucciones para la carpeta y los enlaces.
            url_refresco_archivos = f"{api_base_url.rstrip('/')}/moodle/course/{course_id}/trigger-file-refresh"
            
            resumen_html = f"""
            <div>
                <h4>{nombre_carpeta_contexto}</h4>
                <p>Por favor, cree manualmente una carpeta con el nombre exacto "<strong>{nombre_carpeta_contexto}</strong>" dentro de esta sección y suba allí sus archivos de contexto.</p>
                <hr/>
                <p><a href="{url_refresco_archivos}" target="_blank">{nombre_url_refresco}</a></p>
            """
            if n8n_webhook_url:
                resumen_html += f"""
                <p><a href="{n8n_webhook_url}" target="_blank">{nombre_url_chat}</a></p>
                """
            resumen_html += "</div>"

            # 2. Crear la sección "ENTRENAI" usando el plugin y establecer su resumen con el HTML.
            seccion_info = self.crear_seccion_con_plugin(
                course_id=course_id,
                position=0, 
                nombre_seccion=nombre_seccion_principal,
                resumen_seccion=resumen_html # El resumen ahora incluye los links y la instrucción de la carpeta
            )

            if not seccion_info or "id" not in seccion_info or seccion_info["id"] is None:
                print(f"CLIENTE_MOODLE: Error crítico - No se pudo crear o configurar la sección '{nombre_seccion_principal}' usando el plugin.")
                return None 
            
            id_seccion_entrenai = seccion_info["id"]
            print(f"CLIENTE_MOODLE: Sección '{nombre_seccion_principal}' creada y configurada con ID: {id_seccion_entrenai} y resumen actualizado.")
            
            # Ya no se llama a agregar_recurso_curso para folder y urls desde aquí,
            # ya que están embebidos en el summary de la sección.
            
            return id_seccion_entrenai

        except MoodleAPIException as e:
            print(f"CLIENTE_MOODLE: Error de API Moodle durante configurar_seccion_entrenai: {e}")
            return None 
        except Exception as e_gen:
            print(f"CLIENTE_MOODLE: Error general inesperado durante configurar_seccion_entrenai: {e_gen}")
            return None


    def obtener_url_descarga(self, url_archivo: str) -> str:
        """Convierte una URL relativa de un archivo en una URL de descarga completa."""
        if url_archivo.startswith("http"):
            return url_archivo
        return urljoin(self.url_base, url_archivo)

    def descargar_archivo(self, url_archivo: str, ruta_destino: str) -> bool:
        """Descarga un archivo de Moodle."""
        url_completa = self.obtener_url_descarga(url_archivo)
        if "?" in url_completa:
            url_completa += f"&token={self.token}"
        else:
            url_completa += f"?token={self.token}"
        try:
            respuesta = requests.get(url_completa, stream=True, timeout=30)
            respuesta.raise_for_status()
            with open(ruta_destino, "wb") as archivo:
                for chunk in respuesta.iter_content(chunk_size=8192):
                    archivo.write(chunk)
            return True
        except Exception as e:
            print(f"Error al descargar archivo: {e}")
            return False

    # El método que se llamaba `crear_seccion_curso` y que contenía la lógica de `configurar_seccion_entrenai`
    # ha sido renombrado a `configurar_seccion_entrenai` y movido arriba.
    # Ahora, el método `crear_seccion_curso` original (obsoleto) se mantiene abajo.

    # Método obsoleto/incorrecto para crear secciones, se reemplaza por crear_seccion_con_plugin
    def crear_seccion_curso(
        self,
        id_curso: int,
        nombre_seccion: str,
        resumen_seccion: str = "",
        secuencia: Optional[List[int]] = None, # Parámetro no usado
    ) -> Optional[List[Dict[str, Any]]]:
        """
        [OBSOLETO PARA NUEVA LÓGICA DE SECCIÓN ENTRENAI]
        Intenta asegurar que una sección exista usando core_course_edit_section (singular).
        """
        print(f"ADVERTENCIA: Se llamó al método obsoleto ClienteMoodle.crear_seccion_curso para '{nombre_seccion}'. Usar configurar_seccion_entrenai o crear_seccion_con_plugin en su lugar.")
        try:
            secciones_actuales = self.obtener_contenido_curso(id_curso)
            seccion_existente = next(
                (s for s in secciones_actuales if s.get("name") == nombre_seccion), None
            )
            if seccion_existente:
                print(
                    f"La sección '{nombre_seccion}' ya existe en el curso {id_curso} con ID {seccion_existente.get('id')}"
                )
                return [
                    s
                    for s in secciones_actuales
                    if s.get("id") == seccion_existente.get("id")
                ]

            print(
                f"Sección '{nombre_seccion}' no encontrada. Intentando actualizar la última sección visible..."
            )
            secciones_visibles = [
                s
                for s in secciones_actuales
                if s.get("id") != 0 and s.get("uservisible", True)
            ]
            if not secciones_visibles:
                print(
                    f"ERROR CRÍTICO: No hay secciones visibles existentes en el curso {id_curso} para intentar actualizar a '{nombre_seccion}'. No se puede crear la sección con core_course_edit_section."
                )
                return None
            seccion_a_actualizar = max(
                secciones_visibles, key=lambda s: s.get("section", 0)
            )
            id_seccion_a_actualizar = seccion_a_actualizar.get("id")
            if not id_seccion_a_actualizar:
                print(
                    f"ERROR CRÍTICO: No se pudo obtener un ID válido para la última sección visible (Nombre: '{seccion_a_actualizar.get('name')}')."
                )
                return None
            print(
                f"Intentando actualizar sección ID {id_seccion_a_actualizar} (Nombre actual: '{seccion_a_actualizar.get('name')}') a '{nombre_seccion}'..."
            )
            parametros_actualizacion = {
                "sections": [ # core_course_edit_section espera un array de secciones
                    {
                        "id": id_seccion_a_actualizar,
                        "name": nombre_seccion,
                        "summary": resumen_seccion,
                        "summaryformat": 1,
                        "visible": 1,
                    }
                ]
            }
            self._hacer_peticion("core_course_edit_section", parametros_actualizacion) # Esta es la llamada problemática
            print(f"Llamada a core_course_edit_section para actualizar la sección ID {id_seccion_a_actualizar} completada.")
            secciones_despues_de_actualizar = self.obtener_contenido_curso(id_curso)
            seccion_actualizada = next(
                (s for s in secciones_despues_de_actualizar if s.get("id") == id_seccion_a_actualizar and s.get("name") == nombre_seccion), None,
            )
            if seccion_actualizada:
                print(f"Sección ID {id_seccion_a_actualizar} actualizada exitosamente a '{nombre_seccion}'.")
                return [seccion_actualizada]
            else:
                print(f"ERROR CRÍTICO: Falló el intento de actualizar la sección ID {id_seccion_a_actualizar} a '{nombre_seccion}'.")
                return None
        except MoodleAPIException as e:
            print(f"Error de API Moodle al intentar asegurar la sección '{nombre_seccion}' en el curso {id_curso} (desde método obsoleto): {e}")
            return None 
        except Exception as e_gen:
            print(f"Error general inesperado al asegurar la sección '{nombre_seccion}' en el curso {id_curso} (desde método obsoleto): {e_gen}")
            return None


    def crear_recurso_label(
        self,
        id_curso: int, 
        id_seccion: int,
        nombre: str,
        intro: str,
        introformat: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        [OBSOLETO] Crea un recurso de tipo etiqueta (label). Usar agregar_recurso_curso.
        """
        print(f"ADVERTENCIA: Se llamó al método obsoleto ClienteMoodle.crear_recurso_label para '{nombre}'. Usar agregar_recurso_curso en su lugar.")
        # raise NotImplementedError("Este método es obsoleto. Usar agregar_recurso_curso(modulename='label', ...).")
        # Para no romper, intentamos llamar a la nueva función
        cmid = self.agregar_recurso_curso(
            course_id=id_curso, # agregar_recurso_curso necesita course_id
            section_id=id_seccion,
            modulename="label",
            name=nombre,
            intro=intro,
            introformat=introformat
        )
        return {"cmid": cmid} if cmid is not None else None


    # Método obsoleto/incorrecto para crear URLs, se reemplaza por agregar_recurso_curso(modulename='url', ...)
    def crear_recurso_url(
        self,
        id_curso: int, # No usado por core_course_edit_module si se pasa cmid
        id_seccion: int,
        nombre: str,
        url_externa: str,
        intro: str = "",
        display: int = 0,
        introformat: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        [OBSOLETO] Crea un recurso de tipo URL. Usar agregar_recurso_curso.
        """
        print(f"ADVERTENCIA: Se llamó al método obsoleto ClienteMoodle.crear_recurso_url para '{nombre}'. Usar agregar_recurso_curso en su lugar.")
        # raise NotImplementedError("Este método es obsoleto. Usar agregar_recurso_curso(modulename='url', ...).")
        cmid = self.agregar_recurso_curso(
            course_id=id_curso, # agregar_recurso_curso necesita course_id
            section_id=id_seccion,
            modulename="url",
            name=nombre,
            intro=intro,
            introformat=introformat,
            externalurl=url_externa,
            display=display
        )
        return {"cmid": cmid} if cmid is not None else None
