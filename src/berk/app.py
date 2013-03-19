import os.path
import sys
import collections

import git_api

# Uncomment the following lines when creating the executable with py2exe
# import PySide.QtXml
# from berk import dist_resources

# Uncomment the following line when not using py2exe
from berk import dev_resources

from berk import Event

from berk.model import Workspace

from berk.gui import View
from berk.gui.workspace.window import WorkspaceWindow

from PySide.QtGui import QApplication
from PySide.QtCore import Signal


#if hasattr(sys, 'frozen'):
#    plugin_dir = os.path.join(os.path.dirname(sys.executable), 'plugins')
#else:
#    plugin_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
#        os.path.realpath(__file__)))), 'plugins')


class Application(QApplication):
    repo_added = Signal()

    @staticmethod
    def create(workspace, argv=[]):
        app = Application(argv)
        app.workspace =  workspace
        app.view_focus_out = collections.defaultdict(Event)
        app.view_focus_in = collections.defaultdict(Event)
        app.focusChanged.connect(app.focus_changed)
        return app

    def focus_changed(self, old, new):
        old_view = old
        while old_view and not isinstance(old_view, View):
            old_view = old_view.parent()
        new_view = new
        while new_view and not isinstance(new_view, View):
            new_view = new_view.parent()
        if old_view == new_view: return
        self.view_focus_out[old_view](old, new)
        self.view_focus_in[new_view](old, new)


def main(argv):
    git = git_api.Git()
    workspace = Workspace(git)
    app = Application.create(workspace, argv=argv)
    main_window = WorkspaceWindow()
    main_window.open_default_views()
    main_window.show()
    return app.exec_()

if __name__ == '__main__':
    main(sys.argv)
