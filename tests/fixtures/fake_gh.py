#!/usr/bin/env python3
"""A fake ``gh`` executable backed by a JSON state file.

Lets the whole GitHub-facing surface be integration-tested without a GitHub
account, a network, or a real ``gh`` install (SPEC 63).

Control via environment:

``RH_FAKE_GH_STATE``       path to the JSON state file (required)
``RH_FAKE_GH_FAIL``        ``auth`` | ``network`` | ``other`` — inject failures
``RH_FAKE_GH_FAIL_TIMES``  fail this many invocations, then succeed (retry tests)
``RH_FAKE_GH_LOG``         append each argv (JSON) here, for assertions
"""

import json
import os
import sys

AUTH_ERROR = "gh: To use GitHub CLI in a GitHub Actions workflow, run: gh auth login\nHTTP 401: Bad credentials"
NETWORK_ERROR = "error connecting to api.github.com\ndial tcp: lookup api.github.com: temporary failure in name resolution"
OTHER_ERROR = "GraphQL: Something unexpected happened (createIssue)"


def state_path():
    path = os.environ.get("RH_FAKE_GH_STATE")
    if not path:
        sys.stderr.write("fake gh: RH_FAKE_GH_STATE is not set\n")
        raise SystemExit(3)
    return path


def load():
    path = state_path()
    if not os.path.exists(path):
        return {"repo": "octo/research", "issues": {}, "prs": {}, "next_issue": 1, "next_pr": 1000, "calls": 0}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save(state):
    with open(state_path(), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def log_call(argv):
    path = os.environ.get("RH_FAKE_GH_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(argv) + "\n")


def maybe_fail(state):
    mode = os.environ.get("RH_FAKE_GH_FAIL", "").strip().lower()
    if not mode or mode == "none":
        return
    limit = os.environ.get("RH_FAKE_GH_FAIL_TIMES")
    if limit:
        state["calls"] = int(state.get("calls", 0)) + 1
        save(state)
        if state["calls"] > int(limit):
            return
    message = {"auth": AUTH_ERROR, "network": NETWORK_ERROR}.get(mode, OTHER_ERROR)
    sys.stderr.write(message + "\n")
    raise SystemExit(1)


def next_timestamp(state):
    """Monotonic ISO timestamps so ordering in listings is deterministic."""
    seq = int(state.get("clock", 0)) + 1
    state["clock"] = seq
    return "2026-09-%02dT%02d:00:00Z" % (1 + (seq // 24) % 28, seq % 24)


def take(args, flag):
    """Return the value following ``flag`` and remove both from ``args``."""
    if flag in args:
        index = args.index(flag)
        value = args[index + 1] if index + 1 < len(args) else ""
        del args[index : index + 2]
        return value
    return None


def take_all(args, flag):
    values = []
    while flag in args:
        values.append(take(args, flag))
    return values


def body_of(args):
    path = take(args, "--body-file")
    if path:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    return take(args, "--body") or ""


def out(text):
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def issue_url(state, number):
    return "https://github.com/%s/issues/%d" % (state["repo"], number)


def pr_url(state, number):
    return "https://github.com/%s/pull/%d" % (state["repo"], number)


def main(argv):
    log_call(argv)
    args = list(argv)
    if not args:
        out("gh version 2.60.0 (fake)")
        return 0
    if args[0] in ("--version", "version"):
        out("gh version 2.60.0 (fake)")
        return 0

    state = load()
    take(args, "--repo")
    take(args, "--header")

    if args[:2] == ["auth", "status"]:
        maybe_fail(state)
        out("github.com\n  - Logged in to github.com as fake-user")
        return 0

    maybe_fail(state)
    command = args[0]

    if command == "repo" and args[1:2] == ["view"]:
        fields = (take(args, "--json") or "").split(",")
        payload = {}
        if "nameWithOwner" in fields:
            payload["nameWithOwner"] = state["repo"]
        if "defaultBranchRef" in fields:
            payload["defaultBranchRef"] = {"name": state.get("default_branch", "main")}
        out(json.dumps(payload))
        return 0

    if command == "issue":
        return issue_command(state, args)
    if command == "pr":
        return pr_command(state, args)
    if command == "api":
        return api_command(state, args)

    sys.stderr.write("fake gh: unsupported command: %s\n" % " ".join(argv))
    return 2


def issue_command(state, args):
    action = args[1] if len(args) > 1 else ""
    if action == "create":
        title = take(args, "--title") or ""
        labels = take_all(args, "--label")
        body = body_of(args)
        number = int(state["next_issue"])
        state["next_issue"] = number + 1
        state["issues"][str(number)] = {
            "number": number,
            "title": title,
            "body": body,
            "state": "OPEN",
            "labels": [{"name": name} for name in labels],
            "comments": [],
            "url": issue_url(state, number),
            "createdAt": next_timestamp(state),
        }
        save(state)
        out(issue_url(state, number))
        return 0

    if action == "view":
        number = args[2]
        issue = state["issues"].get(str(number))
        if issue is None:
            sys.stderr.write("gh: issue not found\n")
            return 1
        fields = (take(args, "--json") or "").split(",")
        payload = {key: issue.get(key) for key in fields if key in issue}
        out(json.dumps(payload))
        return 0

    if action == "list":
        wanted = (take(args, "--state") or "open").upper()
        limit = take(args, "--limit")
        label = take(args, "--label")
        # Real `gh` returns exactly the fields requested via --json, so the
        # fake must too: callers rely on asking for `body` to find markers.
        fields = [f for f in (take(args, "--json") or "").split(",") if f]
        items = []
        for issue in state["issues"].values():
            if wanted != "ALL" and issue["state"] != wanted:
                continue
            if label and label not in [lab["name"] for lab in issue.get("labels", [])]:
                continue
            items.append({key: issue.get(key) for key in fields} if fields else dict(issue))
        items.sort(key=lambda item: item.get("number") or 0, reverse=True)
        if limit:
            items = items[: int(limit)]
        out(json.dumps(items))
        return 0

    if action == "comment":
        number = args[2]
        issue = state["issues"].get(str(number))
        if issue is None:
            sys.stderr.write("gh: issue not found\n")
            return 1
        body = body_of(args)
        comment_id = 100000 + sum(len(i.get("comments", [])) for i in state["issues"].values())
        url = "%s#issuecomment-%d" % (issue["url"], comment_id)
        issue.setdefault("comments", []).append(
            {"id": comment_id, "body": body, "html_url": url, "user": {"login": "fake-user"}}
        )
        save(state)
        out(url)
        return 0

    if action == "close":
        number = args[2]
        issue = state["issues"].get(str(number))
        if issue is None:
            sys.stderr.write("gh: issue not found\n")
            return 1
        issue["state"] = "CLOSED"
        save(state)
        out("closed %s" % number)
        return 0

    if action == "edit":
        number = args[2]
        issue = state["issues"].get(str(number))
        if issue is None:
            sys.stderr.write("gh: issue not found\n")
            return 1
        issue["body"] = body_of(args)
        save(state)
        out(issue["url"])
        return 0

    sys.stderr.write("fake gh: unsupported issue action: %s\n" % action)
    return 2


def pr_command(state, args):
    action = args[1] if len(args) > 1 else ""
    if action == "create":
        title = take(args, "--title") or ""
        head = take(args, "--head") or ""
        base = take(args, "--base") or state.get("default_branch", "main")
        draft = "--draft" in args
        body = body_of(args)
        number = int(state["next_pr"])
        state["next_pr"] = number + 1
        state["prs"][str(number)] = {
            "number": number,
            "title": title,
            "body": body,
            "state": "OPEN",
            "isDraft": draft,
            "headRefName": head,
            "baseRefName": base,
            "url": pr_url(state, number),
            "mergedAt": None,
            "comments": [],
        }
        save(state)
        out(pr_url(state, number))
        return 0

    if action == "view":
        ref = args[2]
        take(args, "--json")
        pr = state["prs"].get(str(ref))
        if pr is None:
            for candidate in state["prs"].values():
                if candidate["headRefName"] == ref:
                    pr = candidate
                    break
        if pr is None:
            sys.stderr.write("gh: no pull requests found\n")
            return 1
        out(json.dumps(pr))
        return 0

    if action == "list":
        head = take(args, "--head")
        wanted = (take(args, "--state") or "open").upper()
        take(args, "--limit")
        take(args, "--json")
        items = [
            pr
            for pr in state["prs"].values()
            if (head is None or pr["headRefName"] == head) and (wanted == "ALL" or pr["state"] == wanted)
        ]
        out(json.dumps(items))
        return 0

    if action == "edit":
        number = args[2]
        pr = state["prs"].get(str(number))
        if pr is None:
            sys.stderr.write("gh: no pull requests found\n")
            return 1
        pr["body"] = body_of(args)
        save(state)
        out(pr["url"])
        return 0

    if action == "comment":
        number = args[2]
        pr = state["prs"].get(str(number))
        if pr is None:
            sys.stderr.write("gh: no pull requests found\n")
            return 1
        pr.setdefault("comments", []).append({"body": body_of(args)})
        save(state)
        out(pr["url"])
        return 0

    if action == "merge":
        # RDH must never reach this. Fail loudly so a regression is obvious.
        sys.stderr.write("fake gh: `gh pr merge` must never be invoked by RDH\n")
        return 99

    sys.stderr.write("fake gh: unsupported pr action: %s\n" % action)
    return 2


def api_command(state, args):
    paginate = "--paginate" in args
    if paginate:
        args.remove("--paginate")
    path = args[1] if len(args) > 1 else ""
    parts = path.strip("/").split("/")
    # repos/{owner}/{repo}/issues/{n}/comments
    if len(parts) >= 6 and parts[0] == "repos" and parts[3] == "issues" and parts[5] == "comments":
        issue = state["issues"].get(parts[4])
        comments = issue.get("comments", []) if issue else []
        if paginate and len(comments) > 2:
            # Emit multiple pages, exactly as `gh api --paginate` concatenates them.
            for start in range(0, len(comments), 2):
                out(json.dumps(comments[start : start + 2]))
            return 0
        out(json.dumps(comments))
        return 0
    sys.stderr.write("fake gh: unsupported api path: %s\n" % path)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
