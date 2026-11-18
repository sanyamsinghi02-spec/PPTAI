
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

APP_DIR = Path(__file__).parent
COMPONENT_DIR = APP_DIR / "player_component"

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
MAX_SLIDES = 100

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

MODEL_NAME = st.secrets.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

if not (COMPONENT_DIR / "index.html").is_file():
    st.error(
        "Player frontend not found. Make sure "
        "player_component/index.html exists in your GitHub repository."
    )
    st.stop()

player_component = components.declare_component(
    "ai_ppt_player",
    path=str(COMPONENT_DIR.resolve()),
)


# =========================================================
# SESSION STATE
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
# GEMINI API
# =========================================================

def get_api_keys():
    keys = [
        st.secrets.get("GEMINI_API_KEY", ""),
        st.secrets.get("GEMINI_API_KEY_2", ""),
        st.secrets.get("GEMINI_API_KEY_3", ""),
    ]

    return [
        key.strip()
        for key in keys
        if key and key.strip()
    ]


def parse_json_response(response_text):
    if not response_text:
        raise ValueError("Gemini returned an empty response.")

    cleaned = response_text.strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*```$", "", cleaned)

    return json.loads(cleaned)


def generate_ai_response(
    user_prompt,
    slide_index,
    slide_count,
    slide_bytes,
    mime_type,
):
    api_keys = get_api_keys()

    if not api_keys:
        raise ValueError(
            "No Gemini API key found. Add GEMINI_API_KEY "
            "under Streamlit Secrets."
        )

    # Keep recent conversation turns for context.
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

You can:
1. Explain the current slide in simple language.
2. Give examples and practical applications.
3. Answer follow-up questions using conversation context.
4. Discuss concepts related to the current slide.
5. Create an additional presentation slide when explicitly requested.

If the user asks a question or wants a conversational response,
return this JSON:

{{
  "type": "answer",
  "spoken_text": "A natural, friendly answer suitable for speaking aloud.",
  "display_text": "A readable answer for the screen."
}}

If the user explicitly asks to create, add, or generate a slide,
return:

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

For generated slides:
- Include 3 to 5 concise bullet points.
- Make the content useful and professional.
- Do not generate a slide unless requested.

Return only valid JSON.
"""

    last_error = None

    for api_key in api_keys:
        try:
            client = genai.Client(api_key=api_key)

            contents = [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(
                    data=slide_bytes,
                    mime_type=mime_type,
                ),
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

            if data.get("type") == "slide":
                bullets = data.get("bullets", [])

                if not isinstance(bullets, list):
                    bullets = []

                bullets = [
                    str(item).strip()[:500]
                    for item in bullets[:5]
                    if str(item).strip()
                ]

                return {
                    "type": "slide",
                    "title": str(
                        data.get("title", "AI Generated Slide")
                    )[:180],
                    "bullets": bullets or ["No content returned."],
                    "spoken_text": str(
                        data.get("spoken_text", "Here is your new slide.")
                    )[:3000],
                }

            if data.get("type") == "answer":
                spoken = str(
                    data.get("spoken_text", "I couldn't generate an answer.")
                )[:6000]

                return {
                    "type": "answer",
                    "spoken_text": spoken,
                    "display_text": str(
                        data.get("display_text", spoken)
                    )[:6000],
                }

            raise ValueError("Unsupported response type from Gemini.")

        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Gemini request failed: {last_error}")


# =========================================================
# ZIP PROCESSING
# =========================================================

def natural_sort_key(value):
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def extract_slides(zip_bytes):
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError("ZIP file exceeds the 50 MB limit.")

    slides = []
    total_size = 0

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            candidates = []

            for info in archive.infolist():
                if info.is_dir():
                    continue

                if (
                    info.filename.startswith("__MACOSX/")
                    or "/." in info.filename
                ):
                    continue

                suffix = Path(info.filename).suffix.lower()

                if suffix in ALLOWED_EXTENSIONS:
                    candidates.append(info)

            candidates.sort(
                key=lambda item: natural_sort_key(item.filename)
            )

            if not candidates:
                raise ValueError(
                    "No PNG, JPG, JPEG or WEBP images found in the ZIP."
                )

            if len(candidates) > MAX_SLIDES:
                raise ValueError(
                    f"Maximum allowed slides: {MAX_SLIDES}."
                )

            for info in candidates:
                if info.file_size > MAX_IMAGE_BYTES:
                    raise ValueError(
                        f"{Path(info.filename).name} exceeds 10 MB."
                    )

                total_size += info.file_size

                if total_size > MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError(
                        "Total image size exceeds 40 MB."
                    )

                image_bytes = archive.read(info)
                mime_type = mimetypes.guess_type(info.filename)[0]

                if mime_type not in {
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                }:
                    continue

                slides.append({
                    "name": Path(info.filename).name,
                    "bytes": image_bytes,
                    "mime_type": mime_type,
                    "src": (
                        f"data:{mime_type};base64,"
                        + base64.b64encode(image_bytes).decode("ascii")
                    ),
                })

    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP.") from exc

    if not slides:
        raise ValueError("No supported slide images could be read.")

    return slides


# =========================================================
# APP HEADER AND SIDEBAR
# =========================================================

st.title("✨ AI Presentation Player")

st.caption(
    "Present, navigate, and have a voice conversation with your AI tutor."
)

with st.sidebar:
    st.header("Presentation")

    uploaded_file = st.file_uploader(
        "Upload slide ZIP",
        type=["zip"],
        help="Upload a ZIP containing PNG, JPG, JPEG or WEBP slide images.",
    )

    if st.button(
        "🚀 Load presentation",
        type="primary",
        use_container_width=True,
    ):
        if uploaded_file is None:
            st.error("Please upload a ZIP file.")
        else:
            try:
                with st.spinner("Loading your slides..."):
                    st.session_state.slides = extract_slides(
                        uploaded_file.getvalue()
                    )
                    st.session_state.loaded = True
                    st.session_state.ai_response = None
                    st.session_state.ai_response_id = 0
                    st.session_state.last_request_id = None
                    st.session_state.conversation = []
                    st.session_state.last_error = None

                st.success(
                    f"{len(st.session_state.slides)} slides loaded."
                )
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.caption(f"Gemini model: {MODEL_NAME}")
    st.caption("Voice features require browser microphone permission.")

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.conversation = []
        st.session_state.ai_response = None
        st.rerun()


if st.session_state.last_error:
    st.error(st.session_state.last_error)

if not st.session_state.loaded or not st.session_state.slides:
    st.info(
        "Upload a ZIP of slide images and select Load presentation."
    )
    st.stop()


# =========================================================
# COMPONENT DATA
# =========================================================

component_slides = [
    {
        "name": slide["name"],
        "src": slide["src"],
    }
    for slide in st.session_state.slides
]

component_value = player_component(
    slides=component_slides,
    response=st.session_state.ai_response,
    response_id=st.session_state.ai_response_id,
    key="ai_presentation_player",
    default=None,
)


# =========================================================
# PROCESS AI REQUESTS
# =========================================================

if isinstance(component_value, dict):
    request_id = component_value.get("request_id")
    user_prompt = str(
        component_value.get("prompt", "")
    ).strip()

    slide_index = component_value.get("slide_index", 0)

    if (
        request_id
        and request_id != st.session_state.last_request_id
        and user_prompt
    ):
        st.session_state.last_request_id = request_id

        try:
            slide_index = int(slide_index)
        except (TypeError, ValueError):
            slide_index = 0

        slide_index = max(
            0,
            min(slide_index, len(st.session_state.slides) - 1),
        )

        current_slide = st.session_state.slides[slide_index]

        # Add user message to conversation history.
        st.session_state.conversation.append({
            "role": "user",
            "text": user_prompt,
        })

        try:
            with st.spinner("AI is thinking..."):
                result = generate_ai_response(
                    user_prompt=user_prompt,
                    slide_index=slide_index,
                    slide_count=len(st.session_state.slides),
                    slide_bytes=current_slide["bytes"],
                    mime_type=current_slide["mime_type"],
                )

            st.session_state.conversation.append({
                "role": "assistant",
                "text": result.get(
                    "spoken_text",
                    result.get("display_text", ""),
                ),
            })

            # Keep conversation history manageable.
            st.session_state.conversation = (
                st.session_state.conversation[-20:]
            )

            st.session_state.ai_response = result
            st.session_state.ai_response_id += 1
            st.session_state.last_error = None

        except Exception as exc:
            st.session_state.last_error = str(exc)

            st.session_state.ai_response = {
                "type": "answer",
                "spoken_text": "Sorry, I couldn't process that request.",
                "display_text": f"AI error: {exc}",
            }

            st.session_state.ai_response_id += 1

        st.rerun()

