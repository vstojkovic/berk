import os.path

from berk.gui import setup_ui

from PySide.QtGui import QDialog, QDialogButtonBox, QFileDialog, QIcon, QStyle

class OpenRepositoryDialog(QDialog):
    def __init__(self, git, work_tree_dir=None, git_dir=None, parent=None):
        super(OpenRepositoryDialog, self).__init__(parent=parent)
        self.git = git
        setup_ui(self)
        if parent is not None:
            self.move(parent.geometry().center() - self.rect().center())
        self.init_icons()
        self.init_messages()
        self.work_tree_dir = work_tree_dir
        self.git_dir = git_dir
        self.work_tree_text.textChanged.connect(self.dir_text_changed)
        self.browse_work_tree_button.clicked.connect(self.browse_work_tree)
        self.git_dir_text.textChanged.connect(self.dir_text_changed)
        self.browse_git_dir_button.clicked.connect(self.browse_git_dir)
        self.showing_more = bool(git_dir)
        self.toggle_more_less_button.clicked.connect(self.toggle_showing_more)
        self.directories_updated()

    def init_icons(self):
        get_icon = self.style().standardIcon
        self.icon_err, self.icon_wrn, self.icon_inf = [
            get_icon(icon_id).pixmap(16, 16)
            for icon_id in (
                QStyle.SP_MessageBoxCritical,
                QStyle.SP_MessageBoxWarning,
                QStyle.SP_MessageBoxInformation)]

    def init_messages(self):
        self.message_err_need_git_dir = self.tr(
            "Not a valid repository. Please correct the work tree path or specify a .git directory manually.")
        self.message_err_invalid_git_dir = self.tr(
            "The .git directory is invalid.")
        self.message_wrn_non_bare = self.tr(
            "The work tree is unspecified and the .git directory does not point to a bare repository.")
        self.message_inf_bare = self.tr("You are adding a bare repository.")

    @property
    def work_tree_dir(self):
        if self.work_tree_text.text():
            return str(self.work_tree_text.text())

    @work_tree_dir.setter
    def work_tree_dir(self, value):
        self.work_tree_text.setText(value or '')

    @property
    def git_dir(self):
        if self.git_dir_text.text():
            return str(self.git_dir_text.text())

    @git_dir.setter
    def git_dir(self, value):
        self.git_dir_text.setText(value or '')

    def browse_work_tree(self):
        path = QFileDialog.getExistingDirectory(self,
            self.tr('Select Work Tree'), self.work_tree_dir)
        if path:
            self.work_tree_dir = path

    def browse_git_dir(self):
        path = QFileDialog.getExistingDirectory(self,
            self.tr('Select .git Directory'), self.git_dir)
        if path:
            self.git_dir = path

    def dir_text_changed(self, text):
        self.directories_updated()

    def directories_updated(self):
        work_tree_dir = self.work_tree_text.text()
        git_dir = self.git_dir_text.text()
        if git_dir:
            try:
                git_dir_prop, is_bare = self.git.get_properties(git_dir,
                    git_dir=True, bare=True)
                is_git_dir = (git_dir_prop == git_dir)
            except:
                is_git_dir = False
            if not is_git_dir:
                self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(False)
                self.message_icon_label.setPixmap(self.icon_err)
                self.message_label.setText(self.message_err_invalid_git_dir)
                return
            if not work_tree_dir:
                self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(True)
                if is_bare:
                    self.message_icon_label.setPixmap(self.icon_inf)
                    self.message_label.setText(self.message_inf_bare)
                else:
                    self.message_icon_label.setPixmap(self.icon_wrn)
                    self.message_label.setText(self.message_wrn_non_bare)
                return
        else:
            try:
                work_tree_prop = self.git.get_properties(work_tree_dir,
                    work_tree_dir=True)[0]
                work_tree_ok = os.path.relpath(work_tree_prop, work_tree_dir) == '.'
            except:
                work_tree_ok = False
            if not work_tree_ok:
                self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(False)
                self.message_icon_label.setPixmap(self.icon_err)
                self.message_label.setText(self.message_err_need_git_dir)
                return
        self.dialog_buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        self.message_icon_label.clear()
        self.message_label.clear()

    @property
    def showing_more(self):
        return self._showing_more

    @showing_more.setter
    def showing_more(self, value):
        self._showing_more = value
        self.update_showing_more_ui()

    def toggle_showing_more(self):
        self.showing_more = not self.showing_more

    def update_showing_more_ui(self):
        self.git_dir_label.setVisible(self.showing_more)
        self.git_dir_text.setVisible(self.showing_more)
        self.browse_git_dir_button.setVisible(self.showing_more)
        if self.showing_more:
            self.toggle_more_less_button.setText(self.tr('&Less'))
            self.toggle_more_less_button.setIcon(QIcon(':/app/images/less.png'))
        else:
            self.toggle_more_less_button.setText(self.tr('&More'))
            self.toggle_more_less_button.setIcon(QIcon(':/app/images/more.png'))
