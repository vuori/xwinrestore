# xwinrestore: Remember window positions for different display configurations

`xwinrestore` remembers and restore X11 window sizes and positions for
different display configurations. For example, when you disconnect an external
display from your laptop, `xwinrestore` restores your windows on the laptop
to the positions they had before you last attached the external display.

`xwinrestore` was inspired by the [RestoreWindows](https://github.com/gurrhack/RestoreWindows)
program for Microsoft Windows.

As a bonus feature, it also supports optional automatic screen resizing, which is useful
with certain combinations remote desktop viewers and desktop environments. For example,
[XFCE4 does not auto-resize the screen](https://gitlab.xfce.org/xfce/xfce4-settings/-/issues/142)
when a SPICE viewer (`virt-viewer`) window is resized. Resizing can be enabled
with the `-P` option.

## Usage

### Prerequisites

`xwinrestore` requires Python 3.7 or newer, and version 0.24 or newer of the
[python-xlib](https://github.com/python-xlib/python-xlib) package. You can
install the latter using your operating system's package management or by
running `pip install python-xlib` (some systems may use `pip3`).

Note to Ubuntu users: Ubuntu 20.04 LTS and earlier ship version 0.23 of
python-xlib, which is not compatible with `xwinrestore`. Either install with `pip` or
install the version packaged with a newer distribution.

Your window manager must support at least version 1.1 of the
[Extended Window Manager Hints](https://specifications.freedesktop.org/wm-spec/wm-spec-latest.html)
specification. `xwinrestore` has so far only been tested with `xfwm4`.

### Installation

Copy `xwinrestore.py` to a location of your choice, for example `/usr/local/bin`.

### Usage

Run `xwinrestore.py` in the background on login. You can start it from
`.xinitrc`, `.xsession` or similar file, or through your desktop
environment's autostart facility.

If you need automatic screen resizing, add the `-P` option. This is
currently supported only in single-display configurations and is
likely only useful for virtual (remote desktop) displays.

Run the program with `--help` to see command line options. If you
encounter problems, try running the program manually with `-vv` to see
debug logging.

## Bug reports and patches

Please use Github issues for bug reports. Patches may be sent as diffs or pull requests.
However, code should be kept in a single file to keep installation simple.

## License

```
    Copyright 2020 Valtteri Vuorikoski

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
```
