import importlib
import sys

try:
    importlib.import_module('bot.bot')
    print('BOT_IMPORT_OK')
except Exception as e:
    print('BOT_IMPORT_FAIL:', repr(e))
    sys.exit(1)

