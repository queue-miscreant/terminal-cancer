#!/usr/bin/env python3
#util.py
'''
Module for miscellaneous classes that are not inherently overlay or display
oriented. Also contains keypress-handling callback framework.
'''
import os
from os import path
import curses
import inspect
import asyncio
from functools import partial as partial_apply

__all__ = ["staticize", "KeyException", "KeyContainer", "key_handler"
	, "Sigil", "argsplit", "argunsplit", "tab_file"
	, "History", "LazyIterList"]

def numdrawing(string, width=-1):
	'''
	Number of drawing characters in the string (up to width).
	Ostensibly the number of non-escape sequence characters
	'''
	if not width:
		return 0
	escape = False
	ret = 0
	for i in string:
		temp = (i == '\x1b') or escape
		#not escaped and not transitioning to escape
		if not temp:
			ret += 1
			if ret == width:
				return ret
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return ret

#HANDLER-HELPER FUNCTIONS-------------------------------------------------------
def staticize(func, *args, doc=None, **kwargs):
	'''functools.partial, but conserves or adds documentation'''
	ret = partial_apply(func, *args, **kwargs)
	ret.__doc__ = doc or func.__doc__
	return ret

class KeyException(Exception):
	'''Exception caught in `Screen.input` to capture failed keypresses'''

#Key setup
class KeyContainer:
	'''Object for parsing key sequences and passing them onto handlers'''
	_VALID_KEYNAMES = {
		  "tab":		9
		, "enter":		10
		, "backspace":	127
	}
	#these keys point to another key
	_KEY_LUT = {
		  curses.KEY_BACKSPACE:	127		#undo curses ^h redirect
		, curses.KEY_ENTER:		10		#numpad enter
		, 13:					10		#CR to LF, but curses does it already
	}
	MOUSE_MASK = 0
	_MOUSE_BUTTONS = {	#curses.getch with nodelay tends to hang on PRESSED
		  "left":		curses.BUTTON1_RELEASED
		, "middle":		curses.BUTTON2_RELEASED
		, "right":		curses.BUTTON3_RELEASED
		, "wheel-up":	curses.BUTTON4_PRESSED #mouse wheel is fine, though
		, "wheel-down":	2**21
	}
	_MOUSE_ERROR = "expected signature ({0}, x, y) or ({0}) from function '{1}'"
	_last_mouse = None	#curses.ungetmouse but not broken

	@classmethod
	def initialize_class(cls):
		for curse_name in dir(curses):
			if "KEY_" not in curse_name \
			or curse_name in ("KEY_RESIZE", "KEY_MOUSE"):
				continue
			better_name = curse_name[4:].lower()
			if better_name == "dc":
				better_name = "delete"
			if better_name not in cls._VALID_KEYNAMES: #no remapping keys
				cls._VALID_KEYNAMES[better_name] = getattr(curses, curse_name)

		#simple command key names
		for no_print in range(32):
			#correct keynames for ^@ and ^_ (\x00 and \x1f), lowercase otherwise
			cls._VALID_KEYNAMES["^%s" % (chr(no_print+64).lower())] = no_print
		for print_char in range(32, 127):
			cls._VALID_KEYNAMES[chr(print_char)] = print_char
		for mouse_button in cls._MOUSE_BUTTONS.values():
			cls.MOUSE_MASK |= mouse_button

	def __init__(self):
		self._keys = { #strange because these are the opposite of defaults, but these are special
			27:						self._BoundKey(self._callalt, True)
			, curses.KEY_MOUSE:		self._BoundKey(self._callmouse, True)
		}
		self._altkeys = {}
		self._mouse = {}

	def screen_keys(self, screen):
		'''Bind control keys to a screen ^l, resize'''
		self._keys.update({
			12:						self._BoundKey(screen.redraw_all) #^l
			, curses.KEY_RESIZE:	self._BoundKey(screen.schedule_resize)
		})

	def __call__(self, chars, *args, do_input=True, raise_=True): #pylint: disable=inconsistent-return-statements
		'''
		Run a key's callback. This expects a single argument: a list of numbers
		terminated by -1. Subsequent arguments are passed to the key handler.
		Raises KeyException if there is no handler, otherwise propagates
		handler's return
		'''
		try:
			char = self._KEY_LUT[chars[0]]
		except KeyError:
			char = chars[0]

		#capture keys that are handled and (escaped, short, or curses remapped)
		if char in self._keys \
		and (char == 27 or len(chars) <= 2 or char > 255):
			#include trailing -1
			return self._keys[char](chars[1:] or [-1], *args)
		#capture the rest of inputs, as long as they begin printable
		if do_input and -1 in self._keys \
		and (char in range(32, 255) or char in (9, 10)):
			return self._keys[-1](chars[:-1], *args)
		if raise_:
			raise KeyException

	def _callalt(self, *args):
		'''Run a alt-key's callback'''
		chars = args[-1]
		if not chars[0] in self._altkeys:
			raise KeyException
		return self._altkeys[chars[0]](chars, *args[:-1])

	def _callmouse(self, *args):
		'''Run a mouse's callback. Saves invalid mouse data for next call'''
		chars = [i for i in args[-1] if i != curses.KEY_MOUSE]
		args = args[:-1]
		if chars[0] != -1:
			#control not returned to loop until later
			asyncio.get_event_loop().call_soon(
				partial_apply(self, chars, *args, raise_=False))
		try:
			if self._last_mouse is not None:
				x, y, state = self._last_mouse	#pylint: disable=unpacking-non-sequence
				KeyContainer._last_mouse = None
			else:
				_, x, y, _, state = curses.getmouse()
			error_sig = "..."
			if state not in self._mouse:
				if -1 not in self._mouse:
					KeyContainer._last_mouse = (x, y, state)
					raise KeyException
				error_sig = "..., state"
				args = (*args, state)
				state = -1
			try:
				return self._mouse[state](chars, *args, x, y)
			except TypeError:
				return self._mouse[state](chars, *args)
		except TypeError as exc:
			raise TypeError(self._MOUSE_ERROR.format(error_sig
				, self._mouse[state])) from exc
		except curses.error:
			pass
		raise KeyException

	def __dir__(self):
		'''Get a list of key handlers and their documentation'''
		ret = []
		for i, j in self._VALID_KEYNAMES.items():
			#ignore named characters and escape, they're not verbose
			if i in ("^[", "^i", "^j", chr(127), "mouse"):
				continue
			if i == ' ':
				i = "space"
			doc_string = ""
			format_string = ""
			if j in self._keys:
				doc_string = self._keys[j].doc
				format_string = "{}: {}"
			elif j in self._altkeys:
				doc_string = self._altkeys[j].doc
				format_string = "a-{}: {}"
			else:
				continue
			ret.append(format_string.format(i, doc_string))
		return ret

	def _get_key(self, key_name):
		'''Retrieve list reference and equivalent value'''
		#straight integers
		if isinstance(key_name, int):
			return self._keys, key_name
		if key_name.lower() == "mouse":
			return self._mouse, -1

		ret_list = self._keys
		true_name = key_name
		lookup = self._VALID_KEYNAMES
		#alt buttons
		if key_name.startswith("a-"):
			ret_list = self._altkeys
			true_name = key_name[2:]
		#mouse buttons
		elif key_name.startswith("mouse-"):
			ret_list = self._mouse
			true_name = key_name[6:]
			lookup = self._MOUSE_BUTTONS
		try:
			true_name = lookup[true_name]
		except KeyError:
			raise ValueError(f"key {repr(key_name)} invalid")
		return ret_list, true_name

	def __getitem__(self, other):
		list_ref, name = self._get_key(other)
		return list_ref[name]

	def __delitem__(self, other):
		list_ref, name = self._get_key(other)
		del list_ref[name]

	def __contains__(self, other):
		'''
		Returns whether this object can handle running the key `other`
		Can be either a list of characters or the formal name of a key
		'''
		if isinstance(other, list):
			try:
				char = self._KEY_LUT[other[0]]
			except KeyError:
				char = other[0]

			#alt escapes
			if char == 27:
				return other[1] in self._altkeys
			printing = char in range(32, 255) or char in (9, 10)
			return char in self._keys or (-1 in self._keys and printing)

		list_ref, key_name = self._get_key(other)
		return key_name in list_ref

	def mouse(self, *args, state, x=0, y=0):
		'''Unget some mouse data and run the associated mouse callback'''
		KeyContainer._last_mouse = (x, y, state)
		try:
			return self._callmouse(*args, [-1])
		except KeyException:
			KeyContainer._last_mouse = None
		raise KeyException

	def nomouse(self):
		'''Unbind the mouse from _keys'''
		if curses.KEY_MOUSE in self._keys:
			del self._keys[curses.KEY_MOUSE]

	def noalt(self):
		'''Unbind alt keys'''
		if 27 in self._keys:
			del self._keys[27]

	@classmethod
	def clone_key(cls, old, new):
		'''Redirect one key to another. DO NOT USE FOR VALUES IN range(32,128)'''
		try:
			if isinstance(old, str):
				old = cls._VALID_KEYNAMES[old]
			if isinstance(new, str):
				new = cls._VALID_KEYNAMES[new]
		except KeyError:
			raise ValueError("%s or %s is an invalid key name"%(old, new))
		cls._KEY_LUT[old] = new

	class _BoundKey:
		'''
		Function wrapper for key handler. If a handler should receive extra
		keypresses recorded, `pass_keys` is True. Return value is overridden if
		`return_val` is not None. Documentation is overriden to `doc`
		'''
		def __init__(self, func, pass_keys=False, return_val=None, doc=None):
			self._func = func
			self._nullary = not inspect.signature(func).parameters
			self._pass_keys = not self._nullary and pass_keys
			self._return = return_val
			self.doc = inspect.getdoc(self._func) if doc is None else doc
			if self.doc is None:
				self.doc = "(no documentation)"
			else:
				if return_val == 0:
					self.doc += " (keeps overlay open)"
				elif return_val == -1:
					self.doc += " (and close overlay)"

		def __call__(self, keys, *args):
			args = tuple() if self._nullary else args
			ret = self._func(*args, keys) if self._pass_keys else self._func(*args)
			return ret if self._return is None else self._return

		def __eq__(self, other):
			return other == self._func

		def __repr__(self):
			return f"BoundKey({repr(self._func)}) at {hex(id(self))}"

	def add_key(self, key_name, func, pass_keys=False, return_val=None, doc=None): #pylint: disable=too-many-arguments
		'''Key addition that supports some nicer names than ASCII numbers'''
		if not isinstance(func, self._BoundKey):
			func = self._BoundKey(func, pass_keys, return_val, doc)

		list_ref, name = self._get_key(key_name)
		list_ref[name] = func
KeyContainer.initialize_class()

class key_handler: #pylint: disable=invalid-name
	'''
	Function decorator for key handlers. `key_name` must be one of: a raw
	character number, a valid keyname, a-[keyname] for Alt combination,
	^[keyname] for Ctrl combination, or mouse-{right, left...} for mouse.
	Valid keynames are found in KeyContainer._VALID_KEYNAMES; usually curses
	KEY_* names, without KEY_, or the string of length 1 typed.
	'''
	def __init__(self, key_name, override=None, doc=None, **kwargs):
		self.bound = None
		self.keys = [(key_name, override, doc, kwargs)]

	def __call__(self, func=None, *args, **kwargs):
		if func is None:
			return func(*args, **kwargs)
		if isinstance(func, key_handler):
			func.keys.extend(self.keys)
			return func
		self.bound = func
		return self

	def __repr__(self):
		return f"key_handler({self.keys}, {self.bound})"

	def bind(self, keys: KeyContainer, redefine=True):
		'''
		Bind function to `keys`. Function is partially called with extra kwargs
		specified, and if `override` is specified, returns that value instead
		'''
		for key_name, override, doc, keywords in self.keys:
			if not redefine and key_name in keys:
				continue
			try:
				bind = staticize(self.bound, **keywords)
				pass_keys = (key_name == -1) #pass keys only if -1 ("input")
				keys.add_key(key_name, bind, pass_keys, override, doc)
			except KeyError:
				print("Failed binding {} to {} ".format(key_name, self.bound))

quitlambda = KeyContainer._BoundKey(lambda: -1, doc="Close overlay") #pylint: disable=invalid-name

#CYCLICAL COMPLETION HELPERS----------------------------------------------------
class Sigil:
	'''
	Suggestion-generating class. Instances can add sigils and their
	corresponding completion lists (or list factories).
	The class itself has "global" sigils, which are valid across multiple
	instances, as well as "extra" completers.
	Global sigils can be added by `Sigil(sigil_name, [suggestion_list])`, and
	return a list of suggestions
	Extra completers can be added by `Sigil(extra_completer)`, and return a
	2-tuple of `(cursor_adjustment, suggestion_list)`
	'''
	_global_sigils = []		#sigils that are valid in all non-isolated text boxes
	_global_suggestions = []		#and their completers
	_extra_suggest = []		#if all sigils fail, then we need an extra suggestion
	def __init__(self, global_sigil=None, global_suggest=None):
		if global_sigil is not None:
			if global_suggest is not None:
				self.add_sigil(global_sigil, global_suggest, True)
				return
			if not callable(global_sigil):
				raise ValueError(f"Invalid argument to Sigil: {global_sigil}")
			self._extra_suggest.append(global_sigil)
			return
		self._sigils = []
		self._suggestions = []

	def add_sigil(self, sigil, suggestion, isglobal=False):
		'''
		Add a sigil and associated suggestion. Suggestion can be a list or
		list factory with signature (partial word[, word number])
		'''
		suggest = suggestion
		if not callable(suggestion):
			suggest = lambda x, y: suggestion
		else:
			numargs = len(inspect.signature(suggestion).parameters)
			if numargs == 1:
				suggest = lambda x, y: suggestion(x)
		suggest_list = lambda x, y: [i for i in suggest(x, y) if i.startswith(x)]

		#append to the global or local list
		if isglobal:
			self._global_sigils.append(sigil)
			self._global_suggestions.append(suggest_list)
		else:
			self._sigils.append(sigil)
			self._suggestions.append(suggest_list)

	def complete(self, wordlist):
		'''
		Based on wordlist, attempt to generate a suggestion list as well as a
		cursor position adjustment. Completion takes place in the order:
		local sigils -> global sigils -> extra suggestions
		The former two are supplied only with the last entry of wordlist, but
		extras are supplied with the entire wordlist.
		'''
		last_word = wordlist[-1]
		wordnum = len(wordlist) - 1
		for sigils, callbacks in [(self._sigils, self._suggestions),	#local suggestions
		(self._global_sigils, self._global_suggestions)]:				#global suggestios
			for sigil, callback in zip(sigils, callbacks):
				if last_word.startswith(sigil):
					return len(sigil), callback(last_word[len(sigil):], wordnum)
		#extra suggestions
		for callback in self._extra_suggest:
			suggestion = callback(wordlist)
			#unpack tuple
			if isinstance(suggestion, tuple):
				return suggestion
			#don't stop trying until we get a nonempty list
			if suggestion:
				return 0, suggestion
		return 0, []

class _Splitter:
	'''Class that holds some state for argsplit and argunsplit'''
	def __init__(self):
		self._single = False
		self._double = False
		self._escaping = False

	@classmethod
	def get_splitters(cls):
		temp = cls()
		return temp.argsplit, temp.argunsplit

	def clear(self):
		self._single = False
		self._double = False
		self._escaping = False

	def argsplit(self, string: str):
		'''shlex.split with  ', ", and \\, but insensitive to unmatched quotes'''
		ret = self._argsplit(string)
		self.clear()
		return ret

	def _argsplit(self, string):
		'''argsplit backend that saves flag state in members'''
		buffer = ""
		args = []
		for i in string:
			if self._escaping:
				self._escaping = False
				if self._single or self._double:
					i = '\\'
				buffer += i
				continue

			if i == '\\' and not (self._single or self._double):
				self._escaping = True
			elif i == "'" and not self._double: #only one quote flag at once
				self._single ^= True
			elif i == '"' and not self._single:
				self._double ^= True
			elif i == ' ' and not (self._single or self._double):
				args.append(buffer)
				buffer = ""
			else:
				buffer += i
		args.append(buffer)
		return args

	def argunsplit(self, wordlist):
		'''
		Convert a word list into an arg list. Entries of word lists still end
		with the splitting character, like spaces.
		'''
		if not wordlist:
			return [""], ""
		ret = []
		prefix = ""
		for wordnum, word in enumerate(wordlist):
			buffer_list = self._argsplit(word)
			buffer_list[0] = prefix + buffer_list[0]
			#coalesce escapes
			#also pop empty words besides the last one
			if self._escaping or self._single or self._double \
			or (not buffer_list[-1] and wordnum < len(wordlist)-1):
				prefix = buffer_list.pop()
			ret.extend(buffer_list)
		if prefix:
			ret.append(prefix)
		unclosed = self._single and '\'' or (self._double and '"' or "")
		self.clear()
		return ret, unclosed
argsplit, argunsplit = _Splitter.get_splitters() #pylint: disable=invalid-name

def tab_file(partial):
	'''A file tabbing utility for ScrollSuggest'''
	prefix, reduction = path.split(partial)
	try:
		directory = prefix
		if not directory or not directory[0] in "~/":
			directory = path.join(os.getcwd(), prefix)
		directory = path.expanduser(directory)
		ls_files = os.listdir(directory)
	except (NotADirectoryError, FileNotFoundError):
		return []

	ret = []
	for i in ls_files:
		#don't suggest hidden or nonmatching files
		if i.startswith('.') or not i.startswith(reduction):
			continue
		if path.isdir(path.join(directory, i)):
			i += '/'
		ret.append(path.join(prefix, i))

	return sorted(ret)

#LISTLIKE CLASSES---------------------------------------------------------------
class LazyIterList(list):
	'''
	List-like class that builds itself on top of an iterator and has memory
	of current location. If `step` is called at the end of stored values and
	the iterator is not exhausted, it extends itself.
	'''
	def __init__(self, it):
		super().__init__()

		self._iter = it
		self._pos = 0
		try:
			self.append(next(it))
		except StopIteration:
			raise TypeError("Exhausted iterator used in LazyIterList init")

	def step(self, step):
		'''
		Select something in the direction step (1 or -1)
		Returns the item in the direction of the step, or if unable, None
		'''
		if step == 1:
			#step forward
			if self._pos + 1 >= len(self):
				if self._iter:	#if the iterator is active
					try:
						self.append(next(self._iter))
					except StopIteration:
						#just in case the following doesn't activate the gc
						del self._iter
						self._iter = None
						return None
				else:
					return None
			self._pos += 1
			return self[self._pos]
		#step backward
		if step == -1:
			#at the beginning already
			if not self._pos:
				return None
			self._pos -= 1
			return self[self._pos]
		return None

class History:
	'''
	Container class for historical entries, similar to an actual shell
	'''
	def __init__(self, *args, size=50):
		self.history = list(args)
		self._selhis = 0
		self._size = size
		#storage for next entry, so that you can scroll up, then down again
		self.bottom = None

	def __repr__(self):
		return "History({})".format(repr(self.history))

	def nexthist(self, replace=""):
		'''Next historical entry (less recent)'''
		if not self.history:
			return ""
		if replace:
			if not self._selhis:
				#at the bottom, starting history
				self.bottom = replace
			else:
				#else, update the entry
				self.history[-self._selhis] = replace
		#go backward in history
		self._selhis += (self._selhis < (len(self.history)))
		#return what we just retrieved
		return self.history[-self._selhis]

	def prevhist(self, replace=""):
		'''Previous historical entry (more recent)'''
		if not self.history:
			return ""
		if replace and self._selhis: #not at the bottom already
			self.history[-self._selhis] = replace
		#go forward in history
		self._selhis -= (self._selhis > 0)
		#return what we just retreived
		return (self._selhis and self.history[-self._selhis]) or self.bottom or ""

	def append(self, new):
		'''Add new entry in history and maintain maximum size'''
		if not self.bottom:
			#not already added from history manipulation
			self.history.append(new)
		self.bottom = None
		self.history = self.history[-self._size:]
		self._selhis = 0
