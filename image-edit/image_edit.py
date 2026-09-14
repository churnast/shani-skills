#!/usr/bin/env python3
"""Редактор картинок для агента: убрать фон, наложить слой, посмотреть размеры.

Зачем отдельный скрипт: код картинок, написанный прямо в команду терминала
(`python3 - <<'PY'` или `python3 -c`), большинство движков агентов считают
опасным и требуют подтверждения от человека. Вызов готового скрипта
подтверждения не требует. Плюс системный python может быть без Pillow:
скрипт сам переходит на python окружения агента, если его запустили там,
где Pillow нет.

Команды:
  info ФАЙЛ [ФАЙЛ...]
      размеры, режим, есть ли прозрачность, насколько фон белый

  rembg ВХОД ВЫХОД [--method auto|rembg|white] [--threshold 18] [--band 18]
        [--feather 2] [--all-white]
      убирает фон, сохраняет PNG с прозрачностью

  compose ОСНОВА СЛОЙ ВЫХОД [--anchor bottom-center] [--x 0] [--y 0]
        [--scale 1.0 | --width N | --height N | --fit-width 0.5 | --fit-height 0.8]
        [--opacity 1.0] [--no-trim] [--bg white]
      кладёт слой поверх основы с масштабом и выравниванием

  place ОСНОВА ЧЕЛОВЕК ВЫХОД [флаги rembg и compose]
      одной командой: убрать фон у второй картинки и наложить на первую

Размеры и выравнивание:
  --scale       множитель к собственному размеру слоя (1.0 = как есть)
  --width/--height  точный размер слоя в пикселях, вторая сторона по пропорции
  --fit-width/--fit-height  доля от ширины/высоты основы (0.8 = 80% высоты)
  --anchor      top-left, top-center, top-right, center-left, center,
                center-right, bottom-left, bottom-center, bottom-right
  --x/--y       сдвиг от точки привязки в пикселях, можно отрицательный

Готовый файл кладётся туда, куда сказано, а если путь не задан, в
~/.hermes/image_edit/. Последней строкой скрипт печатает готовую строку
`MEDIA:<путь>`: её нужно перенести в ответ пользователю, тогда Telegram приложит файл
к сообщению. Без этой строки пользователь результата не увидит.

Работает без интернета: белый фон снимается пороговой маской с заливкой от
краёв и сглаживанием края. rembg (нейросеть) используется, только если он
установлен, и нужен для сложного фона, не для белого.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERMES = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
OUT_DIR = HERMES / "image_edit"
ANCHORS = (
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
)
ANCHOR_ALIASES = {
    "top": "top-center", "bottom": "bottom-center",
    "left": "center-left", "right": "center-right",
    "middle": "center", "centre": "center",
}


def die(msg: str, code: int = 1):
    """Ошибка одной строкой по-русски, без трассировки."""
    print("❌ " + msg, file=sys.stderr)
    raise SystemExit(code)


def _python_with_pillow():
    """Питон, у которого есть Pillow и numpy. Системный python3 на сервере их не имеет."""
    seen = []
    cands = [
        HERMES / "hermes-agent/venv/bin/python",
        Path.home() / ".hermes/hermes-agent/venv/bin/python",
    ]
    for cand in cands:
        cand = str(cand)
        if cand in seen or not os.path.exists(cand):
            continue
        seen.append(cand)
        try:
            probe = subprocess.run(
                [cand, "-c", "import PIL, numpy"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            )
        except Exception:
            continue
        if probe.returncode == 0:
            return cand
    return None


def _ensure_libs():
    """Pillow и numpy обязательны. Нет их в текущем питоне: перезапускаемся в питоне движка."""
    try:
        import PIL  # noqa: F401
        import numpy  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("IMAGE_EDIT_REEXEC"):
        die("нет Pillow или numpy даже в питоне движка. Поставить: "
            "pip install Pillow numpy")
    other = _python_with_pillow()
    if not other:
        die("нет Pillow или numpy ни в этом питоне, ни в питоне движка "
            "(~/.hermes/hermes-agent/venv/bin/python). Поставить: "
            "pip install Pillow numpy")
    os.environ["IMAGE_EDIT_REEXEC"] = "1"
    os.execv(other, [other, os.path.abspath(__file__)] + sys.argv[1:])


_ensure_libs()

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter, ImageOps  # noqa: E402

Image.MAX_IMAGE_PIXELS = 200_000_000


# ---------------------------------------------------------------- чтение и запись

def load(path, name="файл"):
    p = Path(os.path.expanduser(str(path)))
    if not p.exists():
        die("%s не найден: %s" % (name, p))
    try:
        im = Image.open(p)
        im.load()
    except Exception as e:
        die("%s не читается как картинка (%s): %s" % (name, type(e).__name__, p))
    fmt = im.format
    try:
        im = ImageOps.exif_transpose(im)  # снимки с телефона лежат боком без этого
    except Exception:
        pass
    im.format = fmt  # поворот теряет формат, а он нужен для info
    return p, im


def out_path(value, suffix=".png"):
    """Путь результата. Пусто: имя со временем в ~/.hermes/image_edit/."""
    if value:
        p = Path(os.path.expanduser(str(value)))
    else:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        p = OUT_DIR / ("image-%s%s" % (stamp, suffix))
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    return p


def save(im, path, bg="white", quality=95):
    """Сохранение. PNG держит прозрачность, JPEG подкладывает фон."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        flat = Image.new("RGB", im.size, bg)
        flat.paste(im.convert("RGBA"), (0, 0), im.convert("RGBA"))
        flat.save(path, "JPEG", quality=quality, subsampling=0)
    else:
        if ext not in (".png", ".webp"):
            path = path.with_suffix(".png")
        im.convert("RGBA").save(path, "PNG")
    return path


def report(path, im, what="Готово"):
    """Итог и строка доставки. Строку MEDIA агент переносит в ответ пользователю."""
    p = Path(path).resolve()
    size = p.stat().st_size
    print("%s: %s" % (what, p))
    print("Размер: %dx%d, режим %s, %.0f КБ" % (im.size[0], im.size[1], im.mode, size / 1024))
    print("Показать пользователю: перенеси следующую строку в ответ")
    print("MEDIA:%s" % p)


# ---------------------------------------------------------------- фон

def _white_distance(rgb):
    """Насколько пиксель далёк от белого: 0 у чистого белого, 255 у чёрного."""
    return 255 - rgb.min(axis=2).astype(np.int16)


def _propagate(allowed, seed, max_passes=8):
    """Заливка от краёв: разрешённые пиксели, до которых можно дойти от рамки.

    Проходы построчные и постолбцовые, каждый шаг это операция numpy над целой
    строкой или колонкой, поэтому картинка 2000x2000 обрабатывается за секунды.
    Так белое внутри фигуры (воротник, лист бумаги в руках) остаётся на месте:
    до него от рамки не дойти.
    """
    h, w = allowed.shape
    for _ in range(max_passes):
        before = int(seed.sum())
        for j in range(1, w):
            seed[:, j] |= seed[:, j - 1] & allowed[:, j]
        for j in range(w - 2, -1, -1):
            seed[:, j] |= seed[:, j + 1] & allowed[:, j]
        for i in range(1, h):
            seed[i, :] |= seed[i - 1, :] & allowed[i, :]
        for i in range(h - 2, -1, -1):
            seed[i, :] |= seed[i + 1, :] & allowed[i, :]
        if int(seed.sum()) == before:
            break
    return seed


def _odd(n):
    n = max(3, int(n))
    return n if n % 2 else n + 1


def remove_white(im, threshold=18, feather=2, connected=True, band=None):
    """Убирает белый фон пороговой маской. Возвращает RGBA и долю снятого.

    Два порога. Ближе threshold к белому: фон, прозрачность полная. От
    threshold до threshold+band: край, прозрачность частичная, чтобы контур не
    получился ступеньками. Дальше: фигура, её не трогаем.
    """
    im = im.convert("RGBA")
    arr = np.asarray(im).astype(np.uint8)
    rgb = arr[:, :, :3]
    dist = _white_distance(rgb)
    band = max(4, int(threshold) if band is None else int(band))
    outer = int(threshold) + band
    near_white = dist <= outer

    if connected:
        seed = np.zeros(near_white.shape, dtype=bool)
        seed[0, :] = near_white[0, :]
        seed[-1, :] = near_white[-1, :]
        seed[:, 0] = near_white[:, 0]
        seed[:, -1] = near_white[:, -1]
        background = _propagate(near_white, seed)
    else:
        background = near_white

    soft = np.clip((dist.astype(np.float32) - float(threshold)) / float(band), 0.0, 1.0) * 255.0
    alpha = np.where(background, soft, 255.0).astype(np.uint8)
    alpha = np.minimum(alpha, arr[:, :, 3])  # прозрачное во входе прозрачным и остаётся

    if feather > 0:
        blurred = np.asarray(
            Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(feather))
        )
        # размытие не должно возвращать непрозрачность вглубь фона
        deep = Image.fromarray(np.where(background, 255, 0).astype(np.uint8))
        deep = np.asarray(deep.filter(ImageFilter.MinFilter(_odd(2 * feather + 1))))
        alpha = np.where(deep == 255, np.minimum(blurred, alpha), blurred).astype(np.uint8)

    out = arr.copy()
    out[:, :, 3] = alpha
    share = float((alpha < 16).sum()) / float(alpha.size)
    return Image.fromarray(out), share


def remove_background(im, method="auto", threshold=18, feather=2, connected=True, band=None):
    """Основной путь rembg, если он установлен. Запасной путь пороговый по белому."""
    if method in ("auto", "rembg"):
        try:
            from rembg import remove as rembg_remove
        except ImportError:
            if method == "rembg":
                die("rembg не установлен. Белый фон снимается и без него: "
                    "--method white. Поставить rembg: "
                    "pip install rembg")
            rembg_remove = None
        if rembg_remove is not None:
            try:
                res = rembg_remove(im.convert("RGBA"))
                arr = np.asarray(res.convert("RGBA"))
                share = float((arr[:, :, 3] < 16).sum()) / float(arr[:, :, 3].size)
                return Image.fromarray(arr), share, "rembg"
            except Exception as e:
                if method == "rembg":
                    die("rembg не отработал (%s: %s). Попробуй --method white"
                        % (type(e).__name__, e))
                print("rembg не отработал (%s), иду пороговым путём по белому"
                      % type(e).__name__)
    res, share = remove_white(im, threshold=threshold, feather=feather,
                              connected=connected, band=band)
    return res, share, "белый порог"


def alpha_bbox(im):
    """Прямоугольник видимой части: без него слой «стоит» по своим пустым полям."""
    a = np.asarray(im.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(a > 16)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ---------------------------------------------------------------- команды

def cmd_info(args):
    for path in args.files:
        p, im = load(path)
        rgba = im.convert("RGBA")
        arr = np.asarray(rgba)
        alpha = arr[:, :, 3]
        transparent = float((alpha < 16).sum()) / float(alpha.size)
        dist = _white_distance(arr[:, :, :3])
        border = np.concatenate([dist[0, :], dist[-1, :], dist[:, 0], dist[:, -1]])
        white_border = float((border <= 18).sum()) / float(border.size)
        print("Файл: %s" % p.resolve())
        print("  размер: %dx%d, режим %s, формат %s, %.0f КБ"
              % (im.size[0], im.size[1], im.mode, im.format or "?", p.stat().st_size / 1024))
        print("  прозрачных пикселей: %.0f%%" % (transparent * 100))
        print("  белого по рамке: %.0f%%" % (white_border * 100))
        if white_border > 0.8 and transparent < 0.05:
            print("  фон белый и сплошной: снимется командой rembg без нейросети")
        elif transparent > 0.05:
            print("  прозрачность уже есть: фон снимать не нужно")
        else:
            print("  фон по рамке не белый: пороговый путь не сработает, нужен rembg")
    return 0


def cmd_rembg(args):
    src, im = load(args.input, "исходная картинка")
    dst = out_path(args.output, ".png")
    if dst.resolve() == src.resolve():
        die("выход совпадает со входом, исходник затирать нельзя: %s" % dst)
    res, share, how = remove_background(
        im, method=args.method, threshold=args.threshold,
        feather=args.feather, connected=not args.all_white, band=args.band,
    )
    if share < 0.01:
        print("Внимание: снято меньше 1% пикселей. Фон мог быть не белым, "
              "посмотри info и подними --threshold")
    if share > 0.97:
        print("Внимание: снято больше 97% пикселей, от картинки почти ничего "
              "не осталось. Опусти --threshold")
    box = alpha_bbox(res)
    saved = save(res, dst)
    print("Фон убран (%s), прозрачным стало %.0f%% пикселей" % (how, share * 100))
    if box:
        print("Видимая часть: %dx%d в прямоугольнике %s"
              % (box[2] - box[0], box[3] - box[1], str(box)))
    report(saved, res, "Готово")
    return 0


def _scaled_size(layer, base, args):
    lw, lh = layer.size
    bw, bh = base.size
    if args.width:
        w = int(args.width)
        return w, max(1, round(lh * w / lw))
    if args.height:
        h = int(args.height)
        return max(1, round(lw * h / lh)), h
    if args.fit_width:
        w = max(1, round(bw * float(args.fit_width)))
        return w, max(1, round(lh * w / lw))
    if args.fit_height:
        h = max(1, round(bh * float(args.fit_height)))
        return max(1, round(lw * h / lh)), h
    s = float(args.scale)
    return max(1, round(lw * s)), max(1, round(lh * s))


def _anchor_xy(anchor, base, layer, dx, dy):
    bw, bh = base.size
    lw, lh = layer.size
    vert, _, horiz = ("center-center" if anchor == "center" else anchor).partition("-")
    x = {"left": 0, "center": (bw - lw) // 2, "right": bw - lw}[horiz]
    y = {"top": 0, "center": (bh - lh) // 2, "bottom": bh - lh}[vert]
    return x + int(dx), y + int(dy)


def compose(base, layer, args):
    """Накладывает слой на основу. Возвращает картинку и прямоугольник слоя."""
    base = base.convert("RGBA")
    layer = layer.convert("RGBA")

    if not args.no_trim:
        box = alpha_bbox(layer)
        if box and box != (0, 0, layer.size[0], layer.size[1]):
            layer = layer.crop(box)
            print("Обрезала пустые поля слоя: осталось %dx%d" % layer.size)

    new_size = _scaled_size(layer, base, args)
    if new_size != layer.size:
        layer = layer.resize(new_size, Image.LANCZOS)
        print("Слой приведён к %dx%d" % new_size)

    if float(args.opacity) < 1.0:
        a = np.asarray(layer)[:, :, 3].astype(np.float32) * float(args.opacity)
        arr = np.asarray(layer).copy()
        arr[:, :, 3] = np.clip(a, 0, 255).astype(np.uint8)
        layer = Image.fromarray(arr)

    anchor = ANCHOR_ALIASES.get(args.anchor, args.anchor)
    if anchor not in ANCHORS:
        die("не знаю выравнивание «%s». Есть: %s" % (args.anchor, ", ".join(ANCHORS)))
    x, y = _anchor_xy(anchor, base, layer, args.x, args.y)

    if (x < 0 or y < 0 or x + layer.size[0] > base.size[0]
            or y + layer.size[1] > base.size[1]):
        print("Внимание: слой выходит за основу и будет обрезан. "
              "Уменьши его (--fit-height) или сдвинь (--x, --y)")

    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out.alpha_composite(base)
    out.alpha_composite(layer, (x, y))
    return out, (x, y, x + layer.size[0], y + layer.size[1])


def cmd_compose(args):
    bpath, base = load(args.base, "основа")
    lpath, layer = load(args.layer, "слой")
    dst = out_path(args.output, ".png")
    for src in (bpath, lpath):
        if dst.resolve() == src.resolve():
            die("выход совпадает со входом, исходник затирать нельзя: %s" % dst)
    res, box = compose(base, layer, args)
    saved = save(res, dst, bg=args.bg)
    print("Основа %dx%d, слой встал в прямоугольник %s (выравнивание %s)"
          % (base.size[0], base.size[1], str(box), args.anchor))
    report(saved, res, "Готово")
    return 0


def cmd_place(args):
    bpath, base = load(args.base, "основа")
    lpath, person = load(args.layer, "картинка человека")
    dst = out_path(args.output, ".png")
    for src in (bpath, lpath):
        if dst.resolve() == src.resolve():
            die("выход совпадает со входом, исходник затирать нельзя: %s" % dst)
    cut, share, how = remove_background(
        person, method=args.method, threshold=args.threshold,
        feather=args.feather, connected=not args.all_white, band=args.band,
    )
    print("Фон убран (%s), прозрачным стало %.0f%% пикселей" % (how, share * 100))
    if share < 0.01:
        print("Внимание: снято меньше 1% пикселей, фон мог быть не белым")
    res, box = compose(base, cut, args)
    saved = save(res, dst, bg=args.bg)
    print("Основа %dx%d, человек встал в прямоугольник %s (выравнивание %s)"
          % (base.size[0], base.size[1], str(box), args.anchor))
    report(saved, res, "Готово")
    return 0


# ---------------------------------------------------------------- разбор аргументов

def add_cut_flags(p):
    p.add_argument("--method", choices=("auto", "rembg", "white"), default="auto",
                   help="auto: rembg, если установлен, иначе белый порог")
    p.add_argument("--threshold", type=int, default=18,
                   help="насколько далеко от белого считать фоном (0..255, по умолчанию 18)")
    p.add_argument("--band", type=int, default=None,
                   help="ширина полосы полупрозрачного края за порогом (по умолчанию как порог)")
    p.add_argument("--feather", type=int, default=2,
                   help="сглаживание края в пикселях (0 выключает)")
    p.add_argument("--all-white", action="store_true",
                   help="снимать весь белый, включая белое внутри фигуры")


def add_place_flags(p):
    p.add_argument("--anchor", default="bottom-center",
                   help="выравнивание: " + ", ".join(ANCHORS))
    p.add_argument("--x", type=int, default=0, help="сдвиг вправо от точки привязки")
    p.add_argument("--y", type=int, default=0, help="сдвиг вниз от точки привязки")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--scale", type=float, default=1.0, help="множитель размера слоя")
    g.add_argument("--width", type=int, help="ширина слоя в пикселях")
    g.add_argument("--height", type=int, help="высота слоя в пикселях")
    g.add_argument("--fit-width", type=float, help="доля от ширины основы, например 0.5")
    g.add_argument("--fit-height", type=float, help="доля от высоты основы, например 0.8")
    p.add_argument("--opacity", type=float, default=1.0, help="прозрачность слоя 0..1")
    p.add_argument("--no-trim", action="store_true",
                   help="не обрезать пустые поля слоя перед наложением")
    p.add_argument("--bg", default="white", help="цвет подложки при сохранении в JPEG")


def build_parser():
    p = argparse.ArgumentParser(
        prog="image_edit.py",
        description="Картинки для агента: убрать фон, наложить слой, посмотреть размеры.",
    )
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("info", help="размеры, прозрачность, белый ли фон")
    pi.add_argument("files", nargs="+")
    pi.set_defaults(func=cmd_info)

    pr = sub.add_parser("rembg", help="убрать фон, сохранить PNG с прозрачностью")
    pr.add_argument("input")
    pr.add_argument("output", nargs="?")
    add_cut_flags(pr)
    pr.set_defaults(func=cmd_rembg)

    pc = sub.add_parser("compose", help="наложить слой поверх основы")
    pc.add_argument("base")
    pc.add_argument("layer")
    pc.add_argument("output", nargs="?")
    add_place_flags(pc)
    pc.set_defaults(func=cmd_compose)

    pp = sub.add_parser("place", help="убрать фон у слоя и наложить его на основу")
    pp.add_argument("base")
    pp.add_argument("layer")
    pp.add_argument("output", nargs="?")
    add_cut_flags(pp)
    add_place_flags(pp)
    pp.set_defaults(func=cmd_place)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
