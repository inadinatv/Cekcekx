from scraper import extract_videos


def test_extracts_sources_and_deduplicates():
    source = '''<article><h2>Deneme</h2><video poster="cover.jpg"><source src="/media/test.mp4" type="video/mp4"></video></article>'''
    videos = extract_videos(source, "https://example.com/page")
    assert len(videos) == 1
    assert videos[0].url == "https://example.com/media/test.mp4"
    assert videos[0].title == "Deneme"


def test_extracts_embedded_stream_url():
    source = '<script>const config = {src: "https://cdn.example.com/stream.m3u8?token=1"}</script>'
    videos = extract_videos(source, "https://example.com")
    assert [video.url for video in videos] == ["https://cdn.example.com/stream.m3u8?token=1"]


def test_ignores_numeric_ids_and_images():
    source = '<a href="/watch/12345">Watch</a><img src="https://example.com/a.mp4.jpg">'
    assert extract_videos(source, "https://example.com") == []
