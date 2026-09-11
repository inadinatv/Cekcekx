# Cekcekx video botu

Bot, varsayılan olarak Evooli AMP ana sayfasındaki (`https://1ppa99-evooli-com.cdn.ampproject.org/c/s/1ppa99.evooli.com/amp/`) video sayfalarını takip ederek gerçek video bağlantılarını (`video`, `source`, `amp-video`, `iframe`, bağlantılar ve gömülü JSON/JS) bulur; özellikle MP4 bağlantılarını `index.html` ve `playlist.m3u` olarak kaydeder.

AMP sayfasındaki tüm film/dizi bağlantıları otomatik keşfedilir, her bir detay sayfası ziyaret edilerek içindeki MP4/WebM/M3U8 kaynakları toplanır. JSON içindeki `\/` kaçışlı ve göreli (`/media/...mp4`) yollar da çözülür.

## Yerelde çalıştırma

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scraper.py --url "https://1ppa99-evooli-com.cdn.ampproject.org/c/s/1ppa99.evooli.com/amp/"
```

Seçenekler: `--output`, `--playlist`, `--max-videos`, `--max-pages`, `--timeout` ve `--no-crawl`. Varsayılan URL `TARGET_URL` ortam değişkeniyle de verilebilir.

- `--max-pages 30`: AMP ana sayfasından takip edilecek maksimum video detay sayfası
- `--no-crawl`: Sadece verilen URL'den video çıkar, sayfa takibi yapma

## GitHub Actions

İş akışı altı saatte bir çalışır veya **Actions > Video kataloğunu güncelle > Run workflow** ile elle başlatılır. Farklı bir kaynak kullanmak için repository variable olarak `TARGET_URL` ekleyin. İş akışı gerçek sayfada bulunan bağlantıları kaydeder; tahmini CDN adresi üretmez ve erişim engellerini aşmaya çalışmaz.

> Not: Kaynak site video dosyalarında CORS veya oturum zorunluluğu uyguluyorsa, tarayıcıdaki oynatıcı çalışmayabilir. HTML ve M3U yine bulunan doğrudan bağlantıyı gösterir.
