import os
import sys
import json
from pathlib import Path

# Add the root directory to path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
sys.path.append(root_dir)

from worker.domain.caption_policy import extract_publish_music_metadata, build_publish_caption_and_hashtags
from worker.domain.job_metadata import parse_job_metadata
from worker.services.llm_service import LLMService

def test_metadata_extraction():
    print("--- Test Case 1: Metadata Extraction (Split-Screen / Voiceover Job) ---")
    # A standard split-screen job
    job = {
        "id": 999,
        "video_title_idea": "Thấy bình yên từ lòng biết ơn",
        "scenes_layout_json": json.dumps([{"scene_id": 1, "duration": 4}]),
        "seo_tags_metadata": json.dumps({
            "title": "Bình yên từ điều nhỏ nhặt",
            "hashtags": ["chualanh", "bieton"],
            "tiktok_microblog_caption": "Hãy biết ơn những điều nhỏ bé xung quanh ta.",
            "pinned_comment": "Bình yên không ở đâu xa, nó nằm ngay trong những điều nhỏ bé..."
        }),
        "raw_topic": "Lòng biết ơn",
        "full_voice_script": "Cảm ơn vì những điều nhỏ nhặt.",
        "bg_music_url": "http://example.com/some_music.mp3", # Background music url but NOT a music_reactive job
        "audio_style_hint": "chill",
        "pipeline_state": "RENDERED"
    }
    
    music_meta = extract_publish_music_metadata(job)
    print("Extracted music metadata (should be empty dict for non-music job):", music_meta)
    assert music_meta == {}, "Music metadata should be empty for voiceover jobs"
    
    metadata = parse_job_metadata(job)
    seo_data = json.loads(job["seo_tags_metadata"])
    caption, hashtags = build_publish_caption_and_hashtags(job, metadata, seo_data, music_meta)
    print("Generated Caption:", caption)
    print("Generated Hashtags:", hashtags)
    assert "Hãy biết ơn" in caption, "Caption should match tiktok_microblog_caption"
    print("Test Case 1 Passed! \u2705")

def test_llm_comment_generation():
    print("\n--- Test Case 2: LLM Comment Generation ---")
    llm = LLMService()
    if not llm.api_available:
        print("API keys not available, skipping real LLM call (will verify fallback)")
    
    topic = "Biết ơn những điều nhỏ bé"
    script = "Đôi khi vấp ngã giúp ta nhìn sâu sắc hơn vào bản thân. Thắt chặt lại dây giày cũ để bước tiếp..."
    comment = llm.generate_philosophical_comment(topic, script)
    print("Generated Comment:\n", comment)
    assert len(comment) > 50, "Comment should be generated with reasonable length"
    print("Test Case 2 Passed! \u2705")

def test_publisher_mock():
    print("\n--- Test Case 3: Playwright Commenting Mock & Signature Checks ---")
    from worker.services.publisher_service import PublisherService
    import inspect
    
    publisher = PublisherService()
    sig = inspect.signature(publisher.publish_video_to_tiktok)
    print("publish_video_to_tiktok signature:", sig)
    assert "comment_text" in sig.parameters, "publish_video_to_tiktok signature should accept comment_text"
    print("Test Case 3 Passed! \u2705")

if __name__ == "__main__":
    try:
        test_metadata_extraction()
        test_llm_comment_generation()
        test_publisher_mock()
        print("\nAll Tests Passed!")
    except Exception as e:
        print("\nTest Failed!")
        import traceback
        traceback.print_exc()
        sys.exit(1)
