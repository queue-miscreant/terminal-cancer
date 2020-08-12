display.py
====================

The module display.py is intended to perform two things:
* efficiently store and apply text coloring and effects, and
* break strings into a number of lines that are smaller than a certain column width.

It is an abstraction over [ANSI escape sequences](https://en.wikipedia.org/wiki/ANSI_escape_code)


Exceptions
----------
This module defines a single exception, `DisplayException`, used internally
when displays go wrong


Bare Functions
---------------------

### `collen(string: str) -> int`
Column width of the `string`. Equivalent to `wcswidth` in `wcwidth.py`,
but ignores ANSI escape sequences.
For example, `collen("\x1b[mあ")` will return 2, since the character 'あ'
occupies 2 columns, but the ANSI escape is effectively zero-width

`string`: (unicode) String to find the column width of \
`@return`: Column width


### `columnslice(string: str, width: int) -> int`
Slices a `string` to column `width`.

`string`: (unicode) Input string \
`width`: Column width to cut to \
`@return`: Index of `string` that gives the best "cut"



colors/\_ColorManager
---------------------

Centralized color/effect management.
Stores most of the various strings that modify terminal display.
This class has a single instance, created at startup; additional instances do nothing.

Basic colors can be accessed by the list of valid color names:
* "black"
* "red"
* "green"
* "yellow"
* "blue"
* "magenta"
* "cyan"
* "white"
* ""
* "none"

These are in ascending order by color number (i.e, black is at index 0, and corresponds to '30').

These cannot be directly used to color text.
Instead, foreground/background color pairs must be defined with `def_color` before being used.

It is the user's responsibility to store the color definitions in order to tell them apart.
However, there are several predefined colors used in various places:

* `colors.default`:		default text/default background
* `colors.system`: 		red text/white background
* `colors.red_text`:	red text/default background
* `colors.green_text`:	green text/default background
* `colors.yellow_text`:	yellow text/default background

The last four are mainly for interal use by input.py and chat.py.

Richer colors can be automatically defined by setting the member `two56on` to `True`,
if not already defined by previously toggling on. These correspond to colored text
on default background, and can be accessed either with `colors.two56` or `colors.grayscale`

The module also supports effects turned on and off. Predefined effects are:
* Reverse video (i.e. white text on black -> black text on white)
* Underline

### Methods

#### `colors.def_color(fore, back="none", intense=False) -> int`
Defines a color.
`fore`: Foreground color. Either from the list of basic colors above or an integer
0-255 for 256-color mode. \
`back`: Background color. Either from the list of basic colors above or an integer
0-255 for 256-color mode. \
`intense`: Color intensity on/off. Some terminal emulators render intense colors as bold. \
`@return`: UID corresponding to this color


#### `colors.def_effect(effect_on, effect_off) -> int`
Define an effect.
Intended for zero-column-width strings like ANSI escapes, but not strictly enforced.
Text in Coloring objects may render improperly.

`effect_on`: The string used to turn the effect on \
`effect_off`: The string used to turn the effect off \
`@return`: UID corresponding to this effect


#### `colors.two56(color, too_black=0.1, too_white=0.9, reweight=None) -> int`
Retrieve a 256-color mode color UID.

`color`: Either an int directly referring to a 256-color,
	a string like "[#]FFFFFF", or a 3-tuple/list \
`too_black`: If the average RGB value (range 0-1) should fall below this value,
	the default color will be returned as fallback \
`too_white`: If the average RGB value (range 0-1) should go above this value,
	the default color will be returned as fallback \
`reweight`: If a unary callable is supplied, then the RGB values (range 0-1) will
	be modified by this function before being converted to the final color number \
`@return`: If 256-color mode is enabled, the color UID closest to `color`
	Otherwise, the default color will be returned as fallback

#### `grayscale(gray) -> int`
Retrieve a grayscale from 256-color mode colors.

`gray`: An integer from 0 (black) to 23 (white), representing the steps of grayscale \
`@return`: If 256-color mod is enabled, the grayscale step
	Otherwise, the default color will be returned as fallback

Coloring
-------------------
The workhorse class of the module.
Wraps a string and stores information pertaining to color/effects that apply at which positions.
Once a Coloring object is defined, more colors and effects CANNOT be defined.

To retrieve a string with applied coloring, use `format(coloring)`.
If the string must be confined to a particular column width, use `coloring.break_lines(width)`


### Magic

#### `str(coloring)`
Retrieves the string currently contained

#### `bool(coloring)`
Whether the string currently contained is null or not

#### `format(coloring) -> str`
Applies the stored formatting to the string, without regard for column width

`@return`: A string with the contained colors/effects applied

#### `coloring + (str or Coloring)`
Modifies `coloring` to add the effects of of the RHS.

`@return`: The modified `coloring`


### Methods

#### `Coloring(string: str, remove_fractur=True)`

`string`: String to wrap \
`remove_fractur`: If enabled, will convert "bad" fractur characters whose
column widths cause problems down to ASCII equivalents

#### `Coloring.clear()`
Clear all stored formatting. 

#### `Coloring.sub_slice(sub: str, start, end=None)`
Splice in string `sub` as a replacement for `str(self)[start:end]`

`sub`: String to insert \
`start`: String index to start splice at.
	Negative indices can be used to refer to positions relative to the end of the string \
`end`: String index to end splice at
	Negative indices can be used to refer to positions relative to the end of the string
	`None` refers to the end of the string

#### `Coloring.colored_at(postition) -> bool`
Whether or not the instance has a color/effect at string index `position`

`@return`: See above

#### `Coloring.insert_color(position, color)`
Inserts a `color` at a `position` in the string.
Note that positions beyond it will have that color until a new color is described

`position`: The string index at which the color should appear \
`color`: A valid color UID returned by `colors.def_color` or `colors.two56`

#### `Coloring.effect_range(start: int, end: int, effect: int)`
Adds an `effect` to string slice `[start:end]`.
For example, `effectRange(0,-1,0)` will make the entire string excluding the
last character reverse video.

`start`: String index effect begins at \
`end`: String index effect ends at \
`effect`: A valid effect UID returned by `colors.def_effect` \

#### `Coloring.add_global_effect(effect: int, pos=0)`
Turn an effect until the end of the string.
Shorthand for `effectRange(pos, len(str), effect)` where `str` is the string contained.

#### `Coloring.find_color(end: int)`
Find the most recent color before index `end`

`end`: String index to query color at \
`@return`: Color UID that applies before `end`


#### `Coloring.color_by_regex(regex: re.Pattern, group_func, fallback=None, group=0)`
Insert a color from a compiled `regex`.
When the regex is matched, `color` will be applied to the match (at the corresponding `group`),
preserving the color immediately before the match.

e.g.: Say we have a completely green string "(Green)" that contains a matching substring.
If we apply a color that corresponds to blue, then the match will be drawn in blue while
maintaining the green color after the match ends; i.e. "(Green)(Blue)(Green)"

`regex`: Compiled regex pattern \
`group_func`: An integer or unary callable that returns an integer.
	The callable should expect the matching group of the regex. \
`fallback` is the fallback color if no colors exist before the match. \
`group`: Regex group to apply the color to.

#### `Coloring.effect_by_regex(regex: re.Pattern, effect, group=0)`
Adds an effect with effect number `effect` to the regex match.

`regex`: Compiled regex pattern \
`effect`: A valid effect UID returned by `colors.def_effect` \
`group`: The regex group to apply the effect to


#### `Coloring.breaklines(length: int, outdent="", keep_empty=True) -> [str]`
Applies coloring and effects to the contained string and
breaks it into lines with column width no greater than `length`

`length`: Maximum column width to allow \
`outdent`: A leading string for all lines besides the first \
`keep_empty`: Whether "empty" lines are kept in the returned list \
`@return`: A list of formatted strings, each of column width at most `length`


JustifiedColoring
-------------------
Subclass of Coloring. 
"Justification" in this case refers to producing strings of a consistent column width.
Strings which are too long will have an ellipsis inserted to indicate missing text.
Strings which are too short will be padded out.

Additionally, indicator lamps can be added to the "right side" for richer displays.


### Methods

#### `add_indicator(sub: str, color=None, effect=None)`
Add an indicator lamp-esque display `sub` to displayed right-justified.

`sub`: String to add to be right-justified \
`color`: Color to apply to the right side
	Either None or a valid color UID returned by `colors.def_color` or `colors.two56` \
`effect`: Effect to apply to the right side
	Either None or a valid effect UID returned by `colors.def_effect`


#### `justify(length, justchar=' ', ensure_indicator=2) -> str`
Formats the string contained, ellipsized or padded to `length`

`length`: Desired column width \
`justchar`: Character to use as padding to the specified width `length` \
`ensure_indicator`: the number of columns to reserve for the indicator lamp, if one exists \
`@return`: Formatted string, with column width `length`


Scrollable
-------------------
Textbox-like input in the terminal.
Whereas JustifiedColoring consistently ellipsizes the string in the middle, this class
will scroll along with the terminal cursor.
Generally, when the cursor moves or text is modified, the `_onchanged` callback is called.

### Methods

#### `Scrollable(width: int, string="")`

`width`: Column width of the display. \
`string`: String to wrap.


#### `Scrollable.show(password=False) -> str`
Retrieve a "good slice" of the string contained.

`password`: Whether or not to draw \
`@return`: The aforementioned "good slice". If printed, the terminal cursor position will
	be saved at the location of the scrollable's cursor.


#### `Scrollable.setstr(new: str)`
Set the contained string and move cursor to the end

`new`: New contained string


#### `Scrollable.clear()`
Clears the contained text.


#### `Scrollable.setnonscroll(new: str)`
Set a string to draw at the beginning of the scrollable, but not part of the
wrapped string

`new`: New nonscrolling string.
	Column width must be shorter than `Scrollable.MAX_NONSCROLL_WIDTH`


#### `Scrollable.setwidth(new: int)`
Set the maximum column width

`new`: New column width.


#### `Scrollable.movepos(dist)`
Move the cursor left or right a certain distance

`distance` Number of characters to move.
	Positive is rightward, negative is leftward.


#### `Scrollable.home()`
Move the cursor to the beginning of the string


#### `Scrollable.end()`
Move the cursor to the end of the string


#### `Scrollable.wordback()`
Move the cursor to the beginning of the current or previous word


#### `Scrollable.wordnext()`
Move the cursor to the end of the current or next word


#### `Scrollable.append(new)`
Append a string at the cursor position.

`new`: String to append


#### `Scrollable.backspace()`
Backspace at the current cursor position


#### `Scrollable.delchar()`
Delete character at the current cursor position


#### `Scrollable.delword()`
Delete word behind cursor.
Equivalent to backspace() until the position specified by `wordback`


#### `Scrollable.delword()`
Delete word ahead of cursor.
Equivalent to delchar() until the position specified by `wordnext`


ScrollSuggest
-------------------
Subclass of Scrollable
Adds suggestion-tabbing through functionality


### Methods

#### `ScrollSuggest.complete(completer: Sigil)`
Enter "tabbing mode" if not already, generating suggestions list.
If in tabbing mode already, advance to the next suggestion and replace contained text


#### `ScrollSuggest.backcomplete()`
If in tabbing mode, return to the previous suggestion and replace contained text
