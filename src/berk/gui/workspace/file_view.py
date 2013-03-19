import git_api

from berk.gui import connect_destructor, FileIconProvider, FilterModel, \
    model_item, View
from berk.gui.workspace import apply_status_to_icon, deep_file_list, \
    exclude_ignored, exclude_unmodified, exclude_untracked, shallow_file_list, \
    status_text

from PySide.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide.QtGui import QApplication, QStyle


class FileModel(QAbstractTableModel):
    column_getters = [
        lambda item: item.name,
        lambda item: status_text[item.index_status],
        lambda item: status_text[item.work_tree_status],
        lambda item: item.path,
    ]

    def __init__(self, workspace, parent=None):
        super(FileModel, self).__init__(parent=parent)
        connect_destructor(self)
        self.workspace = workspace
        self._file_source = None
        self._files = None
        self.column_names = [self.tr('Name'), self.tr('Index Status'),
            self.tr('Work Tree Status'), self.tr('Full Path')]
        self.icon_provider = FileIconProvider()
        workspace.item_updated += self.item_updated
        workspace.before_repo_refreshed += self.before_repo_refreshed
        workspace.repo_refreshed += self.repo_refreshed

    def _destroyed(self):
        self.workspace.item_updated -= self.item_updated
        self.workspace.before_repo_refreshed -= self.before_repo_refreshed
        self.workspace.repo_refreshed -= self.repo_refreshed

    @property
    def file_source(self):
        return self._file_source

    @file_source.setter
    def file_source(self, source):
        self._file_source = source
        self.refresh()

    @property
    def files(self):
        return self._files

    def refresh(self):
        self.beginResetModel()
        self._refresh_files()
        self.endResetModel()

    # To be overridden in subclasses
    def _refresh_files(self):
        files = self.file_source()
        self._files = tuple(files) if files else None

    def model_item(self, index):
        if not (self.files and index.isValid()): return None
        return self.files[index.row()]

    def item_is_mine(self, item):
        return item and self.files and item in self.files

    def item_index(self, item, column=0):
        if not self.item_is_mine(item):
            return QModelIndex()
        return self.createIndex(self.files.index(item), column, None)

    def item_updated(self, item):
        if not self.item_is_mine(item): return
        self.dataChanged.emit(self.item_index(item),
            self.item_index(item, len(self.column_names)))

    def before_repo_refreshed(self, repo):
        if self.files and any(file.repo is repo for file in self.files):
            self.beginResetModel()

    def repo_refreshed(self, repo):
        if self.files and any(file.repo is repo for file in self.files):
            self._refresh_files()
            self.endResetModel()

    def rowCount(self, parent):
        if not self.files: return 0
        return len(self.files)

    def columnCount(self, parent):
        return len(self.column_names)

    def data(self, index, role):
        if not index.isValid():
            return None
        item = model_item(index)
        if role == Qt.DisplayRole:
            return self.column_getters[index.column()](item)
        if role == Qt.DecorationRole:
            if index.column() > 0:
                return None
            return apply_status_to_icon(self.icon_provider[item.os_path],
                item.index_status, item.work_tree_status)

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return str(section)
        return self.column_names[section]


class FileView(View):
    preferred_dock_area = Qt.RightDockWidgetArea

    def create_ui(self):
        super(FileView, self).create_ui()
        self.toggle_deep_button.setIcon(QApplication.style().standardIcon(
            QStyle.SP_DirIcon))
        self.toggle_deep_button.toggled.connect(self.deep_toggled)
        self.toggle_unmodified_button.setIcon(apply_status_to_icon(
            QApplication.style().standardIcon(QStyle.SP_FileIcon),
            git_api.UNMODIFIED, git_api.UNMODIFIED))
        self.toggle_unmodified_button.toggled.connect(self.toggle_filter(
            exclude_unmodified))
        self.toggle_untracked_button.setIcon(apply_status_to_icon(
            QApplication.style().standardIcon(QStyle.SP_FileIcon),
            git_api.UNTRACKED, git_api.UNTRACKED))
        self.toggle_untracked_button.toggled.connect(self.toggle_filter(
            exclude_untracked))
        self.toggle_ignored_button.setIcon(apply_status_to_icon(
            QApplication.style().standardIcon(QStyle.SP_FileIcon),
            git_api.IGNORED, git_api.IGNORED))
        self.toggle_ignored_button.toggled.connect(self.toggle_filter(
            exclude_ignored))
        self.filter_text.textEdited.connect(self.filter_text_edited)
        workspace = self.app.workspace
        self._directory = None
        self._file_lister = shallow_file_list
        self.file_model = FileModel(workspace, parent=self)
        self.file_model.file_source = lambda: (self._file_lister(self._directory)
            if self._directory else None)
        self.filter_model = FilterModel(parent=self)
        self.filter_model.setSourceModel(self.file_model)
        self.file_list.setModel(self.filter_model)
        # We must assign the selection model to a variable, to avoid triggering
        # a segfault bug (temporary PyObject* destroyed prematurely)
        # see https://bugreports.qt-project.org/browse/PYSIDE-79
        selection_model = self.file_list.selectionModel()
        selection_model.currentChanged.connect(self.current_item_changed)
        selection_model.selectionChanged.connect(self.item_selection_changed)
        self.app.view_focus_out[self] += self.lost_focus
        self.app.view_focus_in[self] += self.gained_focus

    def on_added_to_window(self):
        super(FileView, self).on_added_to_window()
        if not self.parent().file_view:
            self.parent().file_view = self

    def on_removed_from_window(self):
        super(FileView, self).on_removed_from_window()
        if self.parent().file_view is self:
            self.parent().file_view = None

    @property
    def directory(self):
        return self._directory

    @directory.setter
    def directory(self, new_dir):
        self._directory = new_dir
        self.file_model.refresh()

    @property
    def selected_files(self):
        return tuple(model_item(index) for index in
            self.file_list.selectionModel().selectedRows())

    def deep_toggled(self, deep):
        if deep:
            self._file_lister = deep_file_list
        else:
            self._file_lister = shallow_file_list
        self.file_model.refresh()

    def toggle_filter(self, filter_func):
        def handler(include):
            if include:
                self.filter_model.filters -= filter_func
            else:
                self.filter_model.filters += filter_func
        return handler

    def filter_text_edited(self, text):
        if text:
            self.filter_model.filters += self.exclude_by_path
        else:
            self.filter_model.filters -= self.exclude_by_path

    def exclude_by_path(self, item):
        return self.filter_text.text() in item.name

    def current_item_changed(self, index, old_index):
        self.parent().current_item_changed.emit(model_item(index))

    def item_selection_changed(self, selected, deselected):
        self.parent().item_selection_changed.emit(self.selected_files)

    def lost_focus(self, old, now):
        self.parent().current_item_changed.emit(None)
        self.parent().item_selection_changed.emit([])

    def gained_focus(self, old, now):
        self.parent().current_item_changed.emit(model_item(
            self.file_list.currentIndex()))
        self.parent().item_selection_changed.emit(self.selected_files)
