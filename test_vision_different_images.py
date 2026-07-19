"""Test vision review with different images (not same image repeated)."""
import sys, os
sys.path.insert(0, "src")

IMAGES = [
    "workspace/jobs/when-suffering-knocks-don-t-open-the-door-within/images/scene-001.png",
    "workspace/jobs/when-suffering-knocks-don-t-open-the-door-within/images/scene-002.png",
    "workspace/jobs/when-suffering-knocks-don-t-open-the-door-within/images/scene-003.png",
]
PROMPTS = [
    "A contemplative figure sitting in a dimly lit room, facing away from viewer.",
    "Symbolic imagery of storm clouds parting to reveal a beam of golden light.",
    "Ancient stone steps leading upward through misty forest.",
]

def main():
    from video_core.providers.vision.llama_cpp_provider import LlamaCppVisionProvider
    from pathlib import Path

    print("Loading model...", flush=True)
    provider = LlamaCppVisionProvider(model_name="qwen2_5_vl_3b")
    model = provider._load_model()
    if model is None:
        print("Model failed to load!", file=sys.stderr)
        sys.exit(1)
    print(f"Model loaded. n_ctx={model.n_ctx()}, n_batch={model.n_batch}", flush=True)

    for i, (img_path, prompt) in enumerate(zip(IMAGES, PROMPTS)):
        img = Path(img_path)
        if not img.exists():
            print(f"SKIP: {img_path} not found", flush=True)
            continue
        
        from PIL import Image
        w, h = Image.open(img).size
        print(f"\n=== Image {i+1}: {img.name} ({w}x{h}) ===", flush=True)

        # Simulate the full review cycle: 3 calls per image (like review_engine does)
        for call_num in range(1, 4):
            print(f"  Call {call_num}...", flush=True)
            result = provider.review(image_path=img, visual_prompt=prompt)
            print(f"  Result: status={result.status}, score={result.score}", flush=True)

    print("\nAll done — no crash!", flush=True)

if __name__ == "__main__":
    main()
