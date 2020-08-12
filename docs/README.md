Project Documentation
=====================
This package is meant to make IRC-like terminal display easier.

The package itself is split up into multple modules:
1. wcwidth
	* This module implements the C function wcwidth. This will not be covered in this documentation, so please check [the original source code](https://github.com/jquast/wcwidth).
2. display.py
	* Very basic text- and color-rendering classes
3. util.py
	* Various extra functions, including the key callback framework
4. base.py
	* Base classes for overlays. Also contains the code for "starting" the display mode
5. input.py
	* Various more complex overlays for different input types. Also contains InputMux.
5. chat.py
	* Message display container classes and display overlay.
6. linkopen.py
	* Link opening with system file viewers based on various analyses of the link
