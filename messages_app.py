import webview
from webview.menu import Menu, MenuAction, MenuSeparator
import threading
import sys
import os
import pystray
from PIL import Image, ImageDraw
import json
import webbrowser
import ctypes
from ctypes import wintypes
import time
import socket
import urllib.request
from win11toast import toast as win11_toast

# ─── Single-instance lock ─────────────────────────────────────────────────────
_LOCK_SOCKET = None

def ensure_single_instance():
    global _LOCK_SOCKET
    try:
        _LOCK_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _LOCK_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _LOCK_SOCKET.bind(('127.0.0.1', 47821))
        return True
    except OSError:
        return False

# ─── Config ───────────────────────────────────────────────────────────────────
_APP_DATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'google-messages')
os.makedirs(_APP_DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(_APP_DATA_DIR, 'config.json')

DEFAULT_SETTINGS = {
    'tray_enabled':              True,
    'start_in_tray':             False,
    'taskbar_flash':             True,
    'minimize_to_tray':          True,
    'close_to_tray':             True,
    'hide_notification_content': False,
    'monochrome_icon':           False,
    'tray_icon_red_dot':         True,
    'check_for_updates':         True,
    'menu_visible':              True,
    'saved_window_width':        1100,
    'saved_window_height':       800,
    'saved_window_x':            None,
    'saved_window_y':            None,
}

def load_settings():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                saved = json.load(f)
            return {**DEFAULT_SETTINGS, **saved}
        except:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings_file():
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(settings, f, indent=2)
    except:
        pass

settings = load_settings()

# ─── Globals ──────────────────────────────────────────────────────────────────
window           = None
tray_icon        = None
is_quitting      = False
window_is_hidden = False
_unread_count    = 0
_menu_visible    = settings.get('menu_visible', True)
_main_form       = None   # WinForms Form reference, cached once

# Checkable menu items → settings key
CHECKABLE_ITEMS = {
    'Enable System Tray Icon':     ('tray_enabled',              True),
    'Start in Tray':               ('start_in_tray',             False),
    'Minimize to Tray':            ('minimize_to_tray',          True),
    'Close to Tray':               ('close_to_tray',             True),
    'Monochrome Icon':             ('monochrome_icon',           False),
    'Red Dot for Unread':          ('tray_icon_red_dot',         True),
    'Hide Notification Content':   ('hide_notification_content', False),
    'Flash Taskbar on Message':    ('taskbar_flash',             True),
    'Check for Updates on Launch': ('check_for_updates',         True),
}

# ─── Win32 Flash ──────────────────────────────────────────────────────────────
class FLASHWINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('hwnd', wintypes.HWND),
                ('dwFlags', wintypes.DWORD), ('uCount', wintypes.UINT),
                ('dwTimeout', wintypes.DWORD)]
FLASHW_ALL       = 0x00000003
FLASHW_TIMERNOFG = 0x0000000C
FLASHW_STOP      = 0x00000000

# ─── Alt-key keyboard hook ────────────────────────────────────────────────────
WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_SYSKEYDOWN  = 0x0104
WM_SYSKEYUP    = 0x0105
VK_MENU        = 0x12

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wintypes.DWORD), ('scanCode', wintypes.DWORD),
                ('flags',  wintypes.DWORD), ('time',     wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_ulong)]

_hook_ref = None
_alt_solo = False   # True when Alt pressed with no other key yet

# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)

def is_our_process_focused():
    """True if the foreground window belongs to our process (by PID)."""
    try:
        fg = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        return pid.value == os.getpid()
    except:
        return False

def find_main_hwnd():
    """Find any top-level HWND belonging to our process."""
    result = []
    pid = os.getpid()
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    def cb(h, _):
        p = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and ctypes.windll.user32.IsWindowVisible(h):
            n = ctypes.windll.user32.GetWindowTextLengthW(h)
            if n > 0:
                result.append(h)
        return True
    ctypes.windll.user32.EnumWindows(EnumProc(cb), 0)
    return result[0] if result else None

def get_dpi_scale():
    try:
        hwnd = find_main_hwnd() or ctypes.windll.user32.GetDesktopWindow()
        return ctypes.windll.user32.GetDpiForWindow(hwnd) / 96.0
    except:
        return 1.0

def get_window_rect():
    hwnd = find_main_hwnd()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    s = get_dpi_scale()
    x = int(rect.left / s);  y = int(rect.top / s)
    w = int((rect.right - rect.left) / s)
    h = int((rect.bottom - rect.top) / s)
    return (x, y, w, h) if w > 100 and h > 100 else None

def flash_taskbar():
    hwnd = find_main_hwnd()
    if hwnd:
        try:
            fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd,
                            FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
        except: pass

def stop_flash_taskbar():
    hwnd = find_main_hwnd()
    if hwnd:
        try:
            fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_STOP, 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
        except: pass

def _save_window_geometry():
    try:
        r = get_window_rect()
        if r:
            x, y, w, h = r
            settings.update(saved_window_width=w, saved_window_height=h,
                            saved_window_x=x, saved_window_y=y)
            save_settings_file()
    except: pass

# ─── WinForms menu helpers (pythonnet) ────────────────────────────────────────
# pywebview uses WinForms.MenuStrip — NOT a classic Win32 HMENU.
# We manipulate it via pythonnet to avoid any remove/dispose (which crashes).

def _winform_invoke(form, fn):
    """Run fn on the form's UI thread safely."""
    try:
        from System import Action
        if form.InvokeRequired:
            form.Invoke(Action(fn))
        else:
            fn()
    except: pass

def _menu_set_visible(form, visible):
    """Show or hide the MenuStrip on a form (Visible toggle — no dispose)."""
    def _do():
        try:
            for ctrl in form.Controls:
                if type(ctrl).__name__ == 'MenuStrip':
                    ctrl.Visible = visible
        except: pass
    _winform_invoke(form, _do)

def _menu_apply_checkmarks(form):
    """Set ToolStripMenuItem.Checked in-place based on current settings."""
    def _do():
        try:
            for ctrl in form.Controls:
                if type(ctrl).__name__ != 'MenuStrip':
                    continue
                for top in ctrl.Items:
                    try:
                        for sub in top.DropDownItems:
                            try:
                                text = str(sub.Text).strip() if sub.Text else ''
                                if text in CHECKABLE_ITEMS:
                                    key, default = CHECKABLE_ITEMS[text]
                                    sub.Checked = bool(settings.get(key, default))
                            except: pass
                    except: pass
        except: pass
    _winform_invoke(form, _do)

def _cache_main_form():
    """Capture the WinForms Form reference ONCE (before the page title changes it)."""
    global _main_form
    try:
        from System.Windows.Forms import Application
        for form in Application.OpenForms:
            _main_form = form
            return
    except: pass

# ─── Menu bar visibility ──────────────────────────────────────────────────────
def hide_menu_bar():
    global _menu_visible
    if _main_form:
        _menu_set_visible(_main_form, False)
    _menu_visible = False
    settings['menu_visible'] = False
    save_settings_file()

def show_menu_bar():
    global _menu_visible
    if _main_form:
        _menu_set_visible(_main_form, True)
        _menu_apply_checkmarks(_main_form)
    _menu_visible = True
    settings['menu_visible'] = True
    save_settings_file()

# Removed unstable global keyboard hook.
def _install_keyboard_hook():
    pass

# ─── Tray icon ────────────────────────────────────────────────────────────────
def make_icon_image(monochrome=False, red_dot=False):
    try:
        img = Image.open(get_resource_path('icon.png')).convert('RGBA')\
                   .resize((64, 64), Image.LANCZOS)
        if monochrome:
            img = img.convert('LA').convert('RGBA')
        if red_dot:
            draw = ImageDraw.Draw(img)
            d = 14; x0, y0 = 64 - d * 2 - 2, 2
            draw.ellipse([x0, y0, x0 + d * 2, y0 + d * 2], fill=(220, 40, 40, 255))
        return img
    except:
        return Image.new('RGBA', (64, 64), (0, 120, 212, 255))

def update_tray_icon_image():
    if not tray_icon: return
    try:
        mono = settings.get('monochrome_icon', False)
        dot  = settings.get('tray_icon_red_dot', True) and (_unread_count > 0)
        tray_icon.icon = make_icon_image(monochrome=mono, red_dot=dot)
    except: pass

# ─── Update check ─────────────────────────────────────────────────────────────
CURRENT_VERSION = '6.0.2'
RELEASES_API = ('https://api.github.com/repos/'
                'PatrickHusband/google-messages/releases/latest')

def check_for_updates():
    try:
        req = urllib.request.Request(RELEASES_API,
                                     headers={'User-Agent': 'GoogleMessagesDesktop'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
        latest = data.get('tag_name', '').lstrip('v')
        def _ver(v):
            try: return tuple(int(x) for x in v.split('.'))
            except: return (0,)
        if latest and _ver(latest) > _ver(CURRENT_VERSION):
            def on_click(_):
                webbrowser.open('https://github.com/PatrickHusband/'
                                'google-messages/releases/latest')
            win11_toast('Update Available',
                        f'Version {latest} is available. Click to download.',
                        on_click=on_click)
    except: pass

# ─── Window events ────────────────────────────────────────────────────────────
def on_closing():
    global is_quitting, window_is_hidden
    if is_quitting: return True
    _save_window_geometry()
    if settings.get('close_to_tray'):
        window.hide(); window_is_hidden = True
        return False
    return True

def on_minimized():
    global window_is_hidden
    if settings.get('minimize_to_tray'):
        window.hide(); window_is_hidden = True

# ─── Settings toggle ─────────────────────────────────────────────────────────
def toggle_setting(key, default=False):
    """Flip a boolean setting and update the menu checkmark in-place."""
    settings[key] = not settings.get(key, default)
    save_settings_file()
    if key == 'tray_enabled':
        update_tray_state()
    if key in ('monochrome_icon', 'tray_icon_red_dot'):
        update_tray_icon_image()
    # Update checkmarks in the existing MenuStrip — NO remove/re-add (avoids crash)
    if _main_form:
        threading.Thread(target=_menu_apply_checkmarks,
                         args=(_main_form,), daemon=True).start()

# ─── API ──────────────────────────────────────────────────────────────────────
class Api:
    def trigger_notification(self):
        if settings.get('taskbar_flash'):
            flash_taskbar()

    def trigger_notification_with_content(self, title, body, avatar_url=''):
        global _unread_count
        _unread_count += 1
        update_tray_icon_image()
        def _toast():
            if settings.get('hide_notification_content', False):
                t, b, avatar_url_ = 'Google Messages', 'New message', ''
            else:
                t = title or 'Google Messages'
                b = body  or 'New message'
                avatar_url_ = avatar_url or ''
            def on_click(args=None):
                global window_is_hidden, _unread_count
                try:
                    window.show(); window_is_hidden = False
                    hwnd = find_main_hwnd()
                    if hwnd:
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                except: pass
            # Resolve icon: use contact avatar URL if available, else app icon
            icon_path = get_resource_path('icon.png')
            if avatar_url_ and avatar_url_.startswith('http'):
                try:
                    import tempfile, os as _os
                    ext = '.jpg'
                    if 'png' in avatar_url_: ext = '.png'
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext,
                                                      dir=_APP_DATA_DIR)
                    with urllib.request.urlopen(avatar_url_, timeout=3) as r:
                        tmp.write(r.read())
                    tmp.close()
                    icon_path = tmp.name
                except: pass
            toasted = False
            try:
                win11_toast(t, b, icon=icon_path, on_click=on_click)
                toasted = True
            except: pass
            if not toasted:
                # Fallback: pystray tray balloon (always works)
                try:
                    if tray_icon:
                        tray_icon.notify(b, t)
                except: pass
        threading.Thread(target=_toast, daemon=True).start()
        if settings.get('taskbar_flash'):
            flash_taskbar()

    def mark_as_read(self):
        global _unread_count
        _unread_count = 0
        update_tray_icon_image()
        stop_flash_taskbar()

    def open_about(self):
        about_path = get_resource_path('about.html')
        about_url  = 'file:///' + about_path.replace('\\', '/')
        rect = get_window_rect()
        aw, ah = 400, 480
        kw = dict(width=aw, height=ah, resizable=False, on_top=True)
        if rect:
            mx, my, mw, mh = rect
            kw['x'] = mx + (mw - aw) // 2
            kw['y'] = my + (mh - ah) // 2
        about_win = webview.create_window(
            'About \u2013 Google Messages', about_url, **kw)

        def _poll_and_restore_menu():
            """WinForms controls can only have one parent. When pywebview creates
            the About window, it accidentally moves the global MenuStrip into it!
            We catch this and move it back to the main window."""
            main = _main_form
            for _ in range(40):      # 40 × 100 ms = 4 seconds max
                time.sleep(0.1)
                try:
                    from System.Windows.Forms import Application
                    for form in Application.OpenForms:
                        if form is not main:
                            strips = [c for c in form.Controls
                                      if type(c).__name__ == 'MenuStrip']
                            if strips:
                                def _move_back():
                                    try:
                                        strip = strips[0]
                                        form.Controls.Remove(strip)
                                        form.MainMenuStrip = None
                                        if main and not main.Controls.Contains(strip):
                                            main.Controls.Add(strip)
                                            main.MainMenuStrip = strip
                                        strip.Visible = _menu_visible
                                    except: pass
                                _winform_invoke(main, _move_back)
                                return   # done
                except: pass
        threading.Thread(target=_poll_and_restore_menu, daemon=True).start()

    def open_github(self):
        webbrowser.open('https://github.com/PatrickHusband/google-messages')

    def check_updates_now(self):
        threading.Thread(target=check_for_updates, daemon=True).start()

api = Api()

# ─── Menu ────────────────────────────────────────────────────────────────────
def build_menu():
    """Menu items. Checkmarks are applied via ToolStripMenuItem.Checked
    after the menu is attached — pywebview 6.1 doesn't support checked= natively."""
    return [
        Menu('View', [
            MenuAction('Reload Page',
                       lambda: window.load_url('https://messages.google.com/web/')),
            MenuSeparator(),
            MenuAction('Zoom In',
                       lambda: window.run_js(
                           'document.body.style.zoom=(Math.round((parseFloat('
                           'document.body.style.zoom||1)+0.1)*10)/10).toString()')),
            MenuAction('Zoom Out',
                       lambda: window.run_js(
                           'document.body.style.zoom=(Math.max(0.3,Math.round(('
                           'parseFloat(document.body.style.zoom||1)-0.1)*10)/10)).toString()')),
            MenuAction('Actual Size',
                       lambda: window.run_js('document.body.style.zoom="1"')),
            MenuSeparator(),
            MenuAction('Toggle Full Screen', lambda: window.toggle_fullscreen()),
            MenuSeparator(),
            MenuAction('Hide Menu Bar  (Restore via Tray Icon)', hide_menu_bar),
        ]),
        Menu('Tray', [
            MenuAction('Enable System Tray Icon',
                       lambda: toggle_setting('tray_enabled', True)),
            MenuSeparator(),
            MenuAction('Start in Tray',
                       lambda: toggle_setting('start_in_tray', False)),
            MenuAction('Minimize to Tray',
                       lambda: toggle_setting('minimize_to_tray', True)),
            MenuAction('Close to Tray',
                       lambda: toggle_setting('close_to_tray', True)),
            MenuSeparator(),
            MenuAction('Monochrome Icon',
                       lambda: toggle_setting('monochrome_icon', False)),
            MenuAction('Red Dot for Unread',
                       lambda: toggle_setting('tray_icon_red_dot', True)),
        ]),
        Menu('Notifications', [
            MenuAction('Hide Notification Content',
                       lambda: toggle_setting('hide_notification_content', False)),
            MenuAction('Flash Taskbar on Message',
                       lambda: toggle_setting('taskbar_flash', True)),
        ]),
        Menu('App', [
            MenuAction('About',                api.open_about),
            MenuSeparator(),
            MenuAction('Check for Updates on Launch',
                       lambda: toggle_setting('check_for_updates', True)),
            MenuAction('Check for Updates Now', api.check_updates_now),
            MenuSeparator(),
            MenuAction('Quit', safe_quit),
        ]),
    ]

# ─── Injected JS ─────────────────────────────────────────────────────────────
INJECTED_JS = r"""
(function() {
    'use strict';
    if (window._amd_injected) return;
    window._amd_injected = true;

    // Attempt to intercept window.Notification (belt-and-suspenders;
    // Google Messages uses a Service Worker so this may not fire)
    var _Orig = window.Notification;
    function FakeNotification(title, opts) {
        if (window.pywebview && window.pywebview.api) {
            window.pywebview.api.trigger_notification_with_content(
                title, (opts && opts.body) ? opts.body : '', '');
        }
        return { close: function() {} };
    }
    FakeNotification.permission        = 'granted';
    FakeNotification.requestPermission = function() { return Promise.resolve('granted'); };
    FakeNotification.prototype         = _Orig ? _Orig.prototype : {};
    window.Notification = FakeNotification;

    // NOTE: We do NOT mark_as_read on window focus — the tray dot should only
    // clear when the unread count in the title actually drops to 0.

    // Scrape the top conversation in the sidebar for rich notification content.
    // aria-label on list items is the most stable: "Name, snippet, time ago"
    function _scrapeLatest() {
        try {
            var SELECTORS = [
                'mws-conversation-list-item',
                'a[href*="/web/conversations/"]',
                '[data-e2e-conversation-id]'
            ];
            var items = null;
            for (var s = 0; s < SELECTORS.length; s++) {
                items = document.querySelectorAll(SELECTORS[s]);
                if (items.length) break;
            }
            if (!items || !items.length) return {};
            var el = items[0];

            // aria-label: "Name, snippet, time" — most stable source
            var aria = el.getAttribute('aria-label') || '';
            if (aria) {
                var parts = aria.split(',').map(function(p){ return p.trim(); });
                var name    = parts[0] || '';
                // Middle parts are the snippet; last part is usually a timestamp
                var snippet = parts.slice(1, parts.length > 2 ? -1 : undefined).join(', ');
                var img  = el.querySelector('img[src*="googleusercontent"], img[src*="google"], img[src*="lh3"]');
                return { name: name, body: snippet, avatar: img ? img.src : '' };
            }

            // Fallback: text node hunting
            var nameEl = el.querySelector('[class*="name"], [class*="Name"], h2, h3, strong');
            var bodyEl = el.querySelector('[class*="snippet"], [class*="preview"], [class*="body"], p');
            var img2   = el.querySelector('img[src]');
            return {
                name:   nameEl ? nameEl.textContent.trim().split('\n')[0] : '',
                body:   bodyEl ? bodyEl.textContent.trim().split('\n')[0] : '',
                avatar: img2   ? img2.src : ''
            };
        } catch(e) { return {}; }
    }

    // Primary notification trigger: watch title for (N) unread badge.
    var _lastCount = 0;
    setInterval(function() {
        if (!window.pywebview || !window.pywebview.api) return;
        var m = document.title.match(/\((\d+)\)/);
        var count = m ? parseInt(m[1], 10) : 0;
        if (count > _lastCount) {
            var diff = count - _lastCount;
            var info = _scrapeLatest();
            var name   = info.name   || 'Google Messages';
            var body   = info.body   || (diff === 1 ? 'New message' : diff + ' new messages');
            var avatar = info.avatar || '';
            window.pywebview.api.trigger_notification_with_content(name, body, avatar);
        }
        if (count === 0 && _lastCount > 0) window.pywebview.api.mark_as_read();
        _lastCount = count;
    }, 1500);
})();
"""

# ─── Quit & Tray ──────────────────────────────────────────────────────────────
def safe_quit():
    global is_quitting, tray_icon
    is_quitting = True
    _save_window_geometry()
    if tray_icon:
        try: tray_icon.stop()
        except: pass
    try: window.destroy()
    except: pass
    os._exit(0)

def update_tray_state():
    global tray_icon
    if settings.get('tray_enabled'):
        if not tray_icon:
            threading.Thread(target=setup_tray, daemon=True).start()
    else:
        if tray_icon:
            try: tray_icon.stop()
            except: pass
            tray_icon = None

def setup_tray():
    global tray_icon
    try:
        image = make_icon_image(monochrome=settings.get('monochrome_icon', False))
        def toggle_window():
            global window_is_hidden
            try:
                if window_is_hidden: window.show(); window_is_hidden = False
                else: window.hide(); window_is_hidden = True
            except: pass
        def toggle_menu_bar():
            if _menu_visible:
                hide_menu_bar()
            else:
                show_menu_bar()
                
        tray_menu = pystray.Menu(
            pystray.MenuItem('Show / Hide',       toggle_window,    default=True),
            pystray.MenuItem('Toggle Menu Bar',   toggle_menu_bar),
            pystray.MenuItem('About',             api.open_about),
            pystray.MenuItem('Check for Updates', api.check_updates_now),
            pystray.MenuItem('Quit',              safe_quit),
        )
        tray_icon = pystray.Icon('Google Messages', image, 'Google Messages', tray_menu)
        tray_icon.run()
    except: pass

# ─── Main ─────────────────────────────────────────────────────────────────────
def create_app():
    global window
    w = int(settings.get('saved_window_width',  1100))
    h = int(settings.get('saved_window_height', 800))
    raw_x, raw_y = settings.get('saved_window_x'), settings.get('saved_window_y')
    x = int(raw_x) if isinstance(raw_x, (int, float)) else None
    y = int(raw_y) if isinstance(raw_y, (int, float)) else None
    kw = dict(width=w, height=h, min_size=(600, 400), js_api=api)
    if x is not None and y is not None:
        kw['x'], kw['y'] = x, y

    window = webview.create_window('Google Messages',
                                   'https://messages.google.com/web/', **kw)
    window.events.closing   += on_closing
    window.events.minimized += on_minimized

    def _inject_js():
        """Re-inject our JS overrides. Safe to call on every page load
        because the script guards itself with window._amd_injected."""
        try:
            window.run_js(INJECTED_JS)
        except: pass

    # Re-inject on every page navigation (e.g. after Google sign-in redirect)
    window.events.loaded += _inject_js

    def on_loaded(win):
        _inject_js()

        def _init():
            # Cache the main form BEFORE the page title might change it
            _cache_main_form()
            time.sleep(0.6)   # let MenuStrip fully attach
            if _main_form:
                _menu_apply_checkmarks(_main_form)
                if not settings.get('menu_visible', True):
                    _menu_set_visible(_main_form, False)

        threading.Thread(target=_init, daemon=True).start()

        if settings.get('start_in_tray'):
            global window_is_hidden
            win.hide(); window_is_hidden = True
        if settings.get('check_for_updates', True):
            threading.Thread(target=check_for_updates, daemon=True).start()

    threading.Thread(target=_install_keyboard_hook, daemon=True).start()
    update_tray_state()
    webview.start(on_loaded, window, private_mode=False,
                  menu=build_menu(), storage_path=_APP_DATA_DIR)

if __name__ == '__main__':
    if not ensure_single_instance():
        sys.exit(0)
    create_app()
