# Cipher

Shazam for movies. Hear dialogue, tap one button, get the movie and where to watch it.

## How it works

1. Tap the button in Cipher while a video is playing
2. Cipher listens for up to 30 seconds
3. Whisper transcribes the captured audio
4. Transcript is embedded and searched against a Qdrant vector DB of movie subtitles
5. JustWatch lookup finds where to stream it
6. Result shows: "A Few Good Men (1992) - Watch on Netflix"
7. Tap → deep link directly into the streaming app

## Structure

```
cipher/
├── backend/
│   ├── main.py          # FastAPI app, single POST /identify endpoint
│   ├── search.py        # Qdrant vector search logic
│   ├── transcribe.py    # Whisper STT logic
│   ├── justwatch.py     # JustWatch scraper for streaming availability
│   └── requirements.txt
├── ios/                 # SwiftUI app (single screen)
├── scripts/
│   ├── parse_srt.py     # Parse + clean + chunk SRT files
│   ├── embed.py         # Embed chunks + store in Qdrant
│   └── data/            # Raw .srt files go here
└── README.md
```

## Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Data pipeline
1. Drop `.srt` files into `scripts/data/`
2. `python scripts/parse_srt.py`
3. `python scripts/embed.py`
