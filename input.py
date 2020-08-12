#!/usr/bin/env python3
#client/input.py
'''
Various non-text input overlays. Also includes InputMux, which
provides a nice interface for modifying values within a context.
'''
import asyncio
from .display import SELECT, CLEAR_FORMATTING, colors \
	, Box, Coloring, JustifiedColoring, DisplayException
from .util import staticize, quitlambda, key_handler, numdrawing
from .base import FutureOverlay, OverlayBase, TextOverlay

__all__ = ["ListOverlay", "VisualListOverlay", "ColorOverlay"
	, "ColorSliderOverlay", "ConfirmOverlay", "DisplayOverlay", "TabOverlay"
	, "PromptOverlay", "InputMux"]

#DISPLAY CLASSES----------------------------------------------------------------
class ListOverlay(FutureOverlay, Box): #pylint: disable=too-many-instance-attributes
	'''
	Allows user to select an entry from a list. By default, the list is cloned,
	but a callable with signature (`out_list`) that returns a `list` can be
	specified with `builder`.
	The display of each entry can be altered with the `line_drawer` decorator.
	'''
	replace = True
	def __init__(self, parent, out_list, modes=None, builder=list):
		super().__init__(parent)
		self._it = 0	#current list selector
		self.mode = 0	#current 'mode'; adds some dimensionality to callback

		self.raw, self._builder = out_list, builder
		self.list = builder(self.raw)

		self._draw_other = None
		self._modes = [""] if modes is None else modes
		self._search = None

		self._draw_cache = {}

		self.add_keys({
			 'H':		self.open_help
			, 'q':		quitlambda
		})

	it = property(lambda self: self._it
		, doc="Currently selected list index")
	@it.setter
	def it(self, dest): #pylint: disable=invalid-name
		self._do_move(dest)

	search = property(lambda self: self._search
		, doc="Current string to search with n/N")
	@search.setter
	def search(self, new):
		status = ""
		if new:
			status = '/' + new
		else:
			new = None
		self.parent.write_status(status, 1)
		self._search = new

	@property
	def selected(self):
		'''The currently selected element from self.list.'''
		return self.list[self.it]

	def remove(self):
		super().remove()
		self.parent.update_input()

	def __getitem__(self, val):
		'''Sugar for `self.list[val]`'''
		return self.list[val]

	def __iter__(self):
		'''Sugar for `iter(self.list)`'''
		return iter(self.list)

	def __call__(self, lines):
		'''
		Display a list in a box. If too long, entries are trimmed
		to include an ellipsis
		'''
		lines[0] = self.box_top()
		size = self.height-2
		maxx = self.width-2
		#worst case column: |(value[0])…(value[-1])|
		#				    1    2     3  4        5
		#worst case rows: |(list member)|
		#				  1	2			3
		if size < 1 or maxx < 3:
			raise DisplayException()
		#which portion of the list is currently displaced
		partition = self.it - (self.it%size)
		#get the partition of the list we're at, pad the list
		sub_list = self.list[partition:partition+size]
		sub_list = sub_list + ["" for i in range(size-len(sub_list))]
		#display lines
		for i, row in enumerate(sub_list):
			if not isinstance(row, JustifiedColoring):
				row = JustifiedColoring(str(row))
			#alter the string to be drawn
			if i+partition < len(self.list):
				self._draw_line(row, i+partition)
			#justifiedcolorings have their own cache, but we rebuild them each redraw
			cache_fetch = self._draw_cache.get(row)
			if cache_fetch is None:
				cache_fetch = row.justify(maxx)
				self._draw_cache[row] = cache_fetch
			lines[i+1] = self.box_noform(cache_fetch)

		lines[-1] = self.box_bottom(self._modes[self.mode])
		return lines

	def resize(self, _, __):
		self._draw_cache.clear()

	def _draw_line(self, line, number):
		'''Callback to run to modify display of each line. '''
		if self._draw_other is not None:
			self._draw_other(self, line, number)
		if number == self.it:	#reverse video on selected line
			line.add_global_effect(0)

	def line_drawer(self, func):
		'''
		Decorator to set a line drawer. Expects signature (self, line, number),
		where `line` is a Coloring object of a line and `number`
		is its index in self.list
		'''
		self._draw_other = func

	def _do_move(self, dest):
		'''
		Callback for setting property 'it'. Useful for when an update is needed
		self.it changes (like VisualListOverlay)
		'''
		self._it = dest

	def _goto_lambda(self, func, direction, loop):
		'''
		Backend for goto_lambda.
		`direction` = 0 for closer to the top, 1 for closer to the bottom.
		'''
		start = self.it
		for i in range(len(self.list)-start-1 if direction else start):
			i = (start+i+1) if direction else (start-i-1)
			if func(i):
				self.it = i #pylint: disable=invalid-name
				return
		if loop:
			for i in range(start if direction else len(self.list)-start-1):
				i = i if direction else len(self.list)-i-1
				if func(i):
					self.it = i
					return
		else:
			self.it = int(direction and (len(self.list)-1))

	def goto_lambda(self, func, loop=False):
		'''
		Move to a list entry for which `func` returns True.
		`func`'s signature should be (self.list index)
		'''
		return tuple(staticize(self._goto_lambda, func, i, loop)
			for i in range(2))

	#predefined list iteration methods
	@key_handler("down", amt=1, doc="Down one list item")
	@key_handler("j", amt=1, doc="Down one list item")
	@key_handler("mouse-wheel-down", amt=1, doc="Down one list item")
	@key_handler("up", amt=-1, doc="Up one list item")
	@key_handler("k", amt=-1, doc="Up one list item")
	@key_handler("mouse-wheel-up", amt=-1, doc="Up one list item")
	def increment(self, amt):
		'''Move self.it by amt'''
		if not self.list:
			return
		self.it = (self.it + amt) % len(self.list) #pylint: disable=invalid-name

	@key_handler("l", amt=1, doc="Go to next mode")
	@key_handler("h", amt=-1, doc="Go to previous mode")
	@key_handler("right", amt=1, doc="Go to next mode")
	@key_handler("left", amt=-1, doc="Go to previous mode")
	def chmode(self, amt):
		'''Move to mode amt over, with looparound'''
		self.mode = (self.mode + amt) % len(self._modes)

	@key_handler("g", is_end=0, doc="Go to beginning of list")
	@key_handler("G", is_end=1, doc="Go to end of list")
	def goto_edge(self, is_end):
		self.it = int(is_end and (len(self.list)-1))

	@key_handler("mouse-left")
	@key_handler("mouse-right", override=0)
	def try_mouse(self, _, y):
		'''Run enter on the element of the list that was clicked'''
		#Manipulate self.it and try_enter
		#y in the list
		size = self.height - 2
		#borders
		if not y in range(1, size+1):
			return None
		newit = (self.it//size)*size + (y - 1)
		if newit >= len(self.list):
			return None
		self.it = newit #pylint: disable=invalid-name
		enter_fun = self.keys["enter"]
		if callable(enter_fun):
			return enter_fun([-1], self)
		return None

	@key_handler("^r")
	def regen_list(self):
		'''Regenerate list based on raw list reference'''
		if self.raw:
			self.list = self._builder(self.raw)

	@key_handler('/')
	@key_handler("^f")
	def open_search(self):
		'''Open a search window'''
		search = TextOverlay(self.parent)
		search.nonscroll = '/'
		@search.callback
		def _(value):
			self.search = str(value)
			self.scroll_search.bound(self, 1)
			return 1
		search.add()

	@key_handler("backspace")
	def clear_search(self):
		'''Clear search'''
		self.search = ""

	@key_handler("n", direction=1)
	@key_handler("N", direction=0)
	def scroll_search(self, direction):
		'''Scroll through search index'''
		def goto(index):
			value = str(self.list[index])
			if value and self.search is not None:
				return value.lower().find(self.search.lower()) != -1
			return False
		self._goto_lambda(goto, direction, True)

class VisualListOverlay(ListOverlay, Box):
	'''ListOverlay with visual mode like in vim: can select multiple rows'''
	replace = True
	def __init__(self, parent, *args, **kwargs):
		super().__init__(parent, *args, **kwargs)
		self._selected = set()
		self._select_buffer = set()
		self._start_select = -1

	@property
	def current(self):
		'''Sugar more similar to `ListOverlay.selected`'''
		return self.list[self.it]

	@property
	def selected(self):
		'''Get list of selected items'''
		indices = self._selected_index()
		#add the iterator; idempotent if already in set
		#here so that the currently selected line doesn't draw an underline
		indices.add(self.it)
		return [self.list[i] for i in indices]

	def _do_move(self, dest):
		'''Update selection'''
		if self._start_select + 1:
			if dest < self._start_select:	#selecting below start
				self._select_buffer = set(range(dest, self._start_select))
			else:
				self._select_buffer = set(range(self._start_select+1, dest+1))
		self._it = dest

	def _draw_line(self, line, number):
		'''New draw callback that adds an underline to selected elements'''
		super()._draw_line(line, number)
		if number in self._selected_index():
			line.add_global_effect(1)

	def clear(self):
		self._selected = set()	#list of indices selected by visual mode
		self._select_buffer = set()
		self._start_select = -1

	def _selected_index(self):
		'''Get list (set) of selected and buffered indices'''
		return self._selected.symmetric_difference(self._select_buffer)

	@key_handler('s')
	def toggle(self):
		'''Toggle the current line'''
		self._selected.symmetric_difference_update((self.it,))

	@key_handler('v')
	def toggle_select(self):
		'''Toggle visual mode selecting'''
		if self._start_select + 1:	#already selecting
			#canonize the select
			self._selected.symmetric_difference_update(self._select_buffer)
			self._select_buffer = set()
			self._start_select = -1
			return
		self._selected.symmetric_difference_update((self.it,))
		self._start_select = self.it

	@key_handler('q')
	def clear_quit(self):
		'''Clear the selection or quit the overlay'''
		if self._select_buffer or self._selected:
			return self.clear()
		return -1

class ColorOverlay(ListOverlay, Box):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	_SELECTIONS = ["normal", "shade", "tint", "grayscale"]
	_COLOR_LIST = ["red", "orange", "yellow", "light green", "green", "teal",
		"cyan", "turquoise", "blue", "purple", "magenta", "pink", "color sliders"]

	def __init__(self, parent, initcolor=None):
		super().__init__(parent, self._COLOR_LIST, self._SELECTIONS)
		self.initcolor = [127, 127, 127]
		self._callback = None

		#parse initcolor
		if isinstance(initcolor, str) and len(initcolor) == 6:
			initcolor = [int(initcolor[i*2:(i+1)*2], 16) for i in range(3)]
		if isinstance(initcolor, list) and len(initcolor) == 3:
			self.initcolor = initcolor
			#how much each color corrseponds to some color from the genspecturm
			divs = [divmod(i*5/255, 1) for i in initcolor]
			#if each error is low enough to be looked for
			if all(i[1] < .05 for i in divs):
				for i, j in enumerate(self.SPECTRUM[:3]):
					try:
						find = j.index(tuple(int(k[0]) for k in divs))
						self.it = find
						self.mode = i
						break
					except ValueError:
						pass
			else:
				self.it = len(self._COLOR_LIST)-1

	def _new_callback(self, fut):
		'''Add Color slider overlay if the right element's selected'''
		if self.it == 12:
			further_input = ColorSliderOverlay(self.parent, self.initcolor)
			further_input.callback(self._callback)
			self.swap(further_input)
			return
		super()._new_calllback(fut)

	@property
	def selected(self):
		'''Retrieve color as RGB 3-tuple'''
		which = self.SPECTRUM[self.mode][self.it]
		if self.mode == 3:
			return (255 * which/ 12 for i in range(3))
		return tuple(int(i*255/5) for i in which)

	def _draw_line(self, line, number):
		'''Add color samples to the end of lines'''
		super()._draw_line(line, number)
		#reserved for color sliders
		if number == len(self._COLOR_LIST)-1 or not colors.two56on:
			return
		which = self.SPECTRUM[self.mode][number]
		if self.mode == 3: #grayscale
			color = colors.grayscale(number * 2)
		else:
			color = colors.two56([i*255/5 for i in which])
		try:
			line.add_indicator(' ', color, 0)
		except DisplayException:
			pass

	@classmethod
	def genspectrum(cls):
		'''
		Create colors that correspond to values of _COLOR_LIST, as well as
		as tints, shades, and 12-step-grayscale
		'''
		init = [0, 2]
		final = [5, 2]
		rspec = [(5, g, 0) for g in init]
		yspec = [(r, 5, 0) for r in final]
		cspec = [(0, 5, b) for b in init]
		bspec = [(0, g, 5) for g in final]
		ispec = [(r, 0, 5) for r in init]
		mspec = [(5, 0, b) for b in final]

		#flatten spectra
		spectrum = [item for i in (rspec, yspec, cspec, bspec, ispec, mspec)
			for item in i]

		shade = [(max(0, i[0]-1), max(0, i[1]-1), max(0, i[2]-1))
			for i in spectrum]
		tint = [(min(5, i[0]+1), min(5, i[1]+1), min(5, i[2]+1))
			for i in spectrum]
		grayscale = range(12)

		cls.SPECTRUM = [spectrum, shade, tint, grayscale]
ColorOverlay.genspectrum()

class ColorSliderOverlay(FutureOverlay, Box):
	'''Display 3 bars for red, green, and blue.'''
	replace = True
	NAMES = ["Red", "Green", "Blue"]

	def __init__(self, parent, initcolor=None):
		super().__init__(parent)
		initcolor = initcolor if initcolor is not None else [127, 127, 127]
		if not isinstance(initcolor, (tuple, list)):
			raise TypeError("initcolor must be list or tuple")
		self._color = list(initcolor)
		self._update_text()
		self._rgb = 0

		self.add_keys({'q':		quitlambda})

	selected = property(lambda self: tuple(self._color))

	def __call__(self, lines):
		'''Display 3 bars, their names, values, and string in hex'''
		wide = (self.width-2)//3 - 1
		space = self.height-7
		if space < 1 or wide < 5: #green is the longest name
			raise DisplayException()
		lines[0] = self.box_top()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space = ratio of value to 255)
			for j in range(3):
				if (space-i)*255 < (self._color[j]*space):
					string += colors.RGB_COLUMNS[j]
				string += ' ' * wide + CLEAR_FORMATTING + ' '
			#justify (including escape sequence length)
			lines[i+1] = self.box_part(string)
		sep = self.box_part("")
		lines[-6] = sep
		names, vals = "", ""
		for i in range(3):
			if i == self._rgb:
				names += SELECT
				vals += SELECT
			names += self.NAMES[i].center(wide) + CLEAR_FORMATTING
			vals += str(self._color[i]).center(wide) + CLEAR_FORMATTING
		lines[-5] = self.box_part(names) #4 lines
		lines[-4] = self.box_part(vals) #3 line
		lines[-3] = sep #2 lines
		formatted = format(self._colored_text)
		nondraw = len(formatted) - numdrawing(formatted)
		lines[-2] = self.box_part(formatted.rjust(nondraw + 3*(wide+1)//2)) #1
		lines[-1] = self.box_bottom() #last line

	#predefined self-traversal methods
	@key_handler('up', amt=1, doc="Increase selected color by 1")
	@key_handler('k', amt=1, doc="Increase selected color by 1")
	@key_handler('ppage', amt=10, doc="Increase selected color by 10")
	@key_handler('home', amt=255, doc="Set color value to 255")
	@key_handler('down', amt=-1, doc="Decrease selected color by 1")
	@key_handler('j', amt=-1, doc="Decrease selected color by 1")
	@key_handler('npage', amt=-10, doc="Decrease selected color by 10")
	@key_handler('end', amt=-255, doc="Set color value to 0")
	def increment(self, amt):
		'''Increase the selected color by amt'''
		self._color[self._rgb] = max(0, min(255, self._color[self._rgb] + amt))
		self._update_text()

	@key_handler('h', amt=-1, doc="Go to color to left")
	@key_handler('left', amt=-1, doc="Go to color to left")
	@key_handler('l', amt=1, doc="Go to color to right")
	@key_handler('right', amt=1, doc="Go to color to right")
	def chmode(self, amt):
		'''Go to the color amt to the right'''
		self._rgb = (self._rgb + amt) % 3

	def _update_text(self):
		self._colored_text = Coloring(self.to_hex(self._color))
		self._colored_text.insert_color(0, colors.two56(self._color))

	@staticmethod
	def to_hex(color):
		'''Get color in hex form'''
		return ''.join("{:02X}".format(int(i)) for i in color)

class DisplayOverlay(OverlayBase, Box):
	'''
	Overlay that displays a message in a box. Valid messages are (lists of)
	strings and (lists of) Coloring objects.
	'''
	def __init__(self, parent, prompts, outdent=""):
		super().__init__(parent)
		self.replace = False		#bother drawing under this overlay?
		self._begin = 0				#internal scroll
		self._outdent = outdent

		self._rawlist = []
		self._prompts = []
		self.prompts = prompts

		self.add_keys({
			 'q':		quitlambda
			, 'H':		self.open_help
		})

	outdent = property(lambda self: self._outdent)
	@outdent.setter
	def outdent(self, val):
		self._outdent = val

	prompts = property(lambda self: self._rawlist)
	@prompts.setter
	def prompts(self, strings):
		'''Basically re-initialize without making a new overlay'''
		if isinstance(strings, (str, Coloring)):
			strings = [strings]
		self._rawlist = [i if isinstance(i, Coloring) else Coloring(i)
			for i in strings]

		#flattened list of broken strings
		self._prompts = [j for i in self._rawlist
			for j in i.breaklines(self.width-2, outdent=self._outdent)]
		#bigger than the box holding it
		self.replace = len(self._prompts) > self.height-2

		self._begin = 0

	def __call__(self, lines):
		'''Display message'''
		begin = max((self.height-2)//2 - len(self._prompts)//2, 0) \
			if not self.replace else 0
		i = 0
		lines[begin] = self.box_top()
		for i in range(min(len(self._prompts), len(lines)-2)):
			lines[begin+i+1] = self.box_part(self._prompts[self._begin+i])
		i += 2
		#fill in the rest of the box
		if self.replace:
			while begin + i < len(lines)-1:
				lines[begin+i] = self.box_part("")
				i += 1
			scrollbar = 1 + self._begin * (len(lines)-3) / (len(self._prompts)-len(lines)+2)
			lines[int(scrollbar)] = lines[int(scrollbar)][:-1] + 'o'
		lines[begin+i] = self.box_bottom()

	def resize(self, newx, newy):
		'''Resize message'''
		if self._rawlist is None:
			return
		self._prompts = [j for i in self._rawlist
			for j in i.breaklines(newx-2, outdent=self._outdent)]
		# if bigger than the box holding it, stop drawing the overlay behind it
		self.replace = len(self._prompts) > self.height-2

	@key_handler('k', amt=-1, doc="Scroll upward")
	@key_handler('up', amt=-1, doc="Scroll upward")
	@key_handler('j', amt=1, doc="Scroll downward")
	@key_handler('down', amt=1, doc="Scroll downward")
	def scroll(self, amt):
		if not self.replace: #nothing to scroll
			return
		maxlines = self.height-2
		self._begin = min(max(0, self._begin+amt), len(self._prompts) - maxlines)

	@key_handler('g', top=True, doc="Scroll top")
	@key_handler('G', top=False, doc="Scroll bottom")
	def scroll_border(self, top):
		if not self.replace: #nothing to scroll
			return
		maxlines = self.height-2
		self._begin = 0 if top else len(self._prompts) - maxlines

class PromptOverlay(DisplayOverlay, TextOverlay):
	'''Combine text input with a prompt'''
	def __init__(self, screen, prompt, default=None, password=False):
		DisplayOverlay.__init__(self, screen, prompt)
		TextOverlay.__init__(self, screen, default, password)

class TabOverlay(FutureOverlay):
	'''
	Overlay for 'tabbing' through things.
	Displays options on lines nearest to the input scrollable
	'''
	def __init__(self, parent, tab_list, *args, rows=5): #pylint: disable=too-many-arguments
		super().__init__(parent)
		self.list = tab_list
		self._it = 0
		self._rows = min(len(tab_list), rows, self.height)
		self.replace = self._rows == self.height
		#add extra keys for tabbing
		for i, j in enumerate(args):
			self.key_handler(j, direction=(1 - 2*(i % 2)))(self.move_it.bound)
		append = lambda _, chars: self.parent.text.append_bytes(chars) or -1
		self.add_keys({-1:	append})
	it = property(lambda self: self._it)

	def __call__(self, lines):
		'''Display message'''
		line_offset = 1
		for i, entry in zip(range(self._rows), (self.list + self.list)[self._it:]):
			entry = Coloring(entry)
			entry.add_global_effect(1)
			if i == 0:
				entry.add_global_effect(0)
			formatted = entry.breaklines(self.width, "  ")
			for j, line in enumerate(reversed(formatted)):
				lines[-line_offset-j] = line
			line_offset += len(formatted)

	def add(self, set_result=False): #pylint: disable=arguments-differ
		'''
		Add the overlay. `set_result` controls when whether to "autotab" when
		the overlay is added. If this is true and the list is a singleton,
		the overlay is not added
		'''
		if set_result:
			self._future.set_result(self.list[self._it])
			if len(self.list) <= 1:
				return
		super().add()

	@key_handler('tab', direction=1, doc="Tab forward")
	@key_handler('btab', direction=-1, doc="Tab backward")
	def move_it(self, direction):
		self._it = (self._it + direction) % len(self.list)
		try:
			self._future.set_result(self.list[self._it])
		except: #pylint: disable=bare-except
			pass

class ConfirmOverlay(OverlayBase):
	'''Overlay to confirm selection y/n (no slash)'''
	replace = False
	def __init__(self, parent, prompt, callback):
		super().__init__(parent)
		self._prompt = prompt

		def call():
			if asyncio.iscoroutine(callback):
				self.parent.loop.create_task(callback)
			else:
				self.parent.loop.call_soon(callback)
			self.parent.blurb.release()
			return -1

		self.add_keys({			#run these in order
			  'y':	call
			, 'n':	(self.parent.blurb.release, -1)
		})
		self.keys.nomouse()
		self.keys.noalt()

	def add(self):
		'''Hold prompt blurb'''
		self.parent.blurb.hold(self._prompt)
		super().add()

#INPUTMUX CLASS-----------------------------------------------------------------
class InputMux:
	'''
	Abstraction for a set of adjustable values to display with a ListOverlay.
	Comes pre-built with drawing for each kind of value.
	'''
	def __init__(self, confirm_if_button=True):
		self.parent = None

		self.ordering = []
		self.indices = {}
		self.context = None
		self.confirm_if_button = confirm_if_button
		self.has_button = False
		self.warn_exit = False

	def add(self, parent, context):
		'''Add the muxer with ChatangoOverlay `parent`'''
		self.context = context
		self.parent = parent
		overlay = ListOverlay(parent
			, [self.indices[i].doc for i in self.ordering])
		overlay.line_drawer(self._drawing)

		@overlay.key_handler("enter")
		@overlay.key_handler(' ')
		@overlay.key_handler("tab")
		def _(me):
			"Change value"
			return self.indices[self.ordering[me.it]].select()

		overlay.add_keys({
			'q':	staticize(self.try_warn, parent, overlay
				, doc=quitlambda.doc)
		})

		overlay.add()

	def _drawing(self, _, string, i):
		'''Defer to the _ListEl's local drawer'''
		element = self.indices[self.ordering[i]]
		#needs a drawer and a getter
		if element.draw and element.get:
			element.draw(self, element.get(self.context), string)

	def try_warn(self, parent, overlay):
		'''Exit, warning about unconfirmed values'''
		if self.warn_exit:
			ConfirmOverlay(parent, "Really close menu? (y/n)"
				, overlay.remove).add()
			return None
		return -1

	def listel(self, data_type):
		'''
		Decorator to create an input field with a certain data type.
		`data_type` can be one of "str", "color", "enum", "bool", or "button"
		When a function is decorated with a particular data type, it acts as a
		getter for a list element, similar to a `property` getter.
		Setters and drawers can be added in the same way as properties

		func should have signature:
			(context:	the context as supplied by the InputMux)
		The name of the field in the list will be derived from func.__doc__
		'''
		return staticize(self._ListEl, self, data_type)

	class _ListEl:
		'''
		Backend class.
		Use `listel` to abstract away the `parent` argument in __init__
		'''
		def __init__(self, parent, data_type, func):
			self.name = func.__name__
			if parent.indices.get(self.name):
				raise TypeError("Cannot implement element {} more " \
					"than once".format(repr(self.name)))
			#bind parent names
			self.parent = parent
			self.parent.indices[self.name] = self
			self.parent.ordering.append(self.name)
			self.doc = func.__doc__

			self._type = data_type
			if self._type == "color":
				self.draw = self.draw_color
			elif self._type == "str":
				self.draw = self.draw_string
			elif self._type == "enum":
				self.draw = self.draw_enum
			elif self._type == "bool":
				self.draw = self.draw_bool
			elif self._type == "button":
				self.draw = None
				self.get = None
				self._set = func
				if self.parent.confirm_if_button:
					self.parent.has_button = True
				return
			else:	#invalid type
				raise TypeError("input type {} not recognized".format(repr(data_type)))

			self.get = func
			self._set = None

		def setter(self, func):
			'''
			Decorator to set setter. Setters should have the signature:
				(context:	the context supplied by the InputMux
				,value:		the new value after input)
			'''
			self._set = func
			return self

		def drawer(self, func):
			'''
			Decorator to set drawer. Drawers should have the signature:
				(mux:		the InputMux instance the _ListEl is a part of
				,value:		the value of the element obtained by the getter
				,coloring:	the row's Coloring object)
			'''
			self.draw = func
			return self

		def select(self):
			'''Open input overlay to modify value'''
			further_input = None
			if self._type == "color":
				further_input = ColorOverlay(self.parent.parent
					, self.get(self.parent.context))			#initial color
				@further_input.callback
				def _(rgb): #pylint: disable=unused-variable
					self._set(self.parent.context, rgb)
					return 1

			elif self._type == "str":
				further_input = PromptOverlay(self.parent.parent
					, self.doc
					, default=str(self.get(self.parent.context)))
				@further_input.callback
				def _(string):
					self._set(self.parent.context, string)
					return 1

			elif self._type == "enum":
				enumeration, index = self.get(self.parent.context)
				further_input = ListOverlay(self.parent.parent
					, enumeration)		#enum entries
				further_input.it = index

				@further_input.callback
				def _(_): #neither the name of the function nor the value matter
					self._set(self.parent.context, further_input.it)
					return 1

			elif self._type == "bool":
				self._set(self.parent.context,
					not self.get(self.parent.context))	#toggle

			elif self._type == "button":
				ret = self._set(self.parent.context)
				self.parent.warn_exit = False
				return ret

			self.parent.warn_exit = self.parent.has_button
			if further_input:
				further_input.add()
			return None

		@staticmethod
		def draw_color(_, value, coloring):
			'''Default color drawer'''
			coloring.add_indicator(' ', colors.two56(value), 0)

		@staticmethod
		def draw_string(_, value, coloring):
			'''Default string drawer'''
			val = str(value)
			coloring.add_indicator(val, colors.yellow_text)

		@classmethod
		def draw_enum(cls, mux, value, coloring):
			'''Default enum drawer'''
			#dereference and run string drawer
			cls.draw_string(mux, value[0][value[1]], coloring)

		@staticmethod
		def draw_bool(_, value, coloring):
			'''Default bool drawer'''
			coloring.add_indicator('y' if value else 'n'
				, colors.green_text if value else colors.red_text)
