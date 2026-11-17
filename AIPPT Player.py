import base64
import json
import os
import tempfile
import webbrowser
import pythoncom
import streamlit as st
import win32com.client

# ==========================================
# HARDCODE YOUR GEMINI API KEY(S) HERE
# ==========================================
# Read secrets securely from Streamlit Cloud
GEMINI_API_KEYS = st.secrets["GEMINI_API_KEYS"]

# ==========================================

st.set_page_config(
    page_title="AI-Enabled PPT Player", page_icon="✨", layout="centered"
)

st.title("✨ AI-Enabled PowerPoint Player")
st.markdown(
    "Upload any `.pptx` presentation to launch it in a full-screen player with"
    " **live impromptu AI slide generation**."
)

# Only the PowerPoint file uploader is needed now
uploaded_file = st.file_uploader(
    "Upload your PowerPoint file (.pptx)", type=["pptx"]
)
manual_path = st.text_input(
    "Or paste local file path (Optional)",
    placeholder=r"C:\Users\Name\Documents\deck.pptx",
)


def convert_ppt_to_images(pptx_path: str) -> list[str]:
  """Exports each slide of a .pptx file as a base64 PNG image using PowerPoint."""
  pythoncom.CoInitialize()
  abs_path = os.path.abspath(pptx_path)

  ppt = win32com.client.Dispatch("PowerPoint.Application")
  presentation = ppt.Presentations.Open(abs_path, WithWindow=False)

  slide_images = []
  with tempfile.TemporaryDirectory() as tmpdir:
    for i, slide in enumerate(presentation.Slides, start=1):
      img_path = os.path.join(tmpdir, f"slide_{i}.png")
      slide.Export(img_path, "PNG", 1920, 1080)
      with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
        slide_images.append(f"data:image/png;base64,{b64}")

  presentation.Close()
  return slide_images


def build_ai_player_html(slides_b64: list[str], keys_string: str) -> str:
  # Process keys into a JavaScript array (supports single or multiple comma-separated keys)
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
    body {{ background: #000; color: #f8fafc; overflow: hidden; height: 100vh; display: flex; flex-direction: column; }}

    #deck {{ flex: 1; position: relative; width: 100%; height: 100%; }}
    .slide {{
      position: absolute; inset: 0;
      display: none; flex-direction: column; justify-content: center; align-items: center;
      background: #000;
      animation: fadeIn 0.25s ease;
    }}
    .slide.active {{ display: flex; }}
    @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}

    .ppt-image-slide img {{ width: 100%; height: 100%; object-fit: contain; }}

    .ai-generated-slide {{ padding: 6% 10%; align-items: flex-start; justify-content: center; background: radial-gradient(circle at top right, #1e293b, #0f172a); }}
    .ai-generated-slide h1 {{ font-size: 3.2rem; color: #38bdf8; margin-bottom: 1.5rem; line-height: 1.2; }}
    .ai-generated-slide ul {{ list-style: none; font-size: 1.7rem; line-height: 1.7; color: #e2e8f0; }}
    .ai-generated-slide li {{ margin-bottom: 1rem; padding-left: 1.8rem; position: relative; }}
    .ai-generated-slide li::before {{ content: "▹"; position: absolute; left: 0; color: #38bdf8; font-weight: bold; }}

    #hud {{
      position: fixed; bottom: 14px; right: 22px;
      background: rgba(15, 23, 42, 0.8); padding: 4px 10px; border-radius: 6px;
      font-size: 0.85rem; color: #94a3b8; pointer-events: none; z-index: 50;
    }}

    #ai-bar {{
      position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%);
      width: 680px; max-width: 90vw;
      background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(12px);
      border: 1px solid #38bdf8; border-radius: 12px;
      padding: 14px 18px; display: none; align-items: center; gap: 12px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8); z-index: 100;
    }}
    #ai-bar.open {{ display: flex; }}
    #ai-input {{ flex: 1; background: transparent; border: none; outline: none; color: #fff; font-size: 1.1rem; }}
    #ai-status {{ font-size: 0.85rem; color: #38bdf8; white-space: nowrap; }}
  </style>
</head>
<body>
  <div id="deck">{slides_html}</div>
  <div id="hud">Slide <span id="slide-num">1</span> / <span id="slide-total">{len(slides_b64)}</span> &nbsp;|&nbsp; Press <strong>/</strong> for AI &nbsp;|&nbsp; <strong>F11</strong> Fullscreen</div>

  <div id="ai-bar">
    <span>✨</span>
    <input type="text" id="ai-input" placeholder="Type impromptu slide command & hit Enter..." />
    <span id="ai-status"></span>
  </div>

  <script>
    const API_KEYS = {keys_js_array};
    let keyIndex = 0;
    let currentSlide = 0;

    const aiBar = document.getElementById("ai-bar");
    const aiInput = document.getElementById("ai-input");
    const aiStatus = document.getElementById("ai-status");

    function updateSlides() {{
      const slides = document.querySelectorAll(".slide");
      slides.forEach((s, i) => s.classList.toggle("active", i === currentSlide));
      document.getElementById("slide-num").textContent = currentSlide + 1;
      document.getElementById("slide-total").textContent = slides.length;
    }}

    document.addEventListener("keydown", (e) => {{
      if (e.key === "/" && !aiBar.classList.contains("open")) {{
        e.preventDefault();
        aiBar.classList.add("open");
        aiInput.focus();
        return;
      }}
      if (e.key === "Escape" && aiBar.classList.contains("open")) {{
        aiBar.classList.remove("open");
        aiInput.blur();
        return;
      }}
      if (document.activeElement === aiInput) return;

      const total = document.querySelectorAll(".slide").length;
      if (e.key === "ArrowRight" || e.key === " ") {{
        if (currentSlide < total - 1) {{ currentSlide++; updateSlides(); }}
      }} else if (e.key === "ArrowLeft") {{
        if (currentSlide > 0) {{ currentSlide--; updateSlides(); }}
      }}
    }});

    aiInput.addEventListener("keydown", async (e) => {{
      if (e.key !== "Enter") return;
      const prompt = aiInput.value.trim();
      if (!prompt) return;

      aiStatus.textContent = "Generating...";
      aiInput.disabled = true;

      // Rotate through keys automatically if multiple are provided
      let currentKey = API_KEYS[keyIndex % API_KEYS.length];
      keyIndex++;

      try {{
        const res = await fetch(
          `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${{currentKey}}`,
          {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              contents: [{{
                parts: [{{
                  text: `Create a presentation slide for: "${{prompt}}". Return strictly valid JSON with keys "title" (string) and "bullets" (array of 3 to 5 concise strings, max 12 words each). No markdown.`
                }}]
              }}],
              generationConfig: {{ responseMimeType: "application/json" }}
            }})
          }}
        );

        const data = await res.json();
        const slideObj = JSON.parse(data.candidates[0].content.parts[0].text);

        const newSection = document.createElement("section");
        newSection.className = "slide ai-generated-slide";
        const bulletsHtml = slideObj.bullets.map(b => `<li>${{b}}</li>`).join("");
        newSection.innerHTML = `<h1>${{slideObj.title}}</h1><ul>${{bulletsHtml}}</ul>`;

        const slides = document.querySelectorAll(".slide");
        slides[currentSlide].after(newSection);

        currentSlide++;
        updateSlides();
        aiInput.value = "";
        aiBar.classList.remove("open");
      }} catch (err) {{
        aiStatus.textContent = "Error! Check API key.";
        console.error(err);
      }} finally {{
        aiInput.disabled = false;
        setTimeout(() => {{ aiStatus.textContent = ""; }}, 2000);
      }}
    }});
  </script>
</body>
</html>
"""


if st.button("🚀 Launch AI-Enabled Presentation", type="primary"):
  if not uploaded_file and not manual_path:
    st.error("Please upload a .pptx file or enter a file path.")
  else:
    with st.spinner("Converting slides and building presentation player..."):
      try:
        if uploaded_file is not None:
          temp_pptx = os.path.join(tempfile.gettempdir(), uploaded_file.name)
          with open(temp_pptx, "wb") as f:
            f.write(uploaded_file.getbuffer())
          target_path = temp_pptx
        else:
          target_path = manual_path.strip().strip('"')

        if not os.path.exists(target_path):
          st.error(f"File not found: {target_path}")
        else:
          slides_b64 = convert_ppt_to_images(target_path)
          html_content = build_ai_player_html(slides_b64, GEMINI_API_KEYS)

          output_path = os.path.abspath("ai_enabled_deck.html")
          with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

          st.success(
              f"✅ Converted {len(slides_b64)} slides! Opening player tab..."
          )
          webbrowser.open("file://" + output_path)
      except Exception as e:
        st.error(f"Error processing presentation: {e}")