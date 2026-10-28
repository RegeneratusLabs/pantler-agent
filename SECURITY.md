# Security

Pantler runs on your own machine, holds your business records, and is reachable from your browser
at a loopback address. That is a small attack surface, but it is a real one: a page you visit can
make requests a browser will make to `127.0.0.1`, and any local process can reach a listening
port.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's [private vulnerability
reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository (*Security* → *Report a vulnerability*). That opens a draft advisory only the
maintainers and you can see.

Useful in a report: what you can reach, what you expected, the exact request or file, and whether
you reproduced it against a real server. A reasoned claim is welcome; a reproduced one is better.

## What is in scope

- The BFF in `app/server`: origin and host checks, the write guards, path handling, the preview
  jail, the attachment and record routes.
- The profile boundary: whether one business's workspace, credentials, records or output can be
  reached from another's session.
- The distribution and the scripts that ship it: whether a skill or plugin can be made to execute
  something it should not, and whether the generated payload can drift from its source.
- The web app: anything that lets a page or a renderer run script it should not, and anything that
  exposes the engine key to the browser.

## What is out of scope

- **The Hermes engine.** It is a separate project at a pinned commit. Report engine issues
  [upstream](https://github.com/NousResearch/hermes-agent).
- **Your own machine.** If an attacker already runs code as your user, they can read the records
  file. Pantler does not claim to be an OS sandbox, and the tool-call boundary is a guard rather
  than a jail.
- **A model that has been socially engineered** into calling a legitimate tool with hostile
  arguments. Pantler's answer is deterministic resolution plus an approval card for the writes
  that matter, not a promise that a language model cannot be fooled.

## Expectations

This is an early project without a bug bounty. Reports are read, acknowledged when there is
something to say, and fixed in the open once a release carries the fix — with credit unless you
ask otherwise.
