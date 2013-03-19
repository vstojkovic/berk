import contextlib

from ctypes import windll, WinError, Structure, byref, sizeof, POINTER, memset
from ctypes import c_bool, c_void_p, c_uint32, c_int32, c_uint16, c_ubyte
from ctypes import c_wchar, c_wchar_p, c_char_p

from PySide.QtGui import QFileIconProvider, QIcon, QImage, QPixmap

class FileIconProvider(object):
    def __init__(self):
        self.qt_provider = QFileIconProvider()

    def __getitem__(self, path):
        icon = QIcon()
        has_images = False
        with disposable_hicon(get_file_icon(path)) as hicon:
            pixmap = pixmap_from_hicon(hicon)
            if pixmap:
                icon.addPixmap(pixmap)
                has_images = True
        with disposable_hicon(get_file_icon(path, large=True)) as hicon:
            pixmap = pixmap_from_hicon(hicon)
            if pixmap:
                icon.addPixmap(pixmap)
                has_images = True
        if has_images: return icon
        return self.qt_provider.icon(QFileIconProvider.File)


@contextlib.contextmanager
def disposable_hicon(hicon):
    try:
        yield hicon
    finally:
        DestroyIcon(hicon)


_com_initialized = False

def initialize_com():
    global _com_initialized
    if not _com_initialized:
        CoInitializeEx(None, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE)
        _com_initialized = True

def get_file_icon(path, large=False):
    info = SHFILEINFO()
    flags = SHGFI_ICON | SHGFI_SYSICONINDEX
    flags |= SHGFI_LARGEICON if large else SHGFI_SMALLICON
    initialize_com()
    rc = SHGetFileInfo(path, 0, byref(info), sizeof(info), flags)
    if not rc and info.iIcon: return
    return info.hIcon

def image_from_hbitmap(hdc, bitmap, width, height):
    bitmap_info = BITMAPINFO()
    memset(byref(bitmap_info), 0, sizeof(bitmap_info))
    bitmap_info.bmiHeader.biSize = sizeof(bitmap_info.bmiHeader)
    bitmap_info.bmiHeader.biWidth = width
    bitmap_info.bmiHeader.biHeight = -height
    bitmap_info.bmiHeader.biPlanes = 1
    bitmap_info.bmiHeader.biBitCount = 32
    bitmap_info.bmiHeader.biCompression = BI_RGB
    bitmap_info.bmiHeader.biSizeImage = width * height * 4
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    if image.isNull(): return image
    data = (c_ubyte * bitmap_info.bmiHeader.biSizeImage)()
    if not GetDIBits(hdc, bitmap, 0, height, data, byref(bitmap_info), 
            DIB_RGB_COLORS):
        raise WindowsError('call to GetDIBits failed')
    bytes_per_line = image.bytesPerLine()
    for y in xrange(0, height):
        offset = y * bytes_per_line
        line = image.scanLine(y)
        for x in xrange(0, bytes_per_line):
            line[x] = chr(data[offset + x])
    return image

def pixmap_from_hicon(hicon):
    if not hicon: return
    screen_device = GetDC(None)
    hdc = CreateCompatibleDC(screen_device)
    ReleaseDC(None, screen_device)
    icon_info = ICONINFO()
    if not GetIconInfo(hicon, byref(icon_info)):
        raise WindowsError('call to GetIconInfo failed')
    width = icon_info.xHotspot * 2
    height = icon_info.yHotspot * 2
    bitmap_header = BITMAPINFOHEADER()
    bitmap_header.biSize = sizeof(bitmap_header)
    bitmap_header.biWidth = width
    bitmap_header.biHeight = height
    bitmap_header.biPlanes = 1
    bitmap_header.biBitCount = 32
    bitmap_header.biCompression = BI_RGB
    bitmap_header.biSizeImage = 0
    bitmap_header.biXPelsPerMeter = 0
    bitmap_header.biYPelsPerMeter = 0
    bitmap_header.biClrUsed = 0
    bitmap_header.biClrImportant = 0
    bits = c_void_p()
    win_bitmap = CreateDIBSection(hdc, byref(bitmap_header), DIB_RGB_COLORS, 
        byref(bits), None, 0);
    old_hdc = SelectObject(hdc, win_bitmap)
    DrawIconEx(hdc, 0, 0, hicon, width, height, 0, None, DI_NORMAL)
    image = image_from_hbitmap(hdc, win_bitmap, width, height)
    # do the alpha shit
    DeleteObject(icon_info.hbmMask)
    DeleteObject(icon_info.hbmColor)
    SelectObject(hdc, old_hdc)
    DeleteObject(win_bitmap)
    DeleteDC(hdc)
    return QPixmap.fromImage(image)


class SHFILEINFO(Structure):
    _fields_ = [
        ("hIcon", c_void_p),
        ("iIcon", c_int32),
        ("dwAttributes", c_uint32),
        ("szDisplayName", c_wchar * 260),
        ("szTypeName", c_wchar * 80)]

COINIT_APARTMENTTHREADED = 0x2
COINIT_DISABLE_OLE1DDE = 0x4

SHGFI_ICON = 0x100
SHGFI_SYSICONINDEX = 0x4000
SHGFI_LARGEICON = 0x0
SHGFI_SMALLICON = 0x1

SHGetFileInfo = windll.shell32.SHGetFileInfoW
SHGetFileInfo.argtypes = [c_wchar_p, c_uint32, POINTER(SHFILEINFO), c_uint32,
    c_uint32]
SHGetFileInfo.restype = c_int32

CoInitializeEx = windll.ole32.CoInitializeEx
CoInitializeEx.argtypes = [c_void_p, c_uint32]
CoInitializeEx.restype = c_uint32

class ICONINFO(Structure):
    _fields_ = [
        ("fIcon", c_bool),
        ("xHotspot", c_uint32),
        ("yHotspot", c_uint32),
        ("hbmMask", c_void_p),
        ("hbmColor", c_void_p)]

DI_NORMAL = 3

GetIconInfo = windll.user32.GetIconInfo
GetIconInfo.argtypes = [c_void_p, POINTER(ICONINFO)]
GetIconInfo.restype = c_bool

GetDC = windll.user32.GetDC
GetDC.argtypes = [c_void_p]
GetDC.restype = c_void_p

ReleaseDC = windll.user32.ReleaseDC
ReleaseDC.argtypes = [c_void_p, c_void_p]
ReleaseDC.restype = c_int32

DrawIconEx = windll.user32.DrawIconEx
DrawIconEx.argtypes = [c_void_p, c_int32, c_int32, c_void_p, c_int32, c_int32,
    c_uint32, c_void_p, c_uint32]
DrawIconEx.restype = c_bool

DestroyIcon = windll.user32.DestroyIcon
DestroyIcon.argtypes = [c_void_p]
DestroyIcon.restype = c_bool

class BITMAPINFOHEADER(Structure):    
    _fields_ = [
        ('biSize', c_uint32),
        ('biWidth', c_int32),
        ('biHeight', c_int32),
        ('biPlanes', c_uint16),
        ('biBitCount', c_uint16),
        ('biCompression', c_uint32),
        ('biSizeImage', c_uint32),
        ('biXPelsPerMeter', c_int32),
        ('biYPelsPerMeter', c_int32),
        ('biClrUsed', c_uint32),
        ('biClrImportant', c_uint32)
    ]

class BITMAPINFO(Structure):    
    _fields_ = [
        ('bmiHeader', BITMAPINFOHEADER),
        ('bmiColors', c_uint32 * 3)
    ]

BI_RGB = 0

DIB_RGB_COLORS = 0

CreateCompatibleDC = windll.gdi32.CreateCompatibleDC
CreateCompatibleDC.argtypes = [c_void_p]
CreateCompatibleDC.restype = c_void_p

DeleteDC = windll.gdi32.DeleteDC
DeleteDC.argtypes = [c_void_p]
DeleteDC.restype = c_bool

SelectObject = windll.gdi32.SelectObject
SelectObject.argtypes = [c_void_p, c_void_p]
SelectObject.restype = c_void_p

DeleteObject = windll.gdi32.DeleteObject
DeleteObject.argtypes = [c_void_p]
DeleteObject.restype = c_bool

CreateDIBSection = windll.gdi32.CreateDIBSection
CreateDIBSection.argtypes = [c_void_p, POINTER(BITMAPINFOHEADER), c_uint32, 
    POINTER(c_void_p), c_void_p, c_uint32]
CreateDIBSection.restype = c_void_p

GetDIBits = windll.gdi32.GetDIBits
GetDIBits.argtypes = [c_void_p, c_void_p, c_uint32, c_uint32, POINTER(c_ubyte), 
    POINTER(BITMAPINFO), c_uint32]
GetDIBits.restype = c_int32
