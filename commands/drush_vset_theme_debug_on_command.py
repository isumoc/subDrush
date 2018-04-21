import threading
from ..lib.drush import DrushAPI
from ..lib.thread_progress import ThreadProgress

import sublime_plugin


class DrushVsetThemeDebugOnCommand(sublime_plugin.WindowCommand):
    """
    A command that sets theme Debug to On.
    """
    def run(self):
        drush_api = DrushAPI(self.window.active_view())
        thread = DrushVsetThemeDebugOnThread(self.window, drush_api)
        thread.start()
        ThreadProgress(thread,
                       'Setting Theme Debug On',
                       "Theme Debug Set Now On" %
                       drush_api.get_drupal_root())


class DrushVsetThemeDebugOnThread(threading.Thread):
    """
    A thread to clear all caches.
    """
    def __init__(self, window, drush_api):
        self.window = window
        self.drush_api = drush_api
        threading.Thread.__init__(self)

    def run(self):
        args = list()
        args.append('theme_debug')
        args.append('1')
        self.drush_api.run_command('vset', args, list())
