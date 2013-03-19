import posixpath

from berk.model import Repo, WorkspaceDirectory
from berk.gui import busy_cursor, connect_destructor, FileIconProvider, \
    model_item, setup_ui
from berk.gui.workspace import apply_status_to_icon, deep_file_list, \
    exclude_ignored, exclude_unmodified
from berk.gui.workspace.file_view import FileModel
from berk.gui.select_commit import SelectCommitDialog

from PySide.QtCore import QAbstractTableModel, Qt
from PySide.QtGui import QDialog, QDialogButtonBox, QFont, QMenu

class StagedChangesModel(QAbstractTableModel):
    column_getters = [
        lambda item: posixpath.basename(item.path),
        lambda item: item.path,
        lambda item: item.lines_added,
        lambda item: item.lines_deleted,
        lambda item: item.new_path
    ]

    def __init__(self, repo, root_dir, parent=None):
        super(StagedChangesModel, self).__init__(parent=parent)
        connect_destructor(self)
        self.repo = repo
        self.root_dir = root_dir
        self.column_names = [self.tr('Name'), self.tr('Path'), self.tr('Added'),
            self.tr('Deleted'), self.tr('New Path')]
        self.icon_provider = FileIconProvider()
        self.repo.workspace.before_repo_refreshed += self.before_repo_refreshed
        self.repo.workspace.repo_refreshed += self.repo_refreshed
        self.refresh()

    def _destroyed(self):
        self.repo.workspace.before_repo_refreshed -= self.before_repo_refreshed
        self.repo.workspace.repo_refreshed -= self.repo_refreshed

    def refresh(self):
        self.beginResetModel()
        self._refresh_changes()
        self.endResetModel()

    def _refresh_changes(self):
        if self.root_dir and not isinstance(self.root_dir, Repo):
            diff_items = (self.root_dir,)
        else:
            diff_items = ()
        self.changeset = tuple(self.repo.diff_summary(staged=True,
            renames=True, paths=diff_items))

    def before_repo_refreshed(self, repo):
        if self.repo is repo:
            self.beginResetModel()

    def repo_refreshed(self, repo):
        if self.repo is repo:
            self._refresh_changes()
            self.endResetModel()

    def rowCount(self, parent):
        return len(self.changeset)

    def columnCount(self, parent):
        return len(self.column_names)

    def data(self, index, role):
        if not index.isValid():
            return None
        item = self.changeset[index.row()]
        if role == Qt.DisplayRole:
            return self.column_getters[index.column()](item)
        if role == Qt.DecorationRole:
            if index.column() > 0:
                return None
            workspace_item = self.repo.resolve(
                item.new_path or item.path)
            return apply_status_to_icon(
                self.icon_provider[workspace_item.os_path],
                workspace_item.index_status, workspace_item.work_tree_status)

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return str(section)
        return self.column_names[section]


class LocalChangesModel(FileModel):
    def _refresh_files(self):
        super(LocalChangesModel, self)._refresh_files()
        self.included_files = set(self.files) if self.files else ()

    def flags(self, index):
        result = super(LocalChangesModel, self).flags(index)
        if index.column() == 0:
            result |= Qt.ItemIsUserCheckable
        return result

    def data(self, index, role):
        if role == Qt.CheckStateRole:
            if index.column() > 0:
                return None
            item = model_item(index)
            return Qt.Checked if item in self.included_files else Qt.Unchecked
        return super(LocalChangesModel, self).data(index, role)

    def setData(self, index, value, role):
        if role != Qt.CheckStateRole or index.column() > 0: return False
        item = model_item(index)
        if item in self.included_files:
            self.included_files.remove(item)
        else:
            self.included_files.add(item)
        self.dataChanged.emit(index, index)
        return True


class CommitDialog(QDialog):
    def __init__(self, repo, selected_items, parent=None):
        super(CommitDialog, self).__init__(parent=parent)
        self.repo = repo
        setup_ui(self)
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        if parent is not None:
            self.move(parent.geometry().center() - self.rect().center())
        self.selected_items = selected_items
        if len(selected_items) == 1 and isinstance(selected_items[0],
                WorkspaceDirectory):
            self.root_dir = selected_items[0]
        else:
            self.root_dir = None
        fixed_font = QFont('Courier', self.message_text.font().pointSize())
        fixed_font.setStyleHint(QFont.Monospace)
        self.message_text.setFont(fixed_font)
        self.text_pos_label.setFont(fixed_font)
        with busy_cursor():
            self.staged_changes_model = StagedChangesModel(repo, self.root_dir,
                parent=self)
            self.local_changes_model = LocalChangesModel(repo.workspace,
                parent=self)
            self.local_changes_model.file_source = lambda: tuple(deep_item
                for selected_item in selected_items
                for deep_item in deep_file_list(selected_item)
                if exclude_unmodified(deep_item) and exclude_ignored(deep_item))
            if self.root_dir:
                self.staged_changes_button.setChecked(True)
                self.show_staged_changes()
            else:
                self.local_changes_button.setChecked(True)
                self.show_local_changes()
            if self.repo.head_ref:
                (self.last_commit,) = self.repo.log(max_commits=1)
            else:
                self.last_commit = None
                self.action_reuse_last_msg.setEnabled(False)
                self.action_reuse_log_msg.setEnabled(False)
                self.amend_checkbox.setEnabled(False)
        self.staged_changes_button.clicked.connect(self.show_staged_changes)
        self.local_changes_button.clicked.connect(self.show_local_changes)
        self.local_changes_model.dataChanged.connect(self.local_change_toggled)
        self.message_text.cursorPositionChanged.connect(self.text_pos_changed)
        self.message_text.textChanged.connect(self.message_text_changed)
        reuse_menu = QMenu()
        reuse_menu.addAction(self.action_reuse_last_msg)
        reuse_menu.addAction(self.action_reuse_log_msg)
        self.reuse_msg_button.setDefaultAction(self.action_reuse_last_msg)
        self.reuse_msg_button.setMenu(reuse_menu)
        self.action_reuse_last_msg.triggered.connect(self.reuse_last_message)
        self.action_reuse_log_msg.triggered.connect(self.select_old_message)
        self.amend_checkbox.toggled.connect(self.amend_toggled)

    @property
    def use_staged_changes(self):
        return self.staged_changes_button.isChecked()

    @property
    def selected_local_changes(self):
        return self.local_changes_model.included_files

    @property
    def message(self):
        return self.message_text.toPlainText().strip()

    @property
    def amend(self):
        return self.amend_checkbox.isChecked()

    def update_ok_button(self):
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(bool(
            self.message and (self.use_staged_changes or
                              self.selected_local_changes)))

    def show_staged_changes(self):
        self.change_list.setModel(self.staged_changes_model)
        self.update_ok_button()

    def show_local_changes(self):
        self.change_list.setModel(self.local_changes_model)
        self.update_ok_button()

    def local_change_toggled(self, top_left, bottom_right):
        self.update_ok_button()

    def text_pos_changed(self):
        cursor = self.message_text.textCursor()
        line = cursor.blockNumber()
        col = cursor.columnNumber()
        self.text_pos_label.setText('%d:%d' % (line + 1, col + 1))

    def message_text_changed(self):
        self.update_ok_button()

    def reuse_last_message(self):
        self.message_text.setPlainText('\n'.join(self.last_commit.message))

    def select_old_message(self):
        dialog = SelectCommitDialog(self.repo, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.message_text.setPlainText('\n'.join(
                dialog.selected_commit.message))

    def amend_toggled(self, should_amend):
        if should_amend and not self.message:
            self.reuse_last_message()
