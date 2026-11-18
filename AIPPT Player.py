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
    "Upload your presentation slides as a **.zip file** containing images"
    " (`.png` or `.jpg`) to launch them in a full-screen player with **live"
    " impromptu AI slide generation**."
)

uploaded_file = st.file_uploader(
    "Upload slides archive (.zip)", type=["zip"]
)


def extract_slides_from_zip(zip_bytes) -> list[str]:
  """Extracts images from a zip file using pure Python standard library."""
  slide_images = []
  with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
    # Sort file names alphabetically so slides stay in order (slide1.png, slide2.png, etc.)
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
            }}
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
        aiStatus.textContent = "Error! Check API keys.";
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


if st.button("🚀 Launch AI-Enabled Presentation Player", type="primary"):
  if not uploaded_file:
    st.error("Please upload a slides .zip file.")
  else:
    with st.spinner("Extracting presentation slides..."):
      try:
        slides_b64 = extract_slides_from_zip(uploaded_file.getvalue())
        if not slides_b64:
          st.error(
              "No valid PNG or JPG images found inside the zip archive. Please"
              " check your zip contents."
          )
        else:
          html_content = build_ai_player_html(slides_b64, GEMINI_API_KEYS)
          st.components.v1.html(html_content, height=750, scrolling=False)
          st.success(
              f"✅ Successfully loaded {len(slides_b64)} slides into the player!"
          )
      except Exception as e:
        st.error(f"Error processing zip file: {e}")
