from berk.gui import busy_cursor, FilterModel, model_item, setup_ui
from berk.gui.history import commit_matches_text, create_log_graph, \
    LogGraphDelegate, LogGraphModel

from PySide.QtGui import QDialog, QDialogButtonBox

class SelectCommitDialog(QDialog):
    def __init__(self, repo, files=(), revs=(), all=True, parent=None):
        super(SelectCommitDialog, self).__init__(parent=parent)
        self.repo = repo
        self.files = files
        self.revs = revs
        self.all = all
        setup_ui(self)
        if parent is not None:
            self.move(parent.geometry().center() - self.rect().center())
        with busy_cursor():
            self.graph_model = LogGraphModel(self.repo,
                lambda: create_log_graph(self.repo,
                    self.repo.log(paths=[f.path for f in self.files],
                    revs=self.revs, all=self.all)))
        self.filter_model = FilterModel()
        self.filter_model.setSourceModel(self.graph_model)
        self.default_delegate = self.graph_table.itemDelegate()
        self.graph_delegate = LogGraphDelegate()
        self.graph_table.setModel(self.filter_model)
        self.graph_table.setItemDelegate(self.graph_delegate)
        self.filter_text.textEdited.connect(self.filter_text_edited)
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        # We must assign the selection model to a variable, to avoid triggering
        # a segfault bug (temporary PyObject* destroyed prematurely)
        # see https://bugreports.qt-project.org/browse/PYSIDE-79
        selection_model = self.graph_table.selectionModel()
        selection_model.currentChanged.connect(self.commit_clicked)

    @property
    def selected_commit(self):
        selected_row = model_item(self.graph_table.currentIndex())
        return selected_row.log_entry if selected_row else None

    def filter_text_edited(self, text):
        if text:
            self.graph_table.hideColumn(0)
            self.filter_model.filters += self.filter_graph_row
        else:
            self.filter_model.filters -= self.filter_graph_row
            self.graph_table.showColumn(0)

    def filter_graph_row(self, graph_row):
        return commit_matches_text(graph_row.log_entry, self.filter_text.text())

    def commit_clicked(self, index, old_index):
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(bool(
            self.selected_commit))
