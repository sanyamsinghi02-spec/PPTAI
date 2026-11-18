import base64
import json
import zipfile
import io
import streamlit as st

# ==========================================
# SECURE MULTI-KEY ROTATION CONFIGURATION
# ==========================================
key1 = st.secrets.get("GEMINI_API_KEY", "")
key2 = st.secrets.get("GEMINI_API_KEY_2", "")
key3 = st.secrets.get("GEMINI_API_KEY_3", "")

GEMINI_API_KEYS = f"{key1},{key2},{key3}"
# ==========================================

st.set_page_config(
    page_title="AI-Enabled Presentation Player", page_icon="✨", layout="centered"
)

st.title("✨ AI-Enabled Presentation Player")
st.markdown(
    "Upload your slides **.zip file** to launch an interactive player with"
    " **live voice-controlled AI slide generation**."
)

uploaded_file = st.file_uploader(
    "Upload slides archive (.zip)", type=["zip"]
)


def extract_slides_from_zip(zip_bytes) -> list[str]:
  slide_images = []
  with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
    file_list = sorted(
        [
            f
            for f in z.namelist()
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
            and not f.startswith("__MACOSX/")
        ]
    )

    for filename in file_list:
      img_data = z.read(filename)
      b64 = base64.b64encode(img_data).decode("utf-8")
      slide_images.append(f"data:image/png;base64,{b64}")

  return slide_images


def build_ai_player_html(slides_b64: list[str], keys_string: str) -> str:
  keys_list = [k.strip() for k in keys_string.split(",") if k.strip()]
  keys_js_array = json.dumps(keys_list)

  slides_html = ""
  for idx, img_data in enumerate(slides_b64):
    active_cls = "active" if idx == 0 else ""
    slides_html += f"""
        <section class="slide ppt-image-slide {active_cls}">
            <img src="{img_data}" alt="Slide {idx+1}" />
        </section>
        """

  return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>AI-Enabled Presentation</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, sans-serif; }}
    body {{ background: #000; color: #f8fafc; overflow: hidden; height: 100vh; display: flex; flex-direction: column; outline: none; }}

    #deck {{ flex: 1; position: relative; width: 100%; height: 100%; }}
    .slide {{
      position: absolute; inset: 0;
      display: none; flex-direction: column; justify-content: center; align-items: center;
      background: #000;
    }}
    .slide.active {{ display: flex; }}

    .ppt-image-slide img {{ width: 100%; height: 100%; object-fit: contain; }}

    .ai-generated-slide {{ padding: 6% 10%; align-items: flex-start; justify-content: center; background: radial-gradient(circle at top right, #1e293b, #0f172a); }}
    .ai-generated-slide h1 {{ font-size: 3.2rem; color: #38bdf8; margin-bottom: 1.5rem; line-height: 1.2; }}
    .ai-generated-slide ul {{ list-style: none; font-size: 1.7rem; line-height: 1.7; color: #e2e8f0; }}
    .ai-generated-slide li {{ margin-bottom: 1rem; padding-left: 1.8rem; position: relative; }}
    .ai-generated-slide li::before {{ content: "▹"; position: absolute; left: 0; color: #38bdf8; font-weight: bold; }}

    #nav-controls {{
      position: fixed; bottom: 14px; left: 20px;
      display: flex; gap: 8px; z-index: 60;
    }}
    .nav-btn {{
      background: rgba(30, 41, 59, 0.9); color: #f8fafc; border: 1px solid #475569;
      padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; font-weight: 600;
    }}
    .nav-btn:hover {{ background: rgba(51, 65, 85, 1); border-color: #38bdf8; }}

    #hud {{
      position: fixed; bottom: 14px; right: 22px;
      background: rgba(15, 23, 42, 0.85); padding: 6px 12px; border-radius: 6px;
      font-size: 0.85rem; color: #94a3b8; z-index: 50; border: 1px solid #334155;
    }}

    #ai-bar {{
      position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
      width: 720px; max-width: 90vw;
      background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(12px);
      border: 1px solid #38bdf8; border-radius: 12px;
      padding: 14px 18px; display: none; align-items: center; gap: 12px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8); z-index: 100;
    }}
    #ai-bar.open {{ display: flex; }}
    #ai-input {{ flex: 1; background: transparent; border: none; outline: none; color: #fff; font-size: 1.1rem; }}
    
    .mic-btn {{
      background: #ef4444; color: white; border: none; border-radius: 50%;
      width: 36px; height: 36px; cursor: pointer; display: flex; align-items: center; justify-content: center;
      font-size: 1rem; transition: transform 0.2s;
    }}
    .mic-btn.listening {{ background: #22c55e; animation: pulse 1.5s infinite; }}
    @keyframes pulse {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(1.1); }} 100% {{ transform: scale(1); }} }}

    #ai-status {{ font-size: 0.85rem; color: #38bdf8; white-space: nowrap; }}
  </style>
</head>
<body tabindex="0" id="player-body">
  <div id="deck">{slides_html}</div>

  <div id="nav-controls">
    <button class="nav-btn" onclick="prevSlide()">◀ Prev</button>
    <button class="nav-btn" onclick="nextSlide()">Next ▶</button>
  </div>

  <div id="hud">Slide <span id="slide-num">1</span> / <span id="slide-total">{len(slides_b64)}</span> &nbsp;|&nbsp; Press <strong>/</strong> for AI</div>

  <div id="ai-bar">
    <span>✨</span>
    <input type="text" id="ai-input" placeholder="Type or click mic to speak command..." />
    <button id="mic-btn" class="mic-btn" onclick="toggleSpeechRecognition()" title="Voice Input">🎤</button>
    <span id="ai-status"></span>
  </div>

  <script>
    const API_KEYS = {keys_js_array};
    let keyIndex = 0;
    let currentSlide = 0;

    const aiBar = document.getElementById("ai-bar");
    const aiInput = document.getElementById("ai-input");
    const aiStatus = document.getElementById("ai-status");
    const micBtn = document.getElementById("mic-btn");
    const playerBody = document.getElementById("player-body");

    window.onload = () => {{ playerBody.focus(); }};

    function updateSlides() {{
      const slides = document.querySelectorAll(".slide");
      slides.forEach((s, i) => s.classList.toggle("active", i === currentSlide));
      document.getElementById("slide-num").textContent = currentSlide + 1;
      document.getElementById("slide-total").textContent = slides.length;
    }}

    function nextSlide() {{
      const total = document.querySelectorAll(".slide").length;
      if (currentSlide < total - 1) {{ currentSlide++; updateSlides(); }}
    }}

    function prevSlide() {{
      if (currentSlide > 0) {{ currentSlide--; updateSlides(); }}
    }}

    let recognition = null;
    let isListening = false;

    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {{
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;

      recognition.onstart = () => {{
        isListening = true;
        micBtn.classList.add("listening");
        aiStatus.textContent = "Listening...";
      }};

      recognition.onresult = (event) => {{
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {{
          transcript += event.results[i][0].transcript;
        }}
        aiInput.value = transcript;
      }};
