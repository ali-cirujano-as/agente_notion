#!/usr/bin/env python3
"""Analiza todas las vistas compartidas e identifica las bases de datos fuente."""

import os
from dotenv import load_dotenv
from notion_shared.notion_client import NotionClient

load_dotenv()


def analyze_page_for_linked_databases(client: NotionClient, page_id: str, page_title: str, depth=0):
    """Analiza una página recursivamente buscando bases de datos embebidas (vistas)."""
    if depth > 2:
        return []
    
    linked_dbs = []
    
    try:
        blocks = client.get_block_children(page_id)
        
        for block in blocks:
            btype = block.get("type", "")
            
            # Si es una base de datos hija (child_database), es una VISTA
            if btype == "child_database":
                db_id = block["id"]
                db_title = block.get("child_database", {}).get("title", "Sin título")
                
                # Intentar obtener información de la base de datos
                try:
                    db_info = client.get_database(db_id)
                    
                    # Verificar si es una linked database
                    is_inline = db_info.get("is_inline", False)
                    
                    linked_dbs.append({
                        "view_id": db_id,
                        "view_title": db_title,
                        "page_title": page_title,
                        "is_inline": is_inline,
                        "url": f"https://notion.so/{db_id.replace('-', '')}"
                    })
                    
                except Exception as e:
                    error_msg = str(e)
                    # Si el error menciona "linked database", extraer el ID de la fuente
                    if "linked database" in error_msg.lower():
                        # Intentar extraer el ID de la base de datos fuente del mensaje de error
                        linked_dbs.append({
                            "view_id": db_id,
                            "view_title": db_title,
                            "page_title": page_title,
                            "is_inline": False,
                            "is_linked": True,
                            "error": error_msg,
                            "url": f"https://notion.so/{db_id.replace('-', '')}"
                        })
            
            # Recurrir en bloques con hijos
            if block.get("has_children"):
                child_dbs = analyze_page_for_linked_databases(client, block["id"], page_title, depth + 1)
                linked_dbs.extend(child_dbs)
    
    except Exception as e:
        pass
    
    return linked_dbs


def analyze_token(name: str, token: str):
    """Analiza un token y muestra todas las vistas y sus fuentes."""
    if not token:
        print(f"\n⚠️  {name}: Token no configurado")
        return
    
    client = NotionClient(token)
    print(f"\n{'='*80}")
    print(f"🔑 TOKEN: {name}")
    print(f"{'='*80}")
    
    # Obtener todas las páginas
    pages = client.search_all(filter_type="page")
    print(f"\n📄 Páginas accesibles: {len(pages)}")
    
    # Obtener todas las bases de datos
    databases = client.search_all(filter_type="database")
    print(f"🗃️  Bases de datos accesibles: {len(databases)}")
    
    # Analizar cada página buscando vistas embebidas
    print(f"\n🔍 Analizando páginas en busca de vistas (linked databases)...")
    all_views = []
    
    for page in pages:
        # Extraer título
        props = page.get("properties", {})
        title_prop = props.get("title", {})
        title_list = title_prop.get("title", [])
        page_title = title_list[0].get("plain_text", "Sin título") if title_list else "Sin título"
        
        # Buscar vistas en esta página
        views = analyze_page_for_linked_databases(client, page["id"], page_title)
        all_views.extend(views)
    
    # Mostrar resultados
    if all_views:
        print(f"\n📊 VISTAS ENCONTRADAS: {len(all_views)}")
        for i, view in enumerate(all_views, 1):
            print(f"\n  {i}. Vista: {view['view_title']}")
            print(f"     Página contenedora: {view['page_title']}")
            print(f"     ID de la vista: {view['view_id']}")
            print(f"     URL: {view['url']}")
            
            if view.get("is_linked"):
                print(f"     ⚠️  ESTA ES UNA VISTA (linked database)")
                print(f"     Error: {view.get('error', '')[:100]}...")
                print(f"     ❌ NO PUEDES ACCEDER A ESTA VISTA DIRECTAMENTE")
                print(f"     ✅ NECESITAS COMPARTIR LA BASE DE DATOS FUENTE")
            elif view.get("is_inline"):
                print(f"     ✅ Esta es una base de datos inline (accesible)")
            else:
                print(f"     ℹ️  Tipo desconocido")
    else:
        print(f"\n✅ No se encontraron vistas embebidas en las páginas")
    
    # Mostrar bases de datos accesibles directamente
    if databases:
        print(f"\n🗃️  BASES DE DATOS FUENTE ACCESIBLES:")
        for i, db in enumerate(databases, 1):
            title = db.get("title", [])
            title_text = title[0].get("plain_text", "Sin título") if title else "Sin título"
            db_id = db.get("id", "")
            print(f"\n  {i}. {title_text}")
            print(f"     ID: {db_id}")
            print(f"     URL: https://notion.so/{db_id.replace('-', '')}")
            
            # Contar filas
            try:
                rows = client.query_database(db_id)
                print(f"     Filas: {len(rows)}")
            except Exception as e:
                print(f"     Filas: Error ({str(e)[:50]})")
    
    # Recomendaciones
    print(f"\n💡 RECOMENDACIONES:")
    if all_views:
        has_linked = any(v.get("is_linked") for v in all_views)
        if has_linked:
            print(f"  ⚠️  Tienes vistas (linked databases) que NO son accesibles")
            print(f"  📝 Para acceder a la información de estas vistas:")
            print(f"     1. Identifica la base de datos FUENTE de cada vista")
            print(f"     2. Ve a la base de datos fuente en Notion")
            print(f"     3. Haz clic en ··· (tres puntos) → Connections")
            print(f"     4. Conecta la integración correspondiente:")
            if name == "AWS":
                print(f"        → Para AWS: conecta 'ADK AWS'")
            elif name == "GCP":
                print(f"        → Para GCP: conecta 'ADK GCP'")
            print(f"     5. Una vez conectada la fuente, podrás acceder a los datos")
    
    if databases:
        print(f"\n  ✅ Las bases de datos fuente listadas arriba YA son accesibles")
        print(f"  ✅ El agente puede leer información de estas bases de datos")


def main():
    print("🔍 ANÁLISIS DE VISTAS Y BASES DE DATOS FUENTE")
    print("="*80)
    
    # Analizar cada token
    analyze_token("AWS", os.getenv("NOTION_TOKEN_AWS", ""))
    analyze_token("GCP", os.getenv("NOTION_TOKEN_GCP", ""))
    
    print(f"\n{'='*80}")
    print("✅ Análisis completado")
    print("="*80)


if __name__ == "__main__":
    main()
