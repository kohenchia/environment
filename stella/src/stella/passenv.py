"""Which credentials Stella's sessions run on: the `pass_env` variables, on or off.

The owner names the variables (`pass_env`, typically a token that bills a shared
quota instead of their own). One stored switch says whether they are in use, and
everything Stella starts follows it: team windows, her own session, and the
scheduler's headless runs (daily log, nightly jobs, catch-up passes).

    switch on   each variable is set: from `<pass_env_dir>/<NAME>` (one file per
                variable, so a rotated value is picked up), else from the caller's environment
    switch off  each variable is removed, even if tmux or the caller has it

`stella run` sets the switch from its own environment (started with the variables,
everything runs on them; started without, nothing does) unless told `--pass-env on|off`.
`stella pass-env on|off` flips it mid-day. With no switch recorded yet, the caller's
environment decides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from stella import ledger
from stella.config import settings, store_dir


def _file() -> Path:
    return store_dir() / "pass-env.json"


def mode() -> str | None:
    """'on', 'off', or None when no switch has been recorded."""
    try:
        m = json.loads(_file().read_text()).get("mode")
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return m if m in {"on", "off"} else None


def set_mode(m: str, by: str) -> dict | None:
    """Record the switch; returns the ledger event, or None if it was already so. Refuses
    (SystemExit, switch unchanged) to turn on when a variable has no value anywhere."""
    if m == "on":
        _, missing = _values()
        if missing:
            raise SystemExit(f"not switched on: {_missing_text(missing)}")
    if m == mode():
        return None
    store_dir().mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps({"mode": m, "by": by, "ts": ledger.now().isoformat()}))
    names = ", ".join(settings().pass_env)
    return ledger.append("pass_env", by=by, mode=m, text=f"pass_env {m} ({names})")


def from_environment() -> str:
    """What the caller's own environment says: 'on' if it has every variable."""
    names = settings().pass_env
    return "on" if names and all(os.environ.get(k) for k in names) else "off"


def _from_dir(name: str) -> str | None:
    d = settings().pass_env_dir
    if not d:
        return None
    try:
        return (d / name).read_text().strip() or None
    except OSError:
        return None


def resolve() -> dict[str, str | None]:
    """Each variable's value for a session started now; None means 'remove it'.

    Raises SystemExit when the switch is on but a value is nowhere to be found:
    starting the session anyway would quietly run it on the wrong credentials.
    """
    names = settings().pass_env
    m = mode()
    if m is None:
        return {k: os.environ.get(k) for k in names}
    if m == "off":
        return {k: None for k in names}
    out, missing = _values()
    if missing:
        raise SystemExit(f"pass_env is on but {_missing_text(missing)}")
    return out


def _values() -> tuple[dict[str, str | None], list[str]]:
    out = {k: _from_dir(k) or os.environ.get(k) for k in settings().pass_env}
    return out, [k for k, v in out.items() if not v]


def _missing_text(missing: list[str]) -> str:
    d = settings().pass_env_dir
    where = f"{d}/<NAME>" if d else "anywhere else (no pass_env_dir is set)"
    return f"{', '.join(missing)} has no value in the environment or {where}"


def apply(env: dict[str, str]) -> dict[str, str]:
    """`env` with the pass_env variables set or removed per the switch."""
    out = dict(env)
    for k, v in resolve().items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def status() -> str:
    names = settings().pass_env
    if not names:
        return "No pass_env variables are configured."
    m = mode()
    lines = [f"pass_env: {', '.join(names)}",
             f"switch: {m or 'not set (each session follows its caller environment)'}"]
    for k in names:
        here = "set" if os.environ.get(k) else "unset"
        f = settings().pass_env_dir / k if settings().pass_env_dir else None
        lines.append(f"  {k}: this environment {here}; file {f if f else '-'} "
                     f"{'present' if f and f.exists() else 'missing' if f else ''}".rstrip())
    return "\n".join(lines)
