"""Сеть: соединения, повторы, задержки между запросами и обход VPN-туннеля.

Имя модуля `web`, а не `http`: файл `http.py` в каталоге скриптов перекрыл бы стандартный
пакет `http`, из которого `urllib` берёт соединения.

Хосты, до которых трафик через туннель не доходит, перечислены в `direct_hosts`
(`project.toml` или переменная `LIT_DIRECT_HOSTS`). К ним запрос идёт с адреса другого
сетевого интерфейса, полученного от `local_sources()`.
"""
from __future__ import annotations

import functools
import html
import http.client
import http.cookiejar
import os
import re
import socket
import ssl
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DELAYS = {'arxiv.org': 3.0, 'mathnet.ru': 2.0, 'semanticscholar.org': 1.0}  # секунд между запросами
USER_AGENT = 'lit/2.0 (research script)'
# Заполняется configure(): хосты, к которым идём с другого сетевого интерфейса.
DIRECT_HOSTS: list[str] = []


def configure(root: Path, direct_hosts: list[str] | None = None) -> None:
    """Список хостов: аргумент, переменная LIT_DIRECT_HOSTS или project.toml."""
    global DIRECT_HOSTS
    configured = tomllib.loads((root / 'project.toml').read_text(encoding='utf-8')) \
        if (root / 'project.toml').exists() else {}
    from_env = [host.strip() for host in os.environ.get('LIT_DIRECT_HOSTS', '').split(',') if host.strip()]
    DIRECT_HOSTS = direct_hosts if direct_hosts is not None else \
        from_env or configured.get('sources', {}).get('direct_hosts', ['mathnet.ru'])
_jar = http.cookiejar.CookieJar()
_openers: dict = {}
_routes: dict = {}
_last: dict = {}
_tls = None


def tls_context() -> ssl.SSLContext:
    """Системные корневые сертификаты и набор certifi: Windows подгружает корни лениво."""
    global _tls
    if _tls is None:
        _tls = ssl.create_default_context()
        try:
            import certifi
            _tls.load_verify_locations(certifi.where())
        except ImportError:
            pass
    return _tls


def local_sources() -> list[str]:
    """Локальные адреса вне маршрута по умолчанию, то есть вне VPN-туннеля."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))
            default = probe.getsockname()[0]
        found = {item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return []
    return sorted(address for address in found
                  if address != default and not address.startswith(('127.', '169.254.')))


def opener(source: str | None) -> urllib.request.OpenerDirector:
    if source not in _openers:
        bind = {'source_address': (source, 0)} if source else {}

        class Https(urllib.request.HTTPSHandler):
            def https_open(self, request):
                return self.do_open(functools.partial(http.client.HTTPSConnection, **bind), request,
                                    context=tls_context())

        class Http(urllib.request.HTTPHandler):
            def http_open(self, request):
                return self.do_open(functools.partial(http.client.HTTPConnection, **bind), request)

        # Ссылка на PDF в MathNet отдаёт файл только сессии с cookie, выданной при перенаправлении
        _openers[source] = urllib.request.build_opener(Https(), Http(), urllib.request.HTTPCookieProcessor(_jar))
    return _openers[source]


def site_of(url: str) -> str:
    return '.'.join((urllib.parse.urlsplit(url).hostname or '').split('.')[-2:])


def http_get(url: str, tries: int = 4) -> bytes:
    site = site_of(url)
    direct = any(site == host or site.endswith('.' + host) for host in DIRECT_HOSTS)
    routes = [_routes[site]] if site in _routes else (local_sources() + [None] if direct else [None])
    failure = None
    for source in routes:
        for attempt in range(tries):
            time.sleep(max(0.0, _last.get(site, 0.0) + DELAYS.get(site, 0.3) - time.monotonic()))
            try:
                request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
                with opener(source).open(request, timeout=25 if len(routes) > 1 else 90) as response:
                    data = response.read()
                _routes[site] = source
                return data
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == tries:
                    raise
                time.sleep(5 * (attempt + 1))
            except (urllib.error.URLError, OSError) as error:
                failure = error
                break
            finally:
                _last[site] = time.monotonic()
    hint = (' Хост из списка direct_hosts недоступен ни через туннель, ни напрямую: добавьте для него прямое '
            'правило в VPN-клиенте или отключите VPN на время загрузки.') if direct else ''
    raise ConnectionError(f'{site}: нет соединения ({failure}).{hint}')


def squash(text: str | None) -> str:
    return ' '.join((text or '').split())


def html_text(fragment: str) -> str:
    return squash(html.unescape(re.sub(r'<[^>]+>', ' ', fragment)).replace('\xa0', ' '))
