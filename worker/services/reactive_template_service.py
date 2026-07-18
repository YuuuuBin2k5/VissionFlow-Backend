import html
import json
from pathlib import Path

from worker.config import ASSETS_DIR


MOOD_THEMES = {
    "SAD_RAIN": {
        "keywords": "rainy night window portrait",
        "accent": "#9cc9ff",
        "background": "#06111f",
    },
    "CYBERPUNK_NIGHT": {
        "keywords": "cyberpunk neon city portrait",
        "accent": "#ff3df2",
        "background": "#090016",
    },
    "COZY_CHILL": {
        "keywords": "cozy room warm lights portrait",
        "accent": "#ffd166",
        "background": "#160f08",
    },
    "FOCUS_LOFI": {
        "keywords": "lofi desk study night portrait",
        "accent": "#72efdd",
        "background": "#071917",
    },
}


class ReactiveTemplateService:
    def get_mood_theme(self, mood: str) -> dict:
        return MOOD_THEMES.get(mood, MOOD_THEMES["FOCUS_LOFI"])

    def create_template(
        self,
        job_id: int,
        song_title: str,
        artist_name: str,
        caption: str,
        mood: str,
        background_video_path: str,
        audio_data: dict,
        caption_timeline: list | None = None,
        visual_plan: dict | None = None,
        visual_assets: dict | None = None,
        template_mode: str = "full_video",
    ) -> str:
        theme = self.get_mood_theme(mood)
        visual_plan = visual_plan or {}
        visual_assets = visual_assets or {}
        visual_template = visual_plan.get("visual_template") or visual_plan.get("music_video_template") or "type_1"
        if visual_template == "type_2":
            return self.create_selena_template(
                job_id=job_id,
                song_title=song_title,
                artist_name=artist_name,
                caption=caption,
                mood=mood,
                background_video_path=background_video_path,
                audio_data=audio_data,
                caption_timeline=caption_timeline,
                visual_plan=visual_plan,
                visual_assets=visual_assets,
                template_mode=template_mode,
            )
        elif visual_template == "lofi_anime":
            return self.create_lofi_anime_template(
                job_id=job_id,
                song_title=song_title,
                artist_name=artist_name,
                caption=caption,
                mood=mood,
                background_video_path=background_video_path,
                audio_data=audio_data,
                caption_timeline=caption_timeline,
                visual_plan=visual_plan,
                visual_assets=visual_assets,
                template_mode=template_mode,
            )
        visual_mode = visual_plan.get("visual_mode") or "portrait_lyric"
        is_overlay = template_mode == "transparent_overlay"
        effect_intensity = visual_plan.get("effect_intensity") or "soft"
        accent = visual_plan.get("accent") or theme["accent"]
        color_grade = visual_plan.get("color_grade") or "soft_lofi"
        video_paths = visual_assets.get("background_video_paths") or [background_video_path]
        video_uris = [Path(path).resolve().as_uri() for path in video_paths if path and Path(path).exists()]
        if not video_uris and background_video_path:
            video_uris = [Path(background_video_path).resolve().as_uri()]
        portrait_path = visual_assets.get("portrait_image_path")
        portrait_uri = Path(portrait_path).resolve().as_uri() if portrait_path and Path(portrait_path).exists() else ""
        html_path = Path(ASSETS_DIR) / f"reactive_render_{job_id}.html"
        payload = json.dumps(audio_data, ensure_ascii=False)
        captions_payload = json.dumps(caption_timeline or [], ensure_ascii=False)
        plan_payload = json.dumps(visual_plan, ensure_ascii=False)
        font_path = Path("shared/fonts/Montserrat-ExtraBold.ttf").resolve().as_uri()
        video_layers = "" if is_overlay else "\n  ".join(
            f'<video id="bg{index}" class="bg-video{" active" if index == 0 else ""}" src="{uri}" muted loop playsinline preload="auto"></video>'
            for index, uri in enumerate(video_uris)
        )
        if video_layers:
            video_layers = video_layers.replace('id="bg0"', 'id="bg"')
        portrait_markup = (
            f'<img class="portrait-bg" src="{portrait_uri}" />\n'
            f'  <img class="portrait-main" id="portraitMain" src="{portrait_uri}" />'
            if portrait_uri and visual_mode == "portrait_lyric" and not is_overlay
            else ""
        )
        body_class = f"mode-{html.escape(visual_mode)} intensity-{html.escape(effect_intensity)} grade-{html.escape(color_grade)} template-{html.escape(template_mode)}"

        html_doc = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <style>
    @font-face {{
      font-family: 'Montserrat';
      src: url('{font_path}') format('truetype');
      font-weight: 800;
      font-style: normal;
    }}
    body {{
      margin: 0;
      width: 1080px;
      height: 1920px;
      overflow: hidden;
      background: {'transparent' if is_overlay else theme["background"]};
      font-family: 'Montserrat', Arial, sans-serif;
    }}
    .stage {{
      position: absolute;
      inset: 0;
      overflow: hidden;
      background: {theme["background"]};
    }}
    .template-transparent_overlay .stage,
    .template-transparent_overlay .veil {{
      display: none;
    }}
    .bg-video, .portrait-bg {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: 0;
      filter: blur(9px) brightness(0.58) saturate(1.15);
      transform: scale(1.08);
      transition: opacity .12s linear, filter .12s linear, transform .12s linear;
    }}
    .bg-video.active {{
      opacity: 1;
    }}
    .mode-portrait_lyric .bg-video {{
      opacity: .42;
    }}
    .mode-portrait_lyric .portrait-bg {{
      opacity: 1;
      filter: blur(24px) brightness(.46) saturate(1.18);
      transform: scale(1.18);
    }}
    .portrait-main {{
      position: absolute;
      left: 126px;
      right: 126px;
      top: 244px;
      width: 828px;
      height: 1040px;
      object-fit: cover;
      border-radius: 26px;
      box-shadow: 0 32px 100px rgba(0,0,0,.64), 0 0 80px {accent}55;
      border: 1px solid rgba(255,255,255,.18);
      transform-origin: center;
    }}
    .grade-neon_contrast .bg-video.active {{
      filter: blur(6px) brightness(.72) saturate(1.55) contrast(1.18);
    }}
    .grade-high_contrast .bg-video.active {{
      filter: blur(6px) brightness(.66) saturate(1.32) contrast(1.2);
    }}
    .grade-warm_soft .bg-video.active, .grade-warm_soft .portrait-bg {{
      filter: blur(18px) brightness(.55) saturate(1.18) sepia(.1);
    }}
    .stage.hit .bg-video.active {{
      filter: blur(4px) brightness(1.02) saturate(1.45);
      transform: scale(1.12);
    }}
    .stage.hit .portrait-main {{
      transform: scale(1.055) rotate(.8deg);
    }}
    .veil {{
      position: absolute;
      inset: 0;
      background: radial-gradient(circle at 50% 30%, transparent 0, rgba(0,0,0,.25) 45%, rgba(0,0,0,.76) 100%);
    }}
    .flash {{
      position: absolute;
      inset: 0;
      background: rgba(255,255,255,.92);
      opacity: 0;
      pointer-events: none;
      mix-blend-mode: screen;
    }}
    .rgb {{
      position: absolute;
      inset: 0;
      opacity: 0;
      pointer-events: none;
      background: linear-gradient(90deg, rgba(255,0,80,.18), transparent 35%, rgba(0,220,255,.18));
      mix-blend-mode: screen;
      transform: translateX(0);
    }}
    .card {{
      position: absolute;
      left: 82px;
      right: 82px;
      bottom: 172px;
      min-height: 250px;
      padding: 0;
      box-sizing: border-box;
      background: transparent;
      transform-origin: center;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      align-items: center;
      text-align: center;
    }}
    h1 {{
      color: #fff;
      font-size: 28px;
      font-weight: 800;
      line-height: 1.15;
      margin: 0 0 6px;
      word-wrap: break-word;
      text-shadow: 0 3px 24px rgba(0,0,0,.9);
    }}
    .artist {{
      color: rgba(255,255,255,.72);
      font-size: 20px;
      margin: 0 0 28px;
      text-shadow: 0 3px 18px rgba(0,0,0,.9);
    }}
    .caption {{
      color: rgba(255,255,255,.96);
      display: inline-block;
      max-width: 820px;
      padding: 14px 23px 16px;
      border-radius: 12px;
      background: rgba(0,0,0,.48);
      border: 1px solid rgba(255,255,255,.14);
      font-size: 31px;
      line-height: 1.24;
      min-height: 0;
      margin: 0 0 24px;
      word-wrap: break-word;
      text-wrap: balance;
      text-shadow: 0 3px 22px rgba(0,0,0,.82), 0 0 14px {accent}88;
      opacity: .96;
      transform: translateY(0);
      filter: blur(0);
      transition: opacity .18s ease, transform .18s ease, filter .18s ease;
    }}
    .caption.switching {{
      opacity: .12;
      transform: translateY(18px);
      filter: blur(6px);
    }}
    .spectrum {{
      display: flex;
      align-items: flex-end;
      justify-content: center;
      gap: 8px;
      height: 54px;
      margin-top: 6px;
    }}
    .bar {{
      width: 8px;
      min-height: 10px;
      border-radius: 8px;
      background: linear-gradient(to top, #fff, {theme["accent"]});
      box-shadow: 0 0 18px {accent};
    }}
    .disc {{
      position: absolute;
      width: 260px;
      height: 260px;
      border-radius: 50%;
      right: 96px;
      top: 190px;
      background: radial-gradient(circle, #111 0 12%, {accent} 13% 15%, #111 16% 100%);
      box-shadow: 0 0 70px {accent};
    }}
    .template-transparent_overlay .disc {{
      display: none;
    }}
    .template-transparent_overlay .card {{
      bottom: 132px;
    }}
    .template-transparent_overlay h1,
    .template-transparent_overlay .artist {{
      opacity: .72;
    }}
    .mode-portrait_lyric .disc {{
      opacity: .38;
    }}
    .mode-beat_cut_video .disc {{
      opacity: .78;
    }}
    .mode-beat_cut_video .card {{
      bottom: 136px;
    }}
    .intensity-hard .caption {{
      background: rgba(0,0,0,.38);
      border-color: rgba(255,255,255,.2);
    }}
  </style>
</head>
<body class="{body_class}">
  <div class="stage" id="stage">
  {video_layers}
  {portrait_markup}
  </div>
  <div class="veil"></div>
  <div class="flash" id="flash"></div>
  <div class="rgb" id="rgb"></div>
  <div class="disc" id="disc"></div>
  <div class="card" id="card">
    <h1>{html.escape(song_title)}</h1>
    <div class="artist">{html.escape(artist_name)}</div>
    <div class="caption">{html.escape(caption)}</div>
    <div class="spectrum" id="spectrum"></div>
  </div>
  <script>
    const audioData = {payload};
    const captionTimeline = {captions_payload};
    const visualPlan = {plan_payload};
    const bars = [];
    const totalBars = 28;
    const stage = document.getElementById('stage');
    const flash = document.getElementById('flash');
    const rgb = document.getElementById('rgb');
    const spectrum = document.getElementById('spectrum');
    const card = document.getElementById('card');
    const disc = document.getElementById('disc');
    const portraitMain = document.getElementById('portraitMain');
    const captionEl = document.querySelector('.caption');
    const videoLayers = Array.from(document.querySelectorAll('.bg-video'));
    const cutEvents = audioData.cut_events || [];
    const dropEvents = audioData.drop_events || [];
    let activeCaptionIndex = -1;
    let activeVideoIndex = 0;
    
    // Auto-adjust font size for long titles and captions to prevent layout overflow
    const titleEl = document.querySelector('h1');
    if (titleEl) {{
      const textLen = titleEl.textContent.length;
      if (textLen > 35) {{
        titleEl.style.fontSize = '30px';
      }} else if (textLen > 22) {{
        titleEl.style.fontSize = '38px';
      }}
    }}
    
    if (captionEl) {{
      const textLen = captionEl.textContent.length;
      if (textLen > 100) {{
        captionEl.style.fontSize = '22px';
        captionEl.style.lineHeight = '1.2';
      }} else if (textLen > 60) {{
        captionEl.style.fontSize = '26px';
        captionEl.style.lineHeight = '1.2';
      }}
    }}

    for (let i = 0; i < totalBars; i++) {{
      const bar = document.createElement('div');
      bar.className = 'bar';
      spectrum.appendChild(bar);
      bars.push(bar);
    }}
    window.updateVisualsForFrame = function(frameIndex) {{
      const currentTime = frameIndex / (audioData.fps || 24);
      videoLayers.forEach(video => {{
        if (video && Number.isFinite(video.duration) && video.duration > 0) {{
          video.currentTime = currentTime % video.duration;
        }}
      }});
      if (videoLayers.length > 1 && cutEvents.length) {{
        let cutIndex = 0;
        for (let i = 0; i < cutEvents.length; i++) {{
          if (currentTime >= cutEvents[i].time) cutIndex = i + 1;
        }}
        const nextVideoIndex = cutIndex % videoLayers.length;
        if (nextVideoIndex !== activeVideoIndex) {{
          videoLayers[activeVideoIndex]?.classList.remove('active');
          activeVideoIndex = nextVideoIndex;
          videoLayers[activeVideoIndex]?.classList.add('active');
        }}
      }}
      if (captionTimeline.length && captionEl) {{
        const nextIndex = captionTimeline.findIndex(item => currentTime >= item.start && currentTime < item.end);
        if (nextIndex !== -1 && nextIndex !== activeCaptionIndex) {{
          activeCaptionIndex = nextIndex;
          captionEl.classList.add('switching');
          captionEl.textContent = captionTimeline[nextIndex].text;
          const len = captionEl.textContent.length;
          captionEl.style.fontSize = len > 64 ? '22px' : len > 44 ? '26px' : '31px';
          void captionEl.offsetWidth;
          captionEl.classList.remove('switching');
        }}
      }}
      const bass = audioData.bass[frameIndex] || 0.05;
      const mid = audioData.mid[frameIndex] || 0.05;
      const treble = audioData.treble[frameIndex] || 0.05;
      const nearDrop = dropEvents.find(event => Math.abs(currentTime - event.time) < 0.12);
      const nearCut = cutEvents.find(event => Math.abs(currentTime - event.time) < 0.1);
      const hitStrength = Math.max(bass, nearDrop ? nearDrop.strength || 0.8 : 0, nearCut ? nearCut.strength || 0.5 : 0);
      if (stage) {{
        stage.classList.toggle('hit', hitStrength > 0.68);
      }}
      if (flash) {{
        const flashPower = nearDrop ? Math.min(0.5, 0.16 + hitStrength * 0.42) : 0;
        flash.style.opacity = `${{flashPower}}`;
      }}
      if (rgb) {{
        const useGlitch = visualPlan.effect_intensity === 'hard' && nearDrop;
        rgb.style.opacity = useGlitch ? `${{Math.min(.38, .12 + hitStrength * .24)}}` : '0';
        rgb.style.transform = `translateX(${{useGlitch ? Math.sin(frameIndex) * 16 : 0}}px)`;
      }}
      bars.forEach((bar, index) => {{
        const wave = Math.sin((index / (totalBars - 1)) * Math.PI);
        const energy = (bass * 0.65) + (mid * 0.25) + (treble * 0.1);
        bar.style.height = `${{12 + energy * 120 * wave}}px`;
        bar.style.opacity = `${{0.45 + energy * 0.55}}`;
      }});
      card.style.transform = `scale(${{1 + bass * 0.04 + (nearDrop ? 0.025 : 0)}})`;
      card.style.boxShadow = `0 0 ${{50 + bass * 90}}px rgba(255,255,255,.16)`;
      disc.style.transform = `rotate(${{frameIndex * 2.5}}deg) scale(${{1 + bass * 0.05}})`;
      if (portraitMain) {{
        const slowZoom = 1.025 + Math.sin(currentTime * 0.18) * 0.018 + bass * 0.014;
        const slowRotate = Math.sin(currentTime * 0.12) * 1.2;
        portraitMain.style.transform = `scale(${{slowZoom}}) rotate(${{slowRotate}}deg)`;
      }}
      if (captionEl) {{
        captionEl.style.transform = `translateY(${{-4 - bass * 8}}px)`;
      }}
    }};
  </script>
</body>
</html>
"""
        html_path.write_text(html_doc, encoding="utf-8")
        return str(html_path)


    def create_selena_template(
        self,
        job_id: int,
        song_title: str,
        artist_name: str,
        caption: str,
        mood: str,
        background_video_path: str,
        audio_data: dict,
        caption_timeline: list | None = None,
        visual_plan: dict | None = None,
        visual_assets: dict | None = None,
        template_mode: str = "full_video",
    ) -> str:
        theme = self.get_mood_theme(mood)
        visual_plan = visual_plan or {}
        visual_assets = visual_assets or {}
        is_overlay = template_mode == "transparent_overlay"
        accent = visual_plan.get("accent") or "#ccff00" # High-fidelity Selena lime green glow
        video_paths = visual_assets.get("background_video_paths") or [background_video_path]
        video_uris = [Path(path).resolve().as_uri() for path in video_paths if path and Path(path).exists()]
        if not video_uris and background_video_path:
            video_uris = [Path(background_video_path).resolve().as_uri()]
        
        portrait_path = visual_assets.get("portrait_image_path")
        portrait_uri = Path(portrait_path).resolve().as_uri() if portrait_path and Path(portrait_path).exists() else ""
        
        html_path = Path(ASSETS_DIR) / f"reactive_render_{job_id}.html"
        payload = json.dumps(audio_data, ensure_ascii=False)
        captions_payload = json.dumps(caption_timeline or [], ensure_ascii=False)
        plan_payload = json.dumps(visual_plan, ensure_ascii=False)

        import base64
        font_file = Path("shared/fonts/Montserrat-ExtraBold.ttf")
        font_src = font_file.resolve().as_uri()
        if font_file.exists():
            try:
                with open(font_file, "rb") as f:
                    font_base64 = base64.b64encode(f.read()).decode("utf-8")
                font_src = f"data:font/ttf;base64,{font_base64}"
            except Exception as e:
                print(f"[ReactiveTemplateService Warning] Failed to read font file as base64 for Type 2: {e}")

        video_layers = "" if is_overlay else "\n  ".join(
            f'<video id="bg{index}" class="bg-video{" active" if index == 0 else ""}" src="{uri}" muted loop playsinline preload="auto"></video>'
            for index, uri in enumerate(video_uris)
        )
        if video_layers:
            video_layers = video_layers.replace('id="bg0"', 'id="bg"')

        # HTML document for the premium Selena visualizer layout
        html_doc = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@800;900&display=swap');
    @font-face {{
      font-family: 'Montserrat';
      src: url('{font_src}') format('truetype');
      font-weight: 800;
      font-style: normal;
    }}
    body {{
      margin: 0;
      width: 1080px;
      height: 1920px;
      overflow: hidden;
      background: {'transparent' if is_overlay else '#050a12'};
      font-family: 'Montserrat', Arial, sans-serif;
    }}
    .stage {{
      position: absolute;
      inset: 0;
      overflow: hidden;
      background: {'transparent' if is_overlay else '#050a12'};
    }}
    .bg-video {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: 0;
      filter: brightness(0.68) saturate(1.15);
      transform: scale(1.0);
      transition: opacity .12s linear;
    }}
    .bg-video.active {{
      opacity: 0.7;
    }}
    .treble-clef {{
      position: absolute;
      top: 96px;
      left: 96px;
      font-size: 86px;
      color: #fff;
      font-family: 'Segoe UI Symbol', 'Apple Symbols', 'Noto Sans Symbols', sans-serif;
      text-shadow: 0 0 16px rgba(255,255,255,0.7), 0 0 30px {accent};
      z-index: 10;
      transform-origin: center;
      transition: transform 0.08s linear;
    }}
    .logo-box {{
      position: absolute;
      top: 96px;
      right: 96px;
      z-index: 10;
    }}
    .album-cover-box {{
      position: absolute;
      left: 96px;
      top: 460px;
      width: 440px;
      height: 440px;
      border-radius: 12px;
      overflow: hidden;
      border: 4px solid #fff;
      box-shadow: 0 0 25px rgba(255,255,255,0.4), 0 0 50px {accent};
      z-index: 5;
      transform-origin: center;
      transition: transform 0.08s linear, box-shadow 0.08s linear;
    }}
    .album-cover-img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}
    .info-box {{
      position: absolute;
      left: 580px;
      top: 520px;
      width: 400px;
      display: flex;
      flex-direction: column;
      z-index: 5;
      color: #fff;
    }}
    .song-title {{
      font-size: 52px;
      font-weight: 900;
      color: #ffff00;
      text-shadow: 0 4px 18px rgba(0, 0, 0, 0.95);
      text-transform: uppercase;
      margin: 0 0 10px 0;
      word-wrap: break-word;
      letter-spacing: 1px;
    }}
    .progress-time {{
      font-size: 32px;
      font-weight: 700;
      color: #fff;
      text-shadow: 0 2px 10px rgba(0, 0, 0, 0.8);
      margin-bottom: 20px;
      letter-spacing: 1px;
    }}
    .progress-bar-container {{
      position: relative;
      width: 400px;
      height: 16px;
      border: 3px solid #fff;
      border-radius: 0px;
      background: rgba(0, 0, 0, 0.3);
      overflow: hidden;
    }}
    .progress-bar-fill {{
      height: 100%;
      width: 0%;
      background: #fff;
      box-shadow: 0 0 12px #fff, 0 0 20px {accent};
    }}
    .progress-line-decor {{
      margin-top: 12px;
      width: 400px;
      border-top: 3px dotted rgba(255, 255, 255, 0.6);
    }}
    .chevron-controls {{
      position: absolute;
      right: 48px;
      top: 50%;
      transform: translateY(-50%);
      display: flex;
      flex-direction: column;
      gap: 20px;
      z-index: 10;
    }}
    .chevron-btn {{
      width: 64px;
      height: 64px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.1);
      border: 2px solid rgba(255, 255, 255, 0.25);
      backdrop-filter: blur(10px);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
      transition: transform 0.2s;
    }}
    .caption-overlay {{
      position: absolute;
      left: 100px;
      right: 100px;
      bottom: 220px;
      text-align: center;
      color: #fff;
      font-size: 44px;
      font-weight: 800;
      text-transform: uppercase;
      line-height: 1.4;
      text-shadow: 0 0 20px {accent}, 0 4px 16px rgba(0, 0, 0, 0.95);
      background: rgba(5, 8, 15, 0.42);
      backdrop-filter: blur(15px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      padding: 22px 32px;
      border-radius: 20px;
      z-index: 10;
      box-shadow: 0 20px 60px rgba(0,0,0,0.6);
      transition: opacity 0.15s ease, transform 0.15s ease;
      display: none;
    }}
  </style>
</head>
<body>
  <div class="stage" id="stage">
    {video_layers}
  </div>
  <canvas id="constellationCanvas" style="position: absolute; inset: 0; pointer-events: none; z-index: 1;"></canvas>
  
  <div class="treble-clef" id="trebleClef">&#x1D11E;</div>
  
  <div class="logo-box">
    <svg width="550" height="120" viewBox="0 0 550 120" style="overflow: visible;">
      <!-- Cyber circuit top path with 3 splits -->
      <path d="M 50 35 L 420 35 L 440 15 L 490 15" fill="none" stroke="#fff" stroke-width="2" />
      <circle cx="490" cy="15" r="4" fill="#fff" />
      
      <path d="M 420 35 L 445 35 L 475 35" fill="none" stroke="#fff" stroke-width="2" />
      <circle cx="475" cy="35" r="4" fill="#fff" />
      
      <path d="M 420 35 L 440 55 L 510 55" fill="none" stroke="#fff" stroke-width="2" />
      <circle cx="510" cy="55" r="4" fill="#fff" />
      
      <!-- Middle separating path -->
      <path d="M 200 80 L 430 80 L 445 95 L 485 95" fill="none" stroke="#fff" stroke-width="2" />
      <circle cx="485" cy="95" r="4" fill="#fff" />
      
      <!-- Text elements -->
      <text x="410" y="65" font-family="'Montserrat', sans-serif" font-weight="900" font-size="28" fill="#fff" text-anchor="end" letter-spacing="2">YUUUUBIN_CAPYBARA</text>
      <text x="410" y="95" font-family="'Montserrat', sans-serif" font-weight="800" font-size="14" fill="#fff" text-anchor="end" letter-spacing="8">MUSIC</text>
    </svg>
  </div>

  <div class="album-cover-box" id="albumCover">
    <img class="album-cover-img" src="{portrait_uri}" />
  </div>

  <div class="info-box">
    <h1 class="song-title">{html.escape(song_title)}</h1>
    <div class="progress-time" id="progressTime">0:00 - 0:00</div>
    <div class="progress-bar-container">
      <div class="progress-bar-fill" id="progressBarFill"></div>
    </div>
    <div class="progress-line-decor"></div>
  </div>

  <div class="chevron-controls">
    <div class="chevron-btn">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>
    </div>
    <div class="chevron-btn">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
    </div>
  </div>

  <div class="caption-overlay" id="captionOverlay"></div>

  <script>
    const audioData = {payload};
    const captionTimeline = {captions_payload};
    const visualPlan = {plan_payload};
    const stage = document.getElementById('stage');
    const albumCover = document.getElementById('albumCover');
    const trebleClef = document.getElementById('trebleClef');
    const progressTime = document.getElementById('progressTime');
    const progressBarFill = document.getElementById('progressBarFill');
    const captionOverlay = document.getElementById('captionOverlay');
    const videoLayers = Array.from(document.querySelectorAll('.bg-video'));
    const cutEvents = audioData.cut_events || [];
    
    let activeVideoIndex = 0;
    let activeCaptionIndex = -1;

    // Formatting helpers
    function formatTime(secs) {{
      const m = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return `${{m}}:${{s < 10 ? '0' : ''}}${{s}}`;
    }}

    // Setup visualizer canvas
    const canvas = document.getElementById('constellationCanvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 1080;
    canvas.height = 1920;

    // Heart particle system
    const hearts = [];
    const heartColumns = [420, 720, 900];
    
    function spawnHeart() {{
      if (hearts.length > 30) return;
      const colX = heartColumns[Math.floor(Math.random() * heartColumns.length)];
      hearts.push({{
        x: colX + (Math.random() - 0.5) * 40,
        y: 1950,
        vy: -1.2 - Math.random() * 1.5,
        size: 10 + Math.random() * 14,
        opacity: 0.15 + Math.random() * 0.35,
        fadeSpeed: 0.002 + Math.random() * 0.003
      }});
    }}

    function drawHeart(cx, cy, size, opacity) {{
      ctx.save();
      ctx.globalAlpha = opacity;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
      ctx.shadowBlur = 8;
      ctx.shadowColor = '{accent}';
      ctx.beginPath();
      const topY = cy - size / 2;
      ctx.moveTo(cx, cy + size / 3);
      ctx.bezierCurveTo(cx - size / 2, cy - size / 6, cx - size / 2, topY, cx, topY);
      ctx.bezierCurveTo(cx + size / 2, topY, cx + size / 2, cy - size / 6, cx, cy + size / 3);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }}

    // Dynamic constellation network particles
    const particles = [];
    const particleCount = 25;
    for (let i = 0; i < particleCount; i++) {{
      particles.push({{
        x: 100 + Math.random() * 880,
        y: 200 + Math.random() * 1500,
        vx: (Math.random() - 0.5) * 1.2,
        vy: (Math.random() - 0.5) * 1.2,
        baseRadius: 3 + Math.random() * 3
      }});
    }}

    function drawConstellation(bass, mid, treble) {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      // Update & Draw Heart Particles in Background
      if (Math.random() < 0.08) spawnHeart();
      for (let i = hearts.length - 1; i >= 0; i--) {{
        const h = hearts[i];
        h.y += h.vy * (1.0 + bass * 1.5);
        h.opacity -= h.fadeSpeed;
        if (h.opacity <= 0 || h.y < -50) {{
          hearts.splice(i, 1);
        }} else {{
          drawHeart(h.x, h.y, h.size, h.opacity);
        }}
      }}

      // Draw standard particle-to-particle constellation net
      const speedBoost = 1.0 + bass * 3.5;
      const sizeBoost = 1.0 + mid * 2.5;
      const opacityVal = 0.08 + bass * 0.32;

      ctx.strokeStyle = `rgba(173, 255, 47, ${{opacityVal}})`;
      ctx.lineWidth = 1.2 + bass * 2.8;
      
      for (let i = 0; i < particles.length; i++) {{
        for (let j = i + 1; j < particles.length; j++) {{
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 200) {{
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.stroke();
          }}
        }}
      }}

      particles.forEach(p => {{
        p.x += p.vx * speedBoost;
        p.y += p.vy * speedBoost;

        if (p.x < 50 || p.x > 1030) p.vx *= -1;
        if (p.y < 50 || p.y > 1870) p.vy *= -1;

        const r = p.baseRadius * sizeBoost;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${{0.5 + mid * 0.5}})`;
        ctx.shadowBlur = 8 + bass * 18;
        ctx.shadowColor = '{accent}';
        ctx.fill();
      }});

      // --- HIGH FIDELITY SELENA SIGNATURE CONSTELLATION LINE ---
      const nodeA = {{ x: 536, y: 900 }};
      const nodeB = {{ 
        x: 480 + Math.sin(Date.now() * 0.003) * (15 + bass * 30), 
        y: 980 + Math.cos(Date.now() * 0.003) * (15 + bass * 30) 
      }};
      const nodeC = {{ x: 580, y: 930 }};

      ctx.save();
      ctx.strokeStyle = '#ccff00';
      ctx.lineWidth = 4 + bass * 6;
      ctx.shadowBlur = 15 + bass * 25;
      ctx.shadowColor = '#ccff00';
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      ctx.beginPath();
      ctx.moveTo(nodeA.x, nodeA.y);
      ctx.lineTo(nodeB.x, nodeB.y);
      ctx.lineTo(nodeC.x, nodeC.y);
      ctx.stroke();

      ctx.shadowColor = '#ffff00';
      ctx.fillStyle = '#ffff00';
      const nodeRadius = 8 + bass * 6;

      [nodeB, nodeC].forEach(node => {{
        ctx.beginPath();
        ctx.arc(node.x, node.y, nodeRadius, 0, Math.PI * 2);
        ctx.fill();
      }});
      ctx.restore();
    }}

    window.updateVisualsForFrame = function(frameIndex) {{
      const fps = audioData.fps || 24;
      const currentTime = frameIndex / fps;
      const duration = audioData.duration || 60.0;

      // Video playback sync
      videoLayers.forEach(video => {{
        if (video && Number.isFinite(video.duration) && video.duration > 0) {{
          video.currentTime = currentTime % video.duration;
        }}
      }});

      if (videoLayers.length > 1 && cutEvents.length) {{
        let cutIndex = 0;
        for (let i = 0; i < cutEvents.length; i++) {{
          if (currentTime >= cutEvents[i].time) cutIndex = i + 1;
        }}
        const nextVideoIndex = cutIndex % videoLayers.length;
        if (nextVideoIndex !== activeVideoIndex) {{
          videoLayers[activeVideoIndex]?.classList.remove('active');
          activeVideoIndex = nextVideoIndex;
          videoLayers[activeVideoIndex]?.classList.add('active');
        }}
      }}

      // Progress indicators
      const progressPercent = Math.min(100, Math.max(0, (currentTime / duration) * 100));
      progressBarFill.style.width = `${{progressPercent}}%`;
      progressTime.textContent = `${{formatTime(currentTime)}} - ${{formatTime(duration)}}`;

      // Audio energies
      const bass = audioData.bass[frameIndex] || 0.05;
      const mid = audioData.mid[frameIndex] || 0.05;
      const treble = audioData.treble[frameIndex] || 0.05;

      // Pulse treble clef and album cover
      trebleClef.style.transform = `scale(${{1.0 + treble * 0.18}}) rotate(${{Math.sin(currentTime * 3) * 6 * treble}}deg)`;
      albumCover.style.transform = `scale(${{1.0 + bass * 0.06}}) rotate(${{Math.sin(currentTime * 1.5) * 1.5}}deg)`;
      albumCover.style.boxShadow = `0 24px 80px rgba(0,0,0,0.65), 0 0 ${{40 + bass * 80}}px {accent}`;

      // Render canvas constellation & hearts visualizer
      drawConstellation(bass, mid, treble);

      // Subtitles processing
      if (captionTimeline.length && captionOverlay) {{
        const nextIndex = captionTimeline.findIndex(item => currentTime >= item.start && currentTime < item.end);
        if (nextIndex !== -1) {{
          if (nextIndex !== activeCaptionIndex) {{
            activeCaptionIndex = nextIndex;
            captionOverlay.style.display = 'block';
            captionOverlay.style.opacity = '1';
            captionOverlay.textContent = captionTimeline[nextIndex].text;
            captionOverlay.style.transform = `translateY(${{-bass * 15}}px) scale(${{1 + bass * 0.03}})`;
          }} else {{
            captionOverlay.style.transform = `translateY(${{-bass * 15}}px) scale(${{1 + bass * 0.03}})`;
          }}
        }} else {{
          activeCaptionIndex = -1;
          captionOverlay.style.opacity = '0';
          captionOverlay.style.display = 'none';
        }}
      }}
    }};
  </script>
</body>
</html>
"""
        html_path.write_text(html_doc, encoding="utf-8")
        return str(html_path)


    def create_lofi_anime_template(
        self,
        job_id: int,
        song_title: str,
        artist_name: str,
        caption: str,
        mood: str,
        background_video_path: str,
        audio_data: dict,
        caption_timeline: list | None = None,
        visual_plan: dict | None = None,
        visual_assets: dict | None = None,
        template_mode: str = "full_video",
    ) -> str:
        theme = self.get_mood_theme(mood)
        visual_plan = visual_plan or {}
        visual_assets = visual_assets or {}
        is_overlay = template_mode == "transparent_overlay"
        accent = visual_plan.get("accent") or "#ffd166" # Warm nostalgic glow
        video_paths = visual_assets.get("background_video_paths") or [background_video_path]
        video_uris = [Path(path).resolve().as_uri() for path in video_paths if path and Path(path).exists()]
        if not video_uris and background_video_path:
            video_uris = [Path(background_video_path).resolve().as_uri()]
        
        html_path = Path(ASSETS_DIR) / f"reactive_render_{job_id}.html"
        payload = json.dumps(audio_data, ensure_ascii=False)
        captions_payload = json.dumps(caption_timeline or [], ensure_ascii=False)
        plan_payload = json.dumps(visual_plan, ensure_ascii=False)

        video_layers = "" if is_overlay else "\n  ".join(
            f'<video id="bg{index}" class="bg-video{" active" if index == 0 else ""}" src="{uri}" muted loop playsinline preload="auto"></video>'
            for index, uri in enumerate(video_uris)
        )
        if video_layers:
            video_layers = video_layers.replace('id="bg0"', 'id="bg"')

        # HTML document for the premium Lofi Anime visualizer layout
        html_doc = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700;800&family=Montserrat:wght@700;800;900&display=swap');
    body {{
      margin: 0;
      width: 1080px;
      height: 1920px;
      overflow: hidden;
      background: {'transparent' if is_overlay else '#05050a'};
      font-family: 'Montserrat', Arial, sans-serif;
    }}
    .stage {{
      position: absolute;
      inset: 0;
      overflow: hidden;
      background: {'transparent' if is_overlay else '#05050a'};
    }}
    .bg-video {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: 0;
      filter: brightness(0.52) contrast(1.15);
      transition: opacity .2s ease-in-out;
      z-index: 1;
      animation: kenBurns 45s infinite alternate ease-in-out;
      transform-origin: center;
    }}
    .bg-video.active {{
      opacity: 0.85;
    }}
    .gradient-overlay {{
      position: absolute;
      inset: 0;
      background: linear-gradient(to bottom, rgba(0,0,0,0) 40%, rgba(0,0,0,0.85) 100%);
      pointer-events: none;
      z-index: 2;
    }}
    .song-indicator {{
      position: absolute;
      top: 200px;
      left: 108px;
      color: rgba(255, 255, 255, 0.85);
      z-index: 10;
      text-align: left;
    }}
    .indicator-title {{
      font-size: 28px;
      font-weight: 800;
      letter-spacing: 1px;
      text-transform: uppercase;
      margin: 0 0 6px 0;
      text-shadow: 0 2px 8px rgba(0,0,0,0.8);
    }}
    .indicator-artist {{
      font-size: 18px;
      font-weight: 700;
      color: rgba(255, 255, 255, 0.55);
      letter-spacing: 1px;
      text-transform: uppercase;
      margin: 0;
      text-shadow: 0 2px 6px rgba(0,0,0,0.8);
    }}
    .indicator-divider {{
      width: 80px;
      height: 2px;
      background: rgba(255, 255, 255, 0.35);
      margin: 10px 0;
    }}
    .indicator-time {{
      font-size: 20px;
      font-weight: 700;
      font-family: monospace;
      color: {accent};
      text-shadow: 0 2px 6px rgba(0,0,0,0.8);
    }}
    .grain-overlay {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 8;
      background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
      opacity: 0.045;
      mix-blend-mode: overlay;
    }}
    .vignette {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 9;
      background: radial-gradient(circle, transparent 40%, rgba(0,0,0,0.72) 100%);
    }}
    .philosophy-card {{
      position: absolute;
      bottom: 380px;
      left: 108px;
      width: 864px; /* Perfectly centered 80% width in lower-center safe zone */
      background: rgba(10, 10, 15, 0.45);
      backdrop-filter: blur(25px);
      -webkit-backdrop-filter: blur(25px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 32px;
      padding: 60px 45px;
      box-sizing: border-box;
      z-index: 10;
      box-shadow: 0 30px 60px rgba(0,0,0,0.5), inset 0 1px 1px rgba(255,255,255,0.1);
      text-align: center;
      transition: opacity 0.3s ease, transform 0.3s ease;
      opacity: 0;
      transform: translateY(20px);
      display: none;
    }}
    .subtitle-word {{
      font-family: 'Montserrat', sans-serif;
      font-weight: 800;
      font-size: 52px;
      color: rgba(255, 255, 255, 0.45);
      display: inline-block;
      margin: 6px 12px;
      transition: all 0.15s ease-out;
      letter-spacing: 0.5px;
    }}
    .subtitle-word.active {{
      color: #FFD700; /* Rich gold highlight */
      text-shadow: 0 0 25px rgba(255, 215, 0, 0.6), 0 2px 4px rgba(0,0,0,0.8);
      transform: scale(1.15);
    }}
    @keyframes kenBurns {{
      0% {{ transform: scale(1.0) translate(0, 0); }}
      100% {{ transform: scale(1.08) translate(-2%, -1%); }}
    }}
  </style>
</head>
<body>
  <div class="stage" id="stage">
    {video_layers}
  </div>
  <div class="gradient-overlay"></div>
  <div class="grain-overlay"></div>
  <div class="vignette"></div>
  
  <canvas id="firefliesCanvas" style="position: absolute; inset: 0; pointer-events: none; z-index: 5;"></canvas>
  
  <div class="song-indicator">
    <div class="indicator-title">{html.escape(song_title)}</div>
    <div class="indicator-artist">{html.escape(artist_name)}</div>
    <div class="indicator-divider"></div>
    <div class="indicator-time" id="indicatorTime">00:00 / 00:00</div>
  </div>

  <div class="philosophy-card" id="captionOverlay"></div>

  <script>
    const audioData = {payload};
    const captionTimeline = {captions_payload};
    const visualPlan = {plan_payload};
    const stage = document.getElementById('stage');
    const indicatorTime = document.getElementById('indicatorTime');
    const captionOverlay = document.getElementById('captionOverlay');
    const videoLayers = Array.from(document.querySelectorAll('.bg-video'));
    const cutEvents = audioData.cut_events || [];
    
    let activeVideoIndex = 0;
    let activeCaptionIndex = -1;

    function formatTime(secs) {{
      const m = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return `${{m < 10 ? '0' : ''}}${{m}}:${{s < 10 ? '0' : ''}}${{s}}`;
    }}

    const canvas = document.getElementById('firefliesCanvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 1080;
    canvas.height = 1920;

    const particles = [];
    const particleCount = 25; // Optimized count
    for (let i = 0; i < particleCount; i++) {{
      particles.push({{
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.5,
        vy: -0.4 - Math.random() * 0.8,
        radius: 4 + Math.random() * 6,
        alpha: 0.15 + Math.random() * 0.5,
        phase: Math.random() * Math.PI * 2
      }});
    }}

    function drawFireflies(bass, treble) {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      
      const speedBoost = 1.0 + treble * 2.5;
      const glowBoost = 1.0 + bass * 1.5;

      particles.forEach(p => {{
        p.y += p.vy * speedBoost;
        p.x += p.vx + Math.sin(Date.now() * 0.001 + p.phase) * 0.25;

        if (p.y < -50) {{
          p.y = canvas.height + 50;
          p.x = Math.random() * canvas.width;
        }}
        if (p.x < -50 || p.x > canvas.width + 50) {{
          p.vx *= -1;
        }}

        const glow = Math.sin(Date.now() * 0.002 + p.phase) * 0.15 + 0.5;
        ctx.save();
        ctx.globalAlpha = p.alpha * glow * glowBoost;
        ctx.fillStyle = '{accent}';
        ctx.shadowBlur = 12 + bass * 20;
        ctx.shadowColor = '{accent}';
        
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }});
    }}

    window.updateVisualsForFrame = function(frameIndex) {{
      const fps = audioData.fps || 30; // 30 FPS standard
      const currentTime = frameIndex / fps;
      const duration = audioData.duration || 60.0;

      videoLayers.forEach(video => {{
        if (video && Number.isFinite(video.duration) && video.duration > 0) {{
          video.currentTime = currentTime % video.duration;
        }}
      }});

      if (videoLayers.length > 1 && cutEvents.length) {{
        let cutIndex = 0;
        for (let i = 0; i < cutEvents.length; i++) {{
          if (currentTime >= cutEvents[i].time) cutIndex = i + 1;
        }}
        const nextVideoIndex = cutIndex % videoLayers.length;
        if (nextVideoIndex !== activeVideoIndex) {{
          videoLayers[activeVideoIndex]?.classList.remove('active');
          activeVideoIndex = nextVideoIndex;
          videoLayers[activeVideoIndex]?.classList.add('active');
        }}
      }}

      indicatorTime.textContent = `${{formatTime(currentTime)}} / ${{formatTime(duration)}}`;

      const bass = audioData.bass[frameIndex] || 0.05;
      const treble = audioData.treble[frameIndex] || 0.05;

      stage.style.transform = `scale(${{1.0 + bass * 0.015}})`;

      drawFireflies(bass, treble);

      if (captionTimeline.length && captionOverlay) {{
        const nextIndex = captionTimeline.findIndex(item => currentTime >= item.start && currentTime < item.end);
        if (nextIndex !== -1) {{
          const item = captionTimeline[nextIndex];
          if (nextIndex !== activeCaptionIndex) {{
            activeCaptionIndex = nextIndex;
            captionOverlay.style.display = 'block';
            void captionOverlay.offsetWidth;
            captionOverlay.style.opacity = '1';
            captionOverlay.style.transform = 'translateY(0)';
            
            const words = item.text.split(' ');
            captionOverlay.innerHTML = words.map((w, idx) => `<span class="subtitle-word" id="word_${{nextIndex}}_${{idx}}">${{w}}</span>`).join(' ');
          }}
          
          const words = item.text.split(' ');
          const progress = (currentTime - item.start) / (item.end - item.start);
          const activeWordIndex = Math.min(words.length - 1, Math.max(0, Math.floor(progress * words.length)));
          
          words.forEach((_, idx) => {{
            const span = document.getElementById(`word_${{nextIndex}}_${{idx}}`);
            if (span) {{
              if (idx === activeWordIndex) {{
                span.classList.add('active');
              }} else {{
                span.classList.remove('active');
              }}
            }}
          }});
        }} else {{
          if (activeCaptionIndex !== -1) {{
            activeCaptionIndex = -1;
            captionOverlay.style.opacity = '0';
            captionOverlay.style.transform = 'translateY(20px)';
            setTimeout(() => {{
              if (activeCaptionIndex === -1) {{
                captionOverlay.style.display = 'none';
              }}
            }}, 300);
          }}
        }}
      }}
    }};
  </script>
</body>
</html>
"""
        html_path.write_text(html_doc, encoding="utf-8")
        return str(html_path)
