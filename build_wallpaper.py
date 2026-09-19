# -*- coding: utf-8 -*-
"""把模板 + 资源拼成自包含壁纸 HTML（场景视频 base64 内嵌）。"""
import os, base64

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "wallpaper_template.html")
VIDEO = os.path.join(HERE, "assets", "scene_loop.mp4")
POSTER = os.path.join(HERE, "assets", "scene_master.jpg")
OUT = os.path.join(HERE, "桌面伴侣-雪团-壁纸.html")


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    tpl = open(TPL, "r", encoding="utf-8").read()
    tpl = tpl.replace("__VIDEO_B64__", b64(VIDEO))
    tpl = tpl.replace("__POSTER_B64__", b64(POSTER))
    assert "__VIDEO_B64__" not in tpl and "__POSTER_B64__" not in tpl, "占位符未替换完"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(tpl)
    print("[build] 已生成 %s (%.2f MB)" % (OUT, os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
