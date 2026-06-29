from pathlib import Path
import os

from huggingface_hub import InferenceClient

client = InferenceClient(
    provider="hf-inference",
    api_key=os.environ["HF_TOKEN"],
)

image = client.text_to_image(
    "A cinematic sunrise over the Himalayas, ultra realistic, golden hour",
    model="black-forest-labs/FLUX.1-schnell",
)

Path("tmp").mkdir(exist_ok=True)

image.save("tmp/test.png")

print("SUCCESS")
