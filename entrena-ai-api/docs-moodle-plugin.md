# Implementación del Plugin de Moodle para EntrenaAI

Este documento describe los pasos necesarios para implementar un plugin sencillo de Moodle que permita:

1. Añadir un botón "Crear IA personalizada" en la interfaz del curso
2. Detectar cuando se suben archivos a la carpeta específica y enviar notificaciones

## Estructura del Plugin

El plugin debe seguir la estructura estándar de Moodle:

```
local/entrena_ai/
├── classes/
│   ├── observer.php
│   └── external.php
├── db/
│   ├── access.php
│   ├── events.php
│   └── services.php
├── lang/
│   └── en/
│       └── local_entrena_ai.php
├── templates/
│   └── button.mustache
├── amd/
│   └── src/
│       └── button_handler.js
├── lib.php
├── version.php
└── settings.php
```

## Implementación Paso a Paso

### 1. Configuración Básica (version.php)

```php
<?php
defined('MOODLE_INTERNAL') || die();

$plugin->component = 'local_entrena_ai';
$plugin->version = 2025060100;
$plugin->requires = 2023042400; // Moodle 4.1
$plugin->maturity = MATURITY_ALPHA;
$plugin->release = 'v0.1.0';
```

### 2. Archivo de Lenguaje (lang/en/local_entrena_ai.php)

```php
<?php
$string['pluginname'] = 'EntrenaAI Integration';
$string['create_ai'] = 'Crear IA personalizada';
$string['ai_created'] = 'IA personalizada creada exitosamente';
$string['ai_creation_failed'] = 'Error al crear IA personalizada';
$string['upload_files'] = 'Subir archivos para entrenar la IA';
```

### 3. Añadir el Botón al Curso (lib.php)

```php
<?php
defined('MOODLE_INTERNAL') || die();

function local_entrena_ai_extend_navigation_course($navigation, $course, $context) {
    global $CFG, $USER;
    
    if (has_capability('local/entrena_ai:create', $context)) {
        $url = new moodle_url('/local/entrena_ai/create_ai.php', ['course' => $course->id]);
        $navigation->add(
            get_string('create_ai', 'local_entrena_ai'),
            $url,
            navigation_node::TYPE_SETTING,
            null,
            'entrena_ai',
            new pix_icon('t/add', '')
        );
    }
}
```

### 4. Clase Externa para API (classes/external.php)

```php
<?php
namespace local_entrena_ai;

defined('MOODLE_INTERNAL') || die();
require_once($CFG->libdir . '/externallib.php');

class external extends \external_api {
    /**
     * Crear IA personalizada
     */
    public static function create_ai_parameters() {
        return new \external_function_parameters([
            'courseid' => new \external_value(PARAM_INT, 'ID del curso'),
            'userid' => new \external_value(PARAM_INT, 'ID del usuario'),
            'foldername' => new \external_value(PARAM_TEXT, 'Nombre de la carpeta', VALUE_DEFAULT, 'entrenaí')
        ]);
    }

    public static function create_ai($courseid, $userid, $foldername) {
        global $CFG;
        
        // Validar parámetros
        $params = self::validate_parameters(self::create_ai_parameters(), [
            'courseid' => $courseid,
            'userid' => $userid,
            'foldername' => $foldername
        ]);
        
        // Configuración del API backend
        $api_url = get_config('local_entrena_ai', 'api_url');
        if (empty($api_url)) {
            $api_url = 'http://localhost:8000'; // Default para el POC
        }
        
        // Llamar al backend
        $curl = new \curl();
        $curl->setHeader(['Content-Type: application/json']);
        
        $payload = json_encode([
            'course_id' => $params['courseid'],
            'user_id' => $params['userid'],
            'folder_name' => $params['foldername']
        ]);
        
        $response = $curl->post($api_url . '/moodle/create-virtual-ai', $payload);
        $result = json_decode($response);
        
        return [
            'success' => $result && isset($result->status) && $result->status === 'success',
            'message' => $result && isset($result->message) ? $result->message : 'Error desconocido',
            'data' => $result && isset($result->data) ? (array)$result->data : []
        ];
    }

    public static function create_ai_returns() {
        return new \external_single_structure([
            'success' => new \external_value(PARAM_BOOL, 'Si la operación fue exitosa'),
            'message' => new \external_value(PARAM_TEXT, 'Mensaje de respuesta'),
            'data' => new \external_single_structure([
                'course_id' => new \external_value(PARAM_INT, 'ID del curso', VALUE_OPTIONAL),
                'folder_id' => new \external_value(PARAM_INT, 'ID de la carpeta creada', VALUE_OPTIONAL),
                'folder_name' => new \external_value(PARAM_TEXT, 'Nombre de la carpeta', VALUE_OPTIONAL),
                'collection_name' => new \external_value(PARAM_TEXT, 'Nombre de la colección en Qdrant', VALUE_OPTIONAL),
                'workflow_id' => new \external_value(PARAM_TEXT, 'ID del workflow en N8n', VALUE_OPTIONAL),
                'chat_url' => new \external_value(PARAM_URL, 'URL del chat', VALUE_OPTIONAL)
            ], 'Datos de respuesta', VALUE_OPTIONAL)
        ]);
    }
}
```

### 5. Observador de Eventos (classes/observer.php)

```php
<?php
namespace local_entrena_ai;

defined('MOODLE_INTERNAL') || die();

class observer {
    /**
     * Escucha eventos de subida de archivos
     */
    public static function file_uploaded(\core\event\base $event) {
        global $DB, $CFG;
        
        $eventdata = $event->get_data();
        $contextlevel = $eventdata['contextlevel'];
        
        // Solo nos interesan archivos subidos a cursos
        if ($contextlevel != CONTEXT_COURSE && $contextlevel != CONTEXT_MODULE) {
            return;
        }
        
        $courseid = $eventdata['courseid'];
        
        // Obtener información del archivo
        $fs = get_file_storage();
        $file = $fs->get_file_by_id($eventdata['objectid']);
        
        if (!$file) {
            return;
        }
        
        // Verificar si el archivo está en la carpeta "entrenaí"
        $filepath = $file->get_filepath();
        $filename = $file->get_filename();
        $contenthash = $file->get_contenthash();
        
        // Esto asume que la carpeta tiene un nombre específico
        // En una implementación real, deberías verificar contra un valor almacenado en la configuración
        if (strpos($filepath, '/entrenaí/') === false) {
            return;
        }
        
        // Obtener URL del archivo
        $fileurl = moodle_url::make_pluginfile_url(
            $file->get_contextid(),
            $file->get_component(),
            $file->get_filearea(),
            $file->get_itemid(),
            $file->get_filepath(),
            $file->get_filename()
        );
        
        // Configuración del API backend
        $api_url = get_config('local_entrena_ai', 'api_url');
        if (empty($api_url)) {
            $api_url = 'http://localhost:8000'; // Default para el POC
        }
        
        // Enviar notificación al backend
        $curl = new \curl();
        $curl->setHeader(['Content-Type: application/json']);
        
        $payload = json_encode([
            'course_id' => $courseid,
            'files' => [
                [
                    'filename' => $filename,
                    'url' => $fileurl->out(false),
                    'timestamp' => time(),
                    'file_id' => $file->get_id()
                ]
            ]
        ]);
        
        // Llamada asíncrona para no bloquear la interfaz de usuario
        $curl->post($api_url . '/moodle/incoming-files', $payload);
    }
}
```

### 6. Registrar los Eventos (db/events.php)

```php
<?php
defined('MOODLE_INTERNAL') || die();

$observers = [
    [
        'eventname' => '\core\event\course_module_created',
        'callback' => '\local_entrena_ai\observer::file_uploaded',
    ],
    [
        'eventname' => '\core\event\course_module_updated',
        'callback' => '\local_entrena_ai\observer::file_uploaded',
    ],
];
```

### 7. Configuración del Plugin (settings.php)

```php
<?php
defined('MOODLE_INTERNAL') || die();

if ($hassiteconfig) {
    $settings = new admin_settingpage('local_entrena_ai', get_string('pluginname', 'local_entrena_ai'));
    $ADMIN->add('localplugins', $settings);
    
    $settings->add(new admin_setting_configtext(
        'local_entrena_ai/api_url',
        get_string('api_url', 'local_entrena_ai'),
        get_string('api_url_desc', 'local_entrena_ai'),
        'http://localhost:8000',
        PARAM_URL
    ));
}
```

## Instalación

1. Coloca el código en la carpeta `moodle/local/entrena_ai/`.
2. Navega a la página de notificaciones del administrador para instalar el plugin.
3. Configura la URL de la API en la configuración del plugin.

## Consideraciones

- Este es un plugin simplificado para un POC
- En producción, necesitarías más validaciones y manejo de errores
- Deberías considerar la seguridad y autenticación entre Moodle y tu backend

## Alternativa: Usar Webhooks

Si no quieres desarrollar un plugin completo, puedes utilizar un plugin de webhooks existente como [local_webhooks](https://moodle.org/plugins/local_webhooks) o [tool_trigger](https://moodle.org/plugins/tool_trigger) para enviar notificaciones cuando se suben archivos. 