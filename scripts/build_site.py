#!/usr/bin/env python3
"""Reconstruye el blog estático a partir del volcado SQL de WordPress."""

from __future__ import annotations

import html
import warnings

from bs4 import MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path("/Users/estebanetayo/EstebanEtayo")
SQL_PATH = Path(
    "/Users/estebanetayo/Library/Mobile Documents/com~apple~CloudDocs/db486499487_db_1and1_com.sql"
)
MEDIA_ROOT = ROOT / "media"
ASSETS = ROOT / "assets"
MANIFEST = ROOT / ".build-manifest.txt"
SITE = "https://estebanetayo.es"
NAV_PAGES: list[dict] = []
BLOCK_TAGS = {"p", "h2", "h3", "h4", "h5", "ul", "ol", "blockquote", "pre", "figure", "table", "div", "hr"}
HOSTS = {"estebanetayo.es", "www.estebanetayo.es"}
RESERVED = {
    "assets",
    "media",
    "css",
    "js",
    "scripts",
    "tema",
    "category",
    "tag",
    "index.html",
    "favicon.svg",
}

MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
MONTHS_SHORT = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)
SPAM_HINTS = (
    "viagra",
    "cialis",
    "casino",
    "payday",
    "seo service",
    "forex",
    "crypto",
    "lottery",
)


def parse_rows(blob: str) -> tuple[list[list], int]:
    rows = []
    i = 0
    n = len(blob)
    while i < n:
        while i < n and blob[i] in " \t\r\n,":
            i += 1
        if i >= n or blob[i] == ";":
            break
        if blob[i] != "(":
            raise ValueError(f"Se esperaba una fila SQL cerca de: {blob[i:i+40]!r}")
        i += 1
        fields = []
        while True:
            while i < n and blob[i] in " \t\r\n":
                i += 1
            if i >= n:
                break
            if blob[i] == "'":
                i += 1
                chars = []
                while i < n:
                    char = blob[i]
                    if char == "\\":
                        i += 1
                        if i >= n:
                            break
                        esc = blob[i]
                        chars.append(
                            {
                                "n": "\n",
                                "r": "\r",
                                "t": "\t",
                                "0": "\0",
                                "Z": "\x1a",
                                "\\": "\\",
                                "'": "'",
                                '"': '"',
                            }.get(esc, esc)
                        )
                        i += 1
                    elif char == "'":
                        if i + 1 < n and blob[i + 1] == "'":
                            chars.append("'")
                            i += 2
                        else:
                            i += 1
                            break
                    else:
                        chars.append(char)
                        i += 1
                fields.append("".join(chars))
            elif blob.startswith("NULL", i):
                fields.append(None)
                i += 4
            else:
                j = i
                while j < n and blob[j] not in ",)":
                    j += 1
                fields.append(blob[i:j].strip())
                i = j
            while i < n and blob[i] in " \t\r\n":
                i += 1
            if i < n and blob[i] == ",":
                i += 1
                continue
            if i < n and blob[i] == ")":
                i += 1
                break
            raise ValueError(f"Fila SQL incompleta cerca de: {blob[i:i+40]!r}")
        rows.append(fields)
    return rows, i


def extract_inserts(sql: str, table: str) -> list[list]:
    marker = f"INSERT INTO `{table}`"
    rows = []
    idx = 0
    while True:
        start = sql.find(marker, idx)
        if start < 0:
            break
        values = sql.find("VALUES", start)
        if values < 0:
            break
        parsed, consumed = parse_rows(sql[values + len("VALUES") :])
        rows.extend(parsed)
        idx = values + len("VALUES") + consumed
    return rows


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def plain_text(fragment: str) -> str:
    text = BeautifulSoup(fragment or "", "html.parser").get_text(" ", strip=True)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def excerpt(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def long_date(value: str) -> str:
    year, month, day = value[:10].split("-")
    return f"{int(day)} de {MONTHS[int(month) - 1]} de {year}"


def short_date(value: str) -> str:
    year, month, day = value[:10].split("-")
    return f"{int(day)} {MONTHS_SHORT[int(month) - 1]} {year}"


def youtube_id(blob: str) -> str | None:
    match = re.search(r"(?:v=|embed/|youtu\.be/|/v/)([\w-]{6,})", blob)
    return match.group(1) if match else None


def youtube_iframe(video_id: str) -> str:
    src = f"https://www.youtube-nocookie.com/embed/{video_id}"
    return (
        f'<div class="video"><iframe src="{src}" title="Vídeo" '
        'loading="lazy" allowfullscreen></iframe></div>'
    )


def local_upload(path: str) -> str | None:
    marker = "/wp-content/uploads/"
    if marker not in path:
        return None
    rel = unquote(path.split(marker, 1)[1]).lstrip("/")
    return resolve_media(rel)


def resolve_media(rel: str) -> str | None:
    rel = rel.split("?")[0]
    candidate = MEDIA_ROOT / rel
    if candidate.is_file():
        return "/media/" + rel
    sized = re.match(r"^(.*)-\d+x\d+(\.[A-Za-z0-9]+)$", Path(rel).name)
    if sized:
        original = str(Path(rel).with_name(sized.group(1) + sized.group(2)))
        if (MEDIA_ROOT / original).is_file():
            return "/media/" + original
    return None


def rewrite_url(href: str, ctx: dict) -> str:
    if not href:
        return href
    href = href.strip()
    if href.startswith(("#", "mailto:", "javascript:")):
        return "" if href.startswith("javascript:") else href
    absolute = href
    if href.startswith("//"):
        absolute = "http:" + href
    parsed = urlparse(absolute)
    host = (parsed.netloc or "").lower()
    if host and host not in HOSTS and not href.startswith("/"):
        return href
    path = unquote(parsed.path or "")
    media = local_upload(path)
    if media:
        return media
    query = parse_qs(parsed.query)
    for key in ("p", "page_id"):
        if key in query and query[key][0].isdigit():
            slug = ctx["slug_by_id"].get(int(query[key][0]))
            if slug:
                return f"/{slug}/"
    if "cat" in query and query["cat"][0].isdigit():
        slug = ctx["category_by_tax"].get(int(query["cat"][0]))
        if slug:
            return f"/tema/{slug}/"
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "/"
    if parts[0] == "category" and len(parts) > 1 and parts[1] in ctx["categories"]:
        return f"/tema/{parts[1]}/"
    if parts[0] == "tag" and len(parts) > 1:
        return f"/tema/{parts[1]}/" if parts[1] in ctx["categories"] else href
    if parts[0].isdigit() and len(parts[0]) == 4 and parts[-1] in ctx["id_by_slug"]:
        return f"/{parts[-1]}/"
    if len(parts) == 1 and parts[0] in ctx["id_by_slug"]:
        return f"/{parts[0]}/"
    if host in HOSTS:
        return path or "/"
    return href


def expand_captions(source: str) -> str:
    def replace(match: re.Match) -> str:
        soup = BeautifulSoup(match.group(1), "html.parser")
        image = soup.find("img")
        if not image:
            return match.group(1)
        image.extract()
        caption = plain_text(str(soup))
        figure = f"<figure>{image}</figure>"
        if caption:
            figure = f"<figure>{image}<figcaption>{esc(caption)}</figcaption></figure>"
        return figure

    return re.sub(r"\[caption\b[^\]]*\](.*?)\[/caption\]", replace, source, flags=re.I | re.S)


def expand_galleries(source: str, post: dict, ctx: dict) -> str:
    def replace(match: re.Match) -> str:
        attrs = match.group(1) or ""
        ids_match = re.search(r"ids=[\"']([\d,\s]+)[\"']", attrs)
        if ids_match:
            ids = [int(part) for part in ids_match.group(1).split(",") if part.strip().isdigit()]
        else:
            ids = ctx["gallery_ids"].get(post["id"], [])
        figures = []
        for attachment_id in ids:
            attachment = ctx["attachments"].get(attachment_id)
            if not attachment or not attachment.get("src"):
                continue
            alt = esc(attachment.get("alt") or attachment.get("title") or "")
            src = esc(attachment["src"])
            figures.append(f'<a href="{src}"><img src="{src}" alt="{alt}"></a>')
        if not figures:
            return ""
        return '<div class="gallery">' + "".join(figures) + "</div>"

    return re.sub(r"\[gallery\b([^\]]*)\]", replace, source, flags=re.I)


def replace_embeds(source: str) -> str:
    def replace(match: re.Match) -> str:
        video = youtube_id(match.group(0))
        return youtube_iframe(video) if video else ""

    source = re.sub(r"<object\b.*?</object>", replace, source, flags=re.I | re.S)
    source = re.sub(r"<embed\b[^>]*>", replace, source, flags=re.I)
    return source


def clean_html(source: str, post: dict, ctx: dict) -> str:
    source = source or ""
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    source = re.sub(r"<!--more-->", "", source, flags=re.I)
    source = expand_captions(source)
    source = expand_galleries(source, post, ctx)
    source = re.sub(r"\[/?[a-zA-Z][a-zA-Z0-9_-]*[^\]]*\]", "", source)
    source = replace_embeds(source)
    soup = BeautifulSoup(f'<div id="root">{source}</div>', "html.parser")
    root = soup.find(id="root")

    for tag in list(root.find_all(["script", "style", "noscript", "form", "iframe", "object", "embed"])):
        if tag.name == "iframe":
            video = youtube_id(tag.get("src") or "")
            if not video:
                tag.decompose()
                continue
            tag.attrs = {
                "src": f"https://www.youtube-nocookie.com/embed/{video}",
                "title": "Vídeo",
                "loading": "lazy",
                "allowfullscreen": "",
            }
            parent_classes = tag.parent.get("class") or [] if tag.parent else []
            if "video" not in parent_classes:
                tag.wrap(soup.new_tag("div", attrs={"class": "video"}))
        else:
            tag.decompose()

    for tag in list(root.find_all(True)):
        if tag.name == "a":
            href = rewrite_url(tag.get("href") or "", ctx)
            children = list(tag.contents)
            tag.attrs = {}
            if href:
                tag["href"] = href
                if href.startswith("http"):
                    tag["rel"] = "noopener noreferrer"
                    tag["target"] = "_blank"
            else:
                tag.unwrap()
        elif tag.name == "img":
            src = rewrite_url(tag.get("src") or "", ctx)
            alt = tag.get("alt") or tag.get("title") or ""
            width = tag.get("width")
            tag.attrs = {"alt": alt, "loading": "lazy"}
            if src:
                tag["src"] = src
            else:
                tag.decompose()
                continue
            if width and str(width).isdigit():
                tag["width"] = str(width)
                if int(width) <= 120:
                    tag["class"] = ["icon"]
        elif tag.name in {"td", "th"}:
            tag.attrs = {}
        elif tag.name == "div" and "gallery" in (tag.get("class") or []):
            tag.attrs = {"class": "gallery"}
        elif tag.name == "div" and "video" in (tag.get("class") or []):
            tag.attrs = {"class": "video"}
        elif tag.name not in {"figure", "figcaption", "iframe"}:
            tag.attrs = {}

    for div in reversed(list(root.find_all("div"))):
        classes = div.get("class") or []
        if "gallery" in classes or "video" in classes:
            continue
        if div.find(list(BLOCK_TAGS - {"div"})):
            div.unwrap()
        else:
            div.name = "p"
            div.attrs = {}
    for span in list(root.find_all(["span", "font"])):
        span.unwrap()
    repair_split_words(root)
    for quote in list(root.find_all("blockquote")):
        paragraphize(quote, soup)
    paragraphize(root, soup)

    for heading in list(root.find_all("h1")):
        heading.name = "h2"

    for table in list(root.find_all("table")):
        wrap = soup.new_tag("div", attrs={"class": "table-wrap"})
        table.wrap(wrap)

    for paragraph in list(root.find_all("p")):
        if paragraph.find("p"):
            paragraph.unwrap()
    for paragraph in list(root.find_all("p")):
        if not paragraph.get_text(strip=True) and not paragraph.find(["img", "iframe"]):
            paragraph.decompose()

    rendered = "".join(str(child) for child in root.contents)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()


def repair_split_words(root) -> None:
    for link in list(root.find_all("a")):
        nxt = link.next_sibling
        if not isinstance(nxt, NavigableString):
            continue
        match = re.match(r"^([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)", str(nxt))
        if not match or not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]$", link.get_text()):
            continue
        link.append(match.group(1))
        rest = str(nxt)[match.end() :]
        if rest:
            nxt.replace_with(rest)
        else:
            nxt.extract()


def paragraphize(container, soup: BeautifulSoup) -> None:
    nodes = list(container.contents)
    for node in nodes:
        node.extract()
    buffer: list = []

    def emit() -> None:
        if not buffer:
            return
        chunks: list[list] = [[]]
        for node in buffer:
            if isinstance(node, NavigableString):
                pieces = re.split(r"\n\s*\n", str(node))
                for index, piece in enumerate(pieces):
                    if index:
                        chunks.append([])
                    lead = bool(piece[:1].isspace())
                    trail = bool(piece[-1:].isspace()) if piece else False
                    text = re.sub(r"\s+", " ", piece).strip()
                    if text:
                        if lead:
                            text = " " + text
                        if trail:
                            text = text + " "
                        chunks[-1].append(soup.new_string(text))
                    elif (lead or trail) and chunks[-1]:
                        chunks[-1].append(soup.new_string(" "))
            elif isinstance(node, Tag) and node.name == "br":
                if chunks[-1] and isinstance(chunks[-1][-1], Tag) and chunks[-1][-1].name == "br":
                    chunks[-1].pop()
                    chunks.append([])
                else:
                    chunks[-1].append(node)
            else:
                chunks[-1].append(node)
        for chunk in chunks:
            meaningful = [
                node
                for node in chunk
                if not (isinstance(node, NavigableString) and not str(node).strip())
                and not (isinstance(node, Tag) and node.name == "br")
            ]
            if not meaningful:
                continue
            paragraph = soup.new_tag("p")
            for node in chunk:
                if isinstance(node, Tag) and node.name == "br":
                    continue
                if isinstance(node, NavigableString):
                    text = str(node)
                    if not text.strip():
                        if paragraph.contents and not str(paragraph.contents[-1]).endswith(" "):
                            paragraph.append(soup.new_string(" "))
                        continue
                    if (
                        paragraph.contents
                        and not isinstance(paragraph.contents[-1], NavigableString)
                        and not text.startswith(" ")
                    ):
                        text = " " + text
                    paragraph.append(soup.new_string(text))
                else:
                    if (
                        paragraph.contents
                        and isinstance(paragraph.contents[-1], NavigableString)
                        and not str(paragraph.contents[-1]).endswith((" ", "\n"))
                        and node.get_text()[:1].isalnum()
                    ):
                        paragraph.append(soup.new_string(" "))
                    paragraph.append(node)
            container.append(paragraph)
        buffer.clear()

    for node in nodes:
        if isinstance(node, Tag) and node.name in BLOCK_TAGS:
            emit()
            container.append(node)
        else:
            buffer.append(node)
    emit()


def comment_is_public(row: dict) -> bool:
    if row["approved"] != "1":
        return False
    if row["type"] not in ("", "comment"):
        return False
    text = plain_text(row["content"])
    if len(text) < 2:
        return False
    blob = f"{text} {row['author']}".lower()
    if any(hint in blob for hint in SPAM_HINTS):
        return False
    if re.fullmatch(r"https?://\S+", text):
        return False
    return True


def render_comment_body(content: str) -> str:
    text = plain_text(content)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content.replace("\r\n", "\n")) if part.strip()]
    if not paragraphs:
        paragraphs = [text]
    blocks = []
    url_re = re.compile(r"(https?://[^\s<]+)")
    for part in paragraphs:
        cleaned = plain_text(part)
        if not cleaned:
            continue
        pieces = []
        cursor = 0
        for match in url_re.finditer(cleaned):
            pieces.append(esc(cleaned[cursor:match.start()]))
            url = match.group(1).rstrip(".,)")
            pieces.append(
                f'<a href="{esc(url)}" rel="nofollow noopener noreferrer" target="_blank">{esc(url)}</a>'
            )
            cursor = match.end()
        pieces.append(esc(cleaned[cursor:]))
        blocks.append(f"<p>{''.join(pieces)}</p>")
    return "".join(blocks)


def load_model() -> dict:
    sql = SQL_PATH.read_text(encoding="utf-8", errors="replace")
    terms = {
        int(row[0]): {"name": row[1], "slug": row[2]}
        for row in extract_inserts(sql, "Wordpress5195_wp_terms")
    }
    taxonomy = {}
    for row in extract_inserts(sql, "Wordpress5195_wp_term_taxonomy"):
        tax_id = int(row[0])
        term = terms.get(int(row[1]), {})
        taxonomy[tax_id] = {
            "id": tax_id,
            "term_id": int(row[1]),
            "taxonomy": row[2],
            "name": term.get("name") or "",
            "slug": term.get("slug") or "",
        }
    relations = defaultdict(list)
    for row in extract_inserts(sql, "Wordpress5195_wp_term_relationships"):
        relations[int(row[0])].append(int(row[1]))

    meta = defaultdict(dict)
    for row in extract_inserts(sql, "Wordpress5195_wp_postmeta"):
        key = row[2] or ""
        if key in {"_thumbnail_id", "_wp_attached_file", "_wp_attachment_image_alt"}:
            meta[int(row[1])][key] = row[3] or ""

    posts = []
    attachments = {}
    for row in extract_inserts(sql, "Wordpress5195_wp_posts"):
        if len(row) < 23:
            continue
        kind = row[20]
        status = row[7]
        record = {
            "id": int(row[0]),
            "date": row[2],
            "content": row[4] or "",
            "title": plain_text(row[5] or "") or "Sin título",
            "excerpt": plain_text(row[6] or ""),
            "status": status,
            "slug": row[11] or "",
            "parent": int(row[17] or 0),
            "guid": row[18] or "",
            "modified": row[14] or row[2],
            "menu_order": int(row[19] or 0),
            "type": kind,
            "mime": row[21] or "",
        }
        if kind == "attachment":
            rel = meta[record["id"]].get("_wp_attached_file")
            src = resolve_media(rel) if rel else local_upload(urlparse(record["guid"]).path)
            record["src"] = src
            record["alt"] = meta[record["id"]].get("_wp_attachment_image_alt") or record["title"]
            attachments[record["id"]] = record
            continue
        if kind in {"post", "page"} and status == "publish":
            record["thumbnail_id"] = meta[record["id"]].get("_thumbnail_id")
            posts.append(record)

    used = set(RESERVED)
    slug_by_id = {}
    id_by_slug = {}
    for record in sorted(posts, key=lambda item: (item["type"] != "page", item["id"])):
        base = unquote((record["slug"] or f"entrada-{record['id']}").strip().strip("/"))
        slug = base
        if slug in used:
            slug = f"{base}-{record['id']}"
        used.add(slug)
        record["slug"] = slug
        slug_by_id[record["id"]] = slug
        id_by_slug[slug] = record["id"]

    categories = {}
    for item in taxonomy.values():
        if item["taxonomy"] == "category" and item["slug"]:
            categories[item["slug"]] = item["name"]
    category_by_tax = {
        item["id"]: item["slug"]
        for item in taxonomy.values()
        if item["taxonomy"] == "category"
    }

    gallery_ids = defaultdict(list)
    for attachment in attachments.values():
        if attachment["parent"] and (attachment["mime"] or "").startswith("image") and attachment.get("src"):
            gallery_ids[attachment["parent"]].append(attachment["id"])
    for ids in gallery_ids.values():
        ids.sort()

    comments = []
    for row in extract_inserts(sql, "Wordpress5195_wp_comments"):
        if len(row) < 15:
            continue
        item = {
            "id": int(row[0]),
            "post_id": int(row[1]),
            "author": plain_text(row[2] or "") or "Anónimo",
            "date": row[6],
            "content": row[8] or "",
            "approved": str(row[10]),
            "type": row[12] or "",
            "parent": int(row[13] or 0),
        }
        if comment_is_public(item):
            comments.append(item)

    ctx = {
        "slug_by_id": slug_by_id,
        "id_by_slug": id_by_slug,
        "categories": categories,
        "category_by_tax": category_by_tax,
        "attachments": attachments,
        "gallery_ids": gallery_ids,
        "taxonomy": taxonomy,
        "relations": relations,
    }
    for record in posts:
        cats = []
        tags = []
        seen = set()
        for tax_id in relations.get(record["id"], []):
            item = taxonomy.get(tax_id)
            if not item or item["slug"] in seen:
                continue
            seen.add(item["slug"])
            if item["taxonomy"] == "category":
                cats.append(item)
            elif item["taxonomy"] == "post_tag":
                tags.append(item)
        record["categories"] = cats
        record["tags"] = tags
        record["html"] = clean_html(record["content"], record, ctx)
        record["text"] = plain_text(record["html"])
        record["summary"] = record["excerpt"] or excerpt(record["text"])
        words = len(record["text"].split())
        record["minutes"] = max(1, round(words / 220)) if words else 1
        thumb = record.get("thumbnail_id")
        image = None
        if thumb and str(thumb).isdigit():
            image = attachments.get(int(thumb), {}).get("src")
        if not image:
            match = re.search(r'src="(/media/[^"]+)"', record["html"])
            image = match.group(1) if match else None
        record["image"] = image

    comments_by_post = defaultdict(list)
    for item in comments:
        comments_by_post[item["post_id"]].append(item)
    for bucket in comments_by_post.values():
        bucket.sort(key=lambda item: item["date"])

    return {
        "posts": [item for item in posts if item["type"] == "post"],
        "pages": [item for item in posts if item["type"] == "page"],
        "comments": comments_by_post,
        "categories": categories,
    }


def header(current: str) -> str:
    labels = {
        "sobre-mi": "Sobre mí",
        "mis-aplicaciones": "Aplicaciones",
        "contactar": "Contacto",
    }
    pages = [("/", "Archivo", "home")]
    for page in NAV_PAGES:
        pages.append((f"/{page['slug']}/", labels.get(page["slug"], page["title"]), page["slug"]))
    pages.append(("/temas/", "Temas", "temas"))
    links = []
    for href, label, key in pages:
        current_attr = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="{href}"{current_attr}>{label}</a>')
    return (
        '<header class="mast"><div class="mast-inner">'
        '<a class="brand" href="/"><span class="monogram">EE</span><span>Esteban Etayo</span></a>'
        f'<nav class="nav" aria-label="Secciones">{"".join(links)}</nav>'
        '<form class="finder" action="/" method="get" role="search">'
        '<label class="sr-only" for="q">Buscar en el archivo</label>'
        '<input id="q" name="q" type="search" placeholder="Buscar en el archivo" autocomplete="off">'
        "</form></div></header>"
    )


def footer(span: str) -> str:
    return (
        '<footer class="footer"><p>Archivo de estebanetayo.es, recuperado con los textos originales. '
        f"Publicado entre {esc(span)}. Diseño nuevo.</p></footer>"
        '<dialog id="lightbox"><img alt=""></dialog>'
    )


def page_shell(title: str, description: str, body: str, current: str, span: str, image: str | None = None, canonical: str = "/") -> str:
    image_meta = ""
    if image:
        image_meta = f'<meta property="og:image" content="{esc(SITE + image)}">'
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f'<meta name="description" content="{esc(description)}">\n'
        f'<link rel="canonical" href="{esc(SITE + canonical)}">\n'
        '<meta property="og:title" content="' + esc(title) + '">\n'
        f'<meta property="og:description" content="{esc(description)}">\n'
        '<meta property="og:type" content="article">\n'
        f'<meta property="og:url" content="{esc(SITE + canonical)}">\n'
        + image_meta
        + '<meta name="theme-color" content="#f3ecdf">\n'
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,620&family=Outfit:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">\n'
        '<link rel="stylesheet" href="/assets/css/site.css">\n'
        "</head>\n<body>\n"
        '<a class="skip" href="#contenido">Saltar al contenido</a>\n'
        + header(current)
        + body
        + footer(span)
        + '\n<script src="/assets/js/site.js"></script>\n</body>\n</html>\n'
    )


def entry_list(items: list[dict]) -> str:
    grouped = defaultdict(list)
    for item in items:
        grouped[item["date"][:4]].append(item)
    chunks = ['<div class="archive">']
    for year in sorted(grouped, reverse=True):
        chunks.append(f'<h2 class="year" id="y-{year}">{year}</h2>')
        for item in grouped[year]:
            cats = "".join(
                f'<a href="/tema/{esc(cat["slug"])}/">{esc(cat["name"])}</a>'
                for cat in item["categories"]
            )
            search = esc(f"{item['title']} {item['summary']} {' '.join(cat['name'] for cat in item['categories'])}")
            summary = f'<p class="excerpt">{esc(item["summary"])}</p>' if item["summary"] else ""
            catline = f'<p class="cats">{cats}</p>' if cats else ""
            chunks.append(
                f'<article class="entry" data-search="{search}">'
                f'<time datetime="{esc(item["date"][:10])}">{esc(short_date(item["date"]))}</time>'
                "<div>"
                f'<h2><a href="/{esc(item["slug"])}/">{esc(item["title"])}</a></h2>'
                f"{summary}{catline}"
                "</div></article>"
            )
    chunks.append("</div>")
    return "".join(chunks)


def render_comments(items: list[dict]) -> str:
    if not items:
        return ""
    by_id = {item["id"]: item for item in items}
    children = defaultdict(list)
    roots = []
    for item in items:
        if item["parent"] in by_id:
            children[item["parent"]].append(item)
        else:
            roots.append(item)

    def block(item: dict, depth: int) -> str:
        klass = "comment child" if depth else "comment"
        html_block = (
            f'<article class="{klass}">'
            f'<p class="who"><b>{esc(item["author"])}</b> · {esc(long_date(item["date"]))}</p>'
            f"{render_comment_body(item['content'])}</article>"
        )
        return html_block + "".join(block(child, depth + 1) for child in children[item["id"]])

    inner = "".join(block(item, 0) for item in roots)
    label = "Comentario" if len(items) == 1 else "Comentarios"
    return f'<section class="comments"><h2>{label}</h2>{inner}</section>'


def write(path: Path, content: str, written: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    written.append(str(path.relative_to(ROOT)))


def clean_previous() -> None:
    if not MANIFEST.exists():
        return
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith(("/", ".")) or ".." in Path(line).parts:
            continue
        target = ROOT / line
        if target.name == "index.html" and target.parent != ROOT:
            shutil.rmtree(target.parent, ignore_errors=True)
        elif target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)


def main() -> None:
    model = load_model()
    posts = sorted(model["posts"], key=lambda item: item["date"], reverse=True)
    pages = sorted(model["pages"], key=lambda item: (item["menu_order"], item["date"]))
    NAV_PAGES.clear()
    NAV_PAGES.extend(pages)
    chronological = sorted(model["posts"], key=lambda item: (item["date"], item["id"]))
    index_by_id = {item["id"]: position for position, item in enumerate(chronological)}
    first = min(item["date"] for item in posts)
    last = max(item["date"] for item in posts)
    span = f"{long_date(first)} y {long_date(last)}"
    description = (
        "Blog sobre las tecnologías de la información, investigación, "
        "desarrollo de proyectos personales, emprendimiento, etc."
    )

    clean_previous()
    written: list[str] = []

    year_links = sorted({item["date"][:4] for item in posts}, reverse=True)
    years_nav = "".join(f'<a href="#y-{year}">{year}</a>' for year in year_links)
    home = (
        '<main id="contenido" class="wrap">'
        '<section class="hero">'
        f'<p class="kicker">Archivo · {first[:4]} — {last[:4]}</p>'
        "<h1>Esteban Etayo</h1>"
        f'<p class="lede">{esc(description)}</p>'
        f'<p class="hero-note">{len(posts)} entradas con los textos originales, recuperadas del blog.</p>'
        f'<nav class="years" aria-label="Años">{years_nav}</nav>'
        '<p class="result-count" aria-live="polite"></p>'
        "</section>"
        '<p class="empty" hidden>Ninguna entrada coincide con la búsqueda.</p>'
        + entry_list(posts)
        + "</main>"
    )
    write(
        ROOT / "index.html",
        page_shell("Esteban Etayo", description, home, "home", span, canonical="/"),
        written,
    )

    about = next((item for item in pages if item["slug"] == "sobre-mi"), None)
    for page in pages:
        body = (
            '<main id="contenido" class="wrap">'
            '<article>'
            '<header class="post-head">'
            f'<p class="kicker">Página</p><h1>{esc(page["title"])}</h1>'
            f'<p class="byline">Última edición: {esc(long_date(page["modified"] or page["date"]))}</p>'
            "</header>"
            f'<div class="prose">{page["html"]}</div>'
            "</article></main>"
        )
        current = "sobre-mi" if page["slug"] == "sobre-mi" else ""
        write(
            ROOT / page["slug"] / "index.html",
            page_shell(
                f'{page["title"]} · Esteban Etayo',
                excerpt(page["text"] or description, 160),
                body,
                current,
                span,
                page["image"],
                f'/{page["slug"]}/',
            ),
            written,
        )

    category_posts = defaultdict(list)
    for item in posts:
        for cat in item["categories"]:
            category_posts[cat["slug"]].append(item)

    topic_items = []
    for slug, name in model["categories"].items():
        count = len(category_posts.get(slug, []))
        if count:
            topic_items.append((count, name, slug))
    topic_items.sort(key=lambda item: (-item[0], item[1].lower()))
    topics_html = "".join(
        f'<li><a href="/tema/{esc(slug)}/">{esc(name)} <span class="count">{count}</span></a></li>'
        for count, name, slug in topic_items
    )
    topics_body = (
        '<main id="contenido" class="wrap">'
        '<p class="kicker">Archivo</p>'
        '<h1 class="page-title">Temas</h1>'
        f'<ul class="topics">{topics_html}</ul>'
        "</main>"
    )
    write(
        ROOT / "temas" / "index.html",
        page_shell("Temas · Esteban Etayo", "Temas del archivo de Esteban Etayo.", topics_body, "temas", span, canonical="/temas/"),
        written,
    )

    for count, name, slug in topic_items:
        items = category_posts[slug]
        body = (
            '<main id="contenido" class="wrap">'
            '<p class="kicker">Tema</p>'
            f'<h1 class="page-title">{esc(name)}</h1>'
            f'<p class="hero-note">{count} entradas.</p>'
            '<p class="result-count" aria-live="polite"></p>'
            '<p class="empty" hidden>Ninguna entrada coincide con la búsqueda.</p>'
            + entry_list(items)
            + "</main>"
        )
        write(
            ROOT / "tema" / slug / "index.html",
            page_shell(f"{name} · Esteban Etayo", f"Entradas sobre {name}.", body, "", span, canonical=f"/tema/{slug}/"),
            written,
        )

    for item in posts:
        position = index_by_id[item["id"]]
        older = chronological[position - 1] if position > 0 else None
        newer = chronological[position + 1] if position + 1 < len(chronological) else None
        nav_bits = []
        if older:
            nav_bits.append(
                f'<a href="/{esc(older["slug"])}/"><span class="label">Anterior</span><strong>{esc(older["title"])}</strong></a>'
            )
        else:
            nav_bits.append("<span></span>")
        if newer:
            nav_bits.append(
                f'<a class="next" href="/{esc(newer["slug"])}/"><span class="label">Siguiente</span><strong>{esc(newer["title"])}</strong></a>'
            )
        cats = "".join(
            f'<a class="cat-link" href="/tema/{esc(cat["slug"])}/">{esc(cat["name"])}</a> '
            for cat in item["categories"]
        )
        tags = ""
        if item["tags"]:
            tags = '<p class="tags">' + " · ".join(esc(tag["name"]) for tag in item["tags"]) + "</p>"
        payload = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": item["title"],
            "datePublished": item["date"].replace(" ", "T"),
            "inLanguage": "es",
            "author": {"@type": "Person", "name": "Esteban Etayo"},
            "url": f'{SITE}/{item["slug"]}/',
        }
        if item["image"]:
            payload["image"] = SITE + item["image"]
        schema = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
        minutes = "1 minuto de lectura" if item["minutes"] == 1 else f'{item["minutes"]} minutos de lectura'
        body = (
            '<main id="contenido" class="wrap"><article>'
            '<header class="post-head">'
            f'<p class="cats">{cats}</p>'
            f'<h1>{esc(item["title"])}</h1>'
            f'<p class="byline">{esc(long_date(item["date"]))} · {minutes}</p>'
            f"{tags}</header>"
            f'<div class="prose">{item["html"]}</div>'
            f'<nav class="post-nav" aria-label="Más entradas">{"".join(nav_bits)}</nav>'
            f'{render_comments(model["comments"].get(item["id"], []))}'
            f'<script type="application/ld+json">{schema}</script>'
            "</article></main>"
        )
        write(
            ROOT / item["slug"] / "index.html",
            page_shell(
                f'{item["title"]} · Esteban Etayo',
                item["summary"] or description,
                body,
                "",
                span,
                item["image"],
                f'/{item["slug"]}/',
            ),
            written,
        )

    not_found = (
        '<main id="contenido" class="wrap">'
        '<p class="kicker">404</p>'
        '<h1 class="page-title">Esta página no está en el archivo</h1>'
        '<p class="lede">El texto que buscas no se recuperó con el blog, o la dirección ha cambiado.</p>'
        '<p><a href="/">Volver al archivo</a></p></main>'
    )
    write(ROOT / "404.html", page_shell("No encontrada · Esteban Etayo", "Página no encontrada.", not_found, "", span, canonical="/404.html"), written)

    urls = ["/", "/temas/", "/404.html"]
    urls.extend(f'/{page["slug"]}/' for page in pages)
    urls.extend(f"/tema/{slug}/" for _, _, slug in topic_items)
    urls.extend(f'/{item["slug"]}/' for item in posts)
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        sitemap.append(f"<url><loc>{esc(SITE + url)}</loc></url>")
    sitemap.append("</urlset>")
    write(ROOT / "sitemap.xml", "\n".join(sitemap) + "\n", written)
    write(
        ROOT / "robots.txt",
        f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n",
        written,
    )
    for asset in ("favicon.svg",):
        target = ROOT / asset
        shutil.copyfile(ASSETS / asset, target)
        written.append(asset)

    MANIFEST.write_text("\n".join(written) + "\n", encoding="utf-8")

    missing = []
    for item in posts + pages:
        for src in re.findall(r'(?:src|href)="(/media/[^"]+)"', item["html"]):
            if not (ROOT / src.lstrip("/")).is_file():
                missing.append(f"{item['slug']} -> {src}")
    print(f"Medios locales ausentes: {len(missing)}")
    for line in missing[:30]:
        print(" ", line)
    print(f"Entradas: {len(posts)}")
    print(f"Páginas: {len(pages)} -> {', '.join(page['title'] + ' /' + page['slug'] for page in pages)}")
    print(f"Temas: {len(topic_items)}")
    print(f"Comentarios publicados: {sum(len(v) for v in model['comments'].values())}")
    print(f"Fechas: {first} -> {last}")
    print("Títulos:")
    for item in reversed(chronological):
        print(f"  {item['date'][:10]}  {item['title']}")


if __name__ == "__main__":
    main()
