"""Stable source-app target for the channel-specific Windows shortcut."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if sys.argv[1:] == ['Dev']:
    os.environ['LINGUAR_DEV_MODE'] = '1'
elif sys.argv[1:] != ['Main']:
    raise SystemExit('Launch the installed Trial app instead.')
import home_web
home_web.main()
