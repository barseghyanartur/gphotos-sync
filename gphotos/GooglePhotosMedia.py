#!/usr/bin/env python3
# coding: utf8

from pathlib import Path
from . import Utils
from .BaseMedia import BaseMedia
from typing import Dict, List, Union, Any
from datetime import datetime
import re

from .Checks import valid_file_name

DuplicateSuffix = re.compile(r"(.*)[ ]\(\d+\)(\..*)")

JSONValue = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]
JSONType = Union[Dict[str, JSONValue], List[JSONValue]]


class GooglePhotosMedia(BaseMedia):
    def __init__(self, media_json: JSONType, to_lower=False):
        self.__media_json: JSONType = media_json
        self.__uid: str = None
        self.__lower = to_lower
        super(GooglePhotosMedia, self).__init__()
        if self.is_video():
            self.__media_meta = None
            self.__media_meta = media_json.get("mediaMetadata").get("video")
        else:
            self.__media_meta = media_json.get("mediaMetadata").get("photo")

    @property
    def uid(self) -> str:
        return self.__uid

    # ----- override Properties below -----
    @property
    def size(self) -> int:
        return 0

    @property
    def id(self) -> str:
        return self.__media_json["id"]

    @property
    def description(self) -> str:
        try:
            return valid_file_name(self.__media_json["description"])
        except KeyError:
            return ""

    @property
    def orig_name(self) -> Path:
        try:
            name = self.__media_json["filename"]
            matches = DuplicateSuffix.match(name)
            if matches:
                # append the prefix and the suffix, ditching the ' (n)'
                name = "{}{}".format(*matches.groups())
        except KeyError:
            name = ""
        if self.__lower:
            name = name.lower()
        return Path(valid_file_name(name))

    @property
    def create_date(self) -> datetime:
        try:
            create_date = self.__media_json["mediaMetadata"].get("creationTime")
            photo_date = Utils.string_to_date(create_date)
        except (KeyError, ValueError):
            photo_date = Utils.MINIMUM_DATE

        return photo_date

    @property
    def modify_date(self) -> datetime:
        date = Utils.MINIMUM_DATE
        return date

    @property
    def mime_type(self) -> str:
        return self.__media_json.get("mimeType")

    @property
    def url(self) -> str:
        return self.__media_json.get("productUrl")

    @property
    def camera_model(self):
        camera_model = None
        try:
            camera_model = self.__media_meta.get("cameraModel")
        except (KeyError, AttributeError):
            pass
        return camera_model
