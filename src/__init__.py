#!/usr/bin/env python3
'''Terminal display package with link opening capabilities.'''
#TODO As nice as key_handlers are, just having a config file would work better

from .base import *
from .input import *
from .chat import *
from .util import key_handler, KeyContainer, Sigil, tab_file
from .display import Box, Coloring, colors

#expose colors names for convenience
two56 = colors.two56
raw_num = colors.raw_num
grayscale = colors.grayscale
raw_num = colors.raw_num
#expose base names
on_done = Manager.on_done
start = Manager.start
command = Command.command
InputOverlay = PromptOverlay
