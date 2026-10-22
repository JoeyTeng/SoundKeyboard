import copy
import os
import sys
import tempfile
import threading
from contextlib import nullcontext

import pygame
from PyQt5.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont, QIcon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QToolBox,
    QVBoxLayout,
    QWidget,
)

from audio_engine import AudioEngine
from platform_input import KEY_DOWN, KEY_UP, create_backend, normalize_key


def get_resource_path(relative_path):
    """获取资源文件的绝对路径（兼容开发环境和PyInstaller打包后的环境）"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)


class KeySignal(QObject):
    pressed = pyqtSignal(str)
    released = pyqtSignal(str)
    error = pyqtSignal(str)


# ===================== 按键捕获对话框 =====================
class KeyCaptureDialog(QDialog):
    captured = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("捕获按键")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setFixedSize(320, 150)
        self.captured_key = ""
        self._hook_id = None
        self.backend = parent.parent_vkb.backend
        self.captured.connect(self._set_key)
        layout = QVBoxLayout(self)
        self.label = QLabel("请按下要绑定的按键...")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        layout.addWidget(self.label)
        self.lbl_key = QLabel("")
        self.lbl_key.setAlignment(Qt.AlignCenter)
        self.lbl_key.setFont(QFont("Arial", 20, QFont.Bold))
        self.lbl_key.setStyleSheet("color: #FF8C00; padding: 10px;")
        layout.addWidget(self.lbl_key)
        bl = QHBoxLayout()
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setEnabled(False)
        self.btn_ok.setFocusPolicy(Qt.NoFocus)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFocusPolicy(Qt.NoFocus)
        self.btn_cancel.clicked.connect(self.reject)
        bl.addWidget(self.btn_ok)
        bl.addWidget(self.btn_cancel)
        layout.addLayout(bl)
        self.setStyleSheet("""
            QDialog{background-color:#1a1a1a;}QLabel{color:white;}
            QPushButton{background-color:#333;color:white;border:1px solid #666;border-radius:4px;padding:8px 20px;font-weight:bold;}
            QPushButton:hover{background-color:#555;}QPushButton:disabled{color:#666;}
        """)

    def keyPressEvent(self, e):
        # Local capture remains usable before global input access is granted.
        keys = {
            Qt.Key_Space: "space",
            Qt.Key_Return: "enter",
            Qt.Key_Enter: "enter",
            Qt.Key_Escape: "esc",
            Qt.Key_Backspace: "back",
            Qt.Key_Delete: "del",
            Qt.Key_Shift: "shift",
            Qt.Key_Control: "ctrl",
            Qt.Key_Alt: "alt",
            Qt.Key_Meta: "win",
            Qt.Key_CapsLock: "caps",
            Qt.Key_Tab: "tab",
            Qt.Key_Left: "left",
            Qt.Key_Right: "right",
            Qt.Key_Up: "up",
            Qt.Key_Down: "down",
            Qt.Key_Home: "home",
            Qt.Key_End: "end",
            Qt.Key_PageUp: "pageup",
            Qt.Key_PageDown: "pagedown",
        }
        if self._hook_id is None:
            self._set_key(keys.get(e.key(), normalize_key(e.text())))
        e.accept()

    def keyReleaseEvent(self, e):
        pass

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self._hook_id = self.backend.on_press(self._on_key)
        except Exception:
            self.label.setText("Global input unavailable; press a key in this window.")

    def hideEvent(self, e):
        if self._hook_id is not None:
            self.backend.unhook(self._hook_id)
            self._hook_id = None
        super().hideEvent(e)

    def _on_key(self, e):
        k = normalize_key(e.name, getattr(e, "scan_code", None))
        self.captured.emit(k)

    def _set_key(self, k):
        if k:
            self.captured_key = k
            self.lbl_key.setText(k.upper())
            self.btn_ok.setEnabled(True)


class ReadOnlyItem(QTableWidgetItem):
    def __init__(self, text=""):
        super().__init__(text)
        self.setFlags(self.flags() & ~Qt.ItemIsEditable)


# ===================== 设置面板 =====================
class CustomSettingsUI(QWidget):
    def __init__(self, parent_vkb):
        super().__init__()
        self.parent_vkb = parent_vkb
        self.audio = parent_vkb.audio
        self.setWindowTitle("设置")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(600, 720)
        self._drag_pos = None
        self.is_editing = False
        self._rules_snapshot = {}
        self.init_ui()
        self.update_theme(self.parent_vkb.theme_color)

    def init_ui(self):
        ml = QVBoxLayout(self)
        ml.setContentsMargins(15, 15, 15, 15)
        self.container = QWidget()
        self.container.setObjectName("SC")
        cl = QVBoxLayout(self.container)
        cl.setContentsMargins(20, 20, 20, 20)

        hl = QHBoxLayout()
        self.lbl_title = QLabel("⚙️ 键盘设置")
        self.lbl_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.clicked.connect(self._on_close)
        hl.addWidget(self.lbl_title)
        hl.addStretch()
        hl.addWidget(self.btn_close)
        cl.addLayout(hl)

        self.toolbox = QToolBox()
        cl.addWidget(self.toolbox)

        # 1) 外观
        p2 = QWidget()
        v2 = QVBoxLayout(p2)
        ht = QHBoxLayout()
        ht.addWidget(QLabel("主题:"))
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["橙色", "绿色", "蓝色"])
        self.combo_theme.currentIndexChanged.connect(self.parent_vkb.change_theme)
        ht.addWidget(self.combo_theme)
        v2.addLayout(ht)

        hs = QHBoxLayout()
        hs.addWidget(QLabel("尺寸:"))
        self.sl_scale = QSlider(Qt.Horizontal)
        self.sl_scale.setRange(20, 70)
        self.sl_scale.setValue(40)
        self.sl_scale.valueChanged.connect(self.parent_vkb.update_scale)
        self.lbl_s = QLabel("40")
        self.lbl_s.setFixedWidth(30)
        self.sl_scale.valueChanged.connect(lambda v: self.lbl_s.setText(str(v)))
        hs.addWidget(self.sl_scale)
        hs.addWidget(self.lbl_s)
        v2.addLayout(hs)

        ho = QHBoxLayout()
        ho.addWidget(QLabel("不透明度:"))
        self.sl_op = QSlider(Qt.Horizontal)
        self.sl_op.setRange(20, 100)
        self.sl_op.setValue(100)
        self.sl_op.valueChanged.connect(self.parent_vkb.update_opacity)
        self.lbl_o = QLabel("100%")
        self.lbl_o.setFixedWidth(40)
        self.sl_op.valueChanged.connect(lambda v: self.lbl_o.setText(f"{v}%"))
        ho.addWidget(self.sl_op)
        ho.addWidget(self.lbl_o)
        v2.addLayout(ho)

        info_v2 = QLabel(
            "请先到【音效与模式】中导入现有音效包或在【音效自定义】中绑定按键\n按下Shift：倒放\n按下CapsLock：水牛音"
        )
        info_v2.setStyleSheet("color:#999;font-size:11px;padding:8px;")
        v2.addWidget(info_v2)
        v2.addStretch()
        self.toolbox.addItem(p2, "🖥️ 外观")

        # 2) 音效
        p1 = QWidget()
        v1 = QVBoxLayout(p1)
        self.btn_load = QPushButton("📂 导入音效包")
        self.btn_load.clicked.connect(self.do_load_pack)
        self.btn_perf = QPushButton("🎹 开启演奏模式")
        self.btn_perf.setCheckable(True)
        self.btn_perf.toggled.connect(self.toggle_perf)
        info_v1 = QLabel(
            "使用此功能，确保在音效包文件夹中有key.mp3/ogg/wav/flac\n开启后按ASD...K键"
        )
        info_v1.setStyleSheet("color:#999;font-size:11px;padding:8px;")
        v1.addWidget(self.btn_load)
        v1.addWidget(self.btn_perf)
        v1.addWidget(info_v1)
        v1.addStretch()
        self.toolbox.addItem(p1, "🎵 音效与模式")

        # 3) 规则
        p3 = QWidget()
        v3 = QVBoxLayout(p3)
        tip = QLabel("保存以生效规则")
        tip.setStyleSheet("color:#888;font-size:10px;padding:4px;")
        v3.addWidget(tip)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["按键", "音频文件", "启用", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._on_cell_dbl)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setDefaultSectionSize(38)
        v3.addWidget(self.table)

        hb = QHBoxLayout()
        self.btn_open_dir = QPushButton("📂 打开目录")
        self.btn_open_dir.clicked.connect(self.open_rule_dir)
        self.btn_add = QPushButton("+ 添加")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_save = QPushButton("保存")
        self.btn_save.clicked.connect(self.do_save)
        hb.addWidget(self.btn_open_dir)
        hb.addWidget(self.btn_add)
        hb.addWidget(self.btn_save)
        v3.addLayout(hb)
        self.toolbox.addItem(p3, "⌨️ 音效自定义")

        # 4) 关于
        p4 = QWidget()
        v4 = QVBoxLayout(p4)
        al = QLabel(
            '<div align="center" style="margin-top:20px;">'
            '<a href="https://space.bilibili.com/6297797" style="color:#00aaff;text-decoration:none;font-size:18px;font-weight:bold;">作者 @依然匹萨吧</a><br><br>'
            '<span style="color:#ff5555;font-size:13px;font-weight:bold;">本软件免费，禁止商用</span></div>'
        )
        al.setOpenExternalLinks(True)
        v4.addWidget(al)
        v4.addStretch()
        self.toolbox.addItem(p4, "ℹ️ 关于")
        ml.addWidget(self.container)

    def update_theme(self, tc):
        self.btn_close.setStyleSheet(
            f"QPushButton{{background:transparent;color:{tc};font-size:20px;font-weight:bold;border:none;}}QPushButton:hover{{color:red;}}"
        )
        self.setStyleSheet(f"""
            QWidget#SC{{background-color:rgba(15,15,15,240);border:2px solid {tc};border-radius:10px;}}
            QLabel{{color:#eee;font-size:13px;font-weight:bold;}}
            QPushButton{{background-color:rgba(30,30,30,200);color:{tc};border:1px solid {tc};border-radius:5px;padding:8px;font-weight:bold;}}
            QPushButton:hover{{background-color:{tc};color:black;}}
            QToolBox::tab{{background-color:rgba(30,30,30,200);color:{tc};border:1px solid {tc};border-radius:4px;font-weight:bold;font-size:14px;}}
            QToolBox::tab:selected{{background-color:{tc};color:black;}}
            QWidget{{background-color:transparent;}}
            QTableWidget{{background-color:rgba(10,10,10,200);color:{tc};gridline-color:{tc};border:1px solid {tc};font-size:12px;}}
            QTableWidget::item{{padding:4px;background-color:rgba(10,10,10,200);color:{tc};}}
            QTableWidget::item:selected{{background-color:rgba(60,60,60,200);color:white;}}
            QHeaderView::section{{background-color:rgba(30,30,30,255);color:white;border:none;padding:4px;border-bottom:1px solid {tc};}}
            QComboBox{{background-color:rgba(30,30,30,200);color:white;border:1px solid {tc};padding:3px;border-radius:3px;}}
            QComboBox QAbstractItemView{{background-color:rgba(30,30,30,245);color:white;border:1px solid {tc};selection-background-color:{tc};selection-color:black;outline:none;}}
            QComboBox::drop-down{{border:none;width:20px;}}
            QComboBox::down-arrow{{image:none;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid {tc};margin-right:5px;}}
            QSlider::groove:horizontal{{border:1px solid #999;height:8px;background:#333;border-radius:4px;}}
            QSlider::handle:horizontal{{background:{tc};width:18px;margin:-5px 0;border-radius:9px;}}
            QCheckBox{{color:{tc};}}QCheckBox::indicator{{width:16px;height:16px;border:1px solid {tc};border-radius:3px;background-color:rgba(30,30,30,200);}}
            QCheckBox::indicator:checked{{background-color:{tc};}}
        """)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def showEvent(self, e):
        super().showEvent(e)
        self.is_editing = True
        self._rules_snapshot = copy.deepcopy(self.audio.rules)
        self.refresh_table()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.is_editing = False

    def _on_close(self):
        cur = self._collect()
        if cur != self._rules_snapshot:
            msg = QMessageBox(self)
            msg.setWindowTitle("未保存")
            msg.setText("规则已修改，是否保存？")
            msg.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            msg.setStyleSheet(
                "QMessageBox{background-color:#1a1a1a;}QLabel{color:white;}QPushButton{background-color:#333;color:white;border:1px solid #666;border-radius:4px;padding:6px 16px;min-width:70px;}QPushButton:hover{background-color:#555;}"
            )
            r = msg.exec_()
            if r == QMessageBox.Save:
                self.do_save()
                self.hide()
            elif r == QMessageBox.Discard:
                self.audio.rules = copy.deepcopy(self._rules_snapshot)
                self.audio.reload_sounds()
                self.hide()
            return
        self.hide()

    def _collect(self):
        rules = {}
        for r in range(self.table.rowCount()):
            ki = self.table.item(r, 0)
            fi = self.table.item(r, 1)
            cw = self.table.cellWidget(r, 2)
            if ki and fi and cw:
                ch = (
                    cw.findChild(QCheckBox)
                    if isinstance(cw, QWidget) and not isinstance(cw, QCheckBox)
                    else cw
                )
                if ch:
                    k = ki.text().strip().lower()
                    if k and k != "(双击设置)":
                        rules[k] = {"file": fi.text().strip(), "enabled": ch.isChecked()}
        return rules

    def do_load_pack(self):
        f = QFileDialog.getExistingDirectory(self, "选择音效包")
        if f:
            reply = QMessageBox.question(
                self, "导入音效包", "是否导入当前规则？", QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.audio.load_pack(f, overwrite_rules=True)
                self._rules_snapshot = copy.deepcopy(self.audio.rules)
                self.refresh_table()

    def toggle_perf(self, c):
        if c:
            fp = None
            if self.audio.pack_dir:
                for ext in ["wav", "mp3", "ogg", "flac"]:
                    temp = os.path.join(self.audio.pack_dir, f"key.{ext}")
                    if os.path.exists(temp):
                        fp = temp
                        break
            if fp:
                self.btn_perf.setText("🎹 退出演奏模式")
                self.audio.load_performance_key(fp)
            else:
                sd = self.audio.pack_dir if self.audio.pack_dir else ""
                f, _ = QFileDialog.getOpenFileName(
                    self, "选择音频文件", sd, "Audio (*.wav *.mp3 *.ogg *.flac)"
                )
                if f:
                    self.btn_perf.setText("🎹 退出演奏模式")
                    self.audio.load_performance_key(f)
                else:
                    self.btn_perf.setChecked(False)
        else:
            self.btn_perf.setText("🎹 开启演奏模式")
            self.audio.is_performance_mode = False

    def refresh_table(self):
        self.table.setRowCount(0)
        for k, c in self.audio.rules.items():
            self._ins(k, c.get("file", ""), c.get("enabled", True))

    def _ins(self, key, file, enabled):
        r = self.table.rowCount()
        self.table.insertRow(r)
        ki = ReadOnlyItem(key)
        ki.setToolTip("双击捕获按键")
        self.table.setItem(r, 0, ki)
        fi = ReadOnlyItem(file if file else "(双击浏览)")
        fi.setToolTip("双击选择音频")
        self.table.setItem(r, 1, fi)
        chk = QCheckBox()
        chk.setChecked(enabled)
        chk.clicked.connect(lambda: self.do_save())
        cwd1 = QWidget()
        l1 = QHBoxLayout(cwd1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setAlignment(Qt.AlignCenter)
        l1.addWidget(chk)
        self.table.setCellWidget(r, 2, cwd1)

        bd = QPushButton("❌️")
        bd.setFixedSize(26, 26)
        bd.setStyleSheet("padding: 0px; margin: 0px;")
        bd.clicked.connect(lambda: self._del(bd))
        cwd2 = QWidget()
        l2 = QHBoxLayout(cwd2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setAlignment(Qt.AlignCenter)
        l2.addWidget(bd)
        self.table.setCellWidget(r, 3, cwd2)

    def _del(self, w):
        for r in range(self.table.rowCount()):
            cw = self.table.cellWidget(r, 3)
            # 兼容直接放置button或者用QWidget包裹的情况
            if cw is w or (cw and cw.isAncestorOf(w)):
                ki = self.table.item(r, 0)
                n = ki.text() if ki else "?"
                msg = QMessageBox(self)
                msg.setWindowTitle("删除")
                msg.setText(f'删除"{n}"？')
                msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                msg.setStyleSheet(
                    "QMessageBox{background-color:#1a1a1a;}QLabel{color:white;}QPushButton{background-color:#333;color:white;border:1px solid #666;border-radius:4px;padding:6px 16px;min-width:70px;}QPushButton:hover{background-color:#555;}"
                )
                if msg.exec_() == QMessageBox.Yes:
                    self.table.removeRow(r)
                    self.do_save()
                return

    def _on_cell_dbl(self, row, col):
        if col == 0:
            dlg = KeyCaptureDialog(self)
            if dlg.exec_() == QDialog.Accepted and dlg.captured_key:
                self.table.item(row, 0).setText(dlg.captured_key)
                self.do_save()
        elif col == 1:
            sd = self.audio.pack_dir if self.audio.pack_dir else ""
            fp, _ = QFileDialog.getOpenFileName(
                self, "选择音频", sd, "音频(*.wav *.mp3 *.ogg *.flac);;所有(*)"
            )
            if fp:
                if self.audio.pack_dir and fp.startswith(self.audio.pack_dir):
                    fp = os.path.relpath(fp, self.audio.pack_dir)
                self.table.item(row, 1).setText(fp)
                self.do_save()

    def add_row(self):
        self._ins("(双击设置)", "", True)
        self.table.scrollToBottom()
        self.table.selectRow(self.table.rowCount() - 1)
        self.do_save()

    def open_rule_dir(self):
        d = self.audio.pack_dir
        if d and os.path.exists(d):
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        else:
            QMessageBox.information(self, "提示", "尚未选择音效包，不存在规则集目录。")

    def do_save(self):
        self.audio.rules = self._collect()
        self.audio.save_rules()
        self.audio.reload_sounds()
        self._rules_snapshot = copy.deepcopy(self.audio.rules)
        self.btn_save.setText("✅ 已保存!")
        self.btn_save.setEnabled(False)
        QTimer.singleShot(
            1500, lambda: (self.btn_save.setText("保存"), self.btn_save.setEnabled(True))
        )


# ===================== 主界面 =====================
class VirtualKeyboardApp(QWidget):
    def __init__(self, enable_global_input=True, pack_dir=None):
        super().__init__()
        self.setWindowTitle("音效键盘")
        self.icon_path = get_resource_path("sound_keyboard.ico")
        self.setWindowIcon(QIcon(self.icon_path))
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        if sys.platform == "darwin":
            # Keep the keyboard available while typing in another application.
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)

        self.backend = create_backend()
        self._hook_id = None
        self._input_error_dialog = None
        self.audio = AudioEngine(pack_dir)
        self.theme_color = "#FF8C00"
        self.base_size = 40
        self.buttons = {}
        self.pressed_keys = set()
        self._last_fg_hwnd = 0
        self.locked_modifiers = set()

        self.key_sig = KeySignal()
        self.key_sig.pressed.connect(self.on_key_pressed)
        self.key_sig.released.connect(self.on_key_released)
        self.key_sig.error.connect(self._show_input_error)
        self._drag_pos = None

        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._cleanup_stuck)
        self._cleanup_timer.start(1500)

        self._fg_timer = QTimer(self)
        self._fg_timer.timeout.connect(self._track_fg)
        if enable_global_input:
            self._fg_timer.start(100)

        self.init_ui()
        self.init_tray()
        self.settings_dialog = CustomSettingsUI(self)
        if enable_global_input:
            self.start_keyboard_hook()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def _track_fg(self):
        own_windows = [int(self.winId())]
        if hasattr(self, "settings_dialog"):
            own_windows.append(int(self.settings_dialog.winId()))
        target = self.backend.foreground_target(own_windows)
        if target:
            self._last_fg_hwnd = target

    def _show_input_error(self, message):
        if self._input_error_dialog is not None and self._input_error_dialog.isVisible():
            return
        dialog = QMessageBox(QMessageBox.Warning, "Keyboard access", message, QMessageBox.Ok, self)
        self._input_error_dialog = dialog
        dialog.open()

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(QIcon(self.icon_path), self)
        self.tray_icon.setToolTip("音效键盘")
        tm = QMenu()
        tm.setStyleSheet(
            "QMenu{background-color:#222;color:#fff;border:1px solid #555;}QMenu::item:selected{background-color:#555;}"
        )
        a1 = QAction("显示/隐藏", self)
        a1.triggered.connect(self.toggle_vis)
        a2 = QAction("⚙️ 设置", self)
        a2.triggered.connect(self.open_settings)
        a3 = QAction("❌ 退出", self)
        a3.triggered.connect(self.quit_app)
        retry = QAction("Retry keyboard access", self)
        retry.triggered.connect(self.start_keyboard_hook)
        tm.addAction(a1)
        tm.addAction(a2)
        tm.addAction(retry)
        tm.addSeparator()
        tm.addAction(a3)
        self.tray_icon.setContextMenu(tm)
        self.tray_icon.activated.connect(
            lambda r: self.toggle_vis() if r == QSystemTrayIcon.DoubleClick else None
        )
        self.tray_icon.show()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(5)

        top = QHBoxLayout()
        top.addStretch()

        self.lbl_rev = QLabel("REV")
        self.lbl_rev.setFixedSize(35, 18)
        self.lbl_rev.setAlignment(Qt.AlignCenter)
        self.lbl_rev.setFont(QFont("Arial", 7, QFont.Bold))
        top.addWidget(self.lbl_rev)

        self.lbl_oct = QLabel("OCT↓")
        self.lbl_oct.setFixedSize(40, 18)
        self.lbl_oct.setAlignment(Qt.AlignCenter)
        self.lbl_oct.setFont(QFont("Arial", 7, QFont.Bold))
        top.addWidget(self.lbl_oct)

        # ★ 组合键锁按钮
        self.mod_btns = {}
        modifiers = [("ctrl", "Ctrl"), ("shift", "Shift"), ("alt", "Alt")]
        if sys.platform == "darwin":
            modifiers = [("ctrl", "Ctrl"), ("shift", "Shift"), ("alt", "Opt"), ("win", "Cmd")]
        for mn, ml in modifiers:
            b = QPushButton(ml)
            b.setFixedSize(42, 18)
            b.setFont(QFont("Arial", 7, QFont.Bold))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.toggled.connect(lambda c, m=mn: self._toggle_mod(m, c))
            self.mod_btns[mn] = b
            top.addWidget(b)

        self.btn_gear = QPushButton("⚙️")
        self.btn_gear.setFixedSize(30, 22)
        self.btn_gear.setFocusPolicy(Qt.NoFocus)
        self.btn_gear.clicked.connect(self.open_settings)
        top.addWidget(self.btn_gear)
        self.main_layout.addLayout(top)

        self.kb_container = QWidget()
        self.kb_container.setObjectName("KBC")
        self.kb_layout = QVBoxLayout(self.kb_container)
        self.kb_layout.setContentsMargins(10, 10, 10, 10)

        self.rows_def = [
            [
                ("esc", "ESC", 1),
                ("f1", "F1", 1),
                ("f2", "F2", 1),
                ("f3", "F3", 1),
                ("f4", "F4", 1),
                ("f5", "F5", 1),
                ("f6", "F6", 1),
                ("f7", "F7", 1),
                ("f8", "F8", 1),
                ("f9", "F9", 1),
                ("f10", "F10", 1),
                ("f11", "F11", 1),
                ("f12", "F12", 1),
                ("ins", "INS", 1),
                ("del", "DEL", 1),
            ],
            [
                ("`", "~", 1),
                ("1", "1", 1),
                ("2", "2", 1),
                ("3", "3", 1),
                ("4", "4", 1),
                ("5", "5", 1),
                ("6", "6", 1),
                ("7", "7", 1),
                ("8", "8", 1),
                ("9", "9", 1),
                ("0", "0", 1),
                ("-", "-", 1),
                ("=", "=", 1),
                ("back", "⌫", 2),
            ],
            [
                ("tab", "TAB", 1.5),
                ("q", "Q", 1),
                ("w", "W", 1),
                ("e", "E", 1),
                ("r", "R", 1),
                ("t", "T", 1),
                ("y", "Y", 1),
                ("u", "U", 1),
                ("i", "I", 1),
                ("o", "O", 1),
                ("p", "P", 1),
                ("[", "[", 1),
                ("]", "]", 1),
                ("\\", "\\", 1.5),
            ],
            [
                ("caps", "CAPS", 1.75),
                ("a", "A", 1),
                ("s", "S", 1),
                ("d", "D", 1),
                ("f", "F", 1),
                ("g", "G", 1),
                ("h", "H", 1),
                ("j", "J", 1),
                ("k", "K", 1),
                ("l", "L", 1),
                (";", ";", 1),
                ("'", "'", 1),
                ("enter", "⏎", 2.25),
            ],
            [
                ("shift", "⇧SHIFT", 2.25),
                ("z", "Z", 1),
                ("x", "X", 1),
                ("c", "C", 1),
                ("v", "V", 1),
                ("b", "B", 1),
                ("n", "N", 1),
                ("m", "M", 1),
                (",", ",", 1),
                (".", ".", 1),
                ("/", "/", 1),
                ("rshift", "SHIFT⇧", 2.75),
            ],
            [
                ("ctrl", "CTRL", 1.25),
                ("win", "WIN", 1.25),
                ("alt", "ALT", 1.25),
                ("space", "", 6.25),
                ("left", "◀", 1.25),
                ("up", "▲", 1.25),
                ("down", "▼", 1.25),
                ("right", "▶", 1.25),
            ],
        ]

        if sys.platform == "darwin":
            labels = {"win": "⌘ CMD", "alt": "⌥ OPT", "ctrl": "⌃ CTRL", "del": "⌦"}
            self.rows_def = [
                [(key, labels.get(key, label), width) for key, label, width in row]
                for row in self.rows_def
            ]

        self.row_layouts = []
        for row in self.rows_def:
            hl = QHBoxLayout()
            hl.setSpacing(0)
            for rk, dt, wm in row:
                btn = QPushButton(dt)
                btn.setProperty("width_mult", wm)
                btn.setProperty("is_pressed", False)
                btn.setFocusPolicy(Qt.NoFocus)
                self.buttons[rk] = btn
                hl.addWidget(btn)
                # ★ 用 pressed/released 实现完整按下-释放体验
                btn.pressed.connect(lambda k=rk: self._vk_press(k))
                btn.released.connect(lambda k=rk: self._vk_release(k))
            self.kb_layout.addLayout(hl)
            self.row_layouts.append(hl)

        self.main_layout.addWidget(self.kb_container)
        self.update_scale(self.base_size)

    def _toggle_mod(self, mod, checked):
        if checked:
            self.locked_modifiers.add(mod)
        else:
            self.locked_modifiers.discard(mod)
        self._update_mod_styles()

    def _update_mod_styles(self):
        for m, b in self.mod_btns.items():
            if b.isChecked():
                b.setStyleSheet(
                    f"background-color:{self.theme_color};color:black;border:1px solid {self.theme_color};border-radius:3px;font-weight:bold;"
                )
            else:
                b.setStyleSheet(
                    "background-color:rgba(30,30,30,200);color:#888;border:1px solid #555;border-radius:3px;"
                )

    def _vk_press(self, key):
        """鼠标按下虚拟按键"""
        if key in self.buttons:
            self.buttons[key].setProperty("is_pressed", True)
            self._style_btn(self.buttons[key], True)
        # 播放音效
        self.audio.play_key(key)
        self._update_indicators()

    def _vk_release(self, key):
        """鼠标释放虚拟按键"""
        if key in self.buttons:
            self.buttons[key].setProperty("is_pressed", False)
            self._style_btn(self.buttons[key], False)
        self.audio.release_key(key)

        # ★ 模拟输入：先恢复前台窗口焦点再 SendInput
        mods = list(self.locked_modifiers)
        target = self._last_fg_hwnd

        if target:
            threading.Thread(
                target=self._simulate_keys, args=(key, mods, target), daemon=True
            ).start()

        # 非修饰键时清除组合键锁
        if (
            key not in ("ctrl", "rctrl", "shift", "rshift", "alt", "ralt", "win", "rwin", "caps")
            and self.locked_modifiers
        ):
            self.locked_modifiers.clear()
            for b in self.mod_btns.values():
                b.setChecked(False)
            self._update_mod_styles()

    def _style_btn(self, btn, active):
        if active:
            btn.setStyleSheet(
                f"background-color:{self.theme_color};color:#000;border:2px solid {self.theme_color};border-radius:5px;font-weight:bold;"
            )
        else:
            btn.setStyleSheet(
                f"background-color:rgba(10,10,10,150);color:{self.theme_color};border:1px solid {self.theme_color};border-radius:5px;font-weight:bold;"
            )

    def _update_indicators(self):
        if self.audio.shift_reverse:
            self.lbl_rev.setStyleSheet(
                f"background-color:{self.theme_color};color:black;border-radius:3px;font-weight:bold;"
            )
        else:
            self.lbl_rev.setStyleSheet(
                "background-color:rgba(30,30,30,200);color:#555;border:1px solid #555;border-radius:3px;"
            )
        if self.audio.caps_octave_down:
            self.lbl_oct.setStyleSheet(
                f"background-color:{self.theme_color};color:black;border-radius:3px;font-weight:bold;"
            )
        else:
            self.lbl_oct.setStyleSheet(
                "background-color:rgba(30,30,30,200);color:#555;border:1px solid #555;border-radius:3px;"
            )

    def apply_styles(self):
        self.kb_container.setStyleSheet(
            f"QWidget#KBC{{background-color:rgba(15,15,15,240);border:2px solid {self.theme_color};border-radius:10px;}}"
        )
        self.btn_gear.setStyleSheet(
            f"background-color:rgba(30,30,30,200);color:{self.theme_color};border:1px solid {self.theme_color};border-radius:5px;font-weight:bold;"
        )
        for btn in self.buttons.values():
            self._style_btn(btn, btn.property("is_pressed"))
        self._update_indicators()
        self._update_mod_styles()

    def update_scale(self, sz):
        self.base_size = sz
        sp = max(2, int(sz * 0.12))
        self.kb_layout.setSpacing(sp)
        font = QFont("Arial", max(6, int(sz * 0.28)), QFont.Bold)
        for ri, row in enumerate(self.rows_def):
            n = len(row)
            self.row_layouts[ri].setSpacing(sp)
            ts = sp * (n - 1)
            aw = int(15.0 * sz) - ts
            tm = sum(m for _, _, m in row)
            rw = [(m / tm) * aw for _, _, m in row]
            iw = [int(w) for w in rw]
            pe = aw - sum(iw)
            rem = sorted(range(n), key=lambda i: rw[i] - iw[i], reverse=True)
            for i in range(abs(pe)):
                iw[rem[i % n]] += 1 if pe > 0 else -1
            for i, (rk, _, _) in enumerate(row):
                self.buttons[rk].setFixedSize(iw[i], sz)
                self.buttons[rk].setFont(font)
        self.apply_styles()
        self.adjustSize()

    def update_opacity(self, v):
        self.setWindowOpacity(v / 100.0)

    def change_theme(self, idx):
        cs = ["#FF8C00", "#00FF00", "#00FFFF", "#AA00FF", "#FF3333"]
        if 0 <= idx < len(cs):
            self.theme_color = cs[idx]
            self.apply_styles()
            if hasattr(self, "settings_dialog"):
                self.settings_dialog.update_theme(self.theme_color)

    def open_settings(self):
        self.settings_dialog.show()
        self.settings_dialog.raise_()

    def toggle_vis(self):
        self.hide() if self.isVisible() else self.show()

    def shutdown(self):
        self._cleanup_timer.stop()
        self._fg_timer.stop()
        self.backend.unhook_all()
        pygame.mixer.quit()

    def quit_app(self):
        QApplication.quit()

    def _simulate_keys(self, key, mods, target):
        try:
            self.backend.simulate_keys(key, mods, target)
        except Exception as error:
            self.key_sig.error.emit(str(error))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos:
            self.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def start_keyboard_hook(self):
        if self._hook_id is not None:
            return

        def on_hook(e):
            if self.backend.is_simulating:
                return
            k = normalize_key(e.name, getattr(e, "scan_code", None))
            if not k:
                return
            if e.event_type == KEY_DOWN:
                self.key_sig.pressed.emit(k)
            elif e.event_type == KEY_UP:
                self.key_sig.released.emit(k)

        try:
            self._hook_id = self.backend.hook(on_hook)
        except Exception as error:
            self.key_sig.error.emit(str(error))

    def _cleanup_stuck(self):
        for k, b in self.buttons.items():
            if b.property("is_pressed") and k not in self.pressed_keys:
                b.setProperty("is_pressed", False)
                self._style_btn(b, False)

    def on_key_pressed(self, key):
        if self.settings_dialog.is_editing and self.settings_dialog.isActiveWindow():
            return
        if key in self.pressed_keys:
            return
        self.pressed_keys.add(key)
        if key in self.buttons:
            self.buttons[key].setProperty("is_pressed", True)
            self._style_btn(self.buttons[key], True)
        self.audio.play_key(key)
        self._update_indicators()

    def on_key_released(self, key):
        if key in self.buttons:
            self.buttons[key].setProperty("is_pressed", False)
            self._style_btn(self.buttons[key], False)
        self.audio.release_key(key)
        self.pressed_keys.discard(key)


def run():
    """Run normally, or perform a silent startup check without global input access."""
    import argparse

    parser = argparse.ArgumentParser(description="SoundKeyboard desktop application")
    parser.add_argument("--smoke-test", action="store_true", help="Check startup silently and exit")
    args = parser.parse_args()
    if args.smoke_test:
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    QApplication.setQuitOnLastWindowClosed(False)
    context = (
        tempfile.TemporaryDirectory(prefix="soundkeyboard-smoke-")
        if args.smoke_test
        else nullcontext(None)
    )
    with context as pack_dir:
        window = VirtualKeyboardApp(enable_global_input=not args.smoke_test, pack_dir=pack_dir)
        if args.smoke_test:
            window.backend.prepare()
        window.show()
        if args.smoke_test:
            QTimer.singleShot(200, app.quit)
        return app.exec_()


if __name__ == "__main__":
    sys.exit(run())
