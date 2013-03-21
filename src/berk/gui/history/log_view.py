from berk.gui import busy_cursor, View
from berk.gui.history import create_log_graph, LogGraphModel, LogGraphDelegate

from PySide.QtCore import Qt

class LogView(View):
    preferred_dock_area = Qt.RightDockWidgetArea

    def __init__(self, repo, files=(), revs=(), all=False):
        super(LogView, self).__init__()
        self.repo = repo
        self.paths = [str(f) for f in files]
        self.revs = revs
        self.all = all

    def create_ui(self):
        super(LogView, self).create_ui()
        with busy_cursor():
            self.graph_model = LogGraphModel(self.repo, paths=self.paths,
                revs=self.revs, all=self.all, parent=self)
        self.graph_table.setItemDelegate(LogGraphDelegate())
        self.log_filter.source_model = self.graph_model
        self.log_filter.viewer = self.graph_table
