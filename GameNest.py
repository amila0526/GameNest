"""
Requirements:
 pip install PyQt5
 pip install pywin32

Run:
 python GameNest.py
"""

import sys
import os
import json
import subprocess
import ctypes
from pathlib import Path
from PyQt5 import QtWidgets, QtGui, QtCore
import win32api, win32con, win32gui, win32ui
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from PyQt5.QtGui import QColor
import subprocess
import time
from PyQt5.QtMultimedia import QSoundEffect
from PyQt5.QtCore import QUrl

GAMES_DB = Path(__file__).with_suffix("").parent / "games.json"

# -------------------- Admin Check --------------------
def is_admin():
    """Return True if the current process has admin privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """Relaunch the script with admin privileges via UAC prompt."""
    python_exe = sys.executable
    script = os.path.abspath(sys.argv[0])
    params = ' '.join([f'"{x}"' for x in sys.argv[1:]])
    # ShellExecuteW returns >32 if successful
    ctypes.windll.shell32.ShellExecuteW(None, "runas", python_exe, f'"{script}" {params}', None, 1)
    sys.exit()  # exit current instance immediately

# -------------------- Main --------------------
if __name__ == "__main__":
    # Trigger UAC immediately if not admin
    if not is_admin():
        run_as_admin()

    # From here on, we are running as admin
    from GameNest import GameNestLauncher  # import after admin check to avoid PyQt init issues

    app = QtWidgets.QApplication(sys.argv)
    win = GameNestLauncher()
    win.show()
    sys.exit(app.exec_())
    
class HoverButton(QtWidgets.QPushButton):
    def __init__(self, text, sound_effect=None):
        super().__init__(text)
        self.sound_effect = sound_effect

    def enterEvent(self, event):
        if self.sound_effect:
            self.sound_effect.play()
        super().enterEvent(event)    

def launch_selected_game(self):
    item = self.sidebar.currentItem()
    if not item:
        QtWidgets.QMessageBox.information(self, "Launch", "Please select a game first.")
        return

    game = next((g for g in self.games if g.path == item.data(QtCore.Qt.UserRole)), None)
    if not game:
        return

    try:
        # Start the game process
        process = subprocess.Popen([game.path])
        start_time = time.time()

        # Optional: disable launcher while game is running
        self.setEnabled(False)

        # Wait until the game process exits
        process.wait()
        end_time = time.time()

        # Re-enable launcher
        self.setEnabled(True)

        # Update playtime
        session_seconds = int(end_time - start_time)
        game.total_playtime += session_seconds
        game.last_played = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        
        self.save_games()
        self.on_game_selected(item)

        # Show a small notification
        QtWidgets.QMessageBox.information(self, "Playtime Recorded",
                                          f"You played {game.name} for {session_seconds//3600}h "
                                          f"{(session_seconds%3600)//60}m {session_seconds%60}s this session.")

    except Exception as e:
        self.setEnabled(True)
        QtWidgets.QMessageBox.warning(self, "Error", f"Failed to launch: {e}")

def get_game_icon(exe_path):
    """
    Try to extract icon from the exe. 
    If that fails, search the folder for any .ico file and use it.
    Returns path to saved icon (.bmp) or None.
    """
    folder = os.path.dirname(exe_path)
    icon_save_path = Path(folder) / (os.path.splitext(os.path.basename(exe_path))[0] + ".bmp")

    # --- Try extracting from exe ---
    try:
        large, small = win32gui.ExtractIconEx(exe_path, 0)
        if large:
            ico_x = win32api.GetSystemMetrics(win32con.SM_CXICON)
            hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
            hbmp = win32ui.CreateBitmap()
            hbmp.CreateCompatibleBitmap(hdc, ico_x, ico_x)
            hdc_mem = hdc.CreateCompatibleDC()
            hdc_mem.SelectObject(hbmp)
            win32gui.DrawIconEx(hdc_mem.GetHandleOutput(), 0, 0, large[0], ico_x, ico_x, 0, 0, win32con.DI_NORMAL)
            hbmp.SaveBitmapFile(hdc_mem, str(icon_save_path))
            for i in large: win32gui.DestroyIcon(i)
            return str(icon_save_path)
    except Exception as e:
        print(f"Failed to extract icon from exe: {e}")

    # --- Fallback: search for .ico files in the folder ---
    try:
        for f in os.listdir(folder):
            if f.lower().endswith(".ico"):
                return str(Path(folder) / f)
    except Exception as e:
        print(f"Failed to find .ico in folder: {e}")

    return None

class GameEntry:
    def __init__(self, name, path, icon_path=None):
        self.name = name
        self.path = path
        self.icon_path = icon_path
        self.is_favorite = False
        self.notes = ""
        self.last_played = "Never"
        self.total_playtime = 0

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.path,
            "icon_path": self.icon_path,
            "is_favorite": self.is_favorite,
            "notes": self.notes,
            "last_played": self.last_played,
            "total_playtime": self.total_playtime
        }

    @staticmethod
    def from_dict(data):
        g = GameEntry(data["name"], data["path"], data.get("icon_path"))
        g.is_favorite = data.get("is_favorite", False)
        g.notes = data.get("notes", "")
        g.last_played = data.get("last_played", "Never")
        g.total_playtime = data.get("total_playtime", 0)
        return g

class GameNestLauncher(QtWidgets.QMainWindow):
    def __init__(self):
        self.gradient_shift = 0
        self.custom_background_path = None
        self.bg_blur_amount = 0
        super().__init__()
        self.setWindowTitle("GameNest")
        self.resize(1000, 560)
        
        import sys, os, shutil

        # --- AppData-backed games.json ---
        appdata = os.getenv("APPDATA") or os.path.expanduser("~")
        appdata_dir = os.path.join(appdata, "GameNest")
        os.makedirs(appdata_dir, exist_ok=True)
        self.games_file = os.path.join(appdata_dir, "games.json")

        # --- Data ---
        self.custom_scan_folders = []
        self.games = []
        self.custom_background_path = None

        # --- Background ---
        self.bg_label = QtWidgets.QLabel(self)
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        self.bg_label.lower()
        self.bg_label.setScaledContents(True)

        # --- Main Layout ---
        main_widget = QtWidgets.QWidget()
        self.main_layout = QtWidgets.QHBoxLayout()
        main_widget.setLayout(self.main_layout)
        self.setCentralWidget(main_widget)

        # --- Stylesheet ---
        self.setStyleSheet("""
    QWidget {
        background: transparent;
        font-family: "Segoe UI", sans-serif;
        color: white;
    }

    QWidget#sidebarWidget {
        background: rgba(46, 0, 51, 180);
        border-right: 1px solid rgba(120, 0, 255, 0.4);
        border-radius: 14px;
        margin: 8px;
    }

    QListWidget {
        background: transparent;
        border: none;
        color: white;
        font-size: 11pt;
    }
    QListWidget::item {
        padding: 8px;
        border-radius: 6px;
        margin: 2px;
    }
    QListWidget::item:selected {
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 #7d00e6, stop:1 #5a00b0
        );
        border: 1px solid rgba(255,255,255,0.1);
    }

    QWidget#centerWidget {
        background: rgba(59, 0, 102, 180);
        border-radius: 18px;
        margin: 10px;
        border: 1px solid rgba(120, 0, 255, 0.4);
    }

    QLabel {
        color: white;
        font-size: 11pt;
    }
    QLabel#titleLabel {
        font-size: 16pt;
        font-weight: bold;
    }

    QWidget#rightWidget {
        background: rgba(46, 0, 51, 180);
        border-left: 1px solid rgba(120, 0, 255, 0.4);
        border-radius: 14px;
        margin: 8px;
    }

    QPushButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #5a00b0, stop:1 #7d00e6
    );
    color: white;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 500;
    }
    QPushButton:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #7d00e6, stop:1 #9c00ff
    );
    border: 1px solid rgba(255,255,255,0.2);
    /* Glow effect */
    box-shadow: 0 0 12px rgba(125,0,230,0.8);
    }
    QPushButton:pressed {
    background: #400080;
    }

    QTabWidget::pane {
        border: 1px solid rgba(120, 0, 255, 0.4);
        background: rgba(46, 0, 51, 180);
        border-radius: 10px;
    }
    QTabBar::tab {
        background: rgba(90, 0, 176, 180);
        color: white;
        padding: 6px 14px;
        margin-right: 4px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        border: 1px solid rgba(255,255,255,0.05);
    }
    QTabBar::tab:selected {
        background: rgba(125, 0, 230, 200);
        border-bottom: 2px solid white;
    }

    QMessageBox {
        background-color: #3b0066;
        color: white;
        font-size: 12pt;
    }
""")

        # --- Sidebar ---
        self.sidebar = QtWidgets.QListWidget()
        self.sidebar.setIconSize(QtCore.QSize(48, 48))
        self.sidebar.setFixedWidth(260)
        self.sidebar.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self.sidebar_context_menu)
        self.sidebar.itemClicked.connect(self.on_game_selected)

        sidebar_layout = QtWidgets.QVBoxLayout()
        header_layout = QtWidgets.QHBoxLayout()
        title_label = QtWidgets.QLabel("GameNest")
        title_label.setStyleSheet("font-weight:bold;font-size:16pt;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        add_btn = QtWidgets.QPushButton("+")
        add_btn.setFixedSize(28, 28)
        add_btn.clicked.connect(self.on_add_clicked)
        header_layout.addWidget(add_btn)
        sidebar_layout.addLayout(header_layout)

        # --- Search bar ---
        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText("Search games...")
        self.search_bar.textChanged.connect(self.filter_sidebar)
        sidebar_layout.addWidget(self.search_bar)

        sidebar_layout.addWidget(self.sidebar)

        sidebar_widget = QtWidgets.QWidget()
        sidebar_widget.setLayout(sidebar_layout)
        sidebar_widget.setObjectName("sidebarWidget")
        self.apply_shadow(sidebar_widget)

        # --- Center Panel ---
        self.center = QtWidgets.QWidget()
        self.center.setObjectName("centerWidget")
        center_layout = QtWidgets.QVBoxLayout()
        self.center.setLayout(center_layout)

        self.favorite_btn = QtWidgets.QPushButton("♡ Add to Favorites")
        self.favorite_btn.setCheckable(True)
        self.favorite_btn.clicked.connect(self.toggle_favorite)
        center_layout.addWidget(self.favorite_btn, alignment=QtCore.Qt.AlignCenter)

        center_layout.addStretch()
        self.game_icon = QtWidgets.QLabel()
        self.game_icon.setFixedSize(128, 128)
        self.game_icon.setAlignment(QtCore.Qt.AlignCenter)
        center_layout.addWidget(self.game_icon, alignment=QtCore.Qt.AlignCenter)

        self.game_name = QtWidgets.QLabel("Select a game")
        self.game_name.setStyleSheet("font-size:14pt;font-weight:600;")
        center_layout.addWidget(self.game_name, alignment=QtCore.Qt.AlignCenter)

        self.game_path = QtWidgets.QLabel("")
        self.game_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        center_layout.addWidget(self.game_path, alignment=QtCore.Qt.AlignCenter)

        self.game_notes = QtWidgets.QLabel("")
        center_layout.addWidget(self.game_notes, alignment=QtCore.Qt.AlignCenter)

        self.game_last_played = QtWidgets.QLabel("")
        center_layout.addWidget(self.game_last_played, alignment=QtCore.Qt.AlignCenter)

        self.game_playtime = QtWidgets.QLabel("Total Playtime: 0h 0m 0s")
        center_layout.addWidget(self.game_playtime, alignment=QtCore.Qt.AlignCenter)

        launch_btn = QtWidgets.QPushButton("Launch")
        launch_btn.setFixedHeight(40)
        launch_btn.clicked.connect(self.launch_selected_game)
        center_layout.addWidget(launch_btn, alignment=QtCore.Qt.AlignCenter)

        self.apply_shadow(self.center)

        # --- Right Panel / Settings ---
        self.right_widget = QtWidgets.QWidget()
        self.right_widget.setObjectName("rightWidget")
        self.right_layout = QtWidgets.QVBoxLayout()
        self.right_widget.setLayout(self.right_layout)

        self.settings_tabs = QtWidgets.QTabWidget()
        self.right_layout.addWidget(self.settings_tabs)

        # Scan Folders tab
        folders_tab = QtWidgets.QWidget()
        folders_layout = QtWidgets.QVBoxLayout()
        folders_tab.setLayout(folders_layout)
        self.folders_list = QtWidgets.QListWidget()
        folders_layout.addWidget(self.folders_list)
        add_folder_btn = QtWidgets.QPushButton("Add Folder")
        add_folder_btn.clicked.connect(self.add_scan_folder)
        folders_layout.addWidget(add_folder_btn)
        remove_folder_btn = QtWidgets.QPushButton("Remove Selected Folder")
        remove_folder_btn.clicked.connect(self.remove_scan_folder)
        folders_layout.addWidget(remove_folder_btn)
        self.settings_tabs.addTab(folders_tab, "Scan Folders")

        # -------------------- Misc tab --------------------
        misc_tab = QtWidgets.QWidget()
        misc_layout = QtWidgets.QVBoxLayout()
        misc_tab.setLayout(misc_layout)

        # Reset Games List button
        reset_btn = QtWidgets.QPushButton("Reset Games List")
        reset_btn.clicked.connect(self.reset_games_list)
        misc_layout.addWidget(reset_btn)

        # Set Custom Background button
        bg_btn = QtWidgets.QPushButton("Set Custom Background")
        bg_btn.clicked.connect(self.set_custom_background)
        misc_layout.addWidget(bg_btn)

        # Background Blur slider
        self.blur_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.blur_slider.setMinimum(0)
        self.blur_slider.setMaximum(20)  # max blur radius
        self.blur_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.blur_slider.setTickInterval(1)
        self.blur_slider.valueChanged.connect(self.set_background_blur)
        misc_layout.addWidget(QtWidgets.QLabel("Background Blur"))
        misc_layout.addWidget(self.blur_slider)

        misc_layout.addStretch()
        self.settings_tabs.addTab(misc_tab, "Miscellaneous")

        # -------------------- Apply blur effect to background --------------------
        self.bg_blur_amount = 0  # default blur
        self.blur_effect = QtWidgets.QGraphicsBlurEffect()
        self.bg_label.setGraphicsEffect(self.blur_effect)
        self.blur_effect.setBlurRadius(self.bg_blur_amount)
        self.blur_slider.setValue(self.bg_blur_amount)


        # Add panels
        self.main_layout.addWidget(sidebar_widget)
        self.main_layout.addWidget(self.center, stretch=1)
        self.main_layout.addWidget(self.right_widget)

        # Load games
        self.load_games()
        self.refresh_sidebar()
        self.refresh_folders_list()
        if self.custom_background_path:
            self.load_background(self.custom_background_path)

        # Animated default gradient
        self.bg_timer = QtCore.QTimer()
        self.bg_timer.timeout.connect(self.update_default_background)
        self.bg_timer.start(50)

    # -------------------- Search --------------------

    def filter_sidebar(self):
        query = self.search_bar.text().lower()
        self.sidebar.clear()
        for g in self.games:
            if query in g.name.lower():
                item = QtWidgets.QListWidgetItem()
                item.setText(g.name)
                item.setData(QtCore.Qt.UserRole, g.path)
                icon = QtGui.QIcon(g.icon_path) if g.icon_path and os.path.exists(g.icon_path) else self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
                item.setIcon(icon)
                self.sidebar.addItem(item)    

    # -------------------- Methods --------------------
    def apply_shadow(self, widget, color=QtGui.QColor(125,0,230), blur=25, x=0, y=0):
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(blur)
        shadow.setColor(color)
        shadow.setOffset(x, y)
        widget.setGraphicsEffect(shadow)

    # -------------------- BG Blur --------------------

    def set_background_blur(self, value):
        self.bg_blur_amount = value
        self.blur_effect.setBlurRadius(value)
        self.save_games()  # persist in games.json

    # -------------------- Favorites --------------------

    def toggle_favorite(self):
        item = self.sidebar.currentItem()
        if not item:
            return
        # Get the game object by path
        game = next((g for g in self.games if g.path == item.data(QtCore.Qt.UserRole)), None)
        if not game:
            return

        # Toggle the favorite variable
        game.is_favorite = not getattr(game, "is_favorite", False)

        # Update the button text
        self.favorite_btn.setText("♥ Remove from Favorites" if game.is_favorite else "♡ Add to Favorites")

        # Save the change
        self.save_games()

        # Refresh only the current item text
        item.setText(f"♥ {game.name}" if game.is_favorite else game.name)

    # -------------------- Background --------------------
    def update_default_background(self):
        if self.custom_background_path: return
        pix = QtGui.QPixmap(self.size())
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        gradient = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        self.gradient_shift = (self.gradient_shift + 1) % 360
        color1 = QtGui.QColor.fromHsv(self.gradient_shift, 255, 50)
        color2 = QtGui.QColor.fromHsv((self.gradient_shift+60)%360, 255, 50)
        gradient.setColorAt(0, color1)
        gradient.setColorAt(1, color2)
        painter.fillRect(self.rect(), gradient)
        painter.end()
        self.bg_label.setPixmap(pix)

    def set_custom_background(self):
        dlg = QtWidgets.QFileDialog(self, "Select Background Image or GIF")
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dlg.setNameFilter("Images (*.png *.jpg *.jpeg *.gif)")
        if dlg.exec_():
            path = dlg.selectedFiles()[0]
            self.custom_background_path = path
            self.save_games()
            self.load_background(path)

    def load_background(self, path):
        if path.lower().endswith(".gif"):
            movie = QtGui.QMovie(path)
            self.bg_label.setMovie(movie)
            movie.start()
        else:
            pix = QtGui.QPixmap(path).scaled(self.size(), QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
            self.bg_label.setPixmap(pix)

    # -------------------- Sidebar / Game Selection --------------------
    def on_game_selected(self, item):
        path = item.data(QtCore.Qt.UserRole)
        game = next((g for g in self.games if g.path == path), None)
        if not game: return
        self.game_name.setText(game.name)
        self.game_path.setText(game.path)
        icon = QtGui.QIcon(game.icon_path) if game.icon_path and os.path.exists(game.icon_path) else item.icon()
        self.game_icon.setPixmap(icon.pixmap(128,128))
        self.game_notes.setText(f"Notes: {getattr(game,'notes','')}")
        self.game_last_played.setText(f"Last Played: {getattr(game,'last_played','Never')}")
        self.game_playtime.setText(f"Total Playtime: {game.total_playtime//3600}h {(game.total_playtime%3600)//60}m {game.total_playtime%60}s")
        self.favorite_btn.setText("♥ Remove from Favorites" if getattr(game,'is_favorite',False) else "♡ Add to Favorites")

    def sidebar_context_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        if not item: return
        menu = QtWidgets.QMenu()
        launch_action = menu.addAction("Launch")
        rename_action = menu.addAction("Rename")
        remove_action = menu.addAction("Remove")
        notes_action = menu.addAction("Edit Notes")
        action = menu.exec_(self.sidebar.mapToGlobal(pos))
        path = item.data(QtCore.Qt.UserRole)
        game = next((g for g in self.games if g.path == path), None)
        if not game: return
        if action == launch_action:
            self.sidebar.setCurrentItem(item)
            self.launch_selected_game()
        elif action == rename_action:
            self.rename_game(game)
        elif action == remove_action:
            self.remove_game(game)
        elif action == notes_action:
            self.edit_notes(game)

    # -------------------- Scan Folders --------------------
    def add_scan_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Select Folder to Scan")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        if dlg.exec_():
            folder = dlg.selectedFiles()[0]
            if folder not in self.custom_scan_folders:
                self.custom_scan_folders.append(folder)
                self.refresh_folders_list()

    def remove_scan_folder(self):
        items = self.folders_list.selectedItems()
        for item in items:
            folder = item.text()
            if folder in self.custom_scan_folders:
                self.custom_scan_folders.remove(folder)
        self.refresh_folders_list()

    def refresh_folders_list(self):
        self.folders_list.clear()
        for f in self.custom_scan_folders:
            self.folders_list.addItem(f)

    # -------------------- Reset --------------------
    def reset_games_list(self):
        confirm = QtWidgets.QMessageBox.question(self, "Confirm Reset", "Are you sure you want to clear all games?")
        if confirm == QtWidgets.QMessageBox.Yes:
            self.games = []
            self.save_games()
            self.refresh_sidebar()

    # -------------------- Persistence --------------------
    def load_games(self):
        if os.path.exists(self.games_file):
            try:
                with open(self.games_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.games = []
                    for x in data.get("games", []):
                        g = GameEntry.from_dict(x)
                        g.notes = x.get("notes","")
                        g.last_played = x.get("last_played","Never")
                        self.games.append(g)
                    self.custom_scan_folders = data.get("custom_scan_folders", [])
                    self.custom_background_path = data.get("custom_background_path", None)
                    self.bg_blur_amount = data.get("custom_background_blur", 0)
                    self.blur_effect.setBlurRadius(self.bg_blur_amount)
                    self.blur_slider.setValue(self.bg_blur_amount)
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Failed to load games.json: {e}")
        else:
            self.save_games()

    def save_games(self):
        try:
            with open(self.games_file, "w", encoding="utf-8") as f:
                json.dump({
                    "games":[{**g.to_dict(), "notes":getattr(g,"notes",""), "last_played":getattr(g,"last_played","Never")} for g in self.games],
                    "custom_scan_folders": self.custom_scan_folders,
                    "custom_background_path": self.custom_background_path,
                    "custom_background_blur": getattr(self, "bg_blur_amount", 0)
                }, f, indent=2)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to save games.json: {e}")

    # -------------------- Sidebar Refresh --------------------

    def refresh_sidebar(self):
        self.sidebar.clear()
        for g in self.games:
            item = QtWidgets.QListWidgetItem()
            # Add heart if favorite
            display_name = f"♥ {g.name}" if getattr(g, "is_favorite", False) else g.name
            item.setText(display_name)
            item.setData(QtCore.Qt.UserRole, g.path)
            icon = QtGui.QIcon(g.icon_path) if g.icon_path and os.path.exists(g.icon_path) else self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
            item.setIcon(icon)
            self.sidebar.addItem(item)

    # -------------------- Game Management --------------------
    def launch_selected_game(self):
        item = self.sidebar.currentItem()
        if not item:
            QtWidgets.QMessageBox.information(self, "Launch", "Please select a game first.")
            return
        path = item.data(QtCore.Qt.UserRole)
        game = next((g for g in self.games if g.path == path), None)
        if not game:
            return
        try:
            os.startfile(path)
            # update last played
            game.last_played = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
            self.save_games()
            self.on_game_selected(item)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to launch: {e}")

    def rename_game(self, game):
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Rename Game", "New name:", text=game.name)
        if ok and new_name:
            game.name = new_name
            self.save_games()
            self.refresh_sidebar()

    def remove_game(self, game):
        confirm = QtWidgets.QMessageBox.question(self, "Confirm Removal", f"Remove {game.name}?")
        if confirm == QtWidgets.QMessageBox.Yes:
            self.games.remove(game)
            self.save_games()
            self.refresh_sidebar()

    def edit_notes(self, game):
        text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "Edit Notes", "Notes:", text=getattr(game,"notes",""))
        if ok:
            game.notes = text
            self.save_games()
            self.on_game_selected(self.sidebar.currentItem())

    # -------------------- Sidebar Refresh --------------------

    
    def add_scan_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Select Folder to Scan")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        if dlg.exec_():
            folder = dlg.selectedFiles()[0]
            if folder not in self.custom_scan_folders:
                self.custom_scan_folders.append(folder)
                self.refresh_folders_list()

    def remove_scan_folder(self):
        items = self.folders_list.selectedItems()
        for item in items:
            folder = item.text()
            if folder in self.custom_scan_folders:
                self.custom_scan_folders.remove(folder)
        self.refresh_folders_list()

    def refresh_folders_list(self):
        self.folders_list.clear()
        for folder in self.custom_scan_folders:
            self.folders_list.addItem(folder)

    def reset_games_list(self):
        self.games = []
        self.save_games()
        self.refresh_sidebar()

    # -------------------- Game Management --------------------
    def on_add_clicked(self):
        self.add_game_manually()

    def add_game_manually(self):
        dlg = QtWidgets.QFileDialog(self, "Select Game Executable")
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        if dlg.exec_():
            path = dlg.selectedFiles()[0]
            name = os.path.basename(path)
            self.games.append(GameEntry(name=name, path=path))
            self.save_games()
            self.refresh_sidebar()

    def launch_selected_game(self):
        item = self.sidebar.currentItem()
        if not item:
            QtWidgets.QMessageBox.information(self, "Launch", "Please select a game first.")
            return
        path = item.data(QtCore.Qt.UserRole)
        try:
            os.startfile(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to launch: {e}")

    def remove_selected_game(self):
        item = self.sidebar.currentItem()
        if not item:
            QtWidgets.QMessageBox.information(self, "Remove", "Please select a game first.")
            return
        name = item.text()
        path = item.data(QtCore.Qt.UserRole)
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove '{name}'?"
        )
        if confirm == QtWidgets.QMessageBox.Yes:
            self.games = [g for g in self.games if g.path != path]
            self.save_games()
            self.refresh_sidebar()
            self.game_name.setText("Select a game")
            self.game_path.setText("")
            self.game_icon.clear()

    def rename_selected_game(self):
        item = self.sidebar.currentItem()
        if not item:
            QtWidgets.QMessageBox.information(self, "Rename", "Please select a game first.")
            return
        old_name = item.text()
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Rename Game", "New name:", text=old_name)
        if ok and new_name:
            for g in self.games:
                if g.path == item.data(QtCore.Qt.UserRole):
                    g.name = new_name
            self.save_games()
            self.refresh_sidebar()

    def remove_selected_game(self, item):
        name = item.text()
        path = item.data(QtCore.Qt.UserRole)
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove '{name}' from the launcher?"
        )
        if confirm == QtWidgets.QMessageBox.Yes:
            self.games = [g for g in self.games if g.path != path]
            self.save_games()
            self.refresh_sidebar()
            self.game_name.setText("Select a game")
            self.game_path.setText("")
            self.game_icon.clear()

    def apply_hover_glow(button, color=QColor(125,0,230), blur=20):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(blur)
        shadow.setColor(color)
        shadow.setOffset(0,0)
        button.setGraphicsEffect(shadow)      

    # -------------------- Add / Detect Games --------------------
    def on_add_clicked(self):
        menu = QtWidgets.QMenu()
        detect_action = menu.addAction("Detect already existing games")
        manual_action = menu.addAction("Add game manually")
        action = menu.exec_(QtGui.QCursor.pos())
        if action == detect_action:
            if not is_admin():
                run_as_admin()
            else:
                self.detect_games()
        elif action == manual_action:
            self.add_game_manually()

    def add_game_manually(self):
        dlg = QtWidgets.QFileDialog(self, "Select game executable")
        dlg.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        dlg.setNameFilter("Executables (*.exe);;All Files (*)")
        if dlg.exec_():
            paths = dlg.selectedFiles()
            if paths:
                exe = paths[0]
                name = os.path.splitext(os.path.basename(exe))[0]
                icon_path = get_game_icon(exe)
                self.games.append(GameEntry(name, exe, icon_path))
                self.save_games()
                self.refresh_sidebar()

    # -------------------- Settings / Scan Folders --------------------
    def add_scan_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Select Folder to Scan")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        if dlg.exec_():
            folder = dlg.selectedFiles()[0]
            if folder not in self.custom_scan_folders:
                self.custom_scan_folders.append(folder)
                self.refresh_folders_list()

    def remove_scan_folder(self):
        items = self.folders_list.selectedItems()
        for item in items:
            folder = item.text()
            if folder in self.custom_scan_folders:
                self.custom_scan_folders.remove(folder)
        self.refresh_folders_list()

    def refresh_folders_list(self):
        self.folders_list.clear()
        for f in self.custom_scan_folders:
            self.folders_list.addItem(f)

    def reset_games_list(self):
        confirm = QtWidgets.QMessageBox.question(self, "Confirm Reset", "Are you sure you want to clear all games?")
        if confirm == QtWidgets.QMessageBox.Yes:
            self.games = []
            self.save_games()
            self.refresh_sidebar()

    def detect_games(self):
        default_folders = [
            r"C:\Program Files (x86)\Steam\steamapps\common",
            r"C:\Program Files\Epic Games",
            r"C:\Program Files\HoYoPlay\games",
            r"C:\Program Files\GOG Galaxy\Games",
            r"C:\Games"
        ]
        to_scan = [p for p in default_folders + self.custom_scan_folders if os.path.exists(p)]

        def find_game_exe(folder_path):
            candidates = []
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if f.lower().endswith(".exe"):
                        candidates.append(os.path.join(root, f))
            if not candidates:
                return None
            folder_basename = os.path.basename(folder_path).lower()
            for c in candidates:
                if folder_basename in os.path.splitext(os.path.basename(c))[0].lower():
                    if not any(x in os.path.basename(c).lower() for x in ['unitycrashhandler','_data','_x64']):
                        return c
            for c in candidates:
                if 'launcher' in os.path.basename(c).lower():
                    if not any(x in os.path.basename(c).lower() for x in ['unitycrashhandler','_data','_x64']):
                        return c
            filtered = [c for c in candidates if not any(x in os.path.basename(c).lower() for x in ['unitycrashhandler','_data','_x64'])]
            if filtered:
                return filtered[0]
            return candidates[0]

        candidates = []
        for root in to_scan:
            for entry in os.scandir(root):
                if entry.is_dir():
                    exe_found = find_game_exe(entry.path)
                    if exe_found and not any(g.path == exe_found for g in self.games):
                        icon_path = get_game_icon(exe_found)
                        candidates.append(GameEntry(entry.name, exe_found, icon_path))

        if not candidates:
            QtWidgets.QMessageBox.information(self, "Detect", "No games found in the specified folders.")
            return

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Detected games")
        dlg.resize(600, 400)
        layout = QtWidgets.QVBoxLayout()
        listw = QtWidgets.QListWidget()
        listw.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        for c in candidates:
            item = QtWidgets.QListWidgetItem(f"{c.name} — {c.path}")
            listw.addItem(item)
        layout.addWidget(QtWidgets.QLabel(f"Detected {len(candidates)} games. Choose which to add:"))
        layout.addWidget(listw)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        dlg.setLayout(layout)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            selected = [candidates[i.row()] for i in listw.selectedIndexes()]
            for s in selected:
                if not any(g.path == s.path for g in self.games):
                    self.games.append(s)
            self.save_games()
            self.refresh_sidebar()

    # -------------------- Settings Tab --------------------
    def add_scan_folder(self):
        dlg = QtWidgets.QFileDialog(self, "Select Folder to Scan")
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        if dlg.exec_():
            folder = dlg.selectedFiles()[0]
            if folder not in self.custom_scan_folders:
                self.custom_scan_folders.append(folder)
                self.refresh_folders_list()

    def remove_scan_folder(self):
        items = self.folders_list.selectedItems()
        for item in items:
            folder = item.text()
            if folder in self.custom_scan_folders:
                self.custom_scan_folders.remove(folder)
        self.refresh_folders_list()

    def refresh_folders_list(self):
        self.folders_list.clear()
        for f in self.custom_scan_folders:
            self.folders_list.addItem(f)

    def reset_games_list(self):
        confirm = QtWidgets.QMessageBox.question(self, "Confirm Reset", "Are you sure you want to clear all games?")
        if confirm == QtWidgets.QMessageBox.Yes:
            self.games = []
            self.save_games()
            self.refresh_sidebar()

def main():
    app = QtWidgets.QApplication(sys.argv)
    win = GameNestLauncher()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":

    main()
