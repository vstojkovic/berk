from berk.gui import busy_cursor, model_item, setup_ui
from berk.gui.history import LogGraphDelegate, LogGraphModel

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
                paths=[f.path for f in self.files], revs=self.revs,
                all=self.all, parent=self)
        self.graph_table.setItemDelegate(LogGraphDelegate())
        self.log_filter.source_model = self.graph_model
        self.log_filter.viewer = self.graph_table
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

    def commit_clicked(self, index, old_index):
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(bool(
            self.selected_commit))
