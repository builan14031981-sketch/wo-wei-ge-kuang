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

# Windows 下抑制 ffmpeg 弹出的黑窗口（其他平台该常量不存在，用 0 兜底）
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

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

# 规范化音源键（引擎内部统一使用这些 key）
CANONICAL_SOURCES = ['netease', 'tencent', 'kugou', 'kuwo', 'migu', 'bilibili', 'douyin', 'ximalaya']
# 匹配时的优先顺序（越靠前越优先）
SEARCH_ORDER = ['netease', 'tencent', 'kugou', 'kuwo', 'migu', 'bilibili', 'douyin', 'ximalaya']


def sanitize_filename(name):
    if not name:
        return "未知"
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\r', '\n', '\t']:
        name = name.replace(ch, '_')
    return name.strip()


# ----------------- 音源 Provider 抽象层（多接口容错） -----------------

class MusicProvider:
    name = "base"
    # canonical source -> 该 provider 实际使用的 source 参数名
    source_map = {}

    def search(self, keyword, source, count):
        """返回规范化结果列表：[{id,title,artist,album,source,pic_id,provider,raw}]"""
        raise NotImplementedError

    def resolve(self, item):
        """根据搜索结果解析出可下载音频直链，返回 (url, size, br)"""
        raise NotImplementedError

    def parse_playlist(self, playlist_url):
        """解析歌单链接，成功返回列表，不支持返回 None，出错也可返回 None"""
        return None


class GdstudioProvider(MusicProvider):
    name = "gdstudio"
    base = "https://music-api.gdstudio.xyz/api.php"
    source_map = {
        'netease': 'netease', 'tencent': 'tencent', 'kugou': 'kugou',
        'kuwo': 'kuwo', 'bilibili': 'bilibili'
    }

    def _norm(self, it, source):
        artists = it.get('artist', [])
        art = ' / '.join(artists) if isinstance(artists, list) else str(artists)
        return {
            'id': it.get('url_id') or it.get('id'),
            'title': it.get('name', ''),
            'artist': art,
            'album': it.get('album', ''),
            'source': source,
            'pic_id': it.get('pic_id', ''),
            'provider': self.name,
            'raw': it
        }

    def search(self, keyword, source, count):
        name = urllib.parse.quote(keyword)
        url = f"{self.base}?types=search&count={count}&source={source}&pages=1&name={name}"
        r = requests.get(url, headers=HEADERS, timeout=5)
        r.raise_for_status()
        items = r.json()
        out = []
        if isinstance(items, list):
            for it in items:
                out.append(self._norm(it, source))
        return out

    def get_audio_url(self, song_id, source):
        try:
            url = f"{self.base}?types=url&id={urllib.parse.quote(str(song_id))}&source={source}"
            res = requests.get(url, headers=HEADERS, timeout=6)
            res.raise_for_status()
            res = res.json()
            audio_url = res.get('url')
            if audio_url and audio_url.startswith('http'):
                return audio_url, res.get('size', 0), res.get('br', 320)
        except Exception:
            pass
        return None, 0, 0

    def resolve(self, item):
        uid = item.get('id') or (item.get('raw') or {}).get('url_id') or (item.get('raw') or {}).get('id')
        return self.get_audio_url(uid, item['source'])

    def parse_playlist(self, playlist_url):
        if 'kugou.com' in playlist_url:
            return self._parse_kugou_playlist(playlist_url)
        if 'music.163.com' in playlist_url:
            return self._parse_netease_playlist(playlist_url)
        return None

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


class MetingProvider(MusicProvider):
    """Meting 系聚合接口：覆盖 网易云 / QQ音乐 / 酷狗 / 酷我（抖音/喜马拉雅/咪咕需其它接口）"""
    name = "meting"
    # 多个公共实例，按顺序尝试，命中后缓存
    bases = [
        "https://api.injahow.cn/meting/",
        "https://meting.api.origya.com/",
        "https://api.cenguigui.cn/api/meting/",
        "https://music.cyrilstudio.fr/"
    ]
    source_map = {
        'netease': 'netease', 'tencent': 'tencent', 'kugou': 'kugou', 'kuwo': 'kuwo'
    }
    _working_base = None

    def _base(self):
        return self._working_base or self.bases[0]

    def _norm(self, it, source):
        artist = it.get('artist')
        if isinstance(artist, list):
            artist = ' / '.join(artist)
        elif not isinstance(artist, str):
            artist = str(artist or '')
        return {
            'id': it.get('id'),
            'title': it.get('name', ''),
            'artist': artist,
            'album': it.get('album', ''),
            'source': source,
            'pic_id': it.get('pic', ''),
            'provider': self.name,
            'raw': it
        }

    def _do_get(self, url):
        try:
            r = requests.get(url, headers=HEADERS, timeout=6)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def search(self, keyword, source, count):
        base = self._base()
        main_url = f"{base}?type=search&server={source}&msg={urllib.parse.quote(keyword)}&limit={count}"
        items = self._do_get(main_url)
        # 若当前实例返回错误，逐一尝试其它实例
        if not isinstance(items, list):
            for b in self.bases:
                if b == base:
                    continue
                j = self._do_get(f"{b}?type=search&server={source}&msg={urllib.parse.quote(keyword)}&limit={count}")
                if isinstance(j, list):
                    self._working_base = b
                    items = j
                    break
        out = []
        if isinstance(items, list):
            for it in items:
                out.append(self._norm(it, source))
        return out

    def resolve(self, item):
        src = item['source']
        uid = item.get('id')
        if not uid:
            return None, 0, 0
        base = self._base()
        j = self._do_get(f"{base}?type=url&id={urllib.parse.quote(str(uid))}&server={src}")
        if isinstance(j, dict):
            au = j.get('url')
        elif isinstance(j, str):
            au = j
        else:
            au = None
        if au and str(au).startswith('http'):
            return au, 0, 320
        # 当前实例失败则换实例重试
        for b in self.bases:
            if b == base:
                continue
            j = self._do_get(f"{b}?type=url&id={urllib.parse.quote(str(uid))}&server={src}")
            if isinstance(j, dict) and j.get('url'):
                self._working_base = b
                return j.get('url'), 0, 320
        return None, 0, 0


class MusicEngine:
    def __init__(self, output_dir=None, bitrate=320):
        if not output_dir:
            self.output_dir = os.path.join(os.path.expanduser("~"), "Music", "我为歌狂Downloads")
        else:
            self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.sources = list(CANONICAL_SOURCES)
        self.bitrate = bitrate
        self._dl_lock = threading.Lock()
        self._downloading = set()
        # Provider 顺序：优先 Meting（覆盖更广），gdstudio 兜底
        self.providers = [MetingProvider(), GdstudioProvider()]

    def _provider_by_name(self, name):
        for p in self.providers:
            if p.name == name:
                return p
        return None

    # ---------------- 聚合搜索 ----------------
    def search(self, keyword, source='all', count=15):
        keyword = keyword.strip()
        if not keyword:
            return []

        results = []
        target_sources = self.sources if source == 'all' else [source]

        for src in target_sources:
            for prov in self.providers:
                mapped = prov.source_map.get(src)
                if not mapped:
                    continue
                try:
                    items = prov.search(keyword, mapped, count)
                    for it in items:
                        results.append(it)
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
        for prov in self.providers:
            mapped = prov.source_map.get(source)
            if not mapped:
                continue
            try:
                url, size, br = prov.resolve({'id': song_id, 'source': source, 'provider': prov.name})
                if url:
                    return url, size, br
            except Exception:
                continue
        return None, 0, 0

    def resolve(self, item):
        prov = self._provider_by_name(item.get('provider'))
        if not prov:
            return None, 0, 0
        return prov.resolve(item)

    def _find_audio(self, query, count=5):
        """按优先级跨 Provider 查找首个可下载音源，返回 (url, source, name) 或 None"""
        for canon in SEARCH_ORDER:
            for prov in self.providers:
                mapped = prov.source_map.get(canon)
                if not mapped:
                    continue
                try:
                    items = prov.search(query, mapped, count)
                except Exception:
                    continue
                for it in items:
                    name = it.get('title', '')
                    if '伴奏' in name and '伴奏' not in query:
                        continue
                    if '片段' in name or '铃声' in name:
                        continue
                    audio_url, size, br = self.resolve(it)
                    if audio_url and (size > 150000 or canon == 'bilibili'):
                        return audio_url, canon, it
        return None

    # ---------------- 歌单解析 ----------------
    def parse_playlist_url(self, playlist_url):
        playlist_url = playlist_url.strip()
        # 已知平台优先走专属解析（网易云 / 酷狗）
        for prov in self.providers:
            try:
                res = prov.parse_playlist(playlist_url)
            except Exception:
                continue
            if res is None:
                continue
            if isinstance(res, dict) and res.get('error'):
                return res
            if isinstance(res, list):
                return res
        # 汽水音乐 / 抖音：仅能读到歌单元数据，曲目在签名接口后，识别歌单名并引导粘贴
        if self._is_qishui_link(playlist_url):
            return self._parse_qishui_playlist(playlist_url)
        # 其它平台（喜马拉雅等）尽力而为抓取歌名
        songs = self._best_effort_extract_names(playlist_url)
        if songs:
            return songs
        return {'error': '暂无法自动解析该链接（可能需登录或平台限制）。请直接把歌单里的歌名粘贴到「粘贴歌单文本」框导入。'}

    @staticmethod
    def _is_qishui_link(url):
        return 'qishui.douyin' in url or ('douyin.com' in url and '/s/' in url)

    @staticmethod
    def _unescape_json_str(s):
        # 仅还原 JSON 字符串里的 \/ \" \\ 与 \uXXXX 转义，保留已解码的中文（避免 unicode_escape 把 UTF-8 二次损坏）
        s = s.replace('\\/', '/').replace('\\"', '"').replace('\\\\', '\\')
        s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
        return s

    def _parse_qishui_playlist(self, url):
        """汽水音乐/抖音歌单：从 SSR 的 _ROUTER_DATA 中直接提取曲目列表（无需签名）。"""
        try:
            r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=12)
            html = r.text or ""
            return self._extract_qishui_medias(html)
        except Exception:
            return {'error': '汽水音乐/抖音链接解析失败（网络或页面异常）。请直接把歌单里的歌名粘贴到「粘贴歌单文本」框导入。'}

    def _extract_qishui_medias(self, html):
        try:
            idx = html.index('_ROUTER_DATA')
        except ValueError:
            return {'error': '未识别到汽水音乐页面数据。请直接把歌单里的歌名粘贴到「粘贴歌单文本」框导入。'}
        start = html.index('{', idx)
        try:
            obj, _ = json.JSONDecoder().raw_decode(html, start)
        except Exception:
            return {'error': '汽水音乐页面数据解析失败。请直接把歌单里的歌名粘贴到「粘贴歌单文本」框导入。'}
        try:
            page = obj['loaderData']['playlist_page']
        except (KeyError, TypeError):
            return {'error': '未找到歌单曲目数据。请直接把歌单里的歌名粘贴到「粘贴歌单文本」框导入。'}
        medias = page.get('medias') or []
        songs = []
        for m in medias:
            if not isinstance(m, dict) or m.get('type') != 'track':
                continue
            track = (m.get('entity') or {}).get('track') or {}
            title = (track.get('name') or '').strip()
            if not title:
                continue
            artists = track.get('artists') or []
            artist = ' / '.join(a.get('name', '') for a in artists if isinstance(a, dict) and a.get('name'))
            dur = int(track.get('duration') or 0)
            if dur > 100000:  # 毫秒 -> 秒
                dur = dur // 1000
            songs.append({
                'title': title,
                'artist': artist,
                'duration': dur,
                'hash': '',
                'album_id': ''
            })
        if not songs:
            return {'error': '该汽水音乐歌单未包含可识别曲目。请直接把歌单里的歌名粘贴到「粘贴歌单文本」框导入。'}
        return songs

    def _best_effort_extract_names(self, playlist_url):
        """尽力而为：抓取页面并从 JSON/文本中提取可能的歌名。过滤乱码/视频标题，要求 ≥2 条才接受。"""
        try:
            req_headers = dict(HEADERS)
            req_headers['Accept'] = 'text/html,application/json'
            r = requests.get(playlist_url, headers=req_headers, allow_redirects=True, timeout=10)
            text = r.text or ""
            raw = []
            for m in re.finditer(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
                t = self._unescape_json_str(m.group(1)).strip()
                raw.append(t)
            titles = []
            for t in raw:
                if not t:
                    continue
                if '\ufffd' in t:          # 乱码
                    continue
                if '#' in t:              # 视频标题/话题
                    continue
                if 'http' in t:
                    continue
                if not (2 <= len(t) <= 60):  # 异常长度
                    continue
                titles.append(t)
            seen = set()
            uniq = []
            for t in titles:
                if t not in seen:
                    seen.add(t)
                    uniq.append(t)
            if len(uniq) < 2:
                return []
            songs = []
            for t in uniq[:200]:
                artist = ''
                title = t
                for sep in [' - ', ' – ', ' — ', '：', ' : ', ' / ']:
                    if sep in title:
                        parts = title.split(sep, 1)
                        artist = parts[0].strip()
                        title = parts[1].strip()
                        break
                title = title.strip('"\' \t')
                artist = artist.strip('"\' \t')
                if title:
                    songs.append({
                        'title': title, 'artist': artist,
                        'duration': 0, 'hash': '', 'album_id': ''
                    })
            return songs
        except Exception:
            return []

    def parse_text_playlist(self, text):
        """解析用户粘贴的歌单文本为统一歌曲结构。每行一首，可写「歌手 - 歌名」或只写歌名。"""
        songs = []
        seen = set()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # 去掉序号前缀：1. 1、1) 1、
            line = re.sub(r'^\d+[.、)]\s*', '', line)
            artist = ''
            title = line
            for sep in [' - ', ' – ', ' — ', '：', ' : ', ' / ', ' -']:
                if sep in title:
                    parts = title.split(sep, 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                    break
            title = title.strip('"\' \t')
            artist = artist.strip('"\' \t')
            if not title:
                continue
            key = (title.lower(), artist.lower())
            if key in seen:
                continue
            seen.add(key)
            songs.append({
                'title': title, 'artist': artist,
                'duration': 0, 'hash': '', 'album_id': ''
            })
        return songs

    # ---------------- 自动匹配并下载 ----------------
    def auto_match_and_download(self, title, artist, progress_callback=None, is_stopped=None):
        def _stopped():
            return bool(is_stopped and is_stopped())

        # 用户原始输入对应的文件名（用于快速去重：相同输入不再重复下载）
        raw_artist = sanitize_filename(artist) or "未知歌手"
        raw_title = sanitize_filename(title) or "未知歌曲"
        raw_path = os.path.join(self.output_dir, f"{raw_artist} - {raw_title}.mp3")
        if os.path.exists(raw_path) and os.path.getsize(raw_path) > 100000:
            if progress_callback:
                progress_callback(100, "已存在", raw_path)
            return True, raw_path

        if _stopped():
            return False, "已停止"

        if progress_callback:
            progress_callback(10, "正在全网匹配最佳音源...", None)

        found_audio = self._find_audio(f"{title} {artist}".strip(), 5)

        if not found_audio:
            # Fallback by title only
            found_audio = self._find_audio(title, 3)

        if not found_audio:
            if progress_callback:
                progress_callback(-1, "未找到可用音源", None)
            return False, "未找到可用音源"

        if _stopped():
            return False, "已停止"

        audio_url, src, _ = found_audio
        # 文件名与标签以用户填写为准（可预测、不会因错误匹配而张冠李戴）；缺失时仅用占位
        clean_artist = sanitize_filename(artist) or "未知歌手"
        clean_title = sanitize_filename(title) or "未知歌曲"
        target_name = f"{clean_artist} - {clean_title}.mp3"
        target_path = os.path.join(self.output_dir, target_name)

        if os.path.exists(target_path) and os.path.getsize(target_path) > 100000:
            if progress_callback:
                progress_callback(100, "已存在", target_path)
            return True, target_path

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
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=CREATE_NO_WINDOW)
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

    # ---------------- 启动音源自检 ----------------
    def get_available_sources(self, probe_keyword="晴天"):
        """并发探测每个规范音源是否有可用 Provider，返回可用音源列表"""
        def probe(canon):
            for prov in self.providers:
                mapped = prov.source_map.get(canon)
                if not mapped:
                    continue
                try:
                    items = prov.search(probe_keyword, mapped, 1)
                    if items:
                        return True
                except Exception:
                    continue
            return False

        avail = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(probe, c): c for c in self.sources}
            for f in futures:
                c = futures[f]
                try:
                    avail[c] = f.result()
                except Exception:
                    avail[c] = False
        return [c for c in self.sources if avail.get(c)]
