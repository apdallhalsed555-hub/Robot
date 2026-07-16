# Mahmoud's Individual Contribution
## AI Robot System (Musa) — Graduation Project

**Kafrelsheikh University — Faculty of Engineering — Intelligent Systems Program**

---

---

## 1. Overview

My contribution to the Musa robot system spans four core subsystems that form the **complete voice interaction pipeline** — from the moment the user speaks, through cognitive reasoning, to the robot's spoken reply, plus the web search tool that gives the robot access to live information.

This document focuses on the **engineering decisions, parameter tuning, and custom logic** I implemented. These subsystems are not off-the-shelf model downloads; each required careful calibration, custom filtering layers, and architectural design to achieve real-time, natural interaction.


![Architecture Diagram](scratch/kroki_1.png)

---

## 2. Text-to-Speech (TTS) Engine

**Source**: [tts_engine.py](file:///x:/Robot-main/Robot-main/voice/tts_engine.py)

### 2.1 Model Selection & Configuration

| Parameter | Value | Rationale |
|:---|:---|:---|
| **Model** | Kokoro (`KPipeline`) | Lightweight, local, FP16-capable TTS with natural prosody |
| **Voice** | `af_heart` | Selected for warm, conversational tone suitable for a companion robot |
| **Speed** | `1.0×` | Natural pacing; avoids rushed or sluggish delivery |
| **Sample Rate** | `24,000 Hz` | Kokoro's native output rate — no resampling needed |
| **Language Code** | `"a"` (American English) | Matches the English-only system constraint |
| **Device** | Auto (`cuda` / `cpu`) | GPU-accelerated synthesis when available; CPU fallback |

### 2.2 SentenceBuffer — Streaming Architecture

A critical design I implemented is the **SentenceBuffer** class, which enables the robot to start speaking **before the LLM finishes generating its full response**. This is the single largest latency optimization in the entire system.


![Architecture Diagram](scratch/kroki_2.png)

**How it works:**

- Tokens from the LLM are accumulated into a buffer
- A regex pattern `(.*?[.?!:\n]+)\s*` splits the buffer at sentence boundaries (`.`, `?`, `!`, `:`, `\n`)
- As soon as a complete sentence is detected, it's immediately dispatched to Kokoro for synthesis
- When the LLM stream ends, `flush()` sends any remaining partial text

**Impact**: The first sentence reaches the speaker **~120 ms** after Kokoro receives it, while the LLM is still generating the rest. Without this, the user would wait for the entire LLM response (~290 ms) *plus* full TTS synthesis before hearing anything.

### 2.3 Barge-In Interrupt System

The robot supports **real-time user interruption** — if the user starts speaking while the robot is talking, playback stops instantly:

```python
def interrupt(self):
    with self._lock:
        if self.is_speaking:
            self.stop_event.set()     # Signal all loops to stop
            sd.stop()                 # Immediately halt audio output
            self.is_speaking = False
```

**Design decisions:**
- `threading.Event` is used as a cooperative cancellation signal checked at every sentence boundary
- `sounddevice.stop()` provides hardware-level audio cutoff (< 5 ms)
- `is_speaking` flag allows the STT engine to distinguish robot speech from user speech
- `last_output_end_ts` timestamp enables the post-TTS cooldown window (prevents echo pickup)

---

## 3. Speech-to-Text (STT) Engine

**Source**: [stt_engine.py](file:///x:/Robot-main/Robot-main/voice/stt_engine.py)

### 3.1 Model Configuration & Tuning

The STT engine uses **faster-whisper** (CTranslate2-optimized Whisper) with extensive parameter tuning:

| Parameter | Value | Purpose |
|:---|:---|:---|
| **Model Size** | `small` | Balance of accuracy vs. latency (~480 ms per utterance) |
| **Compute Type** | `float16` (GPU) / `int8` (CPU) | FP16 halves VRAM usage; INT8 for CPU fallback |
| **Beam Size** | `5` | Higher beam = better accuracy for accented speech |
| **Temperature** | `0.0` | Deterministic decoding — no randomness in transcription |
| **VAD Filter** | `enabled` | Silero VAD pre-filters silence before Whisper processes it |
| **VAD Min Silence** | `450 ms` | Tuned to avoid splitting mid-sentence pauses |
| **No-Speech Threshold** | `0.72` | Segments with > 72% no-speech probability are discarded |
| **Log Prob Threshold** | `-1.0` | Rejects very low-confidence segments |
| **Compression Ratio** | `2.4` | Detects and discards repetitive hallucination loops |
| **Avg LogProb Floor** | `-0.85` | Custom threshold — segments below this confidence are dropped |

### 3.2 Audio Capture Pipeline

The STT runs two dedicated threads:


![Architecture Diagram](scratch/kroki_3.png)

**Key audio parameters:**

| Parameter | Value | Why This Value |
|:---|:---|:---|
| **Sample Rate** | `16,000 Hz` | Whisper's native input rate — no resampling overhead |
| **Chunk Size** | `1,024 samples` | 64 ms per chunk — low latency while avoiding buffer underruns |
| **Silence Threshold** | `0.02` RMS | Tuned for typical room noise floor; avoids false triggers |
| **Silence Duration** | `0.8 s` | Time of silence before finalizing — allows natural pauses |
| **Max Chunk Duration** | `30 s` | Prevents unbounded memory growth; triggers mid-utterance stitching |
| **Barge-In RMS** | `max(0.055, 1.5 × SILENCE_THRESHOLD)` | Must be louder than ambient to interrupt — prevents echo self-triggers |
| **Post-TTS Cooldown** | `0.65 s` | After robot stops speaking, ignore quiet mic for 650 ms to suppress speaker bleed / echo tails |
| **Startup Grace** | `0.5 s` | Ignore first 500 ms of audio after system boot (mic initialization noise) |

### 3.3 Hallucination Suppression (Custom Logic)

This is where the most engineering effort went. Raw Whisper output from ambient noise produces many false positives. I implemented a **multi-layer filtering pipeline**:


![Architecture Diagram](scratch/kroki_4.png)

**Filter layers in detail:**

1. **Repetitive Garbage Detection** ([locale.py](file:///x:/Robot-main/Robot-main/brain/locale.py)): If >= 45% of words are the same word, or <= 2 unique words in 8+ word sequences, discard. Catches Whisper loop hallucinations.

2. **Short Utterance Whitelist**: Transcriptions under 3 words are almost always noise *unless* they match a curated set of legitimate short phrases (`hello`, `yes`, `stop`, `help`, etc.) or name introduction patterns (`I'm...`, `My name is...`).

3. **Known Hallucination Phrases**: A hardcoded set of Whisper's most common false positives from ambient noise: `"thank you"`, `"thanks for watching"`, `"like and subscribe"`, `"the end"`, etc.

4. **Alphabetic Ratio Check**: If less than 30% of characters are alphabetic (mostly punctuation/numbers from noise), discard.

5. **Confidence Floor**: Average log-probability across all segments must be >= `-0.85`. This is stricter than Whisper's default and was tuned through testing to reject uncertain transcriptions while keeping accented speech.

### 3.4 Silence Accumulation Prevention

A subtle but important optimization:

```python
# If we don't have speech yet, only keep the last 1.0 second of audio as context
if not has_speech:
    max_frames = int(self.SAMPLE_RATE * 1.0)
    if len(current_audio) > max_frames:
        current_audio = current_audio[-max_frames:]
```

Without this, during long periods of silence the audio buffer grows unboundedly. When speech finally arrives, Whisper would need to process minutes of silence, causing massive latency. This cap ensures only 1 second of pre-speech context is kept.

### 3.5 Initial Prompt Biasing

```python
def _compose_initial_prompt(self):
    chunks = [
        "Mahmoud, Abdullah, Ola, Egypt, Musa, Robot, AI, Hello, Hi, My name is",
    ]
    # + optional external vocabulary file
```

Whisper's `initial_prompt` parameter biases the decoder toward expected vocabulary. By seeding it with team member names, the robot's name, and common introductory phrases, transcription accuracy for these terms improves significantly — especially for non-native English speakers.

---

## 4. Orchestration Logic — The Brain Between STT and TTS

This is the **central nervous system** that connects hearing to speech. It's not just "call the LLM and speak the result" — there are multiple layers of logic that make the interaction feel natural.

### 4.1 Prioritized Event Bus

**Source**: [events.py](file:///x:/Robot-main/Robot-main/core/events.py)


![Architecture Diagram](scratch/kroki_5.png)

**Why priority matters**: If the user speaks while a vision event is queued, the speech event **always** processes first. This ensures the robot never ignores the user to comment on a visual change.

| Priority | Event Type | Example |
|:---|:---|:---|
| `0` (highest) | `SpeechEvent` | User said "Search for transistors" |
| `1` (lower) | `VisionChangeEvent` | New face appeared in camera |

### 4.2 Barge-In + Echo Suppression State Machine

The interaction between STT and TTS during simultaneous operation is managed by a carefully designed state machine:


![Architecture Diagram](scratch/kroki_6.png)

**The three key thresholds and their relationship:**

```
BARGE_IN_RMS (0.055) ─────────────── User clearly speaking
                                      (overrides robot speech)

                     ← 1.5× gap →

SILENCE_THRESHOLD (0.02) ────────── Normal speech detected
                                      (start accumulating)

0.00 ────────────────────────────── Complete silence
```

The barge-in threshold is intentionally set to `max(0.055, 1.5 × SILENCE_THRESHOLD)`. This gap ensures that **quiet echo bleed** from the robot's own speaker doesn't trigger a false barge-in, while a **real human voice** (which is louder) does.

### 4.3 Addressing Heuristics — Who Is the User Talking To?

**Source**: [addressing.py](file:///x:/Robot-main/Robot-main/brain/addressing.py)

In multi-person scenarios, the robot needs to determine whether speech is directed at it or is just overheard conversation between humans. I implemented a **scoring system** that runs with zero LLM latency:

| Signal | Score Change | Example |
|:---|:---|:---|
| Wake word detected (`"musa"`, `"hey musa"`) | `+0.42` | "Hey Musa, what time is it?" |
| Question or direct request | `+0.28` | "Can you search for...?" |
| Single person, neutral phrasing | `+0.12` | "I need to find something" |
| Multiple people, no robot cue | `-0.08` | Two people chatting nearby |
| Mentions another person's name | `-0.24` | "Abdullah, did you finish?" |
| Short backchannel with multiple people | `-0.22` | "yeah", "uh-huh", "ok" |

**Decision threshold**: Score >= `0.45` means likely for robot, respond normally. Score < `0.45` means likely overheard, acknowledge lightly or stay silent.

### 4.4 LLM Tool Execution Loop with Error Recovery

**Source**: [llm_engine.py](file:///x:/Robot-main/Robot-main/brain/llm_engine.py)

The LLM (Groq LLAMA-3.3-70B) supports tool calling, but the model sometimes generates malformed tool syntax. I implemented a **multi-layer recovery system**:


![Architecture Diagram](scratch/kroki_7.png)

> [!IMPORTANT]
> **Latency fix I implemented**: Previously, when Groq threw a `400` error for malformed tool calls, the system rotated through all 4 API keys (retrying the same bad request 4 times) before recovering. I modified [llm_provider.py](file:///x:/Robot-main/Robot-main/brain/llm_provider.py) to **immediately raise** `400`/`tool_use_failed` errors, skipping useless retries. Key rotation now only triggers for actual rate limits (`429`) or server errors.

### 4.5 Filler Phrases During Tool Execution

While a tool executes (web search, memory lookup), the robot speaks a contextual filler to avoid awkward silence:

```python
def on_tool(tool_name: str):
    if tool_name == "search_web":
        tts.say("hold on, let me look that up real quick.")
    elif tool_name == "search_memory":
        tts.say("give me a second, let me check my memory.")
    else:
        tts.say("hold on a second.")
```

This runs **synchronously** before the tool executes, so the user hears feedback immediately while the search runs in the background.

### 4.6 Memory Architecture (STM + LTM)

**Sources**: [stm.py](file:///x:/Robot-main/Robot-main/brain/memory/stm.py) | [ltm.py](file:///x:/Robot-main/Robot-main/brain/memory/ltm.py)


![Architecture Diagram](scratch/kroki_8.png)

| Memory Type | Capacity | Embedding Model | Dimension | Storage |
|:---|:---|:---|:---|:---|
| **STM** | 5 exchanges (rolling) | N/A (raw text) | — | In-memory |
| **LTM** | Unlimited (per-user) | `BAAI/bge-small-en-v1.5` | 384 | Qdrant |

**Query-Fusion RAG** (my implementation in LTM): When retrieving memories, I don't just embed the raw query. If a user profile hint is available, I create a **blended embedding**:

```python
blended = f"{user_profile_hint}\nTopic: {query}"
vec_blended = embed(blended)
final_vector = (vec_query + vec_blended) * 0.5  # average fusion
```

This improves recall for pronouns and contextual references (e.g., "what did I tell you about my project?" retrieves better when the system knows the user's project context).

---

## 5. Web Search Tool

**Source**: [web_search_tool.py](file:///x:/Robot-main/Robot-main/brain/tools/web_search_tool.py)

### 5.1 Architecture — Triple-Fallback Search


![Architecture Diagram](scratch/kroki_9.png)

### 5.2 Configuration Parameters

| Parameter | Value | Purpose |
|:---|:---|:---|
| **Max Results** | `3` | Keeps LLM context small; avoids token bloat |
| **Snippet Max Chars** | `450` | Truncates long snippets to stay within token budget |
| **Search Depth** | `"advanced"` (Tavily) | Deeper crawling for more accurate results |
| **Translation Temp** | `0.0` | Deterministic Arabic-to-English translation |
| **Fallback Regions** | `wt-wt, us-en, eg-en` | DuckDuckGo region rotation for broader coverage |

### 5.3 Arabic Query Translation

The robot's STT may transcribe Arabic speech. Since web search engines return better results for English queries, I implemented automatic Arabic detection and translation:

```python
def translate_query_if_arabic(query: str) -> str:
    # Detect Arabic Unicode range: U+0600 to U+06FF
    if not re.search(r"[\u0600-\u06FF]", query):
        return query  # Not Arabic, skip

    # Use Groq LLM for translation (temperature=0 for consistency)
    chat = ChatGroq(api_key=keys[0], temperature=0.0)
    response = chat.invoke(
        "Translate the following Arabic search query to English. "
        "Return ONLY the English translation: " + query
    )
    return response.content.strip()
```

### 5.4 Contextual Search Enhancement

The web search tool receives the recent conversation context automatically:

```python
def search_web_binding(query: str) -> str:
    return search_web(
        query,
        conversation_context=stm.compact_snippet_for_tools(900)
    )
```

The `compact_snippet_for_tools()` method provides up to 900 characters of recent conversation, allowing the search to be contextually aware of what the user has been discussing.

---

## 6. End-to-End Latency Analysis

### 6.1 Processing Pipeline Breakdown

| Stage | Component | Avg Latency | My Contribution |
|:---|:---|:---|:---|
| **1. Audio Capture + VAD** | STT `_process_loop` | ~350 ms | ✅ Tuned silence threshold, VAD params |
| **2. Transcription** | faster-whisper (small, FP16) | ~480 ms | ✅ Model config, hallucination filters |
| **3. LTM RAG Prefetch** | BGE-small + Qdrant | ~45 ms | ✅ Query-fusion implementation |
| **4. LLM Reasoning** | Groq LLAMA-3.3-70B | ~290 ms | ✅ Tool loop, error recovery |
| **5. First Sentence TTS** | Kokoro (FP16) | ~120 ms | ✅ SentenceBuffer streaming |
| **Total** | | **~1,285 ms** | |

### 6.2 Latency Savings from My Optimizations


![Architecture Diagram](scratch/kroki_10.png)

| Optimization | Latency Saved |
|:---|:---|
| SentenceBuffer streaming (speak first sentence while LLM continues) | **~280 ms** |
| Immediate 400-error raise (skip 3 useless API retries) | **~2,000–4,000 ms** (when tool errors occur) |
| Silence accumulation cap (1s pre-speech buffer) | **Variable** (prevents 10s+ delays after long silence) |
| Hallucination filtering (prevents processing garbage) | **~500 ms** per false positive avoided |

---

## 7. Summary of Engineering Decisions

> [!IMPORTANT]
> Every parameter listed in this document was **manually tuned through iterative testing** — not left at defaults. The difference between a working real-time system and a sluggish demo lies in these numbers.

| Decision | Why It Matters |
|:---|:---|
| **Whisper `temperature=0.0`** | Eliminates random variation in transcription — same audio always produces same text |
| **Custom `avg_logprob >= -0.85`** | Stricter than Whisper's default; rejects uncertain ambient noise transcriptions |
| **`SILENCE_DURATION = 0.8s`** | Shorter than typical (1.0-1.5s) — makes the robot feel more responsive |
| **`BARGE_IN_RMS = 1.5x SILENCE_THRESHOLD`** | Prevents echo self-triggers while allowing real interruptions |
| **`POST_TTS_COOLDOWN = 0.65s`** | Suppresses speaker bleed without making the robot seem deaf after speaking |
| **SentenceBuffer regex splitting** | Enables sub-second first-word latency from a streaming LLM |
| **Triple-fallback web search** | Tavily then DDG Text then DDG News ensures the robot almost never fails to find information |
| **400-error immediate raise** | Eliminates 2-4 seconds of wasted API retries on malformed tool calls |
| **Priority 0 for speech events** | User voice always trumps vision events — robot never ignores you |
| **Addressing score heuristic** | Zero-latency directedness detection without an extra LLM call |
