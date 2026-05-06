# Documento de Requisitos: Notion-Slack Ops Agent

## Introducción

El Notion-Slack Ops Agent es un agente de IA especializado que permite al equipo de BizOps de la organización consultar información técnica y operacional directamente desde Slack. El agente integra Notion (donde se almacena la documentación técnica de AWS/GCP) con Slack (donde trabaja el equipo), proporcionando búsqueda inteligente de información sobre aprovisionamiento, facturación, cuentas, soporte técnico, procesos operacionales y documentación de servicios cloud. El agente sigue la arquitectura establecida por los agentes AWS y GCP existentes, reutilizando módulos compartidos de Notion y Slack sin requerir modificaciones en la infraestructura existente.

## Glosario

- **Agent (Agente ADK)**: Componente de IA que interpreta consultas en lenguaje natural y ejecuta herramientas para responder preguntas.
- **Notion**: Plataforma de gestión de documentos donde se almacena la documentación técnica y operacional.
- **Slack**: Plataforma de comunicación donde el equipo de BizOps interactúa con el agente.
- **Whitelist (Lista Blanca)**: Archivo JSON que almacena los IDs de usuarios de Slack autorizados a usar el agente.
- **NotionIndexer**: Módulo compartido que indexa documentos de Notion en un archivo JSON local para búsqueda rápida.
- **Socket Mode**: Protocolo de Slack que permite que el bot reciba eventos sin exponer un servidor HTTP público.
- **Reindexación**: Proceso de actualizar el índice local con los cambios más recientes de Notion.
- **Gemini 2.0 Flash**: Modelo de lenguaje de IA utilizado por el agente para interpretar consultas y generar respuestas.
- **Admin**: Usuario de Slack con permisos para gestionar la whitelist y aprobar/rechazar solicitudes de acceso.
- **Índice Ops**: Archivo JSON (`.data/ops_index.json`) que contiene todos los documentos de Notion indexados para búsqueda.

## Requisitos

### Requisito 1: Búsqueda de Información Técnica y Operacional

**Historia de Usuario**: Como miembro del equipo de BizOps, quiero buscar información sobre aprovisionamiento de AWS/GCP, facturación, cuentas, soporte técnico y procesos operacionales directamente desde Slack, para poder acceder rápidamente a la información que necesito sin abandonar mi flujo de trabajo.

#### Criterios de Aceptación

1. CUANDO un usuario autorizado envía un mensaje directo al bot con una consulta técnica/operacional, ENTONCES el agente SHALL buscar en el índice de Notion (páginas Y bases de datos) y devolver resultados relevantes en Slack.
2. CUANDO la búsqueda encuentra documentos relevantes, ENTONCES el agente SHALL mostrar hasta 5 resultados con título, tipo de documento y contenido resumido (máximo 2000 caracteres por documento).
3. CUANDO la búsqueda encuentra filas de bases de datos, ENTONCES el agente SHALL incluir TODAS las columnas indexadas, incluyendo "Notas Comercial" y "Documentación Pendiente" cuando estén presentes.
4. CUANDO la búsqueda no encuentra resultados, ENTONCES el agente SHALL informar al usuario que no encontró información relevante y sugerir reindexar la documentación.
5. CUANDO un documento es muy grande (más de 4000 caracteres), ENTONCES el agente SHALL filtrar las líneas más relevantes según los términos de búsqueda antes de mostrar el contenido.
6. CUANDO el usuario realiza una consulta, ENTONCES el agente SHALL responder en español con un lenguaje claro y conciso, sintetizando la información sin copiar texto literal de los documentos.

### Requisito 2: Reindexación de Documentación Técnica y Bases de Datos

**Historia de Usuario**: Como administrador del agente, quiero poder reindexar la documentación técnica y bases de datos desde Notion, para asegurar que el agente siempre tiene acceso a la información más reciente, incluyendo columnas específicas como "Notas Comercial" y "Documentación Pendiente".

#### Criterios de Aceptación

1. CUANDO un usuario autorizado solicita reindexar la documentación (mediante comando o solicitud explícita), ENTONCES el agente SHALL conectarse a Notion y descargar todos los documentos accesibles (páginas y bases de datos).
2. CUANDO la reindexación procesa bases de datos, ENTONCES el agente SHALL extraer TODAS las columnas de cada fila, incluyendo "Notas Comercial", "Documentación Pendiente", "Cliente", "Status", y cualquier otra columna presente.
3. CUANDO la reindexación se completa exitosamente, ENTONCES el agente SHALL guardar el índice actualizado en `.data/ops_index.json` y confirmar el número de documentos indexados.
4. CUANDO ocurre un error durante la reindexación (token inválido, conexión fallida, etc.), ENTONCES el agente SHALL capturar la excepción y devolver un mensaje de error descriptivo.
5. CUANDO el índice se regenera, ENTONCES todos los documentos anteriores SHALL ser reemplazados completamente (no es una actualización incremental).
6. CUANDO la reindexación finaliza, ENTONCES el índice SHALL incluir metadatos como timestamp de indexación, número total de documentos, y para cada documento: ID de Notion, tipo, título, contenido extraído (con todas las columnas), URL y fecha de última edición.

### Requisito 3: Control de Acceso por Whitelist

**Historia de Usuario**: Como administrador de seguridad, quiero controlar quién puede acceder al agente ops mediante una lista blanca, para asegurar que solo miembros autorizados del equipo de BizOps acceden a información técnica sensible.

#### Criterios de Aceptación

1. CUANDO un usuario no autorizado intenta consultar el agente, ENTONCES el bot SHALL mostrar un mensaje de acceso denegado y un botón para solicitar acceso.
2. CUANDO un usuario no autorizado hace clic en "Solicitar acceso", ENTONCES el bot SHALL notificar a todos los administradores con botones para aprobar o rechazar la solicitud.
3. CUANDO un administrador aprueba una solicitud de acceso, ENTONCES el usuario SHALL ser añadido a la whitelist y notificado de que ya puede usar el agente.
4. CUANDO un administrador rechaza una solicitud de acceso, ENTONCES el usuario SHALL ser notificado del rechazo.
5. CUANDO un usuario está en la whitelist, ENTONCES podrá consultar el agente sin restricciones.
6. CUANDO un usuario es administrador (en la variable de entorno `SLACK_ADMIN_USERS`), ENTONCES podrá consultar el agente sin necesidad de estar en la whitelist.

### Requisito 4: Comandos de Administración

**Historia de Usuario**: Como administrador del agente, quiero gestionar la whitelist mediante comandos de Slack, para poder añadir, eliminar y listar usuarios autorizados de forma rápida.

#### Criterios de Aceptación

1. CUANDO un administrador envía el comando `admin lista`, ENTONCES el bot SHALL mostrar todos los usuarios actualmente en la whitelist.
2. CUANDO un administrador envía el comando `admin añadir @usuario`, ENTONCES el bot SHALL añadir el usuario a la whitelist y confirmar la acción.
3. CUANDO un administrador envía el comando `admin quitar @usuario`, ENTONCES el bot SHALL eliminar el usuario de la whitelist y confirmar la acción.
4. CUANDO un usuario no administrador intenta ejecutar comandos admin, ENTONCES el bot SHALL rechazar el comando y mostrar un mensaje de permiso denegado.
5. CUANDO se ejecuta un comando admin, ENTONCES la whitelist SHALL persistirse en `.data/whitelist_ops.json` para que los cambios sean permanentes.

### Requisito 5: Integración con Slack Socket Mode

**Historia de Usuario**: Como operador de infraestructura, quiero que el bot funcione sin exponer un servidor HTTP público, para simplificar la configuración de red y seguridad.

#### Criterios de Aceptación

1. CUANDO el bot se inicia, ENTONCES SHALL conectarse a Slack mediante Socket Mode usando el token de aplicación (`SLACK_APP_TOKEN_OPS`).
2. CUANDO el bot recibe un mensaje directo de un usuario, ENTONCES SHALL procesarlo y responder en el mismo canal.
3. CUANDO el bot recibe una acción de botón (solicitar acceso, aprobar, rechazar), ENTONCES SHALL procesarla correctamente.
4. CUANDO ocurre un error de conexión, ENTONCES el bot SHALL registrar el error y intentar reconectarse automáticamente.

### Requisito 6: Configuración y Variables de Entorno

**Historia de Usuario**: Como administrador de sistemas, quiero configurar el agente mediante variables de entorno, para poder desplegar múltiples instancias con diferentes configuraciones sin modificar código.

#### Criterios de Aceptación

1. CUANDO el bot se inicia, ENTONCES SHALL leer las siguientes variables de entorno:
   - `NOTION_TOKEN_OPS`: Token de integración de Notion para el workspace de BizOps
   - `SLACK_BOT_TOKEN_OPS`: Token del bot de Slack
   - `SLACK_APP_TOKEN_OPS`: Token de aplicación de Slack para Socket Mode
   - `SLACK_ADMIN_USERS`: Lista de IDs de usuarios de Slack que son administradores (separados por comas)
   - `GOOGLE_API_KEY`: Clave de API de Google para acceder a Gemini
2. CUANDO falta una variable de entorno requerida, ENTONCES el bot SHALL fallar con un mensaje de error claro indicando qué variable falta.
3. CUANDO todas las variables están configuradas correctamente, ENTONCES el bot SHALL iniciar sin errores.

### Requisito 7: Modelo de IA y Respuestas

**Historia de Usuario**: Como usuario del agente, quiero recibir respuestas precisas y bien formateadas en Slack, para poder entender fácilmente la información que busco.

#### Criterios de Aceptación

1. CUANDO el agente genera una respuesta, ENTONCES SHALL utilizar el modelo Gemini 2.0 Flash para interpretar la consulta y generar la respuesta.
2. CUANDO el agente responde, ENTONCES SHALL convertir el formato Markdown a formato Slack (negrita, cursiva, encabezados, código).
3. CUANDO el agente responde, ENTONCES SHALL responder siempre en español.
4. CUANDO el agente responde, ENTONCES SHALL sintetizar la información con sus propias palabras, sin copiar texto literal de los documentos de Notion.
5. CUANDO el agente responde, ENTONCES NO SHALL incluir enlaces, fuentes ni referencias de Notion en la respuesta (excepto URLs de dashboards operacionales si son explícitamente mencionadas en los documentos).
6. CUANDO el agente no puede generar una respuesta válida, ENTONCES SHALL informar al usuario que no pudo procesar la pregunta y sugerir reformularla.

### Requisito 8: Manejo de Errores y Recuperación

**Historia de Usuario**: Como usuario del agente, quiero que el bot maneje errores de forma elegante, para que pueda reintentar o contactar con un administrador si algo falla.

#### Criterios de Aceptación

1. CUANDO el índice está vacío o no existe, ENTONCES el agente SHALL informar al usuario y sugerir ejecutar la reindexación.
2. CUANDO el token de Notion es inválido o expirado, ENTONCES la reindexación SHALL fallar con un mensaje de error descriptivo.
3. CUANDO la ejecución del agente supera el timeout (120 segundos), ENTONCES el bot SHALL informar al usuario que hubo un error y sugerir reintentar.
4. CUANDO ocurre un error inesperado, ENTONCES el bot SHALL registrar el error en los logs y mostrar un mensaje genérico al usuario.
5. CUANDO un usuario intenta consultar sin acceso, ENTONCES el bot SHALL mostrar el flujo de solicitud de acceso en lugar de un error genérico.

### Requisito 9: Reutilización de Módulos Compartidos

**Historia de Usuario**: Como arquitecto de software, quiero que el agente ops reutilice los módulos compartidos existentes, para mantener la consistencia arquitectónica y evitar duplicación de código.

#### Criterios de Aceptación

1. CUANDO el agente se inicializa, ENTONCES SHALL importar `NotionIndexer` desde `notion_shared.indexer` sin modificar ese módulo.
2. CUANDO el agente se inicializa, ENTONCES SHALL importar la función `run_bot` desde `slack_bot.py` sin modificar ese módulo.
3. CUANDO el agente se inicializa, ENTONCES SHALL seguir el mismo patrón arquitectónico que `aws_agent` y `gcp_agent` (estructura de directorios, nombres de funciones, herramientas).
4. CUANDO el agente se inicializa, ENTONCES NO SHALL requerir cambios en `notion_shared`, `slack_bot.py` ni en ningún otro módulo compartido.

### Requisito 10: Estructura de Directorios y Archivos

**Historia de Usuario**: Como desarrollador, quiero que el agente ops siga la estructura de directorios establecida, para poder encontrar y mantener el código fácilmente.

#### Criterios de Aceptación

1. CUANDO el agente se despliega, ENTONCES SHALL tener la siguiente estructura:
   - `agents/ops_agent/__init__.py`: Módulo de inicialización que exporta el agente
   - `agents/ops_agent/agent.py`: Definición del agente ADK con herramientas
   - `run_ops_bot.py`: Script de arranque del bot de Slack
2. CUANDO el agente se ejecuta, ENTONCES SHALL crear/actualizar los siguientes archivos:
   - `.data/ops_index.json`: Índice de documentos de Notion
   - `.data/whitelist_ops.json`: Lista blanca de usuarios autorizados
3. CUANDO el repositorio se sincroniza, ENTONCES `.data/` SHALL estar excluido del control de versiones (ya está en `.gitignore`).

### Requisito 11: Documentación y Especificación del Agente

**Historia de Usuario**: Como usuario del agente, quiero entender qué puede hacer el agente y cómo usarlo, para poder aprovechar al máximo sus capacidades.

#### Criterios de Aceptación

1. CUANDO el agente se inicializa, ENTONCES SHALL tener una descripción clara: "Agente experto en información técnica y operacional de AWS/GCP para el equipo de BizOps."
2. CUANDO el agente responde, ENTONCES SHALL seguir instrucciones especializadas para consultas técnicas y operacionales (aprovisionamiento, facturación, cuentas, soporte, procesos operacionales, documentación de servicios cloud).
3. CUANDO el agente responde, ENTONCES SHALL estar especializado en el dominio técnico/operacional de BizOps, diferenciándose de los agentes AWS y GCP que están más enfocados en consultas específicas de cada proveedor.

### Requisito 12: Rendimiento y Escalabilidad

**Historia de Usuario**: Como operador del sistema, quiero que el agente responda rápidamente a las consultas, para que el equipo de BizOps pueda trabajar sin interrupciones.

#### Criterios de Aceptación

1. CUANDO un usuario realiza una consulta, ENTONCES el agente SHALL responder en menos de 120 segundos (timeout configurado).
2. CUANDO el agente busca en el índice, ENTONCES SHALL limitar los resultados a máximo 5 documentos para mantener el contexto del LLM manejable.
3. CUANDO el agente procesa un documento grande, ENTONCES SHALL truncar el contenido a máximo 2000 caracteres por documento.
4. CUANDO el agente procesa un documento muy grande (>4000 caracteres), ENTONCES SHALL filtrar las líneas más relevantes según los términos de búsqueda antes de enviarlas al LLM.
5. CUANDO el índice se carga, ENTONCES SHALL hacerlo desde el archivo JSON local (`.data/ops_index.json`) sin conectarse a Notion en cada búsqueda.

### Requisito 13: Seguridad de Datos Sensibles

**Historia de Usuario**: Como responsable de seguridad, quiero que la información técnica sensible esté protegida, para cumplir con políticas de seguridad y privacidad.

#### Criterios de Aceptación

1. CUANDO el agente se configura, ENTONCES los tokens de Notion y Slack SHALL almacenarse en `.env` y nunca en código fuente.
2. CUANDO el índice se genera, ENTONCES SHALL almacenarse en `.data/ops_index.json` que está excluido del repositorio.
3. CUANDO la whitelist se actualiza, ENTONCES SHALL almacenarse en `.data/whitelist_ops.json` que está excluido del repositorio.
4. CUANDO un usuario no autorizado intenta acceder, ENTONCES el bot SHALL rechazar la solicitud sin revelar información sobre qué documentos existen.
5. CUANDO un administrador gestiona la whitelist, ENTONCES solo los usuarios en `SLACK_ADMIN_USERS` SHALL poder ejecutar comandos admin.
