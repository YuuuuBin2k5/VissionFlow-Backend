import re
from pathlib import Path

# Path to the file
file_path = Path("worker/services/reactive_template_service.py")
content = file_path.read_text(encoding="utf-8")

# 1. Inject visual_template routing at create_template start
target_signature = 'theme = self.get_mood_theme(mood)\n        visual_plan = visual_plan or {}\n        visual_assets = visual_assets or {}'
replacement_routing = """theme = self.get_mood_theme(mood)
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
            )"""

if target_signature in content:
    content = content.replace(target_signature, replacement_routing)
    print("[SUCCESS] Routing successfully injected into create_template!")
else:
    print("[ERROR] Target signature for routing injection not found in file!")

# 2. Append both Selena (Type 2) and Lofi Anime (Type 3) visualizer templates to the end of the ReactiveTemplateService class
# The class file ends with the create_template HTML wrapper close block
end_marker = """        html_path.write_text(html_doc, encoding="utf-8")
        return str(html_path)"""

selena_code = """    def create_selena_template(
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

        video_layers = "" if is_overlay else "\\n  ".join(
            f'<video id="bg{index}" class="bg-video{" active" if index == 0 else ""}" src="{uri}" muted loop playsinline preload="auto"></video>'
            for index, uri in enumerate(video_uris)
        )
        if video_layers:
            video_layers = video_layers.replace('id="bg0"', 'id="bg"')

        # HTML document for the premium Selena visualizer layout
        html_doc = f\"\"\"<!DOCTYPE html>
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
\"\"\"
        html_path.write_text(html_doc, encoding="utf-8")
        return str(html_path)
"""

lofi_code = """    def create_lofi_anime_template(
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

        video_layers = "" if is_overlay else "\\n  ".join(
            f'<video id="bg{index}" class="bg-video{" active" if index == 0 else ""}" src="{uri}" muted loop playsinline preload="auto"></video>'
            for index, uri in enumerate(video_uris)
        )
        if video_layers:
            video_layers = video_layers.replace('id="bg0"', 'id="bg"')

        # HTML document for the premium Lofi Anime visualizer layout
        html_doc = f\"\"\"<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Caveat:wght@700&family=Montserrat:wght@700;800;900&display=swap');
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
      filter: brightness(0.65) saturate(1.1) sepia(0.08);
      transform: scale(1.0);
      transition: opacity .2s ease-in-out;
    }}
    .bg-video.active {{
      opacity: 0.85;
    }}
    .song-indicator {{
      position: absolute;
      bottom: 96px;
      left: 96px;
      color: rgba(255, 255, 255, 0.8);
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
    .caption-overlay {{
      position: absolute;
      left: 80px;
      right: 80px;
      top: 50%;
      transform: translateY(-50%);
      text-align: center;
      color: #fff;
      font-family: 'Caveat', cursive, serif;
      font-size: 76px;
      font-weight: 700;
      line-height: 1.3;
      text-shadow: 0 0 20px rgba(255, 255, 255, 0.4), 0 0 40px {accent}55, 0 4px 20px rgba(0, 0, 0, 0.95);
      z-index: 10;
      transition: opacity 0.25s ease-in-out, transform 0.25s ease-in-out;
      opacity: 0;
      display: none;
    }}
  </style>
</head>
<body>
  <div class="stage" id="stage">
    {video_layers}
  </div>
  <div class="grain-overlay"></div>
  <div class="vignette"></div>
  
  <canvas id="firefliesCanvas" style="position: absolute; inset: 0; pointer-events: none; z-index: 5;"></canvas>
  
  <div class="song-indicator">
    <div class="indicator-title">{html.escape(song_title)}</div>
    <div class="indicator-artist">{html.escape(artist_name)}</div>
    <div class="indicator-divider"></div>
    <div class="indicator-time" id="indicatorTime">00:00 / 00:00</div>
  </div>

  <div class="caption-overlay" id="captionOverlay"></div>

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
    const particleCount = 20;
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
      const fps = audioData.fps || 24;
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
          if (nextIndex !== activeCaptionIndex) {{
            activeCaptionIndex = nextIndex;
            captionOverlay.style.display = 'block';
            captionOverlay.style.opacity = '1';
            captionOverlay.textContent = captionTimeline[nextIndex].text;
            captionOverlay.style.transform = `translateY(-50%) scale(${{1.0 + bass * 0.03}})`;
          }} else {{
            captionOverlay.style.transform = `translateY(-50%) scale(${{1.0 + bass * 0.03}})`;
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
\"\"\"
        html_path.write_text(html_doc, encoding="utf-8")
        return str(html_path)
"""

# Append both methods
content = content + "\n\n" + selena_code + "\n\n" + lofi_code

file_path.write_text(content, encoding="utf-8")
print("[SUCCESS] Appended both Type 2 (Selena) and Type 3 (Lofi Anime) templates flawlessly!")
