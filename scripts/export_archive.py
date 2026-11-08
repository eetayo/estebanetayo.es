#!/usr/bin/env python3
"""Exporta el archivo 2009-2014 ya generado a content/archivo/*.json.

Se ejecuta una sola vez. Desde entonces el archivo histórico vive en
content/archivo/ y build_2026.py genera el sitio sin necesitar el volcado SQL.
"""
import json, re, sys
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "content" / "archivo"

def text(el):
    return el.get_text(" ", strip=True) if el else ""

def main():
    posts, pages = [], []
    for idx in sorted(ROOT.glob("*/index.html")):
        slug = idx.parent.name
        if slug in {"tema", "temas", "assets", "media", "scripts", "content", "proyectos", "archivo"}:
            continue
        soup = BeautifulSoup(idx.read_text("utf-8"), "html.parser")
        art = soup.select_one("main article")
        if not art:
            continue
        head = art.select_one(".post-head")
        prose = art.select_one(".prose")
        desc = soup.find("meta", attrs={"name": "description"})
        og = soup.find("meta", attrs={"property": "og:image"})
        item = {
            "slug": slug,
            "title": text(head.h1),
            "description": desc["content"] if desc else "",
            "image": og["content"].replace("https://estebanetayo.es", "") if og else "",
            "html": prose.decode_contents() if prose else "",
        }
        ld = art.find("script", type="application/ld+json")
        if ld:
            data = json.loads(ld.string)
            item["date"] = data["datePublished"]
            item["topics"] = [{"name": a.get_text(strip=True), "slug": a["href"].strip("/").split("/")[-1]}
                              for a in head.select(".cats a")]
            tags = head.select_one(".tags")
            item["tags"] = [t.strip() for t in text(tags).split(",") if t.strip()] if tags else []
            item["comments"] = []
            for c in art.select(".comments .comment"):
                who = c.select_one(".who")
                name = text(who.b) if who and who.b else ""
                when = text(who).split("·", 1)[-1].strip() if who else ""
                body = "".join(str(p) for p in c.find_all("p") if p is not who)
                item["comments"].append({"author": name, "date": when, "html": body,
                                         "reply": "child" in (c.get("class") or [])})
            posts.append(item)
        else:
            byline = text(head.select_one(".byline"))
            item["modified_label"] = byline.replace("Última edición:", "").strip()
            pages.append(item)
    posts.sort(key=lambda p: p["date"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "entradas.json").write_text(json.dumps(posts, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "paginas.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1), "utf-8")
    print(len(posts), "entradas,", len(pages), "páginas,", sum(len(p["comments"]) for p in posts), "comentarios")

if __name__ == "__main__":
    main()
