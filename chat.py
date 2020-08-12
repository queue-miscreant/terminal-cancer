#!/usr/bin/env python3
#client/chat.py
'''Overlays that provide chatroom-like interfaces.'''
import time
import asyncio
import traceback
from collections import deque

from .display import SELECT_AND_MOVE, Box, collen, colors, Coloring
from .base import TextOverlay
from .util import numdrawing, key_handler, KeyException, KeyContainer, LazyIterList
from .linkopen import xclip
from .input import DisplayOverlay
__all__ = ["ChatOverlay", "Message", "add_message_scroller"]

class Message(Coloring):
	'''
	Virtual wrapper class around "Coloring" objects. Allows certain kinds of
	message objects (like those from a certain service) to have a standard
	colorizing method, without binding tightly to a ChatOverlay subclass
	'''
	INDENT = "    "
	KEEP_EMPTY = True
	_shown_class = -1
	subclasses = []		#list of subclasses
	subclass_keys = {}	#dict of keys
	msg_count = 0
	def __init__(self, msg, remove_fractur=True, **kwargs):
		super().__init__(msg, remove_fractur)
		self.__dict__.update(kwargs)
		if hasattr(self, "_examine"):
			for examiner in self._examine:
				examiner(self)

		self._mid = Message.msg_count
		#memoization
		self._cached_display = []
		self._cached_hash = -1	#hash of coloring
		self._cached_width = 0	#screen width
		self._last_recolor = -1
		Message.msg_count += 1

	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)
		cls.subclasses.append(cls)

	mid = property(lambda self: self._mid)
	display = property(lambda self: self._cached_display)
	height = property(lambda self: len(self._cached_display))
	@property
	def filtered(self):
		if 0 <= self._shown_class <= len(self.subclasses) \
		and not isinstance(self, self.subclasses[self._shown_class]):
			return True
		return self.filter()

	@classmethod
	def move_filter(cls, val=None):
		'''
		Move the filtered subclass list index. If `val` is an integer, then
		this cycles between 'all' and the rest of subclasses. If a subclass,
		then it sets the filter to only that subclass. If None or not supplied,
		then all messages are unfiltered.
		returns a string corresponding to the allowed message type
		'''
		if val is None:
			cls._shown_class = -1
		elif isinstance(val, type):
			cls._shown_class = cls.subclasses.index(val)
		else:
			cls._shown_class += val + 1
			cls._shown_class %= len(cls.subclasses)+1
			cls._shown_class -= 1
			val = cls.subclasses[cls._shown_class]
		if cls._shown_class == -1:
			return 'all'
		return val.__name__

	def colorize(self):
		'''
		Virtual method to standardize colorizing a particular subclass of
		message. Used in Messages objects to create a contiguous display of
		messages.
		'''

	def filter(self): #pylint: disable=no-self-use
		'''
		Virtual method to standardize filtering of a particular subclass of
		message. Used in Messages objects to decide whether or not to display a
		message. True means that the message is filtered.
		'''
		return False

	def setstr(self, new, clear=True, remove_fractur=True):
		'''
		Invalidate cache and set contained string to something new.
		By default, also clears the contained formatting.
		'''
		super().setstr(new, clear, remove_fractur)
		self._last_recolor = -1
		self._cached_hash = -1
		self._cached_width = 0

	def cache_display(self, width, recolor_count):
		'''
		Break a message to `width` columns. Does nothing if matches last call.
		'''
		if self.filtered: #invalidate cache
			self._cached_display.clear()
			self._last_recolor = -1
			self._cached_hash = -1
			self._cached_width = 0
			return
		self_hash = self._cached_hash
		if self._last_recolor < recolor_count:
			#recolor message in the same way
			self.clear()
			self.colorize()
			self._last_recolor = recolor_count
			self_hash = hash(self)
		if self._cached_hash == self_hash and self._cached_width == width: #don't break lines again
			return
		self._cached_display = super().breaklines(width, self.INDENT, self.KEEP_EMPTY)
		self._cached_hash = self_hash
		self._cached_width = width

	def dump(self, prefix="", coloring=False):
		'''Dump public variables associated with the message'''
		publics = {i: j for i, j in self.__dict__.items() \
			if not i.startswith('_')}
		if coloring:
			print(repr(self), prefix, publics)
		else:
			print(prefix, publics)

	@classmethod
	def examine(cls, func):
		'''
		Wrapper for a function that monitors instantiation of messages.
		`func` must have signature (message), the instance in question
		'''
		if not hasattr(cls, "_examine"):
			cls._examine = []
		cls._examine.append(func)
		return func

	@classmethod
	def key_handler(cls, key_name, override_val=None):
		'''
		Decorator for adding a key handler. Key handlers for Messages objects
		expect signature (message, calling overlay)
		Mouse handlers expect signature (message, calling overlay, position)
		See OverlayBase.add_keys documentation for valid values of `key_name`
		'''
		keys = cls.subclass_keys.get(cls)
		if keys is None:
			keys = KeyContainer()
			#mouse callbacks don't work quite the same; they need an overlay
			keys.nomouse()
			cls.subclass_keys[cls] = keys
		def ret(func):
			keys.add_key(key_name, func, return_val=override_val)
			return func
		return ret

@Message.key_handler("^x")
def copy_message(message, overlay):
	'''Copy selected message to clipboard'''
	overlay.parent.loop.create_task(
		xclip(overlay.parent, str(message)))

class SystemMessage(Message):
	'''System messages that are colored red-on-white'''
	def colorize(self):
		self.insert_color(0, colors.system)

class Messages: #pylint: disable=too-many-instance-attributes
	'''Container object for Message objects'''
	def __init__(self, parent, no_recolors=False):
		self.parent = parent

		self.can_select = True
		self._all_messages = deque()	#all Message objects
		#selectors
		self._selector = 0		#selected message
		self._start_message = 0	#start drawing upward from this index+1
		self._start_inner = 0	#ignore drawing this many lines in start_message
		self._height_up = 0		#lines between start_message and the selector
		self._hidden_top = 0	#number of lines of the topmost message hidden
		#lazy storage
		self._lazy_bounds = [0, 0]	#latest/earliest messages to recolor
		self._lazy_offset = 0		#lines added since last lazy_bounds modification
		self._last_recolor = -1 if no_recolors else 0

	def __len__(self):
		return len(self._all_messages)

	def dump(self):
		self_dict = {i:j for i, j in self.__dict__.items()
			if i not in ("_all_messages", "parent")}
		print(self_dict)

	def clear(self, domessages=True):
		'''Clear all lines and messages'''
		self.can_select = True
		if domessages:
			self._all_messages.clear()
			self._lazy_bounds = [0, 0]
			self._lazy_offset = 0
		self._selector = 0
		self._start_message = 0
		self._start_inner = 0
		self._height_up = 0
		self._hidden_top = 0
		self._last_recolor += (self._last_recolor >= 0)

	def stop_select(self):
		'''Stop selecting'''
		if self._selector:
			#only change the lazy bounds if our range isn't a continuous run
			if self._start_message - self._lazy_offset \
			 not in range(*self._lazy_bounds):
				self._lazy_bounds = [0, 0]
			self.clear(False)
			self._lazy_offset = 0
			return True
		return False

	@property
	def selected(self):
		'''
		Frontend for getting the selected message. Returns None if no message is
		selected, or a Message object (or subclass)
		'''
		return self._all_messages[-self._selector] if self._selector else None

	@property
	def has_hidden(self):
		'''Retrieve whether there are hidden messages below (have scrolled upward)'''
		return bool(self._start_message)

	def display(self, lines):
		'''Using cached data in the messages, display to lines'''
		if not self._all_messages:
			return
		line_number = 2
		msg_number = self._start_message + 1
		ignore = self._start_inner
#		cached_range = range(*self._lazy_bounds)
		self._lazy_bounds[0] = min(self._lazy_bounds[0] + self._lazy_offset, msg_number)
		#traverse list of lines
		while line_number <= len(lines) and msg_number <= len(self._all_messages):
			reverse = SELECT_AND_MOVE if msg_number == self._selector else ""
			msg = self._all_messages[-msg_number]
#			if msg_number - self._lazy_offset not in cached_range:
			msg.cache_display(self.parent.width, self._last_recolor)
			#if a message is ignored, then msg.display is []
			for line_count, line in enumerate(reversed(msg.display)):
				if ignore > line_count:
					continue
				if line_number > len(lines):
					break
				ignore = 0
				lines[-line_number] = reverse + line
				line_number += 1
			msg_number += 1
		self._lazy_bounds[1] = max(self._lazy_bounds[1] + self._lazy_offset, msg_number)
		self._lazy_offset = 0

	def up(self, amount=1):
		height = self.parent.height-1
		select = self._selector+1

		#the currently selected message is the top message
		if self._start_message+1 == self._selector:
			new_inner = min(self._start_inner + amount	#add to the inner height
				, self.selected.height - height)		#or use the max possible
			self._hidden_top = 0
			if new_inner >= self._start_inner:
				inner_diff = new_inner - self._start_inner
				self._start_inner = new_inner
				amount -= inner_diff
				if amount <= 0:
					return inner_diff
		elif self._hidden_top > 0:
			delta = self._hidden_top - amount
			if delta >= 0 or amount > 1:
				self._hidden_top = delta
				self._justify_start(amount, height)
				return amount
			amount -= self._hidden_top
			self._hidden_top = 0

		#out of checking for scrolling inside of a message; go by messages now
		num_messages = 0
		addlines = 0
		cached_range = range(*self._lazy_bounds)
		while num_messages < amount:
			if select > len(self._all_messages):
				break
			if select - self._lazy_offset not in cached_range:
				#recache to get the correct message height
				self._all_messages[-select].cache_display(self.parent.width
					, self._last_recolor)
			last_height = self._all_messages[-select].height
			if last_height:
				num_messages += 1
				addlines += last_height
			select += 1
		self._lazy_bounds[1] = max(self._lazy_bounds[1] + self._lazy_offset
			, select)
		self._lazy_offset = 0
		self._selector = select-1

		#so at this point we're moving up `addlines` lines
		self._height_up += addlines
		if self._height_up > height:
			#next message is already visible
			delta = self._height_up - height
			if amount == 1:
				if addlines - delta > 0:
					self._hidden_top = delta
					self._height_up = height
					return 1
				self._justify_start(min(addlines, 1), height)
				self._hidden_top = addlines - 1
				return 1
			addlines = delta
			self._justify_start(addlines, height)

		return addlines

	def _justify_start(self, amount, height):
		start = self._start_message+1
		startlines = -self._start_inner
		last_height = 0
		while startlines <= amount:
			last_height = self._all_messages[-start].height
			startlines += last_height
			start += 1
		self._start_message = start-2
		#the last message is perfect for what we need
		if startlines - last_height == amount:
			self._start_inner = 0
		#the first message we checked was enough
		elif startlines == last_height:
			self._start_inner = amount
		else:
			self._start_inner = last_height - startlines + amount

		self._height_up = height

	def down(self, amount=1):
		if not self._selector:
			return 0
		height = self.parent.height-1
		#scroll within a message if possible, if there is a hidden line
		if self._selector == self._start_message+1 and self._start_inner > 0:
			self._hidden_top = 0
			new_inner = max(-1, self._start_inner - amount)
			inner_diff = self._start_inner - new_inner
			self._start_inner = new_inner
			self._height_up = min(height, self._height_up+amount)
			amount -= inner_diff
			if new_inner < 0:
				if self._selector == 1:
					self.stop_select()
					return 0
				return inner_diff
			if amount <= 0:
				return inner_diff

		#out of checking for scrolling inside of a message; go by messages now
		select = self._selector
		last_height = 0
		num_messages = 0
		addlines = 0
		cached_range = range(*self._lazy_bounds)
		while num_messages <= amount:
			#stop selecting if too low
			if select == 0:
				self.stop_select()
				return 0
			if select - self._lazy_offset not in cached_range:
				self._all_messages[-select].cache_display(self.parent.width
					, self._last_recolor)
			last_height = self._all_messages[-select].height
			if last_height:
				addlines += last_height
				num_messages += 1
			select -= 1
		self._lazy_bounds[0] = min(self._lazy_bounds[0] + self._lazy_offset
			, select+1)
		self._lazy_offset = 0
		self._selector = select+1

		#so at this point we're moving down `addlines` lines
		self._height_up -= addlines - last_height
		if self._height_up < last_height and select < self._start_message:
			self._start_message = select
			if amount == 1:
				self._start_inner = self.selected.height-1
				self._height_up = 1
				return 1
			self._start_inner = max(self.selected.height - height, 0)
			self._height_up = min(self.selected.height, height)
		elif self._hidden_top > 0:
			self._height_up = max(height - self._hidden_top, 1)

		self._hidden_top = 0
		return addlines

	def append(self, msg: Message):
		'''Add new message to the left (bottom)'''
		#undisplayed messages have length zero
		self._all_messages.append(msg)
		msg.cache_display(self.parent.width, self._last_recolor)

		#adjust selector iterators
		if self._selector:
			self._selector += 1
			#scrolled up too far to see
			if self._start_message == 0 \
			and msg.height + self._height_up <= (self.parent.height-1):
				self._height_up += msg.height
				self._lazy_offset += 1
				return msg.mid
			self._start_message += 1

		return msg.mid

	def prepend(self, msg: Message):
		'''Prepend new message. Use msg_prepend instead'''
		self._all_messages.appendleft(msg)
		msg.cache_display(self.parent.width, self._last_recolor)
		return msg.mid

	def delete(self, test, delete_all=False):
		'''
		Delete a message. If `test` is an int, then the message with that id
		will be deleted. Otherwise, the first message for which `test`(Message)
		is True will be deleted. If `all` is true, then all messages satisfying
		`test` are deleted.
		'''
		if not self._all_messages:
			return
		if isinstance(test, int):
			mid = test
			test = lambda x: x.mid == mid
		elif not callable(test):
			raise TypeError("delete requires callable")

		start = 1

		while start <= len(self._all_messages):
			msg = self._all_messages[-start]
			if test(msg):
				del self._all_messages[-start]
				start -= 1
				if self._selector > start: #below the selector
					self._selector += 1
					self._height_up -= msg.height
					#have to add back the inner height
					if start == self._selector:
						self._height_up += self._start_inner
						if self._selector == self._start_inner: #off by 1 anyway
							self._start_inner += 1
							self._height_up = self.selected.height
				if not delete_all:
					self.parent.redo_lines()
					return
			start += 1
		self.parent.redo_lines()

	def from_position(self, x, y):
		'''Get the message and depth into the message at position x,y'''
		#we always draw "upward," so 0 being the bottom is more useful
		y = (self.parent.height-1) - y
		if y <= 0:
			return "", -1
		#we start drawing from this message
		start = self._start_message+1
		height = -self._start_inner
		#find message until we exceed the height
		while height < y:
			#advance the message number, or return if we go too far
			if start > len(self._all_messages):
				return "", -1
			msg = self._all_messages[-start]
			height += msg.height
			start += 1

		#line depth into the message
		depth = height - y
		indent_size = numdrawing(msg.INDENT)
		#only ignore the indent on messages larger than 0
		pos = sum(numdrawing(line) - (i and indent_size) \
			for i, line in enumerate(msg.display[:depth]))

		indent_size = indent_size if depth else 0
		if x >= collen(msg.INDENT) or not depth:
			#try to get a slice up to the position 'x'
			pos += min(len(str(msg))-1, \
				max(0, numdrawing(msg.display[depth], x) - indent_size))
		return msg, pos

	def scroll_to(self, index):
		'''
		Directly set selector and height_up, then redo_lines.
		Redraw necessary afterward.
		'''
		if not self._all_messages:
			return
		height = self.parent.height-1

		self._selector = index
		self._start_message = index-1
		self._hidden_top = 0
		if index:
			self._start_inner = max(self.selected.height - height, 0)
			self._height_up = min(self.selected.height, height)
		self._lazy_bounds = [index, index]
		self._lazy_offset = 0

	def scroll_top(self):
		top = self._selector
		self.scroll_to(len(self._all_messages))
		if self._selector == top:
			return -1
		return None

	def iterate_with(self, callback):
		'''
		Returns an iterator that yields when the callback is true.
		Callback is called with arguments passed into append (or msg_append...)
		'''
		if not self._all_messages:
			return
		select = 1
		while select <= len(self._all_messages):
			message = self._all_messages[-select]
			try:
				ret = callback(message)
			except Exception: #pylint: disable=broad-except
				traceback.print_exc()
				continue
			if ret:
				yield message, select
			select += 1

	def get_first(self, callback):
		'''
		Get the first instance (if any) that `iterate_with` would retireve
		Raises ValueError if no message satisfies callback
		'''
		for message, select in self.iterate_with(callback):
			return message, select
		raise ValueError("no messages match callback")

	#REAPPLY METHODS-----------------------------------------------------------
	def redo_lines(self, recolor=True):
		'''Re-apply Message coloring and redraw all visible lines'''
		if recolor:
			self._last_recolor += 1
		self._hidden_top = 0
		self._lazy_bounds = [self._start_message, self._start_message]

class ChatOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every `push_times` seconds, 0 to disable.
	'''
	replace = True
	def __init__(self, parent, push_times=600, no_recolors=False):
		super().__init__(parent)
		del self.keys["^w"] #unbind overlay exit
		self._push_times = push_times
		self._push_task = None
		self._last_time = -1
		#options for TextOverlays
		self._empty_close = False
		self.isolated = False
		self.add_keys({
			   "^p":	lambda: (self.messages.selected and self.messages.selected.dump(coloring=True)) or 1
			 , "^o":	lambda: self.messages.dump() or 1
		})

		self.messages = Messages(self, no_recolors)

	can_select = property(lambda self: self.messages.can_select)
	@can_select.setter
	def can_select(self, new):
		self.messages.can_select = new

	async def _time_loop(self):
		'''Prints the current time every 10 minutes'''
		while self._push_times > 0:
			await asyncio.sleep(self._push_times)
			self.msg_time()

	#method overloading---------------------------------------------------------
	def __call__(self, lines):
		'''Display messages'''
		self.messages.display(lines)
		separator = Box.CHAR_HSPACE * (self.parent.width - 1)
		separator += '^' if self.messages.has_hidden else Box.CHAR_HSPACE
		lines[-1] = separator

	def add(self):
		'''Start timeloop and add overlay'''
		super().add()
		if self._push_times > 0:
			self._push_task = self.parent.loop.create_task(self._time_loop())

	def remove(self):
		'''
		Quit timeloop (if it hasn't already exited).
		Exit client if last overlay.
		'''
		if self._push_task is not None:
			#finish running the task
			self._push_task.cancel()
		if self.index == 0:
			self.parent.stop()
		super().remove()

	def resize(self, newx, newy):
		'''Resize scrollable and maybe draw lines again if width changed'''
		super().resize(newx, newy)
		self.messages.redo_lines(False)
		return 1

	def run_key(self, overlay, chars, do_input):
		'''Delegate running characters to a selected message that supports it'''
		selected = self.messages.selected
		ret = None
		try:
			#only ignore message keys if there is a superior overlay that is
			#not a TextOverlay and can run the chars provided
			ignore = overlay != self and not isinstance(overlay, TextOverlay) \
				and chars in overlay.keys
			if selected is None or ignore:
				raise KeyException
			prevent_exception = False
			for subclass in type(selected).mro():
				try:
					keys = Message.subclass_keys.get(subclass)
					if keys is not None:
						#pass in the message and this overlay to the handler
						ret = keys(chars, selected, self)
						prevent_exception = True
						break
				except KeyException:
					pass
			if not prevent_exception:
				raise KeyException
		except KeyException:
			ret = overlay.keys(chars, overlay, do_input=do_input)

		if not ret and -1 in overlay.keys:
			ret = self.messages.stop_select()
			self.parent.update_input()
		elif ret == -1:
			overlay.remove()
		if overlay != self:
			return 1
		return ret

	@key_handler("mouse")
	def _mouse(self, state, x, y):
		'''Delegate mouse to message clicked on'''
		msg, pos = self.messages.from_position(x, y)
		for subclass in type(msg).mro():
			try:
				keys = Message.subclass_keys.get(subclass)
				if keys is not None:
					return keys.mouse(msg, self, pos, state=state, x=x, y=y)
			except KeyException:
				pass
		return 1

	#MESSAGE SELECTION----------------------------------------------------------
	def _max_select(self):
		self.parent.sound_bell()
		#self.can_select = 0

	@key_handler("ppage", amount=5)
	@key_handler("a-k")
	@key_handler("mouse-wheel-up")
	def select_up(self, amount=1):
		'''Select message up'''
		if not self.can_select:
			return 1
		#go up the number of lines of the "next" selected message
		upmsg = self.messages.up(amount)
		#but only if there is a next message
		if not upmsg:
			self._max_select()
		return 1

	@key_handler("npage", amount=5)
	@key_handler("a-j")
	@key_handler("mouse-wheel-down")
	def select_down(self, amount=1):
		'''Select message down'''
		if not self.can_select:
			return 1
		#go down the number of lines of the currently selected message
		self.messages.down(amount)
		if self.messages.selected is None:
			#move the cursor back
			self.parent.update_input()
		return 1

	@key_handler("^m", direction=-1)
	@key_handler("^n", direction=1)
	def cycle_message_filter(self, direction):
		'''Cycle the displayed Message subclasses'''
		displayed = Message.move_filter(direction)
		self.redo_lines()
		self.parent.blurb.push(f"displaying: '{displayed}'")

	@key_handler("a-g")
	def select_top(self):
		'''Select top message'''
		if not self.can_select:
			return 1
		if self.messages.scroll_top() == -1:
			self._max_select()
		return 1

	def clear(self):
		'''Clear all messages'''
		self.messages.clear()

	def redo_lines(self, recolor=True):
		self.messages.redo_lines(recolor)
		self.parent.schedule_display()

	#MESSAGE ADDITION----------------------------------------------------------
	def msg_system(self, base, prepend=False):
		'''System message'''
		if prepend:
			return self.msg_prepend(SystemMessage(base))
		return self.msg_append(SystemMessage(base))

	def msg_time(self, numtime=None, predicate="", prepend=False):
		'''Push a system message of the time'''
		dtime = time.strftime("%H:%M:%S"
			, time.localtime(numtime or time.time()))
		ret = self.msg_system(predicate+dtime, prepend=prepend)
		if not predicate and not prepend:
			if self._last_time == ret-1:
				self.messages.delete(self._last_time)
			self._last_time = ret
		return ret

	def msg_append(self, post: Message):
		'''Append a message'''
		self.parent.schedule_display()
		return self.messages.append(post)

	def msg_prepend(self, post: Message):
		'''Prepend a message'''
		self.parent.schedule_display()
		return self.messages.prepend(post)

class _MessageScrollOverlay(DisplayOverlay):
	'''
	DisplayOverlay with the added capabilities to display messages in a
	LazyIterList and to scroll a ChatOverlay to the message index of such
	a message. Do not directly create these; use add_message_scroller.
	'''
	def __init__(self, overlay, lazy_list, early, late):
		self.lazy_list = lazy_list
		message, self.msg_index = lazy_list[0]
		self.early = early
		self.late = late
		super().__init__(overlay.parent, message, Message.INDENT)

		scroll_to = lambda: overlay.messages.scroll_to(self.msg_index) or -1
		self.add_keys({
			  'tab':	scroll_to
			, 'enter':	scroll_to
		})

	@key_handler('N', step=-1)
	@key_handler('a-j', step=-1)
	@key_handler('n', step=1)
	@key_handler('a-k', step=1)
	def next(self, step):
		attempt = self.lazy_list.step(step)
		if attempt:
			self.prompts, self.msg_index = attempt
		elif step == 1:
			self.parent.blurb.push(self.early)
		elif step == -1:
			self.parent.blurb.push(self.late)

def add_message_scroller(overlay, callback, empty, early, late):
	'''
	Add a message scroller for a particular callback.
	This wraps Messages.iterate_with with a LazyIterList, spawns an instance of
	_MessageScrollOverlay, and adds it to the same parent as overlay.
	Error blurbs are printed to overlay's parent: `empty` for an exhausted
	iterator, `early` for when no earlier messages matching the callback are
	found, and `late` for the same situation with later messages.
	'''
	try:
		lazy_list = LazyIterList(overlay.messages.iterate_with(callback))
	except TypeError:
		return overlay.parent.blurb.push(empty)

	ret = _MessageScrollOverlay(overlay, lazy_list, early, late)
	ret.add()
	return ret
