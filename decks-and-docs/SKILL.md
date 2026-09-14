---
name: decks-and-docs
description: "ALWAYS use when the user asks for a presentation, slides, a deck, a document, a report or a brief as a file, «send it as pdf», «I need a docx», «I need a pptx», «put it in a file», and generally whenever the result is a file the user will show or send to someone. Build the file with make_deck.py and make_doc.py and send the file itself to the chat, not a story about how it was built."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags:
      - presentation
      - slides
      - document
      - pptx
      - docx
      - pdf
    related_skills:
      - powerpoint
      - docx
      - pdf
---

# Decks and documents

The user asks for a presentation or a document when a file is needed: to show
someone, attach to a letter, print, put on a drive. So the answer is a file in
the chat, not the text "here is a structure of six slides".

Two scripts build the file, both live in the agent's scripts folder:

- `python3 <scripts dir>/make_deck.py <spec.json>`: presentation .pptx
- `python3 <scripts dir>/make_doc.py <spec.json> [--pdf]`: document .docx and
  a PDF next to it

Both print the path of the finished file and nothing else.

## When to build a file

- The user said "presentation", "slides", "deck", "I will show it at a meeting".
- The user asks for a document, report, instruction, brief, offer as one file.
- The user asks "in pdf", "in docx", "as a file", "so I can send it".
- A finished analysis or plan the user will carry outside: offer a file in one
  line, but build only after the user's "yes".

When not: an answer to a question, a short list, anything the user will read
right in the chat. A file for the sake of a file is an extra step.

## What to ask before building

No more than two or three questions, each with your own suggested answer so the
user has something to confirm:

1. For whom and why (colleagues, partner, client, self): this decides length
   and tone.
2. How many slides or sections and what must be inside.
3. Are there pictures or numbers to insert and where they are.

If the user says "do it yourself", propose a structure in one message (slide
titles as a list) and build after "yes". Inventing content silently is not
allowed: numbers, names, prices and facts come from what the user sent or are
asked for. An empty spot is better than an invented one.

## The spec

One JSON, the same for the deck and the document. Write it to a temporary file
(for example `/tmp/deck.json`) and pass it to the script; `-` reads stdin.

```json
{
  "title": "Title",
  "subtitle": "subtitle, optional",
  "footer": "footer line on slides, defaults to the title",
  "theme": "sand",
  "slides": [
    {"title": "Section name"},
    {"title": "Heading", "bullets": ["point", "another point"]},
    {"title": "Heading", "text": "paragraph\n\nsecond paragraph", "notes": "speaker note"},
    {"title": "Heading", "bullets": ["point"], "image": "/path/picture.png"}
  ]
}
```

- Slide fields: `title`, `subtitle`, `text`, `bullets`, `image`, `notes`. Any
  can be omitted.
- A slide with only `title` becomes a section divider.
- In the document `slides` is read as sections; the field may be called
  `sections`. `notes` does not go into the document, it is speaker notes.
- Themes: `sand` (warm light, default), `night` (dark), `mint` (light green).
  No custom colours, one font (Arial) for all themes. `--theme` overrides the
  spec.
- A picture must exist as a file first (sent by the user, on disk, produced by
  another tool); `image` takes the path to it. A missing picture does not
  break the build: the slide is built without it and a warning goes to stderr.

The finished file goes by default to `~/.hermes/cache/documents/` (under
`HERMES_HOME`). This is one of the folders the gateway is allowed to send
attachments from, so a file from there goes to the chat without extra steps.
Your own name: `--out /path/name.pptx`. `--json` prints a machine-readable
answer.

## Sending the file

The file goes to the chat with the `MEDIA:` mark in your own reply; the mark
text itself is not shown. Use the exact path the script printed:

```
Done, here is the deck MEDIA:/path/to/.hermes/cache/documents/plan.pptx
```

From a script or the terminal `hermes send` does the same:

```
hermes send --to telegram "MEDIA:/path/to/.hermes/cache/documents/plan.pptx"
```

The `[[as_document]]` mark before `MEDIA:` forces sending as a file instead of
a compressed picture: needed for images; .pptx and .docx go as files anyway.

## Exit rules

1. Promised a presentation: the reply contains the file. A retold structure
   instead of a file is an unfulfilled request.
2. Short reply: one line "what was built" plus the file itself. How the JSON
   is arranged, which scripts ran and how long it took is not needed.
3. Something did not build (no picture, missing data): send the file anyway
   and write in one line what is missing and why.
4. Edits after the user's remarks: rebuild the whole file and send a new one,
   do not explain what should be changed.

## If the script complains

- "Нет библиотеки python-pptx" or "python-docx": packages are missing. Run
  `pip install python-pptx python-docx` (and `pip install reportlab` for PDF)
  once and retry.
- "Описание слайдов не разобралось как JSON": your JSON is broken, fix the
  spec, not the script.
- "PDF не собран: в системе нет шрифта с кириллицей": the .docx is ready
  anyway, send it and say the PDF did not come out. The PDF needs a system
  font with Cyrillic: DejaVu or Liberation on Linux, Verdana or Arial Unicode
  on macOS.
- Do not patch `make_deck.py` and `make_doc.py` on the fly. A new feature is a
  change in the script's source, not a workaround in the chat.

## Neighbouring skills

The engine's built-in skills `powerpoint`, `docx`, `xlsx`, `pdf` can do more:
read someone's .pptx, fix an existing file, build an .xlsx table, split and
merge PDFs. Take them when working with an existing file. When a new file has
to be built for the user, take this skill: one look and one way out.

## Setup

Dependencies: `python-pptx` (deck), `python-docx` (document), `reportlab` plus
a system font with Cyrillic (PDF, optional). Install with
`pip install python-pptx python-docx reportlab`. Put `make_deck.py` and
`make_doc.py` into the agent's scripts folder, `SKILL.md` into the skills
folder. The output folder follows `HERMES_HOME` (default `~/.hermes`).

## Кратко по-русски

Один JSON (`title`, `subtitle`, `theme`, `slides` или `sections` с полями
`title`, `subtitle`, `text`, `bullets`, `image`, `notes`). `make_deck.py
spec.json` собирает .pptx, `make_doc.py spec.json --pdf` собирает .docx и PDF.
Темы `sand`, `night`, `mint`. Файл ложится в `~/.hermes/cache/documents/`, в
чат уходит строкой `MEDIA:<путь>`. Зависимости: python-pptx, python-docx,
reportlab.
