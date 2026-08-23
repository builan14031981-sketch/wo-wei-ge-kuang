import os
import re
import sys
import json
import time
import shutil
import threading
import urllib.parse
import requests
import subprocess
from concurrent.futures import ThreadPoolExecutor

FFMPEG_CANDIDATES = ["ffmpeg", "ffmpeg.exe"]

def get_ffmpeg_path():
    # 打包内嵌优先：PyInstaller 的 _MEIPASS 或同目录下的 ffmpeg
    search_dirs = []
    if getattr(sys, '_MEIPASS', None):
        search_dirs.append(sys._MEIPASS)
    search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    search_dirs.append(os.getcwd())
    for base in search_dirs:
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    for p in FFMPEG_CANDIDATES:
        if os.path.exists(p):
            return p
        if shutil.which(p):
            return shutil.which(p)
    return "ffmpeg"

FFMPEG_PATH = get_ffmpeg_path()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
}

def sanitize_filename(name):
    if not name:
        return "未知"
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\r', '\n', '\t']:
        name = name.replace(ch, '_')
    return name.strip()

class MusicEngine:
    def __init__(self, output_dir=None, bitrate=320):
        if not output_dir:
            self.output_dir = os.path.join(os.path.expanduser("~"), "Music", "我为歌狂Downloads")
        else:
            self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.sources = ['netease', 'tencent', 'kugou', 'kuwo', 'bilibili']
        self.bitrate = bitrate
        self._dl_lock = threading.Lock()
        self._downloading = set()

    def search(self, keyword, source='all', count=15):
        keyword = keyword.strip()
        if not keyword:
            return []
            
        results = []
        target_sources = self.sources if source == 'all' else [source]
        
        for src in target_sources:
            try:
                name = urllib.parse.quote(keyword)
                url = f"https://music-api.gdstudio.xyz/api.php?types=search&count={count}&source={src}&pages=1&name={name}"
                r = requests.get(url, headers=HEADERS, timeout=5)
                r.raise_for_status()
                items = r.json()
                if isinstance(items, list):
                    for item in items:
                        title = item.get('name', '')
                        artists = item.get('artist', [])
                        art_str = ' / '.join(artists) if isinstance(artists, list) else str(artists)
                        album = item.get('album', '')
                        
                        results.append({
                            'id': item.get('url_id') or item.get('id'),
                            'title': title,
                            'artist': art_str,
                            'album': album,
                            'source': src,
                            'pic_id': item.get('pic_id', ''),
                            'raw': item
                        })
            except Exception:
                continue
                
        # Deduplicate results by (title, artist, source)
        seen = set()
        unique = []
        for r in results:
            key = (r['title'].lower().strip(), r['artist'].lower().strip(), r['source'])
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    def get_audio_url(self, song_id, source):
        try:
            url = f"https://music-api.gdstudio.xyz/api.php?types=url&id={urllib.parse.quote(str(song_id))}&source={source}"
            res = requests.get(url, headers=HEADERS, timeout=6)
            res.raise_for_status()
            res = res.json()
            audio_url = res.get('url')
            if audio_url and audio_url.startswith('http'):
                return audio_url, res.get('size', 0), res.get('br', 320)
        except Exception:
            pass
        return None, 0, 0

    def parse_playlist_url(self, playlist_url):
        playlist_url = playlist_url.strip()
        if 'kugou.com' in playlist_url:
            return self._parse_kugou_playlist(playlist_url)
        if 'music.163.com' in playlist_url:
            return self._parse_netease_playlist(playlist_url)
        return {'error': '暂不支持的歌单链接（目前仅支持酷狗与网易云公开歌单）'}

    def _parse_kugou_playlist(self, kugou_url):
        try:
            r = requests.get(kugou_url, allow_redirects=True, headers=HEADERS, timeout=12)
            html = r.text
            start_tag = "var dataFromSmarty = "
            idx = html.find(start_tag)
            if idx == -1:
                return []
            content = html[idx + len(start_tag):]
            songs_data, _ = json.JSONDecoder().raw_decode(content)
            
            song_list = []
            for s in songs_data:
                title = s.get('song_name') or s.get('filename') or s.get('audio_name') or ''
                artist = s.get('author_name') or s.get('singername') or ''
                duration = int(s.get('timelength', 0) or 0) // 1000
                title = title.replace('&nbsp;', ' ').strip()
                artist = artist.replace('&nbsp;', ' ').strip()
                if title:
                    song_list.append({
                        'title': title,
                        'artist': artist,
                        'duration': duration,
                        'hash': s.get('hash', ''),
                        'album_id': s.get('album_id', '')
                    })
            return song_list
        except Exception:
            return []

    def _parse_netease_playlist(self, netease_url):
        try:
            m = re.search(r'id=(\d+)', netease_url)
            if not m:
                return []
            pid = m.group(1)
            req_headers = dict(HEADERS)
            req_headers['Referer'] = 'https://music.163.com/'
            api = f"https://music.163.com/api/playlist/detail?id={pid}"
            r = requests.get(api, headers=req_headers, timeout=12)
            r.raise_for_status()
            data = r.json()
            if data.get('code') in (20001, 301) or data.get('msg'):
                return {'error': '该网易云歌单需要登录后才能读取（属于“我的”/私有歌单）。当前版本暂不支持，请改用公开歌单链接，或将歌单设为公开后重试。'}
            result = data.get('result') or data.get('playlist') or {}
            tracks = result.get('tracks') or []
            song_list = []
            for t in tracks:
                title = t.get('name', '')
                artists = t.get('artists') or []
                artist = ' / '.join(a.get('name', '') for a in artists) if artists else ''
                duration = int(t.get('duration', 0) or 0) // 1000
                if title:
                    song_list.append({
                        'title': title.strip(),
                        'artist': artist.strip(),
                        'duration': duration,
                        'hash': '',
                        'album_id': ''
                    })
            return song_list
        except Exception:
            return []

    def auto_match_and_download(self, title, artist, progress_callback=None, is_stopped=None):
        def _stopped():
            return bool(is_stopped and is_stopped())

        clean_artist = sanitize_filename(artist) or "未知歌手"
        clean_title = sanitize_filename(title) or "未知歌曲"
        target_name = f"{clean_artist} - {clean_title}.mp3"
        target_path = os.path.join(self.output_dir, target_name)

        if os.path.exists(target_path) and os.path.getsize(target_path) > 100000:
            if progress_callback:
                progress_callback(100, "已存在", target_path)
            return True, target_path

        if _stopped():
            return False, "已停止"

        if progress_callback:
            progress_callback(10, "正在全网匹配最佳音源...", None)

        found_audio = None
        q = f"{title} {artist}".strip()
        q_enc = urllib.parse.quote(q)

        for src in self.sources:
            if _stopped():
                return False, "已停止"
            try:
                url = f"https://music-api.gdstudio.xyz/api.php?types=search&count=5&source={src}&pages=1&name={q_enc}"
                items = requests.get(url, headers=HEADERS, timeout=5)
                items.raise_for_status()
                items = items.json()
                if isinstance(items, list) and len(items) > 0:
                    for item in items:
                        name = item.get('name', '')
                        if '伴奏' in name and '伴奏' not in title:
                            continue
                        if '片段' in name or '铃声' in name:
                            continue
                        uid = item.get('url_id') or item.get('id')
                        audio_url, size, br = self.get_audio_url(uid, src)
                        if audio_url and (size > 150000 or src == 'bilibili'):
                            found_audio = (audio_url, src, item.get('name', title))
                            break
                if found_audio:
                    break
            except Exception:
                continue

        if not found_audio:
            # Fallback by title only
            for src in ['netease', 'tencent', 'kuwo']:
                if _stopped():
                    return False, "已停止"
                try:
                    url = f"https://music-api.gdstudio.xyz/api.php?types=search&count=3&source={src}&pages=1&name={urllib.parse.quote(title)}"
                    items = requests.get(url, headers=HEADERS, timeout=5)
                    items.raise_for_status()
                    items = items.json()
                    if isinstance(items, list) and len(items) > 0:
                        for item in items:
                            uid = item.get('url_id') or item.get('id')
                            audio_url, size, br = self.get_audio_url(uid, src)
                            if audio_url and size > 150000:
                                found_audio = (audio_url, src, item.get('name', title))
                                break
                    if found_audio:
                        break
                except Exception:
                    continue

        if not found_audio:
            if progress_callback:
                progress_callback(-1, "未找到可用音源", None)
            return False, "未找到可用音源"

        if _stopped():
            return False, "已停止"

        audio_url, src, matched_name = found_audio
        if progress_callback:
            progress_callback(40, f"正在下载音频流 [{src}]...", None)

        # 防止同一文件被多个并发任务同时写入而损坏
        with self._dl_lock:
            if target_path in self._downloading:
                if progress_callback:
                    progress_callback(100, "已存在", target_path)
                return True, target_path
            self._downloading.add(target_path)
        try:
            temp_raw = os.path.join(self.output_dir, f"temp_{int(time.time()*1000)}.raw")
            req_headers = dict(HEADERS)
            if 'bilivideo' in audio_url:
                req_headers['Referer'] = 'https://www.bilibili.com'

            r_dl = requests.get(audio_url, headers=req_headers, stream=True, timeout=30)
            if r_dl.status_code != 200:
                if progress_callback:
                    progress_callback(-1, "流媒体下载失败", None)
                return False, "下载流失败"

            total_dl = 0
            with open(temp_raw, 'wb') as f:
                for chunk in r_dl.iter_content(chunk_size=128*1024):
                    if _stopped():
                        f.close()
                        if os.path.exists(temp_raw):
                            try:
                                os.remove(temp_raw)
                            except Exception:
                                pass
                        if progress_callback:
                            progress_callback(-1, "已停止", None)
                        return False, "已停止"
                    if chunk:
                        f.write(chunk)
                        total_dl += len(chunk)

            if progress_callback:
                progress_callback(80, "正在转码 320K MP3 并写入标签...", None)

            cmd = [
                FFMPEG_PATH,
                '-y',
                '-i', temp_raw,
                '-vn',
                '-b:a', f'{self.bitrate}k',
                '-metadata', f'title={title}',
                '-metadata', f'artist={artist}',
                target_path
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(temp_raw):
                os.remove(temp_raw)

            if os.path.exists(target_path) and os.path.getsize(target_path) > 80000:
                if progress_callback:
                    progress_callback(100, "下载并转码完成", target_path)
                return True, target_path
            else:
                if progress_callback:
                    progress_callback(-1, "转码校验未通过", None)
                return False, "转码失败"
        except Exception as e:
            if progress_callback:
                progress_callback(-1, f"下载出错: {str(e)}", None)
            return False, str(e)
        finally:
            with self._dl_lock:
                self._downloading.discard(target_path)
