
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

MODEL_NAME = st.secrets.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)


# =========================================================
# SESSION STATE INITIALIZATION
# =========================================================

DEFAULTS = {
    "slides": [],
    "loaded": False,
    "conversation": [],
    "current_slide_index": 0,
    "generated_slides": [],
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
    slide_bytes,
    mime_type
):

    api_keys = get_api_keys()

    if not api_keys:
        raise ValueError(
            "No Gemini API key found in Streamlit Secrets."
        )

    history = st.session_state.conversation[-12:]

    conversation_text = ""

    for item in history:

        role = (
            "User"
            if item["role"] == "user"
            else "Assistant"
        )

        conversation_text += (
            f"\n{role}: {item['text']}\n"
        )

    prompt = f"""
You are a friendly, intelligent and conversational
AI presentation tutor.

The user is currently viewing slide {slide_index + 1}
of {slide_count}.

Use the attached slide image to understand the slide.

CONVERSATION SO FAR:
{conversation_text}

LATEST USER MESSAGE:
{user_prompt}

IMPORTANT INSTRUCTIONS:

1. Answer questions naturally and clearly.
2. Explain difficult concepts in simple language.
3. Give practical examples wherever useful.
4. Remember the conversation context.
5. Focus on the currently displayed slide when relevant.

If the user asks a question or wants a conversational
response, return:

{{
  "type": "answer",
  "spoken_text": "A natural conversational answer.",
  "display_text": "A readable answer for the screen."
}}

If the user explicitly asks to create, add or generate
a new slide, return:

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
                http_options=types.HttpOptions(
                    timeout=30000
                )
            )

            contents = [
                types.Part.from_text(text=prompt),

                types.Part.from_bytes(
                    data=slide_bytes,
                    mime_type=mime_type
                ),
            ]

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.5,
                    max_output_tokens=1200,
                ),
            )

            data = parse_json_response(response.text)

            if data.get("type") not in ["answer", "slide"]:
                raise ValueError(
                    "Gemini returned an unsupported response type."
                )

            return data

        except Exception as exc:

            last_error = exc

    raise RuntimeError(
        f"Gemini request failed. Last error: {last_error}"
    )


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
        raise ValueError(
            "ZIP file exceeds the 50 MB limit."
        )

    slides = []
    total_size = 0

    try:

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:

            candidates = []

            for info in archive.infolist():

                if (
                    info.is_dir()
                    or info.filename.startswith("__MACOSX/")
                    or "/." in info.filename
                ):
                    continue

                if (
                    Path(info.filename).suffix.lower()
                    in ALLOWED_EXTENSIONS
                ):
                    candidates.append(info)

            candidates.sort(
                key=lambda item: natural_sort_key(
                    item.filename
                )
            )

            if not candidates:
                raise ValueError(
                    "No PNG, JPG, JPEG or WEBP images found."
                )

            if len(candidates) > MAX_SLIDES:
                raise ValueError(
                    f"Maximum allowed slides: {MAX_SLIDES}."
                )

            for info in candidates:

                if info.file_size > MAX_IMAGE_BYTES:
                    raise ValueError(
                        f"{Path(info.filename).name} "
                        "exceeds the 10 MB limit."
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
                    "src": (
                        f"data:{mime_type};base64,"
                        + base64.b64encode(
                            image_bytes
                        ).decode("ascii")
                    ),
                })

    except zipfile.BadZipFile as exc:

        raise ValueError(
            "The uploaded file is not a valid ZIP."
        ) from exc

    if not slides:
        raise ValueError(
            "No supported slide images could be read."
        )

    return slides


# =========================================================
# APP HEADER
# =========================================================

st.title("✨ AI Presentation Player")

st.caption(
    "Present, navigate and have a conversation "
    "with your AI presentation tutor."
)


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.header("📂 Presentation")

    uploaded_file = st.file_uploader(
        "Upload slide ZIP",
        type=["zip"],
        help=(
            "Upload a ZIP containing PNG, JPG, JPEG "
            "or WEBP slide images."
        ),
    )

    if st.button(
        "🚀 Load presentation",
        type="primary",
        use_container_width=True
    ):

        if uploaded_file is None:

            st.error("Please upload a ZIP file.")

        else:

            try:

                with st.spinner("Loading your slides..."):

                    new_slides = extract_slides(
                        uploaded_file.getvalue()
                    )

                    st.session_state.slides = new_slides
                    st.session_state.loaded = True
                    st.session_state.current_slide_index = 0
                    st.session_state.conversation = []
                    st.session_state.generated_slides = []
                    st.session_state.last_error = None

                st.success(
                    f"{len(new_slides)} slides loaded successfully!"
                )

                st.rerun()

            except Exception as exc:

                st.error(str(exc))

    st.divider()

    st.caption(f"Gemini model: {MODEL_NAME}")

    if st.button(
        "🗑️ Clear conversation",
        use_container_width=True
    ):

        st.session_state.conversation = []
        st.session_state.generated_slides = []
        st.session_state.last_error = None

        st.rerun()


# =========================================================
# CHECK PRESENTATION
# =========================================================

if (
    not st.session_state.loaded
    or not st.session_state.slides
):

    st.info(
        "Upload a ZIP of slide images in the sidebar "
        "and select Load presentation."
    )

    st.stop()


# =========================================================
# PRESENTATION PLAYER
# =========================================================

slides = st.session_state.slides
total_slides = len(slides)

st.session_state.current_slide_index = max(
    0,
    min(
        st.session_state.current_slide_index,
        total_slides - 1
    )
)

left, right = st.columns([2.2, 1])


# =========================================================
# LEFT SIDE: SLIDE VIEWER
# =========================================================

with left:

    st.subheader("📽️ Presentation")

    current_index = st.session_state.current_slide_index

    current_slide = slides[current_index]

    st.image(
        current_slide["bytes"],
        use_container_width=True
    )

    st.caption(
        f"Slide {current_index + 1} of {total_slides}"
        f" | {current_slide['name']}"
    )

    col1, col2, col3 = st.columns([1, 2, 1])

    with col1:

        if st.button(
            "← Previous",
            use_container_width=True,
            disabled=(current_index == 0)
        ):

            st.session_state.current_slide_index -= 1
            st.rerun()

    with col2:

        st.progress(
            (current_index + 1) / total_slides
        )

    with col3:

        if st.button(
            "Next →",
            use_container_width=True,
            disabled=(current_index >= total_slides - 1)
        ):

            st.session_state.current_slide_index += 1
            st.rerun()

    st.caption(
        "Use Previous and Next to navigate your presentation."
    )


# =========================================================
# RIGHT SIDE: AI TUTOR
# =========================================================

with right:

    st.subheader("🤖 AI Presentation Tutor")

    st.caption(
        "Ask questions about the currently displayed slide."
    )

    # Display conversation history

    for message in st.session_state.conversation:

        with st.chat_message(message["role"]):

            st.markdown(message["text"])

    # User input

    user_prompt = st.chat_input(
        "Ask anything about this slide..."
    )

    if user_prompt:

        current_index = st.session_state.current_slide_index

        current_slide = slides[current_index]

        try:

            with st.spinner(
                "🤔 Gemini is thinking..."
            ):

                result = generate_ai_response(
                    user_prompt=user_prompt,
                    slide_index=current_index,
                    slide_count=total_slides,
                    slide_bytes=current_slide["bytes"],
                    mime_type=current_slide["mime_type"],
                )

            # Prepare answer

            answer = result.get(
                "display_text",
                result.get(
                    "spoken_text",
                    "No answer returned."
                )
            )

            # Save conversation

            st.session_state.conversation.append({
                "role": "user",
                "text": user_prompt
            })

            st.session_state.conversation.append({
                "role": "assistant",
                "text": answer
            })

            # Save generated slide

            if result.get("type") == "slide":

                st.session_state.generated_slides.append(
                    result
                )

            st.session_state.last_error = None

            st.rerun()

        except Exception as exc:

            st.session_state.conversation.append({
                "role": "user",
                "text": user_prompt
            })

            st.session_state.last_error = str(exc)

            st.error(
                f"Gemini could not respond: {exc}"
            )


# =========================================================
# GENERATED SLIDES
# =========================================================

if st.session_state.generated_slides:

    st.divider()

    st.subheader("✨ AI Generated Slides")

    for index, generated in enumerate(
        st.session_state.generated_slides,
        start=1
    ):

        with st.expander(
            f"Generated Slide {index}: "
            f"{generated.get('title', 'New Slide')}",
            expanded=True
        ):

            st.markdown(
                f"## {generated.get('title', 'New Slide')}"
            )

            for bullet in generated.get("bullets", []):

                st.markdown(f"- {bullet}")

            if generated.get("spoken_text"):

                st.caption(
                    generated["spoken_text"]
                )
