# xwinrestore: Remember window positions for different display configurations

`xwinrestore` remembers and restores X11 window sizes and positions for
different display configurations. For example, when you disconnect an external
display from your laptop, `xwinrestore` restores your windows on the laptop's
internal display to the positions they had before you last attached the
external display.

`xwinrestore` was inspired by the [RestoreWindows](https://github.com/gurrhack/RestoreWindows)
program for Microsoft Windows.

As a bonus feature, it also supports optional automatic screen resizing, which is useful
with certain combinations of remote desktop viewers and desktop environments. For example,
[XFCE4 does not auto-resize the screen](https://gitlab.xfce.org/xfce/xfce4-settings/-/issues/142)
when a SPICE viewer (`virt-viewer`) window is resized. Auto-resizing can be enabled
with the `-P` option.

**This project is suspended as of 2023, as I have switched to a tiling window manager.**

## Usage

### Prerequisites

`xwinrestore` requires Python 3.7 or newer, and version 0.24 or newer of the
[python-xlib](https://github.com/python-xlib/python-xlib) package. You can
install the latter using your operating system's package management or by
running `pip install python-xlib` (some systems may use `pip3`).

Note to Ubuntu users: Ubuntu 20.04 LTS and earlier ship with version 0.23 of
python-xlib, which is not compatible with `xwinrestore`. Either install a newer
version with `pip` or install [the version packaged for a newer
distribution](https://packages.ubuntu.com/groovy/python3-xlib).

Your window manager must support at least version 1.1 of the
[Extended Window Manager Hints](https://specifications.freedesktop.org/wm-spec/wm-spec-latest.html)
specification. `xwinrestore` has so far only been tested with `xfwm4`.
Your X server must also support the RandR extension version 1.2 or newer.

### Installation

Copy `xwinrestore.py` to a location of your choice, for example `/usr/local/bin`.

### Usage

Run `xwinrestore.py` in the background on login. You can start it from
`.xinitrc`, `.xsession` or similar file, or through your desktop
environment's autostart facility.

If you need automatic screen resizing, add the `-P` option. This is
currently supported only in single-display configurations and is
likely only useful for virtual (remote desktop) displays. The effect
should be an automated version of running the command (in the case of `virt-viewer`)
`xrandr --output Virtual-1 --auto` after window resize.

Run the program with `--help` to see command line options. If you
encounter problems, try running the program manually with `-vv` to enable
debug logging.

### Limitations

  * Window configurations are stored based on the windows' internal
    identifiers. In practice, if you quit and relaunch an application, its
    position cannot be restored. Window matching based on window titles
    and classes may be implemented in the future.

  * Desktop panning has not been tested. Attempting to use
    `xwinrestore` with panning enabled is likely to cause
    problems. Other exotic RandR configurations, such as multi-output
    CRTCs, may also cause problems.

  * Unlikely to work with (X)Wayland now or in the future.
  
  * Actions (position restore, screen resize) are delayed to avoid stepping
    on the actual window manager's toes. Current settings are rather
    conservative, but some waiting is probably unavoidable since we must manage
    windows without being the window manager.

## Bug reports and patches

Please use Github issues for bug reports. Patches may be sent as diffs or pull requests.
However, code should be kept in a single file to keep installation simple.

Bug reports should include logs. Kill any running instace of `xwinrestore`, run
`xwinrestore.py -vv` in a terminal and reproduce the problem to capture a debug log.

## Links

  * [wmctrl](https://github.com/Conservatory/wmctrl) source was used as a reference for
    the more arcane EWMH incantations.
    
  * [RandR extension documentation](https://www.x.org/releases/current/doc/randrproto/randrproto.txt)
    is useful for understanding the code. Only a small subset of the RandR conceptual model is
    supported by `xwinrestore`.

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
