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

    def crear_seccion_curso(
        self,
        id_curso: int,
        nombre_seccion: str,
        resumen_seccion: str = "",
        secuencia: Optional[List[int]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Intenta asegurar que una sección exista usando core_course_edit_section (singular).
        Primero busca si existe. Si no, intenta ACTUALIZAR la última sección visible.
        Este método NO PUEDE CREAR una sección nueva si no hay una candidata para actualizar.

        Args:
            id_curso: ID del curso en Moodle.
            nombre_seccion: Nombre deseado de la sección.
            resumen_seccion: Resumen o descripción de la sección.

        Returns:
            Lista con la sección encontrada o actualizada, o None si falla.
        """
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

            # Buscar la última sección visible (excluyendo la sección general id=0)
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

            # Intentar actualizar la última sección visible
            seccion_a_actualizar = max(
                secciones_visibles, key=lambda s: s.get("section", 0)
            )  # 'section' es el índice
            id_seccion_a_actualizar = seccion_a_actualizar.get("id")

            if not id_seccion_a_actualizar:
                print(
                    f"ERROR CRÍTICO: No se pudo obtener un ID válido para la última sección visible (Nombre: '{seccion_a_actualizar.get('name')}')."
                )
                return None

            print(
                f"Intentando actualizar sección ID {id_seccion_a_actualizar} (Nombre actual: '{seccion_a_actualizar.get('name')}') a '{nombre_seccion}'..."
            )

            # Parámetros para core_course_edit_section (singular) - acción de actualización
            # La acción 'update' podría ser implícita si se provee el 'id'.
            # Probar sin 'action' explícito primero.
            # core_course_edit_section espera un array de secciones.
            parametros_actualizacion = {
                "sections": [
                    {
                        "id": id_seccion_a_actualizar,
                        "name": nombre_seccion,
                        "summary": resumen_seccion,
                        "summaryformat": 1,  # HTML
                        "visible": 1,
                        # Otros parámetros como 'sequence', 'parent' podrían ser necesarios dependiendo de la configuración
                    }
                ]
            }

            # Llamar a core_course_edit_section (singular)
            self._hacer_peticion("core_course_edit_section", parametros_actualizacion)
            print(
                f"Llamada a core_course_edit_section para actualizar la sección ID {id_seccion_a_actualizar} completada."
            )

            # Verificar si la actualización fue exitosa
            secciones_despues_de_actualizar = self.obtener_contenido_curso(id_curso)
            seccion_actualizada = next(
                (
                    s
                    for s in secciones_despues_de_actualizar
                    if s.get("id") == id_seccion_a_actualizar
                    and s.get("name") == nombre_seccion
                ),
                None,
            )

            if seccion_actualizada:
                print(
                    f"Sección ID {id_seccion_a_actualizar} actualizada exitosamente a '{nombre_seccion}'."
                )
                return [seccion_actualizada]
            else:
                print(
                    f"ERROR CRÍTICO: Falló el intento de actualizar la sección ID {id_seccion_a_actualizar} a '{nombre_seccion}'."
                )
                print(
                    f"Secciones después del intento de actualización: {secciones_despues_de_actualizar}"
                )
                return None

        except MoodleAPIException as e:
            print(
                f"Error de API Moodle al intentar asegurar la sección '{nombre_seccion}' en el curso {id_curso}: {e}"
            )
            return None
        except Exception as e_gen:
            print(
                f"Error general inesperado al asegurar la sección '{nombre_seccion}' en el curso {id_curso}: {e_gen}"
            )
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
        Crea un recurso de tipo etiqueta (label) en una sección de un curso usando core_course_edit_module (singular).

        Args:
            id_curso: ID del curso (puede no ser necesario para la función singular).
            id_seccion: ID de la sección donde se creará el label.
            nombre: Nombre o título del label.
            intro: Contenido HTML del label.
            introformat: Formato del contenido (1 para HTML).

        Returns:
            Diccionario con la información del label creado (ej. cmid) o None si falla.
        """
        # Parámetros para core_course_edit_module (singular) - intento de añadir
        # La estructura exacta es incierta, probamos con 'instance'
        params_api = {
            "action": "add",  # Puede que no sea necesario o válido para la singular
            "sectionid": id_seccion,
            "modulename": "label",
            "instance": {
                "name": nombre,
                "intro": intro,
                "introformat": introformat,
            },
            # Podría necesitar courseid directamente aquí también
            # "courseid": id_curso
        }

        try:
            print(
                f"Intentando crear Label '{nombre}' en sección {id_seccion} usando core_course_edit_module con params: {params_api}"
            )
            # Llamar a la función singular
            respuesta_api = self._hacer_peticion("core_course_edit_module", params_api)

            # La respuesta de la función singular podría ser diferente.
            # Si tiene éxito al añadir, podría devolver el cmid directamente o dentro de una estructura.
            # Si solo edita, esta llamada fallará si no se provee un 'id' (cmid).
            # Asumimos por ahora que podría devolver 'cmid' si funciona.
            if isinstance(respuesta_api, dict) and respuesta_api.get("cmid"):
                cmid = respuesta_api["cmid"]
                print(
                    f"Label '{nombre}' creado/actualizado con cmid: {cmid} en sección {id_seccion}"
                )
                return {"cmid": cmid, "warnings": respuesta_api.get("warnings", [])}
            elif isinstance(respuesta_api, dict) and respuesta_api.get("warnings"):
                print(
                    f"Advertencias al crear label '{nombre}': {respuesta_api['warnings']}"
                )
                # Si hay warnings pero no cmid, probablemente falló.
                return None
            # Podría devolver un array vacío en éxito sin cmid explícito? Menos probable.
            elif isinstance(respuesta_api, list) and not respuesta_api:
                print(
                    f"Llamada a core_course_edit_module para Label '{nombre}' exitosa pero no devolvió cmid explícito. Se necesita verificar manualmente."
                )
                # No podemos retornar un cmid fiable. Considerar como fallo parcial.
                return None  # O un diccionario indicando éxito parcial

            print(
                f"Respuesta inesperada de core_course_edit_module para label '{nombre}': {respuesta_api}"
            )
            return None
        except MoodleAPIException as e:
            print(f"Error de API Moodle al crear label '{nombre}': {e}")
            return None
        except requests.HTTPError as e:
            print(
                f"Error HTTP al llamar a core_course_edit_module para crear label: {e.response.text if e.response else e}"
            )
            return None
        except Exception as e_gen:
            print(f"Error general al crear label con core_course_edit_module: {e_gen}")
            return None

    def crear_recurso_url(
        self,
        id_curso: int,
        id_seccion: int,
        nombre: str,
        url_externa: str,
        intro: str = "",
        display: int = 0,
        introformat: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Crea un recurso de tipo URL en una sección de un curso usando core_course_edit_module (singular).

        Args:
            id_curso: ID del curso (puede no ser necesario).
            id_seccion: ID de la sección donde se creará la URL.
            nombre: Nombre del recurso URL.
            url_externa: La URL a enlazar.
            intro: Descripción o introducción para la URL.
            display: Cómo mostrar la URL (0: Automático, 1: Embebido, 2: Abrir, 3: En popup).
            introformat: Formato de la introducción (1 para HTML).

        Returns:
            Diccionario con la información del recurso URL creado o None si falla.
        """
        # Parámetros para core_course_edit_module (singular) - intento de añadir
        params_api = {
            "action": "add",  # Puede que no sea necesario o válido
            "sectionid": id_seccion,
            "modulename": "url",
            "instance": {
                "name": nombre,
                "externalurl": url_externa,
                "intro": intro,
                "introformat": introformat,
                "display": display,
            },
            # "courseid": id_curso
        }

        try:
            print(
                f"Intentando crear URL '{nombre}' en sección {id_seccion} usando core_course_edit_module con params: {params_api}"
            )
            # Llamar a la función singular
            respuesta_api = self._hacer_peticion("core_course_edit_module", params_api)

            if isinstance(respuesta_api, dict) and respuesta_api.get("cmid"):
                cmid = respuesta_api["cmid"]
                print(
                    f"URL '{nombre}' creada/actualizada con cmid: {cmid} en sección {id_seccion}"
                )
                return {"cmid": cmid, "warnings": respuesta_api.get("warnings", [])}
            elif isinstance(respuesta_api, dict) and respuesta_api.get("warnings"):
                print(
                    f"Advertencias al crear URL '{nombre}': {respuesta_api['warnings']}"
                )
                return None  # Asumir fallo si no hay cmid
            elif isinstance(respuesta_api, list) and not respuesta_api:
                print(
                    f"Llamada a core_course_edit_module para URL '{nombre}' exitosa pero no devolvió cmid explícito. Se necesita verificar manualmente."
                )
                return None

            print(
                f"Respuesta inesperada de core_course_edit_module para URL '{nombre}': {respuesta_api}"
            )
            return None
        except MoodleAPIException as e:
            print(f"Error de API Moodle al crear URL '{nombre}': {e}")
            return None
        except requests.HTTPError as e:
            print(
                f"Error HTTP al llamar a core_course_edit_module para crear URL: {e.response.text if e.response else e}"
            )
            return None
        except Exception as e_gen:
            print(f"Error general al crear URL con core_course_edit_module: {e_gen}")
            return None

    def configurar_seccion_entrenai(
        self, course_id: int, api_base_url: str, n8n_webhook_url: Optional[str]
    ) -> Optional[int]:
        """
        Asegura que la sección 'Entrenai' exista en el curso y añade los recursos necesarios,
        intentando usar las funciones singulares core_course_edit_section y core_course_edit_module.

        Args:
            course_id: ID del curso de Moodle.
            api_base_url: URL base de la API de FastAPI para el enlace de refresco.
            n8n_webhook_url: URL del webhook del chat de N8N (puede ser None).

        Returns:
            El ID de la sección 'Entrenai' si la configuración fue exitosa, None en caso contrario.
        """
        moodle_section_name = "Entrenai"
        section_id = None

        try:
            # 1. Asegurar que la sección exista (intentando actualizar si no existe)
            secciones = self.crear_seccion_curso(course_id, moodle_section_name)

            if not secciones:
                print(
                    f"Error: No se pudo asegurar la existencia de la sección '{moodle_section_name}' en el curso {course_id} usando core_course_edit_section."
                )
                return None

            if not isinstance(secciones[0], dict):
                print(
                    f"Error: El resultado de crear_seccion_curso no es una lista con un diccionario. Es: {type(secciones[0])}, Valor: {secciones[0]}"
                )
                return None

            if not secciones[0].get("id"):
                print(
                    f"Error: No se pudo obtener el ID de la sección '{moodle_section_name}' en el curso {course_id}. Detalles: {secciones[0]}"
                )
                return None
            section_id = secciones[0].get("id")
            print(f"Sección '{moodle_section_name}' asegurada con ID: {section_id}")

            if section_id is None or not isinstance(section_id, int):
                print(
                    f"Error: ID de sección inválido ({section_id}) para la sección '{moodle_section_name}' en el curso {course_id}"
                )
                return None

            # 2. Crear recurso Label con instrucciones (usando core_course_edit_module)
            folder_instructions_html = """
                <div>
                    <h4>Carpeta de Archivos para IA</h4>
                    <p>Utiliza la funcionalidad estándar de Moodle para agregar una carpeta llamada "Archivos IA"
                       dentro de esta sección. Sube aquí los documentos (PDF, DOCX, TXT, MD)
                       que desees utilizar para entrenar la inteligencia artificial de este curso.</p>
                    <p>Una vez subidos los archivos, utiliza el enlace "Actualizar Contenidos de IA" para procesarlos.</p>
                </div>
            """
            label_result = self.crear_recurso_label(
                id_curso=course_id,
                id_seccion=section_id,
                nombre="Instrucciones Carpeta IA",
                intro=folder_instructions_html,
                introformat=1,
            )
            if label_result:
                print(
                    "Recurso 'label' con instrucciones para carpeta creado/actualizado."
                )
            else:
                print(
                    f"Advertencia: No se pudo crear/actualizar el recurso Label en sección {section_id}."
                )
                # Continuar de todos modos

            # 3. Crear recurso URL para actualizar contenidos (usando core_course_edit_module)
            refresh_url = f"{api_base_url.rstrip('/')}/api/v1/entrenai/refresh-content/{course_id}"
            refresh_url_result = self.crear_recurso_url(
                id_curso=course_id,
                id_seccion=section_id,
                nombre="Actualizar Contenidos de IA",
                url_externa=refresh_url,
                intro="Haz clic aquí para procesar los nuevos archivos subidos a la carpeta 'Archivos IA' y actualizar la base de conocimientos de la IA.",
                display=0,
            )
            if refresh_url_result:
                print(
                    f"Recurso URL 'Actualizar Contenidos de IA' creado/actualizado, apuntando a: {refresh_url}"
                )
            else:
                print(
                    f"Advertencia: No se pudo crear/actualizar el recurso URL de refresco en sección {section_id}."
                )
                # Continuar

            # 4. Crear recurso URL para el chat N8N (usando core_course_edit_module)
            if n8n_webhook_url:
                chat_url_result = self.crear_recurso_url(
                    id_curso=course_id,
                    id_seccion=section_id,
                    nombre="Chat con IA del Curso",
                    url_externa=n8n_webhook_url,
                    intro="Accede aquí al chat interactivo con la inteligencia artificial personalizada para este curso.",
                    display=2,
                )
                if chat_url_result:
                    print(
                        f"Recurso URL 'Chat con IA del Curso' creado/actualizado, apuntando a: {n8n_webhook_url}"
                    )
                else:
                    print(
                        f"Advertencia: No se pudo crear/actualizar el recurso URL del chat en sección {section_id}."
                    )
            else:
                print(
                    "Advertencia: No se proporcionó URL de webhook de N8N, no se creará el enlace al chat."
                )

            # Si llegamos aquí, al menos la sección fue asegurada.
            return section_id

        except Exception as e:
            # Captura cualquier otra excepción no esperada durante la configuración
            print(
                f"Error inesperado durante la configuración de la sección Entrenai para el curso {course_id}: {e}"
            )
            return None
