import importlib.util, sys, os
from types import ModuleType

class DummyFlask:
    def __init__(self, *args, **kwargs):
        pass
    def route(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

flask = ModuleType('flask')
flask.Flask = DummyFlask
flask.flash = lambda *args, **kwargs: None
flask.jsonify = lambda *args, **kwargs: None
flask.redirect = lambda *args, **kwargs: None
flask.render_template = lambda *args, **kwargs: None
flask.request = None
flask.send_file = lambda *args, **kwargs: None
flask.url_for = lambda *args, **kwargs: None
flask.after_this_request = lambda f: f
sys.modules['flask'] = flask

werkzeug_utils = ModuleType('werkzeug.utils')
werkzeug_utils.secure_filename = lambda filename: filename
sys.modules['werkzeug.utils'] = werkzeug_utils

yt_dlp = ModuleType('yt_dlp')
setattr(yt_dlp, 'YoutubeDL', object)
sys.modules['yt_dlp'] = yt_dlp

spec = importlib.util.spec_from_file_location('app', r'f:\MY FILES\Projects\yt-downloader\app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

os.makedirs(r'f:\tmp', exist_ok=True)
with open(r'f:\tmp\in.mp4', 'wb') as f:
    f.write(b'0' * 5720000)

options = {
    'resolution': 'original',
    'aspect_ratio': 'original',
    'start_trim': 0,
    'end_trim': 0,
    'target_mode': 'size',
    'target_percentage': 0,
    'target_size_mb': 5,
}
print('build pass1:', app.build_compression_command(r'f:\tmp\in.mp4', r'f:\tmp\out.mp4', options, pass_number=1, pass_log=r'f:\tmp\ffmpeg_pass'))
print('build pass2:', app.build_compression_command(r'f:\tmp\in.mp4', r'f:\tmp\out.mp4', options, pass_number=2, pass_log=r'f:\tmp\ffmpeg_pass'))
print('build normal:', app.build_compression_command(r'f:\tmp\in.mp4', r'f:\tmp\out.mp4', options))
