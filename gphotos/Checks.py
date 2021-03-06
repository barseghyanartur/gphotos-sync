import os

import re
import logging
import random
import shutil
import subprocess
from pathlib import Path
from psutil import disk_partitions

log = logging.getLogger(__name__)

MAX_PATH_LENGTH: int = 4096
MAX_FILENAME_LENGTH: int = 255
UNICODE_FILENAMES: bool = True
FILESYSTEM_TYPE: str = None
FILESYSTEM_IS_LINUX: bool = None

# regex for illegal characters in file names and database queries
fix_linux = re.compile(r"[/]|[\x00-\x1f]|\x7f|\x00")
fix_windows = re.compile(r'[<>:"/\\|?*]|[\x00-\x1f]|\x7f|\x00')
fix_windows_ending = re.compile("([ .]+$)")
fix_unicode = re.compile(r"[^\x00-\x7F]")


def checkFilesystem(mypath):
    global FILESYSTEM_TYPE, FILESYSTEM_IS_LINUX

    if not FILESYSTEM_TYPE:
        FILESYSTEM_TYPE = ""
        for part in disk_partitions():
            if part.mountpoint == "/":
                FILESYSTEM_TYPE = part.fstype
                continue

            if str(mypath).startswith(part.mountpoint):
                FILESYSTEM_TYPE = part.fstype
                break
        FILESYSTEM_TYPE = FILESYSTEM_TYPE.lower()
        FILESYSTEM_IS_LINUX = not (
            "fat" in FILESYSTEM_TYPE or "ntfs" in FILESYSTEM_TYPE
        )
        log.info(f"Target filesystem {mypath} is {FILESYSTEM_TYPE}")

    return FILESYSTEM_TYPE


def symlinks_supported(root_folder: Path) -> bool:
    log.debug("Checking if is filesystem supports symbolic links...")
    dst = "test_dst_%s" % random.getrandbits(32)
    src = "test_src_%s" % random.getrandbits(32)
    dst_file = root_folder / dst
    src_file = root_folder / src
    src_file.touch()
    try:
        dst_file.symlink_to(src_file)
        src_file.unlink()
        dst_file.unlink()
    except (OSError, FileNotFoundError):
        src_file.unlink()
        log.error("Symbolic links not supported")
        log.error("Albums are not going to be synced - requires symlinks")
        return False
    return True


def unicode_filenames(root_folder: Path) -> bool:
    global UNICODE_FILENAMES
    log.debug("Checking if File system supports unicode filenames...")
    testfile = root_folder / ".unicode_test.\U0001f604"
    # noinspection PyBroadException
    try:
        testfile.touch()
    except BaseException:
        log.info("Filesystem does not support Unicode filenames")
        UNICODE_FILENAMES = False
    else:
        log.info("Filesystem supports Unicode filenames")
        UNICODE_FILENAMES = True
        testfile.unlink()
    return UNICODE_FILENAMES


def is_case_sensitive(root_folder: Path) -> bool:
    log.debug("Checking if File system is case insensitive...")

    check_folder = root_folder / ".gphotos_check"
    case_file = check_folder / "Temp.Test"
    no_case_file = check_folder / "TEMP.TEST"
    try:
        check_folder.mkdir()
        case_file.touch()
        no_case_file.touch()
        files = list(check_folder.glob("*"))
        if len(files) != 2:
            raise ValueError("separate case files not seen")
        case_file.unlink()
        no_case_file.unlink()
    except (FileNotFoundError, ValueError):
        log.info("Case insensitive file system found")
        return False
    else:
        log.info("Case sensitive file system found")
        return True
    finally:
        shutil.rmtree(check_folder)


# noinspection PyBroadException
def get_max_path_length(root_folder: Path) -> int:
    global MAX_PATH_LENGTH
    # found this on:
    # https://stackoverflow.com/questions/32807560/how-do-i-get-in-python-the-maximum-filesystem-path-length-in-unix
    try:
        MAX_PATH_LENGTH = int(
            subprocess.check_output(["getconf", "PATH_MAX", str(root_folder)])
        )
    except BaseException:
        # for failures choose a safe size for Windows filesystems
        MAX_PATH_LENGTH = 248
        log.warning(
            f"cant determine max filepath length, defaulting to " f"{MAX_PATH_LENGTH}"
        )
    log.debug("MAX_PATH_LENGTH: %d" % MAX_PATH_LENGTH)
    return MAX_PATH_LENGTH


# noinspection PyBroadException
def get_max_filename_length(root_folder: Path) -> int:
    global MAX_FILENAME_LENGTH
    try:
        info = os.statvfs(str(root_folder))
        MAX_FILENAME_LENGTH = info.f_namemax
    except BaseException:
        # for failures choose a safe size for Windows filesystems
        MAX_FILENAME_LENGTH = 248
        log.warning(
            f"cant determine max filename length, "
            f"defaulting to {MAX_FILENAME_LENGTH}"
        )
    log.debug("MAX_FILENAME_LENGTH: %d" % MAX_FILENAME_LENGTH)
    return MAX_FILENAME_LENGTH


def valid_file_name(s: str) -> str:
    """
    makes sure a string is valid for creating file names

    :param (str) s: input string
    :return: (str): sanitized string
    """
    global UNICODE_FILENAMES, FILESYSTEM_IS_LINUX
    if FILESYSTEM_IS_LINUX:
        s = fix_linux.sub("_", s)
    else:
        s = fix_windows.sub("_", s)
        s = fix_windows_ending.split(s)[0]

    if not UNICODE_FILENAMES:
        s = fix_unicode.sub("_", s)
    return s
