#!/usr/bin/env python3
#linkopen.py
'''
Library for opening links. Allows extension through wrappers
Open links by file extension, site pattern, or lambda truth
evaluation.
Althought this does not import .display (or any other module in the package),
open_link expects an instance of base.Screen as its first argument.

All openers are made into coroutines so that create_subprocess_exec can be
yielded from. open_link creates a task in the Screen instance's loop
'''
import os	#cygwin, stupid stdout/err hack
import sys	#same
import re	#link patterns, link pattern openers
import asyncio		#subprocess spawning
import traceback	#link opening failures
from http.client import HTTPException	#for catching IncompleteRead
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from html import unescape
from subprocess import DEVNULL, PIPE

from .input import ConfirmOverlay, DisplayOverlay
from .display import colors

IMG_ARGS = ["feh"]
MPV_ARGS = ["mpv", "--pause"]
XCLIP_ARGS = ["xclip", "-sel", "c"]
YTDL_ARGS = ["youtube-dl"]
if sys.platform in ("win32", "cygwin"):
	#by default, BROWSER does not include `cygstart`, which is a cygwin program
	#that will (for links) open things in the default system browser
	if os.getenv("BROWSER") is None:
		#prioritize cygstart for windows users
		os.environ["BROWSER"] = os.path.pathsep.join(["cygstart", "chrome"
			, "firefox", "waterfox", "palemoon"])

import webbrowser #pylint: disable=wrong-import-position, wrong-import-order

__all__ =	["LINK_RE", "get_defaults", "get_extension", "opener", "open_link"
	, "visit_link", "images", "videos", "browser", "urlopen_async", "get_opengraph"]

#extension recognizing regex
_NO_QUERY_FRAGMENT_RE =	re.compile(r"[^?#]+(?=.*)")
_EXTENSION_RE = re.compile(r"\.(\w+)[&/\?]?")
LINK_RE = re.compile("(https?://.+?\\.[^`\\s]+)")
#opengraph regex
OG_RE = re.compile(b"<meta\\s+(?:name|property)=\"og:([:\\w]+)\"\\s+" \
	b"content=\"(.+?)\"", re.MULTILINE)

class LinkException(Exception):
	'''Exception for errors in client.linkopen'''

def get_defaults():
	'''
	Get the names of the default functions. These are hopefully
	descriptive enough
	'''
	return [i.__name__ for i in opener.defaults]

def get_extension(link):
	'''
	Get the extension (png, jpg) that a particular link ends with
	Extension must be recognized by open_link.
	'''
	try:
		#try at first with the GET variable
		extensions = _EXTENSION_RE.findall(link)
		if extensions and extensions[-1].lower() in opener.exts:
			return extensions[-1].lower()
		#now trim it off
		link = _NO_QUERY_FRAGMENT_RE.match(link)[0]
		extensions = _EXTENSION_RE.findall(link)
		if extensions and extensions[-1].lower() in opener.exts:
			return extensions[-1].lower()
	except (IndexError, NameError):
		pass
	return ""

async def urlopen_async(link, loop=None):
	'''Awaitable urllib.request.urlopen; run in a thread pool executor'''
	if loop is None:
		loop = asyncio.get_event_loop()
	try:
		ret = await loop.run_in_executor(None, urlopen, link)
		return ret
	except (HTTPError, HTTPException):
		return ""

async def get_opengraph(link, *args, loop=None):
	'''
	Awaitable OpenGraph data, with HTML5 entities converted into unicode.
	If a tag repeats (like image), the value will be a list. Returns dict if no
	extra args supplied. Otherwise, for each in `*args`, return is such that
	`value1[, value2] = get_opengraph(..., key1[, key2])` formats correctly.
	'''
	html = await urlopen_async(link, loop=loop)
	if not html:
		raise Exception(f"Curl failed for {repr(link)}")

	full = {}
	for i, j in OG_RE.findall(html.read()):
		i = i.decode()
		j = unescape(j.decode())
		prev = full.get(i)
		if prev is None:
			full[i] = j
			continue
		if not isinstance(prev, list):
			full[i] = [prev]
		full[i].append(j)

	if not args:
		return full
	if len(args) == 1:
		return full[args[0]]		#never try 1-tuple assignment
	return [full[i] if i in full else None for i in args]	#tuple unpacking

class DummyScreen: #pylint: disable=too-few-public-methods
	'''Dummy class for base.Screen used by _LinkDelegator'''
	loop = property(lambda _: asyncio.get_event_loop())
	class blurb: #pylint: disable=invalid-name
		push = lambda _: None
		hold = lambda _: None
		release = lambda _: None
	def add_overlay(self, other):
		pass
	def pop_overlay(self, other):
		pass

#---------------------------------------------------------------
class _LinkDelegator: #pylint: disable=invalid-name
	'''
	Class that delegates opening links to the openers, keeps track of which
	links have been visited, and issues redraws when that updates
	'''
	warning_count = 5
	def __init__(self):
		self._visited = set()
		self._visit_redraw = []

	def __call__(self, screen, links, default=0, force=False):
		'''Open a link (or list of links) with the declared openers'''
		if screen is None:
			screen = DummyScreen()
		if not isinstance(links, list):
			links = [links]

		#limit opening too many links
		if not force and not isinstance(screen, DummyScreen) \
		and len(links) >= self.warning_count:
			ConfirmOverlay(screen, "Really open %d links? (y/n)" % len(links)
				, lambda: self(screen, links, default, True)).add()
			return

		do_redraw = False
		for link in links:
			if not isinstance(link, (tuple, list)):
				link = (link,)
			#append to visited links
			if link[0] not in self._visited:
				self._visited.add(link[0])
				do_redraw = True
			func = opener.get(link[0], default)
			screen.loop.create_task(self._open_safe(func, screen, link))

		if do_redraw:
			for func in self._visit_redraw:
				func()

	def visit_link(self, links):
		'''Mark links as visited without using an opener'''
		if not isinstance(links, list):
			links = [links]

		do_redraw = False
		for link in links:
			#append to visited links
			if link not in self._visited:
				self._visited.add(link)
				do_redraw = True

		if do_redraw:
			for func in self._visit_redraw:
				func()

	async def _open_safe(self, func, screen, link):
		'''Safely open a link and catch exceptions'''
		try:
			try:
				await func(screen, *link)
			except TypeError:
				await func(screen, link[0])
		except Exception as exc: #pylint: disable=broad-except
			screen.blurb.push("Error opening link: " + str(exc))
			traceback.print_exc()

	def is_visited(self, link):
		'''Returns if a link has been visited'''
		return link in self._visited

	def add_redraw_method(self, func):
		'''Add function `func` to call (with no arguments) on link visit'''
		self._visit_redraw.append(func)

	def del_redraw_method(self, func):
		'''Delete redraw method `func` added with `add_redraw_method`'''
		try:
			index = self._visit_redraw.index(func)
			del self._visit_redraw[index]
		except ValueError:
			pass
open_link = _LinkDelegator() #pylint: disable=invalid-name
visit_link = open_link.visit_link #pylint: disable=invalid-name

class opener: #pylint: disable=invalid-name
	'''
	Decorator for a link opener. With no arguments, sets a default opener.
	Otherwise, the first argument must be "default", "extension", "pattern",
	or "lambda". Extension openers open links of a certain extension, pattern
	openers match a string or regex, and lambdas open a link when a callable
	(that accepts the link as an argument) returns true.
	'''
	#storage for openers
	defaults = []
	exts = {}
	sites = {}
	lambdas = []
	lambda_lut = []

	def __init__(self, *args):
		if len(args) == 1 and callable(args[0]):
			self._type = "default"
			self.func = self(args[0])
			return
		if args[0] not in ["default", "extension", "pattern", "lambda"]:
			raise LinkException("invalid first argument of " + \
				"linkopen.opener {}".format(args[0]))
		self._type = args[0]
		self._argument = args[1]

	def __call__(self, *args, **kw):
		#call the function normally
		if hasattr(self, "func"):
			return self.func(*args, **kw)
		#coroutinize the function unless it already is one
		#(i.e. with stacked wrappers or async def)
		func = args[0]
		if not asyncio.iscoroutinefunction(func):
			func = asyncio.coroutine(func)

		#gross if statements
		if self._type == "default":
			self.defaults.append(func)
		elif self._type == "extension":
			self.exts[self._argument] = func
		elif self._type == "pattern":
			self.sites[self._argument] = func
		elif self._type == "lambda":
			self.lambdas.append(self._argument)
			self.lambda_lut.append(func)
		#allow stacking wrappers
		return func

	@classmethod
	def get(cls, link, default):
		#don't need to step through opener types if default is set
		if default:
			return cls.defaults[default-1]
		#check from ext
		ext = get_extension(link)
		ext_opener = cls.exts.get(ext)
		if ext_opener is not None:
			return ext_opener
		#check for patterns
		for i, j in cls.sites.items():
			found = False
			#compiled regex
			if isinstance(i, re.Pattern):
				found = i.search(link)
			elif isinstance(i, str):
				found = 1+link.find(i)
			if found:
				return j
		#check for lambdas
		for i, j in zip(cls.lambdas, cls.lambda_lut):
			if i(link):
				return j
		return cls.defaults[0]

#PREDEFINED OPENERS-------------------------------------------------------------
@opener("extension", "jpeg")
@opener("extension", "jpg")
@opener("extension", "jpg:large")
@opener("extension", "png")
@opener("extension", "png:large")
async def images(screen, link):
	'''Start feh (or replaced image viewer) in screen.loop'''
	if not IMG_ARGS:
		return await browser(screen, link)
	if isinstance(link, list):
		if not link:
			return
		args = IMG_ARGS.copy()
		args.extend(i for i in link if isinstance(i, str))
	elif isinstance(link, str):
		args = IMG_ARGS + [link]
	else:
		print(link)
		raise Exception("Attempted to open non-string")
	screen.blurb.push("Displaying image...")
	try:
		await asyncio.create_subprocess_exec(*args
			, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, loop=screen.loop)
	except FileNotFoundError:
		screen.blurb.push("Image viewer %s not found, defaulting to browser" % \
			IMG_ARGS[0])
		IMG_ARGS.clear()
		ret = await browser(screen, link)
		return ret

@opener("extension", "webm")
@opener("extension", "mp4")
@opener("extension", "gif")
async def videos(screen, link, title=None):
	'''Start mpv (or replaced video player) in screen.loop'''
	if not MPV_ARGS:
		return await browser(screen, link)
	screen.blurb.push("Playing video...")
	if title is not None and args[0] == "mpv": #mpv-specific hack
		args.extend(["--title={}".format(title)])
	args = MPV_ARGS + [link]
	try:
		await asyncio.create_subprocess_exec(*args
			, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, loop=screen.loop)
	except FileNotFoundError:
		screen.blurb.push("Video player %s not found, defaulting to browser" % \
			MPV_ARGS[0])
		MPV_ARGS.clear()
		ret = await browser(screen, link)
		return ret

@opener
async def browser(screen, link):
	'''Open new tab without webbrowser outputting to stdout/err'''
	screen.blurb.push("Opened new tab")
	#get file descriptors for stdout
	fdout, fderr = sys.stdout.fileno(), sys.stderr.fileno()
	savout, saverr = os.dup(fdout), os.dup(fderr)	#get new file descriptors
	#close output briefly because open_new_tab prints garbage
	os.close(fdout)
	if fdout != fderr:
		os.close(fderr)
	try:
		webbrowser.open_new_tab(link)
	finally:	#reopen stdout/stderr
		os.dup2(savout, fdout)
		os.dup2(saverr, fderr)

async def clipboard(string):
	'''Copy `string` to standard selection clipboard'''
	if not XCLIP_ARGS:
		return
	try:
		process = await asyncio.create_subprocess_exec(*XCLIP_ARGS
			, stdin=PIPE, stdout=DEVNULL, stderr=DEVNULL)
	except FileNotFoundError as exc:
		XCLIP_ARGS.clear()
		raise Exception("Fatal xclip error") from exc
	await process.communicate(string.encode("utf-8"))

@opener
async def xclip(screen, link):
	'''Copy a link to the main clipboard'''
	await clipboard(link)
	screen.blurb.push("Copied to clipboard")

TWITTER_RE = re.compile(r"twitter\.com/.+/status")
@opener("pattern", TWITTER_RE)
async def twitter(screen, link):
	mobile_link = link.find("mobile.twitter")
	if mobile_link != -1:
		link = link[:mobile_link] + link[mobile_link+7:]

	title, image, video, desc = await get_opengraph(
		Request(link, headers={"User-Agent": "Twitterbot"})
		, "title", "image", "video:url", "description", loop=screen.loop)
	#twitter always returns at least one image; the pfp
	if isinstance(image, str) and image.find("profile_images") != -1:
		image = []

	#no, I'm not kidding, twitter double-encodes the HTML entities
	#but most parsers are insensitive to this because of the following:
	#"&amp;amp;..." = "(&amp;)..." -> "(&)amp;..." -> "(&amp;)..." -> "&..."
	try:
		who	=	unescape(title[:title.rfind(" on Twitter")])
		desc =	unescape(desc[1:-1]) #remove quotes
	except AttributeError as ae:
		raise KeyError("Curl failed to find tag") from ae

	disp = [(who, colors.yellow_text)
		, desc]
	additional = ""
	if video:
		additional = "1 video"
	elif isinstance(image, str):
		additional = "1 image"
	elif image:
		additional = "%d image(s)" % len(image)

	new = DisplayOverlay(screen, disp + \
		[(additional, colors.yellow_text), "", link])
	@new.key_handler("^g")
	@new.key_handler("enter", override=-1)
	def open_link(_):
		screen.loop.create_task(browser(screen, link))

	@new.key_handler("i")
	def open_images(_):
		if video:
			screen.loop.create_task(videos(screen, video))
		elif image is not None:
			screen.loop.create_task(images(screen, image))

	new.add()

@opener
async def download(screen, link):
	'''Download a link with youtube-dl'''
	screen.blurb.push("Starting download ({})...".format(link))
	args = YTDL_ARGS + [link]

	try:
		process = await asyncio.create_subprocess_exec(*args
			, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE, loop=screen.loop)
	except FileNotFoundError as no_file:
		YTDL_ARGS.clear()
		raise Exception("youtube-dl not found") from no_file

	_, stderr = await process.communicate()
	for line in stderr.decode():
		if line.startswith("ERROR: "):
			raise Exception(line[7:].replace('\n', ' '))

	await process.wait()
	screen.blurb.push("Download completed")

#as consequence of youtube-dl; players with compatable hooks benefit from this
@opener("pattern", "youtube.com/watch")
@opener("pattern", "youtu.be/")
async def youtube(screen, link):
	title, image, desc = await get_opengraph(link
		, "title", "image", "description", loop=screen.loop)

	new = DisplayOverlay(screen, [
		  "Title:\n" + title
		, ""
		, "Description:\n" + desc
		, ""
		, link #TODO maybe color link?
	])

	@new.key_handler('i')
	def open_image(_):
		'''Open video thumbnail'''
		open_link(screen, image)

	@new.key_handler('b')
	def open_browser(_):
		'''Open video in browser'''
		screen.loop.create_task(browser(screen, link))
		return -1

	@new.key_handler("^g")
	@new.key_handler("enter", -1)
	def open_video(_):
		'''Open video in youtube-dl enabled video player'''
		screen.loop.create_task(videos(screen, link))

	new.add()
