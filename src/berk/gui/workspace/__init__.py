import git_api

from berk.model import WorkspaceDirectory

from PySide.QtCore import QObject
from PySide.QtGui import QIcon, QPainter, QPixmap


def workspace_item(model_index):
    if not (model_index and model_index.isValid()): return None
    return model_index.model().workspace_item(model_index)


class StatusText(QObject):
    def __init__(self):
        QObject.__init__(self, None)
        self.status_text_map = {
            git_api.UNMODIFIED: self.tr('Unmodified'),
            git_api.MODIFIED: self.tr('Modified'),
            git_api.ADDED: self.tr('Added'),
            git_api.DELETED: self.tr('Deleted'),
            git_api.RENAMED: self.tr('Renamed'),
            git_api.COPIED: self.tr('Copied'),
            git_api.UNMERGED: self.tr('Unmerged'),
            git_api.UNTRACKED: self.tr('Untracked'),
            git_api.IGNORED: self.tr('Ignored'),
            git_api.MISSING_PATH: self.tr('Missing')
        }

    def __getitem__(self, index):
        return self.status_text_map[index]

status_text = StatusText()


class StatusIcon(object):
    def __init__(self):
        self.icons = {}

    def icon_name(self, index_status, work_tree_status):
        if index_status == git_api.UNTRACKED: return 'untracked.png'
        if index_status == git_api.IGNORED: return 'ignored.png'
        if index_status == git_api.UNMODIFIED and \
                        work_tree_status == git_api.UNMODIFIED: return 'unmodified.png'
        if index_status == git_api.ADDED: return 'added.png'
        if index_status == git_api.DELETED: return 'deleted.png'
        if index_status in (git_api.RENAMED, git_api.COPIED):
            return 'renamed-or-copied.png'
        if index_status == git_api.MODIFIED or \
                        work_tree_status == git_api.MODIFIED: return 'modified.png'
        if work_tree_status == git_api.DELETED: return 'missing.png'

    def __getitem__(self, status):
        icon_name = self.icon_name(*status)
        if not icon_name: return
        try:
            return self.icons[icon_name]
        except KeyError:
            icon = QPixmap(':/app/images/overlays/16/%s' % icon_name)
            self.icons[icon_name] = icon
            return icon

status_icon = StatusIcon()

def apply_status_to_icon(icon, index_status, work_tree_status):
    result = QIcon()
    overlay = status_icon[index_status, work_tree_status]
    for size in icon.availableSizes():
        pixmap = icon.pixmap(size).copy()
        x, y = (size - overlay.size()).toTuple()
        QPainter(pixmap).drawPixmap(x, y, overlay)
        result.addPixmap(pixmap)
    return result


def shallow_file_list(root):
    return root.files

def deep_file_list(root):
    result = []
    def recurse(directory):
        result.extend(directory.files)
        for child_dir in directory.dirs:
            recurse(child_dir)
    if isinstance(root, WorkspaceDirectory):
        recurse(root)
    else:
        result.append(root)
    return result


def exclude_unmodified(item):
    return item.index_status != git_api.UNMODIFIED or \
           item.work_tree_status != git_api.UNMODIFIED

def exclude_untracked(item):
    return item.index_status != git_api.UNTRACKED

def exclude_ignored(item):
    return item.index_status != git_api.IGNORED
