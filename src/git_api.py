from __future__ import print_function

import subprocess
import os.path
import re
import collections
import dateutil.parser


UNMODIFIED = 0
MODIFIED = 1
ADDED = 2
DELETED = 3
RENAMED = 4
COPIED = 5
UNMERGED = 6
UNTRACKED = -1
IGNORED = -2
MISSING_PATH = -3

_status_char_map = {
    ' ' : UNMODIFIED,
    'M' : MODIFIED,
    'A' : ADDED,
    'D' : DELETED,
    'R' : RENAMED,
    'C' : COPIED,
    'U' : UNMERGED,
    '?' : UNTRACKED,
    '!' : IGNORED
}


def is_exe(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def is_true_str(s):
    return s.lower() == 'true'


def find_git_executable(program):
    path, name = os.path.split(program)
    if path:
        if is_exe(program):
            return program
    else:
        if 'PATHEXT' in os.environ:
            extensions = os.environ['PATHEXT'].split(';')
        else:
            extensions = []
        for path in os.environ['PATH'].split(os.pathsep):
            candidate = os.path.join(path, program)
            if is_exe(candidate):
                return candidate
            for ext in extensions:
                if is_exe(candidate + ext):
                    return candidate + ext
    return None


class GitExe(object):
    def __init__(self, program='git'):
        self._executable = find_git_executable(program)

    def __getattr__(self, name):
        def create_command(*args, **kwargs):
            cmd_name = name.replace('_', '-')
            cmd_args = [self._executable, cmd_name]
            cmd_options = {}
            for k, v in kwargs.iteritems():
                # if a kwarg starts with _, it's a command object option
                if k.startswith('_'):
                    cmd_options[k[1:]] = v
                else: # it's a command-line switch or argument
                    if v is None: continue
                    if len(k) == 1:
                        if v is not False:
                            cmd_args.append('-' + k)
                            if v is not True:
                                cmd_args.append(str(v))
                    else:
                        if v is not False:
                            k = k.replace('_', '-')
                            if v is True:
                                cmd_args.append('--' + k)
                            else:
                                cmd_args.append('--%s=%s' % (k, str(v)))
            for arg in args:
                if isinstance(arg, collections.Iterable) and not isinstance(
                        arg, basestring):
                    for item in arg:
                        cmd_args.append(str(item))
                else:
                    cmd_args.append(str(arg))
            return GitCommand(cmd_args, **cmd_options)
        return create_command


_rc_exception_class = {}
def rc_exception_class(return_code):
    int_code = int(return_code)
    if int_code in _rc_exception_class:
        cls = _rc_exception_class[int_code]
    else:
        cls_name = 'GitCommandError_%d' % int_code
        cls = type(cls_name, (GitCommandError,), {'code': int_code})
        _rc_exception_class[int_code] = cls
    return cls


class GitCommandError(Exception):
    def __init__(self, message):
        super(GitCommandError, self).__init__(message)
        self.message = message

    def __str__(self):
        # We get self.code from the concrete class (see rc_exception_class)
        return 'Git command failed, code %d, message: %s' % (self.code, 
            self.message)


Default = object()
class GitCommand(object):
    def __init__(self, args, cwd=None, env=None, ok_codes=(0,), readonly=False,
            no_io=False, flush_print=True):
        # Uncomment to debug:
        # print(' '.join(args))
        self.args = args
        self.cwd = cwd
        if env:
            self.env = dict((k, v) for k, v in env.iteritems() if v is not None)
            if not self.env:
                self.env = None
        else:
            self.env = None
        self.ok_codes = ok_codes
        self.readonly = readonly
        self._no_io = no_io
        self._stdin_fd = None if (no_io or readonly) else subprocess.PIPE
        self._stdout_fd = None if no_io else subprocess.PIPE
        self.flush_print = flush_print
        self.process = None
        self.output = ''

    def clone(self):
        return GitCommand(self.args, cwd=self.cwd, env=self.env,
            ok_codes=self.ok_codes, readonly=self.readonly, no_io=self._no_io,
            flush_print=self.flush_print)

    def popen(self, stdin=Default, stdout=Default):
        if stdin is Default:
            stdin = self._stdin_fd
        if stdout is Default:
            stdout = self._stdout_fd
        if self.process is not None:
            return self.process
        if self.env:
            env = os.environ.copy()
            env.update(self.env)
        else:
            env = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        else:
            startupinfo = None
        self.process = subprocess.Popen(args=self.args, cwd=self.cwd, env=env,
            startupinfo=startupinfo, stdin=stdin, stdout=stdout, 
            stderr=subprocess.STDOUT)
        return self.process

    @property
    def returncode(self):
        if self.process is None:
            return None
        return self.process.returncode

    def __int__(self):
        return self.returncode

    def __nonzero__(self):
        return self.returncode in self.ok_codes

    def __eq__(self, other):
        return self.returncode == other

    def wait(self, chomp=True):
        if chomp:
            self.output += self.popen().communicate()[0]
        else:
            self.popen().wait()
        return self

    def check(self, chomp=True):
        if chomp:
            self.output += self.popen().communicate()[0]
        else:
            self.wait()
        if not self:
            if not chomp:
                self.output += self.popen().communicate()[0]
            raise rc_exception_class(self)(self.output)
        return self

    @property
    def stdin(self):
        return self.popen().stdin

    @property
    def stdout(self):
        return self.popen().stdout

    def read(self, size=None):
        if size is not None:
            return self.stdout.read(size)
        else:
            return self.stdout.read()

    def __iter__(self):
        return iter(self.stdout)

    def println(self, *values):
        print(*values, file=self.stdin)
        if self.flush_print:
            self.stdin.flush()
        return self


StatusEntry = collections.namedtuple('StatusEntry', 
    ('path', 'index_status', 'work_tree_status', 'old_path'))
LogEntry = collections.namedtuple('LogEntry', 
    ('commit_id', 'refs', 'parent_ids',
        'author_name', 'author_email', 'author_date',
        'committer_name', 'committer_email', 'committer_date', 
        'message'))
DiffSummaryEntry = collections.namedtuple('DiffSummaryEntry',
    ('path', 'lines_added', 'lines_deleted', 'new_path'))


def _parse_status_output(output):
    paths = re.finditer('(.*?)\0', output)
    while True:
        path = paths.next().group(1)
        index_status = _status_char_map[path[0]]
        work_tree_status = _status_char_map[path[1]]
        if index_status in (RENAMED, COPIED):
            old_path = paths.next().group(1)
        else:
            old_path = None
        yield StatusEntry(path[3:], index_status, work_tree_status, old_path)


def _parse_log_file(log_file):
    def nextline():
        return log_file.readline()
    while True:
        line = nextline().rstrip()
        if not line: return
        if not line.startswith('#'):
            raise ValueError('Invalid Git log output format')
        else:
            line = line[1:]
        commit_id = line
        line = nextline().strip('\n ()')
        refs = tuple(line.split(', ')) if line else ()
        line = nextline().rstrip()
        parent_ids = tuple(line.split(' ')) if line else ()
        author_name = nextline().rstrip()
        author_email = nextline().rstrip()
        author_date = dateutil.parser.parse(nextline().rstrip())
        commiter_name = nextline().rstrip()
        commiter_email = nextline().rstrip()
        commiter_date = dateutil.parser.parse(nextline().rstrip())
        message = []
        line = nextline().rstrip('\n')
        while line and (line != '.'):
            message.append(line[1:])
            line = nextline().rstrip('\n')
        message = tuple(message)
        yield LogEntry(commit_id, refs, parent_ids, author_name, author_email, 
            author_date, commiter_name, commiter_email, commiter_date, message)

LOG_FMT = r'#%H%n%d%n%P%n%aN%n%aE%n%ai%n%cN%n%cE%n%ci%n%w(0,1,1)%B%n%w(0,0,0).'


DIFF_SUMMARY_REGEX = re.compile(r'([^\t]+)\t([^\t]+)\t(.*)')

def _parse_diff_summary(output):
    entries = re.finditer('(.*?)\0', output)
    while True:
        entry = entries.next().group(1)
        added, deleted, path = DIFF_SUMMARY_REGEX.match(entry).groups()
        if path:
            new_path = None
        else:
            path = entries.next().group(1)
            new_path = entries.next().group(1)
        try:
            added = int(added)
        except ValueError:
            added = None
        try:
            deleted = int(deleted)
        except ValueError:
            deleted = None
        yield DiffSummaryEntry(path, added, deleted, new_path)

REF_BRANCH = 0
REF_REMOTE = 1
REF_TAG = 2
REF_OTHER = -1


def parse_ref(ref):
    if ref.startswith('refs/heads/'):
        return ref[11:], REF_BRANCH
    elif ref.startswith('refs/remotes/'):
        return ref[13:], REF_REMOTE
    elif ref.startswith('refs/tags/'):
        return ref[10:], REF_TAG
    else:
        return ref, REF_OTHER


class Git(object):
    def __init__(self, exe_name = 'git'):
        self.exe = GitExe(exe_name)

    def get_properties(self, path, git_dir=False, work_tree_dir=False,
            bare=False):
        def abs_path(result):
            if not os.path.isabs(result):
                result = os.path.join(path, result)
            return os.path.normpath(result)
        properties = []
        if git_dir: properties.append(('--git-dir', abs_path))
        if work_tree_dir: properties.append(('--show-toplevel', abs_path))
        if bare: properties.append(('--is-bare-repository', is_true_str))
        switches, parsers = zip(*properties)
        cmd = self.exe.rev_parse(switches, _cwd=path)
        results = cmd.check().output.splitlines()
        return [parse(result) for parse, result in zip(parsers, results)]

    def is_git_dir(self, path):
        try:
            return (path == self.get_properties(path, git_dir=True)[0])
        except:
            return False

    def init(self, repo_dir, bare=False, shared=None, template_dir=None,
            separate_git_dir=None):
        if shared is False:
            shared_mask = 'umask'
        elif shared is True:
            shared_mask = 'group'
        elif isinstance(shared, int):
            shared_mask = '{:04o}'.format(shared)
        else:
            shared_mask = shared
        cmd = self.exe.init(repo_dir, quiet=True, bare=bare, shared=shared_mask,
            template=template_dir, separate_git_dir=separate_git_dir)
        return cmd.check().output

    def _repo_opts(self, work_tree_dir, git_dir):
        env = None
        if git_dir and work_tree_dir:
            if os.path.join(work_tree_dir, '.git') != git_dir:
                env = {'GIT_DIR': git_dir, 'GIT_WORK_TREE': work_tree_dir}
        return dict(_cwd=(work_tree_dir or git_dir), _env=env)

    def refs(self, work_tree_dir, git_dir=None, branches=False, remotes=False, 
            tags=False, globs=None):
        args = ['--symbolic']
        if branches: args.append('--glob=refs/heads/*')
        if remotes: args.append('--glob=refs/remotes/*')
        if tags: args.append('--glob=refs/tags/*')
        if globs:
            if isinstance(globs, basestring):
                args.append('--glob=%s' % globs)
            else:
                args.extend('--glob=%s' % glob for glob in globs)
        if len(args) == 1: args.append('--all')
        cmd = self.exe.rev_parse(*args, 
            **self._repo_opts(work_tree_dir, git_dir))
        return cmd.check().output.splitlines()

    def head(self, work_tree_dir, git_dir=None):
        cmd = self.exe.rev_parse('HEAD', symbolic_full_name=True, 
            **self._repo_opts(work_tree_dir, git_dir))
        result = cmd.check().output.rstrip()
        if result.startswith('refs/'):
            return result

    def status(self, work_tree_dir, git_dir=None, paths=()):
        cmd = self.exe.status('-z', '--ignored', '--', paths,
            **self._repo_opts(work_tree_dir, git_dir))
        return _parse_status_output(cmd.check().output)

    def diff_summary(self, work_tree_dir, git_dir=None, revs=(), paths=(), 
            staged=False, renames=False):
        cmd = self.exe.diff('-z', '--numstat', revs, '--', paths,
            staged=staged, find_renames=renames,
            **self._repo_opts(work_tree_dir, git_dir))
        return _parse_diff_summary(cmd.check().output)

    def stage(self, work_tree_dir, git_dir=None, paths=None):
        cmd = self.exe.add('--all', '--', paths or '.',
            **self._repo_opts(work_tree_dir, git_dir))
        return cmd.check().output

    def unstage(self, work_tree_dir, git_dir=None, paths=None):
        cmd = self.exe.reset('-q', '--', paths or '.',
            **self._repo_opts(work_tree_dir, git_dir))
        return cmd.check().output

    def commit(self, work_tree_dir, message, git_dir=None, paths=(),
            amend=False):
        cmd = self.exe.commit('--', paths, file='-', amend=amend, only=bool(paths),
            **self._repo_opts(work_tree_dir, git_dir))
        cmd.stdin.write(message)
        cmd.stdin.flush()
        cmd.stdin.close()
        return cmd.check().output

    def log(self, work_tree_dir, git_dir=None, revs=None, paths=(),
            all=False, max_commits=None, skip_commits=None):
        cmd = self.exe.log(revs or (), '--', paths, all=all, format=LOG_FMT, 
            decorate='full', max_count=max_commits, skip=skip_commits, parents=True,
            **self._repo_opts(work_tree_dir, git_dir))
        return _parse_log_file(cmd.stdout)

