"""Exploración acotada y de solo lectura de aplicaciones autorizadas.

Explora HTML y enlaces GET dentro del mismo origen; no presupone resultados
funcionales ni modifica datos. Para interfaces SPA puede descubrir menos nodos que
un navegador renderizado; Selenium valida de verdad durante la ejecución.
"""
from __future__ import annotations
import re
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
import httpx
from .robot_engine import validate_path

MAX_PAGES = 16
SKIP_SEGMENTS = re.compile(r'(?i)(?:^|[/_-])(logout|log-out|salir|delete|remove|borrar|eliminar|cancel|pagar|checkout|reset|drop|export|download|descargar|transfer|transferir|administrar|admin|edit|editar)(?:$|[/_.-])')


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self.in_title = False
        self.links = []
        self.elements = []
        self.form_count = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'title': self.in_title = True
        if tag == 'a' and attrs.get('href'): self.links.append(attrs['href'])
        if tag == 'form': self.form_count += 1
        if tag in ('input','button','select','textarea','a','h1','h2','label'):
            if attrs.get('type','').lower() in ('hidden','password','file') or attrs.get('disabled') is not None:
                return
            loc = ''
            if attrs.get('id') and re.fullmatch(r'[A-Za-z][\w:-]{0,90}', attrs['id']):
                loc = 'id=' + attrs['id']
            elif attrs.get('name') and re.fullmatch(r'[A-Za-z][\w:-]{0,90}', attrs['name']):
                loc = 'name=' + attrs['name']
            elif tag in ('body','h1','h2'):
                loc = 'css=' + tag
            if loc:
                self.elements.append({'tag':tag, 'selector':loc, 'label':(attrs.get('aria-label') or attrs.get('placeholder') or attrs.get('id') or attrs.get('name') or tag)[:85]})
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title_parts.append(data)


def _safe_path(base_url: str, location: str, current_path: str = '/') -> str|None:
    """Normaliza link en un camino interno sin query/fragment, ni acciones peligrosas."""
    if not location or any(c in location for c in '\\\r\n\t') or location.startswith(('javascript:', 'data:', 'mailto:', 'tel:', '#')):
        return None
    parsed_base = urlsplit(base_url)
    current = urljoin(base_url.rstrip('/')+'/', current_path.lstrip('/'))
    final = urlsplit(urljoin(current, location))
    if (final.scheme, final.netloc) != (parsed_base.scheme, parsed_base.netloc): return None
    if final.query or final.username or final.password: return None
    path = unquote(final.path or '/')
    if (len(path) > 170 or '//' in path or '\\' in path or any(seg in ('.','..') for seg in path.split('/'))
        or SKIP_SEGMENTS.search(path) or path.lower().endswith(('.pdf','.zip','.png','.jpg','.jpeg','.gif','.css','.js','.webp','.svg','.ico','.xml','.json','.csv'))):
        return None
    try: return validate_path(path)
    except ValueError: return None


def _fetch_html(client: httpx.Client, base_url: str, path: str):
    url = urljoin(base_url.rstrip('/')+'/', path.lstrip('/'))
    response = client.get(url, follow_redirects=False)
    if response.status_code in (301,302,303,307,308):
        location = response.headers.get('location','')
        redirect_path = _safe_path(base_url,location,path)
        if redirect_path is None: raise ValueError('Redirección fuera de la aplicación autorizada')
        url = urljoin(base_url.rstrip('/')+'/', redirect_path.lstrip('/'))
        response = client.get(url, follow_redirects=False)
    response.raise_for_status()
    if 'text/html' not in response.headers.get('content-type','').lower():
        raise ValueError('La ruta no entrega HTML; para APIs JSON utiliza las suites del motor estándar')
    # Máximo 1.5MB en memoria; evitar inspección excesiva.
    if len(response.content) > 1_500_000: raise ValueError('Página demasiado grande para analizar')
    parser = PageParser()
    parser.feed(response.text)
    return parser


def inspect_page(base_url: str, page_path: str):
    path = validate_path(page_path)
    with httpx.Client(timeout=8, trust_env=False) as client:
        parser = _fetch_html(client,base_url,path)
    unique = {x['selector']:x for x in parser.elements}
    links = sorted(set(p for l in parser.links if (p := _safe_path(base_url,l,path)) is not None))
    return {'path':path, 'title':' '.join(parser.title_parts).strip()[:100], 'elements':list(unique.values())[:90],
            'links':links[:60], 'forms':parser.form_count,
            'notice':'Los selectores provienen del HTML recibido. Selenium verificará su existencia en el navegador al ejecutarlos.'}


def crawl_site(base_url: str, start_path: str, max_pages: int = 8):
    if not (1 <= max_pages <= MAX_PAGES): raise ValueError(f'El número de páginas debe ser de 1 a {MAX_PAGES}')
    path = validate_path(start_path)
    visited=set(); queued={path}; pending=deque([path]); pages=[]; failures=[]
    with httpx.Client(timeout=8,trust_env=False) as client:
        while pending and len(pages) < max_pages and len(visited) < 40:
            next_path=pending.popleft();queued.discard(next_path)
            if next_path in visited: continue
            visited.add(next_path)
            try:
                parser=_fetch_html(client,base_url,next_path)
                title=' '.join(parser.title_parts).strip()[:100] or next_path
                pages.append({'path':next_path,'title':title,'elements':len(parser.elements),
                              'locators':list({e['selector']:e for e in parser.elements}.values())[:8]})
                for l in parser.links:
                    candidate=_safe_path(base_url,l,next_path)
                    if candidate is not None and candidate not in visited and candidate not in queued:
                        pending.append(candidate);queued.add(candidate)
            except (httpx.HTTPError,ValueError) as exc:
                failures.append({'path':next_path,'error':type(exc).__name__})
    return {'pages':pages,'errors':failures, 'visited':len(visited), 'limit':max_pages,
            'notice':'Exploración limitada de enlaces HTML del mismo origen; no prueba todas las reglas de negocio ni pantallas tras autenticación. No pulsa botones ni envía formularios.'}
