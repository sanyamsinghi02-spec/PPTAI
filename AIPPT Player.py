import base64
import io
import json
import mimetypes
import re
import zipfile
from pathlib import Path

import streamlit as st
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

MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-1.5-flash")

# =========================================================
# SESSION STATE INITIALIZATION
# =========================================================

DEFAULTS = {
    "slides": [],
    "loaded": False,
    "slide_index": 0,
    "generated_slides": [],
    "conversation": [],
    "last_error": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# =========================================================
# GEMINI API HANDLER
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

def generate_ai_response(user_prompt, slide_index, slide_count, slide_name):
    api_keys = get_api_keys()
    if not api_keys:
        raise ValueError("No Gemini API key found under Streamlit Secrets.")

    history = st.session_state.conversation[-8:]
    conversation_text = ""
    for item in history:
        role = "User" if item["role"] == "user" else "Assistant"
        conversation_text += f"\n{role}: {item['text']}\n"

    prompt = f"""
You are a friendly, intelligent, conversational AI presentation tutor.
The user is viewing slide {slide_index + 1} of {slide_count} (Filename: {slide_name}).

CONVERSATION SO FAR:
{conversation_text}

LATEST USER MESSAGE:
{user_prompt}

If the user asks a question or wants a conversational response, return this JSON:
{{
  "type": "answer",
  "spoken_text": "A natural, friendly answer.",
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
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=15_000)
            )
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.6,
                    max_output_tokens=1000,
                ),
            )
            data = parse_json_response(response.text)
            if data.get("type") in ["slide", "answer"]:
                return data
            raise ValueError("Unsupported response type from Gemini.")
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Gemini request failed: {last_error}")

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
# SIDEBAR CONTROLS
# =========================================================

st.title("✨ AI Presentation Player")

with st.sidebar:
    st.header("Presentation Setup")
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
                with st.spinner("Loading slides..."):
                    st.session_state.slides = extract_slides(uploaded_file.getvalue())
                    st.session_state.loaded = True
                    st.session_state.slide_index = 0
                    st.session_state.generated_slides = []
                    st.session_state.conversation = []
                    st.session_state.last_error = None
                st.success(f"{len(st.session_state.slides)} slides loaded.")
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    if st.button("Clear chat history", use_container_width=True):
        st.session_state.conversation = []
        st.rerun()

if st.session_state.last_error:
    st.error(st.session_state.last_error)

if not st.session_state.loaded or not st.session_state.slides:
    st.info("Upload a ZIP file in the sidebar and click **Load presentation** to start.")
    st.stop()

# =========================================================
# MAIN PRESENTATION & AI LAYOUT
# =========================================================

total_slides = len(st.session_state.slides) + len(st.session_state.generated_slides)

col_pres, col_chat = st.columns([1.5, 1], gap="medium")

with col_pres:
    # Navigation controls
    nav_cols = st.columns([1, 2, 1])
    with nav_cols[0]:
        if st.button("⬅️ Previous", use_container_width=True) and st.session_state.slide_index > 0:
            st.session_state.slide_index -= 1
            st.rerun()
    with nav_cols[1]:
        st.markdown(f"<p style='text-align: center; font-weight: bold;'>Slide {st.session_state.slide_index + 1} of {total_slides}</p>", unsafe_allow_html=True)
    with nav_cols[2]:
        if st.button("Next ➡️", use_container_width=True) and st.session_state.slide_index < total_slides - 1:
            st.session_state.slide_index += 1
            st.rerun()

    # Display Slide Stage
    if st.session_state.slide_index < len(st.session_state.slides):
        current_slide = st.session_state.slides[st.session_state.slide_index]
        st.image(current_slide["src"], use_container_width=True, caption=current_slide["name"])
    else:
        gen_idx = st.session_state.slide_index - len(st.session_state.slides)
        gen_slide = st.session_state.generated_slides[gen_idx]
        
        st.markdown(
            f"""
            <div style="padding: 30px; background: linear-gradient(135deg, #172554, #312e81); border-radius: 12px; color: white; min-height: 350px;">
                <h2 style="text-align: center; margin-bottom: 20px;">{gen_slide.get('title', 'AI Generated Slide')}</h2>
                <ul>
                    {"".join([f"<li style='font-size: 18px; margin: 10px 0;'>{b}</li>" for b in gen_slide.get('bullets', [])])}
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

with col_chat:
    st.markdown("### 🤖 AI Tutor Chat")
    
    # Chat History Container
    chat_container = st.container(height=450)
    with chat_container:
        if not st.session_state.conversation:
            st.info("Ask a question about this slide or request a new slide!")
        for message in st.session_state.conversation:
            with st.chat_message(message["role"]):
                st.markdown(message["text"])

    # User Input Prompt Box
    user_prompt = st.chat_input("Ask anything about this slide or ask to generate a new slide...")

    if user_prompt:
        st.session_state.conversation.append({"role": "user", "text": user_prompt})
        
        # Determine current slide info
        if st.session_state.slide_index < len(st.session_state.slides):
            slide_name = st.session_state.slides[st.session_state.slide_index]["name"]
        else:
            slide_name = "AI Generated Slide"

        with st.spinner("AI is thinking..."):
            try:
                result = generate_ai_response(
                    user_prompt=user_prompt,
                    slide_index=st.session_state.slide_index,
                    slide_count=total_slides,
                    slide_name=slide_name,
                )
                
                ai_text = result.get("display_text", result.get("spoken_text", "Done."))
                
                if result.get("type") == "slide":
                    st.session_state.generated_slides.append(result)
                    st.session_state.slide_index = len(st.session_state.slides) + len(st.session_state.generated_slides) - 1
                    ai_text = f"✨ Created new slide: **{result.get('title')}**"

                st.session_state.conversation.append({"role": "assistant", "text": ai_text})
                st.rerun()

            except Exception as exc:
                st.error(f"Error: {exc}")
