# DeepTutor Feature & Technical Roadmap

This roadmap tracks ongoing enhancements, architectural improvements, and pending model integrations for DeepTutor.

---

## 1. Immersive Reading & Translation Engine

### Active Default Engine
- **Model**: `Qwen 3.5 4B` (via local Ollama / Apple Silicon Metal GPU)
- **Status**: Production Default
- **Performance**: ~55 tokens/sec on Apple M4 Pro (0.7–1.0s latency per paragraph)
- **Features**: High translation quality across literary and technical domains, zero-thinking-tag suppression (`think=false`), terminology guardrails with placeholder protection.

### Pending Integration: Tencent Hy-MT2 (1.8B / 7B)
- **Target**: Dedicated lightweight multilingual machine translation engine (`tencent/Hy-MT2-1.8B-GGUF`)
- **Upstream Dependency**: [llama.cpp PR #22836](https://github.com/ggml-org/llama.cpp/pull/22836)
  - *Details*: Adds `STQ1_0` (Sherry 1.25-bit ternary quantization) kernel and native `hunyuan-dense` architecture support.
- **DeepTutor Readiness**:
  - `deeptutor/services/translation/glossary.py`: `is_hymt_model()` and `build_hymt_translation_prompt()` implemented.
  - `deeptutor/immersive_reading/service.py`: Dynamic model resolution and IFMT instruction template support added.
- **Activation Trigger**: Enable `hy-mt2:1.8b` as the default dedicated translation backend once upstream `llama.cpp` merges PR #22836 and Ollama integrates the updated runtime.

---

## 2. Knowledge Base & Document Sources
- [x] Local EPUB / PDF parser and section indexing
- [x] Bi-directional bilingual reader synchronization
- [x] Offline ECDICT dictionary integration
- [x] GitHub repository synchronization and documentation tree navigation
- [ ] Web source crawler incremental update and semantic chunking

---

## 3. Capabilities & Multi-Agent Workflows
- [x] `chat`: Unified agentic loop with tool mounting
- [x] `mastery_path`: Guided learning & diagnostic exercises
- [x] `deep_solve` & `deep_research`: Extended reasoning & multi-step synthesis
- [x] `visualize`: Mermaid, Chart.js, SVG, and Manim rendering
