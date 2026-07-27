# 🔐 GitHub Secrets Kurulum Rehberi

Bu uygulama API anahtarlarını **GitHub Secrets** üzerinden yönetir. Böylece şifreleriniz kodda görünmez ve çok daha güvenli olur.

## 📋 Adım 1: GitHub Secrets Ekleme

1. GitHub reponuza gidin
2. **Settings** sekmesine tıklayın
3. Sol menüden **Secrets and variables** → **Codespaces** (veya **Actions**) seçin
4. **New repository secret** butonuna tıklayın

### Eklemeniz Gereken 3 Secret:

| Secret Name | Değer (Örnek) | Nereden Bulunur? |
|-------------|---------------|------------------|
| `GEMINI_API_KEY` | `AIzaSyD...` | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `TELEGRAM_BOT_TOKEN` | `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz` | Telegram'da [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | `-100123456789` | Telegram'da [@userinfobot](https://t.me/userinfobot) veya kanal ID'si |

---

## 🎯 Detaylı Açıklamalar

### 1️⃣ GEMINI_API_KEY
- Google AI Studio'ya git: https://aistudio.google.com/app/apikey
- "Create API Key" butonuna tıkla
- Oluşan anahtarı kopyala ve GitHub'a yapıştır

### 2️⃣ TELEGRAM_BOT_TOKEN
- Telegram'da [@BotFather](https://t.me/BotFather) ile konuş
- `/newbot` komutunu gönder
- Botuna bir isim ver
- Sana verdiği token'ı kopyala (örnek: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 3️⃣ TELEGRAM_CHAT_ID
#### Özel sohbet için:
- Telegram'da [@userinfobot](https://t.me/userinfobot) başlat
- `/start` de
- Sana gelen `Id:` değerini kopyala

#### Kanal için:
- Kanalını oluştur
- Botunu kanala admin olarak ekle
- Kanal ID'si genellikle `-100` ile başlar (örnek: `-1001234567890`)

---

## 🚀 Codespaces'i Başlatma

1. Repo ana sayfasında yeşil **Code** butonuna tıkla
2. **Codespaces** sekmesine geç
3. **Create codespace on main** de
4. Terminal açılınca otomatik başlayacak, başlamazsa:
   ```bash
   streamlit run app.py
   ```

---

## ✅ Test Etme

1. Codespaces açıldıktan sonra Streamlit arayüzü yüklenecek
2. Konu girip "ÜRET" butonuna bas
3. Eğer her şey doğruysa:
   - ✅ İçerikler ekranda görünecek
   - ✅ Ses dosyası oluşturulacak
   - ✅ 5 ayrı mesaj Telegram'ına gelecek

---

## ⚠️ Hata Çözümü

### "API anahtarları bulunamadı" hatası alıyorsan:
- Secrets'ları doğru eklediğinden emin ol
- Codespaces'i yeniden başlat
- Veya `.streamlit/secrets.toml` dosyasını yerel test için kullan

### Telegram mesajları gelmiyorsa:
- BOT_TOKEN ve CHAT_ID'yi kontrol et
- Bot'un kanalında admin yetkisi var mı kontrol et
- Chat ID'nin doğru formatta olduğundan emin ol (`-` işareti önemli!)

---

## 📁 Yerel Test İçin (Opsiyonel)

Eğer GitHub Secrets yerine yerel test yapmak istersen:

```bash
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Sonra `.streamlit/secrets.toml` dosyasını açıp kendi anahtarlarını ekle.

**NOT:** `secrets.toml` dosyasını asla GitHub'a commit etme! (.gitignore'da zaten var)
