<p align="center"><img src="assets/logo.png" width="112" alt="YDikte logosu"></p>

<h1 align="center">YDikte</h1>

<p align="center">Windows için sistem genelinde yapay zekâlı dikte.<br>Tuşa bas, konuş, bırak: metin imlecin olduğu yere yazılır.<br>Hesap yok, telemetri yok, yerel modelle internetsiz çalışır.</p>

## Kullanım

| Yaptığın | Sonuç |
|---|---|
| **Sağ Ctrl**'yi basılı tut, konuş, bırak | Kayıt, yazıya dökme, metni yazma |
| **Çift dokun** | Eller serbest kayıt, hiçbir şey basılı tutulmaz |
| Eller serbestteyken **bir kez daha dokun** | Durdurur ve metni yazar |
| **Esc** | Kaydı atar veya süren yazıya dökmeyi öldürür. Esc odaktaki uygulamaya da ulaşır |
| 5 dakika dolunca | Kayıt kendiliğinden durur ve metin yazılır |

Ekranın altındaki küçük gösterge kaydın açık olduğunu ve modu gösterir: kırmızı `Dinliyor`, yeşil `Eller serbest 0:42`, mavi `Yazıya dökülüyor…`. Sağ Ctrl+C gibi kısayollar normal çalışmaya devam eder, dikte sayılmaz.

**Ayarlar penceresi:** tray simgesine sol tıkla veya YDikte zaten çalışırken kısayola yeniden çift tıkla. Kısayol, motor, dil, mikrofon, API anahtarları ve davranışlar buradan değiştirilir, değişiklikler kendiliğinden uygulanır. Tray simgesine sağ tıklayınca açma/kapama ve çıkış menüsü gelir.

## Kurulum

Python 3.11 veya üstü gerekir. Başka paket gerekmez.

```
python install.py --gpu     # NVIDIA kart için. 685 MB indirir, yaklaşık 1,2 GB yer kaplar
python install.py           # veya yalnızca CPU. 8 MB indirir
```

Betik whisper.cpp'yi ve `small` modeli (488 MB) indirir, SHA-256 ile doğrular ve Masaüstüne `YDikte` kısayolu koyar. Daha doğru ama daha yavaş sonuç için `--model medium` ekle (1,5 GB).

Metin temizleme için API anahtarını ayarlar penceresine yapıştır. Anahtarlar `.env` dosyasına yazılır, git'e girmez ve pencerede bir daha gösterilmez. ChatGPT aboneliği API anahtarı değildir: OpenAI anahtarı platform.openai.com'dan alınır ve ayrı faturalandırılır. Anahtar veya internet yoksa ham metin yazılır, dikte yine çalışır.

## Terminaller ve yönetici pencereleri

**Terminaller (Claude Code dahil).** Ham modda çalışan bir konsol uygulamasına Ctrl+V metin olarak değil kontrol karakteri olarak ulaşır, yani yapıştırma olmaz. YDikte terminal pencerelerini tanır ve metni tuş tuş yazar. Türkçe karakterler korunur, satır sonları boşluğa çevrilir ki metin kendiliğinden gönderilmesin. Metin yine panoda kalır. `[insert] method` ile `auto`, `paste` veya `type` seçilebilir.

**Yönetici olarak açılmış pencereler.** Windows, normal bir programın yönetici penceresindeki tuşları görmesini de oraya tuş göndermesini de engeller. Odaktaki pencere böyleyse YDikte bir kez uyarır. İki çözüm var:

1. **Terminali normal aç (önerilen).** Yönetici yetkisi gerekmiyorsa sorun kendiliğinden kalkar.
2. **Ayarlar > Yönetici pencerelerinde de çalış.** YDikte yükseltilmiş çalışır ve her başlatmada Windows onay ister.

YDikte bunun için onay istemeyen bir zamanlanmış görev oluşturmaz. Kod, normal programların da yazabildiği bir klasörde duruyor; sessiz yükseltme, bilgisayardaki herhangi bir programa yönetici yetkisine giden bir yol açardı.

## İzinler

**Accessibility** ve **Input Monitoring**, macOS kavramlarıdır. Windows'ta karşılıkları yoktur ve izin penceresi çıkmaz. Windows'ta bakman gerekenler:

| Konu | Ne yapmalı |
|---|---|
| **Mikrofon** | *Ayarlar > Gizlilik ve güvenlik > Mikrofon*: "Mikrofon erişimi" ve **"Masaüstü uygulamalarının mikrofonunuza erişmesine izin verin"** açık olmalı. Test: `python ydikte.pyw --mic-test` |
| **Smart App Control** | Açıksa da kapatman gerekmez. YDikte derlenmiş `.exe` değil, imzalı `pythonw.exe` üzerinde çalışan Python'dur. `whisper-cli.exe` imzasızdır; Windows ileride engellerse uyarı çıkar, o zaman motoru Groq veya OpenAI yap |
| **Antivirüs** | Sistem geneli klavye kancası kullanan programlar bazen işaretlenir. Kanca yalnızca tuş kodlarına bakar, yazılanı saklamaz (`ydikte/hook.py`) |
| **Tam ekran oyunlar** | Özel tam ekran modunda gösterge görünmeyebilir, dikte yine çalışır |

## Ayar dosyası

Ayarlar penceresinde olmayan her şey `config.toml` içinde, her seçenek orada açıklanmıştır. Kaydedince birkaç saniye içinde uygulanır.

```toml
hotkey = "rctrl"            # "f13", "capslock", "ctrl+win", "ctrl+shift+space", "vk:0x7C", "sc:0x5D"

[transcription]
backend = "local"           # local | groq | openai | auto
language = "auto"           # kısa kayıtlarda yanlış algılanırsa "tr"

[insert]
method = "auto"             # auto | paste | type
restore_clipboard = false   # true: yapıştırdıktan sonra eski pano içeriğini geri getirir

[llm]
provider = "auto"           # auto | openrouter | openai | groq | custom | none

[app]
run_as_admin = false        # yönetici pencerelerinde de çalış
```

**Fn tuşu:** Çoğu dizüstünde Fn klavye donanımında işlenir ve Windows onu hiç görmez, bu yüzden hiçbir program yakalayamaz. Seninkini denemek için `python ydikte.pyw --keytest` çalıştırıp Fn'e bas. Satır çıkarsa o kodu `hotkey` olarak yaz, çıkmazsa başka bir tuş seç.

**Sağ Alt kullanma:** Türkçe klavyede o tuş AltGr'dir, `@` gibi karakterler için gerekir.

## Gizlilik

- `local` modunda ses bilgisayardan çıkmaz. Geçici dosya yazıya dökmeden sonra silinir.
- Bulut motorunu seçersen ses o sağlayıcıya gider. Anahtar varsa temizleme için metin seçili LLM sağlayıcısına gider. Bunların dışında ağ bağlantısı yapılmaz.
- Motor `Yerel` ve temizleme `Kapalı` iken hiçbir şey dışarı çıkmaz.
- `ydikte.log` yalnızca süre, ses seviyesi ve karakter sayısı tutar, söylediklerini tutmaz.
- `restore_clipboard = true` iken metin Win+V geçmişine de girmez.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| Kısayol bir pencerede hiç çalışmıyor | O pencere yönetici olarak açılmıştır, yukarıdaki bölüme bak |
| Bilgisayar açıldıktan sonraki ilk dikte çok yavaş | GPU sürümünün DLL'leri yükleniyor, bir kez yaşanır. Testte ilk çalıştırma 15-110 sn, sonrakiler yaklaşık 4 sn sürdü |
| `Ses duyulmadı` | Mikrofon sessiz veya yanlış cihaz seçili. Ayarlardan mikrofonu değiştir. `ydikte.log` içindeki `loudness` değeri 30'un altındaysa YDikte onu sessizlik sayar |
| Türkçe yanlış algılanıyor | Dili `Türkçe` yap, gerekirse `install.py --gpu --model medium` |
| Bir uygulamaya yapıştırmıyor | Metin panodadır, Ctrl+V'ye bas. Kalıcı çözüm olarak `method = "type"` dene |

## Geliştirme

```
python -m unittest discover -s tests -v          # mantık testleri, sahte API sunucusuyla
python tests/e2e.py konusma.wav                  # gerçek masaüstünde uçtan uca (16 kHz mono WAV, Node gerekir)
python tools/make_logo.py                        # logoyu ve tray simgelerini yeniden çizer
```

`e2e.py` kendi pencerelerini açar ve bir süre klavye odağını alır, çalışırken klavyeye dokunma.

Kod `ydikte/` altında: `machine.py` durum makinesi, `hotkey.py` tuş eşleme, `hook.py` klavye kancası, `audio.py` mikrofon, `pipeline.py` yazıya dökme ve temizleme, `insert.py` pano, yapıştırma ve yazma, `elevate.py` yönetici modu, `pill.py` gösterge, `tray.py` tray menüsü, `settings_ui.py` ayarlar penceresi, `gfx.py` çizim, `app.py` hepsini bağlar.
