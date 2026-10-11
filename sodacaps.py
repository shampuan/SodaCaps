#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import random
import math
from PyQt6.QtWidgets import (QApplication, QMainWindow, QGraphicsView, 
                             QGraphicsScene, QGraphicsEllipseItem, 
                             QGraphicsObject, QGraphicsTextItem, 
                             QGraphicsItem, QLabel, QGraphicsPathItem,
                             QGraphicsColorizeEffect, QGraphicsBlurEffect,
                             QDialog, QVBoxLayout, QHBoxLayout, QPushButton)
from PyQt6.QtGui import QColor, QPen, QBrush, QFont, QAction, QPainter, QPainterPath, QIcon
from PyQt6.QtCore import Qt, QPointF, QRectF, QPropertyAnimation, pyqtProperty
from PyQt6.QtWidgets import QGraphicsPixmapItem

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "1"
os.environ["QT_QPA_PLATFORM"] = "wayland;xcb"
import pygame

# --- SES SEVIYELERI (0.0 ile 1.0 arasi) ---
VOL_BGM_STREET_PARTY = 0.30     # 1. Fon Müziği (Street Party)
VOL_BGM_DUBAKUPADO = 0.40       # 2. Fon Müziği (Dubakupado)
VOL_BGM_BEACHFRONT = 0.40       # 3. Fon Müziği (Beachfront Celebration)
VOL_BGM_TWO_FINGER = 0.40       # 4. Fon Müziği (Two Finger Johnny)
VOL_BGM_VADODORA = 0.45         # 5. Fon Müziği (Vadodora)

VOL_OPENING = 0.5      # Bolum Basi Kapak Acilma Sesi
VOL_DRAG = 0.4         # Surukleme Sesi
VOL_SNAP = 0.25         # Yuvalara Oturma (Snap) Sesi
VOL_COLUMN_WIN = 0.4   # 4 Kapak Esitlenme Sesi
VOL_LEVEL_WIN = 0.5    # Bolum Gecildi Sesi
VOL_GAME_WIN = 0.7     # Oyun Tamamen Bitti Sesi
from PyQt6.QtGui import QPixmap, QImage

# --- OYUN PARAMETRELERİ ---
CAP_RADIUS = 22
DIAMETER = 48       # Grid adımı kapağın tam çapı kadar (22*2 + 4px pay)
TRACK_WIDTH = 50
SLOT_DEPTH = 4      # Her dikey kanalda kaç kapak olacak
BUFFER_CAPS = 1     # Sagda ve solda 1'er kapaklik park alani (Daraltilmis cep)

# Calisma dizinini dinamik olarak tespit et
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPS_DIR = os.path.join(BASE_DIR, "caps")
SOUNDS_DIR = os.path.join(BASE_DIR, "sounds")
BG_DIR = os.path.join(BASE_DIR, "background")

# Kullanilabilir kapak resimlerinin listesi (Seviye siralamasina gore)
CAP_FILES = [
    "Red.png",
    "Orange.png",
    "Yellow.png",
    "Green.png",
    "Blue.png",
    "Black.png"
]

def sharpen_image(pixmap):
    """Gorselleri piksel bozulmasina karsi netlestiren keskinlestirme filtresi"""
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(img)

class CapItem(QGraphicsPixmapItem):
    """Resimli ve Grid Uyumlu Gazoz Kapagi"""
    def __init__(self, pixmap, color_id, board):
        super().__init__()
        self.color_id = color_id
        self.board = board
        self.current_node = None

        self.setPixmap(pixmap)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        orig_w = pixmap.width()
        orig_h = pixmap.height()
        scale_factor = DIAMETER / orig_w
        self.setScale(scale_factor)
        self.setOffset(-orig_w / 2, -orig_h / 2)

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(10)

    def mousePressEvent(self, event):
        # Eğer bu kapak bir dikey kanalda ise ve ustunde baska kapak varsa TUTULAMAZ!
        if not self.board.can_pick_up(self):
            event.ignore()
            return
        
        # Geri alabilmek için hamle başlamadan önce tahta durumunu kaydet
        self.board.record_state()

        self.setZValue(20)
        self.board.prepare_drag_limits(self)
        self.board.start_drag_sound() # Surukleme sesini baslat
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            new_pos = value
            return self.board.clamp_to_track(self, new_pos)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setZValue(10)
        self.board.stop_drag_sound() # Surukleme sesini durdur
        self.board.snap_to_best_grid(self)
        self.board.check_column_completions() # Kanal doldu mu kontrolu
        self.board.check_win_condition()


class FadeOverlay(QGraphicsObject):
    """Sahne gecislerindeki tam ekran Kararma Efekti"""
    def __init__(self, rect):
        super().__init__()
        self.rect_area = rect.adjusted(-500, -500, 500, 500)
        self.setZValue(100)
        self.opacity_val = 0.0
        self.setOpacity(self.opacity_val)

    def boundingRect(self):
        return self.rect_area

    def paint(self, painter, option, widget=None):
        painter.setBrush(QBrush(Qt.GlobalColor.black))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawRect(self.rect_area)

    def get_op(self):
        return self.opacity_val

    def set_op(self, val):
        self.opacity_val = val
        self.setOpacity(val)

    fade_opacity = pyqtProperty(float, get_op, set_op)


class CustomGameView(QGraphicsView):
    """Pencereyi tam kaplayan yuksek kaliteli arkaplan cizicisi"""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.bg_pixmap = None
        self.is_black_screen = False
        self.music_text = "" # Arka plan resmi üzerine basılacak şarkı bilgisi
        
        bg_file = os.path.join(BG_DIR, "background.png")
        if os.path.exists(bg_file):
            self.bg_pixmap = QPixmap(bg_file)

    def drawBackground(self, painter, rect):
        viewport_rect = self.viewport().rect()

        # Bitiş ekranında tüm pencereyi kenarlıksız simsiyah kaplar
        if self.is_black_screen:
            painter.save()
            painter.resetTransform()
            painter.fillRect(viewport_rect, QColor("#08090C"))
            painter.restore()
        elif self.bg_pixmap and not self.bg_pixmap.isNull():
            painter.save()
            painter.resetTransform()
            scaled_bg = self.bg_pixmap.scaled(
                viewport_rect.size(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap(0, 0, scaled_bg)
            painter.restore()
        else:
            super().drawBackground(painter, rect)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        # Oyun alanının içine, arka plan görselinin tam sağ altına metni bas
        if getattr(self, 'music_text', '') and not self.is_black_screen:
            painter.save()
            painter.resetTransform()
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            
            font = QFont("Ubuntu", 11)
            font.setStyleHint(QFont.StyleHint.SansSerif)
            painter.setFont(font)

            # Sağ alt köşeden 16px içeride pay bırak
            viewport_rect = self.viewport().rect()
            text_rect = viewport_rect.adjusted(0, 0, -16, -10)

            # Her türlü ahşap/açık zemin üzerinde net okunsun diye hafif siyah gölge
            painter.setPen(QColor(0, 0, 0, 180))
            painter.drawText(text_rect.translated(1, 1), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, self.music_text)

            # Saf beyaz 11 punto metin
            painter.setPen(QColor(255, 255, 255, 235))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, self.music_text)
            painter.restore()

class LevelButtonItem(QGraphicsObject):
    """Ana menüdeki 4 ana Level seçim kartı"""
    def __init__(self, start_level, title, subtitle, desc, on_click_callback):
        super().__init__()
        self.start_level = start_level
        self.title = title
        self.subtitle = subtitle
        self.desc = desc
        self.on_click_callback = on_click_callback
        self.is_hovered = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.w = 150
        self.h = 185

    def boundingRect(self):
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect().adjusted(2, 2, -2, -2)

        # Kart Arka Planı
        if self.is_hovered:
            painter.setBrush(QBrush(QColor(42, 58, 78, 235)))
            painter.setPen(QPen(QColor(241, 196, 15, 240), 2.5))
        else:
            painter.setBrush(QBrush(QColor(20, 28, 40, 210)))
            painter.setPen(QPen(QColor(255, 255, 255, 75), 1.4))

        painter.drawRoundedRect(rect, 16, 16)

        # Seviye Başlığı (LEVEL 1 vb.)
        painter.setPen(QColor("#F4D03F") if self.is_hovered else QColor("#FFFFFF"))
        painter.setFont(QFont("Ubuntu", 15, QFont.Weight.Bold))
        painter.drawText(QRectF(-self.w / 2, -self.h / 2 + 18, self.w, 30), Qt.AlignmentFlag.AlignCenter, self.title)

        # Bölüm Aralığı (Bölüm 1 - 10 vb.)
        painter.setPen(QColor("#2ECC71"))
        painter.setFont(QFont("Ubuntu", 11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(-self.w / 2, -self.h / 2 + 54, self.w, 24), Qt.AlignmentFlag.AlignCenter, self.subtitle)

        # Renk / Zorluk Bilgisi (3 Renk vb.)
        painter.setPen(QColor("#BDC3C7"))
        painter.setFont(QFont("Ubuntu", 10))
        painter.drawText(QRectF(-self.w / 2, -self.h / 2 + 82, self.w, 24), Qt.AlignmentFlag.AlignCenter, self.desc)

        # Kart İçi "BAŞLA" Rozeti / Butonu
        btn_rect = QRectF(-48, self.h / 2 - 44, 96, 28)
        if self.is_hovered:
            painter.setBrush(QBrush(QColor("#F1C40F")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(btn_rect, 14, 14)
            painter.setPen(QColor("#1C2833"))
        else:
            painter.setBrush(QBrush(QColor(255, 255, 255, 25)))
            painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
            painter.drawRoundedRect(btn_rect, 14, 14)
            painter.setPen(QColor("#ECF0F1"))

        painter.setFont(QFont("Ubuntu", 10, QFont.Weight.Bold))
        painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, "START")

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            from PyQt6.QtCore import QTimer
            lvl = self.start_level
            cb = self.on_click_callback
            # Sahneyi buton olayını bitirdikten hemen sonra güvenle temizle ve oyunu başlat
            QTimer.singleShot(10, lambda: cb(lvl))
            return
        super().mousePressEvent(event)

class SimpleMenuButton(QGraphicsObject):
    """Bitiş ekranı için sade, oval ve tek bir menü butonu"""
    def __init__(self, text, on_click_callback):
        super().__init__()
        self.text = text
        self.on_click_callback = on_click_callback
        self.is_hovered = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.w = 170
        self.h = 42

    def boundingRect(self):
        return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.boundingRect()

        if self.is_hovered:
            painter.setBrush(QBrush(QColor(241, 196, 15, 230)))
            painter.setPen(QPen(QColor(255, 255, 255, 240), 1.5))
            text_color = QColor("#141A22")
        else:
            painter.setBrush(QBrush(QColor(30, 42, 58, 220)))
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1.2))
            text_color = QColor("#ECF0F1")

        painter.drawRoundedRect(rect, 21, 21)
        painter.setPen(text_color)
        painter.setFont(QFont("Ubuntu", 11, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            from PyQt6.QtCore import QTimer
            cb = self.on_click_callback
            QTimer.singleShot(10, cb)
            return
        super().mousePressEvent(event)

def generate_frosted_track_pixmap(bg_pixmap, scene_rect, track_path, track_width):
    """Arka plani ray sekline gore kesip gercekten bulandiran (macOS Frosted Glass) uretici"""
    w = int(scene_rect.width())
    h = int(scene_rect.height())
    if w <= 0 or h <= 0:
        return None

    # 1. Sahne ölçusunde arka planı örnekle
    if bg_pixmap and not bg_pixmap.isNull():
        scaled_bg = bg_pixmap.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    else:
        scaled_bg = QPixmap(w, h)
        scaled_bg.fill(QColor("#2C3E50"))

    # 2. Arka plani güçlü bir şekilde bulandır
    small_w = max(10, w // 8)
    small_h = max(10, h // 8)
    blurred_img = scaled_bg.scaled(
        small_w, small_h, 
        Qt.AspectRatioMode.IgnoreAspectRatio, 
        Qt.TransformationMode.SmoothTransformation
    ).scaled(
        w, h, 
        Qt.AspectRatioMode.IgnoreAspectRatio, 
        Qt.TransformationMode.SmoothTransformation
    )

    # 3. Ray şeklinde bir maske aç ve sadece rayların içine bu bulandırılmış resmi yerleştir
    result_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    result_img.fill(Qt.GlobalColor.transparent)

    p = QPainter(result_img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Sahne ofsetini dengele
    p.translate(-scene_rect.x(), -scene_rect.y())

    # Ray maskesini çiz
    p.setPen(QPen(Qt.GlobalColor.white, track_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(track_path)

    # Maskenin içine bulandırılmış arkaplanı dök
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.drawPixmap(int(scene_rect.x()), int(scene_rect.y()), blurred_img)

    # 1. Camın dış çevresine zarif, yarı saydam füme/gri bir çerçeve bordürü çek:
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
    p.setPen(QPen(QColor(0, 0, 0, 45), track_width + 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(track_path)

    # 2. Bulanıklığın üzerine tam ray şeklinde ipeksi beyaz cam parıltısı sür:
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.setPen(QPen(QColor(255, 255, 255, 70), track_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(track_path)

    p.end()
    return QPixmap.fromImage(result_img)

class GameWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soda Caps")
        self.resize(850, 600)

        # Uygulama ve pencere ikonu (aynı dizindeki sodacaps.png)
        self.app_icon_path = os.path.join(BASE_DIR, "sodacaps.png")
        if os.path.exists(self.app_icon_path):
            self.setWindowIcon(QIcon(self.app_icon_path))

        self.current_level = 1
        self.moves = 0
        self.history_stack = [] # Geri al (Undo) geçmişi
        self.is_in_game = False

        self.init_ui()
        self.init_sound()
        self.show_main_menu() # Oyun direkt açılmaz, önce bölüm seçim menüsü gelir
        
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(50, self.fit_board_to_window)

    def init_ui(self):
        menu_bar = self.menuBar()
        game_menu = menu_bar.addMenu("&Game")

        self.main_menu_act = QAction("Back to Main Menu", self)
        self.main_menu_act.setShortcut("Esc")
        self.main_menu_act.triggered.connect(self.show_main_menu)
        game_menu.addAction(self.main_menu_act)

        game_menu.addSeparator()

        self.undo_act = QAction("Undo", self)
        self.undo_act.setShortcut("Ctrl+Z")
        self.undo_act.triggered.connect(self.undo_move)
        game_menu.addAction(self.undo_act)
        
        # Sadece aktif bölümü başlangiç haline getirir
        self.restart_level_act = QAction("Restart Level", self)
        self.restart_level_act.setShortcut("Ctrl+R")
        self.restart_level_act.triggered.connect(lambda: self.load_level(self.current_level) if self.is_in_game else None)
        game_menu.addAction(self.restart_level_act)

        # Oyunu en başa, 1. bölüme döndürür
        restart_game_act = QAction("Restart Game (Level 1)", self)
        restart_game_act.setShortcut("Ctrl+Shift+R")
        restart_game_act.triggered.connect(self.restart_entire_game)
        game_menu.addAction(restart_game_act)

        game_menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        game_menu.addAction(exit_act)

        # --- YARDIM MENÜSÜ ---
        help_menu = menu_bar.addMenu("&Help")

        # 1. Alt Menü: Language
        lang_menu = help_menu.addMenu("Language")
        en_act = QAction("English (Default)", self)
        en_act.setCheckable(True)
        en_act.setChecked(True)
        lang_menu.addAction(en_act)

        tr_act = QAction("Türkçe", self)
        tr_act.setCheckable(True)
        tr_act.setChecked(False)
        tr_act.setEnabled(False)
        lang_menu.addAction(tr_act)

        # 2. Alt Menü: About
        about_act = QAction("About", self)
        if os.path.exists(self.app_icon_path):
            about_act.setIcon(QIcon(self.app_icon_path))
        about_act.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_act)

        self.status_bar = self.statusBar()
        self.level_label = QLabel(f"Level: {self.current_level} / 40")
        self.move_label = QLabel(f"Moves: {self.moves}")
        
        # Pencerenin sağ altındaki beyaz ve 11 punto müzik bilgi etiketi
        self.music_label = QLabel("")
        self.music_label.setStyleSheet("color: #FFFFFF; font-size: 11pt; font-weight: 500; margin-left: 15px; margin-right: 8px;")

        self.status_bar.addWidget(self.level_label)
        self.status_bar.addPermanentWidget(self.move_label)
        self.status_bar.addPermanentWidget(self.music_label)

        self.scene = QGraphicsScene(self)
        self.view = CustomGameView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(self.view)

    def restart_entire_game(self):
        """Oyunu en baştan, Seviye 1'den başlatır."""
        self.start_game_at_level(1)

    def show_about_dialog(self):
        """Soda Caps About Dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("About Soda Caps")
        if os.path.exists(self.app_icon_path):
            dialog.setWindowIcon(QIcon(self.app_icon_path))

        dialog.setFixedWidth(500)

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(15)

        # Üst Başlık ve Logo Alanı
        header_layout = QHBoxLayout()
        if os.path.exists(self.app_icon_path):
            logo_label = QLabel()
            pix = QPixmap(self.app_icon_path).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pix)
            header_layout.addWidget(logo_label)

        title_label = QLabel("Soda Caps")
        title_label.setFont(QFont("Ubuntu", 18, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #F4D03F;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # Bilgi ve Lisans Metni (HTML formatında net ve tıklanabilir linkli)
        info_label = QLabel(
            "<b>Version:</b> 1.0.0<br>"
            "<b>License:</b> GNU GPLv3<br>"
            "<b>Programming Language:</b> Python3<br>"
            "<b>GUI:</b> PyQt6<br>"
            "<b>Game Engine:</b> Pure Python scripts<br>"
            "<b>Audio Engine:</b> Pygame<br>"
            "<b>Developer:</b> A. Serhat KILIÇOĞLU (shampuan)<br>"
            "<b>GitHub:</b> <a href='https://www.github.com/shampuan' style='color: #3498DB;'>www.github.com/shampuan</a><br><br>"
            "A free soda bottle cap matching puzzle game enriched with sound effects "
            "and Kevin MacLeod's high quality royalty-free music. "
            "All content is free and lawful.<br><br>"
            "<i>This application comes with absolutely no warranty.</i><br><br>"
            "<b>Copyright &copy; 2026 - A. Serhat KILIÇOĞLU</b>"
        )
        info_label.setFont(QFont("Ubuntu", 10))
        info_label.setWordWrap(True)
        info_label.setOpenExternalLinks(True)
        main_layout.addWidget(info_label)

        # Tamam Butonu
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(100)
        ok_btn.setFixedHeight(32)
        ok_btn.setFont(QFont("Ubuntu", 10, QFont.Weight.Bold))
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(ok_btn)
        main_layout.addLayout(btn_layout)

        dialog.exec()

    def show_main_menu(self):
        """Başlangıçta ve istendiğinde açılan Bölüm Seçim / Başlama Ekranı"""
        self.is_in_game = False
        self.view.is_black_screen = False # Normal arkaplanı geri getir
        
        # Havai fişek animasyonu çalışıyorsa temizle ve durdur
        if hasattr(self, 'firework_timer') and self.firework_timer.isActive():
            self.firework_timer.stop()

        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

        self.scene.clear()
        self.history_stack.clear()
        self.level_label.setText("Main Menu - Level Select")
        self.move_label.setText("")

        self.undo_act.setEnabled(False)
        self.restart_level_act.setEnabled(False)

        menu_w, menu_h = 820, 560
        self.scene.setSceneRect(0, 0, menu_w, menu_h)
        cx, cy = menu_w / 2, menu_h / 2

        # 1. Menü Arka Plan Paneli (Yarı Saydam Buzlu Cam Kart)
        panel_rect = QRectF(40, 25, menu_w - 80, menu_h - 50)
        p_path = QPainterPath()
        p_path.addRoundedRect(panel_rect, 18, 18)
        self.scene.addPath(
            p_path,
            QPen(QColor(255, 255, 255, 50), 1.5),
            QBrush(QColor(15, 20, 30, 205))
        )

        # 2. Oyun Başlığı
        title = QGraphicsTextItem("SODA CAPS")
        title.setFont(QFont("Ubuntu", 26, QFont.Weight.Bold))
        title.setDefaultTextColor(QColor("#F4D03F"))
        t_bound = title.boundingRect()
        title.setPos(cx - (t_bound.width() / 2), panel_rect.top() + 15)
        self.scene.addItem(title)

        # 3. Subtitle
        sub = QGraphicsTextItem("Select the level you want to start")
        sub.setFont(QFont("Ubuntu", 12, QFont.Weight.Medium))
        sub.setDefaultTextColor(QColor("#AAB7B8"))
        s_bound = sub.boundingRect()
        sub.setPos(cx - (s_bound.width() / 2), panel_rect.top() + 60)
        self.scene.addItem(sub)

        # 4. 4 Main Level Cards
        levels_data = [
            (1,  "LEVEL 1", "Levels 1 - 10",  "3 Colors / Easy"),
            (11, "LEVEL 2", "Levels 11 - 20", "4 Colors / Medium"),
            (21, "LEVEL 3", "Levels 21 - 30", "5 Colors / Hard"),
            (31, "LEVEL 4", "Levels 31 - 40", "6 Colors / Expert")
        ]

        card_spacing = 168
        cards_start_x = cx - (1.5 * card_spacing)
        cards_y = cy + 28

        for idx, (start_lvl, title_str, sub_str, desc_str) in enumerate(levels_data):
            bx = cards_start_x + (idx * card_spacing)
            btn = LevelButtonItem(start_lvl, title_str, sub_str, desc_str, self.start_game_at_level)
            btn.setPos(bx, cards_y)
            btn.setZValue(10)
            self.scene.addItem(btn)

        self.fit_board_to_window()

    def start_game_at_level(self, level_num):
        """Seçilen bölümü başlatır"""
        self.current_level = level_num
        self.load_level(self.current_level)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_board_to_window()

    def fit_board_to_window(self):
        if hasattr(self, 'scene') and self.scene.sceneRect().isValid():
            self.view.resetTransform()
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def init_sound(self):
        """Pygame Mixer ile cizirtisiz, yuksek kaliteli ses yonetimi"""
        try:
            # Cızırtı ve gecikmeyi önleyen donanım ayarları:
            # 44100Hz standart frekans, 16-bit imzali ses, 2 kanal (stereo), 2048 tampon bellek
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=2048)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(8)
            
            # Ses kanalları
            self.ch_opening = pygame.mixer.Channel(0)
            self.ch_drag = pygame.mixer.Channel(1)
            self.ch_snap = pygame.mixer.Channel(2)
            self.ch_col_win = pygame.mixer.Channel(3)
            self.ch_game_win = pygame.mixer.Channel(4)

            # Ses efekt dosyalarını yükle
            def load_sfx(name, vol):
                path = os.path.join(SOUNDS_DIR, name)
                if os.path.exists(path):
                    s = pygame.mixer.Sound(path)
                    s.set_volume(vol)
                    return s
                else:
                    print(f"Uyari: Ses dosyasi bulunamadi: {path}")
                    return None

            def find_sound_file(base_name):
                # Dosyayı hem olduğu gibi hem de .ogg/.wav uzantılarıyla ara
                for ext in ["", ".ogg", ".wav"]:
                    candidate = os.path.join(SOUNDS_DIR, base_name + ext)
                    if os.path.exists(candidate):
                        return candidate
                return None

            def load_sfx_safe(name, vol):
                path = find_sound_file(name)
                if path:
                    s = pygame.mixer.Sound(path)
                    s.set_volume(vol)
                    return s
                else:
                    print(f"Uyari: Ses dosyasi bulunamadi: {name} (sounds klasorunu kontrol edin)")
                    return None

            self.sfx_opening = load_sfx_safe("freesound_community-pouring-soda-51566", VOL_OPENING)
            self.sfx_drag = load_sfx_safe("strachszydlo-dragging-chain-on-the-concrete-and-on-the-ground-477712", VOL_DRAG)
            self.sfx_snap = load_sfx_safe("freesound_community-opening-a-cap-36052", VOL_SNAP)
            self.sfx_col_win = load_sfx_safe("puyopuyomegafan1234-winner-game-sound-404167", VOL_COLUMN_WIN)
            self.sfx_level_win = load_sfx_safe("cartoon-music-game-sfx-correct-game-show-alert-494539", VOL_LEVEL_WIN)
            self.sfx_game_win = load_sfx_safe("Kevin MacLeod - Running Fanfare", VOL_GAME_WIN)

            # Fon Müzikleri ve en başta tanımlanan ses seviyeleri
            self.bgm_playlist = [
                ("kevin_macleod_-_street_party.ogg", VOL_BGM_STREET_PARTY),
                ("Kevin MacLeod - Dubakupado.ogg", VOL_BGM_DUBAKUPADO),
                ("Kevin MacLeod - Beachfront Celebration.ogg", VOL_BGM_BEACHFRONT),
                ("Kevin MacLeod - Two Finger Johnny.ogg", VOL_BGM_TWO_FINGER),
                ("Kevin MacLeod - Vadodora.ogg", VOL_BGM_VADODORA)
            ]
                
        except Exception as e:
            print(f"Ses sistemi baslatilamadi: {e}")

    def start_drag_sound(self):
        if hasattr(self, 'ch_drag') and hasattr(self, 'sfx_drag') and self.sfx_drag:
            if not self.ch_drag.get_busy():
                self.ch_drag.play(self.sfx_drag, loops=-1)

    def stop_drag_sound(self):
        if hasattr(self, 'ch_drag'):
            self.ch_drag.stop()

    def play_snap_sound(self):
        if hasattr(self, 'ch_snap') and hasattr(self, 'sfx_snap') and self.sfx_snap:
            self.ch_snap.play(self.sfx_snap)

    def get_color_count_for_level(self, level):
        if level <= 10:
            return 3
        elif level <= 20:
            return 4
        elif level <= 30:
            return 5
        else:
            return 6

    def load_level(self, level):
        self.is_in_game = True
        self.undo_act.setEnabled(True)
        self.restart_level_act.setEnabled(True)
        self.music_label.setText("") # Müzik başlayana kadar temizle
        self.view.music_text = ""
        self.view.viewport().update()

        # Bölüm yüklenirken veya yeniden başlatilirken çalan müziği derhal sustur
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

        self.scene.clear()
        self.moves = 0
        self.history_stack.clear()
        self.move_label.setText(f"Moves: {self.moves}")
        self.level_label.setText(f"Level: {level} / 40")

        self.color_count = self.get_color_count_for_level(level)
        self.setup_board_geometry()
        self.draw_tracks()
        self.spawn_caps()

        self.fit_board_to_window()
        self.play_fade_in()

        # Bu bölumde hangi kanalların 4'lü tamamlandigini takip eden küme
        self.completed_columns = set()

        # Bölüm başu gazoz açılma sesini çal
        if hasattr(self, 'ch_opening') and hasattr(self, 'sfx_opening') and self.sfx_opening:
            self.ch_opening.play(self.sfx_opening)

        # Gazoz dökülme sesi duyulsun, 2 saniye sonra fon müziği girsin
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, self.start_bgm)

    def start_bgm(self):
        """Her bolumde siradaki fon muzigini dinamik olarak yukler ve baslatir."""
        try:
            if hasattr(self, 'bgm_playlist') and self.bgm_playlist:
                track_index = (self.current_level - 1) % len(self.bgm_playlist)
                track_name, track_vol = self.bgm_playlist[track_index]
                track_path = os.path.join(SOUNDS_DIR, track_name)

                # Parça isimlerini düzenli gösterim formatına eşle
                music_titles = {
                    "kevin_macleod_-_street_party.ogg": "Kevin MacLeod - Street Party",
                    "Kevin MacLeod - Dubakupado.ogg": "Kevin MacLeod - Dubakupado",
                    "Kevin MacLeod - Beachfront Celebration.ogg": "Kevin MacLeod - Beachfront Celebration",
                    "Kevin MacLeod - Two Finger Johnny.ogg": "Kevin MacLeod - Two Finger Johnny",
                    "Kevin MacLeod - Vadodora.ogg": "Kevin MacLeod - Vadodora"
                }

                if os.path.exists(track_path):
                    pygame.mixer.music.stop()
                    pygame.mixer.music.load(track_path)
                    pygame.mixer.music.set_volume(track_vol)
                    pygame.mixer.music.play(loops=-1) # Sonsuz dongu

                    # Parçanın besteci ve adını belirle
                    display_title = music_titles.get(track_name, track_name.rsplit('.', 1)[0])
                    self.music_label.setText(display_title) # Durum çubuğundaki
                    self.view.music_text = display_title    # Arka plan görselinin tam sağ altındaki
                    self.view.viewport().update()
        except Exception as e:
            print(f"Muzik calinamadi: {e}")

    def record_state(self):
        state = []
        for cap in self.caps:
            node_id = cap.current_node['id'] if cap.current_node else None
            state.append((cap, node_id))
        self.history_stack.append(state)

    def undo_move(self):
        if not self.history_stack or self.moves <= 0:
            return

        last_state = self.history_stack.pop()
        
        for node in self.grid_nodes:
            node['occupant'] = None

        for cap, node_id in last_state:
            target_node = next((n for n in self.grid_nodes if n['id'] == node_id), None)
            if target_node:
                cap.setPos(target_node['pos'])
                cap.current_node = target_node
                target_node['occupant'] = cap

        self.moves -= 1
        self.move_label.setText(f"Moves: {self.moves}")

    def setup_board_geometry(self):
        self.corridor_y = 120
        self.start_x = 80
        self.step = DIAMETER
        
        self.slot_x_positions = []
        for i in range(self.color_count):
            sx = self.start_x + (BUFFER_CAPS * self.step) + (i * self.step * 2)
            self.slot_x_positions.append(sx)

        self.end_x = self.slot_x_positions[-1] + (BUFFER_CAPS * self.step)
        self.corridor_width = self.end_x - self.start_x

        self.grid_nodes = []

        cur_x = self.start_x
        corr_idx = 0
        while cur_x <= self.end_x + 1:
            self.grid_nodes.append({
                'id': f"corr_{corr_idx}",
                'pos': QPointF(cur_x, self.corridor_y),
                'occupant': None,
                'is_corridor': True,
                'col': None,
                'row': None
            })
            cur_x += self.step
            corr_idx += 1

        for col_idx, sx in enumerate(self.slot_x_positions):
            for row in range(SLOT_DEPTH):
                sy = self.corridor_y + ((row + 1) * self.step)
                self.grid_nodes.append({
                    'id': f"slot_{col_idx}_{row}",
                    'pos': QPointF(sx, sy),
                    'occupant': None,
                    'is_corridor': False,
                    'col': col_idx,
                    'row': row
                })

        # Bombelerin ve konturların tam görünmesi için genişletilmiş güvenli paylar:
        pad_x = 38       # 24 -> 38 (Sağ ve sol bombelerin kırpılmasını tamamen önler)
        pad_top = 45
        pad_bottom = 35

        min_x = self.start_x - pad_x
        min_y = self.corridor_y - (self.step / 2) - pad_top
        
        total_w = self.corridor_width + (pad_x * 2)
        total_h = (SLOT_DEPTH * self.step) + (self.step / 2) + pad_top + pad_bottom

        self.scene.setSceneRect(min_x, min_y, total_w, total_h)

    def draw_tracks(self):
        """Gercek macOS Akrilik Buzlu Cam (Sifir Kontur, Saf Bulanik Zemin)"""
        # Raylarin geometrik yolu
        track_path = QPainterPath()
        track_path.moveTo(self.start_x, self.corridor_y)
        track_path.lineTo(self.end_x, self.corridor_y)

        max_y = self.corridor_y + (SLOT_DEPTH * self.step)
        for sx in self.slot_x_positions:
            track_path.moveTo(sx, self.corridor_y)
            track_path.lineTo(sx, max_y)

        # Arka plan resmini kullanarak tam ray şeklinde bulanık cam pixmap'ı üret
        s_rect = self.scene.sceneRect()
        bg_pix = getattr(self.view, 'bg_pixmap', None)
        frosted_pixmap = generate_frosted_track_pixmap(bg_pix, s_rect, track_path, TRACK_WIDTH)

        if frosted_pixmap:
            glass_item = self.scene.addPixmap(frosted_pixmap)
            glass_item.setPos(s_rect.x(), s_rect.y())
            glass_item.setZValue(1) # Kapakların tam altında, arka planın üstünde

    def spawn_caps(self):
        self.caps = []
        slot_nodes = [n for n in self.grid_nodes if not n['is_corridor']]
        
        pixmap_cache = {}
        for color_id in range(self.color_count):
            file_name = CAP_FILES[color_id]
            file_path = os.path.join(CAPS_DIR, file_name)
            pix = QPixmap(file_path)
            
            if pix.isNull():
                pix = QPixmap(DIAMETER, DIAMETER)
                pix.fill(Qt.GlobalColor.gray)
            else:
                pix = sharpen_image(pix)
                
            pixmap_cache[color_id] = pix

        color_pool = []
        for color_id in range(self.color_count):
            color_pool.extend([color_id] * SLOT_DEPTH)

        random.seed(self.current_level * 105)
        random.shuffle(color_pool)

        for i, node in enumerate(slot_nodes):
            color_id = color_pool[i]
            cap = CapItem(pixmap_cache[color_id], color_id, self)
            
            cap.setPos(node['pos'])
            cap.current_node = node
            node['occupant'] = cap
            
            self.scene.addItem(cap)
            self.caps.append(cap)

    def can_pick_up(self, cap):
        node = cap.current_node
        if not node:
            return True
        if node['is_corridor']:
            return True
        
        col = node['col']
        current_row = node['row']
        
        # 1. Kendi kanalında üstünde başka kapak var mı?
        for r in range(current_row):
            above_node = next((n for n in self.grid_nodes if not n['is_corridor'] and n['col'] == col and n['row'] == r), None)
            if above_node and above_node['occupant'] is not None:
                return False

        # 2. KRITIK KONTROL: Kanalın tam agzinda (koridorda) duran bir kapak var mı?
        # Eğer çukurun ağzı tıkalıysa, içerideki kapak yukarı atlayıp çıkamaz!
        col_x = self.slot_x_positions[col]
        mouth_node = next((n for n in self.grid_nodes if n['is_corridor'] and abs(n['pos'].x() - col_x) < 5), None)
        if mouth_node and mouth_node['occupant'] is not None:
            return False

        return True

    def prepare_drag_limits(self, cap):
        """Koridorda veya kanal agzinda bekleyen diger kapaklari asilamaz duvar yapar."""
        # Koridordaki ve kanal ağzına çok yakın (Y ekseninde hafif sarkan) diğer kapaklar
        other_caps_x = [
            c.pos().x() for c in self.caps 
            if c != cap and c.pos().y() <= (self.corridor_y + (self.step * 0.6))
        ]
        
        cap_x = cap.pos().x()

        # Sol taraf engelleri
        left_obstacles = [x for x in other_caps_x if x < cap_x - 5]
        self.drag_min_x = (max(left_obstacles) + self.step) if left_obstacles else self.start_x

        # Sağ taraf engelleri
        right_obstacles = [x for x in other_caps_x if x > cap_x + 5]
        self.drag_max_x = (min(right_obstacles) - self.step) if right_obstacles else self.end_x

    def clamp_to_track(self, cap, pos):
        raw_x = pos.x()
        raw_y = pos.y()

        min_x = getattr(self, 'drag_min_x', self.start_x)
        max_x = getattr(self, 'drag_max_x', self.end_x)
        max_y = self.corridor_y + (SLOT_DEPTH * self.step)

        # Kapak yatayda engelleri (aradaki diğer kapakları) ASLA AŞAMAZ!
        clamped_x = max(min_x, min(raw_x, max_x))

        closest_sx = min(self.slot_x_positions, key=lambda val: abs(val - clamped_x))
        dist_to_slot = abs(closest_sx - clamped_x)
        closest_col_idx = self.slot_x_positions.index(closest_sx)

        # 1. Kanal, kapağın ulaşabileceği menzil sınırları içinde mi? (Engel arkasındaki kanala atlayamaz)
        can_reach_slot = (min_x - 5 <= closest_sx <= max_x + 5)

        # 2. Kanalın tam ağzında bekleyen başka bir kapak var mı? (Ağzı tıkalı kanala girilemez!)
        mouth_node = next((n for n in self.grid_nodes if n['is_corridor'] and abs(n['pos'].x() - closest_sx) < 5), None)
        mouth_is_blocked = (mouth_node and mouth_node['occupant'] not in (None, cap))

        # Yalnızca engeli aşmadan ulaşabiliyorsa ve kanal ağzı açıksa aşağı inmesine izin ver
        if can_reach_slot and not mouth_is_blocked and dist_to_slot < (self.step / 3) and raw_y > self.corridor_y:
            x = closest_sx
            col_caps = [
                n for n in self.grid_nodes 
                if not n['is_corridor'] and n['col'] == closest_col_idx and n['occupant'] not in (None, cap)
            ]
            if col_caps:
                min_occupied_row = min(n['row'] for n in col_caps)
                limit_y = self.corridor_y + (min_occupied_row * self.step)
                y = min(limit_y, max(self.corridor_y, raw_y))
            else:
                y = min(max_y, max(self.corridor_y, raw_y))
        else:
            y = self.corridor_y
            x = clamped_x

        return QPointF(x, y)

    def snap_to_best_grid(self, cap):
        cap_pos = cap.pos()

        old_node = cap.current_node
        if old_node:
            old_node['occupant'] = None

        target_node = None

        closest_col_idx = min(
            range(self.color_count),
            key=lambda c_idx: abs(self.slot_x_positions[c_idx] - cap_pos.x())
        )
        dist_to_slot_x = abs(self.slot_x_positions[closest_col_idx] - cap_pos.x())

        column_nodes = [
            n for n in self.grid_nodes 
            if not n['is_corridor'] and n['col'] == closest_col_idx
        ]
        column_nodes.sort(key=lambda n: n['row'])
        has_empty_in_column = any(n['occupant'] is None for n in column_nodes)

        # Dikey kanal ağzına yakınlık: Yarım kapak mesafesi
        is_near_column = dist_to_slot_x < (self.step * 0.5)
        is_dragged_down = cap_pos.y() > (self.corridor_y + 5)

        # 1. MUTLAK KURAL: Kanal ağzında bırakıldıysa ve kanalda bosluk varsa KESiNLiKLE AşAğI DüşüR!
        # (Hiçbir orta tepe kuralı veya koridor mıknatısı bu kuralı ezemez)
        if (is_near_column or is_dragged_down) and has_empty_in_column:
            for node in reversed(column_nodes):
                if node['occupant'] is None:
                    target_node = node
                    break
        else:
            # 2. KORİDORDA AKILLI ÇEKİM MANTIĞI
            corridor_nodes = [n for n in self.grid_nodes if n['is_corridor']]
            corridor_nodes.sort(key=lambda n: n['pos'].x())

            board_mid_x = (self.start_x + self.end_x) / 2
            
            # ORTA TEPE KURALI: Sadece ve sadece tam ortadaki iki kanal arasındaki TEPEYE denk geliyorsa!
            # Tolerans daraltildi (0.8 -> 0.45), boylece komşu kanalların ağzını asla gasp edemez.
            is_even_columns = (self.color_count % 2 == 0)
            is_near_center_peak = abs(cap_pos.x() - board_mid_x) <= (self.step * 0.45)

            if is_even_columns and is_near_center_peak:
                empty_nodes = [n for n in corridor_nodes if n['occupant'] is None]
                if empty_nodes:
                    target_node = min(empty_nodes, key=lambda n: abs(n['pos'].x() - board_mid_x))
                else:
                    target_node = old_node

            # DİĞER DURUMLAR: OTOMATİK SOLA VEYA SAĞA ÇEKİLME
            elif cap_pos.x() < board_mid_x:
                target_node = None
                # En soldan başlayarak ilk boş koridor yuvasına çek
                for node in corridor_nodes:
                    if node['occupant'] is None:
                        target_node = node
                        break
                if target_node is None:
                    for node in reversed(corridor_nodes):
                        if node['occupant'] is None:
                            target_node = node
                            break
            else:
                target_node = None
                # En sağdan başlayarak ilk boş koridor yuvasına çek
                for node in reversed(corridor_nodes):
                    if node['occupant'] is None:
                        target_node = node
                        break
                if target_node is None:
                    for node in corridor_nodes:
                        if node['occupant'] is None:
                            target_node = node
                            break

            if target_node is None:
                target_node = old_node

        if target_node is None:
            target_node = old_node

        cap.setPos(target_node['pos'])
        target_node['occupant'] = cap
        
        if target_node != old_node:
            self.moves += 1
            self.move_label.setText(f"Moves: {self.moves}")
            self.play_snap_sound() # Yuvaya oturduğunda klik sesini tetikletiyrouz.
        else:
            if self.history_stack:
                self.history_stack.pop()
        
        cap.current_node = target_node

        # Kapağı bıraktıktan sonra kanal ağzında veya havada asılı kalan kapak varsa aşağı düşür
        self.apply_gravity()

    def apply_gravity(self):
        """Kanal ağzında veya havada asılı kalan kapakları yerçekimiyle en alt boşluğa düşürür."""
        for col_idx in range(self.color_count):
            col_x = self.slot_x_positions[col_idx]
            column_nodes = [
                n for n in self.grid_nodes 
                if not n['is_corridor'] and n['col'] == col_idx
            ]
            column_nodes.sort(key=lambda n: n['row'])

            # 1. Sütun içindeki boşlukları kapat (aradaki boşluklara üstteki kapakları düşür)
            for r in range(SLOT_DEPTH - 1, 0, -1):
                target = column_nodes[r]
                if target['occupant'] is None:
                    for above_r in range(r - 1, -1, -1):
                        source = column_nodes[above_r]
                        if source['occupant'] is not None:
                            moving_cap = source['occupant']
                            source['occupant'] = None
                            target['occupant'] = moving_cap
                            moving_cap.current_node = target
                            moving_cap.setPos(target['pos'])
                            break

            # 2. Kanal ağzında (koridorda) bekleyen kapak varsa ve kanalda yer varsa aşağı düşür
            empty_slots = [n for n in reversed(column_nodes) if n['occupant'] is None]
            if empty_slots:
                mouth_node = next(
                    (n for n in self.grid_nodes if n['is_corridor'] and abs(n['pos'].x() - col_x) < 5), 
                    None
                )
                if mouth_node and mouth_node['occupant'] is not None:
                    falling_cap = mouth_node['occupant']
                    target_slot = empty_slots[0]
                    mouth_node['occupant'] = None
                    target_slot['occupant'] = falling_cap
                    falling_cap.current_node = target_slot
                    falling_cap.setPos(target_slot['pos'])

    def is_all_completed(self):
        """Tum bolumun bitip bitmedigini sessizce denetler."""
        # Koridorda kapak varsa bitmemiştir
        if any(n['occupant'] is not None for n in self.grid_nodes if n['is_corridor']):
            return False
        # Tüm kanallar tek renk dolu mu?
        for col_idx in range(self.color_count):
            col_caps = [n['occupant'] for n in self.grid_nodes if not n['is_corridor'] and n['col'] == col_idx]
            if len(col_caps) != SLOT_DEPTH or any(c is None for c in col_caps):
                return False
            if not all(c.color_id == col_caps[0].color_id for c in col_caps):
                return False
        return True

    def flash_column_caps(self, caps):
        """Dortlenen kapaklari 3 kez hizlica beyaz yakip sondurur (Asla cokmeyen guvenli flas)."""
        from PyQt6.QtCore import QTimer
        
        # Her kapağın tam üzerine beyaz yarım-saydam parıltı diskleri yerleştir
        overlays = []
        r = DIAMETER / 2
        for cap in caps:
            pos = cap.pos()
            # Beyaz parilti diski
            ov = self.scene.addEllipse(
                pos.x() - r, pos.y() - r, DIAMETER, DIAMETER,
                QPen(Qt.PenStyle.NoPen),
                QBrush(QColor(255, 255, 255, 220)) # Parlak Saf Beyaz
            )
            ov.setZValue(35) # Kapağın hemen üstünde
            ov.setVisible(False)
            overlays.append(ov)

        # 3 Kez Aç-Kapa Zamanlaması (ms)
        def set_flash_visible(state):
            for ov in overlays:
                ov.setVisible(state)

        def cleanup_flash():
            for ov in overlays:
                if ov.scene():
                    self.scene.removeItem(ov)

        # 3 Flaş Darbesi
        QTimer.singleShot(50, lambda: set_flash_visible(True))   # 1. Aç
        QTimer.singleShot(130, lambda: set_flash_visible(False)) # 1. Kapa
        QTimer.singleShot(210, lambda: set_flash_visible(True))  # 2. Aç
        QTimer.singleShot(290, lambda: set_flash_visible(False)) # 2. Kapa
        QTimer.singleShot(370, lambda: set_flash_visible(True))  # 3. Aç
        QTimer.singleShot(450, cleanup_flash)                    # 3. Kapa ve Sahneden Sil

    def check_column_completions(self):
        """Bir kanalda 4 ayni renk tamamlandiginda 3 kez flas yapar ve ozel ses calar."""
        is_game_won = self.is_all_completed()

        for col_idx in range(self.color_count):
            if col_idx in self.completed_columns:
                continue

            col_caps = [
                n['occupant'] for n in self.grid_nodes 
                if not n['is_corridor'] and n['col'] == col_idx
            ]
            
            if len(col_caps) == SLOT_DEPTH and all(c is not None for c in col_caps):
                first_color = col_caps[0].color_id
                if all(c.color_id == first_color for c in col_caps):
                    self.completed_columns.add(col_idx)

                    # 1. Kapakları 3 kez hızla beyaz parlat (Flaş)
                    self.flash_column_caps(col_caps)

                    # 2. Bölüm bittiyse müzik çakışmasını önle, bitmediyse zafer sesini çal
                    if not is_game_won:
                        if hasattr(self, 'ch_col_win') and hasattr(self, 'sfx_col_win') and self.sfx_col_win:
                            self.ch_col_win.play(self.sfx_col_win)

    def check_win_condition(self):
        for node in self.grid_nodes:
            if node['is_corridor'] and node['occupant'] is not None:
                return

        for col_idx in range(self.color_count):
            col_caps = [
                n['occupant'] for n in self.grid_nodes 
                if not n['is_corridor'] and n['col'] == col_idx
            ]
            
            if any(c is None for c in col_caps):
                return
            
            first_color = col_caps[0].color_id
            if not all(c.color_id == first_color for c in col_caps):
                return

        self.level_completed()

    def level_completed(self):
        # 1. Kapakları dondur ve TÜM KANALLARI AYNI ANDA 3 KEZ BEYAZ PARLAT (Zafer Flaşı!)
        for cap in self.caps:
            cap.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        
        self.flash_column_caps(self.caps)

        # 2. Fon müziğini derhal sustur
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

        # 3. Bölum zafer sesini tek başina çal
        if hasattr(self, 'ch_game_win') and hasattr(self, 'sfx_level_win') and self.sfx_level_win:
            self.ch_game_win.play(self.sfx_level_win)

        s_rect = self.scene.sceneRect()
        cx = s_rect.center().x()
        cy = s_rect.center().y()

        panel_w = min(s_rect.width() * 0.75, 270)
        panel_h = 105
        panel_rect = QRectF(cx - (panel_w / 2), cy - (panel_h / 2), panel_w, panel_h)

        panel_path = QPainterPath()
        panel_path.addRoundedRect(panel_rect, 12, 12)

        panel = self.scene.addPath(
            panel_path,
            QPen(QColor(255, 255, 255, 60), 1.2),
            QBrush(QColor(20, 24, 30, 230))
        )
        panel.setZValue(90)

        title = QGraphicsTextItem("CONGRATULATIONS!")
        title.setFont(QFont("Ubuntu", 18, QFont.Weight.Bold))
        title.setDefaultTextColor(QColor("#F4D03F"))
        title.setZValue(91)
        t_bound = title.boundingRect()
        title.setPos(cx - (t_bound.width() / 2), panel_rect.top() + 10)
        self.scene.addItem(title)

        sub = QGraphicsTextItem(f"Level {self.current_level} Completed!")
        sub.setFont(QFont("Ubuntu", 12, QFont.Weight.Medium))
        sub.setDefaultTextColor(QColor("#2ECC71"))
        sub.setZValue(91)
        s_bound = sub.boundingRect()
        sub.setPos(cx - (s_bound.width() / 2), panel_rect.top() + 45)
        self.scene.addItem(sub)

        info = QGraphicsTextItem(f"Total Moves: {self.moves}")
        info.setFont(QFont("Ubuntu", 9))
        info.setDefaultTextColor(QColor("#BDC3C7"))
        info.setZValue(91)
        i_bound = info.boundingRect()
        info.setPos(cx - (i_bound.width() / 2), panel_rect.top() + 72)
        self.scene.addItem(info)

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1500, self.play_fade_out_and_next)

    def play_fade_in(self):
        rect = self.scene.sceneRect()
        overlay = FadeOverlay(rect)
        self.scene.addItem(overlay)
        
        self._fade_anim = QPropertyAnimation(overlay, b"fade_opacity")
        self._fade_anim.setDuration(800)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(lambda: self.scene.removeItem(overlay))
        self._fade_anim.start()

    def play_fade_out_and_next(self):
        rect = self.scene.sceneRect()
        overlay = FadeOverlay(rect)
        self.scene.addItem(overlay)

        self._fade_anim = QPropertyAnimation(overlay, b"fade_opacity")
        self._fade_anim.setDuration(900)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.finished.connect(self.go_next_level)
        self._fade_anim.start()

    def go_next_level(self):
        if self.current_level < 40:
            self.current_level += 1
            self.load_level(self.current_level)
        else:
            self.show_game_finished_screen()

    def show_game_finished_screen(self):
        """Kutusuz, doğrudan havai fişek gökyüzüne basılan ferah bitiş ekranı"""
        self.is_in_game = False
        self.view.is_black_screen = True # Tüm pencereyi yüzde yüz simsiyah yap
        self.view.viewport().update()
        self.undo_act.setEnabled(False)
        self.restart_level_act.setEnabled(False)

        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

        # Zafer Fanfarı
        if hasattr(self, 'ch_game_win') and hasattr(self, 'sfx_game_win') and self.sfx_game_win:
            self.ch_game_win.play(self.sfx_game_win)

        self.scene.clear()
        self.level_label.setText("Game Completed!")
        self.move_label.setText("")

        win_w, win_h = 850, 600
        self.scene.setSceneRect(0, 0, win_w, win_h)
        cx = win_w / 2

        # 1. Deep Black Sky Background
        bg_black = self.scene.addRect(0, 0, win_w, win_h, QPen(Qt.PenStyle.NoPen), QBrush(QColor("#08090C")))
        bg_black.setZValue(0)

        # 2. Text Drawn Directly on the Sky
        t1 = QGraphicsTextItem("Congratulations! You beat the game!")
        t1.setFont(QFont("Ubuntu", 25, QFont.Weight.Bold))
        t1.setDefaultTextColor(QColor("#F4D03F"))
        t1.setZValue(50)
        t1.setPos(cx - (t1.boundingRect().width() / 2), 120)
        self.scene.addItem(t1)

        t2 = QGraphicsTextItem("That's enough gaming for now.")
        t2.setFont(QFont("Ubuntu", 17, QFont.Weight.DemiBold))
        t2.setDefaultTextColor(QColor("#E74C3C"))
        t2.setZValue(50)
        t2.setPos(cx - (t2.boundingRect().width() / 2), 195)
        self.scene.addItem(t2)

        t3 = QGraphicsTextItem("Too much gaming can be harmful to mental health.")
        t3.setFont(QFont("Ubuntu", 14, QFont.Weight.Medium))
        t3.setDefaultTextColor(QColor("#BDC3C7"))
        t3.setZValue(50)
        t3.setPos(cx - (t3.boundingRect().width() / 2), 255)
        self.scene.addItem(t3)

        t4 = QGraphicsTextItem("Thanks for playing!")
        t4.setFont(QFont("Ubuntu", 18, QFont.Weight.Bold))
        t4.setDefaultTextColor(QColor("#2ECC71"))
        t4.setZValue(50)
        t4.setPos(cx - (t4.boundingRect().width() / 2), 320)
        self.scene.addItem(t4)

        # 3. Simple Single "Main Menu" Button
        btn_main = SimpleMenuButton("Main Menu", self.show_main_menu)
        btn_main.setPos(cx, 425)
        btn_main.setZValue(60)
        self.scene.addItem(btn_main)

        # 4. Arka Planda Süzülen Havai Fişek Motoru
        from PyQt6.QtCore import QTimer
        self.particles = []
        self.firework_tick = 0
        self.firework_timer = QTimer(self)
        self.firework_timer.timeout.connect(self._tick_fireworks)
        self.firework_timer.start(30)

        self.fit_board_to_window()

    def _tick_fireworks(self):
        """Havai fişek parçacıklarını hareket ettirir"""
        self.firework_tick += 1

        if self.firework_tick % 18 == 0:
            burst_x = random.uniform(90, 760)
            burst_y = random.uniform(60, 380)
            palette = [
                QColor("#FF4757"), QColor("#2ED573"), QColor("#FFA502"),
                QColor("#1E90FF"), QColor("#9B59B6"), QColor("#F1C40F"),
                QColor("#00D2D3"), QColor("#FFFFFF")
            ]
            c = random.choice(palette)

            for _ in range(26):
                ang = random.uniform(0, 2 * math.pi)
                spd = random.uniform(1.8, 5.2)
                dot = self.scene.addEllipse(-2, -2, 4, 4, QPen(Qt.PenStyle.NoPen), QBrush(c))
                dot.setPos(burst_x, burst_y)
                dot.setZValue(15)
                self.particles.append({
                    'item': dot, 'x': burst_x, 'y': burst_y,
                    'vx': math.cos(ang) * spd, 'vy': math.sin(ang) * spd,
                    'life': 1.0, 'decay': random.uniform(0.018, 0.035)
                })

        survivors = []
        for p in self.particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.07
            p['life'] -= p['decay']

            if p['life'] > 0:
                p['item'].setPos(p['x'], p['y'])
                p['item'].setOpacity(p['life'])
                survivors.append(p)
            else:
                if p['item'].scene():
                    self.scene.removeItem(p['item'])

        self.particles = survivors


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    if "Breeze" in [s for s in QApplication.style().name()]:
        app.setStyle("Breeze")
        
    window = GameWindow()
    window.show()
    sys.exit(app.exec())