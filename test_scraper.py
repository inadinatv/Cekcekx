"""Cekcekx video botu testleri.

Tüm testler çevrimdışı çalışır: ağ isteği yapılmaz, gerçek archive.org API
yanıtlarından alınmış sabit (fixture) JSON'lar kullanılır.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scraper import (
    FetchStats,
    Robots,
    Video,
    absolutize,
    absolutize_image,
    build_video_from_item,
    crawl_site,
    create_html,
    create_json,
    create_m3u_playlist,
    extract_page_links,
    extract_videos,
    first_year,
    format_duration,
    is_video_url,
    license_label,
    load_videos_json,
    normalize_text,
    pick_poster,
    pick_video_file,
)

# --------------------------------------------------------------------------- #
# Sabitler — archive.org metadata API'sinin gerçek yanıt biçimi
# --------------------------------------------------------------------------- #
IA_METADATA = {
    "server": "ia900000.us.archive.org",
    "dir": "/0/items/Nosferatu1922_201611",
    "metadata": {
        "identifier": "Nosferatu1922_201611",
        "title": "Nosferatu - symfonia grozy (Niemcy, 1922) - rez. F. W. Murnau",
        "creator": "F. W. Murnau",
        "year": 1922,
        "date": "1922-01-01",
        "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/",
        "collection": ["featurefilms", "censusmurnau"],
        "subject": ["german expressionism", "silent film"],
        "description": "Bir kamu malı sessiz film kopyasi.",
    },
    "files": [
        {
            "name": "Nosferatu (1922).mp4",
            "source": "original",
            "format": "MPEG4",
            "length": "5488.27",
            "size": "2968746864",
            "height": "576",
            "width": "768",
        },
        {
            "name": "Nosferatu (1922).ogv",
            "source": "derivative",
            "format": "Ogg Video",
            "original": "Nosferatu (1922).mp4",
            "length": "5488.27",
            "size": "410080263",
            "height": "300",
            "width": "400",
        },
        {
            "name": "Nosferatu1922_201611.thumbs/Nosferatu (1922)_000001.jpg",
            "source": "derivative",
            "format": "Thumbnail",
            "original": "Nosferatu (1922).mp4",
            "size": "11867",
        },
        {"name": "Nosferatu1922_201611_files.xml", "format": "Metadata", "size": "1234"},
        {"name": "__image.jpg", "source": "original", "format": "Item Tile", "size": "5000"},
    ],
}


class FakeFetcher:
    """Fetcher arayüzünü taklit eder; agaga gitmez."""

    def __init__(self, pages: dict[str, str], *, robots: str | None = None) -> None:
        self.pages = pages
        self.robots = robots
        self.stats = FetchStats()
        self.calls: list[str] = []
        self.user_agent = "test-agent"

    def get(self, url: str, *, timeout: float | None = None) -> str:
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            if self.robots is None:
                raise FileNotFoundError(404)
            return self.robots
        if url not in self.pages:
            raise FileNotFoundError(url)
        return self.pages[url]

    def get_json(self, url: str):
        return json.loads(self.get(url))


# --------------------------------------------------------------------------- #
# archive.org kaynağı
# --------------------------------------------------------------------------- #
def test_build_video_from_real_metadata_shape():
    videos = build_video_from_item("Nosferatu1922_201611", IA_METADATA)
    assert len(videos) == 1
    video = videos[0]
    assert video.url == (
        "https://archive.org/download/Nosferatu1922_201611/Nosferatu%20%281922%29.mp4"
    )
    assert video.title.startswith("Nosferatu")
    assert video.year == "1922"
    assert video.license == "Kamu malı"
    assert video.duration == "1:31:28"
    assert video.page == "https://archive.org/details/Nosferatu1922_201611"
    assert video.source == "archive.org"
    assert video.license == "Kamu malı"
    # Kapak: secilen mp4'e ait thumbnail kullanilir
    assert video.poster.startswith("https://archive.org/download/Nosferatu1922_201611/")
    assert "thumbs" in video.poster


def test_build_video_prefers_browser_friendly_mp4():
    files = [
        {"name": "big.mkv", "format": "Matroska Video", "length": "100"},
        {"name": "small.ogv", "format": "Ogg Video", "length": "100"},
        {"name": "web.mp4", "format": "h.264 MPEG4", "length": "100", "height": "480",
         "size": "1000000", "source": "derivative"},
    ]
    chosen = pick_video_file(files)
    assert chosen is not None
    assert chosen["name"] == "web.mp4"


def test_poster_falls_back_to_thumb_service():
    files = [{"name": "readme.txt", "format": "Text File"}]
    poster = pick_poster(files, "some_item", "movie.mp4")
    assert poster == "https://archive.org/services/img/some_item"


def test_no_video_files_yields_no_videos():
    meta = {"metadata": {"title": "Sadece kitap"}, "files": [{"name": "book.pdf", "format": "Text"}]}
    assert build_video_from_item("book_123", meta) == []


def test_duration_parsing_variants():
    assert format_duration("5488.27") == "1:31:28"
    assert format_duration("00:59:01") == "59:01"
    assert format_duration(75) == "1:15"
    assert format_duration("") == ""
    assert format_duration(None) == ""
    assert format_duration("bilinmiyor") == "bilinmiyor"


def test_license_labels():
    assert license_label("https://creativecommons.org/publicdomain/mark/1.0/") == "Kamu malı"
    assert license_label(["https://creativecommons.org/licenses/by/4.0/"]).startswith("CC BY")
    assert license_label("") == "Lisans bilgisi yok"


def test_first_year_and_normalize():
    assert first_year(["", "film 1972 restored"]) == "1972"
    assert first_year([]) == ""
    assert normalize_text("<b>Merhaba</b>\n  dünya", 400) == "Merhaba dünya"


# --------------------------------------------------------------------------- #
# HTML çıkarımı
# --------------------------------------------------------------------------- #
def test_extracts_video_source_and_dedupes():
    source = (
        '<article><h2>Deneme</h2><video poster="cover.jpg">'
        '<source src="/media/test.mp4" type="video/mp4">'
        '<source src="/media/test.mp4" type="video/mp4"></video></article>'
    )
    videos = extract_videos(source, "https://example.com/page")
    assert len(videos) == 1
    assert videos[0].url == "https://example.com/media/test.mp4"
    assert videos[0].title == "Deneme"
    assert videos[0].poster == "https://example.com/cover.jpg"


def test_extracts_amp_video_and_og_poster():
    source = (
        '<head><meta property="og:image" content="/shots/amp.jpg">'
        "<title>AMP Film</title></head>"
        '<amp-video src="https://cdn.example.com/video.mp4" poster="p.jpg"></amp-video>'
    )
    videos = extract_videos(source, "https://example.com/amp/")
    assert len(videos) == 1
    assert videos[0].url == "https://cdn.example.com/video.mp4"
    assert videos[0].poster == "https://example.com/amp/p.jpg"
    assert videos[0].title == "AMP Film"


def test_escaped_relative_json_path_is_resolved():
    source = r'<script>window.data = {"file": "\/media\/movie.mp4?token=abc"}</script>'
    videos = extract_videos(source, "https://example.com/amp/")
    assert videos[0].url == "https://example.com/media/movie.mp4?token=abc"


def test_ignores_images_and_numeric_page_ids():
    source = '<a href="/watch/12345">Izle</a><img src="https://example.com/a.mp4.jpg">'
    assert extract_videos(source, "https://example.com") == []
    assert is_video_url("https://example.com/a.mp4.jpg") is False
    assert absolutize("/img/poster.jpg", "https://example.com/x") is None


def test_absolutize_rejects_unsafe_schemes():
    assert absolutize("data:video/mp4;base64,AAAA", "https://example.com") is None
    assert absolutize("blob:https://example.com/xyz", "https://example.com") is None
    assert absolutize_image("data:image/png;base64,AA", "https://example.com") == ""


def test_max_videos_limit():
    source = "".join(f'<video src="https://cdn.example.com/v{i}.mp4"></video>' for i in range(50))
    assert len(extract_videos(source, "https://example.com", max_videos=5)) == 5


# --------------------------------------------------------------------------- #
# Sayfa bağlantıları
# --------------------------------------------------------------------------- #
def test_page_links_same_host_only_by_default():
    source = """
    <html><body>
      <a href="/amp/film-1-izle/">Film 1</a>
      <a href="/amp/dizi-2-bolum-1/">Dizi 2</a>
      <a href="/tag/aksiyon">Etiket</a>
      <a href="https://baskasinin-sitesi.com/amp/film-3/">Izinsiz dis site</a>
      <a href="/media/trailer.mp4">Duz mp4</a>
      <a href="#top">Capa</a>
    </body></html>
    """
    links = extract_page_links(source, "https://example.com/amp/")
    assert any("film-1-izle" in link for link in links)
    assert any("dizi-2-bolum-1" in link for link in links)
    assert not any("baskasinin-sitesi" in link for link in links)
    assert not any("/tag/" in link for link in links)
    assert not any(".mp4" in link for link in links)


def test_page_links_respect_explicit_host_allowlist():
    source = '<a href="https://medya.ornek.net/amp/film-9-izle/">Film 9</a>'
    allowed = extract_page_links(
        source, "https://ornek.net/amp/", extra_hosts=["medya.ornek.net"]
    )
    assert any("film-9-izle" in link for link in allowed)
    blocked = extract_page_links(source, "https://ornek.net/amp/")
    assert blocked == []


def test_page_links_skip_legal_and_nav_pages():
    source = (
        '<a href="/iletisim/">Iletisim</a><a href="/dmca/">DMCA</a>'
        '<a href="/category/film/">Kategori</a><a href="/film/kayip-kent-izle/">Kayip Kent</a>'
    )
    links = extract_page_links(source, "https://ornek.net/")
    assert links == ["https://ornek.net/film/kayip-kent-izle/"]


def test_page_links_max_links():
    source = "".join(f'<a href="/amp/film-{i}-izle/">F{i}</a>' for i in range(20))
    assert len(extract_page_links(source, "https://example.com/amp/", max_links=5)) == 5


def test_page_links_and_videos_work_without_bs4(monkeypatch):
    """bs4 kurulu değilse regex fallback devreye girmeli."""
    import scraper

    monkeypatch.setattr(scraper, "BeautifulSoup", None)
    source = (
        "<html><head><title> regex başlık </title></head><body>"
        '<a href="/amp/film-x-izle/">X</a><a href="/tag/y">Y</a>'
        '<video poster="/kapak.jpg" src="/files/movie.mp4"></video>'
        "</body></html>"
    )
    assert extract_page_links(source, "https://example.com/") == [
        "https://example.com/amp/film-x-izle/"
    ]
    videos = extract_videos(source, "https://example.com/")
    assert [v.url for v in videos] == ["https://example.com/files/movie.mp4"]
    assert videos[0].poster == "https://example.com/kapak.jpg"


# --------------------------------------------------------------------------- #
# Tarama + robots.txt
# --------------------------------------------------------------------------- #
def test_crawl_site_follows_detail_pages_and_dedupes():
    homepage = (
        '<a href="/amp/kayip-kent-izle/">Kayip Kent</a>'
        '<a href="/amp/kayip-kent-izle/?p=2">Ayni icerik degil</a>'
    )
    detail = '<video poster="/p/kayip.jpg" src="https://cdn.ornek.net/film/kayip.mp4"></video>'
    fetcher = FakeFetcher(
        {
            "https://ornek.net/amp/": homepage,
            "https://ornek.net/amp/kayip-kent-izle/": detail,
            "https://ornek.net/amp/kayip-kent-izle/?p=2":
                '<video src="https://cdn.ornek.net/film/kayip.mp4"></video>',
        }
    )
    videos = crawl_site("https://ornek.net/amp/", fetcher=fetcher, max_pages=5)
    assert len(videos) == 1
    assert videos[0].url == "https://cdn.ornek.net/film/kayip.mp4"
    assert videos[0].poster == "https://ornek.net/p/kayip.jpg"


def test_crawl_site_honours_robots_disallow():
    homepage = '<a href="/amp/kayip-kent-izle/">Kayip Kent</a>'
    fetcher = FakeFetcher(
        {"https://ornek.net/amp/": homepage},
        robots="User-agent: *\nDisallow: /amp/kayip\n",
    )
    videos = crawl_site("https://ornek.net/amp/", fetcher=fetcher, max_pages=5)
    assert videos == []
    assert fetcher.stats.skipped_robots == 1


def test_crawl_site_stops_when_start_url_is_disallowed():
    fetcher = FakeFetcher({"https://ornek.net/amp/": "<a href='/amp/a-b-c-izle/'>x</a>"},
                          robots="User-agent: *\nDisallow: /\n")
    assert crawl_site("https://ornek.net/amp/", fetcher=fetcher) == []
    # robots.txt disindaki istek yapilmamali
    assert fetcher.calls == ["https://ornek.net/robots.txt"]


def test_robots_fail_open_when_missing():
    fetcher = FakeFetcher({}, robots=None)
    assert Robots(fetcher).allowed("https://ornek.net/x") is True


def test_robots_blocks_path():
    fetcher = FakeFetcher({}, robots="User-agent: *\nDisallow: /private\n")
    robots = Robots(fetcher)
    assert robots.allowed("https://ornek.net/private/a") is False
    assert robots.allowed("https://ornek.net/public/a") is True


# --------------------------------------------------------------------------- #
# Ureticiler (HTML kart / JSON / M3U)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sample_videos() -> list[Video]:
    return [
        Video(
            title="Kayip Kent <script>alert(1)</script>",
            url="https://archive.org/download/kayip/kayip.mp4",
            poster="https://archive.org/services/img/kayip",
            page="https://archive.org/details/kayip",
            description='Açıklama "tırnaklı" ve </script> kaçıran bir parça',
            duration="1:20:00",
            year="1927",
            license="Kamu malı",
            source="archive.org",
            tags=("sessiz film", "ekspresyonizm"),
        ),
        Video(title="", url="https://example.org/b.webm"),
    ]


def test_create_html_renders_cards_with_poster(sample_videos, tmp_path: Path):
    out = tmp_path / "index.html"
    create_html(sample_videos, out, "archive.org API", title="Video arşivi")
    page = out.read_text(encoding="utf-8")
    payload = json.loads(page.split("const videos = ", 1)[1].split(";\nconst grid", 1)[0])
    assert payload[0]["title"] == "Kayip Kent <script>alert(1)</script>"
    assert payload[0]["poster"].endswith("/kayip")
    assert payload[0]["tags"] == ["sessiz film", "ekspresyonizm"]
    # XSS: JSON icindeki </script> kacisli olmali
    assert "</script> kaçıran" not in page
    assert "alert(1)" in page  # veri olarak duruyor ama etiket olarak degil
    assert page.count("<script>") == 1
    assert 'class="card"' in page and "loading=\"lazy\"" in page
    assert "Kaynak: archive.org API" in page


def test_embed_json_escapes_html_breakout():
    from scraper import _embed_json

    tricky = Video(
        title='</script><script>alert(1)</script>',
        url="https://example.com/a.mp4",
        description="a && b < c > d",
    )
    blob = _embed_json([tricky])
    assert "</script>" not in blob
    assert "<script>" not in blob
    assert r"\u003c" in blob
    decoded = json.loads(blob)
    assert decoded[0]["title"] == '</script><script>alert(1)</script>'
    assert decoded[0]["description"] == "a && b < c > d"


def test_create_html_empty_state(tmp_path: Path):
    out = tmp_path / "index.html"
    create_html([], out, "test")
    assert "Hiç video bulunamadı" in out.read_text(encoding="utf-8")


def test_json_roundtrip(sample_videos, tmp_path: Path):
    out = tmp_path / "videos.json"
    create_json(sample_videos, out)
    loaded = load_videos_json(out)
    assert len(loaded) == 2
    assert loaded[0].duration == "1:20:00"
    assert loaded[0].tags == ("sessiz film", "ekspresyonizm")
    assert loaded[1].title == "Video" or loaded[1].title == ""
    assert loaded[1].url == "https://example.org/b.webm"


def test_m3u_playlist_entries(sample_videos, tmp_path: Path):
    out = tmp_path / "playlist.m3u"
    create_m3u_playlist(sample_videos, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '#EXTM3U version="1"'
    assert lines[1].startswith('#EXTINF:-1 ')
    assert 'group-title="archive.org"' in lines[1]
    assert 'tvg-logo="https://archive.org/services/img/kayip' in lines[1]
    assert lines[2] == "https://archive.org/download/kayip/kayip.mp4"
    assert len(lines) == 1 + 2 * len(sample_videos)


def test_main_does_not_overwrite_catalogue_when_empty(tmp_path, monkeypatch):
    """Ag/kaynak hatasında önceki (dolu) katalog korunmalı."""
    from scraper import main

    out = tmp_path / "index.html"
    out.write_text("onceki dolu katalog", encoding="utf-8")
    monkeypatch.setattr("scraper.crawl_site", lambda *a, **k: [])
    rc = main([
        "--source", "html", "--url", "https://own-site.example/amp/",
        "--output", str(out), "--json", str(tmp_path / "v.json"),
        "--playlist", str(tmp_path / "p.m3u"),
    ])
    assert rc == 1
    assert out.read_text(encoding="utf-8") == "onceki dolu katalog"
    assert not (tmp_path / "v.json").exists()


def test_main_from_json_writes_outputs(tmp_path):
    from scraper import main

    src = tmp_path / "cache.json"
    create_json(
        [Video(title="Deneme", url="https://example.org/a.mp4", poster="https://example.org/a.jpg")],
        src,
    )
    out = tmp_path / "index.html"
    rc = main([
        "--from-json", str(src), "--output", str(out),
        "--json", str(tmp_path / "v.json"), "--playlist", str(tmp_path / "p.m3u"),
    ])
    assert rc == 0
    page = out.read_text(encoding="utf-8")
    assert "https://example.org/a.mp4" in page and "Deneme" in page


def test_display_title_fallback():
    assert Video(title="   ", url="https://x/y.mp4").display_title == "Adsız video"


# --------------------------------------------------------------------------- #
# Guvenlik / politika bekçi testleri
# --------------------------------------------------------------------------- #
def test_explicit_content_filter_defaults_on():
    from scraper import DEFAULT_EXCLUDE, exclusion_needles, is_excluded

    needles = exclusion_needles()
    assert set(DEFAULT_EXCLUDE).issubset(set(needles))
    adult = Video(title="Brazzers porn derlemesi", url="https://cdn.example/x.mp4")
    clean = Video(title="Cleopatra", url="https://archive.org/download/Cleopatra_1912/Cleopatra.mp4")
    assert is_excluded(adult, needles) is True
    assert is_excluded(clean, needles) is False
    # kullanici kendi filtresini ekleyebilir
    assert is_excluded(clean, exclusion_needles(["cleopatra"])) is True
    assert exclusion_needles(()) == exclusion_needles()


def test_no_url_guessing_from_numeric_ids():
    """Sayida ID'den CDN URL uretmek yasak: baska bir kod yolu bulamazsak bos doneriz."""
    source = '<div data-id="364324"><a href="/film/364324">Izle</a></div>'
    assert extract_videos(source, "https://ornek.net/") == []
    assert not hasattr(Video, "from_id")
    assert "cdn." not in json.dumps([{"url": v.url} for v in extract_videos(source, "https://x")])


def test_module_documents_guardrails():
    import scraper

    doc = scraper.__doc__ or ""
    for phrase in ("CORS proxy", "DRM", "ID"):
        assert phrase in doc


def test_default_query_is_license_filtered():
    from scraper import DEFAULT_IA_QUERY

    assert "mediatype:movies" in DEFAULT_IA_QUERY
    assert "licenseurl:*publicdomain*" in DEFAULT_IA_QUERY


def test_fetcher_rejects_non_http_scheme():
    from scraper import Fetcher

    with pytest.raises(ValueError):
        Fetcher().get("file:///etc/passwd")
