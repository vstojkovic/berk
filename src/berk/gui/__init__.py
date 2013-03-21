import operator
import functools
import contextlib
import sys

from berk import Event

from PySide.QtUiTools import QUiLoader
from PySide.QtGui import QApplication, QBrush, QColor, QCursor, QDialog, \
    QDockWidget, QLineEdit, QMainWindow, QPainter, QPalette, \
    QSortFilterProxyModel, QStyle, QStyleOption, QWidget
from PySide.QtCore import QEvent, QObject, QRect, Qt, Signal


if sys.platform == 'win32':
    from .win32_icon_provider import FileIconProvider
else:
    from .qt_icon_provider import FileIconProvider




def rgb_color(rgb):
    return QColor.fromRgb(rgb >> 16, (rgb >> 8) & 0xff, rgb & 0xff)




class connect_destructor(QObject):
    def __init__(self, target, handler=None):
        super(connect_destructor, self).__init__(parent=target)
        target.destroyed.connect(self.target_destroyed)
        self.handler = handler if handler else target._destroyed

    def target_destroyed(self, target=None):
        self.handler()
        self.deleteLater()




@contextlib.contextmanager
def busy_cursor(widget=None, cursor=Qt.WaitCursor):
    if widget:
        widget.setCursor(cursor)
    else:
        QApplication.setOverrideCursor(cursor)
    try:
        yield
    finally:
        if widget:
            widget.unsetCursor()
        else:
            QApplication.restoreOverrideCursor()




def loadable_widget(arg):
    def make_decorator(widget_name):
        def decorator(cls):
            WidgetBuilder.custom_widgets[widget_name] = cls
            return cls
        return decorator
    if isinstance(arg, basestring):
        return make_decorator(arg)
    return make_decorator(arg.__name__)(arg)

class WidgetBuilder(QUiLoader):
    custom_widgets = {}

    def __init__(self, root, parent):
        super(WidgetBuilder, self).__init__()
        assert root or parent
        self.root = root
        self.root_parent = parent
        self.seen_root = False

    def createWidget(self, className, parent=None, name=''):
        if not self.seen_root:
            self.seen_root = True
            if self.root:
                return self.root
            parent = self.root_parent
        if className in self.custom_widgets:
            result = self.custom_widgets[className](parent=parent)
            result.setObjectName(name)
            return result
        return super(WidgetBuilder, self).createWidget(className, parent, name)


def pattern_path(pattern):
    return functools.partial(operator.mod, pattern)

def map_path(map):
    return functools.partial(operator.getitem, map)

def widget_name_or_class(widget):
    return widget.objectName() or widget.__class__.__name__

class WidgetLoader(object):
    TARGET = object()

    def __init__(self, name_to_path=None, object_to_name=None):
        self.name_to_path = name_to_path or pattern_path('%s.ui')
        self.object_to_name = object_to_name or widget_name_or_class

    def object_to_path(self, target):
        return self.name_to_path(self.object_to_name(target))

    def setup_ui(self, target, root=TARGET, parent=None, name=None):
        if root is WidgetLoader.TARGET:
            root = target
        if name:
            path = self.name_to_path(name)
        else:
            path = self.object_to_path(target)
        ret = WidgetBuilder(root, parent).load(path)
        if ret is not target:
            self.create_children_name_attributes(target, ret)
        return ret

    def create_children_name_attributes(self, target, root):
        for child in root.children():
            name = child.objectName()
            if name and not name.startswith('_') and not name.startswith('qt_'):
                if not hasattr(target, name):
                    setattr(target, name, child)
            self.create_children_name_attributes(target, child)


widget_loader = WidgetLoader(pattern_path(':/app/gui/%s.ui'))

def setup_ui(widget, root=WidgetLoader.TARGET, parent=None, name=None):
    return widget_loader.setup_ui(widget, root=root, parent=parent, name=None)




@loadable_widget
class FilterEditor(QLineEdit):
    def __init__(self, parent=None):
        super(FilterEditor, self).__init__(parent=parent)
        style = QApplication.style()
        self.glyph_width = style.pixelMetric(QStyle.PM_TabCloseIndicatorWidth)
        self.glyph_height = style.pixelMetric(QStyle.PM_TabCloseIndicatorHeight)
        self.frame_width = style.pixelMetric(QStyle.PM_DefaultFrameWidth)
        self.hovering = False
        self.old_cursor = None
        self.setTextMargins(0, 0, self.glyph_width + self.frame_width, 0)

    @property
    def glyph_rect(self):
        return QRect(self.width() - self.glyph_width - self.frame_width * 2,
            self.frame_width * 2, self.glyph_width, self.glyph_height)

    def _start_hover(self):
        self.hovering = True
        self.old_cursor = self.cursor()
        self.setCursor(Qt.ArrowCursor)

    def _end_hover(self):
        self.hovering = False
        if self.old_cursor:
            self.setCursor(self.old_cursor)
        else:
            self.unsetCursor()
        self.old_cursor = None

    def mouseMoveEvent(self, event):
        super(FilterEditor, self).mouseMoveEvent(event)
        if self.glyph_rect.contains(event.pos()):
            if self.text() and not self.hovering:
                self._start_hover()
        else:
            if self.hovering:
                self._end_hover()

    def mousePressEvent(self, event):
        if self.glyph_rect.contains(event.pos()) and self.text():
            self._end_hover()
            self.setText('')
            self.textEdited.emit('')
        else:
            super(FilterEditor, self).mousePressEvent(event)

    def paintEvent(self, event):
        super(FilterEditor, self).paintEvent(event)
        if not self.text(): return
        option = QStyleOption()
        option.rect = self.glyph_rect
        painter = QPainter(self)
        style = QApplication.style()

        style.drawPrimitive(QStyle.PE_IndicatorTabClose, option, painter)



def model_item(qt_index):
    if not (qt_index and qt_index.isValid()): return None
    return qt_index.model().model_item(qt_index)


class FilterSet(object):
    def __init__(self):
        self.changed = Event()
        self._filters = set()

    def __iadd__(self, func):
        self._filters.add(func)
        self.changed()
        return self

    def __isub__(self, func):
        self._filters.remove(func)
        self.changed()
        return self

    def __call__(self, item):
        return all(func(item) for func in self._filters)


class FilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super(FilterModel, self).__init__(parent=parent)
        self.filters = FilterSet()
        self.filters.changed += self.invalidateFilter
        self._row_item_getter = lambda model, row, parent: model_item(
            model.index(row, 0, parent))

    @property
    def row_item_getter(self):
        return self._row_item_getter

    @row_item_getter.setter
    def row_item_getter(self, func):
        self._row_item_getter = func
        self.invalidateFilter()

    def model_item(self, index):
        if not index.isValid(): return None
        return self.sourceModel().model_item(self.mapToSource(index))

    def filterAcceptsRow(self, source_row, source_parent):
        return self.filters(self.row_item_getter(self.sourceModel(), source_row,
            source_parent))




class Dialog(QDialog):
    def __init__(self, parent=None):
        super(Dialog, self).__init__(parent=parent)
        setup_ui(self)
        if parent is not None:
            self.move(parent.window().geometry().center() - self.rect().center())




def paint_redock_overlay(widget):
    painter = QPainter(widget)
    brush = QBrush(QApplication.palette().color(QPalette.Highlight),
                   Qt.Dense6Pattern)
    painter.fillRect(widget.rect(), brush)

class RedockOverlay(QWidget):
    def __init__(self, parent, owner):
        super(RedockOverlay, self).__init__(parent=parent)
        self.setPalette(Qt.transparent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.owner = owner

    def paintEvent(self, event):
        super(RedockOverlay, self).paintEvent(event)
        if self.owner.is_redock_target:
            paint_redock_overlay(self)


class View(QDockWidget):
    preferred_dock_area = Qt.LeftDockWidgetArea
    added_to_window = Signal()
    removed_from_window = Signal()
    floated = Signal()
    closed = Signal()

    def __init__(self):
        super(View, self).__init__()
        connect_destructor(self)
        self._is_redock_target = False
        self._redock_target = None
        self.redocking = False
        self._parent = None
        self.topLevelChanged.connect(self.floating_changed)

    def _destroyed(self):
        pass

    @property
    def app(self):
        return QApplication.instance()

    def qParent(self):
        return super(View, self).parent()

    def parent(self):
        return self._parent

    @property
    def dock_area(self):
        return self.parent().dockWidgetArea(self)

    @property
    def redock_target(self):
        return self._redock_target

    @redock_target.setter
    def redock_target(self, target):
        if self._redock_target == target: return
        if self._redock_target is not None:
            self._redock_target.is_redock_target = False
        self._redock_target = target
        if target is not None:
            target.activateWindow()
            self.raise_()
            target.is_redock_target = True

    @property
    def is_redock_target(self):
        return self._is_redock_target

    @is_redock_target.setter
    def is_redock_target(self, value):
        if self._is_redock_target == value:
            return
        self._is_redock_target = value
        self.overlay.update()

    def floating_changed(self):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, self.isFloating())
        if not self.isFloating():
            self.redock_target = None

    def changeEvent(self, event):
        super(View, self).changeEvent(event)
        if event.type() == QEvent.ParentChange:
            if self.parent():
                self.on_removed_from_window()
            self._parent = self.qParent()
            if self.parent():
                self.on_added_to_window()
        if self.isFloating() and event.type() == QEvent.ActivationChange and \
                self.isActiveWindow():
            if self.redocking: return
            if self.redock_target:
                target = self.redock_target
                self.redock_target = None
                self.redock(target)
            else:
                self.on_floated()

    def redock(self, target):
        self.redocking = True
        try:
            # If the following line is removed, when you redock a view that was
            # previously left floating, it stops responding to clicks on its
            # title widget
            self.setFloating(False)
            self.parent().removeDockWidget(self)
            if isinstance(target, View):
                target.parent().tabifyDockWidget(target, self)
                # If the following line is removed, self.raise_() won't always
                # result in making the redocked view's tab current
                target.raise_()
            else:
                target.addDockWidget(self.preferred_dock_area, self)
            self.show()
            self.raise_()
            self.activateWindow()
        finally:
            self.redocking = False

    def on_floated(self):
        self.floated.emit()

    def moveEvent(self, event):
        if self.isFloating():
            cursor_widget = self.app.widgetAt(QCursor.pos())
            if cursor_widget and (self.parent() is not cursor_widget.window()):
                target = cursor_widget
                while target and not isinstance(target, (View, Window)):
                    target = target.parent()
                if isinstance(target, View):
                    if not self.isAreaAllowed(target.dock_area) or \
                            not target.parent().accepts_view(self):
                        target = None
                if isinstance(target, Window):
                    if target.findChild(View) or not target.accepts_view(self):
                        target = None
                self.redock_target = target
            else:
                self.redock_target = None
        return super(View, self).moveEvent(event)

    def resizeEvent(self, event):
        super(View, self).resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def create_ui(self):
        setup_ui(self)
        self.overlay = RedockOverlay(self, self)

    def on_added_to_window(self):
        self.added_to_window.emit()
        self.parent().on_view_added(self)

    def on_removed_from_window(self):
        self.removed_from_window.emit()
        self.parent().on_view_removed(self)

    def closeEvent(self, event):
        super(View, self).closeEvent(event)
        self.closed.emit()




class ViewToggler(QObject):
    def __init__(self, action, view_factory):
        super(ViewToggler, self).__init__(parent=action)
        self.action = action
        self.create_view = view_factory
        self._view = None
        action.triggered[bool].connect(self.action_triggered)

    @property
    def view(self):
        return self._view

    @view.setter
    def view(self, view):
        if self.view:
            self.disconnect_view()
        self._view = view
        if self.view:
            self.connect_view()

    def connect_view(self):
        self.view.visibilityChanged.connect(self.view_visibility_changed)

    def disconnect_view(self):
        self.view.visibilityChanged.disconnect(self.view_visibility_changed)

    def action_triggered(self, show):
        if not self.view:
            self.create_view()
        self.view.setVisible(show)

    def view_visibility_changed(self, show):
        self.action.setChecked(self.sender().isVisible())




class Window(QMainWindow):
    def __init__(self, parent=None):
        super(Window, self).__init__(parent=parent)
        self._is_redock_target = False
        setup_ui(self)
        self.setCentralWidget(QWidget())
        self.centralWidget().hide()
        self.setDockOptions(QMainWindow.AnimatedDocks |
            QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)

    @property
    def app(self):
        return QApplication.instance()

    @property
    def is_redock_target(self):
        return self._is_redock_target

    @is_redock_target.setter
    def is_redock_target(self, value):
        if self._is_redock_target == value:
            return
        self._is_redock_target = value
        self.update()

    def paintEvent(self, event):
        super(Window, self).paintEvent(event)
        if self.is_redock_target:
            paint_redock_overlay(self)

    def accepts_view(self, view):
        return True

    def open_views(self, *views):
        for view in views:
            view.setParent(self)
            view.create_ui()
        for view in views:
            self.addDockWidget(view.preferred_dock_area, view)
        return views

    def view_factory(self, view_type):
        def factory():
            return self.open_views(view_type())[0]
        return factory

    def on_view_added(self, view):
        pass

    def on_view_removed(self, view):
        pass
