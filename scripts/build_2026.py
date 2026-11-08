#!/usr/bin/env python3
"""Genera estebanetayo.es (diseño «Cota», 2026) en dist/.

Fuentes:
  content/archivo/entradas.json   80 entradas 2009-2014 (exportadas una vez)
  content/archivo/paginas.json    Sobre mí, Contactar, Mis aplicaciones
  content/proyectos/*.md          un fichero por proyecto (ver _plantilla.md)
  media/, assets/                 se copian tal cual

Uso:
  python3 scripts/build_2026.py                 # sitio de producción en dist/
  python3 scripts/build_2026.py --preview DIR   # copia con enlaces relativos (vista previa)
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import random
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
SITE = "https://estebanetayo.es"
NAME = "Esteban Etayo"
TZ = ZoneInfo("Europe/Madrid")
PLACE = "Fustiñana · Ribera de Navarra"
COORDS = "41°57′N 1°29′W"
BUILD_DATE = date.today()
ASSET_VERSION = BUILD_DATE.strftime("%Y%m%d")

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MONTHS_SHORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
STATES = {
    "activo": "En marcha",
    "pausa": "En pausa",
    "cerrado": "Etapa cerrada",
    "vendido": "Vendido",
}

e = html.escape


def iso(dt: datetime) -> str:
    return dt.replace(tzinfo=TZ).isoformat()


def long_date(d: date) -> str:
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def short_date(d: date) -> str:
    return f"{d.day:02d} {MONTHS_SHORT[d.month - 1]}"


def url_path(path: str) -> str:
    """Ruta pública percent-encoded (para canonical, sitemap y feed)."""
    return quote(path, safe="/-_.~")


def abs_url(path: str) -> str:
    return SITE + url_path(path)


def words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s))


def clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n:
        return s
    cut = s[: n - 1].rsplit(" ", 1)[0].rstrip(",.;:")
    return cut + "…"


# --------------------------------------------------------------------------
# Contenido
# --------------------------------------------------------------------------

def load_archive():
    posts = json.loads((CONTENT / "archivo" / "entradas.json").read_text("utf-8"))
    pages = json.loads((CONTENT / "archivo" / "paginas.json").read_text("utf-8"))
    for p in posts:
        p["dt"] = datetime.fromisoformat(p["date"])
        p["path"] = f"/{p['slug']}/"
        p["text"] = strip_tags(p["html"])
        p["words"] = words(p["text"])
    posts.sort(key=lambda p: p["dt"])
    for i, p in enumerate(posts):
        p["prev"] = posts[i - 1] if i > 0 else None
        p["next"] = posts[i + 1] if i + 1 < len(posts) else None
    for p in pages:
        p["path"] = f"/{p['slug']}/"
    return posts, {p["slug"]: p for p in pages}


def parse_front_matter(text: str):
    if not text.startswith("---"):
        return {}, text
    _, fm, body = text.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        meta[key.strip()] = value
    return meta, body.strip()


def inline_md(s: str) -> str:
    s = e(s, quote=False)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*", r"<em>\1</em>", s)
    return s


def markdown(md: str) -> str:
    out, para, items = [], [], []

    def flush():
        if para:
            out.append(f"<p>{inline_md(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline_md(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in md.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("#"):
            flush()
            level = min(len(s) - len(s.lstrip("#")), 4)
            out.append(f"<h{level}>{inline_md(s.lstrip('#').strip())}</h{level}>")
        elif s.startswith(("- ", "* ")):
            if para:
                flush()
            items.append(s[2:])
        else:
            if items:
                flush()
            para.append(s)
    flush()
    return "\n".join(out)


def load_projects(posts_by_slug):
    projects = []
    for f in sorted((CONTENT / "proyectos").glob("*.md")):
        if f.name.startswith("_"):
            continue
        meta, body = parse_front_matter(f.read_text("utf-8"))
        for req in ("nombre", "resumen", "estado"):
            if not meta.get(req):
                raise SystemExit(f"{f.name}: falta el campo obligatorio «{req}»")
        if meta["estado"] not in STATES:
            raise SystemExit(f"{f.name}: estado «{meta['estado']}» no válido ({', '.join(STATES)})")
        slug = meta.get("slug") or f.stem
        related = [s.strip() for s in meta.get("posts", "").split(",") if s.strip()]
        missing = [s for s in related if s not in posts_by_slug]
        if missing:
            raise SystemExit(f"{f.name}: no existen estas entradas: {', '.join(missing)}")
        # Separa la lista de hitos del cuerpo para maquetarla aparte.
        milestones = []
        m = re.search(r"^##\s*Hitos\s*$(.*?)(?=^##\s|\Z)", body, flags=re.M | re.S)
        if m:
            for line in m.group(1).strip().splitlines():
                line = line.strip()[2:].strip() if line.strip().startswith(("- ", "* ")) else ""
                if "·" in line:
                    when, what = line.split("·", 1)
                    milestones.append((when.strip(), what.strip()))
            body = body[: m.start()] + body[m.end():]
        yes = lambda k: meta.get(k, "").lower() in {"sí", "si", "true", "yes", "1"}
        projects.append({
            "slug": slug,
            "path": f"/proyectos/{slug}/",
            "name": meta["nombre"],
            "summary": meta["resumen"],
            "state": meta["estado"],
            "start": meta.get("inicio", ""),
            "end": meta.get("fin", ""),
            "url": meta.get("url", ""),
            "sector": meta.get("sector", ""),
            "role": meta.get("rol", ""),
            "featured": yes("destacado"),
            "draft": yes("provisional"),
            "order": int(meta.get("orden", "50") or 50),
            "posts": [posts_by_slug[s] for s in related],
            "body": markdown(body),
            "milestones": milestones,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc),
        })
    active = lambda p: p["state"] in ("activo", "pausa")
    projects.sort(key=lambda p: (not active(p), p["order"], p["name"]))
    for p in projects:
        for post in p["posts"]:
            post.setdefault("projects", []).append(p)
    return projects


def years_label(p) -> str:
    if p["start"] and p["end"]:
        return f"{p['start']}–{p['end']}"
    if p["start"]:
        return f"{p['start']}–hoy" if p["state"] in ("activo", "pausa") else p["start"]
    return "en curso"


def domain(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


# --------------------------------------------------------------------------
# Firma visual: curvas de nivel
# --------------------------------------------------------------------------

def contour_svg(seed: int = 7, width: int = 720, height: int = 720, peaks=None, levels: int = 15,
                cls: str = "topo") -> str:
    rnd = random.Random(seed)
    peaks = peaks or [(0.62, 0.42, 1.0), (0.18, 0.86, 0.55)]
    paths = []
    for cx, cy, size in peaks:
        harmonics = [(k, rnd.uniform(0.04, 0.12) / k ** 0.6, rnd.uniform(0, math.tau)) for k in range(2, 7)]
        n = int(levels * size)
        for lvl in range(1, n + 1):
            base = lvl / n * size * width * 0.62
            drift = rnd.uniform(-0.015, 0.015)
            pts = []
            steps = 72
            for i in range(steps):
                t = i / steps * math.tau
                r = base * (1 + sum(a * math.sin(k * t + ph + lvl * 0.09) for k, a, ph in harmonics))
                x = cx * width + r * math.cos(t) * 1.08 + drift * width * lvl * 0.4
                y = cy * height + r * math.sin(t) * 0.86
                pts.append((x, y))
            d = catmull_rom(pts)
            major = " class=\"major\"" if lvl % 5 == 0 else ""
            paths.append(f'<path{major} d="{d}"/>')
    return (f'<svg class="{cls}" viewBox="0 0 {width} {height}" aria-hidden="true" focusable="false" '
            f'preserveAspectRatio="xMidYMid slice">{"".join(paths)}</svg>')


def catmull_rom(pts) -> str:
    n = len(pts)
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return "".join(d) + "Z"


# --------------------------------------------------------------------------
# Plantilla común
# --------------------------------------------------------------------------

NAV = [("/proyectos/", "Proyectos"), ("/blog/", "Blog"), ("/sobre-mi/", "Sobre mí"), ("/contactar/", "Contacto")]

FONTS = ("https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500"
         "&family=Newsreader:ital,opsz,wght@0,6..72,300..600;1,6..72,300..500&display=swap")

ICON_SEARCH = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/>'
               '<path d="M15.5 15.5 21 21"/></svg>')
ICON_ARROW = '<svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
ICON_OUT = '<svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M8 7h9v9"/></svg>'


def person_ld():
    return {
        "@type": "Person",
        "@id": f"{SITE}/#esteban",
        "name": NAME,
        "url": f"{SITE}/",
        "image": f"{SITE}/media/2010/06/fotoMia.jpg",
        "jobTitle": "Emprendedor digital",
        "homeLocation": {"@type": "Place", "name": "Fustiñana, Navarra, España"},
        "alumniOf": {"@type": "CollegeOrUniversity", "name": "Universidad de Zaragoza"},
        "knowsAbout": ["Comercio electrónico", "Desarrollo de apps móviles", "SEO", "Turismo digital"],
        "sameAs": ["https://github.com/eetayo"],
    }


def website_ld():
    return {"@type": "WebSite", "@id": f"{SITE}/#website", "url": f"{SITE}/", "name": NAME,
            "inLanguage": "es-ES", "publisher": {"@id": f"{SITE}/#esteban"}}


def breadcrumbs_ld(items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": name, "item": abs_url(path)}
        for i, (name, path) in enumerate(items)]}


def breadcrumbs_html(items):
    parts = []
    for i, (name, path) in enumerate(items):
        if i == len(items) - 1:
            parts.append(f'<li aria-current="page">{e(name)}</li>')
        else:
            parts.append(f'<li><a href="{path}">{e(name)}</a></li>')
    return f'<nav class="crumbs" aria-label="Migas de pan"><ol>{"".join(parts)}</ol></nav>'


def layout(*, path, title, description, body, section=None, og_type="website", image=None,
           ld=None, robots=None, canonical=True, body_class="", published=None):
    canon = abs_url(path)
    head = [
        '<!DOCTYPE html>', '<html lang="es">', '<head>', '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{e(title)}</title>',
        f'<meta name="description" content="{e(description)}">',
    ]
    if robots:
        head.append(f'<meta name="robots" content="{robots}">')
    if canonical:
        head.append(f'<link rel="canonical" href="{canon}">')
    head += [
        f'<meta property="og:site_name" content="{NAME}">',
        '<meta property="og:locale" content="es_ES">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:url" content="{canon}">',
        f'<meta property="og:image" content="{SITE}{url_path(image) if image else "/assets/og.png"}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    if published:
        head.append(f'<meta property="article:published_time" content="{published}">')
    head += [
        '<meta name="theme-color" content="#f1eee8" media="(prefers-color-scheme: light)">',
        '<meta name="theme-color" content="#121413" media="(prefers-color-scheme: dark)">',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
        f'<link rel="alternate" type="application/atom+xml" title="{NAME}" href="/feed.xml">',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        f'<link rel="stylesheet" href="{FONTS}">',
        f'<link rel="stylesheet" href="/assets/css/cota.css?v={ASSET_VERSION}">',
        '<script>try{var t=localStorage.getItem("tema");if(t)document.documentElement.dataset.theme=t}catch(_){}</script>',
    ]
    if ld:
        graph = {"@context": "https://schema.org", "@graph": ld}
        head.append('<script type="application/ld+json">'
                    + json.dumps(graph, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    head.append("</head>")
    current = ' aria-current="page"'
    nav = "".join(f'<a href="{href}"{current if section == href else ""}>{label}</a>' for href, label in NAV)
    header = (
        '<a class="skip" href="#contenido">Saltar al contenido</a>'
        '<header class="mast"><div class="mast-inner">'
        f'<a class="brand" href="/" aria-label="{NAME}, inicio"><span class="mark">EE</span>'
        f'<span class="brand-name">{NAME}</span></a>'
        f'<nav class="nav" aria-label="Principal">{nav}</nav>'
        f'<a class="icon-btn" href="/blog/#buscar" aria-label="Buscar en el blog">{ICON_SEARCH}</a>'
        '</div></header>'
    )
    footer = (
        '<footer class="foot"><div class="foot-inner">'
        f'<div class="foot-sign"><span class="mark">EE</span><p><strong>{NAME}</strong><br>'
        'Emprendedor digital. Escribiendo desde 2009.</p></div>'
        '<nav class="foot-nav" aria-label="Pie">'
        '<a href="/proyectos/">Proyectos</a><a href="/blog/">Blog 2009–2014</a><a href="/temas/">Temas</a>'
        '<a href="/sobre-mi/">Sobre mí</a><a href="/contactar/">Contacto</a><a href="/feed.xml">RSS</a></nav>'
        f'<p class="coords mono">{COORDS} · {PLACE}</p>'
        '<button class="theme-toggle mono" type="button" aria-label="Cambiar entre modo claro y oscuro">'
        '<span class="sun">Claro</span> / <span class="moon">Oscuro</span></button>'
        '</div></footer>'
    )
    return "\n".join(head) + f'\n<body class="{body_class}">\n{header}\n<main id="contenido">\n{body}\n</main>\n{footer}\n' \
        f'<script src="/assets/js/cota.js?v={ASSET_VERSION}" defer></script>\n</body>\n</html>\n'


# --------------------------------------------------------------------------
# Piezas
# --------------------------------------------------------------------------

def state_badge(p):
    return f'<span class="state state-{p["state"]}"><i aria-hidden="true"></i>{STATES[p["state"]]}</span>'


def project_row(p, heading="h3"):
    draft = '<span class="draft mono">texto provisional</span>' if p["draft"] else ""
    site = f'<span class="domain mono">{e(domain(p["url"]))}</span>' if p["url"] else ""
    return (
        f'<li class="prow" data-state="{p["state"]}"><a href="{p["path"]}">'
        f'<span class="cota mono">{e(years_label(p))}</span>'
        f'<span class="pmain"><{heading} class="pname">{e(p["name"])}</{heading}>'
        f'<span class="psum">{e(p["summary"])}</span></span>'
        f'<span class="pmeta">{state_badge(p)}<span class="sector mono">{e(p["sector"])}</span>{site}{draft}</span>'
        f'{ICON_ARROW}</a></li>'
    )


def post_row(p, show_year=False):
    d = p["dt"].date()
    stamp = f"{short_date(d)} {d.year}" if show_year else short_date(d)
    return (
        f'<li class="erow" data-id="{e(p["slug"])}"><a href="{p["path"]}">'
        f'<time class="mono" datetime="{d.isoformat()}">{stamp}</time>'
        f'<span class="etitle">{e(p["title"])}</span>'
        f'<span class="etopics mono">{e(", ".join(t["name"] for t in p["topics"]))}</span></a></li>'
    )


def histogram(posts, link=True):
    per_year = Counter(p["dt"].year for p in posts)
    top = max(per_year.values())
    bars = []
    for y in sorted(per_year):
        h = max(8, round(per_year[y] / top * 100))
        inner = (f'<span class="bar" style="--h:{h}%"></span><span class="mono yr">{y}</span>'
                 f'<span class="mono n">{per_year[y]}</span>')
        bars.append(f'<a href="/blog/#y-{y}">{inner}</a>' if link else f"<span>{inner}</span>")
    return f'<div class="histo" aria-label="Entradas por año">{"".join(bars)}</div>'


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------

def page_home(posts, projects):
    live = [p for p in projects if p["state"] in ("activo", "pausa")]
    featured = [p for p in live if p["featured"]] or live[:6]
    picks = [s for s in ("la-ortopedia-online-movernos-com-empieza-rodar", "os-presento-xocolabs",
                         "¿cuanto-vale-tu-idea-como-la-convierto-en-una-startup",
                         "elevator-pitch-o-discurso-del-ascensor")]
    by_slug = {p["slug"]: p for p in posts}
    picks = [by_slug[s] for s in picks if s in by_slug][:4]

    timeline = [("2009", "Empieza este blog", "/hello-world/")]
    for p in sorted([p for p in projects if p["start"]], key=lambda p: p["start"]):
        timeline.append((p["start"], p["name"], p["path"]))
    timeline.append(("Hoy", f"{len(live)} proyectos en marcha", "/proyectos/"))
    tl = "".join(f'<li><a href="{href}"><span class="mono">{e(y)}</span><span>{e(t)}</span></a></li>'
                 for y, t, href in timeline)

    pick_cards = "".join(
        f'<li><a href="{p["path"]}"><span class="mono">{long_date(p["dt"].date())}</span>'
        f'<span class="ptitle">{e(p["title"])}</span><span class="pexc">{e(clip(p["description"], 150))}</span></a></li>'
        for p in picks)

    body = f"""
<section class="hero">
  {contour_svg()}
  <div class="hero-inner">
    <p class="kicker mono">{COORDS} · {PLACE}</p>
    <h1 class="display">Esteban<br>Etayo</h1>
    <p class="claim">Ingeniero y emprendedor. Construyo proyectos digitales desde la Ribera de Navarra y llevo contándolo aquí <em>desde 2009</em>.</p>
    <p class="stats mono"><span>{len(live)} proyectos en marcha</span><span>{len(posts)} entradas en el blog</span><span>2009–{BUILD_DATE.year}</span></p>
    <p class="cta"><a class="btn" href="/proyectos/">Ver proyectos {ICON_ARROW}</a><a class="btn ghost" href="/contactar/">Escríbeme</a></p>
  </div>
</section>

<section class="band" aria-labelledby="h-proyectos">
  <div class="sec-head"><p class="kicker mono">01 · Ahora</p><h2 id="h-proyectos">Proyectos en marcha</h2>
  <a class="more" href="/proyectos/">Todos los proyectos {ICON_ARROW}</a></div>
  <ul class="plist">{''.join(project_row(p) for p in featured)}</ul>
</section>

<section class="band" aria-labelledby="h-camino">
  <div class="sec-head"><p class="kicker mono">02 · Camino</p><h2 id="h-camino">De las apps a la tienda online, y de ahí a hoy</h2></div>
  <ol class="timeline">{tl}</ol>
</section>

<section class="band strata-band" aria-labelledby="h-blog">
  <div class="sec-head"><p class="kicker mono">03 · Cuaderno 2009–2014</p><h2 id="h-blog">Del blog</h2>
  <a class="more" href="/blog/">Las {len(posts)} entradas {ICON_ARROW}</a></div>
  <p class="sec-lede">Lo que escribí mientras aprendía a hacer apps, daba charlas y montaba mis primeros negocios. Se conserva tal cual, con sus direcciones de siempre.</p>
  {histogram(posts)}
  <ul class="picks">{pick_cards}</ul>
</section>

<section class="band contact-band" aria-labelledby="h-contacto">
  <h2 id="h-contacto" class="display-s">¿Hablamos de un proyecto?</h2>
  <p><a class="btn" href="/contactar/">Contacto {ICON_ARROW}</a></p>
</section>
"""
    ld = [person_ld(), website_ld(),
          {"@type": "ProfilePage", "@id": f"{SITE}/#webpage", "url": f"{SITE}/", "name": NAME,
           "isPartOf": {"@id": f"{SITE}/#website"}, "mainEntity": {"@id": f"{SITE}/#esteban"}, "inLanguage": "es-ES"}]
    return layout(path="/", title=f"{NAME} · Emprendedor digital en Navarra: proyectos y blog",
                  description=(f"Soy Esteban Etayo, ingeniero y emprendedor en la Ribera de Navarra. "
                               f"Mis proyectos: {', '.join(p['name'] for p in featured[:4])}… y mi blog desde 2009."),
                  body=body, section="/", ld=ld, body_class="home", og_type="profile")


def page_projects(projects):
    counts = Counter("live" if p["state"] in ("activo", "pausa") else "past" for p in projects)
    body = f"""
<section class="page-head with-topo">
  {contour_svg(seed=11, peaks=[(0.85, 0.3, 0.9)], cls="topo topo-s")}
  {breadcrumbs_html([("Inicio", "/"), ("Proyectos", "/proyectos/")])}
  <h1 class="display-m">Proyectos</h1>
  <p class="lede">Negocios y productos digitales que he puesto en marcha, los de ahora y los que ya cerraron etapa. Cada uno con su historia.</p>
  <div class="chips" role="group" aria-label="Filtrar por estado">
    <button type="button" class="chip" data-filter="all" aria-pressed="true">Todos <span class="mono">{len(projects)}</span></button>
    <button type="button" class="chip" data-filter="live" aria-pressed="false">En marcha <span class="mono">{counts['live']}</span></button>
    <button type="button" class="chip" data-filter="past" aria-pressed="false">Etapas cerradas <span class="mono">{counts['past']}</span></button>
  </div>
</section>
<section class="band tight">
  <ul class="plist" id="proyectos">{''.join(project_row(p, "h2") for p in projects)}</ul>
</section>
"""
    ld = [person_ld(), website_ld(),
          {"@type": "CollectionPage", "url": abs_url("/proyectos/"), "name": "Proyectos de Esteban Etayo",
           "isPartOf": {"@id": f"{SITE}/#website"},
           "hasPart": [{"@id": abs_url(p["path"]) + "#proyecto"} for p in projects]},
          breadcrumbs_ld([("Inicio", "/"), ("Proyectos", "/proyectos/")])]
    return layout(path="/proyectos/", title=f"Proyectos · {NAME}",
                  description="Proyectos de emprendimiento de Esteban Etayo: comercio electrónico, turismo, juegos y apps. Los activos y los que cerraron etapa.",
                  body=body, section="/proyectos/", ld=ld)


def page_project(p, projects):
    i = projects.index(p)
    nxt = projects[(i + 1) % len(projects)]
    facts = [("Estado", state_badge(p)), ("Años", e(years_label(p))), ("Sector", e(p["sector"])),
             ("Rol", e(p["role"]))]
    if p["url"]:
        facts.append(("Web", f'<a href="{e(p["url"])}" rel="noopener">{e(domain(p["url"]))}</a>'))
    facts_html = "".join(f"<div><dt class=\"mono\">{k}</dt><dd>{v}</dd></div>" for k, v in facts if v)
    miles = ""
    if p["milestones"]:
        miles = ('<section class="miles"><h2 class="kicker mono">Hitos</h2><ol>'
                 + "".join(f'<li><span class="mono">{e(w)}</span><span>{inline_md(t)}</span></li>'
                           for w, t in p["milestones"]) + "</ol></section>")
    origin = ""
    if p["posts"]:
        origin = ('<section class="origin"><h2 class="kicker mono">Lo conté en el blog</h2><ul class="elist">'
                  + "".join(post_row(x, show_year=True) for x in p["posts"]) + "</ul></section>")
    draft = ('<p class="note mono">Texto provisional: pendiente de la descripción definitiva.</p>'
             if p["draft"] else "")
    visit = (f'<a class="btn" href="{e(p["url"])}" rel="noopener">Visitar {e(domain(p["url"]))} {ICON_OUT}</a>'
             if p["url"] else "")
    crumbs = [("Inicio", "/"), ("Proyectos", "/proyectos/"), (p["name"], p["path"])]
    body = f"""
<article class="project">
  <header class="page-head with-topo">
    {contour_svg(seed=sum(map(ord, p['slug'])), peaks=[(0.82, 0.35, 0.8)], cls="topo topo-s")}
    {breadcrumbs_html(crumbs)}
    <p class="kicker mono">{e(years_label(p))} · {e(p['sector'])}</p>
    <h1 class="display-m">{e(p['name'])}</h1>
    <p class="lede">{e(p['summary'])}</p>
    <p class="cta">{visit}</p>
  </header>
  <div class="project-grid">
    <dl class="facts">{facts_html}</dl>
    <div class="prose">{draft}{p['body']}</div>
  </div>
  {miles}
  {origin}
  <nav class="next-project" aria-label="Siguiente proyecto"><a href="{nxt['path']}"><span class="kicker mono">Siguiente proyecto</span><strong>{e(nxt['name'])}</strong>{ICON_ARROW}</a></nav>
</article>
"""
    entity = {"@type": "Organization" if p["url"] else "CreativeWork", "@id": abs_url(p["path"]) + "#proyecto",
              "name": p["name"], "description": p["summary"]}
    if p["url"]:
        entity["url"] = p["url"]
        entity["founder"] = {"@id": f"{SITE}/#esteban"}
        if p["start"]:
            entity["foundingDate"] = p["start"]
    else:
        entity["creator"] = {"@id": f"{SITE}/#esteban"}
        if p["start"]:
            entity["dateCreated"] = p["start"]
    ld = [person_ld(), website_ld(), entity,
          {"@type": "WebPage", "url": abs_url(p["path"]), "name": p["name"], "about": {"@id": entity["@id"]},
           "isPartOf": {"@id": f"{SITE}/#website"}},
          breadcrumbs_ld(crumbs)]
    return layout(path=p["path"], title=f"{p['name']}: {clip(p['summary'], 52)} · {NAME}",
                  description=clip(p["summary"] + f" Proyecto de {NAME}, {years_label(p)}.", 158),
                  body=body, section="/proyectos/", ld=ld)


def page_blog(posts, topics):
    by_year = defaultdict(list)
    for p in sorted(posts, key=lambda p: p["dt"], reverse=True):
        by_year[p["dt"].year].append(p)
    strata = "".join(
        f'<section class="stratum" id="y-{y}" style="--s:{i}"><h2 class="yr display-s">{y} '
        f'<span class="mono">{len(items)} entradas</span></h2><ul class="elist">'
        + "".join(post_row(p) for p in items) + "</ul></section>"
        for i, (y, items) in enumerate(sorted(by_year.items(), reverse=True)))
    chips = "".join(f'<a class="chip" href="/tema/{t["slug"]}/">{e(t["name"])} <span class="mono">{t["count"]}</span></a>'
                    for t in topics)
    body = f"""
<section class="page-head">
  {breadcrumbs_html([("Inicio", "/"), ("Blog", "/blog/")])}
  <p class="kicker mono">Cuaderno 2009–2014</p>
  <h1 class="display-m">Blog</h1>
  <p class="lede">{len(posts)} entradas sobre apps Android e iPhone, juegos, cloud, ponencias y mis primeros pasos como emprendedor. Textos originales, sin retocar.</p>
  <form class="finder" role="search" action="/blog/" method="get" id="buscar">
    <label class="mono" for="q">Buscar en el blog</label>
    <div class="finder-row">{ICON_SEARCH}<input id="q" name="q" type="search" autocomplete="off" placeholder="aquadroid, nfc, startup…"></div>
    <p class="result-count mono" aria-live="polite"></p>
  </form>
  {histogram(posts)}
  <div class="chips topics" aria-label="Temas">{chips}</div>
</section>
<p class="empty band tight" hidden>Ninguna entrada coincide con la búsqueda.</p>
<div class="strata">{strata}</div>
"""
    ld = [person_ld(), website_ld(),
          {"@type": "Blog", "@id": f"{SITE}/blog/#blog", "url": abs_url("/blog/"), "name": f"Blog de {NAME} (2009–2014)",
           "author": {"@id": f"{SITE}/#esteban"}, "inLanguage": "es-ES"},
          breadcrumbs_ld([("Inicio", "/"), ("Blog", "/blog/")])]
    return layout(path="/blog/", title=f"Blog 2009–2014: apps, juegos y emprendimiento · {NAME}",
                  description=f"Las {len(posts)} entradas del blog de Esteban Etayo entre 2009 y 2014: desarrollo Android e iOS, juegos móviles, cloud computing, ponencias y emprendimiento.",
                  body=body, section="/blog/", ld=ld)


def historic_note(d: date, kind="entrada"):
    age = BUILD_DATE.year - d.year
    return (f'<aside class="historic mono" role="note"><span class="dot" aria-hidden="true"></span>'
            f'Archivo · {kind} escrita en {d.year}, hace {age} años. Se conserva el texto original.</aside>')


def comments_html(p):
    cs = p.get("comments") or []
    if not cs:
        return ""
    items = "".join(
        f'<li class="comment{" reply" if c.get("reply") else ""}"><p class="who mono"><b>{e(c["author"])}</b> · {e(c["date"])}</p>'
        f'{c["html"]}</li>' for c in cs)
    label = "1 comentario" if len(cs) == 1 else f"{len(cs)} comentarios"
    return (f'<section class="comments"><details><summary><span class="kicker mono">Conversación de la época</span>'
            f'<strong>{label}</strong><span class="mono">cerrados</span></summary><ol>{items}</ol></details></section>')


def page_post(p):
    d = p["dt"].date()
    topic = p["topics"][0] if p["topics"] else None
    crumbs = [("Inicio", "/"), ("Blog", "/blog/")]
    if topic:
        crumbs.append((topic["name"], f"/tema/{topic['slug']}/"))
    crumbs.append((clip(p["title"], 40), p["path"]))
    cats = "".join(f'<a class="tag" href="/tema/{t["slug"]}/">{e(t["name"])}</a>' for t in p["topics"])
    callout = ""
    for proj in p.get("projects", []):
        callout += (f'<aside class="callout"><span class="kicker mono">Esta entrada es parte de un proyecto</span>'
                    f'<a href="{proj["path"]}"><strong>{e(proj["name"])}</strong> · {e(proj["summary"])} {ICON_ARROW}</a></aside>')
    minutes = max(1, round(p["words"] / 220))
    nav = []
    if p["prev"]:
        nav.append(f'<a class="prev" href="{p["prev"]["path"]}"><span class="kicker mono">Anterior</span><strong>{e(p["prev"]["title"])}</strong></a>')
    if p["next"]:
        nav.append(f'<a class="next" href="{p["next"]["path"]}"><span class="kicker mono">Siguiente</span><strong>{e(p["next"]["title"])}</strong></a>')
    tags = f'<p class="tags mono">Etiquetas: {e(", ".join(p["tags"]))}</p>' if p["tags"] else ""
    body = f"""
<article class="post">
  <header class="post-head">
    {breadcrumbs_html(crumbs)}
    <p class="post-meta mono"><time datetime="{iso(p['dt'])}">{long_date(d)}</time> · {minutes} min de lectura</p>
    <h1 class="display-m">{e(p['title'])}</h1>
    <p class="cats">{cats}</p>
  </header>
  {historic_note(d)}
  {callout}
  <div class="prose">{p['html']}</div>
  {tags}
  {comments_html(p)}
  <nav class="post-nav" aria-label="Más entradas">{''.join(nav)}</nav>
</article>
"""
    desc = p["description"] or clip(p["text"], 155)
    image = p["image"] or None
    posting = {
        "@type": "BlogPosting", "@id": abs_url(p["path"]) + "#entrada", "headline": p["title"][:110],
        "description": desc, "datePublished": iso(p["dt"]), "dateModified": iso(p["dt"]),
        "inLanguage": "es-ES", "url": abs_url(p["path"]), "mainEntityOfPage": abs_url(p["path"]),
        "author": {"@id": f"{SITE}/#esteban"}, "publisher": {"@id": f"{SITE}/#esteban"},
        "isPartOf": {"@id": f"{SITE}/blog/#blog"}, "wordCount": p["words"],
        "keywords": [t["name"] for t in p["topics"]] + p["tags"],
    }
    if image:
        posting["image"] = abs_url(image)
    if p.get("comments"):
        posting["commentCount"] = len(p["comments"])
    ld = [person_ld(), website_ld(), posting, breadcrumbs_ld(crumbs)]
    seo_title = clip(p["title"].replace("->", "").replace("<-", ""), 58)
    return layout(path=p["path"], title=f"{seo_title} · {NAME}", description=desc, body=body,
                  section="/blog/", og_type="article", image=image, ld=ld, published=iso(p["dt"]),
                  body_class="is-post")


def page_static(pg, projects):
    extra, intro, crumbs = "", "", [("Inicio", "/"), (pg["title"], pg["path"])]
    if pg["slug"] == "sobre-mi":
        live = [p for p in projects if p["state"] in ("activo", "pausa")]
        intro = f"""
<section class="today">
  <p class="kicker mono">Hoy · {BUILD_DATE.year}</p>
  <p class="lede">Ingeniero informático por la Universidad de Zaragoza y emprendedor digital desde la Ribera de Navarra. Ahora mismo llevo {len(live)} proyectos en marcha.</p>
  <ul class="plist compact">{''.join(project_row(p) for p in live[:6])}</ul>
  <p class="note mono">Debajo, el texto de «Sobre mí» tal como lo dejé en 2013.</p>
</section>"""
    if pg["slug"] == "mis-aplicaciones":
        intro = ('<aside class="callout"><span class="kicker mono">Hoy</span><a href="/proyectos/xocolabs/">'
                 f'<strong>Xocolabs</strong> · La historia de estas apps, ahora como proyecto {ICON_ARROW}</a></aside>')
    m = re.search(r"(\d{4})$", pg.get("modified_label", ""))
    year = int(m.group(1)) if m else 2013
    body = f"""
<article class="post page-{pg['slug']}">
  <header class="post-head">
    {breadcrumbs_html(crumbs)}
    <h1 class="display-m">{e(pg['title'].replace('Sobre Mi', 'Sobre mí'))}</h1>
  </header>
  {intro}
  {historic_note(date(year, 1, 1), 'página').replace('escrita en', 'editada por última vez en')}
  <div class="prose">{pg['html']}</div>
  <p class="tags mono">Última edición: {e(pg.get('modified_label', ''))}</p>
</article>
"""
    titles = {
        "sobre-mi": (f"Sobre mí · {NAME}", f"Quién es Esteban Etayo: ingeniero informático y emprendedor digital en Fustiñana, Navarra. Proyectos actuales y trayectoria desde 2009."),
        "contactar": (f"Contacto · {NAME}", "Cómo contactar con Esteban Etayo para hablar de proyectos, colaboraciones o cualquier idea."),
        "mis-aplicaciones": (f"Mis aplicaciones Android e iOS (2010–2013) · {NAME}", "Las apps y juegos móviles que publiqué entre 2010 y 2013: Logic Labyrinth, Aquadroid, ChristmasRun y más."),
    }
    title, desc = titles.get(pg["slug"], (f"{pg['title']} · {NAME}", pg["description"]))
    ld = [person_ld(), website_ld(),
          {"@type": "AboutPage" if pg["slug"] == "sobre-mi" else ("ContactPage" if pg["slug"] == "contactar" else "WebPage"),
           "url": abs_url(pg["path"]), "name": title, "isPartOf": {"@id": f"{SITE}/#website"},
           **({"mainEntity": {"@id": f"{SITE}/#esteban"}} if pg["slug"] == "sobre-mi" else {})},
          breadcrumbs_ld(crumbs)]
    section = pg["path"] if pg["path"] in dict(NAV) else None
    return layout(path=pg["path"], title=title, description=desc, body=body, section=section, ld=ld,
                  image=pg.get("image") or None, og_type="profile" if pg["slug"] == "sobre-mi" else "website")


def page_topics(topics):
    items = "".join(f'<li><a href="/tema/{t["slug"]}/"><span class="tname">{e(t["name"])}</span>'
                    f'<span class="mono">{t["count"]} {"entrada" if t["count"] == 1 else "entradas"}</span>{ICON_ARROW}</a></li>'
                    for t in topics)
    crumbs = [("Inicio", "/"), ("Blog", "/blog/"), ("Temas", "/temas/")]
    body = f"""
<section class="page-head">{breadcrumbs_html(crumbs)}<h1 class="display-m">Temas</h1>
<p class="lede">Los {len(topics)} temas del blog entre 2009 y 2014.</p></section>
<section class="band tight"><ul class="topic-list">{items}</ul></section>"""
    return layout(path="/temas/", title=f"Temas del blog 2009–2014 · {NAME}",
                  description="Temas del blog de Esteban Etayo: Android, iPhone, tecnología, juegos, ponencias, cloud computing y más.",
                  body=body, section="/blog/", ld=[person_ld(), website_ld(), breadcrumbs_ld(crumbs)])


TOPIC_INTRO = {
    "android": "Desarrollo de apps y juegos para Android desde 2010: SoundPool, gestión de memoria, menús, NFC, servicios web y la vida en el Android Market.",
    "iphone": "Mis primeros pasos como desarrollador iOS: el curso de Stanford, ChristmasRun y las diferencias entre vender en la App Store y en Android.",
    "juegos": "Los juegos que hice para Android e iOS y lo que aprendí sobre su negocio: Aquadroid, Logic Labyrinth, ChristmasRun.",
    "ponencia": "Charlas y congresos en los que participé o que resumí: FICOD, DevUp, DRT4All, JSWeb y el congreso de geolocalización.",
}


def page_topic(t, posts):
    items = [p for p in posts if any(x["slug"] == t["slug"] for x in p["topics"])]
    items.sort(key=lambda p: p["dt"], reverse=True)
    crumbs = [("Inicio", "/"), ("Blog", "/blog/"), (t["name"], f"/tema/{t['slug']}/")]
    intro = TOPIC_INTRO.get(t["slug"], f"Entradas del blog sobre {t['name']} escritas entre 2009 y 2014.")
    body = f"""
<section class="page-head">{breadcrumbs_html(crumbs)}<p class="kicker mono">Tema · {len(items)} {"entrada" if len(items) == 1 else "entradas"}</p>
<h1 class="display-m">{e(t['name'])}</h1><p class="lede">{e(intro)}</p></section>
<section class="band tight"><ul class="elist">{''.join(post_row(p, show_year=True) for p in items)}</ul>
<p><a class="more" href="/temas/">Todos los temas {ICON_ARROW}</a></p></section>"""
    robots = "noindex,follow" if len(items) < 3 else None
    return layout(path=f"/tema/{t['slug']}/", title=f"{t['name']}: entradas 2009–2014 · {NAME}",
                  description=clip(intro, 158), body=body, section="/blog/", robots=robots,
                  ld=[person_ld(), website_ld(), breadcrumbs_ld(crumbs)])


def page_404(projects):
    body = f"""
<section class="page-head with-topo">
  {contour_svg(seed=404, peaks=[(0.8, 0.4, 0.9)], cls="topo topo-s")}
  <p class="kicker mono">Error 404 · fuera del mapa</p>
  <h1 class="display-m">Esta página no está en el mapa</h1>
  <p class="lede">Puede que la dirección haya cambiado o que el texto no se recuperara del blog antiguo.</p>
  <form class="finder" role="search" action="/blog/" method="get">
    <label class="mono" for="q404">Buscar en el blog</label>
    <div class="finder-row">{ICON_SEARCH}<input id="q404" name="q" type="search" autocomplete="off"></div>
  </form>
  <p class="cta"><a class="btn" href="/">Ir al inicio</a><a class="btn ghost" href="/proyectos/">Proyectos</a><a class="btn ghost" href="/blog/">Blog</a></p>
</section>"""
    return layout(path="/404.html", title=f"Página no encontrada · {NAME}", description="Esta página no existe.",
                  body=body, robots="noindex", canonical=False)


# --------------------------------------------------------------------------
# Ficheros técnicos
# --------------------------------------------------------------------------

def sitemap(posts, projects, pages, topics):
    entries = [("/", BUILD_DATE.isoformat()), ("/proyectos/", BUILD_DATE.isoformat()),
               ("/blog/", BUILD_DATE.isoformat()), ("/temas/", BUILD_DATE.isoformat())]
    entries += [(p["path"], p["mtime"].date().isoformat()) for p in projects]
    entries += [(pg["path"], BUILD_DATE.isoformat()) for pg in pages.values()]
    entries += [(f"/tema/{t['slug']}/", BUILD_DATE.isoformat()) for t in topics if t["count"] >= 3]
    entries += [(p["path"], p["dt"].date().isoformat()) for p in posts if p["words"] >= 25]
    rows = "".join(f"<url><loc>{e(abs_url(path))}</loc><lastmod>{lm}</lastmod></url>\n" for path, lm in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "</urlset>\n")


def feed(posts, projects):
    now = datetime.now(TZ).replace(microsecond=0).isoformat()
    items = []
    for p in projects:
        items.append((p["mtime"].isoformat(), p["name"], p["path"], p["summary"]))
    for p in sorted(posts, key=lambda p: p["dt"], reverse=True)[:30]:
        items.append((iso(p["dt"]), p["title"], p["path"], p["description"]))
    entries = "".join(
        f"<entry><title>{e(t)}</title><link href=\"{abs_url(path)}\"/><id>{abs_url(path)}</id>"
        f"<updated>{u}</updated><summary>{e(s)}</summary></entry>\n" for u, t, path, s in items)
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="es">\n'
            f'<title>{NAME}</title><link href="{SITE}/"/><link rel="self" href="{SITE}/feed.xml"/>'
            f'<id>{SITE}/</id><updated>{now}</updated><author><name>{NAME}</name></author>\n{entries}</feed>\n')


REDIRECTS = """# Direcciones heredadas de WordPress
/feed/                 /feed.xml   301
/feed                  /feed.xml   301
/comments/feed/        /feed.xml   301
/category/:slug/       /tema/:slug/ 301
/category/:slug        /tema/:slug/ 301
/tag/*                 /blog/      301
/page/*                /blog/      301
/wp-content/uploads/*  /media/:splat 301
/archivo/              /blog/      301
"""

ROBOTS = f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n"

FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#191b1a"/>
<path d="M10 46c8-10 18-4 26-12s14-10 18-8" fill="none" stroke="#c23b22" stroke-width="2.5"/>
<text x="32" y="38" text-anchor="middle" font-family="Georgia, serif" font-size="22" fill="#f1eee8">EE</text>
</svg>
"""


# --------------------------------------------------------------------------
# Escritura y vista previa
# --------------------------------------------------------------------------

def write(out: Path, path: str, content: str):
    target = out / path.lstrip("/")
    if path.endswith("/"):
        target = target / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, "utf-8")


def build(out: Path, copy_media=True):
    posts, pages = load_archive()
    by_slug = {p["slug"]: p for p in posts}
    projects = load_projects(by_slug)
    tcount = Counter()
    names = {}
    for p in posts:
        for t in p["topics"]:
            tcount[t["slug"]] += 1
            names[t["slug"]] = t["name"]
    topics = [{"slug": s, "name": names[s], "count": c} for s, c in tcount.most_common()]

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    write(out, "/", page_home(posts, projects))
    write(out, "/proyectos/", page_projects(projects))
    for p in projects:
        write(out, p["path"], page_project(p, projects))
    write(out, "/blog/", page_blog(posts, topics))
    for p in posts:
        write(out, p["path"], page_post(p))
    for pg in pages.values():
        write(out, pg["path"], page_static(pg, projects))
    write(out, "/temas/", page_topics(topics))
    for t in topics:
        write(out, f"/tema/{t['slug']}/", page_topic(t, posts))
    write(out, "/404.html", page_404(projects))
    write(out, "/sitemap.xml", sitemap(posts, projects, pages, topics))
    write(out, "/feed.xml", feed(posts, projects))
    write(out, "/robots.txt", ROBOTS)
    write(out, "/_redirects", REDIRECTS)
    write(out, "/favicon.svg", FAVICON)
    index = [{"u": p["path"], "t": p["title"], "y": p["dt"].year,
              "x": re.sub(r"\s+", " ", " ".join([p["title"], p["text"], " ".join(t["name"] for t in p["topics"]), " ".join(p["tags"])]))}
             for p in posts]
    write(out, "/blog/indice.json", json.dumps(index, ensure_ascii=False))
    shutil.copytree(ROOT / "assets", out / "assets", ignore=shutil.ignore_patterns("site.css", "site.js", ".DS_Store"))
    if copy_media:
        shutil.copytree(ROOT / "media", out / "media", ignore=shutil.ignore_patterns(".DS_Store"))
    print(f"{len(posts)} entradas · {len(pages)} páginas · {len(projects)} proyectos · {len(topics)} temas → {out}")
    return out


def relativize(out: Path, media_base: str):
    """Convierte rutas absolutas en relativas (para vista previa servida en un subdirectorio)."""
    attr = re.compile(r'(href|src)="(/[^"]*)"')
    for f in out.rglob("*.html"):
        rel_dir = f.parent.relative_to(out)
        depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
        up = "../" * depth or "./"

        def fix(m):
            kind, target = m.group(1), m.group(2)
            if target.startswith("//"):
                return m.group(0)
            if media_base and target.startswith("/media/"):
                return f'{kind}="{media_base}{quote(target, safe="/-_.~")}"'
            path, _, frag = target.partition("#")
            path, _, query = path.partition("?")
            if path.endswith("/"):
                path += "index.html"
            new = up + quote(path.lstrip("/"), safe="/-_.~")
            if query and not path.endswith(".html"):
                new += "?" + query
            if frag:
                new += "#" + frag
            return f'{kind}="{new}"'

        text = attr.sub(fix, f.read_text("utf-8"))
        f.write_text(text, "utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--preview", help="genera una copia con enlaces relativos en este directorio")
    ap.add_argument("--media-base", default="", help="servir /media/ desde otro dominio")
    args = ap.parse_args()
    if args.preview:
        out = build(Path(args.preview), copy_media=False)
        relativize(out, args.media_base)
        if not args.media_base:
            # Copia solo las imágenes que usan las páginas.
            used = set()
            for f in out.rglob("*.html"):
                used.update(re.findall(r'(?:src|href)="(?:\.\./|\./)*(media/[^"]+)"', f.read_text("utf-8")))
            from urllib.parse import unquote
            for m in used:
                src = ROOT / unquote(m)
                if src.exists():
                    (out / unquote(m)).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, out / unquote(m))
            print(len(used), "imágenes copiadas a la vista previa")
    else:
        build(Path(args.out))


if __name__ == "__main__":
    main()
