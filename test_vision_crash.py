"""Minimal test: reproduce vision QA crash with actual parameters.

Run with: uv run python test_vision_crash.py
"""
import sys
import os
sys.path.insert(0, "src")

IMAGE = "workspace/jobs/when-suffering-knocks-don-t-open-the-door-within/images/scene-001.png"
PROMPT = "An empty courtyard at dusk, rendered in high angle from above, reveals a single weathered wooden bench against a crumbling stone wall. Cinematically lit in golden-hour tones, shallow depth of field."

def main():
    from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider
    from pathlib import Path

    print("Loading model...", flush=True)
    provider = LlamaCppVisionProvider(model_name="qwen2_5_vl_3b")

    # Force model load by calling review once
    img = Path(IMAGE)
    if not img.exists():
        print(f"ERROR: {IMAGE} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Image: {img}, size={img.stat().st_size} bytes", flush=True)

    # Check actual model params after load
    model = provider._load_model()
    if model is None:
        print("Model failed to load!", file=sys.stderr)
        sys.exit(1)

    print(f"Model loaded. n_ctx={model.n_ctx()}, n_batch={model.n_batch}, n_ubatch={model.context_params.n_ubatch}", flush=True)

    for attempt in range(1, 4):
        print(f"\n=== Attempt {attempt} ===", flush=True)
        result = provider.review(image_path=img, visual_prompt=PROMPT)
        print(f"Result: status={result.status}, score={result.score}", flush=True)

    print("\nAll attempts succeeded — no crash.", flush=True)

if __name__ == "__main__":
    main()
