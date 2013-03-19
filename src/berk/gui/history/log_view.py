from berk.gui import busy_cursor, FilterModel, View
from berk.gui.history import create_log_graph, commit_matches_text, \
    LogGraphModel, LogGraphDelegate

from PySide.QtCore import Qt

class LogView(View):
    preferred_dock_area = Qt.RightDockWidgetArea

    def __init__(self, repo, files=(), revs=(), all=True):
        super(LogView, self).__init__()
        self.repo = repo
        self.paths = [str(f) for f in files]
        self.revs = revs
        self.all = all

    def create_ui(self):
        super(LogView, self).create_ui()
        with busy_cursor():
            self.graph_model = LogGraphModel(self.repo,
                lambda: create_log_graph(self.repo,
                    self.repo.log(paths=self.paths, revs=self.revs,
                        all=self.all)))
        self.filter_model = FilterModel()
        self.filter_model.setSourceModel(self.graph_model)
        self.default_delegate = self.graph_table.itemDelegate()
        self.graph_delegate = LogGraphDelegate()
        self.graph_table.setModel(self.filter_model)
        self.graph_table.setItemDelegate(self.graph_delegate)
        self.filter_text.textEdited.connect(self.filter_text_edited)

    def filter_text_edited(self, text):
        if text:
            self.graph_table.hideColumn(0)
            self.filter_model.filters += self.filter_graph_row
        else:
            self.filter_model.filters -= self.filter_graph_row
            self.graph_table.showColumn(0)

    def filter_graph_row(self, graph_row):
        return commit_matches_text(graph_row.log_entry, self.filter_text.text())
