# Cipher

Shazam for movies. Identify movies by audio, image, or both.

## Features

- **Audio search**: Hear dialogue, tap, get the movie
- **Image search**: Snap a screenshot, identify the scene
- **Smart matching**: CLIP embeddings + voting logic across multiple images
- **Streaming links**: JustWatch integration shows where to watch
- **History & watchlist**: Track found movies and save for later

## How it works

### Audio
1. Tap the button while a video is playing
2. Cipher listens for up to 30 seconds
3. Whisper transcribes the audio
4. Transcript is searched against a Qdrant vector DB of movie subtitles
5. JustWatch lookup finds streaming availability

### Cipher Vision (Image search)
1. Take a screenshot of what you're watching
2. CLIP embeds the image and searches Qdrant
3. Voting logic aggregates multiple images for better accuracy
4. Returns movie match with confidence score

## Structure

```
cipher/
├── backend/
│   ├── main.py          # FastAPI app (POST /identify, /identify/image)
│   ├── search.py        # Audio search: Qdrant vector search
│   ├── transcribe.py    # Whisper STT
│   ├── tmdb.py          # Movie metadata + posters
│   ├── justwatch.py     # Streaming availability
│   └── requirements.txt
├── vision/
│   ├── search.py        # CLIP embedding + voting logic
│   ├── embed_frames.py  # Frame extraction + CLIP embedding
│   └── run_all.py       # Batch embed movies (gitignored)
├── expo/                # React Native app (iOS/Android)
│   ├── App.tsx          # Main UI
│   └── package.json
├── scripts/
│   ├── parse_srt.py     # Parse + clean + chunk SRT files
│   ├── embed.py         # Embed chunks + store in Qdrant
│   └── data/            # Raw .srt files
└── README.md
```

## Setup

### Prerequisites
- Python 3.9+
- Node.js 18+
- Qdrant running locally on port 6333
- TMDB API key (free at themoviedb.org)

### Backend
```bash
cd backend
pip install -r requirements.txt
echo "TMDB_API_KEY=your_key_here" > .env
uvicorn main:app --reload
```

### Qdrant
```bash
docker run -p 6333:6333 qdrant/qdrant
```

### Audio embeddings
1. Drop `.srt` files into `scripts/data/`
2. `python scripts/parse_srt.py`
3. `python scripts/embed.py`

### Vision embeddings
```bash
python vision/embed_frames.py --url "https://..." --movie "Movie Name" --year 2024
```

### Mobile app (Expo)
```bash
cd expo
npm install
npx expo start
```
