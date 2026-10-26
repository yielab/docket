"""The ``when.command`` policy predicate: a shell command read by invocation."""

from __future__ import annotations

import pytest

from docket.governance import policy as _policy
from docket.governance.policy_command import command_matches, validate_command

SUBJECT = "docket.governance.policy_command"


def _matches(spec: dict[str, object], command: str, tool: str = "bash") -> bool:
    return command_matches(spec, tool, {"command": command})


class TestProgramVerbArgsWrites:
    def test_program_names_the_invocation_after_quoting_and_wrappers(self) -> None:
        spec = {"program": "rm"}

        assert _matches(spec, "rm x")
        assert _matches(spec, '"rm" x')
        assert _matches(spec, "env FOO=1 xargs rm")
        assert not _matches(spec, "echo rm")

    def test_program_accepts_a_glob(self) -> None:
        assert _matches({"program": "mkfs*"}, "mkfs.ext4 /dev/sdb1")
        assert not _matches({"program": "mkfs*"}, "mkdir x")

    def test_verb_is_found_past_options_and_their_values(self) -> None:
        spec = {"program": "kubectl", "verb": ["apply", "delete"]}

        assert _matches(spec, "kubectl apply -f d.yaml")
        assert _matches(spec, "kubectl -n prod apply -f d.yaml")
        assert _matches(spec, "kubectl --context=prod delete deploy app")
        assert not _matches(spec, "kubectl get pods -n apply-ns")

    def test_a_single_letter_option_names_the_cluster_it_sits_in(self) -> None:
        spec = {"program": "rm", "args": ["-r", "-f", "--recursive"]}

        assert _matches(spec, "rm -rf build")
        assert _matches(spec, "rm -fr build")
        assert _matches(spec, "rm --recursive build")
        assert not _matches(spec, "rm build")
        assert not _matches(spec, "rm --force-not-this build")

    def test_an_arg_with_a_glob_character_is_a_pattern_and_any_other_is_a_word(self) -> None:
        spec = {"program": "git", "verb": ["push"], "args": ["+*", "*:*", "main"]}

        assert _matches(spec, "git push origin +feature")
        assert _matches(spec, "git push origin HEAD:refs/heads/x")
        assert _matches(spec, "git push origin main")
        assert not _matches(spec, "git push origin feature")
        assert not _matches(spec, "git pull origin main2")

    def test_every_key_must_hold_for_the_same_invocation(self) -> None:
        spec = {"program": "git", "verb": ["reset"], "args": ["--hard"]}

        assert _matches(spec, "git reset --hard HEAD~1")
        assert not _matches(spec, "git reset HEAD~1")
        assert not _matches(spec, "git status --hard; git reset x")

    def test_writes_are_globs_over_redirects_and_known_writers(self) -> None:
        spec = {"writes": ["*.env", "*.ssh/*"]}

        assert _matches(spec, "echo k=v > .env")
        assert _matches(spec, "cat k >> ~/.ssh/authorized_keys")
        assert _matches(spec, "cp x app/.env")
        assert _matches(spec, "tee .env")
        assert not _matches(spec, "cat .env")
        assert not _matches(spec, "ls ~/.ssh/")

    def test_any_invocation_behind_a_separator_can_satisfy_it(self) -> None:
        assert _matches({"program": "rm"}, "ls && echo a | rm x")

    def test_only_a_bash_call_with_a_readable_command_matches(self) -> None:
        assert not _matches({"program": "rm"}, "rm x", tool="write")
        assert not command_matches({"program": "rm"}, "bash", {})
        assert not command_matches({"program": "rm"}, "bash", {"command": 3})
        assert not _matches({"program": "rm"}, "rm 'unclosed")


class TestValidation:
    @pytest.mark.parametrize(
        "command",
        [{"program": "rm"}, {"verb": ["apply"], "args": ["-f"]}, {"writes": "*.env"}],
    )
    def test_a_well_formed_mapping_is_valid(self, command: object) -> None:
        assert validate_command(command, "p") == ""

    @pytest.mark.parametrize(
        ("command", "needle"),
        [
            ("rm", "non-empty mapping"),
            ({}, "non-empty mapping"),
            ({"programme": "rm"}, "unknown when.command key"),
            ({"program": []}, "when.command.program"),
            ({"args": [1]}, "when.command.args"),
            ({"writes": ["", "x"]}, "when.command.writes"),
        ],
    )
    def test_a_malformed_mapping_names_the_problem(self, command: object, needle: str) -> None:
        assert needle in validate_command(command, "p")

    def test_a_policy_with_a_bad_command_fails_validation_and_a_good_one_does_not(self) -> None:
        good = {
            "id": "p",
            "applies_to": ["*"],
            "hook": "pre_tool_call",
            "action": "require_approval",
            "when": {"command": {"program": "rm"}},
        }
        bad = {**good, "when": {"command": {"program": ""}}}

        assert _policy._validate_doc(good, "p") == ""
        assert "when.command.program" in _policy._validate_doc(bad, "p")
