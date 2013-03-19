import git_api

from berk.model import Repo, WorkspaceDirectory, WorkTreeFile
from berk.gui import busy_cursor, ViewToggler, Window
from berk.gui.workspace.directory_view import DirectoryView
from berk.gui.workspace.file_view import FileView
from berk.gui.workspace.open_repository import OpenRepositoryDialog
from berk.gui.workspace.create_repository import CreateRepositoryDialog
from berk.gui.history import LogView
from berk.gui.commit import CommitDialog

from PySide.QtCore import Signal, Qt
from PySide.QtGui import QDialog, QFileDialog


def has_log(item):
    if not item: return False
    if not item.repo.head_id: return False
    if isinstance(item, WorkspaceDirectory):
        return True
    return item.index_status not in (git_api.IGNORED, git_api.UNTRACKED)

def can_stage(item):
    if not item: return False
    if isinstance(item, Repo):
        return not item.bare
    if isinstance(item, WorkspaceDirectory):
        return True
    return item.work_tree_status not in (git_api.IGNORED, git_api.UNMODIFIED)

def can_unstage(item):
    if not item: return False
    if isinstance(item, Repo):
        return not item.bare
    if isinstance(item, WorkspaceDirectory):
        return True
    return item.index_status not in (git_api.IGNORED, git_api.UNTRACKED,
        git_api.UNMODIFIED)

def can_commit(item):
    if not item: return False
    if isinstance(item, Repo):
        return not item.bare
    if isinstance(item, WorkspaceDirectory):
        return True
    if item.index_status == git_api.IGNORED:
        return False
    return (item.index_status != git_api.UNMODIFIED) or \
           (item.work_tree_status != git_api.UNMODIFIED)

class WorkspaceWindow(Window):
    item_selection_changed = Signal(list)
    current_item_changed = Signal(WorkTreeFile)

    def __init__(self, parent=None):
        super(WorkspaceWindow, self).__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.current_item = None
        self.selected_items = None
        self.current_item_changed.connect(self.handle_current_item_changed)
        self.item_selection_changed.connect(self.handle_item_selection_changed)
        self.action_view_directories.toggler = ViewToggler(
            self.action_view_directories, self.view_factory(DirectoryView))
        self.action_view_files.toggler = ViewToggler(self.action_view_files,
            self.view_factory(FileView))
        self.action_open_repository.triggered.connect(self.open_repository)
        self.action_new_repository.triggered.connect(self.create_repository)
        self.action_log.setEnabled(False)
        self.action_log.triggered.connect(self.show_log)
        self.action_stage.setEnabled(False)
        self.action_stage.triggered.connect(self.stage_selection)
        self.action_unstage.setEnabled(False)
        self.action_unstage.triggered.connect(self.unstage_selection)
        self.action_commit.setEnabled(False)
        self.action_commit.triggered.connect(self.commit_selection)

    @property
    def directory_view(self):
        return self.action_view_directories.toggler.view

    @directory_view.setter
    def directory_view(self, view):
        self.action_view_directories.toggler.view = view

    @property
    def file_view(self):
        return self.action_view_files.toggler.view

    @file_view.setter
    def file_view(self, view):
        self.action_view_files.toggler.view = view

    def open_default_views(self):
        self.open_views(DirectoryView(), FileView())

    def on_view_added(self, view):
        super(WorkspaceWindow, self).on_view_added(view)
        view.floated.connect(self.view_floated)

    def on_view_removed(self, view):
        super(WorkspaceWindow, self).on_view_removed(view)
        view.floated.disconnect(self.view_floated)

    def view_floated(self):
        view = self.sender()
        new_parent = WorkspaceWindow()
        new_parent.setGeometry(view.geometry())
        view.redock(new_parent)
        new_parent.show()

    def open_repository(self):
        dir_path = QFileDialog.getExistingDirectory(self, 
            self.tr('Open Repository'))
        if not dir_path:
            return
        kwargs = dict(git=self.app.workspace.git, parent=self)
        if self.app.workspace.git.is_git_dir(dir_path):
            kwargs['git_dir'] = dir_path
        else:
            kwargs['work_tree_dir'] = dir_path
        dialog = OpenRepositoryDialog(**kwargs)
        if dialog.exec_() == QDialog.Accepted:
            with busy_cursor():
                repo = Repo(work_tree_dir=dialog.work_tree_dir,
                    git_dir=dialog.git_dir)
                self.app.workspace.add_repo(repo)

    def create_repository(self):
        dir_path = QFileDialog.getExistingDirectory(self,
            self.tr('Create Repository'))
        if not dir_path:
            return
        dialog = CreateRepositoryDialog(git=self.app.workspace.git,
            repo_dir=dir_path, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            with busy_cursor():
                self.app.workspace.git.init(dialog.repo_dir, bare=dialog.bare,
                    shared=dialog.shared, template_dir=dialog.template_dir,
                    separate_git_dir=dialog.git_dir)
                if dialog.bare:
                    repo = Repo(work_tree_dir=None, git_dir=dialog.repo_dir)
                else:
                    repo = Repo(work_tree_dir=dialog.repo_dir)
                self.app.workspace.add_repo(repo)

    @property
    def selection_repo(self):
        if not self.selected_items: return None
        first_item = self.selected_items[0]
        return first_item.repo

    def update_current_item_actions(self):
        pass

    def handle_current_item_changed(self, item):
        self.current_item = item
        self.update_current_item_actions()

    def update_selection_actions(self):
        self.action_log.setEnabled(any(has_log(item)
            for item in self.selected_items))
        self.action_stage.setEnabled(any(can_stage(item)
            for item in self.selected_items))
        self.action_unstage.setEnabled(any(can_unstage(item)
            for item in self.selected_items))
        self.action_commit.setEnabled(any(can_commit(item)
            for item in self.selected_items))

    def handle_item_selection_changed(self, items):
        self.selected_items = items
        self.update_selection_actions()

    def show_log(self):
        if isinstance(self.current_item, Repo):
            self.open_views(LogView(repo=self.current_item))
        else:
            self.open_views(LogView(repo=self.current_item.repo,
                files=self.selected_items))

    def stage_selection(self):
        with busy_cursor():
            self.selection_repo.stage(self.selected_items)
        self.update_selection_actions()
        self.update_current_item_actions()

    def unstage_selection(self):
        with busy_cursor():
            self.selection_repo.unstage(self.selected_items)
        self.update_selection_actions()
        self.update_current_item_actions()

    def commit_selection(self):
        repo = self.selection_repo
        dialog = CommitDialog(repo=repo, selected_items=self.selected_items,
            parent=self)
        if dialog.exec_() == QDialog.Rejected: return
        with busy_cursor():
            if dialog.use_staged_changes:
                files = ()
            else:
                files = tuple(dialog.selected_local_changes)
                to_add = filter(lambda f: f.index_status == git_api.UNTRACKED,
                    files)
                if to_add:
                    repo.stage(to_add)
            repo.commit(message=dialog.message, paths=files, amend=dialog.amend)
