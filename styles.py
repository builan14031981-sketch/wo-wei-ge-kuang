"""
Apple HIG & macOS 原生浅色极简风格 QSS 样式系统
- 主色调：Apple 经典高光蓝 (#0071E3 / #007AFF), 珊瑚红 (#FF2D55), 薄荷绿 (#34C759), 警示红 (#FF3B30)
- 背景色：macOS 冰霜白 / 极简浅灰 (#F5F6F8 / #FFFFFF)
- 侧边栏：macOS 原生浅灰侧栏 (#EBECEF)
- 右键菜单：macOS 极简悬浮微阴影菜单，严格控制内边距与对齐
"""

QSS_STYLE = """
/* 全局重置 - 彻底消除系统虚线 Focus 框 */
* {
    outline: none;
}

QWidget {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Segoe UI", "Microsoft YaHei", sans-serif;
    color: #1D1D1F;
    font-size: 13px;
    background: transparent;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
}

/* 主窗体容器 (macOS 冰霜白) */
#MainContainer {
    background: #F5F6F8;
    border-radius: 16px;
    border: 1px solid rgba(0, 0, 0, 0.12);
}

/* 顶栏控制栏 */
#TitleBar {
    background: #EBECEF;
    border-top-left-radius: 16px;
    border-top-right-radius: 16px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

#AppTitle {
    font-size: 14px;
    font-weight: 600;
    color: #1D1D1F;
    letter-spacing: 0.3px;
}

#TitleBadge {
    background: rgba(0, 113, 227, 0.10);
    color: #0071E3;
    font-size: 10px;
    font-weight: 700;
    border-radius: 6px;
    padding: 2px 7px;
}

/* 右上角现代窗口控制按钮 */
.WinControlBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #4B5563;
    width: 32px;
    height: 32px;
    min-width: 32px;
    min-height: 32px;
    max-width: 32px;
    max-height: 32px;
    margin: 0px 2px;
}
.WinControlBtn:hover {
    background: rgba(0, 0, 0, 0.06);
    color: #111827;
}
.WinControlBtn:pressed {
    background: rgba(0, 0, 0, 0.12);
}

#BtnWinClose:hover {
    background: #FF3B30;
    color: #FFFFFF;
}
#BtnWinClose:pressed {
    background: #D70015;
    color: #FFFFFF;
}

/* 侧边导航栏 (macOS 原生磨砂质感) */
#Sidebar {
    background: #EBECEF;
    border-right: 1px solid rgba(0, 0, 0, 0.08);
    border-bottom-left-radius: 16px;
}

/* 导航按钮 (macOS 胶囊药丸) */
.NavBtn {
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 9px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
    color: #4B5563;
    margin: 2px 8px;
}
.NavBtn:hover {
    background: rgba(0, 0, 0, 0.04);
    color: #111827;
}
.NavBtn[active="true"] {
    background: #0071E3;
    color: #FFFFFF;
    font-weight: 600;
}

/* 页面内容容器 */
#ContentArea {
    background: transparent;
}

/* 纯白悬浮卡片 (macOS Light Card) */
.CardWidget {
    background: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 12px;
    padding: 10px 14px;
}
.CardWidget:hover {
    border: 1px solid rgba(0, 0, 0, 0.12);
}

/* 搜索框与输入控件 */
QLineEdit {
    background: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.14);
    border-radius: 10px;
    padding: 8px 12px;
    color: #1D1D1F;
    font-size: 13px;
}
QLineEdit:focus {
    border: 1.5px solid #0071E3;
    background: #FFFFFF;
}

/* 主操作按钮 (Apple 高光蓝胶囊) */
.PrimaryBtn {
    background: #0071E3;
    border: none;
    border-radius: 10px;
    padding: 8px 18px;
    color: #FFFFFF;
    font-weight: 600;
    font-size: 13px;
}
.PrimaryBtn:hover {
    background: #0077ED;
}
.PrimaryBtn:pressed {
    background: #005BB5;
}

/* 警示操作按钮 (停止/危险动作) */
.DangerBtn {
    background: rgba(255, 59, 48, 0.10);
    border: 1px solid rgba(255, 59, 48, 0.25);
    border-radius: 10px;
    padding: 7px 14px;
    color: #FF3B30;
    font-weight: 600;
    font-size: 12px;
}
.DangerBtn:hover {
    background: #FF3B30;
    border: 1px solid #FF3B30;
    color: #FFFFFF;
}
.DangerBtn:pressed {
    background: #D70015;
    color: #FFFFFF;
}

/* 次要操作按钮 (macOS 浅灰胶囊) */
.SecondaryBtn {
    background: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.14);
    border-radius: 10px;
    padding: 7px 14px;
    color: #374151;
    font-weight: 500;
    font-size: 12px;
}
.SecondaryBtn:hover {
    background: #F3F4F6;
    border: 1px solid rgba(0, 0, 0, 0.22);
    color: #111827;
}

/* 下拉框 ComboBox */
QComboBox {
    background: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.14);
    border-radius: 8px;
    padding: 6px 12px;
    color: #1D1D1F;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 8px;
    selection-background-color: #0071E3;
    selection-color: #FFFFFF;
    color: #1D1D1F;
    padding: 4px;
}

/* 现代表格 (彻底消除虚线 Focus 框与杂线) */
QTableWidget {
    background: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 12px;
    color: #1F2937;
    gridline-color: transparent;
    outline: none;
}
QTableWidget::item {
    padding: 6px 10px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.04);
    border-top: none;
    border-left: none;
    border-right: none;
    outline: none;
}
QTableWidget::item:selected {
    background: rgba(0, 113, 227, 0.08);
    color: #0071E3;
    border-bottom: 1px solid rgba(0, 113, 227, 0.12);
    outline: none;
}
QTableWidget::item:focus {
    outline: none;
    border: none;
    border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

QHeaderView::section {
    background: #F9FAFB;
    color: #6B7280;
    padding: 9px 10px;
    border: none;
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
    font-weight: 600;
    font-size: 12px;
}

/* 复选框 QCheckBox */
QCheckBox {
    spacing: 6px;
    color: #4B5563;
    font-size: 12px;
    font-weight: 500;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1.5px solid rgba(0, 0, 0, 0.20);
    border-radius: 5px;
    background: #FFFFFF;
}
QCheckBox::indicator:hover {
    border-color: #0071E3;
}
QCheckBox::indicator:checked {
    background: #0071E3;
    border-color: #0071E3;
    image: none;
}

/* 表格内操作微按钮 */
.TableDownloadBtn {
    background: rgba(0, 113, 227, 0.08);
    border: 1px solid rgba(0, 113, 227, 0.20);
    border-radius: 7px;
    padding: 4px 8px;
    color: #0071E3;
    font-weight: 600;
    font-size: 11px;
}
.TableDownloadBtn:hover {
    background: #0071E3;
    color: #FFFFFF;
    border: 1px solid #0071E3;
}

.TableDeleteBtn {
    background: rgba(255, 59, 48, 0.08);
    border: 1px solid rgba(255, 59, 48, 0.20);
    border-radius: 7px;
    padding: 4px 8px;
    color: #FF3B30;
    font-weight: 600;
    font-size: 11px;
}
.TableDeleteBtn:hover {
    background: #FF3B30;
    color: #FFFFFF;
    border: 1px solid #FF3B30;
}

/* 自定义滚动条 (macOS 极简细灰) */
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 2px 1px;
}
QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.18);
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(0, 0, 0, 0.35);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* 进度条 ProgressBar */
QProgressBar {
    background: rgba(0, 0, 0, 0.06);
    border: none;
    border-radius: 6px;
    text-align: center;
    color: #1F2937;
    font-size: 11px;
    font-weight: 600;
    height: 10px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0071E3, stop:1 #34C759);
    border-radius: 5px;
}

/* =========================================================================
   macOS 原生精致右键菜单 (严禁间隙错位，像素级对齐)
   ========================================================================= */
QMenu {
    background-color: #FFFFFF;
    border: 1px solid rgba(0, 0, 0, 0.12);
    border-radius: 10px;
    padding: 5px;
    margin: 0px;
}
QMenu::item {
    background-color: transparent;
    padding: 6px 14px 6px 10px;
    border-radius: 6px;
    color: #1D1D1F;
    font-size: 13px;
    font-weight: 500;
    margin: 1px 0px;
}
QMenu::item:selected {
    background-color: #0071E3;
    color: #FFFFFF;
}
QMenu::item:disabled {
    color: #9CA3AF;
    background-color: transparent;
}
QMenu::separator {
    height: 1px;
    background-color: rgba(0, 0, 0, 0.08);
    margin: 4px 6px;
}
QMenu::icon {
    padding-left: 4px;
    padding-right: 8px;
}

/* 弹出层强制不透明，避免继承全局透明导致 Windows 下全黑 */
QMenu, QMessageBox, QDialog, QFileDialog {
    background-color: #FFFFFF;
    color: #1D1D1F;
}
"""
