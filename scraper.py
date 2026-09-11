import os
import re
import json
import urllib.parse
import urllib3
import requests
import cloudscraper
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TARGET_URL = "https://www.evoolipxnyxzq.shop/"
REFERER = "https://www.evoolipxnyxzq.shop/"
USER_AGENT = "Mozilla/5.0 (Linux; Android 15; 2412DPC0AG Build/AP3A.240905.015.A2; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/151.0.7922.199 Mobile Safari/537.36"

def get_html_content():
    """Bot korumasını atlatarak sayfa kaynağını çeker"""
    html = ""
    
    # 1. YÖNTEM: Cloudscraper (Anti-Bot Atlatıcı)
    print("Yöntem 1 deneniyor: Cloudscraper (Gerçek Tarayıcı Taklidi)...")
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'android', 'desktop': False}
        )
        scraper.headers.update({
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        })
        res = scraper.get(TARGET_URL, timeout=15)
        html = res.text
    except Exception as e:
        print(f"Cloudscraper hatası: {e}")

    # EĞER SAYFA HALA BOŞSA (0 Karakter) 2. YÖNTEME GEÇ
    if len(html) < 50:
        print("Yöntem 1 engellendi. Yöntem 2 deneniyor: AllOrigins Proxy API...")
        try:
            api_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(TARGET_URL)}"
            proxy_res = requests.get(api_url, timeout=15)
            html = proxy_res.json().get("contents", "")
        except Exception as e:
            print(f"Proxy API hatası: {e}")

    return html

def analyze_and_crawl():
    html = get_html_content()
    print(f"\n[!] Alınan sayfa boyutu: {len(html)} karakter")

    if len(html) < 50:
        print("HATA: Site her iki yöntemde de boş sayfa döndürdü. Koruma çok yüksek.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(strip=True) if soup.title else "Başlık Yok"
    print(f"[!] Sayfa Başlığı: {page_title}")

    videos = []
    seen_ids = set()

    # Sayfadaki 5-7 haneli tüm potansiyel Video ID'lerini tara (Örn: 364291)
    id_matches = re.findall(r'(?:id|video|item|post|play|/)?["\'/=:]+(\d{5,7})(?:\.html|\.mp4|["\'&?])?', html, re.IGNORECASE)
    
    for vid in id_matches:
        # Sahte veya işe yaramaz olabilecek ID'leri filtrele
        if vid not in seen_ids and not vid.startswith("000") and vid not in ["100000", "999999"]:
            seen_ids.add(vid)
            # Video linkini türetiyoruz
            generated_url = f"https://cdn.evolliecdnsx.com/{vid}.mp4"
            videos.append({
                "title": f"Video #{vid}",
                "url": generated_url,
                "poster": ""
            })

    return videos

def create_m3u_playlist(videos):
    if not videos: return
    lines = ["#EXTM3U"]
    encoded_ua = urllib.parse.quote(USER_AGENT)
    encoded_ref = urllib.parse.quote(REFERER)

    for v in videos:
        pipe_url = f"{v['url']}|User-Agent={encoded_ua}|Referer={encoded_ref}"
        lines.append(f'#EXTINF:-1,{v["title"]}')
        lines.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
        lines.append(f'#EXTVLCOPT:http-referrer={REFERER}')
        lines.append(pipe_url)

    with open("playlist.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def create_html(videos):
    if not videos: return
    videos_json = json.dumps(videos, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Evoli Mobil Portalı</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, sans-serif; }}
        body {{ background: #090d16; color: #f8fafc; padding: 12px; }}
        .header {{ text-align: center; margin-bottom: 12px; }}
        .header h1 {{ font-size: 18px; color: #38bdf8; }}
        .player-box {{ background: #000; border-radius: 10px; overflow: hidden; margin-bottom: 12px; position: sticky; top: 5px; z-index: 99; box-shadow: 0 4px 15px rgba(0,0,0,0.8); }}
        video {{ width: 100%; aspect-ratio: 16/9; display: block; }}
        .info {{ padding: 8px 12px; background: #1e293b; font-size: 13px; font-weight: bold; }}
        .action-btns {{ display: flex; gap: 8px; margin-bottom: 12px; }}
        .btn {{ flex: 1; padding: 10px; background: #0284c7; color: #fff; text-align: center; border-radius: 8px; text-decoration: none; font-size: 12px; font-weight: bold; border: none; cursor: pointer; }}
        .btn-vlc {{ background: #ea580c; }}
        .list {{ display: flex; flex-direction: column; gap: 8px; }}
        .item {{ display: flex; justify-content: space-between; align-items: center; background: #1e293b; padding: 12px; border-radius: 8px; }}
        .item-title {{ font-size: 13px; font-weight: 500; }}
        .play-btn {{ padding: 6px 12px; background: #10b981; color: #fff; border: none; border-radius: 6px; font-size: 12px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Evoli Film Arşivi</h1>
    </div>
    <div class="player-box">
        <video id="player" controls playsinline></video>
        <div id="videoTitle" class="info">Bir video seçin</div>
    </div>
    <div class="action-btns">
        <button class="btn btn-vlc" onclick="openInVLC()">VLC ile Aç</button>
        <a href="playlist.m3u" download class="btn">M3U Listesini İndir</a>
    </div>
    <div class="list" id="videoList"></div>
    <script>
        const videos = {videos_json};
        const player = document.getElementById('player');
        const titleEl = document.getElementById('videoTitle');
        let currentUrl = "";
        const PROXY = "https://corsproxy.io/?";

        function selectVideo(url, title) {{
            currentUrl = url;
            titleEl.innerText = title;
            player.src = PROXY + encodeURIComponent(url);
            player.play().catch(() => {{}});
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
        }}

        function openInVLC() {{
            if (!currentUrl) return alert("Listeden video seçin!");
            window.location.href = "intent:" + currentUrl + "#Intent;type=video/*;package=org.videolan.vlc;end";
        }}

        function render() {{
            const listEl = document.getElementById('videoList');
            listEl.innerHTML = "";
            videos.forEach(v => {{
                const div = document.createElement('div');
                div.className = 'item';
                div.innerHTML = `
                    <div class="item-title">${{v.title}}</div>
                    <button class="play-btn" onclick="selectVideo('${{v.url}}', '${{v.title}}')">Oynat</button>
                `;
                listEl.appendChild(div);
            }});
        }}
        render();
        if (videos.length > 0) {{
            selectVideo(videos[0].url, videos[0].title);
        }}
    </script>
</body>
</html>
"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    vids = analyze_and_crawl()
    print(f"\n[+] Bulunan toplam video sayısı: {len(vids)}")
    if vids:
        create_m3u_playlist(vids)
        create_html(vids)
        print("[+] index.html ve playlist.m3u oluşturuldu.")
