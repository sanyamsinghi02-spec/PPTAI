import os
import io
import json
import re
import zipfile
from pathlib import Path
import gradio as gr
from openai import OpenAI
from google import genai
from google.genai import types

# Configuration
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024
MAX_SLIDES = 100
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# API Key Retrieval
def get_gemini_api_keys():
    keys = [
        os.getenv("GEMINI_API_KEY", ""),
        os.getenv("GEMINI_API_KEY_2", ""),
        os.getenv("GEMINI_API_KEY_3", ""),
    ]
    return [key.strip() for key in keys if key and key.strip()]

def parse_json_response(response_text):
    if not response_text:
        raise ValueError("AI returned an empty response.")
    cleaned = response_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)

def generate_ai_response(user_prompt, slide_index, slide_count, slide_bytes, mime_type, history):
    # Format history for prompt context
    conversation_text = ""
    for user_msg, assistant_msg in history[-4:]:
        if user_msg:
            conversation_text += f"\nUser: {user_msg}\n"
        if assistant_msg:
            conversation_text += f"Assistant: {assistant_msg}\n"

    prompt = f"""
You are a friendly, intelligent, conversational AI presentation tutor.
The user is viewing slide {slide_index + 1} of {slide_count}.

CONVERSATION SO FAR:
{conversation_text}

LATEST USER MESSAGE:
{user_prompt}

If the user asks a question or wants a conversational response, return ONLY a JSON object in this exact format:
{{
  "type": "answer",
  "spoken_text": "A natural, friendly answer suitable for speaking aloud.",
  "display_text": "A readable answer for the screen."
}}

If the user explicitly asks to create, add, or generate a slide, return ONLY a JSON object in this exact format:
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
"""

    last_error = None

    # 1. Try Groq First (Lightning Fast)
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key, timeout=15.0)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.6,
                max_tokens=1000,
            )
            data = json.loads(response.choices[0].message.content)
            if data.get("type") in ["slide", "answer"]:
                return data
        except Exception as exc:
            last_error = exc

    # 2. Fallback to Gemini Multi-Key Pool
    gemini_keys = get_gemini_api_keys()
    if gemini_keys and slide_bytes:
        for api_key in gemini_keys:
            try:
                client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20_000))
                contents = [
                    types.Part.from_text(text=prompt),
                    types.Part.from_bytes(data=slide_bytes, mime_type=mime_type),
                ]
                response = client.models.generate_content(
                    model=GEMINI_MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.6,
                        max_output_tokens=1000,
                    ),
                )
                data = parse_json_response(response.text)
                if data.get("type") in ["slide", "answer"]:
                    return data
            except Exception as exc:
                last_error = exc

    raise RuntimeError(f"All AI API requests failed or timed out. Last error: {last_error}")

# Slide Extraction Helper
def natural_sort_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]

def process_zip_upload(file_obj):
    if not file_obj:
        return [], 0, "Please upload a ZIP file."
    
    with open(file_obj.name, "rb") as f:
        zip_bytes = f.read()

    if len(zip_bytes) > MAX_ZIP_BYTES:
        return [], 0, "ZIP file exceeds 50 MB limit."

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
            
            for info in candidates:
                image_bytes = archive.read(info)
                mime_type = mimetypes.guess_type(info.filename)[0] or "image/png"
                slides.append({
                    "name": Path(info.filename).name,
                    "bytes": image_bytes,
                    "mime_type": mime_type,
                    "image": io.BytesIO(image_bytes) # Gradio compatible image stream
                })
    except Exception as e:
        return [], 0, f"Error reading ZIP: {str(e)}"

    if not slides:
        return [], 0, "No valid images found in ZIP."

    return slides, 0, f"Successfully loaded {len(slides)} slides!"

# Gradio UI Layout
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# ✨ AI Presentation Player (Gradio Edition)")
    
    slides_state = gr.State([])
    generated_slides_state = gr.State([])
    index_state = gr.State(0)

    with gr.Row():
        with gr.Column(scale=2):
            file_input = gr.File(label="Upload Slide Deck (.zip)", file_types=[".zip"])
            load_btn = gr.Button("🚀 Load Presentation", variant="primary")
            load_status = gr.Markdown()

            slide_display = gr.Image(label="Current Slide", interactive=False)
            
            with gr.Row():
                prev_btn = gr.Button("⬅️ Previous")
                slide_counter = gr.Markdown("Slide 0 of 0")
                next_btn = gr.Button("Next ➡️")

        with gr.Column(scale=1):
            chatbot = gr.Chatbot(label="🤖 AI Teammate", height=450)
            chat_input = gr.Textbox(placeholder="Ask a question or request a new slide...", label="Your Message")
            send_btn = gr.Button("Send ➤", variant="primary")

    # Logic for loading presentation
    def load_presentation(file_obj):
        slides, idx, msg = process_zip_upload(file_obj)
        if not slides:
            return slides, [], 0, msg, None, "Slide 0 of 0"
        first_slide_img = slides[0]["bytes"]
        counter_text = f"Slide 1 of {len(slides)}"
        return slides, [], 0, msg, first_slide_img, counter_text

    load_btn.click(
        load_presentation,
        inputs=[file_input],
        outputs=[slides_state, generated_slides_state, index_state, load_status, slide_display, slide_counter]
    )

    # Navigation logic
    def change_slide(direction, index, slides, gen_slides):
        total = len(slides) + len(gen_slides)
        if total == 0:
            return index, None, "Slide 0 of 0"
        
        new_index = max(0, min(index + direction, total - 1))
        
        if new_index < len(slides):
            img = slides[new_index]["bytes"]
        else:
            # Handle generated slide preview formatting if needed
            img = None 
            
        counter_text = f"Slide {new_index + 1} of {total}"
        return new_index, img, counter_text

    prev_btn.click(lambda idx, s, g: change_slide(-1, idx, s, g), [index_state, slides_state, generated_slides_state], [index_state, slide_display, slide_counter])
    next_btn.click(lambda idx, s, g: change_slide(1, idx, s, g), [index_state, slides_state, generated_slides_state], [index_state, slide_display, slide_counter])

    # Chat interaction logic
    def handle_chat(user_message, history, slides, gen_slides, index):
        if not user_message.strip():
            return history, slides, gen_slides, index

        history = history + [[user_message, None]]
        total_slides = len(slides) + len(gen_slides)
        
        # Get active slide context bytes
        slide_bytes, mime_type = b"", "image/png"
        if index < len(slides):
            slide_bytes = slides[index]["bytes"]
            mime_type = slides[index]["mime_type"]

        try:
            result = generate_ai_response(user_message, index, total_slides, slide_bytes, mime_type, history)
            
            if result.get("type") == "slide":
                gen_slides.append(result)
                new_idx = len(slides) + len(gen_slides) - 1
                ai_text = f"✨ Created new slide: **{result.get('title')}**"
                history[-1][1] = ai_text
                return history, slides, gen_slides, new_idx
            else:
                ai_text = result.get("display_text", result.get("spoken_text", "Done."))
                history[-1][1] = ai_text
                return history, slides, gen_slides, index
        except Exception as e:
            history[-1][1] = f"Error: {str(e)}"
            return history, slides, gen_slides, index

    send_btn.click(
        handle_chat,
        inputs=[chat_input, chatbot, slides_state, generated_slides_state, index_state],
        outputs=[chatbot, slides_state, generated_slides_state, index_state]
    )

if __name__ == "__main__":
    demo.launch()
