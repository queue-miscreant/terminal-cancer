#!/usr/bin/env python3
#client/display.py
'''
Module for formatting; support for fitting strings to column widths and ANSI
color escape string manipulations. Also contains generic string containers.
'''
import re
from math import ceil, floor
from .util import Sigil
from .wcwidth import wcwidth

#all imports needed by overlay.py
__all__ =	["CLEAR_FORMATTING", "CHAR_CURSOR", "SELECT", "SELECT_AND_MOVE"
			, "collen", "columnslice", "colors", "Box", "Coloring"
			, "JustifiedColoring", "Scrollable", "ScrollSuggest"]

#character ranges that don't appear to cooperate with wcwidth (even the C implementation)
BAD_CHARSETS = [
	  (119964, 26, ord('A'))	#uppercase math
	, (119990, 26, ord('a'))	#lowercase math
	, (119860, 26, ord('A'))	#uppercase italic math
	, (119886, 26, ord('a'))	#lowercase italic math
	, (120172, 26, ord('A'))	#uppercase fractur
	, (120198, 26, ord('a'))	#lowercase fractur
	, (120068, 26, ord('A'))	#uppercase math fractur
	, (120094, 26, ord('a'))	#lowercase math fractur
]

def _parse_fractur(raw):
	cooked = ""
	for i in raw:
		for begin, length, onto in BAD_CHARSETS:
			if ord(i) in range(begin, begin+length):
				i = chr(ord(i) - begin + onto)
				break
		if ord(i) == 136:
			continue
		cooked += i
	return cooked

#REGEXES------------------------------------------------------------------------
#sane textbox splitting characters
_SANE_TEXTBOX =	r"\s\-\+/`~,;="
#sane textbox word-backspace
_UP_TO_WORD_RE = re.compile("([^{0}]*[{0}])*[^{0}]+[{0}]*".format(
	_SANE_TEXTBOX))
#sane textbox word-delete
_NEXT_WORD_RE =	re.compile("([{0}]*[^{0}]+)".format(_SANE_TEXTBOX))
#line breaking characters
_LINE_BREAKING = "- 　"

#COLORING CONSTANTS------------------------------------------------------------
CHAR_CURSOR = "\x1b[s"
SELECT = "\x1b[7m"
SELECT_AND_MOVE = CHAR_CURSOR + SELECT
CLEAR_FORMATTING = "\x1b[m"

#COLUMN WIDTH FUNCTIONS--------------------------------------------------------
def collen(string):
	'''Column width of a string'''
	escape = False
	ret = 0
	for i in string:
		temp = (i == '\x1b') or escape
		#not escaped and not transitioning to escape
		if not temp:
			ret += max(0, wcwidth(i))
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return ret

def columnslice(string, width):
	'''Fit string to column width'''
	escape = False
	#number of columns passed, number of chars passed
	trace, lentr = 0, 0
	for lentr, i in enumerate(string):
		temp = (i == '\x1b') or escape
		#escapes (FSM-style)
		if not temp:
			trace += max(0, wcwidth(i))
			if trace > width:
				return lentr
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return lentr + 1

#COLORING STUFF-----------------------------------------------------------------
class DisplayException(Exception):
	'''Exception for handling errors from Coloring or Scrollable manipulation'''

class _ColorManager: #pylint: disable=too-many-instance-attributes
	'''
	Container class for defining terminal colors.
	Includes support for 256-colors terminal output.
	'''
	#valid color names to add
	COLOR_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan"
		, "white", "", "none"]
	CAN_DEFINE_EFFECTS = True
	RGB_COLUMNS = ["\x1b[31;22;41m"		#red
				 , "\x1b[32;22;42m"		#green
				 , "\x1b[34;22;44m"]	#blue

	def __init__(self):
		self._two56 = False
		self._two56_start = None

		#storage for defined pairs
		self.colors = [
			  "\x1b[39;22;49m"	#Normal/Normal			0
			, "\x1b[31;22;47m"	#Red/White				1
			, "\x1b[31;22;49m"	#red	(InputMux)		2
			, "\x1b[32;22;49m"	#green	(InputMux)		3
			, "\x1b[33;22;49m"	#yellow	(InputMux)		4
		]
		self._predefined = len(self.colors)
		#names
		self.default = self.raw_num(0)
		self.system = self.raw_num(1)
		self.red_text = self.raw_num(2)
		self.green_text = self.raw_num(3)
		self.yellow_text = self.raw_num(4)

		#a tuple containing 'on' and 'off'
		self.effects =	[
			  (SELECT, "\x1b[27m")
			, ("\x1b[4m", "\x1b[24m")
		]
		self._effects_bits = (1 << len(self.effects))-1

	predefined = property(lambda self: self._predefined)
	effects_bits = property(lambda self: self._effects_bits)
	defined = property(lambda self: len(self.colors) - self._predefined
		, doc="The number of defined colors (discluding predefined ones)")

	two56on = property(lambda self: self._two56
		, doc='''Turn 256 colors on (and if undefined, define colors) or off''')
	@two56on.setter
	def two56on(self, state):
		self._two56 = state
		if state and self._two56_start is None: #not defined on startup
			self._two56_start = self.defined
			for i in range(256):
				self.def_color(i)

	def _continue_formatting(self, last_color, last_effect, next_effect):
		'''Used internally to build a ANSI formatting string'''
		formatting = self.colors[last_color-1] if last_color > 0 else ""
		return formatting + "".join(effect[bool((1 << i) & last_effect)] \
			for i, effect in enumerate(self.effects) if (1 << i) & next_effect)

	def def_color(self, fore, back="none", intense=False):
		'''Define a new foreground/background pair, optionally intense'''
		pair = "\x1b[3"
		if isinstance(fore, int):
			pair += "8;5;%d" % fore
		else:
			pair += str(self.COLOR_NAMES.index(fore))
			pair += intense and ";1" or ";22"
		if isinstance(back, int):
			pair += ";48;5;%d" % back
		else:
			pair += ";4%d" % self.COLOR_NAMES.index(back)
		self.colors.append(pair+"m")
		return self.defined-1

	def def_effect(self, effect_on, effect_off):
		'''Define a new effect, turned on and off with `effect_on`/`effect_off`'''
		if not self.CAN_DEFINE_EFFECTS:
			raise DisplayException("cannot define effect; a Coloring object already exists")
		self.effects.append((effect_on, effect_off))
		self._effects_bits = (self._effects_bits << 1) | 1
		return len(self.effects)-1

	def raw_num(self, pair_number):
		'''
		Get raw pair number, without respect to number of predefined ones.
		Use in conjunction with getColor or Coloring.insert_color to use
		predefined colors
		'''
		if pair_number < 0:
			raise DisplayException("raw numbers may not be below 0")
		return pair_number - self.predefined

	def two56(self, color, too_black=0.1, too_white=0.9, reweight=None):
		'''
		Convert a hex string, 3-tuple, or pre-calculated int to 256 color
		Returns `colors.default` if not running in 256 color mode
		'''
		if not self._two56:
			return self.default

		if isinstance(color, int):
			return self._two56_start + color
		if isinstance(color, float):
			raise TypeError("cannot interpret float as color number")

		if not color: #empty string
			return self.default

		try:
			if isinstance(color, str):
				if color.startswith("#"):
					color = color[1:]
				parts_len = len(color)//3
				rgbf = [int(color[i*parts_len:(i+1)*parts_len], 16)/\
					(16**parts_len) for i in range(3)]
			else:
				rgbf = [i/255 for i in color]

			avg = sum(rgbf)/3
			if callable(reweight):
				rgbf = reweight(rgbf)
			elif reweight is not None:
				rgbf = self.reweight(rgbf)
			#too white or too black
			elif avg < too_black or avg > too_white:
				return self.default

			if sum((i - avg)**2 for i in rgbf)**0.5 < 0.05:
				return self.grayscale(int(avg*24))

			return self._two56_start + 16 + \
				sum(map(lambda x, y: int(x*5)*y, rgbf, [36, 6, 1]))
		except (AttributeError, TypeError):
			return self.default

	@staticmethod
	def reweight(rgbf):
		avg = sum(rgbf) / 3
		rew = lambda x, y: [i*j for i, j in zip(x, y)]

		if avg < 0.1:
			rgbf = rew(rgbf, [1.25, 1.25, 1.25])
		elif avg > 0.9:
			rgbf = rew(rgbf, [0.75, 0.75, 0.75])
		avg = sum(rgbf) / 3
		unblueness = sum(rgbf) - rgbf[2]
		if abs(unblueness - avg) < 5e-3: #dark blue admixtures
			rgbf = rew(rgbf, [1.20, 1.20, 1.10])
		elif unblueness < 0.15: #VERY blue colors
			if rgbf[2] < 0.35:
				rgbf = [0.2, 0.2, 0.6] #this is a bad color, but it's the best I can do
			else:
				rgbf[1] = rgbf[2]/4
		return rgbf

	def grayscale(self, color):
		'''Gets a 256-color grayscale `color` from 0 (black) to 24 (white)'''
		color = min(max(color, 0), 24)
		return self.two56(color + 232) #magic, but whatever
colors = _ColorManager() #pylint: disable=invalid-name

class Box:
	'''
	Virtual class containing useful box shaping characters.
	Subclasses must have `width` property, like Overlays
	'''
	CHAR_HSPACE = '─'
	CHAR_VSPACE = '│'
	CHAR_TOPL = '┌'
	CHAR_TOPR = '┐'
	CHAR_BTML = '└'
	CHAR_BTMR = '┘'

	def box_just(self, string, justchar=' '):
		'''Pad string by column width'''
		if not hasattr(self, "width"):
			raise DisplayException("cannot get width of Box %s" % self.__name__)
		return string + justchar*(self.width-2-collen(string))

	def box_format(self, left, string, right, justchar=' '):
		'''Format and justify part of box'''
		return "{}{}{}".format(left, self.box_just(string, justchar), right)

	def box_noform(self, string):
		'''Returns a string in the sides of a box. Does not pad spaces'''
		return self.CHAR_VSPACE + string + self.CHAR_VSPACE

	def box_part(self, fmt=''):
		'''Returns a properly sized string of the sides of a box'''
		return self.box_format(self.CHAR_VSPACE, fmt
			, self.CHAR_VSPACE)

	def box_top(self, fmt=''):
		'''Returns a properly sized string of the top of a box'''
		return self.box_format(self.CHAR_TOPL, fmt, self.CHAR_TOPR
			, self.CHAR_HSPACE)

	def box_bottom(self, fmt=''):
		'''Returns a properly sized string of the bottom of a box'''
		return self.box_format(self.CHAR_BTML, fmt, self.CHAR_BTMR
			, self.CHAR_HSPACE)

class Coloring:
	'''Container for a string and coloring to be done'''
	def __init__(self, string, remove_fractur=True):
		colors.CAN_DEFINE_EFFECTS = False #pylint: disable=invalid-name
		self._str = ""
		self._positions = []
		self._formatting = []
		self._maxpos = -1
		self.setstr(string, False, remove_fractur)

	def __hash__(self):
		'''Base hash on internal parameters only, to make memoization easier'''
		return hash((self._str
			, frozenset(self._positions), frozenset(self._formatting)))

	def clear(self):
		'''Clear all positions and formatting'''
		self._maxpos = -1
		self._positions.clear()
		self._formatting.clear()

	def setstr(self, new, clear=True, remove_fractur=True):
		'''
		Set contained string to something new, clearing formatting if `clear`
		`new` can be a (str, color) tuple to instantly add a color
		'''
		if clear:
			self.clear()
		color = None
		if isinstance(new, tuple):
			new, color = new #extract a color
		if remove_fractur:
			new = _parse_fractur(new)
		self._str = new
		if color is not None:
			self.insert_color(0, color)

	def __add__(self, other):
		if isinstance(other, str):
			self._str += other
			return self
		if not isinstance(other, Coloring):
			raise TypeError("Cannot concat non-Coloring to Coloring")
		if other._positions and other._positions[0]+len(self._str) == self._maxpos:
			final = self._formatting.pop()
			other._formatting[0] ^= final & colors._effects_bits
			self._positions.pop()
			self._maxpos = len(self._str) + other._maxpos
		self._formatting.extend(other._formatting)
		self._positions.extend((pos+len(self._str) for pos in other._positions))
		self._str += other._str
		return self

	def __repr__(self):
		return "<{} string = {}, positions = {}, formatting = {}>".format(
			str(type(self)), repr(self._str), self._positions, self._formatting)

	def __str__(self):
		'''Get the string contained'''
		return self._str

	def __bool__(self):
		'''Test for emptiness'''
		return bool(self._str)

	def __format__(self, *args):
		'''Colorize the string'''
		ret = ""
		tracker = 0
		last_effect = 0
		for pos, form in zip(self._positions, self._formatting):
			color = form >> len(colors.effects)
			next_effect = form & colors._effects_bits
			ret += self._str[tracker:pos] + \
				colors._continue_formatting(color, last_effect, next_effect)
			tracker = pos
			last_effect ^= next_effect
		ret += self._str[tracker:]
		return ret + CLEAR_FORMATTING

	def sub_slice(self, sub, start, end=None):
		'''
		Overwrite rest of string at position `start`; optionally end overwrite
		at position `end`. Basically works as slice assignment.
		'''
		if start < 0:
			start = max(0, start+len(self._str))
		pos = 0
		for pos, i in enumerate(self._positions):
			if i >= start:
				break
		self._positions = self._positions[:pos]
		self._formatting = self._positions[:pos]

		if end:
			if end < 0:
				end	= max(0, len(self._str))
			for pos, i in enumerate(self._positions):
				if i > start:
					self._positions[pos] = i + len(sub)
			last = self.find_color(start) or colors.default
			self._insert_color(end, last)
			self._str = self._str[:start] + sub + self._str[end:]
			return
		self._str = self._str[:start] + sub

	def colored_at(self, position):
		'''return a bool that represents if that position is colored yet'''
		return position in self._positions

	def _insert_color(self, position, formatting):
		'''insert_color backend that doesn't do sanity checking on formatting'''
		if position > self._maxpos:
			self._positions.append(position)
			self._formatting.append(formatting)
			self._maxpos = position
			return
		i = 0
		while position > self._positions[i]:
			i += 1
		if self._positions[i] == position:		#position already used
			effect = self._formatting[i] & colors.effects_bits
			self._formatting[i] = formatting | effect
		else:
			self._positions.insert(i, position)
			self._formatting.insert(i, formatting)

	def insert_color(self, position, formatting):
		'''
		Insert positions/formatting into color dictionary
		formatting must be a proper color (in `colors`, added with `def_color`)
		'''
		if position < 0:
			position = max(position+len(self._str), 0)
		formatting += colors.predefined + 1
		formatting <<= len(colors.effects)
		self._insert_color(position, formatting)

	def effect_range(self, start, end, formatting):
		'''
		Insert an effect at _str[start:end]
		`formatting` must be a number corresponding to an `effect`
		'''
		if start < 0:
			start = len(self._str) + start
		if not end or end <= 0:
			end = len(self._str) + int(end if end is not None else 0)
		if start >= end:
			return

		effect = 1 << formatting
		if start > self._maxpos:
			self._positions.append(start)
			self._formatting.append(effect)
			self._positions.append(end)
			self._formatting.append(effect)
			self._maxpos = end
			return
		i = 0
		while start > self._positions[i]:
			i += 1
		if self._positions[i] == start:	#if we're writing into a number
			self._formatting[i] |= effect
		else:
			self._positions.insert(i, start)
			self._formatting.insert(i, effect)
		i += 1

		while i < len(self._positions) and end > self._positions[i]:
			if self._formatting[i] & effect: #if this effect turns off here
				self._formatting[i] ^= effect
			i += 1
		if end > self._maxpos:
			self._positions.append(end)
			self._formatting.append(effect)
			self._maxpos = end
		#position exists
		elif self._positions[i] == end:
			self._formatting[i] |= effect
		else:
			self._positions.insert(i, end)
			self._formatting.insert(i, effect)

	def add_global_effect(self, effect_number, pos=0):
		'''Add effect to string'''
		self.effect_range(pos, len(self._str), effect_number)

	def find_color(self, end):
		'''Most recent color before end. Safe when no matches are found'''
		if self._maxpos == -1:
			return None
		if end > self._maxpos:
			return self._formatting[-1] & ~colors.effects_bits #ignore the formatting
		last = self._formatting[0]
		effects = 0
		for pos, form in zip(self._positions, self._formatting):
			effects ^= form & colors.effects_bits
			if end < pos:
				return last
			last = (form & ~colors.effects_bits) | effects
		return last

	def color_by_regex(self, regex, group_func, fallback=None, group=0):
		'''
		Color from a compiled regex, generating the respective color number
		from captured group. group_func should be an int or callable that
		returns int
		'''
		if not callable(group_func):
			ret = group_func	#get another ref to prevent recursion
			group_func = lambda x: ret
		# only get_last when supplied a color number fallback
		get_last = False
		if isinstance(fallback, int):
			get_last = True

		for find in regex.finditer(self._str):
			begin = find.start(group)
			end = find.end(group)
			# insert the color
			if get_last:
				# find the most recent color
				last = self.find_color(begin)
				last = fallback if last is None else last
				self.insert_color(begin, group_func(find.group(group)))
				# backend because last is already valid
				self._insert_color(end, last)
			else:
				self.insert_color(begin, group_func(find.group(group)))

	def effect_by_regex(self, regex, effect, group=0):
		for find in regex.finditer(self._str+' '):
			self.effect_range(find.start(group), find.end(group), effect)

	def breaklines(self, length, outdent="", keep_empty=True): #pylint: disable=too-many-locals
		'''
		Break string (courteous of spaces) into a list of strings spanning up
		to `length` columns. If there are empty lines (i.e. two newlines in a
		row), `keep_empty` preserves them as such (default True)
		'''
		broken, line_buffer = [], ""  #list to return, last pre-broken line
		outdent_len = collen(outdent) #cache the length of the outdent

		start = 0	#last index to append from
		lastcol, space = 0, length	#remaining columns: at "good" position, total

		format_pos, get_format = 0, bool(self._positions) #formatting iterators
		last_color, last_effect = 0, 0	#last color/effect; continue after break
		#character by character, the old fashioned way
		for pos, (j, lenj) in enumerate(map(lambda x: (x, wcwidth(x)), self._str)):
			#if we have a 'next color', and we're at that position
			if get_format and pos == self._positions[format_pos]:
				line_buffer += self._str[start:pos]
				start = pos
				#decode the color/effect
				last_color = (self._formatting[format_pos] >> len(colors.effects)) \
					or last_color
				next_effect = self._formatting[format_pos] & colors._effects_bits
				format_pos += 1
				get_format = format_pos != len(self._positions)
				#do we even need to draw this?
				if space > 0:
					line_buffer += colors._continue_formatting(last_color
						, last_effect, next_effect)
				#effects are turned off and on by the same bit
				last_effect ^= next_effect
			if j == '\t':
				#tabs are the length of outdents; pad out spaces
				lenj = outdent_len
				line_buffer += self._str[start:pos] + ' '*min(lenj, space)
				start = pos+1
			elif j in ('\r', '\n'):
				if keep_empty or space != length - outdent_len:
					#add in a space to preserve string position
					broken.append(line_buffer + self._str[start:pos] + ' ' + \
						CLEAR_FORMATTING)
				#refresh variables
				line_buffer = outdent + \
					colors._continue_formatting(last_color, 0, last_effect)
				start = pos+1
				#remove outdent from space left
				lastcol, space = 0, length - outdent_len
				continue
			elif ord(j) < 32:		#other non printing
				continue

			space -= lenj
			#if this is a line breaking character and we have room just after it
			if j in _LINE_BREAKING and space > 0:
				#add the last word
				line_buffer += self._str[start:pos+1]
				start = pos+1
				lastcol = space
			if space <= 0:			#time to break
				#do we have a 'last space (breaking char)' recent enough to split after?
				if 0 < lastcol < (length >> 1):
					broken.append(line_buffer + CLEAR_FORMATTING)
					line_buffer = outdent + colors._continue_formatting(last_color
						, 0, last_effect)
					lenj += lastcol
				#split on a long word
				else:
					broken.append(line_buffer + self._str[start:pos] + \
						CLEAR_FORMATTING)
					line_buffer = outdent + colors._continue_formatting(last_color
						, 0, last_effect)
					start = pos
				lastcol = 0
				#tab space minus this next character
				space = length - outdent_len - lenj

		#empty the buffer one last time
		line_buffer += self._str[start:]
		if keep_empty or space != length - outdent_len + collen(self._str[start:]):
			broken.append(line_buffer+CLEAR_FORMATTING)

		return broken

class JustifiedColoring(Coloring):
	'''
	Coloring object fitted to a certain column length.
	Can add indicator lamps and shorten strings with ellipses.
	'''
	_ELLIPSIS = '…'
	def __init__(self, string, remove_fractur=True):
		super().__init__(string, remove_fractur)
		self._indicator = None
		self._memoargs = None
		self._rendered = None

	indicator = property(lambda self: self._indicator[0] \
		if self._indicator is not None else "")

	def __hash__(self):
		'''Include indicator in memoize hash'''
		return hash((self._str, self._indicator
			, frozenset(self._positions), frozenset(self._formatting)))

	def __eq__(self, other):
		return isinstance(other, JustifiedColoring) \
			and (hash(self) == hash(other))

	def __bool__(self):
		'''Test for emptiness'''
		return bool(self._indicator or self._str)

	def add_indicator(self, sub: str, color=None, effect=None):
		'''
		Replace some spaces at the end of a string. Optionally inserts a color
		for the string `sub`. Useful for ListOverlays.
		'''
		if sub == "":
			return
		formatting = ""
		try:
			formatting += colors.colors[color + colors.predefined]
		except (TypeError, IndexError):
			pass
		try:
			formatting += colors.effects[effect][0]
		except (TypeError, IndexError):
			pass
		self._indicator = (sub, formatting)

	def _justify(self, half_width):
		'''
		Backend for justify that does the parsing of `positions` and `formatting`
		Adds the ellipsis and or leaves the string alone
		'''
		if not self._str:
			return "", 0

		#try slicing the right half of the string short enough
		right = len(self._str) + 1 - \
			columnslice(reversed(self._str), floor(half_width))
		places = list(zip(self._positions, self._formatting))

		#test if we have a suitably short string and just put them out of range
		if right <= len(self._str) // 2 + 1:
			left = len(self._str) + 1
			right = left
		#furthest slice index of the left half of the string
		#if we don't have an odd split which we can insert the ellipsis into
		else:
			left = columnslice(self._str, ceil(half_width))
			i = sum(1 for i in self._positions if i < left)
			form = 0
			places.insert(i, (left, None))
			while i < len(self._positions) and self._positions[i] < right:
				form = places[i]
				i += 1
			places.insert(i+1, (right, form))

		#slightly altered format-style loop
		ret = ""
		tracker = 0
		last_effect = 0
		running_length = 0

		for pos, form in places:
			if form is None:
				#signal to begin omitting stuff
				temp = self._str[tracker:left] + self._ELLIPSIS
				ret += temp
				running_length += collen(temp)
				continue
			if left < pos < right:
				continue

			next_effect = form & colors.effects_bits
			#but if we're back out of the woods
			if not tracker < right == pos:
				temp = self._str[tracker:pos]
				running_length += collen(temp)
				ret += temp
			ret += colors._continue_formatting(form >> len(colors.effects)
				, last_effect, next_effect)

			tracker = pos
			last_effect ^= next_effect

		temp = self._str[tracker:]
		#the string and the unused length
		return ret + temp, collen(temp) + running_length

	def justify(self, length, justchar=' ', ensure_indicator=2):
		'''Justify string to `length` columns and add indicator'''
		#quick memoization
		new_hash = hash((self, length, justchar, ensure_indicator))
		if self._memoargs == new_hash:
			return self._rendered

		sub, color, columns = None, None, 0
		if self._indicator is None:
			ensure_indicator = 0
		else:
			sub, color = self._indicator
			columns = collen(sub)
			ensure_indicator = min(ensure_indicator, columns)
		display, room = self._justify((length - ensure_indicator) / 2)
		#number of columns allowed to the indicator
		room = length - room

		indicator = ""
		if ensure_indicator:
			#trim if too many columns
			if columns > ensure_indicator:
				final_column = columnslice(sub, room-2)
				if final_column < len(sub):
					sub = sub[:final_column] + self._ELLIPSIS
				else:
					sub = sub[:final_column]
				columns = collen(sub)

			indicator = color + sub
			#room indicates how many spaces to add; so this should be accurate
			room -= columns

		self._memoargs = new_hash
		self._rendered = display + (justchar * room) + indicator + CLEAR_FORMATTING
		return self._rendered

#SCROLLABLE CLASSES-------------------------------------------------------------
class Scrollable:
	'''Scrollable text input'''
	MAX_NONSCROLL_WIDTH = 5 #arbitrary maximum prefix length
	_TABLEN = 4

	def __init__(self, width, string=""):
		if width <= self._TABLEN:
			raise DisplayException("Cannot create Scrollable smaller "\
				" or equal to tab width %d"%self._TABLEN)
		self._str = string.replace('\x7f', "")
		self._width = width
		#position of the cursor and display column of the cursor
		self._pos = len(string)
		self._disp = max(0, collen(string)-width)
		#nonscrolling characters
		self._nonscroll = ""
		self._nonscroll_width = 0

	def __repr__(self):
		return f"{type(self)}({self._width}, {repr(self._str)})"

	def __str__(self):
		'''Return the raw text contained'''
		return self._str

	def show(self, password=False):
		'''Display text contained with cursor'''
		#sometimes our self._disp gets off
		self._disp = min(self._disp, len(self._str))
		#iteration variables
		start, end, width = self._disp, self._disp, self._nonscroll_width
		#handle the first test already, +1 for truth values
		endwidth = (end == self._pos) and width+1
		lentext = len(self._str)
		#adjust the tail
		while not endwidth or (width < self._width and end < lentext):
			char = self._str[end]
			if char == '\t':
				width += self._TABLEN
			elif char in ('\n', '\r'):
				width += 2	#for r'\n'
			elif ord(char) >= 32:
				width += wcwidth(char)
			end += 1
			if end == self._pos:
				endwidth = width+1
		#adjust the head
		while width >= self._width:
			char = self._str[start]
			if char == '\t':
				width -= self._TABLEN
			elif char in ('\n', '\r'):
				width -= 2	#for \n
			elif ord(char) >= 32:
				width -= wcwidth(char)
			start += 1
		if password:
			if not endwidth: #cursor is at the end
				endwidth = self._width
			else:
				endwidth -= 1
			return self._nonscroll+('*'*endwidth)+CHAR_CURSOR+\
				('*'*(width-endwidth))
		text = self._nonscroll+self._str[start:self._pos]+\
			CHAR_CURSOR+self._str[self._pos:end]
		#actually replace the lengths I asserted earlier
		return text.replace('\n', '\\n').replace('\r',
			'\\r').replace('\t', ' '*self._TABLEN)
	#SET METHODS----------------------------------------------------------------
	def _onchanged(self):
		'''Useful callback to retreive a new 'good' slice of a string'''

	def setstr(self, new):
		'''Set content of scrollable'''
		self._str = new.replace('\x7f', "")
		self.end()

	def setnonscroll(self, new):
		'''Set nonscrolling characters of scrollable'''
		check = collen(new)
		if check > self.MAX_NONSCROLL_WIDTH:
			new = new[:columnslice(new, self.MAX_NONSCROLL_WIDTH)]
		self._nonscroll = new
		self._nonscroll_width = min(check, self.MAX_NONSCROLL_WIDTH)
		self._onchanged()

	def setwidth(self, new):
		'''Set width of the scrollable'''
		if new <= 0:
			raise DisplayException()
		self._width = new
		self._onchanged()

	#TEXTBOX METHODS-----------------------------------------------------------
	def movepos(self, dist):
		'''Move cursor by distance (can be negative). Adjusts display position'''
		if not self._str:
			self._pos, self._disp = 0, 0
			self._onchanged()
			return
		self._pos = max(0, min(len(self._str), self._pos+dist))
		curspos = self._pos - self._disp
		if curspos <= 0: #left hand side
			self._disp = max(0, self._disp+dist)
		elif (curspos+1) >= self._width: #right hand side
			self._disp = min(self._pos-self._width+1, self._disp+dist)
		self._onchanged()

	def home(self):
		'''Move cursor to the beginning'''
		self._pos = 0
		self._disp = 0
		self._onchanged()

	def end(self):
		'''Move cursor to the end'''
		self._pos = 0
		self._disp = 0
		self.movepos(len(self._str))

	def wordback(self):
		'''Go back to the last word'''
		pos = _UP_TO_WORD_RE.match(' '+self._str[:self._pos])
		if pos:
			#`_UP_TO_WORD_RE`'s first group begins where the last word does
			#use movepos to maintain display offset of 1 b/c space
			self.movepos(pos.end(1)-self._pos-1)
		else:
			self.home()

	def wordnext(self):
		'''Advance to the next word'''
		pos = _NEXT_WORD_RE.match(self._str[self._pos:]+' ')
		if pos:
			#move forward the length of the captured word
			self.movepos((lambda x, y: y - x)(*pos.span(1)))
		else:
			self.end()

	#CHARACTER INSERTION--------------------------------------------------------
	def append(self, new):
		'''Append string at cursor'''
		self._str = self._str[:self._pos] + new.replace('\x7f', "") + \
			self._str[self._pos:]
		self.movepos(len(new))

	#CHARACTER DELETION METHODS-------------------------------------------------
	def backspace(self):
		'''Backspace one char at cursor'''
		#don't backspace at the beginning of the line
		if not self._pos:
			return
		self._str = self._str[:self._pos-1] + self._str[self._pos:]
		self.movepos(-1)

	def delchar(self):
		'''Delete one char ahead of cursor'''
		self._str = self._str[:self._pos] + self._str[self._pos+1:]
		self._onchanged()

	def delword(self):
		'''Delete word behind cursor, like in sane text boxes'''
		pos = _UP_TO_WORD_RE.match(' '+self._str[:self._pos])
		if pos:
			#we started with a space
			span = pos.end(1) - 1
			#how far we went
			self._str = self._str[:span] + self._str[self._pos:]
			self.movepos(span-self._pos)
		else:
			self._str = self._str[self._pos:]
			self._disp = 0
			self._pos = 0
			self._onchanged()

	def delnextword(self):
		'''Delete word ahead of cursor, like in sane text boxes'''
		pos = _NEXT_WORD_RE.match(self._str[self._pos:]+' ')
		if pos:
			span = pos.end(1)
			#how far we went
			self._str = self._str[:self._pos] + self._str[self._pos+span:]
		else:
			self._str = self._str[:self._pos]
		self._onchanged()

	def clear(self):
		'''Clear cursor and string'''
		self._str = ""
		self.home()

class ScrollSuggest(Scrollable): #pylint: disable=too-many-instance-attributes
	'''
	A Scrollable extension with suggestion-based completion from Sigils.
	If you need to extend a Scrollable, it's probably this one
	'''
	def __init__(self, width, string=""):
		super().__init__(width, string)
		#completer
		self._suggest_list = []
		self._suggest_index = 0
		self._clear_suggest = False
		#storage vars
		self._lastdisp = None
		self._lastpos = None		#position of last word tabbed

	def _onchanged(self):
		'''Get rid of stored suggestions'''
		if self._clear_suggest:
			self._suggest_index = -1
			self._suggest_list.clear()
			self._lastpos, self._lastdisp = None, None
		self._clear_suggest = True

	def _splitwords(self):
		'''split words up to current cursor position'''
		ret = []
		buffer = ""
		last_word_pos = 0
		for pos, char in enumerate(self._str):
			if pos >= self._pos:
				break
			buffer += char
			if char in _LINE_BREAKING:
				ret.append(buffer)
				last_word_pos = pos+1
				buffer = ""
				continue
		ret.append(buffer)
		self._lastpos = last_word_pos
		return ret

	def complete(self, completer: Sigil):
		'''Tab forward in suggestions'''
		#need to generate list
		if not self._suggest_list:
			#get word list up until current string position
			wordlist = self._splitwords()
			adjust, self._suggest_list = completer.complete(wordlist)
			#adjust display position
			self._lastpos += adjust
			self._lastdisp = max(0, self._disp - (self._pos - self._lastpos))
			self._suggest_index = -1
		return self._complete(1)

	def backcomplete(self):
		'''Tab backward in suggestions'''
		return self._complete(-1)

	def _complete(self, direction):
		if self._suggest_list:
			sliced = self._str[:self._lastpos]
			suffix = self._str[self._pos:]
			#modify suggestion
			if len(self._suggest_list) > 1:
				self._suggest_index += direction
				self._suggest_index %= len(self._suggest_list)
			self._clear_suggest = False
			suggestion = self._suggest_list[self._suggest_index]
			#adjust string and display
			self._pos = self._lastpos
			self._disp = self._lastdisp
			self._str = sliced + suggestion + suffix
			self.movepos(len(suggestion))
			return True
		return False
