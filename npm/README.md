# triobot (npm launcher)

**Train your own AI. Deploy it everywhere. Own it forever.**

This is the **npm launcher** for [trio.ai](https://github.com/iampopye/trio). trio.ai is a
Python application — this package gives it an `npm` install path so you can run it the same
way you run other CLIs like `npx`.

> **Requires Python 3.10+** on your machine. npm only launches trio; it does not replace the
> Python runtime. If you already use Python, prefer `pip install triobot` directly.

## Install

```bash
# Global install — adds the `trio` command
npm install -g triobot
trio onboard

# Or run without installing
npx triobot onboard
```

On first run the launcher installs the `triobot` Python package automatically.

## Then

```bash
trio agent            # interactive chat
trio serve            # web UI on http://localhost:28337
trio --version
trio help
```

## How it works

The `trio` command from this package:

1. Finds a compatible Python (`py -3` / `python3` / `python`, 3.10+).
2. Ensures the `triobot` PyPI package is installed.
3. Forwards all arguments to `python -m trio`.

Set `TRIO_SKIP_POSTINSTALL=1` to skip the automatic install step during `npm install`.

## Prefer pip?

```bash
pip install triobot
trio onboard
```

Both paths run the exact same CLI.

## License

MIT © 2026 Karan Garg
