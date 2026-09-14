---
name: image-gen
description: "Use when the user asks for a picture: draw, generate an image, make a cover, a logo, an illustration, an avatar, show how something would look, or when the user sends a photo and asks to change it (remove the background, redo it in another style, fix this picture). Draws through the image provider configured in Hermes Agent; the result is a file sent to the user as an attachment, not a description."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags:
      - image
      - drawing
      - creative
---

# Image generation

The agent draws by itself: the picture is produced by the image provider
configured in Hermes Agent (`image_gen.provider` in `~/.hermes/config.yaml`),
takes 20-40 seconds and goes to the user as a file in the chat. No link to an
outside service, no "ask a neural network".

Every picture spends provider quota, so do not draw in batches of ten: one
variant, show it, continue on the user's word.

## When to draw

- The user asks directly: draw, generate, make a picture, a cover, a logo, an
  avatar, an illustration.
- The user sends a photo and asks to change it: remove the background, another
  style, another colour.
- The user asks for a cover for a post and says so.

When not to draw: the user is telling a story or asking for advice and did not
ask for a picture. Do not offer pictures on your own initiative. Diagrams,
charts, tables and anything that must be exact are not drawn: the model draws
something similar, not something correct.

## Tool

`python3 <scripts dir>/image_gen.py <command>`. Full help in the script header.

- `check`: which provider draws and whether access is alive. No network call.
- `draw "<prompt>"`: draw from scratch. Prints the path of the file.
  - `--size square | landscape | portrait`: square (default), wide, tall.
  - `--count N`: up to 4 variants, each one is a separate request and separate
    quota. Default one.
  - `--quality low | medium | high`: low is faster, high is slower and more
    exact, default medium.
  - `--name <name>`: your own file name instead of a piece of the prompt.
  - `--out <dir>`: output folder, default `~/.hermes/images/<date>/`.
  - `--json`: machine-readable answer. `--dry-run`: only show target paths.
- `edit <file> "<what to change>"`: rework a picture the user sent. The source
  file is sent whole; style examples can be added with `--ref <file>`.
  Accepted sources: png, jpg, gif, webp, up to 25 MB.

Write the prompt in English when in doubt: the model understands other
languages, but holds details better in English. Reply to the user in the
user's language.

## What to ask before drawing

One question, not an interrogation, and only when the result would miss
without the answer:

- What the picture is for (post cover, avatar, just to see): this decides the
  shape (tall, wide, square).
- What must be in the picture when the request is one word ("draw a cat" is
  not a task yet: which cat, where, in what mood).
- Whether there is text in the picture and what exactly, verbatim.

The user answered briefly and is in a hurry: do not ask twice, draw by your
own understanding and show it. Edits are cheaper than questions.

## How the result reaches the user

The result is a file, not a description. Describing the picture in words is
pointless: the user will not see it.

The file goes as an attachment with the line `MEDIA:<full path>` in your reply:
the gateway turns it into an attachment. Use the path the script printed. Next
to it one short line in your own words, without retelling what is visible.

To send as a separate message (for example several variants one by one):
`hermes send --to telegram "MEDIA:<path> caption"`, one call per picture.

## Edits

The user says "not that", "redo", "another style": this is `edit` on the file
already drawn, not a new `draw` from scratch. The composition is kept and the
user sees exactly the edit. A completely new picture only when the user says
the idea itself is wrong.

Masks (select an area and redraw only it) are not supported. An edit is
described in words: "remove the hat", "make the background white". The user
asks to change only a fragment: say in one line that cutting out an area is
not possible and offer to describe the edit in words. Do not invent a
workaround.

## When it fails

The script returned an error: name the concrete reason to the user in one line
and do not present the task as done. No picture means no picture.

- Provider access is not alive: say that drawing is down together with the
  access. For the openai-codex provider the fix is `hermes auth codex` on the
  machine where the agent runs.
- The provider returned no picture or an incomplete frame: one retry, and if
  it is empty again, say so directly.
- The source file did not fit (format, size over 25 MB): say that png, jpg,
  gif or webp is needed and ask to send it again.

Never: describe a picture that does not exist, substitute someone else's
picture from the internet, say "drawing it now" and not come back. Drew and
sent in the same reply, or honestly said why not.

## Setup

Requirements: Hermes Agent installed (`HERMES_HOME`, default `~/.hermes`, with
`hermes-agent/venv`), an image provider chosen in `image_gen.provider` of
`config.yaml` and authorized. No extra packages: the script re-executes itself
with the engine python. Put `image_gen.py` into the agent's scripts folder,
`SKILL.md` into the skills folder.

Environment variables: `HERMES_HOME` (engine home), `IMAGE_GEN_DIR` (output
folder), `IMAGE_GEN_PYTHON` (engine python).

## Кратко по-русски

Скрипт `image_gen.py`: `check` (кто рисует), `draw "<описание>"` (нарисовать),
`edit <файл> "<что поменять>"` (переделать присланное). Флаги `--size`,
`--count`, `--quality`, `--name`, `--out`. Результат это файл: строка
`MEDIA:<путь>` в ответе. Маски не поддерживаются, правка описывается словами.
Нужен установленный Hermes Agent с настроенным провайдером картинок.
