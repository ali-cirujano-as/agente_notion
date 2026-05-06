#!/usr/bin/env python3
"""Encuentra las páginas de dashboards específicas y analiza su contenido."""

import os
from dotenv import load_dotenv
from notion_shared.notion_client import NotionClient

load_dotenv()


def find_and_analyze_dashboards(name: str, token: str, keywords: list):
    """Busca páginas específicas por keywords y analiza su contenido."""
    if not token:
        print(f"\n⚠️  {name}: Token no configurado")
        return
    
    client = NotionClient(token)
    print(f"\n{'='*80}")
    print(f"🔑 TOKEN: {name}")
    print(f"{'='*80}")
    
    # Obtener todas las páginas
    pages = client.search_all(filter_type="page")
    
    # Filtrar páginas que coincidan con los keywords
    matching_pages = []
    for page in pages:
        props = page.get("properties", {})
        title_prop = props.get("title", {})
        title_list = title_prop.get("title", [])
        page_title = title_list[0].get("plain_text", "Sin título") if title_list else "Sin título"
        
        # Verificar si algún keyword está en el título
        if any(keyword.lower() in page_title.lower() for keyword in keywords):
            matching_pages.append({
                "id": page["id"],
                "title": page_title,
                "url": page.get("url", ""),
                "parent": page.get("parent", {})
            })
    
    if not matching_pages:
        print(f"\n❌ No se encontraron páginas con los keywords: {', '.join(keywords)}")
        return
    
    print(f"\n📄 PÁGINAS ENCONTRADAS: {len(matching_pages)}")
    
    for i, page in enumerate(matching_pages, 1):
        print(f"\n{'─'*80}")
        print(f"{i}. {page['title']}")
        print(f"   ID: {page['id']}")
        print(f"   URL: {page['url']}")
        
        # Analizar el contenido de la página
        print(f"\n   🔍 Analizando contenido de la página...")
        
        try:
            blocks = client.get_block_children(page['id'])
            
            # Buscar bases de datos embebidas
            child_databases = []
            linked_databases = []
            
            for block in blocks:
                btype = block.get("type", "")
                
                if btype == "child_database":
                    db_id = block["id"]
                    db_title = block.get("child_database", {}).get("title", "Sin título")
                    
                    # Intentar acceder a la base de datos
                    try:
                        db_info = client.get_database(db_id)
                        child_databases.append({
                            "id": db_id,
                            "title": db_title,
                            "accessible": True
                        })
                    except Exception as e:
                        error_msg = str(e)
                        if "linked database" in error_msg.lower():
                            # Es una linked database (vista)
                            # Intentar extraer el ID de la fuente del error
                            import re
                            match = re.search(r'Database with ID ([a-f0-9-]+)', error_msg)
                            source_id = match.group(1) if match else "desconocido"
                            
                            linked_databases.append({
                                "view_id": db_id,
                                "view_title": db_title,
                                "source_id": source_id,
                                "error": error_msg
                            })
                        else:
                            child_databases.append({
                                "id": db_id,
                                "title": db_title,
                                "accessible": False,
                                "error": str(e)[:100]
                            })
            
            # Mostrar resultados
            if child_databases:
                print(f"\n   📊 BASES DE DATOS EMBEBIDAS: {len(child_databases)}")
                for db in child_databases:
                    if db.get("accessible"):
                        print(f"      ✅ {db['title']}")
                        print(f"         ID: {db['id']}")
                        print(f"         URL: https://notion.so/{db['id'].replace('-', '')}")
                    else:
                        print(f"      ❌ {db['title']}")
                        print(f"         ID: {db['id']}")
                        print(f"         Error: {db.get('error', 'Desconocido')}")
            
            if linked_databases:
                print(f"\n   🔗 VISTAS (LINKED DATABASES): {len(linked_databases)}")
                for view in linked_databases:
                    print(f"      ⚠️  {view['view_title']}")
                    print(f"         ID de la vista: {view['view_id']}")
                    print(f"         URL de la vista: https://notion.so/{view['view_id'].replace('-', '')}")
                    print(f"         ID de la fuente: {view['source_id']}")
                    print(f"         URL de la fuente: https://notion.so/{view['source_id'].replace('-', '')}")
                    print(f"\n         ❌ ESTA ES UNA VISTA - NO PUEDES ACCEDER DIRECTAMENTE")
                    print(f"         ✅ NECESITAS COMPARTIR LA BASE DE DATOS FUENTE:")
                    print(f"            1. Abre: https://notion.so/{view['source_id'].replace('-', '')}")
                    print(f"            2. Haz clic en ··· (tres puntos) → Connections")
                    if name == "AWS":
                        print(f"            3. Conecta la integración 'ADK AWS'")
                    elif name == "GCP":
                        print(f"            3. Conecta la integración 'ADK GCP'")
            
            if not child_databases and not linked_databases:
                print(f"      ℹ️  No se encontraron bases de datos embebidas en esta página")
                print(f"      ℹ️  Esta página puede contener solo texto o enlaces")
        
        except Exception as e:
            print(f"      ❌ Error al analizar la página: {e}")


def main():
    print("🔍 ANÁLISIS DE PÁGINAS DE DASHBOARDS")
    print("="*80)
    
    # Keywords para AWS
    aws_keywords = [
        "Provisiones Bloqueadas",
        "EPPM",
        "provisiones en curso"
    ]
    
    # Keywords para GCP
    gcp_keywords = [
        "Provisiones Bloqueadas",
        "EPPM",
        "provisiones en curso",
        "Licencias Caducadas",
        "Avisos de Renovación"
    ]
    
    # Analizar AWS
    find_and_analyze_dashboards("AWS", os.getenv("NOTION_TOKEN_AWS", ""), aws_keywords)
    
    # Analizar GCP
    find_and_analyze_dashboards("GCP", os.getenv("NOTION_TOKEN_GCP", ""), gcp_keywords)
    
    print(f"\n{'='*80}")
    print("✅ Análisis completado")
    print("="*80)


if __name__ == "__main__":
    main()
