import os.path
import posixpath

import itertools
import collections

import inspect

import git_api

from berk import Event


def reflect_repr(obj, *attrs):
    return '%s.%s(%s)' % (
        obj.__class__.__module__, obj.__class__.__name__,
        ', '.join('%s=%s' % (a, repr(getattr(obj, a))) for a in attrs))

Unchanged = object()


def split_path(path, module=os.path):
    head, tail = module.split(path)
    if head == '':
        return [tail]
    result = split_path(head)
    result.append(tail)
    return result


def repo_path_to_os(path):
    remaining, xformed = posixpath.split(path)
    while remaining:
        remaining, tail = posixpath.split(remaining)
        xformed = os.path.join(tail, xformed)
    return xformed


class Workspace(object):
    def __init__(self, git):
        self.git = git
        self.repos = []
        self.before_repo_added = Event()
        self.repo_added = Event()
        self.before_repo_refreshed = Event()
        self.repo_refreshed = Event()
        self.item_updated = Event()

    def add_repo(self, repo):
        self.before_repo_added()
        self.repos.append(repo)
        repo.added_to_workspace(self)
        self.repo_added()


class WorkspaceItem(object):
    def __init__(self, repo, path, os_path):
        self.repo = repo
        self.path = path
        self.name = posixpath.basename(path)
        self.os_path = os_path
        self.parent = None

    @property
    def workspace(self):
        return self.repo.workspace

    def __str__(self):
        return self.path


class WorkspaceDirectory(WorkspaceItem):
    def __init__(self, repo, path, os_path):
        super(WorkspaceDirectory, self).__init__(repo, path, os_path)
        self.set_children(dirs=(), files=())

    def resolve(self, path):
        # use normpath to strip trailing slash (e.g. 'bin/')
        path = posixpath.normpath(path)
        result = self
        for name in split_path(path, posixpath):
            if name == '.':
                continue
            if name == '..':
                result = result.parent
            else:
                result = result.path_map[name]
        return result

    def set_children(self, dirs, files):
        self.dirs = dirs
        self.files = files
        self.path_map = {}
        for item in itertools.chain(self.dirs, self.files):
            item.parent = self
            self.path_map[item.name] = item

    def add_children(self, *children):
        for item in children:
            item.parent = self
            if isinstance(item, WorkspaceDirectory):
                self.dirs.append(item)
            else:
                self.files.append(item)
            self.path_map[item.name] = item


def remove_args(argspec, *args_to_remove):
    args = list(argspec.args)
    defaults = list(argspec.defaults)
    mandatory_count = len(args) - len(defaults or ())
    for arg in args_to_remove:
        idx = args.index(arg)
        args.pop(idx)
        if idx >= mandatory_count:
            defaults.pop(idx - mandatory_count)
        else:
            mandatory_count -= 1
    return argspec._replace(args=args, defaults=tuple(defaults))

def wrap_git_method(method, inject_repo_dirs=True):
    def decorator(impl):
        argspec = inspect.getargspec(method)
        argspec = remove_args(argspec, 'work_tree_dir', 'git_dir')
        call_args = ['{0}={0}'.format(arg) for arg in argspec.args]
        self_arg = argspec.args[0]
        if inject_repo_dirs:
            call_args.append('work_tree_dir={0}.work_tree_dir'.format(self_arg))
            call_args.append('git_dir={0}.git_dir'.format(self_arg))
        wrapper_text = 'lambda {}: _wrapped({})'.format(
            inspect.formatargspec(*argspec)[1:-1],
            ', '.join(call_args))
        wrapper = eval(wrapper_text, {'_wrapped': impl})
        wrapper.__name__ = method.__name__
        return wrapper
    return decorator

def wrap_git_methods(cls):
    def pass_through(member):
        return lambda self, **kwargs: member(self.git, **kwargs)
    for member_name in dir(cls):
        member = getattr(cls, member_name)
        if not inspect.ismethod(member): continue
        if member.im_class is not cls:
            setattr(cls, member_name, wrap_git_method(member)(pass_through(member)))
    return cls

@wrap_git_methods
class Repo(WorkspaceDirectory):
    def __init__(self, work_tree_dir, git_dir=None):
        assert work_tree_dir or git_dir
        self._workspace = None
        super(Repo, self).__init__(repo=self, path='',
            os_path=work_tree_dir or git_dir)
        self.work_tree_dir = work_tree_dir
        self.git_dir = git_dir

    def __repr__(self):
        return reflect_repr(self, 'work_tree_dir', 'git_dir')

    @property
    def workspace(self):
        return self._workspace

    @property
    def git(self):
        return self.workspace.git

    @property
    def bare(self):
        return self.work_tree_dir is None

    def added_to_workspace(self, workspace):
        self._workspace = workspace
        if not self.git_dir:
            self.git_dir = self.git.get_properties(self.work_tree_dir,
                git_dir=True)[0]
        self.refresh()

    def refresh(self):
        self.workspace.before_repo_refreshed(self)
        if self.work_tree_dir:
            self._populate_work_tree()
        else:
            self.set_children(dirs=(), files=())
        self.branches = [ref[len('refs/heads/'):] for ref in
            self.git.refs(self.work_tree_dir, self.git_dir, branches=True)]
        try:
            self.head_id, self.head_ref = self.git.head(self.work_tree_dir,
                self.git_dir)
        except git_api.GitCommandError:
            self.head_id = None
            self.head_ref = None
        if self.head_ref: self.head_ref = self.head_ref[len('refs/heads/'):]
        self.workspace.repo_refreshed(self)

    log = git_api.Git.log
    diff_summary = git_api.Git.diff_summary
    status = git_api.Git.status

    @wrap_git_method(git_api.Git.stage)
    def stage(self, paths, **kwargs):
        self.git.stage(paths=paths, **kwargs)
        self._update_statuses(self.status(paths=paths))

    @wrap_git_method(git_api.Git.unstage)
    def unstage(self, paths, **kwargs):
        self.git.unstage(paths=paths, **kwargs)
        self._update_statuses(self.status(paths=paths))

    @wrap_git_method(git_api.Git.commit)
    def commit(self, **kwargs):
        self.git.commit(**kwargs)
        self.refresh()

    def _populate_work_tree(self):
        status_map = {}
        deleted_map = collections.defaultdict(list)
        status_iter = self.status()
        for path, index_status, work_tree_status, old_path in status_iter:
            # use normpath on the key to strip trailing slash (e.g. 'bin/')
            status_map[posixpath.normpath(path)] = dict(
                index_status=index_status, work_tree_status=work_tree_status,
                old_path=old_path)
            os_path = os.path.join(self.work_tree_dir, repo_path_to_os(path))
            if not os.path.exists(os_path):
                deleted_map[posixpath.dirname(path)].append(path)

        def populate_directory(directory, parent_status):
            dirs = []
            files = []
            for filename in os.listdir(directory.os_path):
                if directory.path == '' and filename == '.git':
                    continue
                file_path = posixpath.join(directory.path, filename)
                file_os_path = os.path.join(directory.os_path, filename)
                file_status = status_map.get(file_path, parent_status)
                if os.path.isdir(file_os_path):
                    dirs.append(populate_directory(
                        WorkspaceDirectory(self, file_path, file_os_path),
                        file_status))
                else:
                    files.append(WorkTreeFile(self, file_path,
                        file_os_path, **file_status))
            directory.set_children(dirs=dirs, files=files)
            return directory

        unmodified = dict(index_status=git_api.UNMODIFIED, 
            work_tree_status=git_api.UNMODIFIED)
        populate_directory(self, unmodified)

        def find_or_create_dir(path):
            result = self
            for name in split_path(path, posixpath):
                if name in result.path_map:
                    result = result.path_map[name]
                else:
                    new_dir = WorkspaceDirectory(self,
                        posixpath.join(result.path, name),
                        os.path.join(result.os_path, name))
                    new_dir.set_children([], [])
                    result.add_children(new_dir)
                    result = new_dir
            return result

        for deleted_path, deleted_files in deleted_map.iteritems():
            parent_dir = find_or_create_dir(deleted_path)
            for deleted_file in deleted_files:
                filename = posixpath.basename(deleted_file)
                file_obj = WorkTreeFile(self, deleted_file,
                    os.path.join(parent_dir.os_path, filename),
                    **status_map[deleted_file])
                parent_dir.add_children(file_obj)

        return

    def _update_item_status(self, item, index_status, work_tree_status,
            old_path):
        if isinstance(item, WorkTreeFile):
            item.update(index_status=index_status,
                work_tree_status=work_tree_status, old_path=old_path)
            return
        for child in itertools.chain(item.dirs, item.files):
            self._update_item_status(child, index_status, work_tree_status,
                old_path)

    def _update_statuses(self, status_iter):
        for path, index_status, work_tree_status, old_path in status_iter:
            self._update_item_status(self.resolve(path), index_status,
                work_tree_status, old_path)


class WorkTreeFile(WorkspaceItem):
    def __init__(self, repo, path, os_path, index_status, work_tree_status, 
            old_path=None):
        super(WorkTreeFile, self).__init__(repo, path, os_path)
        self.index_status = index_status
        self.work_tree_status = work_tree_status
        self.old_path = old_path

    def __repr__(self):
        return reflect_repr(self, 'repo', 'path', 'os_path', 'index_status', 
            'work_tree_status', 'old_path')

    def update(self, index_status=Unchanged, work_tree_status=Unchanged,
            old_path=Unchanged):
        if index_status is not Unchanged:
            self.index_status = index_status
        if work_tree_status is not Unchanged:
            self.work_tree_status = work_tree_status
        if old_path is not Unchanged:
            self.old_path = old_path
        self.workspace.item_updated(self)

    @property
    def our_merge_status(self):
        return self.index_status

    @property
    def their_merge_status(self):
        return self.work_tree_status
