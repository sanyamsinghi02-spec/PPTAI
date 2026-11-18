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
    page_title="AI-Enabled Presentation Player", page_icon="✨", layout="wide"
)

st.title("✨ AI-Enabled Presentation Player")
st.markdown(
    "Upload your slides **.zip file** to launch an interactive player with"
    " **full conversational voice AI**."
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
  keys_json = json.dumps(keys_list)

  slides_html = ""
  for idx, img_data in enumerate(slides_b64):
    active_cls = "active" if idx == 0 else ""
    slides_html += (
        f'<section class="slide ppt-image-slide {active_cls}"><img'
        f' src="{img_data}" alt="Slide {idx+1}" /></section>'
    )

  html_template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>AI-Enabled Presentation</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, sans-serif; }
    body { background: #000; color: #f8fafc; overflow: hidden; height: 100vh; display: flex; flex-direction: column; outline: none; }

    #deck { flex: 1; position: relative; width: 100%; height: 100%; }
    .slide {
      position: absolute; inset: 0;
      display: none; flex-direction: column; justify-content: center; align-items: center;
      background: #000;
    }
    .slide.active { display: flex; }

    .ppt-image-slide img { width: 100%; height: 100%; object-fit: contain; }

    .ai-generated-slide { padding: 5% 8%; align-items: flex-start; justify-content: center; background: radial-gradient(circle at top right, #1e293b, #0f172a); overflow-y: auto; }
    .ai-generated-slide h1 { font-size: 2.5rem; color: #38bdf8; margin-bottom: 1.2rem; line-height: 1.2; }
    .ai-generated-slide p { font-size: 1.3rem; line-height: 1.6; color: #e2e8f0; margin-bottom: 1rem; }
    .ai-generated-slide ul { list-style: none; font-size: 1.3rem; line-height: 1.6; color: #e2e8f0; }
    .ai-generated-slide li { margin-bottom: 0.8rem; padding-left: 1.5rem; position: relative; }
    .ai-generated-slide li::before { content: "▹"; position: absolute; left: 0; color: #38bdf8; font-weight: bold; }

    #focus-overlay {
      position: absolute; inset: 0; background: rgba(0,0,0,0.7);
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      z-index: 200; cursor: pointer; transition: opacity 0.3s ease;
    }
    #focus-overlay.hidden { opacity: 0; pointer-events: none; }
    .focus-box { background: #0f172a; border: 2px solid #38bdf8; padding: 25px 35px; border-radius: 12px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.8); }
    .focus-box h2 { color: #38bdf8; margin-bottom: 8px; font-size: 1.5rem; }
    .focus-box p { color: #94a3b8; font-size: 0.95rem; }

    #nav-controls {
      position: fixed; bottom: 14px; left: 20px;
      display: flex; gap: 8px; z-index: 60;
    }
    .nav-btn {
      background: rgba(30, 41, 59, 0.9); color: #f8fafc; border: 1px solid #475569;
      padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; font-weight: 600;
    }
    .nav-btn:hover { background: rgba(51, 65, 85, 1); border-color: #38bdf8; }

    #hud {
      position: fixed; bottom: 14px; right: 22px;
      background: rgba(15, 23, 42, 0.85); padding: 6px 12px; border-radius: 6px;
      font-size: 0.85rem; color: #94a3b8; z-index: 50; border: 1px solid #334155;
    }

    #ai-bar {
      position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
      width: 720px; max-width: 90vw;
      background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(12px);
      border: 1px solid #38bdf8; border-radius: 12px;
      padding: 14px 18px; display: none; align-items: center; gap: 12px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8); z-index: 100;
    }
    #ai-bar.open { display: flex; }
    #ai-input { flex: 1; background: transparent; border: none; outline: none; color: #fff; font-size: 1.1rem; }
    
    .mic-btn {
      background: #ef4444; color: white; border: none; border-radius: 50%;
      width: 36px; height: 36px; cursor: pointer; display: flex; align-items: center; justify-content: center;
      font-size: 1rem; transition: transform 0.2s;
    }
    .mic-btn.listening { background: #22c55e; animation: pulse 1.5s infinite; }
    @keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.1); } 100% { transform: scale(1); } }

    #ai-status { font-size: 0.85rem; color: #38bdf8; white-space: nowrap; max-width: 300px; overflow: hidden; text-overflow: ellipsis; }
  </style>
</head>
<body tabindex="0" id="player-body">
  <div id="focus-overlay" onclick="activatePlayer()">
    <div class="focus-box">
      <h2>✨ Click Here to Start Presentation</h2>
      <p>Click once to enable keyboard navigation, voice AI, and oral speech responses.</p>
    </div>
  </div>

  <div id="deck">__SLIDES_CONTENT__</div>

  <div id="nav-controls">
    <button class="nav-btn" onclick="prevSlide()">◀ Prev</button>
    <button class="nav-btn" onclick="nextSlide()">Next ▶</button>
  </div>

  <div id="hud">Slide <span id="slide-num">1</span> / <span id="slide-total">__SLIDE_TOTAL__</span> &nbsp;|&nbsp; Press <strong>/</strong> for AI</div>

  <div id="ai-bar">
    <span>✨</span>
    <input type="text" id="ai-input" placeholder="Ask anything or request a slide (voice enabled)..." />
    <button id="mic-btn" class="mic-btn" onclick="toggleSpeechRecognition()" title="Voice Input">🎤</button>
    <span id="ai-status"></span>
  </div>

  <script>
    const API_KEYS = __API_KEYS_JSON__;
    let keyIndex = 0;
    let currentSlide = 0;

    const aiBar = document.getElementById("ai-bar");
    const aiInput = document.getElementById("ai-input");
    const aiStatus = document.getElementById("ai-status");
    const micBtn = document.getElementById("mic-btn");
    const playerBody = document.getElementById("player-body");
    const focusOverlay = document.getElementById("focus-overlay");

    function activatePlayer() {
      focusOverlay.classList.add("hidden");
      playerBody.focus();
    }

    function updateSlides() {
      const slides = document.querySelectorAll(".slide");
      slides.forEach((s, i) => s.classList.toggle("active", i === currentSlide));
      document.getElementById("slide-num").textContent = currentSlide + 1;
      document.getElementById("slide-total").textContent = slides.length;
    }

    function nextSlide() {
      const total = document.querySelectorAll(".slide").length;
      if (currentSlide < total - 1) { currentSlide++; updateSlides(); }
    }

    function prevSlide() {
      if (currentSlide > 0) { currentSlide--; updateSlides(); }
    }

    function speakText(text) {
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        window.speechSynthesis.speak(utterance);
      }
    }

    let recognition = null;
    let isListening = false;

    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = true;

      recognition.onstart = () => {
        isListening = true;
        micBtn.classList.add("listening");
        aiStatus.textContent = "Listening...";
      };

      recognition.onresult = (event) => {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        aiInput.value = transcript;
      };

      recognition.onerror = () => {
        stopListening();
        aiStatus.textContent = "Mic error";
      };

      recognition.onend = () => {
        stopListening();
        if (aiInput.value.trim() !== "") {
          triggerAI(aiInput.value.trim());
        }
      };
    }

    function toggleSpeechRecognition() {
      if (!recognition) {
        alert("Speech recognition is not supported in this browser. Try Google Chrome.");
        return;
      }
      if (isListening) {
        recognition.stop();
      } else {
        aiInput.value = "";
        recognition.start();
      }
    }

    function stopListening() {
      isListening = false;
      micBtn.classList.remove("listening");
      aiStatus.textContent = "";
    }

    window.addEventListener("keydown", (e) => {
      if (e.key === "/" && !aiBar.classList.contains("open")) {
        e.preventDefault();
        aiBar.classList.add("open");
        aiInput.focus();
        if (recognition) recognition.start();
        return;
      }
      if (e.key === "Escape" && aiBar.classList.contains("open")) {
        if (isListening && recognition) recognition.stop();
        aiBar.classList.remove("open");
        aiInput.blur();
        playerBody.focus();
        return;
      }
      if (document.activeElement === aiInput) return;

      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
        e.preventDefault();
        nextSlide();
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        prevSlide();
      }
    });

    aiInput.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter") return;
      const prompt = aiInput.value.trim();
      if (!prompt) return;
      if (isListening && recognition) recognition.stop();
      triggerAI(prompt);
    });

    async function triggerAI(prompt) {
      aiStatus.textContent = "Thinking...";
      aiInput.disabled = true;

      let currentKey = API_KEYS[keyIndex % API_KEYS.length];
      keyIndex++;

      try {
        const res = await fetch(
          'https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key=' + currentKey,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              contents: [{
                parts: [{
                  text: 'You are an intelligent presentation assistant. The user asked: "' + prompt + '". If the user wants a slide generated, return strictly valid JSON with keys "type": "slide", "title" (string), and "bullets" (array of 3-5 strings). If the user asked a general question or wants a conversational/oral answer, return strictly valid JSON with keys "type": "answer", "spoken_text" (a thorough conversational response to be read aloud), and "display_text" (a clear formatted summary for the screen). No markdown formatting blocks like ```json, just raw JSON.'
                }]
              }],
              generationConfig: { responseMimeType: "application/json" }
            })
          }
        );

        const data = await res.json();
        
        if (data.error) {
          throw new Error(data.error.message || "API Error");
        }

        const rawText = data.candidates[0].content.parts[0].text;
        const cleanedText = rawText.replace(/```json/g, '').replace(/```/g, '').trim();
        const aiResponse = JSON.parse(cleanedText);

        const newSection = document.createElement("section");
        newSection.className = "slide ai-generated-slide";

        if (aiResponse.type === "answer") {
          newSection.innerHTML = '<h1>AI Assistant</h1><p>' + aiResponse.display_text.replace(/\\n/g, '<br>') + '</p>';
          speakText(aiResponse.spoken_text);
        } else {
          const bulletsHtml = aiResponse.bullets.map(b => '<li>' + b + '</li>').join("");
          newSection.innerHTML = '<h1>' + aiResponse.title + '</h1><ul>' + bulletsHtml + '</ul>';
          speakText(aiResponse.title + ". " + aiResponse.bullets.join(". "));
        }

        const slides = document.querySelectorAll(".slide");
        slides[currentSlide].after(newSection);

        currentSlide++;
        updateSlides();
        aiInput.value = "";
        aiBar.classList.remove("open");
        playerBody.focus();
      } catch (err) {
        console.error("AI Error:", err);
        aiStatus.textContent = "Error: " + err.message;
      } finally {
        aiInput.disabled = false;
        setTimeout(() => { if (aiStatus.textContent.startsWith("Error")) aiStatus.textContent = ""; }, 4000);
      }
    }
  </script>
</body>
</html>
"""

  return html_template.replace("__SLIDES_CONTENT__", slides_html).replace("__SLIDE_TOTAL__", str(len(slides_b64))).replace("__API_KEYS_JSON__", keys_json)


if st.button("🚀 Launch AI Presentation Player", type="primary"):
  if not uploaded_file:
    st.error("Please upload a slides .zip file.")
  else:
    with st.spinner("Preparing presentation deck..."):
      try:
        slides_b64 = extract_slides_from_zip(uploaded_file.getvalue())
        if not slides_b64:
          st.error("No valid image files found inside the zip archive.")
        else:
          html_content = build_ai_player_html(slides_b64, GEMINI_API_KEYS)
          st.components.v1.html(html_content, height=750, scrolling=False)
          st.success("✅ Successfully loaded presentation with conversational oral AI responses!")
      except Exception as e:
        st.error(f"Error processing presentation: {e}")
