"""
Telegram Chat Exporter - Barcha contentlarni yuklab olish va web interfaceda ko'rsatish
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, asdict
import humanize
import re

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.enums import MessageMediaType
from dotenv import load_dotenv
from backblaze import upload_to_b2

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# Export sozlamalari
DOWNLOAD_MEDIA = True
MAX_FILE_SIZE_MB = 100  # Maksimal yuklab olish uchun fayl hajmi (MB)


@dataclass
class ExportStats:
    """Export statistikasi"""

    total_messages: int = 0
    text_messages: int = 0
    photos: int = 0
    videos: int = 0
    audios: int = 0
    documents: int = 0
    voices: int = 0
    video_notes: int = 0
    stickers: int = 0
    animations: int = 0
    polls: int = 0
    contacts: int = 0
    locations: int = 0
    web_pages: int = 0
    downloaded_files: int = 0
    failed_downloads: int = 0
    download_size_bytes: int = 0


def format_file_size(size_bytes: int) -> str:
    """Fayl hajmini chiroyli formatda qaytaradi"""
    if size_bytes is None:
        return "N/A"
    return humanize.naturalsize(size_bytes)


def get_media_folder(media_type: str) -> str:
    """Media turi uchun papka nomini qaytaradi"""
    folders = {
        "photo": "photos",
        "video": "videos",
        "audio": "audio",
        "document": "files",
        "voice": "voices",
        "video_note": "round_videos",
        "sticker": "stickers",
        "animation": "animations",
    }
    return folders.get(media_type, "other")


class TelegramExporter:
    """Telegram chat exporteri"""

    def __init__(self, chat_id: str | int, output_dir: str = None):
        self.chat_id = chat_id
        self.app = Client("my_account", api_id=API_ID, api_hash=API_HASH)
        self.output_dir = Path(output_dir) if output_dir else None
        self.stats = ExportStats()
        self.messages: list[dict] = []
        self.chat_info: dict = {}
        self.checkpoint_file: Optional[Path] = None
        self.checkpoint_data: dict = {}
        self.chat_folder_name: str = ""

    def _setup_output_dir(self):
        """Chiqish papkasini yaratadi"""
        if not self.output_dir:
            # Chat nomi allaqachon o'rnatilgan bo'lishi kerak (export metodida)
            if not self.chat_folder_name:
                # Fallback: agar chat_folder_name o'rnatilmagan bo'lsa
                chat_name = self.chat_info.get("title") or self.chat_info.get("username") or str(self.chat_id)
                safe_name = re.sub(r'[^\w\s-]', '', chat_name).strip()
                safe_name = re.sub(r'[-\s]+', '_', safe_name)
                if not safe_name:
                    safe_name = f"chat_{self.chat_id}"
                self.chat_folder_name = safe_name
            
            self.output_dir = Path(
                f"exports/{self.chat_folder_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Checkpoint faylini yaratish
        self.checkpoint_file = self.output_dir / "checkpoint.json"
        self._load_checkpoint()

        # Media papkalarini yaratish (vaqtinchalik saqlash uchun)
        media_folders = [
            "photos",
            "videos",
            "audio",
            "files",
            "voices",
            "round_videos",
            "stickers",
            "animations",
        ]
        for folder in media_folders:
            (self.output_dir / folder).mkdir(exist_ok=True)

    def _get_media_unique_id(self, message: Message, media_type: str) -> Optional[str]:
        """Media uchun unique ID ni olish (checkpoint uchun)"""
        try:
            if media_type == "photo" and message.photo:
                return message.photo.file_unique_id
            elif media_type == "video" and message.video:
                return message.video.file_unique_id
            elif media_type == "audio" and message.audio:
                return message.audio.file_unique_id
            elif media_type == "document" and message.document:
                return message.document.file_unique_id
            elif media_type == "voice" and message.voice:
                return message.voice.file_unique_id
            elif media_type == "video_note" and message.video_note:
                return message.video_note.file_unique_id
            elif media_type == "sticker" and message.sticker:
                return message.sticker.file_unique_id
            elif media_type == "animation" and message.animation:
                return message.animation.file_unique_id
        except:
            pass
        # Fallback: message ID + media type
        return f"{message.id}_{media_type}"

    def _is_media_processed(self, unique_id: str) -> bool:
        """Media allaqachon yuklab olingan va yuklanganligini tekshirish"""
        return unique_id in self.checkpoint_data.get("processed_media", set())

    def _mark_media_processed(self, unique_id: str, s3_url: str):
        """Media ni qayta ishlangan deb belgilash"""
        if "processed_media" not in self.checkpoint_data:
            self.checkpoint_data["processed_media"] = {}
        self.checkpoint_data["processed_media"][unique_id] = s3_url
        self._save_checkpoint()

    def _load_checkpoint(self):
        """Checkpoint faylini yuklash"""
        if self.checkpoint_file and self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    self.checkpoint_data = json.load(f)
                processed_count = len(self.checkpoint_data.get("processed_media", {}))
                print(f"   📋 Checkpoint yuklandi: {processed_count} ta media allaqachon qayta ishlangan")
            except Exception as e:
                print(f"   ⚠️ Checkpoint yuklashda xato: {e}")
                self.checkpoint_data = {}
        else:
            self.checkpoint_data = {
                "last_message_id": None,
                "processed_media": {}
            }

    def _save_checkpoint(self):
        """Checkpoint ni saqlash"""
        if self.checkpoint_file:
            try:
                with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump(self.checkpoint_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"   ⚠️ Checkpoint saqlashda xato: {e}")

    async def _download_media(self, message: Message, media_type: str) -> Optional[str]:
        """Media faylni yuklab oladi va S3 ga yuklaydi"""
        if not DOWNLOAD_MEDIA:
            return None

        try:
            # Media unique ID ni olish
            media_unique_id = self._get_media_unique_id(message, media_type)
            
            # Agar allaqachon qayta ishlangan bo'lsa, S3 URL ni qaytarish
            if media_unique_id and self._is_media_processed(media_unique_id):
                s3_url = self.checkpoint_data["processed_media"][media_unique_id]
                print(f"   ⏭️ Media allaqachon yuklangan: {media_unique_id[:20]}...")
                return s3_url

            # Fayl hajmini tekshirish
            file_size = None
            if media_type == "photo" and message.photo:
                file_size = message.photo.file_size
            elif media_type == "video" and message.video:
                file_size = message.video.file_size
            elif media_type == "audio" and message.audio:
                file_size = message.audio.file_size
            elif media_type == "document" and message.document:
                file_size = message.document.file_size
            elif media_type == "voice" and message.voice:
                file_size = message.voice.file_size
            elif media_type == "video_note" and message.video_note:
                file_size = message.video_note.file_size
            elif media_type == "sticker" and message.sticker:
                file_size = message.sticker.file_size
            elif media_type == "animation" and message.animation:
                file_size = message.animation.file_size

            if file_size and file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                print(
                    f"   ⚠️ Fayl juda katta, o'tkazib yuborildi: {format_file_size(file_size)}"
                )
                return None

            folder = get_media_folder(media_type)
            download_path = self.output_dir / folder

            # Faylni yuklab olish
            file_path = await message.download(file_name=str(download_path) + "/")

            if file_path:
                file_path_obj = Path(file_path)
                file_name = file_path_obj.name
                
                # S3 ga yuklash
                object_name = f"{folder}/{file_name}"
                print(f"   📤 S3 ga yuklashga tayyorlanmoqda: {file_name} ({format_file_size(file_size) if file_size else 'N/A'})")
                success, s3_url = upload_to_b2(
                    str(file_path),
                    object_name=object_name,
                    chat_folder=self.chat_folder_name
                )
                
                if success and s3_url:
                    # Media ni qayta ishlangan deb belgilash
                    if media_unique_id:
                        # Checkpoint da S3 URL ni saqlash (keyinroq foydalanish uchun)
                        self._mark_media_processed(media_unique_id, s3_url)
                    
                    # Lokal faylni saqlab qolish (zip yuklab olish uchun)
                    # Fayl S3 ga yuklangan, lekin lokal nusxasi ham kerak
                    print(f"   💾 Lokal fayl saqlanib qoldi (zip uchun): {file_name}")
                    
                    self.stats.downloaded_files += 1
                    if file_size:
                        self.stats.download_size_bytes += file_size
                    
                    # Nisbiy yo'l qaytarish (zip yuklab olish uchun)
                    # Format: folder/filename (masalan: photos/photo_123.jpg)
                    relative_path = f"{folder}/{file_name}"
                    return relative_path
                else:
                    print(f"   ⚠️ S3 ga yuklash muvaffaqiyatsiz: {file_name}")
                    print(f"   💾 Lokal fayl saqlanib qoldi: {file_path}")
                    # Agar S3 ga yuklash muvaffaqiyatsiz bo'lsa, lokal faylni saqlab qolish
                    return f"{folder}/{file_name}"

        except Exception as e:
            self.stats.failed_downloads += 1
            print(f"   ❌ Yuklab olishda xato: {e}")

        return None

    def _serialize_message(
        self, message: Message, media_url: str = None
    ) -> dict[str, Any]:
        """Message ob'yektini dict ga o'tkazadi"""
        data = {
            "id": message.id,
            "date": message.date.isoformat() if message.date else None,
            "chat_id": message.chat.id if message.chat else None,
            "from_user": None,
            "sender_chat": None,
            "text": message.text,
            "caption": message.caption,
            "media_type": message.media.name if message.media else None,
            "media_url": media_url,  # S3 URL yoki lokal fayl yo'li
            "local_file": media_url,  # Qayta ishlash uchun eski nom (backward compatibility)
            "views": message.views,
            "forwards": message.forwards,
            "edit_date": message.edit_date.isoformat() if message.edit_date else None,
            "reply_to_message_id": message.reply_to_message_id,
            "forward_from_chat": None,
            "forward_date": (
                message.forward_date.isoformat() if message.forward_date else None
            ),
            "media_group_id": message.media_group_id,
        }

        # Foydalanuvchi ma'lumotlari
        if message.from_user:
            data["from_user"] = {
                "id": message.from_user.id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
                "last_name": message.from_user.last_name,
            }

        # Sender chat ma'lumotlari
        if message.sender_chat:
            data["sender_chat"] = {
                "id": message.sender_chat.id,
                "title": message.sender_chat.title,
                "username": message.sender_chat.username,
            }

        # Forward ma'lumotlari
        if message.forward_from_chat:
            data["forward_from_chat"] = {
                "id": message.forward_from_chat.id,
                "title": message.forward_from_chat.title,
            }

        # Media ma'lumotlari
        if message.media:
            if message.media == MessageMediaType.PHOTO and message.photo:
                data["photo"] = {
                    "file_id": message.photo.file_id,
                    "width": message.photo.width,
                    "height": message.photo.height,
                    "file_size": message.photo.file_size,
                }
            elif message.media == MessageMediaType.VIDEO and message.video:
                data["video"] = {
                    "file_id": message.video.file_id,
                    "width": message.video.width,
                    "height": message.video.height,
                    "duration": message.video.duration,
                    "file_name": message.video.file_name,
                    "mime_type": message.video.mime_type,
                    "file_size": message.video.file_size,
                }
            elif message.media == MessageMediaType.AUDIO and message.audio:
                data["audio"] = {
                    "file_id": message.audio.file_id,
                    "duration": message.audio.duration,
                    "performer": message.audio.performer,
                    "title": message.audio.title,
                    "file_name": message.audio.file_name,
                    "mime_type": message.audio.mime_type,
                    "file_size": message.audio.file_size,
                }
            elif message.media == MessageMediaType.DOCUMENT and message.document:
                data["document"] = {
                    "file_id": message.document.file_id,
                    "file_name": message.document.file_name,
                    "mime_type": message.document.mime_type,
                    "file_size": message.document.file_size,
                }
            elif message.media == MessageMediaType.VOICE and message.voice:
                data["voice"] = {
                    "file_id": message.voice.file_id,
                    "duration": message.voice.duration,
                    "mime_type": message.voice.mime_type,
                    "file_size": message.voice.file_size,
                }
            elif message.media == MessageMediaType.VIDEO_NOTE and message.video_note:
                data["video_note"] = {
                    "file_id": message.video_note.file_id,
                    "length": message.video_note.length,
                    "duration": message.video_note.duration,
                    "file_size": message.video_note.file_size,
                }
            elif message.media == MessageMediaType.STICKER and message.sticker:
                data["sticker"] = {
                    "file_id": message.sticker.file_id,
                    "width": message.sticker.width,
                    "height": message.sticker.height,
                    "emoji": message.sticker.emoji,
                    "set_name": message.sticker.set_name,
                }
            elif message.media == MessageMediaType.ANIMATION and message.animation:
                data["animation"] = {
                    "file_id": message.animation.file_id,
                    "width": message.animation.width,
                    "height": message.animation.height,
                    "duration": message.animation.duration,
                    "file_name": message.animation.file_name,
                    "file_size": message.animation.file_size,
                }
            elif message.media == MessageMediaType.POLL and message.poll:
                data["poll"] = {
                    "id": message.poll.id,
                    "question": message.poll.question,
                    "options": [
                        {"text": opt.text, "voter_count": opt.voter_count}
                        for opt in message.poll.options
                    ],
                    "total_voter_count": message.poll.total_voter_count,
                    "is_closed": message.poll.is_closed,
                }
            elif message.media == MessageMediaType.LOCATION and message.location:
                data["location"] = {
                    "latitude": message.location.latitude,
                    "longitude": message.location.longitude,
                }
            elif message.media == MessageMediaType.CONTACT and message.contact:
                data["contact"] = {
                    "phone_number": message.contact.phone_number,
                    "first_name": message.contact.first_name,
                    "last_name": message.contact.last_name,
                }
            elif message.media == MessageMediaType.WEB_PAGE and message.web_page:
                data["web_page"] = {
                    "url": message.web_page.url,
                    "title": message.web_page.title,
                    "description": message.web_page.description,
                    "site_name": message.web_page.site_name,
                }

        return data

    def _update_stats(self, message: Message):
        """Statistikani yangilash"""
        self.stats.total_messages += 1

        if message.text and not message.media:
            self.stats.text_messages += 1
        elif message.media:
            media_type = message.media
            if media_type == MessageMediaType.PHOTO:
                self.stats.photos += 1
            elif media_type == MessageMediaType.VIDEO:
                self.stats.videos += 1
            elif media_type == MessageMediaType.AUDIO:
                self.stats.audios += 1
            elif media_type == MessageMediaType.DOCUMENT:
                self.stats.documents += 1
            elif media_type == MessageMediaType.VOICE:
                self.stats.voices += 1
            elif media_type == MessageMediaType.VIDEO_NOTE:
                self.stats.video_notes += 1
            elif media_type == MessageMediaType.STICKER:
                self.stats.stickers += 1
            elif media_type == MessageMediaType.ANIMATION:
                self.stats.animations += 1
            elif media_type == MessageMediaType.POLL:
                self.stats.polls += 1
            elif media_type == MessageMediaType.CONTACT:
                self.stats.contacts += 1
            elif media_type == MessageMediaType.LOCATION:
                self.stats.locations += 1
            elif media_type == MessageMediaType.WEB_PAGE:
                self.stats.web_pages += 1

    async def export(self):
        """Asosiy export funksiyasi"""
        print("=" * 60)
        print("  🚀 TELEGRAM CHAT EXPORTER")
        print("=" * 60)
        print(f"\n📥 Chat tarixini yuklab olish boshlanmoqda: {self.chat_id}")

        async with self.app:
            # Chat ma'lumotlarini olish
            try:
                chat = await self.app.get_chat(self.chat_id)
                self.chat_info = {
                    "id": chat.id,
                    "title": chat.title or chat.first_name,
                    "username": chat.username,
                    "type": chat.type.name if chat.type else None,
                    "members_count": chat.members_count,
                    "description": chat.description,
                    "linked_chat_id": chat.linked_chat.id if chat.linked_chat else None,
                }
                print(
                    f"✅ Chat topildi: {self.chat_info['title'] or self.chat_info['username']}"
                )

                # Chat nomidan foydalanish
                chat_name = self.chat_info.get("title") or self.chat_info.get("username") or str(self.chat_id)
                # Xavfsiz fayl nomi yaratish
                safe_name = re.sub(r'[^\w\s-]', '', chat_name).strip()
                safe_name = re.sub(r'[-\s]+', '_', safe_name)
                if not safe_name:
                    safe_name = f"chat_{self.chat_id}"
                self.chat_folder_name = safe_name

                # Papkani yaratish
                self._setup_output_dir()

            except Exception as e:
                print(f"❌ Chat topilmadi: {e}")
                return

            # Xabarlarni yuklash
            print("\n📨 Xabarlar yuklanmoqda...")
            
            # Checkpoint dan davom ettirish
            last_message_id = self.checkpoint_data.get("last_message_id")
            resume_from_checkpoint = last_message_id is not None
            
            if resume_from_checkpoint:
                print(f"   🔄 Checkpoint dan davom ettirilmoqda (message ID: {last_message_id})...")

            async for message in self.app.get_chat_history(self.chat_id):
                # Checkpoint dan davom ettirish
                if resume_from_checkpoint:
                    if message.id == last_message_id:
                        resume_from_checkpoint = False
                        print(f"   ✅ Checkpoint dan davom ettirildi")
                    else:
                        continue
                
                self._update_stats(message)

                # Media yuklab olish
                media_url = None
                if message.media and DOWNLOAD_MEDIA:
                    media_type = None
                    if message.photo:
                        media_type = "photo"
                    elif message.video:
                        media_type = "video"
                    elif message.audio:
                        media_type = "audio"
                    elif message.document:
                        media_type = "document"
                    elif message.voice:
                        media_type = "voice"
                    elif message.video_note:
                        media_type = "video_note"
                    elif message.sticker:
                        media_type = "sticker"
                    elif message.animation:
                        media_type = "animation"

                    if media_type:
                        media_url = await self._download_media(message, media_type)

                # Xabarni qo'shish
                msg_data = self._serialize_message(message, media_url)
                self.messages.append(msg_data)

                # Checkpoint ni yangilash
                self.checkpoint_data["last_message_id"] = message.id
                if self.stats.total_messages % 50 == 0:
                    self._save_checkpoint()

                # Progress
                if self.stats.total_messages % 100 == 0:
                    print(f"   ✓ {self.stats.total_messages} ta xabar yuklandi...")

        # Xabarlarni teskari tartibga o'tkazish (eski -> yangi)
        self.messages.reverse()

        print(f"\n✅ Jami {self.stats.total_messages} ta xabar yuklandi!")
        print(
            f"📦 {self.stats.downloaded_files} ta fayl yuklandi ({format_file_size(self.stats.download_size_bytes)})"
        )

        # Yakuniy checkpoint ni saqlash
        self._save_checkpoint()

        # Ma'lumotlarni saqlash
        self._save_data()

        # Web interfeys yaratish
        self._generate_web_viewer()

        # Barcha export fayllarini S3 ga yuklash
        self._upload_export_to_s3()

        print(f"\n🎉 Export muvaffaqiyatli yakunlandi!")
        print(f"📂 Papka: {self.output_dir}")
        print(f"🌐 Web viewer: {self.output_dir / 'index.html'}")

    def _save_data(self):
        """Ma'lumotlarni JSON ga saqlash"""
        export_data = {
            "export_date": datetime.now().isoformat(),
            "chat_info": self.chat_info,
            "statistics": asdict(self.stats),
            "total_messages": len(self.messages),
            "messages": self.messages,
        }

        # JSON faylga saqlash
        json_path = self.output_dir / "chat_data.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        print(f"💾 Ma'lumotlar saqlandi: {json_path}")
        print(f"📊 Fayl hajmi: {format_file_size(json_path.stat().st_size)}")

    def _upload_export_to_s3(self):
        """Barcha export fayllarini S3 ga yuklash"""
        print(f"\n📤 Export fayllarini S3 ga yuklash boshlanmoqda...")
        
        files_to_upload = [
            ("chat_data.json", "chat_data.json"),
            ("index.html", "index.html"),
            ("checkpoint.json", "checkpoint.json"),
        ]
        
        uploaded_urls = {}
        
        for local_filename, s3_filename in files_to_upload:
            file_path = self.output_dir / local_filename
            if file_path.exists():
                try:
                    # object_name ni to'g'ri formatda yaratish
                    object_name = f"{self.chat_folder_name}/{s3_filename}"
                    success, s3_url = upload_to_b2(
                        str(file_path),
                        object_name=object_name,
                        chat_folder=None  # object_name da allaqachon chat_folder bor
                    )
                    
                    if success and s3_url:
                        uploaded_urls[local_filename] = s3_url
                        print(f"   ✅ {local_filename} S3 ga yuklandi")
                    else:
                        print(f"   ⚠️ {local_filename} S3 ga yuklashda xato")
                except Exception as e:
                    print(f"   ❌ {local_filename} yuklashda xato: {e}")
            else:
                print(f"   ⚠️ {local_filename} topilmadi")
        
        # S3 URL larni saqlash
        if uploaded_urls:
            s3_info = {
                "s3_base_url": uploaded_urls.get("index.html", "").rsplit("/", 1)[0] if uploaded_urls.get("index.html") else "",
                "files": uploaded_urls,
                "upload_date": datetime.now().isoformat()
            }
            
            s3_info_path = self.output_dir / "s3_info.json"
            with open(s3_info_path, "w", encoding="utf-8") as f:
                json.dump(s3_info, f, ensure_ascii=False, indent=2)
            
            # s3_info.json ni ham S3 ga yuklash
            try:
                s3_info_object_name = f"{self.chat_folder_name}/s3_info.json"
                success, s3_info_url = upload_to_b2(
                    str(s3_info_path),
                    object_name=s3_info_object_name,
                    chat_folder=None
                )
                if success:
                    print(f"   ✅ s3_info.json S3 ga yuklandi")
            except Exception as e:
                print(f"   ⚠️ s3_info.json yuklashda xato: {e}")
            
            if uploaded_urls.get("index.html"):
                print(f"\n🌐 S3 da Web Viewer URL:")
                print(f"   {uploaded_urls['index.html']}")
                print(f"\n💡 Bu URL ni istalgan joydan ochib chat tarixini ko'rishingiz mumkin!")
                print(f"💡 Barcha media fayllar S3 da saqlanadi va HTML ichida ko'rinadi!")

    def _convert_s3_url_to_relative_path(self, url: str) -> str:
        """S3 URL ni nisbiy yo'lga o'zgartirish (zip yuklab olish uchun)"""
        if not url:
            return url
        
        # Agar URL S3 URL bo'lsa, nisbiy yo'lga o'zgartirish
        if url.startswith('http://') or url.startswith('https://'):
            # S3 URL format: https://bucket.s3.region.backblazeb2.com/chat_folder/folder/filename
            # Nisbiy yo'l: folder/filename
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                path = parsed.path.lstrip('/')
                
                # Chat folder ni olib tashlash (birinchi qism)
                parts = path.split('/', 1)
                if len(parts) > 1:
                    # folder/filename qismini olish
                    relative_path = parts[1]
                    return relative_path
                else:
                    # Agar chat_folder yo'q bo'lsa, to'g'ridan-to'g'ri qaytarish
                    return path
            except Exception:
                # Xatolik bo'lsa, asl URL ni qaytarish
                return url
        
        # Agar allaqachon nisbiy yo'l bo'lsa, o'zgartirmaslik
        return url

    def _generate_web_viewer(self):
        """Web viewer HTML yaratish"""
        # Export ma'lumotlarini tayyorlash
        # Media URL larni nisbiy yo'llarga o'zgartirish
        messages_with_relative_paths = []
        for msg in self.messages:
            msg_copy = msg.copy()
            if msg_copy.get('media_url'):
                msg_copy['media_url'] = self._convert_s3_url_to_relative_path(msg_copy['media_url'])
            if msg_copy.get('local_file'):
                msg_copy['local_file'] = self._convert_s3_url_to_relative_path(msg_copy.get('local_file', ''))
            messages_with_relative_paths.append(msg_copy)
        
        export_data = {
            "export_date": datetime.now().isoformat(),
            "chat_info": self.chat_info,
            "statistics": asdict(self.stats),
            "total_messages": len(self.messages),
            "messages": messages_with_relative_paths,
        }

        # JSON ni string ga o'tkazish (HTML ichiga embed qilish uchun)
        json_data = json.dumps(export_data, ensure_ascii=False)

        html_content = self._get_html_template(json_data)

        html_path = self.output_dir / "index.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"🌐 Web viewer yaratildi: {html_path}")

    def _get_html_template(self, json_data: str) -> str:
        """HTML template qaytaradi"""
        return (
            """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>"""
            + (self.chat_info.get("title", "Chat Export"))
            + """ - Telegram Chat Export</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --bg-primary: #0f0f0f;
            --bg-secondary: #1a1a1a;
            --bg-tertiary: #252525;
            --bg-message: #1e1e1e;
            --bg-message-own: #2d5a27;
            --text-primary: #ffffff;
            --text-secondary: #a0a0a0;
            --text-muted: #6a6a6a;
            --accent-primary: #6366f1;
            --accent-secondary: #8b5cf6;
            --accent-gradient: linear-gradient(135deg, #6366f1, #8b5cf6);
            --border-color: #2d2d2d;
            --success: #22c55e;
            --warning: #f59e0b;
            --error: #ef4444;
            --glass-bg: rgba(255, 255, 255, 0.05);
            --glass-border: rgba(255, 255, 255, 0.1);
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        /* Scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }

        ::-webkit-scrollbar-thumb {
            background: var(--bg-tertiary);
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: #444;
        }

        /* Header */
        .header {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 100;
            background: rgba(15, 15, 15, 0.85);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 2rem;
        }

        .header-content {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1.5rem;
        }

        .chat-avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: var(--accent-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
            font-weight: 600;
            color: white;
            flex-shrink: 0;
        }

        .chat-details {
            flex: 1;
            min-width: 0;
        }

        .chat-title {
            font-size: 1.25rem;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .chat-meta {
            font-size: 0.875rem;
            color: var(--text-secondary);
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
        }

        .search-container {
            position: relative;
            width: 300px;
        }

        .search-input {
            width: 100%;
            padding: 0.75rem 1rem 0.75rem 2.75rem;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            font-size: 0.9rem;
            transition: all 0.3s ease;
        }

        .search-input:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
        }

        .search-icon {
            position: absolute;
            left: 1rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
        }

        /* Main Layout */
        .layout {
            display: flex;
            padding-top: 80px;
            min-height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            width: 320px;
            position: fixed;
            left: 0;
            top: 80px;
            bottom: 0;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border-color);
            padding: 1.5rem;
            overflow-y: auto;
        }

        .stats-section {
            margin-bottom: 2rem;
        }

        .stats-title {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 1rem;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.75rem;
        }

        .stat-card {
            background: var(--glass-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1rem;
            transition: all 0.3s ease;
        }

        .stat-card:hover {
            background: rgba(255, 255, 255, 0.08);
            transform: translateY(-2px);
        }

        .stat-value {
            font-size: 1.5rem;
            font-weight: 700;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .stat-label {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }

        /* Filter Buttons */
        .filters {
            margin-bottom: 1.5rem;
        }

        .filter-btn {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            width: 100%;
            padding: 0.75rem 1rem;
            border-radius: 10px;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-size: 0.9rem;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-bottom: 0.5rem;
        }

        .filter-btn:hover {
            background: var(--glass-bg);
            color: var(--text-primary);
        }

        .filter-btn.active {
            background: var(--accent-gradient);
            color: white;
        }

        .filter-count {
            margin-left: auto;
            font-size: 0.75rem;
            background: rgba(0, 0, 0, 0.3);
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
        }

        /* Messages Container */
        .messages-container {
            flex: 1;
            margin-left: 320px;
            padding: 2rem;
            max-width: 900px;
        }

        .messages-list {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        /* Message Card */
        .message {
            background: var(--bg-message);
            border-radius: 16px;
            padding: 1rem 1.25rem;
            max-width: 85%;
            position: relative;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .message-header {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }

        .message-avatar {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            background: var(--accent-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.7rem;
            font-weight: 600;
        }

        .message-sender {
            font-weight: 600;
            font-size: 0.9rem;
            color: var(--accent-primary);
        }

        .message-time {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-left: auto;
        }

        .message-text {
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.5;
        }

        .message-media {
            margin: 0.75rem 0;
            border-radius: 12px;
            overflow: hidden;
            background: var(--bg-tertiary);
        }

        .message-media img {
            max-width: 100%;
            max-height: 400px;
            object-fit: contain;
            display: block;
        }

        .message-media video {
            max-width: 100%;
            max-height: 400px;
            display: block;
        }

        .message-media audio {
            width: 100%;
        }

        .media-placeholder {
            padding: 1.5rem;
            text-align: center;
            color: var(--text-secondary);
        }

        .media-placeholder-icon {
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
        }

        .media-info {
            font-size: 0.85rem;
            padding: 0.75rem;
            background: var(--bg-primary);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .media-info a {
            color: var(--accent-primary);
            text-decoration: none;
        }

        .media-info a:hover {
            text-decoration: underline;
        }

        /* Caption */
        .message-caption {
            margin-top: 0.75rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border-color);
            color: var(--text-secondary);
        }

        /* Reply & Forward */
        .message-reply,
        .message-forward {
            background: rgba(99, 102, 241, 0.1);
            border-left: 3px solid var(--accent-primary);
            padding: 0.5rem 0.75rem;
            margin-bottom: 0.75rem;
            border-radius: 0 8px 8px 0;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        /* Message Stats */
        .message-stats {
            display: flex;
            gap: 1rem;
            margin-top: 0.75rem;
            padding-top: 0.5rem;
            border-top: 1px solid var(--border-color);
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .message-stat {
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }

        /* Poll */
        .poll-container {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 1rem;
            margin: 0.75rem 0;
        }

        .poll-question {
            font-weight: 600;
            margin-bottom: 0.75rem;
        }

        .poll-option {
            background: var(--bg-primary);
            border-radius: 8px;
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .poll-votes {
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        /* Contact */
        .contact-card {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 1rem;
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .contact-avatar {
            width: 48px;
            height: 48px;
            border-radius: 50%;
            background: var(--accent-gradient);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.25rem;
        }

        /* Location */
        .location-card {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 1rem;
            text-align: center;
        }

        .location-coords {
            font-size: 0.9rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }

        /* Sticker */
        .sticker-container {
            display: inline-block;
        }

        .sticker-container img {
            max-width: 200px;
            max-height: 200px;
        }

        .sticker-emoji {
            margin-top: 0.5rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        /* Date Separator */
        .date-separator {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin: 1.5rem 0;
        }

        .date-separator::before,
        .date-separator::after {
            content: '';
            flex: 1;
            height: 1px;
            background: var(--border-color);
        }

        .date-separator span {
            background: var(--bg-secondary);
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }

        /* Load More */
        .load-more {
            text-align: center;
            padding: 2rem;
        }

        .load-more-btn {
            padding: 0.75rem 2rem;
            border-radius: 12px;
            border: none;
            background: var(--accent-gradient);
            color: white;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .load-more-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px -10px rgba(99, 102, 241, 0.5);
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-secondary);
        }

        .empty-state-icon {
            font-size: 4rem;
            margin-bottom: 1rem;
        }

        /* Responsive */
        @media (max-width: 1024px) {
            .sidebar {
                width: 280px;
            }

            .messages-container {
                margin-left: 280px;
            }
        }

        @media (max-width: 768px) {
            .header-content {
                flex-wrap: wrap;
            }

            .search-container {
                width: 100%;
                order: 3;
                margin-top: 0.5rem;
            }

            .sidebar {
                display: none;
            }

            .messages-container {
                margin-left: 0;
                padding: 1rem;
            }

            .message {
                max-width: 95%;
            }
        }

        /* Loading Animation */
        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 2rem;
        }

        .loading-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--border-color);
            border-top-color: var(--accent-primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to {
                transform: rotate(360deg);
            }
        }
    </style>
</head>
<body>
    <!-- Header -->
    <header class="header">
        <div class="header-content">
            <div class="chat-avatar" id="chatAvatar">T</div>
            <div class="chat-details">
                <h1 class="chat-title" id="chatTitle">Loading...</h1>
                <div class="chat-meta" id="chatMeta">
                    <span id="chatType">Loading...</span>
                    <span id="chatMembers"></span>
                </div>
            </div>
            <div class="search-container">
                <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input type="text" class="search-input" id="searchInput" placeholder="Xabarlarni qidirish...">
            </div>
        </div>
    </header>

    <div class="layout">
        <!-- Sidebar -->
        <aside class="sidebar">
            <div class="stats-section">
                <h3 class="stats-title">Statistika</h3>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-value" id="statTotal">0</div>
                        <div class="stat-label">Jami xabarlar</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="statMedia">0</div>
                        <div class="stat-label">Media fayllar</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="statPhotos">0</div>
                        <div class="stat-label">Rasmlar</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="statVideos">0</div>
                        <div class="stat-label">Videolar</div>
                    </div>
                </div>
            </div>

            <div class="filters">
                <h3 class="stats-title">Filtrlar</h3>
                <button class="filter-btn active" data-filter="all">
                    📋 Barcha xabarlar
                    <span class="filter-count" id="filterAll">0</span>
                </button>
                <button class="filter-btn" data-filter="text">
                    📝 Matnli xabarlar
                    <span class="filter-count" id="filterText">0</span>
                </button>
                <button class="filter-btn" data-filter="photo">
                    🖼️ Rasmlar
                    <span class="filter-count" id="filterPhoto">0</span>
                </button>
                <button class="filter-btn" data-filter="video">
                    🎬 Videolar
                    <span class="filter-count" id="filterVideo">0</span>
                </button>
                <button class="filter-btn" data-filter="audio">
                    🎵 Audio
                    <span class="filter-count" id="filterAudio">0</span>
                </button>
                <button class="filter-btn" data-filter="document">
                    📁 Fayllar
                    <span class="filter-count" id="filterDocument">0</span>
                </button>
                <button class="filter-btn" data-filter="voice">
                    🎤 Ovozli xabarlar
                    <span class="filter-count" id="filterVoice">0</span>
                </button>
                <button class="filter-btn" data-filter="sticker">
                    😀 Stikerlar
                    <span class="filter-count" id="filterSticker">0</span>
                </button>
            </div>

            <div class="export-info">
                <h3 class="stats-title">Export ma'lumotlari</h3>
                <p style="font-size: 0.85rem; color: var(--text-secondary);">
                    Sana: <span id="exportDate">-</span>
                </p>
            </div>
        </aside>

        <!-- Messages -->
        <main class="messages-container">
            <div class="loading" id="loading">
                <div class="loading-spinner"></div>
            </div>
            <div class="messages-list" id="messagesList"></div>
            <div class="load-more" id="loadMore" style="display: none;">
                <button class="load-more-btn" id="loadMoreBtn">Ko'proq yuklash</button>
            </div>
        </main>
    </div>

    <script>
        // Embedded chat data (CORS xatosidan qochish uchun)
        const chatData = """
            + json_data
            + """;

        // Global variables
        let allMessages = chatData.messages;
        let displayedMessages = 0;
        const MESSAGES_PER_PAGE = 50;
        let currentFilter = 'all';
        let searchQuery = '';

        // Load chat data - darhol ishga tushirish
        function loadChatData() {
            try {
                initializeUI();
            } catch (error) {
                console.error('Ma\\'lumotlarni yuklashda xato:', error);
                document.getElementById('loading').innerHTML = '<p style="color: var(--error);">Ma\\'lumotlarni yuklashda xato!</p>';
            }
        }

        // Initialize UI
        function initializeUI() {
            // Header
            const { chat_info, statistics, export_date } = chatData;
            
            document.getElementById('chatTitle').textContent = chat_info.title || chat_info.username || 'Chat';
            document.getElementById('chatAvatar').textContent = (chat_info.title || chat_info.username || 'T').charAt(0).toUpperCase();
            document.getElementById('chatType').textContent = formatChatType(chat_info.type);
            
            if (chat_info.members_count) {
                document.getElementById('chatMembers').textContent = `${chat_info.members_count.toLocaleString()} a'zo`;
            }

            // Stats
            document.getElementById('statTotal').textContent = statistics.total_messages.toLocaleString();
            document.getElementById('statMedia').textContent = (
                statistics.photos + statistics.videos + statistics.audios + 
                statistics.documents + statistics.voices + statistics.video_notes
            ).toLocaleString();
            document.getElementById('statPhotos').textContent = statistics.photos.toLocaleString();
            document.getElementById('statVideos').textContent = statistics.videos.toLocaleString();

            // Filter counts
            document.getElementById('filterAll').textContent = statistics.total_messages;
            document.getElementById('filterText').textContent = statistics.text_messages;
            document.getElementById('filterPhoto').textContent = statistics.photos;
            document.getElementById('filterVideo').textContent = statistics.videos;
            document.getElementById('filterAudio').textContent = statistics.audios;
            document.getElementById('filterDocument').textContent = statistics.documents;
            document.getElementById('filterVoice').textContent = statistics.voices;
            document.getElementById('filterSticker').textContent = statistics.stickers;

            // Export date
            document.getElementById('exportDate').textContent = new Date(export_date).toLocaleDateString('uz-UZ', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });

            // Hide loading, show messages
            document.getElementById('loading').style.display = 'none';
            loadMoreMessages();
            setupEventListeners();
        }

        // Format chat type
        function formatChatType(type) {
            const types = {
                'CHANNEL': '📢 Kanal',
                'SUPERGROUP': '👥 Guruh',
                'GROUP': '👥 Guruh',
                'PRIVATE': '👤 Shaxsiy chat',
                'BOT': '🤖 Bot'
            };
            return types[type] || type;
        }

        // Get filtered messages
        function getFilteredMessages() {
            let filtered = [...allMessages];

            // Apply filter
            if (currentFilter !== 'all') {
                filtered = filtered.filter(msg => {
                    if (currentFilter === 'text') {
                        return msg.text && !msg.media_type;
                    }
                    return msg.media_type && msg.media_type.toLowerCase() === currentFilter.toUpperCase();
                });
            }

            // Apply search
            if (searchQuery) {
                const query = searchQuery.toLowerCase();
                filtered = filtered.filter(msg => {
                    const text = (msg.text || '').toLowerCase();
                    const caption = (msg.caption || '').toLowerCase();
                    return text.includes(query) || caption.includes(query);
                });
            }

            return filtered;
        }

        // Load more messages
        function loadMoreMessages() {
            const filtered = getFilteredMessages();
            const messagesToLoad = filtered.slice(displayedMessages, displayedMessages + MESSAGES_PER_PAGE);
            
            if (messagesToLoad.length === 0 && displayedMessages === 0) {
                document.getElementById('messagesList').innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">🔍</div>
                        <p>Xabarlar topilmadi</p>
                    </div>
                `;
                document.getElementById('loadMore').style.display = 'none';
                return;
            }

            let currentDate = '';
            let html = '';

            if (displayedMessages === 0) {
                document.getElementById('messagesList').innerHTML = '';
            }

            messagesToLoad.forEach(msg => {
                const msgDate = new Date(msg.date).toLocaleDateString('uz-UZ', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                });

                if (msgDate !== currentDate) {
                    currentDate = msgDate;
                    html += `<div class="date-separator"><span>${msgDate}</span></div>`;
                }

                html += renderMessage(msg);
            });

            document.getElementById('messagesList').insertAdjacentHTML('beforeend', html);
            displayedMessages += messagesToLoad.length;

            // Show/hide load more button
            if (displayedMessages < filtered.length) {
                document.getElementById('loadMore').style.display = 'block';
            } else {
                document.getElementById('loadMore').style.display = 'none';
            }
        }

        // Render message
        function renderMessage(msg) {
            const sender = msg.from_user 
                ? `${msg.from_user.first_name || ''} ${msg.from_user.last_name || ''}`.trim() || msg.from_user.username
                : msg.sender_chat?.title || 'Anonymous';
            
            const time = new Date(msg.date).toLocaleTimeString('uz-UZ', {
                hour: '2-digit',
                minute: '2-digit'
            });

            const avatar = sender.charAt(0).toUpperCase();

            let mediaHtml = '';
            let textContent = msg.text || '';
            let captionContent = msg.caption || '';

            // Render media
            if (msg.media_type) {
                mediaHtml = renderMedia(msg);
            }

            // Reply info
            let replyHtml = '';
            if (msg.reply_to_message_id) {
                replyHtml = `<div class="message-reply">↩️ Reply to message #${msg.reply_to_message_id}</div>`;
            }

            // Forward info
            let forwardHtml = '';
            if (msg.forward_from_chat) {
                forwardHtml = `<div class="message-forward">↪️ Forwarded from ${msg.forward_from_chat.title}</div>`;
            }

            // Stats
            let statsHtml = '';
            if (msg.views || msg.forwards) {
                statsHtml = `<div class="message-stats">`;
                if (msg.views) {
                    statsHtml += `<span class="message-stat">👁 ${formatNumber(msg.views)}</span>`;
                }
                if (msg.forwards) {
                    statsHtml += `<span class="message-stat">↗️ ${formatNumber(msg.forwards)}</span>`;
                }
                statsHtml += `</div>`;
            }

            return `
                <div class="message" data-id="${msg.id}">
                    <div class="message-header">
                        <div class="message-avatar">${avatar}</div>
                        <span class="message-sender">${escapeHtml(sender)}</span>
                        <span class="message-time">${time}</span>
                    </div>
                    ${replyHtml}
                    ${forwardHtml}
                    ${textContent ? `<div class="message-text">${escapeHtml(textContent)}</div>` : ''}
                    ${mediaHtml}
                    ${captionContent ? `<div class="message-caption">${escapeHtml(captionContent)}</div>` : ''}
                    ${statsHtml}
                </div>
            `;
        }

        // Render media
        function renderMedia(msg) {
            const type = msg.media_type;
            const mediaUrl = msg.media_url || msg.local_file;  // S3 URL yoki lokal fayl

            switch (type) {
                case 'PHOTO':
                    if (mediaUrl) {
                        return `<div class="message-media"><img src="${mediaUrl}" alt="Photo" loading="lazy"></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">🖼️</div><div>Rasm (yuklanmagan)</div></div></div>`;

                case 'VIDEO':
                    if (mediaUrl) {
                        return `<div class="message-media"><video controls><source src="${mediaUrl}" type="video/mp4"></video></div>`;
                    }
                    const videoInfo = msg.video;
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">🎬</div><div>Video${videoInfo ? ` (${formatDuration(videoInfo.duration)}, ${formatSize(videoInfo.file_size)})` : ''}</div></div></div>`;

                case 'AUDIO':
                    if (mediaUrl) {
                        return `<div class="message-media"><audio controls src="${mediaUrl}"></audio>
                            <div class="media-info">${msg.audio?.title || msg.audio?.file_name || 'Audio'} ${msg.audio?.performer ? '- ' + msg.audio.performer : ''}</div></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">🎵</div><div>${msg.audio?.title || 'Audio'}</div></div></div>`;

                case 'DOCUMENT':
                    if (mediaUrl) {
                        return `<div class="message-media"><div class="media-info">📁 <a href="${mediaUrl}" download>${msg.document?.file_name || 'File'}</a> (${formatSize(msg.document?.file_size)})</div></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">📁</div><div>${msg.document?.file_name || 'File'} (${formatSize(msg.document?.file_size)})</div></div></div>`;

                case 'VOICE':
                    if (mediaUrl) {
                        return `<div class="message-media"><audio controls src="${mediaUrl}"></audio>
                            <div class="media-info">🎤 Voice message (${formatDuration(msg.voice?.duration)})</div></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">🎤</div><div>Voice message (${formatDuration(msg.voice?.duration)})</div></div></div>`;

                case 'VIDEO_NOTE':
                    if (mediaUrl) {
                        return `<div class="message-media" style="max-width: 300px;"><video controls style="border-radius: 50%; width: 200px; height: 200px; object-fit: cover;"><source src="${mediaUrl}" type="video/mp4"></video></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">⭕</div><div>Video message</div></div></div>`;

                case 'STICKER':
                    if (mediaUrl) {
                        return `<div class="sticker-container"><img src="${mediaUrl}" alt="Sticker"><div class="sticker-emoji">${msg.sticker?.emoji || ''} ${msg.sticker?.set_name || ''}</div></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder">😀 ${msg.sticker?.emoji || 'Sticker'}</div></div>`;

                case 'ANIMATION':
                    if (mediaUrl) {
                        return `<div class="message-media"><img src="${mediaUrl}" alt="GIF" style="max-width: 300px;"></div>`;
                    }
                    return `<div class="message-media"><div class="media-placeholder"><div class="media-placeholder-icon">🎞️</div><div>GIF</div></div></div>`;

                case 'POLL':
                    const poll = msg.poll;
                    if (!poll) return '';
                    let pollHtml = `<div class="poll-container"><div class="poll-question">📊 ${escapeHtml(poll.question)}</div>`;
                    poll.options.forEach(opt => {
                        pollHtml += `<div class="poll-option"><span>${escapeHtml(opt.text)}</span><span class="poll-votes">${opt.voter_count} votes</span></div>`;
                    });
                    pollHtml += `<div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem;">${poll.total_voter_count} total votes</div></div>`;
                    return pollHtml;

                case 'CONTACT':
                    const contact = msg.contact;
                    if (!contact) return '';
                    return `<div class="contact-card"><div class="contact-avatar">👤</div><div><div style="font-weight: 600;">${escapeHtml(contact.first_name)} ${escapeHtml(contact.last_name || '')}</div><div style="color: var(--text-secondary);">${contact.phone_number}</div></div></div>`;

                case 'LOCATION':
                    const loc = msg.location;
                    if (!loc) return '';
                    return `<div class="location-card"><div style="font-size: 2rem;">📍</div><div class="location-coords">${loc.latitude.toFixed(6)}, ${loc.longitude.toFixed(6)}</div><a href="https://www.google.com/maps?q=${loc.latitude},${loc.longitude}" target="_blank" style="color: var(--accent-primary); text-decoration: none; display: inline-block; margin-top: 0.5rem;">Google Maps-da ochish →</a></div>`;

                case 'WEB_PAGE':
                    const web = msg.web_page;
                    if (!web) return '';
                    return `<div class="message-media"><div class="media-info" style="flex-direction: column; align-items: flex-start; gap: 0.25rem;"><a href="${web.url}" target="_blank">${escapeHtml(web.title || web.url)}</a>${web.description ? `<div style="font-size: 0.85rem; color: var(--text-secondary);">${escapeHtml(web.description.substring(0, 150))}...</div>` : ''}</div></div>`;

                default:
                    return '';
            }
        }

        // Helper functions
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toString();
        }

        function formatSize(bytes) {
            if (!bytes) return 'N/A';
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i];
        }

        function formatDuration(seconds) {
            if (!seconds) return '';
            const mins = Math.floor(seconds / 60);
            const secs = seconds % 60;
            return `${mins}:${secs.toString().padStart(2, '0')}`;
        }

        // Reset and reload
        function resetAndReload() {
            displayedMessages = 0;
            document.getElementById('messagesList').innerHTML = '';
            loadMoreMessages();
        }

        // Setup event listeners
        function setupEventListeners() {
            // Filter buttons
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    currentFilter = btn.dataset.filter;
                    resetAndReload();
                });
            });

            // Search
            let searchTimeout;
            document.getElementById('searchInput').addEventListener('input', (e) => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    searchQuery = e.target.value.trim();
                    resetAndReload();
                }, 300);
            });

            // Load more
            document.getElementById('loadMoreBtn').addEventListener('click', loadMoreMessages);

            // Infinite scroll
            window.addEventListener('scroll', () => {
                const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
                if (scrollTop + clientHeight >= scrollHeight - 500) {
                    const loadMoreEl = document.getElementById('loadMore');
                    if (loadMoreEl.style.display !== 'none') {
                        loadMoreMessages();
                    }
                }
            });
        }

        // Initialize
        loadChatData();
    </script>
</body>
</html>"""
        )


async def main():
    print("=" * 60)
    print("  🚀 TELEGRAM CHAT EXPORTER")
    print("=" * 60)
    print("\nKanal yoki guruh username/ID kiriting.")
    print("Masalan: @durov, durov, yoki -1001234567890\n")

    chat_id = input("Chat ID yoki Username: ").strip()

    if not chat_id:
        print("❌ Chat ID kiritilmadi!")
        return

    # Agar raqam bo'lsa, int ga o'tkazish
    if chat_id.lstrip("-").isdigit():
        chat_id = int(chat_id)

    exporter = TelegramExporter(chat_id)
    await exporter.export()


if __name__ == "__main__":
    asyncio.run(main())
