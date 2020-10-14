#!/usr/bin/env python3
# pylint: disable=invalid-name,too-few-public-methods,global-statement,protected-access

"""Remembers window positions for different display configurations.

Recommended usage is to start this on login from your desktop environment's
autostart."""

import logging
import struct
import argparse
import sys
import time
import signal
import select
from typing import Optional, Sequence, Dict, List

import Xlib.display
import Xlib.error

VERSION = '1.0'

# Default interval for how often to record window positions
DEFAULT_POLL_INTERVAL = 10  # seconds
# Time to let the window manager settle things after monitor changes
SETTLE_INTERVAL = 4  # seconds

DISPLAY: Optional[Xlib.display.Display] = None
BASE_LOG_LEVEL = logging.WARNING
DEBUG_SIG = False
VERY_VERBOSE = False


class CachedAtom:
    """Represents a cached interned atom."""

    def __init__(self, name: str, prop_type: Optional[int] = None) -> None:
        self.name = name

        # Expected return type (for property query atoms)
        if prop_type is None:
            self.prop_type = Xlib.X.AnyPropertyType
        else:
            self.prop_type = prop_type

        self._value = -1

    @property
    def value(self):
        """Return the interned value of this atom."""

        if self._value == -1:
            if DISPLAY is None:
                raise RuntimeError('Atom %r used before display connected' % (self.name,))
            self._value = DISPLAY.intern_atom(self.name)

        return self._value


# https://specifications.freedesktop.org/wm-spec/latest/ar01s03.html#idm45766085291712
ATOM_NET_SUPPORTED = CachedAtom('_NET_SUPPORTED', Xlib.Xatom.ATOM)
# https://specifications.freedesktop.org/wm-spec/latest/ar01s03.html#idm45766085290080
ATOM_NET_CLIENT_LIST = CachedAtom('_NET_CLIENT_LIST', Xlib.Xatom.WINDOW)
# https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html#idm45766085202544
ATOM_NET_WM_DESKTOP = CachedAtom('_NET_WM_DESKTOP', Xlib.Xatom.CARDINAL)
ALL_DESKTOPS = 0xFFFFFFFF
# https://specifications.freedesktop.org/wm-spec/latest/ar01s05.html#idm45766085184336
ATOM_NET_WM_STATE = CachedAtom('_NET_WM_STATE', Xlib.Xatom.ATOM)
ATOM_NET_WM_STATE_STICKY = CachedAtom('_NET_WM_STATE_STICKY')
ATOM_NET_WM_STATE_FULLSCREEN = CachedAtom('_NET_WM_STATE_FULLSCREEN')
# https://specifications.freedesktop.org/wm-spec/latest/ar01s04.html#idm45766085232784
ATOM_NET_MOVERESIZE_WINDOW = CachedAtom('_NET_MOVERESIZE_WINDOW')
ATOM_WM_NAME = CachedAtom('WM_NAME')
ATOM_WM_CLASS = CachedAtom('WM_CLASS')
MOVERESIZE_STRUCT = struct.Struct('IIIII') # (gravity | flags), x, y, w, h
ATOM_UTF8_STRING = CachedAtom('UTF8_STRING')


def _getprop_from_window(window: Xlib.display.drawable.Window,
                         atom: CachedAtom, max_len=1, decode_string=True):
    prop = window.get_property(atom.value, atom.prop_type, 0, max_len)
    if not prop:
        return None

    if not prop.value:
        return None

    if prop.property_type in (Xlib.Xatom.STRING, ATOM_UTF8_STRING.value) and \
       isinstance(prop.value, bytes) and decode_string:
        value = prop.value.decode('utf-8', 'ignore')
    else:
        value = prop.value

    return value


class DisplayConfig:
    """Represents the current X server display configuration."""

    def __init__(self, dply: Xlib.display.Display,
                 root: Optional[Xlib.display.drawable.Window] = None) -> None:
        if root is None:
            root = dply.screen().root

        active = []

        log = logging.getLogger('DisplayConfig')

        resources = root.xrandr_get_screen_resources()._data
        config_ts = resources['config_timestamp']
        for output_id in resources['outputs']:
            disp = self._parse_output(dply, output_id, config_ts)
            if disp is None:
                continue

            active.append(disp)

        self.displays = tuple(sorted(active))
        log.debug('all displays: %s', self)

    @staticmethod
    def _parse_output(dply: Xlib.display.Display,
                      output_id: int, config_ts: int) -> Optional[tuple]:
        output = dply.xrandr_get_output_info(output_id, config_ts)._data
        is_connected = output['connection'] == Xlib.ext.randr.Connected
        if not is_connected:
            return None

        crtc_id = output['crtc']
        if crtc_id == 0:
            return None

        name = output['name']
        crtc = dply.xrandr_get_crtc_info(crtc_id, config_ts)._data
        x = crtc['x']
        y = crtc['y']
        width = crtc['width']
        height = crtc['height']

        return name, x, y, width, height

    def __str__(self) -> str:
        dply_str = []
        for name, x, y, width, height in self.displays:
            dply_str.append(f'{name}:{width}x{height}+{x}+{y}')

        return ','.join(dply_str)

    def __repr__(self) -> str:
        return f'<DisplayConfig@{id(self)}: displays={self.__str__()}>'

    def __eq__(self, other):
        if isinstance(other, tuple):
            return self.displays == other

        if isinstance(other, DisplayConfig):
            return self.displays == other.displays

        return NotImplemented

    def __hash__(self):
        return hash(self.displays)


# pylint: disable=too-many-instance-attributes
class Window:
    """Represents a single client window."""

    def __init__(self, dply: Xlib.display.Display, window_id: int,
                 root: Optional[Xlib.display.drawable.Window] = None) -> None:
        if root is None:
            root = dply.screen().root

        self.dply = dply
        self.root = root

        self.log = logging.getLogger('Window.' + str(window_id))

        window = dply.create_resource_object('window', window_id)
        geom = window.get_geometry()._data
        width = geom['width']
        height = geom['height']

        coords = root.translate_coords(window, 0, 0)._data
        x = coords['x']
        y = coords['y']

        self.window_id = window_id
        self.window = window

        # Get desktop number
        desktop_prop = self._getprop(ATOM_NET_WM_DESKTOP)
        self.desktop_id: Optional[int] = None
        if desktop_prop is not None:
            self.desktop_id = desktop_prop[0]

        # Get window state
        self.state: Optional[int] = None
        state_prop = self._getprop(ATOM_NET_WM_STATE)
        if state_prop is not None:
            self.state = state_prop[0]

        self.wm_name = self._getprop(ATOM_WM_NAME, max_len=32)
        self.wm_class = self._get_wm_class()

        self.position = (x, y, width, height)
        #self.log.debug('found %r', self)

    @classmethod
    def get_windows(cls, dply: Xlib.display.Display,
                    root: Optional[Xlib.display.drawable.Window] = None) -> Sequence['Window']:
        """Return a list of all client windows currently present."""

        if root is None:
            root = dply.screen().root

        log = logging.getLogger('Window.get_windows')
        client_list = _getprop_from_window(root, ATOM_NET_CLIENT_LIST,
                                           max_len=255)
        if client_list is None:
            raise ValueError('display does not support _NET_CLIENT_LIST')

        result: List[Window] = []
        for window_id in client_list:
            try:
                window = cls(dply, window_id, root=root)
                result.append(window)
            except Xlib.error.BadDrawable as exc:
                log.warning('client window 0x%x was listed by window manager but not present: %s',
                            window_id, exc)

        log.debug('found %d client windows (%d entries in list)',
                  len(result), len(client_list))

        return result

    def _getprop(self, atom: CachedAtom, max_len=1, decode_string=True):
        return _getprop_from_window(self.window, atom,
                                    max_len=max_len,
                                    decode_string=decode_string)

    def _get_wm_class(self) -> Optional[str]:
        raw_cls = self._getprop(ATOM_WM_CLASS, max_len=64, decode_string=False)
        cls: Optional[str] = None
        if raw_cls:
            # WM_CLASS has a special null-separate format,
            # e.g. "Navigator\x00Firefox\x00"
            cls_comps = raw_cls.split(b'\x00')
            if len(cls_comps) > 1:
                cls = cls_comps[1].decode('utf-8', 'ignore')
            else:
                cls = cls_comps[0].decode('utf-8', 'ignore')

        return cls

    @property
    def x(self) -> int:
        """x coordinate of this window."""

        return self.position[0]

    @property
    def y(self) -> int:
        """y coordinate of this window."""

        return self.position[1]

    @property
    def width(self) -> int:
        """Width of this window."""

        return self.position[2]

    @property
    def height(self) -> int:
        """Height of this window."""

        return self.position[3]

    @property
    def safe_x(self) -> int:
        """x coordinate of this window."""

        return max(self.position[0], 0)

    @property
    def safe_y(self) -> int:
        """y coordinate of this window."""

        return max(self.position[1], 0)

    def __str__(self) -> str:
        return f'{self.width}x{self.height}+{self.x}+{self.y}'

    def __repr__(self) -> str:
        return f'<Window@{id(self):x}: id=0x{self.window_id:x} name={self.wm_name!r} ' \
            f'class={self.wm_class!r} position={self.__str__()}>'

    def __eq__(self, other):
        if isinstance(other, int):
            return self.window_id == other

        if isinstance(other, Window):
            return self.window_id == other.window_id

        return NotImplemented

    def __hash__(self):
        return hash(self.window_id)

    def should_reposition(self) -> bool:
        """True if repositioning this window is advisable, i.e. it is not a panel,
        fullscreen window or other unusual thing."""

        if self.desktop_id == ALL_DESKTOPS:
            # Window shown on all desktops, probably a panel
            return False

        if self.state in (ATOM_NET_WM_STATE_STICKY.value, ATOM_NET_WM_STATE_FULLSCREEN.value):
            # Should keep hands off this
            return False

        return True

    def reposition(self) -> None:
        """Reset this window to its last recorded position. Does not enforce should_reposition;
        caller should check value before invoking this. Note: if an event loop is not running,
        the display.flush() method must be called after repositioning."""

        # See https://specifications.freedesktop.org/wm-spec/latest/ar01s04.html#idm45766085232784
        # StaticGravity | x,y,w,h present | "pager" request
        flags = 10 | 0xf << 8 | 0x2 << 12

        msg_arg = MOVERESIZE_STRUCT.pack(flags,
                                         self.safe_x, self.safe_y,
                                         self.width, self.height)

        event = Xlib.protocol.event.ClientMessage(
            window=self.window,
            client_type=ATOM_NET_MOVERESIZE_WINDOW.value,
            data=(32, msg_arg))
        self.log.debug('sending _NET_MOVERESIZE_WINDOW: %r, window: %r', event, self)

        self.root.send_event(event,
                             event_mask=
                             Xlib.X.SubstructureRedirectMask | Xlib.X.SubstructureNotifyMask)


class StateStore:
    """Stores window states for all seen configurations."""

    def __init__(self, dply: Xlib.display.Display):
        self.dply = dply
        self.root = dply.screen().root

        self.log = logging.getLogger('StateStore')

        self._current_displays: Optional[DisplayConfig] = None
        self._stored_configs: Dict[DisplayConfig, Sequence[Window]] = {}

    def _update_windows(self, dply_state: DisplayConfig) -> None:
        assert isinstance(dply_state, DisplayConfig)

        old_config = self._stored_configs.get(dply_state)
        new_config = Window.get_windows(self.dply, root=self.root)

        for old_wnd in (old_config or []):
            try:
                new_wnd = new_config[new_config.index(old_wnd)]
            except ValueError:
                continue

            if old_wnd.position != new_wnd.position:
                self.log.debug('window %r (%s) moved: %s -> %s',
                               old_wnd.wm_name, old_wnd.wm_class, old_wnd, new_wnd)

        self._stored_configs[dply_state] = new_config

    # pylint: disable=too-many-return-statements
    def check_wm_support(self) -> bool:
        """Check that the server and window manager support the necessary properties to run this
        program. Should be called once at startup."""

        if Xlib.__version__ < (0, 24):
            # 0.23 has a fatal event parsing bug on Python 3
            self.log.fatal('python-xlib version 0.24 or newer is required')
            return False

        if not self.dply.has_extension('RANDR'):
            self.log.fatal('server does not have the RandR extension')
            return False

        randr_resp = self.dply.xrandr_query_version()
        randr_version = (randr_resp.major_version, randr_resp.minor_version)
        self.log.debug('randr verion %s', randr_version)
        if randr_version < (1, 2):
            self.log.fatal('server must support at least RandR 1.2')
            return False

        props_resp = _getprop_from_window(self.root, ATOM_NET_SUPPORTED,
                                          max_len=255)
        if props_resp is None:
            self.log.fatal('window manager does not support _NET_SUPPORTED')
            return False

        props = frozenset(props_resp)
        if ATOM_NET_CLIENT_LIST.value not in props:
            self.log.fatal('window manager does not support _NET_CLIENT_LIST')
            return False

        if ATOM_NET_MOVERESIZE_WINDOW.value not in props:
            self.log.fatal('window manager does not support _NET_MOVERESIZE_WINDOW')
            return False

        # Other properties are optional

        return True

    def poll(self, displays_changed) -> bool:
        """Updates stored window configurations or updates the display from stored configuration
        if the screen configuration has changed. Screen configuration is only checked if
        displays_changed` is True because the check can be slow. Returns True if screen
        configuration had changed."""

        self.log.debug('polling display state, displays_changed=%s', displays_changed)
        if displays_changed or self._current_displays is None:
            curr_displays = DisplayConfig(self.dply, self.root)
        else:
            curr_displays = None

        if curr_displays is None or curr_displays == self._current_displays:
            if VERY_VERBOSE:
                self.log.debug('display state unchanged: %s', curr_displays)
            self._update_windows(curr_displays or self._current_displays)
            return False

        # Display state has changed. Set new config as current and check
        # if we have a stored window configuration.
        first_run = self._current_displays is None
        self._current_displays = curr_displays

        try:
            new_config = self._stored_configs[curr_displays]
        except KeyError:
            if not first_run:
                self.log.info('display state changed: %s (no stored window configuration)',
                              curr_displays)
            self._update_windows(curr_displays)
            return True

        # Found stored configuration. Restore it.
        for window in new_config:
            if not window.should_reposition():
                continue

            try:
                window.reposition()
            except Xlib.error.BadDrawable as exc:
                self.log.warning('window %r was no longer present: %s', window, exc)
            except Exception: # pylint: disable=broad-except
                self.log.exception('internal error repositioning window %r', window)
        self.dply.flush()

        self.log.info('display state changed: %s (repositioned %d window(s))',
                      curr_displays, len(new_config))

        return True


class EventWaiter:
    """X server event listener."""

    STATE_NO_CHANGE = 0
    STATE_DISP_CHANGED = 1
    STATE_DESTROYED = 2

    def __init__(self, dply: Xlib.display.Display) -> None:
        self.dply = dply

        self.log = logging.getLogger('EventThread')

        self._state = self.STATE_NO_CHANGE
        self._select_done = False

        self._select_events()

    def wait(self, timeout=None) -> int:
        """Wait for a timeout or state change to occur."""

        rem_timeout = timeout
        start_time = time.monotonic()

        while self._state == self.STATE_NO_CHANGE:
            elapsed = time.monotonic() - start_time
            rem_timeout -= elapsed
            if rem_timeout <= 0:
                break

            self.poll(rem_timeout)

        # An event occurred or timeout expired. Reset state to default for next
        # wait, unless destroyed in which case caller should exit.
        return self.flush()

    def poll(self, timeout=0) -> 'EventWaiter':
        """Get events pending on the display once."""

        if VERY_VERBOSE:
            self.log.debug('selecting for %.2f sec', timeout)
        rlist, _, xlist = select.select([self.dply.fileno()], [], [self.dply.fileno()], timeout)
        if VERY_VERBOSE:
            self.log.debug('select returns rlist=%s xlist=%s', rlist, xlist)

        if rlist or xlist:
            self._run()

        return self

    def flush(self) -> None:
        """Flush pending change state."""

        prev_state = self._state
        if self._state != self.STATE_DESTROYED:
            self._state = self.STATE_NO_CHANGE

        return prev_state

    def _select_events(self) -> bool:
        if self._select_done:
            return True

        # pylint: disable=broad-except
        try:
            root = self.dply.screen().root
            root.xrandr_select_input(Xlib.ext.randr.RRCrtcChangeNotifyMask |
                                     Xlib.ext.randr.RROutputChangeNotifyMask)
        except Exception:
            self.log.exception('xrandr_select_input failed')
            self._state = self.STATE_DESTROYED
            return False

        self.log.debug('RandR event mask set')
        self._select_done = True
        return True

    def _run(self):
        """Called internally by wait()."""

        while self._state != self.STATE_DESTROYED and self.dply.pending_events():
            event = self.dply.next_event()

            if event.type == Xlib.X.DestroyNotify:
                self.log.debug('DestroyNotify received')
                self._update_state(self.STATE_DESTROYED)
            elif event.type == self.dply.extension_event.CrtcChangeNotify[0]:
                e_code = (event.type, event.sub_code)
                if e_code == self.dply.extension_event.CrtcChangeNotify:
                    self.log.debug('CRTC change event')
                    self._update_state(self.STATE_DISP_CHANGED)
                elif e_code == self.dply.extension_event.OutputChangeNotify:
                    self.log.debug('Output change event')
                    self._update_state(self.STATE_DISP_CHANGED)
                else:
                    self.log.warning('unexpected CrtcChangeNotify %s', e_code)

    def _update_state(self, new_state) -> bool:
        if self._state == new_state or self._state == self.STATE_DESTROYED:
            return False

        self._state = new_state

        return True


# USR1 signal handler: toggle debug logging
def _usr_handler(_fr, _sig):
    global DEBUG_SIG

    log_root = logging.root
    if DEBUG_SIG:
        log_root.setLevel(BASE_LOG_LEVEL)
        DEBUG_SIG = False

        log_root.log(logging.INFO, "debug logging disabled")
    else:
        log_root.setLevel(logging.DEBUG)
        DEBUG_SIG = True

        log_root.log(logging.INFO, "debug logging enabled")


def main(argv):
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description='Remember window positions on different '
                                     f'display configurations')

    parser.add_argument('-d', '--display', action='store', metavar='HOST:DPY', default=None,
                        help='The X server to contact')
    parser.add_argument('-i', '--interval', action='store', type=int, metavar='SECONDS',
                        default=DEFAULT_POLL_INTERVAL,
                        help='Interval for polling window/screen changes '
                        '(default %(default)s seconds)')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Verbose logging (repeat for debug logging')
    parser.add_argument('-V', '--version', action='store_true',
                        help='Print version and exit')

    args = parser.parse_args(argv)

    if args.version:
        print(VERSION)
        return 0

    global DISPLAY, BASE_LOG_LEVEL, DEBUG_SIG, VERY_VERBOSE

    if args.verbose > 1:
        log_level = logging.DEBUG
        BASE_LOG_LEVEL = logging.INFO  # allow disabling debug
        DEBUG_SIG = True
        if args.verbose > 2:
            VERY_VERBOSE = True
    elif args.verbose > 0:
        BASE_LOG_LEVEL = log_level = logging.INFO
    else:
        BASE_LOG_LEVEL = log_level = logging.WARNING

    logging.basicConfig(level=log_level, format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')
    log = logging.getLogger('main')

    DISPLAY = Xlib.display.Display(display=args.display)

    interval = args.interval
    if interval < 1:
        log.fatal('poll interval must be 1 second or more')
        return 1

    store = StateStore(DISPLAY)
    if not store.check_wm_support():
        log.fatal('your window manager lacks required features to run this program')
        return 2

    signal.signal(signal.SIGUSR1, _usr_handler)

    ev_thread = EventWaiter(DISPLAY)

    state = EventWaiter.STATE_NO_CHANGE
    changes_pending = True

    while state != EventWaiter.STATE_DESTROYED:
        store.poll(changes_pending)
        changes_pending = False

        state = ev_thread.wait(interval)
        if state == EventWaiter.STATE_DISP_CHANGED:
            log.debug('display changes pending')
            changes_pending = True
            # Let things settle down before acting. We don't want to race with
            # the WM which may move around windows after events.
            time.sleep(SETTLE_INTERVAL)
            # We are already committed to a full update, flush events that may
            # have arrived during the settle wait so we don't trigger
            # RandR polling twice.
            ev_thread.poll().flush()

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
