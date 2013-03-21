from berk.gui import Dialog

from PySide.QtGui import QFileDialog, QIcon

class CreateRepositoryDialog(Dialog):
    def __init__(self, git, repo_dir=None, parent=None):
        super(CreateRepositoryDialog, self).__init__(parent=parent)
        self.git = git
        self.repo_dir = repo_dir
        self.browse_repo_dir_button.clicked.connect(self.browse_repo_dir)
        self.browse_template_dir_button.clicked.connect(self.browse_template_dir)
        self.browse_git_dir_button.clicked.connect(self.browse_git_dir)
        self.mask_button.toggled.connect(self.mask_toggled)
        self.bare_checkbox.toggled.connect(self._bare_updated)
        self.showing_more = False
        self.toggle_more_less_button.clicked.connect(self.toggle_showing_more)

    @property
    def repo_dir(self):
        if self.repo_dir_text.text():
            return str(self.repo_dir_text.text())

    @repo_dir.setter
    def repo_dir(self, value):
        self.repo_dir_text.setText(value or '')

    @property
    def template_dir(self):
        if self.template_dir_text.text():
            return str(self.template_dir_text.text())

    @template_dir.setter
    def template_dir(self, value):
        self.template_dir_text.setText(value or '')

    @property
    def git_dir(self):
        if not self.bare and self.git_dir_text.text():
            return str(self.git_dir_text.text())

    @git_dir.setter
    def git_dir(self, value):
        self.git_dir_text.setText(value or '')

    def browse_repo_dir(self):
        path = QFileDialog.getExistingDirectory(self,
            self.tr('Select Repository Directory'), self.repo_dir)
        if path:
            self.repo_dir = path

    def browse_template_dir(self):
        path = QFileDialog.getExistingDirectory(self,
            self.tr('Select Template Directory'), self.template_dir)
        if path:
            self.template_dir = path

    def browse_git_dir(self):
        path = QFileDialog.getExistingDirectory(self,
            self.tr('Select .git Directory'), self.git_dir)
        if path:
            self.git_dir = path

    @property
    def shared(self):
        if self.umask_button.isChecked(): return None
        if self.group_button.isChecked(): return True
        if self.all_button.isChecked(): return 'all'
        if self.mask_button.isChecked():
            mask_value = str(self.mask_text.text())
            if mask_value and mask_value[0] == '0':
                try:
                    mask_value = int(mask_value, 8)
                except ValueError: pass
            return mask_value

    @shared.setter
    def shared(self, value):
        if not value:
            self.umask_button.setChecked(True)
        elif value is True:
            self.group_button.setChecked(True)
        elif value in ('all', 'world', 'everybody'):
            self.all_button.setChecked(True)
        else:
            self.mask_button.setChecked(True)
            if isinstance(value, int):
                self.mask_text.setText('{:04o}'.format(value))
            else:
                self.mask_text.setText(str(value))
            self.mask_toggled(True)

    def mask_toggled(self, checked):
        self.mask_text.setEnabled(checked)
        if checked:
            self.mask_text.setFocus()

    @property
    def bare(self):
        return self.bare_checkbox.isChecked()

    @bare.setter
    def bare(self, value):
        self.bare_checkbox.setChecked(value)
        self._bare_updated(value)

    def _bare_updated(self, bare):
        self.git_dir_text.setEnabled(not bare)
        self.browse_git_dir_button.setEnabled(not bare)

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
        self.template_dir_label.setVisible(self.showing_more)
        self.template_dir_text.setVisible(self.showing_more)
        self.browse_template_dir_button.setVisible(self.showing_more)
        self.git_dir_label.setVisible(self.showing_more)
        self.git_dir_text.setVisible(self.showing_more)
        self.browse_git_dir_button.setVisible(self.showing_more)
        self.shared_label.setVisible(self.showing_more)
        self.shared_group.setVisible(self.showing_more)
        if self.showing_more:
            self.toggle_more_less_button.setText(self.tr('&Less'))
            self.toggle_more_less_button.setIcon(QIcon(':/app/images/less.png'))
        else:
            self.toggle_more_less_button.setText(self.tr('&More'))
            self.toggle_more_less_button.setIcon(QIcon(':/app/images/more.png'))
