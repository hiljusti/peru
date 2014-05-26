#! /usr/bin/env python3

import configparser
import os
from os import path
import shutil
import subprocess
import sys
import urllib.parse


def repo_cache_path(url, cache_root):
    escaped = urllib.parse.quote(url, safe="")
    return path.join(cache_root, escaped)


def git(*args, git_dir=None):
    # avoid forgetting this arg
    assert git_dir is None or path.isdir(git_dir)
    command = ["git"]
    if git_dir:
        command.append("--git-dir=" + git_dir)
    command.extend(args)
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True)
    output, _ = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            "Command exited with error code {0}:\n$ {1}\n{2}"
            .format(process.returncode, " ".join(command), output))
    return output


def git_clone_if_needed(url, cache_path, log_fn=None):
    repo_path = repo_cache_path(url, cache_path)
    if not path.exists(repo_path):
        os.makedirs(repo_path)
        try:
            if log_fn:
                log_fn()
            git("clone", "--mirror", url, repo_path)
        except:
            # Delete the whole thing if the clone failed, to avoid
            # confusing the cache.
            shutil.rmtree(repo_path)
            raise
    return repo_path


class FetchJob:
    def __init__(self, cache_path, dest, url, rev):
        self.cache_path = cache_path
        self.dest = dest
        self.url = url
        self.rev = rev
        self.run()

    def log(self, command):
        print("git {} {}".format(command, self.url))

    def git_clone_cached(self, url):
        log_fn = lambda: self.log("clone")
        return git_clone_if_needed(url, self.cache_path, log_fn)

    def git_already_has_rev(self, repo, rev):
        try:
            # make sure it exists
            git("cat-file", "-e", rev, git_dir=repo)
            # get the hash for this rev
            output = git("rev-parse", rev, git_dir=repo)
        except:
            return False
        # Only return true for revs that are absolute hashes. We could consider
        # treating tags the same way, but 1) tags actually can change and 2)
        # it's not clear at a glance whether something is a branch or a hash.
        # Keep it simple.
        return output.strip() == rev

    def checkout_tree(self, clone, rev, dest):
        self.log("checkout")
        git("--work-tree=" + dest, "checkout", rev, "--", ".", git_dir=clone)
        self.handle_subrepos(clone, rev, dest)

    def handle_subrepos(self, clone_path, rev, work_tree):
        gitmodules = os.path.join(work_tree, ".gitmodules")
        if not os.path.exists(gitmodules):
            return
        parser = configparser.ConfigParser()
        parser.read(gitmodules)
        for section in parser.sections():
            sub_relative_path = parser[section]["path"]
            sub_full_path = os.path.join(work_tree, sub_relative_path)
            sub_url = parser[section]["url"]
            sub_clone = self.git_clone_cached(sub_url)
            ls_tree = git("ls-tree", "-r", rev, sub_relative_path,
                          git_dir=clone_path)
            sub_rev = ls_tree.split()[2]
            self.checkout_tree(sub_clone, sub_rev, sub_full_path)

    def run(self):
        cached_dir = self.git_clone_cached(self.url)
        if not self.git_already_has_rev(cached_dir, self.rev):
            self.log("fetch")
            git("fetch", "--prune", git_dir=cached_dir)
        self.checkout_tree(cached_dir, self.rev, self.dest)


def main():
    sys.argv.pop(0)  # exe name

    url = None
    rev = "master"
    reup_target = "master"
    reup_specified = False

    while sys.argv[0] != "--":
        name = sys.argv.pop(0)
        val = sys.argv.pop(0)
        if name == "url":
            url = val
        elif name == "rev":
            rev = val
        elif name == "reup":
            reup_target = val
            reup_specified = True
        else:
            raise RuntimeError("Unknown plugin field name: " + name)
    assert url is not None

    assert sys.argv.pop(0) == "--"
    command = sys.argv.pop(0)
    if command == "fetch":
        dest = sys.argv.pop(0)
        cache_path = sys.argv.pop(0)
        assert sys.argv == []
        FetchJob(cache_path, dest, url, rev)
    elif command == "reup":
        cache_path = sys.argv.pop(0)
        assert sys.argv == []
        clone = git_clone_if_needed(url, cache_path)
        git("fetch", "--prune", git_dir=clone)
        output = git("rev-parse", reup_target, git_dir=clone)
        new_rev = output.strip()
        print("url:", url)
        if reup_specified:
            print("reup:", reup_target)
        print("rev:", new_rev)
    else:
        raise RuntimeError("Unknown command: " + command)

if __name__ == "__main__":
    main()
