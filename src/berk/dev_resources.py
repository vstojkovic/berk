import os
import os.path
import tempfile
import subprocess

from PySide import QtCore

def load_resources():
    global rcc_data
    resource_dir = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), '..', '..', 'resources'))
    qrc_files = [os.path.join(path, filename)
        for path, dirlist, filelist in os.walk(resource_dir)
        for filename in filelist
        if os.path.splitext(filename)[1] == '.qrc']
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    else:
        startupinfo = None
    temp_fd, temp_path = tempfile.mkstemp()
    subprocess.check_call(
        ['rcc', '-o', temp_path, '-binary'] + qrc_files, stdout=temp_fd, 
        startupinfo=startupinfo)
    with os.fdopen(temp_fd) as rcc_file:
        rcc_data = rcc_file.read()
    os.remove(temp_path)
    QtCore.QResource.registerResourceData(rcc_data)


load_resources()
