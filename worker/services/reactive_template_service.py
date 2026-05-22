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
