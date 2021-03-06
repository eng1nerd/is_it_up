# coding=utf-8
"""
Stop gap build script until I find something better.
"""
import glob
import json
import os
import subprocess
import sys
from json import JSONDecodeError

from pynt import task
from pyntcontrib import execute, safe_cd
from semantic_version import Version

PROJECT_NAME = "is_it_up"
PIPENV = "pipenv run"
SRC = '.'
PYTHON = "python3.7"
IS_DJANGO = False
IS_TRAVIS = 'TRAVIS' in os.environ  # I double we will ever use travis...
GEM_FURY = "n/a"
if IS_TRAVIS:
    PIPENV = ""
else:
    PIPENV = "pipenv run"
IS_APP = True  # freeze requirements

MAC_LIBS = ":"
BUILD_SERVER_LIBS = ":"

sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
from build_utils import check_is_aws, skip_if_no_change, execute_with_environment, get_versions, is_it_worse, timed, \
    execute_get_text

CURRENT_HASH = None

if check_is_aws():
    MAC_LIBS += BUILD_SERVER_LIBS

@task()
@timed()
def clean_state():
    with safe_cd(".build_state"):
        # wild cards don't expand by default
        for file in os.listdir("."):
            if file.startswith("last") and file.endswith(".txt"):
                execute("rm", "-f", str(file))

@task()
@timed()
def update_pip_and_pipenv():
    env = config_pythonpath()
    execute("pip", "install", "--upgrade", "pip")

@task()
@timed()
def clean():
    pass

@task()
@skip_if_no_change("formatting")
@timed()
def formatting():
    with safe_cd(SRC):
        execute(*("{0} black {1}".format(PIPENV, PROJECT_NAME).split(" ")))

@task(clean, formatting)
@skip_if_no_change("compile_py")
@timed()
def compile_py():
    with safe_cd(SRC):
        execute(PYTHON, "-m", "compileall", PROJECT_NAME)

@task()
@timed()
def prospector():
    with safe_cd(SRC):
        execute("pipenv",
                *("run prospector {0} --profile is_it_up_style --pylint-config-file=pylintrc.ini --profile-path=.prospector"
                  .format(PROJECT_NAME)
                  .split(" ")))

@task(compile_py)
@skip_if_no_change("lint", expect_files="lint.txt")
@timed()
def lint():
    with safe_cd(SRC):
        if os.path.isfile("lint.txt"):
            execute("rm", "lint.txt")
    with safe_cd(SRC):
        # so that pylint doesn't stop us with a bad return value

        if IS_DJANGO:
            django_bits = " --load-plugins pylint_django"
        else:
            django_bits = ""

        command = "{0} pylint{1} --rcfile=pylintrc.ini {2}".format(PIPENV, django_bits, PROJECT_NAME).strip()
        print(command)
        command = command.split(" ")

        # keep out of src tree, causes extraneous change detections
        lint_output_file_name = "../lint.txt"
        with open(lint_output_file_name, "w") as outfile:
            # Ths is set up to supress lint failing on even 1 line of lint.
            # but that doesn't distinguish betweet lint or ImportErrors!
            my_env = config_pythonpath()
            #subprocess.run(command, stdout=outfile, env=my_env, timeout=120)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, env=my_env)
            for line in iter(process.stdout.readline, b''):  # replace '' with b'' for Python 3
                if b"memoize.py" in line:
                    continue
                sys.stdout.write(line.decode())
                outfile.write(line.decode())

        fatal_errors = sum(1 for line in open(lint_output_file_name)
                           if "no-member" in line or \
                           "no-name-in-module" in line or \
                           "import-error" in line)

        if fatal_errors > 0:
            for line in open(lint_output_file_name):
                if "no-member" in line or \
                        "no-name-in-module" in line or \
                        "import-error" in line:
                    print(line)

            print("Fatal lint errors : {0}".format(fatal_errors))
            exit(-1)
            return

        num_lines = sum(1 for line in open(lint_output_file_name)
                        if "*************" not in line
                        and "---------------------" not in line
                        and "Your code has been rated at" not in line)

        got_worse = is_it_worse("lint", num_lines, margin=10)
        max_lines = 350
        if num_lines > max_lines or got_worse:
            if got_worse:
                print("lint got worse - lines : {0}".format(num_lines))
            else:
                print("Too many lines of lint : {0} out of max of {1}".format(num_lines, max_lines))
            exit(-1)


@task(lint)
@timed()
def nose_tests():
    with safe_cd(SRC):
        if IS_DJANGO:
            # Django app
            command = "{0} {1} manage.py test {2} -v 2".format(PIPENV, PYTHON, PROJECT_NAME).strip()
            # We'd expect this to be MAC or a build server.
            my_env = config_pythonpath()
            execute_with_environment(command, env=my_env)
        else:
            my_env = config_pythonpath()
            if IS_TRAVIS:
                command = "{0} -m nose {1}".format(PYTHON, "test").strip()
            else:
                command = "{0} {1} -m nose {2}".format(PIPENV, PYTHON, "test").strip()
            print(command)
            execute_with_environment(command, env=my_env)


def config_pythonpath():
    if check_is_aws():
        env = "DEV"
    else:
        env = "MAC"
    my_env = {**os.environ, 'ENV': env}
    my_env["PYTHONPATH"] = my_env.get("PYTHONPATH",
                                      "") + MAC_LIBS
    print(my_env["PYTHONPATH"])
    return my_env



@task()
@skip_if_no_change("vulture", expect_files="dead_code.txt")
@timed()
def dead_code():
    """
    This also finds code you are working on today!
    """
    with safe_cd(SRC):
        exclusions = "--exclude *settings.py,migrations/,*models.py,*_fake.py,*tests.py,*ui/admin.py"
        if IS_TRAVIS:
            command = "{0} vulture {1} {2}".format(PYTHON, PROJECT_NAME, exclusions).strip().split()
        else:
            command = "{0} vulture {1} {2}".format(PIPENV, PROJECT_NAME, exclusions).strip().split()

        output_file_name = "dead_code.txt"
        with open(output_file_name, "w") as outfile:
            env = config_pythonpath()
            subprocess.call(command, stdout=outfile, env=env)

        cutoff = 120
        num_lines = sum(1 for line in open(output_file_name) if line)
        if num_lines > cutoff:
            print("Too many lines of dead code : {0}, max {1}".format(num_lines, cutoff))
            exit(-1)
@task()
@timed()
def coverage():
    """
    Do tests exercise enough code?
    """
    print("Coverage tests always re-run")
    with safe_cd(SRC):
        my_env = config_pythonpath()
        # You will need something like this in pytest.ini
        # By default, pytest is VERY restrictive in the file names it will match.
        #
        # [pytest]
        # DJANGO_SETTINGS_MODULE = core.settings
        # python_files = tests.py test_*.py *_tests.py test*_*.py *_test*.py
        if not os.path.exists("pytest.ini") and IS_DJANGO:
            print("pytest.ini MUST exist for Django test detection or too few tests are found.")
            exit(-1)
            return

        my_env = config_pythonpath()
        command = "{0} py.test {1} --cov={2} --cov-report html:coverage --cov-fail-under 55  --verbose".format(
            PIPENV,
            "test", PROJECT_NAME)
        execute_with_environment(command, my_env)

@task()
@skip_if_no_change("docs")
@timed()
def docs():
    with safe_cd(SRC):
        with safe_cd("docs"):
            my_env = config_pythonpath()
            execute_with_environment("pipenv run make html", env=my_env)


@task()
@timed()
def pip_check():
    print("pip_check always reruns")
    with safe_cd(SRC):
        execute("pipenv", "check")


@task()
@skip_if_no_change("mypy")
@timed()
def mypy():

    command = "{0} mypy {1} --ignore-missing-imports --strict".format(PIPENV, PROJECT_NAME).strip()
    bash_process = subprocess.Popen(command.split(" "),
                                    # shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                    )
    out, err = bash_process.communicate()  # wait
    errors_file = "mypy_errors.txt"

    def is_third_party(value: str) -> bool:
        for directory in []:
            if value.startswith(directory):
                return True
        return False
    with open(errors_file, "w+") as file_handle:
        lines = out.decode().split("\n")
        for line in lines:
            if is_third_party(line):
                continue
            # if "/migrations/" in line:
            #     continue

            file_handle.write(line +"\n")

    num_lines = sum(1 for _ in open(errors_file))
    got_worse = is_it_worse("mypy", num_lines, margin=10)
    max_lines = 500
    if num_lines > max_lines or got_worse:
        if got_worse:
            print("mypy got worse - lines : {0}".format(num_lines))
        else:
            print("Too many lines of mypy : {0} out of max of {1}".format(num_lines, max_lines))
        exit(-1)

@task()
@skip_if_no_change("detect_secrets", expect_files="detect-secrets-results.txt")
@timed()
def detect_secrets():
    # skipo for the moment.
    pass
    # use
    # blah blah = "foo"     # pragma: whitelist secret
    # to ignore a false posites
    errors_file = "detect-secrets-results.txt"

    command = "detect-secrets scan --base64-limit 4 --exclude .idea|lock.json|lint.txt|{0}".format(errors_file)
    print(command)
    bash_process = subprocess.Popen(command.split(" "),
                                    # shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                    )
    out, err = bash_process.communicate()  # wait

    with open(errors_file, "w+") as file_handle:
        result = out.decode()
        if not result:
            print("Failed, no detect secrets results.")
            exit(-1)
        file_handle.write(result)

    try:
        with open(errors_file) as f:
            data = json.load(f)

        if data["results"]:
            for result in data["results"]:
                print(result)
                print("detect-secrets has discovered high entropy strings, possibly passwords?")
                exit(-1)
    except JSONDecodeError:
        pass


@task()
@timed()
def compile_md():
    with safe_cd(SRC):
        execute("pandoc", *("--from=markdown --to=rst --output=README.rst README.md".split(" ")))

@task()
@timed()
def jiggle_version():
    with safe_cd(SRC):
        command = "pip install jiggle_version --upgrade"
        execute(*(command.split(" ")))
        command = "{0} jiggle_version here --module={1}".format(PIPENV, PROJECT_NAME, SRC).strip()
        result = execute_get_text(command)
        print(result)
        command = "{0} jiggle_version find --module={1}".format(PIPENV, PROJECT_NAME, SRC).strip()
        result = execute_get_text(command)
        print(result)



@task()
@timed()
def pin_dependencies():
    with safe_cd(SRC):
        # right not because of black, pylint and astroid and (more?) freeze fails.
        # would have to do this in fresh env w/o dev deps.
        try:
            execute(*("{0} pipenv_to_requirements --freeze".format(PIPENV).strip().split(" ")))
        except:
            print("No pipfile.lock, switching to ordinary freeze")
            execute(*("{0} pip freeze".format(PIPENV).strip().split(" ")))
            raise NotImplementedError("TODO: pipe to requirements.txt")


@task(compile_md)
@timed()
def check_setup_py():
    """
    Setup.py checks package things including README.rst
    """
    with safe_cd(SRC):
        if IS_TRAVIS:
            execute(PYTHON, *("setup.py check -r -s".split(" ")))
        else:
            execute(*("{0} {1} setup.py check -r -s".format(PIPENV, PYTHON).strip().split(" ")))


@task(pin_dependencies, dead_code, check_setup_py, compile_md, compile_py, mypy, lint, nose_tests, docs, jiggle_version, detect_secrets)
@skip_if_no_change("package")
@timed()
def package():
    with safe_cd(SRC):
        for folder in ["build", "dist", PROJECT_NAME + ".egg-info"]:
            execute("rm", "-rf", folder)

    with safe_cd(SRC):
        execute(PYTHON, "setup.py", "sdist", "--formats=gztar,zip")

    os.system('say "package complete."')

@task(package)
@skip_if_no_change("upload_package")
@timed()
def upload_package():
    """
    Not implemented yet
    """
    # TODO: upload if version has changed since last successful upload
    pass


@task()
@timed()
def gemfury():
    """
    Push to gem fury, a repo with private options
    """
    if not GEM_FURY:
        raise Exception("Can't do gemfury things, no gem_fury account.")
    # fury login
    # fury push dist/*.gz --as=YOUR_ACCT
    # fury push dist/*.whl --as=YOUR_ACCT

    command ="fury login --as={0}".format(GEM_FURY)
    cp = subprocess.Popen(command.split(" "),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        shell=False, )
    print(cp.stdout)

    about = {}
    with open(os.path.join(SRC, PROJECT_NAME, "__init__.py")) as f:
        exec(f.read(), about)
    version = Version(about["__version__"])
    print("Have version : " + str(version))
    print("Preparing to upload")

    uploaded_something = False
    if version not in get_versions():
        for kind in ["gz"]: # , "whl"]:
            try:
                files = glob.glob("{0}dist/*.{1}".format(SRC.replace(".", ""), kind))
                for file_name in files:
                    if not file_name:
                        continue
                    command ="fury push {0} --as={1}".format(file_name, GEM_FURY)
                    print(command)
                    cp = subprocess.Popen(command.split(" "),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        shell=False)
                    uploaded_something = True
                    print("result of fury push")
                    for stream in [cp.stdout, cp.stderr]:
                        if stream:
                            for line in stream:
                                print(str(line))
                                #for l in line.split("\n"):
                                #print(l)

            except subprocess.CalledProcessError as cpe:
                print("result of fury push- got error")
                for stream in [cp.stdout, cp.stderr]:
                    if stream:
                        for line in stream:
                            print(str(line))
                            # for l in line.split("\n"):
                            #     print(l)
                print(cpe)
                raise
    if not uploaded_something:
        print("I think... I think... we failed to upload anything")


@task()
@timed()
def echo(*args, **kwargs):
    """
    Pure diagnotics
    """
    print(args)
    print(kwargs)


# Default task (if specified) is run when no task is specified in the command line
# make sure you define the variable __DEFAULT__ after the task is defined
# A good convention is to define it at the end of the module
# __DEFAULT__ is an optional member

__DEFAULT__ = echo
