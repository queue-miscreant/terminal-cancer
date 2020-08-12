Terminal Cancer
===============

A name I thought up just now.
Pending changing it, but I don't see anyone besides me using this.

A Python package that implements curses input and ANSI escape-colored output.   
Written over the course of several years (and re-written once due to wanting async support).
This project was initially part of a chatango client script, but the display capabilities
have been segregated into this project.

Uses [python wcwidth](https://github.com/jquast/wcwidth), which should probably be upgraded to
"dependency", but the files are provided regardless.


Features:
--------------------------
* (Cyclical) Tab completion
* Live terminal resizing
* Colorized and filtered output
	* Color text matching a regex or filter messages based on conditions
* Potential mouse support
* 256 color mode
* Unicode input


Dependencies:
--------------------------
* Python 3
* Python ncurses (included on most distros, Python cygwin)

Optional: (see below for changing)
* Feh image viewer
* MPV
* youtube-dl
* xclip


Changing default openers:
--------------------------
If you want to use some other program like ImageMagick to open images,
you'll have to do the following after importing
```
from term_cancer import linkopen
linkopen.IMG_ARGS = ["animate", ...]
```
Where ... represents more command line arguments. Similarly can be done 
to replace mpv (using `MPV_ARGS`).


Windows (Cygwin):
-----------------
The Python installation under cygwin works mostly fine for input
and drawing within MinTTY, the default cygwin terminal emulator.
The following terminals are NOT supported or have restricted features:
* Console2
	* Partially; 256 color mode works incorrectly
* cmd.exe
	* Unsupported; though it has ANSI escapes, ncurses recognizes different keys
* Powershell
	* Unsupported; see cmd.exe

Testing limited:
* PuTTY

Links in browser may not open correctly by default. On cygwin, this defaults 
to using `cygstart`, which uses the Windows default for paths beginning with 
"http(s)://". On other platforms, the default is handled by the `webbrowser`
Python module.
If you wish to modify this, you can do one of two things:
* add your preferred browser's directory to the Windows PATH environment variable, or
* (cygwin) specify a BROWSER environment variable (as in `BROWSER=chrome chatango.py`)
The latter implies that there is a link to the executable in `/usr/bin` in cygwin.
This can be created with
`ln -s /cygdrive/c/Program\ Files/.../[browser executable].exe /usr/bin`

To preserve the value of BROWSER, add `export BROWSER=chrome` to your ~/.bashrc

There are few good image viewers in windows that support command line arguments,
and fewer if any that attempt to resolve paths with HTTP. Upon failing to open a
link, it will fall back to the browser, which will be the default for the rest
of runtime. If you'd prefer to do the same with videos, change 
`linkopen.MPV_ARGS` (as shown above) to `[]`.
