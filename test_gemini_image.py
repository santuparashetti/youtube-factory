from pathlib import Path
import os

from google import genai
from google.genai import types

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
)

response = client.models.generate_content(
    model="gemini-3.1-flash-image",
    contents="""
A cinematic sunrise over the Himalayas.
Ultra realistic.
Golden hour.
8K.
""",
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
    ),
)

Path("tmp").mkdir(exist_ok=True)

for candidate in response.candidates:
    if not candidate.content:
        continue

    for part in candidate.content.parts:
        if getattr(part, "inline_data", None):
            with open("tmp/test.png", "wb") as f:
                f.write(part.inline_data.data)

print("DONE")