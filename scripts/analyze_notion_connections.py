#!/usr/bin/env python3
"""Analiza las conexiones de Notion para identificar qué desconectar."""

import os
from dotenv import load_dotenv
from notion_shared.notion_client import NotionClient

load_dotenv()


def analyze_token(name: str, token: str):
    """Analiza un token de Notion y muestra información detallada."""
    if not token:
        print(f"\n⚠️  {name}: Token no configurado")
        return

    client = NotionClient(token)
    print(f"\n{'='*80}")
    print(f"🔑 {name}")
    print(f"{'='*80}")

    # Buscar páginas
    pages = client.search_all(filter_type="page")
    
    # Buscar bases de datos
    databases = client.search_all(filter_type="database")

    print(f"\n📊 RESUMEN:")
    print(f"  - Total páginas: {len(pages)}")
    print(f"  - Total bases de datos: {len(databases)}")

    # Agrupar páginas por workspace/parent
    print(f"\n📄 PÁGINAS POR TIPO:")
    
    # Identificar páginas raíz (sin parent o parent es workspace)
    root_pages = []
    child_pages = []
    
    for page in pages:
        parent = page.get("parent", {})
        if parent.get("type") == "workspace":
            root_pages.append(page)
        else:
            child_pages.append(page)
    
    print(f"\n  🏠 Páginas raíz (nivel superior): {len(root_pages)}")
    for page in root_pages[:10]:  # Mostrar solo las primeras 10
        title = page.get("properties", {}).get("title", {}).get("title", [])
        title_text = title[0].get("plain_text", "Sin título") if title else "Sin título"
        page_id = page.get("id", "")
        print(f"    - {title_text}")
        print(f"      ID: {page_id}")
        print(f"      URL: https://notion.so/{page_id.replace('-', '')}")
    
    if len(root_pages) > 10:
        print(f"    ... y {len(root_pages) - 10} más")

    print(f"\n  📑 Páginas hijas (dentro de otras páginas): {len(child_pages)}")
    
    # Analizar bases de datos
    print(f"\n🗃️  BASES DE DATOS:")
    for db in databases:
        title = db.get("title", [])
        title_text = title[0].get("plain_text", "Sin título") if title else "Sin título"
        db_id = db.get("id", "")
        print(f"    - {title_text}")
        print(f"      ID: {db_id}")
        print(f"      URL: https://notion.so/{db_id.replace('-', '')}")
        
        # Contar filas en la base de datos
        try:
            rows = client.query_database(db_id)
            print(f"      Filas: {len(rows)}")
        except Exception as e:
            print(f"      Filas: Error al contar ({str(e)[:50]})")

    # Identificar patrones comunes
    print(f"\n🔍 ANÁLISIS DE CONTENIDO:")
    
    # Buscar páginas con "ALTBO" en el título
    altbo_pages = [p for p in pages if "ALTBO" in str(p.get("properties", {}))]
    if altbo_pages:
        print(f"  - Tickets ALTBO: {len(altbo_pages)} páginas")
    
    # Buscar páginas con "AWS" en el título
    aws_pages = [p for p in pages if "AWS" in str(p.get("properties", {}))]
    if aws_pages:
        print(f"  - Páginas AWS: {len(aws_pages)} páginas")
    
    # Buscar páginas con "GCP" en el título
    gcp_pages = [p for p in pages if "GCP" in str(p.get("properties", {}))]
    if gcp_pages:
        print(f"  - Páginas GCP: {len(gcp_pages)} páginas")

    print(f"\n💡 RECOMENDACIÓN:")
    if len(root_pages) > 0:
        print(f"  Para desconectar este token, ve a Notion y:")
        print(f"  1. Abre cada página raíz listada arriba")
        print(f"  2. Haz clic en ··· (tres puntos)")
        print(f"  3. Connections → Desconecta la integración")
        print(f"  4. Las páginas hijas se desconectarán automáticamente")
    
    if len(databases) > 0:
        print(f"\n  Para las bases de datos:")
        print(f"  1. Abre cada base de datos")
        print(f"  2. Haz clic en ··· (tres puntos)")
        print(f"  3. Connections → Desconecta la integración")


def main():
    print("🔍 ANÁLISIS DE CONEXIONES DE NOTION")
    print("="*80)
    
    # Analizar cada token
    analyze_token("AWS", os.getenv("NOTION_TOKEN_AWS", ""))
    analyze_token("GCP", os.getenv("NOTION_TOKEN_GCP", ""))
    analyze_token("COMMERCIAL", os.getenv("NOTION_TOKEN_COMMERCIAL", ""))
    
    print(f"\n{'='*80}")
    print("✅ Análisis completado")
    print("="*80)


if __name__ == "__main__":
    main()
