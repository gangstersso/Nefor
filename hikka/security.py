"""Checks the commands' security"""

#    Friendly Telegram (telegram userbot)
#    Copyright (C) 2018-2021 The Authors

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

# █ █ ▀ █▄▀ ▄▀█ █▀█ ▀    ▄▀█ ▀█▀ ▄▀█ █▀▄▀█ ▄▀█
# █▀█ █ █ █ █▀█ █▀▄ █ ▄  █▀█  █  █▀█ █ ▀ █ █▀█
#
#              © Copyright 2022
#
#          https://t.me/hikariatama
#
# 🔒 Licensed under the GNU GPLv3
# 🌐 https://www.gnu.org/licenses/agpl-3.0.html

import logging
import time
from typing import Optional

from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import ChatParticipantAdmin, ChatParticipantCreator, Message

from . import main, utils

logger = logging.getLogger(__name__)

OWNER = 1 << 0
SUDO = 1 << 1
SUPPORT = 1 << 2
GROUP_OWNER = 1 << 3
GROUP_ADMIN_ADD_ADMINS = 1 << 4
GROUP_ADMIN_CHANGE_INFO = 1 << 5
GROUP_ADMIN_BAN_USERS = 1 << 6
GROUP_ADMIN_DELETE_MESSAGES = 1 << 7
GROUP_ADMIN_PIN_MESSAGES = 1 << 8
GROUP_ADMIN_INVITE_USERS = 1 << 9
GROUP_ADMIN = 1 << 10
GROUP_MEMBER = 1 << 11
PM = 1 << 12
EVERYONE = 1 << 13

BITMAP = {
    "OWNER": OWNER,
    "SUDO": SUDO,
    "SUPPORT": SUPPORT,
    "GROUP_OWNER": GROUP_OWNER,
    "GROUP_ADMIN_ADD_ADMINS": GROUP_ADMIN_ADD_ADMINS,
    "GROUP_ADMIN_CHANGE_INFO": GROUP_ADMIN_CHANGE_INFO,
    "GROUP_ADMIN_BAN_USERS": GROUP_ADMIN_BAN_USERS,
    "GROUP_ADMIN_DELETE_MESSAGES": GROUP_ADMIN_DELETE_MESSAGES,
    "GROUP_ADMIN_PIN_MESSAGES": GROUP_ADMIN_PIN_MESSAGES,
    "GROUP_ADMIN_INVITE_USERS": GROUP_ADMIN_INVITE_USERS,
    "GROUP_ADMIN": GROUP_ADMIN,
    "GROUP_MEMBER": GROUP_MEMBER,
    "PM": PM,
    "EVERYONE": EVERYONE,
}

GROUP_ADMIN_ANY = (
    GROUP_ADMIN_ADD_ADMINS
    | GROUP_ADMIN_CHANGE_INFO
    | GROUP_ADMIN_BAN_USERS
    | GROUP_ADMIN_DELETE_MESSAGES
    | GROUP_ADMIN_PIN_MESSAGES
    | GROUP_ADMIN_INVITE_USERS
    | GROUP_ADMIN
)

DEFAULT_PERMISSIONS = OWNER | SUDO

PUBLIC_PERMISSIONS = GROUP_OWNER | GROUP_ADMIN_ANY | GROUP_MEMBER | PM

ALL = (1 << 13) - 1


def owner(func: callable) -> callable:
    return _sec(func, OWNER)


def sudo(func: callable) -> callable:
    return _sec(func, SUDO)


def support(func: callable) -> callable:
    return _sec(func, SUDO | SUPPORT)


def group_owner(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_OWNER)


def group_admin_add_admins(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN_ADD_ADMINS)


def group_admin_change_info(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN_CHANGE_INFO)


def group_admin_ban_users(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN_BAN_USERS)


def group_admin_delete_messages(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN_DELETE_MESSAGES)


def group_admin_pin_messages(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN_PIN_MESSAGES)


def group_admin_invite_users(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN_INVITE_USERS)


def group_admin(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_ADMIN)


def group_member(func: callable) -> callable:
    return _sec(func, SUDO | GROUP_MEMBER)


def pm(func: callable) -> callable:
    return _sec(func, SUDO | PM)


def unrestricted(func: callable) -> callable:
    return _sec(func, ALL)


def inline_everyone(func: callable) -> callable:
    return _sec(func, EVERYONE)


def _sec(func: callable, flags: int) -> callable:
    prev = getattr(func, "security", 0)
    func.security = prev | OWNER | flags
    return func


class SecurityManager:
    def __init__(self, db):
        self._any_admin = db.get(__name__, "any_admin", False)
        self._default = db.get(__name__, "default", DEFAULT_PERMISSIONS)
        self._db = db
        self._reload_rights()
        self._cache = {}

    def _reload_rights(self):
        self._owner = list(
            set(
                self._db.get(__name__, "owner", []).copy()
                + ([self._me] if hasattr(self, "_me") else [])
            )
        )
        self._sudo = list(set(self._db.get(__name__, "sudo", []).copy()))
        self._support = list(set(self._db.get(__name__, "support", []).copy()))

    async def init(self, client):
        self._client = client
        self._me = (await client.get_me()).id

    def get_flags(self, func: callable) -> int:
        if isinstance(func, int):
            config = func
        else:
            # Return masks there so user don't need to reboot
            # every time he changes permissions. It doesn't
            # decrease security at all, bc user anyway can
            # access this attribute
            config = self._db.get(__name__, "masks", {}).get(
                f"{func.__module__}.{func.__name__}",
                getattr(func, "security", self._default),
            )

        if config & ~ALL and not config & EVERYONE:
            logger.error("Security config contains unknown bits")
            return False

        return config & self._db.get(__name__, "bounding_mask", DEFAULT_PERMISSIONS)

    async def _check(
        self,
        message: Message,
        func: callable,
        user: Optional[int] = None,
    ) -> bool:
        """Checks if message sender is permitted to execute certain function"""
        self._reload_rights()

        if not (config := self.get_flags(func)):
            return False

        if not user:
            user = message.sender_id

        if user == self._me or getattr(message, "out", False):
            return True

        logger.debug(f"Checking security match for {config}")

        f_owner = config & OWNER
        f_sudo = config & SUDO
        f_support = config & SUPPORT
        f_group_owner = config & GROUP_OWNER
        f_group_admin_add_admins = config & GROUP_ADMIN_ADD_ADMINS
        f_group_admin_change_info = config & GROUP_ADMIN_CHANGE_INFO
        f_group_admin_ban_users = config & GROUP_ADMIN_BAN_USERS
        f_group_admin_delete_messages = config & GROUP_ADMIN_DELETE_MESSAGES
        f_group_admin_pin_messages = config & GROUP_ADMIN_PIN_MESSAGES
        f_group_admin_invite_users = config & GROUP_ADMIN_INVITE_USERS
        f_group_admin = config & GROUP_ADMIN
        f_group_member = config & GROUP_MEMBER
        f_pm = config & PM

        f_group_admin_any = (
            f_group_admin_add_admins
            or f_group_admin_change_info
            or f_group_admin_ban_users
            or f_group_admin_delete_messages
            or f_group_admin_pin_messages
            or f_group_admin_invite_users
            or f_group_admin
        )

        if (
            f_owner
            and user in self._owner
            or f_sudo
            and user in self._sudo
            or f_support
            and user in self._support
        ):
            return True

        if user in self._db.get(main.__name__, "blacklist_users", []):
            return False

        if message is None:  # In case of checking inline query security map
            return bool(config & EVERYONE)

        if f_group_member and message.is_group or f_pm and message.is_private:
            return True

        if message.is_channel:
            if not message.is_group:
                if message.edit_date:
                    return False

                chat_id = utils.get_chat_id(message)
                if (
                    chat_id in self._cache
                    and self._cache[chat_id]["exp"] >= time.time()
                ):
                    chat = self._cache[chat_id]["chat"]
                else:
                    chat = await message.get_chat()
                    self._cache[chat_id] = {"chat": chat, "exp": time.time() + 5 * 60}

                if (
                    not chat.creator
                    and not chat.admin_rights
                    or not chat.creator
                    and not chat.admin_rights.post_messages
                ):
                    return False

                if self._any_admin and f_group_admin_any or f_group_admin:
                    return True
            elif f_group_admin_any or f_group_owner:
                chat_id = utils.get_chat_id(message)
                cache_obj = f"{chat_id}/{user}"
                if (
                    cache_obj in self._cache
                    and self._cache[cache_obj]["exp"] >= time.time()
                ):
                    participant = self._cache[cache_obj]["user"]
                else:
                    participant = await message.client.get_permissions(
                        message.peer_id,
                        user,
                    )
                    self._cache[cache_obj] = {
                        "user": participant,
                        "exp": time.time() + 5 * 60,
                    }

                if (
                    participant.is_creator
                    or participant.is_admin
                    and (
                        self._any_admin
                        and f_group_admin_any
                        or f_group_admin
                        or f_group_admin_add_admins
                        and participant.add_admins
                        or f_group_admin_change_info
                        and participant.change_info
                        or f_group_admin_ban_users
                        and participant.ban_users
                        or f_group_admin_delete_messages
                        and participant.delete_messages
                        or f_group_admin_pin_messages
                        and participant.pin_messages
                        or f_group_admin_invite_users
                        and participant.invite_users
                    )
                ):
                    return True
            return False

        if message.is_group and (f_group_admin_any or f_group_owner):
            chat_id = utils.get_chat_id(message)
            cache_obj = f"{chat_id}/{user}"

            if (
                cache_obj in self._cache
                and self._cache[cache_obj]["exp"] >= time.time()
            ):
                participant = self._cache[cache_obj]["user"]
            else:
                full_chat = await message.client(GetFullChatRequest(message.chat_id))
                participants = full_chat.full_chat.participants.participants
                participant = next(
                    (
                        possible_participant
                        for possible_participant in participants
                        if possible_participant.user_id == message.sender_id
                    ),
                    None,
                )
                self._cache[cache_obj] = {
                    "user": participant,
                    "exp": time.time() + 5 * 60,
                }

            if not participant:
                return

            if (
                isinstance(participant, ChatParticipantCreator)
                or isinstance(participant, ChatParticipantAdmin)
                and f_group_admin_any
            ):
                return True

        return False

    check = _check
