from berk.model import Repo
from berk.gui import connect_destructor, View
from berk.gui import model_item

from PySide.QtCore import QAbstractItemModel, QModelIndex, Qt
from PySide.QtGui import QApplication, QItemSelectionModel, QStyle


class DirectoryModel(QAbstractItemModel):
    def __init__(self, workspace, parent=None):
        super(DirectoryModel, self).__init__(parent=parent)
        connect_destructor(self)
        self.workspace = workspace
        self.header_text = self.tr('Name')
        self.workspace.before_repo_added += self.before_repo_added
        self.workspace.repo_added += self.repo_added
        self.workspace.before_repo_refreshed += self.before_repo_refreshed
        self.workspace.repo_refreshed += self.repo_refreshed

    def _destroyed(self):
        self.workspace.before_repo_added -= self.before_repo_added
        self.workspace.repo_added -= self.repo_added
        self.workspace.before_repo_refreshed -= self.before_repo_refreshed
        self.workspace.repo_refreshed -= self.repo_refreshed

    def model_item(self, index):
        return index.internalPointer()

    def before_repo_added(self):
        idx = len(self.workspace.repos)
        self.beginInsertRows(QModelIndex(), idx, idx)

    def repo_added(self):
        self.endInsertRows()

    def before_repo_refreshed(self, repo):
        self.beginResetModel()

    def repo_refreshed(self, repo):
        self.endResetModel()

    def rowCount(self, parent):
        if not parent.isValid():
            return len(self.workspace.repos)
        parent_dir = model_item(parent)
        return len(parent_dir.dirs) if parent_dir else 0

    def columnCount(self, parent):
        return 1

    def index(self, row, column, parent):
        if column >= 1:
            return QModelIndex()
        if not parent.isValid():
            if row >= len(self.workspace.repos):
                return QModelIndex()
            return self.createIndex(row, column, self.workspace.repos[row])
        parent_dir = model_item(parent)
        if row >= len(parent_dir.dirs):
            return QModelIndex()
        return self.createIndex(row, column, parent_dir.dirs[row])

    def item_index(self, item):
        if item is None:
            return QModelIndex()
        if not item.parent:
            row = self.workspace.repos.index(item)
        else:
            row = item.parent.dirs.index(item)
        return self.createIndex(row, 0, item)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        return self.item_index(model_item(index).parent)

    def data(self, index, role):
        if not index.isValid():
            return None
        item = model_item(index)
        if role == Qt.DisplayRole:
            if isinstance(item, Repo):
                return item.os_path
            return item.name or item.os_path
        if role == Qt.DecorationRole:
            if index.column() > 0:
                return None
            return QApplication.style().standardIcon(QStyle.SP_DirIcon)

    def flags(self, index):
        if not index.isValid():
            return 0
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return str(section)
        return self.header_text


class DirectoryView(View):
    def create_ui(self):
        super(DirectoryView, self).create_ui()
        self.dir_model = DirectoryModel(self.app.workspace, parent=self)
        self.directory_tree.setModel(self.dir_model)
        self._refresh_sel_path = None
        # We must assign the selection model to a variable, to avoid triggering
        # a segfault bug (temporary PyObject* destroyed prematurely)
        # see https://bugreports.qt-project.org/browse/PYSIDE-79
        selection_model = self.directory_tree.selectionModel()
        selection_model.currentChanged.connect(self.dir_selected)
        self.app.view_focus_out[self] += self.lost_focus
        self.app.view_focus_in[self] += self.gained_focus
        self.app.workspace.before_repo_refreshed += self.before_repo_refreshed
        self.app.workspace.repo_refreshed += self.repo_refreshed

    def _destroyed(self):
        self.app.view_focus_out[self] -= self.lost_focus
        self.app.view_focus_in[self] -= self.gained_focus
        self.app.workspace.before_repo_refreshed -= self.before_repo_refreshed
        self.app.workspace.repo_refreshed -= self.repo_refreshed

    def on_added_to_window(self):
        super(DirectoryView, self).on_added_to_window()
        if not self.parent().directory_view:
            self.parent().directory_view = self

    def on_removed_from_window(self):
        super(DirectoryView, self).on_removed_from_window()
        if self.parent().directory_view is self:
            self.parent().directory_view = None

    @property
    def selected_directory(self):
        return model_item(self.directory_tree.currentIndex())

    @selected_directory.setter
    def selected_directory(self, new_dir):
        if new_dir:
            index = self.dir_model.item_index(new_dir)
            self.directory_tree.scrollTo(index)
            self.directory_tree.selectionModel().setCurrentIndex(index,
                QItemSelectionModel.ClearAndSelect)
        else:
            self.directory_tree.selectionModel().setCurrentIndex(QModelIndex(),
                QItemSelectionModel.Clear)

    def _emit_selection_signals(self, item):
        if item:
            self.parent().current_item_changed.emit(item)
            self.parent().item_selection_changed.emit([item])
        else:
            self.parent().current_item_changed.emit(None)
            self.parent().item_selection_changed.emit([])

    def dir_selected(self, index, old_index):
        slave_view = self.parent().file_view
        if slave_view:
            directory = model_item(index)
            slave_view.directory = directory
        self._emit_selection_signals(model_item(index))

    def lost_focus(self, old, new):
        self._emit_selection_signals(None)

    def gained_focus(self, old, new):
        self._emit_selection_signals(self.selected_directory)

    def before_repo_refreshed(self, repo):
        directory = self.selected_directory
        if not directory:
            self._refresh_sel_path = None
        else:
            self._refresh_sel_path = (directory.repo, directory.path)

    def repo_refreshed(self, _=None):
        if not self._refresh_sel_path: return
        repo, path = self._refresh_sel_path
        self.selected_directory = repo.resolve(path)
