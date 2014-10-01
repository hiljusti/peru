import asyncio
import codecs
import io
import subprocess
import sys


def stable_gather(*coros):
    '''asyncio.gather() starts tasks in a nondeterministic order (because it
    calls set() on its arguments). stable_gather starts the list of tasks in
    order, and passes the resulting futures to gather().

    As with gather(), stable_gather() isn't itself a coroutine, but it returns
    a future.'''
    assert len(coros) == len(set(coros)), 'no duplicates allowed'
    futures = [asyncio.async(coro) for coro in coros]
    return asyncio.gather(*futures)


@asyncio.coroutine
def create_subprocess_with_handle(command, display_handle, *, shell=False, cwd,
                                  **kwargs):
    '''Writes subprocess output to a display handle as it comes in, and also
    returns a copy of it as a string. Throws if the subprocess returns an
    error. Note that cwd is a required keyword-only argument, on theory that
    peru should never start child processes "wherever I happen to be running
    right now."'''

    # We're going to get chunks of bytes from the subprocess, and it's possible
    # that one of those chunks ends in the middle of a unicode character. An
    # incremental decoder keeps those dangling bytes around until the next
    # chunk arrives, so that split characters get decoded properly. Use
    # stdout's encoding, but provide a default for the case where stdout has
    # been redirected to a StringIO. (This happens in tests.)
    encoding = sys.stdout.encoding or 'utf8'
    decoder_factory = codecs.getincrementaldecoder(encoding)
    decoder = decoder_factory(errors='replace')

    output_copy = io.StringIO()

    # Display handles are context managers. Entering and exiting the display
    # handle lets the display know when the job starts and stops.
    with display_handle:
        stdin = asyncio.subprocess.DEVNULL
        stdout = asyncio.subprocess.PIPE
        stderr = asyncio.subprocess.STDOUT
        if shell:
            proc = yield from asyncio.create_subprocess_shell(
                command, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd,
                **kwargs)
        else:
            proc = yield from asyncio.create_subprocess_exec(
                *command, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd,
                **kwargs)

        # Read all the output from the subprocess as its comes in.
        while True:
            outputbytes = yield from proc.stdout.read(4096)
            if not outputbytes:
                break
            outputstr = decoder.decode(outputbytes)
            display_handle.write(outputstr)
            output_copy.write(outputstr)

        returncode = yield from proc.wait()

    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode, command, output_copy.getvalue())

    assert not decoder.buffer, 'decoder nonempty: ' + repr(decoder.buffer)

    return output_copy.getvalue()