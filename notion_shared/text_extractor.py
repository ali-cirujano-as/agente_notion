"""Extrae texto plano de bloques y propiedades de Notion."""


def extract_rich_text(rich_text_list: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def extract_block_text(block: dict) -> str:
    """Extrae texto de un bloque de Notion."""
    btype = block.get("type", "")
    bdata = block.get(btype, {})

    if btype in (
        "paragraph", "heading_1", "heading_2", "heading_3",
        "bulleted_list_item", "numbered_list_item", "toggle",
        "quote", "callout",
    ):
        text = extract_rich_text(bdata.get("rich_text", []))
        prefix = ""
        if btype == "heading_1":
            prefix = "# "
        elif btype == "heading_2":
            prefix = "## "
        elif btype == "heading_3":
            prefix = "### "
        elif btype == "bulleted_list_item":
            prefix = "- "
        elif btype == "numbered_list_item":
            prefix = "1. "
        elif btype == "quote":
            prefix = "> "
        return f"{prefix}{text}"

    if btype == "to_do":
        checked = "x" if bdata.get("checked") else " "
        text = extract_rich_text(bdata.get("rich_text", []))
        return f"[{checked}] {text}"

    if btype == "code":
        text = extract_rich_text(bdata.get("rich_text", []))
        lang = bdata.get("language", "")
        return f"```{lang}\n{text}\n```"

    if btype == "divider":
        return "---"

    if btype == "table_row":
        cells = bdata.get("cells", [])
        return " | ".join(extract_rich_text(cell) for cell in cells)

    return ""


def extract_page_title(page: dict) -> str:
    """Extrae el título de una página de Notion."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return extract_rich_text(prop.get("title", []))
    return "Sin título"


def extract_property_value(prop: dict) -> str:
    """Extrae el valor de una propiedad de base de datos."""
    ptype = prop.get("type", "")

    if ptype == "title":
        return extract_rich_text(prop.get("title", []))
    if ptype == "rich_text":
        return extract_rich_text(prop.get("rich_text", []))
    if ptype == "number":
        val = prop.get("number")
        return str(val) if val is not None else ""
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    if ptype == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    if ptype == "date":
        d = prop.get("date")
        if d:
            start = d.get("start", "")
            end = d.get("end", "")
            return f"{start} → {end}" if end else start
        return ""
    if ptype == "checkbox":
        return "Sí" if prop.get("checkbox") else "No"
    if ptype == "url":
        return prop.get("url", "") or ""
    if ptype == "email":
        return prop.get("email", "") or ""
    if ptype == "phone_number":
        return prop.get("phone_number", "") or ""
    if ptype == "status":
        s = prop.get("status")
        return s.get("name", "") if s else ""
    if ptype == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    if ptype == "relation":
        return f"({len(prop.get('relation', []))} relaciones)"
    if ptype == "formula":
        f = prop.get("formula", {})
        ftype = f.get("type", "")
        return str(f.get(ftype, ""))

    return ""


def extract_database_row(row: dict) -> str:
    """Convierte una fila de base de datos a texto."""
    parts = []
    props = row.get("properties", {})
    for name, prop in props.items():
        val = extract_property_value(prop)
        if val:
            parts.append(f"{name}: {val}")
    return " | ".join(parts)
