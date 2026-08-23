import os
import sys
import time
import subprocess
import ctypes
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QPoint, QSize, QUrl
)
from PyQt6.QtGui import QIcon, QFont, QColor, QPixmap, QDesktopServices, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QProgressBar,
    QComboBox, QFrame, QMessageBox, QAbstractItemView,
    QCheckBox, QMenu
)
import qtawesome as qta

from core_engine import MusicEngine, sanitize_filename
from styles import QSS_STYLE

# ----------------- 后台工作线程定义 (支持原子级安全打断与停止) -----------------

class SearchThread(QThread):
    results_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, engine, keyword, source):
        super().__init__()
        self.engine = engine
        self.keyword = keyword
        self.source = source

    def run(self):
        try:
            results = self.engine.search(self.keyword, self.source, count=30)
            self.results_signal.emit(results)
        except Exception as e:
            self.error_signal.emit(str(e))

class PlaylistParseThread(QThread):
    songs_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, engine, playlist_url):
        super().__init__()
        self.engine = engine
        self.playlist_url = playlist_url

    def run(self):
        try:
            songs = self.engine.parse_playlist_url(self.playlist_url)
            self.songs_signal.emit(songs)
        except Exception as e:
            self.error_signal.emit(str(e))

class SingleDownloadThread(QThread):
    progress_signal = pyqtSignal(int, str, str)

    def __init__(self, engine, title, artist):
        super().__init__()
        self.engine = engine
        self.title = title
        self.artist = artist
        self.is_stopped = False

    def run(self):
        def cb(prog, text, path):
            if not self.is_stopped:
                self.progress_signal.emit(prog, text, path or "")
        self.engine.auto_match_and_download(self.title, self.artist, progress_callback=cb, is_stopped=lambda: self.is_stopped)
        if self.is_stopped:
            self.progress_signal.emit(-1, "已停止", "")

    def stop(self):
        self.is_stopped = True

class BatchDownloadThread(QThread):
    song_progress_signal = pyqtSignal(int, int, str, str, str) # idx, total, song_title, status, filepath
    all_done_signal = pyqtSignal(int, int, bool) # success_count, fail_count, was_cancelled

    def __init__(self, engine, songs_list, max_workers=12):
        super().__init__()
        self.engine = engine
        self.songs_list = songs_list
        self.max_workers = max_workers
        self.is_running = True

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        total = len(self.songs_list)
        success_count = 0
        fail_count = 0

        def download_worker(idx, song):
            if not self.is_running:
                return False, ""
            title = song.get('title', '')
            artist = song.get('artist', '')
            self.song_progress_signal.emit(idx, total, f"{artist} - {title}", "下载中...", "")
            ok, res = self.engine.auto_match_and_download(title, artist, is_stopped=lambda: not self.is_running)
            status_text = "完成" if ok else (res if isinstance(res, str) and res else "失败")
            file_path = res if ok else ""
            self.song_progress_signal.emit(idx, total, f"{artist} - {title}", status_text, file_path)
            return ok, file_path

        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        try:
            futures = [executor.submit(download_worker, i, s) for i, s in enumerate(self.songs_list, 1)]
            for f in as_completed(futures):
                if not self.is_running:
                    break
                try:
                    ok, _ = f.result()
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1
                except:
                    fail_count += 1

            if not self.is_running:
                for f in futures:
                    if not f.done():
                        fail_count += 1
        finally:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

        was_cancelled = not self.is_running
        self.all_done_signal.emit(success_count, fail_count, was_cancelled)

    def stop(self):
        self.is_running = False

# ----------------- 主界面窗口 -----------------

class MusicDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine = MusicEngine()
        self.drag_position = QPoint()

        self.max_workers = 12

        self.active_single_downloads = []
        self.batch_thread = None
        self.is_batch_downloading = False

        self.search_results_data = []
        self.playlist_results_data = []

        self.init_window()
        self.init_ui()
        self.setStyleSheet(QSS_STYLE)

    def init_window(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1040, 700)
        self.setMinimumSize(940, 620)
        self.setWindowTitle("我为歌狂 An1.0")
        
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def init_ui(self):
        self.main_container = QWidget(self)
        self.main_container.setObjectName("MainContainer")
        self.setCentralWidget(self.main_container)

        root_layout = QVBoxLayout(self.main_container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. 顶栏
        self.create_title_bar(root_layout)

        # 2. 核心工作区
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # 侧边栏
        self.create_sidebar(body_layout)

        # 主内容区 (macOS 极速纯净零延迟无残影 StackedWidget)
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("ContentArea")
        
        self.page_search = self.create_search_page()
        self.page_playlist = self.create_playlist_page()
        self.page_tasks = self.create_tasks_page()
        self.page_settings = self.create_settings_page()

        self.content_stack.addWidget(self.page_search)
        self.content_stack.addWidget(self.page_playlist)
        self.content_stack.addWidget(self.page_tasks)
        self.content_stack.addWidget(self.page_settings)

        body_layout.addWidget(self.content_stack)
        root_layout.addLayout(body_layout)

    # ---------------- 顶栏与全套窗口控制按键 ----------------
    def create_title_bar(self, parent_layout):
        title_bar = QWidget()
        title_bar.setObjectName("TitleBar")
        title_bar.setFixedHeight(50)
        
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(10)

        # 左侧：A2 珊瑚流光音符图标 + 标题 + 版本标签
        icon_label = QLabel()
        png_icon = os.path.join(os.path.dirname(__file__), "icons_preview", "方案A2_珊瑚流光音符.png")
        if os.path.exists(png_icon):
            pix = QPixmap(png_icon).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pix)
        else:
            icon_label.setPixmap(qta.icon('fa5s.music', color='#FF2D55').pixmap(QSize(22, 22)))

        app_title = QLabel("我为歌狂")
        app_title.setObjectName("AppTitle")
        
        badge = QLabel("An 1.0 Pro")
        badge.setObjectName("TitleBadge")

        layout.addWidget(icon_label)
        layout.addWidget(app_title)
        layout.addWidget(badge)
        layout.addSpacing(16)

        # 中间：呼吸状态提示文字
        self.status_label = QLabel("✨ 聚合全网音源 · 原声 320Kbps MP3")
        self.status_label.setStyleSheet("color: #6B7280; font-size: 12px;")
        layout.addWidget(self.status_label)
        layout.addStretch()

        # 右上角：标准现代窗口控制按键组
        self.btn_win_min = QPushButton()
        self.btn_win_min.setProperty("class", "WinControlBtn")
        self.btn_win_min.setIcon(qta.icon('fa5s.minus', color='#4B5563'))
        self.btn_win_min.setIconSize(QSize(11, 11))
        self.btn_win_min.setToolTip("最小化")
        self.btn_win_min.clicked.connect(self.showMinimized)

        self.btn_win_max = QPushButton()
        self.btn_win_max.setProperty("class", "WinControlBtn")
        self.btn_win_max.setIcon(qta.icon('fa5s.square', color='#4B5563'))
        self.btn_win_max.setIconSize(QSize(10, 10))
        self.btn_win_max.setToolTip("最大化 / 还原")
        self.btn_win_max.clicked.connect(self.toggle_maximized)

        self.btn_win_close = QPushButton()
        self.btn_win_close.setProperty("class", "WinControlBtn")
        self.btn_win_close.setObjectName("BtnWinClose")
        self.btn_win_close.setIcon(qta.icon('fa5s.times', color='#4B5563'))
        self.btn_win_close.setIconSize(QSize(12, 12))
        self.btn_win_close.setToolTip("关闭")
        self.btn_win_close.clicked.connect(self.close)

        layout.addWidget(self.btn_win_min)
        layout.addWidget(self.btn_win_max)
        layout.addWidget(self.btn_win_close)

        parent_layout.addWidget(title_bar)

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_win_max.setIcon(qta.icon('fa5s.square', color='#4B5563'))
        else:
            self.showMaximized()
            self.btn_win_max.setIcon(qta.icon('fa5s.clone', color='#4B5563'))

    # ---------------- 侧边栏导航 ----------------
    def create_sidebar(self, parent_layout):
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 18, 10, 18)
        layout.setSpacing(6)

        self.nav_buttons = []
        self.btn_nav_search = self._create_nav_btn(" 单曲搜索", 'fa5s.search', 0)
        self.btn_nav_playlist = self._create_nav_btn(" 歌单解析", 'fa5s.list-ul', 1)
        self.btn_nav_tasks = self._create_nav_btn(" 下载管理", 'fa5s.arrow-alt-circle-down', 2)
        self.btn_nav_settings = self._create_nav_btn(" 设置选项", 'fa5s.cog', 3)

        layout.addWidget(self.btn_nav_search)
        layout.addWidget(self.btn_nav_playlist)
        layout.addWidget(self.btn_nav_tasks)
        layout.addWidget(self.btn_nav_settings)
        layout.addStretch()

        stats_card = QFrame()
        stats_card.setProperty("class", "CardWidget")
        stats_card_layout = QVBoxLayout(stats_card)
        stats_card_layout.setContentsMargins(10, 10, 10, 10)
        stats_card_layout.setSpacing(4)

        lbl1 = QLabel("🎧 输出规格")
        lbl1.setStyleSheet("color: #6B7280; font-size: 11px; font-weight: bold;")
        lbl2 = QLabel("MP3 320Kbps CBR\nID3v2 元数据标签")
        lbl2.setStyleSheet("color: #0071E3; font-size: 11px; font-weight: 500;")
        stats_card_layout.addWidget(lbl1)
        stats_card_layout.addWidget(lbl2)

        layout.addWidget(stats_card)
        parent_layout.addWidget(sidebar)

        self.set_active_nav(0)

    def _create_nav_btn(self, text, icon_name, page_index):
        btn = QPushButton(text)
        btn.setProperty("class", "NavBtn")
        btn.setIcon(qta.icon(icon_name, color='#4B5563'))
        btn.setIconSize(QSize(14, 14))
        btn.clicked.connect(lambda: self.switch_page(page_index))
        self.nav_buttons.append(btn)
        return btn

    def set_active_nav(self, active_index):
        for idx, btn in enumerate(self.nav_buttons):
            is_active = (idx == active_index)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def switch_page(self, page_index):
        self.set_active_nav(page_index)
        self.content_stack.setCurrentIndex(page_index)

    # ---------------- 页面 1：单曲搜索 (智能全选Toggle + 批量下载 + 零杂线) ----------------
    def create_search_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        search_card = QFrame()
        search_card.setProperty("class", "CardWidget")
        search_card_layout = QHBoxLayout(search_card)
        search_card_layout.setContentsMargins(10, 8, 10, 8)
        search_card_layout.setSpacing(10)

        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("输入歌曲名、歌手名或关键词 (例如: 起风了 周深 / 晴天 周杰伦)...")
        self.input_search.returnPressed.connect(self.start_search)

        self.combo_source = QComboBox()
        self.combo_source.addItems(["全网智能聚合", "网易云音乐", "QQ音乐", "酷狗音乐", "酷我音乐", "Bilibili 音频"])

        self.btn_search = QPushButton(" 搜索歌曲")
        self.btn_search.setProperty("class", "PrimaryBtn")
        self.btn_search.setIcon(qta.icon('fa5s.search', color='#FFFFFF'))
        self.btn_search.clicked.connect(self.start_search)

        search_card_layout.addWidget(self.input_search, 5)
        search_card_layout.addWidget(self.combo_source, 2)
        search_card_layout.addWidget(self.btn_search, 1)

        layout.addWidget(search_card)

        # 多选快捷栏 (支持全选/全不选智能Toggle)
        batch_bar = QWidget()
        batch_bar_layout = QHBoxLayout(batch_bar)
        batch_bar_layout.setContentsMargins(4, 0, 4, 0)
        batch_bar_layout.setSpacing(8)

        self.btn_search_select_toggle = QPushButton("全选")
        self.btn_search_select_toggle.setProperty("class", "SecondaryBtn")
        self.btn_search_select_toggle.clicked.connect(self.toggle_search_selection_all)

        self.btn_search_invert = QPushButton("反选")
        self.btn_search_invert.setProperty("class", "SecondaryBtn")
        self.btn_search_invert.clicked.connect(self.invert_selection_search)

        self.lbl_search_count = QLabel("已选: 0 首")
        self.lbl_search_count.setStyleSheet("color: #6B7280; font-size: 12px; font-weight: 500;")

        self.btn_search_batch_dl = QPushButton(" 批量下载所选歌曲 (0)")
        self.btn_search_batch_dl.setProperty("class", "PrimaryBtn")
        self.btn_search_batch_dl.setIcon(qta.icon('fa5s.cloud-download-alt', color='#FFFFFF'))
        self.btn_search_batch_dl.clicked.connect(self.download_selected_search)
        self.btn_search_batch_dl.setEnabled(False)

        batch_bar_layout.addWidget(self.btn_search_select_toggle)
        batch_bar_layout.addWidget(self.btn_search_invert)
        batch_bar_layout.addSpacing(8)
        batch_bar_layout.addWidget(self.lbl_search_count)
        batch_bar_layout.addStretch()
        batch_bar_layout.addWidget(self.btn_search_batch_dl)

        layout.addWidget(batch_bar)

        # 表格
        self.table_search = QTableWidget()
        self.table_search.setColumnCount(6)
        self.table_search.setHorizontalHeaderLabels(["选择", "歌曲名称", "歌手", "专辑", "渠道", "操作"])
        
        self.table_search.setShowGrid(False)
        self.table_search.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_search.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.table_search.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_search.setColumnWidth(0, 48)
        self.table_search.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_search.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table_search.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table_search.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_search.setColumnWidth(4, 76)
        self.table_search.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table_search.setColumnWidth(5, 96)

        self.table_search.verticalHeader().setVisible(False)
        self.table_search.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_search.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table_search)
        return page

    def start_search(self):
        kw = self.input_search.text().strip()
        if not kw:
            return
        
        source_map = {
            "全网智能聚合": "all",
            "网易云音乐": "netease",
            "QQ音乐": "tencent",
            "酷狗音乐": "kugou",
            "酷我音乐": "kuwo",
            "Bilibili 音频": "bilibili"
        }
        src = source_map.get(self.combo_source.currentText(), "all")
        
        self.btn_search.setEnabled(False)
        self.btn_search.setText(" 搜索中...")
        self.status_label.setText(f"🔍 正在全网检索: {kw} ...")

        self.search_thread = SearchThread(self.engine, kw, src)
        self.search_thread.results_signal.connect(self.on_search_finished)
        self.search_thread.error_signal.connect(self.on_search_error)
        self.search_thread.start()

    def on_search_finished(self, results):
        self.btn_search.setEnabled(True)
        self.btn_search.setText(" 搜索歌曲")
        self.status_label.setText(f"✓ 找到 {len(results)} 条高品质音源")
        self.search_results_data = results
        
        self.table_search.setRowCount(0)
        for row, item in enumerate(results):
            self.table_search.insertRow(row)
            
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.stateChanged.connect(self.update_search_selection_count)
            chk_layout.addWidget(chk)
            
            t_item = QTableWidgetItem(item['title'])
            a_item = QTableWidgetItem(item['artist'])
            alb_item = QTableWidgetItem(item.get('album') or '-')
            
            src_name = item['source'].upper()
            s_item = QTableWidgetItem(src_name)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            s_item.setForeground(QColor('#0071E3'))

            btn_dl = QPushButton(" 下载 MP3")
            btn_dl.setProperty("class", "TableDownloadBtn")
            btn_dl.setIcon(qta.icon('fa5s.download', color='#0071E3'))
            btn_dl.clicked.connect(lambda _, t=item['title'], a=item['artist']: self.trigger_single_download(t, a))

            self.table_search.setCellWidget(row, 0, chk_widget)
            self.table_search.setItem(row, 1, t_item)
            self.table_search.setItem(row, 2, a_item)
            self.table_search.setItem(row, 3, alb_item)
            self.table_search.setItem(row, 4, s_item)
            self.table_search.setCellWidget(row, 5, btn_dl)
            self.table_search.setRowHeight(row, 38)

        self.update_search_selection_count()

    def on_search_error(self, err):
        self.btn_search.setEnabled(True)
        self.btn_search.setText(" 搜索歌曲")
        self.status_label.setText(f"❌ 搜索出错: {err}")

    def toggle_search_selection_all(self):
        # 智能 Toggle: 若当前全部已选中则取消全选，否则全选
        all_checked = True
        has_items = self.table_search.rowCount() > 0
        if not has_items:
            return

        for r in range(self.table_search.rowCount()):
            w = self.table_search.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and not chk.isChecked():
                    all_checked = False
                    break

        new_state = not all_checked
        for r in range(self.table_search.rowCount()):
            w = self.table_search.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(new_state)
                    
        self.update_search_selection_count()

    def invert_selection_search(self):
        for r in range(self.table_search.rowCount()):
            w = self.table_search.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(not chk.isChecked())
        self.update_search_selection_count()

    def update_search_selection_count(self):
        selected_count = 0
        total_rows = self.table_search.rowCount()
        for r in range(total_rows):
            w = self.table_search.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and chk.isChecked():
                    selected_count += 1
                    
        self.lbl_search_count.setText(f"已选: {selected_count} 首")
        self.btn_search_batch_dl.setText(f" 批量下载所选歌曲 ({selected_count})")
        self.btn_search_batch_dl.setEnabled(selected_count > 0)
        
        # 动态更新按钮文案
        if total_rows > 0 and selected_count == total_rows:
            self.btn_search_select_toggle.setText("取消全选")
        else:
            self.btn_search_select_toggle.setText("全选")

    def download_selected_search(self):
        selected_songs = []
        for r in range(self.table_search.rowCount()):
            w = self.table_search.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and chk.isChecked() and r < len(self.search_results_data):
                    selected_songs.append(self.search_results_data[r])
        
        if not selected_songs:
            return
        
        self.current_parsed_songs = selected_songs
        self.trigger_batch_download()

    # ---------------- 页面 2：歌单批量解析 (智能全选Toggle + 一键下载) ----------------
    def create_playlist_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        input_card = QFrame()
        input_card.setProperty("class", "CardWidget")
        input_card_layout = QHBoxLayout(input_card)
        input_card_layout.setContentsMargins(10, 8, 10, 8)
        input_card_layout.setSpacing(10)

        self.input_playlist = QLineEdit()
        self.input_playlist.setPlaceholderText("粘贴酷狗/网易云歌单分享链接 (如 https://t1.kugou.com/...)")

        self.btn_parse_playlist = QPushButton(" 解析歌单")
        self.btn_parse_playlist.setProperty("class", "PrimaryBtn")
        self.btn_parse_playlist.setIcon(qta.icon('fa5s.magic', color='#FFFFFF'))
        self.btn_parse_playlist.clicked.connect(self.start_parse_playlist)

        input_card_layout.addWidget(self.input_playlist, 7)
        input_card_layout.addWidget(self.btn_parse_playlist, 2)

        layout.addWidget(input_card)

        # 歌单多选快捷栏
        pl_batch_bar = QWidget()
        pl_batch_layout = QHBoxLayout(pl_batch_bar)
        pl_batch_layout.setContentsMargins(4, 0, 4, 0)
        pl_batch_layout.setSpacing(8)

        self.btn_pl_select_toggle = QPushButton("取消全选") # 默认全选
        self.btn_pl_select_toggle.setProperty("class", "SecondaryBtn")
        self.btn_pl_select_toggle.clicked.connect(self.toggle_playlist_selection_all)

        self.btn_pl_invert = QPushButton("反选")
        self.btn_pl_invert.setProperty("class", "SecondaryBtn")
        self.btn_pl_invert.clicked.connect(self.invert_selection_playlist)

        self.lbl_pl_count = QLabel("已选: 0 首")
        self.lbl_pl_count.setStyleSheet("color: #6B7280; font-size: 12px; font-weight: 500;")

        self.btn_pl_batch_download = QPushButton(" 一键全部下载 (0)")
        self.btn_pl_batch_download.setProperty("class", "PrimaryBtn")
        self.btn_pl_batch_download.setIcon(qta.icon('fa5s.cloud-download-alt', color='#FFFFFF'))
        self.btn_pl_batch_download.clicked.connect(self.download_selected_playlist)
        self.btn_pl_batch_download.setEnabled(False)

        pl_batch_layout.addWidget(self.btn_pl_select_toggle)
        pl_batch_layout.addWidget(self.btn_pl_invert)
        pl_batch_layout.addSpacing(8)
        pl_batch_layout.addWidget(self.lbl_pl_count)
        pl_batch_layout.addStretch()
        pl_batch_layout.addWidget(self.btn_pl_batch_download)

        layout.addWidget(pl_batch_bar)

        # 歌单表格
        self.table_playlist = QTableWidget()
        self.table_playlist.setColumnCount(5)
        self.table_playlist.setHorizontalHeaderLabels(["选择", "序号", "歌曲名称", "歌手", "时长"])
        
        self.table_playlist.setShowGrid(False)
        self.table_playlist.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_playlist.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.table_playlist.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_playlist.setColumnWidth(0, 48)
        self.table_playlist.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table_playlist.setColumnWidth(1, 48)
        self.table_playlist.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_playlist.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table_playlist.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_playlist.setColumnWidth(4, 70)

        self.table_playlist.verticalHeader().setVisible(False)
        self.table_playlist.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_playlist.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table_playlist)
        self.current_parsed_songs = []
        return page

    def start_parse_playlist(self):
        url = self.input_playlist.text().strip()
        if not url:
            return
        
        self.btn_parse_playlist.setEnabled(False)
        self.btn_parse_playlist.setText(" 解析中...")
        self.status_label.setText("📋 正在抓取并提取歌单数据...")

        self.parse_thread = PlaylistParseThread(self.engine, url)
        self.parse_thread.songs_signal.connect(self.on_playlist_parsed)
        self.parse_thread.error_signal.connect(self.on_playlist_error)
        self.parse_thread.start()

    def on_playlist_parsed(self, songs):
        self.btn_parse_playlist.setEnabled(True)
        self.btn_parse_playlist.setText(" 解析歌单")

        if isinstance(songs, dict) and songs.get('error'):
            self.status_label.setText(f"❌ {songs['error']}")
            self.btn_pl_batch_download.setEnabled(False)
            return

        self.playlist_results_data = songs

        if not songs:
            self.status_label.setText("❌ 未能从该链接解析出歌曲")
            self.btn_pl_batch_download.setEnabled(False)
            return

        self.status_label.setText(f"✓ 成功解析歌单！共 {len(songs)} 首歌曲")

        self.table_playlist.setRowCount(0)
        for row, s in enumerate(songs, 1):
            self.table_playlist.insertRow(row - 1)
            
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(True)
            chk.stateChanged.connect(self.update_playlist_selection_count)
            chk_layout.addWidget(chk)

            idx_item = QTableWidgetItem(str(row))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            title_item = QTableWidgetItem(s['title'])
            artist_item = QTableWidgetItem(s['artist'])
            
            m = s['duration'] // 60
            sec = s['duration'] % 60
            dur_item = QTableWidgetItem(f"{m:02d}:{sec:02d}")
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table_playlist.setCellWidget(row - 1, 0, chk_widget)
            self.table_playlist.setItem(row - 1, 1, idx_item)
            self.table_playlist.setItem(row - 1, 2, title_item)
            self.table_playlist.setItem(row - 1, 3, artist_item)
            self.table_playlist.setItem(row - 1, 4, dur_item)
            self.table_playlist.setRowHeight(row - 1, 36)

        self.update_playlist_selection_count()

    def on_playlist_error(self, err):
        self.btn_parse_playlist.setEnabled(True)
        self.btn_parse_playlist.setText(" 解析歌单")
        self.status_label.setText(f"❌ 解析出错: {err}")

    def toggle_playlist_selection_all(self):
        all_checked = True
        has_items = self.table_playlist.rowCount() > 0
        if not has_items:
            return

        for r in range(self.table_playlist.rowCount()):
            w = self.table_playlist.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and not chk.isChecked():
                    all_checked = False
                    break

        new_state = not all_checked
        for r in range(self.table_playlist.rowCount()):
            w = self.table_playlist.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(new_state)
                    
        self.update_playlist_selection_count()

    def invert_selection_playlist(self):
        for r in range(self.table_playlist.rowCount()):
            w = self.table_playlist.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(not chk.isChecked())
        self.update_playlist_selection_count()

    def update_playlist_selection_count(self):
        selected_count = 0
        total_rows = self.table_playlist.rowCount()
        for r in range(total_rows):
            w = self.table_playlist.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and chk.isChecked():
                    selected_count += 1
                    
        self.lbl_pl_count.setText(f"已选: {selected_count} 首")
        self.btn_pl_batch_download.setText(f" 一键下载所选 ({selected_count} 首)")
        self.btn_pl_batch_download.setEnabled(selected_count > 0)

        if total_rows > 0 and selected_count == total_rows:
            self.btn_pl_select_toggle.setText("取消全选")
        else:
            self.btn_pl_select_toggle.setText("全选")

    def download_selected_playlist(self):
        selected_songs = []
        for r in range(self.table_playlist.rowCount()):
            w = self.table_playlist.cellWidget(r, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk and chk.isChecked() and r < len(self.playlist_results_data):
                    selected_songs.append(self.playlist_results_data[r])
        
        if not selected_songs:
            return
        
        self.current_parsed_songs = selected_songs
        self.trigger_batch_download()

    # ---------------- 页面 3：下载任务管理 (打断/停止 + 清空 + 优雅右键菜单) ----------------
    def create_tasks_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # 顶层控制卡片
        top_card = QFrame()
        top_card.setProperty("class", "CardWidget")
        top_card_layout = QHBoxLayout(top_card)
        top_card_layout.setContentsMargins(10, 8, 10, 8)
        top_card_layout.setSpacing(8)

        self.lbl_tasks_summary = QLabel("当前下载队列: 空闲")
        self.lbl_tasks_summary.setStyleSheet("font-weight: 600; color: #1D1D1F;")

        # 打断/停止下载按键
        self.btn_stop_download = QPushButton(" 停止下载")
        self.btn_stop_download.setProperty("class", "DangerBtn")
        self.btn_stop_download.setIcon(qta.icon('fa5s.stop-circle', color='#FF3B30'))
        self.btn_stop_download.clicked.connect(self.stop_current_downloads)
        self.btn_stop_download.setVisible(False) # 仅在下载中展示

        # 打开下载目录按键
        self.btn_open_folder = QPushButton(" 打开下载目录")
        self.btn_open_folder.setProperty("class", "SecondaryBtn")
        self.btn_open_folder.setIcon(qta.icon('fa5s.folder-open', color='#0071E3'))
        self.btn_open_folder.clicked.connect(self.open_output_dir)

        # 清空任务列表按键
        self.btn_clear_tasks = QPushButton(" 清空列表")
        self.btn_clear_tasks.setProperty("class", "SecondaryBtn")
        self.btn_clear_tasks.setIcon(qta.icon('fa5s.trash-alt', color='#4B5563'))
        self.btn_clear_tasks.clicked.connect(self.clear_tasks_table)

        top_card_layout.addWidget(self.lbl_tasks_summary)
        top_card_layout.addStretch()
        top_card_layout.addWidget(self.btn_stop_download)
        top_card_layout.addWidget(self.btn_open_folder)
        top_card_layout.addWidget(self.btn_clear_tasks)

        layout.addWidget(top_card)

        # 总进度条
        self.batch_prog_bar = QProgressBar()
        self.batch_prog_bar.setValue(0)
        self.batch_prog_bar.setFixedHeight(10)
        layout.addWidget(self.batch_prog_bar)

        # 任务表格 (含右键菜单与操作列)
        self.table_tasks = QTableWidget()
        self.table_tasks.setColumnCount(5)
        self.table_tasks.setHorizontalHeaderLabels(["序号", "歌曲信息", "下载状态", "保存路径", "操作"])
        
        self.table_tasks.setShowGrid(False)
        self.table_tasks.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_tasks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.table_tasks.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_tasks.setColumnWidth(0, 48)
        self.table_tasks.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_tasks.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table_tasks.setColumnWidth(2, 96)
        self.table_tasks.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.table_tasks.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_tasks.setColumnWidth(4, 76)

        self.table_tasks.verticalHeader().setVisible(False)
        self.table_tasks.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_tasks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # 启用精致右键菜单
        self.table_tasks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_tasks.customContextMenuRequested.connect(self.show_task_context_menu)

        layout.addWidget(self.table_tasks)
        return page

    def trigger_single_download(self, title, artist):
        self.switch_page(2)
        row = self.table_tasks.rowCount()
        self.table_tasks.insertRow(row)
        
        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        info_item = QTableWidgetItem(f"{artist} - {title}")
        status_item = QTableWidgetItem("正在匹配音源...")
        status_item.setForeground(QColor('#0071E3'))
        path_item = QTableWidgetItem("-")

        btn_del = QPushButton("删除")
        btn_del.setProperty("class", "TableDeleteBtn")
        btn_del.clicked.connect(lambda _, r=row: self.remove_task_row(r))

        self.table_tasks.setItem(row, 0, idx_item)
        self.table_tasks.setItem(row, 1, info_item)
        self.table_tasks.setItem(row, 2, status_item)
        self.table_tasks.setItem(row, 3, path_item)
        self.table_tasks.setCellWidget(row, 4, btn_del)
        self.table_tasks.setRowHeight(row, 36)

        thread = SingleDownloadThread(self.engine, title, artist)
        thread.progress_signal.connect(lambda p, t, path, r=row: self.on_single_download_progress(r, p, t, path))
        self.active_single_downloads.append(thread)
        thread.start()

    def on_single_download_progress(self, row, progress, status_text, path):
        self.active_single_downloads = [t for t in self.active_single_downloads if t.isRunning()]
        if row < self.table_tasks.rowCount():
            item = self.table_tasks.item(row, 2)
            if item:
                item.setText(status_text)
                if progress == 100:
                    item.setForeground(QColor('#34C759'))
                    self.table_tasks.setItem(row, 3, QTableWidgetItem(path))
                elif progress == -1:
                    item.setForeground(QColor('#FF3B30'))
        self.status_label.setText(f"⬇️ {status_text}")

    def trigger_batch_download(self):
        if not self.current_parsed_songs:
            return
        
        self.switch_page(2)
        self.table_tasks.setRowCount(0)
        total = len(self.current_parsed_songs)

        for i, s in enumerate(self.current_parsed_songs, 1):
            row = i - 1
            self.table_tasks.insertRow(row)
            
            idx_item = QTableWidgetItem(str(i))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            info_item = QTableWidgetItem(f"{s['artist']} - {s['title']}")
            status_item = QTableWidgetItem("等待队列...")
            path_item = QTableWidgetItem("-")

            btn_del = QPushButton("删除")
            btn_del.setProperty("class", "TableDeleteBtn")
            btn_del.clicked.connect(lambda _, r=row: self.remove_task_row(r))

            self.table_tasks.setItem(row, 0, idx_item)
            self.table_tasks.setItem(row, 1, info_item)
            self.table_tasks.setItem(row, 2, status_item)
            self.table_tasks.setItem(row, 3, path_item)
            self.table_tasks.setCellWidget(row, 4, btn_del)
            self.table_tasks.setRowHeight(row, 36)

        self.batch_prog_bar.setValue(0)
        self.lbl_tasks_summary.setText(f"正在多线程并发下载: 0/{total} 首...")
        self.btn_stop_download.setVisible(True)
        self.is_batch_downloading = True

        self.batch_thread = BatchDownloadThread(self.engine, self.current_parsed_songs, max_workers=self.max_workers)
        self.batch_thread.song_progress_signal.connect(self.on_batch_song_progress)
        self.batch_thread.all_done_signal.connect(self.on_batch_all_done)
        self.batch_thread.start()

    def on_batch_song_progress(self, idx, total, song_name, status, filepath):
        if not self.is_batch_downloading:
            return
        row = idx - 1
        if row < self.table_tasks.rowCount():
            item = self.table_tasks.item(row, 2)
            if item:
                item.setText(status)
                if status == "完成":
                    item.setForeground(QColor('#34C759'))
                    if filepath:
                        self.table_tasks.setItem(row, 3, QTableWidgetItem(filepath))
                elif status in ("失败", "已停止"):
                    item.setForeground(QColor('#FF3B30'))
                else:
                    item.setForeground(QColor('#0071E3'))

        completed = sum(1 for r in range(self.table_tasks.rowCount()) if self.table_tasks.item(r, 2) and self.table_tasks.item(r, 2).text() in ["完成", "失败", "已存在", "已停止"])
        pct = int((completed / total) * 100) if total > 0 else 0
        self.batch_prog_bar.setValue(pct)
        self.lbl_tasks_summary.setText(f"正在并发下载: {completed}/{total} 首 ({pct}%)")

    def on_batch_all_done(self, success, fail, was_cancelled):
        self.btn_stop_download.setVisible(False)
        self.is_batch_downloading = False
        
        if was_cancelled:
            self.lbl_tasks_summary.setText(f"⏹ 用户已手动停止下载 (已完成: {success} 首)")
            self.status_label.setText("⏹ 下载任务已中断停止")
        else:
            self.batch_prog_bar.setValue(100)
            self.lbl_tasks_summary.setText(f"🎉 批量下载完成！成功: {success} 首, 失败: {fail} 首")
            self.status_label.setText(f"✓ 下载完成！文件已保存至: {self.engine.output_dir}")
            QMessageBox.information(self, "下载完成", f"全部 {success + fail} 首歌曲批量下载已处理完毕！\n成功: {success} 首\n保存目录: {self.engine.output_dir}")

    def stop_current_downloads(self):
        # 1. 停止批量下载线程
        if self.batch_thread and self.batch_thread.isRunning():
            self.batch_thread.stop()
            
        # 2. 停止单曲下载线程
        for th in self.active_single_downloads:
            if th.isRunning():
                th.stop()
                
        self.btn_stop_download.setVisible(False)
        self.lbl_tasks_summary.setText("⏹ 正在中断停止...")
        self.status_label.setText("⏹ 正在停止所有后台下载任务...")

    def clear_tasks_table(self):
        if self.is_batch_downloading:
            reply = QMessageBox.question(self, "确认清空", "当前有正在进行的下载任务，确定要强制中断并清空列表吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.stop_current_downloads()

        self.table_tasks.setRowCount(0)
        self.batch_prog_bar.setValue(0)
        self.lbl_tasks_summary.setText("当前下载队列: 空闲")

    def remove_task_row(self, row):
        if self.is_batch_downloading:
            QMessageBox.information(self, "提示", "批量下载进行中，暂不支持单独删除任务行。\n可在下载完成后清空列表。")
            return
        if row < self.table_tasks.rowCount():
            self.table_tasks.removeRow(row)
            # 重新刷序号
            for r in range(self.table_tasks.rowCount()):
                item = self.table_tasks.item(r, 0)
                if item:
                    item.setText(str(r + 1))

    # ---------------- 精致 macOS 右键上下文菜单实现 ----------------
    def show_task_context_menu(self, pos):
        selected_row = self.table_tasks.currentRow()
        if selected_row < 0 or selected_row >= self.table_tasks.rowCount():
            return

        item_status = self.table_tasks.item(selected_row, 2)
        status_text = item_status.text() if item_status else ""
        item_path = self.table_tasks.item(selected_row, 3)
        file_path = item_path.text() if item_path else ""

        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 1. 在资源管理器中高亮定位文件
        act_open_dir = QAction(qta.icon('fa5s.folder-open', color='#0071E3'), "打开文件所在位置", self)
        has_valid_file = bool(file_path and file_path != "-" and os.path.exists(file_path))
        act_open_dir.setEnabled(has_valid_file or os.path.exists(self.engine.output_dir))
        act_open_dir.triggered.connect(lambda: self.locate_file_in_explorer(file_path))
        menu.addAction(act_open_dir)

        # 2. 调用系统默认播放器试听
        act_play = QAction(qta.icon('fa5s.play-circle', color='#34C759'), "试听 / 默认播放器打开", self)
        act_play.setEnabled(has_valid_file)
        act_play.triggered.connect(lambda: self.play_audio_file(file_path))
        menu.addAction(act_play)

        menu.addSeparator()

        # 3. 从列表中移除记录
        act_remove = QAction(qta.icon('fa5s.times-circle', color='#6B7280'), "从列表中移除", self)
        act_remove.triggered.connect(lambda: self.remove_task_row(selected_row))
        menu.addAction(act_remove)

        # 4. 彻底删除本地文件
        if has_valid_file:
            act_delete = QAction(qta.icon('fa5s.trash-alt', color='#FF3B30'), "彻底删除本地 MP3", self)
            act_delete.triggered.connect(lambda: self.delete_local_file_and_row(file_path, selected_row))
            menu.addAction(act_delete)

        menu.exec(self.table_tasks.viewport().mapToGlobal(pos))

    def locate_file_in_explorer(self, file_path):
        if file_path and file_path != "-" and os.path.exists(file_path):
            # 在 Windows 资源管理器中高亮选中文件
            subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
        else:
            self.open_output_dir()

    def play_audio_file(self, file_path):
        if file_path and os.path.exists(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def delete_local_file_and_row(self, file_path, row):
        reply = QMessageBox.question(self, "确认删除", "确定要将此歌曲从硬盘中彻底删除吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                QMessageBox.warning(self, "删除失败", f"文件删除失败: {e}")
            self.remove_task_row(row)

    def open_output_dir(self):
        out_dir = self.engine.output_dir
        if os.path.exists(out_dir):
            subprocess.Popen(f'explorer "{out_dir}"')

    # ---------------- 页面 4：设置面板 ----------------
    def create_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        card_dir = QFrame()
        card_dir.setProperty("class", "CardWidget")
        card_dir_layout = QVBoxLayout(card_dir)
        card_dir_layout.setSpacing(8)

        lbl_dir_title = QLabel("📁 MP3 下载存储路径")
        lbl_dir_title.setStyleSheet("font-weight: 600; color: #1D1D1F; font-size: 14px;")

        path_row = QHBoxLayout()
        self.input_dir = QLineEdit(self.engine.output_dir)
        self.input_dir.setReadOnly(True)

        btn_browse = QPushButton(" 更改目录")
        btn_browse.setProperty("class", "SecondaryBtn")
        btn_browse.setIcon(qta.icon('fa5s.folder', color='#374151'))
        btn_browse.clicked.connect(self.browse_output_dir)

        path_row.addWidget(self.input_dir, 4)
        path_row.addWidget(btn_browse, 1)

        card_dir_layout.addWidget(lbl_dir_title)
        card_dir_layout.addLayout(path_row)
        layout.addWidget(card_dir)

        card_opt = QFrame()
        card_opt.setProperty("class", "CardWidget")
        card_opt_layout = QVBoxLayout(card_opt)
        card_opt_layout.setSpacing(12)

        lbl_opt_title = QLabel("⚡ 下载引擎与音频转码配置")
        lbl_opt_title.setStyleSheet("font-weight: 600; color: #1D1D1F; font-size: 14px;")

        row1 = QHBoxLayout()
        lbl_br = QLabel("默认输出码率:")
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["MP3 320Kbps (高保真母带级)", "MP3 192Kbps (标准品质)"])
        self.combo_bitrate.currentIndexChanged.connect(
            lambda i: setattr(self.engine, 'bitrate', [320, 192][i] if i in (0, 1) else 320))
        row1.addWidget(lbl_br)
        row1.addWidget(self.combo_bitrate)
        row1.addStretch()

        row2 = QHBoxLayout()
        lbl_thread = QLabel("最大下载并发线程数:")
        self.combo_threads = QComboBox()
        self.combo_threads.addItems(["12 线程 (推荐 极速并发)", "16 线程 (超高速宽带)", "8 线程 (平衡模式)", "4 线程 (节能模式)"])
        self.combo_threads.currentIndexChanged.connect(
            lambda i: setattr(self, 'max_workers', [12, 16, 8, 4][i] if i in (0, 1, 2, 3) else 12))
        row2.addWidget(lbl_thread)
        row2.addWidget(self.combo_threads)
        row2.addStretch()

        card_opt_layout.addWidget(lbl_opt_title)
        card_opt_layout.addLayout(row1)
        card_opt_layout.addLayout(row2)
        layout.addWidget(card_opt)

        layout.addStretch()
        return page

    def browse_output_dir(self):
        dir_selected = QFileDialog.getExistingDirectory(self, "选择下载保存文件夹", self.engine.output_dir)
        if dir_selected:
            self.engine.output_dir = dir_selected
            self.input_dir.setText(dir_selected)

    # ---------------- 窗口拖动与双击最大化支持 ----------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.pos().y() <= 50:
            self.toggle_maximized()

if __name__ == '__main__':
    if sys.platform == 'win32':
        try:
            app_id = 'wowgekuang.music.downloader.an1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass

    app = QApplication(sys.argv)
    
    icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        
    window = MusicDownloaderApp()
    window.show()
    sys.exit(app.exec())
