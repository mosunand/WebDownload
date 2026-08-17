"""全局 QSS 样式表(iOS 风深色玻璃)。"""

QSS = """
/* ---------- 输入框 ---------- */
QLineEdit {
    background: rgba(255, 255, 255, 38);
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 10px;
    padding: 8px 12px;
    color: #ECECEE;
    font-size: 13px;
    selection-background-color: #4dabf7;
}
QLineEdit::placeholder { color: rgba(255, 255, 255, 130); }
QLineEdit:focus {
    border: 1px solid #4dabf7;
    background: rgba(255, 255, 255, 48);
}
QLineEdit:disabled {
    color: rgba(255, 255, 255, 90);
    background: rgba(255, 255, 255, 15);
}

/* ---------- 数字框 ---------- */
QSpinBox {
    background: rgba(255, 255, 255, 38);
    border: 1px solid rgba(255, 255, 255, 50);
    border-radius: 10px;
    padding: 6px 10px;
    color: #ECECEE;
    font-size: 13px;
}
QSpinBox:focus { border: 1px solid #4dabf7; }
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    background: rgba(255, 255, 255, 18);
    border: none;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: rgba(255, 255, 255, 40);
}

/* ---------- 标签 ---------- */
QLabel {
    color: rgba(255, 255, 255, 222);
    font-size: 13px;
    background: transparent;
}
QLabel#statusLabel {
    color: rgba(255, 255, 255, 178);
    font-size: 12px;
}
QLabel#hintLabel {
    color: rgba(255, 255, 255, 150);
    font-size: 12px;
}
QLabel#dialogTitle {
    color: rgba(255, 255, 255, 235);
    font-size: 17px;
    font-weight: 700;
}
/* 底部信息栏 */
QLabel#footerLabel {
    color: rgba(255, 255, 255, 105);
    font-size: 11px;
}
/* 资源计数胶囊 */
QLabel#countLabel {
    color: #6ec1ff;
    background: rgba(77, 171, 247, 50);
    border: 1px solid rgba(77, 171, 247, 75);
    border-radius: 10px;
    padding: 1px 8px;
    font-size: 11px;
    font-weight: 700;
}

/* ---------- 进度条 ---------- */
QProgressBar {
    background: rgba(255, 255, 255, 35);
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #6ec1ff, stop:1 #4dabf7);
    border-radius: 5px;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 60);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 100);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 60);
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ---------- 工具提示 ---------- */
QToolTip {
    background: rgba(28, 28, 36, 245);
    color: #ECECEE;
    border: 1px solid rgba(255, 255, 255, 45);
    border-radius: 8px;
    padding: 6px 8px;
}

/* ---------- 文件对话框内部按钮(尽量贴合,系统原生部分不可控) ---------- */
QFileDialog QPushButton {
    background: rgba(255, 255, 255, 20);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 8px;
    padding: 6px 14px;
    color: #ECECEE;
}
"""
