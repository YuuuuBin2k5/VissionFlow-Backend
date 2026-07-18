import os
import json
import sqlite3
import shutil
import base64
import ctypes
from ctypes import wintypes
import sys
from pathlib import Path

# Win32 DPAPI Decryption helpers using ctypes
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

def CryptUnprotectData(encrypted_bytes):
    in_blob = DATA_BLOB()
    in_blob.cbData = len(encrypted_bytes)
    in_blob.pbData = ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char))
    
    out_blob = DATA_BLOB()
    
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
        
    decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return decrypted_bytes

def get_chrome_aes_key(user_data_dir):
    local_state_path = os.path.join(user_data_dir, "Local State")
    if not os.path.exists(local_state_path):
        raise FileNotFoundError("Local State file not found.")
        
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.loads(f.read())
        
    encrypted_key_b64 = local_state["os_crypt"]["encrypted_key"]
    encrypted_key = base64.b64decode(encrypted_key_b64)
    
    encrypted_key_payload = encrypted_key[5:]
    aes_key = CryptUnprotectData(encrypted_key_payload)
    return aes_key

def decrypt_cookie_value(encrypted_value, aes_key):
    print(f"Encrypted prefix: {encrypted_value[:10]}")
    if encrypted_value.startswith(b"v10") or encrypted_value.startswith(b"v11"):
        iv = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag = encrypted_value[-16:]
        
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(aes_key)
        try:
            decrypted = aesgcm.decrypt(iv, ciphertext + tag, None)
            return decrypted.decode("utf-8")
        except Exception as e:
            print(f"Decryption failed for v10/v11: {e}")
            return ""
    else:
        try:
            decrypted = CryptUnprotectData(encrypted_value)
            return decrypted.decode("utf-8")
        except Exception as e:
            print(f"Decryption failed for legacy: {e}")
            return ""

def main():
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass
            
    print("Searching Chrome profiles for active Douyin cookies...")
    
    user_profile = os.environ.get("USERPROFILE")
    user_data_dir = os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data")
    temp_cookies_db = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentBot\\worker\\temp_assets\\chrome_cookies_search_temp.db"
    final_cookies_txt = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentBot\\worker\\temp_assets\\douyin_cookies.txt"
    
    if not os.path.exists(user_data_dir):
        print("Chrome User Data directory not found.")
        return
        
    try:
        aes_key = get_chrome_aes_key(user_data_dir)
        print("Successfully decrypted Chrome AES Master Key!")
    except Exception as e:
        print("Failed to decrypt master key:", e)
        return
        
    # Find all profiles
    profiles = ["Default"]
    for item in os.listdir(user_data_dir):
        if item.startswith("Profile "):
            profiles.append(item)
            
    print(f"Checking {len(profiles)} Chrome profiles...")
    
    found_profile = None
    douyin_cookies_list = []
    
    for profile in profiles:
        cookies_path = os.path.join(user_data_dir, profile, "Network", "Cookies")
        if not os.path.exists(cookies_path):
            continue
            
        # Copy file safely
        try:
            shutil.copy2(cookies_path, temp_cookies_db)
            conn = sqlite3.connect(temp_cookies_db)
            cursor = conn.cursor()
            
            # Select cookies
            cursor.execute("SELECT host_key, name, path, is_secure, expires_utc, encrypted_value FROM cookies WHERE host_key LIKE '%douyin.com'")
            rows = cursor.fetchall()
            
            if len(rows) > 0:
                print(f"Profile '{profile}' has {len(rows)} Douyin cookies!")
                
                # Decrypt and store them
                temp_list = []
                for host_key, name, path, is_secure, expires_utc, encrypted_value in rows:
                    decrypted_val = decrypt_cookie_value(encrypted_value, aes_key)
                    if decrypted_val:
                        # Netscape fields
                        domain = host_key
                        flag = "TRUE" if domain.startswith(".") else "FALSE"
                        cookie_path = path
                        secure = "TRUE" if is_secure == 1 else "FALSE"
                        # Convert Chrome expires_utc (microseconds since 1601-01-01) to standard Unix epoch
                        # (Or we can just use a large number / standard epoch)
                        expires = expires_utc
                        if expires_utc > 0:
                            # Convert Chrome time to Unix epoch seconds
                            expires = int((expires_utc - 11644473600000000) / 1000000)
                        
                        temp_list.append((domain, flag, cookie_path, secure, expires, name, decrypted_val))
                
                if len(temp_list) > len(douyin_cookies_list):
                    douyin_cookies_list = temp_list
                    found_profile = profile
                    
            conn.close()
            os.remove(temp_cookies_db)
        except Exception as ex:
            print(f"Error checking profile {profile}: {ex}")
            if os.path.exists(temp_cookies_db):
                try: os.remove(temp_cookies_db)
                except Exception: pass
                
    if douyin_cookies_list:
        print(f"\n--- SUCCESS ---")
        print(f"Best profile found: '{found_profile}' with {len(douyin_cookies_list)} decrypted Douyin cookies.")
        
        # Write Netscape cookies file
        with open(final_cookies_txt, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file! Do not edit.\n\n")
            for domain, flag, path, secure, expires, name, value in douyin_cookies_list:
                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
                
        print(f"Successfully wrote {len(douyin_cookies_list)} Netscape cookies to: {final_cookies_txt}")
        print("Now yt-dlp can use this file directly to bypass Douyin's block!")
    else:
        print("\nCould not find any Douyin cookies in any Chrome profile.")

if __name__ == "__main__":
    main()
