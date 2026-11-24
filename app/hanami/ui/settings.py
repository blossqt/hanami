"""Hanami's settings: starting with Windows, the edge panel (its edge, its tab, what is pinned to
it), the suite's appearance (light or dark, the glass's transparency, its animations), keeping quiet for games,
the sound-output hotkey, updates, and about Hanami.

The appearance is the whole suite's: what is chosen here is kept for every suite app
(suitetheme.set_mode, set_glass_clear, set_motion), and each one running takes it within seconds.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from .. import __version__
from ..catalog import SUITE
from . import icons, suitesettings, theme
from .suitesettings import glyph_font  # noqa: F401 - the icon font, read once in the warm-up (app.py)

SOURCE = 'https://github.com/blossqt/hanami'

UPDATE_CHOICES = {'install': 'Install', 'tell': 'Notify', 'off': 'Off'}
UPDATE_LINES = {
    'install': 'An app in use updates when it closes.',
    'tell': '',
    'off': 'Updates are checked only on request. Hanami does not update itself.',
}


_label, _section, _switch, _indent, _Nav = (suitesettings.label, suitesettings.section, suitesettings.switch,
                                            suitesettings.indent, suitesettings.Nav)


class SettingsWindow(QWidget):
    startup_changed = Signal(bool, list)
    updates_changed = Signal(bool, bool, bool)      # look by itself, tell me, install by itself (one choice)
    hanami_updates_changed = Signal(bool)           # Hanami updates itself
    sound_changed = Signal(bool, str)               # the hotkey on, the hotkey
    window_sound_changed = Signal(bool)             # the switch at the top of Hanami's window: shown or not
    text_changed = Signal(bool, str)                # copying text from the screen: the hotkey on, the hotkey
    output_chosen = Signal(str, str, str)           # 'speakers' or 'headphones', the output's id ('' for none), its name
    panel_changed = Signal(str)                     # the edge the panel slides out at: 'right', 'left' or '' (off)
    tab_changed = Signal(int, int, int)             # the panel's tab: its length and thickness (px), opacity at rest (%)
    pins_changed = Signal(list)                     # the panel's shortcuts: [pins.Pin]
    pages_changed = Signal(list)                    # the panel's pages: names from panel.PAGES, in order
    panel_apps_changed = Signal(list)               # the suite's apps left off the panel's apps page
    sensors_asked = Signal(str)                     # Hanami Sensors: '--install' (or update) or '--uninstall'
    brightness_changed = Signal(bool)               # the panel's brightness sliders: on or off
    buttons_changed = Signal(list)                  # the panel's buttons: names from panel.BUTTONS
    check_now = Signal()
    update_hanami_now = Signal()                    # put the newer Hanami in now, restarting it
    show_page = Signal(str)
    open_url = Signal(str)

    PAGES = [('gear', 'General'), ('sidebar', 'Edge panel'), ('palette', 'Appearance'), ('gamepad', 'Games'), ('speaker', 'Sound'),
             ('scan', 'Screen text'), ('refresh', 'Updates'), ('info', 'About')]

    def __init__(self, start_with: list[str], starts_with_windows: bool, updates: tuple[bool, bool, bool],
                 sound: tuple[bool, str] = (True, ''), panel_edge: str = 'right',
                 tab: tuple[int, int, int] | None = None, pinned: list | None = None,
                 panel_pages: list[str] | None = None, brightness_on: bool = True,
                 text: tuple[bool, str] = (True, ''), panel_buttons: list[str] | None = None,
                 window_sound: bool = True, panel_hidden: list[str] | None = None,
                 apps: list[str] | None = None):
        super().__init__()
        # the apps it has ticks for: all, but for one shown only once it is on this PC
        self._apps = [app for app in SUITE if apps is None or app.name in apps]
        self.setWindowTitle('Hanami settings')
        self.setWindowIcon(icons.app_icon())
        theme.frost(self, backdrop=theme.BACKDROP)
        theme.closes_on_escape(self)
        frame = suitesettings.SettingsFrame(self, icons.render_app_icon(28))
        self.nav, self.pages = frame.nav, frame.pages
        made = [self._general(start_with, starts_with_windows),
                self._edge_panel(panel_edge, tab, list(pinned or []), panel_pages, brightness_on,
                                 panel_buttons, panel_hidden or []),
                self._appearance(), self._games(), self._sound(*sound, window_sound), self._screen_text(*text),
                self._updates(*updates), self._about()]
        # Every page scrolls, as the other apps' do: one that didn't gave the window a least height
        # for each width, and Qt trimmed resizing drags to it.
        for (mark, title), widget in zip(self.PAGES, made):
            frame.add_widget(mark, title, self._scrolled(widget))
        theme.on_restyle(self._appearance_changed)

    def open_page(self, name: str) -> None:
        for index, (_, title) in enumerate(self.PAGES):
            if title.lower() == name.lower():
                self.nav.choose(index)

    # ------------------------------------------------------------------ pages

    _page = staticmethod(suitesettings.page)
    _scrolled = staticmethod(suitesettings.scrolled)

    def _general(self, start_with: list[str], starts_with_windows: bool) -> QWidget:
        page, layout = self._page('General', '')
        frame, box = _section('Starting up')
        holder, self.startup = _switch('Start Hanami when I sign in to Windows',
                                       'Hanami starts in the tray.',
                                       starts_with_windows)
        box.addWidget(holder)
        group, choices = suitesettings.group('Start with Hanami in the background')
        box.addWidget(group)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.start_with: dict[str, QCheckBox] = {}
        for index, app in enumerate(self._apps):
            check = QCheckBox(app.name)
            check.setChecked(app.name in start_with)
            check.setCursor(Qt.PointingHandCursor)
            check.toggled.connect(self._startup_edited)
            self.start_with[app.name] = check
            grid.addWidget(check, index // 2, index % 2)
        grid.setColumnStretch(2, 1)
        choices.addLayout(grid)
        self.startup.toggled.connect(self._startup_edited)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _edge_panel(self, panel_edge: str, tab: tuple[int, int, int] | None, pinned: list,
                    panel_pages: list[str] | None = None, brightness_on: bool = True,
                    panel_buttons: list[str] | None = None, panel_hidden: list[str] = ()) -> QWidget:
        from .panel import BUTTONS, PAGES, TAB_LIMITS, TAB_LOOK     # (the panel's sound switch is drawn from here)
        page, layout = self._page('Edge panel', '')
        frame, box = _section('')
        holder, self.panel_on = _switch('Slide out a panel at the edge of the screen',
                                        'It stays closed over games and full-screen windows.',
                                        bool(panel_edge))
        self.panel_on.toggled.connect(self._panel_edited)
        box.addWidget(holder)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_label('Edge'))
        self.panel_edges = QButtonGroup(self)
        self.edge_buttons: dict[str, QPushButton] = {}
        for name, title in (('left', 'Left'), ('right', 'Right')):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked((panel_edge or 'right') == name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(self._panel_edited)
            self.panel_edges.addButton(button)
            self.edge_buttons[name] = button
        row.addWidget(suitesettings.Segmented(list(self.edge_buttons.values())))
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(frame)
        frame, box = _section('Pages')
        chosen = panel_pages if panel_pages else list(PAGES)
        self.page_switches: dict[str, QCheckBox] = {}
        for name, title, about in (
                ('apps', 'Hanami suite', ''), ('pinned', 'Shortcuts', ''),
                ('stats', 'Stats', 'GPU load, memory and temperature require an NVIDIA graphics card.')):
            holder, check = _switch(title, about, name in chosen)
            check.toggled.connect(self._pages_edited)
            box.addWidget(holder)
            self.page_switches[name] = check
            if name == 'apps':                      # which of the suite's apps that page shows
                box.addWidget(self._panel_apps(panel_hidden))
        layout.addWidget(frame)
        frame, box = _section('Buttons')
        shown = list(BUTTONS) if panel_buttons is None else panel_buttons
        self.button_switches: dict[str, QCheckBox] = {}
        for name, title, about in (
                ('levels', 'Volume and brightness', ''),
                ('output', 'Sound output', 'Switches between the speakers and headphones chosen under Sound.'),
                ('mic', 'Microphone', '')):
            holder, check = _switch(title, about, name in shown)
            check.toggled.connect(self._buttons_edited)
            box.addWidget(holder)
            self.button_switches[name] = check
        layout.addWidget(frame)
        frame, box = _section('Brightness')
        holder, self.brightness_switch = _switch('Monitor brightness', 'Requires DDC/CI, turned on in each '
                                                 'monitor’s own menu.',
                                                 brightness_on)
        self.brightness_switch.toggled.connect(self.brightness_changed)
        box.addWidget(holder)
        self.monitors_found = _label('Looking for monitors…', suitesettings.SMALL, role='dim', wrap=True)
        _indent(self.monitors_found)
        self.monitors_found.setVisible(brightness_on)
        self.brightness_switch.toggled.connect(self.monitors_found.setVisible)
        box.addWidget(self.monitors_found)
        layout.addWidget(frame)
        frame, box = _section('CPU temperature')
        box.addWidget(_label('Requires the Hanami Sensors service. Installing it requires administrator '
                             'permission.', suitesettings.SMALL, role='dim',
                             wrap=True))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.sensors_status = _label('')
        row.addWidget(self.sensors_status, 1)
        self.sensors_install = QPushButton('Install')
        self.sensors_install.clicked.connect(lambda: self.sensors_asked.emit('--install'))
        self.sensors_remove = QPushButton('Remove')
        self.sensors_remove.clicked.connect(lambda: self.sensors_asked.emit('--uninstall'))
        for button in (self.sensors_install, self.sensors_remove):
            button.setCursor(Qt.PointingHandCursor)
            row.addWidget(button)
        box.addLayout(row)
        self.sensors_problem = _label('', suitesettings.SMALL, role='dim', wrap=True)
        self.sensors_problem.hide()
        box.addWidget(self.sensors_problem)
        layout.addWidget(frame)
        frame, box = _section('Tab')
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(suitesettings.ITEMS)
        self.tab_sliders: dict[str, QSlider] = {}
        for index, (name, title, unit, value, (least, most)) in enumerate(zip(
                ('length', 'thickness', 'opacity'), ('Tab length', 'Tab thickness', 'Tab opacity'),
                (' px', ' px', '%'), tab or TAB_LOOK, TAB_LIMITS)):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(least, most)
            slider.setValue(value)
            slider.setCursor(Qt.PointingHandCursor)
            slider.setAccessibleName(title)
            shown = _label(f'{value}{unit}', role='dim')
            shown.setMinimumWidth(48)
            slider.valueChanged.connect(lambda v, shown=shown, unit=unit: (shown.setText(f'{v}{unit}'),
                                                                           self._tab_edited()))
            grid.addWidget(_label(title), index, 0)
            grid.addWidget(slider, index, 1)
            grid.addWidget(shown, index, 2)
            self.tab_sliders[name] = slider
        grid.setColumnStretch(1, 1)
        box.addLayout(grid)
        layout.addWidget(frame)
        frame, box = _section('Shortcuts')
        self.pinned = pinned
        self._pin_rows = QVBoxLayout()
        self._pin_rows.setSpacing(8)
        box.addLayout(self._pin_rows)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.add_file = QPushButton('Add a program or file…')
        self.add_file.clicked.connect(self._choose_file)
        self.add_folder = QPushButton('Add a folder…')
        self.add_folder.clicked.connect(self._choose_folder)
        for button in (self.add_file, self.add_folder):
            button.setCursor(Qt.PointingHandCursor)
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.address = QLineEdit()
        self.address.setPlaceholderText('Website address')
        self.address.returnPressed.connect(self._add_website)
        self.add_site = QPushButton('Add website')
        self.add_site.setCursor(Qt.PointingHandCursor)
        self.add_site.clicked.connect(self._add_website)
        row.addWidget(self.address, 1)
        row.addWidget(self.add_site)
        box.addLayout(row)
        self.pin_note = _label('', suitesettings.SMALL, role='dim', wrap=True)
        box.addWidget(self.pin_note)
        self._show_pinned()
        self._panel_edited(emit=False)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _appearance(self) -> QWidget:
        page, layout = self._page('Appearance', 'Applies to every app in the suite.')
        frame, box = _section('Light or dark')
        row = QHBoxLayout()
        row.setSpacing(8)
        self.modes = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for name, title in theme.MODES.items():
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked(theme.mode() == name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, n=name: theme.set_mode(n))
            self.modes.addButton(button)
            self.mode_buttons[name] = button
        row.addWidget(suitesettings.Segmented(list(self.mode_buttons.values())))
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(frame)

        frame, box = _section('Glass')
        row = QHBoxLayout()
        row.setSpacing(12)
        self.clear_slider = QSlider(Qt.Horizontal)
        self.clear_slider.setRange(0, 100)
        self.clear_slider.setValue(theme.glass_clear())
        self.clear_slider.setCursor(Qt.PointingHandCursor)
        self.clear_slider.setAccessibleName('Glass transparency')
        self.clear_shown = _label(f'{theme.glass_clear()}%', role='dim')
        self.clear_shown.setMinimumWidth(48)
        self.clear_slider.valueChanged.connect(self._clear_edited)
        row.addWidget(_label('Transparency'))
        row.addWidget(self.clear_slider, 1)
        row.addWidget(self.clear_shown)
        box.addLayout(row)
        self._show_clear_enabled()
        if not theme.glass_on():
            box.addWidget(_label('Glass needs Windows 11 with transparency effects on (Settings > Personalisation > '
                                 'Colours).', suitesettings.SMALL, role='dim', wrap=True))
        layout.addWidget(frame)

        frame, box = _section('Motion')
        holder, self.motion = _switch('Animations', 'Also off when Windows’ animation effects are off.',
                                      theme.motion_chosen())
        self.motion.toggled.connect(theme.set_motion)
        box.addWidget(holder)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _games(self) -> QWidget:
        page, layout = self._page('Games', '')
        frame, box = _section('While a full-screen game is in front')
        holder, self.game_quiet = _switch('Keep the suite quiet', 'Notifications are held until the game is no '
                                          'longer in front.', theme.game_quiet_chosen())
        self.game_quiet.toggled.connect(self._game_edited)
        box.addWidget(holder)
        group, choices = suitesettings.group('Grabbit’s downloads')
        box.addWidget(group)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.game_downloads = QButtonGroup(self)
        self.download_buttons: dict[str, QPushButton] = {}
        for name, title in theme.GAME_DOWNLOADS.items():
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked(theme.game_downloads() == name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, n=name: theme.set_game_downloads(n))
            self.game_downloads.addButton(button)
            self.download_buttons[name] = button
        row.addWidget(suitesettings.Segmented(list(self.download_buttons.values())))
        row.addStretch(1)
        choices.addLayout(row)
        box.addWidget(_label('Slow down limits them to 1 MB/s download and 64 KB/s upload.', suitesettings.SMALL,
                             role='dim', wrap=True))
        self._game_edited(theme.game_quiet_chosen(), save=False)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _sound(self, on: bool, hotkey: str, window_sound: bool = True) -> QWidget:
        page, layout = self._page('Sound', '')
        frame, box = _section('Sound output')
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.output_choices: dict[str, QComboBox] = {}
        for row, (which, title) in enumerate((('speakers', 'Speakers'), ('headphones', 'Headphones'))):
            combo = QComboBox()
            combo.setMinimumWidth(320)
            combo.setCursor(Qt.PointingHandCursor)
            combo.currentIndexChanged.connect(lambda _, w=which: self._output_edited(w))
            self.output_choices[which] = combo
            grid.addWidget(_label(title), row, 0)
            grid.addWidget(combo, row, 1)
        grid.setColumnStretch(2, 1)
        box.addLayout(grid)
        holder, self.window_sound = _switch('Show the switch in Hanami’s window', '', window_sound)
        self.window_sound.toggled.connect(self.window_sound_changed)
        box.addWidget(holder)
        holder, self.sound_on = _switch('Switch between them with a hotkey', '', on)
        self.sound_on.toggled.connect(self._sound_edited)
        box.addWidget(holder)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_label('Hotkey'))
        self.sound_key = QKeySequenceEdit(QKeySequence(hotkey))
        self.sound_key.setMaximumSequenceLength(1)
        self.sound_key.setClearButtonEnabled(True)
        self.sound_key.setFixedWidth(200)
        self.sound_key.editingFinished.connect(self._sound_edited)
        # Its clear button empties it without editingFinished: the hotkey stayed until Hanami restarted.
        self.sound_key.keySequenceChanged.connect(lambda keys: keys.isEmpty() and self._sound_edited())
        row.addWidget(self.sound_key)
        row.addStretch(1)
        box.addLayout(row)
        self.sound_problem = _label('', suitesettings.SMALL, role='error', wrap=True)
        self.sound_problem.hide()
        box.addWidget(self.sound_problem)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _screen_text(self, on: bool, hotkey: str) -> QWidget:
        page, layout = self._page('Screen text', '')
        frame, box = _section('Copy text from the screen')
        holder, self.text_on = _switch('Open with a hotkey', '', on)
        self.text_on.toggled.connect(self._text_edited)
        box.addWidget(holder)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_label('Hotkey'))
        self.text_key = QKeySequenceEdit(QKeySequence(hotkey))
        self.text_key.setMaximumSequenceLength(1)
        self.text_key.setClearButtonEnabled(True)
        self.text_key.setFixedWidth(200)
        self.text_key.editingFinished.connect(self._text_edited)
        self.text_key.keySequenceChanged.connect(lambda keys: keys.isEmpty() and self._text_edited())
        row.addWidget(self.text_key)
        row.addStretch(1)
        box.addLayout(row)
        self.text_problem = _label('', suitesettings.SMALL, role='error', wrap=True)
        self.text_problem.hide()
        box.addWidget(self.text_problem)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def show_text_problem(self, problem: str) -> None:
        self.text_problem.setText(problem)
        self.text_problem.setVisible(bool(problem))

    def _text_edited(self, *_) -> None:
        keys = self.text_key.keySequence()
        hotkey = keys.toString(QKeySequence.PortableText) if not keys.isEmpty() else ''
        self.text_changed.emit(self.text_on.isChecked(), hotkey)

    def show_outputs(self, outputs: list, chosen: dict) -> None:
        """The sound outputs plugged in now, with the ones chosen as speakers and headphones
        ({'speakers': (id, name) or None, ...}) - one chosen but not plugged in is still there."""
        for which, combo in self.output_choices.items():
            picked = chosen.get(which)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('None', ('', ''))
            for output in outputs:
                combo.addItem(output.name, (output.id, output.name))
            if picked and picked[0] not in {output.id for output in outputs}:
                combo.addItem(f'{picked[1]} (not connected)', tuple(picked))
            index = next((i for i in range(combo.count()) if picked and combo.itemData(i)[0] == picked[0]), 0)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def show_sound_problem(self, problem: str) -> None:
        self.sound_problem.setText(problem)
        self.sound_problem.setVisible(bool(problem))

    def _updates(self, check: bool, notify: bool, auto: bool, hanami: bool = True) -> QWidget:
        page, layout = self._page('Updates', '')
        frame, box = _section('Updates')
        # One choice where there were three switches: telling or installing needs looking, and
        # an app that installs by itself needs no telling.
        group, choices = suitesettings.group('When an app has an update')
        box.addWidget(group)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.update_choice = QButtonGroup(self)
        self.update_buttons: dict[str, QPushButton] = {}
        chosen = 'off' if not check else 'install' if auto else 'tell'
        for name, title in UPDATE_CHOICES.items():
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked(name == chosen)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, n=name: self._updates_edited(n))
            self.update_choice.addButton(button)
            self.update_buttons[name] = button
        row.addWidget(suitesettings.Segmented(list(self.update_buttons.values())))
        row.addStretch(1)
        choices.addLayout(row)
        self.update_line = _label('', suitesettings.SMALL, role='dim', wrap=True)
        choices.addWidget(self.update_line)
        holder, self.hanami_auto = _switch('Update Hanami automatically', 'Hanami restarts to update.', hanami)
        self.hanami_auto.toggled.connect(self.hanami_updates_changed)
        box.addWidget(holder)
        self._show_update_choice(chosen)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.check_button = QPushButton('Check for updates')
        self.check_button.setCursor(Qt.PointingHandCursor)
        self.check_button.clicked.connect(self.check_now)
        row.addWidget(self.check_button)
        self.checked = _label('', suitesettings.SMALL, role='dim')
        row.addWidget(self.checked, 1)
        self.update_now = QPushButton('Update Hanami')
        self.update_now.setProperty('role', 'primary')
        self.update_now.setCursor(Qt.PointingHandCursor)
        self.update_now.clicked.connect(self.update_hanami_now)
        self.update_now.hide()                      # until there is a newer Hanami to put in
        row.addWidget(self.update_now)
        box.addSpacing(4)
        box.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _about(self) -> QWidget:
        page, layout = self._page('About', '')
        frame, box = _section('Hanami')
        row = QHBoxLayout()
        row.setSpacing(16)
        logo = theme.Label()
        logo.setPixmap(icons.render_app_icon(64))
        row.addWidget(logo, 0, Qt.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(16)                        # title, text and buttons evenly apart, as on the cards
        words.addWidget(suitesettings.heading(f'Hanami {__version__}', 17))
        words.addWidget(_label('Hanami opens, installs and updates the suite’s apps.', suitesettings.SMALL, role='dim', wrap=True))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        notes = QPushButton('Release notes')
        notes.clicked.connect(lambda: self.show_page.emit('Hanami'))
        source = QPushButton('Source code')
        source.clicked.connect(lambda: self.open_url.emit(SOURCE))
        for button in (notes, source):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch(1)
        words.addLayout(buttons)
        row.addLayout(words, 1)
        box.addLayout(row)
        layout.addWidget(frame)
        frame, box = _section('Thanks')
        self.credit = _label('', suitesettings.SMALL, role='dim', wrap=True)
        self.credit.setTextFormat(Qt.RichText)
        self.credit.setOpenExternalLinks(True)
        self._show_credit()
        box.addWidget(self.credit)
        box.addWidget(_label('MIT licence · made by blossqt', suitesettings.SMALL, role='dim'))
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ changes

    def _startup_edited(self, *_, emit: bool = True) -> None:
        if emit:
            self.startup_changed.emit(self.startup.isChecked(),
                                      [name for name, check in self.start_with.items() if check.isChecked()])

    def _game_edited(self, on: bool, save: bool = True) -> None:
        if save:
            theme.set_game_quiet(on)
        for button in self.download_buttons.values():
            button.setEnabled(on)

    def _panel_edited(self, *_, emit: bool = True) -> None:
        on = self.panel_on.isChecked()
        for button in [*self.edge_buttons.values(), *self.tab_sliders.values(), *self.button_switches.values()]:
            button.setEnabled(on)
        self._buttons_edited(emit=False)
        if hasattr(self, 'pin_note'):
            self._show_pinned(self.pin_note.text() if self.pin_note.isVisible() else '')
        if hasattr(self, 'page_switches'):
            self._pages_edited(emit=False)
        edge = next((name for name, button in self.edge_buttons.items() if button.isChecked()), 'right')
        if emit:
            self.panel_changed.emit(edge if on else '')

    def show_sensors(self, state, busy: str = '', problem: str = '') -> None:
        """Hanami Sensors as it is (sensors.State): installed or not, up to date or not, what it
        needs - and, while its setup runs, that (busy); what went wrong, if it did."""
        install, remove = self.sensors_install, self.sensors_remove
        install.setText('Update' if state.outdated else 'Install')
        install.setVisible(not state.installed or state.outdated)
        remove.setVisible(bool(state.installed))
        ready = bool(state.bundled) and state.pawnio and state.dotnet
        if busy:
            text = busy
        elif not state.bundled:
            text = 'Not in this build of Hanami.'
        elif state.installed and state.outdated:
            text = f'Version {state.installed} is installed. Version {state.bundled} is available.'
        elif state.installed:
            text = 'Installed.'
        elif not state.pawnio:
            text = 'Requires PawnIO, which is not installed (pawnio.eu).'
        elif not state.dotnet:
            text = 'Requires the Microsoft .NET 10 Runtime.'
        else:
            text = 'Not installed.'
        self.sensors_status.setText(text)
        install.setEnabled(ready and not busy)
        remove.setEnabled(not busy)
        self.sensors_problem.setText(problem)
        self.sensors_problem.setVisible(bool(problem))

    def show_monitors(self, names: list[str] | None) -> None:
        """The monitors with a brightness to set, by name - None while they are still being looked for."""
        if names is None:
            text = 'Looking for monitors…'
        elif names:
            text = 'Found: ' + ', '.join(names) + '.'
        else:
            text = 'No monitor has DDC/CI turned on.'
        self.monitors_found.setText(text)

    def _panel_apps(self, hidden) -> QWidget:
        """A tick for each of the suite's apps, two by two, as under Starting up."""
        group, choices = suitesettings.group('Apps')
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.panel_app_checks: dict[str, QCheckBox] = {}
        for index, app in enumerate(self._apps):
            check = QCheckBox(app.name)
            check.setChecked(app.name not in hidden)
            check.setCursor(Qt.PointingHandCursor)
            check.toggled.connect(self._panel_apps_edited)
            self.panel_app_checks[app.name] = check
            grid.addWidget(check, index // 2, index % 2)
        grid.setColumnStretch(2, 1)
        choices.addLayout(grid)
        return group

    def _panel_apps_edited(self, *_) -> None:
        self.panel_apps_changed.emit([name for name, check in self.panel_app_checks.items() if not check.isChecked()])

    def _pages_edited(self, *_, emit: bool = True) -> None:
        """The panel's pages: at least one stays - the last one on can't be turned off. The apps
        page's apps are chosen only while it is on."""
        names = [name for name, check in self.page_switches.items() if check.isChecked()]
        on = self.panel_on.isChecked()
        for check in self.page_switches.values():
            check.setEnabled(on and not (check.isChecked() and len(names) == 1))
        for check in self.panel_app_checks.values():
            check.setEnabled(on and 'apps' in names)
        if emit and names:
            self.pages_changed.emit(names)

    def _buttons_edited(self, *_, emit: bool = True) -> None:
        """The panel's buttons. The brightness sliders are in the volume and brightness drop-down,
        so they have nothing to choose without it."""
        names = [name for name, check in self.button_switches.items() if check.isChecked()]
        self.brightness_switch.setEnabled(self.panel_on.isChecked() and 'levels' in names)
        if emit:
            self.buttons_changed.emit(names)

    def _tab_edited(self) -> None:
        s = self.tab_sliders
        self.tab_changed.emit(s['length'].value(), s['thickness'].value(), s['opacity'].value())

    # ------------------------------------------------------------------ what is pinned

    def _show_pinned(self, note: str = '') -> None:
        """The list of what is pinned - each with its icon, where it is and a button to unpin it -
        and the buttons to pin more, while there is room."""
        from . import pins
        while self._pin_rows.count():
            item = self._pin_rows.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()                # at once: deleted only once Qt next gets round to it
                item.widget().deleteLater()
        ratio = self.devicePixelRatioF()
        for index, pin in enumerate(self.pinned):
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(12)
            icon = theme.Label()
            icon.setPixmap(pins.icon(pin, 20, ratio))
            line.addWidget(icon)
            line.addWidget(_label(pin.name))
            where = _label('', suitesettings.SMALL, role='dim')
            where.setText(QFontMetrics(where.font()).elidedText(pin.target, Qt.ElideMiddle, 300))
            line.addWidget(where, 1)
            remove = QPushButton('Remove')
            remove.setCursor(Qt.PointingHandCursor)
            remove.setAccessibleName(f'Remove {pin.name}')
            remove.clicked.connect(lambda _=False, i=index: self._remove_pin(i))
            line.addWidget(remove)
            self._pin_rows.addWidget(row)
        if not self.pinned:
            self._pin_rows.addWidget(_label('No shortcuts yet.', suitesettings.SMALL, role='dim'))
        room = len(self.pinned) < pins.MOST
        for widget in (self.add_file, self.add_folder, self.address, self.add_site):
            widget.setEnabled(room and self.panel_on.isChecked())
        self.pin_note.setText(note or ('' if room else f'The panel holds up to {pins.MOST} shortcuts.'))
        self.pin_note.setVisible(bool(self.pin_note.text()))

    def _pin(self, pin) -> None:
        from . import pins
        if any(p.kind == pin.kind and p.target.lower() == pin.target.lower() for p in self.pinned):
            self._show_pinned(f'{pin.name} is already pinned.')
            return
        if len(self.pinned) >= pins.MOST:
            return
        self.pinned = self.pinned + [pin]
        self.pins_changed.emit(list(self.pinned))
        self._show_pinned()

    def _remove_pin(self, index: int) -> None:
        self.pinned = [pin for i, pin in enumerate(self.pinned) if i != index]
        self.pins_changed.emit(list(self.pinned))
        self._show_pinned()

    def _choose_file(self) -> None:
        from . import pins
        # A shortcut stays a shortcut: Discord's, say, starts it through its updater.
        path, _ = QFileDialog.getOpenFileName(self, 'Add a program or file', str(Path.home() / 'Desktop'),
                                              'All files (*)', options=QFileDialog.DontResolveSymlinks)
        if path:
            self._pin(pins.for_path(path))

    def _choose_folder(self) -> None:
        from . import pins
        path = QFileDialog.getExistingDirectory(self, 'Add a folder', str(Path.home()))
        if path:
            self._pin(pins.for_path(path))

    def _add_website(self) -> None:
        from . import pins
        pin = pins.for_address(self.address.text())
        if pin is None:
            self._show_pinned('That is not a website address.' if self.address.text().strip() else '')
            return
        self.address.clear()
        self._pin(pin)

    def _sound_edited(self, *_) -> None:
        keys = self.sound_key.keySequence()
        hotkey = keys.toString(QKeySequence.PortableText) if not keys.isEmpty() else ''
        self.sound_changed.emit(self.sound_on.isChecked(), hotkey)

    def _output_edited(self, which: str) -> None:
        combo = self.output_choices[which]
        if combo.signalsBlocked():
            return
        output_id, name = combo.currentData() or ('', '')
        self.output_chosen.emit(which, output_id, name)

    def _updates_edited(self, choice: str) -> None:
        self._show_update_choice(choice)
        self.updates_changed.emit(choice != 'off', choice != 'off', choice == 'install')

    def _show_update_choice(self, choice: str) -> None:
        self.update_line.setText(UPDATE_LINES[choice])
        self.update_line.setVisible(bool(UPDATE_LINES[choice]))
        self.hanami_auto.setEnabled(choice != 'off')        # it finds its own updates the same way

    def _show_credit(self) -> None:
        link = f'style="color:{theme.ink()}; text-decoration:none"'
        self.credit.setText(f'Photos by <a href="https://unsplash.com/photos/pkpqoBp11Jc" {link}>Mi Min</a> (this window) '
                            f'and <a href="https://unsplash.com/photos/j3TrGxN_rCM" {link}>Yan Liu</a> (edge panel) '
                            f'on Unsplash.')

    def show_hanami_update(self, version: str, updating: bool) -> None:
        """The button to update Hanami now: with a newer one (version) to put in - and, once
        asked, what it is doing until Hanami restarts."""
        self.update_now.setVisible(bool(version))
        self.update_now.setEnabled(not updating)
        self.update_now.setText(f'Updating to {version}…' if updating else f'Update to {version} now')

    def show_checked(self, text: str, checking: bool) -> None:
        self.checked.setText(text)
        self.check_button.setEnabled(not checking)

    def _clear_edited(self, value: int) -> None:
        self.clear_shown.setText(f'{value}%')
        theme.set_glass_clear(value)

    def _show_clear_enabled(self) -> None:
        """The transparency slider works only where there is glass."""
        self.clear_slider.setEnabled(theme.glass_on())

    def _appearance_changed(self) -> None:
        """The look, light or dark, or the animations changed (here, or in another copy): the
        choices show it."""
        try:
            for name, button in self.mode_buttons.items():
                button.setChecked(theme.mode() == name)
            self._show_clear_enabled()
            if self.clear_slider.value() != theme.glass_clear() and not self.clear_slider.isSliderDown():
                self.clear_slider.blockSignals(True)
                self.clear_slider.setValue(theme.glass_clear())
                self.clear_shown.setText(f'{theme.glass_clear()}%')
                self.clear_slider.blockSignals(False)
            if self.motion.isChecked() != theme.motion_chosen():
                self.motion.blockSignals(True)
                self.motion.setChecked(theme.motion_chosen())
                self.motion.blockSignals(False)
            for name, button in self.download_buttons.items():
                button.setChecked(theme.game_downloads() == name)
            for line in self.findChildren(QLabel, 'about'):
                _indent(line)
            self._show_credit()
            self.nav.update()
        except RuntimeError:                                # the window has gone
            pass
