# Contributing to trio.ai

Thanks for your interest in contributing! Here's how to get started.

## How to Contribute

1. **Fork** this repository
2. **Clone** your fork locally
3. **Create a branch** for your change: `git checkout -b feature/my-feature`
4. **Make your changes** and test them
5. **Commit** with a clear message: `git commit -m "feat: add my feature"`
6. **Push** to your fork: `git push origin feature/my-feature`
7. **Open a Pull Request** against `main`

## Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `chore:` — maintenance tasks

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Include a clear description of what and why
- Update documentation if needed
- Make sure existing functionality isn't broken

## Development Setup

```bash
git clone https://github.com/<your-username>/trio.git
cd trio
pip install -e ".[dev,model]"
python test_setup.py
```

## Code of Conduct

Be respectful. We're building something cool together.

## Questions?

Open an issue or start a discussion.
