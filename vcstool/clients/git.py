import os

from .vcs_base import VcsClientBase, which


class GitClient(VcsClientBase):

    type = 'git'
    _executable = None
    _config_color_is_auto = None

    @staticmethod
    def is_repository(path):
        return os.path.isdir(os.path.join(path, '.git'))

    def __init__(self, path):
        super(GitClient, self).__init__(path)

    def branch(self, command):
        self._check_executable()
        cmd = [GitClient._executable, 'branch']
        result = self._run_command(cmd)

        if not command.all and not result['returncode']:
            # only show current branch
            lines = result['output'].splitlines()
            lines = [l[2:] for l in lines if l.startswith('* ')]
            result['output'] = '\n'.join(lines)

        return result

    def custom(self, command):
        self._check_executable()
        cmd = [GitClient._executable] + command.args
        return self._run_command(cmd)

    def diff(self, command):
        self._check_executable()
        cmd = [GitClient._executable, 'diff']
        self._check_color(cmd)
        if command.context:
            cmd += ['--unified=%d' % command.context]
        return self._run_command(cmd)

    def export(self, command):
        self._check_executable()
        exact = command.exact
        if not exact:
            # determine if a specific branch is checked out or ec is detached
            cmd_branch = [
                GitClient._executable, 'rev-parse', '--abbrev-ref', 'HEAD']
            result_branch = self._run_command(cmd_branch)
            if result_branch['returncode']:
                result_branch['output'] = 'Could not determine ref: ' + \
                    result_branch['output']
                return result_branch
            branch_name = result_branch['output']
            exact = branch_name == 'HEAD'  # is detached

        if not exact:
            # determine the remote of the current branch
            cmd_remote = [
                GitClient._executable, 'rev-parse', '--abbrev-ref',
                '@{upstream}']
            result_remote = self._run_command(cmd_remote)
            if result_remote['returncode']:
                result_remote['output'] = 'Could not determine ref: ' + \
                    result_remote['output']
                return result_remote
            branch_with_remote = result_remote['output']

            # determine remote
            suffix = '/' + branch_name
            assert branch_with_remote.endswith(branch_name), \
                "'%s' does not end with '%s'" % \
                (branch_with_remote, branch_name)
            remote = branch_with_remote[:-len(suffix)]

            # determine url of remote
            result_url = self._get_remote_url(remote)
            if result_url['returncode']:
                return result_url
            url = result_url['output']

            # the result is the remote url and the branch name
            return {
                'cmd': ' && '.join([
                    result_branch['cmd'], result_remote['cmd'],
                    result_url['cmd']]),
                'cwd': self.path,
                'output': '\n'.join([url, branch_name]),
                'returncode': 0,
                'export_data': {'url': url, 'version': branch_name}
            }

        else:
            # determine the hash
            cmd_ref = [GitClient._executable, 'rev-parse', 'HEAD']
            result_ref = self._run_command(cmd_ref)
            if result_ref['returncode']:
                result_ref['output'] = 'Could not determine ref: ' + \
                    result_ref['output']
                return result_ref
            ref = result_ref['output']

            # get all remote names
            cmd_remotes = [GitClient._executable, 'remote']
            result_remotes = self._run_command(cmd_remotes)
            if result_remotes['returncode']:
                result_remotes['output'] = 'Could not determine remotes: ' + \
                    result_remotes['output']
                return result_remotes
            remotes = result_remotes['output'].splitlines()

            # prefer origin and upstream remotes
            if 'upstream' in remotes:
                remotes.remove('upstream')
                remotes.insert(0, 'upstream')
            if 'origin' in remotes:
                remotes.remove('origin')
                remotes.insert(0, 'origin')

            # for each remote name check if the hash is part of the remote
            for remote in remotes:
                # get all remote names
                cmd_refs = [
                    GitClient._executable, 'rev-list', '--remotes=' + remote]
                result_refs = self._run_command(cmd_refs)
                if result_refs['returncode']:
                    result_refs['output'] = \
                        "Could not determine refs of remote '%s': " % \
                        remote + result_refs['output']
                    return result_refs
                refs = result_refs['output'].splitlines()
                if ref not in refs:
                    continue

                # determine url of remote
                result_url = self._get_remote_url(remote)
                if result_url['returncode']:
                    return result_url
                url = result_url['output']
                # the result is the remote url and the hash
                return {
                    'cmd': ' && '.join([result_ref['cmd'], result_url['cmd']]),
                    'cwd': self.path,
                    'output': '\n'.join([url, ref]),
                    'returncode': 0,
                    'export_data': {'url': url, 'version': ref}
                }

            return {
                'cmd': ' && '.join([result_ref['cmd'], result_remotes['cmd']]),
                'cwd': self.path,
                'output': "Could not determine remote containing '%s'" % ref,
                'returncode': 1,
            }

    def _get_remote_url(self, remote):
        cmd_url = [
            GitClient._executable, 'config', '--get', 'remote.%s.url' % remote]
        result_url = self._run_command(cmd_url)
        if result_url['returncode']:
            result_url['output'] = 'Could not determine remote url: %s' % \
                result_url['output']
        return result_url

    def import_(self, command):
        if not command.url or not command.version:
            if not command.url and not command.version:
                value_missing = "'url' and 'version'"
            elif not command.url:
                value_missing = "'url'"
            else:
                value_missing = "'version'"
            return {
                'cmd': '',
                'cwd': self.path,
                'output': 'Repository data lacks the %s value' % value_missing,
                'returncode': 1
            }

        not_exist = self._create_path()
        if not_exist:
            return not_exist

        self._check_executable()
        if GitClient.is_repository(self.path):
            # verify that existing repository is the same
            result_url = self._get_url()
            if result_url['returncode']:
                return result_url
            url = result_url['output'][0]
            remote = result_url['output'][1]
            if url != command.url:
                return {
                    'cmd': '',
                    'cwd': self.path,
                    'output': 'Path already exists and contains a different repository',
                    'returncode': 1
                }
            # pull updates for existing repo
            cmd_pull = [GitClient._executable, 'pull', '--rebase', remote, command.version]
            result_pull = self._run_command(cmd_pull)
            if result_pull['returncode']:
                return result_pull
            cmd = result_pull['cmd']
            output = result_pull['output']

        else:
            cmd_clone = [GitClient._executable, 'clone', command.url, '.']
            result_clone = self._run_command(cmd_clone)
            if result_clone['returncode']:
                result_clone['output'] = "Could not clone repository '%s': %s" % (command.url, result_clone['output'])
                return result_clone
            cmd = result_clone['cmd']
            output = result_clone['output']

        cmd_checkout = [GitClient._executable, 'checkout', command.version]
        result_checkout = self._run_command(cmd_checkout)
        if result_checkout['returncode']:
            result_checkout['output'] = "Could not checkout ref '%s': %s" % (command.version, result_checkout['output'])
            return result_checkout
        cmd += ' && ' + ' '.join(cmd_checkout)
        output = '\n'.join([output, result_checkout['output']])

        return {
            'cmd': cmd,
            'cwd': self.path,
            'output': output,
            'returncode': 0
        }

    def _get_url(self):
        cmd_remote = [GitClient._executable, 'remote', 'show']
        result_remote = self._run_command(cmd_remote)
        if result_remote['returncode']:
            result_remote['output'] = 'Could not determine remote: %s' % \
                result_remote['output']
            return result_remote
        remote = result_remote['output']
        result_url = self._get_remote_url(remote)
        if result_url['returncode']:
            return result_url
        url = result_url['output']
        return {
            'cmd': ' && '.join([result_remote['cmd'], result_url['cmd']]),
            'cwd': self.path,
            'output': [url, remote],
            'returncode': 0
        }

    def log(self, command):
        self._check_executable()
        if command.limit_tag:
            # check if specific tag exists
            cmd_tag = [GitClient._executable, 'tag', '-l', command.limit_tag]
            result_tag = self._run_command(cmd_tag)
            if result_tag['returncode']:
                return result_tag
            if not result_tag['output']:
                return {
                    'cmd': '',
                    'cwd': self.path,
                    'output': "Repository lacks the tag '%s'" % command.limit_tag,
                    'returncode': 1
                }
            # output log since specific tag
            cmd = [GitClient._executable, 'log', '%s..' % command.limit_tag]
        elif command.limit_untagged:
            # determine nearest tag
            cmd_tag = [GitClient._executable, 'describe', '--abbrev=0', '--tags']
            result_tag = self._run_command(cmd_tag)
            if result_tag['returncode']:
                return result_tag
            # output log since nearest tag
            cmd = [GitClient._executable, 'log', '%s..' % result_tag['output']]
        else:
            cmd = [GitClient._executable, 'log']
            if command.limit != 0:
                cmd += ['-%d' % command.limit]
        self._check_color(cmd)
        return self._run_command(cmd)

    def pull(self, _command):
        self._check_executable()
        cmd = [GitClient._executable, 'pull']
        self._check_color(cmd)
        return self._run_command(cmd)

    def push(self, _command):
        self._check_executable()
        cmd = [GitClient._executable, 'push']
        return self._run_command(cmd)

    def remotes(self, _command):
        self._check_executable()
        cmd = [GitClient._executable, 'remote', '-v']
        return self._run_command(cmd)

    def status(self, command):
        self._check_executable()
        if command.hide_empty:
            cmd = [GitClient._executable, 'status', '-s']
            if command.quiet:
                cmd += ['--untracked-files=no']
            result = self._run_command(cmd)
            if result['returncode'] or not result['output']:
                return result
        cmd = [GitClient._executable, 'status']
        self._check_color(cmd)
        if command.quiet:
            cmd += ['--untracked-files=no']
        return self._run_command(cmd)

    def _check_color(self, cmd):
        # check if user uses colorization
        if GitClient._config_color_is_auto is None:
            _cmd = [GitClient._executable, 'config', '--get', 'color.ui']
            result = self._run_command(_cmd)
            GitClient._config_color_is_auto = (result['output'] == 'auto')

        # inject arguments to force colorization
        if GitClient._config_color_is_auto:
            cmd[1:1] = '-c', 'color.ui=always'

    def _check_executable(self):
        assert GitClient._executable is not None, "Could not find 'git' executable"


if not GitClient._executable:
    GitClient._executable = which('git')
