# Cekcekx video botu

Bot, varsayılan olarak verilen Evooli AMP sayfasındaki gerçek video bağlantılarını (`video`, `source`, `iframe`, bağlantılar ve gömülü JSON/JS) bulur; özellikle MP4 bağlantılarını `index.html` ve `playlist.m3u` olarak kaydeder.

## Yerelde çalıştırma

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scraper.py --url "https://ornek-site.tld/"
```

Seçenekler: `--output`, `--playlist`, `--max-videos` ve `--timeout`. Varsayılan URL `TARGET_URL` ortam değişkeniyle de verilebilir.

## GitHub Actions

İş akışı altı saatte bir çalışır veya **Actions > Video kataloğunu güncelle > Run workflow** ile elle başlatılır. Farklı bir kaynak kullanmak için repository variable olarak `TARGET_URL` ekleyin. İş akışı gerçek sayfada bulunan bağlantıları kaydeder; tahmini CDN adresi üretmez ve erişim engellerini aşmaya çalışmaz.

> Not: Kaynak site video dosyalarında CORS veya oturum zorunluluğu uyguluyorsa, tarayıcıdaki oynatıcı çalışmayabilir. HTML ve M3U yine bulunan doğrudan bağlantıyı gösterir.
