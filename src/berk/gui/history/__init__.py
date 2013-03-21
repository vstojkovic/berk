import collections
import bisect
import posixpath

import git_api

from berk.gui import busy_cursor, connect_destructor, FilterModel, \
    loadable_widget, model_item, rgb_color, setup_ui
from berk.gui.branches import PickBranchesDialog

from PySide.QtCore import QAbstractTableModel, QPointF, QSize, Qt
from PySide.QtGui import QAction, QActionGroup, QApplication, QBrush, \
    QFontMetrics, QFrame, QMenu, QPainter, QPainterPath, QPen, QStyle, \
    QStyledItemDelegate, QStyleOptionFocusRect


def commit_matches_text(commit, text):
    return any(
        (text in str(attr)
        if not isinstance(attr, tuple)
        else any(text in str(item) for item in attr))
            for attr in commit)


# Needs to be a class instead of namedtuple, because PySide converts tuples
# into Qt types and isinstance(data, GraphRow) will fail
class GraphRow(object):
    def __init__(self, repo, log_entry, prev_row, commit_node, edges):
        self.repo = repo
        self.log_entry = log_entry
        self.prev_row = prev_row
        self.commit_node = commit_node
        self.edges = edges

GraphNode = collections.namedtuple('GraphNode', ('lane', 'color'))
GraphEdge = collections.namedtuple('GraphEdge',
    ('from_lane', 'to_lane', 'color'))
LaneData = collections.namedtuple('LaneData', ('commit_id', 'color'))


class LogGraphModel(QAbstractTableModel):
    column_getters = [
        lambda row: row,
        lambda row: row.log_entry.message[0],
        lambda row: '%s <%s>' % (row.log_entry.author_name,
        row.log_entry.author_email),
        lambda row: str(row.log_entry.author_date),
        lambda row: row.log_entry.commit_id
    ]

    def __init__(self, repo, revs=None, paths=None, all=False, parent=None):
        super(LogGraphModel, self).__init__(parent=parent)
        connect_destructor(self)
        self.column_names = [self.tr('Graph'), self.tr('Message'),
            self.tr('Author'), self.tr('Date'), self.tr('SHA')]
        self.repo = repo
        self.revs = revs
        self.paths = paths
        self.all = all
        self.graph = None
        self.repo.workspace.before_repo_refreshed += self.before_repo_refreshed
        self.repo.workspace.repo_refreshed += self.repo_refreshed
        self.refresh()

    def _destroyed(self):
        self.repo.workspace.before_repo_refreshed -= self.before_repo_refreshed
        self.repo.workspace.repo_refreshed -= self.repo_refreshed

    def model_item(self, index):
        return self.graph[index.row()]

    def refresh(self):
        self.beginResetModel()
        self._refresh_graph()
        self.endResetModel()

    def _refresh_graph(self):
        self.graph = create_log_graph(self.repo, self.repo.log(revs=self.revs,
            paths=self.paths, all=self.all))

    def before_repo_refreshed(self, repo):
        if repo is self.repo:
            self.beginResetModel()

    def repo_refreshed(self, repo):
        if repo is self.repo:
            self._refresh_graph()
            self.endResetModel()

    def rowCount(self, parent):
        return len(self.graph)

    def columnCount(self, parent):
        return len(self.column_getters)

    def data(self, index, role):
        if not index.isValid():
            return None
        if index.row() >= self.rowCount(None):
            return None
        if index.column() >= self.columnCount(None):
            return None
        if role != Qt.DisplayRole:
            return None
        return self.column_getters[index.column()](model_item(index))

    def flags(self, index):
        if not index.isValid():
            return 0
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Vertical:
            return None
        return self.column_names[section]


def create_log_graph(repo, git_log):
    graph = []
    lanes = []
    commit_lane_map = {}
    color_pool = ColorPool()
    prev_row = None
    for log_entry in git_log:
        # locate the lane for the current commit
        if log_entry.commit_id in commit_lane_map:
            commit_lane = commit_lane_map.pop(log_entry.commit_id)
            commit_color = lanes.pop(commit_lane).color
        else: # if not found, it goes into a new lane
            commit_lane = len(lanes)
            commit_color = color_pool.acquire()
            # calculate by how much we need to shift lanes
        # for every parent not mapped, map it to a lane and shift lanes
        lane_shift = -1
        for parent_id in log_entry.parent_ids:
            if not parent_id in commit_lane_map:
                lane_shift += 1
                parent_lane = commit_lane + lane_shift
                if lane_shift:
                    parent_color = color_pool.acquire()
                else:
                    parent_color = commit_color
                lanes.insert(parent_lane, LaneData(parent_id, parent_color))
                commit_lane_map[parent_id] = parent_lane
                # release commit color if it wasn't used
        if lane_shift < 0:
            color_pool.release(commit_color)
            # update commit lane map to reflect lane shift
        if lane_shift:
            for lane in xrange(commit_lane + lane_shift + 1, len(lanes)):
                commit_lane_map[lanes[lane].commit_id] = lane
                # create the list of edges
        edges = []
        # add parent edges for the current commit
        for parent_id in log_entry.parent_ids:
            parent_lane = commit_lane_map[parent_id]
            edges.append(GraphEdge(
                commit_lane, parent_lane, lanes[parent_lane].color))
            # add straight edges for lanes before the current commit
        for lane in xrange(0, commit_lane):
            edges.append(GraphEdge(lane, lane, lanes[lane].color))
            # add possible angled edges for lanes after the current commit
        for lane in xrange(commit_lane + lane_shift + 1, len(lanes)):
            edges.append(GraphEdge(lane - lane_shift, lane, lanes[lane].color))
            # create the row in the commit list
        prev_row = GraphRow(
            repo=repo,
            log_entry=log_entry,
            prev_row=prev_row,
            commit_node=GraphNode(lane=commit_lane, color=commit_color),
            edges=edges)
        graph.append(prev_row)
    return graph


class ColorPool(object):
    def __init__(self):
        self.highest = -1
        self.unused = []

    def acquire(self):
        if self.unused:
            return -self.unused.pop()
        else:
            self.highest += 1
            return self.highest

    def release(self, color):
        if color == self.highest:
            self.highest -= 1
            if self.unused and (self.unused[0] == -self.highest):
                del self.unused[0]
        else:
            bisect.insort(self.unused, -color)


class LogGraphDelegate(QStyledItemDelegate):
    graph_palette = [rgb_color(rgb) for rgb in [
        0x4040ff, 0xff4040, 0x00c000, 0xcccc00, 0xa066ff, 0x66ccff,
        0xc08000, 0x50cca0, 0xffa066, 0x808080
    ]]

    @classmethod
    def edge_color(cls, color):
        if color < len(cls.graph_palette):
            return cls.graph_palette[color]
        return Qt.black

    node_radius = 4.5 / 30
    node_thickness = 2.0 / 30
    edge_thickness = 4.0 / 30

    ref_palette = {
        (git_api.REF_BRANCH, False): rgb_color(0x80ff80),
        (git_api.REF_BRANCH, True): rgb_color(0xff8080),  # checked out
        git_api.REF_REMOTE: rgb_color(0xffffc0),
        git_api.REF_TAG: rgb_color(0x80c0ff),
    }
    ref_color_default = rgb_color(0xe0e0e0)
    ref_frame_thickness = 1
    ref_padding_x = 4
    ref_padding_y = 2
    ref_spacing = 4
    ref_arrow_ratio = 0.25

    @staticmethod
    def max_edge_lane(edges):
        if edges:
            return max(max(edge.from_lane, edge.to_lane) for edge in edges)
        return 0

    def __init__(self, draw_focus=False, preferred_lane_size=30, parent=None):
        QStyledItemDelegate.__init__(self, parent)
        self.draw_focus = draw_focus
        self.preferred_lane_size = preferred_lane_size

    def refs_size(self, option, refs, skip_head):
        if not refs:
            return 0, 0
        metrics = QFontMetrics(option.font)
        width = 0
        height = 0
        for ref in refs:
            if skip_head and posixpath.basename(ref) == 'HEAD':
                continue
            ref_text = git_api.parse_ref(ref)[0]
            text_rect = metrics.boundingRect(0, 0, 0, 0,
                Qt.AlignLeft | Qt.AlignTop, ref_text)
            text_rect.setWidth(text_rect.width() + self.ref_padding_x)
            text_rect.setHeight(text_rect.height() + self.ref_padding_y)
            width += text_rect.width()
            width += text_rect.height() * self.ref_arrow_ratio
            width += self.ref_spacing
            height = max(height, text_rect.height())
        return width, height

    def sizeHint(self, option, index):
        if not isinstance(index.data(), GraphRow):
            return QStyledItemDelegate.sizeHint(self, option, index)
        row = index.data()
        max_lane = max(row.commit_node.lane, self.max_edge_lane(row.edges))
        if row.prev_row:
            max_lane = max(max_lane, self.max_edge_lane(row.prev_row.edges))

        width = (max_lane + 1) * self.preferred_lane_size
        height = self.preferred_lane_size

        refs_width, refs_height = self.refs_size(option, row.log_entry.refs,
            bool(row.repo.head_ref))
        width += refs_width
        height = max(height, refs_height)

        return QSize(width, height)

    def draw_edge(self, painter, option, edge, lane_offset):
        from_y = 0.5 + lane_offset
        to_y = 1 + from_y
        pen = QPen(self.edge_color(edge.color), self.edge_thickness,
            Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin)
        painter.setPen(pen)
        if edge.from_lane == edge.to_lane:
            line_x = edge.from_lane + 0.5
            painter.drawLine(QPointF(line_x, from_y), QPointF(line_x, to_y))
        else:
            from_x = edge.from_lane + 0.5
            to_x = edge.to_lane + 0.5
            path = QPainterPath()
            path.moveTo(QPointF(from_x, from_y))
            path.cubicTo(from_x, from_y + 0.5, to_x, to_y - 0.5, to_x, to_y)
            painter.drawPath(path)

    def draw_ref(self, painter, option, ref, repo, x):
        if repo.head_ref and posixpath.basename(ref) == 'HEAD':
            return x

        ref_text, ref_type = git_api.parse_ref(ref)
        if ref_type == git_api.REF_BRANCH:
            ref_color = self.ref_palette[ref_type, ref_text == repo.head_ref]
        else:
            ref_color = self.ref_palette.get(ref_type, self.ref_color_default)

        lane_size = option.rect.height()
        painter.setPen(QPen(Qt.black, self.ref_frame_thickness))
        painter.setBrush(QBrush(ref_color))
        painter.setFont(option.font)

        text_rect = painter.boundingRect(0, 0, 0, 0,
            Qt.AlignLeft | Qt.AlignTop, ref_text)
        text_rect.translate(-text_rect.x(), -text_rect.y())
        text_rect.setWidth(text_rect.width() + self.ref_padding_x)
        text_rect.setHeight(text_rect.height() + self.ref_padding_y)
        text_rect.translate(
            x + text_rect.height() * self.ref_arrow_ratio,
            (lane_size - text_rect.height()) / 2)
        path = QPainterPath()
        path.moveTo(x, lane_size / 2)
        path.lineTo(text_rect.left(), text_rect.top())
        path.lineTo(text_rect.right(), text_rect.top())
        path.lineTo(text_rect.right(), text_rect.bottom())
        path.lineTo(text_rect.left(), text_rect.bottom())
        path.lineTo(x, lane_size / 2)
        painter.drawPath(path)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, ref_text)
        return text_rect.right() + self.ref_spacing

    def paint(self, painter, option, index):
        if not self.draw_focus:
            option.state = option.state & (~QStyle.State_HasFocus)

        if not isinstance(index.data(), GraphRow):
            QStyledItemDelegate.paint(self, painter, option, index)
            return

        row = index.data()

        has_focus = option.state & QStyle.State_HasFocus
        option.state = option.state & (~QStyle.State_HasFocus)
        QStyledItemDelegate.paint(self, painter, option, index)

        lane_size = option.rect.height()

        painter.save()

        painter.setClipRect(option.rect)
        painter.translate(option.rect.x(), option.rect.y())
        painter.scale(lane_size, lane_size)
        painter.setRenderHint(QPainter.Antialiasing, True)

        max_lane = row.commit_node.lane

        if row.prev_row:
            for edge in row.prev_row.edges:
                max_lane = max(max_lane, edge.from_lane, edge.to_lane)
                self.draw_edge(painter, option, edge, -1)
        for edge in row.edges:
            max_lane = max(max_lane, edge.from_lane, edge.to_lane)
            self.draw_edge(painter, option, edge, 0)

        pen = QPen(Qt.black, self.node_thickness)
        painter.setPen(pen)
        painter.setBrush(option.palette.window())
        painter.drawEllipse(
            QPointF(row.commit_node.lane + 0.5, 0.5),
            self.node_radius, self.node_radius)

        if row.log_entry.refs:
            painter.resetTransform()
            painter.translate(
                option.rect.x() + (max_lane + 1) * lane_size,
                option.rect.y())

            ref_x = 0
            for ref in row.log_entry.refs:
                ref_x = self.draw_ref(painter, option, ref, row.repo, ref_x)

        painter.restore()

        if has_focus:
            painter.save()
            focus_option = QStyleOptionFocusRect()
            focus_option.rect = option.rect
            QApplication.style().drawPrimitive(QStyle.PE_FrameFocusRect,
                focus_option, painter)
            painter.restore()


@loadable_widget
class LogFilter(QFrame):
    def __init__(self, parent=None):
        super(LogFilter, self).__init__(parent=parent)
        setup_ui(self)
        self.filter_model = FilterModel(parent=self)
        self._viewer = None
        self.revs_menu = QMenu(parent=self)
        self.revs_separator = None
        self.rev_actions = QActionGroup(self)
        self.rev_actions.addAction(self.action_all_refs)
        self.select_revs_button.setMenu(self.revs_menu)
        self.action_all_refs.revs = None
        self.action_all_refs.triggered.connect(self.show_all_refs)
        self.action_select_branches.triggered.connect(self.pick_branches)
        self.filter_text.textEdited.connect(self.filter_text_edited)

    @property
    def source_model(self):
        return self.filter_model.sourceModel()

    @source_model.setter
    def source_model(self, model):
        self.filter_model.setSourceModel(model)
        self.revs_menu.clear()
        for action in self.rev_actions.actions():
            if action is not self.action_all_refs:
                self.rev_actions.removeAction(action)
        self.revs_menu.addAction(self.action_all_refs)
        if not model.repo.head_ref:
            self.revs_menu.addAction(self.create_rev_action(model.repo, 'HEAD'))
        for branch in model.repo.branches:
            self.revs_menu.addAction(self.create_rev_action(model.repo, branch))
        if model.all:
            self._select_action(self.action_all_refs)
        else:
            selected_revs = model.revs
            if not selected_revs:
                if model.repo.head_ref:
                    selected_revs = (model.repo.head_ref,)
                else:
                    selected_revs = ('HEAD',)
            action = self._find_rev_action(selected_revs)
            if not action:
                action = self.create_rev_action(model.repo, model.revs)
                self.revs_menu.addAction(action)
            self._select_action(action)
        self.revs_separator = self.revs_menu.addSeparator()
        self.revs_menu.addAction(self.action_select_branches)

    @property
    def viewer(self):
        return self._viewer

    @viewer.setter
    def viewer(self, new_viewer):
        self._viewer = new_viewer
        self._viewer.setModel(self.filter_model)

    def create_rev_action(self, repo, *revs):
        action = QAction(self.revs_menu)
        action.revs = revs
        action.setText(', '.join(str(rev) for rev in revs))
        action.setCheckable(True)
        action.setActionGroup(self.rev_actions)
        action.triggered.connect(self._revs_action_triggered)
        return action

    def show_all_refs(self):
        self._select_action(self.action_all_refs)
        with busy_cursor():
            self.source_model.revs = ()
            self.source_model.all = True
            self.source_model.refresh()

    def pick_branches(self):
        dialog = PickBranchesDialog(repo=self.source_model.repo, parent=self)
        if dialog.exec_() == dialog.Accepted:
            self.show_revs(*dialog.selected_branches)

    def _select_action(self, action):
        action.setChecked(True)
        self.select_revs_button.setText(action.text())

    def _revs_action_triggered(self):
        self._select_action(self.sender())
        with busy_cursor():
            self.source_model.revs = self.sender().revs
            self.source_model.all = False
            self.source_model.refresh()

    def _find_rev_action(self, revs):
        return next((action for action in self.rev_actions.actions()
            if action.revs == revs), None)

    def show_revs(self, *revs):
        action = self._find_rev_action(revs)
        if not action:
            action = self.create_rev_action(self.source_model.repo, *revs)
            self.revs_menu.insertAction(self.revs_separator, action)
        self._select_action(action)
        with busy_cursor():
            self.source_model.revs = revs
            self.source_model.all = False
            self.source_model.refresh()

    def filter_text_edited(self, text):
        if text:
            self.viewer.hideColumn(0)
            self.filter_model.filters += self.filter_graph_row
        else:
            self.filter_model.filters -= self.filter_graph_row
            self.viewer.showColumn(0)

    def filter_graph_row(self, graph_row):
        return commit_matches_text(graph_row.log_entry, self.filter_text.text())
