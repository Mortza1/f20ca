# Garage Booking Bot — Project Overview & Research Plan

---

## What will the system do?
A real-time voice assistant that books garage appointments through natural speech. The user speaks, the bot listens, extracts booking details (name, car registration, model, mileage, warranty, issue), and confirms a slot — entirely hands-free. The core challenge is doing this with low enough latency to feel like a natural conversation.

## What is the main research question?
**How much can end-to-end voice pipeline latency be reduced in a task-oriented dialogue system, and which architectural and signal-processing techniques contribute most?**

## What components will it have?
```
Microphone → VAD → STT → Hybrid NLU → State Machine → TTS → Speaker
```
- **VAD**: detects when the user is speaking vs silent
- **STT**: converts speech to text (ElevenLabs Scribe)
- **Hybrid NLU**: parser LLM + state machine + fallback conversational LLM
- **TTS**: converts bot text to speech (ElevenLabs Flash)
- **Frontend**: browser-based UI with real-time feedback

## Which tools / subsystems?
| Component | Tool |
|-----------|------|
| Backend | Flask + Socket.IO |
| VAD | Silero VAD (local PyTorch) + browser RMS |
| STT | ElevenLabs Scribe v2 |
| LLM | Cohere Command-A / OpenRouter |
| TTS | ElevenLabs Flash v2.5 via Puter.js |
| State tracking | Custom Python state machine |
| Frontend | Vanilla JS, Web Audio API, FullCalendar |

## How will we evaluate it?
- **Primary metric**: end-to-end latency per turn (ms from silence detection to first audio playback)
- **Breakdown**: measure each stage — VAD, STT, LLM, TTS — independently
- **Accuracy**: field extraction accuracy (how often are name/reg/mileage etc captured correctly)
- **Fallback rate**: % of turns that hit the slow LLM path vs fast parser path
- **Subjective**: conversation naturalness, number of turns to complete a booking

## Group Roles
| Member | Focus |
|--------|-------|
| Murtaza | Architecture — hybrid state machine, dialogue engine, parser/fallback routing |
| Member 2 | End-to-end streaming latency — chunk STT, streaming LLM→TTS pipeline |
| Member 3 | VAD & audio pre-processing — adaptive thresholds, noise handling |
| Member 4 | Information extraction accuracy — phonetic normalisation, constrained decoding |

## Project Plan
**Now (research phase)**
- Each group surveys papers in their area (listed in sections below)
- Identify which techniques are feasible to implement within the project scope
- Document baseline latency numbers from the current working system

**Next (implementation phase)**
- Each group implements their improvement on the shared codebase
- Integration testing: confirm improvements compose without regressions
- Run evaluation metrics on baseline vs improved system

**Final (writeup + presentation)**
- Compare before/after latency breakdowns per stage
- Identify which of the 4 changes had the most impact
- Reflect on what was practical vs what remained theoretical

---

# Four Fundamental Improvements

---

## 1. Architecture: Hybrid State Machine + LLM

### Problem
Baseline pipeline sent every utterance through the LLM — including simple answers like "John" or "No warranty" — adding 600–1200ms per turn unnecessarily.

### Approach
Three-tier decision system, ordered by cost:

1. **Greeting** — hardcoded response, no LLM
2. **Parser path** — small LLM call extracts JSON (<200 tokens), state machine picks the next pre-scripted question
3. **Fallback** — full conversational LLM, streaming, only for ambiguous inputs

State machine tracks 6 ordered fields (`name → car_reg → car_model → mileage → warranty → issue`) and is fully deterministic once a parse succeeds. Inputs are normalised on ingestion (`"120k"` → `120000`, `"yeah"` → `True`). Pre-recorded `.wav` files per question make the fast path near-zero TTS latency.

### Research Papers
- Williams, J. et al. — *Hybrid Code Networks* (ACL 2017)
- Wu, C-S. et al. — *TRADE: Transferable Dialogue State Generator* (ACL 2019)
- Hosseini-Asl, E. et al. — *SimpleTOD* (NeurIPS 2020)
- Wu, C-S. et al. — *TOD-BERT* (EMNLP 2020)

---

## 2. End-to-End Streaming Latency

### Problem
Current pipeline is sequential and blocks at each stage: full audio → STT → full LLM response → TTS → play. Time-to-first-audio is the sum of all stages.

### Targets
- **Chunk-streamed STT**: send audio in rolling chunks rather than waiting for silence to fire the full clip
- **Speculative / early-exit LLM decoding**: begin TTS synthesis on the first completed sentence rather than waiting for the full response
- **Streaming TTS**: pipe LLM token stream directly into TTS API chunk-by-chunk; ElevenLabs flash model already supports this
- **Sentence boundary detection**: split LLM stream at `.`, `?`, `!` to feed TTS in natural playable units

### Research Papers
- He, Y. et al. — *Streaming End-to-End Speech Recognition For Mobile Devices* (ICASSP 2019) — RNN-T streaming ASR
- Leviathan, Y. et al. — *Fast Inference from Transformers via Speculative Decoding* (ICML 2023)
- Cai, T. et al. — *Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads* (2024)
- Chen, C. et al. — *Accelerating Large Language Model Decoding with Speculative Sampling* (DeepMind 2023)

---

## 3. VAD & Audio Pre-processing

### Problem
Two-stage VAD (browser RMS + server Silero) works but has weaknesses: browser RMS threshold is a single global scalar; Silero runs after full conversion which costs latency; no handling of overlapping noise, music, or non-English speech bursts triggering false positives.

### Targets
- **Adaptive threshold VAD**: dynamic noise floor estimation instead of fixed `0.02` RMS
- **Streaming VAD**: run Silero on rolling 30ms frames rather than the full clip post-conversion
- **Multi-class audio tagging**: distinguish speech vs music vs background noise before hitting STT
- **Noise-robust pre-processing**: spectral subtraction or RNNoise-style denoising before VAD and STT

### Research Papers
- Silero Team — *Silero VAD: pre-trained enterprise-grade Voice Activity Detector* (2021)
- Jia, F. et al. — *MarbleNet: Deep 1D Time-Channel Separable Convolutional Neural Network for Voice Activity Detection* (ICASSP 2021)
- Lavechin, M. et al. — *Brouhaha: Multi-task Training for VAD, SNR, and Room Acoustics Estimation* (Interspeech 2022)
- Bredin, H. — *pyannote.audio 2.1: speaker diarization pipeline* (ICASSP 2023)

---

## 4. Information Extraction Accuracy

### Problem
The parser LLM can misread spoken-form inputs: registration plates dictated letter-by-letter (`"Echo Foxtrot 2 3"` → `EF23`), mileage with verbal suffixes (`"about forty-five thousand"`), and warranty phrasing variations. Parse failures cascade to the slower fallback path.

### Targets
- **Phonetic normalisation**: post-process STT output to convert NATO alphabet, number words, and spoken plate formats before sending to parser
- **Constrained decoding / grammar-guided generation**: force the parser LLM output to conform to a strict JSON schema, eliminating malformed responses
- **Few-shot exemplars in parser prompt**: add 3–4 input/output examples covering edge cases (spoken numbers, uncertain phrasing)
- **Confidence scoring**: have the parser return a confidence field; low-confidence fields trigger a targeted clarification question rather than silent storage

### Research Papers
- Radford, A. et al. — *Robust Speech Recognition via Large-Scale Weak Supervision (Whisper)* (ICML 2023) — spoken-form normalisation insights
- Scholak, T. et al. — *PICARD: Parsing Incrementally for Constrained Auto-Regressive Decoding* (EMNLP 2021)
- Geng, S. et al. — *Grammar-Constrained Decoding for Structured NLP Tasks* (EMNLP 2023)
- Wei, J. et al. — *Chain-of-Thought Prompting Elicits Reasoning in Large Language Models* (NeurIPS 2022) — few-shot structured extraction
- Schick, T. et al. — *Toolformer: Language Models Can Teach Themselves to Use Tools* (NeurIPS 2023)
