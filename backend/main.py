# FastAPI app — single POST /identify endpoint

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .transcribe import transcribe
from .search import search
from .justwatch import get_streaming

app = FastAPI()


TEST_QUERY = "You either die a hero or live long enough to see yourself become the villain"


@app.get("/test")
async def test():
    result = search(TEST_QUERY)
    if result is None:
        return JSONResponse({"match": False})
    return JSONResponse({
        "movie": result["movie"],
        "year": result["year"],
        "confidence": result["confidence"],
    })


@app.post("/identify")
async def identify(audio: UploadFile = File(...)):
    suffix = Path(audio.filename).suffix if audio.filename else ".audio"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            content = await audio.read()
            if not content:
                raise HTTPException(status_code=400, detail="Audio file is empty")
            tmp.write(content)

        transcript = transcribe(tmp_path)
        print(f"Transcript: {transcript!r}")

        # Reject if too short or too few real words (gibberish guard)
        words = [w for w in transcript.split() if w.isalpha()]
        if not transcript or len(words) < 2:
            print("Transcript too short or gibberish — rejecting")
            return JSONResponse({"match": False})

        result = search(transcript)
        print(f"Search result: {result}")

        if result is None:
            return JSONResponse({"match": False})

        streaming = get_streaming(result["movie"], result["year"])

        return JSONResponse({
            "movie": result["movie"],
            "year": result["year"],
            "confidence": result["confidence"],
            "streaming": streaming,
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
