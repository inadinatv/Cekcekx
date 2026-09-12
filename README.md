# Cekcekx video botu

Bot, **lisanslı/açık kaynaklı** bir kaynaktan video dosyalarını, kapak resimlerini ve film
bilgilerini (başlık, yıl, süre, lisans, etiketler, açıklama) çeker; bunları

* `index.html` → arama kutulu, kapak resimli **HTML kart ızgarası** (tarayıcıda oynatıcı dahil),
* `videos.json` → ham veri (kartların kaynağı, yeniden üretmek için),
* `playlist.m3u` → VLC/TiviMax/OTT oynatma listesi (`tvg-logo`, `group-title`, süre)

olarak kaydeder. GitHub Actions ile periyodik olarak kendini yeniler.

## Neden eski hâli çalışmıyordu?

Eski sürüm, yetişkin içerik barındıran üçüncü taraf bir sitenin **Google AMP Cache**
kopyasını hedefliyordu (`https://<site>-cdn.ampproject.org/c/s/<site>/amp/`). Üç nedenle
sıfır video üretiyordu:

1. **Google, 1 Temmuz 2026'da AMP Cache / AMP Viewer üzerinden önbellekli sunumu kaldırdı.**
   `/c/s/` ile başlayan proxy adresleri artık publish edilmiş AMP kopyalarını sunmuyor;
   tarama girişi doğrudan yayıncının kendi alan adına gittiği için proxy üzerinden
   içerik çekme dönemi kapandı.
2. Hedef site, erişim engelleri nedeniyle **alt alan adını sürekli değiştiriyordu**;
   koda gömülü (hardcoded) tek bir adres bir süre sonra ölü kalıyor.
3. O type sitelerde MP4 adresi HTML içinde **bulunmuyor**: oynatıcı dosyayı ayrı bir CDN'den
   JavaScript/XHR ile çekiyor. Bunu "bulmanın" tek yolu, kural olarak sayısal ID'den CDN
   adresi üretmek (`.../364324.mp4` gibi) ve erişim kısıtlarını dolaşmaktır. Bu bot
   **bunu yapmaz ve yapmayacaktır**.

Ayrıca bu tip siteler telifli stüdyo içeriklerini izinsiz dağıtır ve "ifşa / sızdırılmış
video" gibi kategoriler rıza dışı içerik (NCII) riski taşır. Bu içeriği tarayıp link + kapak
yayınmak telif ihlali ve GitHub'ın (Ekim 2025'te güncellenen) Kabul Edilebilir Kullanım
Politikası'nın ihlalidir; repo/Account kapatma sebebi olur. Bot bu yüzden hedefini
yasal kaynaklarla değiştirilmiş hâlde bu repoda duruyor.

## Kaynaklar

| Kaynak | Ne zaman kullanılır | Komut |
| --- | --- | --- |
| `ia` (varsayılan) | Açık/kamu malı film arşivi (archive.org resmî API'si). API anahtarı gerekmez. | `python scraper.py` |
| `html` | **Kendi siteniz** veya yazılı izin aldığınız site. | `python scraper.py --source html --url https://siteniz.com/filmler/` |
| `none` | Ağ yok, boş iskelet üret (arayüzü test etmek için). | `python scraper.py --source none --allow-empty` |

Varsayılan archive.org sorgusu, lisansı açıkça kamu malı olarak işaretlenmiş filmleri en çok
indirilenlere göre sıralar:

```
mediatype:movies AND licenseurl:*publicdomain*
```

### Yerelde çalıştırma

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python scraper.py                       # archive.org -> index.html + videos.json + playlist.m3u
python scraper.py --max-videos 100 --only-licensed
python scraper.py --query 'mediatype:movies AND subject:"silent film"' --sort 'week desc'
python scraper.py --from-json videos.json   # ag'a gitmeden HTML'i yeniden uret
python -m pytest -q                        # 36 birim testi, cevrimdisi calisir
```

### Seçenekler

| Bayrak | Açıklık |
| --- | --- |
| `--source {ia,html,none}` | Kaynak seçimi (`SOURCE` ortam değişkeni de olur) |
| `--url` | `--source html` için başlangıç sayfası (`TARGET_URL` de olur) |
| `--query`, `--sort` | archive.org sorgusu ve sıralaması (`IA_QUERY`, `IA_SORT`) |
| `--max-videos`, `--max-pages` | Üst sınırlar (CI'da istek sayısını kontrol eder) |
| `--delay` | İstekler arası bekleme — HTML taramasında taban 0.5 sn (`REQUEST_DELAY`) |
| `--timeout` | Tek istek zaman aşımı |
| `--output`, `--json`, `--playlist` | Çıktı yolları |
| `--from-json` | Önbellekteki veriden HTML/M3U üret (çevrimdışı) |
| `--only-licensed` | Yalnızca `licenseurl` alanı dolu öğeler |
| `--exclude`, `--no-filter-explicit` | İçerik filtresine kelime eklemek / filtre |
| `--allow-offsite`, `--allow-host` | HTML taramasında beyaz liste dışına çıkmak (önerilmez) |
| `--allow-empty` | Hiç video bulunsa bile çıktıları üzerine yaz |

## Kendi sitenizi tararken

`--source html` modu bilinçli olarak kısıtlıdır:

* yalnızca **başlangıç adresinin host'u** (+ `--allow-host` ile eklediğiniz alan adları) taranır,
* **`robots.txt`** okunur; izin verilmeyen yollar atlanır (`skipped_robots` sayacına yazılır),
* istekler arasında gecikme uygulanır, sayfa/`video` sayısı sınırlıdır,
* `video`, `source`, `amp-video`, `iframe`, `embed` etiketleri, `og:image`/`poster` kapakları ve
  sayfadaki JSON/JS konfigürasyonları okunur; `.mp4?token=...` ve `\/media\/x.mp4` gibi
  kaçışlı/göreli yollar çözülür,
* `index.html` ve `videos.json` **asla boş katalogla ezilmez**: kaynak erişilemezse bot hata
  verir ve önceki sürüm yerinde kalır.

`beautifulsoup4` kurulu değilse kod regex tabanlı geri düşüşle çalışmaya devam eder.

## GitHub Actions / Pages

`.github/workflows/scraper.yml` altı saatte bir (ve isterseniz **Actions → Video Botu Calistir →
Run workflow** ile elle) çalışır; önce pytest'ı çalıştırır, sonra ürettiği `index.html`,
`videos.json` ve `playlist.m3u` dosyalarını commit eder. Ayarlar → Pages → *Deploy from a branch*
(`main` / kök) seçiliyse `index.html` doğrudan yayında görünür.

Repo variable olarak istediğiniz tanımlayabilirsiniz: `SOURCE`, `TARGET_URL`, `IA_QUERY`, `IA_SORT`.

> **Güncellenmiş iş akışı:** `docs/scraper-workflow.yml` dosyasında pytest adımı, `concurrency`,
> `timeout-minutes`, repo variable desteği ve üç çıktıyı (`index.html`, `videos.json`,
> `playlist.m3u`) birlikte commit etme davranışı bulunan yeni sürüm duruyor. Bu depoya
> `.github/workflows/` altında push edilemedi (GitHub App'in `workflows` yazma izni yok), bu yüzden
> elle kopyalayın:
>
> ```bash
> cp docs/scraper-workflow.yml .github/workflows/scraper.yml
> git add .github/workflows/scraper.yml && git commit -m "Is akisini guncelle" && git push
> ```
>
> GitHub arayüzünde: **Add file → Commit new file** ile `.github/workflows/scraper.yml` yoluna
> yapıştırmanız da yeterli.

## Ulaşılabilirlik / çıktı notları

* Kartlar tembel (lazy) yüklenen kapak resimleri, süre rozeti, yıl/kaynak/lisans etiketleri ve
  iki satırla kısaltılmış açıklama gösterir; üstteki arama kutusu başlık, açıklama ve etiketlerde
  tarayıcı tarafında süzer.
* Videolar kaynak sunucuda kalır, repoya indirilmez; HTML yalnızca doğrudan bağlantıları listeler.
  Kaynak sunucu `Range`/HTTPS desteklediği sürece `<video>` oynatıcıda akış çalışır.
  Kaynak tarafı CORS veya oturum zorunluluğu uygularsa oynatıcı çalışmayabilir; bağlantı ve
  bilgiler yine listelenir.
* Kapak resmi olmayan kartlar, CSS arka planıyla boşluksuz görünür.

## Katkı / test

```bash
pip install -r requirements.txt && pip install pytest
python -m pytest -q
```

Testler ağa çıkmaz; archive.org'ın gerçek metadata biçiminden üretilmiş sabitler ve
`FakeFetcher` kullanır. Kaçış senaryoları da test edilir: `</script>` enjeksiyonu,
göreli/kaçışlı medya yolları, robots.txt engelleri, boş kaynakta kataloğun korunması.
