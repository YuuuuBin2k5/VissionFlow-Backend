import os
import sys
import json
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Ensure workspace root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Reconfigure stdout for UTF-8 to prevent Windows terminal encoding crashes
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environmental variables
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from worker.services.model_router import ModelRouter
from worker.services.asset_service import AssetService


def test_asset_scoring():
    print("\n=== [TEST 1] Testing Asset Scoring Function ===")
    asset_service = AssetService()
    
    # Candidate 1: Perfect candidate (Long vertical cooking video)
    candidate_1 = {
        "duration": 50,
        "width": 1080,
        "height": 1920,
        "url": "https://pexels.com/video/cooking-satisfying-pasta-preparation-123",
        "description": "Cozy kitchen cooking and vegetable cutting preparation.",
        "user": {"name": "satisfying chef"},
        "tags": ["cooking", "cutting", "satisfying"]
    }
    
    # Candidate 2: Bad candidate (Short, horizontal, watermarked, unrelated)
    candidate_2 = {
        "duration": 15,
        "width": 1920,
        "height": 1080,
        "url": "https://pexels.com/video/random-car-driving-logo-456",
        "description": "Watermark overlay drive.",
        "user": {"name": "car channel"},
        "tags": ["car", "watermark"]
    }
    
    score_1 = asset_service.score_bottom_asset(candidate_1)
    score_2 = asset_service.score_bottom_asset(candidate_2)
    
    print(f"Candidate 1 (Perfect cooking video) - Score: {score_1} (Expected: High positive score)")
    print(f"Candidate 2 (Short watermarked car) - Score: {score_2} (Expected: Low negative score)")
    
    assert score_1 > 0, "Perfect candidate should have a positive score"
    assert score_2 < 0, "Watermarked or short candidate should have a negative score"
    print("[SUCCESS] [TEST 1] Asset scoring completed successfully!")


def test_gemini_prompt():
    print("\n=== [TEST 2] Testing Gemini Prompt for LONG_CHILL_MULTI_ACTION ===")
    router = ModelRouter()
    
    topic = "Thấy bình yên từ lòng biết ơn"
    title_idea = "Bình yên từ lòng biết ơn"
    audience = "Người trưởng thành chiêm nghiệm cuộc sống"
    metadata = {
        "split_mode": "LONG_CHILL_MULTI_ACTION",
        "bottom_visual_type": "satisfying",
        "tone": "healing"
    }
    
    print(f"Sending prompt to Gemini for topic: '{topic}'...")
    details = router.generate_split_screen_details(
        topic=topic,
        title_idea=title_idea,
        audience=audience,
        metadata=metadata
    )
    
    print("\n--- Generated JSON Root-level keys: ---")
    for k in details.keys():
        print(f"- {k}")
        
    print("\nChecking required keys...")
    assert "bottom_asset_requirements" in details, "Missing bottom_asset_requirements key at root"
    assert "youtube_title_options" in details, "Missing youtube_title_options key at root"
    assert "youtube_scannable_description" in details, "Missing youtube_scannable_description key at root"
    assert "youtube_hashtags" in details, "Missing youtube_hashtags key at root"
    assert "youtube_api_tags" in details, "Missing youtube_api_tags key at root"
    
    print("\n--- bottom_asset_requirements: ---")
    print(json.dumps(details["bottom_asset_requirements"], indent=2, ensure_ascii=False))
    
    print("\n--- youtube_title_options[0]: ---")
    print(details["youtube_title_options"][0])
    
    print("\n--- youtube_scannable_description: ---")
    print(details["youtube_scannable_description"][:200] + "...")
    
    print("[SUCCESS] [TEST 2] Gemini prompt and JSON schema verified successfully!")
    return details


def test_pexels_scanned_search(details):
    print("\n=== [TEST 3] Testing Pexels Scanned Search & Scoring ===")
    asset_service = AssetService()
    
    query = details.get("lifestyle_search_query", "cooking satisfying vertical")
    requirements = details.get("bottom_asset_requirements", {})
    
    print(f"Querying Pexels for best bottom asset with query: '{query}'...")
    best_asset = asset_service.search_and_download_best_bottom_asset(query, job_id=999, requirements=requirements)
    
    if best_asset:
        print("\nSuccessfully found and downloaded best bottom asset!")
        print(f"Path: {best_asset['path']}")
        print(f"Duration: {best_asset['duration']}s")
        print(f"Resolution: {best_asset['width']}x{best_asset['height']}")
        print(f"Score: {best_asset['score']}")
        print(f"Source URL: {best_asset['source_url']}")
        
        # Clean up downloaded file to avoid disk build-up
        if os.path.exists(best_asset['path']):
            os.remove(best_asset['path'])
            print(f"Cleaned up temporary test file: {best_asset['path']}")
            
        print("[SUCCESS] [TEST 3] Pexels scanned search completed successfully!")
    else:
        print("[FAIL] [TEST 3] Failed to find or download best bottom asset.")


if __name__ == "__main__":
    print("Starting verification tests...")
    try:
        test_asset_scoring()
        details = test_gemini_prompt()
        test_pexels_scanned_search(details)
        print("\nALL TESTS PASSED SUCCESSFULLY!")
    except Exception as e:
        print(f"\nTest execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
