import os
import re
import tempfile
import subprocess
import requests
import yt_dlp
from flask import Flask, render_template, request, Response

app = Flask(__name__)

BASE_YDL_OPTS = {
    'format': '18/best[ext=mp4]/best',
    'quiet': True,
    'no_warnings': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']
        }
    }
}

def is_legacy_ie():
    ua = request.headers.get('User-Agent', '')
    if re.search(r'MSIE [1-8]\.', ua):
        return True
    return False

def is_legacy_mobile():
    ua = request.headers.get('User-Agent', '')
    # Rileva Android da 1.0 a 2.3.6 e dispositivi Symbian/Nokia d'epoca (N95, N8, Series60)
    if re.search(r'Android ([1]|2\.[0-3])|SymbianOS|Series60|Symbian3|Nokia', ua, re.IGNORECASE):
        return True
    return False

def get_youtube_info(video_id):
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(BASE_YDL_OPTS) as ydl:
        return ydl.extract_info(youtube_url, download=False)

@app.after_request
def skip_localtonet_warning(response):
    response.headers['localtonet-skip-warning'] = 'true'
    return response

@app.route('/')
def index():
    query = request.args.get('q', '')
    video_id = request.args.get('v', '')
    legacy_browser = is_legacy_ie()
    legacy_mobile = is_legacy_mobile()
    
    if video_id:
        try:
            info = get_youtube_info(video_id)
            video_data = {
                'id': video_id,
                'title': info.get('title', 'Video senza titolo'),
                'uploader': info.get('uploader', 'Canale Sconosciuto')
            }
            
            # Se è un mobile d'epoca (Android 1.x-2.3.x / Nokia Symbian), inviamo lo stream MP4 144p
            if legacy_mobile:
                stream_url = f"/stream_android/video.mp4?v={video_id}"
            else:
                stream_url = info.get('url', '')

            return render_template('index.html', video=video_data, stream_url=stream_url, is_legacy_ie=legacy_browser)
        except Exception as e:
            return render_template('index.html', error=f"Flusso non disponibile: {e}", is_legacy_ie=legacy_browser)

    elif query:
        try:
            search_opts = {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
                'extractor_args': BASE_YDL_OPTS['extractor_args']
            }
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                search_results = ydl.extract_info(f"ytsearch5:{query}", download=False)
                items = []
                if 'entries' in search_results:
                    for entry in search_results['entries']:
                        if entry:
                            items.append({
                                'title': entry.get('title'),
                                'url': f"?v={entry.get('id')}",
                                'thumbnail': f"https://i.ytimg.com/vi/{entry.get('id')}/hqdefault.jpg",
                                'uploaderName': entry.get('uploader', 'Canale')
                            })
            return render_template('index.html', results=items, query=query, is_legacy_ie=legacy_browser)
        except Exception as e:
            return render_template('index.html', error=f"Errore: {e}", query=query, is_legacy_ie=legacy_browser)

    return render_template('index.html', is_legacy_ie=legacy_browser)

@app.route('/stream_legacy/video.avi')
def stream_legacy():
    video_id = request.args.get('v', '')
    if not video_id:
        return "ID Video mancante", 400

    try:
        temp_dir = tempfile.gettempdir()
        temp_mp4_path = os.path.join(temp_dir, f"raw_{video_id}.mp4")
        temp_avi_path = os.path.join(temp_dir, f"legacy_{video_id}.mpg")

        if not os.path.exists(temp_avi_path):
            if not os.path.exists(temp_mp4_path):
                ydl_opts = {
                    'format': '18/best[ext=mp4]/best',
                    'outtmpl': temp_mp4_path,
                    'quiet': True,
                    'no_warnings': True,
                    'extractor_args': BASE_YDL_OPTS['extractor_args']
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

            # Transcodifica MPEG-1 per IE6 / Windows 95/98 (320x240, 25fps)
            ffmpeg_cmd = [
                'ffmpeg',
                '-y',
                '-i', temp_mp4_path,
                '-f', 'mpeg',
                '-vcodec', 'mpeg1video',
                '-r', '25',
                '-b:v', '250k',
                '-maxrate', '300k',
                '-bufsize', '40k',
                '-acodec', 'mp2',
                '-ar', '22050',
                '-ac', '1',
                '-ab', '64k',
                '-s', '320x240',
                temp_avi_path
            ]
            subprocess.run(ffmpeg_cmd, check=True)

            if os.path.exists(temp_mp4_path):
                os.remove(temp_mp4_path)

        def generate():
            with open(temp_avi_path, 'rb') as f:
                while chunk := f.read(16384):
                    yield chunk

        file_size = os.path.getsize(temp_avi_path)
        response = Response(generate(), mimetype='video/mpeg')
        response.headers['Content-Length'] = str(file_size)
        response.headers['Accept-Ranges'] = 'bytes'
        return response

    except Exception as e:
        print(f"ERRORE STREAM LEGACY: {e}")
        return f"Errore durante la transcodifica legacy: {e}", 500

@app.route('/stream_android/video.mp4')
def stream_android():
    video_id = request.args.get('v', '')
    if not video_id:
        return "ID Video mancante", 400

    try:
        temp_dir = tempfile.gettempdir()
        temp_raw_path = os.path.join(temp_dir, f"raw_{video_id}.mp4")
        temp_android_path = os.path.join(temp_dir, f"android144p_{video_id}.mp4")

        if not os.path.exists(temp_android_path):
            if not os.path.exists(temp_raw_path):
                ydl_opts = {
                    'format': '18/best[ext=mp4]/best',
                    'outtmpl': temp_raw_path,
                    'quiet': True,
                    'no_warnings': True,
                    'extractor_args': BASE_YDL_OPTS['extractor_args']
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

            # Transcodifica MP4 H.264 Baseline 144p per Android legacy e Nokia/Symbian
            ffmpeg_cmd = [
                'ffmpeg',
                '-y',
                '-i', temp_raw_path,
                '-vcodec', 'libx264',
                '-profile:v', 'baseline',  # Profilo universale per vecchi chip ARM
                '-level', '3.0',
                '-s', '256x144',           # Risoluzione 144p
                '-b:v', '150k',            # Low bitrate
                '-r', '15',                # 15 fps
                '-acodec', 'aac',
                '-ar', '22050',
                '-ac', '1',
                '-ab', '48k',
                '-movflags', '+faststart', # Streaming immediato (moov atom all'inizio)
                temp_android_path
            ]
            subprocess.run(ffmpeg_cmd, check=True)

            if os.path.exists(temp_raw_path):
                os.remove(temp_raw_path)

        def generate():
            with open(temp_android_path, 'rb') as f:
                while chunk := f.read(16384):
                    yield chunk

        file_size = os.path.getsize(temp_android_path)
        response = Response(generate(), mimetype='video/mp4')
        response.headers['Content-Length'] = str(file_size)
        response.headers['Accept-Ranges'] = 'bytes'
        return response

    except Exception as e:
        print(f"ERRORE STREAM MOBILE: {e}")
        return f"Errore durante la transcodifica mobile: {e}", 500

@app.route('/download')
def download_video():
    video_id = request.args.get('v', '')
    if not video_id:
        return "ID Video mancante", 400
        
    try:
        info = get_youtube_info(video_id)
        real_url = info.get('url', '')
        title = info.get('title', 'video').replace(' ', '_')
        headers = info.get('http_headers', {})

        req = requests.get(real_url, headers=headers, stream=True)
        response = Response(req.iter_content(chunk_size=1024*1024), content_type='application/octet-stream')
        response.headers['Content-Disposition'] = f'attachment; filename="{title}.mp4"'
        return response
    except Exception as e:
        return f"Errore durante il reindirizzamento del download: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)