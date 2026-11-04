# Live Coding Agents

**A self-updating directory of open-source AI coding agents.**

Most "awesome" lists go stale within months: links die, projects get abandoned, and star counts are years old. This one maintains itself. Every week a GitHub Action pulls fresh stats for every agent, flags projects that have gone quiet, follows repos that moved, and rebuilds this page.

<!-- SUMMARY -->

**Status legend:** 🟢 Active — commit in the last 90 days · 🟡 Slowing — 90–180 days · 🔴 Inactive — over 180 days · 🪦 Archived on GitHub

**Local** ✅ means the agent can run against a local model (Ollama, llama.cpp, LM Studio and similar).

## 📈 Trending

<!-- TRENDING -->

<!-- TABLES -->

## Add an agent

Know an open-source coding agent that's missing? Add one entry to [`agents.yaml`](agents.yaml) and open a pull request. You only fill in the description fields. Stars, license, activity and status are filled in automatically. See [CONTRIBUTING.md](CONTRIBUTING.md) for the inclusion rules, or [open an issue](../../issues/new/choose) if you'd rather suggest one.

## How it works

- [`agents.yaml`](agents.yaml) holds the hand-written facts about each agent.
- [`scripts/update.py`](scripts/update.py) queries the GitHub API, saves stats to [`data/stats.json`](data/stats.json), appends weekly star counts to [`data/history.jsonl`](data/history.jsonl) for trending, and regenerates this README from [`templates/README.template.md`](templates/README.template.md).
- [`.github/workflows/update.yml`](.github/workflows/update.yml) runs the script every Monday and whenever `agents.yaml` changes, then commits the result.

Star counts and dates come straight from GitHub; descriptions are written by contributors and reviewed in pull requests.

## License

[MIT](LICENSE)
