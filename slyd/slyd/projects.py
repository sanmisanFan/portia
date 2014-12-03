"""
Projects Resource

Manages listing/creation/deletion/renaming of slybot projects on
the local filesystem. Routes to the appropiate resource for fetching
pages and project spec manipulation.
"""

import json, re, shutil, errno, os
from os.path import join
from twisted.web.resource import NoResource
from .resource import SlydJsonResource


# stick to alphanum . and _. Do not allow only .'s (so safe for FS path)
_INVALID_PROJECT_RE = re.compile('[^A-Za-z0-9._]|^\.*$')


_SETTINGS_TEMPLATE = \
"""# Automatically created by: slyd
import os

SPIDER_MANAGER_CLASS = 'slybot.spidermanager.ZipfileSlybotSpiderManager'
EXTENSIONS = {'slybot.closespider.SlybotCloseSpider': 1}
ITEM_PIPELINES = ['slybot.dupefilter.DupeFilterPipeline']
SPIDER_MIDDLEWARES = {'slybot.spiderlets.SpiderletsMiddleware': 999} # as close as possible to spider output
SLYDUPEFILTER_ENABLED = True

PROJECT_ZIPFILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

try:
    from local_slybot_settings import *
except ImportError:
    pass

"""

_SETUP_PY_TEMPLATE = \
"""# Automatically created by: slyd

from setuptools import setup, find_packages

setup(
    name         = '%s',
    version      = '1.0',
    packages     = find_packages(),
    package_data = {
        'spiders': ['*.json']
    },
    data_files = [('', ['project.json', 'items.json', 'extractors.json'])],
    entry_points = {'scrapy': ['settings = spiders.settings']},
    zip_safe = True
)
"""

_SCRAPY_TEMPLATE = \
"""# Automatically created by: slyd

[settings]
default = slybot.settings
"""

def allowed_project_name(name):
    return not _INVALID_PROJECT_RE.search(name)


class ProjectsResource(SlydJsonResource):

    def __init__(self, settings):
    	SlydJsonResource.__init__(self)
    	self.projectsdir = settings['SPEC_DATA_DIR']

    def getChildWithDefault(self, project_path_element, request):
        # TODO: check exists, user has access, etc.
        # rely on the CrawlerSpec for this as storage and auth
        # can be customized
        request.project = project_path_element
        try:
            next_path_element = request.postpath.pop(0)
        except IndexError:
            next_path_element = None
        if next_path_element not in self.children:
            raise NoResource("No such child resource.")
        request.prepath.append(project_path_element)
        return self.children[next_path_element]

    def list_projects(self):
        try:
            for fname in os.listdir(self.projectsdir):
                if os.path.isdir(os.path.join(self.projectsdir, fname)):
                    yield fname
        except OSError as ex:
            if ex.errno != errno.ENOENT:
                raise

    def create_project(self, project_name):
    	project_filename = self.project_filename(project_name)

        os.makedirs(project_filename)
        with open(join(project_filename, 'project.json'), 'wb') as outf:
            outf.write('{}')

        with open(join(project_filename, 'scrapy.cfg'), 'w') as outf:
            outf.write(_SCRAPY_TEMPLATE)

        with open(join(project_filename, 'setup.py'), 'w') as outf:
            outf.write(_SETUP_PY_TEMPLATE % project_name)

        os.makedirs(join(project_filename, 'spiders'))

        with open(join(project_filename, 'spiders', '__init__.py'), 'w') as outf:
            outf.write('')

        with open(join(project_filename, 'spiders', 'settings.py'), 'w') as outf:
            outf.write(_SETTINGS_TEMPLATE)


    def rename_project(self, from_name, to_name):
        os.rename(self.project_filename(from_name),
            self.project_filename(to_name))

    def remove_project(self, name):
        shutil.rmtree(self.project_filename(name))

    def project_filename(self, project_name):
        return join(self.projectsdir, project_name)

    def handle_project_command(self, command_spec):
        command = command_spec.get('cmd')
        dispatch_func = self.project_commands.get(command)
        if dispatch_func is None:
            self.bad_request(
                "unrecognised cmd arg %s, available commands: %s" %
                (command, ', '.join(self.project_commands.keys())))
        args = command_spec.get('args', [])
        for project in args:
            if not allowed_project_name(project):
                self.bad_request('invalid project name %s' % project)
        try:
            retval = dispatch_func(self, *args)
        except TypeError:
            self.bad_request("incorrect args for %s" % command)
        except OSError as ex:
            if ex.errno == errno.ENOENT:
                self.error(404, "Not Found", "No such resource")
            elif ex.errno == errno.EEXIST or ex.errno == errno.ENOTEMPTY:
                self.bad_request("A project with that name already exists")
            raise
        return retval or ''

    def render_GET(self, request):
        request.write(json.dumps(sorted(self.list_projects())))
        return '\n'

    def render_POST(self, request):
        obj = self.read_json(request)
        return self.handle_project_command(obj)

    project_commands = {
        'create': create_project,
        'mv': rename_project,
        'rm': remove_project
    }
