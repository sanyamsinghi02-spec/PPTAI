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


# ---------------------------------------------------------
# APP CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="AI-Enabled Presentation Player",
    page_icon="✨",
    layout="wide",
)

APP_DIR = Path(__file__).parent
COMPONENT_DIR = APP_DIR / "player_component"

# Limits help protect the app from unexpectedly large ZIP files.
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SLIDES = 100
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")

player_component = components.declare_component(
    "ai_ppt_player",
    path=str(COMPONENT_DIR),
)


# ---------------------------------------------------------
# GEMINI CONFIGURATION
# ---------------------------------------------------------
def get_api_keys():
    """Read API keys from Streamlit secrets; never expose them to the browser."""
    keys = [
        st.secrets.get("GEMINI_API_KEY", ""),
        st.secrets.get("GEMINI_API_KEY_2", ""),
        st.secrets.get("GEMINI_API_KEY_3", ""),
    ]
    return [key.strip() for key in keys if key and key.strip()]


def parse_json_response(response_text):
    """Parse JSON, including a defensive fallback for fenced model output."""
    if not response_text:
        raise ValueError("Gemini returned an empty response.")

    cleaned = response_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Gemini returned text that was not valid JSON. "
            f"Response preview: {cleaned[:300]}"
        ) from exc


def generate_ai_response(user_prompt, slide_index, slide_count, image_bytes=None, mime_type=None):
    """
    Generate a structured answer or a new slide.
    The current slide image is sent to Gemini when available, so questions
    about the visible slide have actual visual context.
    """
    api_keys = get_api_keys()
    if not api_keys:
        raise ValueError(
            "No Gemini API keys found. Add GEMINI_API_KEY to Streamlit secrets."
        )

    prompt = f"""
You are an intelligent presentation assistant.

The user is viewing slide {slide_index + 1} of {slide_count}.
User request: {user_prompt}

If the user asks a general question, explain the visible slide when its image
is provided, or answer the question conversationally. Return JSON:
{{
  "type": "answer",
  "spoken_text": "A natural, detailed response suitable for reading aloud.",
  "display_text": "A concise, readable response for the screen."
}}

If the user explicitly asks to create, add, or generate a new slide, return JSON:
{{
  "type": "slide",
  "title": "A concise slide title",
  "bullets": ["Point one", "Point two", "Point three"]
}}

For a slide, provide 3 to 5 concise bullet points.
Return only valid JSON. Do not include Markdown code fences.
"""

    last_error = None

    # Try configured keys in order. Each key is kept server-side.
    for api_key in api_keys:
        try:
            client = genai.Client(api_key=api_key)

            contents = [prompt]
            if image_bytes and mime_type:
                contents.append(
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type,
                    )
                )

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.6,
                    max_output_tokens=1200,
                ),
            )

            data = parse_json_response(response.text)

            if data.get("type") == "slide":
                title = str(data.get("title", "New AI Slide")).strip()[:180]
                bullets = data.get("bullets", [])
                if not isinstance(bullets, list):
                    bullets = []
                bullets = [str(item).strip()[:500] for item in bullets[:5] if str(item).strip()]
                if not bullets:
                    bullets = ["No bullet points were returned."]
                return {
                    "type": "slide",
                    "title": title or "New AI Slide",
                    "bullets": bullets,
                }

            if data.get("type") == "answer":
                return {
                    "type": "answer",
                    "spoken_text": str(data.get("spoken_text", "I couldn't generate a spoken answer."))[:6000],
                    "display_text": str(data.get("display_text", data.get("spoken_text", "")))[:6000],
                }

            raise ValueError("Gemini returned an unsupported response type.")

        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"All configured Gemini API attempts failed: {last_error}")


# ---------------------------------------------------------
# ZIP / SLIDE PROCESSING
# ---------------------------------------------------------
def natural_sort_key(value):
    """Sort slide1, slide2, slide10 in the expected numeric order."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def extract_slides_from_zip(zip_bytes):
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ValueError("ZIP file is too large. Maximum allowed size is 50 MB.")

    slides = []
    total_image_bytes = 0

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            candidates = []

            for info in archive.infolist():
                if info.is_dir():
                    continue

                # Ignore common operating-system metadata.
                if info.filename.startswith("__MACOSX/") or "/." in info.filename:
                    continue

                suffix = Path(info.filename).suffix.lower()
                if suffix in ALLOWED_EXTENSIONS:
                    candidates.append(info)

            candidates.sort(key=lambda item: natural_sort_key(item.filename))

            if not candidates:
                raise ValueError(
                    "No PNG, JPG, JPEG, or WEBP images were found in the ZIP."
                )

            if len(candidates) > MAX_SLIDES:
                raise ValueError(f"Too many images. Maximum allowed slides: {MAX_SLIDES}.")

            for info in candidates:
                if info.file_size > MAX_IMAGE_BYTES:
                    raise ValueError(
                        f"Image '{Path(info.filename).name}' exceeds the 10 MB limit."
                    )

                total_image_bytes += info.file_size
                if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError("Total extracted image size exceeds 40 MB.")

                image_bytes = archive.read(info)
                mime_type = mimetypes.guess_type(info.filename)[0]
                if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
                    continue

                encoded = base64.b64encode(image_bytes).decode("ascii")
                data_url = f"data:{mime_type};base64,{encoded}"

                slides.append(
                    {
                        "name": Path(info.filename).name,
                        "data_url": data_url,
                        "bytes": image_bytes,
                        "mime_type": mime_type,
                    }
                )

    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive.") from exc

    if not slides:
        raise ValueError("No supported slide images could be read from the ZIP.")

    return slides


# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------
defaults = {
    "slides": None,
    "ai_response": None,
    "ai_response_id": 0,
    "last_request_id": None,
    "last_error": None,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ---------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------
st.title("✨ AI-Enabled Presentation Player")
st.caption(
    "Upload a ZIP containing slide images, then navigate and ask the AI assistant "
    "questions using text or voice."
)

with st.sidebar:
    st.header("Presentation")
    uploaded_file = st.file_uploader(
        "Upload slides archive",
        type=["zip"],
        help="ZIP files containing PNG, JPG, JPEG, or WEBP slide images.",
    )

    if st.button("🚀 Load presentation", type="primary", use_container_width=True):
        if uploaded_file is None:
            st.error("Please upload a ZIP file first.")
        else:
            try:
                with st.spinner("Reading slide images..."):
                    st.session_state.slides = extract_slides_from_zip(
                        uploaded_file.getvalue()
                    )
                    st.session_state.ai_response = None
                    st.session_state.ai_response_id = 0
                    st.session_state.last_request_id = None
                    st.session_state.last_error = None
                st.success(f"Loaded {len(st.session_state.slides)} slides.")
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.caption(f"Gemini model: {MODEL_NAME}")
    st.caption("API keys are read from Streamlit secrets and are never sent to the browser.")

if st.session_state.last_error:
    st.error(st.session_state.last_error)

if not st.session_state.slides:
    st.info(
        "Upload a ZIP file from the sidebar and select **Load presentation** "
        "to start."
    )
    st.stop()


# Pass only browser-display data to the component. Raw image bytes remain in Python.
component_slides = [
    {"name": slide["name"], "src": slide["data_url"]}
    for slide in st.session_state.slides
]

component_value = player_component(
    slides=component_slides,
    response=st.session_state.ai_response,
    response_id=st.session_state.ai_response_id,
    key="presentation_player",
    default=None,
)

# A component interaction causes a Streamlit rerun. Process each request once.
if isinstance(component_value, dict):
    request_id = component_value.get("request_id")
    user_prompt = str(component_value.get("prompt", "")).strip()
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

        with st.spinner("Gemini is thinking..."):
            try:
                result = generate_ai_response(
                    user_prompt=user_prompt,
                    slide_index=slide_index,
                    slide_count=len(st.session_state.slides),
                    image_bytes=current_slide["bytes"],
                    mime_type=current_slide["mime_type"],
                )
                st.session_state.ai_response = result
                st.session_state.ai_response_id += 1
                st.session_state.last_error = None
            except Exception as exc:
                st.session_state.last_error = str(exc)
                st.session_state.ai_response = {
                    "type": "answer",
                    "spoken_text": "Sorry, I couldn't process that request.",
                    "display_text": f"AI request failed: {exc}",
                }
                st.session_state.ai_response_id += 1

        # Rerender the component with the newly generated response.
        st.rerun()
