"""
Setup script to download curated high-quality SFX stems & BGM tracks,
bundle them into Client public and Backend assets, and upload to Cloudflare R2 bucket.
"""

import os
import shutil
import urllib.parse
import boto3
import requests

SFX_SOURCES = {
    "whoosh_cinematic_deep.mp3": "https://assets.mixkit.co/active_storage/sfx/2873/2873-preview.mp3",
    "swoosh_quick_air.mp3": "https://assets.mixkit.co/active_storage/sfx/2568/2568-preview.mp3",
    "whoosh_fast.mp3": "https://assets.mixkit.co/active_storage/sfx/2872/2872-preview.mp3",
    "whoosh_sub_boom.mp3": "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3",
    "cinematic_hit.mp3": "https://assets.mixkit.co/active_storage/sfx/2868/2868-preview.mp3",
    "cyber_glitch_switch.mp3": "https://assets.mixkit.co/active_storage/sfx/2575/2575-preview.mp3",
    "camera_shutter_click.mp3": "https://assets.mixkit.co/active_storage/sfx/2578/2578-preview.mp3",
    "tape_rewind_stop.mp3": "https://assets.mixkit.co/active_storage/sfx/2579/2579-preview.mp3",
    "retro_pop_bubble.mp3": "https://assets.mixkit.co/active_storage/sfx/2574/2574-preview.mp3",
    "accent_bell_ting.mp3": "https://assets.mixkit.co/active_storage/sfx/2865/2865-preview.mp3",
    "magic_sparkle.mp3": "https://assets.mixkit.co/active_storage/sfx/2582/2582-preview.mp3",
}

BGM_SOURCES = {
    "bgm_philosophy_clean_soul.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Clean%20Soul.mp3",
    "bgm_science_equatorial.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Equatorial%20Complex.mp3",
    "bgm_mystery_gathering_darkness.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Gathering%20Darkness.mp3",
    "bgm_wealth_long_road.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Long%20Road%20Ahead.mp3",
    "bgm_strategy_virtutes.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Virtutes%20Instrumenti.mp3",
    "bgm_chill_zen_moment.mp3": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/That%20Zen%20Moment.mp3",
}

CLIENT_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "VisionFlow_Client", "public", "audio"))
BACKEND_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "audio"))

def download_file(url: str, dest_path: str) -> bool:
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
        print(f"  [Cached] {os.path.basename(dest_path)} ({os.path.getsize(dest_path)} bytes)")
        return True
    try:
        print(f"  [Downloading] {url} -> {os.path.basename(dest_path)}...")
        r = requests.get(url, timeout=30, stream=True)
        if r.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    f.write(chunk)
            print(f"  [OK] Saved {os.path.basename(dest_path)} ({os.path.getsize(dest_path)} bytes)")
            return True
        else:
            print(f"  [Failed] Status {r.status_code} for {url}")
            return False
    except Exception as e:
        print(f"  [Error] {e} for {url}")
        return False

def sync_audio_assets():
    # 1. Prepare target directories
    for base in [CLIENT_AUDIO_DIR, BACKEND_AUDIO_DIR]:
        os.makedirs(os.path.join(base, "sfx"), exist_ok=True)
        os.makedirs(os.path.join(base, "bgm"), exist_ok=True)

    # 2. Download SFX Stems
    print("\n--- 1. DOWNLOADING SFX STEMS ---")
    for filename, url in SFX_SOURCES.items():
        backend_dest = os.path.join(BACKEND_AUDIO_DIR, "sfx", filename)
        client_dest = os.path.join(CLIENT_AUDIO_DIR, "sfx", filename)
        if download_file(url, backend_dest):
            shutil.copy2(backend_dest, client_dest)

    # 3. Download BGM Tracks
    print("\n--- 2. DOWNLOADING BGM MASTER TRACKS ---")
    for filename, url in BGM_SOURCES.items():
        backend_dest = os.path.join(BACKEND_AUDIO_DIR, "bgm", filename)
        client_dest = os.path.join(CLIENT_AUDIO_DIR, "bgm", filename)
        if download_file(url, backend_dest):
            shutil.copy2(backend_dest, client_dest)

    # 4. Upload to Cloudflare R2
    print("\n--- 3. SYNCING TO CLOUDFLARE R2 ---")
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url="https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com",
            aws_access_key_id="fd28f47a855e5f2097d5f8c24c50da70",
            aws_secret_access_key="c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6",
        )
        bucket_name = "vision-flow"

        # Upload SFX
        for filename in SFX_SOURCES.keys():
            local_path = os.path.join(BACKEND_AUDIO_DIR, "sfx", filename)
            if os.path.exists(local_path):
                r2_key = f"audio/sfx/{filename}"
                s3.upload_file(local_path, bucket_name, r2_key, ExtraArgs={"ContentType": "audio/mpeg"})
                print(f"  [R2 Uploaded] {r2_key}")

        # Upload BGM
        for filename in BGM_SOURCES.keys():
            local_path = os.path.join(BACKEND_AUDIO_DIR, "bgm", filename)
            if os.path.exists(local_path):
                r2_key = f"audio/bgm/{filename}"
                s3.upload_file(local_path, bucket_name, r2_key, ExtraArgs={"ContentType": "audio/mpeg"})
                print(f"  [R2 Uploaded] {r2_key}")

        print("\n✅ All audio assets synchronized locally and to Cloudflare R2 successfully!")
    except Exception as r2_err:
        print(f"⚠️ R2 sync notice: {r2_err}")

if __name__ == "__main__":
    sync_audio_assets()
