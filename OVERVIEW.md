# Cipher — Project Overview

> **Shazam for movies.** Record a clip of dialogue, identify the movie, find where to stream it — instantly.

---

## What It Does

1. User taps a button and holds their phone near a TV/speaker
2. App records up to 15 seconds of audio
3. Audio is transcribed to text via Whisper (runs locally)
4. Transcript is matched against a vector database of movie subtitles
5. Match is confirmed with fuzzy string matching
6. App returns the movie title, poster, rating, synopsis, and streaming links
7. Tap a streaming platform button → the native app opens directly to that movie

---

## Tech Stack

| Layer | Technology |
|---|---|
| Mobile frontend | React Native 19.1.0 + Expo 54 (TypeScript) |
| Backend API | FastAPI (Python) + Uvicorn |
| Speech-to-text | whisper.cpp (local, Metal GPU on Mac) |
| Vector search | Qdrant (Docker) + sentence-transformers `all-MiniLM-L6-v2` |
| Fuzzy matching | RapidFuzz |
| Streaming data | JustWatch GraphQL API (scraped, no official key) |
| Movie metadata | TMDB API |
| Audio recording | expo-av + custom iOS native module (Obj-C) |
| HTTP client | httpx (async) |
| Subtitle parsing | Custom SRT chunker (Python) |

---

## Directory Structure

```
Cipher/
├── backend/              # FastAPI server
│   ├── main.py           # Single POST /identify endpoint
│   ├── transcribe.py     # Whisper.cpp wrapper (STT)
│   ├── search.py         # Two-stage search algorithm
│   ├── justwatch.py      # JustWatch GraphQL scraper
│   ├── tmdb.py           # TMDB movie metadata + images
│   └── requirements.txt
│
├── expo/                 # React Native app
│   ├── App.tsx           # Entire UI (~720 lines, single screen + tabs + modal)
│   ├── app.json          # Expo config
│   └── ios/
│       └── cipherapp/
│           └── AudioSessionModule.m  # Custom native audio module
│
├── scripts/              # Offline data pipeline
│   ├── pipeline.py       # Orchestrator (Docker → embed → serve)
│   ├── chunk_srt.py      # SRT → overlapping text chunks
│   ├── embed.py          # Chunks → Qdrant vector upserts
│   └── data/             # .srt subtitle files + test audio
│
├── .env                  # TMDB_API_KEY, SUBDL_API_KEY
├── search_logic.md       # Algorithm deep-dive
├── notes.md              # Dev log / historical fixes
└── commands.md           # CLI reference
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    iPhone (Expo App)                    │
│                                                         │
│  [Red Record Button]  →  expo-av records 15s m4a        │
│         ↓                                               │
│  POST /identify  (multipart audio file)                 │
└─────────────────────────┬───────────────────────────────┘
                          │  HTTP (local WiFi, port 8000)
                          ▼
┌─────────────────────────────────────────────────────────┐
│                  Mac (FastAPI Server)                   │
│                                                         │
│  1. transcribe.py    m4a → 16kHz WAV → whisper.cpp      │
│  2. search.py        transcript → Qdrant → candidates   │
│                      → RapidFuzz → best match           │
│  3. justwatch.py     movie name → streaming platforms   │
│  4. tmdb.py          movie name → poster, rating, etc.  │
│         ↓                                               │
│  JSON response with all fields combined                 │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    iPhone (Result)                      │
│                                                         │
│  Modal: poster, title, year, genres, confidence %       │
│  Streaming buttons → Linking.openURL → native app       │
└─────────────────────────────────────────────────────────┘
```

---

## Core Algorithm: Two-Stage Search

This is the heart of the project. Naive vector search alone fails because generic phrases ("What are you doing?") match hundreds of movies equally. Fuzzy matching alone is too slow across thousands of movies.

### Stage 1 — Vector Frequency Count

1. Split the Whisper transcript into individual sentences (3+ words)
2. Encode each sentence with `sentence-transformers` (384-dim vectors)
3. Query Qdrant for top 40 nearest subtitle chunks per sentence
4. Tally which movie appears most across all sentences
5. Return top 10 movie candidates

### Stage 2 — Fuzzy Confirmation

1. For each candidate movie, load ALL its subtitle chunks from Qdrant
2. Concatenate chunks into one big `movie_text` string
3. For each transcript sentence, run `rapidfuzz.partial_ratio` against `movie_text`
4. Count how many sentences score ≥ 70 (character-level partial match)
5. Winner = movie with the most high-scoring sentences (tiebreak: average score)

**Why this works:** Stage 1 narrows from thousands of movies to 10 candidates cheaply. Stage 2 confirms exact wording match on just those 10.

**Key thresholds:**
```python
TOP_K = 40            # Qdrant results per sentence
MAX_CANDIDATES = 10   # Movies sent to fuzzy stage
FUZZY_THRESHOLD = 70  # Minimum partial_ratio to count
MIN_FUZZY_MATCHES = 1 # Sentences that must exceed threshold
```

---

## Data Pipeline (Offline)

Run once per batch of new subtitle files:

```
*.srt files  →  chunk_srt.py  →  chunks.json  →  embed.py  →  Qdrant
```

**chunk_srt.py:**
- Parses `Movie_Name_YYYY.srt` filenames to extract title + year
- Strips timing lines, sequence numbers, HTML tags, sound effects `[...]`
- Creates 4-line overlapping windows (1-line overlap) of dialogue
- Outputs flat `chunks.json`

**embed.py:**
- Reads `chunks.json`
- Skips movies already in Qdrant (idempotent — ID is `MD5(movie|year|chunk_index) % 2^63`)
- Batch-encodes texts with `sentence-transformers`
- Upserts 384-dim vectors into Qdrant `cipher` collection

**pipeline.py:**
- Starts Docker + Qdrant container
- Detects Mac local IP, auto-patches `API_URL` in `App.tsx`
- Runs chunk + embed scripts
- Launches FastAPI with `--reload`

---

## API Reference

### `POST /identify`

**Request:** multipart form with `audio` file field (m4a, wav, mp3, etc.)

**Response — no match:**
```json
{ "match": false }
```

**Response — match found:**
```json
{
  "movie": "The Batman",
  "year": 2022,
  "confidence": 92.5,
  "poster_url": "https://image.tmdb.org/t/p/w500/...",
  "backdrop_url": "https://image.tmdb.org/t/p/w500/...",
  "logo_url": null,
  "synopsis": "Two years of stalking the streets...",
  "rating": 7.8,
  "genres": ["Crime", "Drama", "Mystery"],
  "streaming": [
    { "platform": "Max", "deep_link": "max://movie/..." },
    { "platform": "Netflix", "deep_link": "nflx://www.netflix.com/title/..." }
  ]
}
```

**Validation guard:** If Whisper returns fewer than 2 alphabetic words (silence, music, noise), returns `{"match": false}` immediately without hitting search.

---

## Frontend: App.tsx

Single-file React Native app (~720 lines) with one screen, three tabs, and a result modal.

### App State Machine

```
idle  ──tap──►  listening  ──15s/tap──►  processing  ──►  result modal
  ▲                                                              │
  └──────────────────────────── dismiss ────────────────────────┘
```

### Three Tabs

**Home**
- Large red circular button (Netflix gradient `#E50914 → #8B0000`)
- Pulses white border while listening
- "Recently Found" horizontal carousel below (10 items max)

**Library**
- Full history of all identifications (up to 50)
- Grouped by date: Today / Yesterday / day name / month+year
- Shows confidence % alongside each entry
- Tap any row to reopen the result modal

**Watchlist**
- Bookmarked movies (client-side only, no persistence)
- Bookmark icon on result modal toggles add/remove

### Result Modal

- Full-screen slide-up presentation
- Hero poster fills 70% of screen height
- Linear gradient overlay (transparent → black) with title at bottom-left
- Meta line: `Crime · Drama · 2022 · 92% match`
- Streaming buttons (white, one per platform) → `Linking.openURL(deep_link)`
- If nothing streaming: greyed "Not currently streaming" button
- Bookmark icon (red when saved)
- Synopsis text below buttons

### Notifications

After a successful identification, a system banner fires even if the app is backgrounded:
```typescript
Notifications.scheduleNotificationAsync({
  content: { title: movie, body: platforms.join(' · ') },
  trigger: null  // fires immediately
})
```

---

## iOS Native Module: AudioSessionModule

**File:** `expo/ios/cipherapp/AudioSessionModule.m`

**Problem:** iOS automatically ducks other apps' audio when the microphone activates. This makes it impossible to record a movie playing from TikTok/YouTube — the volume drops the moment recording starts.

**Solution:** A custom Objective-C native module exposed to JavaScript via `NativeModules.AudioSessionModule`:

```objc
configure()
  → AVAudioSession.setCategory(.playAndRecord, options: [.mixWithOthers])
```

`.mixWithOthers` tells iOS not to duck other apps. Called before every recording starts.

Also exports:
- `beginBackgroundTask()` — prevents app suspension mid-recording
- `endBackgroundTask()` — cleanup after recording stops

---

## Networking

- FastAPI binds to `0.0.0.0:8000` so the iPhone can reach it on local WiFi
- `pipeline.py` detects the Mac's LAN IP (`ipconfig getifaddr en0`) and patches `API_URL` in `App.tsx` automatically
- iOS `Info.plist` has `NSAllowsArbitraryLoads: true` to allow plain HTTP (no HTTPS required on local network)

---

## Streaming Platform Deep Links

| Platform | Deep Link Pattern |
|---|---|
| Netflix | `nflx://www.netflix.com/title/{id}` |
| Prime Video | `aiv://aiv/play?asin={id}` |
| Max (HBO) | `max://movie/{id}` |
| Hulu | `hulu://{path}` |
| Apple TV+ | `videos://{path}` |

Only FLATRATE (subscription) and FREE (ad-supported) offers are included. Rentals and purchases are filtered out.

---

## Environment Variables

```bash
# .env (not committed)
TMDB_API_KEY=...       # themoviedb.org
SUBDL_API_KEY=...      # subdl.com (subtitle downloads)
```

---

## Running Locally

```bash
# 1. Start Qdrant + embed subtitles + start API server
cd scripts && python pipeline.py

# 2. Start Expo dev client (separate terminal)
cd expo && npx expo start

# 3. Open on iPhone via Expo Go or custom dev client
```

The `pipeline.py` script handles Docker, Qdrant, IP detection, embedding, and server startup in one command.

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| whisper.cpp instead of OpenAI API | Fully local, Metal-accelerated, no latency/cost per call |
| Two-stage search (vector + fuzzy) | Vector alone over-matches generic phrases; fuzzy alone is too slow |
| Overlapping subtitle chunks | Ensures dialogue spanning a chunk boundary still matches |
| Deterministic vector IDs (MD5) | Embedding is idempotent; re-runs don't create duplicates |
| Custom native audio module | iOS ducks audio by default; `.mixWithOthers` prevents it |
| Single `App.tsx` file | Fast iteration; complexity is low enough that splitting isn't needed yet |
| JustWatch GraphQL (unofficial) | No official streaming availability API exists; JustWatch is the best source |

---

## Status

Active development. Core identification flow is working end-to-end. Recent commits include Whisper improvements, fuzzy search logic, cosine similarity tuning, TMDB integration, and UI polish.
