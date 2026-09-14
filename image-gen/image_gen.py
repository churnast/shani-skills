#!/usr/bin/env python3
"""Рисование и правка картинок через провайдера картинок движка Hermes Agent.

    python3 image_gen.py check
    python3 image_gen.py draw "рыжий кот в соломенной шляпе"
    python3 image_gen.py draw "обложка поста" --size landscape --quality high
    python3 image_gen.py draw "три варианта логотипа" --count 3
    python3 image_gen.py edit ~/photo.jpg "убери шляпу, фон сделай белым"
    python3 image_gen.py edit ~/photo.jpg "в этом же стиле" --ref ~/second.png

Скрипт работает через плагины image_gen движка Hermes Agent, поэтому
запускается там, где движок установлен (HERMES_HOME, по умолчанию ~/.hermes).
Кто рисует, задаёт image_gen.provider в ~/.hermes/config.yaml; питон движка
(venv) подхватывается сам. Отдельно ничего ставить не нужно, если провайдер
уже авторизован в движке (например, openai-codex через `hermes auth codex`).

Ступени качества low / medium / high это имена моделей провайдера openai-codex
(gpt-image-2-low / -medium / -high), они уходят в переменную OPENAI_IMAGE_MODEL.

Чего этот путь не умеет: маски (вырезать область и перерисовать только её).
Что поменять на картинке, описывается словами, файл-исходник уходит целиком.

Готовый файл лежит в ~/.hermes/images/<дата>/ (папку меняет IMAGE_GEN_DIR или
--out). Скрипт печатает путь к файлу. Чтобы файл ушёл вложением в чат, в ответ
агента добавляется строка MEDIA:<путь>: гейтвей превращает её во вложение.

Переменные окружения: HERMES_HOME (папка движка), IMAGE_GEN_DIR (папка для
картинок), IMAGE_GEN_PYTHON (питон движка, по умолчанию
HERMES_HOME/hermes-agent/venv/bin/python).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
IMAGES_DIR = Path(os.environ.get("IMAGE_GEN_DIR") or (HERMES_HOME / "images"))
AGENT_DIR = HERMES_HOME / "hermes-agent"
VENV_PY = Path(os.environ.get("IMAGE_GEN_PYTHON") or (AGENT_DIR / "venv" / "bin" / "python"))

SIZES = ("square", "landscape", "portrait")
# Ступени качества плагина openai-codex. Имя ступени уходит в переменную
# OPENAI_IMAGE_MODEL: это штатная точка входа плагина для скриптов.
QUALITY = {"low": "gpt-image-2-low", "medium": "gpt-image-2-medium", "high": "gpt-image-2-high"}
MAX_COUNT = 4
# Форматы, которые принимает картинка-исходник (ограничение провайдера).
SOURCE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


class Fail(Exception):
    """Понятная человеку причина, по которой картинки не будет."""


def now() -> datetime.datetime:
    fixed = os.environ.get("IMAGE_GEN_NOW")
    if fixed:
        return datetime.datetime.fromisoformat(fixed)
    return datetime.datetime.now()


def slug(text: str, limit: int = 40) -> str:
    """Короткое латинское имя файла из описания картинки."""
    out = []
    for ch in (text or "").strip().lower():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum()):
            out.append(ch)
        elif ch in " _-.,":
            out.append("_")
    name = "".join(out)
    while "__" in name:
        name = name.replace("__", "_")
    name = name.strip("_")[:limit].strip("_")
    return name or "kartinka"


def plan_paths(prompt: str, count: int, out_dir: Path, name: str = "") -> list:
    """Куда лягут файлы. Ничего не создаёт: папку делаем только под готовые байты."""
    stamp = now()
    base = slug(name or prompt)
    day = out_dir / stamp.strftime("%Y-%m-%d")
    paths = []
    for i in range(count):
        tail = "" if i == 0 else "_%d" % (i + 1)
        paths.append(day / ("%s_%s%s.png" % (base, stamp.strftime("%H%M%S"), tail)))
    return paths


def free_path(path: Path) -> Path:
    """Тот же путь, а если файл уже есть, то с номером: не затираем чужую картинку."""
    if not path.exists():
        return path
    for n in range(2, 100):
        candidate = path.with_name("%s_%d%s" % (path.stem, n, path.suffix))
        if not candidate.exists():
            return candidate
    raise Fail("В папке %s уже сотня файлов с таким именем, назови картинку иначе (--name)." % path.parent)


def reexec_into_engine_python() -> None:
    """Перезапуститься питоном движка: только там стоят httpx и сам Hermes."""
    if os.environ.get("IMAGE_GEN_INNER") == "1":
        return
    if not (VENV_PY.is_file() and os.access(str(VENV_PY), os.X_OK)):
        return
    try:
        if Path(sys.executable).resolve() == VENV_PY.resolve():
            return
    except OSError:
        pass
    env = dict(os.environ, IMAGE_GEN_INNER="1")
    os.execve(str(VENV_PY), [str(VENV_PY), os.path.abspath(__file__)] + sys.argv[1:], env)


def load_registry():
    """Поднять плагины движка и вернуть его реестр провайдеров картинок."""
    if not AGENT_DIR.is_dir():
        raise Fail(
            "Движок Hermes не найден: нет папки %s. Скрипт работает только там, где установлен "
            "Hermes Agent (HERMES_HOME/hermes-agent)." % AGENT_DIR
        )
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    try:
        from hermes_cli.plugins import discover_plugins
        from agent import image_gen_registry
    except Exception as exc:
        raise Fail(
            "Не получилось поднять движок Hermes из %s (%s: %s). Обычно это значит, что скрипт "
            "запущен не тем питоном: нужен %s." % (AGENT_DIR, type(exc).__name__, exc, VENV_PY)
        )
    try:
        discover_plugins()
    except Exception as exc:
        raise Fail("Плагины движка не загрузились (%s: %s). Без них рисовать нечем." % (type(exc).__name__, exc))
    return image_gen_registry


def pick_provider(need_source_image: bool = False):
    """Активный провайдер картинок. Нет живого: говорим, чего не хватает."""
    registry = load_registry()
    provider = None
    try:
        provider = registry.get_active_provider()
    except Exception:
        provider = None
    if provider is None:
        known = []
        try:
            known = [p.name for p in registry.list_providers()]
        except Exception:
            known = []
        raise Fail(
            "Ни один провайдер картинок не готов рисовать. Зарегистрированы: %s. Обычно причин две: "
            "в ~/.hermes/config.yaml не выбран image_gen.provider, либо протух вход в Codex "
            "(лечится командой hermes auth codex)." % (", ".join(known) or "ни одного")
        )
    if not provider.is_available():
        raise Fail(
            "Провайдер %s выбран, но не готов: нет живого доступа. Для openai-codex это протухший вход "
            "в подписку, лечится командой hermes auth codex." % provider.name
        )
    if need_source_image:
        modalities = []
        try:
            modalities = list(provider.capabilities().get("modalities") or [])
        except Exception:
            modalities = []
        if "image" not in modalities:
            raise Fail(
                "Провайдер %s умеет рисовать с нуля, но не принимает картинку-исходник. Правка по "
                "присланному файлу через него не работает." % provider.name
            )
    return provider


def check_source(path: Path) -> Path:
    resolved = Path(os.path.expanduser(str(path))).resolve()
    if not resolved.is_file():
        raise Fail("Картинки-исходника нет: %s. Проверь путь к файлу." % resolved)
    if resolved.stat().st_size == 0:
        raise Fail("Файл-исходник пустой: %s." % resolved)
    if resolved.suffix.lower() not in SOURCE_SUFFIXES:
        raise Fail(
            "Формат %s провайдер не примет. Подходят png, jpg, gif, webp." % (resolved.suffix or "без расширения")
        )
    if resolved.stat().st_size > 25 * 1024 * 1024:
        raise Fail("Файл больше 25 МБ (%s), провайдер такой не берёт." % resolved.name)
    return resolved


def describe_error(result: dict) -> str:
    """Ответ провайдера превратить в причину по-русски."""
    kind = str(result.get("error_type") or "")
    raw = str(result.get("error") or "провайдер не объяснил причину")
    hints = {
        "auth_required": "Вход в подписку Codex не живой. Нужна команда hermes auth codex.",
        "missing_dependency": "В окружении движка не хватает пакета для запроса.",
        "invalid_argument": "Описание картинки пустое.",
        "invalid_image_input": "Картинка-исходник не подошла.",
        "empty_response": "Провайдер не вернул картинку. Стоит повторить запрос.",
        "incomplete_image": "Провайдер прислал только незаконченный кадр и отдавать его отказался. Стоит повторить запрос.",
        "api_error": "Провайдер ответил ошибкой.",
    }
    head = hints.get(kind, "Провайдер картинку не отдал.")
    return "%s Ответ провайдера: %s" % (head, raw)


def one_image(provider, prompt: str, size: str, source=None, refs=None) -> Path:
    kwargs = {"aspect_ratio": size}
    if source is not None:
        kwargs["image_url"] = str(source)
    if refs:
        kwargs["reference_image_urls"] = [str(r) for r in refs]
    try:
        result = provider.generate(prompt, **kwargs)
    except Exception as exc:
        raise Fail("Запрос к провайдеру %s сорвался (%s: %s)." % (provider.name, type(exc).__name__, exc))
    if not isinstance(result, dict) or not result.get("success"):
        raise Fail(describe_error(result if isinstance(result, dict) else {}))
    made = result.get("image")
    if not made or not Path(str(made)).is_file():
        raise Fail("Провайдер отчитался об успехе, но файла по пути %s нет." % made)
    return Path(str(made))


def deliver(made: Path, target: Path) -> Path:
    """Переложить готовый файл в свою папку. Папку создаём только сейчас."""
    target = free_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(made), str(target))
    except OSError:
        shutil.copy2(str(made), str(target))
    return target


def run_images(a, source=None, refs=None) -> int:
    count = max(1, min(int(a.count), MAX_COUNT))
    out_dir = Path(os.path.expanduser(a.out)) if a.out else IMAGES_DIR
    paths = plan_paths(a.prompt, count, out_dir, getattr(a, "name", "") or "")

    if a.dry_run:
        if a.json:
            print(json.dumps({"dry_run": True, "paths": [str(p) for p in paths]}, ensure_ascii=False))
        else:
            for p in paths:
                print(p)
        return 0

    os.environ["OPENAI_IMAGE_MODEL"] = QUALITY[a.quality]
    provider = pick_provider(need_source_image=source is not None)

    done, errors = [], []
    for path in paths:
        try:
            made = one_image(provider, a.prompt, a.size, source=source, refs=refs)
        except Fail as exc:
            errors.append(str(exc))
            break
        done.append(deliver(made, path))

    if a.json:
        print(json.dumps({
            "ok": bool(done), "provider": provider.name, "quality": a.quality, "size": a.size,
            "paths": [str(p) for p in done], "errors": errors,
        }, ensure_ascii=False))
    else:
        for p in done:
            print(p)
        for e in errors:
            print(e, file=sys.stderr)
    if not done:
        return 1
    if errors:
        print("Сделано %d из %d." % (len(done), count), file=sys.stderr)
    return 0


def cmd_check(a) -> int:
    registry = load_registry()
    rows = []
    for p in registry.list_providers():
        try:
            live = bool(p.is_available())
        except Exception:
            live = False
        rows.append({"name": p.name, "display": p.display_name, "available": live})
    active = None
    try:
        got = registry.get_active_provider()
        active = got.name if got else None
    except Exception:
        active = None
    if a.json:
        print(json.dumps({"active": active, "providers": rows}, ensure_ascii=False))
        return 0 if active else 1
    for r in rows:
        print("%s (%s): %s" % (r["name"], r["display"], "готов" if r["available"] else "нет доступа"))
    if active:
        print("Рисует: %s. Папка с картинками: %s" % (active, IMAGES_DIR))
        return 0
    print("Рисовать нечем: в config.yaml не выбран image_gen.provider или нет живого доступа.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="image_gen.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--size", choices=SIZES, default="square",
                       help="square (квадрат), landscape (лежачая), portrait (стоячая). По умолчанию square")
        p.add_argument("--count", type=int, default=1,
                       help="сколько вариантов, до %d. Каждый вариант это отдельный запрос" % MAX_COUNT)
        p.add_argument("--quality", choices=sorted(QUALITY), default="medium",
                       help="low быстрее, high дольше и точнее. По умолчанию medium")
        p.add_argument("--out", default="", help="папка для файлов, по умолчанию %s" % IMAGES_DIR)
        p.add_argument("--name", default="", help="своё имя файла вместо куска описания")
        p.add_argument("--json", action="store_true", help="ответ машинным JSON")
        p.add_argument("--dry-run", action="store_true",
                       help="только показать, куда лягут файлы, ничего не рисовать и не создавать")

    d = sub.add_parser("draw", help="нарисовать картинку по описанию")
    d.add_argument("prompt", help="что нарисовать, словами")
    common(d)

    e = sub.add_parser("edit", help="переделать присланную картинку по описанию")
    e.add_argument("source", help="файл-исходник (png, jpg, gif, webp)")
    e.add_argument("prompt", help="что поменять, словами")
    e.add_argument("--ref", action="append", default=[], metavar="ФАЙЛ",
                   help="ещё картинки для примера стиля, можно несколько раз")
    e.add_argument("--mask", default="",
                   help="не поддерживается текущим провайдером, оставлено ради понятной ошибки")
    common(e)

    c = sub.add_parser("check", help="какой провайдер рисует и жив ли доступ")
    c.add_argument("--json", action="store_true", help="ответ машинным JSON")
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    try:
        if a.cmd == "check":
            reexec_into_engine_python()
            return cmd_check(a)
        if a.cmd == "draw":
            if not (a.prompt or "").strip():
                raise Fail("Пустое описание: скажи словами, что нарисовать.")
            if not a.dry_run:
                reexec_into_engine_python()
            return run_images(a)
        if a.cmd == "edit":
            if a.mask:
                raise Fail(
                    "Маску текущий провайдер не принимает: он не умеет перерисовывать только выделенную "
                    "область. Опиши правку словами, файл уйдёт целиком."
                )
            if not (a.prompt or "").strip():
                raise Fail("Пустое описание правки: скажи словами, что поменять на картинке.")
            source = check_source(Path(a.source))
            refs = [check_source(Path(r)) for r in a.ref]
            if not a.dry_run:
                reexec_into_engine_python()
            return run_images(a, source=source, refs=refs)
    except Fail as exc:
        print("❌ %s" % exc, file=sys.stderr)
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
