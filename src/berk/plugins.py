import sys
import imp
import importlib
import os.path
import schema
import yaml

from collections import namedtuple, defaultdict, OrderedDict
from semantic_version import Version, Spec
from pygraph.classes.digraph import digraph
from pygraph.algorithms.traversal import traversal
from pygraph.algorithms.accessibility import accessibility
from pygraph.algorithms.sorting import topological_sorting


def relaxed_spec(spec_str):
    if spec_str and (spec_str[0] not in '<>=!'):
        min_ver = Version(spec_str, partial=True)
        return Spec('>=%s' % spec_str, '<%d.0.0' % (min_ver.major + 1))
    return Spec(spec_str)


dependency_schema = {'id': schema.required(str), 
    'version': schema.optional(schema.chain(str, relaxed_spec))}
PluginDependency = namedtuple('PluginDependency', dependency_schema.keys())
dependency_coercer = schema.chain(schema.dict(dependency_schema),
    schema.kwargs(PluginDependency))

manifest_schema = {'id': schema.required(str), 
    'version': schema.required(schema.chain(str, Version)), 
    'name': schema.required(str), 'author': schema.optional(str), 
    'description': schema.optional(str), 'main_module': schema.optional(str), 
    'src_path': schema.optional(str), 
    'required_plugins': schema.optional(schema.list(dependency_coercer)), 
    'exported_modules': schema.optional(schema.list(str))}
PluginManifest = namedtuple('PluginManifest', manifest_schema.keys())
manifest_coercer = schema.chain(schema.dict(manifest_schema), 
    schema.kwargs(PluginManifest))

PluginInfo = namedtuple('PluginInfo', ('active', 'manifest', 'path'))


class PluginModuleLoader(object):
    def __init__(self, file, pathname, description):
        self.file = file
        self.pathname = pathname
        self.description = description

    def load_module(self, full_name):
        try:
            return imp.load_module(full_name, self.file, self.pathname, 
                self.description)
        finally:
            if self.file: self.file.close()

class PluginModuleFinder(object):
    def __init__(self, plugin_path):
        self.plugin_path = plugin_path
        self.plugin_modules = []

    def find_module(self, full_name, path=None):
        if full_name in sys.modules: return
        package, _, name = full_name.rpartition('.')
        pkg_path = os.path.normpath(
            reduce(os.path.join, package.split('.'), self.plugin_path))
        try:
            module_info = imp.find_module(name, [pkg_path])
        except ImportError: return
        self.plugin_modules.append(full_name)
        return PluginModuleLoader(*module_info)


class DependencyProblem(object):
    def __init__(self, plugin_id, dependency):
        self.plugin_id = plugin_id
        self.dependency = dependency

class MissingDependency(DependencyProblem):
    pass

class IncorrectVersion(DependencyProblem):
    pass

class IndirectDependency(DependencyProblem):
    pass

class DisabledDependency(DependencyProblem):
    pass

class CyclicDependency(DependencyProblem):
    def __init__(self, plugin_id):
        super(CyclicDependency, self).__init__(plugin_id, None)


class PluginManagerError(Exception):
    pass

class LoadDependencyError(PluginManagerError):
    def __init__(self, plugin_id, dependency):
        super(DependencyError, self).__init__(
            'Plugin dependency not loaded (id=%r, dependency=%r, version=%r)' % 
            (plugin_id, dependency.id, str(dependency.version)))
        self.plugin_id = plugin_id
        self.dependency = dependency

class UnloadDependencyError(PluginManagerError):
    def __init__(self, plugin_id, dependent_id):
        super(DependencyError, self).__init__(
            'Dependent plugin should be unloaded (id=%r, dependent=%r)' % 
            (plugin_id, dependency.id))
        self.plugin_id = plugin_id
        self.dependent_id = dependent_id


class PluginManager(object):
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.manifests = {}
        self.enabled_plugins = set()
        self.plugins = OrderedDict()
        self.plugin_modules = {}
        self.module_refcount = defaultdict(int)
        self.mark_dirty()

    def plugin_path(self, plugin_id):
        return os.path.join(self.base_dir, plugin_id)

    def load_manifest(self, filename):
        with open(filename, 'r') as f:
            manifest_dict = yaml.safe_load(f)
        return manifest_coercer(manifest_dict)

    def add_manifest(self, manifest, enabled=True):
        if manifest.id in self.manifests:
            raise ValueError('Duplicate plugin ID: %s' % plugin_id)
        self.manifests[manifest.id] = manifest
        if enabled:
            self.enabled_plugins.add(manifest.id)
        self.mark_dirty()

    def add_plugin(self, plugin_id, enabled=True, manifest_path=None):
        if not manifest_path:
            manifest_path = os.path.join(self.plugin_path(plugin_id), 
                'manifest.yml')
        self.add_manifest(self.load_manifest(manifest_path), enabled=enabled)

    def plugin_dependencies(self, plugin_id):
        manifest = self.manifests[plugin_id]
        return manifest.required_plugins or []

    @property
    def dirty(self):
        return self.dependency_graph is None

    def mark_dirty(self):
        self.dependency_graph = None
        self._dependency_problems = None
        self._load_order = None

    def resolve_plugin_dependencies(self):
        graph = digraph()
        problems = defaultdict(list)

        def check_plugin_dependencies(plugin_id):
            result = True

            def add_problem(problem_type, plugin_id, dependency):
                problems[plugin_id].append(problem_type(plugin_id, dependency))
                result = False

            for dependency in self.plugin_dependencies(plugin_id):
                if dependency.id not in self.manifests:
                    add_problem(MissingDependency, plugin_id, dependency)
                elif dependency.version:
                    if manifests[required_id].version not in dependency.version:
                        add_problem(IncorrectVersion, plugin_id, dependency)
                elif dependency.id not in graph:
                    if dependency.id in self.enabled_plugins:
                        add_problem(IndirectDependency, plugin_id, dependency)
                    else:
                        add_problem(DisabledDependency, plugin_id, dependency)

            return result

        def remove_dependents(plugin_id):
            for node in traversal(graph, plugin_id, 'pre'):
                for dependent in graph[node]:
                    edge = node, dependent
                    problems[dependent].append(IndirectDependency(dependent, 
                        graph.get_edge_properties(edge)['dependency']))
                graph.del_node(node)

        graph.add_nodes(self.enabled_plugins)
        for plugin_id in self.enabled_plugins:
            if check_plugin_dependencies(plugin_id):
                for dependency in self.plugin_dependencies(plugin_id):
                    edge = dependency.id, plugin_id
                    graph.add_edge(edge)
                    graph.set_edge_properties(edge, dependency=dependency)
            else:
                remove_dependents(plugin_id)

        transitive_deps = accessibility(graph)
        cycle_nodes = [
            node
            for node in graph
            if any(
                (node in transitive_deps[dependent])
                for dependent in transitive_deps[node]
                if dependent != node)]
        for node in cycle_nodes:
            problems[node].append(CyclicDependency(node))
            graph.del_node(node)

        self.dependency_graph = graph
        self._dependency_problems = problems
        self._load_order = topological_sorting(graph)

    @property
    def dependency_problems(self):
        if self.dirty:
            self.resolve_plugin_dependencies()
        return self._dependency_problems

    @property
    def load_order(self):
        if self.dirty:
            self.resolve_plugin_dependencies()
        return self._load_order

    def dependent_plugins(self, plugin_id):
        if self.dirty:
            self.resolve_plugin_dependencies()
        return self.dependency_graph[plugin_id]

    def _load_plugin(self, plugin_id, path=None):
        manifest = self.manifests[plugin_id]
        path = path or manifest.src_path or self.plugin_path(plugin_id)
        imp.acquire_lock()
        try:
            finder = PluginModuleFinder(path)
            sys.meta_path.append(finder)
            main_module = manifest.main_module or plugin_id
            result = importlib.import_module(main_module)
            plugin_exports = [main_module]
            plugin_modules = []
            if manifest.exported_modules:
                plugin_exports.extend(manifest.exported_modules)
            for module_name in finder.plugin_modules:
                if hasattr(sys.modules[module_name], '__path__'):
                    pkg_prefix = module_name + '.'
                    should_remove = not any(
                        name.startswith(pkg_prefix) for name in plugin_exports)
                else:
                    should_remove = module_name not in plugin_exports
                if should_remove:
                    sys.modules.pop(module_name, None)
                else:
                    plugin_modules.append(module_name)
                    self.module_refcount[module_name] += 1
            self.plugin_modules[plugin_id] = plugin_modules
            return result
        finally:
            sys.meta_path.remove(finder)
            imp.release_lock()

    def load_plugin(self, plugin_id, path=None, recursive=False):
        for dependency in self.plugin_dependencies(plugin_id):
            if dependency.id not in self.plugins:
                if not recursive:
                    raise LoadDependencyError(plugin_id, dependency)
                else:
                    self.load_plugin(dependency_id, recursive=True)
        plugin = self._load_plugin(plugin_id, path)
        self.plugins[plugin_id] = plugin
        return plugin

    def load_all(self):
        for plugin_id in self.load_order:
            self.load_plugin(plugin_id)

    def _unload_plugin(self, plugin_id):
        for module_name in self.plugin_modules[plugin_id]:
            self.module_refcount[module_name] -= 1
            if not self.module_refcount[module_name]:
                sys.modules.pop(module_name, None)
        del self.plugin_modules[plugin_id]
        del self.plugins[plugin_id]

    def unload_plugin(self, plugin_id, recursive=False):
        for dependent in self.dependent_plugins(plugin_id):
            if dependent in self.plugins:
                if not recursive:
                    raise UnloadDependencyError(plugin_id, dependent)
                else:
                    self.unload_plugin(dependent, recursive=True)
        self._unload_plugin(plugin_id)

    def enable_plugin(self, plugin_id):
        if plugin_id in self.enabled_plugins: return
        self.enabled_plugins.add(plugin_id)
        self.mark_dirty()

    def disable_plugin(self, plugin_id, unload_dependents=False):
        if plugin_id not in self.enabled_plugins: return
        if plugin_id in self.plugins:
            self.unload_plugin(plugin_id, recursive=unload_dependents)
        self.enabled_plugins.remove(plugin_id)
        self.mark_dirty()
