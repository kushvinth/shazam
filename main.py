from typing import Optional, List, Dict
import os
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel

from app.model import generate_Spectogram, fingerprint, create_hashes
from app.cron import FingerprintDB
from app.ingession import download_mp3

app = FastAPI(
    title="Shazam Audio Fingerprinting API",
    description="API for audio fingerprinting, matching, and song database management",
    version="0.1.0",
)

db = FingerprintDB("fingerprints.db")


class SongMetadata(BaseModel):
    title: str
    artist: str
    youtube_id: Optional[str] = None


class FingerprintRequest(BaseModel):
    audio_path: str
    metadata: Optional[SongMetadata] = None


class MatchResponse(BaseModel):
    matches: List[Dict]
    total_matches: int


class PipelineResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict] = None


@app.get("/")
def root():
    return {
        "message": "Shazam Audio Fingerprinting API is running",
        "version": "1.0.0",
        "endpoints": {
            "download": "/download - Download a song by name from YouTube",
            "fingerprint": "/fingerprint - Generate fingerprints from audio file",
            "identify": "/identify - Identify a song from audio sample",
            "add_song": "/add-song - Add a new song to database",
            "full_pipeline": "/pipeline - Complete pipeline: fingerprint + add to DB",
            "search": "/search - Search for songs in database",
            "stats": "/stats - Get database statistics",
        },
    }


@app.get("/download")
def download_song(name: str):
    if not name:
        raise HTTPException(status_code=400, detail="Song name is required")

    try:
        download_mp3(name)
        return {
            "success": True,
            "message": f"Successfully downloaded song: {name}",
            "data": {"song_name": name, "download_directory": "./data"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.post("/fingerprint", response_model=PipelineResponse)
async def fingerprint_audio(audio_file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(await audio_file.read())
            tmp_path = tmp.name

        spec, sr, hop = generate_Spectogram(tmp_path)
        peaks = fingerprint(spec, sr, hop)
        hashes = create_hashes(peaks)
        os.unlink(tmp_path)

        return PipelineResponse(
            success=True,
            message=f"Successfully generated {len(hashes)} fingerprint hashes",
            data={
                "total_peaks": len(peaks),
                "total_hashes": len(hashes),
                "sample_hashes": {k: v for k, v in list(hashes.items())[:10]},
                "sample_peaks": peaks[:10],
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fingerprinting failed: {str(e)}")


@app.post("/identify", response_model=MatchResponse)
async def identify_song(audio_file: UploadFile = File(...)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(await audio_file.read())
            tmp_path = tmp.name

        spec, sr, hop = generate_Spectogram(tmp_path)
        peaks = fingerprint(spec, sr, hop)
        query_hashes = create_hashes(peaks)
        os.unlink(tmp_path)

        matches = db.find_matches(query_hashes)
        return MatchResponse(
            matches=matches or [], total_matches=len(matches) if matches else 0
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Identification failed: {str(e)}")


@app.post("/add-song", response_model=PipelineResponse)
async def add_song_to_database(
    audio_file: UploadFile = File(...),
    title: str = None,
    artist: str = None,
    youtube_id: str = None,
):
    if not title or not artist:
        raise HTTPException(status_code=400, detail="Title and artist are required")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(await audio_file.read())
            tmp_path = tmp.name

        spec, sr, hop = generate_Spectogram(tmp_path)
        peaks = fingerprint(spec, sr, hop)
        hashes = create_hashes(peaks)
        os.unlink(tmp_path)

        song_id = db.add_song(title, artist, youtube_id or "", hashes)

        return PipelineResponse(
            success=True,
            message="Successfully added song to database",
            data={
                "song_id": song_id,
                "title": title,
                "artist": artist,
                "fingerprints_stored": len(hashes),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add song: {str(e)}")


@app.post("/pipeline", response_model=PipelineResponse)
async def full_pipeline(
    audio_file: UploadFile = File(...),
    title: str = None,
    artist: str = None,
    youtube_id: str = None,
    identify_only: bool = False,
):
    if not identify_only and (not title or not artist):
        raise HTTPException(
            status_code=400,
            detail="Title and artist required for adding songs (unless identify_only=True)",
        )

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(await audio_file.read())
            tmp_path = tmp.name

        spec, sr, hop = generate_Spectogram(tmp_path)
        peaks = fingerprint(spec, sr, hop)
        hashes = create_hashes(peaks)
        os.unlink(tmp_path)

        if identify_only:
            matches = db.find_matches(hashes)
            return PipelineResponse(
                success=True,
                message=f"Found {len(matches)} potential matches",
                data={
                    "mode": "identify",
                    "matches": matches,
                    "total_hashes_queried": len(hashes),
                },
            )

        song_id = db.add_song(title, artist, youtube_id or "", hashes)
        return PipelineResponse(
            success=True,
            message="Song successfully added to database",
            data={
                "mode": "add_song",
                "song_id": song_id,
                "title": title,
                "artist": artist,
                "fingerprints_stored": len(hashes),
                "peaks_extracted": len(peaks),
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Pipeline execution failed: {str(e)}"
        )


@app.get("/stats", response_model=PipelineResponse)
def get_database_stats():
    try:
        cursor = db.conn.cursor()
        song_count = cursor.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        fingerprint_count = cursor.execute(
            "SELECT COUNT(*) FROM fingerprints"
        ).fetchone()[0]
        songs = cursor.execute(
            "SELECT id, title, artist, youtube_id FROM songs"
        ).fetchall()

        return PipelineResponse(
            success=True,
            message="Database statistics retrieved",
            data={
                "total_songs": song_count,
                "total_fingerprints": fingerprint_count,
                "avg_fingerprints_per_song": (fingerprint_count / song_count)
                if song_count > 0
                else 0,
                "songs": [
                    {"id": s[0], "title": s[1], "artist": s[2], "youtube_id": s[3]}
                    for s in songs
                ],
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve stats: {str(e)}"
        )


@app.get("/search")
def search_songs(query: str = None):
    try:
        cursor = db.conn.cursor()
        if query:
            q_str = f"%{query}%"
            songs = cursor.execute(
                "SELECT id, title, artist, youtube_id FROM songs WHERE title LIKE ? OR artist LIKE ?",
                (q_str, q_str),
            ).fetchall()
        else:
            songs = cursor.execute(
                "SELECT id, title, artist, youtube_id FROM songs"
            ).fetchall()

        results = [
            {"id": s[0], "title": s[1], "artist": s[2], "youtube_id": s[3]}
            for s in songs
        ]

        return {
            "success": True,
            "query": query or "all",
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


def process_local_file(
    audio_path: str, title: str = None, artist: str = None, youtube_id: str = None
):
    spec, sr, hop = generate_Spectogram(audio_path)
    print(f"Spectrogram generated: {spec.shape}")

    peaks = fingerprint(spec, sr, hop)
    print(f"Peaks extracted: {len(peaks)}")

    hashes = create_hashes(peaks)
    print(f"✓ Hashes created: {len(hashes)}")

    if title and artist:
        song_id = db.add_song(title, artist, youtube_id or "", hashes)
        print(f"✓ Song added to database with ID: {song_id}")
        return {"song_id": song_id, "hashes": hashes}

    matches = db.find_matches(hashes)
    print(f"✓ Found {len(matches)} matches")
    return {"matches": matches, "hashes": hashes}


if __name__ == "__main__":
    import uvicorn

    print("Starting Shazam Audio Fingerprinting API...")
    print("API Documentation available at: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
