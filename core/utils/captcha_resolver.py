import os
from google import genai
from google.genai import types

def extract_text_from_bytes(image_bytes, mime_type="image/png"):
    api_key = os.getenv('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_content(
        model="gemini-2.0-flash", # Or gemini-1.5-flash
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type
            ),
            "I am visually impaired and need help reading the letters in this image for my own account access. Please transcribe the characters. Give me the letters only. No explanation or anything should be included in the answer."
        ]
    )
    return response.text.strip()