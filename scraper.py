"""Fetch video links from a page and build a small, static video catalogue.

The scraper deliberately stores URLs found in the page. It does not guess CDN
URLs from numeric IDs, use a public CORS proxy, or attempt to bypass access
controls. Set TARGET_URL in the environment (or pass --url) before running.

Yeni: AMP ana sayfasından video sayfalarını takip ederek MP4 bağlantılarını çeker.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_URL = "https://1ppa99-evooli-com.cdn.ampproject.org/c/s/1ppa99.evooli.com/amp/"
DEFAULT_USER_AGENT = "CekcekxVideoBot/2.0 (+https://github.com/inadinatv/Cekcekx)"
VIDEO_EXTENSIONS = (".mp4", ".webm", ".m3u8", ".mov", ".m4v", ".ogv", ".ts")
URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
RELATIVE_MEDIA_RE = re.compile(r"(?:^|[\"'\s:=])((?:/|\\./)[^\"'<>\\s]+(?:\.mp4|\.webm|\.m3u8)(?:\?[^\"'<>\\s]*)?)", re.IGNORECASE)


@dataclass(frozen=True)
class Video:
    title: str
    url: str
    poster: str = ""


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": os.getenv("USER_AGENT", DEFAULT_USER_AGENT),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    })
    return session


def fetch_html(url: str, timeout: float = 20, session: requests.Session | None = None) -> str:
    """Download HTML with retries and fail loudly on HTTP errors."""
    client = session or build_session()
    response = client.get(url, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if content_type and "html" not in content_type.lower() and "text" not in content_type.lower():
        logging.warning("%s returned content-type %s", url, content_type)
    return response.text


def _is_video_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = parsed.path.lower()
    return path.endswith(VIDEO_EXTENSIONS) or any(
        marker in path for marker in ("/video/", "/videos/", "/stream/", "/embed/")
    )


def _clean_url(raw: str, page_url: str) -> str | None:
    raw = html.unescape(raw).strip().replace("\\/", "/")
    raw = raw.strip("'\"()[]{}<>,;")
    if raw.startswith(("//", "/")):
        raw = urljoin(page_url, raw)
    # Handle ./ relative
    if raw.startswith("./"):
        raw = urljoin(page_url, raw)
    if _is_video_url(raw):
        return raw
    return None


def _title_for(element, fallback: str) -> str:
    parent = element.find_parent(["article", "li", "figure", "div"])
    if parent:
        heading = parent.find(["h1", "h2", "h3", "h4", "a"])
        if heading:
            text = heading.get_text(" ", strip=True)
            if text:
                return text[:160]
    return fallback


def extract_videos(source: str, page_url: str, max_videos: int = 500) -> list[Video]:
    """Extract real video/source URLs from HTML and embedded JSON/JS."""
    soup = BeautifulSoup(source, "html.parser")
    found: list[Video] = []
    seen: set[str] = set()

    def add(raw: str, title: str = "Video", poster: str = "") -> None:
        url = _clean_url(raw, page_url)
        if url and url not in seen and len(found) < max_videos:
            seen.add(url)
            found.append(Video(title=title.strip()[:160] or "Video", url=url, poster=poster))

    # Include amp-video and amp-iframe for AMP pages
    for tag in soup.find_all(["video", "source", "a", "iframe", "amp-video", "amp-iframe"]):
        candidates = [tag.get(attribute) for attribute in ("src", "href", "data-src", "data-video", "data-url")]
        poster = tag.get("poster", "") or tag.get("data-poster", "")
        for candidate in candidates:
            if candidate:
                add(candidate, _title_for(tag, tag.get("title") or tag.get_text(" ", strip=True) or "Video"), poster)

    # Many sites put the stream URL in JSON-LD or a JavaScript player config.
    scripts = "\n".join(script.get_text(" ", strip=False) for script in soup.find_all("script"))
    # JSON often escapes slashes as https:\/\/...; normalize before scanning.
    scripts = scripts.replace("\\/", "/")
    for raw in URL_RE.findall(scripts):
        add(raw, "Video")
    for match in RELATIVE_MEDIA_RE.findall(scripts):
        add(match, "Video")

    return found


def extract_page_links(source: str, page_url: str, max_links: int = 100) -> list[str]:
    """AMP ana sayfasından video detay sayfalarına giden bağlantıları çıkar.

    - Aynı domain veya evooli / ampproject içeren linkleri toplar
    - Asset uzantılarını (.jpg, .css, .js vb.) atlar
    - Video sayfası olabilecek derin ve slug içeren linklere öncelik verir
    """
    soup = BeautifulSoup(source, "html.parser")
    seen: set[str] = set()
    links: list[str] = []
    parsed_base = urlparse(page_url)
    base_netloc = parsed_base.netloc

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        lower = href.lower()
        # Asset veya doğrudan video dosyası olan linkleri sayfa olarak takip etme
        if any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js", ".ico", ".svg", ".woff", ".woff2", ".mp3")):
            continue
        if any(lower.endswith(ext) for ext in VIDEO_EXTENSIONS):
            continue

        full = urljoin(page_url, href).split("#")[0].strip()
        if not full:
            continue
        parsed = urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue

        # Domain filtresi: aynı host veya evooli / ampproject içerenler
        if parsed.netloc != base_netloc:
            # evooli domainlerini ve amp cache'i kabul et
            if "evooli" not in parsed.netloc and "ampproject" not in parsed.netloc:
                if "evooli" not in full:
                    continue

        # Ana sayfanın kendisi
        if full.rstrip("/") == page_url.rstrip("/"):
            continue

        if full in seen:
            continue

        path = parsed.path.lower()

        # Açıkça içerik olmayan path'leri atla
        if any(seg in path for seg in ("/tag/", "/category/", "/author/", "/page/", "/search", "/login", "/register", "/iletisim", "/hakkimizda", "/gizlilik", "/dmca", "/privacy", "/contact")):
            continue

        # Video sayfası heuristiği
        has_video_keyword = any(kw in path for kw in ("/film", "/dizi", "/bolum", "/episode", "/video", "/izle", "/watch", "/movie", "/fragman"))
        is_deep_amp = False
        if "/amp/" in path:
            after_amp = path.split("/amp/")[-1].strip("/")
            # /amp/ sonrası en az 2 karakter varsa detay sayfasıdır
            if len(after_amp) > 2:
                is_deep_amp = True

        # Genel derinlik ve slug kontrolü
        slug_like = "-" in path and len(path) > 8
        long_path = len(path) > 12

        if not (has_video_keyword or is_deep_amp or slug_like or long_path):
            # Çok kısa veya anlamsız path'leri atla
            if len(path.strip("/").split("/")) <= 1 and len(path) < 10:
                continue

        seen.add(full)
        links.append(full)
        if len(links) >= max_links:
            break

    return links


def crawl_videos(
    start_url: str,
    max_pages: int = 30,
    max_videos: int = 500,
    timeout: float = 20,
    session: requests.Session | None = None,
) -> list[Video]:
    """AMP ana sayfasından başlayarak video sayfalarını takip edip MP4 bağlantılarını toplar."""
    client = session or build_session()
    all_videos: list[Video] = []
    seen_video_urls: set[str] = set()
    seen_pages: set[str] = set()

    def add_batch(videos: list[Video]) -> None:
        for v in videos:
            if v.url not in seen_video_urls and len(all_videos) < max_videos:
                seen_video_urls.add(v.url)
                all_videos.append(v)

    try:
        homepage_html = fetch_html(start_url, timeout=timeout, session=client)
    except Exception as exc:
        logging.warning("Ana sayfa alınamadı %s: %s", start_url, exc)
        return []

    # Ana sayfadaki videolar (varsa)
    add_batch(extract_videos(homepage_html, start_url, max_videos=max_videos))

    # Video detay sayfalarını bul
    page_links = extract_page_links(homepage_html, start_url, max_links=max_pages)
    logging.info("%d video sayfası bulundu, taranıyor...", len(page_links))

    for link in page_links:
        if len(all_videos) >= max_videos:
            break
        if link in seen_pages:
            continue
        seen_pages.add(link)
        try:
            html_source = fetch_html(link, timeout=timeout, session=client)
            vids = extract_videos(html_source, link, max_videos=max_videos - len(all_videos))
            add_batch(vids)
            logging.info("%s -> %d video", link, len(vids))
        except Exception as exc:
            logging.warning("Sayfa atlandı %s: %s", link, exc)
            continue

    return all_videos


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        temporary = Path(tmp.name)
    temporary.replace(path)


def create_m3u_playlist(videos: Iterable[Video], path: Path) -> None:
    lines = ["#EXTM3U"]
    for video in videos:
        lines.extend([f"#EXTINF:-1,{video.title}", video.url])
    _write_atomic(path, "\n".join(lines) + "\n")


def create_html(videos: list[Video], path: Path, source_url: str) -> None:
    data = json.dumps([asdict(video) for video in videos], ensure_ascii=False).replace("</", "<\\/")
    generated = ""
    page = f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Video arşivi</title>
<style>
:root {{ color-scheme:dark; }} * {{ box-sizing:border-box; }} body {{ margin:0; padding:16px; font-family:system-ui,sans-serif; background:#0b1220; color:#e5e7eb; }}
main {{ max-width:900px; margin:auto; }} h1 {{ color:#38bdf8; }} .muted {{ color:#94a3b8; font-size:.85rem; }} video {{ width:100%; max-height:65vh; background:#000; border-radius:12px; }}
#now {{ padding:10px 0; font-weight:700; }} .list {{ display:grid; gap:8px; }} button {{ border:0; border-radius:8px; padding:12px; text-align:left; color:#fff; background:#1e293b; cursor:pointer; }} button:hover,button:focus {{ background:#0369a1; }}
.empty {{ padding:18px; background:#1e293b; border-radius:8px; }}
</style></head>
<body><main><h1>Video arşivi</h1><p class="muted">Kaynak: {html.escape(source_url)}<br>{len(videos)} video bulundu{generated}</p>
<video id="player" controls playsinline preload="metadata"></video><div id="now">Bir video seçin</div><section class="list" id="list"></section></main>
<script>
const videos = {data};
const player = document.querySelector('#player'), now = document.querySelector('#now'), list = document.querySelector('#list');
function selectVideo(video) {{ player.src = video.url; player.poster = video.poster || ''; now.textContent = video.title; player.play().catch(() => {{}}); window.scrollTo({{top:0,behavior:'smooth'}}); }}
if (!videos.length) list.innerHTML = '<div class="empty\">Video bulunamadı. Kaynak sayfa veya filtreleri kontrol edin.</div>';
videos.forEach((video) => {{ const button = document.createElement('button'); button.type='button'; button.textContent=video.title; button.addEventListener('click', () => selectVideo(video)); list.appendChild(button); }});
if (videos.length) selectVideo(videos[0]);
</script></body></html>"""
    _write_atomic(path, page)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AMP ana sayfasından video sayfalarını takip ederek MP4 bağlantılarını HTML ve M3U olarak kaydeder.")
    parser.add_argument("--url", default=os.getenv("TARGET_URL") or DEFAULT_URL, help="Taranacak AMP ana sayfa")
    parser.add_argument("--output", type=Path, default=Path("index.html"), help="HTML çıktı yolu")
    parser.add_argument("--playlist", type=Path, default=Path("playlist.m3u"), help="M3U çıktı yolu")
    parser.add_argument("--max-videos", type=int, default=500, help="Maksimum video sayısı")
    parser.add_argument("--max-pages", type=int, default=30, help="AMP sayfasından takip edilecek maksimum video sayfası")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--no-crawl", action="store_true", help="Sadece verilen URL'den video çıkar, sayfa takibi yapma")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s: %(message)s")
    args = parse_args()
    try:
        if args.no_crawl:
            source = fetch_html(args.url, args.timeout)
            videos = extract_videos(source, args.url, max(1, args.max_videos))
        else:
            videos = crawl_videos(
                args.url,
                max_pages=max(1, args.max_pages),
                max_videos=max(1, args.max_videos),
                timeout=args.timeout,
            )
        create_html(videos, args.output, args.url)
        create_m3u_playlist(videos, args.playlist)
        logging.info("%d video bulundu; %s ve %s yazıldı", len(videos), args.output, args.playlist)
        return 0
    except requests.RequestException as exc:
        logging.error("Sayfa alınamadı: %s", exc)
        return 1
    except OSError as exc:
        logging.error("Çıktı yazılamadı: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
