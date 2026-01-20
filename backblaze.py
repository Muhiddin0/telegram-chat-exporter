import os
import boto3
from botocore.exceptions import NoCredentialsError
from dotenv import load_dotenv
from urllib.parse import urlparse

# .env faylidagi o'zgaruvchilarni yuklash
load_dotenv()

# S3 client ni cache qilish
_s3_client = None
_bucket_name = None
_endpoint_url = None
_base_url = None

def _get_s3_client():
    """S3 client ni yaratadi yoki cache qilinganini qaytaradi"""
    global _s3_client, _bucket_name, _endpoint_url, _base_url
    
    if _s3_client is None:
        endpoint_url = os.getenv('B2_ENDPOINT_URL')
        access_key = os.getenv('B2_ACCESS_KEY_ID')
        secret_key = os.getenv('B2_SECRET_ACCESS_KEY')
        bucket_name = os.getenv('B2_BUCKET_NAME')
        
        # Sozlamalarni tekshirish
        missing = []
        if not endpoint_url:
            missing.append('B2_ENDPOINT_URL')
        if not access_key:
            missing.append('B2_ACCESS_KEY_ID')
        if not secret_key:
            missing.append('B2_SECRET_ACCESS_KEY')
        if not bucket_name:
            missing.append('B2_BUCKET_NAME')
        
        if missing:
            error_msg = f"B2 sozlamalari to'liq emas. Quyidagilar topilmadi: {', '.join(missing)}"
            print(f"   ❌ {error_msg}")
            raise ValueError(error_msg)
        
        try:
            _s3_client = boto3.client(
                service_name='s3',
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            _bucket_name = bucket_name
            _endpoint_url = endpoint_url
            
            # Base URL ni yaratish (Backblaze B2 uchun)
            # Avval custom public URL ni tekshirish (.env dan)
            custom_public_url = os.getenv('B2_PUBLIC_URL_BASE')
            if custom_public_url:
                _base_url = custom_public_url.rstrip('/')
            else:
                # Endpoint URL dan domain ni olish
                parsed = urlparse(endpoint_url)
                # Backblaze B2 public URL formati: https://{bucket}.s3.{region}.backblazeb2.com/{key}
                # Endpoint URL odatda: https://s3.{region}.backblazeb2.com
                # Public URL: https://{bucket}.s3.{region}.backblazeb2.com
                if 's3.' in endpoint_url:
                    # Endpoint: https://s3.us-west-000.backblazeb2.com
                    # Public: https://{bucket}.s3.us-west-000.backblazeb2.com
                    _base_url = endpoint_url.replace('s3.', f'{bucket_name}.s3.')
                else:
                    # Fallback: oddiy endpoint dan foydalanish
                    _base_url = endpoint_url.replace('/b2api/v1', '').rstrip('/')
            
            # S3 client ni test qilish (bucket mavjudligini tekshirish)
            try:
                _s3_client.head_bucket(Bucket=bucket_name)
                print(f"   ✅ S3 client muvaffaqiyatli yaratildi (Bucket: {bucket_name})")
            except Exception as test_error:
                print(f"   ⚠️ Bucket tekshiruvida xato: {test_error}")
                print(f"   💡 Bucket nomi va kalitlarni tekshiring.")
                
        except Exception as e:
            error_msg = f"S3 client yaratishda xato: {e}"
            print(f"   ❌ {error_msg}")
            raise ValueError(error_msg)
    
    return _s3_client, _bucket_name, _base_url

def upload_to_b2(file_path, object_name=None, chat_folder=None, max_retries=3):
    """
    Faylni Backblaze B2 (S3 API) ga yuklash funksiyasi (retry bilan)
    
    Args:
        file_path: Yuklab olinadigan fayl yo'li
        object_name: S3 da saqlash uchun object nomi (ixtiyoriy)
        chat_folder: Chat papkasi nomi (ixtiyoriy, object_name oldiga qo'shiladi)
        max_retries: Maksimal qayta urinishlar soni
    
    Returns:
        tuple: (success: bool, url: str yoki None)
    """
    import time
    
    # Agar object_name berilmagan bo'lsa, faylning o'z nomini ishlatamiz
    if object_name is None:
        object_name = os.path.basename(file_path)
    
    # Chat papkasini qo'shish (agar chat_folder berilgan bo'lsa va object_name da yo'q bo'lsa)
    if chat_folder and not object_name.startswith(chat_folder):
        object_name = f"{chat_folder}/{object_name}"
    
    # Retry mechanism
    for attempt in range(max_retries):
        try:
            s3, bucket_name, base_url = _get_s3_client()
            
            if attempt == 0:
                print(f"   📤 S3 ga yuklanmoqda: {object_name}...")
            else:
                print(f"   🔄 Qayta urinilmoqda ({attempt + 1}/{max_retries}): {object_name}...")
            
            # Faylni yuklash
            s3.upload_file(file_path, bucket_name, object_name)
            
            # Yuklash muvaffaqiyatli bo'lganini tekshirish
            try:
                # Object mavjudligini tekshirish
                s3.head_object(Bucket=bucket_name, Key=object_name)
            except Exception as verify_error:
                raise Exception(f"Yuklash tekshiruvida xato: {verify_error}")
            
            # Public URL ni yaratish
            # Backblaze B2 public URL formati: https://{bucket}.s3.{region}.backblazeb2.com/{key}
            # object_name allaqachon chat_folder/{folder}/{filename} formatida
            public_url = f"{base_url}/{object_name}"
            
            if attempt > 0:
                print(f"   ✅ Qayta urinish muvaffaqiyatli: {object_name}")
            else:
                print(f"   ✅ S3 ga muvaffaqiyatli yuklandi: {object_name}")
                print(f"   🔗 URL: {public_url}")
            
            return True, public_url

        except FileNotFoundError:
            print(f"   ❌ Xato: Fayl topilmadi: {file_path}")
            return False, None
        except NoCredentialsError:
            print("   ❌ Xato: S3 kalitlari noto'g'ri yoki topilmadi.")
            print("   💡 .env faylida B2_ACCESS_KEY_ID va B2_SECRET_ACCESS_KEY ni tekshiring.")
            return False, None
        except Exception as e:
            error_msg = str(e)
            if attempt == max_retries - 1:
                print(f"   ❌ S3 ga yuklashda xato ({max_retries} marta urinildi): {error_msg}")
                print(f"   📋 Bucket: {bucket_name}, Object: {object_name}")
                return False, None
            else:
                print(f"   ⚠️ Xato (urinish {attempt + 1}/{max_retries}): {error_msg}")
            # Exponential backoff
            time.sleep(2 ** attempt)
    
    return False, None

# Ishlatib ko'rish
if __name__ == "__main__":
    local_file = 'image.png'  # Kompyuteringizdagi fayl yo'li
    success, url = upload_to_b2(local_file)
    if success:
        print(f"URL: {url}")