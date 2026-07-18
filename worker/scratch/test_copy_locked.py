import os
import shutil

def main():
    user_profile = os.environ.get("USERPROFILE")
    cookies_src = os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Network", "Cookies")
    cookies_dst = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentBot\\worker\\temp_assets\\chrome_cookies_temp"
    
    print(f"Attempting to copy Chrome Cookies from: {cookies_src}")
    if not os.path.exists(cookies_src):
        print("Chrome cookies file not found at default path.")
        return
        
    try:
        shutil.copy2(cookies_src, cookies_dst)
        print("Success! Copied locked cookies database using shutil.copy2.")
    except Exception as e:
        print("Standard copy failed with error:", e)
        
        # Try custom copy using win32/ctypes or open with share flags
        print("\nAttempting custom copy with share flags...")
        try:
            import ctypes
            from ctypes import wintypes
            
            kernel32 = ctypes.windll.kernel32
            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 0x80
            
            # Open file with share flags
            handle = kernel32.CreateFileW(
                cookies_src,
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None
            )
            
            if handle == -1: # INVALID_HANDLE_VALUE
                raise ctypes.WinError()
                
            print("Successfully opened handle to locked file using CreateFileW share flags!")
            
            # Read and write to destination
            buffer_size = 4096
            buffer = ctypes.create_string_buffer(buffer_size)
            bytes_read = wintypes.DWORD()
            
            with open(cookies_dst, "wb") as f_out:
                while True:
                    res = kernel32.ReadFile(handle, buffer, buffer_size, ctypes.byref(bytes_read), None)
                    if not res or bytes_read.value == 0:
                        break
                    f_out.write(buffer.raw[:bytes_read.value])
                    
            kernel32.CloseHandle(handle)
            print("Success!!! Copied locked database using custom CreateFileW!")
        except Exception as ex:
            print("Custom copy failed:", ex)

if __name__ == "__main__":
    main()
