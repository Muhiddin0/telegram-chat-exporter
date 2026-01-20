# 📦 Telegram Chat Exporter

Telegram kanal va guruhlardan xabarlarni export qilish va chiroyli web interfaceda ko'rsatish uchun vosita.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Pyrogram](https://img.shields.io/badge/Pyrogram-2.0+-green.svg)

## ✨ Xususiyatlar

- 📥 **Barcha xabarlarni yuklab olish** - matnlar, rasmlar, videolar, audio, fayllar va boshqalar
- 🖼️ **Media yuklab olish** - barcha media fayllarini lokal saqlash
- 🌐 **Web Viewer** - zamonaviy va chiroyli web interfeys
- 📊 **Statistika** - kanal/guruh bo'yicha batafsil statistika
- 🔍 **Qidiruv** - xabarlar bo'yicha qidirish imkoniyati
- 📱 **Responsive dizayn** - barcha qurilmalarda ko'rinishi yaxshi

## 🚀 O'rnatish

### 1. Repository clone qilish

```bash
git clone https://github.com/user/telegram-chat-exporter.git
cd telegram-chat-exporter
```

### 2. Virtual muhit yaratish

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# yoki
.venv\Scripts\activate  # Windows
```

### 3. Dependencylarni o'rnatish

```bash
pip install -r requirements.txt
```

### 4. `.env` faylini yaratish

```bash
cp .env.example .env
```

`.env` faylini tahrirlang va Telegram API credential'laringizni kiriting:

```env
API_ID=your_api_id
API_HASH=your_api_hash
```

> 📝 API ID va API Hash olish uchun [my.telegram.org](https://my.telegram.org) ga kiring.

## 📖 Foydalanish

### Asosiy foydalanish

```bash
python exporter.py
```

Dastur sizdan kanal yoki guruh username/ID so'raydi:

- Username orqali: `@durov` yoki `durov`
- ID orqali: `-1001234567890`

### Eksport sozlamalari

`exporter.py` faylida quyidagi sozlamalarni o'zgartirishingiz mumkin:

```python
DOWNLOAD_MEDIA = True  # Media fayllarni yuklab olish
MAX_FILE_SIZE_MB = 100  # Maksimal fayl hajmi (MB)
```

## 📁 Fayl strukturasi

Export qilingandan so'ng quyidagi struktura yaratiladi:

```
exports/
└── channel_name_20240120_123456/
    ├── index.html          # Web viewer
    ├── chat_data.json      # Barcha ma'lumotlar JSON formatda
    ├── photos/             # Rasmlar
    ├── videos/             # Videolar
    ├── audio/              # Audio fayllar
    ├── files/              # Hujjatlar
    ├── voices/             # Ovozli xabarlar
    ├── round_videos/       # Dumaloq videolar
    ├── stickers/           # Stikerlar
    └── animations/         # GIF animatsiyalar
```

## 🌐 Web Viewer xususiyatlari

- 🎨 **Zamonaviy dizayn** - Dark mode, glassmorphism effektlari
- 📊 **Statistika paneli** - xabarlar soni, media turlari bo'yicha statistika
- 🔍 **Qidiruv** - real-time xabar qidirish
- 📋 **Filtrlar** - media turlari bo'yicha filtrlash
- 📱 **Responsive** - mobil qurilmalarga moslashgan
- ♾️ **Infinite scroll** - sahifama-sahifa yuklash

## 📊 Qo'llab-quvvatlanadigan media turlari

| Turi                | Yuklab olish | Ko'rsatish |
| ------------------- | ------------ | ---------- |
| 🖼️ Rasmlar          | ✅           | ✅         |
| 🎬 Videolar         | ✅           | ✅         |
| 🎵 Audio            | ✅           | ✅         |
| 📁 Fayllar          | ✅           | ✅         |
| 🎤 Ovozli xabarlar  | ✅           | ✅         |
| ⭕ Dumaloq videolar | ✅           | ✅         |
| 😀 Stikerlar        | ✅           | ✅         |
| 🎞️ GIF              | ✅           | ✅         |
| 📊 So'rovnomalar    | ❌           | ✅         |
| 👤 Kontaktlar       | ❌           | ✅         |
| 📍 Joylashuv        | ❌           | ✅         |
| 🔗 Web sahifalar    | ❌           | ✅         |

## ⚠️ Eslatmalar

1. **Rate Limiting** - Telegram API cheklovlar qo'yadi. Katta kanallarda export sekin bo'lishi mumkin.
2. **Storage** - Media yuklash ko'p joy olishi mumkin. Yetarli diskka ega ekanligingizga ishonch hosil qiling.
3. **Privacy** - Faqat siz a'zo bo'lgan kanal/guruhlarni export qila olasiz.

## 🛠️ Texnologiyalar

- **Python 3.10+**
- **Pyrogram** - Telegram MTProto API client
- **HTML/CSS/JavaScript** - Web viewer

## 📄 Litsenziya

MIT License

## 🤝 Hissa qo'shish

Pull requestlar qabul qilinadi! Katta o'zgarishlar uchun, avval issue oching.

---

<p align="center">
  Made with ❤️ for Telegram
</p>
