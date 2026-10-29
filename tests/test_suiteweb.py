"""suiteweb.py, shared with Grabbit and Dropshift: the full-size picture behind a smaller copy, and
a site's robot check.

    %LOCALAPPDATA%\\HanamiBuild\\venv\\Scripts\\python.exe tests\\test_suiteweb.py

Each site's rule is checked on an address of the kind its pages show (real ones, 2026-10-29);
best() asks a web server of the test's own on 127.0.0.1. Keytap\\.dev\\stock\\live_check.py
runs the rules against the real sites.
"""

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from hanami import suiteweb  # noqa: E402

# (shown, full): what a page shows, and the site's own full-size picture.
SITES = [
    ('https://images.stockcake.com/public/d/d/f/ddf7aab9-167f-4728-bc3c-46252abde868_large/blossom-stockcake.jpg',
     'https://images.stockcake.com/public/d/d/f/ddf7aab9-167f-4728-bc3c-46252abde868/blossom-stockcake.jpg'),
    ('https://images.unsplash.com/photo-1555231955-348aa2312e19?w=640&q=80&auto=format&fit=crop',
     'https://images.unsplash.com/photo-1555231955-348aa2312e19'),
    ('https://images.pexels.com/photos/56866/garden-rose-red-pink-56866.jpeg?auto=compress&cs=tinysrgb&w=600',
     'https://images.pexels.com/photos/56866/garden-rose-red-pink-56866.jpeg'),
    ('https://cdn.pixabay.com/photo/2015/04/23/22/00/tree-736885_640.jpg',
     'https://cdn.pixabay.com/photo/2015/04/23/22/00/tree-736885_1280.jpg'),
    ('https://cdn.pixabay.com/photo/2015/04/23/22/00/tree-736885_960_720.jpg',
     'https://cdn.pixabay.com/photo/2015/04/23/22/00/tree-736885_1280.jpg'),
    ('https://live.staticflickr.com/4181/34452256202_54fd80c3b2_m.jpg',
     'https://live.staticflickr.com/4181/34452256202_54fd80c3b2_b.jpg'),
    ('https://live.staticflickr.com/3951/33484956541_9a3a4f9ecd.jpg',
     'https://live.staticflickr.com/3951/33484956541_9a3a4f9ecd_b.jpg'),
    ('https://cdn.stocksnap.io/img-thumbs/280h/flower-buds_PQSTEMKXUA.jpg',
     'https://cdn.stocksnap.io/img-thumbs/960w/flower-buds_PQSTEMKXUA.jpg'),
    ('https://burst.shopifycdn.com/photos/pink-rose-on-pink.jpg?width=1000&format=pjpg&exif=0&iptc=0',
     'https://burst.shopifycdn.com/photos/pink-rose-on-pink.jpg'),
    ('https://img.magnific.com/free-psd/pink-cherry-blossoms_191095-86226.jpg?semt=ais_hybrid&w=740&q=80',
     'https://img.magnific.com/free-psd/pink-cherry-blossoms_191095-86226.jpg?w=2000'),
    ('https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Example.jpg/330px-Example.jpg',
     'https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg'),
    ('https://res.cloudinary.com/demo/image/upload/w_300,c_scale/sample.jpg',
     'https://res.cloudinary.com/demo/image/upload/sample.jpg'),
    ('https://res.cloudinary.com/demo/image/upload/c_fill,h_200,w_200/v1312461204/sample.jpg',
     'https://res.cloudinary.com/demo/image/upload/v1312461204/sample.jpg'),
    ('https://preview.redd.it/abc123def.jpg?width=640&crop=smart&auto=webp&s=1f2e',
     'https://i.redd.it/abc123def.jpg'),
    ('https://pbs.twimg.com/media/GZ9x0qGWYAAm8Kk?format=jpg&name=small',
     'https://pbs.twimg.com/media/GZ9x0qGWYAAm8Kk?format=jpg&name=orig'),
    ('https://pbs.twimg.com/media/GZ9x0qGWYAAm8Kk.png:large',
     'https://pbs.twimg.com/media/GZ9x0qGWYAAm8Kk?format=png&name=orig'),
    ('https://i.pinimg.com/236x/02/29/d8/0229d8958187347a649bef46abce2e1d.jpg',
     'https://i.pinimg.com/originals/02/29/d8/0229d8958187347a649bef46abce2e1d.jpg'),
    ('https://i.imgur.com/aBcD123m.jpg', 'https://i.imgur.com/aBcD123.jpg'),
    ('https://lh3.googleusercontent.com/abcDEF123=w400-h300-c', 'https://lh3.googleusercontent.com/abcDEF123=s0'),
    ('https://m.media-amazon.com/images/I/51Z+AWDo+eL._AC_UL320_.jpg',
     'https://m.media-amazon.com/images/I/51Z+AWDo+eL.jpg'),
    ('https://i.ebayimg.com/images/g/AbCdEf/s-l300.jpg', 'https://i.ebayimg.com/images/g/AbCdEf/s-l1600.jpg'),
    ('https://i.etsystatic.com/12345/r/il/abcdef/1234567890/il_340x270.1234567890_ab12.jpg',
     'https://i.etsystatic.com/12345/r/il/abcdef/1234567890/il_fullxfull.1234567890_ab12.jpg'),
]


class RuleTests(unittest.TestCase):
    def test_each_sites_own_way(self):
        for shown, full in SITES:
            with self.subTest(shown):
                found = suiteweb.candidates(shown)
                self.assertTrue(found, 'no rule')
                self.assertEqual(found[0], (full, True))

    def test_the_full_picture_has_none(self):
        for _, full in SITES:
            with self.subTest(full):
                self.assertNotIn(True, [sure for _, sure in suiteweb.candidates(full)])

    def test_ways_many_sites_share(self):
        shared = {
            'https://ma.tt/files/2026/09/b97df-all-roads-lead-to-om-1-1024x452.jpg':
                'https://ma.tt/files/2026/09/b97df-all-roads-lead-to-om-1.jpg',             # WordPress
            'https://shop.example.com/cdn/shop/files/rose_640x.jpg?v=17':
                'https://shop.example.com/cdn/shop/files/rose.jpg?v=17',                    # Shopify
            'https://cdn.example.com/p/rose.jpg?w=640&h=480&fit=crop&v=3':
                'https://cdn.example.com/p/rose.jpg?v=3',                                   # imgix and the like
        }
        for shown, full in shared.items():
            with self.subTest(shown):
                self.assertIn((full, False), suiteweb.candidates(shown))

    def test_resizing_servers(self):
        self.assertEqual(suiteweb.candidates('https://site.example/_next/image?url=%2Fp%2Fa.jpg&w=640')[-1],
                         ('https://site.example/p/a.jpg', True))
        self.assertEqual(suiteweb.candidates('https://i0.wp.com/ma.tt/files/2026/09/image-1-1024x768.png?resize=640%2C480')[0],
                         ('https://ma.tt/files/2026/09/image-1.png', False))
        from urllib.parse import quote
        stockcake = 'https://images.stockcake.com/public/d/d/f/ddf7aab9-167f-4728-bc3c-46252abde868'
        found = suiteweb.candidates(f'https://stockcake.com/_next/image?url={quote(stockcake + "_large/b.jpg", safe="")}&w=384')
        self.assertEqual(found[0], (f'{stockcake}/b.jpg', True))

    def test_not_pictures_or_paid_ones(self):
        for url in ('https://www.youtube.com/watch?v=abc', 'https://example.com/page?w=640',
                    'https://plus.unsplash.com/premium_photo-1?w=640',                      # Unsplash+, paid
                    'https://img.freepik.com/premium-photo/rose_123-456.jpg?w=740',         # Freepik Premium
                    'https://www.python.org/static/img/python-logo.png'):
            with self.subTest(url):
                self.assertNotIn(True, [sure for _, sure in suiteweb.candidates(url)])

    def test_robot_checks(self):
        self.assertTrue(suiteweb.robot_check(403, {'cf-mitigated': 'challenge', 'server': 'cloudflare'}))
        self.assertTrue(suiteweb.robot_check(503, {'server': 'cloudflare'}))
        self.assertFalse(suiteweb.robot_check(200, {'server': 'cloudflare'}))
        self.assertFalse(suiteweb.robot_check(403, {'server': 'nginx'}))


PICTURES = {'/small.jpg': 2_000, '/full.jpg': 90_000, '/banner_1200x1200.jpg': 5_000, '/banner.jpg': 3_000,
            '/a-640x480.jpg': 2_000, '/a.jpg': 80_000}


class Site(BaseHTTPRequestHandler):
    asked: list = []

    def _answer(self, body: bool):
        Site.asked.append((self.command, self.path))
        size = PICTURES.get(self.path)
        self.send_response(200 if size else 404)
        self.send_header('Content-Type', 'image/jpeg' if size else 'text/html')
        self.send_header('Content-Length', str(size or 0))
        self.end_headers()
        if body and size:
            self.wfile.write(b'\0' * size)

    def do_HEAD(self):
        self._answer(False)

    def do_GET(self):
        self._answer(True)

    def log_message(self, *args):
        pass


class BestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Site.asked.clear()

    def with_rule(self, shown, *fuller):
        rule = lambda url: [f'{self.base}{path}' for path in fuller] if url == f'{self.base}{shown}' else []  # noqa: E731
        return mock.patch.object(suiteweb, 'SITES', (rule,))

    def test_a_sites_own_way(self):
        with self.with_rule('/small.jpg', '/gone.jpg', '/full.jpg'):
            self.assertEqual(suiteweb.best(f'{self.base}/small.jpg'), f'{self.base}/full.jpg')
        self.assertEqual(Site.asked, [('HEAD', '/gone.jpg'), ('HEAD', '/full.jpg')], 'asked, not downloaded')

    def test_none_answers(self):
        with self.with_rule('/small.jpg', '/gone.jpg'):
            self.assertEqual(suiteweb.best(f'{self.base}/small.jpg'), f'{self.base}/small.jpg')

    def test_a_shared_way_only_when_larger(self):
        with mock.patch.object(suiteweb, 'SITES', ()):
            self.assertEqual(suiteweb.best(f'{self.base}/a-640x480.jpg'), f'{self.base}/a.jpg')
            # A name that only looks resized: the "full" one is smaller, so it is not taken.
            self.assertEqual(suiteweb.best(f'{self.base}/banner_1200x1200.jpg'), f'{self.base}/banner_1200x1200.jpg')

    def test_nothing_asked_without_a_rule(self):
        self.assertEqual(suiteweb.best('https://www.youtube.com/watch?v=abc'), 'https://www.youtube.com/watch?v=abc')
        self.assertEqual(Site.asked, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
