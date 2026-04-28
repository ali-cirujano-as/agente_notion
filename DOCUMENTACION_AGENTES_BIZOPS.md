# Documentación Completa: Agentes BizOps (AWS Info Bot + Google Info Bot)

## 1. Visión General

### ¿Qué es esto?

Son dos asistentes de inteligencia artificial integrados en Slack que permiten al equipo de BizOps de Altostratus consultar información técnica y operacional sin salir de Slack. Los asistentes leen documentación almacenada en Notion, la procesan y responden preguntas en lenguaje natural.

### ¿Por qué existen?

El equipo de BizOps gestiona documentación extensa sobre procesos de AWS y GCP/GWS en Notion: provisiones, facturación, licencias, soporte, cuentas, etc. Buscar información manualmente en Notion es lento. Estos bots permiten preguntar directamente en Slack y obtener respuestas inmediatas basadas en esa documentación.

### ¿Quién los usa?

El equipo de BizOps de Altostratus. El acceso está controlado por una lista blanca (whitelist) por bot. Los administradores pueden gestionar quién tiene acceso.

### Los dos bots

| Bot | Nombre en Slack | Qué cubre | Token Notion |
|---|---|---|---|
| AWS Info Bot | aws_info_bot | Documentación y datos de AWS: provisiones, MPAs, facturación, soporte, cuentas | NOTION_TOKEN_AWS (integración "ADK AWS") |
| Google Info Bot | google_info_bot | Documentación y datos de GCP y Google Workspace: provisiones, licencias, renovaciones, facturación, soporte | NOTION_TOKEN_GCP (integración "ADK GOO") |

### Separación de datos

Ambos bots acceden a una base de datos compartida llamada "Seguimiento Comercial" que contiene provisiones bloqueadas de AWS, GCP y GWS mezcladas. Para evitar que un bot muestre datos del otro, cada bot filtra automáticamente por la columna "Cloud" de la base de datos:

- AWS Info Bot → solo indexa filas donde Cloud = "AWS"
- Google Info Bot → solo indexa filas donde Cloud = "GCP" o Cloud = "GWS"

Si una base de datos no tiene columna "Cloud" (como Licencias Caducadas GWS), se incluye en el bot que tenga acceso a ella.

## 2. Arquitectura Técnica

### Diagrama de flujo

Usuario escribe en Slack (DM al bot) → slack_bot.py recibe el mensaje (Socket Mode) → Verifica si el usuario está en la whitelist → Si no está, muestra botón "Solicitar acceso" → Si está, envía "Consultando la documentación..." → Ejecuta el agente ADK (Gemini 2.5 Pro) → El agente llama a search_xxx_docs(query) → search_xxx_docs busca en el índice JSON local → Devuelve resultados al agente → El agente genera una respuesta en español → slack_bot.py convierte Markdown a formato Slack → Envía la respuesta al usuario en Slack

### Componentes principales

**1. slack_bot.py (módulo compartido)** - Es el corazón del sistema. Gestiona: conexión a Slack via Socket Mode (WebSocket, sin servidor HTTP), control de acceso (whitelist + admins), comandos de administración (admin lista, admin añadir, admin quitar), flujo de solicitud de acceso (botones interactivos), ejecución del agente ADK, conversión de Markdown a formato Slack, sesiones por usuario (memoria de conversación). Ambos bots usan este mismo módulo.

**2. agents/aws_agent/agent.py** - Define el agente AWS: Modelo Gemini 2.5 Pro, herramientas search_aws_docs() y reindex_aws_docs(), instrucciones para responder con datos reales, filtrar por Cloud=AWS, pedir filtro si hay más de 30 resultados. Indexer con cloud_filter=["aws"].

**3. agents/gcp_agent/agent.py** - Define el agente GCP: Modelo Gemini 2.5 Pro, herramientas search_gcp_docs() y reindex_gcp_docs(), instrucciones para responder con datos reales, filtrar por Cloud=GCP/GWS, pedir filtro si hay más de 30 resultados. Indexer con cloud_filter=["gcp", "gws"].

**4. notion_shared/indexer.py (módulo compartido)** - Gestiona la indexación y búsqueda: conecta a Notion API para descargar páginas y bases de datos, extrae texto de bloques, filas de BD, propiedades, filtra filas por columna "Cloud" si se configura cloud_filter, guarda todo en un archivo JSON local, búsqueda por keywords con sinónimos, normalización de tildes y bonus para bases de datos.

**5. notion_shared/notion_client.py** - Cliente HTTP para la API de Notion: buscar páginas y bases de datos (search_all), obtener bloques hijos de una página (get_block_children), consultar filas de una base de datos (query_database), obtener información de una base de datos (get_database).

**6. notion_shared/text_extractor.py** - Extrae texto plano de los objetos de Notion: bloques (párrafos, headings, listas, código, tablas), títulos de páginas, propiedades de bases de datos (texto, números, fechas, selects, etc.), filas de bases de datos (convierte todas las columnas a texto).

**7. cron_reindex.py** - Script de reindexación automática: se ejecuta via cron a las 6:00 y 14:00 cada día, reindexa AWS (con cloud_filter=["aws"]) y GCP (con cloud_filter=["gcp", "gws"]), guarda logs en .data/cron.log.

**8. run_aws_bot.py y run_gcp_bot.py** - Scripts de arranque de cada bot. Cargan variables de entorno, importan el agente y llaman a run_bot().

### Tecnologías utilizadas

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.12 | Lenguaje principal |
| google-adk | 1.26.0 | Framework de agentes de IA (Agent, Runner, Sessions) |
| google-genai | 1.66.0 | SDK de Gemini (modelo de IA) |
| Gemini 2.5 Pro | - | Modelo de lenguaje para interpretar consultas y generar respuestas |
| slack-bolt | 1.27.0 | Framework de Slack (App, Socket Mode) |
| slack-sdk | 3.40.1 | SDK de Slack (WebClient) |
| requests | 2.32.5 | Cliente HTTP para Notion API |
| python-dotenv | 1.2.2 | Carga de variables de entorno desde .env |

## 3. Cómo Funciona la Búsqueda

### Proceso de indexación

1. El indexer se conecta a Notion API con el token correspondiente
2. Busca todas las páginas accesibles (ignora filas de BD sueltas)
3. Para cada página, extrae el contenido recursivamente (incluyendo BDs embebidas)
4. Busca todas las bases de datos accesibles
5. Para cada BD, consulta todas las filas y extrae todas las columnas
6. Si hay cloud_filter, descarta filas cuya columna "Cloud" no coincida
7. Guarda todo en un archivo JSON local

### Proceso de búsqueda

1. El usuario hace una pregunta
2. El agente llama a search_xxx_docs(query)
3. La función carga el índice JSON si no está en memoria
4. Normaliza la query (elimina tildes: "facturación" → "facturacion")
5. Extrae keywords de la query (palabras de más de 2 caracteres)
6. Expande keywords con sinónimos (ej: "caducidad" → también busca "caducadas", "renewal", "renovación")
7. Para cada documento del índice, calcula un score: +2 por cada keyword original encontrada, +1 por cada sinónimo encontrado, +5 bonus si es una base de datos (datos reales), +3 por cada keyword que aparece en el título
8. Ordena por score descendente
9. Devuelve los top 5-10 resultados

### Sinónimos configurados

| Palabra | Sinónimos |
|---|---|
| caducidad | caducadas, caducado, renewal, renovación, expiración, vencimiento, vencidas |
| renovaciones | renewal, renovación, renovar, avisos |
| bloqueadas | bloqueados, bloqueada, bloqueado, bloqueo |
| facturación | factura, facturas, billing, consumo, consumos |
| soporte | support, incidencia, incidencias, ticket, tickets |
| licencias | licencia, suscripciones, suscripción |
| billing | facturación, factura, consumo |

### Manejo de resultados grandes

Cuando una base de datos tiene muchas filas (ej: 103 provisiones bloqueadas): la función search_xxx_docs detecta que hay más de 20 filas de BD, filtra las filas por keywords de la consulta, resume cada fila extrayendo solo columnas clave (Cliente, Key, Status, Notas Comercial, Documentación Pendiente, Comercial Responsable, Assignee, Urgencia, Cloud, Código de Oferta, Fecha Fin Real, Issue Type), devuelve el campo total_rows para que el agente sepa cuántos hay en total, el agente si ve total_rows mayor que 30 pide al usuario que filtre antes de mostrar datos.

## 4. Guía de Uso para Usuarios

### Cómo empezar

1. Abre Slack
2. En la barra de búsqueda, busca "aws_info_bot" (para AWS) o "google_info_bot" (para GCP/GWS)
3. Haz clic en el bot para abrir un mensaje directo
4. Escribe tu pregunta

### Tipos de consultas que puedes hacer

Consultas sobre datos (listados, clientes, estados): "¿Qué provisiones están bloqueadas?", "¿Qué licencias están caducadas?", "¿Qué renovaciones se aproximan?", "Dame las provisiones de Pablo Cristobal", "¿Qué clientes tienen documentación pendiente?"

Consultas sobre procesos (cómo hacer algo): "¿Cómo creo una MPA dedicada?", "¿Cómo muevo un proyecto entre cuentas de facturación?", "¿Cómo funciona el modelo SPAM vs ECAM?", "¿Cómo abro un ticket de soporte?", "¿Qué documentación necesito para provisionar licencias de educación?"

Consultas sobre conceptos: "¿Qué diferencia hay entre MPA y Cuenta Asociada?", "¿Qué es Enterprise Starter (EMA)?", "¿Qué significan las siglas SPAM y ECAM?"

### Cuando hay muchos resultados

Si preguntas algo genérico como "provisiones bloqueadas" y hay más de 30 registros, el bot te dirá: "Hay 103 registros de provisiones bloqueadas. ¿Quieres filtrar por comercial responsable, cliente, estado o urgencia?"

Responde con el filtro: "las de Pablo Cristobal", "las urgentes", "las del cliente PRISA", "las que tienen documentación pendiente".

### Reindexar documentación

Si acabas de actualizar algo en Notion y quieres que el bot lo tenga, escríbele: "Reindexa la documentación". El bot se conectará a Notion, descargará todo y actualizará su índice.

### Memoria de conversación

El bot recuerda la conversación contigo. Si primero preguntas "provisiones bloqueadas" y luego dices "las de Pablo", el bot entiende que quieres las provisiones bloqueadas de Pablo. La memoria se pierde si se reinicia el bot.

## 5. Guía de Administración

### Administradores

Los administradores se definen en la variable de entorno SLACK_ADMIN_USERS en el archivo .env. Los administradores actuales son: U05R4UAD1RT, U054U2B51CP, U07JVBWAY59.

Los administradores pueden: usar los bots sin estar en la whitelist, gestionar la whitelist (añadir/quitar usuarios), aprobar/rechazar solicitudes de acceso.

Para añadir un nuevo administrador, edita .env y añade su ID de Slack separado por coma. Luego reinicia los bots.

### Cómo obtener el ID de Slack de un usuario

En Slack, haz clic en el perfil del usuario, haz clic en los tres puntos (···), selecciona "Copy member ID".

### Comandos de administración

Escribe estos comandos directamente en el DM con el bot:

- admin lista → Muestra todos los usuarios con acceso
- admin añadir @usuario → Añade un usuario a la whitelist
- admin quitar @usuario → Quita un usuario de la whitelist

Puedes añadir varios usuarios a la vez: admin añadir @usuario1 @usuario2 @usuario3

### Flujo de solicitud de acceso

1. Un usuario sin acceso escribe al bot
2. El bot muestra un botón "Solicitar acceso"
3. El usuario hace clic
4. Todos los administradores reciben un DM con botones "Aprobar" y "Rechazar"
5. Un admin hace clic en aprobar o rechazar
6. El usuario recibe notificación del resultado

### Whitelists

Cada bot tiene su propia whitelist independiente: AWS usa .data/whitelist_aws.json, GCP usa .data/whitelist_gcp.json. Si añades un usuario al bot de AWS, no tiene acceso automáticamente al de GCP. Hay que añadirlo en ambos si es necesario.

## 6. Configuración del Entorno

### Requisitos previos

macOS (probado en MacBook Pro), Python 3.12 (instalado via Homebrew), acceso a internet (para Notion API y Gemini API).

### Archivo .env

Ubicación: adk-python/.env

Variables necesarias:
- GOOGLE_API_KEY → API key de Google Gemini (IA)
- NOTION_TOKEN_AWS → Token de integración de Notion para AWS (integración "ADK AWS")
- NOTION_TOKEN_GCP → Token de integración de Notion para GCP/GWS (integración "ADK GOO")
- SLACK_ADMIN_USERS → IDs de administradores separados por comas
- SLACK_BOT_TOKEN_AWS → Token del bot de Slack para AWS (empieza por xoxb-)
- SLACK_APP_TOKEN_AWS → Token de app de Slack para AWS Socket Mode (empieza por xapp-)
- SLACK_BOT_TOKEN_GCP → Token del bot de Slack para GCP (empieza por xoxb-)
- SLACK_APP_TOKEN_GCP → Token de app de Slack para GCP Socket Mode (empieza por xapp-)

### Cron de reindexación

El cron está configurado para ejecutarse a las 6:00 y 14:00 cada día. Para ver el cron actual: crontab -l. Para editar el cron: crontab -e.

La línea del cron es: 0 6,14 * * * cd "/Users/alicirujano/Documents/claudecode/notion_AS/adk-python" && .venv/bin/python cron_reindex.py >> .data/cron.log 2>&1

### Entorno virtual Python

El proyecto usa un entorno virtual en .venv/. Para instalar dependencias si se pierde el venv: python3 -m venv .venv seguido de .venv/bin/pip install -r requirements.txt

## 7. Integraciones de Notion

### Integraciones creadas

| Integración | Token en .env | Qué accede |
|---|---|---|
| ADK AWS | NOTION_TOKEN_AWS | Páginas y BDs de documentación AWS |
| ADK GOO | NOTION_TOKEN_GCP | Páginas y BDs de documentación GCP/GWS |

### Bases de datos compartidas

Con ADK AWS: Listado de Provisiones Bloqueadas (fuente: Seguimiento Comercial, filtrado por Cloud=AWS).

Con ADK GOO: Listado de Provisiones Bloqueadas (fuente: Seguimiento Comercial, filtrado por Cloud=GCP/GWS), Listado de Avisos de Renovación GWS, Licencias Caducadas GWS.

### Cómo compartir una nueva base de datos con una integración

1. Abre la base de datos en Notion
2. Haz clic en los tres puntos (···) en la esquina superior derecha
3. Selecciona "Connections" o "Conexiones"
4. Busca la integración (ADK AWS o ADK GOO)
5. Haz clic para conectarla
6. Reindexa desde terminal: .venv/bin/python cron_reindex.py

### Problema con linked databases (vistas vinculadas)

La API de Notion NO puede acceder directamente a linked databases (vistas). Si una página contiene una vista vinculada a una BD de otro espacio, necesitas compartir la BASE DE DATOS FUENTE (la original) con la integración, no la vista. Para identificar si una BD es una vista: busca una flecha (↗) al inicio del título de la tabla en Notion. Si la ves, es una vista. Haz clic en la flecha para ir a la fuente y comparte ESA con la integración.

### Problema con BDs sincronizadas

Algunas bases de datos en Notion están sincronizadas desde fuentes externas (Jira, Google Sheets, etc.). La API de Notion no puede leer sus datos. El error es: "Database does not contain any data sources accessible by this API bot." Solución: compartir la base de datos fuente original (no la sincronizada) con la integración.

## 8. Cómo se Crearon las Apps de Slack

### Proceso para crear una app de Slack (paso a paso)

**Paso 1 - Crear la app:** Ve a https://api.slack.com/apps, haz clic en "Create New App", selecciona "From scratch" (o "From an app manifest" si duplicas una existente), pon el nombre ("AWS Info Bot" o "GCP Info Bot"), selecciona el workspace Altostratus.

**Paso 2 - Configurar Socket Mode:** En el menú lateral, ve a "Socket Mode", activa "Enable Socket Mode".

**Paso 3 - Crear App-Level Token:** Ve a "Basic Information", baja a "App-Level Tokens", haz clic en "Generate Token and Scopes", nombre: "socket-mode", scope: connections:write, genera el token. Este es SLACK_APP_TOKEN_xxx (empieza por xapp-).

**Paso 4 - Configurar Event Subscriptions:** Ve a "Event Subscriptions", activa "Enable Events", en "Subscribe to bot events" añade: message.im.

**Paso 5 - Configurar OAuth Scopes:** Ve a "OAuth & Permissions", en "Bot Token Scopes" añade: chat:write, im:history, im:read, im:write.

**Paso 6 - Configurar Interactivity:** Ve a "Interactivity & Shortcuts", activa "Interactivity" (necesario para los botones de aprobar/rechazar acceso).

**Paso 7 - Configurar App Home:** Ve a "App Home", en "Show Tabs" activa "Messages Tab", marca "Allow users to send Slash commands and messages from the messages tab".

**Paso 8 - Instalar la app:** Ve a "Install App", haz clic en "Install to Workspace", autoriza los permisos, copia el "Bot User OAuth Token". Este es SLACK_BOT_TOKEN_xxx (empieza por xoxb-).

**Duplicar una app existente (método rápido):** Si ya tienes una app funcionando (ej: AWS) y quieres crear otra (ej: GCP): ve a la app existente → "App Manifest", copia el YAML, crea nueva app → "From an app manifest", pega el YAML y cambia el nombre, crea el App-Level Token manualmente (paso 3), instala la app (paso 8).

## 9. Arranque de los Bots

### Cómo arrancar

Abrir dos terminales separadas.

Terminal 1 para AWS: cd ~/Documents/claudecode/notion_AS/adk-python seguido de .venv/bin/python run_aws_bot.py

Terminal 2 para GCP: cd ~/Documents/claudecode/notion_AS/adk-python seguido de .venv/bin/python run_gcp_bot.py

Las terminales deben quedarse abiertas. Si se cierran, los bots dejan de responder.

### Reindexación manual

Desde terminal: cd ~/Documents/claudecode/notion_AS/adk-python seguido de .venv/bin/python cron_reindex.py

Desde Slack: escríbele al bot "Reindexa la documentación".

## 10. Estructura del Proyecto

adk-python/.env → Variables de entorno (tokens, API keys). adk-python/.data/ → Datos generados (excluido de git): aws_index.json (índice AWS), gcp_index.json (índice GCP/GWS), whitelist_aws.json (lista blanca AWS), whitelist_gcp.json (lista blanca GCP), cron.log (log de reindexaciones). agents/aws_agent/__init__.py y agent.py → Agente AWS. agents/gcp_agent/__init__.py y agent.py → Agente GCP. notion_shared/indexer.py → Indexador compartido. notion_shared/notion_client.py → Cliente Notion API. notion_shared/text_extractor.py → Extractor de texto. slack_bot.py → Bot de Slack compartido. run_aws_bot.py → Arranque bot AWS. run_gcp_bot.py → Arranque bot GCP. cron_reindex.py → Reindexación automática. index_notion.py → Reindexación manual. requirements.txt → Dependencias Python.

## 11. Solución de Problemas

### El bot no responde en Slack

Causa 1 - El bot no está corriendo: Verifica que la terminal donde se ejecuta el bot sigue abierta. Si se cerró, vuelve a arrancarlo.

Causa 2 - Token de Slack inválido: Si reinstalaste la app de Slack, el token xoxb- puede haber cambiado. Ve a https://api.slack.com/apps → tu app → OAuth & Permissions → copia el nuevo token. Actualiza .env con el nuevo token. Reinicia el bot.

Causa 3 - El usuario no tiene acceso: El bot mostrará un botón "Solicitar acceso" si el usuario no está en la whitelist. Un admin debe aprobar la solicitud.

Causa 4 - Socket Mode desactivado: Ve a https://api.slack.com/apps → tu app → Socket Mode → verifica que está activado.

### El bot dice "No encontré información relevante"

Causa 1 - Índice vacío o desactualizado: Reindexa escribiendo al bot "Reindexa la documentación" o desde terminal .venv/bin/python cron_reindex.py.

Causa 2 - La documentación no existe en Notion: Verifica que la información que buscas está en una página de Notion compartida con la integración.

Causa 3 - La búsqueda no encuentra la palabra: Prueba con sinónimos o términos más específicos. Ejemplo: en vez de "caducidad", prueba "licencias caducadas" o "renovaciones".

### El bot muestra datos de AWS en el chat de GCP (o viceversa)

Verifica que en agents/aws_agent/agent.py dice cloud_filter=["aws"]. Verifica que en agents/gcp_agent/agent.py dice cloud_filter=["gcp", "gws"]. Reindexa.

### Error "invalid_auth" al arrancar el bot

El token de Slack es inválido o expirado. Ve a https://api.slack.com/apps → tu app → OAuth & Permissions. Copia el token actualizado y ponlo en .env.

### Error "Token de Notion inválido" al reindexar

El token de Notion puede haber expirado o la integración fue revocada. Ve a https://www.notion.so/my-integrations. Verifica que la integración existe y copia el token actualizado. Ponlo en .env.

### El cron no se ejecuta

Verifica que el cron está configurado: crontab -l. Verifica que el Mac estaba encendido a la hora del cron (6:00 y 14:00). Verifica los logs: tail -50 adk-python/.data/cron.log. Si el Mac estaba dormido, el cron no se ejecuta.

### No puedo escribirle al bot en Slack

Ve a https://api.slack.com/apps → tu app → App Home. Verifica que "Messages Tab" está activado. Verifica que "Allow users to send Slash commands and messages from the messages tab" está marcado. Si acabas de cambiar esto, cierra y vuelve a abrir Slack.

### Una base de datos de Notion no se indexa

Si el error dice "linked database": es una vista vinculada, no una BD real. Necesitas compartir la BD fuente con la integración. Busca la flecha ↗ en el título de la tabla para ir a la fuente.

Si el error dice "does not contain any data sources": es una BD sincronizada desde otra fuente. Necesitas compartir la BD fuente original con la integración.

Si no aparece en el índice pero no da error: puede que el cloud_filter la esté descartando. Si la BD no tiene columna "Cloud", se incluye automáticamente. Si tiene columna "Cloud" pero los valores no coinciden con el filtro, se descarta.

## 12. Historial de Decisiones Técnicas

**¿Por qué Socket Mode y no HTTP Mode?** Socket Mode es más simple: no necesita servidor HTTP público, no necesita SSL, no necesita dominio. Ideal para desarrollo local y equipos pequeños.

**¿Por qué Gemini 2.5 Pro y no Flash?** Flash interpretaba mal las consultas: cuando el usuario pedía "provisiones bloqueadas", Flash explicaba qué son en vez de mostrar el listado. Pro entiende mejor la intención.

**¿Por qué un índice JSON local?** La API de Notion es lenta (2-5 segundos por búsqueda). Con el índice local, la búsqueda es instantánea. El trade-off es que los datos pueden estar desactualizados hasta la próxima reindexación (máximo 8 horas).

**¿Por qué cloud_filter?** La BD "Seguimiento Comercial" mezcla datos de AWS, GCP y GWS. Sin filtro, cada bot mostraría datos del otro.

**¿Por qué sinónimos?** La búsqueda original era por coincidencia exacta. "caducidad" no encontraba "caducadas" ni "renewal".

**¿Por qué normalización de tildes?** Los usuarios escriben sin tildes en Slack. Sin normalización, "facturacion" no encontraba "facturación".

**¿Por qué bonus para bases de datos?** Documentos grandes de proceso siempre puntuaban más alto que las BDs con datos reales. El bonus asegura que los datos reales aparezcan primero.

**¿Por qué sesiones persistentes?** Sin sesiones, cada mensaje era independiente. El agente no recordaba que "las de Pablo" se refería a "provisiones bloqueadas".

## 13. Mantenimiento

### Tareas periódicas

Verificar que los bots están corriendo: diario, escribirle algo al bot en Slack. Verificar logs de reindexación: semanal, tail -50 adk-python/.data/cron.log. Verificar que los tokens no han expirado: mensual, arrancar los bots y ver si dan error.

### Cómo añadir un nuevo administrador

Obtén el ID de Slack del usuario (perfil → ··· → Copy member ID). Edita .env y añade el ID a SLACK_ADMIN_USERS separado por coma. Reinicia ambos bots.

### Cómo añadir sinónimos de búsqueda

En notion_shared/indexer.py, busca el diccionario SYNONYMS y añade nuevas entradas. Reinicia los bots.

### Cómo añadir una nueva base de datos de Notion

En Notion, comparte la BD con la integración correspondiente. Si la BD tiene columna "Cloud", el filtro se aplica automáticamente. Reindexa.

### Cómo crear un tercer bot

Crea la app de Slack siguiendo la sección 8. Crea el directorio agents/nuevo_agent/ con __init__.py y agent.py copiando la estructura de aws_agent. Crea run_nuevo_bot.py copiando run_aws_bot.py. Añade los tokens al .env. Añade el agente al cron_reindex.py. Arranca el bot.

## 14. Checklist para Nuevo Mantenedor

Si Ali deja el proyecto, el nuevo mantenedor necesita:

- Acceso al Mac donde corren los bots (o migrar a la nube)
- Acceso al workspace de Slack de Altostratus como admin
- Acceso a las apps de Slack (https://api.slack.com/apps)
- Acceso a las integraciones de Notion (https://www.notion.so/my-integrations)
- Acceso a Google AI Studio para la API key de Gemini
- Copia del archivo .env con todos los tokens
- Entender esta documentación
- Saber arrancar los bots (run_aws_bot.py, run_gcp_bot.py)
- Saber reindexar (cron_reindex.py)
- Saber gestionar la whitelist (comandos admin en Slack)
- Saber compartir BDs de Notion con las integraciones
- Saber crear/modificar apps de Slack (sección 8)
