import os
import json
import sqlite3
import shutil
import base64
import ctypes
from ctypes import wintypes
import sys

# Win32 DPAPI Decryption helpers using ctypes
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def CryptUnprotectData(encrypted_bytes):
    # Set up DPAPI call
    CRYPTPROTECT_UI_FORCE = 0x2
    
    in_blob = DATA_BLOB()
    in_blob.cbData = len(encrypted_bytes)
    in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char))
    
    out_blob = DATA_BLOB()
    
    # Call CryptUnprotectData
    res = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob)
    )
    
    if not res:
        raise ctypes.WinError()
        
    # Read output bytes
    decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    # Free memory allocated by Windows
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    
    return decrypted_bytes

def get_chrome_aes_key():
    user_profile = os.environ.get("USERPROFILE")
    local_state_path = os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Local State")
    
    if not os.path.exists(local_state_path):
        raise FileNotFoundError("Local State file not found.")
        
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.loads(f.read())
        
    encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
    encrypted_key = base64.b64decode(encrypted_key_b64)
    
    # Strip signature "DPAPI" (first 5 bytes)
    encrypted_key_payload = encrypted_key[5:]
    
    # Decrypt with DPAPI
    aes_key = CryptUnprotectData(encrypted_key_payload)
    return aes_key

def decrypt_cookie_value(encrypted_value, aes_key):
    # Check signature
    if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
        # AES-GCM encryption
        iv = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag = encrypted_value[-16:]
        
        # Decrypt using cryptography library
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(aes_key)
        try:
            decrypted = aesgcm.decrypt(iv, ciphertext + tag, None)
            return decrypted.decode("utf-8")
        except Exception as e:
            # Fallback
            return ""
    else:
        # Older DPAPI encryption
        try:
            decrypted = CryptUnprotectData(encrypted_value)
            return decrypted.decode("utf-8")
        except Exception:
            return ""

def main():
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
            
    print("Testing Chrome cookie decryption on Windows...")
    
    user_profile = os.environ.get("USERPROFILE")
    cookies_src = os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Network", "Cookies")
    cookies_temp = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\temp_assets\\chrome_cookies_temp.db"
    
    if not os.path.exists(cookies_src):
        print("Chrome cookies file not found.")
        return
        
    try:
        shutil.copy2(cookies_src, cookies_temp)
        print("Successfully copied Chrome cookies database.")
        
        aes_key = get_chrome_aes_key()
        print("Successfully decrypted Chrome AES Master Key!")
        
        # Connect to SQLite database
        conn = sqlite3.connect(cookies_temp)
        cursor = conn.cursor()
        
        cursor.execute("SELECT host_key, name, path, is_secure, expires_utc, encrypted_value FROM cookies WHERE host_key LIKE '%douyin.com'")
        rows = cursor.fetchall()
        
        print(f"\nFound {len(rows)} Douyin cookies in Chrome.")
        
        decrypted_count = 0
        for host_key, name, path, is_secure, expires_utc, encrypted_value in rows[:10]:
            decrypted_val = decrypt_cookie_value(encrypted_value, aes_key)
            if decrypted_val:
                print(f"Cookie: {name} = {decrypted_val[:30]}... (Host: {host_key})")
                decrypted_count += 1
                
        print(f"\nDecrypted {decrypted_count} cookies successfully!")
        
        conn.close()
        try:
            os.remove(cookies_temp)
        except Exception:
            pass
            
    except Exception as e:
        print("Failed to decrypt cookies:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
