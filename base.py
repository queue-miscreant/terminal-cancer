#!/usr/bin/env python3
#client/base.py
'''
Base classes for overlays and curses screen abstractions
Screen implements a stack of overlays and sends byte-by-byte curses input to
the topmost one. Output is not done with curses display, but line-by-line
writes to the terminal buffer (`sys.stdout` is reassigned to a temporary file
to keep output clean)
'''
try:
	import curses
except ImportError:
	raise ImportError("Could not import curses; is this running on Windows cmd?")
import sys			#messing around with stdout descriptors
import asyncio		#self-explanatory
import traceback	#error handling without breaking stopping the client
from signal import SIGINT #redirect ctrl-c
from .display import CLEAR_FORMATTING, collen, ScrollSuggest \
	, Coloring, JustifiedColoring, DisplayException
from .util import KeyContainer, KeyException, key_handler, staticize \
	, quitlambda, Sigil, argsplit, argunsplit, History
__all__ = ["Command", "OverlayBase", "TextOverlay", "transform_paste", "Manager"]

_REDIRECTED_OUTPUT = "/tmp/client.log"
#DISPLAY CLASSES----------------------------------------------------------
class Command:
	CHAR_COMMAND = '/'
	#command containers
	commands = {}
	_command_complete = {}

	@classmethod
	def command(cls, name, complete=None):
		'''
		Decorator that adds command `name` with argument suggestion `complete`.
		`complete` is either a list reference that completes the final argument
		or a callable returning a list, called as `complete(argument_list)`
		'''
		complete = complete if complete is not None else []
		def wrapper(func):
			cls.commands[name] = func
			if complete:
				cls._command_complete[name] = complete
			return func
		return wrapper

	@classmethod
	def complete(cls, wordlist):
		command = wordlist[0]
		if not command or command[0] != cls.CHAR_COMMAND:
			return []
		#attempt to find a completer
		try:
			completer = cls._command_complete[command[1:].strip()]
		except KeyError:
			return []
		arglist, unclosed = argunsplit(wordlist[1:])

		#if `completer` is a list reference, it is the command's valid keywords
		if not callable(completer):
			return [str(i) for i in completer if str(i).startswith(arglist[-1])]
		suggestions = completer(arglist[-1])
		ret = []
		for suggest in suggestions:
			has_space = ' ' in suggest
			#pre-escape single quotes in file names before
			if has_space:
				char = unclosed or '\''
				suggest = suggest.replace(char, '\\' + char)
			#add the correct escape
			if unclosed:
				ret.append(suggest + unclosed)
			#quote the suggestion
			elif has_space:
				ret.append(f"'{suggest}'")
			else:
				ret.append(suggest)
		return len(wordlist[-1]) - len(arglist[-1]), ret

	@classmethod
	def run(cls, string, screen):
		'''Run command'''
		#parse arguments like a command line: quotes enclose single args
		args = argsplit(string)

		possible = [i for i in cls.commands if i.startswith(args[0])]
		if not possible:
			screen.blurb.push("command '{}' not found".format(args[0]))
		elif len(possible) > 1:
			screen.blurb.push("ambiguous command; could be "\
				"'{}'".format("', '".join(possible[:10])))
		else:
			screen.loop.create_task(cls._run(possible[0], screen, args[1:]))

	@classmethod
	async def _run(cls, name, screen, args):
		command = cls.commands[name]
		try:
			result = command(screen, *args)
			if asyncio.iscoroutine(result):
				result = await result
			if isinstance(result, OverlayBase):
				result.add()
		except Exception as exc: #pylint: disable=broad-except
			screen.blurb.push(f"{str(exc)} occurred in command '{name}'")
			traceback.print_exc()
Sigil(Command.CHAR_COMMAND
	, lambda _, wordnum: list(Command.commands) if wordnum == 0 else [])
Sigil(Command.complete)

@Command.command("help")
def list_commands(screen, *_):
	'''Display a list of the defined commands and their docstrings'''
	from .input import ListOverlay #pylint: disable=import-outside-toplevel
	command_list = ListOverlay(screen, list(Command.commands))

	@command_list.callback
	def _(result):
		screen.text.append(Command.CHAR_COMMAND + result)
		return -1

	return command_list

@Command.command("quit")
def close(parent, *_):
	parent.stop()

#OVERLAYS----------------------------------------------------------------------
class OverlayBase:
	'''
	Virtual class that redirects input to callbacks and modifies a list
	of (output) strings. All overlays must inherit from OverlayBase
	'''
	replace = False
	def __init__(self, parent):
		if not isinstance(parent, Screen):
			raise TypeError("OverlayBase parent must be an instance of Screen")
		self.parent = parent		#parent
		self.index = None			#index in the stack
		self._term = None			#terminate input; leave None to be equivalent to replace
		self._reverse = JustifiedColoring("")	#text to draw in reverse video
		self._ensure = 2			#number of columns reserved to the RHS in _reverse

		self.keys = KeyContainer()
		self.keys.screen_keys(parent)
		self.add_keys({'^w':	quitlambda})

		#bind remaining unbound keys across classes
		for class_ in reversed(self.__class__.mro()):
			for handler in class_.__dict__.values():
				if isinstance(handler, key_handler):
					handler.bind(self.keys, redefine=False)
		setattr(self, "key_handler", staticize(self.key_handler, _bind_immed=self))

	width = property(lambda self: self.parent.width)
	height = property(lambda self: self.parent.height)

	left = property(lambda self: str(self._reverse), doc="Left side display")
	@left.setter
	def left(self, new):
		self._reverse.setstr(new)
		self.parent.update_status()

	right = property(lambda self: self._reverse.indicator, doc="Right side display")
	@right.setter
	def right(self, new):
		color = None
		if isinstance(new, tuple):
			new, color = new #extract a color
		self._reverse.add_indicator(new, color)
		self.parent.update_status()

	terminate_input = property(lambda self: self.replace if self._term is None else self._term)
	@terminate_input.setter
	def terminate_input(self, new):
		self._term = new

	def __call__(self, lines):
		'''
		Virtual method called by Screen.display. It is supplied with a list
		of lines to be printed to the screen. Modify lines by item (i.e
		lines[value]) to display to the screen
		'''

	def run_key(self, overlay, chars, do_input):
		'''
		Run a key callback. This expects the following arguments: `overlay`,
		the topmost overlay attempting to run a callback, `chars`, a list of
		numbers terminated by -1, and `do_input`, whether to run keys[-1]
		If the return value has boolean True, Screen will
		redraw; if the return value is -1, the overlay will remove itself
		'''
		if overlay.keys(chars, overlay, do_input=do_input) == -1:
			overlay.remove()
		return 1

	def resize(self, newx, newy):
		'''Virtual function called on all overlays in stack on resize event'''

	#frontend methods----------------------------
	def add(self):
		'''Finalize setup and add overlay'''
		if self.index is None:	#idempotence
			self.parent.add_overlay(self)

	def remove(self):
		'''Finalize overlay and pop'''
		if self.index is not None:	#idempotence
			self.parent.pop_overlay(self)

	def swap(self, new):
		'''Pop overlay and add new one in succession.'''
		self.remove()
		new.add()

	def add_keys(self, new_functions, redefine=False):
		'''
		Add keys from preexisting functions. `new_functions` should be a dict
		with either functions or (function, return value) tuples as values
		If redefine is True, then will redefine pre-existing key handlers.
		Also prioritizes binding all class-level key handlers to instance
		'''
		for handler in self.__class__.__dict__.values():
			if isinstance(handler, key_handler):
				handler.bind(self.keys, redefine)

		for key_name, handler in new_functions.items():
			override = None
			if isinstance(handler, tuple):
				handler, override = handler
			elif isinstance(handler, key_handler):
				handler = handler.bound
			if redefine or key_name not in self.keys:
				self.keys.add_key(key_name, handler, key_name == -1, override)

	@classmethod
	def key_handler(cls, key_name, override=None, _bind_immed=None, **kwargs):
		'''
		Decorator for adding a key handler.
		See `client.key_handler` documentation for valid values of `key_name`
		'''
		def ret(func):
			handle = func
			if not isinstance(handle, key_handler): #extract stacked
				handle = key_handler(key_name, override, **kwargs)(func)
			#setattr to class
			if _bind_immed is None:
				name = handle.bound.__name__
				if hasattr(cls, name): #mangle name
					name += str(id(handle))
				setattr(cls, name, handle)
				return handle
			handle.bind(_bind_immed.keys)
			return func	#return the function to re-bind handlers
		return ret

	def _get_help_overlay(self):
		'''Get list of this overlay's keys'''
		from .input import ListOverlay, DisplayOverlay #pylint: disable=import-outside-toplevel
		keys_list = dir(self.keys)
		if hasattr(self, "_more_help"):
			keys_list.extend(self._more_help)
		key_overlay = ListOverlay(self.parent, keys_list)

		@key_overlay.callback
		def _(result): #pylint: disable=unused-variable
			help_display = DisplayOverlay(self.parent, result)
			help_display.key_handler("enter")(quitlambda)
			help_display.add()

		return key_overlay

	def open_help(self):
		'''Open help overlay'''
		self._get_help_overlay().add()

class FutureOverlay(OverlayBase):
	'''
	Overlay extension that can create recurring futures and set callbacks
	If a callback returns value other than boolean False, the overlay is removed
	Alternatively, the "result" property can be awaited multiple times, while
	the "exit" property will remove the overlay after the future is set
	'''
	def __init__(self, parent):
		super().__init__(parent)
		self._future = parent.loop.create_future()
		self._future.add_done_callback(self._new_callback)
		if not hasattr(self, "_callback"):
			self._callback = None

	@property
	def result(self):
		return self._future
	@property
	async def exit(self):
		'''Awaitable property that closes the overlay when done'''
		try: #await; make sure that the callback doesn't run while cancelled
			ret = await self._future
			self._future.remove_done_callback(self._new_callback)
		finally:
			self.remove()
		return ret

	def _new_callback(self, fut):
		'''When the future is done, we need to make a new future object'''
		if self._callback is not None:
			try:
				if self._callback(fut.result()):
					self.remove()
					return
			except asyncio.CancelledError:
				pass
		self._future = self.parent.loop.create_future()
		self._future.add_done_callback(self._new_callback)

	def callback(self, func, do_remove=False):
		'''
		Decorator for a function with a single argument: the future result
		Note that by default, async functions (i.e, generators) only run once
		'''
		if not callable(func):
			raise TypeError(f"Callback expected callable, got {type(func)}")
		if asyncio.iscoroutinefunction(func):
			async def new_future():
				result = await self.result
				remove = await func(result) or do_remove
				if remove:
					self.remove()
			self.parent.loop.create_task(new_future())
			return func
		self._callback = func
		return func

	def remove(self):
		if not self._future.done():
			self._future.cancel()
		super().remove()

	@key_handler("enter", doc="Set value and exit")
	@key_handler("tab", override=0, doc="Set, but keep overlay open")
	def set_result(self):
		try:
			self._future.set_result(self.selected)
		except: #pylint: disable=bare-except
			pass
		return -1

class TextOverlay(FutureOverlay):
	'''Overlay to interact with text input (at bottom of screen)'''
	def __init__(self, parent, default=None, password=False, empty_close=True):
		super().__init__(parent)
		text = parent.text
		self._modified = False
		if default is not None:
			text.setstr(default)
			self._modified = True
		self.completer = Sigil()
		self.password = password
		self.isolated = True
		self._nonscroll = ""
		self._empty_close = empty_close

		del self.keys["enter"]
		del self.keys["tab"]
		self.add_keys({
			  -1:			lambda _, chars: text.append_bytes(chars)
			, "tab":		staticize(text.complete, self.completer)
			, '^d':			text.clear
			, "btab":		text.backcomplete
			, "delete":		text.delchar
			, "shome":		text.clear
			, "up":			staticize(text.history_entry, 1)
			, "down": 		staticize(text.history_entry, -1)
			, "right":		staticize(text.movepos, 1
								, doc="Move cursor right")
			, "left":		staticize(text.movepos, -1
								, doc="Move cursor left")
			, "home":		text.home
			, "end":		text.end
			, 520:			text.delnextword
			, "a-h":		text.wordback
			, "a-l":		text.wordnext
			, "a-backspace":	text.delword
		})

	def add(self):
		super().add()
		if self.isolated and not self._modified:
			self.text.clear()	#TODO maybe use a stack?

	text = property(lambda self: self.parent.text)
	nonscroll = property(lambda self: None)
	@nonscroll.setter
	def nonscroll(self, val):
		if val is None:
			val = self._nonscroll
		else:
			self._nonscroll = val
		self.parent.text.setnonscroll(val)

	@key_handler("backspace")
	def wrap_backspace(self):
		if not str(self.parent.text) and self._empty_close:
			return -1
		return self.parent.text.backspace()

class _NScrollable(ScrollSuggest):
	'''
	A scrollable that updates a Screen on changes, has a history, and can
	escape newlines and tabs with \\.
	'''
	ESCAPE_MAP = {ord('\n'):	'\n'
				, ord('\t'):	'\t'
				, ord('\\'):	'\\'
				, ord('n'):		'\n'
				, ord('t'):		'\t'}
	_transformers = []				#more than meets the ~~eye~~ paste

	def __init__(self, parent):
		super().__init__(parent.width)
		self.parent = parent
		self._escape_mode = False	#next character should be escaped
		self._history = History()

	@property
	def isolated(self):
		last_text = self.parent.last_text
		if last_text is not None:
			return last_text.isolated
		return False

	def append_bytes(self, chars):
		'''Appends to the parent's scrollable. Enters "escape mode" on \\'''
		escape, self._escape_mode = self._escape_mode, False
		if len(chars) == 1:
			char = chars[0]
			if escape and char in self.ESCAPE_MAP:
				self.append(self.ESCAPE_MAP[char])
				return
			if char == ord('\\'):
				self._escape_mode = True
				return
			if char == 10: #newline = enter = set future
				if not self.isolated and str(self) \
				and str(self)[0] == Command.CHAR_COMMAND:
					Command.run(str(self)[1:], self.parent)
				elif self.parent.last_text is not None:
					self.parent.last_text.result.set_result(str(self))
				if not self.isolated:
					self._history.append(str(self))
				self.clear()
				return

		#convert bytes to string
		chars = bytes(filter(lambda x: x < 256, chars)).decode()

		for i in self._transformers:
			chars = i(self.parent, chars)
		self.append(chars)

	def history_entry(self, direction):
		'''Scroll through previous inputs'''
		if self.isolated:
			return
		if direction < 0:
			self.setstr(self._history.prevhist(str(self)))
		else:
			self.setstr(self._history.nexthist(str(self)))

	@classmethod
	def transform_paste(cls, transformer):
		cls._transformers.append(transformer)

	def _onchanged(self):		#TODO option to set result on every change, use for listoverlay
		super()._onchanged()
		self.parent.update_input()
transform_paste = _NScrollable.transform_paste

#OVERLAY MANAGER----------------------------------------------------------------
class Blurb:
	'''Screen helper class that manipulates the last two lines of the window.'''
	REFRESH_TIME = 4
	def __init__(self, parent):
		self.parent = parent
		self._erase = False
		self._refresh_task = None
		self.last = 0
		self.queue = []

	def _push(self, blurb, timestamp):
		'''Helper method to push blurbs and timestamp them'''
		#try to queue a blurb
		if blurb:
			if not isinstance(blurb, Coloring):
				blurb = Coloring(blurb)
			self.queue = blurb.breaklines(self.parent.width)
		#holding a message?
		if self.last < 0:
			return None #don't display nothing, but don't update display
		#next blurb is either a pop from the last message or nothing
		blurb = self.queue.pop(0) if self.queue else ""
		self.last = timestamp
		return blurb

	def push(self, blurb=""):
		'''Pushes blurb to the queue and timestamps the transaction.'''
		self.parent.write_status(self._push(blurb, self.parent.loop.time())
			, self.parent.START_BLURB)

	def hold(self, blurb):
		'''Holds blurb, preempting all `push`s until `release`'''
		self.parent.write_status(self._push(blurb, -1)
			, self.parent.START_BLURB)

	def release(self):
		'''Releases a `hold`. Needed to re-enable `push`'''
		self.last = self.parent.loop.time()
		self.parent.write_status(self._push("", self.last)
			, self.parent.START_BLURB)

	async def _refresh(self):
		'''Helper coroutine to start_refresh'''
		while self._erase:
			await asyncio.sleep(self.REFRESH_TIME)
			if self.parent.loop.time() - self.last > self.REFRESH_TIME: #erase blurbs
				self.push()

	def start_refresh(self):
		'''Start coroutine to advance blurb drawing every `time` seconds'''
		self._erase = True
		self._refresh_task = self.parent.loop.create_task(self._refresh())

	def end_refresh(self):
		'''Stop refresh coroutine'''
		self._erase = False
		if self._refresh_task is not None:
			self._refresh_task.cancel()

class Screen: #pylint: disable=too-many-instance-attributes
	'''
	Abstraction for interacting with the curses screen. Maintains overlays and
	handles I/O. Initialization also acquires and prepares the curses screen.
	'''
	_INTERLEAVE_DELAY = .001
	_INPUT_DELAY = .01

	_RETURN_CURSOR = "\x1b[?25h\x1b[u\n\x1b[A"
	#return cursor to the top of the screen, hide, and clear formatting on drawing
	_DISPLAY_INIT = "\x1b[%d;f" + CLEAR_FORMATTING + "\x1b[?25l"
	#format with tuple (row number, string)
	#move cursor, clear formatting, print string, clear garbage, and return cursor
	_SINGLE_LINE = "\x1b[%d;f" + CLEAR_FORMATTING +"%s\x1b[K" + _RETURN_CURSOR
	_RESERVE_LINES = 3
	START_DISPLAY = 0
	START_TEXT = -3
	START_BLURB = -2
	START_REVERSE = -1

	def __init__(self, manager, refresh_blurbs=True, loop=None):
		if not (sys.stdin.isatty() and sys.stdout.isatty()):
			raise OSError("interactive stdin/stdout required for Screen")
		self.manager = manager
		self.loop = asyncio.get_event_loop() if loop is None else loop

		self.active = True
		self._candisplay = False
		#guessed terminal dimensions
		self.width = 40
		self.height = 30
		#input/display stack
		self._ins = []
		#last high-priority overlay
		self._last_replace = 0
		self._last_text = -1

		self.text = _NScrollable(self)
		self.blurb = Blurb(self)
		if refresh_blurbs:
			self.blurb.start_refresh()

		#redirect stdout
		self._displaybuffer = sys.stdout
		sys.stdout = open(_REDIRECTED_OUTPUT, "a+", buffering=1)
		if sys.stderr.isatty():
			sys.stderr = sys.stdout

		#pass in the control chars for ctrl-c
		loop.add_signal_handler(SIGINT, lambda: curses.ungetch(3))

		#curses input setup
		self._screen = curses.initscr()		#init screen
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input
		self._screen.getch() #the first getch clears the screen

	mouse = property(lambda self: None)
	@mouse.setter
	def mouse(self, state):
		'''Turn the mouse on or off'''
		if not (self.active and self._candisplay):
			return None
		return curses.mousemask(state and KeyContainer.MOUSE_MASK)

	last_text = property(lambda self: self._ins[self._last_text] \
		if self._last_text >= 0 else None)

	def shutdown(self):
		'''Remove all overlays and undo everything in enter'''
		self.blurb.end_refresh()
		#let overlays do cleanup
		try:
			for i in reversed(self._ins):
				i.remove()
		except: #pylint: disable=bare-except
			print("Error occurred during shutdown:")
			traceback.print_exc()
		finally:
			#return to sane mode
			curses.echo(); curses.nocbreak(); self._screen.keypad(0)
			curses.endwin()
			sys.stdout.close() #close the temporary buffer set up
			sys.stdout = self._displaybuffer #reconfigure output
			sys.stderr = sys.stdout

			self.loop.remove_signal_handler(SIGINT)

	def sound_bell(self):
		'''Sound console bell.'''
		self._displaybuffer.write('\a')

	def reverse_top(self):
		'''Alternate display method'''
		self.START_REVERSE = 0
		self.START_DISPLAY = 1
		self.START_TEXT = -2
		self.START_BLURB = -1

	#Display Methods------------------------------------------------------------
	async def resize(self):
		'''Fire all added overlay's resize methods'''
		newy, newx = self._screen.getmaxyx()
		#magic number, but who cares; lines for text, blurbs, and reverse info
		newy -= self._RESERVE_LINES
		try:
			for i in self._ins:
				i.resize(newx, newy)
				await asyncio.sleep(self._INTERLEAVE_DELAY)
			self.width, self.height = newx, newy
			self._candisplay = 1
			self.text.setwidth(newx)
			self.update_input()
			self.update_status()
			await self.display()
		except DisplayException:
			self.width, self.height = newx, newy
			self._candisplay = 0

	async def display(self):
		'''Draw all overlays above the most recent one with replace=True'''
		if not (self.active and self._candisplay and self.height > 0):
			if self.active:
				self._displaybuffer.write("RESIZE TERMINAL")
			return
		#justify number of lines
		lines = ["" for i in range(self.height)]
		try:
		#start with the last "replacing" overlay, then all overlays afterward
			for start in range(self._last_replace, len(self._ins)):
				self._ins[start](lines)
		except DisplayException:
			self._candisplay = 0
			return
		self._displaybuffer.write(self._DISPLAY_INIT % (self.START_DISPLAY + 1))
		#draw each line in lines, deleting the rest of the garbage on the line
		for i in lines:
			self._displaybuffer.write(i+"\x1b[K\n\r")
		self._displaybuffer.write(self._RETURN_CURSOR)

	def update_input(self):
		'''Input display backend'''
		if not (self.active and self._candisplay):
			return
		last = self.last_text
		if last is None:
			return	#no textoverlays added
		string = last.text.show(last.password)
		self.write_status(string, self.START_TEXT, skip=True)

	def update_status(self):
		'''Look for the highest blurb for which status has been set'''
		for i in reversed(self._ins):
			reverse = i._reverse
			if reverse:
				just = reverse.justify(self.width, ensure_indicator=i._ensure)
				self.write_status("\x1b[7m" + just, self.START_REVERSE)
				break

	def write_status(self, string, height, skip=False):
		'''Backend to draw below overlays'''
		if not skip:
			if not (self.active and self._candisplay) or string is None:
				return
		if height < 0:
			height = self.height + self._RESERVE_LINES + height
		self._displaybuffer.write(self._SINGLE_LINE % (height+1, string))

	def schedule_display(self):
		self.loop.create_task(self.display())

	def schedule_resize(self):
		self.loop.create_task(self.resize())

	def redraw_all(self):
		'''Force redraw'''
		self.schedule_display()
		self.blurb.push()
		self.update_input()
		self.update_status()

	#Overlay Backends-----------------------------------------------------------
	def add_overlay(self, overlay):
		'''Add overlay backend. Use overlay.add() instead.'''
		if not isinstance(overlay, OverlayBase):
			return
		overlay.index = len(self._ins)
		self._ins.append(overlay)
		if overlay.replace:
			self._last_replace = overlay.index
		if isinstance(overlay, TextOverlay):
			overlay.nonscroll = None
			self._last_text = overlay.index
			self.update_input()
		#display is not strictly called beforehand, so better safe than sorry
		self.schedule_display()
		self.update_status()

	def pop_overlay(self, overlay):
		'''Pop overlay backend. Use overlay.remove() instead.'''
		del self._ins[overlay.index]
		#look for the last replace and replace indices
		was_text = overlay.index == self._last_text
		self._last_text = -1
		updated = False
		for i, j in enumerate(self._ins):
			if j.replace:
				self._last_replace = i
			if isinstance(j, TextOverlay):
				self._last_text = i
				updated = j.index == i+1
			j.index = i
		if was_text:
			if overlay.isolated:
				self.text.clear()
			if self._last_text > 0:
				self._ins[self._last_text].nonscroll = None
		overlay.index = None
		self.update_input()
		self.schedule_display()
		self.update_status()

	#Overlay Frontends----------------------------------------------------------
	def get_overlay(self, index):
		'''
		Get an overlay by its index in self._ins. Returns None
		if index is invalid
		'''
		if self._ins and index < len(self._ins):
			return self._ins[index]
		return None

	def get_overlays_by_class(self, class_, highest=0):
		'''
		Like getElementsByClassName in a browser.
		Returns a list of Overlays that are instances of `class_`
		'''
		#limit the highest index
		highest = len(self._ins) - highest

		return [j for _, j in zip(range(highest), reversed(self._ins))
			if class_ in type(j).mro()] #respect inheritence

	#Loop Coroutines------------------------------------------------------------
	async def input(self):
		'''
		Wait (non-blocking) for character, then run an overlay's key handler.
		If its return value is boolean True, re-displays the screen.
		'''
		nextch = -1
		while nextch == -1:
			nextch = self._screen.getch()
			await asyncio.sleep(self._INPUT_DELAY)

		#capture ^c and insure that we give control to the event loop
		if nextch == 3:
			self.active = False
			return
		if not self._ins or self._last_replace < 0:
			return

		chars = [nextch]
		while nextch != -1:
			nextch = self._screen.getch()
			chars.append(nextch)
		do_input = True
		context = self._ins[self._last_replace]
		for i in reversed(self._ins):
			try: #shoot up the hierarchy of overlays to try to handle
				if context.run_key(i, chars, do_input):
					await self.display()
				break
			except KeyException:
				do_input = False
			if i.terminate_input:
				break

	def stop(self):
		self.active = False
		#if input is running, this gets it out of the await loop
		curses.ungetch(0)

class Manager:
	'''Main class; creates a screen and maintains graceful exits'''
	_on_exit = []
	def __init__(self, loop=None):
		loop = asyncio.get_event_loop() if loop is None else loop
		if not hasattr(loop, "create_future"):
			setattr(loop, "create_future", lambda: asyncio.Future(loop=loop))
		self.loop = loop
		#general state
		self.exited = asyncio.Event(loop=loop)
		self.screen = None

	async def run(self, prepared_coroutine=None, refresh_blurbs=True):
		'''Main client loop'''
		try:
			self.screen = Screen(self, refresh_blurbs=refresh_blurbs, loop=self.loop)
			await self.screen.resize()
			#done for now; call coroutines waiting for preparation
			if asyncio.iscoroutine(prepared_coroutine):
				self.loop.create_task(prepared_coroutine)
			#keep running key callbacks
			while self.screen.active:
				try:
					await self.screen.input()
				except Exception: #pylint: disable=broad-except
					self.screen.blurb.push("Error occurred in key callback")
					traceback.print_exc()
		except asyncio.CancelledError:
			pass	#catch cancellations
		finally:
			for i in self._on_exit:
				try:
					await i
				except Exception:
					print("Error occurred during shutdown:")
					traceback.print_exc()
			self.exited.set()

	@classmethod
	def start(cls, *args, loop=None):
		'''
		Create an instance of the Manager() class.
		Further arguments are interpreted as func, arg0, arg1,... and called
		when the instance is prepared with `func(Manager, arg0, arg1,...)`
		'''
		#instantiate
		this, prepared_coroutine = cls(loop=loop), None
		try:
			#just use the first arg as a (coroutine) function and prepare coro
			if args and callable(args[0]):
				if not asyncio.iscoroutinefunction(args[0]):
					raise TypeError("Expected coroutine as first argument to "\
						"Manager.start")
				prepared_coroutine = args[0](this, *args[1:])

			this.loop.create_task(this.run(prepared_coroutine))
			this.loop.run_until_complete(this.exited.wait())
		finally:
			if this.screen is not None:
				this.screen.shutdown()
			this.loop.run_until_complete(this.loop.shutdown_asyncgens())

	def stop(self):
		if self.screen is not None:
			self.screen.stop()

	#Miscellaneous Frontends----------------------------------------------------
	@classmethod
	def on_done(cls, func, *args):
		'''Add function or coroutine to run after an instance has shut down'''
		if asyncio.iscoroutinefunction(func):
			func = func(*args)
		if not asyncio.iscoroutine(func):
			func = asyncio.coroutine(func)(*args)
		cls._on_exit.append(func)
		return func
