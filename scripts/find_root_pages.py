#!/usr/bin/env python3
"""Encuentra páginas raíz conectadas a las integraciones de Notion."""

import os
from dotenv import load_dotenv
from notion_shared.notion_client import NotionClient
from notion_shared.text_extractor import extract_page_title

load_dotenv()


def find_root_pages(name: str, token: str):
    """Encuentra páginas raíz (no dentro de bases de datos)."""
    if not token:
        print(f"\n⚠️  {name}: Token no configurado")
        return

    client = NotionClient(token)
    print(f"\n{'='*80}")
    print(f"🔑 {name}")
    print(f"{'='*80}")

    # Buscar todas las páginas
    pages = client.search_all(filter_type="page")
    
    # Filtrar páginas que NO son filas de base de datos
    root_pages = []
    db_pages = []
    
    for page in pages:
        parent = page.get("parent", {})
        parent_type = parent.get("type", "")
        
        if parent_type == "database_id":
            db_pages.append(page)
        else:
            root_pages.append(page)
    
    print(f"\n📊 RESUMEN:")
    print(f"  - Páginas independientes: {len(root_pages)}")
    print(f"  - Filas de base de datos: {len(db_pages)}")
    
    if root_pages:
        print(f"\n🏠 PÁGINAS INDEPENDIENTES A DESCONECTAR:")
        for page in root_pages:
            title = extract_page_title(page)
            page_id = page.get("id", "")
            parent = page.get("parent", {})
            parent_type = parent.get("type", "")
            
            print(f"\n  📄 {title}")
            print(f"     ID: {page_id}")
            print(f"     URL: https://notion.so/{page_id.replace('-', '')}")
            print(f"     Parent: {parent_type}")
            
            # Si tiene parent page_id, mostrar el padre
            if parent_type == "page_id":
                parent_id = parent.get("page_id", "")
                print(f"     Dentro de: https://notion.so/{parent_id.replace('-', '')}")
    else:
        print(f"\n✅ No hay páginas independientes conectadas.")
        print(f"   Todas las páginas son filas de bases de datos.")


def main():
    print("🔍 BUSCANDO PÁGINAS RAÍZ PARA DESCONECTAR")
    print("="*80)
    
    find_root_pages("AWS", os.getenv("NOTION_TOKEN_AWS", ""))
    find_root_pages("GCP", os.getenv("NOTION_TOKEN_GCP", ""))
    
    print(f"\n{'='*80}")
    print("✅ Búsqueda completada")
    print("="*80)


if __name__ == "__main__":
    main()
