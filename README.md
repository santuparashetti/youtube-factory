docs/
│
├── README.md                    # Documentation index
│
├── 00-project/
│   ├── vision.md
│   ├── roadmap.md
│   ├── architecture.md
│   ├── tech-stack.md
│   └── coding-standards.md
│
├── 01-setup/
│   ├── ubuntu-setup.md
│   ├── windows-setup.md
│   ├── macos-setup.md
│   ├── github-setup.md
│   └── troubleshooting.md
│
├── 02-sprints/
│   ├── sprint-01-foundation.md
│   ├── sprint-02-project-manager.md
│   ├── sprint-03-research-agent.md
│   └── ...
│
├── 03-architecture/
│   ├── workflow-engine.md
│   ├── project-model.md
│   ├── provider-system.md
│   ├── agent-system.md
│   └── cache-system.md
│
├── 04-api/
│   ├── cli.md
│   ├── project.md
│   ├── research.md
│   ├── image.md
│   └── video.md
│
├── 05-prompts/
│   ├── research.md
│   ├── script.md
│   ├── image.md
│   └── seo.md
│
└── decisions/
    ├── ADR-001-package-name.md
    ├── ADR-002-workspace-layout.md
    └── ADR-003-provider-architecture.md













    docs/
│
├── README.md                # Documentation index
│
├── manual/
│   ├── 01-foundation.md
│   ├── 02-research-agent.md
│   ├── 03-script-agent.md
│   ├── 04-scene-planner.md
│   ├── 05-image-generator.md
│   ├── 06-video-composer.md
│   └── ...
│
├── architecture/
│   ├── overview.md
│   ├── workflow.md
│   ├── providers.md
│   └── project-model.md
│
├── decisions/
│   ├── ADR-001-package-name.md
│   ├── ADR-002-workspace.md
│   └── ADR-003-provider-interface.md
│
└── prompts/
    ├── research.md
    ├── script.md
    └── image.md

## Text-to-Speech Providers

| Provider       | Command                  | Install                        |
|----------------|--------------------------|--------------------------------|
| edge           | `TTS_PROVIDER=edge`      | Included                       |
| kokoro         | `TTS_PROVIDER=kokoro`    | `uv pip install kokoro soundfile` |
| fish           | `TTS_PROVIDER=fish`      | `uv pip install requests`      |
| cartesia       | `TTS_PROVIDER=cartesia`  | `uv pip install cartesia`      |
| elevenlabs     | `TTS_PROVIDER=elevenlabs` | `uv pip install elevenlabs`   |

### Fish Audio

Fish Audio provides cloud TTS via the Fish Audio REST API. Select it with:

```
TTS_PROVIDER=fish
FISH_API_KEY=your-api-key
FISH_REFERENCE_ID=your-reference-id
FISH_MODEL=s2.1-pro-free
FISH_FORMAT=mp3
```

Environment variables:

| Variable                    | Required | Default  | Description                                   |
|-----------------------------|----------|----------|-----------------------------------------------|
| `FISH_API_KEY`              | Yes      | —        | Fish Audio API key                            |
| `FISH_REFERENCE_ID`         | Yes      | —        | Voice reference ID from your Fish account     |
| `FISH_MODEL`                | No       | `s2.1-pro-free` | Fish Audio model ID                     |
| `FISH_FORMAT`               | No       | `mp3`    | Output audio format                           |
| `FISH_SPEED`                | No       | `1.0`    | Prosody speed multiplier                      |
| `FISH_SAMPLE_RATE`          | No       | `44100`  | Output sample rate in Hz                      |
| `FISH_TEMPERATURE`          | No       | `0.7`    | Sampling temperature (lower = more deterministic) |
| `FISH_TOP_P`                | No       | `0.7`    | Top-p nucleus sampling                        |
| `FISH_REPETITION_PENALTY`   | No       | `1.2`    | Repetition penalty (>1.0 curbs repeated sounds) |
| `FISH_MAX_NEW_TOKENS`       | No       | `1024`   | Max tokens per synthesis chunk                |
| `FISH_NORMALIZE`            | No       | `true`   | Normalize text before synthesis               |
| `FISH_TIMEOUT`              | No       | `60`     | Request timeout in seconds                    |
| `FISH_MAX_RETRIES`          | No       | `3`      | Maximum retry attempts for transient failures |

Change voices by setting `FISH_REFERENCE_ID` to a different reference ID from your Fish Audio account.

Override per-scene voices in code:

```python
provider.generate(text, output_path, voice="another_reference_id")
```

### ElevenLabs

ElevenLabs provides fast, high-quality cloud TTS. Select it with:

```
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your-key
ELEVENLABS_MODEL=eleven_flash_v2_5
ELEVENLABS_VOICE_ID=ZthjuvLPty3kTMaNKVKb
```

Supported models: `eleven_flash_v2_5`, `eleven_turbo_v2_5`, `eleven_multilingual_v2`.

Change voices by setting `ELEVENLABS_VOICE_ID` to any voice ID from your ElevenLabs account.

Override per-scene voices in code:

```python
provider.generate(text, output_path, voice="another_voice_id")
```