"""Cekcekx video botu — video bağlantılarını, kapak resimlerini ve bilgileri çeker;
HTML kart kataloğu, JSON ve M3U oynatma listesi üretir.

Neden bu hâle getirildi?
-----------------------
Eski sürüm, üçüncü taraf bir pornografik video sitesinin **Google AMP Cache**
kopyasını (`...cdn.ampproject.org/c/s/...`) hedefliyordu ve çalışmıyordu çünkü:

1. Google, 1 Temmuz 2026'da AMP Cache / AMP Viewer üzerinden önbellekli sayfa
   sunumunu tamamen kaldırdı; `/c/s/` proxy adresleri artık içerik vermiyor.
2. Hedef site BTK tipi erişim engelleri nedeniyle alt alan adını sürekli
   değiştirdiği için sabit (hardcoded) URL bir süre sonra ölüyor.
3. Sitenin MP4 bağlantıları HTML içinde bulunmuyor; oynatıcı dosyayı JavaScript
   ile ayrı bir CDN'den çekiyor. "Çalışmayan" kısmı buydu ve bunu aşmanın tek
   yolu sayısal ID'lerden CDN URL'i tahmin etmek / engelleri dolaşmak olurdu —
   bu bot bunu yapmaz ve yapmayacaktır.

Ayrıca o site telifli stüdyo içeriklerini izinsiz yayınlıyor ve "liseli ifşa",
"escort", "omegle" gibi kategoriler barındırıyor ( NCII / rıza dışı içerik riski).
Böyle bir kaynağı tarayıp link+kapak yayınmak telif ihlali ve GitHub'ın Ekim 2025
tarihli Kabul Edilebilir Kullanım Politikası'nın (cinsel müstehcen içerik ve
korsan dağıtımın otomatize edilmesi) ihlali anlamına gelir.

Bu bot artık aynı mimariyi **yasal ve lisanslı** kaynaklarla çalıştırır:
  * ``--source ia``   : archive.org resmî arama + metadata API'si. Public domain /
                        Creative Commons filmleri, kapak resmi + açıklama + süre +
                        lisans bilgisiyle birlikte çeker. API anahtarı gerekmez.
  * ``--source html`` : Yalnızca KENDİ siteniz ya da yazılı olarak izin aldığınız
                        site için. robots.txt'ye uyar, aynı hostla sınırlıdır,
                        istekler arası gecikme uygular.
  * ``--from-json``   : Ağ erişimi olmadan mevcut veriden HTML/JSON/M3U yeniden üretir.

Asla yapmaz: sayısal ID'den CDN URL'i tahmin etmek, CORS proxy kullanmak,
DRM/paywall/erişim engeli aşmak, izinsiz üçüncü taraf site taramak.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.robotparser import RobotFileParser

try:  # requests/bs4 opsiyonel: yoksa stdlib fallback ile çalışmaya devam eder.
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment]


DEFAULT_USER_AGENT = "CekcekxVideoBot/3.0 (+https://github.com/inadinatv/Cekcekx)"
ARCHIVE_SEARCH_API = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_API = "https://archive.org/metadata"
ARCHIVE_DOWNLOAD_BASE = "https://archive.org/download"
ARCHIVE_THUMB_SERVICE = "https://archive.org/services/img"
# archive.org'un resmî arama API'si. Varsayılan sorgu, lisansı açıkça
# "public domain" olarak işaretlenmiş filmleri en çok indirilene göre sıralar.
DEFAULT_IA_QUERY = os.getenv("IA_QUERY") or "mediatype:movies AND licenseurl:*publicdomain*"
DEFAULT_SORT = os.getenv("IA_SORT") or "downloads desc"
# Yayınlanan kataloğu aile-dostu tutmak için başlık/etikette bu kelimeler
# geçen öğeler atlanır (yetişkin içerikli koleksiyonlar dahil). IA_EXCLUDE ile genişletin.
DEFAULT_EXCLUDE = (
    "porn", "porografi", "xxx", "nsfw", "erotic", "erotik", "sikiş", "sikis",
    "amcık", "ifşa", "ifsa", "escort", "onlyfans", "camgirl", "bakire",
    "non-consensual", "revenge porn", "rıza dışı",
)
MAX_ITEMS_PER_PAGE = 200

VIDEO_EXTENSIONS = (".mp4", ".webm", ".m3u8", ".mov", ".m4v", ".ogv", ".ts")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
JUNK_IMAGE_EXTENSIONS = (".ico", ".svg", ".css", ".js", ".woff", ".woff2", ".mp3")
URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
RELATIVE_MEDIA_RE = re.compile(
    r"(?:^|[\"'\s:=])((?:/|\.\./)[^\"'<>\\s]+(?:\.mp4|\.webm|\.m3u8)(?:\?[^\s\"'<>\\]*)?)",
    re.IGNORECASE,
)
TRAILING_PUNCTUATION = ".,;:)]}'\"\\ "
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

BLOCKED_HTML_SEGMENTS = (
    "/tag/", "/category/", "/author/", "/page/", "/search", "/login", "/register",
    "/logout", "/cart", "/checkout", "/iletisim", "/hakkimizda", "/gizlilik",
    "/kullanim", "/dmca", "/privacy", "/terms", "/contact", "/about",
)
CONTENT_SLUG_KEYWORDS = (
    "/film", "/dizi", "/bolum", "/episode", "/video", "/izle", "/watch",
    "/movie", "/fragman", "/trailer", "/clip", "/mediatype", "/details",
)


# --------------------------------------------------------------------------- #
# Veri modeli
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Video:
    """Tek bir video kaydı: bağlantı + kapak + künye bilgisi."""

    title: str
    url: str
    poster: str = ""
    page: str = ""
    description: str = ""
    duration: str = ""
    year: str = ""
    license: str = ""
    source: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data

    @property
    def display_title(self) -> str:
        return self.title.strip() or "Adsız video"


@dataclass
class FetchStats:
    """Kaç istek atıldığını ve hata sayısını tutar (CI logları için yararlı)."""

    requests: int = 0
    errors: int = 0
    skipped_robots: int = 0


# --------------------------------------------------------------------------- #
# HTTP katmanı
# --------------------------------------------------------------------------- #
class Fetcher:
    """Kısa, kibar HTTP istemcisi. requests varsa onu, yoksa stdlib'i kullanır."""

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout: float = 20.0,
        delay: float = 0.35,
        retries: int = 3,
        stats: FetchStats | None = None,
    ) -> None:
        self.timeout = timeout
        self.delay = max(0.0, delay)
        self.retries = max(1, retries)
        self.stats = stats if stats is not None else FetchStats()
        self.user_agent = user_agent or os.getenv("USER_AGENT") or DEFAULT_USER_AGENT
        self._last_request_at = 0.0
        self._session = self._build_session() if requests is not None else None

    def _build_session(self):
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
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr,en;q=0.8",
        })
        return session

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        wait = self.delay - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def get(self, url: str, *, timeout: float | None = None) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"Güvenli olmayan şema: {url!r}")
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            self.stats.requests += 1
            try:
                if self._session is not None:
                    response = self._session.get(url, timeout=timeout or self.timeout)
                    if response.status_code == 404:
                        raise FileNotFoundError(f"404 {url}")
                    response.raise_for_status()
                    return response.text
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept": "*/*"},
                )
                with urllib.request.urlopen(request, timeout=timeout or self.timeout) as raw:
                    charset = raw.headers.get_content_charset() or "utf-8"
                    return raw.read().decode(charset, errors="replace")
            except FileNotFoundError:
                raise
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                self.stats.errors += 1
                if attempt < self.retries:
                    time.sleep(min(8.0, 0.8 * (2 ** (attempt - 1))))
            except Exception as exc:  # noqa: BLE001 - beklenmedik hatayı logla, dene
                last_error = exc
                self.stats.errors += 1
                break
        raise ConnectionError(f"{url} alınamadı: {last_error}") from last_error

    def get_json(self, url: str) -> Any:
        return json.loads(self.get(url))


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #
class Robots:
    """robots.txt okuyucusu. Erişilemezse fail-open (uyarı loglanır)."""

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._cache: dict[str, RobotFileParser | None] = {}

    def _parser(self, url: str) -> RobotFileParser | None:
        parsed = urllib.parse.urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._cache:
            parser: RobotFileParser | None = None
            try:
                text = self.fetcher.get(f"{origin}/robots.txt", timeout=10)
            except Exception as exc:  # noqa: BLE001
                logging.debug("robots.txt yok/okunamadı %s: %s", origin, exc)
            else:
                parser = RobotFileParser()
                parser.parse(text.splitlines())
            self._cache[origin] = parser
        return self._cache[origin]

    def allowed(self, url: str) -> bool:
        parser = self._parser(url)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.fetcher.user_agent, url)
        except Exception:  # noqa: BLE001
            return True


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def format_duration(value: Any) -> str:
    """'5488.27' veya '01:31:28' gibi alanları '1:31:28' biçimine çevirir."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if ":" in text:
        parts = [p for p in text.split(":") if p != ""]
        try:
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + int(float(part))
        except ValueError:
            return text[:16]
    else:
        try:
            seconds = int(float(text))
        except ValueError:
            return text[:16]
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def license_label(licenseurl: Any) -> str:
    """archive.org lisans alanını kısa bir etikete çevirir."""
    if isinstance(licenseurl, (list, tuple)):
        licenseurl = next(iter(licenseurl), "")
    if not licenseurl:
        return "Lisans bilgisi yok"
    url = str(licenseurl).strip()
    lowered = url.lower()
    if "publicdomain/mark" in lowered or "publicdomain" in lowered:
        return "Kamu malı"
    match = re.search(r"licenses/([a-z-]+(?:-[a-z0-9]+)*)/([0-9.]+)", lowered)
    if match and "creativecommons" in lowered:
        return f"CC {match.group(1).upper()} {match.group(2)}".replace("BY-NC-ND", "BY-NC-ND")
    return url[:60]


def normalize_text(value: Any, limit: int = 400) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " · ".join(str(item) for item in value if item)
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit].strip()


def first_year(values: Sequence[str]) -> str:
    for value in values:
        match = re.search(r"(18|19|20)\d{2}", str(value))
        if match:
            return match.group(0)
    return ""


def is_video_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path = parsed.path.lower()
    if path.endswith(JUNK_IMAGE_EXTENSIONS):
        return False
    if path.endswith(IMAGE_EXTENSIONS):
        return False
    if path.endswith(VIDEO_EXTENSIONS):
        return True
    # Token'lı akışlar (.mp4?token=...) ve medya klasönleri
    return any(marker in path for marker in ("/video/", "/videos/", "/stream/", "/download/"))


def absolutize(raw: str, page_url: str) -> str | None:
    """Ham URL'i temizler, göreli yolları çözer, video olmayanı eler."""
    raw = html.unescape(raw).strip().replace("\\/", "/")
    raw = raw.rstrip(TRAILING_PUNCTUATION).strip("'\"()[]{}<>,;")
    if not raw or raw.lower().startswith(("data:", "blob:", "javascript:")):
        return None
    if raw.startswith("//"):
        raw = urllib.parse.urlparse(page_url).scheme + ":" + raw
    elif not _SCHEME_RE.match(raw):
        raw = urllib.parse.urljoin(page_url, raw)
    if not raw.lower().startswith(("http://", "https://")):
        return None
    return raw if is_video_url(raw) else None


def absolutize_image(raw: str, page_url: str) -> str:
    """Kapak/adres görselleri için göreli yolları çözer (video filtresi uygulamaz)."""
    raw = html.unescape(str(raw or "")).strip().replace("\\/", "/")
    raw = raw.rstrip(TRAILING_PUNCTUATION).strip("'\"()[]{}<>,;")
    if not raw or raw.lower().startswith(("data:", "javascript:")):
        return ""
    if raw.startswith("//"):
        raw = urllib.parse.urlparse(page_url).scheme + ":" + raw
    elif not _SCHEME_RE.match(raw):
        raw = urllib.parse.urljoin(page_url, raw)
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


# --------------------------------------------------------------------------- #
# Kaynak 1: archive.org (resmî API, lisanslı içerik)
# --------------------------------------------------------------------------- #
def _video_file_score(entry: dict[str, Any]) -> int:
    """Tarayıcıda oynatmaya en uygun MP4 dosyasını seçmek için puan."""
    name = str(entry.get("name", ""))
    lowered = name.lower()
    if "/" in lowered:  # alt klasördeki dosyalar (örn. .thumbs) genelde değildir
        lowered_name = lowered.split("/")[-1]
    else:
        lowered_name = lowered
    fmt = str(entry.get("format", "")).lower()
    score = 0
    if lowered_name.endswith((".mp4", ".m4v")):
        score += 60
    elif lowered_name.endswith(".webm"):
        score += 40
    elif lowered_name.endswith((".ogv", ".ogg")):
        score += 20
    else:
        return -10_000
    if not entry.get("length"):
        score -= 50
    if "h.264" in fmt or "mpeg4" in fmt:
        score += 25
    if re.search(r"\d+\s*k?b mpeg4|\d+mb mpeg4", fmt):
        score += 15  # bitrate'li türev dosya = akışa hazır
    if entry.get("source") == "derivative":
        score += 8
    try:
        height = int(entry.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    if 360 <= height <= 720:
        score += 12
    elif height > 1080:
        score -= 10
    try:
        size = int(entry.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size > 1_500_000_000:
        score -= 25  # indirmesi/akıtması çok ağır
    return score


def pick_video_file(files: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [f for f in files if isinstance(f, dict)]
    if not candidates:
        return None
    ranked = sorted(candidates, key=_video_file_score, reverse=True)
    best = ranked[0]
    return best if _video_file_score(best) > 0 else None


def pick_poster(files: Iterable[dict[str, Any]], identifier: str, video_name: str = "") -> str:
    """Kapak resmi: videoya ait thumbnail, yoksa IA görsel servisi."""
    thumbs: list[str] = []
    loose: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        lowered = name.lower()
        if not lowered.endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        fmt = str(entry.get("format", "")).lower()
        if "thumbnail" in fmt:
            if video_name and entry.get("original") == video_name:
                thumbs.insert(0, name)
            elif not video_name:
                thumbs.append(name)
        elif "/" not in name:
            base = lowered.rsplit("/", 1)[-1]
            if base.endswith("_thumb.jpg") or base == "thumb.jpg":
                loose.append(name)
    for candidate in thumbs + loose:
        return f"{ARCHIVE_DOWNLOAD_BASE}/{identifier}/{urllib.parse.quote(candidate)}"
    return f"{ARCHIVE_THUMB_SERVICE}/{identifier}"


def build_video_from_item(identifier: str, meta: dict[str, Any], max_files: int = 1) -> list[Video]:
    """archive.org metadata yanıtından Video kayıtları üretir (saf fonksiyon)."""
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    files = [f for f in (meta.get("files") or []) if isinstance(f, dict)]
    videos: list[Video] = []
    ranked = sorted(files, key=_video_file_score, reverse=True)
    for entry in ranked[: max(1, max_files)]:
        if _video_file_score(entry) <= 0:
            continue
        name = str(entry.get("name", ""))
        if not name:
            continue
        title = normalize_text(
            metadata.get("title") or entry.get("title") or identifier, limit=160
        )
        video_name = name
        creator = normalize_text(metadata.get("creator"), limit=120)
        year = first_year([metadata.get("year", ""), metadata.get("date", "")])
        description_parts = [
            normalize_text(metadata.get("description"), limit=900),
            f"Yönetmen/Sanatçı: {creator}" if creator else "",
            f"Koleksiyon: {normalize_text(metadata.get('collection'), limit=120)}"
            if isinstance(metadata.get("collection"), (list, tuple))
            else "",
        ]
        description = "\n".join(part for part in description_parts if part).strip()
        tags = [
            normalize_text(item, limit=40)
            for item in (metadata.get("subject") or [])[:6]
            if isinstance(metadata.get("subject"), (list, tuple))
        ]
        poster = pick_poster(files, identifier, video_name)
        page = f"https://archive.org/details/{identifier}"
        videos.append(
            Video(
                title=title or identifier,
                url=f"{ARCHIVE_DOWNLOAD_BASE}/{identifier}/{urllib.parse.quote(name)}",
                poster=poster,
                page=page,
                description=description,
                duration=format_duration(entry.get("length")),
                year=year,
                license=license_label(metadata.get("licenseurl")),
                source="archive.org",
                tags=tuple(dict.fromkeys(t for t in tags if t)),
            )
        )
    return videos


def exclusion_needles(extra: Sequence[str] = ()) -> tuple[str, ...]:
    """Varsayılan + kullanıcı/env filtreleri (küçük harf, tekilleştirilmiş)."""
    env = tuple(part.strip().lower() for part in os.getenv("IA_EXCLUDE", "").split(",") if part.strip())
    return tuple(dict.fromkeys([*DEFAULT_EXCLUDE, *(n.lower() for n in extra if n), *env]))


def is_excluded(video: Video, needles: Sequence[str]) -> bool:
    """Başlık/açıklama/etiket taraması: yetişkin veya rıza dışı içerik ipuçları."""
    hay = " ".join([video.title, video.description, " ".join(video.tags), video.source]).lower()
    return any(needle and needle in hay for needle in needles)


def ia_search(
    fetcher: Fetcher,
    query: str,
    rows: int,
    page: int = 1,
    sort: str = DEFAULT_SORT,
) -> list[str]:
    """advancedsearch API'den identifier listesi alır."""
    params = {
        "q": query,
        "fl[]": "identifier",
        "sort[]": sort,
        "page": str(page),
        "rows": str(min(max(1, rows), MAX_ITEMS_PER_PAGE)),
        "output": "json",
    }
    url = f"{ARCHIVE_SEARCH_API}?{urllib.parse.urlencode(params, doseq=False)}"
    payload = fetcher.get_json(url)
    docs = (payload.get("response") or {}).get("docs") or []
    identifiers: list[str] = []
    for doc in docs:
        identifier = str(doc.get("identifier", "")).strip()
        if identifier and re.fullmatch(r"[A-Za-z0-9._\-]{2,128}", identifier):
            identifiers.append(identifier)
    return identifiers


def collect_archive_videos(
    fetcher: Fetcher,
    query: str,
    *,
    max_videos: int = 60,
    require_license: bool = False,
    exclude: Sequence[str] = (),
    sort: str = DEFAULT_SORT,
) -> list[Video]:
    """Arama yapar, her öğenin metadata'sından kapak + bilgi + MP4 çeker."""
    rows = min(MAX_ITEMS_PER_PAGE, max(max_videos * 2, 20))
    needles = exclusion_needles(exclude)
    videos: list[Video] = []
    seen: set[str] = set()
    identifiers = ia_search(fetcher, query, rows, sort=sort)
    logging.info("archive.org: %d aday öğe bulundu (%r sorgusu)", len(identifiers), query)
    for identifier in identifiers:
        if len(videos) >= max_videos:
            break
        try:
            meta = fetcher.get_json(f"{ARCHIVE_METADATA_API}/{identifier}")
        except Exception as exc:  # noqa: BLE001
            logging.warning("metadata alınamadı %s: %s", identifier, exc)
            continue
        if require_license and not (meta.get("metadata") or {}).get("licenseurl"):
            logging.info("lisans bilgisi olmadığı için atlandı: %s", identifier)
            continue
        for video in build_video_from_item(identifier, meta):
            if video.url in seen:
                continue
            seen.add(video.url)
            if needles and is_excluded(video, needles):
                logging.info("içerik filtresi nedeniyle atlandı: %s", video.title)
                continue
            videos.append(video)
            if len(videos) >= max_videos:
                break
    return videos


# --------------------------------------------------------------------------- #
# Kaynak 2: HTML tarama (yalnızca kendi / izinli siteniz)
# --------------------------------------------------------------------------- #
def _soup(source: str):
    if BeautifulSoup is None:
        return None
    return BeautifulSoup(source, "html.parser")


def _meta_content(soup, names: Sequence[str]) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def extract_videos(source: str, page_url: str, max_videos: int = 500) -> list[Video]:
    """HTML ve gömülü JSON/JS içindeki gerçek video + kapak bağlantılarını çıkarır."""
    soup = _soup(source)
    found: list[Video] = []
    seen: set[str] = set()
    page_title = ""
    page_poster = ""
    page_description = ""
    if soup is not None:
        heading = soup.find("h1") or soup.find(["h2", "title"])
        page_title = normalize_text(heading.get_text(" ", strip=True) if heading else "", 160)
        page_poster = _meta_content(soup, ("og:image", "twitter:image"))
        page_description = _meta_content(soup, ("og:description", "description"))

    def add(raw: str, title: str = "", poster: str = "") -> None:
        url = absolutize(raw, page_url)
        if not url or url in seen or len(found) >= max_videos:
            return
        seen.add(url)
        clean_title = normalize_text(title, 160) or page_title or "Video"
        cover = absolutize_image(poster or page_poster, page_url)
        found.append(
            Video(
                title=clean_title,
                url=url,
                poster=cover,
                page=page_url,
                description=page_description[:900],
                source=urllib.parse.urlparse(page_url).netloc,
            )
        )

    if soup is not None:
        video_tags = (
            "video", "source", "a", "iframe", "amp-video", "amp-iframe", "embed", "object"
        )
        for tag in soup.find_all(list(video_tags)):
            poster = tag.get("poster") or tag.get("data-poster")
            if not poster and tag.name == "source":
                # <source> genelde kapaksızdır; kapak <video> etiketindedir
                parent = tag.find_parent("video")
                if parent is not None:
                    poster = parent.get("poster") or parent.get("data-poster")
            poster = poster or page_poster
            for attribute in ("src", "href", "data-src", "data-video", "data-url"):
                candidate = tag.get(attribute)
                if not candidate:
                    continue
                title = page_title
                if not title:
                    container = tag.find_parent(["article", "li", "figure", "div"])
                    heading = container.find(["h1", "h2", "h3", "a"]) if container else None
                    title = normalize_text(
                        heading.get_text(" ", strip=True) if heading else "Video", 160
                    )
                add(str(candidate), title, str(poster or ""))
        scripts = "\n".join(script.get_text(" ", strip=False) for script in soup.find_all("script"))
    else:  # bs4 yok: regex tabanlı kabaca çıkarım
        title_match = re.search(
            r"<(?:h1|title)[^>]*>(.*?)</(?:h1|title)>", source, re.IGNORECASE | re.DOTALL
        )
        if title_match:
            page_title = normalize_text(title_match.group(1), 160)
        poster_match = re.search(r"<[^>]*poster\s*=\s*[\"']([^\"']+)[\"']", source, re.IGNORECASE)
        og_match = re.search(
            r"<meta[^>]+(?:property|name)\s*=\s*[\"']og:image[\"'][^>]+content\s*=\s*[\"']([^\"']+)[\"']",
            source,
            re.IGNORECASE,
        )
        page_poster = (poster_match.group(1) if poster_match else "") or (
            og_match.group(1) if og_match else ""
        )
        for match in re.finditer(
            r"(?:src|href|data-src)\s*=\s*[\"']([^\"']+\.(?:mp4|webm|m3u8)[^\"']*)[\"']",
            source,
            re.IGNORECASE,
        ):
            add(match.group(1), page_title or "Video", page_poster)
        scripts = re.sub(r"<script[^>]*>", "\n", source, flags=re.IGNORECASE)
        scripts = re.sub(r"</script>", "\n", scripts, flags=re.IGNORECASE)

    scripts = scripts.replace("\\/", "/")
    for raw in URL_RE.findall(scripts):
        add(raw)
    for match in RELATIVE_MEDIA_RE.findall(scripts):
        add(match)
    return found


def extract_page_links(
    source: str,
    page_url: str,
    *,
    max_links: int = 100,
    same_host_only: bool = True,
    extra_hosts: Sequence[str] = (),
) -> list[str]:
    """İçerik (film/dizi/video) sayfalarına giden bağlantıları listeler.

    Varsayılan olarak yalnızca aynı host'taki bağlantıları izler; ``extra_hosts``
    ile açıkça izin verilmeyen hiçbir alan adı taranmaz.
    """
    soup = _soup(source)
    allowed = {h.lower() for h in extra_hosts}
    base_host = urllib.parse.urlparse(page_url).netloc.lower()
    if not same_host_only:
        allowed.add(base_host)
    seen: set[str] = set()
    links: list[str] = []
    if soup is not None:
        hrefs = [str(tag.get("href", "")) for tag in soup.find_all("a", href=True)]
    else:  # bs4 yoksa regex ile topla
        hrefs = re.findall(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"']", source, re.IGNORECASE)

    for href in hrefs:
        href = href.strip()
        if not href or href.lower().startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        lowered = href.lower()
        if lowered.endswith(VIDEO_EXTENSIONS + IMAGE_EXTENSIONS + JUNK_IMAGE_EXTENSIONS):
            continue
        full = urllib.parse.urljoin(page_url, html.unescape(href)).split("#")[0]
        parsed = urllib.parse.urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = parsed.netloc.lower()
        # Alan adı politikası: her zaman başlangıç host'u + açık beyaz liste.
        # same_host_only=False ve beyaz liste boşsa (bilinçli "--allow-offsite") her host geçer.
        open_offsite = not same_host_only and not allowed
        if not open_offsite and not (
            host == base_host
            or host in allowed
            or any(host.endswith("." + entry) for entry in allowed if entry)
        ):
            continue
        if full.rstrip("/") == page_url.rstrip("/"):
            continue
        path = parsed.path.lower()
        if any(segment in path for segment in BLOCKED_HTML_SEGMENTS):
            continue
        has_keyword = any(keyword in path for keyword in CONTENT_SLUG_KEYWORDS)
        slug_like = "-" in path and len(path) > 8
        amp_detail = "/amp/" in path and len(path.split("/amp/")[-1].strip("/")) > 2
        deep_path = len([part for part in path.split("/") if part]) >= 2
        if not (has_keyword or amp_detail or (slug_like and deep_path)):
            continue
        if full in seen:
            continue
        seen.add(full)
        links.append(full)
        if len(links) >= max_links:
            break
    return links


def crawl_site(
    start_url: str,
    *,
    fetcher: Fetcher,
    max_pages: int = 25,
    max_videos: int = 500,
    same_host_only: bool = True,
) -> list[Video]:
    """Bir siteyi derinlemesine tarar; başlangıç sayfası + içerik sayfaları."""
    robots = Robots(fetcher)
    client = fetcher
    videos: list[Video] = []
    seen_urls: set[str] = set()
    seen_pages: set[str] = set()

    def add_batch(batch: Sequence[Video]) -> None:
        for video in batch:
            if video.url in seen_urls or len(videos) >= max_videos:
                continue
            seen_urls.add(video.url)
            videos.append(video)

    if not robots.allowed(start_url):
        logging.error("robots.txt bu sayfayı taramaya izin vermiyor: %s", start_url)
        return []
    try:
        homepage = client.get(start_url)
    except Exception as exc:  # noqa: BLE001
        logging.error("Başlangıç sayfası alınamadı %s: %s", start_url, exc)
        return []
    add_batch(extract_videos(homepage, start_url, max_videos=max_videos))
    detail_links = extract_page_links(
        homepage, start_url, max_links=max_pages, same_host_only=same_host_only
    )
    logging.info("%d içerik sayfası bulundu, taranıyor...", len(detail_links))
    for link in detail_links:
        if len(videos) >= max_videos or link in seen_pages:
            continue
        seen_pages.add(link)
        if not robots.allowed(link):
            client.stats.skipped_robots += 1
            logging.info("robots.txt nedeniyle atlandı: %s", link)
            continue
        try:
            source = client.get(link)
        except Exception as exc:  # noqa: BLE001
            logging.warning("sayfa atlandı %s: %s", link, exc)
            continue
        add_batch(extract_videos(source, link, max_videos=max_videos - len(videos)))
    return videos


# --------------------------------------------------------------------------- #
# Üreticiler
# --------------------------------------------------------------------------- #
def _write_atomic(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        temporary = Path(tmp.name)
    temporary.replace(path)


def create_json(videos: Sequence[Video], path: Path) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(videos),
        "videos": [video.to_dict() for video in videos],
    }
    _write_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def create_m3u_playlist(videos: Sequence[Video], path: Path) -> None:
    """VLC/TiviMax uyumlu, kapak logolu ve gruplu oynatma listesi."""
    lines = ['#EXTM3U version="1"']
    for video in videos:
        attributes = ['tvg-id=""']
        group = html.escape(video.source or "Arşiv", quote=True)
        attributes.append(f'group-title="{group}"')
        if video.poster:
            attributes.append(f'tvg-logo="{html.escape(video.poster, quote=True)}"')
        if video.duration:
            attributes.append(f'tvg-duration="{video.duration}"')
        title = html.escape(video.display_title, quote=False)
        lines.append(f"#EXTINF:-1 {' '.join(attributes)},{title}")
        lines.append(video.url)
    _write_atomic(path, "\n".join(lines) + "\n")


PAGE_TEMPLATE = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>__TITLE__</title>
<style>
:root{--bg:#0b1220;--panel:#151f33;--line:#233246;--fg:#e5e7eb;--muted:#94a3b8;--accent:#38bdf8}
*{box-sizing:border-box}
body{margin:0;padding:20px;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{max-width:1240px;margin:0 auto 18px}
h1{margin:0 0 6px;font-size:1.5rem;color:var(--accent)}
.muted{color:var(--muted);font-size:.86rem;line-height:1.5;margin:0}
.toolbar{max-width:1240px;margin:0 auto 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.toolbar input{flex:1 1 220px;min-width:200px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;color:var(--fg);font-size:.92rem}
.toolbar span.count{color:var(--muted);font-size:.85rem}
#player-wrap{max-width:1240px;margin:0 auto 18px;display:none;background:#000;border-radius:14px;overflow:hidden;border:1px solid var(--line)}
#player-wrap.on{display:block}
video{display:block;width:100%;max-height:62vh;background:#000}
#now{padding:10px 14px;display:flex;gap:12px;justify-content:space-between;align-items:center;font-weight:600;background:var(--panel)}
#now a{color:var(--accent);font-size:.82rem;text-decoration:none;font-weight:500}
.grid{max-width:1240px;margin:0 auto;display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column;cursor:pointer;text-align:left;color:inherit;font:inherit;padding:0;transition:transform .12s,border-color .12s}
.card:hover,.card:focus-visible{transform:translateY(-2px);border-color:var(--accent);outline:none}
.thumb{position:relative;aspect-ratio:16/9;background:#0a0f1b center/cover no-repeat}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.badge{position:absolute;right:8px;bottom:8px;background:rgba(2,6,12,.82);color:#fff;font-size:.72rem;padding:2px 7px;border-radius:6px}
.body{padding:10px 12px 12px;display:flex;flex-direction:column;gap:6px}
.card h2{margin:0;font-size:.92rem;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.desc{margin:0;color:var(--muted);font-size:.78rem;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:auto}
.chip{font-size:.68rem;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:1px 7px}
.chip.lic{color:#a7f3d0;border-color:#065f46}
.empty{grid-column:1/-1;padding:22px;background:var(--panel);border:1px solid var(--line);border-radius:12px;color:var(--muted)}
footer{max-width:1240px;margin:26px auto 0;color:var(--muted);font-size:.78rem;line-height:1.6}
footer a{color:var(--accent)}
</style></head>
<body>
<header>
  <h1>__TITLE__</h1>
  <p class="muted">Kaynak: __SOURCES__ · __COUNT__ video · Üretim: __GENERATED__</p>
</header>
<div class="toolbar">
  <input id="q" type="search" placeholder="Başlık, açıklama veya etikette ara…" aria-label="Ara">
  <span class="count" id="shown"></span>
</div>
<div id="player-wrap">
  <video id="player" controls playsinline preload="metadata"></video>
  <div id="now"><span id="now-title"></span><a id="now-link" target="_blank" rel="noopener noreferrer">Kaynak sayfa ↗</a></div>
</div>
<main class="grid" id="grid"></main>
<noscript><p class="muted" style="max-width:1240px;margin:0 auto">JavaScript kapalı: aşağıdaki bağlantılarla oynatın.</p>
<div class="grid" id="noscript"></div></noscript>
<footer id="foot"></footer>
<script>
const videos = __DATA__;
const grid=document.getElementById('grid'),player=document.getElementById('player'),
wrap=document.getElementById('player-wrap'),nowTitle=document.getElementById('now-title'),
nowLink=document.getElementById('now-link'),q=document.getElementById('q'),shown=document.getElementById('shown'),
foot=document.getElementById('foot'),noscript=document.getElementById('noscript');
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function play(v){wrap.classList.add('on');player.src=v.url;if(v.poster)player.poster=v.poster;
 nowTitle.textContent=v.title;nowLink.href=v.page||v.url;nowLink.style.display=v.page?'':'none';
 player.play().catch(()=>{});wrap.scrollIntoView({behavior:'smooth',block:'start'});}
function matches(v,needle){if(!needle)return true;const hay=[v.title,v.description,(v.tags||[]).join(' '),v.source,v.year].join(' ').toLowerCase();return hay.includes(needle);}
function render(needle){const list=videos.filter(v=>matches(v,needle));
 grid.innerHTML=list.map((v,i)=>`<button class="card" type="button" data-i="${videos.indexOf(v)}">
  <div class="thumb">${v.poster?`<img loading="lazy" src="${esc(v.poster)}" alt="${esc(v.title)} kapak görseli">`:''}
   ${v.duration?`<span class="badge">${esc(v.duration)}</span>`:''}</div>
  <div class="body"><h2>${esc(v.title)}</h2>${v.description?`<p class="desc">${esc(v.description)}</p>`:''}
   <div class="chips">${v.year?`<span class="chip">${esc(v.year)}</span>`:''}${v.source?`<span class="chip">${esc(v.source)}</span>`:''}${v.license?`<span class="chip lic">${esc(v.license)}</span>`:''}${(v.tags||[]).slice(0,2).map(t=>`<span class="chip">${esc(t)}</span>`).join('')}</div>
  </div></button>`).join('') || '<div class="empty">Eşleşen video yok. Filtreyi değiştirin.</div>';
 shown.textContent=list.length+' / '+videos.length+' gösteriliyor';}
q.addEventListener('input',()=>render(q.value.trim().toLowerCase()));
grid.addEventListener('click',e=>{const card=e.target.closest('.card');if(card)play(videos[+card.dataset.i]);});
if(!videos.length){grid.innerHTML='<div class="empty">Hiç video bulunamadı. Kaynak veya sorgu parametrelerini kontrol edin.</div>';}
if(noscript&&videos.length){noscript.innerHTML=videos.slice(0,60).map(v=>`<a class="card" href="${esc(v.url)}"><div class="body"><h2>${esc(v.title)}</h2></div></a>`).join('');}
if(foot)foot.innerHTML='Bu katalog <a href="https://archive.org" rel="noopener">archive.org</a> gibi açık/kamuya açık lisanslı kaynaklardan otomatik üretilir. '
 +'Videolar kaynak sunucuda kalır; yalnızca doğrudan bağlantıları ve kapak görselleri listelenir. '
 +'Kendi sitenizi tararken <code>robots.txt</code> ve telif haklarına uymak sorumluluğunuzdadır.';
render('');
</script>
</body>
</html>
"""


def _embed_json(videos: Sequence[Video]) -> str:
    """JSON'u <script> içine gömmek için HTML-duyarlı karakterleri unicode'a kaçırır.

    Böylece başlık/açıklama içindeki ``</script>`` veya ``<script>`` sayfayı
    kıramaz (script-data double-escape saldırıları dahil).
    """
    data = json.dumps([video.to_dict() for video in videos], ensure_ascii=False, separators=(",", ":"))
    return (
        data.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def create_html(
    videos: Sequence[Video],
    path: Path,
    source_label: str,
    title: str = "Video arşivi",
) -> None:
    """Kart ızgarası üretir: kapak resmi + başlık + süre + etiketler + açıklama."""
    data = _embed_json(videos)
    sources = html.escape(source_label, quote=False)
    page = (
        PAGE_TEMPLATE.replace("__TITLE__", html.escape(title, quote=False))
        .replace("__SOURCES__", sources)
        .replace("__COUNT__", str(len(videos)))
        .replace("__GENERATED__", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        .replace("__DATA__", data)
    )
    _write_atomic(path, page)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def load_videos_json(path: Path) -> list[Video]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items = payload.get("videos") if isinstance(payload, dict) else payload
    videos: list[Video] = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        tags = item.get("tags") or []
        videos.append(
            Video(
                title=str(item.get("title", "Video"))[:160],
                url=str(item["url"]),
                poster=str(item.get("poster", "")),
                page=str(item.get("page", "")),
                description=str(item.get("description", ""))[:900],
                duration=str(item.get("duration", "")),
                year=str(item.get("year", "")),
                license=str(item.get("license", "")),
                source=str(item.get("source", "")),
                tags=tuple(str(tag) for tag in tags)[:8],
            )
        )
    return videos


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lisanslı bir kaynaktan video + kapak + bilgi çekip HTML kart kataloğu üretir."
    )
    parser.add_argument(
        "--source",
        choices=("ia", "html", "none"),
        default=(os.getenv("SOURCE") or "ia").strip().lower(),
        help="ia = archive.org API (varsayılan, lisanslı) | html = kendi siteniz | none = ağ yok",
    )
    parser.add_argument("--url", default=os.getenv("TARGET_URL", ""), help="--source html için başlangıç sayfası")
    parser.add_argument("--query", default=DEFAULT_IA_QUERY, help="--source ia için archive.org sorgusu")
    parser.add_argument("--output", type=Path, default=Path("index.html"))
    parser.add_argument("--json", type=Path, default=Path("videos.json"), dest="json_path")
    parser.add_argument("--playlist", type=Path, default=Path("playlist.m3u"))
    parser.add_argument("--from-json", type=Path, dest="from_json", help="Ağ erişimi olmadan veriden üret")
    parser.add_argument("--max-videos", type=int, default=60)
    parser.add_argument("--max-pages", type=int, default=25, help="--source html: izlenecek maksimum sayfa")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--delay", type=float,
                        default=float(os.getenv("REQUEST_DELAY") or "0.35"),
                        help="İstekler arası bekleme (saniye)")
    parser.add_argument("--allow-empty", action="store_true",
                        help="hiç video bulunsa bile çıktı dosyalarını üzerine yaz")
    parser.add_argument("--only-licensed", action="store_true", help="yalnızca lisans alanı dolu archive.org öğeleri")
    parser.add_argument("--exclude", action="append", default=[],
                        help="başlık/açıklamada geçerse kaydı atla (tekrar edilebilir)")
    parser.add_argument("--no-filter-explicit", dest="filter_explicit", action="store_false",
                        help="yetişkin/NCII içerik filtresini kapatmayın: GitHub bu içeriği yayınlamayı yasaklar")
    parser.add_argument("--sort", default=DEFAULT_SORT, help="--source ia için archive.org sıralaması")
    parser.add_argument("--allow-offsite", action="store_true",
                        help="--source html: extra-host listesindeki alan adlarına da izin ver")
    parser.add_argument("--allow-host", action="append", default=[],
                        help="--source html için açık alan adı beyaz listesi (tekrar edilebilir)")
    parser.add_argument("--title", default="Video arşivi", help="Sayfa başlığı")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s: %(message)s")
    args = parse_args(argv)

    if args.from_json:
        try:
            videos = load_videos_json(args.from_json)
        except (OSError, json.JSONDecodeError) as exc:
            logging.error("%s okunamadı: %s", args.from_json, exc)
            return 1
        label = f"{args.from_json.name} (önbellek)"
        source_label = label
    else:
        needles = exclusion_needles(args.exclude) if args.filter_explicit else tuple(
            n.lower() for n in args.exclude if n
        )
        if args.source == "html":
            if not args.url:
                logging.error(
                    "--source html için --url gerekli. Yalnızca kendi sitenizi veya "
                    "yazılı izin aldığınız bir adresi verin."
                )
                return 2
            host = urllib.parse.urlparse(args.url).netloc.lower()
            if host not in {h.lower() for h in args.allow_host} and not args.allow_offsite:
                args.allow_host = args.allow_host + [host]
            fetcher = Fetcher(timeout=args.timeout, delay=max(0.5, args.delay))
            videos = crawl_site(
                args.url,
                fetcher=fetcher,
                max_pages=max(1, args.max_pages),
                max_videos=max(1, args.max_videos),
                same_host_only=not args.allow_offsite,
            )
            kept = [video for video in videos if not is_excluded(video, needles)]
            if len(kept) != len(videos):
                logging.warning("%d kayıt içerik filtresiyle elendi", len(videos) - len(kept))
            videos = kept
            logging.info("HTML taraması bitti: %d video (%d istek)", len(videos), fetcher.stats.requests)
        elif args.source == "ia":
            fetcher = Fetcher(timeout=args.timeout, delay=args.delay)
            try:
                videos = collect_archive_videos(
                    fetcher,
                    args.query,
                    max_videos=max(1, args.max_videos),
                    require_license=args.only_licensed,
                    exclude=args.exclude,
                    sort=args.sort,
                )
            except Exception as exc:  # noqa: BLE001
                logging.error("archive.org sorgusu başarısız: %s", exc)
                videos = []
            logging.info("archive.org bitti: %d video", len(videos))
        else:
            videos = []
        source_label = "archive.org API" if args.source == "ia" else (args.url or "verilen kaynak")

    if not videos and not args.allow_empty and not args.from_json and args.source != "none":
        logging.error(
            "Hiç video bulunamadı — önceki katalog korunuyor (boş çıktı yazılmadı). "
            "Kaynağı/sorguyu kontrol edin; yine de yazmak için --allow-empty kullanın."
        )
        return 1

    create_html(videos, args.output, source_label, title=args.title)
    create_json(videos, args.json_path)
    create_m3u_playlist(videos, args.playlist)
    logging.info(
        "%d video bulundu; %s, %s ve %s yazıldı",
        len(videos), args.output, args.json_path, args.playlist,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
