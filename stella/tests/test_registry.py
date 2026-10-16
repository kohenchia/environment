"""Requirement 17: teams are driven through their own interface, read live from their files."""


def test_core_teams(env):
    out = env.run("teams").stdout
    assert "builder (core)" in out and "investigator (core)" in out


def test_interface_reads_the_skill_live(env):
    out = env.run("team", "builder", "--no-help").stdout
    assert "Launch (first prompt to the lead): /stella:build {order}" in out
    assert "argument-hint" in out


def test_extension_team_and_live_argument_hint(env):
    skill = env.tmp / "skill.md"
    skill.write_text('---\nname: rev\ndescription: Reviews things.\nargument-hint: "<pr> [focus]"\n---\nbody\n')
    teams = f'[team.reviewer]\nsummary = "Reviews"\nwhen = "a review"\nlaunch = "/rev {{args}}"\nskill_file = "{skill}"\ncommands = ["echo usage: rev-cli status"]\n'
    env.extension(teams=teams)
    out = env.run("team", "reviewer").stdout
    assert "<pr> [focus]" in out and "usage: rev-cli status" in out
    skill.write_text('---\nname: rev\ndescription: Reviews things.\nargument-hint: "<pr> --deep"\n---\n')
    assert "<pr> --deep" in env.run("team", "reviewer").stdout
    r = env.run("launch", "reviewer", "--text", "review 12", "--args", "repo#12 deep", "--name", "rv", "--dry-run")
    assert "'/rev repo#12 deep'" in r.stdout


def test_name_collision_is_an_error(env):
    env.extension(teams='[team.builder]\nsummary = "x"\nwhen = "x"\n')
    assert "defined by both core and acme" in env.run("teams").stdout


def test_doctor_flags_a_missing_skill(env):
    env.extension(teams='[team.ghost]\nsummary = "x"\nwhen = "x"\nskill_file = "/nope/SKILL.md"\n')
    r = env.run("doctor", check=False)
    assert "team ghost interface: skill file missing" in r.stdout
