import google.generativeai as genai
from config import GOOGLE_API_KEY

genai.configure(api_key=GOOGLE_API_KEY)


def summarize_text_gemini(text):
    model = genai.GenerativeModel("gemini-pro")
    try:
        response = model.generate_content(f"Summarize this news:\n\n{text}")
        return response.text.strip()
    except Exception as e:
        return f"Summary failed: {e}"
