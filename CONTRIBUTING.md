# Contributing

Thanks for helping keep this list accurate. There's one file to edit: [`agents.yaml`](agents.yaml). Never edit `README.md` by hand; it's regenerated automatically and your change would be overwritten.

## What belongs here

An agent is included when it is:

1. **Open source**: the code is public on GitHub under an open-source license.
2. **A coding agent**: an LLM writes or changes code beyond single-line autocomplete, for example editing files, running commands, fixing issues or generating a codebase.
3. **A usable tool**: something people can install or run, not a paper with no code, a prompt collection, or a general-purpose agent framework.

Inactive or archived projects stay listed; the status column tells readers what they're getting. Entries are only removed when the repo is deleted or the project stops meeting the rules above.

## Adding an agent

Add an entry under the right category in `agents.yaml`:

```yaml
  - name: My Agent
    repo: owner/my-agent
    description: One line in your own words, under 120 characters.
    category: terminal          # terminal | ide | autonomous | app-builder | multi-agent
    interface: [terminal, ide]  # any of: terminal, ide, web, desktop
    models: Any provider        # short text, e.g. "Claude", "Any (via LiteLLM)"
    local: true                 # optional: can it run on a local model?
```

Don't add stars, license or dates; the updater fetches them.

Check your entry before opening a pull request:

```bash
pip install -r requirements.txt
python scripts/update.py --check
```

The same check runs on every pull request, along with a check that the repo exists.

## Style

- Describe what the agent *does*, not marketing claims ("fast", "best", "revolutionary").
- Don't copy the project's own tagline; write it in your words.
- Use the project's own capitalisation for its name.

## Changing the page layout

Edit [`templates/README.template.md`](templates/README.template.md), then rebuild locally without hitting the API:

```bash
python scripts/update.py --offline
```
