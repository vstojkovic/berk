from berk.gui import connect_destructor, Dialog, FilterModel, model_item

from PySide.QtCore import QAbstractTableModel, Qt
from PySide.QtGui import QDialogButtonBox


class PickBranchesDialog(Dialog):
    def __init__(self, repo, parent=None):
        super(PickBranchesDialog, self).__init__(parent=parent)
        self.repo = repo
        self.branch_model = BranchModel(repo, checkable=True, parent=self)
        self.filter_model = FilterModel(parent=self)
        self.filter_model.setSourceModel(self.branch_model)
        self.branch_list.setModel(self.filter_model)
        self.filter_text.textEdited.connect(self.filter_text_edited)
        self.branch_model.dataChanged.connect(self.branch_toggled)
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    @property
    def selected_branches(self):
        return self.branch_model.checked_branches

    def filter_text_edited(self, text):
        if text:
            self.filter_model.filters += self.filter_branch
        else:
            self.filter_model.filters -= self.filter_branch

    def branch_toggled(self, top_left, bottom_right):
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(bool(
            self.branch_model.checked_branches))

    def filter_branch(self, branch):
        return self.filter_text.text() in str(branch)


class BranchModel(QAbstractTableModel):
    column_getters = [str]

    def __init__(self, repo, checkable=False, parent=None):
        super(BranchModel, self).__init__(parent=parent)
        connect_destructor(self)
        self.repo = repo
        self.column_names = [self.tr('Name')]
        self.checked_branches = set()
        self._checkable = checkable
        self.repo.workspace.before_repo_refreshed += self.before_repo_refreshed
        self.repo.workspace.repo_refreshed += self.repo_refreshed

    def _destroyed(self):
        self.repo.workspace.before_repo_refreshed -= self.before_repo_refreshed
        self.repo.workspace.repo_refreshed -= self.repo_refreshed

    def model_item(self, index):
        if not index.isValid(): return None
        return self.repo.branches[index.row()]

    @property
    def checkable(self):
        return self._checkable

    @checkable.setter
    def checkable(self, value):
        self._checkable = value
        self.dataChanged.emit(self.createIndex(0, 0, None),
            self.createIndex(len(self.repo.branches) - 1, 0, None))

    def before_repo_refreshed(self, repo):
        if repo is self.repo: self.beginResetModel()

    def repo_refreshed(self, repo):
        if repo is self.repo: self.endResetModel()

    def rowCount(self, parent):
        return len(self.repo.branches)

    def columnCount(self, parent):
        return len(self.column_names)

    def flags(self, index):
        result = super(BranchModel, self).flags(index)
        if self.checkable and index.column() == 0:
            result |= Qt.ItemIsUserCheckable
        return result

    def data(self, index, role):
        if not index.isValid():
            return None
        item = model_item(index)
        if role == Qt.DisplayRole:
            return self.column_getters[index.column()](item)
        if role == Qt.CheckStateRole:
            if index.column() > 0:
                return None
            item = model_item(index)
            return Qt.Checked if item in self.checked_branches else Qt.Unchecked

    def setData(self, index, value, role):
        if role != Qt.CheckStateRole or index.column() > 0: return False
        item = model_item(index)
        if item in self.checked_branches:
            self.checked_branches.remove(item)
        else:
            self.checked_branches.add(item)
        self.dataChanged.emit(index, index)
        return True

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.column_names[section]
