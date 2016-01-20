import asyncio
import os
import time

import peru.cache
from shared import assert_contents, create_dir, make_synchronous, PeruTest


class CacheTest(PeruTest):
    @make_synchronous
    def setUp(self):
        self.cache = yield from peru.cache.Cache(create_dir())
        self.content = {
            'a': 'foo',
            'b/c': 'bar',
            'b/d': 'baz',
        }
        self.content_dir = create_dir(self.content)
        self.content_tree = yield from self.cache.import_tree(self.content_dir)

    @make_synchronous
    def test_basic_export(self):
        export_dir = create_dir()
        yield from self.cache.export_tree(self.content_tree, export_dir)
        assert_contents(export_dir, self.content)

    @make_synchronous
    def test_export_force_with_preexisting_files(self):
        # Create a working tree with a conflicting file.
        dirty_content = {'a': 'junk'}
        export_dir = create_dir(dirty_content)
        # Export should fail by default.
        with self.assertRaises(peru.cache.DirtyWorkingCopyError):
            yield from self.cache.export_tree(self.content_tree, export_dir)
        assert_contents(export_dir, dirty_content)
        # But it should suceed with the force flag.
        yield from self.cache.export_tree(
            self.content_tree, export_dir, force=True)
        assert_contents(export_dir, self.content)

    @make_synchronous
    def test_export_force_with_changed_files(self):
        export_dir = create_dir()
        yield from self.cache.export_tree(self.content_tree, export_dir)
        # If we dirty a file, a resync should fail.
        with open(os.path.join(export_dir, 'a'), 'w') as f:
            f.write('dirty')
        with self.assertRaises(peru.cache.DirtyWorkingCopyError):
            yield from self.cache.export_tree(
                self.content_tree, export_dir, previous_tree=self.content_tree)
        # But it should succeed with the --force flag.
        yield from self.cache.export_tree(
            self.content_tree, export_dir, force=True,
            previous_tree=self.content_tree)
        assert_contents(export_dir, self.content)

    @make_synchronous
    def test_multiple_imports(self):
        new_content = {'fee/fi': 'fo fum'}
        new_tree = yield from self.cache.import_tree(create_dir(new_content))
        export_dir = create_dir()
        yield from self.cache.export_tree(new_tree, export_dir)
        assert_contents(export_dir, new_content)

    @make_synchronous
    def test_import_with_gitignore(self):
        # Make sure our git imports don't get confused by .gitignore files.
        new_content = {'fee/fi': 'fo fum', '.gitignore': 'fee/'}
        new_tree = yield from self.cache.import_tree(create_dir(new_content))
        export_dir = create_dir()
        yield from self.cache.export_tree(new_tree, export_dir)
        assert_contents(export_dir, new_content)

    @make_synchronous
    def test_import_with_files(self):
        all_content = {'foo': '',
                       'bar': '',
                       'baz/bing': ''}
        test_dir = create_dir(all_content)
        tree = yield from self.cache.import_tree(
            test_dir, picks=['foo', 'baz'])
        expected_content = {'foo': '',
                            'baz/bing': ''}
        out_dir = create_dir()
        yield from self.cache.export_tree(tree, out_dir)
        assert_contents(out_dir, expected_content)

    @make_synchronous
    def test_export_with_existing_files(self):
        # Create a dir with an existing file that doesn't conflict.
        more_content = {'untracked': 'stuff'}
        export_dir = create_dir(more_content)
        yield from self.cache.export_tree(self.content_tree, export_dir)
        expected_content = self.content.copy()
        expected_content.update(more_content)
        assert_contents(export_dir, expected_content)

        # But if we try to export twice, the export_dir will now have
        # conflicting files, and export_tree() should throw.
        with self.assertRaises(peru.cache.DirtyWorkingCopyError):
            yield from self.cache.export_tree(self.content_tree, export_dir)

        # By default, git's checkout safety doesn't protect files that are
        # .gitignore'd. Make sure we still throw the right errors in the
        # presence of a .gitignore file.
        with open(os.path.join(export_dir, '.gitignore'), 'w') as f:
            f.write('*\n')  # .gitignore everything
        with self.assertRaises(peru.cache.DirtyWorkingCopyError):
            yield from self.cache.export_tree(self.content_tree, export_dir)

    @make_synchronous
    def test_previous_tree(self):
        export_dir = create_dir(self.content)

        # Create some new content.
        new_content = self.content.copy()
        new_content['a'] += ' different'
        new_content['newfile'] = 'newfile stuff'
        new_dir = create_dir(new_content)
        new_tree = yield from self.cache.import_tree(new_dir)

        # Now use cache.export_tree to move from the original content to the
        # different content.
        yield from self.cache.export_tree(
            new_tree, export_dir, previous_tree=self.content_tree)
        assert_contents(export_dir, new_content)

        # Now do the same thing again, but use a dirty working copy. This
        # should cause an error.
        dirty_content = self.content.copy()
        dirty_content['a'] += ' dirty'
        dirty_dir = create_dir(dirty_content)
        with self.assertRaises(peru.cache.DirtyWorkingCopyError):
            yield from self.cache.export_tree(
                new_tree, dirty_dir, previous_tree=self.content_tree)
        # But if the file is simply missing, it should work.
        os.remove(os.path.join(dirty_dir, 'a'))
        yield from self.cache.export_tree(
            new_tree, dirty_dir, previous_tree=self.content_tree)
        assert_contents(dirty_dir, new_content)

        # Make sure we get an error even if the dirty file is unchanged between
        # the previous tree and the new one.
        no_conflict_dirty_content = self.content.copy()
        no_conflict_dirty_content['b/c'] += ' dirty'
        no_conflict_dirty_dir = create_dir(no_conflict_dirty_content)
        with self.assertRaises(peru.cache.DirtyWorkingCopyError):
            yield from self.cache.export_tree(new_tree, no_conflict_dirty_dir,
                                              previous_tree=self.content_tree)

    @make_synchronous
    def test_missing_files_in_previous_tree(self):
        '''Export should allow missing files, and it should recreate them.'''
        export_dir = create_dir()
        # Nothing in content_tree exists yet, so this export should be the same
        # as if previous_tree wasn't specified.
        yield from self.cache.export_tree(
            self.content_tree, export_dir, previous_tree=self.content_tree)
        assert_contents(export_dir, self.content)
        # Make sure the same applies with just a single missing file.
        os.remove(os.path.join(export_dir, 'a'))
        yield from self.cache.export_tree(
            self.content_tree, export_dir, previous_tree=self.content_tree)
        assert_contents(export_dir, self.content)

    @make_synchronous
    def test_merge_trees(self):
        merged_tree = yield from self.cache.merge_trees(
            self.content_tree, self.content_tree, 'subdir')
        expected_content = dict(self.content)
        for path, content in self.content.items():
            expected_content[os.path.join('subdir', path)] = content
        export_dir = create_dir()
        yield from self.cache.export_tree(merged_tree, export_dir)
        assert_contents(export_dir, expected_content)

        with self.assertRaises(peru.cache.MergeConflictError):
            # subdir/ is already populated, so this merge should throw.
            yield from self.cache.merge_trees(
                merged_tree, self.content_tree, 'subdir')

    @make_synchronous
    def test_merge_with_deep_prefix(self):
        '''This test was inspired by a bug on Windows where we would give git a
        backslash-separated merge prefix, even though git demands forward slash
        as a path separator.'''
        content = {'file': 'stuff'}
        content_dir = create_dir(content)
        tree = yield from self.cache.import_tree(content_dir)
        prefixed_tree = yield from self.cache.merge_trees(None, tree, 'a/b/')
        export_dir = create_dir()
        yield from self.cache.export_tree(prefixed_tree, export_dir)
        assert_contents(export_dir, {'a/b/file': 'stuff'})

    @make_synchronous
    def test_read_file(self):
        a_content = yield from self.cache.read_file(self.content_tree, 'a')
        bc_content = yield from self.cache.read_file(self.content_tree, 'b/c')
        self.assertEqual(b'foo', a_content)
        self.assertEqual(b'bar', bc_content)
        with self.assertRaises(FileNotFoundError):
            yield from self.cache.read_file(self.content_tree, 'nonexistent')
        with self.assertRaises(IsADirectoryError):
            yield from self.cache.read_file(self.content_tree, 'b')

    # A helper method for several tests below below.
    @asyncio.coroutine
    def do_excludes_and_files_test(self, excludes, picks, expected):
        tree = yield from self.cache.import_tree(
            self.content_dir, excludes=excludes, picks=picks)
        out_dir = create_dir()
        yield from self.cache.export_tree(tree, out_dir)
        assert_contents(out_dir, expected)

    @make_synchronous
    def test_import_with_specific_file(self):
        yield from self.do_excludes_and_files_test(
            excludes=[], picks=['a'], expected={'a': 'foo'})

    @make_synchronous
    def test_import_with_specific_dir(self):
        yield from self.do_excludes_and_files_test(
            excludes=[], picks=['b'], expected={'b/c': 'bar', 'b/d': 'baz'})

    @make_synchronous
    def test_import_with_excluded_file(self):
        yield from self.do_excludes_and_files_test(
            excludes=['a'], picks=[], expected={'b/c': 'bar', 'b/d': 'baz'})

    @make_synchronous
    def test_import_with_excluded_dir(self):
        yield from self.do_excludes_and_files_test(
            excludes=['b'], picks=[], expected={'a': 'foo'})

    @make_synchronous
    def test_import_with_excludes_and_files(self):
        yield from self.do_excludes_and_files_test(
            excludes=['b/c'], picks=['b'], expected={'b/d': 'baz'})

    @make_synchronous
    def test_ls_tree(self):
        # Use the recursive case to get valid entries for each file. We could
        # hardcode these, but it would be messy and annoying to maintain.
        entries = yield from self.cache.ls_tree(
            self.content_tree, recursive=True)
        assert entries.keys() == {'a', 'b', 'b/c', 'b/d'}
        assert (entries['a'].type == entries['b/c'].type ==
                entries['b/d'].type == peru.cache.BLOB_TYPE)
        assert entries['b'].type == peru.cache.TREE_TYPE

        # Check the non-recursive, non-path case.
        self.assertDictEqual(
            {'a': entries['a'], 'b': entries['b']},
            (yield from self.cache.ls_tree(self.content_tree)))

        # Check the single file case, and make sure paths are normalized.
        self.assertDictEqual(
            {'b/c': entries['b/c']},
            (yield from self.cache.ls_tree(self.content_tree, 'b/c//./')))

        # Check the single dir case. (Trailing slash shouldn't matter, because
        # we nomalize it, but git will do the wrong thing if we forget
        # normalization.)
        self.assertDictEqual(
            {'b': entries['b']},
            (yield from self.cache.ls_tree(self.content_tree, 'b/')))

        # Check the recursive dir case.
        self.assertDictEqual(
            {'b': entries['b'], 'b/c': entries['b/c'], 'b/d': entries['b/d']},
            (yield from self.cache.ls_tree(
                self.content_tree, 'b', recursive=True)))

        # Make sure that we don't skip over a target file in recursive mode.
        self.assertDictEqual(
            {'b/c': entries['b/c']},
            (yield from self.cache.ls_tree(
                self.content_tree, 'b/c', recursive=True)))

    @make_synchronous
    def test_modify_tree(self):
        base_dir = create_dir({'a': 'foo', 'b/c': 'bar'})
        base_tree = yield from self.cache.import_tree(base_dir)
        entries = yield from self.cache.ls_tree(base_tree, recursive=True)
        cases = []

        # Test regular deletions.
        cases.append(({'a': None},
                      {'b/c': 'bar'}))
        cases.append(({'a//./': None},  # Paths should get normalized.
                      {'b/c': 'bar'}))
        cases.append(({'b': None},
                      {'a': 'foo'}))
        cases.append(({'b/c': None},
                      {'a': 'foo'}))
        cases.append(({'x/y/z': None},
                      {'a': 'foo', 'b/c': 'bar'}))
        cases.append(({'b/x': None},
                      {'a': 'foo', 'b/c': 'bar'}))
        # Test the case where we try to delete below a file.
        cases.append(({'a/x': None},
                      {'a': 'foo', 'b/c': 'bar'}))
        # Test insertions.
        cases.append(({'b': entries['a']},
                      {'a': 'foo', 'b': 'foo'}))
        cases.append(({'x': entries['a']},
                      {'a': 'foo', 'x': 'foo', 'b/c': 'bar'}))
        cases.append(({'x': entries['b']},
                      {'a': 'foo', 'b/c': 'bar', 'x/c': 'bar'}))
        cases.append(({'d/e/f': entries['a']},
                      {'a': 'foo', 'b/c': 'bar', 'd/e/f': 'foo'}))
        cases.append(({'d/e/f': entries['b']},
                      {'a': 'foo', 'b/c': 'bar', 'd/e/f/c': 'bar'}))

        for modifications, result in cases:
            modified_tree = yield from self.cache.modify_tree(
                base_tree, modifications)
            modified_dir = create_dir()
            yield from self.cache.export_tree(modified_tree, modified_dir)
            error_msg = ('modify_tree failed to give result {} '
                         'for modifications {}'.format(
                             repr(result), repr(modifications)))
            assert_contents(modified_dir, result, message=error_msg)

    @make_synchronous
    def test_git_attributes(self):
        # Setting the 'text' attribute when files contain Windows-style
        # newlines makes them appear dirty, which leads to errors where the
        # cache thinks its own checked out files are dirty. (I don't honestly
        # understand all the details.) The cache's git calls will read
        # .gitattributes in the sync dir, so we need to set our own attributes
        # in the $GIT_DIR to override. Everything in this test has to be done
        # in binary mode or it will all get muddled up when we actually run it
        # on Windows.
        windows_content = {'file': b'windows newline\r\n'}
        gitattributes_content = {'.gitattributes': b'* text'}
        both_content = windows_content.copy()
        both_content.update(gitattributes_content)
        windows_dir = create_dir(windows_content)
        tree = yield from self.cache.import_tree(windows_dir)
        out_dir = create_dir(gitattributes_content)
        # This export fails without the fix mentioned above.
        yield from self.cache.export_tree(tree, out_dir)
        assert_contents(out_dir, both_content, binary=True)

    @make_synchronous
    def test_touched_file(self):
        # Bumping the mtime on a file makes it appear dirty to `git
        # diff-files`. However, when the index is refreshed with `git
        # update-index`, the dirtiness should go away. This test guarantees
        # that we do that refresh, both with and without a cached index file.
        # Note that because the index file only has an mtime resolution of 1
        # second, we have to artificially inflate the mtime to guarantee that
        # the file will actually appear dirty.
        export_dir = create_dir()
        a_path = os.path.join(export_dir, 'a')
        t = time.time()

        def bump_mtime_one_minute():
            nonlocal t
            t += 60  # Add a whole minute to the mtime we set.
            os.utime(a_path, (t, t))

        # Do the first export.
        yield from self.cache.export_tree(self.content_tree, export_dir)
        # Touch a and rerun the export with no cached index.
        bump_mtime_one_minute()
        yield from self.cache.export_tree(
            self.content_tree, export_dir, previous_tree=self.content_tree)
        # Create a cached index file.
        index_dir = create_dir()
        index_file = os.path.join(index_dir, 'test_index_file')
        yield from self.cache.export_tree(
            self.content_tree, export_dir, previous_tree=self.content_tree,
            previous_index_file=index_file)
        # Finally, touch a again and rerun the export using the cached index.
        bump_mtime_one_minute()
        yield from self.cache.export_tree(
            self.content_tree, export_dir, previous_tree=self.content_tree,
            previous_index_file=index_file)
