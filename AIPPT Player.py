
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
    page_title="AI-Enabled Presentation Player",
    page_icon="✨",
    layout="wide",
)

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
MAX_SLIDES = 100

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

MODEL_NAME = st.secrets.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)


# =========================================================
# SESSION STATE
# =========================================================

defaults = {
    "slides": [],
    "current_slide": 0,
    "ai_response": None,
    "generated_slides": [],
    "presentation_loaded": False,
}

for key, value in defaults.items():
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
        flags=re.IGNORECASE
    )

    cleaned = re.sub(r"\s*```$", "", cleaned)

    return json.loads(cleaned)


def generate_ai_response(
    user_prompt,
    slide_index,
    slide_count,
    image_bytes=None,
    mime_type=None
):

    api_keys = get_api_keys()

    if not api_keys:
        raise ValueError(
            "Gemini API keys are missing. "
            "Please configure GEMINI_API_KEY in Streamlit secrets."
        )

    prompt = f"""
You are an intelligent AI presentation assistant.

The user is currently viewing slide {slide_index + 1}
out of {slide_count} slides.

User request:
{user_prompt}

If the user asks a question, explain the current slide
using the supplied slide image.

Return this JSON format:

{{
    "type": "answer",
    "spoken_text": "Detailed natural answer",
    "display_text": "Readable answer for the screen"
}}

If the user explicitly asks to create, add, or generate
a new presentation slide, return:

{{
    "type": "slide",
    "title": "Slide title",
    "bullets": [
        "Point one",
        "Point two",
        "Point three"
    ]
}}

For generated slides:
- Provide 3 to 5 useful bullet points.
- Keep the content concise.
- Make the slide professional and informative.

Return ONLY valid JSON.
Do not use Markdown code fences.
"""

    last_error = None

    for api_key in api_keys:

        try:

            client = genai.Client(api_key=api_key)

            contents = [prompt]

            if image_bytes and mime_type:

                contents.append(
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type
                    )
                )

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
                    "bullets": bullets,
                }

            if data.get("type") == "answer":

                return {
                    "type": "answer",
                    "spoken_text": str(
                        data.get("spoken_text", "")
                    )[:6000],
                    "display_text": str(
                        data.get("display_text", "")
                    )[:6000],
                }

            raise ValueError(
                "Gemini returned an unsupported response."
            )

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"All Gemini API attempts failed: {last_error}"
    )


# =========================================================
# ZIP FILE PROCESSING
# =========================================================

def natural_sort_key(value):

    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def extract_slides_from_zip(zip_bytes):

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

                if info.filename.startswith("__MACOSX/"):
                    continue

                suffix = Path(info.filename).suffix.lower()

                if suffix in ALLOWED_EXTENSIONS:
                    candidates.append(info)

            candidates.sort(
                key=lambda item: natural_sort_key(item.filename)
            )

            if not candidates:
                raise ValueError(
                    "No PNG, JPG, JPEG or WEBP images found."
                )

            if len(candidates) > MAX_SLIDES:
                raise ValueError(
                    f"Maximum allowed slides: {MAX_SLIDES}"
                )

            for info in candidates:

                if info.file_size > MAX_IMAGE_BYTES:
                    raise ValueError(
                        f"{info.filename} exceeds the 10 MB image limit."
                    )

                total_size += info.file_size

                if total_size > MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError(
                        "Total image size exceeds 40 MB."
                    )

                image_bytes = archive.read(info)

                mime_type = mimetypes.guess_type(
                    info.filename
                )[0]

                if mime_type not in {
                    "image/png",
                    "image/jpeg",
                    "image/webp"
                }:
                    continue

                slides.append({
                    "name": Path(info.filename).name,
                    "bytes": image_bytes,
                    "mime_type": mime_type,
                })

    except zipfile.BadZipFile:
        raise ValueError("Invalid ZIP file.")

    if not slides:
        raise ValueError("No supported images found.")

    return slides


# =========================================================
# SIDEBAR
# =========================================================

st.title("✨ AI-Enabled Presentation Player")

st.caption(
    "An interactive presentation player powered by Gemini AI."
)

with st.sidebar:

    st.header("📂 Presentation")

    uploaded_file = st.file_uploader(
        "Upload your presentation ZIP",
        type=["zip"],
    )

    if st.button(
        "🚀 Load Presentation",
        type="primary",
        use_container_width=True
    ):

        if uploaded_file is None:

            st.error("Please upload a ZIP file.")

        else:

            try:

                with st.spinner("Loading slides..."):

                    slides = extract_slides_from_zip(
                        uploaded_file.getvalue()
                    )

                    st.session_state.slides = slides
                    st.session_state.current_slide = 0
                    st.session_state.ai_response = None
                    st.session_state.generated_slides = []
                    st.session_state.presentation_loaded = True

                st.success(
                    f"{len(slides)} slides loaded successfully!"
                )

            except Exception as exc:

                st.error(str(exc))

    st.divider()

    st.caption(f"AI Model: {MODEL_NAME}")

    st.caption(
        "Powered by Google Gemini"
    )


# =========================================================
# PRESENTATION PLAYER
# =========================================================

if not st.session_state.presentation_loaded:

    st.info(
        "Upload a ZIP file containing your slide images "
        "and click Load Presentation."
    )

    st.stop()


slides = st.session_state.slides

total_slides = len(slides)

current_index = st.session_state.current_slide

current_slide = slides[current_index]


# =========================================================
# SLIDE DISPLAY
# =========================================================

st.subheader(
    f"Slide {current_index + 1} of {total_slides}"
)

st.image(
    current_slide["bytes"],
    use_container_width=True
)


# =========================================================
# NAVIGATION
# =========================================================

col1, col2, col3 = st.columns([1, 2, 1])

with col1:

    if st.button(
        "⬅ Previous",
        use_container_width=True,
        disabled=current_index == 0
    ):

        st.session_state.current_slide -= 1
        st.session_state.ai_response = None
        st.rerun()


with col2:

    st.progress(
        (current_index + 1) / total_slides
    )


with col3:

    if st.button(
        "Next ➡",
        use_container_width=True,
        disabled=current_index == total_slides - 1
    ):

        st.session_state.current_slide += 1
        st.session_state.ai_response = None
        st.rerun()


# =========================================================
# AI ASSISTANT
# =========================================================

st.divider()

st.header("🤖 AI Presentation Assistant")

st.write(
    "Ask questions about the current slide, "
    "request explanations, or generate additional slides."
)

user_prompt = st.text_area(
    "Your question or instruction",
    placeholder=(
        "Example: Explain this slide in simple language.\n"
        "Example: Give me a practical example.\n"
        "Example: Create a new slide on this topic."
    ),
    height=110,
    key="user_prompt"
)


if st.button(
    "✨ Ask AI",
    type="primary",
    use_container_width=True
):

    if not user_prompt.strip():

        st.warning("Please enter a question or instruction.")

    else:

        try:

            with st.spinner("Gemini is thinking..."):

                result = generate_ai_response(
                    user_prompt=user_prompt,
                    slide_index=current_index,
                    slide_count=total_slides,
                    image_bytes=current_slide["bytes"],
                    mime_type=current_slide["mime_type"],
                )

                st.session_state.ai_response = result

                if result["type"] == "slide":

                    st.session_state.generated_slides.append(
                        result
                    )

        except Exception as exc:

            st.error(f"AI Error: {exc}")


# =========================================================
# AI RESPONSE DISPLAY
# =========================================================

if st.session_state.ai_response:

    result = st.session_state.ai_response

    st.divider()

    if result["type"] == "answer":

        st.subheader("💡 AI Explanation")

        st.markdown(
            result["display_text"]
        )

    elif result["type"] == "slide":

        st.subheader("🎨 AI Generated Slide")

        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, #172554, #312e81);
                padding: 35px;
                border-radius: 16px;
                color: white;
                min-height: 300px;
            ">
                <h1 style="color:white; text-align:center;">
                    {result["title"]}
                </h1>
            </div>
            """,
            unsafe_allow_html=True
        )

        for bullet in result["bullets"]:

            st.markdown(f"### • {bullet}")


# =========================================================
# GENERATED SLIDE HISTORY
# =========================================================

if st.session_state.generated_slides:

    st.divider()

    st.subheader("📚 AI Generated Slides")

    for number, slide in enumerate(
        st.session_state.generated_slides,
        start=1
    ):

        with st.expander(
            f"Generated Slide {number}: {slide['title']}"
        ):

            st.markdown(
                f"## {slide['title']}"
            )

            for bullet in slide["bullets"]:

                st.markdown(f"- {bullet}")


# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption(
    "AI-Enabled Presentation Player | Powered by Google Gemini"
)
