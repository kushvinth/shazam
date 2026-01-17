import requests
import yt_dlp
import ffmpeg
import os
from fastapi import FastAPI

URL = "https://itunes.apple.com/search"

app = FastAPI(title="Ingession API")


@app.get("/download")
def download_mp3(NAME: str):
    if NAME:
        params = {
            "term": NAME,
            "media": "music",
            "entity": "song",
            "limit": 1,
            # "js_runtimes": "/usr/local/bin/node" ## Installed Demo with Brew
        }
        response = requests.get(URL, params=params)
        data = response.json()

        # https://stackoverflow.com/questions/73516823/using-yt-dlp-in-a-python-script-how-do-i-download-a-specific-section-of-a-video
        # https://stackoverflow.com/questions/74157935/getting-the-file-name-of-downloaded-video-using-yt-dlp#:~:text=import%20subprocess%20someFileType%20=%20subprocess.getoutput,4214%209

        ytd_params = {
            "format": "bestaudio/best",
            "outtmpl": f"./data/%(title)s.%(ext)s",
        }
        with yt_dlp.YoutubeDL(ytd_params) as ydl:  # type: ignore
            for i in data["results"]:
                query = f"{i['artistName']} - {i['trackName']} official audio"
                ydl.download([f"ytsearch1: {query}"])

        for i in os.listdir("./data"):
            file_path = os.path.join("./data", i)
            # print("-" * 30)
            # print(i)
            if not i.endswith(".mp3"):
                print("-" * 30)
                ffmpeg.input(file_path).output(
                    os.path.splitext(file_path)[0] + ".wav", audio_bitrate="192k"
                ).run(overwrite_output=True)
                os.remove("./data/" + i)
