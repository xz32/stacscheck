#!/usr/bin/env python
# -*- coding: utf-8 -*-


# Stacscheck

import os
import subprocess
import re
import sys
from threading import Thread
import difflib
import jinja2


from optparse import OptionParser

# The HTML output
JINJAPAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>{{Practical}} - {{ SubmissionID }} </title>
</head>
<body>
    <table style="width:100%">
    {% for test in Tests %}
    <tr id="test{{ loop.index }}" bgcolor=
    {% if test.pass %} "#BFB" {% else %} "#FBB" {% endif %} >
    <td>{% if test.pass %} Tick {% else %} Cross {% endif %}</td>

        <td> {{ test.name }} </td>
        <td> {{ test.pass }} </td>
        <td> {{ test.returnval }} </td>
    </tr>
    <tr>
    <td colspan="5">
        {% if test.htmldiff %}
        {{ test.htmldiff | safe }}
        {% else %}
        <div display="inline">
        {% for line in  test.stdout.splitlines() %}
        {{line}}<br>
        {% endfor %}
        </div>
        <div display="inline">
        {% for line in  test.stderr.splitlines() %}
        {{line}}<br>
        {% endfor %}
        </div>
        {% endif %}
    </td>
    </tr>
    {% endfor %}
    </table>

</body>
</html>
"""

# Store the base test directory
TESTBASE = None

# Simple function to print out more verbose information if -v is passed
VERBOSE = True
def verbose_print(arg):
    if VERBOSE:
        print(str(arg)+"\n")

def warn_print(arg):
    print("WARNING: " + str(arg) + "\n")

# Store the results of all tests
testStore = []


# Record that a test was run, printing as approriate
def register_returnval_test(test):
    if test["returnval"] == 0:
        print("** Test pass : " + test["name"])
        test["pass"] = True
    else:
        print("** Test fail : " + test["name"])
    
    if test["returnval"] != 0 or test.get("alwaysoutput", False):
        print("---stdout---")
        print(test.get("stdout", ""))
        if test.get("stderr", False):
            print("---stderr---" + test["stderr"])
        print("---");
        
        test["pass"] = False
    testStore.append(test)

# Takes a single string with newlines, and returns a list of lines
# We strip all whitespace, then add a "\n" on the end
# This is to deal with differences in invisible whitespaces
def strip_string(string):
    return [l.strip() + "\n" for l in string.split("\n") if l.strip() != '']


def register_diff_test(test, comparefile):
    verbose_print(test)
    with open(comparefile, 'r') as stream:
        comparelines = stream.read()
    comparelines = strip_string(comparelines)
    userlines = strip_string(test["stdout"])
    test["comparelines"] = comparelines
    test["userlines"] = userlines
    if comparelines == userlines:
        print("** Compare test pass : " + test["name"])
        test["pass"] = True
    else:
        print("** Compare test fail : " + test["name"])
        test["textdiff"] =  list(difflib.unified_diff(userlines,comparelines,"Submission","Reference","",""))
        test["htmldiff"] = difflib.HtmlDiff().make_table(comparelines, userlines, "Submission", "Reference")
        print("".join(test["textdiff"]))
        test["pass"] = False
    testStore.append(test)


# Given a filename of a test, get a nicer, shorter name which
# describes the test. First drop extension, then remove TESTBASE
def nice_name(name):
    return os.path.splitext(name)[0][len(TESTBASE):]


# Read from a stream, recording result in a record
# Caps the total amount read to ~10MB
def read_stream(outdict, name, stream):
    stream_limit = 10000000
    outstr = ''
    while True:
        chunk = stream.read(stream_limit - len(outstr))
        # End of file reached
        if chunk == '':
            outdict[name] = outstr
            return

        # Add chunk
        outstr = outstr + chunk

        if len(outstr) == stream_limit:
            outstr += "\n ... Output truncated\n"
            outdict[name] = outstr
            # Throw away rest of stream
            while stream.read(1024) != '':
                pass
            return


# Run a program, given as a list [prog, arg1, arg2], with
# an optional file to read as stdin, and optional extra environment variables
def run_program(program, stdin, extra_env):
    env_copy = os.environ.copy()

    verbose_print("Running " + " ".join(program))
    if not os.access(program[0], os.X_OK):
        warn_print(program[0] + " is not executable")

    if extra_env is not None:
        for key in extra_env:
            env_copy[key] = extra_env[key]

    try:
        proc = subprocess.Popen(program, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, close_fds=True, shell=True, env=env_copy)

        retdict = dict()

        thread_err = Thread(target=read_stream, args=(retdict, "stderr", proc.stderr))
        thread_err.start()
        thread_out = Thread(target=read_stream, args=(retdict, "stdout", proc.stdout))
        thread_out.start()

        if stdin is not None:
            stdinfd = open(stdin, "r")
            proc.stdin.write(stdinfd.read())
            stdinfd.close()
        # Either we have filled stdin, or we are putting nothing in it
        proc.stdin.close()

        thread_err.join()
        thread_out.join()
        proc.wait()

        retdict["returnval"] = proc.returncode
        verbose_print("Tested " + str(program) + ", recieved output: " + str(retdict))
        return retdict
    except OSError:
        warn_print(program[0] + " is broken / not executable")
        return {"returnval": 1, "stdout": "", "stderr": ""}


# Find files in 'directory' matching 'regex'
def files_in_dir_matching_regex(directory, regex):
    files = [os.path.join(directory, f) for f in sorted(os.listdir(directory))
             if re.match(regex, f) and
             os.path.isfile(os.path.join(directory, f))]
    verbose_print("Found " + str(files) + " matching " + str(regex) + " in " + str(directory))
    return files

# Accept a directory name relative to
def run_tests_recursive(testdir):
    verbose_print("Checking in " + testdir)
    # First check for a build*.sh

    buildscripts = files_in_dir_matching_regex(testdir, r'build.*\.sh')
    for buildsh in buildscripts:
        buildshret = run_program([buildsh], None, None)
        buildshret["name"] = nice_name(buildsh)
        register_returnval_test(buildshret)
        if buildshret["returnval"] != 0:
            verbose_print("Exiting early due to failed " + buildsh)
            return

    testscripts = files_in_dir_matching_regex(testdir, r'test.*\.sh')

    for test in testscripts:
        result = run_program([test], None, None)
        result["name"] = nice_name(test)
        register_returnval_test(result)

    infoscripts = files_in_dir_matching_regex(testdir, r'info.*\.sh')

    for info in infoscripts:
        result = run_program([info], None, None)
        result["name"] = nice_name(info)
        result["alwaysoutput"] = True
        register_returnval_test(result)


    progscripts = files_in_dir_matching_regex(testdir, r'prog.*\.sh')

    outfiles = files_in_dir_matching_regex(testdir, r'.*\.out')

    if (len(outfiles) == 0) != (len(progscripts) == 0):
        if len(outfiles) == 0:
            warn_print("Found prog*.sh without *.out files in " + testdir)
        else:
            warn_print("Found *.out files without prog*.sh in " + testdir)
    for progsh in progscripts:
        for out in outfiles:
            infile = out[:-4] + ".in"
            if not os.path.isfile(infile):
                infile = None
            result = run_program([progsh], infile, None)
            result["name"] = nice_name(progsh) + "-" + os.path.basename(out)
            register_diff_test(result, out)

    subdirs = [os.path.join(testdir, d) for d in sorted(os.listdir(testdir))
               if os.path.isdir(os.path.join(testdir, d))]

    for d in subdirs:
        run_tests_recursive(d)


##################################################################
# Main program
def run():
    global VERBOSE, TESTBASE
    parser = OptionParser(usage="%prog [options] test1 test2 ... ")
    parser.add_option("--id", dest="subid", default="<unknown>",
                      help="Give identifier for submission")
    parser.add_option("--html", dest="htmlout",
                      help="Produce HTML overview", metavar="FILE")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="Output more information during test")

    (options, args) = parser.parse_args()
    if len(args) != 1:
        sys.exit("Must give exactly one test to run")

    VERBOSE = options.verbose
    TESTBASE = args[0]

    run_tests_recursive(TESTBASE)

    if options.htmlout is not None:
        env = jinja2.Environment(autoescape=True)
        template = env.from_string(JINJAPAGE)
        with open(options.htmlout, "w") as html:
            html.write(template.render(Practical=TESTBASE,
                                       SubmissionID=options.subid,
                                       Tests=testStore))

if __name__ == "__main__":
    run()