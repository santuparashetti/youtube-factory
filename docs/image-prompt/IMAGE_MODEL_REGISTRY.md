# IMAGE MODEL REGISTRY

The following image models are available for video scene generation.

This pipeline generates **video scene images only**.

It MUST NOT generate thumbnail images, marketing assets, title cards, posters, or promotional artwork.

---

## Model 1

Model:
black-forest-labs/FLUX.1-schnell

Tier:
Low Cost

Primary Purpose:
Default image generation.

Characteristics:

- Lowest inference cost
- Fastest generation
- Good photorealism
- Good overall quality
- Moderate prompt adherence
- Moderate composition accuracy

Recommended For:

- Standard scenes
- Environmental scenes
- Backgrounds
- Most storyboard images
- First-pass generation

Generation Strategy:

- Generate TWO candidates.
- Use different random seeds.
- Evaluate both using Vision QA.
- Keep only the highest scoring image.

---

## Model 2

Model:
Qwen/Qwen-Image

Tier:
Medium Cost

Primary Purpose:
Quality escalation.

Characteristics:

- Excellent prompt adherence
- Excellent composition
- Better anatomy
- Better realism
- Better lighting
- Better object consistency

Recommended For:

- Vision QA failures
- Complex compositions
- Difficult lighting
- Emotionally important scenes
- Symbolic scenes
- High-detail scenes

Generation Strategy:

- Generate ONE image.
- Preserve scene intent.
- Improve realism and prompt adherence.
- Run Vision QA.

---

## Model 3

Model:
black-forest-labs/FLUX.1-dev

Tier:
Premium

Primary Purpose:
Final quality escalation.

Characteristics:

- Highest visual quality
- Excellent realism
- Excellent prompt adherence
- Excellent lighting
- Excellent cinematic detail

Recommended For:

- Scenes that repeatedly fail Vision QA
- Highly complex scenes
- Critical story moments
- Final fallback when other models cannot satisfy quality requirements

Generation Strategy:

- Generate ONE image.
- Optimize for maximum quality.
- Ignore generation speed.
- Run Vision QA.

---

# MODEL SELECTION POLICY

The objective is NOT to use the best model.

The objective is to produce the required visual quality using the lowest possible inference cost.

Always begin with:

black-forest-labs/FLUX.1-schnell

↓

Generate TWO candidates

↓

Vision QA

↓

If Quality Score ≥ Target

Accept.

↓

If Quality Score < Target

Refine only the failing prompt sections.

Retry ONCE using:

black-forest-labs/FLUX.1-schnell

↓

Vision QA

↓

If still below target

Escalate to:

Qwen/Qwen-Image

↓

Vision QA

↓

If still below target

Escalate to:

black-forest-labs/FLUX.1-dev

↓

Vision QA

↓

Accept the highest-scoring image.

---

# PROMPT ADAPTATION

Before generation, adapt the prompt to the selected model.

For black-forest-labs/FLUX.1-schnell

- Composition first
- Short, explicit instructions
- Positive constraints
- Minimal repetition
- Avoid conflicting instructions

For Qwen/Qwen-Image

- Rich environmental detail
- Cinematic lighting
- Strong atmosphere
- Enhanced realism
- Detailed storytelling

For black-forest-labs/FLUX.1-dev

- Maximum realism
- Maximum texture detail
- Rich environmental complexity
- Fine cinematic lighting
- Highest prompt fidelity

Never reuse the exact same prompt across models.

Optimize prompts specifically for the selected model while preserving:

- Story continuity
- Scene intent
- Camera angle
- Composition
- Subject identity
- Emotional tone

---

# COST OPTIMIZATION POLICY

Always optimize for **Quality per Dollar**.

Priority order:

1. Better prompt construction
2. Better candidate selection
3. Better prompt refinement
4. Model escalation

Premium models are the last resort.

Never escalate unless lower-cost models cannot satisfy the required quality.

Never generate thumbnails or promotional artwork in this pipeline.