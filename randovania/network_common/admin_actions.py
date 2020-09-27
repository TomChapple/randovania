from enum import Enum


class SessionAdminGlobalAction(Enum):
    """Actions that operate on the session itself"""
    CREATE_ROW = "create_row"
    CHANGE_ROW = "change_row"
    DELETE_ROW = "delete_row"
    CHANGE_LAYOUT_DESCRIPTION = "change_layout_description"
    DOWNLOAD_LAYOUT_DESCRIPTION = "download_layout_description"
    START_SESSION = "start_session"
    RESET_SESSION = "reset_session"


class SessionAdminUserAction(Enum):
    """Actions that operate on top of an user"""
    KICK = "kick"
    MOVE = "move"
    SWITCH_IS_OBSERVER = "switch_is_observer"
    SWITCH_ADMIN = "switch_admin"
    CREATE_PATCHER_FILE = "create_patcher_file"
    ABANDON = "abandon"
