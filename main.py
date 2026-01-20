import os
import json
from datetime import datetime
from typing import Any

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.enums import MessageMediaType
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")


def serialize_message(message: Message) -> dict[str, Any]:
    """Pyrogram Message obyektini JSON-ga mos formatga o'tkazadi."""

    data = {
        "id": message.id,
        "date": message.date.isoformat() if message.date else None,
        "chat_id": message.chat.id if message.chat else None,
        "chat_title": message.chat.title if message.chat else None,
        "chat_username": message.chat.username if message.chat else None,
        "chat_type": (
            message.chat.type.name if message.chat and message.chat.type else None
        ),
        "from_user_id": message.from_user.id if message.from_user else None,
        "from_user_username": message.from_user.username if message.from_user else None,
        "from_user_first_name": (
            message.from_user.first_name if message.from_user else None
        ),
        "from_user_last_name": (
            message.from_user.last_name if message.from_user else None
        ),
        "sender_chat_id": message.sender_chat.id if message.sender_chat else None,
        "sender_chat_title": message.sender_chat.title if message.sender_chat else None,
        "text": message.text,
        "caption": message.caption,
        "media_type": message.media.name if message.media else None,
        "views": message.views,
        "forwards": message.forwards,
        "edit_date": message.edit_date.isoformat() if message.edit_date else None,
        "reply_to_message_id": message.reply_to_message_id,
        "forward_from_chat_id": (
            message.forward_from_chat.id if message.forward_from_chat else None
        ),
        "forward_from_chat_title": (
            message.forward_from_chat.title if message.forward_from_chat else None
        ),
        "forward_date": (
            message.forward_date.isoformat() if message.forward_date else None
        ),
        "media_group_id": message.media_group_id,
    }

    # Media-ga qarab qo'shimcha ma'lumotlar
    if message.media:
        if message.media == MessageMediaType.PHOTO and message.photo:
            data["photo"] = {
                "file_id": message.photo.file_id,
                "file_unique_id": message.photo.file_unique_id,
                "width": message.photo.width,
                "height": message.photo.height,
                "file_size": message.photo.file_size,
            }
        elif message.media == MessageMediaType.VIDEO and message.video:
            data["video"] = {
                "file_id": message.video.file_id,
                "file_unique_id": message.video.file_unique_id,
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
                "file_unique_id": message.audio.file_unique_id,
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
                "file_unique_id": message.document.file_unique_id,
                "file_name": message.document.file_name,
                "mime_type": message.document.mime_type,
                "file_size": message.document.file_size,
            }
        elif message.media == MessageMediaType.VOICE and message.voice:
            data["voice"] = {
                "file_id": message.voice.file_id,
                "file_unique_id": message.voice.file_unique_id,
                "duration": message.voice.duration,
                "mime_type": message.voice.mime_type,
                "file_size": message.voice.file_size,
            }
        elif message.media == MessageMediaType.VIDEO_NOTE and message.video_note:
            data["video_note"] = {
                "file_id": message.video_note.file_id,
                "file_unique_id": message.video_note.file_unique_id,
                "length": message.video_note.length,
                "duration": message.video_note.duration,
                "file_size": message.video_note.file_size,
            }
        elif message.media == MessageMediaType.STICKER and message.sticker:
            data["sticker"] = {
                "file_id": message.sticker.file_id,
                "file_unique_id": message.sticker.file_unique_id,
                "width": message.sticker.width,
                "height": message.sticker.height,
                "emoji": message.sticker.emoji,
                "set_name": message.sticker.set_name,
            }
        elif message.media == MessageMediaType.ANIMATION and message.animation:
            data["animation"] = {
                "file_id": message.animation.file_id,
                "file_unique_id": message.animation.file_unique_id,
                "width": message.animation.width,
                "height": message.animation.height,
                "duration": message.animation.duration,
                "file_name": message.animation.file_name,
                "mime_type": message.animation.mime_type,
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
                "user_id": message.contact.user_id,
            }
        elif message.media == MessageMediaType.WEB_PAGE and message.web_page:
            data["web_page"] = {
                "url": message.web_page.url,
                "title": message.web_page.title,
                "description": message.web_page.description,
                "site_name": message.web_page.site_name,
            }

    return data


def export_chat_history(chat_id: str | int) -> None:
    """Berilgan chat ID yoki username uchun barcha xabarlarni export qiladi."""

    app = Client("my_account", api_id=API_ID, api_hash=API_HASH)

    print(f"\n📥 Chat tarixini yuklab olish boshlanmoqda: {chat_id}")

    messages = []
    count = 0

    with app:
        # Chat haqida ma'lumot olish
        try:
            chat = app.get_chat(chat_id)
            chat_info = {
                "id": chat.id,
                "title": chat.title,
                "username": chat.username,
                "type": chat.type.name if chat.type else None,
                "members_count": chat.members_count,
                "description": chat.description,
            }
            print(f"✅ Chat topildi: {chat.title or chat.username or chat.id}")
        except Exception as e:
            print(f"❌ Chat topilmadi: {e}")
            return

        # Barcha xabarlarni olish
        print("📨 Xabarlar yuklanmoqda...")

        for message in app.get_chat_history(chat_id):
            count += 1
            messages.append(serialize_message(message))

            # Progress ko'rsatish
            if count % 100 == 0:
                print(f"   ✓ {count} ta xabar yuklandi...")

    print(f"✅ Jami {count} ta xabar yuklandi!")

    # JSON faylga saqlash
    export_data = {
        "export_date": datetime.now().isoformat(),
        "chat_info": chat_info,
        "total_messages": len(messages),
        "messages": messages,
    }

    # Fayl nomini yaratish
    safe_name = str(chat_id).replace("@", "").replace("/", "_")
    filename = f"export_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    print(f"💾 Ma'lumotlar saqlandi: {filename}")
    print(f"📊 Fayl hajmi: {os.path.getsize(filename) / 1024:.2f} KB")


def main():
    print("=" * 50)
    print("  TELEGRAM CHAT EXPORTER")
    print("=" * 50)
    print("\nKanal yoki guruh username/ID kiriting.")
    print("Masalan: @durov, durov, yoki -1001234567890\n")

    chat_id = input("Chat ID yoki Username: ").strip()

    if not chat_id:
        print("❌ Chat ID kiritilmadi!")
        return

    # Agar raqam bo'lsa, int ga o'tkazish
    if chat_id.lstrip("-").isdigit():
        chat_id = int(chat_id)

    export_chat_history(chat_id)


if __name__ == "__main__":
    main()
