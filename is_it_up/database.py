# coding=utf-8
"""
Checking database access
"""

import socket
from typing import Dict, Optional, Union

from is_it_up.base import IsItUpBase

_ = Dict, Union, Optional


class DatabaseChecker(IsItUpBase):
    def __init__(
        self, host: str, user: str, database: str, password: str, port: Union[str, int]
    ):
        super(DatabaseChecker, self).__init__()
        pass

    def check_postgres(self):
        pass

    def check_mysql(self):
        pass
