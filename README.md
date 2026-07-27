# otoXtra - Telegram Entegrasyonlu Reels + Threads Asistanı 🏎️

Yapay zeka ile otomatik Reels ve Threads içeriği üreten, üretilen içerikleri Telegram'a ayrı mesajlar olarak gönderen uygulama.

## ✨ Özellikler

- 🎥 Video analizi ile otomatik içerik üretimi
- 🎙️ Seslendirme metni ve ses dosyası oluşturma
- 📱 Reels açıklaması ve hashtag'ler
- 🎬 Kapak başlığı alternatifleri
- 🧵 Threads için optimize edilmiş açıklama
- 📤 **Telegram entegrasyonu** - Tüm içerikleri ayrı mesajlar olarak Telegram'a gönderir

## 🚀 GitHub Codespaces ile Kullanım

1. Bu repoyu GitHub'da açın
2. `Code` > `Codespaces` > `Create codespace on main` butonuna tıklayın
3. Codespaces açıldığında terminalde otomatik olarak bağımlılıklar yüklenecektir
4. Streamlit uygulaması otomatik olarak başlayacaktır

## ⚙️ Ayarlar

### 1. Gemini API Anahtarları

GitHub Codespaces'ta:
1. Sol menüden `Variables and secrets` > `Secrets` sekmesine gidin
2. `New secret` butonuna tıklayın
3. `GEMINI_KEYS` adında bir secret oluşturun ve aşağıdaki formatı kullanın:

```toml
[GEMINI_KEYS]
"email1@gmail.com" = "AIzaSy...anahtar1..."
"email2@gmail.com" = "AIzaSy...anahtar2..."
```

### 2. Telegram Bot Ayarları (Opsiyonel)

Telegram entegrasyonunu kullanmak isterseniz:

1. **Bot Token Alın:**
   - Telegram'da [@BotFather](https://t.me/BotFather) ile konuşun
   - `/newbot` komutu ile yeni bot oluşturun
   - Size verilen token'ı kopyalayın

2. **Chat ID Bulun:**
   - Bot'unuzu bir gruba ekleyin veya birebir konuşma başlatın
   - Grubun/chat'in ID'sini bulun (örn: `-1001234567890`)

3. **GitHub Secret Ekleyin:**
   - `TELEGRAM_BOT_TOKEN` secret'ını oluşturun ve bot token'ınızı yapıştırın
   - `TELEGRAM_CHAT_ID` secret'ını olutsurun ve chat ID'nizi yapıştırın

Veya `.streamlit/secrets.toml` dosyasına ekleyin:

```toml
[TELEGRAM]
BOT_TOKEN = "1234567890:AAHkLxXxXxXxXxXxXxXxXxXxXxXxXxXxXxX"
CHAT_ID = "-1001234567890"
```

## 📤 Telegram'a Gönderilen İçerikler

Uygulama başarıyla çalıştığında, eğer Telegram ayarları yapılandırılmışsa, aşağıdaki içerikleri **ayrı ayrı mesajlar** olarak Telegram'a gönderir:

1. 🎙️ **Ses dosyası** - Voice message olarak
2. 📝 **Seslendirme metni** - Metin mesajı olarak
3. 📱 **Reels açıklaması** - Hashtag'ler ile birlikte
4. 🎬 **Kapak başlıkları** - 5 alternatif başlık
5. 🧵 **Threads açıklaması** - Sohbet havasında kısa metin

## 📁 Dosya Yapısı

```
/workspace
├── app.py                      # Ana uygulama
├── requirements.txt            # Python bağımlılıkları
├── .streamlit/
│   └── secrets.toml.example    # Secrets şablonu
├── kurallar.txt                # İçerik üretim kuralları
├── sistem_talimati.txt         # Sistem prompt'u
├── video_analiz_promptu.txt    # Video analiz prompt'u
├── threads_promptu.txt         # Threads üretim prompt'u
└── guncellik_talimati.txt      # Güncellik talimatı
```

## 🔧 Yerel Geliştirme

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# Uygulamayı çalıştır
streamlit run app.py
```

## 📝 Notlar

- Telegram entegrasyonu opsiyoneldir. API anahtarları girilmezse uygulama normal çalışmaya devam eder.
- Her üretim sonrası içerikler otomatik olarak Telegram'a gönderilir.
- Geçmiş üretimler uygulamada saklanır ve tekrar görüntülenebilir.

## 🛠️ Teknolojiler

- Python
- Streamlit
- Google Gemini AI
- Telegram Bot API