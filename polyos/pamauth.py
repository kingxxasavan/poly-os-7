"""Check a password with PAM (the lock screen), without any extra Python package.

Uses libpam through ctypes with the "polyos-lock" service (/etc/pam.d/polyos-lock, which
includes Debian's common-auth). An unprivileged process may check only its own user's
password: pam_unix does it through the setgid unix_chkpwd helper, like any screen locker.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging

log = logging.getLogger("polyos.pam")

PAM_PROMPT_ECHO_OFF = 1
PAM_PROMPT_ECHO_ON = 2
PAM_SUCCESS = 0
SERVICE = "polyos-lock"


class _Message(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class _Response(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_char_p), ("resp_retcode", ctypes.c_int)]


_CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(_Message)),
                         ctypes.POINTER(ctypes.POINTER(_Response)), ctypes.c_void_p)


class _Conv(ctypes.Structure):
    _fields_ = [("conv", _CONV), ("appdata_ptr", ctypes.c_void_p)]


_libs: tuple | None = None


def _load():
    global _libs
    if _libs is None:
        pam_name = ctypes.util.find_library("pam")
        libc_name = ctypes.util.find_library("c")
        if not pam_name or not libc_name:
            raise OSError("libpam is not available")
        pam = ctypes.CDLL(pam_name)
        libc = ctypes.CDLL(libc_name)
        libc.calloc.restype = ctypes.c_void_p
        libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        libc.strdup.restype = ctypes.c_void_p
        libc.strdup.argtypes = [ctypes.c_char_p]
        pam.pam_start.restype = ctypes.c_int
        pam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(_Conv), ctypes.POINTER(ctypes.c_void_p)]
        pam.pam_authenticate.restype = ctypes.c_int
        pam.pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_acct_mgmt.restype = ctypes.c_int
        pam.pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_end.restype = ctypes.c_int
        pam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _libs = (pam, libc)
    return _libs


def authenticate(user: str, password: str, service: str = SERVICE) -> bool:
    """True if `password` is `user`'s password."""
    pam, libc = _load()
    secret = password.encode("utf-8")

    @_CONV
    def conversation(n, messages, responses, _data):
        # PAM frees the answers itself, so they must come from the C heap.
        addr = libc.calloc(n, ctypes.sizeof(_Response))
        responses[0] = ctypes.cast(addr, ctypes.POINTER(_Response))
        for i in range(n):
            if messages[i].contents.msg_style in (PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON):
                responses[0][i].resp = ctypes.cast(libc.strdup(secret), ctypes.c_char_p)
                responses[0][i].resp_retcode = 0
        return PAM_SUCCESS

    handle = ctypes.c_void_p()
    conv = _Conv(conversation, None)
    rc = pam.pam_start(service.encode(), user.encode(), ctypes.byref(conv), ctypes.byref(handle))
    if rc != PAM_SUCCESS:
        log.warning("pam_start failed (%s)", rc)
        return False
    try:
        rc = pam.pam_authenticate(handle, 0)
        if rc == PAM_SUCCESS:
            rc = pam.pam_acct_mgmt(handle, 0)
        return rc == PAM_SUCCESS
    finally:
        pam.pam_end(handle, rc)
