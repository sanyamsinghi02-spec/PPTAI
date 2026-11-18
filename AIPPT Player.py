import base64
import io
import json
import mimetypes
import re
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types

# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="AI Presentation Player",
    page_icon="✨",
    layout="wide",
)

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
MAX_SLIDES = 100

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-3.8-flash")

# =========================================================
# SESSION STATE INITIALIZATION
# =========================================================

DEFAULTS = {
    "slides": [],
    "loaded": False,
    "ai_response": None,
    "ai_response_id": 0,
    "last_request_id": None,
    "conversation": [],
    "last_error": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# =========================================================
# GEMINI API HANDLER (WITH TIMEOUT PROTECTION)
# =========================================================

def get_api_keys():
    keys = [
        st.secrets.get("GEMINI_API_KEY", ""),
        st.secrets.get("GEMINI_API_KEY_2", ""),
        st.secrets.get("GEMINI_API_KEY_3", ""),
    ]
    return [key.strip() for key in keys if key and key.strip()]

def parse_json_response(response_text):
    if not response_text:
        raise ValueError("Gemini returned an empty response.")
    cleaned = response_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)

def generate_ai_response(user_prompt, slide_index, slide_count, slide_bytes, mime_type):
    api_keys = get_api_keys()
    if not api_keys:
        raise ValueError("No Gemini API key found under Streamlit Secrets.")

    history = st.session_state.conversation[-12:]
    conversation_text = ""
    for item in history:
        role = "User" if item["role"] == "user" else "Assistant"
        conversation_text += f"\n{role}: {item['text']}\n"

    prompt = f"""
You are a friendly, intelligent, conversational AI presentation tutor.
The user is viewing slide {slide_index + 1} of {slide_count}.

CONVERSATION SO FAR:
{conversation_text}

LATEST USER MESSAGE:
{user_prompt}

If the user asks a question or wants a conversational response, return this JSON:
{{
  "type": "answer",
  "spoken_text": "A natural, friendly answer suitable for speaking aloud.",
  "display_text": "A readable answer for the screen."
}}

If the user explicitly asks to create, add, or generate a slide, return:
{{
  "type": "slide",
  "title": "A clear slide title",
  "bullets": [
    "First important point",
    "Second important point",
    "Third important point"
  ],
  "spoken_text": "Briefly introduce the new slide."
}}

Return only valid JSON.
"""

    last_error = None
    for api_key in api_keys:
        try:
            # Enforce a 25-second timeout to prevent indefinite hanging on free-tier bottlenecks
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=25_000)
            )
            contents = [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=slide_bytes, mime_type=mime_type),
            ]
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.6,
                    max_output_tokens=1500,
                ),
            )
            data = parse_json_response(response.text)
            if data.get("type") in ["slide", "answer"]:
                return data
            raise ValueError("Unsupported response type from Gemini.")
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Gemini request failed or timed out: {last_error}")

# =========================================================
# ZIP PROCESSING
# =========================================================

def natural_sort_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]

def extract_slides(zip_bytes):
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError("ZIP file exceeds the 50 MB limit.")
    slides = []
    total_size = 0
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            candidates = []
            for info in archive.infolist():
                if info.is_dir() or info.filename.startswith("__MACOSX/") or "/." in info.filename:
                    continue
                if Path(info.filename).suffix.lower() in ALLOWED_EXTENSIONS:
                    candidates.append(info)
            candidates.sort(key=lambda item: natural_sort_key(item.filename))
            if not candidates:
                raise ValueError("No PNG, JPG, JPEG or WEBP images found in the ZIP.")
            if len(candidates) > MAX_SLIDES:
                raise ValueError(f"Maximum allowed slides: {MAX_SLIDES}.")
            for info in candidates:
                if info.file_size > MAX_IMAGE_BYTES:
                    raise ValueError(f"{Path(info.filename).name} exceeds 10 MB.")
                total_size += info.file_size
                if total_size > MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError("Total image size exceeds 40 MB.")
                image_bytes = archive.read(info)
                mime_type = mimetypes.guess_type(info.filename)[0]
                if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
                    continue
                slides.append({
                    "name": Path(info.filename).name,
                    "bytes": image_bytes,
                    "mime_type": mime_type,
                    "src": f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii"),
                })
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP.") from exc
    if not slides:
        raise ValueError("No supported slide images could be read.")
    return slides

# =========================================================
# APP SIDEBAR & INTERFACE
# =========================================================

st.title("✨ AI Presentation Player")
st.caption("Present, navigate, and have a voice conversation with your AI tutor.")

with st.sidebar:
    st.header("Presentation")
    uploaded_file = st.file_uploader(
        "Upload slide ZIP",
        type=["zip"],
        help="Upload a ZIP containing PNG, JPG, JPEG or WEBP slide images.",
    )

    if st.button("🚀 Load presentation", type="primary", use_container_width=True):
        if uploaded_file is None:
            st.error("Please upload a ZIP file.")
        else:
            try:
                with st.spinner("Loading your slides..."):
                    st.session_state.slides = extract_slides(uploaded_file.getvalue())
                    st.session_state.loaded = True
                    st.session_state.ai_response = None
                    st.session_state.ai_response_id = 0
                    st.session_state.last_request_id = None
                    st.session_state.conversation = []
                    st.session_state.last_error = None
                st.success(f"{len(st.session_state.slides)} slides loaded.")
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.caption(f"Gemini model: {MODEL_NAME}")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.conversation = []
        st.session_state.ai_response = None
        st.rerun()

if st.session_state.last_error:
    st.error(st.session_state.last_error)

if not st.session_state.loaded or not st.session_state.slides:
    st.info("Upload a ZIP of slide images in the sidebar and select Load presentation.")
    st.stop()

# =========================================================
# STREAMLIT COMPONENT DATA & RENDERING
# =========================================================

component_slides = [{"name": s["name"], "src": s["src"]} for s in st.session_state.slides]
response_data = json.dumps(st.session_state.ai_response) if st.session_state.ai_response else "null"

html_code = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Presentation Player</title>
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; width: 100%; min-height: 100%; background: #080d19; color: #f8fafc; font-family: Arial, sans-serif; }}
body {{ padding: 12px; }}
#player {{ width: 100%; min-height: 650px; background: #0f172a; border: 1px solid #263449; border-radius: 16px; overflow: hidden; }}
.topbar {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 16px; background: #111c31; border-bottom: 1px solid #263449; flex-wrap: wrap; }}
.brand {{ font-size: 17px; font-weight: bold; }}
.status {{ color: #94a3b8; font-size: 12px; }}
.layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 320px; min-height: 590px; }}
.presentation {{ padding: 14px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }}
.slide-stage {{ width: 100%; aspect-ratio: 16 / 9; min-height: 250px; background: #020617; border: 1px solid #334155; border-radius: 10px; overflow: hidden; display: flex; align-items: center; justify-content: center; }}
.slide-stage img {{ width: 100%; height: 100%; object-fit: contain; }}
.generated-slide {{ width: 100%; height: 100%; padding: 6%; background: linear-gradient(135deg, #172554, #312e81); display: flex; flex-direction: column; justify-content: center; }}
.generated-slide h1 {{ text-align: center; font-size: clamp(22px, 3vw, 42px); margin: 0 0 24px; }}
.generated-slide li {{ font-size: clamp(14px, 1.6vw, 23px); margin: 12px 0; line-height: 1.4; }}
.controls {{ display: flex; align-items: center; justify-content: center; gap: 10px; flex-wrap: wrap; }}
button {{ cursor: pointer; border: 0; border-radius: 8px; padding: 10px 15px; background: #253653; color: white; font-size: 14px; font-weight: 600; }}
button:hover {{ background: #38547d; }}
button:disabled {{ opacity: 0.35; cursor: not-allowed; }}
.primary {{ background: #4f46e5; }}
.primary:hover {{ background: #6366f1; }}
.mic {{ background: #be123c; }}
.mic.listening {{ background: #dc2626; animation: pulse 1s infinite; }}
@keyframes pulse {{ 50% {{ opacity: 0.55; }} }}
.counter {{ color: #cbd5e1; font-size: 13px; min-width: 90px; text-align: center; }}
.progress {{ width: 100%; height: 5px; background: #273449; border-radius: 20px; overflow: hidden; }}
.progress-inner {{ height: 100%; width: 0%; background: #818cf8; transition: width 0.2s; }}
.keyboard-help {{ color: #94a3b8; font-size: 11px; text-align: center; }}
.assistant {{ display: flex; flex-direction: column; min-width: 0; background: #111c31; border-left: 1px solid #263449; min-height: 590px; }}
.assistant-header {{ padding: 16px; border-bottom: 1px solid #263449; }}
.assistant-header h3 {{ margin: 0 0 5px; }}
.assistant-header p {{ margin: 0; color: #94a3b8; font-size: 12px; }}
.messages {{ padding: 12px; flex: 1; overflow-y: auto; max-height: 440px; min-height: 220px; }}
.message {{ padding: 11px; border-radius: 10px; margin-bottom: 10px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }}
.user-message {{ background: #263a60; margin-left: 18px; }}
.ai-message {{ background: #1e293b; margin-right: 18px; }}
.message-label {{ color: #a5b4fc; font-size: 10px; font-weight: bold; margin-bottom: 5px; }}
.composer {{ padding: 12px; border-top: 1px solid #263449; }}
textarea {{ width: 100%; min-height: 75px; resize: vertical; padding: 10px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: white; font-size: 13px; outline: none; }}
textarea:focus {{ border-color: #818cf8; }}
.composer-buttons {{ display: flex; gap: 8px; margin-top: 8px; }}
.composer-buttons button {{ flex: 1; }}
.voice-note {{ color: #94a3b8; font-size: 10px; margin-top: 8px; }}
#notice {{ color: #fbbf24; font-size: 12px; min-height: 16px; margin-top: 5px; }}
@media (max-width: 850px) {{
    .layout {{ grid-template-columns: 1fr; }}
    .assistant {{ border-left: 0; border-top: 1px solid #263449; min-height: 430px; }}
}}
</style>
</head>
<body>
<div id="player">
    <div class="topbar">
        <div class="brand">✨ AI Presentation Player</div>
        <div class="status" id="status">Ready</div>
        <button id="fullscreenBtn">⛶ Fullscreen</button>
    </div>
    <div class="layout">
        <section class="presentation">
            <div class="slide-stage" id="slideStage"><div>Loading slides...</div></div>
            <div class="progress"><div class="progress-inner" id="progressInner"></div></div>
            <div class="controls">
                <button id="prevBtn">← Previous</button>
                <div class="counter" id="counter">0 / 0</div>
                <button id="nextBtn" class="primary">Next →</button>
            </div>
            <div class="keyboard-help">Keyboard: ← Previous | → or Space Next</div>
        </section>
        <aside class="assistant">
            <div class="assistant-header">
                <h3>🤖 AI Teammate</h3>
                <p>Talk naturally. Ask questions about your slides.</p>
            </div>
            <div class="messages" id="messages">
                <div class="message ai-message">
                    <div class="message-label">AI TUTOR</div> Hello! Ask me to explain a slide, give examples, or create a new slide.
                </div>
            </div>
            <div class="composer">
                <textarea id="prompt" placeholder="Ask anything about this slide..."></textarea>
                <div class="composer-buttons">
                    <button id="micBtn" class="mic">🎙 Speak</button>
                    <button id="sendBtn" class="primary">Send ➤</button>
                </div>
                <div class="voice-note">AI answers can be spoken aloud.</div>
                <div id="notice"></div>
            </div>
        </aside>
    </div>
</div>

<script>
const slides = {json.dumps(component_slides)};
let currentIndex = 0;
let generatedSlides = [];
let recognition = null;
let listening = false;

const stage = document.getElementById("slideStage");
const counter = document.getElementById("counter");
const status = document.getElementById("status");
const messages = document.getElementById("messages");
const promptBox = document.getElementById("prompt");
const notice = document.getElementById("notice");
const player = document.getElementById("player");

function sendToStreamlit(type, data) {{
    window.parent.postMessage({{
        isStreamlitMessage: true,
        type: type,
        ...data
    }}, "*");
}}

function setComponentValue(value) {{
    sendToStreamlit("streamlit:setComponentValue", {{ value: value }});
}}

function setFrameHeight(height) {{
    sendToStreamlit("streamlit:setFrameHeight", {{ height: height }});
}}

function allSlideCount() {{ return slides.length + generatedSlides.length; }}

function renderSlide() {{
    const total = allSlideCount();
    if (!total) return;
    currentIndex = Math.max(0, Math.min(currentIndex, total - 1));
    stage.innerHTML = "";

    if (currentIndex < slides.length) {{
        const slide = slides[currentIndex];
        const img = document.createElement("img");
        img.src = slide.src;
        img.alt = slide.name || "Slide";
        stage.appendChild(img);
    }} else {{
        const generated = generatedSlides[currentIndex - slides.length];
        const wrapper = document.createElement("div");
        wrapper.className = "generated-slide";
        const heading = document.createElement("h1");
        heading.textContent = generated.title || "AI Generated Slide";
        wrapper.appendChild(heading);
        const list = document.createElement("ul");
        (generated.bullets || []).forEach(b => {{
            const item = document.createElement("li");
            item.textContent = b;
            list.appendChild(item);
        }});
        wrapper.appendChild(list);
        stage.appendChild(wrapper);
    }}

    counter.textContent = (currentIndex + 1) + " / " + total;
    document.getElementById("prevBtn").disabled = (currentIndex === 0);
    document.getElementById("nextBtn").disabled = (currentIndex >= total - 1);
    document.getElementById("progressInner").style.width = (((currentIndex + 1) / total) * 100) + "%";
    status.textContent = "Viewing slide " + (currentIndex + 1);
    setFrameHeight(750);
}}

function nextSlide() {{ if (currentIndex < allSlideCount() - 1) {{ currentIndex++; renderSlide(); }} }}
function previousSlide() {{ if (currentIndex > 0) {{ currentIndex--; renderSlide(); }} }}

document.getElementById("nextBtn").addEventListener("click", nextSlide);
document.getElementById("prevBtn").addEventListener("click", previousSlide);

document.addEventListener("keydown", (e) => {{
    if (["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.key === "ArrowRight" || e.key === " ") {{ e.preventDefault(); nextSlide(); }}
    if (e.key === "ArrowLeft") {{ e.preventDefault(); previousSlide(); }}
}});

document.getElementById("fullscreenBtn").addEventListener("click", async () => {{
    try {{
        if (!document.fullscreenElement) await player.requestFullscreen();
        else await document.exitFullscreen();
    }} catch (err) {{}}
}});

function addMessage(role, text) {{
    const message = document.createElement("div");
    message.className = "message " + (role === "user" ? "user-message" : "ai-message");
    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent = role === "user" ? "YOU" : "AI TUTOR";
    const content = document.createElement("div");
    content.textContent = text;
    message.appendChild(label);
    message.appendChild(content);
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
}}

function speak(text) {{
    if ('speechSynthesis' in window) {{
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "en-IN";
        window.speechSynthesis.speak(utterance);
    }}
}}

function sendPrompt() {{
    const prompt = String(promptBox.value || "").trim();
    if (!prompt) return;

    addMessage("user", prompt);
    promptBox.value = "";
    notice.textContent = "AI is thinking...";
    status.textContent = "AI is thinking...";

    setComponentValue({{
        request_id: Date.now().toString(),
        prompt: prompt,
        slide_index: Math.min(currentIndex, slides.length - 1)
    }});
}}

document.getElementById("sendBtn").addEventListener("click", sendPrompt);
promptBox.addEventListener("keydown", (e) => {{
    if (e.key === "Enter" && !e.shiftKey) {{ e.preventDefault(); sendPrompt(); }}
}});

const initialResponse = {response_data};
if (initialResponse) {{
    notice.textContent = "";
    status.textContent = "Ready";
    if (initialResponse.type === "slide") {{
        generatedSlides.push(initialResponse);
        addMessage("ai", initialResponse.spoken_text || "I've created a new slide.");
        currentIndex = allSlideCount() - 1;
        speak(initialResponse.spoken_text || initialResponse.title);
    }} else {{
        const answer = initialResponse.display_text || initialResponse.spoken_text || "Done.";
        addMessage("ai", answer);
        speak(initialResponse.spoken_text || answer);
    }}
}}

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const micButton = document.getElementById("micBtn");
if (SpeechRecognition) {{
    recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.onstart = () => {{ listening = true; micButton.classList.add("listening"); micButton.textContent = "🔴 Listening..."; }};
    recognition.onresult = (e) => {{ promptBox.value = e.results[0][0].transcript; sendPrompt(); }};
    recognition.onend = () => {{ listening = false; micButton.classList.remove("listening"); micButton.textContent = "🎙 Speak"; }};
    micButton.addEventListener("click", () => {{ if (listening) recognition.stop(); else recognition.start(); }});
}} else {{
    micButton.disabled = true;
    micButton.textContent = "Voice N/A";
}}

sendToStreamlit("streamlit:componentReady", {{ apiVersion: 1 }});
renderSlide();
</script>
</body>
</html>
"""

component_value = components.html(
    html_code,
    height=750,
    scrolling=False,
)

# Process backend AI requests when component value updates
if isinstance(component_value, dict):
    request_id = component_value.get("request_id")
    user_prompt = str(component_value.get("prompt", "")).strip()
    slide_index = int(component_value.get("slide_index", 0))

    if request_id and request_id != st.session_state.last_request_id and user_prompt:
        st.session_state.last_request_id = request_id
        slides = st.session_state.slides
        slide_index = max(0, min(slide_index, len(slides) - 1))
        current_slide = slides[slide_index]

        st.session_state.conversation.append({"role": "user", "text": user_prompt})
        try:
            result = generate_ai_response(
                user_prompt=user_prompt,
                slide_index=slide_index,
                slide_count=len(slides),
                slide_bytes=current_slide["bytes"],
                mime_type=current_slide["mime_type"],
            )
            st.session_state.conversation.append({"role": "assistant", "text": result.get("spoken_text", "")})
            st.session_state.ai_response = result
            st.session_state.ai_response_id += 1
            st.session_state.last_error = None
            st.rerun()
        except Exception as exc:
            st.session_state.last_error = str(exc)
            st.session_state.ai_response = {
                "type": "answer",
                "spoken_text": "Sorry, the request timed out or failed. Please try again.",
                "display_text": f"Error: {exc}"
            }
            st.session_state.ai_response_id += 1
            st.rerun()
