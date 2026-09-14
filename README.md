# Shani skills

Clean, shareable skills for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
Each folder is one skill: `SKILL.md` (instructions the agent reads) plus the script it calls.
No personal data, no server paths, no keys: drop a folder into your agent's skills directory and go.

| Skill | What it does | Needs |
|-------|--------------|-------|
| `image-edit` | Edit pictures: remove background, cut out a person, overlay, straighten, move, resize | Pillow, numpy; rembg optional |
| `image-gen` | Generate pictures (covers, logos, illustrations, avatars) via an image model | the image provider configured in Hermes Agent (`hermes auth codex` or an OpenAI key) |
| `decks-and-docs` | Build .pptx decks and .docx / .pdf documents from plain text | python-pptx, python-docx, reportlab |

## Install

```bash
git clone https://github.com/churnast/shani-skills.git
cp -R shani-skills/<skill> ~/.hermes/skills/<skill>
```

Then read the skill's `SKILL.md` for the script call and its dependencies.

## Who

Maintained for Shani, a personal Hermes agent. Requests for a clean version of another skill: open an issue.
