# Plan de Implementación: Notion-Slack Ops Agent

## Descripción General

El Notion-Slack Ops Agent es un agente ADK especializado que permite al equipo de BizOps consultar información técnica y operacional directamente desde Slack. El agente sigue la arquitectura establecida por los agentes AWS y GCP existentes, reutilizando módulos compartidos de Notion y Slack sin requerir modificaciones en la infraestructura existente.

## Tareas

- [ ] 1. Crear la estructura del módulo ops_agent
  - Crear el directorio `agents/ops_agent/`
  - Crear el archivo `agents/ops_agent/__init__.py` que exporte el agente
  - Crear el archivo `agents/ops_agent/agent.py` con la definición del agente ADK
  - _Requisitos: 10.1, 9.3_

- [ ] 2. Implementar la herramienta de búsqueda de documentos técnicos
  - Implementar la función `search_ops_docs(query: str) -> dict` en `agent.py`
  - Integrar con `NotionIndexer` para buscar en el índice local
  - Implementar filtrado de líneas relevantes para documentos grandes (>4000 caracteres)
  - Limitar resultados a máximo 5 documentos
  - Truncar contenido a máximo 2000 caracteres por documento
  - Devolver resultados con título, tipo, contenido y URL
  - Manejar caso de índice vacío con mensaje descriptivo
  - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 12.2, 12.3, 12.4_

- [ ]* 2.1 Escribir pruebas unitarias para search_ops_docs
  - Probar búsqueda exitosa con resultados
  - Probar búsqueda sin resultados
  - Probar truncado de contenido a 2000 caracteres
  - Probar filtrado de documentos grandes (>4000 caracteres)
  - Probar límite de 5 resultados
  - _Requisitos: 1.2, 1.4, 12.2, 12.3, 12.4_

- [ ] 3. Implementar la herramienta de reindexación de documentos técnicos
  - Implementar la función `reindex_ops_docs() -> dict` en `agent.py`
  - Integrar con `NotionIndexer.index_all()` para indexar desde Notion
  - Capturar excepciones (token inválido, conexión fallida, etc.)
  - Devolver mensaje de éxito con número de documentos indexados
  - Devolver mensaje de error descriptivo en caso de fallo
  - Guardar el índice en `.data/ops_index.json`
  - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ]* 3.1 Escribir pruebas unitarias para reindex_ops_docs
  - Probar reindexación exitosa
  - Probar manejo de token inválido
  - Probar manejo de conexión fallida
  - Probar que el índice se regenera completamente (no incremental)
  - Probar que se incluyen metadatos requeridos (timestamp, total_documents)
  - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 4. Definir el agente ADK con instrucciones especializadas
  - Crear instancia de `Agent` con modelo `gemini-2.0-flash`
  - Configurar nombre: "ops_agent"
  - Configurar descripción: "Agente experto en información técnica y operacional de AWS/GCP para el equipo de BizOps."
  - Escribir instrucciones especializadas para consultas técnicas y operacionales (aprovisionamiento, facturación, cuentas, soporte, procesos operacionales, documentación de servicios cloud)
  - Registrar herramientas: `search_ops_docs` y `reindex_ops_docs`
  - Instruir al agente para usar siempre search_ops_docs antes de responder
  - Instruir al agente para responder en español, sintetizando información sin copiar texto literal
  - Instruir al agente para no incluir referencias de Notion (excepto URLs de dashboards operacionales)
  - _Requisitos: 7.1, 7.3, 7.4, 7.5, 11.1, 11.2, 11.3_

- [ ]* 4.1 Escribir pruebas de integración para el agente ADK
  - Probar que el agente responde a consultas técnicas/operacionales típicas
  - Probar que el agente usa search_ops_docs
  - Probar que el agente responde en español
  - Probar que el agente sintetiza información sin copiar texto literal
  - Probar que el agente no incluye referencias de Notion
  - _Requisitos: 7.1, 7.3, 7.4, 7.5, 11.1, 11.2, 11.3_

- [ ] 5. Crear el script de arranque del bot de Slack
  - Crear el archivo `run_ops_bot.py` en la raíz del proyecto
  - Cargar variables de entorno desde `.env`
  - Importar el agente desde `agents.ops_agent.agent`
  - Configurar rutas de índice y whitelist
  - Invocar `run_bot()` del módulo compartido `slack_bot.py` con parámetros correctos
  - Pasar `bot_token`, `app_token`, `whitelist_path`, `adk_agent` y `bot_name`
  - _Requisitos: 6.1, 10.1, 9.1, 9.2_

- [ ]* 5.1 Escribir pruebas de integración para el bot de Slack
  - Probar que el bot se inicia sin errores con variables de entorno correctas
  - Probar que el bot falla con mensaje claro si falta una variable de entorno requerida
  - Probar que el bot se conecta a Slack mediante Socket Mode
  - _Requisitos: 5.1, 6.2, 6.3_

- [ ] 6. Configurar variables de entorno requeridas
  - Documentar las variables de entorno requeridas en `.env.example` o README
  - Variables requeridas:
    - `NOTION_TOKEN_OPS`: Token de integración de Notion
    - `SLACK_BOT_TOKEN_OPS`: Token del bot de Slack
    - `SLACK_APP_TOKEN_OPS`: Token de aplicación de Slack para Socket Mode
    - `SLACK_ADMIN_USERS`: Lista de IDs de administradores (separados por comas)
    - `GOOGLE_API_KEY`: Clave de API de Google para Gemini
  - _Requisitos: 6.1, 6.2, 6.3_

- [ ] 7. Verificar integración con módulos compartidos
  - Verificar que `NotionIndexer` se importa correctamente desde `notion_shared.indexer`
  - Verificar que `run_bot` se importa correctamente desde `slack_bot.py`
  - Verificar que no se requieren cambios en `notion_shared` ni `slack_bot.py`
  - Verificar que el agente sigue el mismo patrón que `aws_agent` y `gcp_agent`
  - _Requisitos: 9.1, 9.2, 9.3, 9.4_

- [ ] 8. Punto de control - Verificar estructura y configuración
  - Verificar que la estructura de directorios es correcta
  - Verificar que todas las variables de entorno están configuradas
  - Verificar que el agente se importa correctamente
  - Verificar que no hay errores de sintaxis
  - Asegurarse de que todas las pruebas pasen, consultar al usuario si hay dudas.

- [ ] 9. Implementar búsqueda avanzada con filtrado de keywords
  - Mejorar `search_ops_docs` para extraer keywords de la consulta
  - Para documentos grandes (>4000 caracteres), puntuar cada línea por relevancia
  - Ordenar líneas por número de keywords coincidentes
  - Seleccionar las 15 líneas más relevantes
  - Aplicar este filtrado solo a documentos grandes, no a documentos pequeños
  - _Requisitos: 1.4, 12.4_

- [ ]* 9.1 Escribir pruebas de propiedad para filtrado de documentos grandes
  - **Propiedad 2: Filtrado de documentos grandes**
  - **Valida: Requisitos 1.4, 12.4**
  - Probar que para cualquier documento >4000 caracteres, el contenido mostrado contiene solo líneas relevantes
  - Probar que las líneas más relevantes aparecen primero
  - Probar que se seleccionan máximo 15 líneas

- [ ] 10. Implementar manejo de errores y recuperación
  - Implementar manejo de índice vacío o inexistente
  - Implementar manejo de token de Notion inválido o expirado
  - Implementar manejo de timeout del agente ADK (120 segundos)
  - Implementar manejo de usuario sin acceso (flujo de solicitud de acceso)
  - Implementar logging de errores
  - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ]* 10.1 Escribir pruebas unitarias para manejo de errores
  - Probar que índice vacío devuelve mensaje descriptivo
  - Probar que token inválido devuelve error descriptivo
  - Probar que timeout se maneja correctamente
  - Probar que usuario sin acceso ve flujo de solicitud
  - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 11. Verificar creación de archivos de datos
  - Verificar que `.data/ops_index.json` se crea correctamente
  - Verificar que `.data/whitelist_ops.json` se crea correctamente
  - Verificar que ambos archivos están excluidos del repositorio (`.gitignore`)
  - Verificar que los archivos contienen contenido válido
  - _Requisitos: 10.2, 13.2, 13.3_

- [ ]* 11.1 Escribir pruebas de propiedad para creación de archivos
  - **Propiedad 17: Archivos de datos se crean correctamente**
  - **Valida: Requisitos 10.2**
  - Probar que `.data/ops_index.json` se crea con estructura válida
  - Probar que `.data/whitelist_ops.json` se crea con estructura válida
  - Probar que ambos archivos persisten después de reiniciar el bot

- [ ] 12. Verificar búsqueda usa índice local
  - Verificar que `search_ops_docs` usa `.data/ops_index.json` local
  - Verificar que no se conecta a Notion API en cada búsqueda
  - Verificar que el índice se carga correctamente desde el archivo JSON
  - _Requisitos: 12.5_

- [ ]* 12.1 Escribir pruebas de propiedad para búsqueda local
  - **Propiedad 18: Búsquedas usan índice local**
  - **Valida: Requisitos 12.5**
  - Probar que búsquedas no requieren conexión a Notion API
  - Probar que el índice se carga desde archivo local
  - Probar que búsquedas son rápidas (<1 segundo)

- [ ] 13. Verificar respuestas dentro del timeout
  - Verificar que todas las respuestas se generan en menos de 120 segundos
  - Verificar que el timeout se configura correctamente en `slack_bot.py`
  - Verificar que se muestra mensaje de error si se excede el timeout
  - _Requisitos: 12.1_

- [ ]* 13.1 Escribir pruebas de propiedad para timeout
  - **Propiedad 19: Respuestas dentro del timeout**
  - **Valida: Requisitos 12.1**
  - Probar que respuestas se generan en menos de 120 segundos
  - Probar que timeout se maneja correctamente

- [ ] 14. Verificar seguridad de datos sensibles
  - Verificar que tokens de Notion y Slack se almacenan en `.env`
  - Verificar que `.env` está excluido del repositorio
  - Verificar que el índice ops está excluido del repositorio
  - Verificar que la whitelist está excluida del repositorio
  - Verificar que usuario sin acceso no ve información sobre documentos
  - Verificar que solo administradores pueden gestionar whitelist
  - _Requisitos: 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ]* 14.1 Escribir pruebas de propiedad para seguridad
  - **Propiedad 16: Acceso denegado sin revelar información**
  - **Valida: Requisitos 8.5, 13.4**
  - Probar que usuario no autorizado no ve información sobre documentos
  - Probar que solo administradores pueden ejecutar comandos admin

- [ ] 15. Punto de control - Verificar todas las pruebas pasan
  - Ejecutar todas las pruebas unitarias
  - Ejecutar todas las pruebas de integración
  - Ejecutar todas las pruebas de propiedad
  - Verificar que no hay errores de sintaxis
  - Asegurarse de que todas las pruebas pasen, consultar al usuario si hay dudas.

- [ ] 16. Documentación y especificación final
  - Crear o actualizar `AGENTS.md` con información del agente ops
  - Documentar cómo configurar variables de entorno
  - Documentar cómo ejecutar el bot
  - Documentar cómo reindexar la documentación
  - Documentar cómo gestionar la whitelist
  - _Requisitos: 11.1, 11.2, 11.3_

- [ ] 17. Verificación final de integración
  - Verificar que el agente se integra correctamente con `slack_bot.py`
  - Verificar que el agente responde a consultas técnicas/operacionales típicas
  - Verificar que el flujo de acceso (whitelist, solicitud, aprobación) funciona
  - Verificar que los comandos admin funcionan correctamente
  - Verificar que la reindexación funciona correctamente
  - _Requisitos: 1.1, 2.1, 3.1, 4.1, 5.1, 6.1_

- [ ] 18. Punto de control final - Asegurar que todas las pruebas pasan
  - Ejecutar todas las pruebas
  - Verificar que no hay errores
  - Asegurarse de que todas las pruebas pasen, consultar al usuario si hay dudas.

## Notas

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los puntos de control aseguran validación incremental
- Las pruebas de propiedad validan propiedades de corrección universales
- Las pruebas unitarias validan ejemplos específicos y casos límite
- El agente ops sigue el mismo patrón que los agentes AWS y GCP existentes
- No se requieren cambios en módulos compartidos (`notion_shared`, `slack_bot.py`)
- El agente usa `gemini-2.0-flash` para balance entre velocidad y calidad
