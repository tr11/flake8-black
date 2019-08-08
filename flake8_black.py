"""Check Python code passes black style validation via flake8.

This is a plugin for the tool flake8 tool for checking Python
soucre code using the tool black.
"""
from functools import lru_cache
from os import path
from pathlib import Path

import black
import toml

from flake8 import utils as stdin_utils
from flake8 import LOG


__version__ = "0.1.1"

black_prefix = "BLK"


def find_diff_start(old_src, new_src):
    """Find line number and column number where text first differs."""
    old_lines = old_src.split("\n")
    new_lines = new_src.split("\n")

    for line in range(min(len(old_lines), len(new_lines))):
        old = old_lines[line]
        new = new_lines[line]
        if old == new:
            continue
        for col in range(min(len(old), len(new))):
            if old[col] != new[col]:
                return line, col
        # Difference at the end of the line...
        return line, min(len(old), len(new))
    # Difference at the end of the file...
    return min(len(old_lines), len(new_lines)), 0


class BlackStyleChecker(object):
    """Checker of Python code using black."""

    name = "black"
    version = __version__

    STDIN_NAMES = {"stdin", "-", "(none)", None}

    def __init__(self, tree, filename="(none)"):
        """Initialise."""
        self.tree = tree
        self.filename = filename
        self.line_length = black.DEFAULT_LINE_LENGTH  # Expect to be 88

    @property
    @lru_cache()
    def config_file(self):
        """File path to the black configuration file."""
        if self.flake8_black_config:
            flake8_black_path = Path(self.flake8_black_config)

            if self.flake8_config:
                flake8_config_path = path.dirname(path.abspath(self.flake8_config))
                return Path(flake8_config_path) / flake8_black_path

            return flake8_black_path

        source_path = (
            self.filename
            if self.filename not in self.STDIN_NAMES
            else Path.cwd().as_posix()
        )
        project_root = black.find_project_root((Path(source_path),))
        return project_root / "pyproject.toml"

    def _load_black_config(self):
        if self.config_file.is_file():
            LOG.info("flake8-black: Loading black config from %s" % self.config_file)
            pyproject_toml = toml.load(str(self.config_file))
            config = pyproject_toml.get("tool", {}).get("black", {})
            return {k.replace("--", "").replace("-", "_"): v for k, v in config.items()}
        elif self.config_file:
            LOG.info("flake8-black: Did not find %s" % self.config_file)
        return None

    @property
    def _file_mode(self):
        target_versions = set()
        skip_string_normalization = False

        black_config = self._load_black_config()
        if black_config:
            target_versions = {
                black.TargetVersion[val.upper()]
                for val in black_config.get("target_version", [])
            }
            self.line_length = black_config.get("line_length", self.line_length)
            skip_string_normalization = black_config.get(
                "skip_string_normalization", False
            )
        # Requires black 19.3b0 or later:
        return black.FileMode(
            target_versions=target_versions,
            line_length=self.line_length,
            string_normalization=not skip_string_normalization,
        )

    @classmethod
    def add_options(cls, parser):
        """Adding black-config option."""
        parser.add_option(
            "--black-config",
            default=None,
            action="store",
            type="string",
            parse_from_config=True,
            help="Path to black configuration file "
            "(overrides the default pyproject.toml)",
        )

    @classmethod
    def parse_options(cls, options):
        """Adding black-config option."""
        cls.flake8_black_config = options.black_config
        cls.flake8_config = options.config

    def run(self):
        """Use black to check code style."""
        msg = None
        line = 0
        col = 0

        try:
            if self.filename in self.STDIN_NAMES:
                self.filename = "stdin"
                source = stdin_utils.stdin_get_value()
            else:
                with open(self.filename, "rb") as buf:
                    source, _, _ = black.decode_bytes(buf.read())
        except Exception as e:
            source = ""
            msg = "900 Failed to load file: %s" % e

        if not source and not msg:
            # Empty file (good)
            return
        elif source:
            # Call black...
            try:
                new_code = black.format_file_contents(
                    source, mode=self._file_mode, fast=False
                )
            except black.NothingChanged:
                return
            except black.InvalidInput:
                msg = "901 Invalid input."
            except Exception as e:
                msg = "999 Unexpected exception: %s" % e
            else:
                assert (
                    new_code != source
                ), "Black made changes without raising NothingChanged"
                line, col = find_diff_start(source, new_code)
                line += 1  # Strange as col seems to be zero based?
                msg = "100 Black would make changes."
        # If we don't know the line or column numbers, leaving as zero.
        yield line, col, black_prefix + msg, type(self)
