from PySide.QtCore import QFileInfo
from PySide.QtGui import QFileIconProvider

class FileIconProvider(object):
    def __init__(self):
        self.qt_provider = QFileIconProvider()

    def __getitem__(self, path):
        return self.qt_provider.icon(QFileInfo(path))
