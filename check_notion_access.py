#!/usr/bin/env python3
"""Muestra qué páginas y bases de datos ve cada token de Notion."""
import os
from dotenv import load_dotenv
from notion_shared.notion_client import NotionClient
from notion_shared.text_extractor import extract_page_title

load_dotenv()


def check_token(name: str, token: str):
    if not token:
        print(f"\n❌ {name}: Token no configurado")
        return

    client = NotionClient(token)
    print(f"\n{'='*60}")
    print(f"🔑 {name}")
    print(f"{'='*60}")

    # Páginas
    pages = client.search_all(filter_type="page")
    print(f"\n📄 Páginas ({len(pages)}):")
    for p in pages:
        title = extract_page_title(p)
        pid = p["id"]
        url = p.get("url", "")
        print(f"  - {title}")
        print(f"    ID: {pid}")
        print(f"    URL: {url}")

    # Bases de datos
    dbs = client.search_all(filter_type="database")
    print(f"\n🗃️  Bases de datos ({len(dbs)}):")
    for db in dbs:
        title_list = db.get("title", [])
        title = title_list[0].get("plain_text", "Sin título") if title_list else "Sin título"
        did = db["id"]
        url = db.get("url", "")
        print(f"  - {title}")
        print(f"    ID: {did}")
        print(f"    URL: {url}")

    if not pages and not dbs:
        print("\n⚠️  Este token no tiene acceso a nada.")
        print("   Ve a Notion → página → ··· → Connections → conecta la integración")


def main():
    check_token("AWS", os.getenv("NOTION_TOKEN_AWS", ""))
    check_token("GCP", os.getenv("NOTION_TOKEN_GCP", ""))


if __name__ == "__main__":
    main()
