DECORATORS
----------
###	client.colorer
Adds a colorer to be applied to the client.  
Decoratee arguments:  
```
	msg:		The message as a coloring object. See coloring under objects.
	*args:		The rest of the arguments. Currently:
			0:		reply (boolean)
			1:		history (boolean)
			2:		channel number
```

###	client.chatfilter
Function run on attempt to push message. If any filter returns true, the message is not displayed  
Decoratee arguments:
```
	*args:	Same arguments as in client.colorer
```

###	client.onkey(valid_keyname)
Causes a function to be run on keypress.  
Arguments:
```
	valid_keyname:	Self-explanatory. Must be the name of a valid key in curses._VALID_KEYNAMES
```
Decoratee arguments:
```
	self:	the current client object
```

###	client.command(command_name)
Declare command. Access commands with /  
Arguments:
```
	command_name:	The name of the command. Type /command_name to run
```
Decoratee arguments:
```
	self:		The current client object
	arglist:	Space-delimited values following the command name
```

###	client.opener(type,pattern_or_extension)
Function run on attempt to open link.  
Arguments:
```
	type:			0,1, or 2. 0 is the default opener, 1 is for extensions, and 2 is for URL patterns
	pattern_or_extension:	The pattern or extension. Optional for default opener
```
Decoratee arguments:
```
	self:	The client object. Passed so that blurbs can be printed from within functions
	link:	The link being opened
	ext:	The extension captured. Optional for default opener
```

###	*See how these are called in chatango.py, such as in F3()*

AUXILIARY CLASSES
-----------------
###	client.botclass():
A bot class. All bot instances (in start) are expected to descend from it
Members:
```
	parent:		The current instance of client.main
```
Methods:
```
	setparent(overlay):	Sets parent to overlay. Raises exception if overlay is not a client.main
```

OVERLAYS
--------
###	client.overlayBase()
Base class of overlays. For something to be added to the overlay stack, it must derive from this class. 
All subsequent overlays are descendents of it  
Members:
```
	_altkeys:	Dictionary of escaped keys, i.e. sequences that start with ESC (ASCII 27)
			Keys must be ints, values must be functions that take no arguments
			Special key None is for the Escape key
	_keys:		ASCII (and curses values) of keys. Keys must be ints,
			values must be functions that take a single list argument	
```
Methods:
```
	__call__(chars):	Attempt to redirect input based on the _keys dict
	_callalt(chars):	Alt key backend that redirects ASCII 27 to entries in altkeys
	display(lines):		Does nothing. This has the effect of not modifying output at all
	post():			A method that is run after every keypress if the _keys entry
				Evaluates to something false. e.g. 0, None. Does nothing by default
	addKeys(newkeys):	Where newkeys is a dictionary, accepts valid keynames (i.e., in
				client._VALID_KEYNAMES) and updates _keys accordingly
				Newkeys values are functions with exactly one argument: the overlay.
	addResize():		Run when an overlay is added. Maps curses.KEY_RESIZE to
				client.main.resize, ensuring that resizing always has the same effect
```

###	client.listOverlay(outputList,[drawOther,[modes = [""]]])
Displays a list (or string iterable) of objects. Selection controlled with arrow keys (or jk)  
Arguments:
```
	outputList:	The list to output. Simple.
	drawOther:	A function that takes two arguments: a client.coloring object of a string in
			outputList, and its position in the list
	modes:		List of 'modes.' The values are drawn in the lower left corner
```
Members:
```
	it:		The "iterator." An integer that points to an index in outList
	mode:		Similar to it, but for iterating over modes. This is decided at instantiation,
			so it is the programmer's duty to make a 'mode' functional.
	list:		The outputList specified during instantiation
	_modes:		Names of modes. Since these are just for output, they are a private member.
	_numentries:	Equivalent to len(list), but stored int he class
	_nummodes:	Equivalent to len(_modes), but stored in the class.
	_drawOther:	The drawOther specified during instantiation
```
Methods:
```
	increment(amt):	Increment it and mod by _numentries
	chmode(amt):	Increment mode and mod by _nummodes
	display(lines):	Display a box containing the list entries, with the selected one in reverse video.
```

###	client.colorOverlay([initColor = [127,127,127]])
Displays 3 bars correlating to a three byte hex color.
Arguments:
```
	initColor:	The color contained will be initialized to this
```
Members:
```
	color:		A list of integers from 0 to 255, containing the value of the color
	_rgb:		Which color, red, green, or blue, is selected
```
Methods:
```
	increment(amt):	Increment color[_rgb] by amt, within the range 0 to 255
	chmode(amt):	Increment _rgb and mod by 3. Alternatively stated, rotate between colors
	display(lines):	Display a box containing the list entries, with the selected one in reverse video.
```
		
###	client.inputOverlay(prompt,[password = False,end = False]):
Displays 3 rows, with input in the middle
Arguments:
```
	prompt:		A string to display next to input. Similar to the default python function input.
	password:	Whether to replace the characters in the string with *s, as in a password screen.
	end:		Whether to end the program on abrupt exit, such as KeyboardInterrupt or pressing ESC
```
Members:
```
	text:		A scrollable object containing input
	_done:		Whether the inputOverlay is finished running or not. waitForInput halts when true.
	_prompt:	The prompt to display. See above.
	_password:	Password display. See above.
	_end:		End on abrupt quit. See above.
```
Methods:
```
	_input(chars):
	_finish():	Finish input. Sets _done to True and closes the overlay.
	_stop():	Finish input, but clear and cloas the overlay.
	display(lines):	Display 3 rows in the middle of the screen in the format prompt: input
	waitForInput():	When an instance of inputOverlay is created in another thread, this allows
			input to be polled.
```

###	client.commandOverlay(parent)
Descendant of inputOverlay. However, instead displays client.CHAR_COMMAND followed by input
Arguments:
```
	parent:		The instance of client.main. Passed so that commands can call display methods.
```
Members:
```
	parent:		Instance of client.main. See above.
```
Methods:
```
	_run:			Run the command in text. If a command returns an overlay, the commandOverlay
				will replace itself with the new one.
	_backspacewrap():	Wraps backspace so that if text is empty, the overlay quits.
	display(lines):		Display command input on the last available.
```

###	client.escapeOverlay(scrollable)
Invisible overlay. Analogous to a 'mode' that allows input of escaped characters like newline.
Arguments:
```
	scrollable:	A scrollable instance to append to.
```

###	client.escapeOverlay(function)
Invisible overlay. Analogous to a 'mode' that allows confirmation before running a function
Arguments:
```
	function:	Function with no arguments. Run on press of 'y'.
```

###	client.mainOverlay(parent)
The main overlay. If it is ever removed, the program quits.
Arguments:
```
	parent:		The instance of client.main.
```
Members:
```
	addoninit:	Exists before __init__. A list of keys to add to the class during __init__.
			Handled by client.onkey wrapper.
	text:		A scrollable that contains input.
	parent:		The instance of client.main.
	_allMessages:	All messages appended by append
	_lines:		_allMessages, broken apart by breaklines.
	_selector:	Select message. Specifically, the number of unfiltered messages 'up'
	_filtered:	Number of messages filtered. Used to bound _selector.
```
Methods:
```
	_post():		See overlayBase.post. This post stops selecting and re-fires display
	_replaceback():		Opens an escapeOverlay instance.
	_input(chars):		Append chars as (decoded) bytes to text
	selectup():		Selects the next message.	
	selectdown():		Selects the previous message.
	linklist():		Opens a listOverlay of lastlinks, backwards.
	isselecting():		Returns _selector. Intened to be used to branch if selecting (i.e if self.isselecting():...)
	addOverlay(new):	Equivalent to self.parent.addOverlay
	getselect(num):		Gets the selected message. A frontend for _allMessages[_selector] that returns the right message
	redolines():		Redo enough lines to not be apparent.
	clearlines():		Clear _lines, _allMessages, _selector, and _filtered
	append(newline, args = None):	Append [newline,args,len(breaklines(newline))] to _allMessages. If filtered,
					nothing else happens. If not, breaklines gets appended to _lines.
	display(lines):		Don't make me explain this. If selecting, it does a dance. If not, it goes up
				len(lines) in _lines and displays that back, with a bar at the end
```
