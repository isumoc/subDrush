import os
import pickle
import hashlib
import fnmatch
import subprocess
import json
import time
import shutil
import copy

import sublime

from ..lib.output import Output


class DrushAPI(object):

    def __init__(self, view):
        """
        The `view` object is self.window.active_view() and is used to identify
        the Drupal root.
        """
        self.drupal_root = ""
        self.working_dir = ""
        if view:
            self.working_dir = view.window().folders()
            if len(self.working_dir) > 0:
                self.set_working_dir(self.working_dir[0])
            else:
                # If we only have one file open, set working dir based on the
                # directory that the open file resides in.
                self.working_dir = os.path.dirname(view.file_name())
            self.drupal_root = self.get_drupal_root()

    def check_requirements(self):
        """
        Check if user has Drush 6 installed.
        """
        major_version = self.get_drush_version()
        if major_version < 6:
            print("Drush major version outdated: %d" % major_version)
            sublime.status_message('Please upgrade to Drush 6!')

    def get_drush_version(self):
        """
        Return the Drush major version (5, 6 etc).
        """
        result = subprocess.Popen([self.get_drush_path(),
                                  '--version',
                                  '--pipe'],
                                  stdout=subprocess.PIPE).communicate(
            )[0].decode('utf-8')
        if not result:
            return 0
        return int(result[:1])

    def get_drush_path(self):
        """
        Get the path to the Drush executable. It's either in Packages or
        Installed Packages, depending on the user's installation method.
        If either of those fail, check for system-wide Drush.
        """
        print('subDrush: Using /usr/local/bin/drush.')
        return '/usr/local/bin/drush'

    def load_command_info(self, command):
        """
        Check if cached data exists. If cache is older than a minute, don't
        use it.
        """
        commands = dict()
        bin = self.get_cache_bin(self.get_drupal_root()) + "/commands"
        if os.path.isfile(bin):
            last_modified = os.path.getmtime(bin)
            if (time.time() - last_modified < 360):
                cache_bin = open(bin, 'rb')
                data = pickle.load(cache_bin)
                cache_bin.close()
                if command in data[u'core'][u'commands']:
                    commands = data[u'core'][u'commands'][command]
                    return commands
        data = json.loads(
            subprocess.Popen([self.get_drush_path(), '--format=json'],
                             stdout=subprocess.PIPE
                             ).communicate()[0].decode('utf-8'))
        output = open(bin, 'wb')
        pickle.dump(data, output)
        output.close()
        commands = data[u'core'][u'commands'][command]
        return commands

    def load_command_args(self, command):
        """
        Loads valid arguments for a command. This is useful for identifying,
        for example, which cache bins to display in a given environment.
        """
        bin = self.get_cache_bin(
            self.get_drupal_root() + "/" + command) + "/" + command
        if os.path.isfile(bin):
            cache_bin = open(bin, 'rb')
            last_modified = os.path.getmtime(bin)
            if (time.time() - last_modified < 360):
                args = pickle.load(cache_bin)
                cache_bin.close()
                return args
        args = subprocess.Popen([self.get_drush_path(),
                                '--root=%s' % self.get_drupal_root(),
                                '--pipe', command],
                                stdout=subprocess.PIPE
                                ).communicate()[0].decode('utf-8').splitlines()
        output = open(bin, 'wb')
        pickle.dump(args, output)
        output.close()
        return args

    def build_command_list(self):
        """
        Build the command list to pass to subprocess. We are adding the path
        to drush, then the path to the Drupal root.
        """
        command = []
        command.append(self.get_drush_path())
        command.append('--root=%s' % self.get_drupal_root())
        return command

    def parse_backend_output(self, data, type="normal"):
        data_raw = copy.copy(data).replace('\0', '')
        data = data.replace('\0', '')
        backend_json = dict(log=list(), message=list(), message_raw='')
        backend_output = ''
        message_raw = ''
        message_type = "log"
        for line in data.splitlines():
            if 'DRUSH_BACKEND:' in line:
                data_raw.replace(line, '')
                backend_output = line.replace('DRUSH_BACKEND:', '')
            elif ('DRUSH_BACKEND_OUTPUT_START>>>' in line):
                data_raw.replace(line, '')
                message_type = "message"
                backend_output = line.replace(
                    'DRUSH_BACKEND_OUTPUT_START>>>',
                    '').replace('<<<DRUSH_BACKEND_OUTPUT_END', '')
            else:
                # Build the string of data to display to user.
                message_raw += "%s\n" % line
            try:
                json_data = json.loads(backend_output)
                backend_json[message_type].append(json_data)
            except Exception as e:
                print('subDrush: Error on json.loads: %s' % e)
        backend_json['message_raw'] = message_raw
        return backend_json

    def run_command(self, command, args, options):
        """
        Run a Drush command. args and options must both be lists.
        """
        cmd = self.build_command_list()
        cmd.append(command)
        if args:
            for arg in args:
                cmd.append(arg)
        if options:
            for opt in options:
                cmd.append(opt)
        cmd.append('--nocolor')
        cmd.append('--backend')

        print('subDrush: Call to Drush: %s' % ' '.join(cmd))
        try:
            backend_output = subprocess.check_output(cmd,
                                                     stderr=subprocess.STDOUT,
                                                     universal_newlines=True)
            data = self.parse_backend_output(backend_output)
            if data['message_raw']:
                return data['message_raw'].replace('\n', "\n")
            elif data['message'][0]['output']:
                return data['message'][0]['output'].replace('\n', "\n")
            else:
                print('subDrush: Failed to get output!')
                return 'Failed to get output!'
        except subprocess.CalledProcessError as e:
            data = self.parse_backend_output(e.output, "error")
            error_log = data['message'][0]['error_log']
            pairs = [(k, v) for (k, v) in error_log.items()]
            error_string = ''
            for k, v in pairs:
                # Format as YAML
                if error_string:
                    error_string = ''.join("%s\n%s: \"%s\""
                                           % (error_string, k, v[0]))
                else:
                    error_string = ''.join("%s: \"%s\"" % (k, v[0]))
            print('subDrush: Error returned from Drush: %s'
                  % error_string)
            cmd_string_error = 'COMMAND_FAILURE: "%s"' % ' '.join(cmd)
            Output(sublime.active_window(), 'drush-error', 'YAML',
                   cmd_string_error + "\n" + error_string).render()
            return False

    def get_local_site_aliases(self):
        """
        Returns a list of local site aliases.
        """
        options = list()
        options.append('--local')
        options.append('--format=json')
        aliases = self.run_command('site-alias', list(), options)
        if not aliases:
            return False
        aliases = json.loads(aliases)
        local_aliases = list()
        for alias, values in aliases.items():
            local_aliases.append(values[u'#name'].rsplit('.', 1)[0])
        return local_aliases

    def get_site_alias_from_drupal_root(self, directory):
        """
        Returns a string of the alias name that corresponds
        to `directory`, or False if an alias could not be found.
        Alias name will look like `@example.local`
        """
        options = list()
        options.append('-r')
        options.append('--local')
        options.append('--full')
        options.append('--format=json')
        drush_aliases = self.run_command('site-alias', list(), options)

        if not drush_aliases:
            return False
        drush_aliases = json.loads(drush_aliases)
        for alias, values in drush_aliases.items():
            if 'root' in values and directory == values[u'root'].replace(
                    '\/', '/'):
                return values['#name'].replace('@', '').rsplit('.', 1)[0]
        return False

    def set_working_dir(self, directory):
        """
        Sets the working directory.
        """
        self.working_dir = directory

    def get_drupal_root(self):
        """
        Returns the path to Drupal root, based on looking at self.working_dir
        """
        if self.drupal_root:
            return self.drupal_root
        if not self.working_dir:
            # If the working directory hasn't been set, return "drush"
            print('Working directory is not set, returning "drush"')
            return 'drush'

        bin = self.get_cache_bin(self.working_dir) + "/drupal_root"
        if os.path.isfile(bin):
            bin = open(bin, 'rb')
            last_modified = os.path.getmtime(bin.name)
            # If older than 24 hours, refresh cache.
            if (time.time() - last_modified < 86400):
                self.drupal_root = pickle.load(bin)
                bin.close()
                if os.path.isdir(self.drupal_root):
                    print('Load Drupal root from cache %s' % self.drupal_root)
                    return self.drupal_root
            else:
                print('Cache is expired!')
                bin.close()
        else:
            print('Cache bin is not a file, cannot load.')

        print('Searching for Drupal root in working dir')
        matches = []
        for root, dirnames, filenames in os.walk(self.working_dir):
            for filename in fnmatch.filter(filenames, 'system.module'):
                matches.append(os.path.join(root, filename))
                break
            if len(matches) > 0:
                break
        if len(matches) > 0:
            # Get path to Drupal root
            paths = matches[0].split('/')
            # Ugly, but works
            del(paths[-3:-1])
            del(paths[-1])
            drupal_root = "/".join(paths)
            # Create a cache bin for the Drupal root
            new_cache_bin = self.get_cache_bin(self.working_dir) + \
                "/drupal_root"
            # Save path to Drupal root in working dir cache
            print('Saving drupal_root "%s" in cache' % drupal_root)
            output = open(new_cache_bin, 'wb')
            pickle.dump(drupal_root, output)
            output.close()
            return drupal_root
        else:
            # Use `drush dd` to see if we can get Drupal root that way.
            command = []
            command.append(self.get_drush_path())
            command.append('dd')
            command.append('--nocolor')
            response = subprocess.Popen(command,
                                        stdout=subprocess.PIPE,
                                        cwd=self.working_dir
                                        ).communicate()[0].decode('utf-8'
                                                                  ).strip('\n')
            # If `drush dd` returns a directory, then return that.
            if os.path.isdir(response) is True:
                print("`drush dd` found a directory: %s" % response)
                return response
            else:
                # Default to Drush cache bin.
                print("Using 'drush' cache bin")
                self.get_cache_bin('drush')
                return 'drush'
        return self.working_dir

    def get_cache_bin(self, bin):
        """
        Returns a cache bin. If the bin doesn't exist, it is created.
        """
        cache_bin_name = hashlib.sha224(bin.encode('utf-8')).hexdigest()
        sublime_cache_path = sublime.cache_path()
        cache_bin = sublime_cache_path + "/" + "sublime-drush" + "/" \
            + cache_bin_name
        if os.path.isdir(cache_bin) is False:
            print('Bin not found. Created new cache bin: %s' % cache_bin)
            os.makedirs(cache_bin)
        else:
            print('Returning cache bin for "%s"' % bin)
        return cache_bin
